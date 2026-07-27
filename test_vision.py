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


def test_missing_style_block_reports_every_style_field():
    assert vision.validate_schema({"subject": "x"}) == [
        f"style.{f}" for f in vision.STYLE_FIELDS
    ]


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all vision tests passed")
