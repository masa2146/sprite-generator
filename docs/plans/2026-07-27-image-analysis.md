# Image Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract a reference image's style (render, camera, lighting, palette, linework, realism) and subject via a vision model, turn the style into the pack's `[style] prefix`, and optionally add the subject as a new asset — plus a Claude Code skill that does the same analysis using Claude's own vision.

**Architecture:** Three new units with one responsibility each. `packwriter.py` edits a TOML pack by targeted line replacement (never re-serializing, so comments survive) behind a backup/write/verify/restore guard. `vision.py` turns image bytes into the fixed schema and the schema into prompt text. `gen.py analyze` wires them together. The retry loop currently inside `orclient.generate` is extracted so vision reuses it rather than growing a second copy. The Claude Code skill is a separate, side-effect-free path to the same schema.

**Tech Stack:** Python 3.11+ (`tomllib` read-only from stdlib), `requests`, existing `pillow`/`rembg`. No new dependencies.

**Spec:** `docs/specs/2026-07-27-image-analysis-design.md`

## Global Constraints

- Python 3.11+. `tomllib` is stdlib and **read-only** — never add `toml`, `tomli-w`, or `pyyaml`.
- Third-party dependencies stay exactly: `requests`, `pillow`, `rembg[gpu]`. This plan adds none.
- No test framework. Tests are `assert`-based functions in `test_*.py`, runnable as `python3 test_vision.py`. No pytest fixtures, no conftest, no mocking library — use the hand-rolled recorder/stub patterns already in `test_client.py` and `test_build.py`.
- **This machine has no `python` on PATH — only `python3`.** Every command, in code and in docs.
- API keys come from environment variables only. `key_env` holds the *name*; the existing credential guard in `config.load_pack` must also cover `[vision] key_env`.
- Writing to a pack file must never re-serialize it. Comments in `packs/hc_v1.toml` are load-bearing documentation.
- Every pack write is guarded: backup → write → re-parse and verify → restore from backup on failure.
- The analysis schema is exactly six style fields (`render`, `camera`, `lighting`, `palette`, `linework`, `realism`) plus `subject`. Field join order for prompt text is fixed: `render, camera, lighting, linework, realism, palette`.
- `style` and `subject` never mix: `subject` must not enter the style prefix.
- The Claude Code skill writes no files and runs no commands.

---

## File Structure

| File | Responsibility |
|---|---|
| `packwriter.py` | Targeted TOML edits (style prefix, append asset) with backup/verify/restore |
| `vision.py` | Analysis prompt, schema extraction/validation, prompt-text assembly, vision HTTP call |
| `orclient.py` | *(modified)* retry loop extracted to `post_with_retry` so `vision` shares it |
| `config.py` | *(modified)* `[vision]` resolution on `Pack` |
| `gen.py` | *(modified)* `analyze` subcommand |
| `test_packwriter.py` | Comment preservation, targeted replacement, restore-on-failure |
| `test_vision.py` | Schema extraction/validation, prompt assembly, vision request |
| `.claude/skills/image-style/SKILL.md` | Claude Code skill |
| `README.md` | *(modified)* document `analyze`, `[vision]`, and the skill |

Task order follows dependencies: `packwriter` depends on nothing; `config` depends on nothing; `vision` depends on `orclient`'s extracted helper; `gen analyze` depends on all three; the skill depends only on the schema being settled.

---

### Task 1: TOML pack writer

**Files:**
- Create: `packwriter.py`
- Test: `test_packwriter.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class PackWriteError(Exception)`
  - `update_pack(path, prefix: str | None = None, new_asset: tuple[str, str] | None = None) -> None` — `new_asset` is `(asset_id, prompt)`. Atomic: either both edits land and verify, or the file is byte-identical to how it started.

**Why targeted replacement:** `tomllib` cannot write. Parsing and re-emitting the pack would delete every comment in it — including the ones explaining `cutout = false` and the transport choice. So we edit the exact bytes we mean to change and leave everything else alone.

- [ ] **Step 1: Write the failing tests**

Create `test_packwriter.py`:

```python
"""TOML pack writer tests. Run: python3 test_packwriter.py"""
import tempfile
import tomllib
from pathlib import Path

from packwriter import PackWriteError, update_pack

PACK = '''# Example pack: hyper-casual mobile game asset set.
# Copy this file, change the ids and prompts, keep the structure.

[api]
base_url = "https://openrouter.ai/api/v1"
key_env  = "OPENROUTER_API_KEY"   # env var NAME, never the key itself

[pack]
model = "bytedance-seed/seedream-4.5"

[style]
# Prepended to every prompt, including the style plates.
prefix = """
old prefix line one,
old prefix line two
"""
plate_prompt = "a play button, a coin icon, and a small round character"

[defaults]
aspect_ratio = "1:1"

[[assets]]
id     = "btn_play"
prompt = "play button, rounded rectangle, white triangle glyph"

[[assets]]
id     = "bg_sky"
prompt = "seamless pastel sky gradient"
# This asset IS the whole image, not a sprite with a subject to cut out.
cutout = false
'''


def _pack_file(text=PACK):
    d = Path(tempfile.mkdtemp())
    p = d / "hc_v1.toml"
    p.write_text(text)
    return p


def _load(p):
    with open(p, "rb") as fh:
        return tomllib.load(fh)


def _comment_lines(text):
    return [ln for ln in text.splitlines() if ln.lstrip().startswith("#")]


def test_prefix_is_replaced():
    p = _pack_file()
    update_pack(p, prefix="new prefix text")
    assert _load(p)["style"]["prefix"].strip() == "new prefix text"


def test_every_comment_survives_a_prefix_write():
    p = _pack_file()
    before = _comment_lines(PACK)
    update_pack(p, prefix="new prefix text")
    after = _comment_lines(p.read_text())
    assert after == before, (before, after)


def test_untouched_sections_are_byte_identical():
    p = _pack_file()
    update_pack(p, prefix="new prefix text")
    text = p.read_text()
    for line in ('base_url = "https://openrouter.ai/api/v1"',
                 'model = "bytedance-seed/seedream-4.5"',
                 'plate_prompt = "a play button, a coin icon, and a small round character"',
                 'aspect_ratio = "1:1"',
                 'cutout = false'):
        assert line in text, line


def test_existing_assets_are_untouched_by_a_prefix_write():
    p = _pack_file()
    update_pack(p, prefix="new prefix text")
    assets = _load(p)["assets"]
    assert [a["id"] for a in assets] == ["btn_play", "bg_sky"]
    assert assets[1]["cutout"] is False


def test_asset_is_appended():
    p = _pack_file()
    update_pack(p, new_asset=("coin_ref", "gold coin icon, front view"))
    assets = _load(p)["assets"]
    assert [a["id"] for a in assets] == ["btn_play", "bg_sky", "coin_ref"]
    assert assets[2]["prompt"] == "gold coin icon, front view"


def test_prefix_and_asset_in_one_call():
    p = _pack_file()
    update_pack(p, prefix="new prefix", new_asset=("coin_ref", "gold coin icon"))
    d = _load(p)
    assert d["style"]["prefix"].strip() == "new prefix"
    assert d["assets"][-1]["id"] == "coin_ref"


def test_duplicate_asset_id_is_rejected_and_file_unchanged():
    p = _pack_file()
    original = p.read_text()
    try:
        update_pack(p, new_asset=("btn_play", "something else"))
        raise AssertionError("expected PackWriteError")
    except PackWriteError as exc:
        assert "btn_play" in str(exc)
    assert p.read_text() == original


def test_prompt_with_quotes_and_newlines_round_trips():
    p = _pack_file()
    tricky = 'a "glossy" coin\nwith a backslash \\ in it'
    update_pack(p, new_asset=("odd", tricky))
    assert _load(p)["assets"][-1]["prompt"] == tricky


def test_prefix_with_triple_quotes_round_trips():
    p = _pack_file()
    update_pack(p, prefix='has """ inside it')
    assert _load(p)["style"]["prefix"].strip() == 'has """ inside it'


def test_style_section_is_created_when_missing():
    no_style = PACK.replace('''[style]
# Prepended to every prompt, including the style plates.
prefix = """
old prefix line one,
old prefix line two
"""
plate_prompt = "a play button, a coin icon, and a small round character"

''', "")
    p = _pack_file(no_style)
    update_pack(p, prefix="brand new prefix")
    d = _load(p)
    assert d["style"]["prefix"].strip() == "brand new prefix"
    assert [a["id"] for a in d["assets"]] == ["btn_play", "bg_sky"]


def test_a_backup_file_is_left_behind():
    p = _pack_file()
    update_pack(p, prefix="new prefix text")
    assert p.with_suffix(".toml.bak").read_text() == PACK


def test_file_is_restored_when_verification_fails(monkey=None):
    """If the written file does not re-parse, the original must come back."""
    import packwriter
    p = _pack_file()
    original = p.read_text()
    broken = packwriter._set_style_prefix

    def sabotage(text, prefix):
        return text + '\n[[assets]]\nid = "x"\n'   # missing required prompt -> invalid pack

    packwriter._set_style_prefix = sabotage
    try:
        update_pack(p, prefix="whatever")
        raise AssertionError("expected PackWriteError")
    except PackWriteError:
        pass
    finally:
        packwriter._set_style_prefix = broken
    assert p.read_text() == original


def test_no_op_call_is_rejected():
    p = _pack_file()
    try:
        update_pack(p)
        raise AssertionError("expected PackWriteError")
    except PackWriteError:
        pass


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all packwriter tests passed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_packwriter.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'packwriter'`

- [ ] **Step 3: Write `packwriter.py`**

```python
"""Targeted edits to a TOML pack file.

tomllib is read-only, and re-serializing a parsed pack would delete every
comment in it — including the ones documenting cutout and the transport
choice. So we replace exactly the bytes we mean to change and leave the rest
of the file untouched, then verify the result still parses before keeping it.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


class PackWriteError(Exception):
    """The pack could not be updated; the file on disk is unchanged."""


# A section header at the start of a line: [style], [[assets]], ...
_SECTION = re.compile(r"^\[", re.M)
# prefix = "..." or prefix = """...""" (multi-line), captured as one value.
_PREFIX = re.compile(
    r'^([ \t]*prefix[ \t]*=[ \t]*)("""(?:.|\n)*?"""|"(?:[^"\\]|\\.)*")',
    re.M,
)


def _toml_string(value: str) -> str:
    """Encode a Python string as a TOML basic string.

    TOML basic strings use the same escapes as JSON, so json.dumps produces a
    valid one — and it handles embedded quotes, backslashes and newlines that
    would otherwise break the file.
    """
    return json.dumps(value)


def _prefix_literal(value: str) -> str:
    """Multi-line form when it is safe, quoted form when it is not."""
    if '"""' in value or "\\" in value:
        return _toml_string(value)
    return f'"""\n{value.strip()}\n"""'


def _section_body_span(text: str, header: str) -> tuple[int, int] | None:
    """Character span of a section's body, from after its header to the next one."""
    match = re.search(rf"^\[{re.escape(header)}\][ \t]*$", text, re.M)
    if not match:
        return None
    start = match.end()
    nxt = _SECTION.search(text, start)
    return start, (nxt.start() if nxt else len(text))


def _set_style_prefix(text: str, prefix: str) -> str:
    span = _section_body_span(text, "style")
    literal = _prefix_literal(prefix)

    if span is None:
        # No [style] section. Insert one before the first [[assets]] — TOML
        # table order matters, and a [style] table after [[assets]] would be
        # parsed as belonging to the last asset.
        block = f"[style]\nprefix = {literal}\n\n"
        first_asset = re.search(r"^\[\[assets\]\]", text, re.M)
        if first_asset:
            return text[: first_asset.start()] + block + text[first_asset.start() :]
        return text.rstrip("\n") + "\n\n" + block

    start, end = span
    body = text[start:end]
    replaced, count = _PREFIX.subn(lambda m: m.group(1) + literal, body, count=1)
    if count == 0:
        # [style] exists but has no prefix key — add one at the top of the body.
        replaced = f"\nprefix = {literal}\n" + body.lstrip("\n")
    return text[:start] + replaced + text[end:]


def _append_asset(text: str, asset_id: str, prompt: str) -> str:
    """Append a new [[assets]] block. Appending never shifts existing lines."""
    block = (
        f"\n[[assets]]\n"
        f"id     = {_toml_string(asset_id)}\n"
        f"prompt = {_toml_string(prompt)}\n"
    )
    return text.rstrip("\n") + "\n" + block


def _parse(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def update_pack(
    path,
    prefix: str | None = None,
    new_asset: tuple[str, str] | None = None,
) -> None:
    """Update a pack's style prefix and/or append an asset.

    Atomic in effect: the file either ends up with both edits applied and
    verified, or byte-identical to how it started.
    """
    path = Path(path)
    if prefix is None and new_asset is None:
        raise PackWriteError("update_pack: nothing to write")

    try:
        original = path.read_text()
    except OSError as exc:
        raise PackWriteError(f"cannot read {path}: {exc}")

    try:
        existing = _parse(path)
    except tomllib.TOMLDecodeError as exc:
        raise PackWriteError(f"{path} is not valid TOML to begin with: {exc}")

    if new_asset is not None:
        asset_id, asset_prompt = new_asset
        if any(a.get("id") == asset_id for a in existing.get("assets", [])):
            raise PackWriteError(
                f"asset id {asset_id!r} already exists in {path} — pick another id "
                "(a duplicate id makes the pack unloadable)"
            )

    text = original
    if prefix is not None:
        text = _set_style_prefix(text, prefix)
    if new_asset is not None:
        text = _append_asset(text, new_asset[0], new_asset[1])

    backup = path.with_suffix(path.suffix + ".bak")
    backup.write_text(original)
    path.write_text(text)

    try:
        written = _parse(path)
        if prefix is not None and written.get("style", {}).get("prefix", "").strip() != prefix.strip():
            raise ValueError("prefix did not round-trip")
        if new_asset is not None:
            ids = [a.get("id") for a in written.get("assets", [])]
            if new_asset[0] not in ids:
                raise ValueError(f"asset {new_asset[0]!r} missing after write")
            if len(ids) != len(existing.get("assets", [])) + 1:
                raise ValueError("asset count changed unexpectedly")
    except Exception as exc:
        path.write_text(original)
        raise PackWriteError(
            f"write to {path} did not verify ({exc}); the original has been restored "
            f"(a copy is also at {backup})"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_packwriter.py`
Expected: thirteen `ok  test_...` lines, then `all packwriter tests passed`

- [ ] **Step 5: Commit**

```bash
git add packwriter.py test_packwriter.py
git commit -m "feat: add TOML pack writer that preserves comments"
```

---

### Task 2: `[vision]` configuration

**Files:**
- Modify: `config.py`
- Test: `test_config.py` (append)

**Interfaces:**
- Consumes: existing `config.load_pack`, `SpecError`, `_VALID_ENV_NAME`, the credential guard.
- Produces, on `Pack`:
  - fields `vision_base_url: str`, `vision_key_env: str`, `vision_model: str | None`
  - method `vision_api_key() -> str | None`
- `load_pack` gains `vision_base_url=None` and `vision_model=None` keyword arguments.

**Fallback rule:** when `[vision]` omits a value, it falls back to the corresponding `[api]`/`[pack]` value already resolved — so someone using one endpoint for everything writes nothing. Precedence for each: CLI arg > `[vision]` > `[api]`/`[pack]` resolved value.

`vision_model` may be `None`; `analyze` is the only thing that needs it and reports a clear error then, rather than blocking `build` for packs that never analyze anything.

- [ ] **Step 1: Write the failing tests**

Append to `test_config.py`, before the `if __name__ == "__main__":` block:

```python
# --- [vision] section -------------------------------------------------------

VISION_SPEC = """
[api]
base_url = "https://openrouter.ai/api/v1"
key_env  = "OPENROUTER_API_KEY"

[vision]
base_url = "http://localhost:4000/v1"
key_env  = "OMNIROUTE_API_KEY"
model    = "anthropic/claude-sonnet-5"

[pack]
model = "bytedance-seed/seedream-4.5"

[style]
prefix = "p"

[[assets]]
id = "a"
prompt = "q"
"""


def test_vision_section_is_read():
    _clear_env()
    pack = load_pack(_write(VISION_SPEC))
    assert pack.vision_base_url == "http://localhost:4000/v1"
    assert pack.vision_key_env == "OMNIROUTE_API_KEY"
    assert pack.vision_model == "anthropic/claude-sonnet-5"


def test_vision_falls_back_to_api_section_when_absent():
    _clear_env()
    no_vision = VISION_SPEC.replace('''[vision]
base_url = "http://localhost:4000/v1"
key_env  = "OMNIROUTE_API_KEY"
model    = "anthropic/claude-sonnet-5"

''', "")
    pack = load_pack(_write(no_vision))
    assert pack.vision_base_url == "https://openrouter.ai/api/v1"
    assert pack.vision_key_env == "OPENROUTER_API_KEY"
    assert pack.vision_model is None


def test_vision_partial_section_falls_back_per_field():
    _clear_env()
    partial = VISION_SPEC.replace('''base_url = "http://localhost:4000/v1"
key_env  = "OMNIROUTE_API_KEY"
model    = "anthropic/claude-sonnet-5"''', 'model    = "some/vision-model"')
    pack = load_pack(_write(partial))
    assert pack.vision_base_url == "https://openrouter.ai/api/v1"   # from [api]
    assert pack.vision_key_env == "OPENROUTER_API_KEY"              # from [api]
    assert pack.vision_model == "some/vision-model"                 # from [vision]


def test_vision_cli_overrides_beat_the_spec():
    _clear_env()
    pack = load_pack(_write(VISION_SPEC),
                     vision_base_url="http://cli/v1", vision_model="cli/model")
    assert pack.vision_base_url == "http://cli/v1"
    assert pack.vision_model == "cli/model"


def test_vision_api_key_reads_its_own_env_var():
    _clear_env()
    pack = load_pack(_write(VISION_SPEC))
    assert pack.vision_api_key() is None
    os.environ["OMNIROUTE_API_KEY"] = "sk-vision"
    try:
        assert pack.vision_api_key() == "sk-vision"
    finally:
        del os.environ["OMNIROUTE_API_KEY"]


def test_vision_empty_key_env_means_no_key():
    _clear_env()
    spec = VISION_SPEC.replace('key_env  = "OMNIROUTE_API_KEY"', 'key_env  = ""')
    assert load_pack(_write(spec)).vision_api_key() is None


def test_vision_key_env_credential_guard():
    _clear_env()
    spec = VISION_SPEC.replace('key_env  = "OMNIROUTE_API_KEY"',
                               'key_env  = "sk-or-v1-abcdef1234567890"')
    try:
        load_pack(_write(spec))
        raise AssertionError("expected SpecError")
    except SpecError as exc:
        assert "key_env" in str(exc)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_config.py`
Expected: FAIL with `AttributeError: 'Pack' object has no attribute 'vision_base_url'`

- [ ] **Step 3: Modify `config.py`**

Add to the `Pack` dataclass, after `default_aspect_ratio`:

```python
    vision_base_url: str = ""
    vision_key_env: str = ""
    vision_model: str | None = None
```

Add this method to `Pack`, next to `api_key`:

```python
    def vision_api_key(self) -> str | None:
        """Vision may use a different endpoint and key than image generation."""
        return os.environ.get(self.vision_key_env) if self.vision_key_env else None
```

Extract the credential guard from `load_pack` into a module-level function (it now has two callers), placed above `load_pack`:

```python
def _check_key_env(key_env, where: str) -> None:
    """Reject a key value pasted where an env var *name* belongs.

    Users have pasted a live key here more than once; the silent consequence is
    no Authorization header and a confusing 401, so fail loudly at load time.
    """
    if not key_env:
        return  # explicitly empty: this endpoint needs no key
    if (
        not isinstance(key_env, str)
        or key_env.startswith("sk-")
        or not _VALID_ENV_NAME.fullmatch(key_env)
    ):
        raise SpecError(
            f"{where} key_env looks like a credential value, not an environment "
            f"variable name: {key_env!r}. key_env takes the NAME of an env var that "
            'holds the key, e.g. key_env = "OPENROUTER_API_KEY", with the key itself '
            "set via `export OPENROUTER_API_KEY=sk-...` — never the key itself in the spec."
        )
```

Replace the existing inline guard in `load_pack` with `_check_key_env(key_env, "[api]")`.

Change the `load_pack` signature to add the two new keyword arguments:

```python
def load_pack(
    spec_path,
    base_url: str | None = None,
    model: str | None = None,
    transport: str | None = None,
    vision_base_url: str | None = None,
    vision_model: str | None = None,
    out_root: Path = Path("out"),
) -> Pack:
```

After the existing `key_env` guard call and before the assets loop, resolve the vision settings:

```python
    vision = raw.get("vision", {})
    resolved_vision_base = (
        vision_base_url or vision.get("base_url") or resolved_base
    )
    resolved_vision_model = vision_model or vision.get("model")
    vision_key_env = vision["key_env"] if "key_env" in vision else key_env
    _check_key_env(vision_key_env, "[vision]")
```

Add to the `Pack(...)` construction at the end:

```python
        vision_base_url=resolved_vision_base,
        vision_key_env=vision_key_env,
        vision_model=resolved_vision_model,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_config.py`
Expected: all tests pass, including the seven new `test_vision_*` ones

- [ ] **Step 5: Run the whole suite**

Run: `python3 test_post.py && python3 test_config.py && python3 test_client.py && python3 test_build.py && python3 test_packwriter.py`
Expected: every suite prints its pass line

- [ ] **Step 6: Commit**

```bash
git add config.py test_config.py
git commit -m "feat: resolve a [vision] endpoint that falls back to [api]"
```

---

### Task 3: Vision analysis

**Files:**
- Modify: `orclient.py` (extract the retry loop)
- Create: `vision.py`
- Test: `test_vision.py`
- Test: `test_client.py` (append one test for the extracted helper)

**Interfaces:**
- Consumes: `config.Pack` (`vision_base_url`, `vision_model`, `vision_api_key()`), `orclient.ApiError`.
- Produces:
  - In `orclient`: `post_with_retry(url, payload, headers, retries=3, sleeper=time.sleep) -> dict` — returns the parsed 200 body, raises `ApiError` otherwise. `generate` is refactored to use it; its behavior must not change.
  - In `vision`: `STYLE_FIELDS: tuple[str, ...]`, `ANALYSIS_PROMPT: str`, `class AnalysisError(Exception)`, `extract_schema(text: str) -> dict`, `validate_schema(schema: dict) -> list[str]` (returns missing field paths), `style_prefix(schema: dict) -> str`, `reproduction_prompt(schema: dict) -> str`, `analyze(pack, image_bytes: bytes, retries=3, sleeper=time.sleep) -> tuple[dict, str]` returning `(schema, raw_text)`.

**Field order is fixed** — `render, camera, lighting, linework, realism, palette` — so every pack's prefix carries the same axes in the same order.

- [ ] **Step 1: Write the failing tests**

Create `test_vision.py`:

```python
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
```

Also append this to `test_client.py`, before its `if __name__ == "__main__":` block, to pin the extracted helper directly:

```python
def test_post_with_retry_returns_the_parsed_body_and_retries_5xx():
    rec = _Recorder([_Resp(500), _Resp(200, {"ok": True})])
    slept = []
    original = orclient.requests.post
    orclient.requests.post = rec
    try:
        body = orclient.post_with_retry("http://svc/v1/x", {"a": 1}, {}, sleeper=slept.append)
    finally:
        orclient.requests.post = original
    assert body == {"ok": True}
    assert len(rec.calls) == 2
    assert slept == [2]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_vision.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'vision'`

- [ ] **Step 3: Extract the retry loop in `orclient.py`**

Add this function above `generate`:

```python
def post_with_retry(
    url: str,
    payload: dict,
    headers: dict,
    retries: int = 3,
    sleeper=time.sleep,
) -> dict:
    """POST and return the parsed 200 body, retrying transient failures.

    429, 5xx and network-level errors retry with 2s then 4s backoff and no
    sleep after the final attempt. Other 4xx (bad prompt, unknown model, bad
    key) raise immediately — retrying them is pointless. Shared by image
    generation and vision analysis so there is only one retry policy.
    """
    last_error: ApiError | None = None
    for attempt in range(retries):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
        except requests.exceptions.RequestException as exc:
            # Timeout, connection reset, DNS failure, ... With a 180s timeout on
            # image generation, a timeout is the single most likely transient
            # failure — treat it like a 5xx and retry with the same backoff.
            last_error = ApiError(f"{type(exc).__name__}: {exc}")
            if attempt < retries - 1:
                sleeper(2 ** (attempt + 1))
            continue

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = ApiError(f"HTTP {resp.status_code}", resp.status_code)
            if attempt < retries - 1:
                sleeper(2 ** (attempt + 1))
            continue

        raise ApiError(f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

    raise last_error if last_error is not None else ApiError(
        f"post_with_retry called with retries={retries}: no attempt was made"
    )
```

Then replace `generate`'s loop (everything from `last_error: ApiError | None = None` to the final `raise`) with:

```python
    body = post_with_retry(url, payload, headers, retries=retries, sleeper=sleeper)
    return parse(body), response_cost(body), body
```

`generate`'s observable behavior must not change — the existing `test_client.py` retry tests still cover it.

- [ ] **Step 4: Write `vision.py`**

```python
"""Analyse a reference image into a fixed style schema.

The schema is fixed rather than free-form so every pack's style prefix carries
the same axes in the same order — a model asked for prose writes "a nice icon";
a model asked for six named fields has to answer each one.

style and subject stay separate: style applies to every asset in the pack,
subject describes only the analysed image. Folding subject into the prefix
would make every asset drift toward that one object.
"""

from __future__ import annotations

import base64
import json
import re

import orclient

STYLE_FIELDS = ("render", "camera", "lighting", "palette", "linework", "realism")
# Join order for prompt text, deliberately different from STYLE_FIELDS: palette
# reads best last, after the visual description it tints.
_JOIN_ORDER = ("render", "camera", "lighting", "linework", "realism", "palette")

ANALYSIS_PROMPT = """Analyse this image and describe it as JSON, with exactly this shape:

{
  "style": {
    "render":   "render technique and material, e.g. soft 3D render, glossy plastic material",
    "camera":   "camera angle and framing, e.g. 3/4 front view, slight high angle, centered",
    "lighting": "light direction, softness, shadows, e.g. top-left key light, soft ambient occlusion",
    "palette":  "dominant colours as hex codes, e.g. #FF6B4A #4ECDC4 #FFE66D",
    "linework": "outlines and geometry, e.g. no outline, rounded geometry, soft bevels",
    "realism":  "stylisation axis, e.g. stylized cartoon, not photorealistic"
  },
  "subject": "what the image actually depicts, as a generation prompt would phrase it"
}

Rules:
- "style" describes HOW the image looks and must not name the subject.
- "subject" describes WHAT it depicts, phrased as an image-generation prompt.
- Every field must be filled in. Reply with JSON only, no commentary."""

_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


class AnalysisError(Exception):
    """The image could not be analysed into the schema."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


def extract_schema(text: str) -> dict:
    """Pull the JSON object out of a model reply.

    Models wrap JSON in fences, prefix it with prose, or both — so try the
    fenced form, then the first balanced-looking object, before giving up.
    """
    match = _FENCED.search(text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise AnalysisError("no JSON object found in the reply", raw=text)


def validate_schema(schema: dict) -> list[str]:
    """Return the dotted paths of missing or blank fields; empty means valid."""
    missing: list[str] = []
    style = schema.get("style")
    if not isinstance(style, dict):
        missing.extend(f"style.{f}" for f in STYLE_FIELDS)
    else:
        for field in STYLE_FIELDS:
            value = style.get(field)
            if not isinstance(value, str) or not value.strip():
                missing.append(f"style.{field}")
    subject = schema.get("subject")
    if not isinstance(subject, str) or not subject.strip():
        missing.append("subject")
    return missing


def style_prefix(schema: dict) -> str:
    """The pack's [style] prefix: style fields only, never the subject."""
    style = schema.get("style", {})
    return ", ".join(style[f].strip() for f in _JOIN_ORDER if style.get(f))


def reproduction_prompt(schema: dict) -> str:
    """A ready prompt for regenerating this image: subject first, then style."""
    return f"{schema['subject'].strip()}, {style_prefix(schema)}"


def analyze(pack, image_bytes: bytes, retries: int = 3, sleeper=None) -> tuple[dict, str]:
    """Send the image to the vision endpoint. Returns (schema, raw_reply_text)."""
    if not pack.vision_model:
        raise AnalysisError(
            "no vision model: set [vision] model, pass --vision-model, "
            "or set [pack] model to a vision-capable model"
        )

    mime = orclient._sniff_mime(image_bytes)
    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "model": pack.vision_model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": ANALYSIS_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]}],
    }
    headers = {"Content-Type": "application/json"}
    key = pack.vision_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    url = pack.vision_base_url.rstrip("/") + "/chat/completions"
    kwargs = {"retries": retries}
    if sleeper is not None:
        kwargs["sleeper"] = sleeper
    body = orclient.post_with_retry(url, payload, headers, **kwargs)

    message = ((body.get("choices") or [{}])[0] or {}).get("message") or {}
    content = message.get("content")
    text = content if isinstance(content, str) else json.dumps(content)

    schema = extract_schema(text)          # raises AnalysisError carrying raw text
    missing = validate_schema(schema)
    if missing:
        raise AnalysisError(
            f"analysis is missing {len(missing)} field(s): {', '.join(missing)}",
            raw=text,
        )
    return schema, text
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 test_vision.py && python3 test_client.py`
Expected: both suites pass; `test_vision.py` prints twenty `ok  test_...` lines

- [ ] **Step 6: Commit**

```bash
git add orclient.py vision.py test_vision.py test_client.py
git commit -m "feat: analyse a reference image into a fixed style schema"
```

---

### Task 4: `gen.py analyze`

**Files:**
- Modify: `gen.py`
- Test: `test_build.py` (append)

**Interfaces:**
- Consumes: `vision.analyze`, `vision.style_prefix`, `vision.reproduction_prompt`, `vision.AnalysisError`; `packwriter.update_pack`, `packwriter.PackWriteError`; `config.load_pack`, `config.SpecError`.
- Produces: `cmd_analyze(args) -> int`, and an `analyze` subparser registered in `main`.

**Argument shape:** `analyze` takes the image as its positional and the pack as `--pack`, unlike the other subcommands whose positional *is* the spec. So `_add_common` gets split: the endpoint flags move into `_add_endpoint_flags`, which `_add_common` and `analyze` both call.

- [ ] **Step 1: Write the failing tests**

Append to `test_build.py`, before the `if __name__ == "__main__":` block:

```python
# --- analyze ----------------------------------------------------------------

ANALYSIS_SCHEMA = {
    "style": {
        "render": "soft 3D render, glossy plastic",
        "camera": "3/4 front view",
        "lighting": "top-left key light",
        "palette": "#FF6B4A #4ECDC4",
        "linework": "no outline, rounded geometry",
        "realism": "stylized cartoon",
    },
    "subject": "gold coin icon, front view, thick rim",
}


class _VisionStub:
    """Replaces vision.analyze for the duration of a test."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.images = []

    def __enter__(self):
        self._orig = gen.vision.analyze

        def fake(pack, image_bytes, **kw):
            self.images.append(image_bytes)
            if self.error:
                raise self.error
            return self.result, json.dumps(self.result)

        gen.vision.analyze = fake
        return self

    def __exit__(self, *exc):
        gen.vision.analyze = self._orig


def _analyze_pack(tmp):
    """A spec on disk plus a reference image; returns (spec_path, image_path)."""
    spec = _spec_file(SPEC)
    img = Path(tmp) / "ref.png"
    img.write_bytes(_png((7, 8, 9)))
    return spec, img


def test_analyze_dry_run_writes_nothing():
    tmp = tempfile.mkdtemp()
    spec, img = _analyze_pack(tmp)
    before = spec.read_text()
    with _VisionStub(result=ANALYSIS_SCHEMA):
        code = gen.main(["analyze", str(img), "--pack", str(spec),
                         "--out-root", tmp, "--dry-run"])
    assert code == 0
    assert spec.read_text() == before
    assert not (Path(tmp) / "hc_v1" / "style_bible.png").exists()


def test_analyze_writes_the_style_prefix():
    tmp = tempfile.mkdtemp()
    spec, img = _analyze_pack(tmp)
    with _VisionStub(result=ANALYSIS_SCHEMA):
        code = gen.main(["analyze", str(img), "--pack", str(spec), "--out-root", tmp])
    assert code == 0
    import tomllib
    with open(spec, "rb") as fh:
        written = tomllib.load(fh)["style"]["prefix"]
    assert "soft 3D render, glossy plastic" in written
    assert ANALYSIS_SCHEMA["subject"] not in written   # subject must not leak in


def test_analyze_copies_the_image_as_the_style_bible():
    tmp = tempfile.mkdtemp()
    spec, img = _analyze_pack(tmp)
    with _VisionStub(result=ANALYSIS_SCHEMA):
        gen.main(["analyze", str(img), "--pack", str(spec), "--out-root", tmp])
    bible = Path(tmp) / "hc_v1" / "style_bible.png"
    assert bible.read_bytes() == img.read_bytes()


def test_analyze_add_asset_appends_the_subject():
    tmp = tempfile.mkdtemp()
    spec, img = _analyze_pack(tmp)
    with _VisionStub(result=ANALYSIS_SCHEMA):
        code = gen.main(["analyze", str(img), "--pack", str(spec),
                         "--out-root", tmp, "--add-asset", "coin_ref"])
    assert code == 0
    import tomllib
    with open(spec, "rb") as fh:
        assets = tomllib.load(fh)["assets"]
    assert assets[-1]["id"] == "coin_ref"
    assert assets[-1]["prompt"].startswith(ANALYSIS_SCHEMA["subject"])


def test_analyze_without_add_asset_leaves_assets_alone():
    tmp = tempfile.mkdtemp()
    spec, img = _analyze_pack(tmp)
    import tomllib
    with open(spec, "rb") as fh:
        before = len(tomllib.load(fh)["assets"])
    with _VisionStub(result=ANALYSIS_SCHEMA):
        gen.main(["analyze", str(img), "--pack", str(spec), "--out-root", tmp])
    with open(spec, "rb") as fh:
        assert len(tomllib.load(fh)["assets"]) == before


def test_analyze_duplicate_asset_id_fails_without_writing():
    tmp = tempfile.mkdtemp()
    spec, img = _analyze_pack(tmp)
    before = spec.read_text()
    with _VisionStub(result=ANALYSIS_SCHEMA):
        code = gen.main(["analyze", str(img), "--pack", str(spec),
                         "--out-root", tmp, "--add-asset", "btn_play"])
    assert code == 1
    assert spec.read_text() == before


def test_analyze_missing_image_exits_cleanly():
    tmp = tempfile.mkdtemp()
    spec, _ = _analyze_pack(tmp)
    with _VisionStub(result=ANALYSIS_SCHEMA):
        code = gen.main(["analyze", str(Path(tmp) / "nope.png"),
                         "--pack", str(spec), "--out-root", tmp])
    assert code == 1


def test_analyze_failure_writes_the_raw_reply_and_leaves_the_pack_alone():
    tmp = tempfile.mkdtemp()
    spec, img = _analyze_pack(tmp)
    before = spec.read_text()
    err = gen.vision.AnalysisError("no JSON object found in the reply",
                                   raw="I cannot analyze this image.")
    with _VisionStub(error=err):
        code = gen.main(["analyze", str(img), "--pack", str(spec), "--out-root", tmp])
    assert code == 1
    assert spec.read_text() == before
    dump = img.with_suffix(".png.analysis-error.txt")
    assert "I cannot analyze this image." in dump.read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_build.py`
Expected: FAIL with `AttributeError: module 'gen' has no attribute 'vision'` (or an argparse error on the `analyze` subcommand)

- [ ] **Step 3: Add `analyze` to `gen.py`**

Add to the imports at the top:

```python
import packwriter
import vision
```

Add `cmd_analyze` above `_add_common`:

```python
def cmd_analyze(args):
    try:
        pack = config.load_pack(
            args.pack, base_url=args.base_url, model=args.model,
            transport=args.transport, vision_base_url=args.vision_base_url,
            vision_model=args.vision_model, out_root=Path(args.out_root),
        )
    except config.SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    image_path = Path(args.image)
    try:
        image_bytes = image_path.read_bytes()
    except OSError as exc:
        print(f"error: cannot read {image_path}: {exc}", file=sys.stderr)
        return 1

    try:
        schema, _raw = vision.analyze(pack, image_bytes)
    except vision.AnalysisError as exc:
        # The reply is the only evidence of what went wrong; keep it on disk
        # rather than making the user re-run and re-pay to see it again.
        if exc.raw:
            dump = image_path.with_suffix(image_path.suffix + ".analysis-error.txt")
            try:
                dump.write_text(exc.raw)
                print(f"error: {exc} (raw reply written to {dump})", file=sys.stderr)
            except OSError:
                print(f"error: {exc}", file=sys.stderr)
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1
    except orclient.ApiError as exc:
        print(f"error: vision request failed: {exc}", file=sys.stderr)
        return 1

    prefix = vision.style_prefix(schema)
    repro = vision.reproduction_prompt(schema)

    print("style:")
    for field in vision.STYLE_FIELDS:
        print(f"  {field:<9} {schema['style'][field]}")
    print(f"\nsubject: {schema['subject']}")
    print(f"\n[style] prefix:\n{prefix}")
    print(f"\nreproduction prompt:\n{repro}")

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    try:
        packwriter.update_pack(
            args.pack,
            prefix=prefix,
            new_asset=(args.add_asset, repro) if args.add_asset else None,
        )
    except packwriter.PackWriteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"\nwrote [style] prefix -> {args.pack}")
    if args.add_asset:
        print(f"wrote [[assets]] {args.add_asset} -> {args.pack}")

    pack.out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(image_path, pack.style_bible)
    print(f"wrote style bible     -> {pack.style_bible}")
    print(f"\nnow run:  python3 gen.py build {args.pack}")
    return 0
```

Split `_add_common` so `analyze` can reuse the endpoint flags without inheriting the `spec` positional:

```python
def _add_endpoint_flags(sub):
    sub.add_argument("--base-url", default=None, help="override [api] base_url")
    sub.add_argument("--model", default=None, help="override [pack] model")
    sub.add_argument("--transport", default=None, choices=config.VALID_TRANSPORTS,
                     help="override [api] transport")
    sub.add_argument("--vision-base-url", default=None,
                     help="override [vision] base_url")
    sub.add_argument("--vision-model", default=None, help="override [vision] model")
    sub.add_argument("--out-root", default="out", help="root output directory")


def _add_common(sub):
    sub.add_argument("spec")
    _add_endpoint_flags(sub)
```

Register the subcommand in `main`, after the `pick` parser:

```python
    analyze = subs.add_parser(
        "analyze", help="analyse a reference image into the pack's style prefix")
    analyze.add_argument("image", help="reference image to analyse")
    analyze.add_argument("--pack", required=True, help="spec file to update")
    _add_endpoint_flags(analyze)
    analyze.add_argument("--add-asset", default=None, metavar="ID",
                         help="also append the detected subject as a new asset")
    analyze.add_argument("--dry-run", action="store_true",
                         help="print the analysis, write nothing")
    analyze.set_defaults(func=cmd_analyze)
```

- [ ] **Step 4: Fix a stale command in the test file's docstring**

`test_build.py`'s first line reads `Run: python test_build.py`. There is no
`python` on this machine, only `python3`. Since you are already editing this
file, correct it:

```python
"""Build orchestration tests. No network, no rembg. Run: python3 test_build.py"""
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 test_build.py`
Expected: all tests pass, including the eight new `test_analyze_*` ones

- [ ] **Step 6: Run the whole suite**

Run: `python3 test_post.py && python3 test_config.py && python3 test_client.py && python3 test_build.py && python3 test_packwriter.py && python3 test_vision.py`
Expected: every suite prints its pass line

- [ ] **Step 7: Commit**

```bash
git add gen.py test_build.py
git commit -m "feat: add analyze command writing style prefix and style bible"
```

---

### Task 5: Claude Code skill and docs

**Files:**
- Create: `.claude/skills/image-style/SKILL.md`
- Modify: `README.md`
- Modify: `packs/hc_v1.toml` (add a commented `[vision]` example)

**Interfaces:**
- Consumes: the schema and field order settled in Task 3. Nothing consumes this task.

**The skill runs no commands and writes no files.** Claude Code can read an image directly, so the skill needs no endpoint, key or cost — it is the zero-setup path to the same schema `gen.py analyze` produces.

- [ ] **Step 1: Write the skill**

Create `.claude/skills/image-style/SKILL.md`:

````markdown
---
name: image-style
description: Analyse a reference image into a fixed style schema — render, camera, lighting, palette, linework, realism — plus what the image depicts, and turn them into a style prefix and a ready reproduction prompt. Use when the user shares an image and wants its look described, reproduced, or turned into a sprite-generator pack's style prefix.
---

# Image Style Analysis

Read a reference image and describe it in a fixed schema, then turn that schema
into two pieces of prompt text.

This produces the same schema as `gen.py analyze` in the sprite_generator
project, so output from either can be used in place of the other. Unlike the
CLI, this skill needs no API endpoint or key — you can see the image directly.

## What to do

1. **Read the image** the user points at.
2. **Fill in the schema below.** Every field. If something genuinely cannot be
   determined, say so in that field rather than leaving it blank or inventing
   detail.
3. **Print the three blocks** in the Output section.

**Write nothing to disk and run no commands.** This skill only reads and
reports. If the user wants the result written into a pack file, that is
`gen.py analyze`'s job — tell them the command rather than editing the file
yourself.

## Schema

Six style fields plus a subject:

| field | what it captures |
|---|---|
| `render` | render technique and material — *soft 3D render, glossy plastic material* |
| `camera` | angle and framing — *3/4 front view, slight high angle, centered* |
| `lighting` | direction, softness, shadows — *top-left key light, soft ambient occlusion, no harsh shadow* |
| `palette` | dominant colours as hex codes — *#FF6B4A #4ECDC4 #FFE66D* |
| `linework` | outlines and geometry — *no outline, rounded geometry, soft bevels* |
| `realism` | stylisation axis — *stylized cartoon, not photorealistic* |
| `subject` | what it depicts, phrased as a generation prompt would |

**`style` describes HOW the image looks and must never name the subject.**
`subject` describes WHAT it depicts. Keeping them apart matters: the style
fields get applied to a whole set of assets, and a subject that leaks into them
makes every asset drift toward that one object — the button starts looking like
the coin.

Give hex codes in `palette`, not colour names. "Warm orange" is not
reproducible; `#FF6B4A` is.

## Output

### 1. Metrics table

The six style fields and the subject, one per row.

### 2. Style prefix

The style fields joined in this exact order, comma-separated, subject excluded:

```
render, camera, lighting, linework, realism, palette
```

This is what goes in a pack's `[style] prefix`. The order is fixed so that
every pack's prefix carries the same axes in the same sequence.

### 3. Reproduction prompt

`subject` first, then the style prefix — a ready prompt for regenerating this
image or a close sibling:

```
<subject>, <style prefix>
```

If the user asks for JSON, emit exactly this shape so it matches the CLI:

```json
{
  "style": {
    "render": "...", "camera": "...", "lighting": "...",
    "palette": "...", "linework": "...", "realism": "..."
  },
  "subject": "..."
}
```

## Using it with the sprite generator

To write the result into a pack instead of copying by hand:

```bash
python3 gen.py analyze <image> --pack packs/<name>.toml
```

That writes the `[style] prefix`, copies the image to
`out/<pack>/style_bible.png`, and with `--add-asset <id>` appends the subject as
a new asset. Add `--dry-run` to preview without writing.
````

- [ ] **Step 2: Verify the skill file is well-formed**

Run: `head -5 .claude/skills/image-style/SKILL.md`
Expected: a YAML frontmatter block opening with `---`, then `name: image-style`

- [ ] **Step 3: Add a commented `[vision]` example to `packs/hc_v1.toml`**

Insert after the `[api]` block:

```toml
# Optional: a separate endpoint for `analyze` (image understanding). Omit the
# whole section to reuse [api]. Each field falls back individually.
# [vision]
# base_url = "http://localhost:4000/v1"   # omniroute / litellm
# key_env  = "OMNIROUTE_API_KEY"
# model    = "anthropic/claude-sonnet-5"
```

- [ ] **Step 4: Document `analyze` in `README.md`**

Add to the "Use" section, before the numbered `init` step:

````markdown
If you already have a reference image, skip `init`/`pick` entirely — analyse it
instead. That writes the style prefix *and* locks the image as the style bible,
saving the four style-plate generations:

```bash
python3 gen.py analyze ref.png --pack packs/hc_v1.toml
```
````

Add this section after the "Transport" section:

````markdown
## Analysing a reference image

```bash
python3 gen.py analyze <image> --pack <spec.toml> [--add-asset <id>] [--dry-run]
```

Sends the image to a vision model and extracts six style fields — render,
camera, lighting, palette, linework, realism — plus what the image depicts.
The style fields become the pack's `[style] prefix`; the image is copied to
`out/<pack>/style_bible.png`; with `--add-asset <id>` the detected subject is
appended as a new asset. `--dry-run` prints everything and writes nothing.

The subject is deliberately kept out of the style prefix: the prefix applies to
every asset in the pack, and a subject folded into it makes them all drift
toward that one object.

### The `[vision]` endpoint

Analysis can use a different endpoint and model than image generation — a plain
OpenAI-schema `/chat/completions` that accepts an image and replies with text:

```toml
[vision]
base_url = "http://localhost:4000/v1"   # omniroute / litellm
key_env  = "OMNIROUTE_API_KEY"
model    = "anthropic/claude-sonnet-5"
```

Omit the section entirely to reuse `[api]`. Each field falls back on its own, so
you can override just the model. Precedence: `--vision-base-url` /
`--vision-model` > `[vision]` > `[api]`.

### Writing to the pack

`analyze` edits the pack in place with targeted line replacement rather than
re-serializing it, so every comment survives. Each write is guarded: the file is
backed up to `<pack>.toml.bak`, written, re-parsed and verified — and restored
from the original if verification fails.

### Doing the same thing inside Claude Code

`.claude/skills/image-style/SKILL.md` performs the same analysis using Claude's
own vision, with no endpoint, key or cost. It only reads and reports — writing
into a pack stays `analyze`'s job. To use it from other projects:

```bash
ln -s "$PWD/.claude/skills/image-style" ~/.claude/skills/image-style
```
````

Also add `test_packwriter.py` and `test_vision.py` to the Tests section's command.

- [ ] **Step 5: Verify the docs match the code**

Run: `python3 gen.py analyze --help`
Expected: usage shows the `image` positional, `--pack`, `--add-asset`, `--dry-run`, and the vision flags

Run: `python3 gen.py build packs/hc_v1.toml --dry-run`
Expected: still 8 assets and an estimate — the commented `[vision]` block must not have broken the pack

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/image-style/SKILL.md README.md packs/hc_v1.toml
git commit -m "docs: add image-style skill and document the analyze command"
```

---

## Notes for the implementer

**Do not "improve" these while implementing:**

- Targeted line replacement instead of parsing and re-emitting the TOML is the
  whole point of `packwriter`. `tomllib` cannot write, and any round-trip
  through a parser deletes the comments that document the pack.
- The backup/write/verify/restore sequence is not belt-and-braces: a corrupted
  pack is unloadable, and the user's own edits live in that file.
- `style` and `subject` staying separate is structural, not stylistic.
- The join order (`render, camera, lighting, linework, realism, palette`)
  differs from `STYLE_FIELDS` on purpose — palette reads best last.
- `extract_schema` being loose about fenced blocks and surrounding prose is
  deliberate; models wrap JSON in all of these.
- The Claude Code skill writing nothing and running nothing is what makes it
  safe to invoke anywhere.

**Deliberately not implemented** (from the spec's out-of-scope list): the skill
generating images or writing packs, drift checking of generated output,
multi-image style averaging, and auto-deriving an asset id from the subject.
