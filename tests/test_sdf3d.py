"""Renderer tests. Everything renders at OVERSAMPLE=1 and 32x32 — the point
is to pin behaviour, not to look at anything."""
from pathlib import Path

import numpy as np
from PIL import Image

import sdf3d
from sdf3d import flat, render, sphere, squash, torus_z, torus_y, scale_y
from sdf3d import material, surface, union
from sdf3d import ramp_bands, ramp_linear

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


def test_a_banded_render_has_flat_steps():
    """Cel shading is not a look this library picks — it is a ramp the asset
    hands in. What the renderer must guarantee is that the steps come out
    flat rather than smeared."""
    img = _small(sphere(0.7), color=flat((200, 200, 200)),
                 ramp=ramp_bands([0.35, 0.75]), ao=0.0, rim=0.0, spec=0.0)
    a = np.asarray(img).astype(int)
    lit = a[..., :3].max(axis=-1)[a[..., 3] > 250]
    assert len(np.unique(lit)) <= 4, np.unique(lit)
