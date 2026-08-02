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
import binascii
import json
import re
import time

import requests

_DATA_URI = re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,([A-Za-z0-9+/=]+)")
_TIMEOUT = 180


def _b64(s) -> bytes | None:
    """Decode a base64 payload, or return None instead of raising.

    A malformed/truncated payload (bad padding) or a non-string payload (a
    provider that sends b64_json as something other than a string) must not
    kill the caller with a bare binascii.Error/TypeError — the caller falls
    through to the next parsing strategy and ultimately to ImageMissing, so
    the raw response still gets written to disk for inspection.
    """
    try:
        return base64.b64decode(s) if isinstance(s, str) else None
    except binascii.Error:
        return None


def chat_prompt_with_ratio(prompt: str, aspect_ratio: str | None) -> str:
    """The chat transport has no structured field for aspect ratio, so it gets
    appended to the prompt text. Shared with cli.py's --dry-run so the dry-run
    output matches what generate() actually sends."""
    return f"{prompt}, aspect ratio {aspect_ratio}" if aspect_ratio else prompt


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


def image_part(data: bytes) -> dict:
    """One image as an OpenAI-shaped data-URI part."""
    b64 = base64.b64encode(data).decode()
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{_sniff_mime(data)};base64,{b64}"},
    }


def reference_part(data: bytes, role: str) -> dict:
    """One entry of input_references: an image plus the job it does.

    `role` is not in OpenRouter's schema, but the local backend routes on it and
    treats an unroled reference as a style hint — which it then never uses,
    because a text-to-image graph has no style-conditioning input and
    transforming a style hint just returns a copy of it. Sending no role at all
    is therefore the one option that is certainly wrong.
    """
    return {**image_part(data), "role": role}


def build_payload(
    model: str,
    prompt: str,
    structure_png: bytes | None = None,
    seed: int | None = None,
    style_png: bytes | None = None,
) -> dict:
    # chat has no per-image role field, so the only thing that can tie an image
    # to its job is text sitting next to it. With one image there is nothing to
    # tie — that shape is left exactly as it was.
    present = [(img, label) for img, label in
               ((structure_png, "image1"), (style_png, "image2")) if img]
    if len(present) < 2:
        content: list[dict] = [{"type": "text", "text": prompt}]
        content += [image_part(img) for img, _ in present]
    else:
        content = []
        for img, label in present:
            content.append({"type": "text", "text": f"{label}:"})
            content.append(image_part(img))
        content.append({"type": "text", "text": prompt})
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
    structure_png: bytes | None = None,
    seed: int | None = None,
    style_png: bytes | None = None,
) -> dict:
    """Payload for POST {base_url}/images. Optional fields are omitted
    entirely (not sent as null) when absent — that's what the contract asks for."""
    body: dict = {"model": model, "prompt": prompt, "n": 1}
    if aspect_ratio is not None:
        body["aspect_ratio"] = aspect_ratio
    if seed is not None:
        body["seed"] = seed
    # Same order as build_payload, but the meaning now travels in `role`, not
    # in the position: object first, style second.
    refs = [reference_part(img, role)
            for img, role in ((structure_png, "structure"), (style_png, "style"))
            if img]
    if refs:
        body["input_references"] = refs
    return body


def build_headers(pack) -> dict:
    headers = {"Content-Type": "application/json"}
    key = pack.api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def parse_image(resp: dict) -> bytes:
    """Dig the image out of a response. Providers vary, so this is deliberately
    loose. A decode failure (truncated/invalid base64) at either site below
    must not propagate — it falls through to the next strategy, same as
    "no image found here", so a bad response still ends in ImageMissing
    rather than a bare binascii.Error."""
    message = ((resp.get("choices") or [{}])[0] or {}).get("message") or {}

    # Preferred shape: OpenRouter's message.images[]
    for item in message.get("images") or []:
        url = ((item or {}).get("image_url") or {}).get("url", "")
        if url.startswith("data:image"):
            decoded = _b64(url.split(",", 1)[1])
            if decoded is not None:
                return decoded

    # Fallback: any data URI anywhere in the message, whether the content is a
    # plain string or a structured list.
    match = _DATA_URI.search(json.dumps(message))
    if match:
        decoded = _b64(match.group(1))
        if decoded is not None:
            return decoded

    raise ImageMissing(resp)


def parse_image_images(resp: dict) -> bytes:
    """Dig the image out of a POST /images response. Prefers data[0].b64_json;
    falls back to the same tolerant data-URI regex used for chat. Must not
    raise TypeError/IndexError/KeyError on degenerate shapes (data: [],
    data: [null], missing data key, data not a list) and must not propagate a
    base64 decode failure (truncated b64_json, non-string b64_json) — either
    case falls through to the regex fallback and then to ImageMissing."""
    data = resp.get("data")
    first = data[0] if isinstance(data, list) and data else None
    if isinstance(first, dict):
        decoded = _b64(first.get("b64_json"))
        if decoded is not None:
            return decoded

    match = _DATA_URI.search(json.dumps(resp))
    if match:
        decoded = _b64(match.group(1))
        if decoded is not None:
            return decoded

    raise ImageMissing(resp)


def response_cost(resp: dict) -> float | None:
    """Cost is an OpenRouter extension; local endpoints usually omit it."""
    cost = (resp.get("usage") or {}).get("cost")
    return float(cost) if isinstance(cost, (int, float)) else None


def post_with_retry(
    url: str,
    payload: dict,
    headers: dict,
    retries: int = 3,
    sleeper=time.sleep,
) -> dict:
    """POST and return the parsed 200 body, retrying transient failures.

    429, 5xx and network-level errors retry with 2s then 4s backoff and no
    sleep after the final attempt. Other 4xx (bad prompt, unknown model, bad
    key) raise immediately — retrying them is pointless. Shared by image
    generation and vision analysis so there is only one retry policy.
    """
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
            try:
                return resp.json()
            except ValueError:
                # A 200 with a non-JSON body (an HTML error page from a proxy
                # missing /v1, an unconfigured litellm route, a captive
                # portal) is easy to reach and must not surface as a bare
                # requests.exceptions.JSONDecodeError — that's not an ApiError
                # and cmd_analyze has no catch-all for it.
                raise ApiError(f"200 response was not JSON: {resp.text[:200]}", 200)

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = ApiError(f"HTTP {resp.status_code}", resp.status_code)
            if attempt < retries - 1:
                sleeper(2 ** (attempt + 1))
            continue

        raise ApiError(f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

    raise last_error if last_error is not None else ApiError(
        f"post_with_retry called with retries={retries}: no attempt was made"
    )


def generate(
    pack,
    prompt: str,
    aspect_ratio: str | None = None,
    structure_png: bytes | None = None,
    style_png: bytes | None = None,
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
            structure_png=structure_png, seed=seed, style_png=style_png,
        )
        parse = parse_image_images
    else:
        url = pack.base_url.rstrip("/") + "/chat/completions"
        payload = build_payload(
            pack.model, chat_prompt_with_ratio(prompt, aspect_ratio),
            structure_png=structure_png, seed=seed, style_png=style_png,
        )
        parse = parse_image

    body = post_with_retry(url, payload, headers, retries=retries, sleeper=sleeper)
    return parse(body), response_cost(body), body
