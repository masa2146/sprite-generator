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
    parts = [(sphere(r*0.92, tuple(c + d*0.02)), material(sclera, spec=0.35,
                                                          shininess=60))]
    if iris > 0:
        parts.append((sphere(iris, tuple(c + d*(r*0.80))),
                      material(iris_color, spec=0.30, shininess=50)))
    parts.append((sphere(max(pupil, 1e-4), tuple(c + d*(r*0.88))),
                  material(pupil_color, spec=0.20, shininess=40)))

    decals = []
    if glint > 0:
        off = np.array([-0.35, 0.35, 0.0])
        gd = d + off
        decals.append((tuple(gd / (np.linalg.norm(gd) + 1e-9)),
                       math.degrees(glint*8), 0.7, glint_color))
    return Eye(socket, parts, decals)
