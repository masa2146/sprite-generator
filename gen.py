"""Sprite generator CLI.

Commands:
    init <spec>     generate style plate candidates
    pick <spec> N   lock candidate N as the pack's style bible
    build <spec>    generate every asset in the spec
    analyze <image> derive the style prefix (and style bible) from a reference image
    make            pack-less one-shot: an image, a text, or both -> one sprite
    extract         find every sprite in an image and write a buildable pack
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import sys
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

import config
import extract
import orclient
import packwriter
import post
import vision

EST_COST = 0.04          # per-image estimate for --dry-run only
DEFAULT_MAX_COST = 5.00
WORKERS = 4              # API calls are I/O bound; rembg stays on the main thread
PLATE_COUNT = 4          # style plate candidates produced by `init`


def select_assets(assets, only):
    """Filter assets by a comma-separated id list, preserving spec order."""
    if not only:
        return list(assets)
    wanted = [x.strip() for x in only.split(",") if x.strip()]
    known = {a.id for a in assets}
    unknown = [w for w in wanted if w not in known]
    if unknown:
        raise SystemExit(f"unknown asset id(s): {', '.join(unknown)}")
    return [a for a in assets if a.id in set(wanted)]


def _record(pack, asset, status, cost=None, file=None, error=None):
    return {
        "id": asset.id,
        "status": status,
        "prompt": pack.full_prompt(asset),
        "model": pack.model,
        "base_url": pack.base_url,
        "transport": pack.transport,
        "aspect_ratio": asset.aspect_ratio,
        "seed": pack.seed_for(asset.id),
        "cost": cost,
        "file": file,
        "error": error,
    }


def build_one(pack, asset, reference_png):
    """Generate and post-process one asset. Returns a manifest record, never raises."""
    out_dir = pack.out_dir
    if asset.reference is not None:
        try:
            reference_png = asset.reference.read_bytes()
        except OSError as exc:
            # Fail this asset only — the pack's other assets are unaffected.
            return _record(pack, asset, "failed",
                           error=f"cannot read reference {asset.reference}: {exc}")
    try:
        png, cost, _raw = orclient.generate(
            pack,
            pack.full_prompt(asset),
            aspect_ratio=asset.aspect_ratio,
            reference_png=reference_png,
            seed=pack.seed_for(asset.id),
        )
    except orclient.ImageMissing as exc:
        try:
            (out_dir / f"{asset.id}.error.json").write_text(json.dumps(exc.raw, indent=2))
            note = f" (see {asset.id}.error.json)"
        except Exception as write_exc:
            note = f" (also failed to write {asset.id}.error.json: {write_exc})"
        return _record(pack, asset, "failed", error=f"no image in response{note}")
    except orclient.ApiError as exc:
        return _record(pack, asset, "failed", error=str(exc))
    except Exception as exc:  # transport-level surprises: connection reset, DNS, ...
        return _record(pack, asset, "failed", error=f"{type(exc).__name__}: {exc}")

    # The image is paid for by this point. If post-processing fails, keep the raw
    # file rather than losing the money.
    try:
        target = out_dir / f"{asset.id}.png"
        if asset.cutout:
            img = post.cut_background(png)
            img = post.trim_and_pad(img)
            img.save(target)
        else:
            # This asset IS the whole image (background/seamless tile) — there
            # is no subject to cut out or trim, ship the bytes unmodified.
            target.write_bytes(png)
    except Exception as exc:
        try:
            (out_dir / f"{asset.id}.raw.png").write_bytes(png)
            note = f" (raw kept as {asset.id}.raw.png)"
        except Exception as write_exc:
            note = f" (also failed to keep raw png: {write_exc})"
        return _record(pack, asset, "failed", cost=cost,
                       error=f"post-processing: {exc}{note}")

    return _record(pack, asset, "ok", cost=cost, file=str(target))


def _missing_key(pack) -> bool:
    """An empty key_env means the endpoint needs no key. A named one that is unset
    is a mistake worth catching before we start firing doomed requests."""
    if pack.key_env and pack.api_key() is None:
        print(f"error: ${pack.key_env} is not set", file=sys.stderr)
        return True
    return False


def _report_analysis_error(exc: "vision.AnalysisError", image_path: Path) -> int:
    """The reply is the only evidence of what went wrong; keep it on disk
    rather than making the user re-run and re-pay to see it again."""
    if exc.raw:
        dump = image_path.with_suffix(image_path.suffix + ".analysis-error.txt")
        try:
            dump.write_text(exc.raw, encoding="utf-8")
            print(f"error: {exc} (raw reply written to {dump})", file=sys.stderr)
        except Exception:
            # Raw model text is not guaranteed ASCII (curly quotes, em-dashes),
            # so a locale-encoding failure here (UnicodeEncodeError, not an
            # OSError) must not swallow the analysis error the dump exists to
            # record.
            print(f"error: {exc}", file=sys.stderr)
    else:
        print(f"error: {exc}", file=sys.stderr)
    return 1


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _merge_manifest(manifest_path, new_records):
    """Merge this run's records into any existing manifest, keyed by asset id.

    A `build --only` run must not truncate the provenance of ids it didn't
    touch. Records for ids not in this run are preserved; records for ids in
    this run are replaced. A corrupt/unreadable existing manifest must not
    crash the run — fall back to this run's records alone.
    """
    if not manifest_path.exists():
        return new_records
    try:
        existing = json.loads(manifest_path.read_text())
        by_id = {r["id"]: r for r in existing}
    except Exception as exc:
        print(f"warning: existing manifest unreadable ({exc}), "
              "writing only this run's records", file=sys.stderr)
        return new_records
    for rec in new_records:
        by_id[rec["id"]] = rec
    return list(by_id.values())


def cmd_build(args):
    try:
        pack = config.load_pack(
            args.spec, base_url=args.base_url, model=args.model,
            transport=args.transport, out_root=Path(args.out_root),
        )
    except config.SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    targets = select_assets(pack.assets, args.only)

    if args.dry_run:
        for asset in targets:
            # Show what will actually go on the wire, which differs by transport:
            # chat has no structured aspect_ratio field so it's appended to the
            # prompt text; images sends it as a separate JSON field.
            if pack.transport == "images":
                print(f"[{asset.id}] {pack.full_prompt(asset)}  (aspect_ratio={asset.aspect_ratio})")
            else:
                wire_prompt = orclient.chat_prompt_with_ratio(
                    pack.full_prompt(asset), asset.aspect_ratio
                )
                print(f"[{asset.id}] {wire_prompt}")
        print(f"\n{len(targets)} assets, est. ${len(targets) * EST_COST:.2f}")
        return 0

    if _missing_key(pack):
        return 1

    needs_bible = any(a.reference is None for a in targets)
    if needs_bible and not pack.style_bible.exists():
        print(f"error: {pack.style_bible} not found — run `init` then `pick` first",
              file=sys.stderr)
        return 1

    pack.out_dir.mkdir(parents=True, exist_ok=True)
    reference = pack.style_bible.read_bytes() if needs_bible else None

    records = []
    spent = 0.0
    cost_seen = False  # True once any record reports a real cost
    warned_no_cost = False
    stopped_early = False

    for chunk in _chunks(targets, WORKERS):
        if cost_seen and spent >= args.max_cost:
            stopped_early = True
            break
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [(a, pool.submit(build_one, pack, a, reference)) for a in chunk]
            # build_one's contract is "never raises," but this is defence in depth:
            # if it somehow does, that asset degrades to a failed record instead of
            # taking down the whole batch.
            chunk_records = []
            for asset, fut in futures:
                try:
                    chunk_records.append(fut.result())
                except Exception as exc:
                    chunk_records.append(
                        _record(pack, asset, "failed", error=f"internal error: {exc}")
                    )
        for rec in chunk_records:
            records.append(rec)
            print(f"[{rec['id']:<16}] {rec['status']}"
                  + (f" — {rec['error']}" if rec["error"] else ""))
            if rec["status"] == "ok":
                if rec["cost"] is None:
                    # One response missing cost doesn't mean the provider never
                    # reports it — charge the estimate and keep enforcing. Only
                    # a run where NO record ever reports cost disables the
                    # ceiling entirely (see `cost_seen` gate above).
                    if not warned_no_cost:
                        print("warning: cost reporting unavailable for one or more "
                              f"responses; charging the ${EST_COST:.2f} estimate for those")
                        warned_no_cost = True
                    spent += EST_COST
                else:
                    cost_seen = True
                    spent += rec["cost"]

    manifest_ok = True
    try:
        merged = _merge_manifest(pack.manifest_path, records)
        pack.manifest_path.write_text(json.dumps(merged, indent=2))
    except Exception as exc:
        manifest_ok = False
        print(f"error: failed to write manifest: {exc}", file=sys.stderr)

    ok = sum(1 for r in records if r["status"] == "ok")
    failed = [r for r in records if r["status"] == "failed"]
    budget = f"(${spent:.2f} / ${args.max_cost:.2f})" if cost_seen else "(cost unknown)"
    print(f"\ndone: {ok} ok, {len(failed)} failed  {budget}")
    if stopped_early:
        print(f"stopped: cost ceiling ${args.max_cost:.2f} reached, "
              f"{len(targets) - len(records)} assets not requested")
    if failed:
        print("failed: " + ", ".join(f"{r['id']} ({r['error']})" for r in failed))
        print(f"retry: python3 gen.py build {args.spec} --only "
              + ",".join(r["id"] for r in failed))
    # A truncated run (cost ceiling hit) or a failed manifest write means the batch
    # is incomplete or unrecorded, even if every asset that did run succeeded — a
    # caller chaining `&& upload` must not treat that as a clean success.
    return 1 if (failed or stopped_early or not manifest_ok) else 0


def contact_sheet(paths, out_path):
    """Compose candidate images into a 2x2 grid so they can be compared at a glance."""
    images = [Image.open(p).convert("RGB") for p in paths]
    cell_w = max(im.width for im in images)
    cell_h = max(im.height for im in images)
    sheet = Image.new("RGB", (cell_w * 2, cell_h * 2), (24, 24, 24))
    for i, im in enumerate(images):
        sheet.paste(im, ((i % 2) * cell_w, (i // 2) * cell_h))
    sheet.save(out_path)
    for im in images:
        im.close()
    return out_path


def cmd_init(args):
    try:
        pack = config.load_pack(
            args.spec, base_url=args.base_url, model=args.model,
            transport=args.transport, out_root=Path(args.out_root),
        )
    except config.SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not pack.plate_prompt.strip():
        print("error: [style] plate_prompt is empty — it should show a button, "
              "an icon and a character together", file=sys.stderr)
        return 1

    if _missing_key(pack):
        return 1

    pack.candidates_dir.mkdir(parents=True, exist_ok=True)
    prompt = pack.plate_full_prompt()
    written = []
    spent = 0.0
    cost_available = True

    # Sequential on purpose: four requests, and stopping at the ceiling matters
    # more than shaving a few seconds.
    for i in range(PLATE_COUNT):
        if cost_available and spent >= args.max_cost:
            print(f"stopped: cost ceiling ${args.max_cost:.2f} reached")
            break
        try:
            # Plates carry no reference image: this is where the style is born.
            # Use the pack's own default ratio, not a hardcoded "1:1" — a pack
            # whose defaults are e.g. 9:16 must not get a square style bible
            # used as the reference for non-square assets.
            png, cost, _raw = orclient.generate(
                pack, prompt, aspect_ratio=pack.default_aspect_ratio, seed=i
            )
        except (orclient.ApiError, orclient.ImageMissing) as exc:
            print(f"[plate {i}] failed — {exc}", file=sys.stderr)
            continue
        except Exception as exc:  # transport-level surprises: connection reset, DNS, ...
            print(f"[plate {i}] failed — {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        # Named by position among successes, not by loop index `i` — so a mid-
        # sequence failure can't desync the on-disk files from the contact
        # sheet cells (built from `written`) or from the printed pick hint.
        idx = len(written)
        target = pack.candidates_dir / f"{idx}.png"
        target.write_bytes(png)  # raw, no background removal
        written.append(target)
        print(f"[plate {i}] ok -> {idx}.png")
        if cost is None:
            cost_available = False
        else:
            spent += cost

    if not written:
        print("error: no plates were generated", file=sys.stderr)
        return 1

    sheet = contact_sheet(written, pack.candidates_dir / "contact_sheet.png")
    print(f"\n{len(written)} plates → {sheet}")
    print(f"pick one:  python3 gen.py pick {args.spec} <0-{len(written) - 1}>")
    if not args.no_open:
        webbrowser.open(Path(sheet).resolve().as_uri())
    return 0


def cmd_pick(args):
    try:
        pack = config.load_pack(
            args.spec, base_url=args.base_url, model=args.model,
            transport=args.transport, out_root=Path(args.out_root),
        )
    except config.SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    candidate = pack.candidates_dir / f"{args.index}.png"
    if not candidate.exists():
        print(f"error: {candidate} not found — run `init` first", file=sys.stderr)
        return 1

    try:
        pack.out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate, pack.style_bible)
    except OSError as exc:
        print(f"error: cannot write {pack.style_bible}: {exc}", file=sys.stderr)
        return 1
    print(f"style bible locked: {pack.style_bible}")
    print(f"now run:  python3 gen.py build {args.spec}")
    return 0


def cmd_analyze(args):
    try:
        pack = config.load_pack(
            args.pack, base_url=args.base_url, model=args.model,
            transport=args.transport, vision_base_url=args.vision_base_url,
            vision_model=args.vision_model, out_root=Path(args.out_root),
        )
    except config.SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    image_path = Path(args.image)
    try:
        image_bytes = image_path.read_bytes()
    except OSError as exc:
        print(f"error: cannot read {image_path}: {exc}", file=sys.stderr)
        return 1

    # Same check build/init do for [api] key_env, against the vision key instead —
    # analyze always calls the vision endpoint, dry-run included, so this applies
    # unconditionally rather than only outside --dry-run.
    if pack.vision_key_env and pack.vision_api_key() is None:
        print(f"error: ${pack.vision_key_env} is not set", file=sys.stderr)
        return 1

    try:
        schema, _raw = vision.analyze(pack, image_bytes)
    except vision.AnalysisError as exc:
        return _report_analysis_error(exc, image_path)
    except orclient.ApiError as exc:
        print(f"error: vision request failed: {exc}", file=sys.stderr)
        return 1

    prefix = vision.style_prefix(schema)
    repro = vision.reproduction_prompt(schema)

    print("style:")
    for field in vision.STYLE_FIELDS:
        print(f"  {field:<9} {schema['style'][field]}")
    print(f"\nsubject: {schema['subject']}")
    print(f"\n[style] prefix:\n{prefix}")
    print(f"\nreproduction prompt:\n{repro}")

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    try:
        packwriter.update_pack(
            args.pack,
            prefix=prefix,
            # Store subject + form + detail (vision.subject_prompt), matching
            # every other asset in the pack: the style prefix is applied at
            # build time by full_prompt(), not frozen into the asset's own
            # prompt. Embedding `repro` (subject + prefix) would double the
            # style now and freeze a stale copy of it forever, silently
            # drifting from the pack the moment the prefix changes. Subject
            # alone, on the other hand, is too narrow to rebuild the object
            # from — form and detail are what the schema grew those fields
            # for, and this asset is exactly the "one object" they describe.
            new_asset=(args.add_asset, vision.subject_prompt(schema)) if args.add_asset else None,
        )
    except packwriter.PackWriteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"\nwrote [style] prefix -> {args.pack}")
    if args.add_asset:
        print(f"wrote [[assets]] {args.add_asset} -> {args.pack}")

    try:
        pack.out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image_path, pack.style_bible)
    except OSError as exc:
        print(f"error: pack was updated but the style bible could not be written "
              f"({exc}); copy {image_path} to {pack.style_bible} yourself, or "
              "re-run analyze", file=sys.stderr)
        return 1
    print(f"wrote style bible     -> {pack.style_bible}")
    print(f"\nnow run:  python3 gen.py build {args.pack}")
    return 0


def slugify(text: str, limit: int = 40) -> str:
    """A filesystem-safe fragment of `text` for the output filename."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-")
    return s or "sprite"


def cmd_make(args):
    if not args.image and not (args.text or "").strip():
        print("error: give an image (-i), a text (-t), or both", file=sys.stderr)
        return 1

    try:
        pack = config.env_pack(
            base_url=args.base_url, model=args.model, transport=args.transport,
            vision_base_url=args.vision_base_url, vision_model=args.vision_model,
            out_root=Path(args.out_root),
        )
    except config.SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if _missing_key(pack):
        return 1

    # Same check cmd_analyze does, against the vision key instead — only
    # relevant here when an image is actually going to be analysed.
    if args.image and pack.vision_key_env and pack.vision_api_key() is None:
        print(f"error: ${pack.vision_key_env} is not set", file=sys.stderr)
        return 1

    image_path = None
    image_bytes = None
    if args.image:
        image_path = Path(args.image)
        try:
            image_bytes = image_path.read_bytes()
        except OSError as exc:
            print(f"error: cannot read {image_path}: {exc}", file=sys.stderr)
            return 1

    schema = None
    if image_bytes is not None:
        try:
            schema, _raw = vision.analyze(pack, image_bytes, user_text=args.text)
        except vision.AnalysisError as exc:
            return _report_analysis_error(exc, image_path)
        except orclient.ApiError as exc:
            print(f"error: vision request failed: {exc}", file=sys.stderr)
            return 1
        body = vision.object_prompt(schema)
        slug = slugify(schema.get("subject") or args.text or "sprite")
    else:
        # Text only: nothing to analyse, so no vision call and no vision cost.
        body = args.text.strip()
        slug = slugify(args.text)

    prompt = body if args.no_cutout else f"{body} {config.BG_CLAUSE}"

    if schema is not None:
        print("analysis:")
        for field in vision.PROMPT_ORDER:
            value = (schema.get(field) if field in vision.SUBJECT_FIELDS
                     else (schema.get("style") or {}).get(field))
            if value:
                print(f"  {field:<9} {value}")
        print()
    print(f"prompt:\n{prompt}\n")

    if args.dry_run:
        print("dry run: nothing written")
        return 0

    out_dir = pack.out_dir
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"error: cannot create {out_dir}: {exc}", file=sys.stderr)
        return 1

    reference = str(image_path.resolve()) if image_path is not None else None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    spent = 0.0
    cost_seen = False  # True once any variant reports a real cost
    written = failed = 0
    stopped_early = False

    for i in range(args.n):
        if cost_seen and spent >= args.max_cost:
            stopped_early = True
            break
        suffix = f"-{i}" if args.n > 1 else ""
        name = f"{stamp}-{slug}{suffix}"
        try:
            png, cost, _raw = orclient.generate(
                pack, prompt, aspect_ratio=args.aspect_ratio,
                reference_png=image_bytes, seed=i,
            )
        except orclient.ImageMissing as exc:
            try:
                (out_dir / f"{name}.error.json").write_text(json.dumps(exc.raw, indent=2))
                note = f" (see {name}.error.json)"
            except Exception as write_exc:
                note = f" (also failed to write {name}.error.json: {write_exc})"
            print(f"[{name}] failed — no image in response{note}", file=sys.stderr)
            failed += 1
            continue
        except orclient.ApiError as exc:
            print(f"[{name}] failed — {exc}", file=sys.stderr)
            failed += 1
            continue
        except Exception as exc:
            print(f"[{name}] failed — {type(exc).__name__}: {exc}", file=sys.stderr)
            failed += 1
            continue

        # The image is paid for by this point. If post-processing fails, keep the
        # raw file AND still write a sidecar — build_one's reasoning applies here
        # too, and more so: the sidecar is the only provenance `make` has at all.
        target = out_dir / f"{name}.png"
        post_error = None
        try:
            if args.no_cutout:
                target.write_bytes(png)
            else:
                img = post.cut_background(png)
                img = post.trim_and_pad(img)
                img.save(target)
        except Exception as exc:
            try:
                (out_dir / f"{name}.raw.png").write_bytes(png)
                note = f" (raw kept as {name}.raw.png)"
            except Exception as write_exc:
                note = f" (also failed to keep raw png: {write_exc})"
            post_error = f"post-processing: {exc}{note}"
            print(f"[{name}] failed — {post_error}", file=sys.stderr)
            failed += 1

        sidecar = {
            "status": "failed" if post_error else "ok",
            "prompt": prompt, "schema": schema, "model": pack.model,
            "transport": pack.transport, "base_url": pack.base_url,
            "aspect_ratio": args.aspect_ratio, "seed": i, "cost": cost,
            "user_text": args.text, "reference": reference,
            "file": str(target) if post_error is None else None,
            "error": post_error,
        }
        try:
            (out_dir / f"{name}.json").write_text(
                json.dumps(sidecar, indent=2), encoding="utf-8")
        except OSError as exc:
            print(f"[{name}] warning: sidecar not written: {exc}", file=sys.stderr)

        if post_error is None:
            print(f"[{name}] ok -> {target}")
            written += 1
        if cost is not None:
            cost_seen = True
            spent += cost

    budget = f"(${spent:.2f})" if cost_seen else "(cost unknown — --max-cost not enforced)"
    print(f"\ndone: {written} written, {failed} failed  {budget}")
    if stopped_early:
        print(f"stopped: cost ceiling ${args.max_cost:.2f} reached, "
              f"{args.n - (written + failed)} variant(s) not requested")
    # A truncated run (cost ceiling hit) means fewer variants exist than -n asked
    # for, even if every variant that did run succeeded — a caller chaining
    # `&& upload` must not treat that as a clean success (see cmd_build).
    return 1 if (failed or stopped_early or written == 0) else 0


def cmd_extract(args):
    pack_path = Path(args.pack)
    if pack_path.exists():
        # Refuse before spending the vision call. A pack the user has already
        # pruned by hand is the most valuable thing in this flow to lose.
        print(f"error: {pack_path} already exists — delete it or choose another path",
              file=sys.stderr)
        return 1

    image_path = Path(args.image)
    try:
        image_bytes = image_path.read_bytes()
    except OSError as exc:
        print(f"error: cannot read {image_path}: {exc}", file=sys.stderr)
        return 1

    try:
        pack = config.env_pack(
            base_url=args.base_url, model=args.model, transport=args.transport,
            vision_base_url=args.vision_base_url, vision_model=args.vision_model,
            out_root=Path(args.out_root),
        )
    except config.SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if pack.vision_key_env and pack.vision_api_key() is None:
        print(f"error: ${pack.vision_key_env} is not set", file=sys.stderr)
        return 1

    try:
        schema, _raw = vision.analyze_objects(pack, image_bytes)
    except vision.AnalysisError as exc:
        return _report_analysis_error(exc, image_path)
    except orclient.ApiError as exc:
        print(f"error: vision request failed: {exc}", file=sys.stderr)
        return 1

    objects = schema["objects"]
    if len(objects) > args.max_objects:
        print(f"note: {len(objects)} objects found, keeping the first "
              f"{args.max_objects} (raise --max-objects to keep more)")
        objects = objects[: args.max_objects]

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        print(f"error: cannot decode {image_path}: {exc}", file=sys.stderr)
        return 1

    refs_dir = Path(args.refs_dir) if args.refs_dir else pack_path.parent / "refs"

    if args.dry_run:
        print(f"style: {', '.join(schema['style'].get(f, '') for f in vision.STYLE_FIELDS)}\n")
        # Screen exactly as the real run does, so the preview cannot promise an
        # object that extract would then drop.
        accepted, rejected = extract.screen_objects(objects, image.width, image.height)
        for obj in accepted:
            state = "ANIMATED" if obj.get("animated") else "static"
            print(f"  {obj['id']:<20} {state:<9} {','.join(obj.get('views') or [])}")
        for obj_id, reason in rejected:
            print(f"  {obj_id:<20} {'—':<9} REJECT ({reason})")
        print(f"\ndry run: nothing written (would write {pack_path} and {refs_dir})")
        return 0

    try:
        kept, rejected = extract.crop_objects(image, objects, refs_dir)
    except OSError as exc:
        print(f"error: cannot write crops to {refs_dir}: {exc}", file=sys.stderr)
        return 1

    for obj_id, reason in rejected:
        print(f"  dropped {obj_id}: {reason}", file=sys.stderr)

    if not kept:
        print("error: no usable objects — nothing written", file=sys.stderr)
        return 1

    sheet = None
    try:
        sheet = extract.labelled_sheet(kept, refs_dir / "_contact_sheet.png")
    except Exception as exc:
        # The sheet is a review aid, not the deliverable — losing it must not
        # cost the user the crops and the pack they already paid for.
        print(f"warning: contact sheet not written: {exc}", file=sys.stderr)

    text = extract.pack_text(pack.model, pack.key_env, schema["style"], kept, refs_dir, pack_path)
    try:
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write {pack_path}: {exc}", file=sys.stderr)
        return 1

    total = sum(len(o.get("views") or [1]) for o in kept)
    print(f"\n{len(kept)} objects, {total} assets -> {pack_path}")
    print(f"crops -> {refs_dir}")
    if sheet and not args.no_open:
        webbrowser.open(Path(sheet).resolve().as_uri())
    print(f"\nreview the sheet, prune the pack, then:\n"
          f"  python3 gen.py build {pack_path} --dry-run")
    return 0


def _add_endpoint_flags(sub):
    sub.add_argument("--base-url", default=None, help="override [api] base_url")
    sub.add_argument("--model", default=None, help="override [pack] model")
    sub.add_argument("--transport", default=None, choices=config.VALID_TRANSPORTS,
                     help="override [api] transport")
    sub.add_argument("--vision-base-url", default=None,
                     help="override [vision] base_url")
    sub.add_argument("--vision-model", default=None, help="override [vision] model")
    sub.add_argument("--out-root", default="out", help="root output directory")


def _add_common(sub):
    sub.add_argument("spec")
    _add_endpoint_flags(sub)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gen.py", description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)

    build = subs.add_parser("build", help="generate every asset in the spec")
    _add_common(build)
    build.add_argument("--only", default=None, help="comma-separated asset ids")
    build.add_argument("--dry-run", action="store_true",
                       help="print prompts and estimated cost, make no requests")
    build.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST,
                       help=f"USD ceiling (default {DEFAULT_MAX_COST})")
    build.set_defaults(func=cmd_build)

    init = subs.add_parser("init", help="generate style plate candidates")
    _add_common(init)
    init.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST,
                      help=f"USD ceiling (default {DEFAULT_MAX_COST})")
    init.add_argument("--no-open", action="store_true",
                      help="do not open the contact sheet in a browser")
    init.set_defaults(func=cmd_init)

    pick = subs.add_parser("pick", help="lock a candidate as the pack's style bible")
    _add_common(pick)
    pick.add_argument("index", type=int, help="candidate number shown by init")
    pick.set_defaults(func=cmd_pick)

    analyze = subs.add_parser(
        "analyze", help="analyse a reference image into the pack's style prefix")
    analyze.add_argument("image", help="reference image to analyse")
    analyze.add_argument("--pack", required=True, help="spec file to update")
    _add_endpoint_flags(analyze)
    analyze.add_argument("--add-asset", default=None, metavar="ID",
                         help="also append the detected subject as a new asset")
    analyze.add_argument("--dry-run", action="store_true",
                         help="print the analysis, write nothing "
                              "(the vision call is still made and still costs)")
    analyze.set_defaults(func=cmd_analyze)

    make = subs.add_parser(
        "make", help="generate one sprite from an image, a text, or both")
    make.add_argument("-i", "--image", default=None, help="reference image")
    make.add_argument("-t", "--text", default=None,
                      help="what to make; overrides the image where they conflict")
    make.add_argument("-n", type=int, default=1, help="number of variants")
    make.add_argument("--aspect-ratio", default="1:1")
    make.add_argument("--no-cutout", action="store_true",
                      help="whole-image output: no backdrop, no alpha cut, no trim")
    make.add_argument("--dry-run", action="store_true",
                      help="print the analysis and prompt, generate nothing "
                           "(with -i, the vision call is still made and still costs)")
    make.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST,
                      help=f"USD ceiling (default {DEFAULT_MAX_COST})")
    _add_endpoint_flags(make)
    make.set_defaults(func=cmd_make)

    extract_p = subs.add_parser(
        "extract", help="find every sprite in an image and write a buildable pack")
    extract_p.add_argument("-i", "--image", required=True, help="source image")
    extract_p.add_argument("--pack", required=True, help="pack file to create")
    extract_p.add_argument("--refs-dir", default=None,
                           help="where crops go (default: refs/ beside the pack)")
    extract_p.add_argument("--max-objects", type=int,
                           default=extract.DEFAULT_MAX_OBJECTS,
                           help=f"cap (default {extract.DEFAULT_MAX_OBJECTS})")
    extract_p.add_argument("--no-open", action="store_true",
                           help="do not open the contact sheet")
    extract_p.add_argument("--dry-run", action="store_true",
                           help="print what would be written (the vision call is still "
                                "made and still costs)")
    _add_endpoint_flags(extract_p)
    extract_p.set_defaults(func=cmd_extract)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
