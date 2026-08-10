"""sdf3d - a tiny orthographic SDF raymarcher for soft-3D game sprites.

Use this when a sprite must read as a real 3D volume (jelly cubes, coins,
capsules, tilted views of a piece) - painted 2D layers plateau at "almost"
for these, because the reference's shading follows true geometry.

Design choices (deliberate, keep them):
- ORTHOGRAPHIC camera: sprites need no perspective distortion, and assets of
  one set stay proportionally comparable. The camera tilts around X only
  (looking slightly down), which is how casual-game pieces are shown.
- Sphere tracing on a vectorized numpy grid: fast enough at 2-3x supersample.
- Normals from central differences of the SDF.
- One global light per asset SET (a module-level constant you override once),
  Lambert diffuse + Blinn specular + normal-based fake AO + optional rim.
  Consistency across a set comes from sharing camera tilt + light, exactly
  like sharing a palette in 2D.
- Alpha = smooth hit coverage, so edges come out anti-aliased after the
  final downsample.

Everything returns PIL RGBA images at the requested final size.

Example - an orange jelly cube seen slightly from above:

    from sdf3d import *
    cube = rounded_box((0.62, 0.55, 0.62), 0.16)
    img = render(cube, size=(290, 328), tilt=18,
                 color=grade_y((255, 214, 90), (248, 166, 8), (215, 118, 0)),
                 spec=0.55, shininess=42)
"""
import math
import numpy as np
from PIL import Image

OVERSAMPLE = 3          # render at Nx, downsample once (Lanczos)
MAX_STEPS = 96
EPS = 1e-3
LIGHT = (-0.35, 0.75, 0.55)   # unit-ish, +y is UP in world space (top light)


# ------------------------------------------------------------ primitives
# All primitives are functions p(N,3) -> distance(N,). World units: the
# visible frame is roughly x,y in [-1, 1]. +y up, +z toward the camera.

def sphere(r, center=(0, 0, 0)):
    c = np.array(center, float)
    return lambda p: np.linalg.norm(p - c, axis=-1) - r


def rounded_box(half, r, center=(0, 0, 0)):
    b = np.array(half, float) - r
    c = np.array(center, float)
    def f(p):
        q = np.abs(p - c) - b
        outside = np.linalg.norm(np.maximum(q, 0), axis=-1)
        inside = np.minimum(q.max(axis=-1), 0)
        return outside + inside - r
    return f


def capsule(a, b, r):
    a, b = np.array(a, float), np.array(b, float)
    ab = b - a
    def f(p):
        t = np.clip(((p - a) @ ab) / (ab @ ab), 0, 1)
        return np.linalg.norm(p - (a + t[..., None] * ab), axis=-1) - r
    return f


def cylinder_y(r, h, center=(0, 0, 0), round_r=0.0):
    """Y-axis cylinder (a coin lying flat is cylinder_y with small h,
    viewed with tilt). round_r rounds the rim edge."""
    c = np.array(center, float)
    def f(p):
        q = p - c
        dxz = np.sqrt(q[..., 0]**2 + q[..., 2]**2) - (r - round_r)
        dy = np.abs(q[..., 1]) - (h - round_r)
        outside = np.sqrt(np.maximum(dxz, 0)**2 + np.maximum(dy, 0)**2)
        inside = np.minimum(np.maximum(dxz, dy), 0)
        return outside + inside - round_r
    return f


def torus_y(R, r, center=(0, 0, 0)):
    c = np.array(center, float)
    def f(p):
        q = p - c
        dxz = np.sqrt(q[..., 0]**2 + q[..., 2]**2) - R
        return np.sqrt(dxz**2 + q[..., 1]**2) - r
    return f


def torus_z(R, r, center=(0, 0, 0)):
    """Ring standing in the XY plane, facing the camera.

    torus_y lies flat and disappears at tilt=0, so an asset that needs a ring
    seen face-on — a septum ring, a hoop, a portal — cannot use it. This lived
    in one set's private copy of the library until it was moved here.
    """
    c = np.array(center, float)
    def f(p):
        q = p - c
        dxy = np.sqrt(q[..., 0]**2 + q[..., 1]**2) - R
        return np.sqrt(dxy**2 + q[..., 2]**2) - r
    return f


def squash(fn, sx, sy, sz):
    """Non-uniform scale of an SDF, Lipschitz-corrected by the smallest factor.

    Approximate, which is all a sprite needs: an ear has to be flat
    front-to-back like its reference's, and a capsule alone is a round stick.
    Two character scripts each defined their own copy of this before it was
    moved here.
    """
    inv = np.array([1.0 / sx, 1.0 / sy, 1.0 / sz])
    k = min(sx, sy, sz)
    return lambda p: fn(p * inv) * k


def scale_y(fn, s):
    """Squash/stretch a primitive along Y."""
    return squash(fn, 1.0, s, 1.0)


# ------------------------------------------------------------ combinators
def union(*fns):
    return lambda p: np.minimum.reduce([f(p) for f in fns])


def smooth_union(k, *fns):
    """Blobby merge - use for organic joins (body+ears). k ~ 0.05-0.2."""
    def f(p):
        d = fns[0](p)
        for g in fns[1:]:
            d2 = g(p)
            h = np.clip(0.5 + 0.5*(d2 - d)/k, 0, 1)
            d = d2 + (d - d2)*h - k*h*(1-h)
        return d
    return f


def subtract(a, b):
    return lambda p: np.maximum(a(p), -b(p))


def intersect(a, b):
    return lambda p: np.maximum(a(p), b(p))


# ------------------------------------------------------------ materials
def grade_y(top, mid, bottom, y0=0.6, y1=-0.6):
    """Color by world height: lighter top -> darker bottom, the standard
    top-lit toy look. Returns color(p, n) -> (N,3) float."""
    t_, m_, b_ = (np.array(c, float) for c in (top, mid, bottom))
    def color(p, n):
        t = np.clip((p[..., 1] - y1) / (y0 - y1), 0, 1)[..., None]
        hi = np.clip((t - 0.5)*2, 0, 1)
        lo = np.clip(t*2, 0, 1)
        return b_ + (m_ - b_)*lo + (hi)*(t_ - m_)
    return color


def flat(rgb):
    c = np.array(rgb, float)
    return lambda p, n: np.broadcast_to(c, p.shape[:-1] + (3,)).copy()


# -------------------------------------------------------------- ramps
def ramp_linear(ambient=0.42, diffuse=0.62):
    """The response this renderer has always had: ambient plus a linear
    diffuse term. It is the default so that adding the seam changes nothing."""
    return lambda lam: ambient + diffuse*lam


def ramp_bands(thresholds, ambient=0.42, diffuse=0.62):
    """Cel shading: N-L quantised at the given thresholds.

    The band count, the band widths and the endpoints are the ramp's, not the
    renderer's — that is how the technique is authored in practice, and
    burying a band count in code is precisely what takes it away from whoever
    is directing the look.
    """
    t = np.asarray(sorted(thresholds), float)
    if t.size == 0:
        return ramp_linear(ambient, diffuse)
    def f(lam):
        step = np.searchsorted(t, lam) / float(t.size)
        return ambient + diffuse*step
    return f


# ------------------------------------------------------------ renderer
def render(sdf, size=(256, 256), tilt=15, yaw=0.0, color=flat((240, 160, 20)),
           light=None, ambient=0.42, diffuse=0.62, spec=0.5, shininess=40,
           rim=0.10, ao=0.55, ao_radius=0.12, frame=1.15, bg_alpha=0,
           spec_color=(255, 255, 255), rim_color=(255, 255, 255), ramp=None):
    """Render an SDF to a final-size RGBA sprite.

    tilt: camera pitch in degrees (looking down when positive).
    frame: world half-width mapped to the image half-width - shrink to zoom.
    ao_radius: how far the AO taps reach along the normal, in world units.
    It is a parameter rather than a constant because the estimator is
    scale-dependent: the visible frame in this renderer is roughly
    x, y in [-1, 1], so a set working at a different scale needs a
    different radius.
    ramp: N-L -> shade multiplier. None builds ramp_linear(ambient, diffuse),
    so the two scalars keep working for a caller that never heard of ramps;
    a caller that passes its own ramp has taken responsibility for both.
    Everything else is standard Blinn-Phong with a fake AO term derived from
    how concave the neighborhood is (cheap, stable, good enough for sprites).
    """
    W, H = size
    w, h = W*OVERSAMPLE, H*OVERSAMPLE
    lx, ly, lz = light if light is not None else LIGHT
    ln = math.sqrt(lx*lx + ly*ly + lz*lz)
    L = np.array([lx/ln, ly/ln, lz/ln])

    # camera basis: orthographic, pitched around X by tilt, then turned
    # around Y by yaw (turntable - the way character turnarounds are shot)
    a = math.radians(tilt)
    fwd = np.array([0.0, -math.sin(a), -math.cos(a)])
    up = np.array([0.0, math.cos(a), -math.sin(a)])
    right = np.array([1.0, 0.0, 0.0])
    if yaw:
        b = math.radians(yaw)
        cb, sb = math.cos(b), math.sin(b)
        roty = np.array([[cb, 0, sb], [0, 1, 0], [-sb, 0, cb]])
        fwd, up, right = roty @ fwd, roty @ up, roty @ right

    xs = np.linspace(-frame, frame, w)
    ys = np.linspace(frame*H/W, -frame*H/W, h)
    gx, gy = np.meshgrid(xs, ys)
    origins = (gx[..., None]*right + gy[..., None]*up) - fwd*3.0
    origins = origins.reshape(-1, 3)
    d = fwd  # same direction for every ray (orthographic)

    t = np.zeros(origins.shape[0])
    alive = np.ones(origins.shape[0], bool)
    for _ in range(MAX_STEPS):
        if not alive.any():
            break
        p = origins[alive] + t[alive, None]*d
        dist = sdf(p)
        t[alive] += dist
        done = (dist < EPS) | (t[alive] > 8.0)
        idx = np.where(alive)[0]
        alive[idx[done]] = False

    hit = t < 8.0 - 1e-6
    p = origins + t[:, None]*d

    # normals by central differences (only where hit)
    n = np.zeros_like(p)
    if hit.any():
        ph = p[hit]
        e = 1.5e-3
        grads = []
        for i in range(3):
            o = np.zeros(3); o[i] = e
            grads.append(sdf(ph + o) - sdf(ph - o))
        g = np.stack(grads, axis=-1)
        g /= np.linalg.norm(g, axis=-1, keepdims=True) + 1e-9
        n[hit] = g

    shade = np.zeros((origins.shape[0], 3))
    if hit.any():
        ph, nh = p[hit], n[hit]
        rows = ph.shape[0]
        # A Surface carries its own spec/shininess/rim per hit point, gathered
        # from the nearest part; a plain colour function (every existing
        # asset) still gets the scene-wide scalars, broadcast into arrays so
        # the shading arithmetic below has one shape to work with either way.
        if isinstance(color, Surface):
            base, spec_a, shin_a, rim_a, scol_a, hard_a = color.resolve(ph, nh)
        else:
            base = color(ph, nh)
            spec_a = np.full(rows, float(spec))
            shin_a = np.full(rows, float(shininess))
            rim_a = np.full(rows, float(rim))
            scol_a = np.broadcast_to(np.array(spec_color, float), (rows, 3))
            hard_a = np.full(rows, np.nan)
        # rim_color stays a scene-wide parameter, not a per-material one:
        # Material.rim is intensity only, so its colour is this scalar for
        # every part, exactly like scol_a is for the scalar (non-Surface) path.
        rcol_a = np.broadcast_to(np.array(rim_color, float), (rows, 3))

        lam = np.clip(nh @ L, 0, 1)
        Hv = L + np.array([0, 0, 1.0]); Hv /= np.linalg.norm(Hv)
        sp = np.clip(nh @ Hv, 0, 1) ** shin_a
        # Five taps marched along the normal, Quilez's estimator: each sample
        # asks how much closer the surface is than the step that was taken,
        # which is exactly how concave the neighbourhood is. The single sample
        # this replaced could not tell a crease from a gentle curve.
        occ = np.zeros(ph.shape[0])
        sca = 1.0
        for i in range(1, 6):
            hstep = 0.01 + ao_radius * i / 5.0
            occ += (hstep - sdf(ph + nh*hstep)) * sca
            sca *= 0.95
        aoterm = np.clip(1.0 - 3.0*ao*occ, 0, 1)
        rimterm = rim_a * np.clip(1 - nh[:, 2], 0, 1)**2
        shade_t = (ramp or ramp_linear(ambient, diffuse))(lam)
        c = base*shade_t[:, None]*aoterm[:, None] \
            + scol_a*(spec_a*sp)[:, None] + rcol_a*rimterm[:, None]
        shade[hit] = np.clip(c, 0, 255)

    # smooth alpha from the miss distance at the surface (AA at silhouette)
    alpha = np.zeros(origins.shape[0])
    alpha[hit] = 255
    img = np.concatenate([shade, alpha[:, None]], axis=1)
    img = img.reshape(h, w, 4).astype(np.uint8)
    out = Image.fromarray(img, 'RGBA').resize((W, H), Image.LANCZOS)
    if bg_alpha:
        bgimg = Image.new('RGBA', (W, H), (128, 128, 128, 255))
        bgimg.alpha_composite(out)
        return bgimg
    return out


# ------------------------------------------ object-space materials (v4)
class Material:
    """A part's colour AND its surface. Splitting these was the ceiling: the
    old part_color varied colour alone, so bone, hide and metal came out of
    one render with the same gloss."""
    __slots__ = ("color", "spec", "shininess", "rim", "spec_color", "spec_hard")

    def __init__(self, color, spec, shininess, rim, spec_color, spec_hard):
        self.color = color
        self.spec = spec
        self.shininess = shininess
        self.rim = rim
        self.spec_color = spec_color
        self.spec_hard = spec_hard


def material(color, spec=0.5, shininess=40, rim=0.10,
             spec_color=(255, 255, 255), spec_hard=None):
    return Material(color, spec, shininess, rim, spec_color, spec_hard)


class Surface:
    """Materials keyed by nearest part.

    At each surface point the part whose SDF reads closest to zero wins. That
    is exact for a hard `union` and WRONG inside a `smooth_union` band, where
    the surface belongs to neither part — so blend softly only within one
    material, and hard-union anything that needs its own.
    """
    def __init__(self, parts):
        self.parts = list(parts)

    def resolve(self, p, n):
        ds = np.stack([np.abs(f(p)) for f, _ in self.parts], axis=-1)
        idx = ds.argmin(axis=-1)
        rows = p.shape[0]
        base = np.zeros((rows, 3))
        spec = np.zeros(rows)
        shin = np.zeros(rows)
        rim = np.zeros(rows)
        scol = np.zeros((rows, 3))
        hard = np.full(rows, np.nan)
        for i, (_, m) in enumerate(self.parts):
            msk = idx == i
            if not msk.any():
                continue
            c = m.color
            base[msk] = c(p[msk], n[msk]) if callable(c) else np.array(c, float)
            spec[msk] = m.spec
            shin[msk] = m.shininess
            rim[msk] = m.rim
            scol[msk] = np.array(m.spec_color, float)
            if m.spec_hard is not None:
                hard[msk] = m.spec_hard
        return base, spec, shin, rim, scol, hard

    def __call__(self, p, n):
        """Colour only, so a Surface can be the base of spots(): face decals
        paint over a body that already has materials."""
        return self.resolve(p, n)[0]


def surface(parts):
    return Surface(parts)


def spots(base, decals, center=(0, 0, 0)):
    """Face features as OBJECT-SPACE decals: they live on the surface and
    rotate/occlude correctly with camera yaw - never place features in
    screen space, that is exactly what breaks 3/4 and side views.

    decals = [(direction(3,), radius_deg, soft_deg, rgb), ...] where
    direction points from `center` to the feature (e.g. +z face, eyes at
    (+-0.28, 0.05, 1)). Later decals paint over earlier ones (glints last).
    """
    C = np.array(center, float)
    dd = [(np.array(d, float) / np.linalg.norm(d), r, s, np.array(c, float))
          for d, r, s, c in decals]
    def color(p, n):
        c = base(p, n) if callable(c := base) else np.broadcast_to(
            np.array(base, float), p.shape[:-1] + (3,)).copy()
        v = p - C
        v = v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9)
        for dv, rad, soft, rgb in dd:
            ang = np.degrees(np.arccos(np.clip(v @ dv, -1, 1)))
            w = np.clip((rad - ang) / max(soft, 1e-3), 0, 1)[..., None]
            c = c * (1 - w) + rgb * w
        return c
    return color
