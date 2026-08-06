"""Image post-processing: background removal and trim/pad geometry."""

from __future__ import annotations

import math
import statistics
from io import BytesIO

from PIL import Image

_SESSION = None

# How far a pixel may sit from the measured backdrop colour and still count as
# backdrop. Wide enough for the gradient and JPEG-ish noise a generator leaves in
# a nominally flat fill, tight enough that a sprite's own mid-grey survives.
_BACKDROP_TOL = 20


def border_median(img) -> tuple[int, int, int]:
    """Median colour of the image's four corner patches.

    Measured rather than assumed: the backdrop does not come back at the
    #808080 that was asked for — one live loop returned 157,157,154.

    Corners, not the whole one-pixel frame. A tileable piece is asked to run
    from one edge of the picture to the other, which puts the subject itself
    along two whole sides of that frame; sampling it there made the subject the
    backdrop and the cut erased all but a smear of the sprite. Only an image
    with subject in all four corners defeats this, and that is a full-bleed
    image — which is what cutout = false is for.
    """
    rgb = img.convert("RGB")
    w, h = rgb.size
    patch = max(2, min(w, h) // 20)
    corners = ((0, 0), (w - patch, 0), (0, h - patch), (w - patch, h - patch))
    pixels = []
    for x, y in corners:
        pixels += list(rgb.crop((x, y, x + patch, y + patch)).getdata())
    return tuple(int(statistics.median(channel)) for channel in zip(*pixels))


def _drop_enclosed_backdrop(cut: Image.Image, original: Image.Image) -> Image.Image:
    """Clear backdrop that the cut kept because the subject encloses it.

    rembg segments by salience, and a hole in the middle of a subject reads as
    part of it: a conveyor loop came back as a ring with its own centre still
    filled in. Backdrop is backdrop wherever it sits, so the colour decides,
    not the topology.

    ponytail: a sprite that is genuinely this grey would get punched through.
    The tolerance is tight and the backdrop is one the prompt reserves, so it
    has not happened; a flood fill inward from the border is the upgrade if it
    ever does.
    """
    backdrop = border_median(original)
    rgb = original.convert("RGB")
    alpha = cut.getchannel("A")
    # Per-channel bands ANDed together: a pixel is backdrop only if all three
    # sit inside the tolerance, so a coloured pixel of similar brightness stays.
    mask = None
    for channel, target in zip(rgb.split(), backdrop):
        lo, hi = target - _BACKDROP_TOL, target + _BACKDROP_TOL
        band = channel.point(lambda v, lo=lo, hi=hi: 255 if lo <= v <= hi else 0)
        mask = band if mask is None else Image.composite(band, mask, mask)
    cut = cut.copy()
    cut.putalpha(Image.composite(Image.new("L", cut.size, 0), alpha, mask))
    return cut


def _key_out_backdrop(img: Image.Image) -> Image.Image:
    """Cut by colour alone: everything near the backdrop becomes transparent.

    The fallback for when the segmenter cannot run. BG_CLAUSE asks for a flat
    solid backdrop precisely so this is possible, and _drop_enclosed_backdrop
    already does the work — starting from fully opaque makes it the whole cut
    rather than a touch-up. Edges come out hard where rembg would have matted
    them, which is why this is second choice and not first.
    """
    opaque = img.convert("RGBA")
    opaque.putalpha(255)
    return _drop_enclosed_backdrop(opaque, img)


def cut_background(data: bytes) -> Image.Image:
    """Remove the background from encoded image bytes. Returns an RGBA image.

    The rembg session is created lazily and reused: building it downloads the
    birefnet-general weights on first use and is far too slow to repeat per asset.

    birefnet-general wants most of a gigabyte in one allocation and does not get
    it on a machine already holding a diffusion model in RAM — it failed with
    "Failed to allocate memory for requested buffer of size 822083584" right
    after the image had been generated. Losing a finished image to the step that
    was only meant to tidy it is the worst outcome available, so any failure here
    falls through to the colour key instead of raising.
    """
    global _SESSION
    img = Image.open(BytesIO(data)).convert("RGBA")
    try:
        from rembg import new_session, remove

        if _SESSION is None:
            _SESSION = new_session("birefnet-general")
        cut = remove(img, session=_SESSION).convert("RGBA")
    except Exception:
        return _key_out_backdrop(img)
    return _drop_enclosed_backdrop(cut, img)


def match_palette(img: Image.Image, master: Image.Image) -> Image.Image:
    """Pull an image's colours onto another image's, channel by channel.

    Pieces of one object generated in separate requests do not come back the
    same colour: a conveyor corner butted perfectly against its straight run —
    same band width, rails in line — but with a paler channel and cream
    highlights where the run had white. Geometry is what the model is needed
    for; the palette is already known from the piece that came out right.

    Mean and standard deviation per channel, over opaque pixels only. It moves
    the whole distribution, so a cast lifts and the contrast lands, while the
    model's own shading — the taper on a highlight, the shadow under a lip —
    survives as relative variation.

    ponytail: per-channel RGB, not a proper LAB transfer. It cannot fix a piece
    whose hue is wrong in one region only; a segmented or LAB-based match is the
    upgrade if that shows up.
    """
    import numpy as np

    src = img.convert("RGBA")
    a = np.asarray(src, dtype=np.float32)
    m = np.asarray(master.convert("RGBA"), dtype=np.float32)
    src_mask = a[..., 3] > 0
    m_mask = m[..., 3] > 0
    if not src_mask.any() or not m_mask.any():
        return img

    out = a.copy()
    for c in range(3):
        s, t = a[..., c][src_mask], m[..., c][m_mask]
        s_sd = s.std()
        if s_sd < 1e-3:                     # a flat channel has nothing to scale
            out[..., c] = np.clip(a[..., c] - s.mean() + t.mean(), 0, 255)
        else:
            out[..., c] = np.clip((a[..., c] - s.mean()) * (t.std() / s_sd) + t.mean(),
                                  0, 255)
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def trim_and_pad(img: Image.Image, margin: float = 0.04) -> Image.Image:
    """Crop to the alpha bounding box, then pad to a centered transparent square.

    `margin` is applied to each side, so the square's side is the subject's long
    edge times (1 + 2 * margin), rounded up to an even number. Nothing is ever
    resampled: this is crop plus transparent fill, so subject pixels survive
    bit-exact.
    """
    img = img.convert("RGBA")
    bbox = img.getchannel("A").getbbox()
    if bbox is None:
        return img  # fully transparent: nothing to trim, nothing to center

    cropped = img.crop(bbox)
    w, h = cropped.size
    side = math.ceil(max(w, h) * (1 + 2 * margin) / 2) * 2
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(cropped, ((side - w) // 2, (side - h) // 2))
    return canvas
