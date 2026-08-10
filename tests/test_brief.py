"""sprite brief tests. Run: python3 -m pytest tests/test_brief.py"""
import json
import tempfile
from pathlib import Path

import brief


def _analysis(**overrides):
    data = {
        "style": "soft 3D cartoon, glossy plastic, #2e2c4a, #ffffff",
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
    path = Path(tmp) / "analysis.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_analysis_returns_style_and_objects():
    with tempfile.TemporaryDirectory() as tmp:
        style, objects = brief.load_analysis(_write(tmp, _analysis()))
    # Schema v1's one-line style, wrapped as the dict prompts.asset_prompt
    # expects — see the bridge comment in load_analysis.
    assert style == {"render": "soft 3D cartoon, glossy plastic, #2e2c4a, #ffffff"}
    assert [o["id"] for o in objects] == ["alpha"]
    assert objects[0]["views"] == ["front", "side"]
    assert objects[0]["animated"] is True


def test_a_single_view_object_is_not_marked_animated():
    """labelled_sheet captions each crop with this flag, and a caption that
    misdescribes its crop is the failure this project keeps paying for."""
    data = _analysis()
    data["objects"][0]["views"] = ["front"]
    with tempfile.TemporaryDirectory() as tmp:
        _style, objects = brief.load_analysis(_write(tmp, data))
    assert objects[0]["animated"] is False


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


# --- the HTML brief ---------------------------------------------------------

def _png(path, size=(20, 20), colour=(200, 30, 30)):
    from PIL import Image
    Image.new("RGB", size, colour).save(path)
    return Path(path)


def test_the_page_inlines_both_images():
    """The file has to survive being moved or mailed; refs/ does not travel
    with it."""
    with tempfile.TemporaryDirectory() as tmp:
        crop = _png(Path(tmp) / "alpha.png")
        style = _png(Path(tmp) / "_style.png", size=(40, 40))
        html_text = brief.page(
            [{"id": "alpha-front", "crop": crop, "prompt": "P"}], style, "t")
    assert html_text.count("data:image/png;base64,") == 2
    assert "alpha.png" in html_text          # named so the upload is findable
    assert "_style.png" in html_text


def test_the_style_image_is_inlined_once_no_matter_how_many_assets():
    """Inlining it per asset produced a 55 MB file for a 2.4 MB screenshot
    across 17 assets. Each asset still names the file, so the rule that both
    images go with every message survives without the bytes."""
    with tempfile.TemporaryDirectory() as tmp:
        crop = _png(Path(tmp) / "alpha.png")
        style = _png(Path(tmp) / "_style.png", size=(40, 40))
        entries = [{"id": f"alpha-{i}", "crop": crop, "prompt": "P"} for i in range(4)]
        html_text = brief.page(entries, style, "t")
    assert html_text.count("data:image/png;base64,") == len(entries) + 1
    assert html_text.count("_style.png") == len(entries) + 1   # named per asset


def test_each_asset_gets_its_own_section_and_prompt():
    with tempfile.TemporaryDirectory() as tmp:
        crop = _png(Path(tmp) / "alpha.png")
        style = _png(Path(tmp) / "_style.png")
        entries = [{"id": "alpha-front", "crop": crop, "prompt": "PROMPT ONE"},
                   {"id": "alpha-side", "crop": crop, "prompt": "PROMPT TWO"}]
        html_text = brief.page(entries, style, "t")
    assert html_text.count("class='asset'") == 2
    assert "PROMPT ONE" in html_text and "PROMPT TWO" in html_text
    assert "alpha-front" in html_text and "alpha-side" in html_text


def test_the_page_escapes_prompt_text_and_ids():
    with tempfile.TemporaryDirectory() as tmp:
        crop = _png(Path(tmp) / "alpha.png")
        style = _png(Path(tmp) / "_style.png")
        html_text = brief.page(
            [{"id": "a<b>", "crop": crop, "prompt": "draw a <script> & thing"}],
            style, "t<i>")
    assert "<script>" not in html_text
    assert "&lt;script&gt;" in html_text
    assert "a&lt;b&gt;" in html_text


def test_the_page_references_no_external_file():
    with tempfile.TemporaryDirectory() as tmp:
        crop = _png(Path(tmp) / "alpha.png")
        style = _png(Path(tmp) / "_style.png")
        html_text = brief.page(
            [{"id": "alpha-front", "crop": crop, "prompt": "P"}], style, "t")
    assert "http://" not in html_text and "https://" not in html_text
    assert "<link" not in html_text and "<script" not in html_text
    assert "url(" not in html_text and "@import" not in html_text


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
    argv = ["--image", str(scene), "--analysis", str(analysis),
            "--out-dir", str(out_dir)]
    return brief.main(argv + (extra or [])), out_dir, scene


def test_a_run_writes_crops_the_style_copy_the_sheet_and_the_brief():
    with tempfile.TemporaryDirectory() as tmp:
        code, out_dir, scene = _run(tmp)
        assert code == 0
        assert (out_dir / "brief.html").exists()
        assert (out_dir / "analysis.json").exists()
        assert (out_dir / "refs" / "alpha.png").exists()
        assert (out_dir / "refs" / "_contact_sheet.png").exists()
        style_copy = out_dir / "refs" / "_style.png"
        assert style_copy.exists()
        assert style_copy.read_bytes() == scene.read_bytes()


def test_two_views_produce_two_prompts_over_one_crop():
    """Same crop, different VIEW line — the semantics extract already uses."""
    with tempfile.TemporaryDirectory() as tmp:
        code, out_dir, _scene_path = _run(tmp)
        body = (out_dir / "brief.html").read_text()
        assert code == 0
        assert body.count("class='asset'") == 2
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
        body = (out_dir / "brief.html").read_text()
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
        body = (out_dir / "brief.html").read_text()
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
        assert not (out_dir / "brief.html").exists()


def test_an_existing_brief_is_not_overwritten_from_an_outside_analysis():
    """A brief you have already reviewed and pruned is the most valuable thing
    in this flow."""
    with tempfile.TemporaryDirectory() as tmp:
        code, out_dir, _s = _run(tmp)
        assert code == 0
        marker = "<!-- mine -->"
        (out_dir / "brief.html").write_text(marker, encoding="utf-8")
        code2, _o, _s2 = _run(tmp)
        assert code2 == 1
        assert (out_dir / "brief.html").read_text() == marker


def test_rerunning_from_the_briefs_own_analysis_is_allowed():
    """The whole review loop is: edit analysis.json in place, run again."""
    with tempfile.TemporaryDirectory() as tmp:
        code, out_dir, scene = _run(tmp)
        assert code == 0
        inner = out_dir / "analysis.json"
        data = json.loads(inner.read_text())
        data["objects"][0]["subject"] = "a SECOND PASS rabbit"
        inner.write_text(json.dumps(data), encoding="utf-8")
        code2 = brief.main(["--image", str(scene), "--analysis", str(inner),
                            "--out-dir", str(out_dir)])
        assert code2 == 0
        assert "a SECOND PASS rabbit" in (out_dir / "brief.html").read_text()


def test_a_bad_analysis_writes_nothing_and_exits_one():
    data = _analysis()
    del data["style"]
    with tempfile.TemporaryDirectory() as tmp:
        code, out_dir, _s = _run(tmp, data)
        assert code == 1
        assert not (out_dir / "brief.html").exists()


def test_an_unreadable_image_exits_one():
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.png"
        bad.write_text("not an image", encoding="utf-8")
        analysis = _write(tmp, _analysis())
        code = brief.main(["--image", str(bad), "--analysis", str(analysis),
                           "--out-dir", str(Path(tmp) / "b")])
    assert code == 1

