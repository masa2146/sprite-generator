"""Build orchestration tests. No network, no rembg. Run: python3 test_build.py"""
import base64
import json
import os
import tempfile
import threading
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path

from PIL import Image

import gen
import orclient
import post
from config import Asset, Pack


def _png(color=(10, 20, 30)):
    """A real 64x64 PNG. init writes plates raw and then opens them with PIL,
    so those tests need bytes PIL can actually decode."""
    buf = BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    return buf.getvalue()

SPEC = """
[api]
base_url = "http://svc/v1"
key_env = ""
transport = "chat"
[pack]
model = "m/model"
[style]
prefix = "styled"
plate_prompt = "a button, an icon, a character"
[[assets]]
id = "btn_play"
prompt = "play button"
[[assets]]
id = "icon_coin"
prompt = "coin icon"
[[assets]]
id = "bg_sky"
prompt = "seamless sky"
cutout = false
"""


def _spec_file(text=SPEC):
    d = Path(tempfile.mkdtemp())
    p = d / "hc_v1.toml"
    p.write_text(text)
    return p


class _Stubs:
    """Replaces generate/cut_background/trim_and_pad for the duration of a test.

    `outcomes` may be:
      - a list: consumed positionally (pop(0), lock-protected). Fine when no
        test assertion cares which asset got which outcome (e.g. plates, or
        outcomes that are all interchangeable).
      - a dict of {asset_id: outcome}: looked up by matching the seed passed
        into generate() against pack.seed_for(id). build_one runs assets
        concurrently under ThreadPoolExecutor, so which thread's fake_generate
        call reaches a shared list first is scheduling-dependent — a plain
        pop(0) cannot promise asset X gets outcome X. Use dict-mode whenever a
        test asserts something id-specific.
    """

    def __init__(self, outcomes):
        self.outcomes = outcomes if isinstance(outcomes, dict) else list(outcomes)
        self._lock = threading.Lock()
        self.prompts = []
        self.references = []
        self.aspect_ratios = []  # aspect_ratio passed into generate(), in call order
        self.cut_calls = []   # bytes passed to post.cut_background, in call order
        self.trim_calls = []  # images passed to post.trim_and_pad, in call order

    def __enter__(self):
        self._orig = (gen.orclient.generate, gen.post.cut_background, gen.post.trim_and_pad)

        def fake_generate(pack, prompt, aspect_ratio=None, reference_png=None, seed=None, **kw):
            self.prompts.append(prompt)
            self.references.append(reference_png)
            self.aspect_ratios.append(aspect_ratio)
            if isinstance(self.outcomes, dict):
                outcome = next(
                    v for aid, v in self.outcomes.items() if pack.seed_for(aid) == seed
                )
            else:
                with self._lock:
                    outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            png, cost = outcome
            return png, cost, {"stub": True}

        def fake_cut(data):
            self.cut_calls.append(data)
            return _Img(data)

        def fake_trim(img, **kw):
            self.trim_calls.append(img)
            return _Img(img.data, trimmed=True)

        gen.orclient.generate = fake_generate
        gen.post.cut_background = fake_cut
        gen.post.trim_and_pad = fake_trim
        return self

    def __exit__(self, *exc):
        gen.orclient.generate, gen.post.cut_background, gen.post.trim_and_pad = self._orig


class _Img:
    """Minimal stand-in for a PIL image: records whether trim ran, writes a file."""

    def __init__(self, data, trimmed=False):
        self.data = data
        self.trimmed = trimmed

    def save(self, path):
        Path(path).write_bytes(self.data + (b"-trimmed" if self.trimmed else b""))


def _manifest(tmp, name="t"):
    return json.loads((Path(tmp) / name / "manifest.json").read_text())


def test_select_assets_filters_by_only_and_preserves_spec_order():
    assets = [Asset(id=i, prompt="p") for i in ("a", "b", "c")]
    assert [a.id for a in gen.select_assets(assets, None)] == ["a", "b", "c"]
    assert [a.id for a in gen.select_assets(assets, "c,a")] == ["a", "c"]


def test_select_assets_rejects_unknown_id():
    assets = [Asset(id="a", prompt="p")]
    try:
        gen.select_assets(assets, "nope")
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert "nope" in str(exc)


def test_dry_run_makes_no_requests():
    spec = _spec_file()
    with _Stubs([]) as stubs:
        code = gen.main(["build", str(spec), "--dry-run"])
    assert code == 0
    assert stubs.prompts == []


def test_dry_run_works_without_a_style_bible():
    """--dry-run must not require init/pick to have been run."""
    spec = _spec_file()
    with _Stubs([]):
        assert gen.main(["build", str(spec), "--dry-run"]) == 0


def test_dry_run_shows_the_chat_transports_wire_prompt():
    """Finding 5: under transport = "chat" the wire prompt has ", aspect ratio
    N:M" appended (orclient.generate does this before posting) — --dry-run must
    show that, not just the bare prompt text, or the printed preview lies about
    what will actually be sent."""
    spec = _spec_file()  # SPEC's [api] transport = "chat"
    with _Stubs([]):
        buf = StringIO()
        with redirect_stdout(buf):
            gen.main(["build", str(spec), "--dry-run"])
    assert "aspect ratio 1:1" in buf.getvalue()


def test_dry_run_shows_the_images_transports_structured_aspect_ratio():
    """Under transport = "images" aspect_ratio is a separate JSON field, never
    appended to the prompt text — the dry-run preview must reflect that."""
    spec = _spec_file(SPEC.replace('transport = "chat"', 'transport = "images"'))
    with _Stubs([]):
        buf = StringIO()
        with redirect_stdout(buf):
            gen.main(["build", str(spec), "--dry-run"])
    out = buf.getvalue()
    assert "aspect_ratio=1:1" in out
    assert "aspect ratio 1:1" not in out


def test_build_without_style_bible_exits_with_error():
    spec = _spec_file()
    tmp = tempfile.mkdtemp()
    with _Stubs([]):
        code = gen.main(["build", str(spec), "--out-root", tmp])
    assert code == 1


def _prepare(tmp, spec_text=SPEC):
    """Create a spec plus a style_bible so build can run."""
    spec = _spec_file(spec_text)
    bible = Path(tmp) / "hc_v1" / "style_bible.png"
    bible.parent.mkdir(parents=True, exist_ok=True)
    bible.write_bytes(b"BIBLE")
    return spec


def test_build_writes_png_per_asset_and_a_manifest():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", 0.04), (b"B", 0.04), (b"C", 0.04)]) as stubs:
        code = gen.main(["build", str(spec), "--out-root", tmp])
    assert code == 0
    out = Path(tmp) / "hc_v1"
    assert (out / "btn_play.png").exists()
    assert (out / "icon_coin.png").exists()
    records = _manifest(tmp, "hc_v1")
    assert [r["id"] for r in records] == ["btn_play", "icon_coin", "bg_sky"]
    assert all(r["status"] == "ok" for r in records)
    assert all(r["cost"] == 0.04 for r in records)
    # Every asset in SPEC has aspect_ratio "1:1" (no [defaults] override, no
    # per-asset override) — proves build_one actually threads asset.aspect_ratio
    # into generate() rather than dropping it silently.
    assert stubs.aspect_ratios == ["1:1", "1:1", "1:1"]


def test_build_sends_style_bible_as_reference_on_every_request():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", 0.0), (b"B", 0.0), (b"C", 0.0)]) as stubs:
        gen.main(["build", str(spec), "--out-root", tmp])
    assert stubs.references == [b"BIBLE", b"BIBLE", b"BIBLE"]


def test_build_skips_cutout_pipeline_when_asset_sets_cutout_false():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    outcomes = {"btn_play": (b"A", 0.0), "icon_coin": (b"B", 0.0), "bg_sky": (b"C", 0.0)}
    with _Stubs(outcomes) as stubs:
        gen.main(["build", str(spec), "--out-root", tmp])
    out = Path(tmp) / "hc_v1"
    assert (out / "btn_play.png").read_bytes() == b"A-trimmed"
    assert (out / "bg_sky.png").read_bytes() == b"C"  # cutout = false: saved raw
    # cutout = false must skip both cut_background and trim_and_pad entirely,
    # not just skip the trim step — only the two cutout=true assets call them.
    assert len(stubs.cut_calls) == 2
    assert len(stubs.trim_calls) == 2


def test_one_failing_asset_does_not_stop_the_others():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    outcomes = {
        "btn_play": (b"A", 0.04),
        "icon_coin": orclient.ApiError("HTTP 429", 429),
        "bg_sky": (b"C", 0.04),
    }
    with _Stubs(outcomes):
        code = gen.main(["build", str(spec), "--out-root", tmp])
    assert code == 1  # non-zero because something failed
    records = {r["id"]: r for r in _manifest(tmp, "hc_v1")}
    assert records["btn_play"]["status"] == "ok"
    assert records["icon_coin"]["status"] == "failed"
    assert "429" in records["icon_coin"]["error"]
    assert records["bg_sky"]["status"] == "ok"


def test_missing_image_in_response_writes_error_json():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    outcomes = {
        "btn_play": orclient.ImageMissing({"choices": [{"message": {"content": "refused"}}]}),
        "icon_coin": (b"B", 0.0),
        "bg_sky": (b"C", 0.0),
    }
    with _Stubs(outcomes):
        gen.main(["build", str(spec), "--out-root", tmp])
    dumped = json.loads((Path(tmp) / "hc_v1" / "btn_play.error.json").read_text())
    assert dumped["choices"][0]["message"]["content"] == "refused"


def test_post_processing_failure_keeps_the_raw_png():
    """A generated image is paid for; never throw it away."""
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    outcomes = {"btn_play": (b"RAW", 0.04), "icon_coin": (b"B", 0.0), "bg_sky": (b"C", 0.0)}
    with _Stubs(outcomes) as stubs:
        def boom(data):
            raise RuntimeError("shape error")
        gen.post.cut_background = boom
        gen.main(["build", str(spec), "--out-root", tmp])
    assert (Path(tmp) / "hc_v1" / "btn_play.raw.png").read_bytes() == b"RAW"
    records = {r["id"]: r for r in _manifest(tmp, "hc_v1")}
    assert records["btn_play"]["status"] == "failed"
    assert "shape error" in records["btn_play"]["error"]


def test_error_json_write_failure_still_yields_a_failed_record():
    """Finding 1: if writing {id}.error.json itself fails, build_one must still
    return a failed record instead of letting the exception escape the batch."""
    tmp = tempfile.mkdtemp()
    pack = Pack(
        name="t", base_url="http://svc/v1", key_env="", model="m/model",
        style_prefix="styled", plate_prompt="plate",
        assets=[], out_root=Path(tmp),
    )
    pack.out_dir.mkdir(parents=True, exist_ok=True)
    # "/" in the id makes out_dir / f"{id}.error.json" address a subdirectory that
    # was never created, so the write raises FileNotFoundError.
    asset = Asset(id="bad/nested", prompt="p")
    with _Stubs([orclient.ImageMissing({"choices": []})]):
        rec = gen.build_one(pack, asset, b"BIBLE")
    assert rec["status"] == "failed"
    assert "no image in response" in rec["error"]
    assert "failed to write" in rec["error"]


def test_budget_ceiling_stops_before_the_next_request():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    # The ceiling is checked between chunks, so force chunks of one to observe it
    # precisely. With WORKERS=4 all three assets would fit in a single chunk.
    original_workers = gen.WORKERS
    gen.WORKERS = 1
    try:
        with _Stubs([(b"A", 0.04), (b"B", 0.04), (b"C", 0.04)]) as stubs:
            code = gen.main(["build", str(spec), "--out-root", tmp, "--max-cost", "0.05"])
    finally:
        gen.WORKERS = original_workers
    assert len(stubs.prompts) == 2  # spent 0.08 after two, third never requested
    records = _manifest(tmp, "hc_v1")
    assert len(records) == 2  # manifest still written for what did run
    assert code == 1  # truncated run is not a clean success, even with 0 failures


def test_missing_api_key_exits_before_any_request():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp, SPEC.replace('key_env = ""', 'key_env = "ABSENT_KEY_VAR"'))
    os.environ.pop("ABSENT_KEY_VAR", None)
    with _Stubs([]) as stubs:
        code = gen.main(["build", str(spec), "--out-root", tmp])
    assert code == 1
    assert stubs.prompts == []


def test_dry_run_does_not_require_an_api_key():
    spec = _spec_file(SPEC.replace('key_env = ""', 'key_env = "ABSENT_KEY_VAR"'))
    os.environ.pop("ABSENT_KEY_VAR", None)
    with _Stubs([]):
        assert gen.main(["build", str(spec), "--dry-run"]) == 0


def test_missing_cost_disables_the_ceiling_and_warns_once():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", None), (b"B", None), (b"C", None)]) as stubs:
        code = gen.main(["build", str(spec), "--out-root", tmp, "--max-cost", "0.01"])
    assert code == 0
    assert len(stubs.prompts) == 3  # ceiling could not be enforced, ran everything
    assert all(r["cost"] is None for r in _manifest(tmp, "hc_v1"))


def test_mixed_cost_reporting_keeps_ceiling_enforced_via_estimate():
    """One cost-less response must not permanently disable --max-cost — only a
    provider that NEVER reports cost should. Force chunks of one (WORKERS=1) so
    the mid-run behaviour is observable in order: a real cost, then a missing
    one (charged at EST_COST), then the ceiling must still bite."""
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    original_workers = gen.WORKERS
    gen.WORKERS = 1
    try:
        outcomes = [(b"A", 0.04), (b"B", None), (b"C", 0.04)]
        with _Stubs(outcomes) as stubs:
            code = gen.main(["build", str(spec), "--out-root", tmp, "--max-cost", "0.06"])
    finally:
        gen.WORKERS = original_workers
    # 0.04 (real) + 0.04 (EST_COST estimate for the missing one) = 0.08 >= 0.06:
    # the ceiling still stops the run, proving the latch didn't disable it.
    assert len(stubs.prompts) == 2
    assert code == 1


def test_only_flag_limits_the_build_to_named_assets():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", 0.04)]) as stubs:
        gen.main(["build", str(spec), "--out-root", tmp, "--only", "btn_play"])
    assert len(stubs.prompts) == 1
    assert [r["id"] for r in _manifest(tmp, "hc_v1")] == ["btn_play"]


def test_only_run_preserves_other_ids_in_the_manifest():
    """A full build then a `--only` follow-up must not truncate the manifest to
    just the ids touched by the follow-up — that's the tool's own recommended
    retry command, so losing provenance there is the normal recovery path."""
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", 0.04), (b"B", 0.04), (b"C", 0.04)]):
        gen.main(["build", str(spec), "--out-root", tmp])
    with _Stubs([(b"A2", 0.04)]):
        code = gen.main(["build", str(spec), "--out-root", tmp, "--only", "btn_play"])
    assert code == 0
    records = {r["id"]: r for r in _manifest(tmp, "hc_v1")}
    assert set(records) == {"btn_play", "icon_coin", "bg_sky"}  # nothing dropped
    assert records["btn_play"]["cost"] == 0.04  # replaced by this run
    assert records["icon_coin"]["status"] == "ok"  # preserved from the prior run
    assert records["bg_sky"]["status"] == "ok"


def test_only_run_falls_back_gracefully_when_the_existing_manifest_is_corrupt():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    manifest = Path(tmp) / "hc_v1" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("{not valid json")
    with _Stubs([(b"A", 0.04)]):
        code = gen.main(["build", str(spec), "--out-root", tmp, "--only", "btn_play"])
    assert code == 0  # a corrupt existing manifest must not crash the run
    assert [r["id"] for r in _manifest(tmp, "hc_v1")] == ["btn_play"]


def test_manifest_records_carry_full_provenance():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", 0.04), (b"B", 0.04), (b"C", 0.04)]):
        gen.main(["build", str(spec), "--out-root", tmp])
    rec = _manifest(tmp, "hc_v1")[0]
    for key in ("id", "status", "prompt", "model", "base_url", "transport",
                "aspect_ratio", "seed", "cost", "file", "error"):
        assert key in rec, key
    assert rec["model"] == "m/model"
    assert rec["base_url"] == "http://svc/v1"
    assert rec["transport"] == "chat"  # SPEC's [api] transport
    assert rec["aspect_ratio"] == "1:1"
    assert "play button" in rec["prompt"]
    assert "#808080" in rec["prompt"]  # BG_CLAUSE made it in


def test_bad_spec_exits_cleanly_without_a_traceback():
    bad = _spec_file("[pack]\nmodel = 'm'\n")  # no assets
    assert gen.main(["build", str(bad)]) == 1


# --- init / pick -----------------------------------------------------------

# Distinct real PNGs, so contact_sheet can decode them and so we can tell which
# plate `pick` chose by comparing bytes.
PLATES = [_png((i * 60, 0, 0)) for i in range(4)]


def _plate_outcomes(cost=0.0, count=4):
    return [(PLATES[i], cost) for i in range(count)]


def test_init_generates_four_plates_and_a_contact_sheet():
    tmp = tempfile.mkdtemp()
    spec = _spec_file()
    with _Stubs(_plate_outcomes(0.04)) as stubs:
        code = gen.main(["init", str(spec), "--out-root", tmp, "--no-open"])
    assert code == 0
    cand = Path(tmp) / "hc_v1" / "style_candidates"
    assert sorted(p.name for p in cand.glob("*.png")) == [
        "0.png", "1.png", "2.png", "3.png", "contact_sheet.png",
    ]
    assert len(stubs.prompts) == 4


def test_init_sends_no_reference_and_uses_the_plate_prompt():
    tmp = tempfile.mkdtemp()
    spec = _spec_file()
    with _Stubs(_plate_outcomes()) as stubs:
        gen.main(["init", str(spec), "--out-root", tmp, "--no-open"])
    assert stubs.references == [None, None, None, None]
    assert all("a button, an icon, a character" in p for p in stubs.prompts)
    assert all("#808080" in p for p in stubs.prompts)
    assert stubs.aspect_ratios == ["1:1", "1:1", "1:1", "1:1"]  # SPEC has no [defaults]


def test_init_uses_the_packs_default_aspect_ratio_not_hardcoded_1_1():
    """Finding 6: cmd_init used to hardcode aspect_ratio="1:1" for every plate,
    regardless of what the pack's own [defaults] said. A pack whose defaults
    are 9:16 would get a square style bible used as the reference for
    non-square assets."""
    tmp = tempfile.mkdtemp()
    spec = _spec_file(SPEC.replace("[style]", '[defaults]\naspect_ratio = "9:16"\n[style]'))
    with _Stubs(_plate_outcomes()) as stubs:
        gen.main(["init", str(spec), "--out-root", tmp, "--no-open"])
    assert stubs.aspect_ratios == ["9:16", "9:16", "9:16", "9:16"]


def test_init_plates_are_saved_raw_without_background_removal():
    tmp = tempfile.mkdtemp()
    spec = _spec_file()
    with _Stubs(_plate_outcomes()):
        gen.main(["init", str(spec), "--out-root", tmp, "--no-open"])
    saved = (Path(tmp) / "hc_v1" / "style_candidates" / "0.png").read_bytes()
    assert saved == PLATES[0]  # byte-identical: nothing was post-processed


def test_init_respects_the_cost_ceiling():
    tmp = tempfile.mkdtemp()
    spec = _spec_file()
    with _Stubs(_plate_outcomes(0.04, count=2)) as stubs:
        code = gen.main(["init", str(spec), "--out-root", tmp, "--no-open",
                         "--max-cost", "0.05"])
    assert len(stubs.prompts) == 2  # spent 0.08 after two, third never requested
    assert code == 0


def test_init_survives_a_mid_sequence_plate_failure_and_stays_in_sync():
    """Plate 1 fails (with a bare transport exception, proving cmd_init's except
    arm also catches Exception, not just ApiError/ImageMissing). The surviving
    files must be named contiguously (0.png, 1.png, ...) by position among
    successes, not by loop index, and the contact sheet cell order must match —
    otherwise the printed <0-N> hint and the sheet disagree with what's on disk."""
    tmp = tempfile.mkdtemp()
    spec = _spec_file()
    outcomes = [(PLATES[0], 0.0), ConnectionError("boom"), (PLATES[2], 0.0), (PLATES[3], 0.0)]
    with _Stubs(outcomes) as stubs:
        code = gen.main(["init", str(spec), "--out-root", tmp, "--no-open"])
    assert code == 0
    assert len(stubs.prompts) == 4  # all four plates were attempted

    cand = Path(tmp) / "hc_v1" / "style_candidates"
    assert sorted(p.name for p in cand.glob("*.png")) == [
        "0.png", "1.png", "2.png", "contact_sheet.png",
    ]  # contiguous: no gap left by the failed plate
    assert (cand / "0.png").read_bytes() == PLATES[0]
    assert (cand / "1.png").read_bytes() == PLATES[2]
    assert (cand / "2.png").read_bytes() == PLATES[3]

    # Cell order in the sheet must match file order: PLATES colors are
    # (i*60, 0, 0), distinct enough to read back from the composed grid.
    with Image.open(cand / "contact_sheet.png") as sheet:
        cell_w, cell_h = sheet.width // 2, sheet.height // 2
        assert sheet.getpixel((cell_w // 2, cell_h // 2))[:3] == (0, 0, 0)      # PLATES[0]
        assert sheet.getpixel((cell_w + cell_w // 2, cell_h // 2))[:3] == (120, 0, 0)  # PLATES[2]
        assert sheet.getpixel((cell_w // 2, cell_h + cell_h // 2))[:3] == (180, 0, 0)  # PLATES[3]


def test_pick_copies_the_chosen_candidate_to_style_bible():
    tmp = tempfile.mkdtemp()
    spec = _spec_file()
    with _Stubs(_plate_outcomes()):
        gen.main(["init", str(spec), "--out-root", tmp, "--no-open"])
    assert gen.main(["pick", str(spec), "2", "--out-root", tmp]) == 0
    assert (Path(tmp) / "hc_v1" / "style_bible.png").read_bytes() == PLATES[2]


def test_pick_rejects_an_out_of_range_index():
    tmp = tempfile.mkdtemp()
    spec = _spec_file()
    with _Stubs(_plate_outcomes()):
        gen.main(["init", str(spec), "--out-root", tmp, "--no-open"])
    assert gen.main(["pick", str(spec), "9", "--out-root", tmp]) == 1


def test_pick_without_init_exits_with_error():
    tmp = tempfile.mkdtemp()
    assert gen.main(["pick", str(_spec_file()), "0", "--out-root", tmp]) == 1


def test_build_runs_after_init_and_pick():
    """End-to-end wiring: the bible written by pick is the reference build sends."""
    tmp = tempfile.mkdtemp()
    spec = _spec_file()
    with _Stubs(_plate_outcomes()):
        gen.main(["init", str(spec), "--out-root", tmp, "--no-open"])
    gen.main(["pick", str(spec), "1", "--out-root", tmp])
    with _Stubs([(b"A", 0.0), (b"B", 0.0), (b"C", 0.0)]) as stubs:
        code = gen.main(["build", str(spec), "--out-root", tmp])
    assert code == 0
    assert stubs.references == [PLATES[1], PLATES[1], PLATES[1]]


def test_contact_sheet_is_a_two_by_two_grid():
    tmp = Path(tempfile.mkdtemp())
    paths = []
    for i in range(4):
        p = tmp / f"{i}.png"
        Image.new("RGB", (100, 100), (i * 60, 0, 0)).save(p)
        paths.append(p)
    sheet = gen.contact_sheet(paths, tmp / "sheet.png")
    with Image.open(sheet) as img:
        assert img.size == (200, 200)


def test_contact_sheet_handles_fewer_than_four_plates():
    """init stops early on a cost ceiling, so the sheet must cope with 2 images."""
    tmp = Path(tempfile.mkdtemp())
    paths = []
    for i in range(2):
        p = tmp / f"{i}.png"
        Image.new("RGB", (100, 100), (0, i * 60, 0)).save(p)
        paths.append(p)
    sheet = gen.contact_sheet(paths, tmp / "sheet.png")
    with Image.open(sheet) as img:
        assert img.size == (200, 200)


# --- real seam: orclient <-> gen -------------------------------------------

def test_real_generate_and_trim_and_pad_run_end_to_end_through_build():
    """Every other test in this file stubs orclient.generate directly, so
    `fake_generate`'s hand-written signature is the only thing asserting the
    orclient <-> gen contract — a real signature drift would sail through all
    other tests untouched. This one stubs only requests.post (network) and
    post.cut_background (avoids downloading rembg weights), and runs a real
    `build --only` through the real config.load_pack, orclient.generate and
    post.trim_and_pad."""
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)

    subject = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    subject.paste((200, 30, 30, 255), (10, 10, 30, 30))
    buf = BytesIO()
    subject.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    class _FakeResp:
        status_code = 200

        def json(self):
            return {
                "choices": [{"message": {"images": [
                    {"image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]}}],
                "usage": {"cost": 0.04},
            }

    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(url)
        return _FakeResp()

    original_post = orclient.requests.post
    original_cut = post.cut_background
    orclient.requests.post = fake_post
    # Real cut_background needs rembg weights; stand in with a plain decode so
    # trim_and_pad (real, unstubbed) still has real alpha geometry to crop.
    post.cut_background = lambda data: Image.open(BytesIO(data)).convert("RGBA")
    try:
        code = gen.main(["build", str(spec), "--out-root", tmp, "--only", "btn_play"])
    finally:
        orclient.requests.post = original_post
        post.cut_background = original_cut

    assert code == 0
    assert calls == ["http://svc/v1/chat/completions"]
    out_png = Path(tmp) / "hc_v1" / "btn_play.png"
    assert out_png.exists()
    with Image.open(out_png) as img:
        assert img.mode == "RGBA"
        assert img.getpixel((0, 0))[3] == 0  # transparent corner survives trim/pad


SPEC_IMAGES = """
[api]
base_url = "http://svc/v1"
key_env = ""
transport = "images"
[pack]
model = "m/model"
[style]
prefix = "styled"
plate_prompt = "a button, an icon, a character"
[[assets]]
id = "btn_play"
prompt = "play button"
aspect_ratio = "3:4"
[[assets]]
id = "icon_coin"
prompt = "coin icon"
[[assets]]
id = "bg_sky"
prompt = "seamless sky"
cutout = false
"""


def test_real_generate_through_build_on_images_transport_posts_aspect_ratio():
    """Finding 2: the images transport is the default real users get, and
    aspect_ratio wiring through gen.py had zero coverage on it — every other
    test in this file stubs orclient.generate directly, and the one real-seam
    test (above) only exercises transport = "chat". Mirrors that test but on
    the images transport, with an images-shaped fake response, and asserts the
    posted URL is .../images and the posted JSON's aspect_ratio equals the
    asset's ratio — the thing a mutation that deletes
    `aspect_ratio=asset.aspect_ratio` from build_one must break."""
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp, SPEC_IMAGES)

    subject = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    subject.paste((200, 30, 30, 255), (10, 10, 30, 30))
    buf = BytesIO()
    subject.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"data": [{"b64_json": b64}], "usage": {"cost": 0.04}}

    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json))
        return _FakeResp()

    original_post = orclient.requests.post
    original_cut = post.cut_background
    orclient.requests.post = fake_post
    post.cut_background = lambda data: Image.open(BytesIO(data)).convert("RGBA")
    try:
        code = gen.main(["build", str(spec), "--out-root", tmp, "--only", "btn_play"])
    finally:
        orclient.requests.post = original_post
        post.cut_background = original_cut

    assert code == 0
    assert len(calls) == 1
    url, posted_json = calls[0]
    assert url == "http://svc/v1/images"
    assert posted_json["aspect_ratio"] == "3:4"  # btn_play's own aspect_ratio
    out_png = Path(tmp) / "hc_v1" / "btn_play.png"
    assert out_png.exists()
    with Image.open(out_png) as img:
        assert img.mode == "RGBA"
        assert img.getpixel((0, 0))[3] == 0  # transparent corner survives trim/pad


# --- analyze ----------------------------------------------------------------

ANALYSIS_SCHEMA = {
    "style": {
        "render": "soft 3D render, glossy plastic",
        "camera": "3/4 front view",
        "lighting": "top-left key light",
        "palette": "#FF6B4A #4ECDC4",
        "linework": "no outline, rounded geometry",
        "realism": "stylized cartoon",
    },
    "subject": "gold coin icon, front view, thick rim",
}


class _VisionStub:
    """Replaces vision.analyze for the duration of a test."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.images = []

    def __enter__(self):
        self._orig = gen.vision.analyze

        def fake(pack, image_bytes, **kw):
            self.images.append(image_bytes)
            if self.error:
                raise self.error
            return self.result, json.dumps(self.result)

        gen.vision.analyze = fake
        return self

    def __exit__(self, *exc):
        gen.vision.analyze = self._orig


def _analyze_pack(tmp):
    """A spec on disk plus a reference image; returns (spec_path, image_path)."""
    spec = _spec_file(SPEC)
    img = Path(tmp) / "ref.png"
    img.write_bytes(_png((7, 8, 9)))
    return spec, img


def test_analyze_dry_run_writes_nothing():
    tmp = tempfile.mkdtemp()
    spec, img = _analyze_pack(tmp)
    before = spec.read_text()
    with _VisionStub(result=ANALYSIS_SCHEMA):
        code = gen.main(["analyze", str(img), "--pack", str(spec),
                         "--out-root", tmp, "--dry-run"])
    assert code == 0
    assert spec.read_text() == before
    assert not (Path(tmp) / "hc_v1" / "style_bible.png").exists()


def test_analyze_writes_the_style_prefix():
    tmp = tempfile.mkdtemp()
    spec, img = _analyze_pack(tmp)
    with _VisionStub(result=ANALYSIS_SCHEMA):
        code = gen.main(["analyze", str(img), "--pack", str(spec), "--out-root", tmp])
    assert code == 0
    import tomllib
    with open(spec, "rb") as fh:
        written = tomllib.load(fh)["style"]["prefix"]
    assert "soft 3D render, glossy plastic" in written
    assert ANALYSIS_SCHEMA["subject"] not in written   # subject must not leak in


def test_analyze_copies_the_image_as_the_style_bible():
    tmp = tempfile.mkdtemp()
    spec, img = _analyze_pack(tmp)
    with _VisionStub(result=ANALYSIS_SCHEMA):
        gen.main(["analyze", str(img), "--pack", str(spec), "--out-root", tmp])
    bible = Path(tmp) / "hc_v1" / "style_bible.png"
    assert bible.read_bytes() == img.read_bytes()


def test_analyze_style_bible_write_failure_reports_the_partial_state():
    """The pack write happens before the style-bible copy; if the copy then
    fails, the pack is already updated on disk. That must be reported plainly
    (not a bare traceback) and the run must still exit 1."""
    tmp = tempfile.mkdtemp()
    spec, img = _analyze_pack(tmp)
    # A file where a directory is expected: mkdir(parents=True) under it raises
    # NotADirectoryError (a real OSError), no mocking needed.
    blocker = Path(tmp) / "blocker"
    blocker.write_text("not a directory")
    with _VisionStub(result=ANALYSIS_SCHEMA):
        code = gen.main(["analyze", str(img), "--pack", str(spec),
                         "--out-root", str(blocker)])
    assert code == 1
    import tomllib
    with open(spec, "rb") as fh:
        written = tomllib.load(fh)["style"]["prefix"]
    assert "soft 3D render, glossy plastic" in written  # the pack write did land
    assert not (blocker / "hc_v1" / "style_bible.png").exists()


def test_analyze_add_asset_appends_the_subject():
    tmp = tempfile.mkdtemp()
    spec, img = _analyze_pack(tmp)
    with _VisionStub(result=ANALYSIS_SCHEMA):
        code = gen.main(["analyze", str(img), "--pack", str(spec),
                         "--out-root", tmp, "--add-asset", "coin_ref"])
    assert code == 0
    import tomllib
    with open(spec, "rb") as fh:
        assets = tomllib.load(fh)["assets"]
    assert assets[-1]["id"] == "coin_ref"
    assert assets[-1]["prompt"].startswith(ANALYSIS_SCHEMA["subject"])


def test_analyze_without_add_asset_leaves_assets_alone():
    tmp = tempfile.mkdtemp()
    spec, img = _analyze_pack(tmp)
    import tomllib
    with open(spec, "rb") as fh:
        before = len(tomllib.load(fh)["assets"])
    with _VisionStub(result=ANALYSIS_SCHEMA):
        gen.main(["analyze", str(img), "--pack", str(spec), "--out-root", tmp])
    with open(spec, "rb") as fh:
        assert len(tomllib.load(fh)["assets"]) == before


def test_analyze_duplicate_asset_id_fails_without_writing():
    tmp = tempfile.mkdtemp()
    spec, img = _analyze_pack(tmp)
    before = spec.read_text()
    with _VisionStub(result=ANALYSIS_SCHEMA):
        code = gen.main(["analyze", str(img), "--pack", str(spec),
                         "--out-root", tmp, "--add-asset", "btn_play"])
    assert code == 1
    assert spec.read_text() == before


def test_analyze_missing_image_exits_cleanly():
    tmp = tempfile.mkdtemp()
    spec, _ = _analyze_pack(tmp)
    with _VisionStub(result=ANALYSIS_SCHEMA):
        code = gen.main(["analyze", str(Path(tmp) / "nope.png"),
                         "--pack", str(spec), "--out-root", tmp])
    assert code == 1


def test_analyze_failure_writes_the_raw_reply_and_leaves_the_pack_alone():
    tmp = tempfile.mkdtemp()
    spec, img = _analyze_pack(tmp)
    before = spec.read_text()
    err = gen.vision.AnalysisError("no JSON object found in the reply",
                                   raw="I cannot analyze this image.")
    with _VisionStub(error=err):
        code = gen.main(["analyze", str(img), "--pack", str(spec), "--out-root", tmp])
    assert code == 1
    assert spec.read_text() == before
    dump = img.with_suffix(".png.analysis-error.txt")
    assert "I cannot analyze this image." in dump.read_text()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all build tests passed")
