"""Turn a screenshot crop into something a generator can redraw from.

A crop lifted from a phone screenshot carries three defects that have nothing to
do with the object in it, and every one of them was measured coming back in the
generated sprite: the capture's pixel steps arrived as pixel art, the screen's
top-to-bottom lighting ramp arrived as a piece dark at one end and pale at the
other, and the phone's letterbox bars arrived as black slabs welded to the
sprite. The prompt already says all three are capture artefacts. It loses —
image evidence beats a sentence — so they are removed here instead.

Nothing in this module makes a judgement. It is the deterministic half of the
work; deciding what to crop, what to call it and what to write about it stays
with whoever is reading the screenshot.
"""

from __future__ import annotations

from PIL import Image, ImageFilter

# Below this summed RGB a pixel is the capture's own black border, not art. A
# genuinely black sprite pixel is rare in this palette and would in any case be
# recovered by the surrounding fill rather than lost.
_LETTERBOX_SUM = 90
# Long edge a reference is upscaled to. The generator resamples to its own
# latent resolution regardless, so this is not about detail — it is about not
# handing it stair-stepped edges to copy.
MIN_LONG_EDGE = 768
# Flat-field gain is clamped: unclamped, the blur has only one side to average
# at the borders and overshoots into black strips down both edges.
_GAIN_LO, _GAIN_HI = 0.85, 1.18


def _median(values):
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def background_colour(img: Image.Image) -> tuple[int, int, int]:
    """The crop's own surroundings, read from its four corner patches.

    Corners rather than the whole frame: an object that runs to an edge of its
    crop puts itself along that whole side.
    """
    rgb = img.convert("RGB")
    w, h = rgb.size
    patch = max(2, min(w, h) // 10)
    pixels = []
    for x, y in ((0, 0), (w - patch, 0), (0, h - patch), (w - patch, h - patch)):
        pixels += list(rgb.crop((x, y, x + patch, y + patch)).getdata())
    return tuple(_median(channel) for channel in zip(*pixels))


def strip_letterbox(img: Image.Image, fill=None) -> Image.Image:
    """Replace the capture's black bars with the crop's own background."""
    rgb = img.convert("RGB")
    fill = tuple(fill) if fill else background_colour(rgb)
    data = list(rgb.getdata())
    if not any(sum(p) < _LETTERBOX_SUM for p in data):
        return rgb
    out = Image.new("RGB", rgb.size)
    out.putdata([fill if sum(p) < _LETTERBOX_SUM else p for p in data])
    return out


def flat_field(img: Image.Image) -> Image.Image:
    """Divide out the slow luminance ramp the screen's lighting left behind.

    A heavy blur of an image is its large-scale brightness and nothing else, so
    dividing by it and restoring the overall level flattens the ramp while
    leaving every edge, highlight and shadow intact.
    """
    import numpy as np

    rgb = img.convert("RGB")
    a = np.asarray(rgb, dtype=np.float32)
    blur = np.asarray(rgb.filter(ImageFilter.GaussianBlur(radius=max(rgb.size) * 0.25)),
                      dtype=np.float32)
    gain = np.clip(blur.mean(axis=(0, 1)) / np.maximum(blur, 1.0), _GAIN_LO, _GAIN_HI)
    return Image.fromarray(np.clip(a * gain, 0, 255).astype(np.uint8), "RGB")


def upscale(img: Image.Image, min_long: int = MIN_LONG_EDGE) -> Image.Image:
    """Resample up to min_long on the long edge. Never downscales."""
    long_edge = max(img.size)
    if long_edge >= min_long:
        return img
    factor = min_long / long_edge
    return img.resize((max(1, round(img.width * factor)),
                       max(1, round(img.height * factor))), Image.LANCZOS)


def row_flatten(img: Image.Image) -> Image.Image:
    """Replace every row with its own median colour.

    For a straight run of something extruded sideways — a rail, a belt, a wall
    course — the cross-section is the whole design and every row is one colour
    by definition. Flattening erases what varies along the run (the direction
    chevrons painted on a conveyor) and cannot touch what does not (the rails,
    which are rows). A median *filter* wide enough to erase the chevrons ate a
    rail; this cannot.

    The median *pixel*, by brightness — not each channel's median separately.
    Separate medians can name a colour that is nowhere in the row: a strip
    padded far enough up to catch a blue HUD badge took its red and green from
    the badge and its blue from the track, and painted the row green.
    """
    rgb = img.convert("RGB")
    w, h = rgb.size
    out = Image.new("RGB", (w, h))
    for y in range(h):
        row = sorted(rgb.crop((0, y, w, y + 1)).getdata(),
                     key=lambda p: (p[0] * 299 + p[1] * 587 + p[2] * 114, p))
        out.paste(Image.new("RGB", (w, 1), row[len(row) // 2]), (0, y))
    return out


def palette(img: Image.Image, count: int = 5) -> list[str]:
    """The crop's dominant colours as hex, most-used first.

    Measured, because asked-for colour is not what comes back: a vision model
    described a conveyor's channel as "pale lilac-white" when it is #434375,
    and the sprite came out pale until the real value went into the prompt.
    """
    small = img.convert("RGB")
    if max(small.size) > 200:                    # quantise cost, not quality
        small = small.resize((min(200, small.width), min(200, small.height)))
    reduced = small.quantize(colors=count, method=Image.MEDIANCUT).convert("RGB")
    counts = reduced.getcolors(small.width * small.height) or []
    return ["#{:02X}{:02X}{:02X}".format(*rgb)
            for _, rgb in sorted(counts, reverse=True)[:count]]


def clean(img: Image.Image, *, flatten_rows: bool = False,
          min_long: int = MIN_LONG_EDGE) -> Image.Image:
    """The whole cleanup, in the order the steps have to run.

    Letterbox first, or its black feeds every later average. Rows next, while
    the image is still small and a row is still one row of the capture.
    Flat-field before upscaling, so the blur radius is measured on real pixels
    rather than interpolated ones. Upscale last.

    Flattened rows skip the flat-field: row_flatten has already removed every
    variation along the run, so the only variation left is the cross-section —
    which is the design, not a lighting ramp. Correcting it anyway tinted the
    top of a conveyor run green, because per-channel gain on a near-neutral
    dark row amplifies whichever channel happens to lead.
    """
    out = strip_letterbox(img)
    if flatten_rows:
        return upscale(row_flatten(out), min_long)
    return upscale(flat_field(out), min_long)


def clean_crops(entries, *, min_long: int = MIN_LONG_EDGE) -> None:
    """Clean every kept object's crop in place and record its palette.

    Runs after the crops are written and after any contents have been blanked
    out of them: blanking maps boxes measured on the source image into crop
    coordinates, which upscaling here would invalidate.
    """
    for entry in entries:
        path = entry.get("crop")
        if not path:
            continue
        with Image.open(path) as opened:
            source = opened.convert("RGB")
        cleaned = clean(source, flatten_rows=bool(entry.get("flatten_rows")),
                        min_long=min_long)
        cleaned.save(path)
        entry["palette"] = palette(cleaned)
