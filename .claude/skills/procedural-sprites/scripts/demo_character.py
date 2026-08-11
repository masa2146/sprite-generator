"""demo_character - the library's own QC, not a style to copy.

It exists so that every piece of character_lib is exercised end to end by
something that renders: an eye built as geometry, a mouth from a stroke, a
turnaround whose light follows the camera, and an expression that is nothing
but a dict of numbers merged over another dict of numbers.

The shape is deliberately plain. A demo that looked designed would become
the thing everybody copies, and this library gives technique, not style.
"""
import sys

from sdf3d import material, render, smooth_union, spots, sphere, surface, union
from sprite_lib import contour, qc_strip

from character_lib import VIEWS, eye, light_for, mirror_decals, stroke, turnaround

FACE = dict(eye_open=1.0, pupil_x=0.0, mouth=0.16, brow=-4.0)
ANGRY = FACE | dict(brow=16.0, eye_open=0.7, mouth=-0.22)

BODY = (200, 120, 90)
INK = (26, 26, 46)

HEAD_CENTRE = (0.0, 0.10, 0.0)      # every decal aims at this


def build(expr):
    """Returns (shape, surface, decals) for one expression."""
    head = sphere(0.62)
    r = 0.17 * expr["eye_open"]
    look = (expr["pupil_x"], 0.05, 1.0)
    # head_center=HEAD_CENTRE so each eye's glint direction is built from
    # the same global centre spots() paints against below, not the origin
    # eye() defaults to - see eye()'s own docstring for why that distinction
    # matters (a glint that lands on the forehead otherwise).
    left = eye((-0.24, 0.10, 0.52), look, r=r, iris=r*0.5, pupil=r*0.25,
              head_center=HEAD_CENTRE)
    right = eye((0.24, 0.10, 0.52), look, r=r, iris=r*0.5, pupil=r*0.25,
               head_center=HEAD_CENTRE)

    shape = union(smooth_union(0.06, head, left.socket, right.socket),
                  *[s for s, _ in left.parts + right.parts])
    surf = surface([(head, material(BODY, spec=0.25, shininess=22))]
                   + left.parts + right.parts)

    mouth = stroke([(-0.22, -0.30 + expr["mouth"], 0.9),
                    (0.0, -0.34, 0.9),
                    (0.22, -0.30 + expr["mouth"], 0.9)],
                   radius_deg=3.0, color=INK, samples=14)
    brow = stroke([(-0.34, 0.34, 0.85),
                   (-0.14, 0.34 + expr["brow"]/100.0, 0.9)],
                  radius_deg=3.4, color=INK, samples=8)
    decals = mouth + brow + mirror_decals(brow) + left.decals + right.decals
    return shape, surf, decals


def _painted(expr):
    """The body's materials with the face decals over them."""
    shape, surf, decals = build(expr)
    return shape, spots(surf, decals, center=HEAD_CENTRE)


def render_one(expr, yaw=0, size=(320, 320)):
    shape, painted = _painted(expr)
    img = render(shape, size=size, tilt=12, yaw=yaw, color=painted,
                 light=light_for(yaw), ao=0.5, rim=0.06)
    return contour(img, width=2, color=INK)


def main():
    for label, expr in (("calm", FACE), ("angry", ANGRY)):
        shape, painted = _painted(expr)
        views = turnaround(shape, views=VIEWS, size=(320, 320), tilt=12,
                           color=painted, ao=0.5, rim=0.06)
        for name, img in views.items():
            out = contour(img, width=2, color=INK)
            out.save(f"demo_{label}_{name}.png")
            print("wrote", f"demo_{label}_{name}.png")
        qc_strip(contour(views["front"], width=2, color=INK),
                 [(48, 48), (96, 96)], f"demo_{label}_qc.png",
                 bg=(56, 54, 92, 255))


if __name__ == "__main__":
    sys.exit(main())
