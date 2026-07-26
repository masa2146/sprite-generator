"""Sprite generator CLI.

Commands:
    init <spec>   generate style plate candidates
    pick <spec> N lock candidate N as the pack's style bible
    build <spec>  generate every asset in the spec
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

import config
import orclient
import post

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

    if not pack.style_bible.exists():
        print(f"error: {pack.style_bible} not found — run `init` then `pick` first",
              file=sys.stderr)
        return 1

    pack.out_dir.mkdir(parents=True, exist_ok=True)
    reference = pack.style_bible.read_bytes()

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

    pack.out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate, pack.style_bible)
    print(f"style bible locked: {pack.style_bible}")
    print(f"now run:  python3 gen.py build {args.spec}")
    return 0


def _add_common(sub):
    sub.add_argument("spec")
    sub.add_argument("--base-url", default=None, help="override [api] base_url")
    sub.add_argument("--model", default=None, help="override [pack] model")
    sub.add_argument("--transport", default=None, choices=config.VALID_TRANSPORTS,
                      help="override [api] transport")
    sub.add_argument("--out-root", default="out", help="root output directory")


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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
