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

from . import orclient

STYLE_FIELDS = ("render", "camera", "lighting", "palette", "linework", "realism")
# Join order for prompt text, deliberately different from STYLE_FIELDS: palette
# reads best last, after the visual description it tints.
_JOIN_ORDER = ("render", "camera", "lighting", "linework", "realism", "palette")

# Subject-side fields: what the object IS and how it is built. These never
# enter a pack's [style] prefix — that prefix is applied to every asset, and
# one object's geometry in it would drag the whole set toward that shape.
SUBJECT_FIELDS = ("subject", "form", "detail")

# Full single-object prompt order: identity, then geometry, then surface
# detail, then style, with palette last.
PROMPT_ORDER = (
    "subject", "form", "detail",
    "render", "camera", "lighting", "linework", "realism", "palette",
)

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
  "form": "the object's construction: how many parts, their arrangement and proportions, e.g. two stacked parts, a ribbed panel above a rounded box with a vertical slot",
  "detail": "distinguishing smaller features: rim thickness, bevels, surface finish, markings",
  "subject": "what the object IS, phrased as an image-generation prompt would name it"
}

Rules:
- "style" describes HOW it looks and must not name the subject.
- "form" describes the object's structure precisely enough to rebuild it from words alone.
- "subject" names WHAT it is, briefly.
- Every field must be filled in. Reply with JSON only, no commentary."""

USER_OVERRIDE_CLAUSE = """

The user also asked for: {text}

Where the user's request conflicts with what you see, follow the user. Fill every
field the user did not speak to from the image as normal."""

_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
# A comma right before a closing brace/bracket: invalid JSON, common model slip.
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


class AnalysisError(Exception):
    """The image could not be analysed into the schema."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


def _loads(candidate: str) -> dict | None:
    """Parse JSON, retrying once with trailing commas stripped.

    A trailing comma before } or ] is invalid JSON but a very common model
    slip — observed live from a Claude model that otherwise returned a
    perfectly-formed schema. Rejecting the whole analysis over one comma
    would throw away a reply the user already paid for.
    """
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(_TRAILING_COMMA.sub(r"\1", candidate))
    except json.JSONDecodeError:
        return None


def extract_schema(text: str) -> dict:
    """Pull the JSON object out of a model reply.

    Models wrap JSON in fences, prefix it with prose, or both — so try the
    fenced form, then the first balanced-looking object, before giving up.
    """
    match = _FENCED.search(text)
    if match:
        parsed = _loads(match.group(1))
        if parsed is not None:
            return parsed

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        parsed = _loads(text[start : end + 1])
        if parsed is not None:
            return parsed

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
    for field in ("form", "detail", "subject"):
        value = schema.get(field)
        if not isinstance(value, str) or not value.strip():
            missing.append(field)
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
    # isinstance, not truthiness: analyze_objects does not run validate_schema,
    # so a model answering "palette" with a list of hex codes reaches here. That
    # must degrade to a shorter prefix, not crash a command that has already
    # paid for the vision call and written crops to disk.
    return ", ".join(
        style[f].strip() for f in _JOIN_ORDER
        if isinstance(style.get(f), str) and style[f].strip()
    )


def reproduction_prompt(schema: dict) -> str:
    """A ready prompt for regenerating this image: subject first, then style."""
    return f"{schema['subject'].strip()}, {style_prefix(schema)}"


def subject_prompt(schema: dict) -> str:
    """One object's identity and construction, without any style fields.

    For a pack asset: the pack's [style] prefix supplies style at build time,
    so an asset prompt carrying style would double it. But subject alone is
    too narrow to rebuild an object from — form and detail are what this
    schema grew to carry.
    """
    parts = [schema.get(f) for f in SUBJECT_FIELDS]
    return ", ".join(p.strip() for p in parts if isinstance(p, str) and p.strip())


def object_prompt(schema: dict) -> str:
    """The full single-object prompt: identity, geometry, detail, then style.

    Unlike style_prefix this deliberately includes subject/form/detail — it
    describes one object rather than a style shared across a set.
    """
    style = schema.get("style") or {}
    parts = []
    for field in PROMPT_ORDER:
        value = schema.get(field) if field in SUBJECT_FIELDS else style.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return ", ".join(parts)


# Closed set of view variations. Closed rather than free-form so file names stay
# predictable and the same command twice yields the same set.
VIEW_POOL = {
    "front": "seen from directly the front",
    "three_quarter": "seen from a three-quarter front angle",
    "side": "seen from directly the side, full profile",
    "back": "seen from directly behind",
    "top_down": "seen from directly above, top-down",
}
DEFAULT_VIEW = "front"

# Labelled lines, one field per line, because a model skips a clause buried in a
# sentence but answers a field it can see. "state" only exists on hand-written
# analyses (brief.py); it is simply absent from a vision reply and dropped here.
FIELD_LABELS = (
    ("subject", "OBJECT"), ("form", "FORM"), ("detail", "DETAIL"), ("state", "STATE"),
)


def field_block(obj: dict, view: str) -> str:
    """One object's fields as labelled lines, ending with its VIEW line.

    Shared by the paid path (extract, into the pack) and the manual path
    (brief, into the HTML) so the two produce the same prompt body.
    """
    lines = [
        f"{label:<10} {obj[key].strip()}"
        for key, label in FIELD_LABELS
        if isinstance(obj.get(key), str) and obj[key].strip()
    ]
    phrase = VIEW_POOL.get(view, VIEW_POOL[DEFAULT_VIEW])
    lines.append("{:<10} {}".format("VIEW", phrase))
    return "\n".join(lines)

OBJECT_ANALYSIS_PROMPT = """List every distinct sprite in this image and describe each one as JSON:

{
  "style": {
    "render":   "render technique and material shared by the whole image",
    "camera":   "camera angle and framing",
    "lighting": "light direction, softness, shadows",
    "palette":  "dominant colours as hex codes",
    "linework": "outlines and geometry",
    "realism":  "stylisation axis"
  },
  "objects": [
    {
      "id": "short_snake_case_name",
      "bbox": [x1, y1, x2, y2],
      "animated": true,
      "views": ["front", "side"],
      "subject": "what this object IS, briefly",
      "form": "its construction: how many parts, arrangement, proportions",
      "detail": "distinguishing smaller features"
    }
  ]
}

Rules:
- "style" describes the whole image once; it must not name any object.
- One entry per distinct sprite SHAPE, not per copy on screen. If several
  objects are the same shape in different colours, or the same shape repeated
  in the same pose, return ONE entry and name the colour variants in "detail".
  Return separate entries only when the silhouette, construction or pose
  genuinely differs. When a shape repeats, "bbox" must enclose ONE
  representative copy — the clearest, least occluded one — never all the
  copies together.
- A box must contain its own object and nothing else that is on this list. If a
  large structure frames the playfield, box the smallest repeating piece of it
  (one straight run, one corner) rather than the whole frame: that piece is
  what the game tiles.
- Include the playfield's built parts, not only the obvious characters: tracks,
  rails, conveyors, launchers, dispensers, slots, containers, platforms. These
  get missed because they are large, low-contrast against the background, or
  partly covered by other objects. Look for them deliberately.
- List gameplay objects first and interface elements (score labels, coin
  counters, settings buttons) last.
- Do not list the background or the whole screen.
- "bbox" is in pixels, top-left origin, [left, top, right, bottom]. It must
  contain the object's FULL extent — every ear, spike, handle and overhang —
  plus a few pixels of margin. A box that clips the object is a failure; a box
  with some extra background around it is fine.
- "animated" is true for anything that moves, rotates, is launched or is
  carried during play. A fixed wall, rail or backdrop panel is not animated.
- "views" may only contain: front, three_quarter, side, back, top_down.
  For an animated object list at least three views the game would actually
  need. For anything not animated list exactly one.
- Reply with JSON only, no commentary."""

OBJECT_USER_CLAUSE = """

The user, who knows this game, describes the image as: {text}

Treat that description as ground truth about what exists and where. Every object
the user names must appear in "objects" at the position they describe, even if
you would otherwise have missed it, merged it into a neighbour, or read it as
part of the background. Keep finding the objects the user did not mention too —
their description adds to your list, it does not replace it.

Where the description conflicts with the rules above, follow the description.
The rules are defaults for when nobody has told you what the game needs; the
user has. If they ask for a whole framing structure as one sprite, box it whole
rather than splitting it into its repeating piece. If they ask for a variant
that is covered up in the image — an empty slot, a label with no text — give it
its own entry, box the clearest example of that part, and say in "subject" and
"detail" what must be left out when it is drawn."""


def normalise_views(views, animated: bool) -> list[str]:
    """Reduce a model's view list to known names, in pool order.

    A static object gets exactly one view: generating four angles of a rail
    segment spends money for nothing.
    """
    if not animated or not isinstance(views, list):
        return [DEFAULT_VIEW]
    wanted = {v for v in views if isinstance(v, str) and v in VIEW_POOL}
    ordered = [v for v in VIEW_POOL if v in wanted]
    return ordered or [DEFAULT_VIEW]


def analyze_objects(pack, image_bytes: bytes, user_text: str | None = None,
                    retries: int = 3, sleeper=None) -> tuple[dict, str]:
    """Ask the vision model for every sprite in the image.

    Returns ({"style": {...}, "objects": [...]}, raw_reply_text). Views are
    normalised here so callers never see a name outside the pool.

    user_text, when given, is the user's own description of the scene. It is
    appended as ground truth rather than merged programmatically: deciding
    whether "the dispenser below the white blocks" is a new object or one the
    model already found is the model's job, not a string comparison's.
    """
    if not pack.vision_model:
        raise AnalysisError(
            "no vision model: set [vision] model, pass --vision-model, "
            "or set SPRITEGEN_VISION_MODEL"
        )

    instruction = OBJECT_ANALYSIS_PROMPT
    if user_text and user_text.strip():
        instruction += OBJECT_USER_CLAUSE.format(text=user_text.strip())

    mime = orclient._sniff_mime(image_bytes)
    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "model": pack.vision_model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": instruction},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]}],
        "stream": False,
        "temperature": 0,
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

    schema = extract_schema(text)
    style = schema.get("style")
    if not isinstance(style, dict) or not style:
        raise AnalysisError("reply has no style block", raw=text)
    objects = schema.get("objects")
    if not isinstance(objects, list) or not objects:
        raise AnalysisError("reply lists no objects", raw=text)

    for obj in objects:
        if isinstance(obj, dict):
            obj["views"] = normalise_views(obj.get("views"), bool(obj.get("animated")))
    return schema, text


def analyze(pack, image_bytes: bytes, user_text: str | None = None,
            retries: int = 3, sleeper=None) -> tuple[dict, str]:
    """Send the image to the vision endpoint. Returns (schema, raw_reply_text)."""
    if not pack.vision_model:
        # Deliberately only two suggestions: load_pack never consults [pack]
        # model for vision, so telling the user to set it would "fix" analyze
        # by pointing build at a vision model that can't generate images.
        raise AnalysisError(
            "no vision model: set [vision] model, pass --vision-model, or set "
            "SPRITEGEN_VISION_MODEL"
        )

    instruction = ANALYSIS_PROMPT
    if user_text and user_text.strip():
        instruction += USER_OVERRIDE_CLAUSE.format(text=user_text.strip())

    mime = orclient._sniff_mime(image_bytes)
    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "model": pack.vision_model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": instruction},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]}],
        # Sent explicitly because omitting it is not the same as false on every
        # proxy: a local omniroute/litellm returns an SSE stream by default,
        # which post_with_retry then reports as "200 response was not JSON".
        "stream": False,
        "temperature": 0,
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
