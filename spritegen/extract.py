"""Turn one image's object list into crops and a buildable pack.

extract generates no images. It validates the boxes a vision model returned,
crops them, renders a sheet you can check them against, and writes a pack —
the existing `build` command does the generating. Keeping those apart is what
makes the cost a separate, explicit decision.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from PIL import Image, ImageDraw

from . import packwriter
from . import vision

MIN_EDGE = 16              # smaller than this cannot be a usable sprite
MAX_AREA_RATIO = 0.9       # a box this big means the model returned the whole screen
DEFAULT_MAX_OBJECTS = 12
# Vision models undershoot boxes: the first live run clipped the ears off every
# rabbit. The crop is a reference for the generator, not the deliverable, so a
# margin of background costs nothing while a clipped silhouette teaches the
# generator the wrong shape.
BOX_PAD = 0.12             # grow each accepted box by this fraction of its size

_LABEL_H = 22              # strip under each cell for its caption
_PAD = 8
_CELL = 220                # longest edge of a crop as drawn on the sheet

# The model's id becomes a filename (refs_dir / f"{id}.png") and, in cli.py, an
# asset id used the same way — untrusted, so it must not contain "/" or "..".
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def reject_reason(bbox, img_w: int, img_h: int) -> str | None:
    """Why this box is unusable, or None if it is fine.

    Every rejection is surfaced to the user rather than dropped: a silently
    missing object makes an incomplete pack look complete.
    """
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return "malformed box (expected [x1, y1, x2, y2])"
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in bbox):
        return "malformed box (non-numeric coordinate)"

    x1, y1, x2, y2 = (int(v) for v in bbox)
    if x2 <= x1 or y2 <= y1:
        return "empty box (zero or inverted area)"
    if x1 < 0 or y1 < 0 or x2 > img_w or y2 > img_h:
        return f"outside the image ({img_w}x{img_h})"
    if (x2 - x1) < MIN_EDGE or (y2 - y1) < MIN_EDGE:
        return f"too small (min edge {MIN_EDGE}px)"
    if ((x2 - x1) * (y2 - y1)) > (img_w * img_h * MAX_AREA_RATIO):
        return "covers the whole image"
    return None


def screen_objects(objects, img_w: int, img_h: int) -> tuple[list[dict], list]:
    """Decide which objects are usable. Returns (accepted, rejected).

    Every check that does not need the image itself lives here so `--dry-run`
    previews exactly the set the real run keeps. Screening in two places let
    the preview and the run disagree, and the preview is what the user reads
    before paying `build`.
    """
    accepted: list[dict] = []
    rejected: list[tuple[str, str]] = []
    seen: set[str] = set()

    for index, obj in enumerate(objects):
        if not isinstance(obj, dict):
            rejected.append((f"object[{index}]", "not an object"))
            continue
        obj_id = obj.get("id")
        if not isinstance(obj_id, str) or not obj_id.strip():
            rejected.append((f"object[{index}]", "missing id"))
            continue
        if not _ID_RE.fullmatch(obj_id):
            rejected.append((obj_id, "unusable id"))
            continue
        # Case-folded: "Block" and "block" are two asset ids but one filename on
        # a case-insensitive filesystem, so the second crop would overwrite the
        # first and the contact sheet would show it twice under two labels.
        if obj_id.lower() in seen:
            rejected.append((obj_id, "duplicate id"))
            continue
        seen.add(obj_id.lower())

        reason = reject_reason(obj.get("bbox"), img_w, img_h)
        if reason:
            rejected.append((obj_id, reason))
            continue
        accepted.append(obj)

    return accepted, rejected


def padded_box(bbox, img_w: int, img_h: int) -> tuple[int, int, int, int]:
    """A validated box grown by BOX_PAD on every side, clamped to the image."""
    x1, y1, x2, y2 = (int(v) for v in bbox)
    dx = round((x2 - x1) * BOX_PAD)
    dy = round((y2 - y1) * BOX_PAD)
    return (max(0, x1 - dx), max(0, y1 - dy),
            min(img_w, x2 + dx), min(img_h, y2 + dy))


def crop_objects(image: Image.Image, objects, refs_dir) -> tuple[list[dict], list]:
    """Crop each usable object to refs_dir. Returns (kept, rejected).

    Each kept object gains a "crop" key holding its Path. Each rejected entry
    is (object_id, reason). A crop that cannot be written rejects that object
    rather than aborting — the other objects are still worth having.
    """
    refs_dir = Path(refs_dir)
    refs_dir.mkdir(parents=True, exist_ok=True)
    accepted, rejected = screen_objects(objects, image.width, image.height)
    kept: list[dict] = []

    for obj in accepted:
        obj_id = obj["id"]
        x1, y1, x2, y2 = padded_box(obj["bbox"], image.width, image.height)
        target = refs_dir / f"{obj_id}.png"
        try:
            image.crop((x1, y1, x2, y2)).save(target)
        except OSError as exc:
            rejected.append((obj_id, f"could not write crop: {exc}"))
            continue

        entry = dict(obj)
        entry["crop"] = target
        kept.append(entry)

    return kept, rejected


def labelled_sheet(entries, out_path) -> Path:
    """Grid of crops, each captioned with its number, id, state and views.

    The caption is the point: a wrong crop is only obvious when you can see
    which object it claims to be.
    """
    out_path = Path(out_path)
    if not entries:
        raise ValueError("labelled_sheet: nothing to draw")

    images = [Image.open(e["crop"]).convert("RGB") for e in entries]
    try:
        # Thumbnail first: cells size to the largest crop, and one full-playfield
        # box (the live run produced a 704x1004 one) otherwise blows the sheet up
        # to thousands of pixels of mostly empty space.
        for im in images:
            im.thumbnail((_CELL, _CELL))
        cell_w = max(im.width for im in images) + _PAD * 2
        cell_h = max(im.height for im in images) + _PAD * 2 + _LABEL_H
        cols = min(4, len(images))
        rows = (len(images) + cols - 1) // cols

        sheet = Image.new("RGB", (cell_w * cols, cell_h * rows), (24, 24, 32))
        draw = ImageDraw.Draw(sheet)
        for i, (im, entry) in enumerate(zip(images, entries)):
            cx, cy = (i % cols) * cell_w, (i // cols) * cell_h
            sheet.paste(im, (cx + (cell_w - im.width) // 2, cy + _PAD))
            state = "ANIMATED" if entry.get("animated") else "static"
            caption = f"{i} · {entry['id']} · {state} · {','.join(entry.get('views') or [])}"
            draw.text((cx + _PAD, cy + cell_h - _LABEL_H + 4), caption[:60],
                      fill=(230, 230, 235))
        sheet.save(out_path)
    finally:
        for im in images:
            im.close()
    return out_path


# A box counts as swallowed when this much of its area sits inside another box.
# Not 1.0: model boxes overlap their neighbours by a pixel or two routinely.
CONTAINED_RATIO = 0.9
# Beyond this many, the prompt clause stops being a description and becomes a
# list. The count is still reported in full.
MAX_NAMED_CONTENTS = 4


def _area(box) -> int:
    x1, y1, x2, y2 = box
    return max(0, x2 - x1) * max(0, y2 - y1)


def find_contents(objects) -> dict:
    """Map each object's id to the ids its box swallows.

    A framing object — a conveyor loop, a tray, a panel — has a box that by
    definition contains whatever it frames, so its crop shows the contents too.
    Left alone, that crop tells the image model "draw this frame AND everything
    inside it", which is the failure that made the first live run unusable.
    Nothing here guesses: every box is already known, so containment is
    arithmetic, not judgement.
    """
    contents: dict[str, list[str]] = {}
    for outer in objects:
        inside = []
        ox1, oy1, ox2, oy2 = (int(v) for v in outer["bbox"])
        outer_area = _area((ox1, oy1, ox2, oy2))
        for inner in objects:
            if inner is outer:
                continue
            ix1, iy1, ix2, iy2 = (int(v) for v in inner["bbox"])
            inner_area = _area((ix1, iy1, ix2, iy2))
            if not inner_area or inner_area >= outer_area:
                continue
            overlap = _area((max(ox1, ix1), max(oy1, iy1),
                             min(ox2, ix2), min(oy2, iy2)))
            if overlap / inner_area >= CONTAINED_RATIO:
                inside.append(inner["id"])
        if inside:
            contents[outer["id"]] = inside
    return contents


def exclusion_names(ids) -> list[str]:
    """Humanised names for the ids a box swallows, capped and summarised.

    Public for exclusion_clause below, its one caller. Kept as its own function
    anyway because the capping and pluralisation is the part that has been
    wrong once already — worth testing in isolation from the sentence it ends
    up in.
    """
    named = [i.replace("_", " ") for i in ids[:MAX_NAMED_CONTENTS]]
    rest = len(ids) - MAX_NAMED_CONTENTS
    if rest > 0:
        named.append(f"and {rest} other element" + ("s" if rest > 1 else ""))
    return named


def exclusion_clause(ids) -> str:
    """What a crop shows but the sprite must not — the pack's `exclude` value.

    Phrased as one DO NOT DRAW bullet, which is where both paths file it:
    config.do_not_draw at build time, brief.py in the HTML.
    """
    return ("the " + ", ".join(exclusion_names(ids))
            + " visible inside it in the reference image")


def pack_text(model: str, key_env: str, style: dict, objects, refs_dir, pack_path,
              style_image=None) -> str:
    """The complete pack TOML: one [[assets]] per object per view.

    The endpoint (base_url/model/transport) is environment-owned and `build`
    reads it from .env — but the key *variable name* is a content decision:
    `cmd_extract` built this pack via `env_pack`, so it already knows which
    variable was populated (SPRITEGEN_API_KEY vs. the OPENROUTER_API_KEY
    default), and recording it documents the environment the pack was created
    against. An empty key_env ("this endpoint needs no key") round-trips as
    key_env = "", not dropped.
    """
    refs_dir, pack_path = Path(refs_dir), Path(pack_path)
    prefix = vision.style_prefix({"style": style})
    contents = find_contents(objects)

    def rel_to_pack(path) -> str:
        """Purely lexical (works whether or not the paths exist yet) and walks
        up with ".." where needed, so a reference stays relative even when
        refs_dir is not under the pack's directory — a pack and its refs must
        be movable together. Written with forward slashes: a pack produced on
        Windows must still load on POSIX, where a backslash is a filename
        character rather than a separator."""
        return Path(os.path.relpath(Path(path).resolve(),
                                    pack_path.parent.resolve())).as_posix()

    lines = [
        "# Generated by `spritegen extract`. Review the contact sheet in the refs",
        "# directory, delete any asset you do not want, then run `spritegen build`.",
        "",
        "[api]",
        f"key_env = {packwriter.toml_string(key_env)}",
        "",
        "[pack]",
        f"model = {packwriter.toml_string(model)}",
        "",
        "[style]",
        f"prefix = {packwriter.prefix_literal(prefix)}",
        'plate_prompt = "a representative object from this set"',
    ]
    if style_image is not None:
        # The source screenshot, sent beside every crop as image2. Text alone
        # does not carry a palette.
        lines.append("reference = " + packwriter.toml_string(rel_to_pack(style_image)))
    lines += [
        "",
        "[defaults]",
        'aspect_ratio = "1:1"',
        "",
    ]

    for obj in objects:
        rel = rel_to_pack(obj["crop"])
        exclude = contents.get(obj["id"])
        for view in obj.get("views") or [vision.DEFAULT_VIEW]:
            # Built as a plain local first: a nested-quote f-string here is a
            # SyntaxError on Python 3.11 ("expression part cannot include a
            # backslash"), which this project's floor still is.
            asset_id = "{}-{}".format(obj["id"], view)
            lines += [
                "[[assets]]",
                "id        = " + packwriter.toml_string(asset_id),
                # Multi-line literal: the body is labelled lines, and \n-escaping
                # them into a basic string would make the pack unreadable to the
                # human who is meant to prune it.
                "prompt    = " + packwriter.prefix_literal(vision.field_block(obj, view)),
            ]
            if exclude:
                lines.append("exclude   = "
                             + packwriter.toml_string(exclusion_clause(exclude)))
            lines += [
                "reference = " + packwriter.toml_string(rel),
                "",
            ]
    return "\n".join(lines)
