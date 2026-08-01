"""Cut the background out of local PNGs — the crops a brief writes, ready to
drop into an engine as sprites."""

from __future__ import annotations

import argparse
import sys
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

import post


def key_background(data: bytes, tol: float = 14.0) -> Image.Image:
    """Clear every pixel reachable from the border whose colour is within `tol`
    of the background's.

    For an asset sheet laid out on one flat colour this beats a matting model
    outright: the model reads a near-black plate or a low-contrast panel as
    background and eats it, while a keyed flood only ever removes the colour it
    was told to. Connectivity is what keeps a dark seam inside an object from
    being punched out along with the background around it.
    """
    img = Image.open(BytesIO(data)).convert("RGB")
    rgb = np.asarray(img).astype(np.int16)
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(border, axis=0)
    similar = np.sqrt(((rgb - bg) ** 2).sum(axis=2)) < tol

    reached = np.zeros(similar.shape, bool)
    reached[0], reached[-1], reached[:, 0], reached[:, -1] = (True,) * 4
    reached &= similar
    while True:
        grown = reached.copy()
        grown[1:] |= reached[:-1]
        grown[:-1] |= reached[1:]
        grown[:, 1:] |= reached[:, :-1]
        grown[:, :-1] |= reached[:, 1:]
        grown &= similar
        if grown.sum() == reached.sum():
            break
        reached = grown

    out = img.convert("RGBA")
    out.putalpha(Image.fromarray(np.where(reached, 0, 255).astype(np.uint8)))
    return out


def cut_glow(data: bytes) -> Image.Image:
    """Alpha straight from brightness above the flat background colour.

    For a soft additive effect — a flash, a glow — there is no subject edge to
    find, and a matting model shreds it into blobs. Reading the alpha off the
    luminance keeps the falloff intact. Assumes a flat background, taken as the
    most common colour rather than a corner pixel — a corner lands on a grid
    line often enough to drag the whole threshold down with it.
    """
    img = Image.open(BytesIO(data)).convert("RGB")
    grey = img.convert("L")
    base = max(grey.getcolors(256))[1]
    span = max(255 - base, 1)
    alpha = grey.point(
        lambda v: max(0, min(255, round((v - base) * 255 / span))))
    out = img.convert("RGBA")
    out.putalpha(alpha)
    return out


def iter_pngs(paths):
    """Every PNG under the given files and directories, sorted, skipping the
    underscore-prefixed sheet images a brief writes alongside the crops."""
    found = []
    for raw in paths:
        path = Path(raw)
        found.extend(sorted(path.glob("*.png")) if path.is_dir() else [path])
    return [p for p in found if not p.name.startswith("_")]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="cutout.py",
        description="Remove the background from PNGs and centre each subject "
                    "on a transparent square.",
    )
    parser.add_argument("paths", nargs="+",
                        help="png files, or directories holding them")
    parser.add_argument("--out-dir", required=True,
                        help="directory to write the cut PNGs into")
    parser.add_argument("--glow", action="store_true",
                        help="soft additive effect: take the alpha from "
                             "brightness instead of matting a subject")
    parser.add_argument("--key", action="store_true",
                        help="asset sheet on one flat colour: flood the "
                             "background colour out from the border instead "
                             "of matting a subject")
    parser.add_argument("--tol", type=float, default=14.0,
                        help="--key colour distance treated as background "
                             "(default 14)")
    args = parser.parse_args(argv)

    sources = iter_pngs(args.paths)
    if not sources:
        print("error: no PNGs to cut", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.glow:
        cut = cut_glow
    elif args.key:
        cut = lambda data: key_background(data, args.tol)
    else:
        cut = post.cut_background
    for src in sources:
        try:
            img = post.trim_and_pad(cut(src.read_bytes()))
        except OSError as exc:
            print(f"  skipped {src.name}: {exc}", file=sys.stderr)
            continue
        img.save(out_dir / src.name)
        print(f"{src.name} -> {out_dir / src.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
