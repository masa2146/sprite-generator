# Sprite Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI that turns a TOML spec of prompts into Unity-ready RGBA sprite PNGs, keeping the whole set visually consistent by sending a locked style-reference image with every request.

**Architecture:** Four modules with one responsibility each. `config.py` parses the spec and resolves configuration precedence. `orclient.py` talks to any OpenAI-schema `/chat/completions` endpoint with `modalities: ["image","text"]` and tolerantly digs the image out of the response. `post.py` cuts the background and trims/pads to a centered square. `gen.py` is the CLI that orchestrates them, enforces the cost ceiling, and writes the manifest. Hosted models do not emit reliable alpha, so every prompt asks for a flat magenta backdrop and alpha is cut locally.

**Tech Stack:** Python 3.11+ (`tomllib` from stdlib), `requests`, `pillow`, `rembg[gpu]` (ships the `birefnet-general` session).

**Spec:** `docs/superpowers/specs/2026-07-26-sprite-generator-design.md`

## Global Constraints

- Python 3.11 or newer. `tomllib` is stdlib from 3.11; do not add `toml`/`pyyaml`.
- Third-party dependencies are exactly: `requests`, `pillow`, `rembg[gpu]`. Adding any other package is out of scope.
- No test framework. Tests are `assert`-based functions in `test_*.py` files, runnable with `python test_post.py`. No pytest fixtures, no conftest, no mocking library. (`pytest test_post.py` happens to work too, but is not required.)
- API keys are read from environment variables only. Never write a key into a spec file, a manifest, or a log line.
- The transport is `POST {base_url}/chat/completions`. Do not call `/images/generations` or `/images/edits`.
- `BG_CLAUSE` is the exact string `isolated on flat solid #FF00FF background, no shadow, no ground plane` and is appended to every generation prompt, including style plates.
- Square padding formula is exact: `side = ceil(max(w, h) * 1.08 / 2) * 2`. No resampling anywhere — crop and transparent fill only.
- Partial failure never aborts the batch. One asset failing must not stop the others.
- Default cost ceiling is 5.00 USD.

---

## File Structure

| File | Responsibility |
|---|---|
| `config.py` | TOML spec loading, config precedence, `Asset`/`Pack` dataclasses, prompt assembly |
| `orclient.py` | HTTP request building, retry policy, tolerant response parsing |
| `post.py` | Background removal (rembg) and trim/pad geometry |
| `gen.py` | CLI entry point, `init`/`pick`/`build` commands, manifest, budget enforcement |
| `test_config.py` | Spec parsing and precedence tests |
| `test_client.py` | Payload shape, parsing fallbacks, retry behaviour |
| `test_post.py` | Trim/pad geometry tests |
| `packs/hc_v1.toml` | Example pack |
| `requirements.txt` | Pinned dependency list |
| `README.md` | Setup and usage |

Task order follows the dependency chain: `post.py` and `config.py` depend on nothing, `orclient.py` depends on `config.py`, `gen.py` depends on all three.

---

### Task 1: Image post-processing

**Files:**
- Create: `post.py`
- Test: `test_post.py`
- Create: `requirements.txt`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `cut_background(data: bytes) -> PIL.Image.Image` — RGBA image with background removed.
  - `trim_and_pad(img: PIL.Image.Image, margin: float = 0.04) -> PIL.Image.Image` — RGBA square.

**Note on test scope:** `trim_and_pad` is the only real algorithm here and is tested directly with synthetic RGBA input. `cut_background` is a thin wrapper over rembg; per the spec, rembg's own accuracy is upstream's responsibility and is not tested. The tests therefore never download a model and run in under a second.

- [ ] **Step 1: Write `requirements.txt`**

```
requests>=2.31
pillow>=10.0
rembg[gpu]>=2.0.75
```

- [ ] **Step 2: Write the failing tests**

Create `test_post.py`:

```python
"""Geometry tests for post.trim_and_pad. Run: python test_post.py"""
from PIL import Image

from post import trim_and_pad


def _canvas(box, size=(512, 512), color=(0, 0, 255, 255)):
    """Transparent canvas with one opaque rectangle at `box` (l, t, r, b)."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    img.paste(color, box)
    return img


def test_square_subject_pads_to_exact_side():
    # 200x200 opaque square -> ceil(200 * 1.08 / 2) * 2 == 216
    out = trim_and_pad(_canvas((156, 156, 356, 356)))
    assert out.size == (216, 216), out.size


def test_output_corner_is_transparent_and_center_is_opaque():
    out = trim_and_pad(_canvas((156, 156, 356, 356)))
    assert out.getpixel((0, 0))[3] == 0
    assert out.getpixel((out.width // 2, out.height // 2))[3] == 255


def test_non_square_subject_pads_to_square_on_long_edge():
    # 200 wide x 300 tall -> ceil(300 * 1.08 / 2) * 2 == 324
    out = trim_and_pad(_canvas((100, 100, 300, 400)))
    assert out.size == (324, 324), out.size


def test_subject_is_centered():
    out = trim_and_pad(_canvas((100, 100, 300, 400)))
    # 324 wide canvas holding a 200-wide subject -> 62px transparent each side
    assert out.getpixel((30, out.height // 2))[3] == 0
    assert out.getpixel((out.width // 2, out.height // 2))[3] == 255


def test_offset_subject_gives_same_result_as_centered_one():
    """Trim must remove position information entirely."""
    a = trim_and_pad(_canvas((0, 0, 200, 200)))
    b = trim_and_pad(_canvas((300, 300, 500, 500)))
    assert a.size == b.size
    assert a.tobytes() == b.tobytes()


def test_fully_transparent_image_is_returned_unchanged():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    assert trim_and_pad(img).size == (64, 64)


def test_no_resampling_subject_pixels_are_untouched():
    out = trim_and_pad(_canvas((156, 156, 356, 356), color=(12, 34, 56, 255)))
    assert out.getpixel((out.width // 2, out.height // 2)) == (12, 34, 56, 255)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all post tests passed")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python test_post.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'post'`

- [ ] **Step 4: Write `post.py`**

```python
"""Image post-processing: background removal and trim/pad geometry."""

from __future__ import annotations

import math
from io import BytesIO

from PIL import Image

_SESSION = None


def cut_background(data: bytes) -> Image.Image:
    """Remove the background from encoded image bytes. Returns an RGBA image.

    The rembg session is created lazily and reused: building it downloads the
    birefnet-general weights on first use and is far too slow to repeat per asset.
    """
    global _SESSION
    from rembg import new_session, remove

    if _SESSION is None:
        _SESSION = new_session("birefnet-general")
    img = Image.open(BytesIO(data)).convert("RGBA")
    return remove(img, session=_SESSION).convert("RGBA")


def trim_and_pad(img: Image.Image, margin: float = 0.04) -> Image.Image:
    """Crop to the alpha bounding box, then pad to a centered transparent square.

    `margin` is applied to each side, so the square's side is the subject's long
    edge times (1 + 2 * margin), rounded up to an even number. Nothing is ever
    resampled: this is crop plus transparent fill, so subject pixels survive
    bit-exact.
    """
    img = img.convert("RGBA")
    bbox = img.getchannel("A").getbbox()
    if bbox is None:
        return img  # fully transparent: nothing to trim, nothing to center

    cropped = img.crop(bbox)
    w, h = cropped.size
    side = math.ceil(max(w, h) * (1 + 2 * margin) / 2) * 2
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(cropped, ((side - w) // 2, (side - h) // 2))
    return canvas
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python test_post.py`
Expected: seven `ok  test_...` lines, then `all post tests passed`

- [ ] **Step 6: Commit**

```bash
git add post.py test_post.py requirements.txt
git commit -m "feat: add sprite post-processing (alpha trim and square pad)"
```

---

### Task 2: Spec loading and config precedence

**Files:**
- Create: `config.py`
- Test: `test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `BG_CLAUSE: str` — the exact backdrop clause.
  - `DEFAULT_BASE_URL: str`, `DEFAULT_KEY_ENV: str`.
  - `class SpecError(Exception)`.
  - `@dataclass Asset` with fields `id: str`, `prompt: str`, `aspect_ratio: str`, `trim: bool`.
  - `@dataclass Pack` with fields `name: str`, `base_url: str`, `key_env: str`, `model: str`, `style_prefix: str`, `plate_prompt: str`, `assets: list[Asset]`; properties `out_dir: Path`, `style_bible: Path`, `candidates_dir: Path`, `manifest_path: Path`; methods `api_key() -> str | None`, `full_prompt(asset: Asset) -> str`, `plate_full_prompt() -> str`, `seed_for(asset_id: str) -> int`.
  - `load_pack(spec_path, base_url=None, model=None, out_root=Path("out")) -> Pack`.

**Note on seeds:** the spec says `seed = hash(asset.id)`. Python's builtin `hash()` for strings is randomized per process unless `PYTHONHASHSEED` is pinned, which would silently break reproducibility. Use `zlib.crc32` instead — same intent, actually deterministic.

- [ ] **Step 1: Write the failing tests**

Create `test_config.py`:

```python
"""Spec parsing and precedence tests. Run: python test_config.py"""
import os
import tempfile
from pathlib import Path

from config import BG_CLAUSE, DEFAULT_BASE_URL, SpecError, load_pack

FULL_SPEC = """
[api]
base_url = "https://spec.example/v1"
key_env  = "SPEC_KEY"

[pack]
model = "spec/model"

[style]
prefix = "hypercasual asset, glossy"
plate_prompt = "a button, an icon, a character"

[defaults]
aspect_ratio = "1:1"

[[assets]]
id = "btn_play"
prompt = "play button"

[[assets]]
id = "hero_idle"
prompt = "round blue character"
aspect_ratio = "3:4"

[[assets]]
id = "bg_sky"
prompt = "seamless sky"
trim = false
"""

MINIMAL_SPEC = """
[pack]
model = "m"
[style]
prefix = "p"
[[assets]]
id = "a"
prompt = "q"
"""


def _write(text, name="hc_v1.toml"):
    d = Path(tempfile.mkdtemp())
    p = d / name
    p.write_text(text)
    return p


def _clear_env():
    for k in ("SPRITEGEN_BASE_URL", "SPRITEGEN_MODEL", "SPEC_KEY", "OPENROUTER_API_KEY"):
        os.environ.pop(k, None)


def test_pack_name_comes_from_spec_filename():
    _clear_env()
    assert load_pack(_write(FULL_SPEC)).name == "hc_v1"


def test_assets_parse_with_defaults_and_overrides():
    _clear_env()
    pack = load_pack(_write(FULL_SPEC))
    by_id = {a.id: a for a in pack.assets}
    assert by_id["btn_play"].aspect_ratio == "1:1"   # from [defaults]
    assert by_id["hero_idle"].aspect_ratio == "3:4"  # asset override
    assert by_id["btn_play"].trim is True            # default
    assert by_id["bg_sky"].trim is False             # asset override


def test_full_prompt_includes_prefix_asset_bg_clause_and_ratio():
    _clear_env()
    pack = load_pack(_write(FULL_SPEC))
    hero = {a.id: a for a in pack.assets}["hero_idle"]
    text = pack.full_prompt(hero)
    assert text.startswith("hypercasual asset, glossy")
    assert "round blue character" in text
    assert BG_CLAUSE in text
    assert text.endswith("aspect ratio 3:4")


def test_plate_prompt_also_carries_prefix_and_bg_clause():
    _clear_env()
    text = load_pack(_write(FULL_SPEC)).plate_full_prompt()
    assert "hypercasual asset, glossy" in text
    assert "a button, an icon, a character" in text
    assert BG_CLAUSE in text


def test_precedence_cli_beats_spec_beats_env_beats_default():
    _clear_env()
    spec = _write(FULL_SPEC)
    assert load_pack(spec, base_url="http://cli/v1").base_url == "http://cli/v1"
    assert load_pack(spec).base_url == "https://spec.example/v1"

    bare = _write(MINIMAL_SPEC)
    os.environ["SPRITEGEN_BASE_URL"] = "http://env/v1"
    assert load_pack(bare).base_url == "http://env/v1"
    del os.environ["SPRITEGEN_BASE_URL"]
    assert load_pack(bare).base_url == DEFAULT_BASE_URL


def test_model_precedence_and_missing_model_is_an_error():
    _clear_env()
    assert load_pack(_write(FULL_SPEC), model="cli/m").model == "cli/m"
    assert load_pack(_write(FULL_SPEC)).model == "spec/model"
    no_model = _write("[style]\nprefix='p'\n[[assets]]\nid='a'\nprompt='q'\n")
    try:
        load_pack(no_model)
        raise AssertionError("expected SpecError")
    except SpecError as e:
        assert "model" in str(e)


def test_api_key_read_from_named_env_var_only():
    _clear_env()
    pack = load_pack(_write(FULL_SPEC))
    assert pack.key_env == "SPEC_KEY"
    assert pack.api_key() is None
    os.environ["SPEC_KEY"] = "sk-test"
    assert pack.api_key() == "sk-test"
    del os.environ["SPEC_KEY"]


def test_empty_key_env_means_no_key_at_all():
    _clear_env()
    spec = _write(MINIMAL_SPEC.replace("[pack]", '[api]\nkey_env = ""\n[pack]'))
    assert load_pack(spec).api_key() is None


def test_duplicate_asset_id_is_rejected():
    _clear_env()
    dupe = _write(MINIMAL_SPEC + "\n[[assets]]\nid = 'a'\nprompt = 'other'\n")
    try:
        load_pack(dupe)
        raise AssertionError("expected SpecError")
    except SpecError as e:
        assert "duplicate" in str(e)


def test_asset_missing_required_field_is_rejected():
    _clear_env()
    bad = _write("[pack]\nmodel='m'\n[style]\nprefix='p'\n[[assets]]\nid='a'\n")
    try:
        load_pack(bad)
        raise AssertionError("expected SpecError")
    except SpecError as e:
        assert "prompt" in str(e)


def test_spec_with_no_assets_is_rejected():
    _clear_env()
    try:
        load_pack(_write("[pack]\nmodel='m'\n[style]\nprefix='p'\n"))
        raise AssertionError("expected SpecError")
    except SpecError as e:
        assert "assets" in str(e)


def test_seed_is_deterministic_across_processes():
    _clear_env()
    pack = load_pack(_write(FULL_SPEC))
    # crc32 is stable; builtin hash() would not be
    assert pack.seed_for("btn_play") == pack.seed_for("btn_play")
    assert pack.seed_for("btn_play") != pack.seed_for("hero_idle")
    assert 0 <= pack.seed_for("btn_play") < 2**31


def test_paths_derive_from_pack_name():
    _clear_env()
    pack = load_pack(_write(FULL_SPEC), out_root=Path("/tmp/outroot"))
    assert pack.out_dir == Path("/tmp/outroot/hc_v1")
    assert pack.style_bible == Path("/tmp/outroot/hc_v1/style_bible.png")
    assert pack.candidates_dir == Path("/tmp/outroot/hc_v1/style_candidates")
    assert pack.manifest_path == Path("/tmp/outroot/hc_v1/manifest.json")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all config tests passed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python test_config.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Write `config.py`**

```python
"""Spec loading and configuration resolution."""

from __future__ import annotations

import os
import tomllib
import zlib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_KEY_ENV = "OPENROUTER_API_KEY"

# Hosted models do not emit reliable alpha, so we ask for a flat backdrop we can
# cut locally. Edge quality comes from this clause, not from the model.
BG_CLAUSE = "isolated on flat solid #FF00FF background, no shadow, no ground plane"


class SpecError(Exception):
    """The spec file is malformed or incomplete."""


@dataclass
class Asset:
    id: str
    prompt: str
    aspect_ratio: str = "1:1"
    trim: bool = True


@dataclass
class Pack:
    name: str
    base_url: str
    key_env: str
    model: str
    style_prefix: str
    plate_prompt: str
    assets: list[Asset] = field(default_factory=list)
    out_root: Path = Path("out")

    @property
    def out_dir(self) -> Path:
        return self.out_root / self.name

    @property
    def style_bible(self) -> Path:
        return self.out_dir / "style_bible.png"

    @property
    def candidates_dir(self) -> Path:
        return self.out_dir / "style_candidates"

    @property
    def manifest_path(self) -> Path:
        return self.out_dir / "manifest.json"

    def api_key(self) -> str | None:
        """Key comes from the environment only, never from the spec file."""
        return os.environ.get(self.key_env) if self.key_env else None

    def full_prompt(self, asset: Asset) -> str:
        return (
            f"{self.style_prefix.strip()} {asset.prompt.strip()} "
            f"{BG_CLAUSE}, aspect ratio {asset.aspect_ratio}"
        )

    def plate_full_prompt(self) -> str:
        return f"{self.style_prefix.strip()} {self.plate_prompt.strip()} {BG_CLAUSE}"

    def seed_for(self, asset_id: str) -> int:
        """Deterministic across processes, unlike builtin hash()."""
        return zlib.crc32(asset_id.encode()) % (2**31)


def load_pack(
    spec_path,
    base_url: str | None = None,
    model: str | None = None,
    out_root: Path = Path("out"),
) -> Pack:
    """Load a TOML spec. Precedence: CLI arg > spec file > env var > default."""
    spec_path = Path(spec_path)
    try:
        with spec_path.open("rb") as fh:
            raw = tomllib.load(fh)
    except FileNotFoundError:
        raise SpecError(f"spec not found: {spec_path}")
    except tomllib.TOMLDecodeError as exc:
        raise SpecError(f"{spec_path}: invalid TOML: {exc}")

    api = raw.get("api", {})
    pack_tbl = raw.get("pack", {})
    style = raw.get("style", {})
    defaults = raw.get("defaults", {})

    resolved_base = (
        base_url
        or api.get("base_url")
        or os.environ.get("SPRITEGEN_BASE_URL")
        or DEFAULT_BASE_URL
    )
    resolved_model = model or pack_tbl.get("model") or os.environ.get("SPRITEGEN_MODEL")
    if not resolved_model:
        raise SpecError("no model: set [pack] model, pass --model, or set SPRITEGEN_MODEL")

    # key_env may be explicitly "" to mean "this endpoint needs no key".
    key_env = api["key_env"] if "key_env" in api else DEFAULT_KEY_ENV

    default_ratio = defaults.get("aspect_ratio", "1:1")
    assets: list[Asset] = []
    seen: set[str] = set()
    for i, row in enumerate(raw.get("assets", [])):
        for required in ("id", "prompt"):
            if required not in row:
                raise SpecError(f"assets[{i}]: '{required}' is required")
        if row["id"] in seen:
            raise SpecError(f"duplicate asset id: {row['id']}")
        seen.add(row["id"])
        assets.append(
            Asset(
                id=row["id"],
                prompt=row["prompt"],
                aspect_ratio=row.get("aspect_ratio", default_ratio),
                trim=row.get("trim", True),
            )
        )
    if not assets:
        raise SpecError(f"{spec_path}: no [[assets]] entries")

    return Pack(
        name=spec_path.stem,
        base_url=resolved_base,
        key_env=key_env,
        model=resolved_model,
        style_prefix=style.get("prefix", ""),
        plate_prompt=style.get("plate_prompt", ""),
        assets=assets,
        out_root=Path(out_root),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python test_config.py`
Expected: thirteen `ok  test_...` lines, then `all config tests passed`

- [ ] **Step 5: Commit**

```bash
git add config.py test_config.py
git commit -m "feat: add spec loading and config precedence resolution"
```

---

### Task 3: Chat-completions transport

**Files:**
- Create: `orclient.py`
- Test: `test_client.py`

**Interfaces:**
- Consumes: `config.Pack` (uses `.base_url`, `.model`, `.api_key()`).
- Produces:
  - `class ApiError(Exception)` with attribute `status: int | None`.
  - `class ImageMissing(Exception)` with attribute `raw: dict` (the full response body, so the caller can dump it for debugging).
  - `build_payload(model: str, prompt: str, reference_png: bytes | None = None, seed: int | None = None) -> dict`.
  - `build_headers(pack) -> dict`.
  - `parse_image(resp: dict) -> bytes`.
  - `response_cost(resp: dict) -> float | None`.
  - `generate(pack, prompt, reference_png=None, seed=None, retries=3, sleeper=time.sleep) -> tuple[bytes, float | None, dict]` returning `(png_bytes, cost_or_none, raw_response)`.

**Note on `sleeper`:** injected so retry tests run instantly instead of sleeping 6 real seconds. Production callers use the default.

- [ ] **Step 1: Write the failing tests**

Create `test_client.py`:

```python
"""Transport tests. No network is touched. Run: python test_client.py"""
import base64
import os

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python test_client.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'orclient'`

- [ ] **Step 3: Write `orclient.py`**

```python
"""Chat-completions transport for image generation.

Targets any OpenAI-schema endpoint that supports modalities: ["image", "text"].
This is the only OpenAI surface that carries a reference image without multipart,
which is why it is used instead of /images/generations or /images/edits.
"""

from __future__ import annotations

import base64
import json
import re
import time

import requests

_DATA_URI = re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,([A-Za-z0-9+/=]+)")
_TIMEOUT = 180


class ApiError(Exception):
    """The endpoint returned a non-200 status."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ImageMissing(Exception):
    """The call succeeded but no image could be found in the response."""

    def __init__(self, raw: dict):
        super().__init__("no image in response")
        self.raw = raw


def build_payload(
    model: str,
    prompt: str,
    reference_png: bytes | None = None,
    seed: int | None = None,
) -> dict:
    content: list[dict] = [{"type": "text", "text": prompt}]
    if reference_png:
        b64 = base64.b64encode(reference_png).decode()
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        )
    body = {
        "model": model,
        "modalities": ["image", "text"],
        "messages": [{"role": "user", "content": content}],
        "usage": {"include": True},
    }
    if seed is not None:
        # Not every provider honours this; the ones that do give us reproducibility.
        body["seed"] = seed
    return body


def build_headers(pack) -> dict:
    headers = {"Content-Type": "application/json"}
    key = pack.api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def parse_image(resp: dict) -> bytes:
    """Dig the image out of a response. Providers vary, so this is deliberately loose."""
    message = ((resp.get("choices") or [{}])[0] or {}).get("message") or {}

    # Preferred shape: OpenRouter's message.images[]
    for item in message.get("images") or []:
        url = ((item or {}).get("image_url") or {}).get("url", "")
        if url.startswith("data:image"):
            return base64.b64decode(url.split(",", 1)[1])

    # Fallback: any data URI anywhere in the message, whether the content is a
    # plain string or a structured list.
    match = _DATA_URI.search(json.dumps(message))
    if match:
        return base64.b64decode(match.group(1))

    raise ImageMissing(resp)


def response_cost(resp: dict) -> float | None:
    """Cost is an OpenRouter extension; local endpoints usually omit it."""
    cost = (resp.get("usage") or {}).get("cost")
    return float(cost) if isinstance(cost, (int, float)) else None


def generate(
    pack,
    prompt: str,
    reference_png: bytes | None = None,
    seed: int | None = None,
    retries: int = 3,
    sleeper=time.sleep,
) -> tuple[bytes, float | None, dict]:
    """Generate one image. Returns (png_bytes, cost_or_none, raw_response)."""
    url = pack.base_url.rstrip("/") + "/chat/completions"
    headers = build_headers(pack)
    payload = build_payload(pack.model, prompt, reference_png, seed)

    last_error: ApiError | None = None
    for attempt in range(retries):
        resp = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
        if resp.status_code == 200:
            body = resp.json()
            return parse_image(body), response_cost(body), body

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = ApiError(f"HTTP {resp.status_code}", resp.status_code)
            if attempt < retries - 1:
                sleeper(2 ** (attempt + 1))
            continue

        # Other 4xx: bad prompt, unknown model, bad key. Retrying is pointless.
        raise ApiError(f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

    raise last_error
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python test_client.py`
Expected: seventeen `ok  test_...` lines, then `all client tests passed`

- [ ] **Step 5: Commit**

```bash
git add orclient.py test_client.py
git commit -m "feat: add chat-completions image transport with retry and tolerant parsing"
```

---

### Task 4: CLI `build` command

**Files:**
- Create: `gen.py`
- Test: `test_build.py`

**Interfaces:**
- Consumes: `config.load_pack`, `config.Pack`, `config.Asset`, `config.SpecError`; `orclient.generate`, `orclient.ApiError`, `orclient.ImageMissing`; `post.cut_background`, `post.trim_and_pad`.
- Produces:
  - `EST_COST: float` — per-image estimate used by `--dry-run` (0.04).
  - `DEFAULT_MAX_COST: float` — 5.00.
  - `WORKERS: int` — 4. Module-level so tests can force single-asset chunks.
  - `select_assets(assets: list[Asset], only: str | None) -> list[Asset]`.
  - `_missing_key(pack) -> bool` — prints and reports whether a named key env var is unset.
  - `build_one(pack, asset, reference_png) -> dict` — one manifest record, never raises.
  - `cmd_build(args) -> int` — process exit code.
  - `main(argv=None) -> int`.

**Manifest record shape** (every key always present):

```python
{"id": str, "status": "ok" | "failed", "prompt": str, "model": str,
 "base_url": str, "seed": int, "cost": float | None,
 "file": str | None, "error": str | None}
```

- [ ] **Step 1: Write the failing tests**

Create `test_build.py`:

```python
"""Build orchestration tests. No network, no rembg. Run: python test_build.py"""
import json
import os
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image

import gen
import orclient
from config import Asset, Pack


def _png(color=(10, 20, 30)):
    """A real 64x64 PNG. init writes plates raw and then opens them with PIL,
    so those tests need bytes PIL can actually decode."""
    buf = BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    return buf.getvalue()

SPEC = """
[api]
key_env = ""
[pack]
model = "m/model"
[style]
prefix = "styled"
plate_prompt = "a button, an icon, a character"
[[assets]]
id = "btn_play"
prompt = "play button"
[[assets]]
id = "icon_coin"
prompt = "coin icon"
[[assets]]
id = "bg_sky"
prompt = "seamless sky"
trim = false
"""


def _spec_file(text=SPEC):
    d = Path(tempfile.mkdtemp())
    p = d / "hc_v1.toml"
    p.write_text(text)
    return p


def _pack(tmp):
    return Pack(
        name="t", base_url="http://svc/v1", key_env="", model="m/model",
        style_prefix="styled", plate_prompt="plate",
        assets=[Asset(id="a", prompt="p")], out_root=Path(tmp),
    )


class _Stubs:
    """Replaces generate/cut_background/trim_and_pad for the duration of a test."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)  # each is (png, cost) or an Exception
        self.prompts = []
        self.references = []

    def __enter__(self):
        self._orig = (gen.orclient.generate, gen.post.cut_background, gen.post.trim_and_pad)

        def fake_generate(pack, prompt, reference_png=None, seed=None, **kw):
            self.prompts.append(prompt)
            self.references.append(reference_png)
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            png, cost = outcome
            return png, cost, {"stub": True}

        gen.orclient.generate = fake_generate
        gen.post.cut_background = lambda data: _Img(data)
        gen.post.trim_and_pad = lambda img, **kw: _Img(img.data, trimmed=True)
        return self

    def __exit__(self, *exc):
        gen.orclient.generate, gen.post.cut_background, gen.post.trim_and_pad = self._orig


class _Img:
    """Minimal stand-in for a PIL image: records whether trim ran, writes a file."""

    def __init__(self, data, trimmed=False):
        self.data = data
        self.trimmed = trimmed

    def save(self, path):
        Path(path).write_bytes(self.data + (b"-trimmed" if self.trimmed else b""))


def _manifest(tmp, name="t"):
    return json.loads((Path(tmp) / name / "manifest.json").read_text())


def test_select_assets_filters_by_only_and_preserves_spec_order():
    assets = [Asset(id=i, prompt="p") for i in ("a", "b", "c")]
    assert [a.id for a in gen.select_assets(assets, None)] == ["a", "b", "c"]
    assert [a.id for a in gen.select_assets(assets, "c,a")] == ["a", "c"]


def test_select_assets_rejects_unknown_id():
    assets = [Asset(id="a", prompt="p")]
    try:
        gen.select_assets(assets, "nope")
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert "nope" in str(exc)


def test_dry_run_makes_no_requests():
    spec = _spec_file()
    with _Stubs([]) as stubs:
        code = gen.main(["build", str(spec), "--dry-run"])
    assert code == 0
    assert stubs.prompts == []


def test_dry_run_works_without_a_style_bible():
    """--dry-run must not require init/pick to have been run."""
    spec = _spec_file()
    with _Stubs([]):
        assert gen.main(["build", str(spec), "--dry-run"]) == 0


def test_build_without_style_bible_exits_with_error():
    spec = _spec_file()
    tmp = tempfile.mkdtemp()
    with _Stubs([]):
        code = gen.main(["build", str(spec), "--out-root", tmp])
    assert code == 1


def _prepare(tmp, spec_text=SPEC):
    """Create a spec plus a style_bible so build can run."""
    spec = _spec_file(spec_text)
    bible = Path(tmp) / "hc_v1" / "style_bible.png"
    bible.parent.mkdir(parents=True, exist_ok=True)
    bible.write_bytes(b"BIBLE")
    return spec


def test_build_writes_png_per_asset_and_a_manifest():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", 0.04), (b"B", 0.04), (b"C", 0.04)]):
        code = gen.main(["build", str(spec), "--out-root", tmp])
    assert code == 0
    out = Path(tmp) / "hc_v1"
    assert (out / "btn_play.png").exists()
    assert (out / "icon_coin.png").exists()
    records = _manifest(tmp, "hc_v1")
    assert [r["id"] for r in records] == ["btn_play", "icon_coin", "bg_sky"]
    assert all(r["status"] == "ok" for r in records)
    assert all(r["cost"] == 0.04 for r in records)


def test_build_sends_style_bible_as_reference_on_every_request():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", 0.0), (b"B", 0.0), (b"C", 0.0)]) as stubs:
        gen.main(["build", str(spec), "--out-root", tmp])
    assert stubs.references == [b"BIBLE", b"BIBLE", b"BIBLE"]


def test_build_skips_trim_when_asset_sets_trim_false():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", 0.0), (b"B", 0.0), (b"C", 0.0)]):
        gen.main(["build", str(spec), "--out-root", tmp])
    out = Path(tmp) / "hc_v1"
    assert (out / "btn_play.png").read_bytes() == b"A-trimmed"
    assert (out / "bg_sky.png").read_bytes() == b"C"  # trim = false


def test_one_failing_asset_does_not_stop_the_others():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    outcomes = [(b"A", 0.04), orclient.ApiError("HTTP 429", 429), (b"C", 0.04)]
    with _Stubs(outcomes):
        code = gen.main(["build", str(spec), "--out-root", tmp])
    assert code == 1  # non-zero because something failed
    records = {r["id"]: r for r in _manifest(tmp, "hc_v1")}
    assert records["btn_play"]["status"] == "ok"
    assert records["icon_coin"]["status"] == "failed"
    assert "429" in records["icon_coin"]["error"]
    assert records["bg_sky"]["status"] == "ok"


def test_missing_image_in_response_writes_error_json():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    outcomes = [
        orclient.ImageMissing({"choices": [{"message": {"content": "refused"}}]}),
        (b"B", 0.0), (b"C", 0.0),
    ]
    with _Stubs(outcomes):
        gen.main(["build", str(spec), "--out-root", tmp])
    dumped = json.loads((Path(tmp) / "hc_v1" / "btn_play.error.json").read_text())
    assert dumped["choices"][0]["message"]["content"] == "refused"


def test_post_processing_failure_keeps_the_raw_png():
    """A generated image is paid for; never throw it away."""
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"RAW", 0.04), (b"B", 0.0), (b"C", 0.0)]) as stubs:
        def boom(data):
            raise RuntimeError("shape error")
        gen.post.cut_background = boom
        gen.main(["build", str(spec), "--out-root", tmp])
    assert (Path(tmp) / "hc_v1" / "btn_play.raw.png").read_bytes() == b"RAW"
    records = {r["id"]: r for r in _manifest(tmp, "hc_v1")}
    assert records["btn_play"]["status"] == "failed"
    assert "shape error" in records["btn_play"]["error"]


def test_budget_ceiling_stops_before_the_next_request():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    # The ceiling is checked between chunks, so force chunks of one to observe it
    # precisely. With WORKERS=4 all three assets would fit in a single chunk.
    original_workers = gen.WORKERS
    gen.WORKERS = 1
    try:
        with _Stubs([(b"A", 0.04), (b"B", 0.04), (b"C", 0.04)]) as stubs:
            gen.main(["build", str(spec), "--out-root", tmp, "--max-cost", "0.05"])
    finally:
        gen.WORKERS = original_workers
    assert len(stubs.prompts) == 2  # spent 0.08 after two, third never requested
    records = _manifest(tmp, "hc_v1")
    assert len(records) == 2  # manifest still written for what did run


def test_missing_api_key_exits_before_any_request():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp, SPEC.replace('key_env = ""', 'key_env = "ABSENT_KEY_VAR"'))
    os.environ.pop("ABSENT_KEY_VAR", None)
    with _Stubs([]) as stubs:
        code = gen.main(["build", str(spec), "--out-root", tmp])
    assert code == 1
    assert stubs.prompts == []


def test_dry_run_does_not_require_an_api_key():
    spec = _spec_file(SPEC.replace('key_env = ""', 'key_env = "ABSENT_KEY_VAR"'))
    os.environ.pop("ABSENT_KEY_VAR", None)
    with _Stubs([]):
        assert gen.main(["build", str(spec), "--dry-run"]) == 0


def test_missing_cost_disables_the_ceiling_and_warns_once():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", None), (b"B", None), (b"C", None)]) as stubs:
        code = gen.main(["build", str(spec), "--out-root", tmp, "--max-cost", "0.01"])
    assert code == 0
    assert len(stubs.prompts) == 3  # ceiling could not be enforced, ran everything
    assert all(r["cost"] is None for r in _manifest(tmp, "hc_v1"))


def test_only_flag_limits_the_build_to_named_assets():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", 0.04)]) as stubs:
        gen.main(["build", str(spec), "--out-root", tmp, "--only", "btn_play"])
    assert len(stubs.prompts) == 1
    assert [r["id"] for r in _manifest(tmp, "hc_v1")] == ["btn_play"]


def test_manifest_records_carry_full_provenance():
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", 0.04), (b"B", 0.04), (b"C", 0.04)]):
        gen.main(["build", str(spec), "--out-root", tmp])
    rec = _manifest(tmp, "hc_v1")[0]
    for key in ("id", "status", "prompt", "model", "base_url", "seed", "cost", "file", "error"):
        assert key in rec, key
    assert rec["model"] == "m/model"
    assert rec["base_url"] == "http://svc/v1"
    assert "play button" in rec["prompt"]
    assert "#FF00FF" in rec["prompt"]  # BG_CLAUSE made it in


def test_bad_spec_exits_cleanly_without_a_traceback():
    bad = _spec_file("[pack]\nmodel = 'm'\n")  # no assets
    assert gen.main(["build", str(bad)]) == 1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all build tests passed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python test_build.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'gen'`

- [ ] **Step 3: Write `gen.py` with the `build` command**

```python
"""Sprite generator CLI.

Commands:
    init <spec>   generate style plate candidates
    pick <spec> N lock candidate N as the pack's style bible
    build <spec>  generate every asset in the spec
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import config
import orclient
import post

EST_COST = 0.04          # per-image estimate for --dry-run only
DEFAULT_MAX_COST = 5.00
WORKERS = 4              # API calls are I/O bound; rembg stays on the main thread


def select_assets(assets, only):
    """Filter assets by a comma-separated id list, preserving spec order."""
    if not only:
        return list(assets)
    wanted = [x.strip() for x in only.split(",") if x.strip()]
    known = {a.id for a in assets}
    unknown = [w for w in wanted if w not in known]
    if unknown:
        raise SystemExit(f"unknown asset id(s): {', '.join(unknown)}")
    return [a for a in assets if a.id in set(wanted)]


def _record(pack, asset, status, cost=None, file=None, error=None):
    return {
        "id": asset.id,
        "status": status,
        "prompt": pack.full_prompt(asset),
        "model": pack.model,
        "base_url": pack.base_url,
        "seed": pack.seed_for(asset.id),
        "cost": cost,
        "file": file,
        "error": error,
    }


def build_one(pack, asset, reference_png):
    """Generate and post-process one asset. Returns a manifest record, never raises."""
    out_dir = pack.out_dir
    try:
        png, cost, _raw = orclient.generate(
            pack,
            pack.full_prompt(asset),
            reference_png=reference_png,
            seed=pack.seed_for(asset.id),
        )
    except orclient.ImageMissing as exc:
        (out_dir / f"{asset.id}.error.json").write_text(json.dumps(exc.raw, indent=2))
        return _record(pack, asset, "failed", error=f"no image in response (see {asset.id}.error.json)")
    except orclient.ApiError as exc:
        return _record(pack, asset, "failed", error=str(exc))
    except Exception as exc:  # transport-level surprises: connection reset, DNS, ...
        return _record(pack, asset, "failed", error=f"{type(exc).__name__}: {exc}")

    # The image is paid for by this point. If post-processing fails, keep the raw
    # file rather than losing the money.
    try:
        img = post.cut_background(png)
        if asset.trim:
            img = post.trim_and_pad(img)
        target = out_dir / f"{asset.id}.png"
        img.save(target)
    except Exception as exc:
        (out_dir / f"{asset.id}.raw.png").write_bytes(png)
        return _record(pack, asset, "failed", cost=cost,
                       error=f"post-processing: {exc} (raw kept as {asset.id}.raw.png)")

    return _record(pack, asset, "ok", cost=cost, file=str(target))


def _missing_key(pack) -> bool:
    """An empty key_env means the endpoint needs no key. A named one that is unset
    is a mistake worth catching before we start firing doomed requests."""
    if pack.key_env and pack.api_key() is None:
        print(f"error: ${pack.key_env} is not set", file=sys.stderr)
        return True
    return False


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def cmd_build(args):
    try:
        pack = config.load_pack(
            args.spec, base_url=args.base_url, model=args.model,
            out_root=Path(args.out_root),
        )
    except config.SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    targets = select_assets(pack.assets, args.only)

    if args.dry_run:
        for asset in targets:
            print(f"[{asset.id}] {pack.full_prompt(asset)}")
        print(f"\n{len(targets)} assets, est. ${len(targets) * EST_COST:.2f}")
        return 0

    if _missing_key(pack):
        return 1

    if not pack.style_bible.exists():
        print(f"error: {pack.style_bible} not found — run `init` then `pick` first",
              file=sys.stderr)
        return 1

    pack.out_dir.mkdir(parents=True, exist_ok=True)
    reference = pack.style_bible.read_bytes()

    records = []
    spent = 0.0
    cost_available = True
    warned_no_cost = False
    stopped_early = False

    for chunk in _chunks(targets, WORKERS):
        if cost_available and spent >= args.max_cost:
            stopped_early = True
            break
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(build_one, pack, a, reference) for a in chunk]
            chunk_records = [f.result() for f in futures]
        for rec in chunk_records:
            records.append(rec)
            print(f"[{rec['id']:<16}] {rec['status']}"
                  + (f" — {rec['error']}" if rec["error"] else ""))
            if rec["cost"] is None and rec["status"] == "ok":
                cost_available = False
                if not warned_no_cost:
                    print("warning: cost reporting unavailable, --max-cost disabled")
                    warned_no_cost = True
            elif rec["cost"]:
                spent += rec["cost"]

    pack.manifest_path.write_text(json.dumps(records, indent=2))

    ok = sum(1 for r in records if r["status"] == "ok")
    failed = [r for r in records if r["status"] == "failed"]
    budget = f"(${spent:.2f} / ${args.max_cost:.2f})" if cost_available else "(cost unknown)"
    print(f"\ndone: {ok} ok, {len(failed)} failed  {budget}")
    if stopped_early:
        print(f"stopped: cost ceiling ${args.max_cost:.2f} reached, "
              f"{len(targets) - len(records)} assets not requested")
    if failed:
        print("failed: " + ", ".join(f"{r['id']} ({r['error']})" for r in failed))
        print(f"retry: python gen.py build {args.spec} --only "
              + ",".join(r["id"] for r in failed))
    return 0 if not failed else 1


def _add_common(sub):
    sub.add_argument("spec")
    sub.add_argument("--base-url", default=None, help="override [api] base_url")
    sub.add_argument("--model", default=None, help="override [pack] model")
    sub.add_argument("--out-root", default="out", help="root output directory")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gen.py", description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)

    build = subs.add_parser("build", help="generate every asset in the spec")
    _add_common(build)
    build.add_argument("--only", default=None, help="comma-separated asset ids")
    build.add_argument("--dry-run", action="store_true",
                       help="print prompts and estimated cost, make no requests")
    build.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST,
                       help=f"USD ceiling (default {DEFAULT_MAX_COST})")
    build.set_defaults(func=cmd_build)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python test_build.py`
Expected: eighteen `ok  test_...` lines, then `all build tests passed`

- [ ] **Step 5: Run the whole suite**

Run: `python test_post.py && python test_config.py && python test_client.py && python test_build.py`
Expected: all four suites print their pass line

- [ ] **Step 6: Commit**

```bash
git add gen.py test_build.py
git commit -m "feat: add build command with manifest, cost ceiling and partial-failure handling"
```

---

### Task 5: CLI `init` and `pick` commands

**Files:**
- Modify: `gen.py` (add `cmd_init`, `cmd_pick`, `contact_sheet`, register subparsers in `main`)
- Modify: `test_build.py` (append the init/pick tests below)

**Interfaces:**
- Consumes: everything from Task 4 (notably `_missing_key`, `_add_common`, `DEFAULT_MAX_COST`) plus `config.Pack.plate_full_prompt`, `config.Pack.candidates_dir`, `config.Pack.style_bible`.
- Produces:
  - `PLATE_COUNT: int` — 4.
  - `contact_sheet(paths: list[Path], out_path: Path) -> Path` — 2x2 grid PNG.
  - `cmd_init(args) -> int`, `cmd_pick(args) -> int`.

**Note:** style plates are saved raw, with no background removal. The bible must match what the model will actually produce for assets — magenta backdrop included — so the reference stays representative.

- [ ] **Step 1: Write the failing tests**

Append to `test_build.py`, before the `if __name__ == "__main__":` block:

```python
# --- init / pick -----------------------------------------------------------

# Distinct real PNGs, so contact_sheet can decode them and so we can tell which
# plate `pick` chose by comparing bytes.
PLATES = [_png((i * 60, 0, 0)) for i in range(4)]


def _plate_outcomes(cost=0.0, count=4):
    return [(PLATES[i], cost) for i in range(count)]


def test_init_generates_four_plates_and_a_contact_sheet():
    tmp = tempfile.mkdtemp()
    spec = _spec_file()
    with _Stubs(_plate_outcomes(0.04)) as stubs:
        code = gen.main(["init", str(spec), "--out-root", tmp, "--no-open"])
    assert code == 0
    cand = Path(tmp) / "hc_v1" / "style_candidates"
    assert sorted(p.name for p in cand.glob("*.png")) == [
        "0.png", "1.png", "2.png", "3.png", "contact_sheet.png",
    ]
    assert len(stubs.prompts) == 4


def test_init_sends_no_reference_and_uses_the_plate_prompt():
    tmp = tempfile.mkdtemp()
    spec = _spec_file()
    with _Stubs(_plate_outcomes()) as stubs:
        gen.main(["init", str(spec), "--out-root", tmp, "--no-open"])
    assert stubs.references == [None, None, None, None]
    assert all("a button, an icon, a character" in p for p in stubs.prompts)
    assert all("#FF00FF" in p for p in stubs.prompts)


def test_init_plates_are_saved_raw_without_background_removal():
    tmp = tempfile.mkdtemp()
    spec = _spec_file()
    with _Stubs(_plate_outcomes()):
        gen.main(["init", str(spec), "--out-root", tmp, "--no-open"])
    saved = (Path(tmp) / "hc_v1" / "style_candidates" / "0.png").read_bytes()
    assert saved == PLATES[0]  # byte-identical: nothing was post-processed


def test_init_respects_the_cost_ceiling():
    tmp = tempfile.mkdtemp()
    spec = _spec_file()
    with _Stubs(_plate_outcomes(0.04, count=2)) as stubs:
        code = gen.main(["init", str(spec), "--out-root", tmp, "--no-open",
                         "--max-cost", "0.05"])
    assert len(stubs.prompts) == 2  # spent 0.08 after two, third never requested
    assert code == 0


def test_pick_copies_the_chosen_candidate_to_style_bible():
    tmp = tempfile.mkdtemp()
    spec = _spec_file()
    with _Stubs(_plate_outcomes()):
        gen.main(["init", str(spec), "--out-root", tmp, "--no-open"])
    assert gen.main(["pick", str(spec), "2", "--out-root", tmp]) == 0
    assert (Path(tmp) / "hc_v1" / "style_bible.png").read_bytes() == PLATES[2]


def test_pick_rejects_an_out_of_range_index():
    tmp = tempfile.mkdtemp()
    spec = _spec_file()
    with _Stubs(_plate_outcomes()):
        gen.main(["init", str(spec), "--out-root", tmp, "--no-open"])
    assert gen.main(["pick", str(spec), "9", "--out-root", tmp]) == 1


def test_pick_without_init_exits_with_error():
    tmp = tempfile.mkdtemp()
    assert gen.main(["pick", str(_spec_file()), "0", "--out-root", tmp]) == 1


def test_build_runs_after_init_and_pick():
    """End-to-end wiring: the bible written by pick is the reference build sends."""
    tmp = tempfile.mkdtemp()
    spec = _spec_file()
    with _Stubs(_plate_outcomes()):
        gen.main(["init", str(spec), "--out-root", tmp, "--no-open"])
    gen.main(["pick", str(spec), "1", "--out-root", tmp])
    with _Stubs([(b"A", 0.0), (b"B", 0.0), (b"C", 0.0)]) as stubs:
        code = gen.main(["build", str(spec), "--out-root", tmp])
    assert code == 0
    assert stubs.references == [PLATES[1], PLATES[1], PLATES[1]]


def test_contact_sheet_is_a_two_by_two_grid():
    tmp = Path(tempfile.mkdtemp())
    paths = []
    for i in range(4):
        p = tmp / f"{i}.png"
        Image.new("RGB", (100, 100), (i * 60, 0, 0)).save(p)
        paths.append(p)
    sheet = gen.contact_sheet(paths, tmp / "sheet.png")
    with Image.open(sheet) as img:
        assert img.size == (200, 200)


def test_contact_sheet_handles_fewer_than_four_plates():
    """init stops early on a cost ceiling, so the sheet must cope with 2 images."""
    tmp = Path(tempfile.mkdtemp())
    paths = []
    for i in range(2):
        p = tmp / f"{i}.png"
        Image.new("RGB", (100, 100), (0, i * 60, 0)).save(p)
        paths.append(p)
    sheet = gen.contact_sheet(paths, tmp / "sheet.png")
    with Image.open(sheet) as img:
        assert img.size == (200, 200)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python test_build.py`
Expected: FAIL with `AttributeError: module 'gen' has no attribute 'contact_sheet'` (or an argparse error on the `init` subcommand)

- [ ] **Step 3: Add init/pick to `gen.py`**

Add these imports at the top of `gen.py`:

```python
import shutil
import webbrowser

from PIL import Image
```

Add `PLATE_COUNT` next to the other constants:

```python
PLATE_COUNT = 4          # style plate candidates produced by `init`
```

Add these functions above `_add_common`:

```python
def contact_sheet(paths, out_path):
    """Compose candidate images into a 2x2 grid so they can be compared at a glance."""
    images = [Image.open(p).convert("RGB") for p in paths]
    cell_w = max(im.width for im in images)
    cell_h = max(im.height for im in images)
    sheet = Image.new("RGB", (cell_w * 2, cell_h * 2), (24, 24, 24))
    for i, im in enumerate(images):
        sheet.paste(im, ((i % 2) * cell_w, (i // 2) * cell_h))
    sheet.save(out_path)
    for im in images:
        im.close()
    return out_path


def cmd_init(args):
    try:
        pack = config.load_pack(
            args.spec, base_url=args.base_url, model=args.model,
            out_root=Path(args.out_root),
        )
    except config.SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not pack.plate_prompt.strip():
        print("error: [style] plate_prompt is empty — it should show a button, "
              "an icon and a character together", file=sys.stderr)
        return 1

    if _missing_key(pack):
        return 1

    pack.candidates_dir.mkdir(parents=True, exist_ok=True)
    prompt = pack.plate_full_prompt()
    written = []
    spent = 0.0
    cost_available = True

    # Sequential on purpose: four requests, and stopping at the ceiling matters
    # more than shaving a few seconds.
    for i in range(PLATE_COUNT):
        if cost_available and spent >= args.max_cost:
            print(f"stopped: cost ceiling ${args.max_cost:.2f} reached")
            break
        try:
            # Plates carry no reference image: this is where the style is born.
            png, cost, _raw = orclient.generate(pack, prompt, seed=i)
        except (orclient.ApiError, orclient.ImageMissing) as exc:
            print(f"[plate {i}] failed — {exc}", file=sys.stderr)
            continue
        target = pack.candidates_dir / f"{i}.png"
        target.write_bytes(png)  # raw, no background removal
        written.append(target)
        print(f"[plate {i}] ok")
        if cost is None:
            cost_available = False
        else:
            spent += cost

    if not written:
        print("error: no plates were generated", file=sys.stderr)
        return 1

    sheet = contact_sheet(written, pack.candidates_dir / "contact_sheet.png")
    print(f"\n{len(written)} plates → {sheet}")
    print(f"pick one:  python gen.py pick {args.spec} <0-{len(written) - 1}>")
    if not args.no_open:
        webbrowser.open(Path(sheet).resolve().as_uri())
    return 0


def cmd_pick(args):
    try:
        pack = config.load_pack(
            args.spec, base_url=args.base_url, model=args.model,
            out_root=Path(args.out_root),
        )
    except config.SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    candidate = pack.candidates_dir / f"{args.index}.png"
    if not candidate.exists():
        print(f"error: {candidate} not found — run `init` first", file=sys.stderr)
        return 1

    pack.out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate, pack.style_bible)
    print(f"style bible locked: {pack.style_bible}")
    print(f"now run:  python gen.py build {args.spec}")
    return 0
```

Register the subcommands in `main`, after the `build` parser:

```python
    init = subs.add_parser("init", help="generate style plate candidates")
    _add_common(init)
    init.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST,
                      help=f"USD ceiling (default {DEFAULT_MAX_COST})")
    init.add_argument("--no-open", action="store_true",
                      help="do not open the contact sheet in a browser")
    init.set_defaults(func=cmd_init)

    pick = subs.add_parser("pick", help="lock a candidate as the pack's style bible")
    _add_common(pick)
    pick.add_argument("index", type=int, help="candidate number shown by init")
    pick.set_defaults(func=cmd_pick)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python test_build.py`
Expected: twenty-eight `ok  test_...` lines, then `all build tests passed`

- [ ] **Step 5: Run the whole suite**

Run: `python test_post.py && python test_config.py && python test_client.py && python test_build.py`
Expected: all four suites pass

- [ ] **Step 6: Commit**

```bash
git add gen.py test_build.py
git commit -m "feat: add init and pick commands for locking a pack style bible"
```

---

### Task 6: Example pack, docs, and live verification

**Files:**
- Create: `packs/hc_v1.toml`
- Create: `README.md`

**Interfaces:**
- Consumes: the complete CLI from Tasks 1-5.
- Produces: nothing other tasks depend on. This is the last task.

- [ ] **Step 1: Write the example pack**

Create `packs/hc_v1.toml`:

```toml
# Example pack: hyper-casual mobile game asset set.
# Copy this file, change the ids and prompts, keep the structure.

[api]
base_url = "https://openrouter.ai/api/v1"
key_env  = "OPENROUTER_API_KEY"
# For a local OpenAI-compatible endpoint:
#   base_url = "http://localhost:8080/v1"
#   key_env  = ""              # empty means no Authorization header at all

[pack]
model = "google/gemini-3.1-flash-image"

[style]
# Prepended to every prompt, including the style plates.
prefix = """
hypercasual mobile game asset, soft 3D render look, glossy plastic material,
rounded geometry, no outline, top-left key light, soft ambient occlusion,
palette #FF6B4A #4ECDC4 #FFE66D #2C3E50
"""
# Shown once per style plate. Keep a UI element, an icon and a character in the
# same frame — that is how you see whether the style holds across asset types.
plate_prompt = "a play button, a coin icon, and a small round character, side by side"

[defaults]
aspect_ratio = "1:1"

[[assets]]
id     = "btn_play"
prompt = "play button, rounded rectangle, white triangle glyph"

[[assets]]
id     = "btn_pause"
prompt = "pause button, rounded rectangle, two white bars"

[[assets]]
id     = "icon_coin"
prompt = "gold coin icon, front view, subtle shine"

[[assets]]
id     = "icon_star"
prompt = "five-pointed star icon, filled, glossy"

[[assets]]
id     = "panel_frame"
prompt = "rounded rectangular UI panel frame, empty center, soft border"

[[assets]]
id     = "hero_idle"
prompt = "small round blue character, idle pose, front view, big friendly eyes"
aspect_ratio = "3:4"

[[assets]]
id     = "obstacle_block"
prompt = "cube-shaped obstacle block, chunky, beveled edges"

[[assets]]
id     = "bg_sky"
prompt = "seamless pastel sky gradient with soft rounded clouds"
aspect_ratio = "9:16"
trim   = false
```

- [ ] **Step 2: Verify the spec parses without touching the network**

Run: `python gen.py build packs/hc_v1.toml --dry-run`
Expected: eight `[asset_id] <full prompt>` lines, each ending in `aspect ratio ...`, each containing `#FF00FF`, then `8 assets, est. $0.32`

- [ ] **Step 3: Write `README.md`**

````markdown
# Sprite Generator

Turns a TOML list of prompts into Unity-ready RGBA sprite PNGs, keeping the whole
set visually consistent by sending a locked style-reference image with every request.

## Install

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY=sk-...
```

Python 3.11 or newer. The first run downloads the `birefnet-general` background
removal weights to `~/.u2net/` (a few hundred MB, once).

## Use

```bash
# 1. Generate four candidate style plates and open them as a contact sheet
python gen.py init packs/hc_v1.toml

# 2. Lock the one you like as this pack's style bible
python gen.py pick packs/hc_v1.toml 2

# 3. Generate everything
python gen.py build packs/hc_v1.toml
```

Output lands in `out/<pack>/`: one RGBA PNG per asset plus `manifest.json`.

Useful flags:

| flag | effect |
|---|---|
| `--dry-run` | print every prompt and the estimated cost, make no requests |
| `--only id1,id2` | regenerate just these assets |
| `--max-cost 2.00` | stop before exceeding this USD total (default 5.00) |
| `--base-url` / `--model` | override the spec for one run |

## Pointing at another endpoint

Any OpenAI-schema endpoint that supports `modalities: ["image", "text"]` on
`/chat/completions` works. Set it in the spec:

```toml
[api]
base_url = "http://localhost:8080/v1"
key_env  = ""     # empty: no Authorization header is sent
```

Precedence is CLI flag > spec file > environment (`SPRITEGEN_BASE_URL`,
`SPRITEGEN_MODEL`) > OpenRouter default. **API keys are read from environment
variables only** — the spec file holds the variable's *name*, never its value.

The `usage.cost` field is an OpenRouter extension. Against an endpoint that omits
it, `--max-cost` cannot be enforced; the tool warns once and continues rather
than pretending the ceiling is active.

## Why the magenta backdrop

Hosted image models do not reliably emit an alpha channel — asked for
transparency, they tend to *paint* a checkerboard. So every prompt requests a flat
`#FF00FF` background and alpha is cut locally with rembg. Edge quality comes from
that clause, not from the model.

## Unity import

Set on each imported sprite: Texture Type `Sprite (2D and UI)`, `Alpha Is
Transparency` checked, Mesh Type `Tight`. Generating `.meta` files automatically
is not implemented.

## Tests

```bash
python test_post.py && python test_config.py && python test_client.py && python test_build.py
```

No network, no rembg model download, runs in about a second.
````

- [ ] **Step 4: Commit the pack and docs**

```bash
git add packs/hc_v1.toml README.md
git commit -m "docs: add example pack and README"
```

- [ ] **Step 5: Live verification — one real asset**

This step costs roughly $0.04 and cannot be automated; it is where the real
quality judgement happens.

```bash
export OPENROUTER_API_KEY=sk-...
python gen.py init packs/hc_v1.toml --max-cost 0.20
# look at the contact sheet, pick the plate whose style you want
python gen.py pick packs/hc_v1.toml <n>
python gen.py build packs/hc_v1.toml --only btn_play --max-cost 0.20
```

Then check, by eye:

1. `out/hc_v1/btn_play.png` opens with a genuinely transparent background — not a
   painted checkerboard.
2. No magenta fringe along the subject's edges. A visible fringe means rembg's
   matting is bleeding the backdrop; try a different backdrop colour in
   `config.BG_CLAUSE` (a mid-grey often helps when the subject is saturated).
3. `out/hc_v1/manifest.json` has one `ok` record with a non-null `cost`.
4. Import into Unity: Texture Type `Sprite (2D and UI)`, `Alpha Is Transparency`
   checked, Mesh Type `Tight`. The sprite should show no halo against a dark
   background.

- [ ] **Step 6: Full run**

```bash
python gen.py build packs/hc_v1.toml --max-cost 1.00
```

Expected: eight assets generated, a `done: 8 ok, 0 failed` summary, and a
manifest with eight records. Compare the eight PNGs side by side — they should
read as belonging to one game. If they do not, the style bible is the thing to
change, not the individual prompts.

---

## Notes for the implementer

**Do not "improve" these while implementing:**

- The magenta `BG_CLAUSE` looks like a hack. It is the mechanism that makes edge
  quality predictable; removing it moves alpha quality back onto the model, where
  it is unreliable.
- `zlib.crc32` instead of `hash()` for seeds is deliberate. Builtin `hash()` is
  randomized per process and would silently break reproducibility.
- `build_one` catching bare `Exception` around post-processing is deliberate. The
  image has already been paid for at that point; the raw file must survive.
- The cost ceiling is checked between chunks, not between individual requests.
  Up to `WORKERS` requests may be in flight when the ceiling is crossed. This is
  the accepted trade-off for parallelism — the overshoot is bounded at four images.
- Tests use plain `assert` and a hand-rolled recorder rather than a mocking
  library, per the spec's no-framework constraint.

**Deliberately not implemented** (from the spec's deferred list): CLIP drift
checking, Unity `.meta` generation, atlas packing, n=4 variant selection, local
LoRA training.
