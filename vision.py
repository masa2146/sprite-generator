"""Analyse a reference image into a fixed style schema.

The schema is fixed rather than free-form so every pack's style prefix carries
the same axes in the same order — a model asked for prose writes "a nice icon";
a model asked for six named fields has to answer each one.

style and subject stay separate: style applies to every asset in the pack,
subject describes only the analysed image. Folding subject into the prefix
would make every asset drift toward that one object.
"""

from __future__ import annotations

import base64
import json
import re

import orclient

STYLE_FIELDS = ("render", "camera", "lighting", "palette", "linework", "realism")
# Join order for prompt text, deliberately different from STYLE_FIELDS: palette
# reads best last, after the visual description it tints.
_JOIN_ORDER = ("render", "camera", "lighting", "linework", "realism", "palette")

ANALYSIS_PROMPT = """Analyse this image and describe it as JSON, with exactly this shape:

{
  "style": {
    "render":   "render technique and material, e.g. soft 3D render, glossy plastic material",
    "camera":   "camera angle and framing, e.g. 3/4 front view, slight high angle, centered",
    "lighting": "light direction, softness, shadows, e.g. top-left key light, soft ambient occlusion",
    "palette":  "dominant colours as hex codes, e.g. #FF6B4A #4ECDC4 #FFE66D",
    "linework": "outlines and geometry, e.g. no outline, rounded geometry, soft bevels",
    "realism":  "stylisation axis, e.g. stylized cartoon, not photorealistic"
  },
  "subject": "what the image actually depicts, as a generation prompt would phrase it"
}

Rules:
- "style" describes HOW the image looks and must not name the subject.
- "subject" describes WHAT it depicts, phrased as an image-generation prompt.
- Every field must be filled in. Reply with JSON only, no commentary."""

_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


class AnalysisError(Exception):
    """The image could not be analysed into the schema."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


def extract_schema(text: str) -> dict:
    """Pull the JSON object out of a model reply.

    Models wrap JSON in fences, prefix it with prose, or both — so try the
    fenced form, then the first balanced-looking object, before giving up.
    """
    match = _FENCED.search(text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise AnalysisError("no JSON object found in the reply", raw=text)


def validate_schema(schema: dict) -> list[str]:
    """Return the dotted paths of missing or blank fields; empty means valid."""
    missing: list[str] = []
    style = schema.get("style")
    if not isinstance(style, dict):
        missing.extend(f"style.{f}" for f in STYLE_FIELDS)
    else:
        for field in STYLE_FIELDS:
            value = style.get(field)
            if not isinstance(value, str) or not value.strip():
                missing.append(f"style.{field}")
    subject = schema.get("subject")
    if not isinstance(subject, str) or not subject.strip():
        missing.append("subject")
    return missing


def style_prefix(schema: dict) -> str:
    """The pack's [style] prefix: style fields only, never the subject.

    ponytail: nothing here structurally stops a model from writing the
    subject into a style field anyway (e.g. "render": "soft 3D render of a
    gold coin") — the prompt forbids it and the field split enforces the
    *shape*, not the *content*. Detecting that is out of scope for this pass;
    upgrade path would be a subject-vs-style overlap check (e.g. flag a style
    field that shares n-grams with `subject`) if drift like that shows up.
    """
    style = schema.get("style", {})
    return ", ".join(style[f].strip() for f in _JOIN_ORDER if style.get(f))


def reproduction_prompt(schema: dict) -> str:
    """A ready prompt for regenerating this image: subject first, then style."""
    return f"{schema['subject'].strip()}, {style_prefix(schema)}"


def analyze(pack, image_bytes: bytes, retries: int = 3, sleeper=None) -> tuple[dict, str]:
    """Send the image to the vision endpoint. Returns (schema, raw_reply_text)."""
    if not pack.vision_model:
        # Deliberately only two suggestions: load_pack never consults [pack]
        # model for vision, so telling the user to set it would "fix" analyze
        # by pointing build at a vision model that can't generate images.
        raise AnalysisError(
            "no vision model: set [vision] model, or pass --vision-model"
        )

    mime = orclient._sniff_mime(image_bytes)
    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "model": pack.vision_model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": ANALYSIS_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]}],
    }
    headers = {"Content-Type": "application/json"}
    key = pack.vision_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    url = pack.vision_base_url.rstrip("/") + "/chat/completions"
    kwargs = {"retries": retries}
    if sleeper is not None:
        kwargs["sleeper"] = sleeper
    body = orclient.post_with_retry(url, payload, headers, **kwargs)

    message = ((body.get("choices") or [{}])[0] or {}).get("message") or {}
    content = message.get("content")
    text = content if isinstance(content, str) else json.dumps(content)

    schema = extract_schema(text)          # raises AnalysisError carrying raw text
    missing = validate_schema(schema)
    if missing:
        raise AnalysisError(
            f"analysis is missing {len(missing)} field(s): {', '.join(missing)}",
            raw=text,
        )
    return schema, text
