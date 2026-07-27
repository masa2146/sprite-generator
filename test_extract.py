"""extract mechanics tests. Run: python3 test_extract.py"""
import tempfile
import tomllib
from pathlib import Path

from PIL import Image

import extract


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


def test_crop_dimensions_match_the_box():
    d = Path(tempfile.mkdtemp())
    kept, _ = extract.crop_objects(_img(), _objects(), d)
    with Image.open(kept[0]["crop"]) as im:
        assert im.size == (100, 100)


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
    return extract.pack_text("m/model", style, kept,
                             Path(tmp) / "refs", Path(tmp) / "p.toml")


def test_pack_text_parses_as_toml():
    tmp = tempfile.mkdtemp()
    d = tomllib.loads(_pack_text(tmp))
    assert d["pack"]["model"] == "m/model"
    assert "render-value" in d["style"]["prefix"]


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
    import vision
    assert assets[1]["prompt"].endswith(vision.VIEW_POOL["side"])
    assert "a round thing" in assets[1]["prompt"]      # form is carried


def test_no_style_field_leaks_into_an_asset_prompt():
    tmp = tempfile.mkdtemp()
    for a in tomllib.loads(_pack_text(tmp))["assets"]:
        assert "render-value" not in a["prompt"]


def test_a_quote_in_a_description_does_not_break_the_toml():
    tmp = tempfile.mkdtemp()
    style = {f: f"{f}-value" for f in
             ("render", "camera", "lighting", "palette", "linework", "realism")}
    objs = _objects()
    objs[0]["subject"] = 'a "glossy" thing with a \\ in it'
    kept, _ = extract.crop_objects(_img(), objs, Path(tmp) / "refs")
    text = extract.pack_text("m/model", style, kept,
                             Path(tmp) / "refs", Path(tmp) / "p.toml")
    assert 'a "glossy" thing' in tomllib.loads(text)["assets"][0]["prompt"]


def test_a_backslash_or_triple_quote_in_a_style_field_does_not_break_the_toml():
    tmp = tempfile.mkdtemp()
    style = {f: f"{f}-value" for f in
             ("render", "camera", "lighting", "palette", "linework", "realism")}
    style["camera"] = "50mm w\\ shallow DOF"
    style["lighting"] = 'has \"\"\" inside'
    kept, _ = extract.crop_objects(_img(), _objects(), Path(tmp) / "refs")
    text = extract.pack_text("m/model", style, kept,
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
    text = extract.pack_text("m/model", {}, kept, refs_dir, pack_dir / "p.toml")
    ref = tomllib.loads(text)["assets"][0]["reference"]
    assert not Path(ref).is_absolute()
    assert ref.startswith("..")


# --- the command ------------------------------------------------------------

import json
import os

import gen

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

    def __enter__(self):
        self._orig = gen.vision.analyze_objects
        import envfile
        self._env = envfile.DEFAULT_ENV_PATH
        envfile.DEFAULT_ENV_PATH = Path(tempfile.mkdtemp()) / "absent.env"

        def fake(pack, image_bytes, **kw):
            self.calls += 1
            if self.error:
                raise self.error
            return self.reply, json.dumps(self.reply)

        gen.vision.analyze_objects = fake
        return self

    def __exit__(self, *exc):
        gen.vision.analyze_objects = self._orig
        import envfile
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
            code = gen.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
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
            code = gen.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
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
            code = gen.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
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
            code = gen.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
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
            code = gen.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
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
            gen.main(["extract", "-i", str(_scene(tmp)), "--pack", str(pack),
                      "--no-open", "--max-objects", "5"])
        assert len(tomllib.loads(pack.read_text())["assets"]) == 5
    finally:
        _env_clear()


def test_extract_missing_image_exits_cleanly():
    tmp = tempfile.mkdtemp(); _env_ready()
    try:
        with _VisionStub() as stub:
            code = gen.main(["extract", "-i", str(Path(tmp) / "nope.png"),
                             "--pack", str(Path(tmp) / "out.toml"), "--no-open"])
        assert code == 1
        assert stub.calls == 0
    finally:
        _env_clear()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all extract tests passed")
