"""HTTP transports for image generation: OpenRouter's /images endpoint and
OpenAI-schema /chat/completions with modalities: ["image", "text"].

/images is OpenRouter-specific and reaches far more image models there —
aspect_ratio, seed and input_references (up to 14 reference images) are all
first-class JSON fields. /chat/completions is kept because local OpenAI-
compatible proxies speak it and carry a reference image without multipart,
which is why it was the only transport originally. pack.transport selects
between them; both share retry policy, headers and cost parsing.
"""

from __future__ import annotations

import base64
import json
import re
import time

import requests

_DATA_URI = re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,([A-Za-z0-9+/=]+)")
_TIMEOUT = 180


class ApiError(Exception):
    """The endpoint returned a non-200 status."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ImageMissing(Exception):
    """The call succeeded but no image could be found in the response."""

    def __init__(self, raw: dict):
        super().__init__("no image in response")
        self.raw = raw


def _sniff_mime(data: bytes) -> str:
    """Guess the image MIME type from magic bytes so the declared type matches
    what was actually returned. A provider may hand back JPEG or WebP even
    though we always ask for PNG; declaring it as image/png regardless can get
    the whole request rejected by a provider that validates the MIME type."""
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"GIF8"):
        return "image/gif"
    return "image/png"  # unknown: fall back to the previous default


def build_payload(
    model: str,
    prompt: str,
    reference_png: bytes | None = None,
    seed: int | None = None,
) -> dict:
    content: list[dict] = [{"type": "text", "text": prompt}]
    if reference_png:
        b64 = base64.b64encode(reference_png).decode()
        mime = _sniff_mime(reference_png)
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
        )
    body = {
        "model": model,
        "modalities": ["image", "text"],
        "messages": [{"role": "user", "content": content}],
        "usage": {"include": True},
    }
    if seed is not None:
        # Not every provider honours this; the ones that do give us reproducibility.
        body["seed"] = seed
    return body


def build_payload_images(
    model: str,
    prompt: str,
    aspect_ratio: str | None = None,
    reference_png: bytes | None = None,
    seed: int | None = None,
) -> dict:
    """Payload for POST {base_url}/images. Optional fields are omitted
    entirely (not sent as null) when absent — that's what the contract asks for."""
    body: dict = {"model": model, "prompt": prompt, "n": 1}
    if aspect_ratio is not None:
        body["aspect_ratio"] = aspect_ratio
    if seed is not None:
        body["seed"] = seed
    if reference_png:
        b64 = base64.b64encode(reference_png).decode()
        mime = _sniff_mime(reference_png)
        body["input_references"] = [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
        ]
    return body


def build_headers(pack) -> dict:
    headers = {"Content-Type": "application/json"}
    key = pack.api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def parse_image(resp: dict) -> bytes:
    """Dig the image out of a response. Providers vary, so this is deliberately loose."""
    message = ((resp.get("choices") or [{}])[0] or {}).get("message") or {}

    # Preferred shape: OpenRouter's message.images[]
    for item in message.get("images") or []:
        url = ((item or {}).get("image_url") or {}).get("url", "")
        if url.startswith("data:image"):
            return base64.b64decode(url.split(",", 1)[1])

    # Fallback: any data URI anywhere in the message, whether the content is a
    # plain string or a structured list.
    match = _DATA_URI.search(json.dumps(message))
    if match:
        return base64.b64decode(match.group(1))

    raise ImageMissing(resp)


def parse_image_images(resp: dict) -> bytes:
    """Dig the image out of a POST /images response. Prefers data[0].b64_json;
    falls back to the same tolerant data-URI regex used for chat. Must not
    raise TypeError/IndexError on degenerate shapes (data: [], data: [null],
    missing data key)."""
    data = resp.get("data") or []
    first = data[0] if data else None
    if isinstance(first, dict):
        b64 = first.get("b64_json")
        if b64:
            return base64.b64decode(b64)

    match = _DATA_URI.search(json.dumps(resp))
    if match:
        return base64.b64decode(match.group(1))

    raise ImageMissing(resp)


def response_cost(resp: dict) -> float | None:
    """Cost is an OpenRouter extension; local endpoints usually omit it."""
    cost = (resp.get("usage") or {}).get("cost")
    return float(cost) if isinstance(cost, (int, float)) else None


def generate(
    pack,
    prompt: str,
    aspect_ratio: str | None = None,
    reference_png: bytes | None = None,
    seed: int | None = None,
    retries: int = 3,
    sleeper=time.sleep,
) -> tuple[bytes, float | None, dict]:
    """Generate one image. Returns (png_bytes, cost_or_none, raw_response).

    Dispatches on pack.transport:
      "images" -> POST {base_url}/images, aspect_ratio as a structured field.
      "chat"   -> POST {base_url}/chat/completions, aspect_ratio appended to
                  the prompt text (only when given) since the endpoint has no
                  structured field for it.
    """
    headers = build_headers(pack)
    if pack.transport == "images":
        url = pack.base_url.rstrip("/") + "/images"
        payload = build_payload_images(
            pack.model, prompt, aspect_ratio=aspect_ratio,
            reference_png=reference_png, seed=seed,
        )
        parse = parse_image_images
    else:
        url = pack.base_url.rstrip("/") + "/chat/completions"
        chat_prompt = f"{prompt}, aspect ratio {aspect_ratio}" if aspect_ratio else prompt
        payload = build_payload(pack.model, chat_prompt, reference_png, seed)
        parse = parse_image

    last_error: ApiError | None = None
    for attempt in range(retries):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
        except requests.exceptions.RequestException as exc:
            # Timeout, connection reset, DNS failure, ... With a 180s timeout on
            # image generation, a timeout is the single most likely transient
            # failure — treat it like a 5xx and retry with the same backoff.
            last_error = ApiError(f"{type(exc).__name__}: {exc}")
            if attempt < retries - 1:
                sleeper(2 ** (attempt + 1))
            continue

        if resp.status_code == 200:
            body = resp.json()
            return parse(body), response_cost(body), body

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = ApiError(f"HTTP {resp.status_code}", resp.status_code)
            if attempt < retries - 1:
                sleeper(2 ** (attempt + 1))
            continue

        # Other 4xx: bad prompt, unknown model, bad key. Retrying is pointless.
        raise ApiError(f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

    raise last_error if last_error is not None else ApiError(
        f"generate() called with retries={retries}: no attempt was made"
    )
