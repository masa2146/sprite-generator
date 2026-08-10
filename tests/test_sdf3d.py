"""Renderer tests. Everything renders at OVERSAMPLE=1 and 32x32 — the point
is to pin behaviour, not to look at anything."""
from pathlib import Path

import numpy as np
from PIL import Image

import sdf3d
from sdf3d import flat, render, sphere, squash, torus_z, torus_y, scale_y
from sdf3d import material, surface, union, rounded_box
from sdf3d import ramp_bands, ramp_linear
from sdf3d import interior_edges

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _small(sdf, **kw):
    """A render small enough to run in a test. OVERSAMPLE is module state, so
    it is set and restored around every call rather than left mutated."""
    before = sdf3d.OVERSAMPLE
    sdf3d.OVERSAMPLE = 1
    try:
        return render(sdf, size=(32, 32), tilt=15, **kw)
    finally:
        sdf3d.OVERSAMPLE = before


def test_the_soft_path_still_renders_exactly_as_it_did():
    """The golden was captured from the renderer as it stood before any of
    this work, with ao and rim off: those two terms are the ones this plan
    deliberately changes, and pinning them would pin the wrong thing. What
    this test protects is the diffuse and specular path — the default ramp
    must reproduce it arithmetic-for-arithmetic."""
    got = _small(sphere(0.7), color=flat((240, 160, 20)), ao=0.0, rim=0.0)
    want = Image.open(FIXTURES / "golden_soft_sphere.png")
    assert np.array_equal(np.asarray(got), np.asarray(want))


def test_torus_z_stands_in_the_xy_plane():
    """torus_y lies flat and vanishes at tilt=0, which is why a set that
    needed a ring standing towards the camera grew its own torus_z rather
    than using the library."""
    ring = torus_z(0.5, 0.1)
    p = np.array([[0.5, 0.0, 0.0], [0.0, 0.5, 0.0], [0.0, 0.0, 0.5]])
    d = ring(p)
    assert abs(d[0] + 0.1) < 1e-6, d       # on the ring, x axis
    assert abs(d[1] + 0.1) < 1e-6, d       # on the ring, y axis
    assert d[2] > 0.3, d                   # z axis is off the ring entirely


def test_squash_scales_each_axis():
    s = squash(sphere(1.0), 2.0, 1.0, 1.0)
    p = np.array([[2.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    d = s(p)
    assert abs(d[0]) < 1e-6, d             # stretched to x=2
    assert abs(d[1]) < 1e-6, d             # untouched on y


def test_scale_y_still_works_through_squash():
    a = scale_y(sphere(1.0), 2.0)
    p = np.array([[0.0, 2.0, 0.0]])
    assert abs(a(p)[0]) < 1e-6, a(p)


def _two_balls(left_mat, right_mat):
    l = sphere(0.42, (-0.45, 0.0, 0.0))
    r = sphere(0.42, (0.45, 0.0, 0.0))
    return union(l, r), surface([(l, left_mat), (r, right_mat)])


def test_each_part_keeps_its_own_colour():
    shape, surf = _two_balls(material((220, 40, 40)), material((40, 80, 220)))
    a = np.asarray(_small(shape, color=surf, ao=0.0, rim=0.0)).astype(int)
    left = a[16, 6, :3]
    right = a[16, 25, :3]
    assert left[0] > left[2] + 60, left
    assert right[2] > right[0] + 60, right


def test_each_part_keeps_its_own_specular():
    """This is the one part_color could not do: it varied colour only, so a
    gold ring came out with the same gloss as the stone it hung on."""
    dull = material((200, 200, 200), spec=0.0, shininess=40)
    shiny = material((200, 200, 200), spec=1.0, shininess=40)
    shape, surf = _two_balls(dull, shiny)
    a = np.asarray(_small(shape, color=surf, ao=0.0, rim=0.0)).astype(int)
    lit = a[..., :3].max(axis=-1)
    assert lit[:, 16:].max() > lit[:, :16].max() + 25, (
        lit[:, :16].max(), lit[:, 16:].max())


def test_a_plain_colour_function_still_renders():
    """The single-material call is what every existing asset makes."""
    img = _small(sphere(0.7), color=flat((240, 160, 20)), ao=0.0, rim=0.0)
    assert img.mode == "RGBA" and img.size == (32, 32)


def test_part_color_is_gone():
    assert not hasattr(sdf3d, "part_color")


def test_a_surface_can_be_the_base_of_a_decal_stack():
    """spots() calls its base as base(p, n). Face decals paint over a body
    that already has materials, so a Surface has to answer that call with its
    colour."""
    from sdf3d import spots
    _, surf = _two_balls(material((220, 40, 40)), material((40, 80, 220)))
    painted = spots(surf, [((0.0, 0.0, 1.0), 40.0, 2.0, (10, 240, 10))],
                    center=(0.45, 0.0, 0.0))
    a = np.asarray(_small(sphere(0.42, (0.45, 0.0, 0.0)), color=painted,
                          ao=0.0, rim=0.0)).astype(int)
    green = ((a[..., 1] > 180) & (a[..., 0] < 120) & (a[..., 3] > 250)).sum()
    assert green > 0, "the decal never reached the surface"


def test_ao_darkens_a_crease_more_than_a_flat_face():
    """Two spheres pushed into each other make a crease along the seam. With
    ao off the seam shades like everything else; with ao on it has to go
    darker, which is what makes parts read as joined rather than stacked."""
    a = sphere(0.45, (-0.28, 0.0, 0.0))
    b = sphere(0.45, (0.28, 0.0, 0.0))
    shape = union(a, b)
    off = np.asarray(_small(shape, color=flat((200, 200, 200)), ao=0.0,
                            rim=0.0)).astype(int)
    on = np.asarray(_small(shape, color=flat((200, 200, 200)), ao=0.8,
                           rim=0.0)).astype(int)
    seam_off = off[16, 16, :3].mean()
    seam_on = on[16, 16, :3].mean()
    # Column 10 is the same scanline as the seam but sits on one sphere's
    # flat, well-lit cap, clear of both the crease and the silhouette's
    # grazing rim (column 4 on this 32x32 render falls outside the merged
    # spheres' ~[-0.73, 0.73] silhouette entirely and is a background miss,
    # unrelated to the AO term either estimator computes).
    edge_on = on[16, 10, :3].mean()
    assert seam_on < seam_off - 12, (seam_on, seam_off)
    assert seam_on < edge_on, (seam_on, edge_on)


def test_the_default_ramp_is_the_old_arithmetic():
    lam = np.linspace(0, 1, 9)
    assert np.allclose(ramp_linear()(lam), 0.42 + 0.62*lam)


def test_bands_quantise_the_response():
    lam = np.linspace(0, 1, 101)
    out = ramp_bands([0.35, 0.75])(lam)
    assert len(np.unique(np.round(out, 6))) == 3, np.unique(out)


def test_an_empty_band_list_is_the_linear_ramp():
    lam = np.linspace(0, 1, 9)
    assert np.allclose(ramp_bands([])(lam), ramp_linear()(lam))


# shininess=20 -> exponent 400 (one of the two source values the brief
# cites). At the module's default light the highlight lands on a single
# pixel at this resolution - too small to compare "how many distinct
# brightness levels" against. This light instead sits close to the view
# axis (0, 0, 1), which widens the highlight to ~100 px at 32x32 while
# still leaving a genuine unlit region elsewhere on the silhouette (two
# hit pixels measured with raw N.L <= 0). spec_hard=0.2 was checked against
# the measured peak of the gated term for this light (~0.79) and the floor
# for a broken (never-fires) gate (~1e-260 at the true shadow pixels used
# below) - it sits far from both.
_HARD_SPEC_LIGHT = (-0.15, 0.15, 1.0)


def test_a_hard_specular_has_a_crisp_edge():
    """A soft highlight fades over many values; a cel one is a flat patch of
    one colour with an anti-aliased boundary. Comparing distinct brightnesses
    only means something where the soft highlight actually contributes
    (soft - spec=0 > 3) - measured at 96 of 1024 pixels for this light/
    material. Inside that footprint the hard render must both show markedly
    fewer levels than the soft one AND still read brighter than spec=0 -
    otherwise "fewer levels" could pass simply because the highlight
    vanished entirely, which is a different bug this test must not miss."""
    soft = surface([(sphere(0.7), material((120, 120, 120), spec=1.0,
                                           shininess=20))])
    hard = surface([(sphere(0.7), material((120, 120, 120), spec=1.0,
                                           shininess=20, spec_hard=0.2))])
    nospec = surface([(sphere(0.7), material((120, 120, 120), spec=0.0,
                                             shininess=20))])
    s = np.asarray(_small(sphere(0.7), color=soft, ao=0.0, rim=0.0,
                          light=_HARD_SPEC_LIGHT)).astype(int)
    h = np.asarray(_small(sphere(0.7), color=hard, ao=0.0, rim=0.0,
                          light=_HARD_SPEC_LIGHT)).astype(int)
    b = np.asarray(_small(sphere(0.7), color=nospec, ao=0.0, rim=0.0,
                          light=_HARD_SPEC_LIGHT)).astype(int)
    region = (s[..., 0].astype(int) - b[..., 0].astype(int)) > 3
    assert region.sum() > 20, "the soft highlight's own footprint vanished"
    hard_levels = len(np.unique(h[..., 0][region]))
    soft_levels = len(np.unique(s[..., 0][region]))
    assert hard_levels < soft_levels, (hard_levels, soft_levels)
    assert h[..., 0][region].max() > b[..., 0][region].max(), (
        h[..., 0][region].max(), b[..., 0][region].max())


def test_a_hard_specular_is_bit_identical_to_spec_zero_in_shadow():
    """Not a test of where the gate multiplies - once it's binarised,
    `(ndh * lit) ** n` and `(ndh ** n) * lit` agree everywhere except a
    hairline seam where `ndh` is already ~0, so no render-level test can
    tell the two placements apart (see the comment beside the gate in
    sdf3d.py). What this guarantees instead, and what callers actually rely
    on: the shadowed side renders with NO specular contribution at all,
    not a dim one. (18, 15) sits inside the highlight patch; (8, 21) is one
    of the two hit pixels on this render with a genuinely negative N.L (not
    merely dim) - the true shadowed side, which must come out bit-for-bit
    identical to a spec=0 render of the same material, not just "under some
    brightness"."""
    hard = surface([(sphere(0.7), material((120, 120, 120), spec=1.0,
                                           shininess=20, spec_hard=0.2))])
    nospec = surface([(sphere(0.7), material((120, 120, 120), spec=0.0,
                                             shininess=20))])
    h = np.asarray(_small(sphere(0.7), color=hard, ao=0.0, rim=0.0,
                          light=_HARD_SPEC_LIGHT)).astype(int)
    b = np.asarray(_small(sphere(0.7), color=nospec, ao=0.0, rim=0.0,
                          light=_HARD_SPEC_LIGHT)).astype(int)
    assert h[18, 15, 0] > b[18, 15, 0] + 100, (h[18, 15, 0], b[18, 15, 0])
    assert np.array_equal(h[8, 21], b[8, 21]), (h[8, 21], b[8, 21])


def test_contact_shadow_darkens_what_sits_under_an_overhang():
    """A ball resting on a slab: with the shadow on, the slab right beneath
    the ball has to go darker than the slab far from it."""
    slab = rounded_box((0.8, 0.06, 0.5), 0.03, (0.0, -0.45, 0.0))
    ball = sphere(0.30, (0.0, -0.10, 0.0))
    shape = union(slab, ball)
    kw = dict(color=flat((200, 200, 200)), ao=0.0, rim=0.0, spec=0.0,
              light=(0.0, 1.0, 0.25))
    off = np.asarray(_small(shape, **kw)).astype(int)
    on = np.asarray(_small(shape, shadow=True, **kw)).astype(int)
    # row 21, col 16 traced by hand: hit point (0.037, -0.389, 0.123),
    # normal (0, 1, 0) exactly - the slab's flat top, directly under the
    # ball's centre (x=0), well within its z=0.3 radius. col 6 on the same
    # row is (-0.705, -0.389, 0.123), same flat normal, outside the ball's
    # footprint - both on-silhouette (alpha 255), neither a background miss.
    row = 21
    under = on[row, 16, :3].mean()
    away = on[row, 6, :3].mean()
    assert under < away - 10, (under, away)
    assert under < off[row, 16, :3].mean() - 10


def test_the_shadow_costs_nothing_when_it_is_off():
    """Off must mean the second march never runs, not that it runs and is
    discarded — the renderer already takes minutes at full size."""
    kw = dict(color=flat((200, 200, 200)), ao=0.0, rim=0.0)
    a = np.asarray(_small(sphere(0.7), **kw))
    b = np.asarray(_small(sphere(0.7), shadow=False, **kw))
    assert np.array_equal(a, b)


def test_buffers_come_back_at_the_final_size():
    img, depth, normal = _small(sphere(0.7), color=flat((200, 200, 200)),
                                buffers=True)
    assert img.size == (32, 32)
    assert depth.shape == (32, 32)
    assert normal.shape == (32, 32, 3)
    assert np.isinf(depth[0, 0])           # a corner ray misses


def test_interior_edges_handles_an_all_miss_buffer():
    """A crop with nothing in it (every ray misses) is a legitimate input -
    an empty part, a box that rendered off-frame - not a caller error. It
    must come back as an empty mask, not crash np.nanmax reducing over zero
    elements."""
    depth = np.full((8, 8), np.inf)
    normal = np.zeros((8, 8, 3))
    edges = np.asarray(interior_edges(depth, normal))
    assert edges.shape == (8, 8)
    assert edges.max() == 0


def _dilate4(mask):
    """4-neighbour dilation - the ring one pixel around `mask`, itself
    excluded. Plain numpy, no scipy: this project's only dependencies are
    pillow and numpy."""
    d = np.zeros_like(mask)
    d[1:, :] |= mask[:-1, :]
    d[:-1, :] |= mask[1:, :]
    d[:, 1:] |= mask[:, :-1]
    d[:, :-1] |= mask[:, 1:]
    return d


def test_an_interior_edge_appears_where_two_parts_cross():
    """The alpha contour can only draw the outside. Where an arm crosses a
    body — or a horn crosses a skull — the line has to come from the depth
    and normal buffers, which the renderer already computes and used to
    throw away.

    A bare `edges.max() == 255` does not prove this: a lone curved sphere at
    this render size already marks most of its own silhouette as "edge" -
    ordinary curvature crosses normal_eps almost everywhere at 32x32 (see
    interior_edges's docstring) - so that assertion passed even with only
    one part. This compares against a control instead. `front` is a small
    sphere placed entirely inside the silhouette of the much larger `back`
    sphere, so `ring` - the pixels touching front's own silhouette from
    just outside it - is unambiguously the seam: it is exactly where back
    is revealed from behind front, nowhere else. `edges_f`, the control,
    covers only front's own footprint (it has no data outside it, by
    construction), so it can never mark anything in `ring` - which is what
    makes `diff & ring` a clean read on the crossing alone, not on back's
    own curvature elsewhere in the frame.
    """
    front = sphere(0.2, (0.0, 0.0, 0.6))
    back = sphere(0.65, (0.0, 0.0, -0.3))

    img_f, depth_f, normal_f = _small(front, color=flat((200, 200, 200)),
                                      buffers=True)
    alpha_f = np.asarray(img_f)[..., 3] > 0
    edges_f = np.asarray(interior_edges(depth_f, normal_f)) == 255  # control
    ring = _dilate4(alpha_f) & ~alpha_f

    _, depth_u, normal_u = _small(union(front, back),
                                  color=flat((200, 200, 200)), buffers=True)
    edges_u = np.asarray(interior_edges(depth_u, normal_u)) == 255

    diff = edges_u & ~edges_f
    assert (diff & ring).any(), "no edge in the ring where back is revealed"


def test_a_banded_render_has_flat_steps():
    """Cel shading is not a look this library picks — it is a ramp the asset
    hands in. What the renderer must guarantee is that the steps come out
    flat rather than smeared."""
    img = _small(sphere(0.7), color=flat((200, 200, 200)),
                 ramp=ramp_bands([0.35, 0.75]), ao=0.0, rim=0.0, spec=0.0)
    a = np.asarray(img).astype(int)
    lit = a[..., :3].max(axis=-1)[a[..., 3] > 250]
    assert len(np.unique(lit)) <= 4, np.unique(lit)
