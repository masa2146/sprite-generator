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
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

import crops
import prompts
import refclean


class BriefError(Exception):
    """The analysis could not be turned into a brief."""


STYLE_FIELDS = ("render", "camera", "lighting", "palette", "linework", "realism")
UNSTATED = "belirtilmemiş"


@dataclass
class Analysis:
    style: dict          # six fields, every one a non-empty string
    style_source: dict   # field -> "kullanıcı" | "stil görseli" | "referans" | "ölçüm" | "varsayılan"
    style_image: Path | None
    objects: list[dict]  # each with id, views, animated, source: Path|None, bbox: list|None


def _resolve(raw, base: Path, where: str) -> Path | None:
    """A path from the analysis, resolved against the analysis file.

    Against the file and not the cwd: the analysis carries its images with it,
    and the review loop runs it again from wherever the user happens to be.
    """
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise BriefError(f"{where}: image path must be a non-empty string")
    path = Path(raw)
    resolved = (path if path.is_absolute() else base / path).resolve()
    if not resolved.exists():
        raise BriefError(f"{where}: no such image: {raw}")
    return resolved


def load_analysis(path) -> Analysis:
    """Read and validate analysis.json. Every error names the offending field,
    and the object's id where there is one: this file is hand-edited between
    runs, and an error that only says "invalid" costs the user a hunt."""
    path = Path(path)
    base = path.parent.resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BriefError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(raw, dict):
        raise BriefError("analysis must be a JSON object")

    style = raw.get("style")
    if not isinstance(style, dict):
        raise BriefError(
            "'style' must be an object with the fields: " + ", ".join(STYLE_FIELDS))
    missing = [f for f in STYLE_FIELDS
               if not isinstance(style.get(f), str) or not style[f].strip()]
    if missing:
        raise BriefError(f"style is missing {len(missing)} field(s): "
                         + ", ".join(missing))
    style = {f: style[f].strip() for f in STYLE_FIELDS}

    raw_source = raw.get("style_source") or {}
    if not isinstance(raw_source, dict):
        raise BriefError("'style_source' must be an object when given")
    # A field nobody claimed is stamped, not guessed. The review page prints
    # this beside every field, so an override that landed on the wrong one is
    # visible instead of silent.
    style_source = {f: str(raw_source.get(f) or UNSTATED).strip() for f in STYLE_FIELDS}

    style_image = _resolve(raw.get("style_image"), base, "style_image")

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
        where = f"objects[{index}] ({obj_id})"

        entry = dict(obj)
        own_source = _resolve(obj.get("source"), base, where)

        bbox = obj.get("bbox")
        if bbox is not None:
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                raise BriefError(f"{where}: 'bbox' must be [x1, y1, x2, y2]")

        # style_image is the picture boxes are CUT from, not a catch-all for
        # anything undescribed — so it only fills in when there is a bbox to
        # cut with. An unconditional fallback here made "text" unreachable
        # whenever the analysis had a style_image: an object the user only
        # described (a shield icon not in this screenshot) silently inherited
        # the whole screen as its identity source. The measured cost: a
        # conveyor loop boxed whole gave its track 80px of a 1024px picture
        # and came back as a picture frame under every wording tried. An
        # object that wants the whole shared picture now must name it
        # explicitly as its own 'source' — deliberate, not a default.
        entry["source"] = own_source or (style_image if bbox is not None else None)

        if bbox is not None and entry["source"] is None:
            raise BriefError(f"{where}: 'bbox' needs an image to cut out of — "
                             "give the object a 'source' or the analysis a "
                             "'style_image'")
        entry["bbox"] = list(bbox) if bbox is not None else None
        entry["views"] = prompts.normalise_views(obj.get("views"))
        # labelled_sheet captions each crop with this flag. Multiple views is
        # the only motion signal this schema carries, so it is what the caption
        # reports — a caption that misdescribes its crop is what this whole
        # review step exists to catch.
        entry["animated"] = len(entry["views"]) > 1
        out.append(entry)
    return Analysis(style, style_source, style_image, out)


def crop_mode(obj: dict) -> str:
    """Which of the three shapes this object's reference takes.

    Cropping is a decision, not a step: one clean picture of one object needs
    no box, a screenshot holding a set needs one per object, and an object the
    user only described has no picture at all. Guessing wrong in either
    direction is expensive — a box around a whole playfield gave its track 80px
    of a 1024px picture and came back as a picture frame every single time.
    """
    if obj.get("source") is None:
        return "text"
    return "crop" if obj.get("bbox") else "whole"


def prepare_refs(analysis, refs_dir) -> tuple[list[dict], list, dict, list[str]]:
    """Write every object's reference image. Returns (kept, rejected, contents, notes).

    Boxes are compared for containment within one source image only: two boxes
    in two different screenshots have no spatial relationship, and reporting one
    as swallowing the other would blank a hole in a crop for no reason.
    """
    refs_dir = Path(refs_dir)
    refs_dir.mkdir(parents=True, exist_ok=True)

    kept: list[dict] = []
    rejected: list = []
    contents: dict = {}
    notes: list[str] = []

    boxed: dict[Path, list[dict]] = {}
    # One id, checked here across all three shapes and every source image —
    # not just within crop_objects's per-source screen_objects. Grouping by
    # source narrowed that check to one image; two boxed objects with the same
    # id in two DIFFERENT images now landed on the same refs_dir/<id>.png with
    # no rejection printed at all, so the first object's picture silently
    # became the second's. Case-folded to agree with screen_objects, which
    # already treats "Block" and "block" as one filename on a case-insensitive
    # filesystem.
    seen: set[str] = set()
    for obj in analysis.objects:
        obj_id = obj["id"]
        if obj_id.lower() in seen:
            rejected.append((obj_id, "duplicate id"))
            continue
        seen.add(obj_id.lower())

        mode = crop_mode(obj)
        # blank is measured in source-image pixels and its rationale (a ban
        # that contradicts the picture loses, and this is the only lever that
        # beats it) holds for any picture — it is only WIRED UP for a
        # bbox-cropped object today, via crops.blank_contents below. That is a
        # gap in where it is applied, not a rule about what the field means.
        # Left silent, a 'whole' or 'text' object carrying a 'blank' looks
        # accepted and does nothing, which is exactly the silent drop this
        # flow is built against.
        if obj.get("blank") and mode != "crop":
            notes.append(f"{obj_id}: 'blank' is ignored — the object is not "
                         f"cut from a box ({mode} reference), so there is no "
                         "crop to paint the boxes out of")
        if mode == "text":
            kept.append(dict(obj))
        elif mode == "whole":
            entry = dict(obj)
            target = refs_dir / f"{obj['id']}.png"
            try:
                with Image.open(obj["source"]) as opened:
                    opened.convert("RGB").save(target)
            except OSError as exc:
                rejected.append((obj["id"], f"cannot read {obj['source']}: {exc}"))
                continue
            entry["crop"] = target
            kept.append(entry)
        else:
            boxed.setdefault(obj["source"], []).append(obj)

    for source, group in boxed.items():
        try:
            with Image.open(source) as opened:
                image = opened.convert("RGB")
        except OSError as exc:
            rejected.extend((o["id"], f"cannot read {source}: {exc}") for o in group)
            continue
        cut, dropped = crops.crop_objects(image, group, refs_dir)
        rejected.extend(dropped)
        inside = crops.find_contents(cut)
        crops.blank_contents(cut, inside, image)
        contents.update(inside)
        kept.extend(cut)

    # After blanking, which maps source-image boxes into crop coordinates that
    # the upscale in here would invalidate.
    refclean.clean_crops([o for o in kept if o.get("crop")])
    return kept, rejected, contents, notes


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
.style-grid { display: grid; grid-template-columns: max-content 1fr;
              gap: .4rem 1rem; margin-bottom: 2rem; align-items: center; }
.src { color: #9a9ab0; font-size: .72rem; margin-left: .5rem; border: 1px solid #33334a;
       border-radius: 3px; padding: 0 .35rem; }
.swatch { display: inline-block; width: 24px; height: 24px; border-radius: 4px;
          vertical-align: middle; margin-right: .3rem; }
.prompts { margin-top: 2.5rem; border-top: 2px solid #2c2c3a; padding-top: 1.5rem; }
"""


def _data_uri(path: Path) -> str:
    """Crops and the style copy are always PNG here because this module writes
    them, so the type is known and needs no sniffing."""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def _swatches(colours) -> str:
    """Measured colours as squares plus their hex, because a name is not
    reproducible: a conveyor's channel was called 'pale lilac-white' when it is
    #434375, and the sprite stayed pale until the measured value went into the prompt."""
    return "".join(
        f"<span class='swatch' style='background:{html.escape(c)}'></span>"
        f"<code>{html.escape(c)}</code>"
        for c in colours or [])


def page(analysis, kept, contents, title: str) -> str:
    """The whole review as one self-contained document.

    Two sections, because the same analysis feeds two ways of making the
    sprite: the review is what gets checked before any code is written, and
    the prompts are what gets pasted into a chat when it is made by hand.
    """
    out = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body>",
        f"<h1>{html.escape(title)}</h1>",
        f"<p class='meta'>{len(kept)} nesne · inceleme + elle üretim prompt'ları</p>",
        "<h2>Stil</h2><div class='style-grid'>",
    ]
    for field in STYLE_FIELDS:
        out.append(
            f"<div><code>{field}</code></div>"
            f"<div>{html.escape(analysis.style[field])}"
            f"<span class='src'>{html.escape(analysis.style_source[field])}</span></div>")
    out.append("</div>")
    if analysis.style_image:
        out += ["<figure class='style'>",
                f"<img src='{_data_uri(analysis.style_image)}' alt=''>",
                f"<figcaption>Picture 2 — {html.escape(analysis.style_image.name)} — "
                "her mesajda crop'un yanında bunu da yükle</figcaption>", "</figure>"]

    out.append("<h2>Nesneler</h2>")
    for obj in kept:
        crop = obj.get("crop")
        out += ["<div class='asset'>", f"<h3>{html.escape(obj['id'])}</h3>",
                "<div class='row'>"]
        if crop:
            out.append(f"<figure><img src='{_data_uri(Path(crop))}' alt=''>"
                       f"<figcaption>Picture 1 — {html.escape(Path(crop).name)}"
                       "</figcaption></figure>")
        else:
            out.append("<p class='pair'>görsel yok — yalnızca tarif</p>")
        out.append(f"<div><p>{_swatches(obj.get('palette'))}</p>")
        for key, label in (("subject", "OBJECT"), ("form", "FORM"),
                           ("detail", "DETAIL"), ("state", "STATE")):
            if isinstance(obj.get(key), str) and obj[key].strip():
                out.append(f"<p><code>{label}</code> {html.escape(obj[key])}</p>")
        out.append("<p><code>VIEWS</code> {}</p></div>".format(
            html.escape(", ".join(obj["views"]))))
        out.append("</div></div>")

    out.append("<h2 class='prompts'>Elle üretim prompt'ları</h2>"
               "<p class='meta'>Her mesajda iki görseli de yükle · sprite başına tek "
               "mesaj · set başına yeni sohbet · indirileni <code>cut.py</code> ile kes</p>")
    for obj in kept:
        has_crop = obj.get("crop") is not None
        for view in obj["views"]:
            text = prompts.asset_prompt(
                obj, view, analysis.style, contents.get(obj["id"]),
                style_image=has_crop and analysis.style_image is not None,
                references=has_crop)
            out += ["<div class='asset'>",
                    f"<h3>{html.escape(obj['id'])}-{html.escape(view)}</h3>",
                    f"<pre>{html.escape(text)}</pre>", "</div>"]
    out.append("</body></html>")
    return "\n".join(out)


# --- the command --------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="brief",
        description="Turn an analysis of a screenshot into crops and "
                    "paste-ready prompts for manual generation.",
    )
    parser.add_argument("--analysis", required=True, help="analysis.json")
    parser.add_argument("--out-dir", required=True,
                        help="directory to create; refused if it already holds a brief")
    parser.add_argument("--no-open", action="store_true",
                        help="do not open the contact sheet")
    args = parser.parse_args(argv)

    analysis_path = Path(args.analysis)
    out_dir = Path(args.out_dir)
    refs_dir = out_dir / "refs"
    review_path = out_dir / "review.html"
    inner_analysis = out_dir / "analysis.json"

    # Refuse to clobber a brief the user has already reviewed — unless the
    # analysis being read IS this brief's own, which is the review loop:
    # edit analysis.json in place, run again.
    if review_path.exists():
        same = (analysis_path.resolve() == inner_analysis.resolve()
                if inner_analysis.exists() else False)
        if not same:
            print(f"error: {review_path} already exists — delete it, choose another "
                  f"--out-dir, or edit {inner_analysis} and re-run from that file",
                  file=sys.stderr)
            return 1

    try:
        parsed = load_analysis(analysis_path)
    except BriefError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        kept, rejected, contents, notes = prepare_refs(parsed, refs_dir)
    except OSError as exc:
        print(f"error: cannot write refs to {refs_dir}: {exc}", file=sys.stderr)
        return 1

    for obj_id, reason in rejected:
        print(f"  dropped {obj_id}: {reason}", file=sys.stderr)

    for note in notes:
        print(f"note: {note}", file=sys.stderr)

    if not kept:
        print("error: no usable objects — nothing written", file=sys.stderr)
        return 1

    for obj_id, inside in contents.items():
        print(f"note: {obj_id}'s box also contains {len(inside)} other object(s) "
              f"({', '.join(inside)}) — they are blanked out of its crop, and its "
              f"prompt asks for it without them", file=sys.stderr)

    # Written only when the analysis actually has a shared style reference —
    # an object cropped or copied from its own source needs no second picture.
    style_copy = None
    if parsed.style_image is not None:
        style_copy = refs_dir / "_style.png"
        try:
            shutil.copyfile(parsed.style_image, style_copy)
        except OSError as exc:
            print(f"error: cannot write {style_copy}: {exc}", file=sys.stderr)
            return 1

    pictured = [obj for obj in kept if obj.get("crop")]

    sheet = None
    if pictured:
        try:
            sheet = crops.labelled_sheet(pictured, refs_dir / "_contact_sheet.png")
        except Exception as exc:
            # A review aid must not cost the user the crops and prompts.
            print(f"warning: contact sheet not written: {exc}", file=sys.stderr)

    # page() renders the style figure only when analysis.style_image is set,
    # so an analysis with no style image (every object cropped or copied from
    # its own source) no longer fails here — it used to, after the crops were
    # already written, because the old single-section page() had nowhere to
    # put a "Picture 2" it did not have.
    title = f"{out_dir.name} — inceleme + elle üretim prompt'ları"
    try:
        review_path.write_text(page(parsed, kept, contents, title), encoding="utf-8")
        if analysis_path.resolve() != inner_analysis.resolve():
            # A straight copy would keep whatever image path the user wrote
            # (often relative, resolved against analysis_path's own
            # directory). The copy lives in out_dir instead, so a relative
            # path would silently resolve against the wrong directory on the
            # next rerun. Stamping in the already-resolved absolute path
            # keeps the review loop ("edit analysis.json in place, run
            # again") working from out_dir.
            raw = json.loads(analysis_path.read_text(encoding="utf-8"))
            raw["style_image"] = str(parsed.style_image) if parsed.style_image else None
            # Per-object source needs the same stamping, and for the same
            # reason: task 7 could leave it alone because nothing cropped from
            # it yet, but prepare_refs does now, so a rerun of this copy from
            # out_dir must still find every object's own picture.
            sources = {obj["id"]: obj["source"] for obj in parsed.objects}
            for raw_obj in raw.get("objects", []):
                source = sources.get(raw_obj.get("id"))
                if source is not None:
                    raw_obj["source"] = str(source)
            inner_analysis.write_text(json.dumps(raw), encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write {review_path}: {exc}", file=sys.stderr)
        return 1

    total_prompts = sum(len(obj["views"]) for obj in kept)
    print(f"\n{len(kept)} objects, {total_prompts} prompts -> {review_path}")
    print(f"uploads -> {refs_dir}")
    if sheet and not args.no_open:
        webbrowser.open(Path(sheet).resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())

