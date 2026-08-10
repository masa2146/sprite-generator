"""Turn an analysis of a screenshot into crops and paste-ready prompts.

Generation happens by hand in Gemini or ChatGPT, so nothing here calls an API
or writes a generated image. The deliverable is a folder you upload from and a
prompt you paste — which makes a retry free, and makes prompt quality the thing
that carries the result.

The prompt is a structured block rather than a paragraph because every block
answers a failure measured on the paid path: an unlabelled pair of reference
images, a missing "exactly one" that produced twelve balls, HUD labels that kept
their text, and a frame whose crop showed everything it framed.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import shutil
import sys
import webbrowser
from pathlib import Path

from PIL import Image

import crops
import prompts
import refclean


class BriefError(Exception):
    """The analysis could not be turned into a brief."""


def load_analysis(path) -> tuple[str, list[dict]]:
    """Read and validate analysis.json. Returns (style, objects).

    Every error names the offending field, and the object's id where there is
    one: this file is meant to be hand-edited between runs, so an error that
    only says "invalid" costs the user a hunt.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BriefError(f"cannot read {path.name}: {exc}") from exc

    if not isinstance(raw, dict):
        raise BriefError("analysis must be a JSON object")

    style = raw.get("style")
    if not isinstance(style, str) or not style.strip():
        raise BriefError("'style' is required and must be a non-empty string")

    objects = raw.get("objects")
    if not isinstance(objects, list) or not objects:
        raise BriefError("'objects' is required and must be a non-empty list")

    out: list[dict] = []
    for index, obj in enumerate(objects):
        if not isinstance(obj, dict):
            raise BriefError(f"objects[{index}]: must be a JSON object")
        obj_id = obj.get("id")
        if not isinstance(obj_id, str) or not obj_id.strip():
            raise BriefError(f"objects[{index}]: 'id' is required")
        bbox = obj.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            raise BriefError(
                f"objects[{index}] ({obj_id}): 'bbox' must be [x1, y1, x2, y2]"
            )
        entry = dict(obj)
        entry["views"] = prompts.normalise_views(obj.get("views"))
        # labelled_sheet captions each crop with this flag. Multiple views is
        # the only motion signal this schema carries, so it is what the caption
        # reports — a caption that misdescribes its crop is what this whole
        # review step exists to catch.
        entry["animated"] = len(entry["views"]) > 1
        out.append(entry)

    # Schema v1 carries style as one line. v2 (the next task) replaces this
    # with the six-field object image-style produces; wrapping it here keeps
    # the move honest — one change at a time.
    style = {"render": style.strip()}
    return style, out


_CSS = """
body { font: 15px/1.55 -apple-system, Segoe UI, sans-serif; margin: 0 auto;
       max-width: 62rem; padding: 2rem 1.25rem; background: #16161c; color: #e8e8ef; }
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
.meta { color: #9a9ab0; font-size: .85rem; margin-bottom: 2rem; }
.asset { border-top: 1px solid #2c2c3a; padding: 1.5rem 0; }
.asset h2 { font-size: 1.05rem; margin: 0 0 .75rem; font-family: ui-monospace, monospace; }
.row { display: flex; gap: 1.25rem; flex-wrap: wrap; margin-bottom: .85rem; }
figure { margin: 0; }
figcaption { color: #9a9ab0; font-size: .75rem; margin-top: .3rem; }
img { max-width: 190px; max-height: 190px; background: #22222c; border-radius: 6px; }
.style { margin: 0 0 2rem; }
.style img { max-width: 260px; max-height: 320px; }
.pair { color: #9a9ab0; font-size: .85rem; margin: 0; align-self: center; }
pre { margin: 0; padding: .85rem; background: #1e1e28; border-radius: 6px;
      white-space: pre-wrap; word-break: break-word;
      font: 13px/1.5 ui-monospace, monospace; }
"""


def _data_uri(path: Path) -> str:
    """Crops and the style copy are always PNG here because this module writes
    them, so the type is known and needs no sniffing."""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def page(entries, style_image: Path, title: str) -> str:
    """The whole brief as one self-contained HTML document.

    Both images are inlined and both are named, because the workflow is: read
    the prompt here, then upload those two files from refs/.
    """
    style_image = Path(style_image)
    style_uri = _data_uri(style_image)
    out = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body>",
        f"<h1>{html.escape(title)}</h1>",
        f"<p class='meta'>{len(entries)} prompts · upload BOTH images with every "
        "message · one message per sprite</p>",
    ]
    # The style image is drawn once, at the top. Repeating it per asset inlines
    # the same base64 blob N times: measured at 55 MB for a 2.4 MB screenshot
    # across 17 assets. Each asset still names it, so the "upload both" rule
    # survives without the bytes.
    out += [
        "<figure class='style'>",
        f"<img src='{style_uri}' alt=''>",
        f"<figcaption>Picture 2 — {html.escape(style_image.name)} — upload this "
        "with EVERY message, alongside the crop</figcaption>",
        "</figure>",
    ]
    for entry in entries:
        crop = Path(entry["crop"])
        out += [
            "<div class='asset'>",
            f"<h2>{html.escape(entry['id'])}</h2>",
            "<div class='row'>",
            f"<figure><img src='{_data_uri(crop)}' alt=''>"
            f"<figcaption>Picture 1 — {html.escape(crop.name)}</figcaption></figure>",
            f"<p class='pair'>+ Picture 2 — {html.escape(style_image.name)}</p>",
            "</div>",
            f"<pre>{html.escape(entry['prompt'])}</pre>",
            "</div>",
        ]
    out.append("</body></html>")
    return "\n".join(out)


# --- the command --------------------------------------------------------

def _load_image(image_path: Path):
    try:
        return Image.open(image_path).convert("RGB")
    except Exception as exc:
        raise BriefError(f"cannot read {image_path}: {exc}") from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="brief",
        description="Turn a screenshot and its analysis into crops and "
                    "paste-ready prompts for manual generation.",
    )
    parser.add_argument("--image", required=True, help="source screenshot")
    parser.add_argument("--analysis", required=True, help="analysis.json")
    parser.add_argument("--out-dir", required=True,
                        help="directory to create; refused if it already holds a brief")
    parser.add_argument("--no-open", action="store_true",
                        help="do not open the contact sheet")
    args = parser.parse_args(argv)

    image_path = Path(args.image)
    analysis_path = Path(args.analysis)
    out_dir = Path(args.out_dir)
    refs_dir = out_dir / "refs"
    brief_path = out_dir / "brief.html"
    inner_analysis = out_dir / "analysis.json"

    # Refuse to clobber a brief the user has already reviewed — unless the
    # analysis being read IS this brief's own, which is the review loop:
    # edit analysis.json in place, run again.
    if brief_path.exists():
        same = (analysis_path.resolve() == inner_analysis.resolve()
                if inner_analysis.exists() else False)
        if not same:
            print(f"error: {brief_path} already exists — delete it, choose another "
                  f"--out-dir, or edit {inner_analysis} and re-run from that file",
                  file=sys.stderr)
            return 1

    try:
        style, objects = load_analysis(analysis_path)
        image = _load_image(image_path)
    except BriefError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        kept, rejected = crops.crop_objects(image, objects, refs_dir)
    except OSError as exc:
        print(f"error: cannot write crops to {refs_dir}: {exc}", file=sys.stderr)
        return 1

    for obj_id, reason in rejected:
        print(f"  dropped {obj_id}: {reason}", file=sys.stderr)

    if not kept:
        print("error: no usable objects — nothing written", file=sys.stderr)
        return 1

    contents = crops.find_contents(kept)
    crops.blank_contents(kept, contents, image)
    # After blanking, which maps source-image boxes into crop coordinates that
    # the upscale here would invalidate.
    refclean.clean_crops(kept)
    for obj_id, inside in contents.items():
        print(f"note: {obj_id}'s box also contains {len(inside)} other object(s) "
              f"({', '.join(inside)}) — they are blanked out of its crop, and its "
              f"prompt asks for it without them", file=sys.stderr)

    style_copy = refs_dir / "_style.png"
    try:
        shutil.copyfile(image_path, style_copy)
    except OSError as exc:
        print(f"error: cannot write {style_copy}: {exc}", file=sys.stderr)
        return 1

    sheet = None
    try:
        sheet = crops.labelled_sheet(kept, refs_dir / "_contact_sheet.png")
    except Exception as exc:
        # A review aid must not cost the user the crops and prompts.
        print(f"warning: contact sheet not written: {exc}", file=sys.stderr)

    entries = []
    for obj in kept:
        for view in obj["views"]:
            entries.append({
                "id": "{}-{}".format(obj["id"], view),
                "crop": obj["crop"],
                "prompt": prompts.asset_prompt(obj, view, style, contents.get(obj["id"])),
            })

    title = f"{out_dir.name} — prompts for manual generation"
    try:
        brief_path.write_text(page(entries, style_copy, title), encoding="utf-8")
        if analysis_path.resolve() != inner_analysis.resolve():
            shutil.copyfile(analysis_path, inner_analysis)
    except OSError as exc:
        print(f"error: cannot write {brief_path}: {exc}", file=sys.stderr)
        return 1

    print(f"\n{len(kept)} objects, {len(entries)} prompts -> {brief_path}")
    print(f"uploads -> {refs_dir}")
    if sheet and not args.no_open:
        webbrowser.open(Path(sheet).resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())

