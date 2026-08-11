"""Character helpers. Small renders only — these pin construction, not looks."""
import numpy as np

import sdf3d
from sdf3d import material, render, sphere, smooth_union, surface, union

from character_lib import eye


def _small(sdf, size=(48, 48), **kw):
    before = sdf3d.OVERSAMPLE
    sdf3d.OVERSAMPLE = 1
    try:
        return render(sdf, size=size, tilt=0, **kw)
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

    This test proves the three materials are distinct. It says nothing
    about whether any of them actually reaches a raymarched ray - a part
    sampled at its OWN apex resolves to itself whether or not the part is
    buried under the one in front of it. See
    test_the_pupil_actually_reaches_the_render for that half.
    """
    head = sphere(0.62)
    head_color = (190, 120, 90)
    r, iris_r, pupil_r = 0.22, 0.11, 0.055
    center = np.array([0.0, 0.05, 0.60])
    look = np.array([0.0, 0.05, 1.0])
    look = look / np.linalg.norm(look)
    e = eye(tuple(center), tuple(look), r=r, iris=iris_r, pupil=pupil_r)
    surf = surface([(head, material(head_color))] + e.parts)

    # eye()'s own front-apex offsets along `look`, mirroring its construction:
    # sclera radius r*0.92 at offset r*0.22; each part after it clears the
    # previous part's cap (offset + radius) by MARGIN = 0.15*r before its
    # own radius is subtracted back out. See character_lib.eye()'s own
    # comment for why this chain, not a fixed r*0.80/r*0.88, is what keeps
    # every part actually reachable.
    MARGIN = 0.15 * r
    sclera_off = r * 0.22
    sclera_cap = sclera_off + r * 0.92
    iris_off = sclera_cap + MARGIN - iris_r
    iris_cap = iris_off + iris_r
    pupil_off = iris_cap + MARGIN - pupil_r
    apexes = np.stack([
        center + look * sclera_cap,
        center + look * iris_cap,
        center + look * (pupil_off + pupil_r),
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


def test_the_pupil_actually_reaches_the_render():
    """Distinct-materials is not the same claim as visible: a part whose
    front cap (offset + its own radius, along `look`) never clears the cap
    of the part in front of it can carry its own material and still never
    win a single raymarched ray, because Surface picks whichever part's SDF
    reads nearest to zero AT THE SURFACE THE RAYMARCH ACTUALLY FOUND - not
    whichever part a test happens to sample.

    Measured, with the pre-fix offsets (r*0.80 iris, r*0.88 pupil) and
    instrumenting Surface.resolve during a real render: of ~330k raymarched
    hits, the pupil won exactly 0, for BOTH eye()'s own defaults and the
    r=0.22 values this file uses above - the pupil's cap sat behind the
    iris's cap by -0.0158 (defaults) and -0.0374 (r=0.22) world units, so it
    was fully swallowed regardless of its colour. This test renders the
    whole eye and looks for actual pixels of each material's colour, not an
    analytic point - it is the only kind of check that catches that."""
    head = sphere(0.62)
    head_color = (190, 120, 90)
    # Colours picked far apart in RGB space (not clustered near white, where
    # a specular highlight on ANY material can land) so nearest-colour
    # classification stays unambiguous after shading.
    sclera_c, iris_c, pupil_c = (230, 230, 235), (200, 60, 40), (20, 20, 160)
    # Larger than eye()'s own defaults: the pupil's world radius has to
    # clear roughly a pixel at this render size to land on any pixel centre
    # at all - a resolution limit of this 80x80 smoke test, not of eye().
    e = eye((0.0, 0.05, 0.60), (0.0, 0.05, 1.0), r=0.3, iris=0.15,
             pupil=0.075, sclera=sclera_c, iris_color=iris_c,
             pupil_color=pupil_c)
    shape = union(smooth_union(0.05, head, e.socket),
                  *[s for s, _ in e.parts])
    surf = surface([(head, material(head_color))] + e.parts)
    a = np.asarray(_small(shape, size=(80, 80), color=surf, ao=0.0, rim=0.0,
                          spec=0.0))
    inside = a[..., 3] > 250
    pixels = a[..., :3][inside].astype(float)
    refs = np.array([head_color, sclera_c, iris_c, pupil_c], float)
    nearest = np.linalg.norm(
        pixels[:, None, :] - refs[None, :, :], axis=-1).argmin(axis=-1)
    counts = {name: int((nearest == i).sum())
              for i, name in enumerate(["head", "sclera", "iris", "pupil"])}
    assert counts["sclera"] >= 5, counts
    assert counts["iris"] >= 5, counts
    assert counts["pupil"] >= 5, counts


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
