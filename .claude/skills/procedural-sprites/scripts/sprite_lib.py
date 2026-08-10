"""sprite_lib - helpers for drawing 2D game sprites procedurally.

Core idea: draw with code (Pillow + numpy) at SS x resolution, downsample with
Lanczos. Edges come out perfectly anti-aliased, results are deterministic,
recoloring is a one-line change. Import everything:

    from sprite_lib import *

All drawing happens on RGBA canvases at SS-supersampled size; call down()
exactly once at the end of each asset.
"""
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops

SS = 4  # supersample factor; all coordinates below are in SS-space


# ------------------------------------------------------------ canvas basics
def canvas(w, h, color=(0, 0, 0, 0)):
    """Transparent RGBA canvas at supersampled size for a final w x h sprite."""
    return Image.new('RGBA', (w * SS, h * SS), color)


def down(im, w, h):
    """Final downsample. Call once per asset - never resize twice."""
    return im.resize((w, h), Image.LANCZOS)


# ------------------------------------------------------------ gradients
def vgrad(w, h, stops):
    """Vertical gradient RGBA image. stops = [(pos 0..1, (r,g,b)), ...]."""
    ys = np.linspace(0, 1, h)
    ps = [p for p, _ in stops]
    cs = np.array([c for _, c in stops], float)
    cols = np.stack([np.interp(ys, ps, cs[:, i]) for i in range(3)], axis=1)
    arr = np.repeat(cols[:, None, :], w, axis=1)
    return Image.fromarray(
        np.dstack([arr, np.full((h, w), 255.0)]).astype(np.uint8))


def rgrad(w, h, cx, cy, r, inner, outer):
    """Radial gradient (inner color at center -> outer at radius r)."""
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    d = np.clip(np.hypot(xx - cx, yy - cy) / r, 0, 1)[..., None]
    arr = np.array(inner, float) * (1 - d) + np.array(outer, float) * d
    return Image.fromarray(
        np.dstack([arr, np.full((h, w, 1), 255.0)]).astype(np.uint8))


# ------------------------------------------------------------ masks & fills
def rr_mask(size, box, radius):
    """L-mode mask of a rounded rectangle."""
    m = Image.new('L', size, 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius=radius, fill=255)
    return m


def ellipse_mask(size, box):
    m = Image.new('L', size, 0)
    ImageDraw.Draw(m).ellipse(box, fill=255)
    return m


def poly_mask(size, points):
    m = Image.new('L', size, 0)
    ImageDraw.Draw(m).polygon(points, fill=255)
    return m


def union(*masks):
    """Union of L masks - build compound silhouettes (body + ears + ...)."""
    out = masks[0].copy()
    for m in masks[1:]:
        out.paste(255, (0, 0), m)
    return out


def fill_grad(dst, mask, stops, box=None):
    """Fill a mask with a vertical gradient spanning `box` (default: mask bbox).
    This is the workhorse: silhouette mask + gradient = shaded body."""
    if box is None:
        box = mask.getbbox()
    x0, y0, x1, y1 = box
    g = vgrad(x1 - x0, y1 - y0, stops)
    layer = Image.new('RGBA', dst.size, (0, 0, 0, 0))
    layer.paste(g, (x0, y0))
    dst.paste(layer, (0, 0), mask)


# ------------------------------------------------------------ light & depth
def sheen(dst, box, radius, color=(255, 255, 255), alpha=90, blur=6,
          clip=None):
    """Soft glossy highlight band. blur is in FINAL pixels (scaled by SS).
    Pass clip=<mask> to keep the glow inside a silhouette."""
    layer = Image.new('RGBA', dst.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius=radius,
                                            fill=color + (alpha,))
    layer = layer.filter(ImageFilter.GaussianBlur(blur * SS))
    if clip is not None:
        black = Image.new('RGBA', dst.size, (0, 0, 0, 0))
        layer = Image.composite(layer, black, clip)
    dst.alpha_composite(layer)


def inner_shadow(dst, mask, offset=(0, 6), alpha=110, blur=4,
                 color=(10, 10, 30)):
    """Darkening just inside a silhouette's edge - gives recessed depth."""
    inv = mask.point(lambda v: 255 - v)
    sh = Image.new('L', mask.size, 0)
    sh.paste(inv, (offset[0] * SS, offset[1] * SS))
    sh = sh.filter(ImageFilter.GaussianBlur(blur * SS))
    layer = Image.new('RGBA', dst.size, color + (0,))
    layer.putalpha(sh.point(lambda v: v * alpha // 255))
    black = Image.new('RGBA', dst.size, (0, 0, 0, 0))
    dst.alpha_composite(Image.composite(layer, black, mask))


def drop_shadow(dst, mask, offset=(0, 4), alpha=120, blur=4,
                color=(20, 14, 40)):
    """Soft shadow behind a silhouette. Call BEFORE filling the body."""
    sh = Image.new('L', mask.size, 0)
    sh.paste(mask, (offset[0] * SS, offset[1] * SS))
    sh = sh.filter(ImageFilter.GaussianBlur(blur * SS))
    layer = Image.new('RGBA', dst.size, color + (0,))
    layer.putalpha(sh.point(lambda v: v * alpha // 255))
    dst.alpha_composite(layer)


# ------------------------------------------------ tileables: section sweep
def sweep_straight(section_fn, width, length, horizontal=True):
    """Tileable straight piece: a cross-section function swept in a line.
    section_fn(t: array 0..1) -> float RGB array; t=0 is the top (or left)."""
    t = (np.arange(width) + 0.5) / width
    rgb = section_fn(t)
    a = np.full(rgb.shape[:-1] + (1,), 255.0)
    strip = np.concatenate([np.tile(rgb[:, None, :], (1, length, 1)),
                            np.tile(a[:, None, :], (1, length, 1))], axis=2)
    im = Image.fromarray(strip.astype(np.uint8))
    return im if horizontal else im.rotate(90, expand=True)


def sweep_corner(section_fn, width, r_in):
    """90-degree corner using the SAME section -> joins the straight piece
    seamlessly by construction. Arc center = bottom-right canvas corner;
    ends are flush with the bottom and right canvas edges.
    t runs 0 at r_out (outside) -> 1 at r_in, matching sweep_straight's top=0
    when the straight approaches from the right."""
    r_out = r_in + width
    S = int(math.ceil(r_out))
    yy, xx = np.mgrid[0:S, 0:S].astype(float) + 0.5
    r = np.hypot(S - xx, S - yy)
    t = 1.0 - (r - r_in) / width
    rgb = section_fn(np.clip(t, 0, 1))
    aa = (np.clip((r - (r_in - 1.5)) / 1.5, 0, 1) *
          np.clip(((r_out + 1.5) - r) / 1.5, 0, 1))
    a = (((r >= r_in - 1.5) & (r <= r_out + 1.5)) * aa * 255)[..., None]
    return Image.fromarray(np.concatenate([rgb, a], 2).astype(np.uint8))


def piecewise_section(segments, soft=0.018):
    """Build a smooth section_fn from [(t0, t1, (r,g,b)), ...] bands.
    Measure the bands from a reference (see measure_section) or design them."""
    def fn(t):
        t = np.clip(t, 0, 1)
        out = np.zeros(t.shape + (3,))
        wa = np.zeros(t.shape)
        for t0, t1, col in segments:
            w = (1 / (1 + np.exp(-(t - t0) / (soft / 2)))) * \
                (1 / (1 + np.exp((t - t1) / (soft / 2))))
            out += w[..., None] * np.array(col, float)
            wa += w
        return out / np.maximum(wa, 1e-6)[..., None]
    return fn


# ------------------------------------------------------------ measurement
def measure_section(ref_path, axis=1):
    """Median color profile across a reference strip crop -> list of
    (row_index, (r,g,b)). Use it to place piecewise_section bands."""
    a = np.asarray(Image.open(ref_path).convert('RGB')).astype(float)
    prof = np.median(a, axis=axis)
    return [(i, tuple(int(v) for v in row)) for i, row in enumerate(prof)]


def dominant_colors(ref_path, n=6):
    """Rough palette extraction from any reference image."""
    im = Image.open(ref_path).convert('RGB').resize((128, 128))
    pal = im.quantize(colors=n, method=Image.MEDIANCUT).getpalette()[:n * 3]
    return [tuple(pal[i * 3:i * 3 + 3]) for i in range(n)]


# ------------------------------------------------------------ output
def rotations(master, angles=(45, 90, 135)):
    """In-plane rotation frames from ONE master - never regenerate rotations."""
    big = master.resize((master.width * 2, master.height * 2), Image.LANCZOS)
    out = []
    for a in angles:
        r = big.rotate(-a, expand=True, resample=Image.BICUBIC)
        out.append(r.resize((r.width // 2, r.height // 2), Image.LANCZOS))
    return out


def contact_sheet(images, path, bg=(128, 128, 128, 255), pad=14, max_w=560,
                  scale=None):
    """QC sheet: paste sprites on the game backdrop at (roughly) in-game size.
    `images` = [(PIL image, display_width_or_None), ...]. A sprite that does
    not read at this size does not ship, however good it looks at 1024."""
    placed, x, y, rowh = [], pad, pad, 0
    for im, w in images:
        if scale and not w:
            w = int(im.width * scale)
        if w:
            im = im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
        if x + im.width > max_w - pad:
            x, y, rowh = pad, y + rowh + pad, 0
        placed.append((im, x, y))
        x += im.width + pad
        rowh = max(rowh, im.height)
    sheet = Image.new('RGBA', (max_w, y + rowh + pad), bg)
    for im, px, py in placed:
        sheet.alpha_composite(im, (px, py))
    sheet.convert('RGB').save(path)
    return sheet


def _plus_dilate(arr):
    """One step of 4-neighbor grey dilation (city-block distance +1)."""
    out = arr.copy()
    out[1:, :] = np.maximum(out[1:, :], arr[:-1, :])
    out[:-1, :] = np.maximum(out[:-1, :], arr[1:, :])
    out[:, 1:] = np.maximum(out[:, 1:], arr[:, :-1])
    out[:, :-1] = np.maximum(out[:, :-1], arr[:, 1:])
    return out


def _square_dilate(arr):
    """One step of 8-neighbor grey dilation (chessboard distance +1) --
    the 4-neighbor step plus the 4 diagonals."""
    out = _plus_dilate(arr)
    out[1:, 1:] = np.maximum(out[1:, 1:], arr[:-1, :-1])
    out[:-1, :-1] = np.maximum(out[:-1, :-1], arr[1:, 1:])
    out[1:, :-1] = np.maximum(out[1:, :-1], arr[:-1, 1:])
    out[:-1, 1:] = np.maximum(out[:-1, 1:], arr[1:, :-1])
    return out


def _round_dilate(im, radius):
    """Grow a grayscale PIL image by `radius` px, round rather than square.

    `ImageFilter.MaxFilter` dilates with a SQUARE structuring element, so it
    grows further along a diagonal boundary normal than an axis-aligned one
    -- measured at width=40 on a 1400px disc: ~12.9px on the axes against
    ~19.8px on the diagonals, a ~1.5x ratio (root 2, plus downsample
    spread). Alternating a 4-neighbor (plus) dilation step with an
    8-neighbor (square) one, one step per unit of radius, grows an octagon
    instead -- within a few percent of a circle in every direction, cheap
    in pure numpy, no new dependency.
    """
    arr = np.asarray(im, dtype=np.uint8)
    for i in range(radius):
        arr = _plus_dilate(arr) if i % 2 == 0 else _square_dilate(arr)
    return Image.fromarray(arr, "L")


def contour(img, width=2, color=(26, 26, 46), threshold=110, ss=3):
    """The set's dark outline, at one width the whole way round.

    The alpha is HARD-THRESHOLDED before it is grown. Dilating an
    anti-aliased alpha instead makes the line's width follow how soft the
    edge happens to be, which is why one asset's horn tips came out blurred
    while its flat sides came out crisp. The growth itself uses
    `_round_dilate`, not a square `MaxFilter`, for the same "one width"
    reason: a square kernel grows ~1.5x further on the diagonal than on the
    axes (see its docstring for the measurement).
    """
    big = img.resize((img.width*ss, img.height*ss), Image.LANCZOS)
    a = big.getchannel("A").point(lambda v: 255 if v > threshold else 0)
    grown = _round_dilate(a, width)
    ring = ImageChops.subtract(grown, a)
    layer = Image.new("RGBA", big.size, tuple(color) + (0,))
    layer.putalpha(ring)
    out = Image.new("RGBA", big.size, (0, 0, 0, 0))
    out.alpha_composite(layer)
    out.alpha_composite(big)
    return out.resize(img.size, Image.LANCZOS)


# ------------------------------------------------ relief shading (v2)
def shade_relief(mask, light=(-0.4, -0.8), dome=10, diffuse=0.55, spec=0.5,
                 shininess=24, ambient=0.62):
    """Physically-motivated shading for a silhouette: build a soft height
    field from the mask (blur = rounded dome), derive normals, then Lambert
    diffuse + Blinn specular from ONE global light direction.

    Returns (shade, specular) as float arrays in 0..1 to multiply/add onto a
    base color layer:  rgb * (ambient + diffuse*shade) + 255*spec*specular

    Use this instead of hand-placed highlight stickers when a piece should
    read as a 3D volume; tune `dome` (bigger = rounder) per asset scale.
    light is (lx, ly) with -y pointing to a top light."""
    h = np.asarray(mask.filter(ImageFilter.GaussianBlur(dome * SS)),
                   float) / 255.0
    gy, gx = np.gradient(h)
    nz = 1.0 / np.sqrt(gx**2 + gy**2 + 1)
    nx, ny = -gx * nz, -gy * nz
    lx, ly = light
    lz = math.sqrt(max(1e-6, 1 - lx*lx - ly*ly))
    lam = np.clip(nx*lx + ny*ly + nz*lz, 0, 1)
    # Blinn half-vector with viewer at +z
    hx, hy, hz = lx, ly, lz + 1
    n = math.sqrt(hx*hx + hy*hy + hz*hz)
    hx, hy, hz = hx/n, hy/n, hz/n
    sp = np.clip(nx*hx + ny*hy + nz*hz, 0, 1) ** shininess
    return ambient + diffuse*lam, spec*sp


def apply_relief(dst, mask, base_rgb_layer, **kw):
    """Convenience: multiply base color layer by relief shade and add the
    specular, clipped to the silhouette."""
    shade, sp = shade_relief(mask, **kw)
    arr = np.asarray(base_rgb_layer).astype(float)
    rgb = np.clip(arr[..., :3]*shade[..., None] + 255*sp[..., None], 0, 255)
    out = np.dstack([rgb, arr[..., 3]]).astype(np.uint8)
    black = Image.new('RGBA', dst.size, (0, 0, 0, 0))
    dst.alpha_composite(Image.composite(Image.fromarray(out), black, mask))


# ------------------------------------------------------------ readability
def readability(img, size=(44, 52)):
    """What survives the shrink to on-screen size, as numbers.

    This measures and reports; it does not decide. Which counts are enough is
    the asset's own acceptance criterion and belongs in the asset's script --
    one obstacle needs its brow bar to survive, a UI pill needs nothing of
    the sort.
    """
    small = np.asarray(img.resize(size, Image.LANCZOS))
    rgb = small[..., :3].astype(int)
    on = small[..., 3].astype(int) > 100
    return dict(dark=int(((rgb.max(axis=-1) < 90) & on).sum()),
               pale=int(((rgb.min(axis=-1) > 170) & on).sum()),
               coverage=round(float(on.mean()), 3))


def silhouette(img, color=(0, 0, 0)):
    """The sprite filled flat, for a workshop habit of a readability check:
    look at the shape alone and see whether it still says what the thing is.
    Not a verified industry standard -- just a picture worth looking at."""
    out = Image.new("RGBA", img.size, tuple(color) + (0,))
    out.putalpha(img.getchannel("A"))
    return out


def qc_strip(img, sizes, path, bg=(128, 128, 128, 255)):
    """The sprite at the sizes the game actually draws it, on the game's own
    backdrop colour. A sprite that does not read here does not ship, however
    good it looks at 1024."""
    return contact_sheet([(img.resize(s, Image.LANCZOS), None) for s in sizes],
                         path, bg=bg)


# ------------------------------------------------ reference comparison (v2)
def side_by_side(ref_path, render, out_path, height=280,
                 bg=(128, 128, 128, 255)):
    """Compose reference | render at the same display height. Render this,
    then LOOK at it, list the mismatches (silhouette, palette, light
    direction, highlight shape) and fix them. Never ship unseen."""
    ref = Image.open(ref_path).convert('RGBA')
    ref = ref.resize((int(ref.width*height/ref.height), height),
                     Image.NEAREST)  # nearest: show the crop as-is
    r = render.resize((int(render.width*height/render.height), height),
                      Image.LANCZOS)
    pad = 16
    sheet = Image.new('RGBA', (ref.width + r.width + pad*3, height + pad*2), bg)
    sheet.alpha_composite(ref, (pad, pad))
    sheet.alpha_composite(r, (ref.width + pad*2, pad))
    sheet.convert('RGB').save(out_path)
    return sheet
