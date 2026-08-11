"""character_lib - the parts of a character a raymarched sprite needs and the
renderer has no opinion about: eyes built as geometry, decals along a curve,
a light that turns with the camera, and a turnaround.

It gives no anatomy. Body plans, proportions and stance are the asset's, and
a library that shipped them would make every character come out of the same
mould.
"""
import math

import numpy as np

from sdf3d import material, sphere


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
