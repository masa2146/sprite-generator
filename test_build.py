"""Build orchestration tests. No network, no rembg. Run: python test_build.py"""
import json
import os
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image

import gen
import orclient
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
trim = false
"""


def _spec_file(text=SPEC):
    d = Path(tempfile.mkdtemp())
    p = d / "hc_v1.toml"
    p.write_text(text)
    return p


class _Stubs:
    """Replaces generate/cut_background/trim_and_pad for the duration of a test."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)  # each is (png, cost) or an Exception
        self.prompts = []
        self.references = []

    def __enter__(self):
        self._orig = (gen.orclient.generate, gen.post.cut_background, gen.post.trim_and_pad)

        def fake_generate(pack, prompt, reference_png=None, seed=None, **kw):
            self.prompts.append(prompt)
            self.references.append(reference_png)
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            png, cost = outcome
            return png, cost, {"stub": True}

        gen.orclient.generate = fake_generate
        gen.post.cut_background = lambda data: _Img(data)
        gen.post.trim_and_pad = lambda img, **kw: _Img(img.data, trimmed=True)
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
    with _Stubs([(b"A", 0.04), (b"B", 0.04), (b"C", 0.04)]):
        code = gen.main(["build", str(spec), "--out-root", tmp])
    assert code == 0
    out = Path(tmp) / "hc_v1"
    assert (out / "btn_play.png").exists()
    assert (out / "icon_coin.png").exists()
    records = _manifest(tmp, "hc_v1")
    assert [r["id"] for r in records] == ["btn_play", "icon_coin", "bg_sky"]
    assert all(r["status"] == "ok" for r in records)
    assert all(r["cost"] == 0.04 for r in records)


def test_build_sends_style_bible_as_reference_on_every_request():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", 0.0), (b"B", 0.0), (b"C", 0.0)]) as stubs:
        gen.main(["build", str(spec), "--out-root", tmp])
    assert stubs.references == [b"BIBLE", b"BIBLE", b"BIBLE"]


def test_build_skips_trim_when_asset_sets_trim_false():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", 0.0), (b"B", 0.0), (b"C", 0.0)]):
        gen.main(["build", str(spec), "--out-root", tmp])
    out = Path(tmp) / "hc_v1"
    assert (out / "btn_play.png").read_bytes() == b"A-trimmed"
    assert (out / "bg_sky.png").read_bytes() == b"C"  # trim = false


def test_one_failing_asset_does_not_stop_the_others():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    outcomes = [(b"A", 0.04), orclient.ApiError("HTTP 429", 429), (b"C", 0.04)]
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
    outcomes = [
        orclient.ImageMissing({"choices": [{"message": {"content": "refused"}}]}),
        (b"B", 0.0), (b"C", 0.0),
    ]
    with _Stubs(outcomes):
        gen.main(["build", str(spec), "--out-root", tmp])
    dumped = json.loads((Path(tmp) / "hc_v1" / "btn_play.error.json").read_text())
    assert dumped["choices"][0]["message"]["content"] == "refused"


def test_post_processing_failure_keeps_the_raw_png():
    """A generated image is paid for; never throw it away."""
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"RAW", 0.04), (b"B", 0.0), (b"C", 0.0)]) as stubs:
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


def test_only_flag_limits_the_build_to_named_assets():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", 0.04)]) as stubs:
        gen.main(["build", str(spec), "--out-root", tmp, "--only", "btn_play"])
    assert len(stubs.prompts) == 1
    assert [r["id"] for r in _manifest(tmp, "hc_v1")] == ["btn_play"]


def test_manifest_records_carry_full_provenance():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", 0.04), (b"B", 0.04), (b"C", 0.04)]):
        gen.main(["build", str(spec), "--out-root", tmp])
    rec = _manifest(tmp, "hc_v1")[0]
    for key in ("id", "status", "prompt", "model", "base_url", "seed", "cost", "file", "error"):
        assert key in rec, key
    assert rec["model"] == "m/model"
    assert rec["base_url"] == "http://svc/v1"
    assert "play button" in rec["prompt"]
    assert "#FF00FF" in rec["prompt"]  # BG_CLAUSE made it in


def test_bad_spec_exits_cleanly_without_a_traceback():
    bad = _spec_file("[pack]\nmodel = 'm'\n")  # no assets
    assert gen.main(["build", str(bad)]) == 1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all build tests passed")
