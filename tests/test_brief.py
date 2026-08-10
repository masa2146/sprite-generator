"""sprite brief tests. Run: python3 -m pytest tests/test_brief.py"""
import json
import os
import re
import tempfile
from pathlib import Path

from PIL import Image

import brief

FULL_STYLE = {
    "render": "soft 3D cartoon", "camera": "3/4 front view",
    "lighting": "top-left key", "palette": "#2e2c4a, #ffffff",
    "linework": "dark contour", "realism": "stylized cartoon",
}


def _analysis(**overrides):
    data = {
        "style": dict(FULL_STYLE),
        "style_image": "scene.png",
        "objects": [
            {
                "id": "alpha",
                "bbox": [10, 10, 110, 110],
                "views": ["front", "side"],
                "subject": "a round white rabbit",
                "form": "one rounded body with two long ears",
                "detail": "pink inner ears, dot eyes",
            }
        ],
    }
    data.update(overrides)
    return data


def _write(tmp, data):
    """Write analysis.json, and a dummy image for its style_image if that
    file is not already there — v2 resolves image paths against the analysis
    file and requires them to exist, so any object carrying a bbox needs one
    on disk."""
    tmp = Path(tmp)
    img_name = data.get("style_image")
    if img_name and not (tmp / img_name).exists():
        Image.new("RGB", (200, 200), (90, 90, 120)).save(tmp / img_name)
    path = tmp / "analysis.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_analysis_returns_style_and_objects():
    with tempfile.TemporaryDirectory() as tmp:
        parsed = brief.load_analysis(_write(tmp, _analysis()))
    assert parsed.style == FULL_STYLE
    assert [o["id"] for o in parsed.objects] == ["alpha"]
    assert parsed.objects[0]["views"] == ["front", "side"]
    assert parsed.objects[0]["animated"] is True


def test_a_single_view_object_is_not_marked_animated():
    """labelled_sheet captions each crop with this flag, and a caption that
    misdescribes its crop is the failure this project keeps paying for."""
    data = _analysis()
    data["objects"][0]["views"] = ["front"]
    with tempfile.TemporaryDirectory() as tmp:
        parsed = brief.load_analysis(_write(tmp, data))
    assert parsed.objects[0]["animated"] is False


def test_a_missing_style_is_named_in_the_error():
    data = _analysis()
    del data["style"]
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(tmp, data)
        try:
            brief.load_analysis(path)
        except brief.BriefError as exc:
            assert "style" in str(exc)
        else:
            raise AssertionError("expected BriefError")


def test_a_bad_bbox_names_the_object_and_the_field():
    data = _analysis()
    data["objects"][0]["bbox"] = [1, 2, 3]
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(tmp, data)
        try:
            brief.load_analysis(path)
        except brief.BriefError as exc:
            assert "alpha" in str(exc) and "bbox" in str(exc)
        else:
            raise AssertionError("expected BriefError")


# --- v2 schema: six-field style, style_source, per-object source, optional bbox

def _analysis_dir(payload, images=("shot.png",)):
    d = Path(tempfile.mkdtemp())
    for name in images:
        Image.new("RGB", (200, 200), (90, 90, 120)).save(d / name)
    path = d / "analysis.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_the_six_style_fields_are_read_as_an_object():
    path = _analysis_dir({
        "style": FULL_STYLE, "style_image": "shot.png",
        "objects": [{"id": "a", "subject": "a thing", "bbox": [10, 10, 90, 90]}],
    })
    parsed = brief.load_analysis(path)
    assert parsed.style["camera"] == "3/4 front view"
    assert parsed.style_image.name == "shot.png"


def test_a_missing_style_field_is_named_in_the_error():
    partial = dict(FULL_STYLE)
    del partial["lighting"]
    path = _analysis_dir({"style": partial,
                          "objects": [{"id": "a", "subject": "x"}]})
    try:
        brief.load_analysis(path)
        assert False, "a missing style field must not pass"
    except brief.BriefError as exc:
        assert "lighting" in str(exc)


def test_a_style_given_as_one_string_is_rejected_with_the_shape_it_wants():
    path = _analysis_dir({"style": "glossy cartoon",
                          "objects": [{"id": "a", "subject": "x"}]})
    try:
        brief.load_analysis(path)
        assert False, "schema v1 style must not pass"
    except brief.BriefError as exc:
        assert "render" in str(exc) and "camera" in str(exc)


def test_an_unspecified_style_source_reads_as_belirtilmemis():
    path = _analysis_dir({"style": FULL_STYLE,
                          "style_source": {"render": "kullanıcı"},
                          "objects": [{"id": "a", "subject": "x"}]})
    parsed = brief.load_analysis(path)
    assert parsed.style_source["render"] == "kullanıcı"
    assert parsed.style_source["palette"] == "belirtilmemiş"


def test_paths_resolve_against_the_analysis_file_not_the_cwd():
    path = _analysis_dir({"style": FULL_STYLE, "style_image": "shot.png",
                          "objects": [{"id": "a", "subject": "x"}]})
    parsed = brief.load_analysis(path)
    assert parsed.style_image.is_absolute()
    assert parsed.style_image.exists()


def test_an_object_falls_back_to_the_style_image_for_its_source():
    path = _analysis_dir({"style": FULL_STYLE, "style_image": "shot.png",
                          "objects": [{"id": "a", "subject": "x",
                                       "bbox": [10, 10, 90, 90]}]})
    obj = brief.load_analysis(path).objects[0]
    assert obj["source"].name == "shot.png"


def test_an_object_may_name_its_own_source():
    path = _analysis_dir({"style": FULL_STYLE, "style_image": "shot.png",
                          "objects": [{"id": "a", "subject": "x",
                                       "source": "other.png"}]},
                         images=("shot.png", "other.png"))
    assert brief.load_analysis(path).objects[0]["source"].name == "other.png"


def test_an_object_with_no_image_anywhere_is_allowed():
    path = _analysis_dir({"style": FULL_STYLE,
                          "objects": [{"id": "a", "subject": "x"}]},
                         images=())
    assert brief.load_analysis(path).objects[0]["source"] is None


def test_a_bbox_without_an_image_names_the_object():
    path = _analysis_dir({"style": FULL_STYLE,
                          "objects": [{"id": "a", "subject": "x",
                                       "bbox": [1, 1, 9, 9]}]},
                         images=())
    try:
        brief.load_analysis(path)
        assert False, "a box with nothing to cut it out of must not pass"
    except brief.BriefError as exc:
        assert "a" in str(exc) and "bbox" in str(exc)


def test_a_missing_source_file_names_the_path():
    path = _analysis_dir({"style": FULL_STYLE,
                          "objects": [{"id": "a", "subject": "x",
                                       "source": "gone.png"}]},
                         images=())
    try:
        brief.load_analysis(path)
        assert False, "a source that is not on disk must not pass"
    except brief.BriefError as exc:
        assert "gone.png" in str(exc)


def test_a_bbox_is_optional_now():
    path = _analysis_dir({"style": FULL_STYLE, "style_image": "shot.png",
                          "objects": [{"id": "a", "subject": "x"}]})
    obj = brief.load_analysis(path).objects[0]
    assert obj["bbox"] is None
    # no bbox and no source, but a style_image present: the shape the
    # fallback rule changed. source must be None, not the style_image.
    assert obj["source"] is None


def test_an_object_with_neither_bbox_nor_source_gets_no_picture_even_with_a_style_image():
    """style_image is the picture boxes are CUT from, not a fallback for
    anything undescribed. The old unconditional fallback handed a purely
    described object — "make me a shield icon in this screen's style", where
    the shield is not in the screenshot — the entire screen as its identity
    source, with nothing to cut it down. The measured relative: a conveyor
    loop boxed whole gave its track 80px of a 1024px picture and came back as
    a picture frame under every wording tried. With no bbox to cut, there is
    nothing to inherit."""
    path = _analysis_dir({"style": FULL_STYLE, "style_image": "shot.png",
                          "objects": [{"id": "a", "subject": "x"}]})
    obj = brief.load_analysis(path).objects[0]
    assert obj["source"] is None
    assert brief.crop_mode(obj) == "text"


def test_an_object_with_a_bbox_and_no_source_still_inherits_the_style_image():
    # the common case — a box cut out of the shared screenshot — must not regress
    path = _analysis_dir({"style": FULL_STYLE, "style_image": "shot.png",
                          "objects": [{"id": "a", "subject": "x",
                                       "bbox": [10, 10, 90, 90]}]})
    obj = brief.load_analysis(path).objects[0]
    assert obj["source"].name == "shot.png"
    assert brief.crop_mode(obj) == "crop"


def test_an_object_may_name_the_shared_picture_as_its_own_whole_source():
    # now that the fallback no longer hands out the shared picture for free,
    # naming it explicitly as 'source' is the only way to ask for it whole
    path = _analysis_dir({"style": FULL_STYLE, "style_image": "shot.png",
                          "objects": [{"id": "a", "subject": "x",
                                       "source": "shot.png"}]})
    obj = brief.load_analysis(path).objects[0]
    assert obj["source"].name == "shot.png"
    assert brief.crop_mode(obj) == "whole"


def test_an_empty_object_list_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(tmp, _analysis(objects=[]))
        try:
            brief.load_analysis(path)
        except brief.BriefError as exc:
            assert "objects" in str(exc)
        else:
            raise AssertionError("expected BriefError")


def test_unreadable_json_names_the_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "analysis.json"
        path.write_text("{not json", encoding="utf-8")
        try:
            brief.load_analysis(path)
        except brief.BriefError as exc:
            assert "analysis.json" in str(exc)
        else:
            raise AssertionError("expected BriefError")


# --- crop_mode and prepare_refs: the crop decision --------------------------

def test_crop_mode_reads_the_three_cases():
    assert brief.crop_mode({"source": Path("a.png"), "bbox": [1, 2, 3, 4]}) == "crop"
    assert brief.crop_mode({"source": Path("a.png"), "bbox": None}) == "whole"
    assert brief.crop_mode({"source": None, "bbox": None}) == "text"


def test_a_whole_image_object_is_copied_not_cut():
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (120, 90), (40, 160, 90)).save(d / "one.png")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [{"id": "blob", "subject": "a blob", "source": "one.png"}],
    }), encoding="utf-8")
    kept, rejected, _, _ = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert not rejected
    assert kept[0]["crop"].name == "blob.png"
    with Image.open(kept[0]["crop"]) as done:
        # cleaned (upscaled past the capture's stair-stepping) but not cropped:
        # the aspect ratio of the source survives
        assert round(done.width / done.height, 2) == round(120 / 90, 2)


def test_a_text_only_object_gets_no_crop_and_is_not_rejected():
    d = Path(tempfile.mkdtemp())
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [{"id": "idea", "subject": "a thing I described"}],
    }), encoding="utf-8")
    kept, rejected, _, _ = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert not rejected
    assert kept[0].get("crop") is None
    assert kept[0].get("palette") in (None, [])


def test_a_text_only_object_writes_no_ref_even_with_a_style_image():
    # a described-only object is a legitimate shape, not a failure — it must
    # be kept, and must not silently inherit the shared screenshot as its ref
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (200, 200), (90, 90, 120)).save(d / "shot.png")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE, "style_image": "shot.png",
        "objects": [{"id": "idea", "subject": "a shield, not in this screenshot"}],
    }), encoding="utf-8")
    kept, rejected, _, _ = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert not rejected
    assert kept[0]["id"] == "idea"
    assert kept[0].get("crop") is None
    assert not (d / "refs" / "idea.png").exists()


def test_a_blank_on_a_whole_image_object_is_reported_not_silently_dropped():
    # blank is only wired up for a bbox-cropped object (crops.blank_contents).
    # A 'whole' object that carries one gets no crash and no effect — which is
    # the silent drop this whole flow is built against — so it must be named
    # in the notes instead.
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (120, 90), (40, 160, 90)).save(d / "one.png")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [{"id": "blob", "subject": "a blob", "source": "one.png",
                    "blank": [[0, 0, 10, 10]]}],
    }), encoding="utf-8")
    kept, rejected, _, notes = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert not rejected
    assert kept[0]["id"] == "blob"  # still kept: this is a note, not a rejection
    assert any("blob" in note for note in notes)


def test_a_blank_on_a_text_only_object_is_reported_too():
    d = Path(tempfile.mkdtemp())
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [{"id": "idea", "subject": "a thing I described",
                    "blank": [[0, 0, 10, 10]]}],
    }), encoding="utf-8")
    _, _, _, notes = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert any("idea" in note for note in notes)


def test_a_blank_on_a_cropped_object_is_not_reported():
    # the one shape blank actually does something on — no note expected
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (200, 200), (90, 90, 120)).save(d / "shot.png")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [{"id": "alpha", "subject": "x", "source": "shot.png",
                    "bbox": [10, 10, 90, 90], "blank": [[20, 20, 30, 30]]}],
    }), encoding="utf-8")
    _, _, _, notes = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert notes == []


def test_boxes_are_only_compared_within_one_source_image():
    d = Path(tempfile.mkdtemp())
    for name in ("a.png", "b.png"):
        Image.new("RGB", (200, 200), (70, 70, 90)).save(d / name)
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [
            {"id": "big", "subject": "a frame", "source": "a.png",
             "bbox": [10, 10, 190, 190]},
            # identical box, different picture: it is NOT inside `big`
            {"id": "other", "subject": "a thing", "source": "b.png",
             "bbox": [20, 20, 120, 120]},
        ],
    }), encoding="utf-8")
    _, _, contents, _ = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert "big" not in contents, "boxes from two different images were compared"


def test_a_box_inside_another_on_the_same_image_is_still_found():
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (200, 200), (70, 70, 90)).save(d / "a.png")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [
            {"id": "tray", "subject": "a tray", "source": "a.png",
             "bbox": [10, 10, 190, 190]},
            {"id": "puck", "subject": "a puck", "source": "a.png",
             "bbox": [60, 60, 120, 120]},
        ],
    }), encoding="utf-8")
    _, _, contents, _ = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert contents.get("tray") == ["puck"]


def test_a_rejected_box_does_not_take_its_neighbours_down():
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (200, 200), (70, 70, 90)).save(d / "a.png")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [
            {"id": "good", "subject": "ok", "source": "a.png",
             "bbox": [10, 10, 90, 90]},
            {"id": "tiny", "subject": "too small", "source": "a.png",
             "bbox": [10, 10, 14, 14]},
        ],
    }), encoding="utf-8")
    kept, rejected, _, _ = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert [o["id"] for o in kept] == ["good"]
    assert rejected and rejected[0][0] == "tiny"


def test_a_duplicate_id_across_two_source_images_is_rejected():
    """Grouping boxed objects by source narrowed screen_objects's duplicate
    check to one image at a time. Two boxed objects sharing an id in two
    DIFFERENT images used to land on the same refs_dir/<id>.png with no
    rejection printed — the first object's picture silently became the
    second's."""
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (200, 200), (10, 10, 10)).save(d / "a.png")
    Image.new("RGB", (200, 200), (250, 250, 250)).save(d / "b.png")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [
            {"id": "dup", "subject": "first", "source": "a.png",
             "bbox": [10, 10, 90, 90]},
            {"id": "dup", "subject": "second", "source": "b.png",
             "bbox": [10, 10, 90, 90]},
        ],
    }), encoding="utf-8")
    kept, rejected, _, _ = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert [o["id"] for o in kept] == ["dup"]
    assert rejected == [("dup", "duplicate id")]
    with Image.open(kept[0]["crop"]) as crop:
        sample = crop.convert("RGB").getpixel((0, 0))
    # a.png's near-black fill survived cleanup; b.png's near-white one never
    # got a chance to overwrite the file.
    assert sum(sample) < 200


def test_a_whole_object_and_a_crop_object_sharing_an_id_is_rejected():
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (200, 200), (10, 10, 10)).save(d / "a.png")
    Image.new("RGB", (200, 200), (250, 250, 250)).save(d / "b.png")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [
            {"id": "dup", "subject": "first, whole", "source": "a.png"},
            {"id": "dup", "subject": "second, boxed", "source": "b.png",
             "bbox": [10, 10, 90, 90]},
        ],
    }), encoding="utf-8")
    kept, rejected, _, _ = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert [o["id"] for o in kept] == ["dup"]
    assert rejected == [("dup", "duplicate id")]
    with Image.open(kept[0]["crop"]) as crop:
        sample = crop.convert("RGB").getpixel((0, 0))
    assert sum(sample) < 200


def test_duplicate_ids_differing_only_in_case_are_rejected_across_sources():
    """Consistent with screen_objects (crops.py), which already treats
    "Block" and "block" as one filename on a case-insensitive filesystem."""
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (200, 200), (10, 10, 10)).save(d / "a.png")
    Image.new("RGB", (200, 200), (250, 250, 250)).save(d / "b.png")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [
            {"id": "Dup", "subject": "first", "source": "a.png",
             "bbox": [10, 10, 90, 90]},
            {"id": "dup", "subject": "second", "source": "b.png",
             "bbox": [10, 10, 90, 90]},
        ],
    }), encoding="utf-8")
    kept, rejected, _, _ = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert [o["id"] for o in kept] == ["Dup"]
    assert rejected == [("dup", "duplicate id")]


# --- id format, all three crop shapes (finding 1) ----------------------------

def test_a_whole_shape_object_with_a_path_escaping_id_is_rejected():
    """crops._ID_RE's format check lived only inside screen_objects, which
    just the 'crop' branch reaches — a 'whole' object's id went straight into
    refs_dir / f"{id}.png" with no check at all, so "../escaped" wrote outside
    the refs directory."""
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (120, 90), (40, 160, 90)).save(d / "one.png")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [{"id": "../escaped", "subject": "a blob", "source": "one.png"}],
    }), encoding="utf-8")
    kept, rejected, _, _ = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert kept == []
    assert rejected == [("../escaped", "unusable id")]
    assert not (d / "escaped.png").exists()


def test_a_text_shape_object_with_a_bad_id_is_rejected():
    d = Path(tempfile.mkdtemp())
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [{"id": "a/b", "subject": "a thing I described"}],
    }), encoding="utf-8")
    kept, rejected, _, _ = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert kept == []
    assert rejected == [("a/b", "unusable id")]


def test_an_id_of_style_does_not_collide_with_the_style_copy():
    """"_style" starts with "_", which ID_RE rejects (no leading alnum) — the
    same regex that already rejects "../escaped". Before this check covered
    the 'whole' shape, an object named "_style" wrote refs/_style.png, and
    then main()'s own shutil.copyfile(style_image) silently overwrote it, so
    review.html showed the whole screenshot as that object's crop with
    nothing saying so."""
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (200, 200), (90, 90, 120)).save(d / "shot.png")
    Image.new("RGB", (120, 90), (40, 160, 90)).save(d / "one.png")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE, "style_image": "shot.png",
        "objects": [
            {"id": "alpha", "subject": "a thing", "bbox": [10, 10, 90, 90]},
            {"id": "_style", "subject": "a blob", "source": "one.png"},
        ],
    }), encoding="utf-8")
    out_dir = d / "brief"
    code = brief.main(["--analysis", str(path), "--out-dir", str(out_dir), "--no-open"])
    assert code == 0
    with Image.open(out_dir / "refs" / "_style.png") as im:
        # the style image (200x200), never "one.png" (120x90) under a stolen name
        assert im.size == (200, 200)


# --- unrecognised view names (finding 2) -------------------------------------

def test_a_mistyped_view_produces_a_note_naming_the_object_and_the_name():
    d = Path(tempfile.mkdtemp())
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [{"id": "alpha", "subject": "x", "views": ["3/4", "frnt"]}],
    }), encoding="utf-8")
    _, _, _, notes = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert any("alpha" in note and "3/4" in note and "frnt" in note for note in notes)


def test_the_written_copy_carries_the_normalised_views_not_the_typed_ones():
    d = Path(tempfile.mkdtemp())
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [{"id": "alpha", "subject": "x", "views": ["3/4"]}],
    }), encoding="utf-8")
    out_dir = d / "brief"
    code = brief.main(["--analysis", str(path), "--out-dir", str(out_dir), "--no-open"])
    assert code == 0
    stamped = json.loads((out_dir / "analysis.json").read_text())
    # "3/4" is not a VIEW_POOL member, so normalise_views drops it and falls
    # back to the default — the copy procedural-sprites reads must agree with
    # what review.html actually rendered, not with what the user typed.
    assert stamped["objects"][0]["views"] == ["front"]


# --- a malformed 'blank' box, wrong arity (finding 10) -----------------------

def test_a_malformed_blank_box_is_reported_not_silently_dropped():
    """'blank' on the wrong SHAPE (a whole/text object) is already reported.
    'blank: [[1, 2, 3]]' — the right shape, a box of the wrong ARITY — used to
    be filtered out by crops.blank_contents with no trace at all."""
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (200, 200), (90, 90, 120)).save(d / "shot.png")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [{"id": "piece", "subject": "x", "source": "shot.png",
                    "bbox": [10, 10, 90, 90], "blank": [[1, 2, 3]]}],
    }), encoding="utf-8")
    _, _, _, notes = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert any("piece" in note for note in notes)


# --- one unreadable source among several (finding 12) ------------------------

def test_one_unreadable_source_does_not_take_the_others_down():
    """prepare_refs isolates a failing source (brief.py's 'whole' branch and
    its boxed-group branch each catch OSError on their own Image.open) so an
    object from a different, readable source survives."""
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (200, 200), (90, 90, 120)).save(d / "good.png")
    bad = d / "bad.png"
    bad.write_text("not an image", encoding="utf-8")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [
            {"id": "ok", "subject": "x", "source": "good.png", "bbox": [10, 10, 90, 90]},
            {"id": "broken", "subject": "y", "source": "bad.png", "bbox": [10, 10, 90, 90]},
        ],
    }), encoding="utf-8")
    kept, rejected, _, _ = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert [o["id"] for o in kept] == ["ok"]
    assert len(rejected) == 1
    assert rejected[0][0] == "broken"
    assert "bad.png" in rejected[0][1]


# --- the HTML review page ----------------------------------------------------

def _rendered(objects, style_image="shot.png", images=("shot.png",)):
    d = Path(tempfile.mkdtemp())
    for name in images:
        Image.new("RGB", (200, 200), (90, 90, 120)).save(d / name)
    payload = {"style": FULL_STYLE, "style_source": {"render": "kullanıcı"},
               "objects": objects}
    if style_image:
        payload["style_image"] = style_image
    path = d / "analysis.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    parsed = brief.load_analysis(path)
    kept, _, contents, _ = brief.prepare_refs(parsed, d / "refs")
    return brief.page(parsed, kept, contents, "t")


def test_the_review_section_prints_every_style_field_with_its_source():
    html = _rendered([{"id": "a", "subject": "x", "bbox": [10, 10, 90, 90]}])
    for field in brief.STYLE_FIELDS:
        assert field in html
    assert "kullanıcı" in html
    assert "belirtilmemiş" in html          # the fields nobody claimed


def test_the_review_section_shows_the_measured_palette_as_swatches():
    html = _rendered([{"id": "a", "subject": "x", "bbox": [10, 10, 90, 90]}])
    swatches = re.findall(r"class='swatch' style='background:(#[0-9A-Fa-f]{6})'", html)
    assert swatches, "no measured colour reached the page"
    # the crop is one flat colour, so its dominant swatch is that colour
    rgb = tuple(int(swatches[0][i:i + 2], 16) for i in (1, 3, 5))
    assert all(abs(a - b) <= 12 for a, b in zip(rgb, (90, 90, 120))), swatches[0]
    assert f"<code>{swatches[0]}</code>" in html


def test_the_prompt_section_carries_a_paste_ready_block_per_view():
    html = _rendered([{"id": "a", "subject": "x", "bbox": [10, 10, 90, 90],
                       "views": ["front", "side"]}])
    assert html.count("DO NOT DRAW") == 2
    assert "a-front" in html and "a-side" in html


def test_the_prompt_names_both_pictures_when_a_style_image_exists():
    html = _rendered([{"id": "a", "subject": "x", "bbox": [10, 10, 90, 90]}])
    assert "Picture 1" in html and "Picture 2" in html


def test_the_prompt_names_one_picture_when_there_is_no_style_image():
    html = _rendered([{"id": "a", "subject": "x", "source": "shot.png",
                       "bbox": [10, 10, 90, 90]}], style_image=None)
    assert "Picture 2" not in html


def test_a_text_only_object_still_gets_a_prompt_and_says_it_has_no_picture():
    html = _rendered([{"id": "idea", "subject": "a described thing"}],
                     style_image=None, images=())
    assert "idea-front" in html
    assert "görsel yok" in html
    assert "Picture 1" not in html


def test_the_style_image_is_inlined_once_no_matter_how_many_objects():
    html = _rendered([{"id": "a", "subject": "x", "bbox": [10, 10, 90, 90]},
                      {"id": "b", "subject": "y", "bbox": [100, 100, 190, 190]}])
    # Measured: repeating the same base64 blob per asset produced a 55 MB page
    # from a 2.4 MB screenshot across 17 assets.
    assert html.count("data:image/png;base64,") == 3   # style + two crops


def test_the_page_escapes_ids_and_prompt_text():
    html = _rendered([{"id": "a", "subject": "<script>alert(1)</script>",
                       "bbox": [10, 10, 90, 90]}])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_the_page_references_no_external_file():
    html = _rendered([{"id": "a", "subject": "x", "bbox": [10, 10, 90, 90]}])
    assert "http://" not in html and "https://" not in html
    assert 'src="refs/' not in html


# --- the command ------------------------------------------------------------

def _scene(tmp, size=(400, 600)):
    from PIL import Image
    path = Path(tmp) / "scene.png"
    Image.new("RGB", size, (30, 30, 50)).save(path)
    return path


def _run(tmp, data=None, out_name="b", extra=None):
    scene = _scene(tmp)
    analysis = _write(tmp, data if data is not None else _analysis())
    out_dir = Path(tmp) / out_name
    # --no-open: without it, main() reaches webbrowser.open and a full-suite
    # run opens a window per test that writes a contact sheet.
    argv = ["--analysis", str(analysis), "--out-dir", str(out_dir), "--no-open"]
    return brief.main(argv + (extra or [])), out_dir, scene


def test_main_writes_review_html_and_the_inner_analysis():
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (200, 200), (90, 90, 120)).save(d / "shot.png")
    src = d / "analysis.json"
    src.write_text(json.dumps({
        "style": FULL_STYLE, "style_image": "shot.png",
        "objects": [{"id": "a", "subject": "x", "bbox": [10, 10, 90, 90]}],
    }), encoding="utf-8")
    out = d / "brief"
    assert brief.main(["--analysis", str(src), "--out-dir", str(out),
                       "--no-open"]) == 0
    assert (out / "review.html").exists()
    assert (out / "analysis.json").exists()
    assert (out / "refs" / "a.png").exists()
    assert (out / "refs" / "_style.png").exists()


def test_two_views_produce_two_prompts_over_one_crop():
    """Same crop, different VIEW line — the semantics extract already uses."""
    with tempfile.TemporaryDirectory() as tmp:
        code, out_dir, _scene_path = _run(tmp)
        body = (out_dir / "review.html").read_text()
        assert code == 0
        # one prompt block per view, each ending in its own DO NOT DRAW —
        # distinct from the single review-section '.asset' the object itself gets
        assert body.count("DO NOT DRAW") == 2
        assert "alpha-front" in body and "alpha-side" in body
        assert len(list((out_dir / "refs").glob("alpha*.png"))) == 1


def test_a_contained_object_reaches_the_do_not_draw_list():
    data = _analysis(objects=[
        {"id": "frame", "bbox": [0, 0, 300, 300], "views": ["front"],
         "subject": "a framing track"},
        {"id": "brick", "bbox": [50, 50, 90, 90], "views": ["front"],
         "subject": "a brick"},
    ])
    with tempfile.TemporaryDirectory() as tmp:
        code, out_dir, _s = _run(tmp, data)
        body = (out_dir / "review.html").read_text()
    assert code == 0
    assert "visible inside it in the reference image" in body
    assert "brick" in body


def test_a_rejected_box_is_reported_and_the_rest_survive():
    data = _analysis(objects=[
        {"id": "alpha", "bbox": [10, 10, 110, 110], "views": ["front"],
         "subject": "a thing"},
        {"id": "whole", "bbox": [0, 0, 400, 600], "views": ["front"],
         "subject": "the whole screen"},
    ])
    with tempfile.TemporaryDirectory() as tmp:
        code, out_dir, _s = _run(tmp, data)
        body = (out_dir / "review.html").read_text()
        assert code == 0
        assert "alpha-front" in body
        assert "whole-front" not in body
        assert not (out_dir / "refs" / "whole.png").exists()


def test_no_usable_object_writes_nothing():
    data = _analysis(objects=[
        {"id": "whole", "bbox": [0, 0, 400, 600], "views": ["front"],
         "subject": "the whole screen"},
    ])
    with tempfile.TemporaryDirectory() as tmp:
        code, out_dir, _s = _run(tmp, data)
        assert code == 1
        assert not (out_dir / "review.html").exists()


def test_an_existing_brief_is_not_overwritten_from_an_outside_analysis():
    """A brief you have already reviewed and pruned is the most valuable thing
    in this flow."""
    with tempfile.TemporaryDirectory() as tmp:
        code, out_dir, _s = _run(tmp)
        assert code == 0
        marker = "<!-- mine -->"
        (out_dir / "review.html").write_text(marker, encoding="utf-8")
        code2, _o, _s2 = _run(tmp)
        assert code2 == 1
        assert (out_dir / "review.html").read_text() == marker


def test_rerunning_from_the_briefs_own_analysis_is_allowed():
    """The whole review loop is: edit analysis.json in place, run again."""
    with tempfile.TemporaryDirectory() as tmp:
        code, out_dir, _scene_path = _run(tmp)
        assert code == 0
        inner = out_dir / "analysis.json"
        data = json.loads(inner.read_text())
        data["objects"][0]["subject"] = "a SECOND PASS rabbit"
        inner.write_text(json.dumps(data), encoding="utf-8")
        code2 = brief.main(["--analysis", str(inner), "--out-dir", str(out_dir),
                           "--no-open"])
        assert code2 == 0
        assert "a SECOND PASS rabbit" in (out_dir / "review.html").read_text()


def test_the_review_copy_stamps_per_object_source_too():
    """Carried forward from task 7's review: the copy stamps style_image as an
    absolute path so a rerun from out_dir still finds it. Task 7 could leave
    per-object 'source' alone because nothing cropped from it yet; task 8 does,
    so the same stamping has to apply to it too, or a rerun of the copy loses
    any object whose source was written as a path relative to the ORIGINAL
    analysis file (which out_dir is not)."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        Image.new("RGB", (200, 200), (90, 90, 120)).save(d / "scene.png")
        Image.new("RGB", (150, 100), (10, 200, 10)).save(d / "obj.png")
        data = _analysis(objects=[
            {"id": "alpha", "subject": "a thing", "source": "obj.png"},
        ])
        analysis_path = d / "analysis.json"
        analysis_path.write_text(json.dumps(data), encoding="utf-8")
        out_dir = d / "b"

        code = brief.main(["--analysis", str(analysis_path), "--out-dir", str(out_dir),
                          "--no-open"])
        assert code == 0

        inner = out_dir / "analysis.json"
        stamped = json.loads(inner.read_text())
        stamped_source = Path(stamped["objects"][0]["source"])
        assert stamped_source.is_absolute()
        assert stamped_source == (d / "obj.png").resolve()

        # The review loop runs the copy again from wherever the user happens
        # to be, not from the original analysis's directory — so load it from
        # a different working directory and confirm the image is still found.
        elsewhere = Path(tempfile.mkdtemp())
        old_cwd = os.getcwd()
        os.chdir(elsewhere)
        try:
            parsed = brief.load_analysis(inner)
        finally:
            os.chdir(old_cwd)
        assert parsed.objects[0]["source"] == (d / "obj.png").resolve()


def test_the_review_copy_stamps_the_measured_palette_too():
    """clean_crops measures a cropped object's real palette onto `kept`, but
    the copy written to out_dir is re-parsed from the ORIGINAL file — so
    without stamping it here, the measurement reaches review.html and never
    analysis.json, which is what procedural-sprites actually reads. A
    text-only object has no crop and so must get no 'palette' key at all."""
    with tempfile.TemporaryDirectory() as tmp:
        data = _analysis(objects=[
            {"id": "alpha", "bbox": [10, 10, 110, 110], "views": ["front"],
             "subject": "a thing"},
            {"id": "label", "subject": "a text badge with no picture"},
        ])
        code, out_dir, _s = _run(tmp, data)
        assert code == 0

        stamped = json.loads((out_dir / "analysis.json").read_text())
        by_id = {o["id"]: o for o in stamped["objects"]}
        assert re.fullmatch(r"#[0-9A-F]{6}", by_id["alpha"]["palette"][0])
        assert "palette" not in by_id["label"]


def test_a_bad_analysis_writes_nothing_and_exits_one():
    data = _analysis()
    del data["style"]
    with tempfile.TemporaryDirectory() as tmp:
        code, out_dir, _s = _run(tmp, data)
        assert code == 1
        assert not (out_dir / "review.html").exists()


def test_an_unreadable_image_exits_one():
    with tempfile.TemporaryDirectory() as tmp:
        # _analysis()'s style_image is "scene.png" — write the corrupt file
        # there directly so _write finds it already on disk and leaves it be.
        bad = Path(tmp) / "scene.png"
        bad.write_text("not an image", encoding="utf-8")
        analysis = _write(tmp, _analysis())
        code = brief.main(["--analysis", str(analysis),
                           "--out-dir", str(Path(tmp) / "b"), "--no-open"])
    assert code == 1


def test_main_writes_review_html_end_to_end_with_no_style_image():
    """Carried forward from task 8's review: main() used to fail late — after
    the crops were already written — because the old single-section page()
    had nowhere to put a "Picture 2" it did not have. It must now succeed."""
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (150, 100), (10, 200, 10)).save(d / "obj.png")
    data = _analysis(objects=[{"id": "alpha", "subject": "a thing", "source": "obj.png"}])
    del data["style_image"]
    analysis_path = d / "analysis.json"
    analysis_path.write_text(json.dumps(data), encoding="utf-8")
    out_dir = d / "b"

    code = brief.main(["--analysis", str(analysis_path), "--out-dir", str(out_dir),
                       "--no-open"])
    assert code == 0
    body = (out_dir / "review.html").read_text()
    assert "Picture 2" not in body
    assert not (out_dir / "refs" / "_style.png").exists()

