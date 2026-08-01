"""Image post-processing: background removal and trim/pad geometry."""

from __future__ import annotations

import math
from io import BytesIO

from PIL import Image

_SESSION = None


def cut_background(data: bytes) -> Image.Image:
    """Remove the background from encoded image bytes. Returns an RGBA image.

    The rembg session is created lazily and reused: building it downloads the
    birefnet-general weights on first use and is far too slow to repeat per asset.
    """
    global _SESSION
    from rembg import new_session, remove

    if _SESSION is None:
        _SESSION = new_session("birefnet-general")
    img = Image.open(BytesIO(data)).convert("RGBA")
    return remove(img, session=_SESSION).convert("RGBA")


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
