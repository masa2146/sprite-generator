"""Turn an analysis of a screenshot into crops and paste-ready prompts.

Generation happens by hand in Gemini or ChatGPT, so nothing here calls an API
or writes a generated image. The deliverable is a folder you upload from and a
prompt you paste — which makes a retry free, and makes prompt quality the thing
that carries the result.

The prompt is a structured block rather than a paragraph because every block
answers a failure measured on the paid path: an unlabelled pair of reference
images, a missing "exactly one" that produced twelve balls, HUD labels that kept
their text, and a frame whose crop showed everything it framed.
"""

from __future__ import annotations

import json
from pathlib import Path

import extract
import vision


class BriefError(Exception):
    """The analysis could not be turned into a brief."""


def normalise_views(views) -> list[str]:
    """Pool members only, in pool order, never empty.

    Closed pool so file names stay predictable and the same analysis twice
    yields the same set. A name outside it is dropped rather than passed
    through, because an unknown view would silently get the `front` phrase.
    """
    wanted = {v for v in views if isinstance(v, str)} if isinstance(views, list) else set()
    return [v for v in vision.VIEW_POOL if v in wanted] or [vision.DEFAULT_VIEW]


def load_analysis(path) -> tuple[str, list[dict]]:
    """Read and validate analysis.json. Returns (style, objects).

    Every error names the offending field, and the object's id where there is
    one: this file is meant to be hand-edited between runs, so an error that
    only says "invalid" costs the user a hunt.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BriefError(f"cannot read {path.name}: {exc}") from exc

    if not isinstance(raw, dict):
        raise BriefError("analysis must be a JSON object")

    style = raw.get("style")
    if not isinstance(style, str) or not style.strip():
        raise BriefError("'style' is required and must be a non-empty string")

    objects = raw.get("objects")
    if not isinstance(objects, list) or not objects:
        raise BriefError("'objects' is required and must be a non-empty list")

    out: list[dict] = []
    for index, obj in enumerate(objects):
        if not isinstance(obj, dict):
            raise BriefError(f"objects[{index}]: must be a JSON object")
        obj_id = obj.get("id")
        if not isinstance(obj_id, str) or not obj_id.strip():
            raise BriefError(f"objects[{index}]: 'id' is required")
        bbox = obj.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            raise BriefError(
                f"objects[{index}] ({obj_id}): 'bbox' must be [x1, y1, x2, y2]"
            )
        entry = dict(obj)
        entry["views"] = normalise_views(obj.get("views"))
        # labelled_sheet captions each crop with this flag. Multiple views is
        # the only motion signal this schema carries, so it is what the caption
        # reports — a caption that misdescribes its crop is what this whole
        # review step exists to catch.
        entry["animated"] = len(entry["views"]) > 1
        out.append(entry)
    return style.strip(), out


_REFERENCES = """REFERENCES
- Image 1 — the object to redraw. Reproduce THIS object.
- Image 2 — the game screenshot. Use it ONLY for art style, palette and
  lighting. Do not copy any object from it."""

_OUTPUT_TAIL = """- Centred and complete, nothing touching or cut off at the edges.
- Small even margin on all sides. Square image.
- Flat solid #808080 background. No shadow, no ground plane, no gradient,
  no scene, no props."""

# Background is a flat grey rather than transparent because the downloaded file
# is cut locally with post.py, and that was measured clean on #808080 while
# #FF00FF bled colour into the alpha edges. Asking a model for a transparent
# PNG varies by model and cannot be relied on.

_FIXED_BANS = """- any text, numbers, labels or logos
- any other object from the screenshot
- more than one copy of the object"""

_FIELDS = ("subject", "form", "detail", "state")
_LABELS = {"subject": "OBJECT", "form": "FORM", "detail": "DETAIL", "state": "STATE"}


def _field_block(obj: dict, view: str) -> str:
    lines = []
    for field in _FIELDS:
        value = obj.get(field)
        if isinstance(value, str) and value.strip():
            lines.append(f"{_LABELS[field]:<10} {value.strip()}")
    phrase = vision.VIEW_POOL.get(view, vision.VIEW_POOL[vision.DEFAULT_VIEW])
    lines.append(f"{'VIEW':<10} {phrase}")
    return "\n".join(lines)


def _do_not_draw(contents) -> str:
    lines = ["DO NOT DRAW"]
    if contents:
        # Naming, capping and pluralisation come from extract so the two
        # callers cannot drift apart.
        lines.append("- the " + ", ".join(extract.exclusion_names(contents))
                     + " visible inside it in the reference image")
    lines.append(_FIXED_BANS)
    return "\n".join(lines)


def asset_prompt(obj: dict, view: str, style: str, contents=None) -> str:
    """One paste-ready prompt for this object in this view.

    Structured blocks rather than a paragraph: on the paid path the constraints
    were buried in a run-on sentence and the ones that mattered were the ones
    the model skipped.
    """
    short = obj["id"].replace("_", " ")
    output = (
        "OUTPUT\n"
        f"- Exactly one {short}, on its own. Not a set, not a grid, not a sheet.\n"
        f"{_OUTPUT_TAIL}"
    )
    return "\n\n".join([
        _REFERENCES,
        _field_block(obj, view),
        f"ART STYLE  {style.strip()}",
        output,
        _do_not_draw(contents),
    ])
