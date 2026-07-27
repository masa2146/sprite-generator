"""Vision analysis tests. No network is touched. Run: python3 test_vision.py"""
import base64
import json
import os
import tempfile
from pathlib import Path

import vision
from config import Pack

SCHEMA = {
    "style": {
        "render": "soft 3D render, glossy plastic material",
        "camera": "3/4 front view, slight high angle",
        "lighting": "top-left key light, soft ambient occlusion",
        "palette": "#FF6B4A #4ECDC4",
        "linework": "no outline, rounded geometry",
        "realism": "stylized cartoon, not photorealistic",
    },
    "form": "a single rounded disc, slightly thicker at the rim",
    "detail": "subtle radial shine across the face",
    "subject": "gold coin icon, front view, thick rim",
}
PNG = b"\x89PNG\r\n\x1a\nFAKE"


def _pack(model="vision/model", key_env=""):
    return Pack(
        name="t", base_url="http://img/v1", key_env="", model="m/model",
        style_prefix="", plate_prompt="", assets=[],
        vision_base_url="http://vis/v1", vision_key_env=key_env, vision_model=model,
    )


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _body(content):
    return {"choices": [{"message": {"content": content}}]}


class _Recorder:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


def _run_analyze(responses, pack=None):
    import orclient
    rec = _Recorder(responses)
    original = orclient.requests.post
    orclient.requests.post = rec
    try:
        return vision.analyze(pack or _pack(), PNG, sleeper=lambda s: None), rec
    finally:
        orclient.requests.post = original


# --- schema extraction ------------------------------------------------------

def test_extract_plain_json():
    assert vision.extract_schema(json.dumps(SCHEMA)) == SCHEMA


def test_extract_json_in_a_fenced_block():
    text = "Here is the analysis:\n```json\n" + json.dumps(SCHEMA) + "\n```\nDone."
    assert vision.extract_schema(text) == SCHEMA


def test_extract_json_in_an_unlabelled_fenced_block():
    text = "```\n" + json.dumps(SCHEMA) + "\n```"
    assert vision.extract_schema(text) == SCHEMA


def test_extract_json_embedded_in_prose():
    text = "Sure! " + json.dumps(SCHEMA) + " Hope that helps."
    assert vision.extract_schema(text) == SCHEMA


def test_extract_tolerates_a_trailing_comma():
    """Observed live: a model returned a correct schema with a comma before }."""
    text = "```json\n" + json.dumps(SCHEMA).replace('"}', '",}') + "\n```"
    assert vision.extract_schema(text) == SCHEMA


def test_extract_tolerates_a_trailing_comma_without_fences():
    bad = json.dumps(SCHEMA)[:-1] + ",}"
    assert vision.extract_schema(bad) == SCHEMA


def test_extract_raises_on_unparseable_text():
    try:
        vision.extract_schema("I cannot analyze this image.")
        raise AssertionError("expected AnalysisError")
    except vision.AnalysisError:
        pass


# --- schema validation ------------------------------------------------------

def test_complete_schema_has_no_missing_fields():
    assert vision.validate_schema(SCHEMA) == []


def test_missing_style_field_is_reported():
    bad = json.loads(json.dumps(SCHEMA))
    del bad["style"]["lighting"]
    assert vision.validate_schema(bad) == ["style.lighting"]


def test_missing_subject_is_reported():
    bad = json.loads(json.dumps(SCHEMA))
    del bad["subject"]
    assert vision.validate_schema(bad) == ["subject"]


def test_blank_field_counts_as_missing():
    bad = json.loads(json.dumps(SCHEMA))
    bad["style"]["palette"] = "   "
    assert vision.validate_schema(bad) == ["style.palette"]


def test_missing_blocks_are_reported_per_field():
    assert vision.validate_schema({"subject": "x"}) == [
        f"style.{f}" for f in vision.STYLE_FIELDS
    ] + ["form", "detail"]


# --- prompt assembly --------------------------------------------------------

def test_style_prefix_joins_fields_in_the_fixed_order():
    text = vision.style_prefix(SCHEMA)
    order = [text.index(SCHEMA["style"][f]) for f in
             ("render", "camera", "lighting", "linework", "realism", "palette")]
    assert order == sorted(order), text


def test_style_prefix_excludes_the_subject():
    assert SCHEMA["subject"] not in vision.style_prefix(SCHEMA)


def test_reproduction_prompt_starts_with_the_subject():
    assert vision.reproduction_prompt(SCHEMA).startswith(SCHEMA["subject"])


def test_reproduction_prompt_carries_every_style_field():
    text = vision.reproduction_prompt(SCHEMA)
    for f in vision.STYLE_FIELDS:
        assert SCHEMA["style"][f] in text, f


# --- the request ------------------------------------------------------------

def test_analyze_posts_to_the_vision_endpoint_with_the_image():
    (schema, raw), rec = _run_analyze([_Resp(200, _body(json.dumps(SCHEMA)))])
    assert schema == SCHEMA
    assert rec.calls[0]["url"] == "http://vis/v1/chat/completions"
    body = rec.calls[0]["json"]
    assert body["model"] == "vision/model"
    assert "modalities" not in body           # text output, not image
    assert body["stream"] is False           # proxies default to SSE otherwise
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert vision.ANALYSIS_PROMPT in content[0]["text"]
    expected = base64.b64encode(PNG).decode()
    assert content[1]["image_url"]["url"] == f"data:image/png;base64,{expected}"


def test_analyze_sends_no_authorization_when_vision_key_env_is_empty():
    _, rec = _run_analyze([_Resp(200, _body(json.dumps(SCHEMA)))])
    assert "Authorization" not in rec.calls[0]["headers"]


def test_analyze_sends_the_vision_key_not_the_image_key():
    os.environ["VIS_KEY"] = "sk-vision"
    try:
        _, rec = _run_analyze([_Resp(200, _body(json.dumps(SCHEMA)))],
                              pack=_pack(key_env="VIS_KEY"))
        assert rec.calls[0]["headers"]["Authorization"] == "Bearer sk-vision"
    finally:
        del os.environ["VIS_KEY"]


def test_analyze_retries_a_429():
    (schema, _), rec = _run_analyze(
        [_Resp(429), _Resp(200, _body(json.dumps(SCHEMA)))]
    )
    assert schema == SCHEMA
    assert len(rec.calls) == 2


def test_analyze_raises_with_the_raw_text_when_the_reply_is_not_json():
    try:
        _run_analyze([_Resp(200, _body("I cannot analyze this image."))])
        raise AssertionError("expected AnalysisError")
    except vision.AnalysisError as exc:
        assert "I cannot analyze this image." in exc.raw


def test_analyze_rejects_a_pack_with_no_vision_model():
    try:
        _run_analyze([_Resp(200, _body(json.dumps(SCHEMA)))], pack=_pack(model=None))
        raise AssertionError("expected AnalysisError")
    except vision.AnalysisError as exc:
        assert "model" in str(exc)


# --- schema growth: form + detail -------------------------------------------

FULL = {
    "style": {
        "render": "soft 3D render, glossy plastic",
        "camera": "3/4 front view",
        "lighting": "top-left key light",
        "palette": "#FF6B4A #4ECDC4",
        "linework": "no outline, rounded geometry",
        "realism": "stylized cartoon",
    },
    "form": "two stacked parts: a ribbed panel above a rounded box with a vertical slot",
    "detail": "thick bevelled rim, soft specular highlight along the top edge",
    "subject": "a small launcher chute",
}


def test_form_and_detail_are_required():
    missing = dict(FULL); del missing["form"]
    assert vision.validate_schema(missing) == ["form"]
    missing2 = dict(FULL); del missing2["detail"]
    assert vision.validate_schema(missing2) == ["detail"]


def test_blank_form_counts_as_missing():
    blank = dict(FULL); blank["form"] = "  "
    assert vision.validate_schema(blank) == ["form"]


def test_full_schema_validates():
    assert vision.validate_schema(FULL) == []


def test_object_prompt_uses_the_fixed_order():
    text = vision.object_prompt(FULL)
    order = [text.index(v) for v in (
        FULL["subject"], FULL["form"], FULL["detail"],
        FULL["style"]["render"], FULL["style"]["camera"], FULL["style"]["lighting"],
        FULL["style"]["linework"], FULL["style"]["realism"], FULL["style"]["palette"],
    )]
    assert order == sorted(order), text


def test_object_prompt_starts_with_the_subject():
    assert vision.object_prompt(FULL).startswith(FULL["subject"])


def test_object_prompt_skips_absent_fields_without_breaking_separators():
    partial = {"subject": "a coin", "style": {"render": "flat vector"}}
    text = vision.object_prompt(partial)
    assert text == "a coin, flat vector"
    assert ", ," not in text


def test_style_prefix_still_excludes_form_and_detail():
    """form/detail describe one object; a shared prefix must not carry them."""
    prefix = vision.style_prefix(FULL)
    assert FULL["form"] not in prefix
    assert FULL["detail"] not in prefix
    assert FULL["subject"] not in prefix


# --- user text override -----------------------------------------------------

def test_analyze_without_user_text_sends_no_override_clause():
    (schema, _), rec = _run_analyze([_Resp(200, _body(json.dumps(FULL)))])
    sent = rec.calls[0]["json"]["messages"][0]["content"][0]["text"]
    assert vision.ANALYSIS_PROMPT in sent
    assert "user also asked" not in sent.lower()


def test_analyze_with_user_text_appends_the_override_clause():
    import orclient
    rec = _Recorder([_Resp(200, _body(json.dumps(FULL)))])
    original = orclient.requests.post
    orclient.requests.post = rec
    try:
        vision.analyze(_pack(), PNG, user_text="make it red", sleeper=lambda s: None)
    finally:
        orclient.requests.post = original
    sent = rec.calls[0]["json"]["messages"][0]["content"][0]["text"]
    assert "make it red" in sent
    assert "user" in sent.lower()


# --- view pool --------------------------------------------------------------

def test_view_pool_contents():
    assert set(vision.VIEW_POOL) == {
        "front", "three_quarter", "side", "back", "top_down"}
    assert vision.DEFAULT_VIEW == "front"
    for phrase in vision.VIEW_POOL.values():
        assert phrase and not phrase.endswith(".")


def test_normalise_views_drops_names_outside_the_pool():
    assert vision.normalise_views(["side", "isometric", "back"], True) == ["side", "back"]


def test_normalise_views_falls_back_to_front_when_nothing_survives():
    assert vision.normalise_views(["isometric", "worm_eye"], True) == ["front"]


def test_normalise_views_dedupes_and_uses_pool_order():
    assert vision.normalise_views(["back", "front", "back"], True) == ["front", "back"]


def test_a_static_object_gets_exactly_one_view():
    assert vision.normalise_views(["front", "side", "back"], False) == ["front"]


def test_normalise_views_handles_a_non_list():
    assert vision.normalise_views(None, True) == ["front"]
    assert vision.normalise_views("side", True) == ["front"]


# --- object analysis --------------------------------------------------------

OBJECTS_REPLY = {
    "style": {
        "render": "soft 3D render, glossy plastic",
        "camera": "top-down flat view",
        "lighting": "soft even ambient",
        "palette": "#2E2A4D #6C4CD6",
        "linework": "no hard outlines",
        "realism": "stylized cartoon",
    },
    "objects": [
        {
            "id": "bunny_white", "bbox": [45, 1000, 165, 1125],
            "animated": True, "views": ["front", "side"],
            "subject": "a plump white rabbit token",
            "form": "a round ball body with two upright ears",
            "detail": "tiny dot eyes, pink nose",
        },
        {
            "id": "launcher", "bbox": [0, 730, 115, 940],
            "animated": False, "views": ["front"],
            "subject": "a launcher chute",
            "form": "a ribbed panel above a rounded box with a vertical slot",
            "detail": "thick bevelled rim",
        },
    ],
}


def test_analyze_objects_returns_style_and_objects():
    (schema, _), rec = _run_objects([_Resp(200, _body(json.dumps(OBJECTS_REPLY)))])
    assert [o["id"] for o in schema["objects"]] == ["bunny_white", "launcher"]
    assert schema["style"]["render"].startswith("soft 3D")


def test_analyze_objects_sends_the_object_prompt_and_the_image():
    _, rec = _run_objects([_Resp(200, _body(json.dumps(OBJECTS_REPLY)))])
    body = rec.calls[0]["json"]
    assert body["stream"] is False
    content = body["messages"][0]["content"]
    assert vision.OBJECT_ANALYSIS_PROMPT in content[0]["text"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_analyze_objects_rejects_a_reply_with_no_objects():
    reply = {"style": OBJECTS_REPLY["style"], "objects": []}
    try:
        _run_objects([_Resp(200, _body(json.dumps(reply)))])
        raise AssertionError("expected AnalysisError")
    except vision.AnalysisError as exc:
        assert "object" in str(exc).lower()


def test_analyze_objects_rejects_a_reply_with_no_style():
    reply = {"objects": OBJECTS_REPLY["objects"]}
    try:
        _run_objects([_Resp(200, _body(json.dumps(reply)))])
        raise AssertionError("expected AnalysisError")
    except vision.AnalysisError as exc:
        assert "style" in str(exc).lower()


def _run_objects(responses, pack=None):
    import orclient
    rec = _Recorder(responses)
    original = orclient.requests.post
    orclient.requests.post = rec
    try:
        return vision.analyze_objects(pack or _pack(), PNG, sleeper=lambda s: None), rec
    finally:
        orclient.requests.post = original


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all vision tests passed")
