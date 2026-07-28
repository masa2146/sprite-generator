"""sprite brief tests. Run: python3 test_brief.py"""
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


def test_views_are_filtered_to_the_pool_and_ordered():
    assert brief.normalise_views(["side", "front"]) == ["front", "side"]


def test_a_view_outside_the_pool_is_dropped():
    assert brief.normalise_views(["isometric", "front"]) == ["front"]


def test_no_usable_view_falls_back_to_front():
    assert brief.normalise_views([]) == ["front"]
    assert brief.normalise_views("front") == ["front"]
    assert brief.normalise_views(["isometric"]) == ["front"]


def test_load_analysis_returns_style_and_objects():
    with tempfile.TemporaryDirectory() as tmp:
        style, objects = brief.load_analysis(_write(tmp, _analysis()))
    assert style == "soft 3D cartoon, glossy plastic, #2e2c4a, #ffffff"
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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all brief tests passed")
