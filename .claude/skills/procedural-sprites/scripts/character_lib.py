"""character_lib - the parts of a character a raymarched sprite needs and the
renderer has no opinion about: eyes built as geometry, decals along a curve,
a light that turns with the camera, and a turnaround.

It gives no anatomy. Body plans, proportions and stance are the asset's, and
a library that shipped them would make every character come out of the same
mould.
"""
import math

import numpy as np

from sdf3d import LIGHT, material, render, sphere

# Convention for turnaround file naming, not an art direction: the library
# gives no opinion on which angles a character set actually needs.
VIEWS = {"front": 0, "three_quarter": 38, "side": 82, "back": 180}


class Eye:
    """socket: smooth-unioned into the head, carrying NO material of its own.
    parts:  hard-unioned, each with its own material.
    decals: passed to spots() alongside the rest of the face.

    The split is the whole point. A nearest-part material select is exact for
    a hard union and wrong inside a smooth_union's blend band, so the piece
    that blends must share the head's material, and the pieces that need
    their own colour must not blend.
    """
    __slots__ = ("socket", "parts", "decals")

    def __init__(self, socket, parts, decals):
        self.socket = socket
        self.parts = parts
        self.decals = decals


def eye(center, look, r=0.09, iris=0.045, pupil=0.022, glint=0.018,
        sclera=(250, 250, 255), iris_color=(60, 40, 30),
        pupil_color=(20, 18, 28), glint_color=(255, 255, 255)):
    """An eye as geometry: a socket bulge, a white, an iris, a pupil, a glint.

    Flat dark shapes stuck on a face read as part of the brow above them —
    the whites are what make a character look back at you. Setting iris to 0
    drops it and gives a plain dot eye, so this does not force a style.
    """
    c = np.array(center, float)
    d = np.array(look, float)
    d = d / (np.linalg.norm(d) + 1e-9)

    socket = sphere(r, tuple(c))

    # Each part is a sphere nested along `look`; only its front CAP (offset
    # from centre + its own radius) can ever reach the camera, so a part is
    # visible at all only where its cap sits strictly beyond the cap of the
    # part behind it -- Surface picks whichever part's SDF reads nearest to
    # zero, and a part whose cap doesn't clear the one behind it never wins
    # a single ray no matter how it's coloured. The old r*0.80/r*0.88
    # offsets did not enforce this: they gave the pupil a cap *behind* the
    # iris's for both the module's defaults and its own test values
    # (measured: 0 of ~330k raymarched hits ever resolved to the pupil).
    # Below, every offset is instead solved from
    #     offset_of_part_in_front = previous_cap + MARGIN - own_radius
    # so the next person changing a radius is working against a stated
    # clearance, not a render that happened to look right.
    #
    # MARGIN scales with r, and so does every offset (the old sclera offset
    # was the fixed distance `d*0.02` while iris/pupil scaled with r; a
    # caller doubling r got a socket and iris that doubled but a sclera
    # bulge that didn't move -- self-similarity broke exactly where a caller
    # was most likely to test it).
    MARGIN = 0.15 * r

    sclera_r = r * 0.92
    sclera_off = r * 0.22
    cap = sclera_off + sclera_r
    parts = [(sphere(sclera_r, tuple(c + d*sclera_off)),
              material(sclera, spec=0.35, shininess=60))]

    if iris > 0:
        cap += MARGIN
        iris_off = cap - iris          # cap == iris_off + iris, by construction
        parts.append((sphere(iris, tuple(c + d*iris_off)),
                      material(iris_color, spec=0.30, shininess=50)))

    # No iris to protrude past (the dot-eye fallback) leaves `cap` at the
    # sclera's, so the pupil clears the sclera directly instead.
    cap += MARGIN
    pupil_r = max(pupil, 1e-4)
    pupil_off = cap - pupil_r
    parts.append((sphere(pupil_r, tuple(c + d*pupil_off)),
                  material(pupil_color, spec=0.20, shininess=40)))

    decals = []
    if glint > 0:
        off = np.array([-0.35, 0.35, 0.0])
        gd = d + off
        decals.append((tuple(gd / (np.linalg.norm(gd) + 1e-9)),
                       math.degrees(glint*8), 0.7, glint_color))
    return Eye(socket, parts, decals)


def stroke(points, radius_deg=2.3, soft_deg=0.9, color=(0, 0, 0), samples=16):
    """A line of decals along a curve through `points`.

    A mouth used to be twenty hand-placed decal tuples in one asset's
    script; this samples the curve instead of asking a caller to place
    each dot itself.

    Piecewise-linear resampling on purpose: a caller that wants a bezier
    passes its own sampled points, and this stays the one thing it says it
    is. Directions are normalised because spots() measures the angle from
    the decal's direction to the surface point.
    """
    pts = np.array(points, float)
    if len(pts) < 2:
        raise ValueError("stroke needs at least two points")
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    want = np.linspace(0.0, cum[-1], samples)
    out = []
    for w in want:
        i = int(np.clip(np.searchsorted(cum, w) - 1, 0, len(seg) - 1))
        # A repeated point makes seg[i] == 0 (zero-length segment); t falls
        # back to 0 so p is just pts[i] instead of a 0/0 division.
        t = 0.0 if seg[i] == 0 else (w - cum[i]) / seg[i]
        p = pts[i] + (pts[i+1] - pts[i])*t
        out.append((tuple(p / (np.linalg.norm(p) + 1e-9)), radius_deg,
                    soft_deg, color))
    return out


def mirrored(fn):
    """Evaluate an SDF at |x|, so one definition gives both sides.

    Offered, not imposed: a caller wanting a symmetric face wraps a
    one-sided part once instead of writing it twice. But it is a helper,
    never a rule — one character in this project has ears at deliberately
    different depths, so the side view shows two of them instead of one
    perfectly overlapping spike. Symmetry is the asset's choice; nothing
    here should force it.
    """
    def f(p):
        q = np.stack([np.abs(p[..., 0]), p[..., 1], p[..., 2]], axis=-1)
        return fn(q)
    return f


def mirror_decals(decals):
    """The same decals on the other side of x."""
    return [((-d[0][0], d[0][1], d[0][2]),) + tuple(d[1:]) for d in decals]


def light_for(yaw, base_light=LIGHT):
    """Turn the light with the camera so it stays on the character's upper
    left in every view.

    A world-fixed light is physically right and useless here: at yaw 180 it
    falls entirely behind the object and the back view comes out flat
    ambient mush. Every other asset in a set is lit from the upper left, so
    rotating the light by the same yaw as the camera is what keeps a
    turnaround matching the rest of the set. This is the same rotation
    `render` applies to its camera basis (see sdf3d.render's `roty`), so the
    light stays fixed relative to the camera, not the object.
    """
    a = math.radians(yaw)
    c, s = math.cos(a), math.sin(a)
    lx, ly, lz = base_light
    return (c*lx + s*lz, ly, -s*lx + c*lz)


def turnaround(shape, views=VIEWS, light=None, **render_kw):
    """One shape, every named view, each lit to match the others.

    Consistency across views is by construction: it is the same object at a
    different camera yaw, not the same character drawn again. Does not touch
    `sdf3d.OVERSAMPLE` — a caller that wants a small/fast render sets that
    itself, the way `_small` does in the tests.
    """
    base = light if light is not None else LIGHT
    return {name: render(shape, yaw=yaw, light=light_for(yaw, base),
                         **render_kw)
            for name, yaw in views.items()}
