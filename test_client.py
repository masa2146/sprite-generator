"""Transport tests. No network is touched. Run: python test_client.py"""
import base64
import os

import requests

import orclient
from config import Pack

PNG = b"\x89PNG\r\n\x1a\nFAKEPIXELS"
B64 = base64.b64encode(PNG).decode()


def _pack(key_env="TEST_KEY", base_url="http://svc/v1"):
    return Pack(
        name="t", base_url=base_url, key_env=key_env, model="m/model",
        style_prefix="", plate_prompt="", assets=[],
    )


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _ok_body(cost=0.04):
    return {
        "choices": [{"message": {"images": [
            {"image_url": {"url": f"data:image/png;base64,{B64}"}}
        ]}}],
        "usage": {"cost": cost},
    }


class _Recorder:
    """Stands in for requests.post and records every call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


def _run_with(responses, **kwargs):
    rec = _Recorder(responses)
    slept = []
    original = orclient.requests.post
    orclient.requests.post = rec
    try:
        result = orclient.generate(
            _pack(), "a prompt", sleeper=slept.append, **kwargs
        )
        return result, rec, slept
    finally:
        orclient.requests.post = original


def _run_expecting_error(responses, exc_type, **kwargs):
    try:
        _run_with(responses, **kwargs)
    except exc_type as exc:
        return exc
    raise AssertionError(f"expected {exc_type.__name__}")


# --- payload shape ---------------------------------------------------------

def test_payload_without_reference_has_only_text_content():
    body = orclient.build_payload("m/model", "hello")
    assert body["model"] == "m/model"
    assert body["modalities"] == ["image", "text"]
    assert body["usage"] == {"include": True}
    content = body["messages"][0]["content"]
    assert len(content) == 1
    assert content[0] == {"type": "text", "text": "hello"}
    assert "seed" not in body


def test_payload_with_reference_appends_base64_data_uri():
    body = orclient.build_payload("m/model", "hello", reference_png=PNG, seed=7)
    content = body["messages"][0]["content"]
    assert len(content) == 2
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == f"data:image/png;base64,{B64}"
    assert body["seed"] == 7


def test_payload_declares_jpeg_mime_for_a_jpeg_reference():
    jpeg = b"\xff\xd8\xff\xe0FAKEJPEGBYTES"
    body = orclient.build_payload("m/model", "hello", reference_png=jpeg)
    url = body["messages"][0]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == jpeg


def test_payload_declares_webp_mime_for_a_webp_reference():
    webp = b"RIFF\x00\x00\x00\x00WEBPVP8 REST"
    body = orclient.build_payload("m/model", "hello", reference_png=webp)
    url = body["messages"][0]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/webp;base64,")


def test_headers_include_bearer_when_key_present():
    os.environ["TEST_KEY"] = "sk-abc"
    try:
        assert orclient.build_headers(_pack())["Authorization"] == "Bearer sk-abc"
    finally:
        del os.environ["TEST_KEY"]


def test_headers_omit_authorization_when_key_env_is_empty():
    assert "Authorization" not in orclient.build_headers(_pack(key_env=""))


def test_headers_omit_authorization_when_env_var_is_unset():
    os.environ.pop("TEST_KEY", None)
    assert "Authorization" not in orclient.build_headers(_pack())


# --- response parsing ------------------------------------------------------

def test_parse_reads_message_images_array():
    assert orclient.parse_image(_ok_body()) == PNG


def test_parse_falls_back_to_data_uri_inside_content():
    body = {"choices": [{"message": {
        "content": f"here you go data:image/png;base64,{B64} enjoy"
    }}]}
    assert orclient.parse_image(body) == PNG


def test_parse_falls_back_to_data_uri_in_structured_content_list():
    body = {"choices": [{"message": {"content": [
        {"type": "text", "text": "ok"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{B64}"}},
    ]}}]}
    assert orclient.parse_image(body) == PNG


def test_parse_raises_image_missing_and_carries_raw_body():
    body = {"choices": [{"message": {"content": "I cannot do that"}}]}
    try:
        orclient.parse_image(body)
        raise AssertionError("expected ImageMissing")
    except orclient.ImageMissing as exc:
        assert exc.raw == body


def test_parse_raises_on_empty_response():
    try:
        orclient.parse_image({})
        raise AssertionError("expected ImageMissing")
    except orclient.ImageMissing:
        pass


def test_cost_is_none_when_provider_omits_usage():
    assert orclient.response_cost({"usage": {}}) is None
    assert orclient.response_cost({}) is None
    assert orclient.response_cost({"usage": {"cost": 0.04}}) == 0.04


# --- request + retry -------------------------------------------------------

def test_generate_posts_to_chat_completions_and_returns_bytes_and_cost():
    (png, cost, raw), rec, slept = _run_with([_Resp(200, _ok_body())])
    assert png == PNG
    assert cost == 0.04
    assert raw["usage"]["cost"] == 0.04
    assert rec.calls[0]["url"] == "http://svc/v1/chat/completions"
    assert slept == []


def test_generate_strips_trailing_slash_from_base_url():
    rec = _Recorder([_Resp(200, _ok_body())])
    original = orclient.requests.post
    orclient.requests.post = rec
    try:
        orclient.generate(_pack(base_url="http://svc/v1/"), "p", sleeper=lambda s: None)
    finally:
        orclient.requests.post = original
    assert rec.calls[0]["url"] == "http://svc/v1/chat/completions"


def test_generate_retries_429_then_succeeds():
    (png, _, _), rec, slept = _run_with([_Resp(429), _Resp(200, _ok_body())])
    assert png == PNG
    assert len(rec.calls) == 2
    assert slept == [2]


def test_generate_gives_up_after_three_attempts_with_backoff():
    exc = _run_expecting_error(
        [_Resp(429), _Resp(429), _Resp(429)], orclient.ApiError
    )
    assert exc.status == 429


def test_generate_backoff_is_two_four_seconds():
    rec = _Recorder([_Resp(500), _Resp(500), _Resp(500)])
    slept = []
    original = orclient.requests.post
    orclient.requests.post = rec
    try:
        orclient.generate(_pack(), "p", sleeper=slept.append)
    except orclient.ApiError:
        pass
    finally:
        orclient.requests.post = original
    assert len(rec.calls) == 3
    assert slept == [2, 4]  # no sleep after the final attempt


def test_generate_retries_on_connection_error_then_succeeds():
    """A timeout/connection reset raises before a status_code exists at all —
    it must be retried like a 5xx, not propagate on the first attempt."""
    events = [requests.exceptions.ConnectionError("boom"), _Resp(200, _ok_body())]

    def fake_post(url, json=None, headers=None, timeout=None):
        item = events.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    slept = []
    original = orclient.requests.post
    orclient.requests.post = fake_post
    try:
        png, cost, _raw = orclient.generate(_pack(), "p", sleeper=slept.append)
    finally:
        orclient.requests.post = original
    assert png == PNG
    assert slept == [2]


def test_generate_gives_up_after_repeated_connection_errors():
    events = [requests.exceptions.ConnectTimeout("timed out")] * 3

    def fake_post(url, json=None, headers=None, timeout=None):
        return_exc = events.pop(0)
        raise return_exc

    original = orclient.requests.post
    orclient.requests.post = fake_post
    try:
        try:
            orclient.generate(_pack(), "p", sleeper=lambda s: None)
            raise AssertionError("expected ApiError")
        except orclient.ApiError as exc:
            assert "ConnectTimeout" in str(exc)
    finally:
        orclient.requests.post = original


def test_generate_with_retries_zero_raises_api_error_not_type_error():
    """last_error is still None if the loop body never runs; must not raise
    TypeError('exceptions must derive from BaseException') from `raise None`."""
    try:
        orclient.generate(_pack(), "p", retries=0, sleeper=lambda s: None)
        raise AssertionError("expected ApiError")
    except orclient.ApiError:
        pass


def test_generate_does_not_retry_4xx_other_than_429():
    rec = _Recorder([_Resp(400, text="bad prompt"), _Resp(200, _ok_body())])
    original = orclient.requests.post
    orclient.requests.post = rec
    try:
        orclient.generate(_pack(), "p", sleeper=lambda s: None)
        raise AssertionError("expected ApiError")
    except orclient.ApiError as exc:
        assert exc.status == 400
        assert "bad prompt" in str(exc)
    finally:
        orclient.requests.post = original
    assert len(rec.calls) == 1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all client tests passed")
