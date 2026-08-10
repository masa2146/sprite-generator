"""Box geometry: validate, pad, crop, blank and sheet.

Nothing here decides anything — it takes boxes someone else chose and turns
them into files on disk. A box that cannot be used is rejected with a reason
and reported; it is never dropped silently, because a crop that quietly went
missing is a defect nobody sees until the sprite is wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw

MIN_EDGE = 16              # smaller than this cannot be a usable sprite
MAX_AREA_RATIO = 0.9       # a box this big means the model returned the whole screen
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


def ring_median(image, box, margin: int = 6) -> tuple[int, int, int]:
    """The median colour of a band just outside `box` in the source image.

    What should show through a hole is whatever surrounds the hole, and that is
    a different colour for every hole: board around a brick field, pink body
    around a number printed on it. One global estimate cannot serve both — and
    a global one taken from the image's border served neither, because a phone
    screenshot's border is its letterbox bars, so every blanked box came back
    a black slab.

    The median *pixel*, never a per-channel median, which can name a colour
    that is nowhere in the band.
    """
    x1, y1, x2, y2 = (int(v) for v in box)
    outer = (max(0, x1 - margin), max(0, y1 - margin),
             min(image.width, x2 + margin), min(image.height, y2 + margin))
    rgb = image.convert("RGB")
    band = [p for i, p in enumerate(rgb.crop(outer).getdata())
            if not (margin <= i % (outer[2] - outer[0]) < (outer[2] - outer[0]) - margin
                    and margin <= i // (outer[2] - outer[0]) < (outer[3] - outer[1]) - margin)]
    if not band:
        band = list(rgb.crop(outer).getdata())
    band.sort(key=lambda p: (p[0] * 299 + p[1] * 587 + p[2] * 114, p))
    return band[len(band) // 2]


def blank_contents(kept, contents, image) -> list[str]:
    """Paint each framing object's contents out of its own crop.

    The `exclude` clause says it in words, and words lose. REFERENCES tells the
    model to take the object's identity from Picture 1 — silhouette, colours,
    markings — and a conveyor crop that still shows the brick field, the
    dispenser and the nozzle is far stronger evidence than a DO NOT DRAW bullet
    is a counterweight. The first live loop came back with the whole board
    drawn inside it. Blanking the boxes makes the picture and the text say the
    same thing.

    Each hole is filled from its own surroundings — see ring_median. A single
    fill for the whole image cannot be right for both a brick field inside a
    loop and a number printed on a pink body, and taking that single fill from
    the image's border was worse still: a phone screenshot's border is its
    letterbox bars, so every blanked box came back a black slab.

    Returns the ids whose crops were rewritten.
    """
    by_id = {obj["id"]: obj for obj in kept}
    framed = {inner for ids in contents.values() for inner in ids}
    touched = []
    for obj in kept:
        obj_id = obj["id"]
        inner_ids = contents.get(obj_id) or []
        # Boxes the analysis asked for by hand: a number printed on a body, a
        # neighbour the padding dragged in. Whatever the model must not copy has
        # to leave the picture — forbidding it in words loses every time.
        hand = [b for b in (obj.get("blank") or [])
                if isinstance(b, (list, tuple)) and len(b) == 4]
        # The padding ring of an object that sits inside another one is that
        # other one's wall, by construction. Blanking ran one way only, so a
        # dispenser's crop lost the projectile while the projectile's crop kept
        # half a dispenser — and on a 26px object the walls are most of what
        # the model is shown.
        walls = obj_id in framed
        if not (inner_ids or hand or walls) or not obj.get("crop"):
            continue

        with Image.open(obj["crop"]) as opened:
            crop = opened.convert("RGB")
        ox1, oy1, _, _ = padded_box(obj["bbox"], image.width, image.height)
        draw = ImageDraw.Draw(crop)

        if walls:
            x1, y1, x2, y2 = (int(v) for v in obj["bbox"])
            # The ring outside this object's own box is the housing's wall, so
            # what belongs there is what surrounds the housing, not what
            # surrounds the object.
            container = next((by_id[o]["bbox"] for o, ids in contents.items()
                              if obj_id in ids and o in by_id), obj["bbox"])
            ring = Image.new("RGB", crop.size, ring_median(image, container))
            ring.paste(crop.crop((x1 - ox1, y1 - oy1, x2 - ox1, y2 - oy1)),
                       (x1 - ox1, y1 - oy1))
            crop = ring
            draw = ImageDraw.Draw(crop)
        for box in [by_id[i]["bbox"] for i in inner_ids if i in by_id] + hand:
            ix1, iy1, ix2, iy2 = (int(v) for v in box)
            draw.rectangle((ix1 - ox1, iy1 - oy1, ix2 - ox1, iy2 - oy1),
                           fill=ring_median(image, box))
        crop.save(obj["crop"])
        touched.append(obj_id)
    return touched
