"""Character helpers. Small renders only — these pin construction, not looks."""
import numpy as np

import sdf3d
from sdf3d import flat, material, render, sphere, smooth_union, surface, union

from character_lib import eye


def _small(sdf, **kw):
    before = sdf3d.OVERSAMPLE
    sdf3d.OVERSAMPLE = 1
    try:
        return render(sdf, size=(48, 48), tilt=0, **kw)
    finally:
        sdf3d.OVERSAMPLE = before


def test_an_eye_shows_sclera_iris_and_pupil_as_three_colours():
    """A single dark shape is what the old face decals gave, and it reads as
    part of the brow rather than as an eye. Three distinct materials are the
    difference.

    Counting distinct rendered colour BANDS does not measure that: Lambert
    shading alone spreads one flat-lit sphere's own surface across a
    dozen-plus buckets at this render size (measured: a lone sphere, one
    material, default light -> 13 buckets of width 40 - so `>= 3 buckets`
    is true before eye() draws anything). Classifying by nearest-of-4-known
    colours is not much safer either: a specular highlight on the dark iris
    or pupil can put a handful of near-white pixels on a material that has
    no white in it at all (measured: recolouring the sclera to the head's
    own tone still left 6 pixels classified "sclera", from iris/pupil
    highlight glare - almost the true sclera's own 28). Sampling the exact
    front-apex point eye() places each part's sphere at, and resolving
    Surface's nearest-part material THERE, is exact and immune to both.
    """
    head = sphere(0.62)
    head_color = (190, 120, 90)
    r, iris_r, pupil_r = 0.22, 0.11, 0.055
    center = np.array([0.0, 0.05, 0.60])
    look = np.array([0.0, 0.05, 1.0])
    look = look / np.linalg.norm(look)
    e = eye(tuple(center), tuple(look), r=r, iris=iris_r, pupil=pupil_r)
    surf = surface([(head, material(head_color))] + e.parts)

    # eye()'s own front-apex offsets along `look`, in construction order:
    # sclera centre +0.02 radius r*0.92; iris centre r*0.80 radius iris;
    # pupil centre r*0.88 radius pupil.
    apexes = np.stack([
        center + look * (0.02 + r * 0.92),
        center + look * (r * 0.80 + iris_r),
        center + look * (r * 0.88 + pupil_r),
    ])
    base, *_ = surf.resolve(apexes, np.broadcast_to(look, apexes.shape))
    sclera, iris, pupil = (tuple(row) for row in base)

    assert len({sclera, iris, pupil}) == 3, (sclera, iris, pupil)
    assert sclera != head_color, "sclera must not read as the head's colour"

    # Smoke check: the whole union/smooth_union assembly still has to render
    # something visible at this size, not just resolve correctly in theory.
    shape = union(smooth_union(0.05, head, e.socket),
                  *[s for s, _ in e.parts])
    a = np.asarray(_small(shape, color=surf, ao=0.0, rim=0.0, spec=0.0))
    assert (a[..., 3] > 250).any()


def test_the_socket_carries_no_material_of_its_own():
    """It is smooth-unioned into the head, so it sits inside the blend band
    where a nearest-part material select is simply wrong. It shares the
    head's material by having none."""
    e = eye((0.0, 0.0, 0.6), (0.0, 0.0, 1.0))
    ids = [s for s, _ in e.parts]
    assert e.socket not in ids


def test_a_glint_is_a_decal_not_geometry():
    e = eye((0.0, 0.0, 0.6), (0.0, 0.0, 1.0))
    assert len(e.decals) == 1
    assert len(e.parts) == 3            # sclera, iris, pupil


def test_zeroed_parameters_give_a_plain_dot_eye():
    """The library must not insist on a cartoon eye — a dot is a legitimate
    style and comes from the same call."""
    e = eye((0.0, 0.0, 0.6), (0.0, 0.0, 1.0), iris=0.0, glint=0.0)
    assert len(e.parts) == 2            # sclera and pupil only
    assert e.decals == []
