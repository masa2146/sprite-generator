"""Renderer tests. Everything renders at OVERSAMPLE=1 and 32x32 — the point
is to pin behaviour, not to look at anything."""
from pathlib import Path

import numpy as np
from PIL import Image

import sdf3d
from sdf3d import flat, render, sphere, squash, torus_z, torus_y, scale_y
from sdf3d import material, surface, union

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
