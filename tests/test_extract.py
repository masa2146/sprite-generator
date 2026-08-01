"""extract mechanics tests. Run: python3 -m pytest tests/test_extract.py"""
import contextlib
import io
import tempfile
import tomllib
from pathlib import Path

from PIL import Image

from spritegen import extract


def _img(w=400, h=600):
    return Image.new("RGB", (w, h), (30, 30, 50))


def _objects():
    return [
        {"id": "alpha", "bbox": [10, 10, 110, 110], "animated": True,
         "views": ["front", "side"], "subject": "a thing",
         "form": "a round thing", "detail": "shiny"},
        {"id": "beta", "bbox": [200, 300, 260, 380], "animated": False,
         "views": ["front"], "subject": "another thing",
         "form": "a boxy thing", "detail": "matte"},
    ]


# --- bbox validation --------------------------------------------------------

def test_a_normal_box_is_accepted():
    assert extract.reject_reason([10, 10, 110, 110], 400, 600) is None


def test_a_box_outside_the_image_is_rejected():
    assert "outside" in extract.reject_reason([380, 10, 460, 110], 400, 600)
    assert "outside" in extract.reject_reason([-5, 10, 110, 110], 400, 600)


def test_a_zero_or_inverted_box_is_rejected():
    assert "empty" in extract.reject_reason([100, 100, 100, 200], 400, 600)
    assert "empty" in extract.reject_reason([200, 100, 100, 200], 400, 600)


def test_a_box_covering_the_whole_image_is_rejected():
    assert "whole image" in extract.reject_reason([0, 0, 400, 600], 400, 600)


def test_a_tiny_box_is_rejected():
    assert "too small" in extract.reject_reason([10, 10, 20, 110], 400, 600)


def test_a_malformed_box_is_rejected():
    assert extract.reject_reason("nope", 400, 600) is not None
    assert extract.reject_reason([1, 2, 3], 400, 600) is not None
    assert extract.reject_reason([1, 2, "x", 4], 400, 600) is not None


# --- cropping ---------------------------------------------------------------

def test_crop_objects_writes_one_file_per_object():
    d = Path(tempfile.mkdtemp())
    kept, rejected = extract.crop_objects(_img(), _objects(), d)
    assert [o["id"] for o in kept] == ["alpha", "beta"]
    assert rejected == []
    assert (d / "alpha.png").exists() and (d / "beta.png").exists()
    assert kept[0]["crop"] == d / "alpha.png"


def test_crop_dimensions_match_the_padded_box():
    d = Path(tempfile.mkdtemp())
    kept, _ = extract.crop_objects(_img(), _objects(), d)
    x1, y1, x2, y2 = extract.padded_box(_objects()[0]["bbox"], 400, 600)
    with Image.open(kept[0]["crop"]) as im:
        assert im.size == (x2 - x1, y2 - y1)


def test_a_rejected_box_is_reported_and_skipped():
    d = Path(tempfile.mkdtemp())
    objs = _objects() + [{"id": "bad", "bbox": [0, 0, 400, 600], "animated": False,
                          "views": ["front"], "subject": "s", "form": "f", "detail": "d"}]
    kept, rejected = extract.crop_objects(_img(), objs, d)
    assert [o["id"] for o in kept] == ["alpha", "beta"]
    assert [r[0] for r in rejected] == ["bad"]
    assert "whole image" in rejected[0][1]
    assert not (d / "bad.png").exists()


def test_an_object_without_an_id_is_rejected_not_crashed():
    d = Path(tempfile.mkdtemp())
    kept, rejected = extract.crop_objects(_img(), [{"bbox": [10, 10, 50, 50]}], d)
    assert kept == []
    assert len(rejected) == 1


def test_a_duplicate_id_is_rejected_and_the_first_crop_survives():
    """Critical 3: two objects sharing an id used to overwrite each other's
    crop on disk and produce an unloadable pack (config.load_pack rejects
    duplicate asset ids). The second occurrence must be rejected, and the
    first object's crop (its real dimensions) must be left untouched."""
    d = Path(tempfile.mkdtemp())
    objs = [
        {"id": "block", "bbox": [10, 10, 110, 110], "animated": False, "views": ["front"]},
        {"id": "block", "bbox": [200, 300, 260, 380], "animated": False, "views": ["front"]},
    ]
    kept, rejected = extract.crop_objects(_img(), objs, d)
    assert [o["id"] for o in kept] == ["block"]
    assert rejected == [("block", "duplicate id")]
    x1, y1, x2, y2 = extract.padded_box([10, 10, 110, 110], 400, 600)
    with Image.open(d / "block.png") as im:
        # the first box's padded dims, not the second box's
        assert im.size == (x2 - x1, y2 - y1)
        assert im.size != (60, 80)


def test_an_id_that_would_escape_the_refs_dir_is_rejected():
    """Important 4: the model's id becomes a path (refs_dir / f"{id}.png") and,
    downstream, an asset id used the same way in cli.py's out_dir. An id like
    "../escaped" must be rejected before it ever reaches Path(), not silently
    written outside refs_dir."""
    d = Path(tempfile.mkdtemp())
    objs = [{"id": "../escaped", "bbox": [10, 10, 110, 110], "animated": False,
             "views": ["front"]}]
    kept, rejected = extract.crop_objects(_img(), objs, d)
    assert kept == []
    assert rejected == [("../escaped", "unusable id")]
    assert not (d.parent / "escaped.png").exists()


def test_an_id_with_a_slash_is_rejected():
    d = Path(tempfile.mkdtemp())
    objs = [{"id": "a/b", "bbox": [10, 10, 110, 110], "animated": False, "views": ["front"]}]
    kept, rejected = extract.crop_objects(_img(), objs, d)
    assert kept == []
    assert rejected == [("a/b", "unusable id")]


# --- contact sheet ----------------------------------------------------------

def test_labelled_sheet_is_written_and_readable():
    d = Path(tempfile.mkdtemp())
    kept, _ = extract.crop_objects(_img(), _objects(), d)
    out = extract.labelled_sheet(kept, d / "_contact_sheet.png")
    assert out.exists()
    with Image.open(out) as im:
        assert im.width > 0 and im.height > 0


def test_labelled_sheet_handles_a_single_entry():
    d = Path(tempfile.mkdtemp())
    kept, _ = extract.crop_objects(_img(), _objects()[:1], d)
    assert extract.labelled_sheet(kept, d / "s.png").exists()


# --- pack text --------------------------------------------------------------

def _pack_text(tmp):
    style = {f: f"{f}-value" for f in
             ("render", "camera", "lighting", "palette", "linework", "realism")}
    kept, _ = extract.crop_objects(_img(), _objects(), Path(tmp) / "refs")
    return extract.pack_text("m/model", "SPRITEGEN_API_KEY", style, kept,
                             Path(tmp) / "refs", Path(tmp) / "p.toml")


def test_pack_text_parses_as_toml():
    tmp = tempfile.mkdtemp()
    d = tomllib.loads(_pack_text(tmp))
    assert d["pack"]["model"] == "m/model"
    assert "render-value" in d["style"]["prefix"]


def test_pack_text_writes_the_key_env():
    """Critical 2: a pack from `extract` must record which env var holds the
    key, or `build` falls back to load_pack's OPENROUTER_API_KEY default and
    fails for a user who followed .env.example and set SPRITEGEN_API_KEY."""
    tmp = tempfile.mkdtemp()
    assert tomllib.loads(_pack_text(tmp))["api"]["key_env"] == "SPRITEGEN_API_KEY"


def test_pack_text_round_trips_an_empty_key_env():
    """An endpoint that needs no key must round-trip as key_env = "", not be
    dropped (which would silently fall back to the OPENROUTER_API_KEY default)."""
    tmp = tempfile.mkdtemp()
    style = {f: f"{f}-value" for f in
             ("render", "camera", "lighting", "palette", "linework", "realism")}
    kept, _ = extract.crop_objects(_img(), _objects(), Path(tmp) / "refs")
    text = extract.pack_text("m/model", "", style, kept,
                             Path(tmp) / "refs", Path(tmp) / "p.toml")
    d = tomllib.loads(text)
    assert "key_env" in d["api"]
    assert d["api"]["key_env"] == ""


def test_pack_text_joins_the_style_prefix_in_visions_join_order():
    """Important 6: pack_text used to reimplement vision.style_prefix with
    STYLE_FIELDS order instead of vision._JOIN_ORDER (palette deliberately
    last), so a pack from `extract` and one from `analyze` carried
    differently-ordered prefixes for the same schema."""
    tmp = tempfile.mkdtemp()
    style = {f: f"{f}-value" for f in
             ("render", "camera", "lighting", "palette", "linework", "realism")}
    kept, _ = extract.crop_objects(_img(), _objects(), Path(tmp) / "refs")
    text = extract.pack_text("m/model", "SPRITEGEN_API_KEY", style, kept,
                             Path(tmp) / "refs", Path(tmp) / "p.toml")
    prefix = tomllib.loads(text)["style"]["prefix"]
    from spritegen import vision
    assert prefix.strip() == vision.style_prefix({"style": style})
    assert prefix.index("palette-value") > prefix.index("realism-value")


def test_one_asset_per_object_view():
    tmp = tempfile.mkdtemp()
    ids = [a["id"] for a in tomllib.loads(_pack_text(tmp))["assets"]]
    assert ids == ["alpha-front", "alpha-side", "beta-front"]


def test_each_asset_points_at_its_own_crop_relative_to_the_pack():
    tmp = tempfile.mkdtemp()
    assets = tomllib.loads(_pack_text(tmp))["assets"]
    assert assets[0]["reference"] == "refs/alpha.png"
    assert assets[2]["reference"] == "refs/beta.png"


def test_the_view_phrase_is_appended_to_the_prompt():
    tmp = tempfile.mkdtemp()
    assets = tomllib.loads(_pack_text(tmp))["assets"]
    from spritegen import vision
    assert assets[1]["prompt"].endswith(vision.VIEW_POOL["side"])
    assert "a round thing" in assets[1]["prompt"]      # form is carried


def test_no_style_field_leaks_into_an_asset_prompt():
    tmp = tempfile.mkdtemp()
    for a in tomllib.loads(_pack_text(tmp))["assets"]:
        assert "render-value" not in a["prompt"]


def test_an_object_with_no_subject_fields_does_not_start_the_prompt_with_a_comma():
    """Minor 7: an object missing subject/form/detail must not produce a prompt
    like ", seen from directly the front" — the leading ", " meant the sprite
    would generate from style + view alone."""
    assert extract._asset_prompt({"id": "x"}, "front") == "seen from directly the front"


def test_a_quote_in_a_description_does_not_break_the_toml():
    tmp = tempfile.mkdtemp()
    style = {f: f"{f}-value" for f in
             ("render", "camera", "lighting", "palette", "linework", "realism")}
    objs = _objects()
    objs[0]["subject"] = 'a "glossy" thing with a \\ in it'
    kept, _ = extract.crop_objects(_img(), objs, Path(tmp) / "refs")
    text = extract.pack_text("m/model", "SPRITEGEN_API_KEY", style, kept,
                             Path(tmp) / "refs", Path(tmp) / "p.toml")
    assert 'a "glossy" thing' in tomllib.loads(text)["assets"][0]["prompt"]


def test_a_backslash_or_triple_quote_in_a_style_field_does_not_break_the_toml():
    tmp = tempfile.mkdtemp()
    style = {f: f"{f}-value" for f in
             ("render", "camera", "lighting", "palette", "linework", "realism")}
    style["camera"] = "50mm w\\ shallow DOF"
    style["lighting"] = 'has \"\"\" inside'
    kept, _ = extract.crop_objects(_img(), _objects(), Path(tmp) / "refs")
    text = extract.pack_text("m/model", "SPRITEGEN_API_KEY", style, kept,
                             Path(tmp) / "refs", Path(tmp) / "p.toml")
    d = tomllib.loads(text)
    assert "50mm w\\ shallow DOF" in d["style"]["prefix"]
    assert 'has """ inside' in d["style"]["prefix"]


def test_a_refs_dir_outside_the_pack_dir_still_gets_a_relative_reference():
    tmp = Path(tempfile.mkdtemp())
    pack_dir = tmp / "pack"
    pack_dir.mkdir()
    refs_dir = tmp / "refs"          # sibling of pack_dir, not inside it
    kept, _ = extract.crop_objects(_img(), _objects(), refs_dir)
    text = extract.pack_text("m/model", "SPRITEGEN_API_KEY", {}, kept, refs_dir, pack_dir / "p.toml")
    ref = tomllib.loads(text)["assets"][0]["reference"]
    assert not Path(ref).is_absolute()
    assert ref.startswith("..")


# --- the command ------------------------------------------------------------

import json
import os

from spritegen import cli

OBJECTS_REPLY = {
    "style": {"render": "soft 3D", "camera": "top-down", "lighting": "soft",
              "palette": "#111111", "linework": "no outline", "realism": "cartoon"},
    "objects": [
        {"id": "alpha", "bbox": [10, 10, 110, 110], "animated": True,
         "views": ["front", "side"], "subject": "a thing", "form": "round", "detail": "shiny"},
        {"id": "beta", "bbox": [200, 300, 260, 380], "animated": False,
         "views": ["front"], "subject": "another", "form": "boxy", "detail": "matte"},
    ],
}


class _VisionStub:
    def __init__(self, reply=None, error=None):
        self.reply = reply if reply is not None else OBJECTS_REPLY
        self.error = error
        self.calls = 0
        self.user_text = None

    def __enter__(self):
        self._orig = cli.vision.analyze_objects
        from spritegen import envfile
        self._env = envfile.DEFAULT_ENV_PATH
        envfile.DEFAULT_ENV_PATH = Path(tempfile.mkdtemp()) / "absent.env"

        def fake(pack, image_bytes, user_text=None, **kw):
            self.calls += 1
            self.user_text = user_text
            if self.error:
                raise self.error
            return self.reply, json.dumps(self.reply)

        cli.vision.analyze_objects = fake
        return self

    def __exit__(self, *exc):
        cli.vision.analyze_objects = self._orig
        from spritegen import envfile
        envfile.DEFAULT_ENV_PATH = self._env


def _env_ready():
    os.environ.update({"SPRITEGEN_MODEL": "img/model",
                       "SPRITEGEN_VISION_MODEL": "vis/model",
                       "SPRITEGEN_API_KEY": "sk-test"})


def _env_clear():
    for k in ("SPRITEGEN_MODEL", "SPRITEGEN_VISION_MODEL", "SPRITEGEN_API_KEY"):
        os.environ.pop(k, None)


def _scene(tmp):
    p = Path(tmp) / "scene.png"
    _img().save(p)
    return p


def test_extract_writes_pack_crops_and_sheet():
    tmp = tempfile.mkdtemp(); _env_ready()
    try:
        pack = Path(tmp) / "out.toml"
        with _VisionStub():
            code = cli.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
                             "--no-open"])
        assert code == 0
        assert pack.exists()
        refs = Path(tmp) / "refs"
        assert (refs / "alpha.png").exists() and (refs / "beta.png").exists()
        assert (refs / "_contact_sheet.png").exists()
        ids = [a["id"] for a in tomllib.loads(pack.read_text())["assets"]]
        assert ids == ["alpha-front", "alpha-side", "beta-front"]
    finally:
        _env_clear()


def test_extract_refuses_to_overwrite_an_existing_pack():
    tmp = tempfile.mkdtemp(); _env_ready()
    try:
        pack = Path(tmp) / "out.toml"
        pack.write_text("# mine\n")
        with _VisionStub() as stub:
            code = cli.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
                             "--no-open"])
        assert code == 1
        assert pack.read_text() == "# mine\n"
        assert stub.calls == 0            # refused before spending the vision call
    finally:
        _env_clear()


def test_extract_dry_run_writes_nothing():
    tmp = tempfile.mkdtemp(); _env_ready()
    try:
        pack = Path(tmp) / "out.toml"
        with _VisionStub():
            code = cli.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
                             "--no-open", "--dry-run"])
        assert code == 0
        assert not pack.exists()
        assert not (Path(tmp) / "refs").exists()
    finally:
        _env_clear()


def test_extract_reports_rejected_boxes_and_keeps_the_rest():
    tmp = tempfile.mkdtemp(); _env_ready()
    reply = json.loads(json.dumps(OBJECTS_REPLY))
    reply["objects"].append({"id": "whole", "bbox": [0, 0, 400, 600], "animated": False,
                             "views": ["front"], "subject": "s", "form": "f", "detail": "d"})
    try:
        pack = Path(tmp) / "out.toml"
        with _VisionStub(reply=reply):
            code = cli.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
                             "--no-open"])
        assert code == 0
        ids = [a["id"] for a in tomllib.loads(pack.read_text())["assets"]]
        assert "whole-front" not in ids
        assert not (Path(tmp) / "refs" / "whole.png").exists()
    finally:
        _env_clear()


def test_extract_fails_when_every_box_is_rejected():
    tmp = tempfile.mkdtemp(); _env_ready()
    reply = {"style": OBJECTS_REPLY["style"],
             "objects": [{"id": "whole", "bbox": [0, 0, 400, 600], "animated": False,
                          "views": ["front"], "subject": "s", "form": "f", "detail": "d"}]}
    try:
        pack = Path(tmp) / "out.toml"
        with _VisionStub(reply=reply):
            code = cli.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
                             "--no-open"])
        assert code == 1
        assert not pack.exists()
    finally:
        _env_clear()


def test_extract_caps_the_object_count():
    tmp = tempfile.mkdtemp(); _env_ready()
    reply = {"style": OBJECTS_REPLY["style"], "objects": []}
    for i in range(20):
        reply["objects"].append(
            {"id": f"o{i}", "bbox": [10, 10, 60, 60], "animated": False,
             "views": ["front"], "subject": "s", "form": "f", "detail": "d"})
    try:
        pack = Path(tmp) / "out.toml"
        with _VisionStub(reply=reply):
            cli.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
                      "--no-open", "--max-objects", "5"])
        assert len(tomllib.loads(pack.read_text())["assets"]) == 5
    finally:
        _env_clear()


def test_extract_missing_image_exits_cleanly():
    tmp = tempfile.mkdtemp(); _env_ready()
    try:
        with _VisionStub() as stub:
            code = cli.main(["extract", "-i", str(Path(tmp) / "nope.png"),
                             "--pack", str(Path(tmp) / "out.toml"), "--no-open"])
        assert code == 1
        assert stub.calls == 0
    finally:
        _env_clear()


# --- the extract -> build seam ----------------------------------------------
#
# Required new test (final review): both criticals live in the extract -> build
# handoff and nothing else crosses it. Critical 1: build's style_bible gate
# used to fire unconditionally, even though every asset extract writes carries
# its own `reference` and never needs one. Critical 2: the pack extract writes
# used to omit [api] key_env, so build fell back to load_pack's
# OPENROUTER_API_KEY default instead of the SPRITEGEN_API_KEY extract itself
# authenticated with.

from spritegen import config


def test_extract_then_build_reaches_generation_without_a_style_bible():
    tmp = tempfile.mkdtemp()
    _env_ready()
    had_or_key = "OPENROUTER_API_KEY" in os.environ
    prior_or_key = os.environ.pop("OPENROUTER_API_KEY", None)
    try:
        pack = Path(tmp) / "packs" / "bunny.toml"
        with _VisionStub():
            code = cli.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
                             "--no-open"])
        assert code == 0

        out_root = Path(tmp) / "out"
        loaded = config.load_pack(pack, out_root=out_root)
        assert loaded.key_env == "SPRITEGEN_API_KEY"   # Critical 2: recorded, not dropped
        assert not loaded.style_bible.exists()          # extract never wrote one

        seed_to_id = {loaded.seed_for(a.id): a.id for a in loaded.assets}
        calls = {}

        def fake_generate(pack_, prompt, aspect_ratio=None, reference_png=None,
                          seed=None, **kw):
            calls[seed_to_id[seed]] = reference_png
            return b"\x89PNG\r\n\x1a\nFAKE", 0.01, {"stub": True}

        class _FakeImg:
            def __init__(self, data):
                self.data = data

            def save(self, path):
                Path(path).write_bytes(self.data)

        original = (cli.orclient.generate, cli.post.cut_background, cli.post.trim_and_pad)
        cli.orclient.generate = fake_generate
        cli.post.cut_background = lambda data: _FakeImg(data)
        cli.post.trim_and_pad = lambda img, **kw: img
        try:
            code = cli.main(["build", str(pack), "--out-root", str(out_root)])
        finally:
            cli.orclient.generate, cli.post.cut_background, cli.post.trim_and_pad = original

        assert code == 0    # Critical 1: build reached generation, no style bible required
        assert not loaded.style_bible.exists()   # still never created

        # Critical 1 + 2 pinned together: every asset's reference_png is its own
        # crop's bytes, not a style bible (there is none) and not None.
        assert set(calls) == {a.id for a in loaded.assets}
        for a in loaded.assets:
            assert a.reference is not None
            assert calls[a.id] == a.reference.read_bytes()
    finally:
        _env_clear()
        if had_or_key:
            os.environ["OPENROUTER_API_KEY"] = prior_or_key


def test_ids_differing_only_in_case_are_rejected_as_duplicates():
    """A case-insensitive filesystem maps both to one crop file, so the second
    would silently overwrite the first and the sheet would show it twice."""
    objs = [
        {"id": "Block", "bbox": [10, 10, 110, 110], "views": ["front"]},
        {"id": "block", "bbox": [200, 300, 260, 380], "views": ["front"]},
    ]
    with tempfile.TemporaryDirectory() as td:
        refs = Path(td) / "refs"
        kept, rejected = extract.crop_objects(_img(), objs, refs)
    assert [k["id"] for k in kept] == ["Block"]
    assert rejected == [("block", "duplicate id")]


def test_the_dry_run_preview_names_the_same_objects_the_real_run_keeps():
    """The preview is what the user reads before paying build, so it must not
    promise an object extract would drop. Goes through the real command: a
    dry-run that screened differently from the run would pass any test that
    only compared the two helpers to each other."""
    reply = json.loads(json.dumps(OBJECTS_REPLY))
    reply["objects"] = [
        dict(reply["objects"][0], id="good"),
        dict(reply["objects"][0], id="Good"),        # collides on a case-insensitive fs
        dict(reply["objects"][0], id="../escaped"),  # would write outside refs/
    ]
    tmp = tempfile.mkdtemp(); _env_ready()
    try:
        pack = Path(tmp) / "out.toml"
        buf = io.StringIO()
        with _VisionStub(reply=reply), contextlib.redirect_stdout(buf):
            code = cli.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
                             "--no-open", "--dry-run"])
        assert code == 0
        preview = buf.getvalue()

        with _VisionStub(reply=reply):
            assert cli.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
                             "--no-open"]) == 0
        built = {a["id"].rsplit("-", 1)[0] for a in tomllib.loads(pack.read_text())["assets"]}
        assert built == {"good"}

        for line in preview.splitlines():
            if line.startswith("  ") and "REJECT" not in line:
                assert line.split()[0] in built, f"preview promised {line.split()[0]!r}"
        assert "REJECT (duplicate id)" in preview
        assert "REJECT (unusable id)" in preview
    finally:
        _env_clear()


def test_the_crop_is_padded_beyond_the_model_s_box():
    """Vision boxes clip: the first live run cut the ears off every rabbit.
    Extra background is free, a clipped silhouette is not."""
    assert extract.padded_box([100, 100, 200, 300], 704, 1526) == (88, 76, 212, 324)


def test_padding_is_clamped_to_the_image():
    assert extract.padded_box([0, 0, 100, 100], 704, 1526) == (0, 0, 112, 112)
    assert extract.padded_box([604, 1426, 704, 1526], 704, 1526) == (592, 1414, 704, 1526)


def test_crop_objects_writes_the_padded_region():
    objs = [{"id": "alpha", "bbox": [100, 100, 200, 300], "views": ["front"]}]
    with tempfile.TemporaryDirectory() as td:
        kept, _ = extract.crop_objects(_img(400, 600), objs, Path(td) / "refs")
        assert Image.open(kept[0]["crop"]).size == (124, 248)   # not the raw 100x200


def test_one_huge_crop_does_not_blow_up_the_contact_sheet():
    """A near-full-playfield box (the live run produced 704x1004) used to size
    every cell, giving a sheet of thousands of pixels of empty space."""
    d = Path(tempfile.mkdtemp())
    objs = [
        {"id": "small", "bbox": [10, 10, 60, 60], "animated": False, "views": ["front"]},
        {"id": "huge", "bbox": [0, 0, 380, 520], "animated": False, "views": ["front"]},
    ]
    kept, rejected = extract.crop_objects(_img(400, 600), objs, d)
    assert rejected == [] and len(kept) == 2
    sheet = extract.labelled_sheet(kept, d / "sheet.png")
    with Image.open(sheet) as im:
        assert im.width <= 2 * (extract._CELL + 32)
        assert im.height <= extract._CELL + 64


def test_extract_passes_the_user_s_description_to_the_vision_call():
    """The user knows the game; --text is what makes the model find the
    dispenser it would otherwise read as background."""
    tmp = tempfile.mkdtemp(); _env_ready()
    try:
        pack = Path(tmp) / "out.toml"
        with _VisionStub() as stub:
            code = cli.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
                             "--no-open", "-t", "there is a conveyor in the middle"])
        assert code == 0
        assert stub.user_text == "there is a conveyor in the middle"
    finally:
        _env_clear()


def test_extract_without_text_passes_none():
    tmp = tempfile.mkdtemp(); _env_ready()
    try:
        pack = Path(tmp) / "out.toml"
        with _VisionStub() as stub:
            assert cli.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
                             "--no-open"]) == 0
        assert stub.user_text is None
    finally:
        _env_clear()


def test_extract_also_writes_the_html_input_sheet():
    """Every pack ships with the merged prompts beside it: that file is what
    gets pasted into another model, and building it by hand after each run is
    the step that gets skipped."""
    tmp = tempfile.mkdtemp(); _env_ready()
    try:
        pack = Path(tmp) / "out.toml"
        with _VisionStub():
            assert cli.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
                             "--no-open"]) == 0
        html = pack.with_suffix(".html")
        assert html.exists()
        body = html.read_text()
        ids = [a["id"] for a in tomllib.loads(pack.read_text())["assets"]]
        for asset_id in ids:
            assert asset_id in body
        assert "data:image/" in body          # references inlined, not linked
    finally:
        _env_clear()


def test_a_dry_run_writes_no_html_sheet():
    tmp = tempfile.mkdtemp(); _env_ready()
    try:
        pack = Path(tmp) / "out.toml"
        with _VisionStub():
            assert cli.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
                             "--no-open", "--dry-run"]) == 0
        assert not pack.with_suffix(".html").exists()
    finally:
        _env_clear()


# --- containment ------------------------------------------------------------

def _boxed(**kw):
    return [{"id": k, "bbox": v} for k, v in kw.items()]


def test_a_framing_box_reports_what_it_swallows():
    """A conveyor loop, a tray, a panel: its box contains what it frames, so
    its crop shows the contents too."""
    objs = _boxed(frame=[0, 0, 300, 300], brick=[50, 50, 90, 90], bunny=[100, 100, 140, 140])
    assert extract.find_contents(objs) == {"frame": ["brick", "bunny"]}


def test_a_neighbouring_box_is_not_contained():
    objs = _boxed(left=[0, 0, 100, 100], right=[120, 0, 220, 100])
    assert extract.find_contents(objs) == {}


def test_a_box_overlapping_only_at_its_edge_is_not_contained():
    """Model boxes clip their neighbours by a few pixels routinely; that must
    not read as containment."""
    objs = _boxed(big=[0, 0, 200, 200], edge=[190, 190, 290, 290])
    assert extract.find_contents(objs) == {}


def test_equal_boxes_do_not_contain_each_other():
    objs = _boxed(a=[0, 0, 100, 100], b=[0, 0, 100, 100])
    assert extract.find_contents(objs) == {}


def test_the_prompt_asks_for_the_object_without_its_contents():
    objs = _boxed(frame=[0, 0, 300, 300], brick_cluster=[50, 50, 90, 90])
    objs[0].update(subject="a looping conveyor track", views=["front"], animated=False)
    objs[1].update(subject="a brick", views=["front"], animated=False)
    with tempfile.TemporaryDirectory() as td:
        kept, _ = extract.crop_objects(_img(400, 600), objs, Path(td) / "refs")
        text = extract.pack_text("m/m", "K", {"render": "r"}, kept,
                                 Path(td) / "refs", Path(td) / "p.toml")
    assets = {a["id"]: a["prompt"] for a in tomllib.loads(text)["assets"]}
    assert "without the brick cluster" in assets["frame-front"]
    assert "reference image" in assets["frame-front"]
    assert "without the" not in assets["brick_cluster-front"]


def test_a_long_content_list_is_summarised_not_dumped():
    ids = {f"thing_{i}": [10 * i, 10 * i, 10 * i + 20, 10 * i + 20] for i in range(1, 9)}
    objs = _boxed(frame=[0, 0, 300, 300], **ids)
    inside = extract.find_contents(objs)["frame"]
    assert len(inside) == 8
    clause = extract._exclusion_clause(inside)
    named = [i for i in ids if i.replace("_", " ") in clause]
    assert len(named) == extract.MAX_NAMED_CONTENTS
    assert "and 4 other elements" in clause
    one_over = extract._exclusion_clause([f"thing_{i}" for i in range(5)])
    assert "and 1 other element" in one_over and "1 other elements" not in one_over

