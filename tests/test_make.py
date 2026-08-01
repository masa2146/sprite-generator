"""`make` command tests. No network, no rembg. Run: python3 -m pytest tests/test_make.py"""
import base64
import json
import os
import tempfile
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path

from PIL import Image

from spritegen import cli
from spritegen import orclient
from spritegen import post


def _png(color=(10, 20, 30)):
    buf = BytesIO()
    Image.new("RGB", (32, 32), color).save(buf, format="PNG")
    return buf.getvalue()


SCHEMA = {
    "style": {
        "render": "soft 3D render, glossy plastic",
        "camera": "3/4 front view",
        "lighting": "top-left key light",
        "palette": "#FF6B4A #4ECDC4",
        "linework": "no outline, rounded geometry",
        "realism": "stylized cartoon",
    },
    "form": "two stacked parts, a ribbed panel above a rounded box",
    "detail": "thick bevelled rim",
    "subject": "a small launcher chute",
}


class _Img:
    """Stands in for a PIL image: records whether trim ran, writes a file."""

    def __init__(self, data, trimmed=False):
        self.data = data
        self.trimmed = trimmed

    def save(self, path):
        Path(path).write_bytes(self.data + (b"-trimmed" if self.trimmed else b""))


class _Stubs:
    """Swaps vision.analyze, orclient.generate and both post functions."""

    def __init__(self, schema=SCHEMA, outcomes=None, analyze_error=None):
        self.schema = schema
        self.outcomes = list(outcomes or [(b"IMG", 0.05)])
        self.analyze_error = analyze_error
        self.analyze_calls = []
        self.prompts = []
        self.references = []
        self.seeds = []
        self.cut_calls = 0
        self.trim_calls = 0

    def __enter__(self):
        self._orig = (cli.vision.analyze, cli.orclient.generate,
                      cli.post.cut_background, cli.post.trim_and_pad)
        # A real .env in the project root would silently fill variables these
        # tests deliberately leave empty, so point the loader at nothing.
        from spritegen import envfile
        self._orig_env_path = envfile.DEFAULT_ENV_PATH
        envfile.DEFAULT_ENV_PATH = Path(tempfile.mkdtemp()) / "absent.env"

        def fake_analyze(pack, image_bytes, user_text=None, **kw):
            self.analyze_calls.append({"bytes": image_bytes, "user_text": user_text})
            if self.analyze_error:
                raise self.analyze_error
            return self.schema, json.dumps(self.schema)

        def fake_generate(pack, prompt, aspect_ratio=None, structure_png=None,
                          seed=None, style_png=None, **kw):
            self.prompts.append(prompt)
            self.references.append(style_png)
            self.seeds.append(seed)
            outcome = self.outcomes.pop(0) if self.outcomes else (b"IMG", 0.05)
            if isinstance(outcome, Exception):
                raise outcome
            data, cost = outcome
            return data, cost, {"stub": True}

        def fake_cut(data):
            self.cut_calls += 1
            return _Img(data)

        def fake_trim(img, **kw):
            self.trim_calls += 1
            return _Img(img.data, trimmed=True)

        cli.vision.analyze = fake_analyze
        cli.orclient.generate = fake_generate
        cli.post.cut_background = fake_cut
        cli.post.trim_and_pad = fake_trim
        return self

    def __exit__(self, *exc):
        (cli.vision.analyze, cli.orclient.generate,
         cli.post.cut_background, cli.post.trim_and_pad) = self._orig
        from spritegen import envfile
        envfile.DEFAULT_ENV_PATH = self._orig_env_path


def _env():
    os.environ.update({
        "SPRITEGEN_MODEL": "img/model",
        "SPRITEGEN_VISION_MODEL": "vis/model",
        "SPRITEGEN_API_KEY": "sk-test",
    })


def _clear():
    for k in ("SPRITEGEN_MODEL", "SPRITEGEN_VISION_MODEL", "SPRITEGEN_API_KEY",
              "SPRITEGEN_BASE_URL", "SPRITEGEN_TRANSPORT"):
        os.environ.pop(k, None)


def _image_file(tmp):
    p = Path(tmp) / "ref.png"
    p.write_bytes(_png())
    return p


# --- slug -------------------------------------------------------------------

def test_slugify_lowercases_and_replaces_runs():
    assert cli.slugify("A Small Launcher Chute!") == "a-small-launcher-chute"


def test_slugify_truncates_and_has_no_trailing_dash():
    s = cli.slugify("x" * 80)
    assert len(s) <= 40 and not s.endswith("-")


def test_slugify_falls_back_when_nothing_survives():
    assert cli.slugify("!!!") == "sprite"


# --- input validation -------------------------------------------------------

def test_neither_image_nor_text_is_an_error():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            assert cli.main(["make", "--out-root", tmp]) == 1
            assert s.analyze_calls == []
            assert s.prompts == []
    finally:
        _clear()


def test_text_only_makes_no_vision_call():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            code = cli.main(["make", "-t", "a glossy blue button", "--out-root", tmp])
        assert code == 0
        assert s.analyze_calls == []                 # nothing to analyse, nothing to pay for
        assert "a glossy blue button" in s.prompts[0]
        assert s.references == [None]
    finally:
        _clear()


def test_image_only_analyses_without_user_text():
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    try:
        with _Stubs() as s:
            code = cli.main(["make", "-i", str(img), "--out-root", tmp])
        assert code == 0
        assert len(s.analyze_calls) == 1
        assert s.analyze_calls[0]["user_text"] is None
        assert SCHEMA["subject"] in s.prompts[0]
    finally:
        _clear()


def test_image_plus_text_passes_the_text_to_analyze():
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    try:
        with _Stubs() as s:
            cli.main(["make", "-i", str(img), "-t", "make it red", "--out-root", tmp])
        assert s.analyze_calls[0]["user_text"] == "make it red"
    finally:
        _clear()


def test_missing_image_file_exits_cleanly():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            code = cli.main(["make", "-i", str(Path(tmp) / "nope.png"),
                             "--out-root", tmp])
        assert code == 1
        assert s.prompts == []
    finally:
        _clear()


# --- prompt + reference -----------------------------------------------------

def test_the_image_is_sent_as_a_generation_reference():
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    try:
        with _Stubs() as s:
            cli.main(["make", "-i", str(img), "--out-root", tmp])
        assert s.references[0] == img.read_bytes()
    finally:
        _clear()


def test_backdrop_clause_is_appended_by_default():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            cli.main(["make", "-t", "a coin", "--out-root", tmp])
        assert "#808080" in s.prompts[0]
    finally:
        _clear()


def test_no_cutout_skips_backdrop_and_post_processing():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            cli.main(["make", "-t", "a seamless sky", "--no-cutout", "--out-root", tmp])
        assert "#808080" not in s.prompts[0]
        assert s.cut_calls == 0 and s.trim_calls == 0
    finally:
        _clear()


# --- output -----------------------------------------------------------------

def test_output_png_and_sidecar_are_written():
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    try:
        with _Stubs():
            cli.main(["make", "-i", str(img), "--out-root", tmp])
        pngs = list((Path(tmp) / "make").glob("*.png"))
        jsons = list((Path(tmp) / "make").glob("*.json"))
        assert len(pngs) == 1 and len(jsons) == 1
        side = json.loads(jsons[0].read_text())
        assert side["schema"] == SCHEMA
        assert SCHEMA["subject"] in side["prompt"]
        assert side["model"] == "img/model"
        assert side["cost"] == 0.05
    finally:
        _clear()


def test_filename_carries_the_subject_slug():
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    try:
        with _Stubs():
            cli.main(["make", "-i", str(img), "--out-root", tmp])
        name = next((Path(tmp) / "make").glob("*.png")).name
        assert "launcher" in name
    finally:
        _clear()


def test_n_variants_write_n_files_with_distinct_seeds():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs(outcomes=[(b"A", 0.05), (b"B", 0.05), (b"C", 0.05)]) as s:
            code = cli.main(["make", "-t", "a coin", "-n", "3", "--out-root", tmp])
        assert code == 0
        assert len(list((Path(tmp) / "make").glob("*.png"))) == 3
        assert len(set(s.seeds)) == 3
    finally:
        _clear()


def test_dry_run_writes_nothing_and_makes_no_image_request():
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    try:
        with _Stubs() as s:
            code = cli.main(["make", "-i", str(img), "--dry-run", "--out-root", tmp])
        assert code == 0
        assert s.prompts == []                       # no generation
        assert not (Path(tmp) / "make").exists()     # not even a directory
    finally:
        _clear()


# --- failures ---------------------------------------------------------------

def test_analysis_failure_exits_one_and_generates_nothing():
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    err = cli.vision.AnalysisError("no JSON object found in the reply", raw="nope")
    try:
        with _Stubs(analyze_error=err) as s:
            code = cli.main(["make", "-i", str(img), "--out-root", tmp])
        assert code == 1
        assert s.prompts == []
        assert (img.parent / "ref.png.analysis-error.txt").read_text() == "nope"
    finally:
        _clear()


def test_one_failed_variant_still_writes_the_others():
    tmp = tempfile.mkdtemp(); _env()
    from spritegen import orclient
    outcomes = [(b"A", 0.05), orclient.ApiError("HTTP 429", 429), (b"C", 0.05)]
    try:
        with _Stubs(outcomes=outcomes):
            code = cli.main(["make", "-t", "a coin", "-n", "3", "--out-root", tmp])
        assert code == 1                                            # something failed
        assert len(list((Path(tmp) / "make").glob("*.png"))) == 2    # the rest survived
    finally:
        _clear()


def test_missing_image_model_exits_cleanly():
    tmp = tempfile.mkdtemp()
    _clear()
    os.environ["SPRITEGEN_VISION_MODEL"] = "vis/model"
    try:
        with _Stubs() as s:
            code = cli.main(["make", "-t", "a coin", "--out-root", tmp])
        assert code == 1
        assert s.prompts == []
    finally:
        _clear()


# --- build-vs-make parity (final review) ------------------------------------

def test_blank_text_and_no_image_is_an_error():
    """The input guard tests truthiness, not content — `-t "   "` used to sail
    through, pay for an empty prompt, and exit 0."""
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            code = cli.main(["make", "-t", "   ", "--out-root", tmp])
        assert code == 1
        assert s.prompts == []
    finally:
        _clear()


def test_missing_api_key_exits_before_any_request():
    """Same diagnosis build/init/analyze give for a missing key: fail fast
    instead of a 401 after three retries per variant."""
    tmp = tempfile.mkdtemp()
    _clear()
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ["SPRITEGEN_MODEL"] = "img/model"
    try:
        with _Stubs() as s:
            code = cli.main(["make", "-t", "a coin", "--out-root", tmp])
        assert code == 1
        assert s.prompts == []
    finally:
        _clear()


def test_missing_vision_key_exits_before_any_request_when_image_given():
    """Mirrors cmd_analyze's vision-key guard. env_pack's own resolution
    happens to make this unreachable in practice today (an unset
    SPRITEGEN_VISION_API_KEY falls back to the same variable the main key
    check already required to be set) — so this exercises cmd_make's guard
    directly against a hand-built Pack, the way it would matter if env_pack's
    fallback ever decoupled the two keys."""
    from spritegen.config import Pack
    tmp = tempfile.mkdtemp()
    img = _image_file(tmp)
    fake_pack = Pack(
        name="make", base_url="http://x/v1", key_env="SPRITEGEN_API_KEY",
        model="img/model", style_prefix="", plate_prompt="", assets=[],
        out_root=Path(tmp), vision_base_url="http://x/v1",
        vision_key_env="ABSENT_VISION_KEY_VAR", vision_model="vis/model",
    )
    os.environ.pop("ABSENT_VISION_KEY_VAR", None)
    _env()
    orig_env_pack = cli.config.env_pack
    cli.config.env_pack = lambda **kw: fake_pack
    try:
        with _Stubs() as s:
            code = cli.main(["make", "-i", str(img), "--out-root", tmp])
        assert code == 1
        assert s.analyze_calls == []
    finally:
        cli.config.env_pack = orig_env_pack
        _clear()


def test_missing_image_in_response_writes_error_json():
    """Finding 7: cmd_make used to fold ImageMissing in with ApiError and
    print only "no image in response" — build_one dumps the raw response to
    disk instead, and `make` is the command most likely pointed at an
    unfamiliar model where that raw reply matters most."""
    tmp = tempfile.mkdtemp(); _env()
    outcomes = [orclient.ImageMissing({"choices": [{"message": {"content": "refused"}}]})]
    try:
        with _Stubs(outcomes=outcomes):
            code = cli.main(["make", "-t", "a coin", "--out-root", tmp])
        assert code == 1
        errors = list((Path(tmp) / "make").glob("*.error.json"))
        assert len(errors) == 1
        dumped = json.loads(errors[0].read_text())
        assert dumped["choices"][0]["message"]["content"] == "refused"
    finally:
        _clear()


def test_post_processing_failure_still_writes_a_sidecar_naming_the_failure():
    """Finding 2: a post-processing failure used to `continue` before the
    sidecar write, leaving a paid-for .raw.png with no provenance at all —
    the one case where the file is non-standard and the money is spent."""
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            def boom(data):
                raise RuntimeError("shape error")
            cli.post.cut_background = boom
            code = cli.main(["make", "-t", "a coin", "--out-root", tmp])
        assert code == 1
        out = Path(tmp) / "make"
        raws = list(out.glob("*.raw.png"))
        jsons = list(out.glob("*.json"))
        pngs = [p for p in out.glob("*.png") if not p.name.endswith(".raw.png")]
        assert len(raws) == 1 and len(jsons) == 1 and len(pngs) == 0
        side = json.loads(jsons[0].read_text())
        assert side["status"] == "failed"
        assert "shape error" in side["error"]
        assert "raw kept as" in side["error"]
        assert side["file"] is None
    finally:
        _clear()


def test_cost_unknown_when_no_variant_reports_cost():
    """Finding 4: `if cost: spent += cost` plus an unconditional "(${spent})"
    printed "$0.00" for a run that may have cost real money — a positive
    claim of zero, not "unknown", for exactly the local-endpoint case
    response_cost's own docstring calls the common one."""
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs(outcomes=[(b"A", None)]):
            buf = StringIO()
            with redirect_stdout(buf):
                code = cli.main(["make", "-t", "a coin", "--out-root", tmp])
        assert code == 0
        out = buf.getvalue()
        assert "cost unknown" in out
        assert "$0.00" not in out
    finally:
        _clear()


def test_legitimate_zero_cost_is_not_reported_as_unknown():
    """The other half of Finding 4: `if cost:` treated an honestly-reported
    0.0 the same as a missing cost. A real 0.0 must count as cost_seen."""
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs(outcomes=[(b"A", 0.0)]):
            buf = StringIO()
            with redirect_stdout(buf):
                code = cli.main(["make", "-t", "a coin", "--out-root", tmp])
        assert code == 0
        assert "cost unknown" not in buf.getvalue()
        assert "$0.00" in buf.getvalue()
    finally:
        _clear()


def test_cost_ceiling_stop_returns_exit_one_even_with_zero_failures():
    """Finding 14: cmd_make used to return 0 after breaking on the cost
    ceiling as long as nothing outright failed — cmd_build deliberately
    returns 1 for exactly this, so a caller chaining `&& upload` doesn't
    treat a truncated run as a clean success."""
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs(outcomes=[(b"A", 0.05), (b"B", 0.05), (b"C", 0.05)]) as s:
            code = cli.main(["make", "-t", "a coin", "-n", "3",
                             "--max-cost", "0.05", "--out-root", tmp])
        assert code == 1
        assert len(s.prompts) == 1  # spent 0.05 after the first, budget exhausted
    finally:
        _clear()


def test_sidecar_reference_path_is_resolved():
    """Finding 15: a relative --image path in the sidecar may be unresolvable
    when someone reads it later from a different working directory."""
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    try:
        with _Stubs():
            cli.main(["make", "-i", str(img), "--out-root", tmp])
        side = json.loads(next((Path(tmp) / "make").glob("*.json")).read_text())
        assert side["reference"] == str(img.resolve())
    finally:
        _clear()


def test_make_real_chain_sends_reference_image_as_input_references():
    """The reference image is the actual basis of the "make the same thing"
    scenario, yet every test above (like every test in this file before this
    wave) stubs vision.analyze and orclient.generate directly — nothing
    asserted that `make -i` actually puts the image on the wire. Mirrors
    test_build.py's real-seam tests: stubs only requests.post (network) and
    post.cut_background (avoids downloading rembg weights), and runs a real
    `make -i` through the real config.env_pack, vision.analyze and
    orclient.generate."""
    tmp = tempfile.mkdtemp()
    img = _image_file(tmp)
    ref_bytes = img.read_bytes()

    subject = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    subject.paste((200, 30, 30, 255), (10, 10, 30, 30))
    buf = BytesIO()
    subject.save(buf, format="PNG")
    gen_b64 = base64.b64encode(buf.getvalue()).decode()
    schema_json = json.dumps(SCHEMA)

    class _FakeResp:
        status_code = 200

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json))
        if url.endswith("/chat/completions"):
            return _FakeResp({"choices": [{"message": {"content": schema_json}}]})
        return _FakeResp({"data": [{"b64_json": gen_b64}], "usage": {"cost": 0.04}})

    from spritegen import envfile
    orig_env_path = envfile.DEFAULT_ENV_PATH
    envfile.DEFAULT_ENV_PATH = Path(tempfile.mkdtemp()) / "absent.env"
    orig_post = orclient.requests.post
    orig_cut = post.cut_background
    orclient.requests.post = fake_post
    post.cut_background = lambda data: Image.open(BytesIO(data)).convert("RGBA")

    _clear(); _env()
    os.environ["SPRITEGEN_BASE_URL"] = "http://svc/v1"
    try:
        code = cli.main(["make", "-i", str(img), "--out-root", tmp])
    finally:
        orclient.requests.post = orig_post
        post.cut_background = orig_cut
        envfile.DEFAULT_ENV_PATH = orig_env_path
        _clear()

    assert code == 0
    image_calls = [j for u, j in calls if u.endswith("/images")]
    assert len(image_calls) == 1
    posted_ref_url = image_calls[0]["input_references"][0]["image_url"]["url"]
    assert posted_ref_url.endswith(base64.b64encode(ref_bytes).decode())
    assert any(u == "http://svc/v1/images" for u, _ in calls)

