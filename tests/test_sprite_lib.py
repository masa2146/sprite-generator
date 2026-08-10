"""2D delivery helpers: the contour every set wears, and the readability
measurements that decide whether a sprite ships."""
import numpy as np
from PIL import Image, ImageFilter

from sprite_lib import contour


def _disc(size=64, r=20):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    a = np.zeros((size, size), np.uint8)
    yy, xx = np.mgrid[0:size, 0:size]
    a[(xx - size//2)**2 + (yy - size//2)**2 <= r*r] = 255
    rgb = np.zeros((size, size, 3), np.uint8)
    rgb[a > 0] = (220, 90, 60)
    return Image.fromarray(np.dstack([rgb, a]), "RGBA")


def _half_soft_disc(size=64, r=20, blur=2):
    """Same silhouette as `_disc`, but the right half of the boundary is
    pre-blurred while the left half stays a hard step -- unequal edge
    softness in one image, like a horn tip's soft AA next to a flat side's
    crisp AA in the character art that motivated this helper. A disc alone
    can't tell hard-thresholding apart from dilating raw alpha, because a
    circle's curvature (and so its AA softness) is the same at every angle."""
    a = np.zeros((size, size), np.uint8)
    yy, xx = np.mgrid[0:size, 0:size]
    a[(xx - size//2)**2 + (yy - size//2)**2 <= r*r] = 255
    hard = Image.fromarray(a, "L")
    soft = hard.filter(ImageFilter.GaussianBlur(blur))
    a = np.array(hard)
    a[:, size//2:] = np.array(soft)[:, size//2:]
    rgb = np.zeros((size, size, 3), np.uint8)
    rgb[a > 0] = (220, 90, 60)
    return Image.fromarray(np.dstack([rgb, a]), "RGBA")


def test_the_contour_is_the_same_width_all_the_way_round():
    out = np.asarray(contour(_disc(), width=3, color=(20, 20, 40)))
    ink = (out[..., :3].sum(axis=-1) < 200) & (out[..., 3] > 128)
    widths = []
    for row in (32,):
        on = np.where(ink[row])[0]
        left = on[on < 32]
        right = on[on > 32]
        widths += [left.max() - left.min() + 1, right.max() - right.min() + 1]
    for col in (32,):
        on = np.where(ink[:, col])[0]
        top = on[on < 32]
        bot = on[on > 32]
        widths += [top.max() - top.min() + 1, bot.max() - bot.min() + 1]
    assert max(widths) - min(widths) <= 1, widths


def test_the_subject_survives_under_the_contour():
    out = np.asarray(contour(_disc(), width=3, color=(20, 20, 40)))
    assert tuple(out[32, 32, :3]) == (220, 90, 60)


def _ray_width(ink, cx, cy, dx, dy):
    """Euclidean extent of the ink band along one ray from (cx, cy) in
    direction (dx, dy) -- (1, 0)/(0, 1) for the axes, (1, 1) for a diagonal.
    Multiplying the pixel-run length by the ray's own per-step distance
    (1 on an axis, root 2 on a diagonal) is what makes the three
    directions comparable in real length rather than pixel count."""
    step = (dx**2 + dy**2) ** 0.5
    vals, d = [], 0
    while True:
        x, y = cx + dx*d, cy + dy*d
        if not (0 <= x < ink.shape[1] and 0 <= y < ink.shape[0]):
            break
        vals.append(ink[y, x])
        d += 1
    on = np.where(vals)[0]
    return (on.max() - on.min() + 1) * step if len(on) else 0


def test_the_contour_is_the_same_width_on_the_diagonal_too():
    # A disc's own AA is angle-invariant (the same blind spot noted above),
    # but ImageFilter.MaxFilter's structuring element is a SQUARE, not a
    # circle: it reaches root-2 further along a diagonal boundary normal
    # than an axis-aligned one. Measured through this same function at
    # size=600/r=200/width=40 (a scale where single-pixel downsample
    # quantization stops dominating): plain MaxFilter gave axis=13px,
    # diagonal=18.38px, ratio 1.41 (root 2); the round dilate this helper
    # actually uses (_plus_dilate/_square_dilate alternation, see
    # _round_dilate) gives axis=13px, diagonal=14.14px, ratio 1.09. The 25%
    # tolerance below sits comfortably above that 9% measured noise floor
    # and comfortably below the 41% a square kernel misses by.
    size, r, width = 600, 200, 40
    out = np.asarray(contour(_disc(size, r), width=width, color=(20, 20, 40)))
    ink = (out[..., :3].sum(axis=-1) < 200) & (out[..., 3] > 128)
    cx = cy = size // 2
    widths = [
        _ray_width(ink, cx, cy, 1, 0),
        _ray_width(ink, cx, cy, 0, 1),
        _ray_width(ink, cx, cy, 1, 1),
    ]
    assert max(widths) / min(widths) <= 1.25, widths


def test_the_contour_stays_opaque_over_a_pre_softened_edge():
    # A disc's own AA is angle-invariant, so it can't catch this: dilating
    # raw alpha (instead of hard-thresholding it first) makes the ring
    # follow the source edge's softness. Over the hard half here it still
    # darkens close to the outline color; over the pre-blurred half it
    # stays close to the subject's own color (220+90+60=370) because the
    # ring alpha never climbs high enough to read as ink -- the "blurred
    # horn tip" bug, reproduced.
    out = np.asarray(contour(_half_soft_disc(), width=3, color=(20, 20, 40)))
    row = 32
    hard_side = out[row, 4:20]
    soft_side = out[row, 44:60]
    hard_darkest = hard_side[hard_side[:, 3] > 128][:, :3].sum(axis=-1).min()
    soft_darkest = soft_side[soft_side[:, 3] > 128][:, :3].sum(axis=-1).min()
    assert hard_darkest < 200, hard_darkest
    assert soft_darkest < 200, soft_darkest
