"""`make` command tests. No network, no rembg. Run: python3 test_make.py"""
import json
import os
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image

import gen


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
        self._orig = (gen.vision.analyze, gen.orclient.generate,
                      gen.post.cut_background, gen.post.trim_and_pad)
        # A real .env in the project root would silently fill variables these
        # tests deliberately leave empty, so point the loader at nothing.
        import envfile
        self._orig_env_path = envfile.DEFAULT_ENV_PATH
        envfile.DEFAULT_ENV_PATH = Path(tempfile.mkdtemp()) / "absent.env"

        def fake_analyze(pack, image_bytes, user_text=None, **kw):
            self.analyze_calls.append({"bytes": image_bytes, "user_text": user_text})
            if self.analyze_error:
                raise self.analyze_error
            return self.schema, json.dumps(self.schema)

        def fake_generate(pack, prompt, aspect_ratio=None, reference_png=None,
                          seed=None, **kw):
            self.prompts.append(prompt)
            self.references.append(reference_png)
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

        gen.vision.analyze = fake_analyze
        gen.orclient.generate = fake_generate
        gen.post.cut_background = fake_cut
        gen.post.trim_and_pad = fake_trim
        return self

    def __exit__(self, *exc):
        (gen.vision.analyze, gen.orclient.generate,
         gen.post.cut_background, gen.post.trim_and_pad) = self._orig
        import envfile
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
    assert gen.slugify("A Small Launcher Chute!") == "a-small-launcher-chute"


def test_slugify_truncates_and_has_no_trailing_dash():
    s = gen.slugify("x" * 80)
    assert len(s) <= 40 and not s.endswith("-")


def test_slugify_falls_back_when_nothing_survives():
    assert gen.slugify("!!!") == "sprite"


# --- input validation -------------------------------------------------------

def test_neither_image_nor_text_is_an_error():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            assert gen.main(["make", "--out-root", tmp]) == 1
            assert s.analyze_calls == []
            assert s.prompts == []
    finally:
        _clear()


def test_text_only_makes_no_vision_call():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            code = gen.main(["make", "-t", "a glossy blue button", "--out-root", tmp])
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
            code = gen.main(["make", "-i", str(img), "--out-root", tmp])
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
            gen.main(["make", "-i", str(img), "-t", "make it red", "--out-root", tmp])
        assert s.analyze_calls[0]["user_text"] == "make it red"
    finally:
        _clear()


def test_missing_image_file_exits_cleanly():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            code = gen.main(["make", "-i", str(Path(tmp) / "nope.png"),
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
            gen.main(["make", "-i", str(img), "--out-root", tmp])
        assert s.references[0] == img.read_bytes()
    finally:
        _clear()


def test_backdrop_clause_is_appended_by_default():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            gen.main(["make", "-t", "a coin", "--out-root", tmp])
        assert "#808080" in s.prompts[0]
    finally:
        _clear()


def test_no_cutout_skips_backdrop_and_post_processing():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            gen.main(["make", "-t", "a seamless sky", "--no-cutout", "--out-root", tmp])
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
            gen.main(["make", "-i", str(img), "--out-root", tmp])
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
            gen.main(["make", "-i", str(img), "--out-root", tmp])
        name = next((Path(tmp) / "make").glob("*.png")).name
        assert "launcher" in name
    finally:
        _clear()


def test_n_variants_write_n_files_with_distinct_seeds():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs(outcomes=[(b"A", 0.05), (b"B", 0.05), (b"C", 0.05)]) as s:
            code = gen.main(["make", "-t", "a coin", "-n", "3", "--out-root", tmp])
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
            code = gen.main(["make", "-i", str(img), "--dry-run", "--out-root", tmp])
        assert code == 0
        assert s.prompts == []                       # no generation
        assert not (Path(tmp) / "make").exists()     # not even a directory
    finally:
        _clear()


# --- failures ---------------------------------------------------------------

def test_analysis_failure_exits_one_and_generates_nothing():
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    err = gen.vision.AnalysisError("no JSON object found in the reply", raw="nope")
    try:
        with _Stubs(analyze_error=err) as s:
            code = gen.main(["make", "-i", str(img), "--out-root", tmp])
        assert code == 1
        assert s.prompts == []
        assert (img.parent / "ref.png.analysis-error.txt").read_text() == "nope"
    finally:
        _clear()


def test_one_failed_variant_still_writes_the_others():
    tmp = tempfile.mkdtemp(); _env()
    import orclient
    outcomes = [(b"A", 0.05), orclient.ApiError("HTTP 429", 429), (b"C", 0.05)]
    try:
        with _Stubs(outcomes=outcomes):
            code = gen.main(["make", "-t", "a coin", "-n", "3", "--out-root", tmp])
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
            code = gen.main(["make", "-t", "a coin", "--out-root", tmp])
        assert code == 1
        assert s.prompts == []
    finally:
        _clear()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all make tests passed")
