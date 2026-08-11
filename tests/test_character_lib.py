"""Character helpers. Small renders only — these pin construction, not looks."""
import numpy as np

import sdf3d
from sdf3d import flat, material, render, sphere, smooth_union, surface, union

from character_lib import VIEWS, eye, light_for, mirror_decals, mirrored, stroke, turnaround
import demo_character


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


def test_a_stroke_samples_the_curve_into_decals():
    """A mouth used to be twenty hand-written decal tuples in the asset."""
    pts = [(0.0, -0.2, 1.0), (0.2, -0.4, 1.0), (0.4, -0.2, 1.0)]
    out = stroke(pts, samples=12)
    assert len(out) == 12
    assert all(len(d) == 4 for d in out)
    first = np.array(out[0][0])
    assert abs(np.linalg.norm(first) - 1.0) < 1e-6   # directions are unit


def test_stroke_directions_follow_the_curve_not_cluster_at_one_end():
    """Unit-length alone is true for ANY direction, including twelve copies
    of the same one — it would pass even if stroke sampled only points[0].
    This pins that the samples actually spread along the curve: the first,
    middle and last directions of a bent path must differ from each other,
    not just each be a unit vector."""
    pts = [(0.0, -0.3, 1.0), (0.3, 0.0, 1.0), (0.0, 0.3, 1.0)]
    out = stroke(pts, samples=9)
    dirs = np.array([d[0] for d in out])
    first, mid, last = dirs[0], dirs[len(dirs) // 2], dirs[-1]
    assert np.linalg.norm(first - last) > 0.2
    assert np.linalg.norm(mid - first) > 0.05
    assert np.linalg.norm(mid - last) > 0.05


def test_stroke_accepts_the_minimum_of_two_points():
    """Two points is the smallest input stroke() must NOT raise on (below
    that, test_stroke_rejects_a_single_point covers the ValueError). With
    only one segment, `i` is clipped into the single-element range [0, 0] —
    every other branch here is the same code the 3-point tests already
    exercise, so this only pins the boundary of the length check itself."""
    out = stroke([(0.0, 0.0, 1.0), (0.3, 0.0, 1.0)], samples=5)
    assert len(out) == 5
    assert all(np.all(np.isfinite(d[0])) for d in out)


def test_stroke_samples_are_weighted_by_arc_length_not_by_point_index():
    """Equally-spaced control points cannot tell arc-length sampling from
    sampling evenly per segment index -- both parameterisations give the
    same output, which is exactly why the tests above (all equally spaced)
    cannot see this. This fixture has one long segment and one short one,
    so the two parameterisations diverge: arc-length sampling puts most
    samples on the long segment, while per-index sampling would give the
    short segment an equal share regardless of its real length -- the
    "decals bunching wherever the control points happen to be dense" bug
    the brief named `stroke` to prevent.
    """
    pts = [(0.0, -0.5, 1.0), (0.5, -0.5, 1.0), (0.5, -0.45, 1.0)]
    p0, p1, p2 = (np.array(p) for p in pts)
    long_len = np.linalg.norm(p1 - p0)
    short_len = np.linalg.norm(p2 - p1)
    assert long_len > 8 * short_len, "fixture must be genuinely uneven"

    def unit(v):
        return v / np.linalg.norm(v)

    # Progress of a sampled direction along the chord from start to end, in
    # the space stroke's output actually lives in (normalised directions) --
    # a coordinate-free way to tell which segment a sample fell on without
    # stroke exposing its internal `t`.
    u0, u2 = unit(p0), unit(p2)
    axis = u2 - u0
    axis = axis / np.linalg.norm(axis)
    boundary = np.dot(unit(p1) - u0, axis)

    out = stroke(pts, samples=13)
    prog = np.array([np.dot(np.array(d[0]) - u0, axis) for d in out])
    on_long = int((prog < boundary).sum())
    on_short = int((prog >= boundary).sum())
    assert on_long > on_short, (on_long, on_short)


def test_stroke_samples_from_the_first_point_toward_the_last():
    """Reversing the sample order (first decal at the curve's END instead
    of its start) passes every other stroke test here -- spots() only uses
    list order for paint-over precedence, but the brief named ordering
    alongside clustering, so it needs its own pin."""
    pts = [(0.0, -0.3, 1.0), (0.3, 0.0, 1.0), (0.0, 0.3, 1.0)]
    out = stroke(pts, samples=9)
    first, last = np.array(out[0][0]), np.array(out[-1][0])
    start = np.array(pts[0]); start = start / np.linalg.norm(start)
    end = np.array(pts[-1]); end = end / np.linalg.norm(end)
    assert np.linalg.norm(first - start) < np.linalg.norm(first - end)
    assert np.linalg.norm(last - end) < np.linalg.norm(last - start)


def test_stroke_handles_a_repeated_point_without_dividing_by_zero():
    """A zero-length first segment (seg[i] == 0) must not produce a NaN
    direction — the caller may pass a repeated anchor point on purpose,
    e.g. to hold the curve still at a corner."""
    pts = [(0.0, 0.0, 1.0), (0.0, 0.0, 1.0), (0.3, 0.0, 1.0)]
    out = stroke(pts, samples=6)
    assert len(out) == 6
    assert all(np.all(np.isfinite(d[0])) for d in out)


def test_stroke_rejects_a_single_point():
    try:
        stroke([(0.0, 0.0, 1.0)])
        assert False, "stroke must refuse fewer than two points"
    except ValueError:
        pass


def test_mirrored_evaluates_at_the_absolute_x():
    """mirrored's job is to fold -x onto +x before evaluating — that only
    means anything if the raw shape actually differs between +x and -x, so
    this pins the fixture's asymmetry before trusting the after-mirroring
    equality below."""
    base = sphere(0.2, (0.5, 0.0, 0.0))
    p = np.array([[0.5, 0.0, 0.0], [-0.5, 0.0, 0.0]])
    raw = base(p)
    assert abs(raw[0] - raw[1]) > 0.5, "fixture must be asymmetric about x"

    f = mirrored(base)
    d = f(p)
    assert abs(d[0] - d[1]) < 1e-9


def test_mirror_decals_flips_x_and_keeps_the_rest():
    src = [((0.3, 0.1, 0.9), 8.0, 1.0, (10, 20, 30))]
    out = mirror_decals(src)
    assert out[0][0][0] == -0.3
    assert out[0][1:] == src[0][1:]


def test_the_light_turns_with_the_camera():
    """A world-fixed light is physically right and useless here: at yaw 180
    it falls entirely behind the object and the back view comes out flat
    ambient mush."""
    base = (-0.35, 0.75, 0.55)
    assert light_for(0, base) == base
    turned = light_for(180, base)
    assert abs(turned[0] + base[0]) < 1e-9
    assert abs(turned[1] - base[1]) < 1e-9


def test_a_turnaround_renders_every_named_view():
    out = turnaround(sphere(0.6), views={"front": 0, "side": 82},
                     size=(24, 24), color=flat((200, 160, 40)), ao=0.0)
    assert set(out) == {"front", "side"}
    assert all(im.size == (24, 24) for im in out.values())


def _brightest_opaque(im, cols):
    """Sum of RGB, restricted to fully-opaque pixels only, over a column
    slice.

    A plain `rgb.sum()` picks up Lanczos ringing at the silhouette's
    semi-transparent edge: `render`'s downsample can overshoot a colour
    channel to 255 at an alpha~1 rim pixel that carries almost no real
    coverage (measured: alpha=1 pixel valued (255,255,255) at a sphere's
    edge). That ringing sits on both halves regardless of where the light
    is, so it drowns the actual shading signal below and left==right on
    every view even for a correctly-rotated light. Masking to alpha==255
    (fully covered, no rim) leaves only real shaded surface behind.
    """
    a = np.asarray(im)
    rgb = a[..., :3].astype(int).sum(axis=-1)
    opaque = a[..., 3] == 255
    return np.where(opaque[:, cols], rgb[:, cols], -1).max()


def test_every_view_is_lit_from_the_same_side_of_the_character():
    """The measurable version of the rule: the lit half stays the lit half."""
    out = turnaround(sphere(0.6), views=VIEWS, size=(32, 32),
                     color=flat((200, 200, 200)), ao=0.0, rim=0.0, spec=0.0)
    for name, im in out.items():
        left = _brightest_opaque(im, slice(0, 16))
        right = _brightest_opaque(im, slice(16, 32))
        assert left > right, (name, left, right)


def test_an_expression_is_a_dict_the_asset_merges():
    """No rig and no class hierarchy: the library takes numbers, and an
    expression is the dict of numbers you hand it."""
    assert demo_character.ANGRY["brow"] != demo_character.FACE["brow"]
    assert set(demo_character.ANGRY) == set(demo_character.FACE)


def test_the_two_expressions_render_differently():
    """A bare `not array_equal` would pass for almost any unrelated change —
    a recolour, a rounding tweak anywhere in the render path — so it would
    not fail if `build()` stopped reading `expr["brow"]`/`expr["mouth"]` at
    all and just drew a fixed face. Render large enough that the decals
    cover more than a handful of pixels (at 48x48/OVERSAMPLE=1 the eye task
    found a decal can cover ZERO — see the pupil finding), then check two
    more specific things instead: the rows that differ stay confined to the
    face (not the whole frame, which is what a global-recolour bug would
    produce), and the opaque pixel COUNT (the silhouette) is untouched —
    decals paint over an existing body, they do not resize the head.

    Measured at size (160, 160) before picking the bounds below: the diff
    rows run 37..120 (a first guess of `< 0.75*160 == 120` failed on that
    exact boundary — not a code bug, see the task report) and silhouette
    coverage is 5932 opaque pixels for BOTH expressions, an exact 0 delta.
    The bounds here keep margin around those measured numbers so a real
    face-decal regression trips them without the test being pixel-exact.
    """
    calm = np.asarray(demo_character.render_one(demo_character.FACE, yaw=0,
                                                  size=(160, 160)))
    angry = np.asarray(demo_character.render_one(demo_character.ANGRY, yaw=0,
                                                   size=(160, 160)))
    assert not np.array_equal(calm, angry)

    diff_rows = np.where(np.any(calm != angry, axis=(1, 2)))[0]
    assert diff_rows.size > 0, "the two expressions must draw different pixels"
    assert 15 < diff_rows.min() and diff_rows.max() < 140, (
        "the difference must stay confined to the face (brow/mouth/eye "
        "decals and geometry), not spread to the top of the head or the "
        "bottom of the frame", diff_rows.min(), diff_rows.max())

    calm_cov = int((calm[..., 3] > 200).sum())
    angry_cov = int((angry[..., 3] > 200).sum())
    assert abs(calm_cov - angry_cov) <= 10, (
        "the silhouette (head outline) must stay put — only the face "
        "decals should move", calm_cov, angry_cov)


def test_the_brow_expression_param_moves_the_brow_decal():
    """Pinpoint check, independent of the pixel test above: FACE and ANGRY
    also differ in `mouth` and `eye_open`, so a render-level diff cannot
    tell a `brow` regression apart from those two still working — a bug
    that dropped `expr["brow"]` from the brow stroke entirely would still
    leave the render test above green. This calls build() directly and
    reads the BROW decals' own directions, sliced out by the composition
    order build() documents (`decals = mouth + brow + mirror_decals(brow) +
    left.decals + right.decals`) using the mouth/brow strokes' own
    `samples=` counts from build()'s source.
    """
    n_mouth, n_brow = 14, 8   # build()'s own stroke(..., samples=...) counts
    _, _, calm = demo_character.build(demo_character.FACE)
    _, _, angry = demo_character.build(demo_character.ANGRY)
    calm_brow = np.array([d[0] for d in calm[n_mouth:n_mouth + n_brow]])
    angry_brow = np.array([d[0] for d in angry[n_mouth:n_mouth + n_brow]])
    assert not np.allclose(calm_brow, angry_brow), "the brow decals must move"


def test_the_mouth_expression_param_moves_the_mouth_decal():
    """Same shape as the brow pinpoint test, same reason: FACE and ANGRY
    also differ in `brow` and `eye_open`, so neither the render-level test
    nor the brow test above would catch a bug that dropped `expr["mouth"]`
    from the mouth stroke. build()'s mouth points reference `expr["mouth"]`
    alone (not `brow` or `eye_open`), so reading just the mouth decals'
    directions isolates it — the mouth stroke is the first one built
    (`decals = mouth + brow + ...`), so its `samples=14` decals are
    `calm[:14]`.
    """
    n_mouth = 14   # build()'s own stroke(..., samples=14) for the mouth
    _, _, calm = demo_character.build(demo_character.FACE)
    _, _, angry = demo_character.build(demo_character.ANGRY)
    calm_mouth = np.array([d[0] for d in calm[:n_mouth]])
    angry_mouth = np.array([d[0] for d in angry[:n_mouth]])
    assert not np.allclose(calm_mouth, angry_mouth), "the mouth decals must move"


def test_the_eye_open_expression_param_changes_the_eye_radius():
    """Same shape again, for `eye_open`: neither the render test nor the
    two decal tests above would catch a bug that hardcoded `r` in build()
    instead of reading `expr["eye_open"]`, because they never look at the
    eyes' geometry at all.

    build() passes `r=r` (and `iris=r*0.5`, `pupil=r*0.25`) into `eye()`,
    which places the sclera at `sclera_off = r*0.22` along `look` with its
    own radius `sclera_r = r*0.92` — so the sclera's SDF sampled at the
    fixed eye-socket centre `build()` itself uses, (-0.24, 0.10, 0.52),
    reads exactly `sclera_off - sclera_r == -0.70*r`: linear in `r`, so a
    changed `eye_open` (and nothing else, since this samples one fixed
    world point) always changes this value. `surf.parts` is
    `[head, left.sclera, left.iris, left.pupil, right.sclera, ...]` — index
    1 is the left eye's sclera (mirroring the brow/mouth tests' reliance on
    build()'s own composition order, not a render).

    Measured for FACE (eye_open=1.0, r=0.17): -0.119. For ANGRY
    (eye_open=0.7, r=0.119): -0.0833.
    """
    left_eye_centre = np.array([[-0.24, 0.10, 0.52]])
    _, calm_surf, _ = demo_character.build(demo_character.FACE)
    _, angry_surf, _ = demo_character.build(demo_character.ANGRY)
    calm_sclera_sdf, calm_mat = calm_surf.parts[1]
    angry_sclera_sdf, angry_mat = angry_surf.parts[1]
    assert calm_mat.color == angry_mat.color == (250, 250, 255), "must be the sclera"
    calm_r = float(calm_sclera_sdf(left_eye_centre)[0])
    angry_r = float(angry_sclera_sdf(left_eye_centre)[0])
    assert calm_r != angry_r, "eye_open must change the geometry the eye carries"
