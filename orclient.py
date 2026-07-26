"""Chat-completions transport for image generation.

Targets any OpenAI-schema endpoint that supports modalities: ["image", "text"].
This is the only OpenAI surface that carries a reference image without multipart,
which is why it is used instead of /images/generations or /images/edits.
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


def build_payload(
    model: str,
    prompt: str,
    reference_png: bytes | None = None,
    seed: int | None = None,
) -> dict:
    content: list[dict] = [{"type": "text", "text": prompt}]
    if reference_png:
        b64 = base64.b64encode(reference_png).decode()
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
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


def response_cost(resp: dict) -> float | None:
    """Cost is an OpenRouter extension; local endpoints usually omit it."""
    cost = (resp.get("usage") or {}).get("cost")
    return float(cost) if isinstance(cost, (int, float)) else None


def generate(
    pack,
    prompt: str,
    reference_png: bytes | None = None,
    seed: int | None = None,
    retries: int = 3,
    sleeper=time.sleep,
) -> tuple[bytes, float | None, dict]:
    """Generate one image. Returns (png_bytes, cost_or_none, raw_response)."""
    url = pack.base_url.rstrip("/") + "/chat/completions"
    headers = build_headers(pack)
    payload = build_payload(pack.model, prompt, reference_png, seed)

    last_error: ApiError | None = None
    for attempt in range(retries):
        resp = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
        if resp.status_code == 200:
            body = resp.json()
            return parse_image(body), response_cost(body), body

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = ApiError(f"HTTP {resp.status_code}", resp.status_code)
            if attempt < retries - 1:
                sleeper(2 ** (attempt + 1))
            continue

        # Other 4xx: bad prompt, unknown model, bad key. Retrying is pointless.
        raise ApiError(f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

    raise last_error
