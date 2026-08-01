# One-Shot `make` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single command that takes an image, a text, or both, and produces one finished sprite — no pack file involved.

**Architecture:** Four small additions rather than a parallel pipeline. `envfile.py` loads `.env` into `os.environ`, which means the existing `key_env` indirection keeps working untouched — no special case. `vision.py` grows two schema fields (`form`, `detail`), an optional user-text override, and an object-prompt assembler. `config.env_pack` builds an ephemeral `Pack` from the environment so `vision.analyze` and `orclient.generate` take it unchanged. `gen.py` gains `cmd_make` to orchestrate.

**Tech Stack:** Python 3.11+, `requests`, `pillow`, `rembg[gpu]`. No new dependencies.

**Spec:** `docs/specs/2026-07-28-one-shot-make-design.md`

## Global Constraints

- Python 3.11+. **Add no dependencies** — no `python-dotenv`, no test framework, no mocking library.
- **No `python` on PATH — only `python3`.** Every command, in code and docs.
- Tests are `assert`-based functions in `test_*.py`, runnable as `python3 test_make.py`. Follow the hand-rolled recorder/stub patterns already in `test_client.py`, `test_vision.py` and `test_build.py`.
- The analysis schema is exactly six style fields (`render`, `camera`, `lighting`, `palette`, `linework`, `realism`) plus `form`, `detail`, `subject` — nine in total.
- Object-prompt join order is fixed: `subject, form, detail, render, camera, lighting, linework, realism, palette`.
- The pack `[style] prefix` still uses **only** the six style fields. `form`, `detail` and `subject` never enter it.
- `.env` **never overrides a real environment variable.** Precedence: CLI flag > real env var > `.env` > built-in default.
- `.env` is searched next to `gen.py` (project root), not in the working directory.
- `--dry-run` writes nothing and makes no image request.
- Text-only input makes **no vision call at all**.

---

## File Structure

| File | Responsibility |
|---|---|
| `envfile.py` | Parse `.env` and load it into `os.environ` without overriding existing values |
| `vision.py` | *(modified)* two new schema fields, optional user-text override, object-prompt assembly |
| `config.py` | *(modified)* `env_pack()` — build an ephemeral `Pack` from the environment |
| `gen.py` | *(modified)* `cmd_make` and its subparser |
| `test_env.py` | `.env` parsing and precedence |
| `test_make.py` | Input validation, prompt assembly, output naming, the `make` flow |
| `.env.example` | Documented template |
| `README.md` | *(modified)* document `make` and `.env` |

Task order: `envfile` depends on nothing; `vision` changes depend on nothing; `config.env_pack` depends on `envfile`; `cmd_make` depends on all three.

---

### Task 1: `.env` loader

**Files:**
- Create: `envfile.py`
- Test: `test_env.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `parse_env(text: str) -> dict[str, str]`
  - `load_env(path=None) -> dict[str, str]` — reads the file, puts values into `os.environ` **only** for keys not already present, returns what it loaded (all parsed pairs, whether or not they were applied). Missing file is not an error: returns `{}`.

**Why load into `os.environ` rather than returning config:** the existing `Pack.api_key()` reads `os.environ[key_env]`. Loading `.env` into the environment means that whole mechanism keeps working with zero special-casing, and `export FOO=...` still wins as users expect.

- [ ] **Step 1: Write the failing tests**

Create `test_env.py`:

```python
"""`.env` loading tests. Run: python3 test_env.py"""
import os
import tempfile
from pathlib import Path

from envfile import load_env, parse_env

SAMPLE = """# a comment
SPRITEGEN_BASE_URL=https://openrouter.ai/api/v1

SPRITEGEN_MODEL="black-forest-labs/flux.2-max"
SPRITEGEN_API_KEY='sk-or-v1-quoted'
  SPRITEGEN_VISION_MODEL = cc/claude-sonnet-5
WEIRD=a=b=c
EMPTY=
export SPRITEGEN_TRANSPORT=images
"""


def _env_file(text=SAMPLE):
    d = Path(tempfile.mkdtemp())
    p = d / ".env"
    p.write_text(text, encoding="utf-8")
    return p


def test_plain_pair():
    assert parse_env(SAMPLE)["SPRITEGEN_BASE_URL"] == "https://openrouter.ai/api/v1"


def test_double_quotes_are_stripped():
    assert parse_env(SAMPLE)["SPRITEGEN_MODEL"] == "black-forest-labs/flux.2-max"


def test_single_quotes_are_stripped():
    assert parse_env(SAMPLE)["SPRITEGEN_API_KEY"] == "sk-or-v1-quoted"


def test_surrounding_whitespace_is_stripped():
    assert parse_env(SAMPLE)["SPRITEGEN_VISION_MODEL"] == "cc/claude-sonnet-5"


def test_only_the_first_equals_splits():
    assert parse_env(SAMPLE)["WEIRD"] == "a=b=c"


def test_empty_value_is_kept():
    assert parse_env(SAMPLE)["EMPTY"] == ""


def test_export_prefix_is_accepted():
    assert parse_env(SAMPLE)["SPRITEGEN_TRANSPORT"] == "images"


def test_comments_and_blank_lines_are_ignored():
    keys = parse_env(SAMPLE).keys()
    assert not any(k.startswith("#") for k in keys)
    assert "" not in keys


def test_a_line_without_equals_is_ignored():
    assert parse_env("JUST_A_WORD\nA=1") == {"A": "1"}


def test_load_env_populates_os_environ():
    for k in ("SPRITEGEN_MODEL", "SPRITEGEN_BASE_URL"):
        os.environ.pop(k, None)
    p = _env_file()
    try:
        loaded = load_env(p)
        assert loaded["SPRITEGEN_MODEL"] == "black-forest-labs/flux.2-max"
        assert os.environ["SPRITEGEN_MODEL"] == "black-forest-labs/flux.2-max"
    finally:
        for k in parse_env(SAMPLE):
            os.environ.pop(k, None)


def test_a_real_env_var_is_not_overridden():
    os.environ["SPRITEGEN_MODEL"] = "already/set"
    p = _env_file()
    try:
        loaded = load_env(p)
        assert loaded["SPRITEGEN_MODEL"] == "black-forest-labs/flux.2-max"  # parsed
        assert os.environ["SPRITEGEN_MODEL"] == "already/set"               # not applied
    finally:
        for k in parse_env(SAMPLE):
            os.environ.pop(k, None)


def test_missing_file_is_not_an_error():
    assert load_env(Path(tempfile.mkdtemp()) / "nope.env") == {}


def test_unreadable_file_is_not_an_error():
    d = Path(tempfile.mkdtemp())
    assert load_env(d) == {}          # a directory, not a file


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all env tests passed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_env.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'envfile'`

- [ ] **Step 3: Write `envfile.py`**

```python
"""Load a .env file into the process environment.

Values go into os.environ rather than being returned as config, because
Pack.api_key() already reads os.environ[key_env] — loading here means that
whole indirection keeps working with no special case for .env-sourced keys.

A real environment variable always wins: `export FOO=bar` overriding the file
is what users expect, and silently losing to a checked-in file would be a
nasty surprise in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ENV_PATH = Path(__file__).resolve().parent / ".env"


def parse_env(text: str) -> dict[str, str]:
    """Parse KEY=value lines. Ignores comments, blanks and lines without '='."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)      # only the first '=' splits
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def load_env(path=None) -> dict[str, str]:
    """Read `path` (default: .env beside this file) and apply it to os.environ.

    Returns every parsed pair, including ones not applied because the variable
    was already set — the caller may want to report what the file contained.
    A missing or unreadable file is not an error.
    """
    path = Path(path) if path is not None else DEFAULT_ENV_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}

    pairs = parse_env(text)
    for key, value in pairs.items():
        os.environ.setdefault(key, value)     # never override a real env var
    return pairs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_env.py`
Expected: thirteen `ok  test_...` lines, then `all env tests passed`

- [ ] **Step 5: Commit**

```bash
git add envfile.py test_env.py
git commit -m "feat: load .env without overriding real environment variables"
```

---

### Task 2: Schema growth, user override, object prompt

**Files:**
- Modify: `vision.py`
- Modify: `test_vision.py`
- Modify: `test_build.py` (its `ANALYSIS_SCHEMA` fixture needs the two new fields)

**Interfaces:**
- Consumes: existing `vision.STYLE_FIELDS`, `ANALYSIS_PROMPT`, `extract_schema`, `validate_schema`, `style_prefix`, `analyze`.
- Produces:
  - `SUBJECT_FIELDS: tuple[str, ...]` — `("subject", "form", "detail")`
  - `PROMPT_ORDER: tuple[str, ...]` — `("subject", "form", "detail", "render", "camera", "lighting", "linework", "realism", "palette")`
  - `object_prompt(schema: dict) -> str` — the full single-object prompt in `PROMPT_ORDER`, skipping absent fields.
  - `analyze(pack, image_bytes, user_text: str | None = None, retries=3, sleeper=None)` — `user_text` appends the override clause.

**This task breaks two existing fixtures on purpose.** `test_vision.py`'s `SCHEMA` and `test_build.py`'s `ANALYSIS_SCHEMA` must gain `form` and `detail`, or `validate_schema` will report them missing. Update both; do not weaken `validate_schema` to accommodate old fixtures.

**Why `style_prefix` must not change:** it feeds a pack's `[style] prefix`, which is applied to *every* asset. `form` and `detail` describe one object's geometry — in a shared prefix they would drag every asset toward that one shape, exactly the reason `subject` is already excluded.

- [ ] **Step 1: Write the failing tests**

Append to `test_vision.py`, before its `if __name__ == "__main__":` block:

```python
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
```

Then update `test_vision.py`'s existing `SCHEMA` constant to include the two new keys, so the pre-existing tests still describe a valid schema:

```python
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
```

And update `test_build.py`'s `ANALYSIS_SCHEMA` the same way:

```python
ANALYSIS_SCHEMA = {
    "style": {
        "render": "soft 3D render, glossy plastic",
        "camera": "3/4 front view",
        "lighting": "top-left key light",
        "palette": "#FF6B4A #4ECDC4",
        "linework": "no outline, rounded geometry",
        "realism": "stylized cartoon",
    },
    "form": "a single rounded disc with a thick rim",
    "detail": "subtle radial shine",
    "subject": "gold coin icon, front view, thick rim",
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_vision.py`
Expected: FAIL with `AttributeError: module 'vision' has no attribute 'object_prompt'`

- [ ] **Step 3: Modify `vision.py`**

Add next to the existing field constants:

```python
# Subject-side fields: what the object IS and how it is built. These never
# enter a pack's [style] prefix — that prefix is applied to every asset, and
# one object's geometry in it would drag the whole set toward that shape.
SUBJECT_FIELDS = ("subject", "form", "detail")

# Full single-object prompt order: identity, then geometry, then surface
# detail, then style, with palette last.
PROMPT_ORDER = (
    "subject", "form", "detail",
    "render", "camera", "lighting", "linework", "realism", "palette",
)
```

Replace `ANALYSIS_PROMPT` with the nine-field version:

```python
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
  "form": "the object's construction: how many parts, their arrangement and proportions, e.g. two stacked parts, a ribbed panel above a rounded box with a vertical slot",
  "detail": "distinguishing smaller features: rim thickness, bevels, surface finish, markings",
  "subject": "what the object IS, phrased as an image-generation prompt would name it"
}

Rules:
- "style" describes HOW it looks and must not name the subject.
- "form" describes the object's structure precisely enough to rebuild it from words alone.
- "subject" names WHAT it is, briefly.
- Every field must be filled in. Reply with JSON only, no commentary."""

USER_OVERRIDE_CLAUSE = """

The user also asked for: {text}

Where the user's request conflicts with what you see, follow the user. Fill every
field the user did not speak to from the image as normal."""
```

Extend `validate_schema` to cover the two new top-level fields — replace its subject check with a loop:

```python
    for field in ("form", "detail", "subject"):
        value = schema.get(field)
        if not isinstance(value, str) or not value.strip():
            missing.append(field)
    return missing
```

Add `object_prompt` after `style_prefix`:

```python
def object_prompt(schema: dict) -> str:
    """The full single-object prompt: identity, geometry, detail, then style.

    Unlike style_prefix this deliberately includes subject/form/detail — it
    describes one object rather than a style shared across a set.
    """
    style = schema.get("style") or {}
    parts = []
    for field in PROMPT_ORDER:
        value = schema.get(field) if field in SUBJECT_FIELDS else style.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return ", ".join(parts)
```

Give `analyze` the new parameter and clause:

```python
def analyze(pack, image_bytes: bytes, user_text: str | None = None,
            retries: int = 3, sleeper=None) -> tuple[dict, str]:
```

and inside, build the instruction text before the payload:

```python
    instruction = ANALYSIS_PROMPT
    if user_text and user_text.strip():
        instruction += USER_OVERRIDE_CLAUSE.format(text=user_text.strip())
```

then use `instruction` in place of `ANALYSIS_PROMPT` in the message content.

- [ ] **Step 4: Run the affected suites**

Run: `python3 test_vision.py && python3 test_build.py`
Expected: both pass. If `test_build.py` fails on a missing `form`/`detail`, its `ANALYSIS_SCHEMA` fixture was not updated — fix the fixture, not `validate_schema`.

- [ ] **Step 5: Commit**

```bash
git add vision.py test_vision.py test_build.py
git commit -m "feat: add form and detail to the schema, plus user-text override"
```

---

### Task 3: `config.env_pack`

**Files:**
- Modify: `config.py`
- Test: `test_config.py` (append)

**Interfaces:**
- Consumes: `envfile.load_env`; existing `Pack`, `DEFAULT_BASE_URL`, `DEFAULT_TRANSPORT`, `VALID_TRANSPORTS`, `SpecError`, `_check_key_env`.
- Produces: `env_pack(base_url=None, model=None, transport=None, vision_base_url=None, vision_model=None, out_root=Path("out")) -> Pack` — an ephemeral `Pack` with no assets, built from the environment.

**Variable names and their fallbacks:**

| setting | primary | falls back to |
|---|---|---|
| base url | `SPRITEGEN_BASE_URL` | `DEFAULT_BASE_URL` |
| api key | `SPRITEGEN_API_KEY` | `OPENROUTER_API_KEY` |
| model | `SPRITEGEN_MODEL` | — (required; clear error) |
| transport | `SPRITEGEN_TRANSPORT` | `DEFAULT_TRANSPORT` |
| vision base url | `SPRITEGEN_VISION_BASE_URL` | the resolved base url |
| vision key | `SPRITEGEN_VISION_API_KEY` | the resolved api key variable |
| vision model | `SPRITEGEN_VISION_MODEL` | — (may be `None`; only `make -i` needs it) |

`key_env` stores the *name* of whichever variable is actually populated, so `Pack.api_key()` works unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `test_config.py`, before its `if __name__ == "__main__":` block:

```python
# --- env_pack ---------------------------------------------------------------

_ENV_VARS = (
    "SPRITEGEN_BASE_URL", "SPRITEGEN_API_KEY", "SPRITEGEN_MODEL",
    "SPRITEGEN_TRANSPORT", "SPRITEGEN_VISION_BASE_URL",
    "SPRITEGEN_VISION_API_KEY", "SPRITEGEN_VISION_MODEL", "OPENROUTER_API_KEY",
)


def _clear_spritegen():
    for k in _ENV_VARS:
        os.environ.pop(k, None)


def test_env_pack_reads_the_environment():
    _clear_spritegen()
    os.environ.update({
        "SPRITEGEN_BASE_URL": "http://env/v1",
        "SPRITEGEN_MODEL": "env/model",
        "SPRITEGEN_API_KEY": "sk-env",
        "SPRITEGEN_VISION_MODEL": "env/vision",
    })
    try:
        from config import env_pack
        p = env_pack()
        assert p.base_url == "http://env/v1"
        assert p.model == "env/model"
        assert p.api_key() == "sk-env"
        assert p.vision_model == "env/vision"
        assert p.assets == []
    finally:
        _clear_spritegen()


def test_env_pack_falls_back_to_openrouter_api_key():
    _clear_spritegen()
    os.environ.update({"SPRITEGEN_MODEL": "m", "OPENROUTER_API_KEY": "sk-legacy"})
    try:
        from config import env_pack
        assert env_pack().api_key() == "sk-legacy"
    finally:
        _clear_spritegen()


def test_env_pack_vision_falls_back_to_the_main_endpoint_and_key():
    _clear_spritegen()
    os.environ.update({
        "SPRITEGEN_BASE_URL": "http://main/v1",
        "SPRITEGEN_MODEL": "m",
        "SPRITEGEN_API_KEY": "sk-main",
    })
    try:
        from config import env_pack
        p = env_pack()
        assert p.vision_base_url == "http://main/v1"
        assert p.vision_api_key() == "sk-main"
        assert p.vision_model is None
    finally:
        _clear_spritegen()


def test_env_pack_cli_arguments_win():
    _clear_spritegen()
    os.environ.update({"SPRITEGEN_MODEL": "env/model"})
    try:
        from config import env_pack
        p = env_pack(model="cli/model", base_url="http://cli/v1",
                     vision_model="cli/vision")
        assert p.model == "cli/model"
        assert p.base_url == "http://cli/v1"
        assert p.vision_model == "cli/vision"
    finally:
        _clear_spritegen()


def test_env_pack_without_a_model_is_an_error():
    _clear_spritegen()
    from config import env_pack
    try:
        env_pack()
        raise AssertionError("expected SpecError")
    except SpecError as exc:
        assert "SPRITEGEN_MODEL" in str(exc)


def test_env_pack_rejects_an_invalid_transport():
    _clear_spritegen()
    os.environ.update({"SPRITEGEN_MODEL": "m", "SPRITEGEN_TRANSPORT": "carrier-pigeon"})
    try:
        from config import env_pack
        env_pack()
        raise AssertionError("expected SpecError")
    except SpecError as exc:
        assert "transport" in str(exc)
    finally:
        _clear_spritegen()


def test_env_pack_defaults_transport_and_base_url():
    _clear_spritegen()
    os.environ.update({"SPRITEGEN_MODEL": "m"})
    try:
        from config import env_pack
        p = env_pack()
        assert p.transport == DEFAULT_TRANSPORT
        assert p.base_url == DEFAULT_BASE_URL
    finally:
        _clear_spritegen()
```

Add `DEFAULT_TRANSPORT` and `DEFAULT_BASE_URL` to `test_config.py`'s imports from `config`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_config.py`
Expected: FAIL with `ImportError: cannot import name 'env_pack' from 'config'`

- [ ] **Step 3: Add `env_pack` to `config.py`**

Add the import at the top:

```python
import envfile
```

Add this function after `load_pack`:

```python
def env_pack(
    base_url: str | None = None,
    model: str | None = None,
    transport: str | None = None,
    vision_base_url: str | None = None,
    vision_model: str | None = None,
    out_root: Path = Path("out"),
) -> Pack:
    """Build an ephemeral Pack from the environment, for the pack-less `make`.

    Loads .env first (which never overrides a real environment variable), so
    the resolution below sees file-provided values as if they had been
    exported. key_env stores the NAME of whichever variable is populated, so
    Pack.api_key() keeps working unchanged.
    """
    envfile.load_env()

    resolved_base = base_url or os.environ.get("SPRITEGEN_BASE_URL") or DEFAULT_BASE_URL

    resolved_model = model or os.environ.get("SPRITEGEN_MODEL")
    if not resolved_model:
        raise SpecError(
            "no image model: set SPRITEGEN_MODEL in .env or the environment, "
            "or pass --model"
        )

    resolved_transport = (
        transport or os.environ.get("SPRITEGEN_TRANSPORT") or DEFAULT_TRANSPORT
    )
    if resolved_transport not in VALID_TRANSPORTS:
        raise SpecError(
            f"invalid transport {resolved_transport!r}: must be 'images' or 'chat' "
            "(set SPRITEGEN_TRANSPORT or pass --transport)"
        )

    # Store the name of whichever key variable is actually populated.
    key_env = "SPRITEGEN_API_KEY" if os.environ.get("SPRITEGEN_API_KEY") else DEFAULT_KEY_ENV
    vision_key_env = (
        "SPRITEGEN_VISION_API_KEY"
        if os.environ.get("SPRITEGEN_VISION_API_KEY")
        else key_env
    )
    _check_key_env(key_env, "SPRITEGEN_API_KEY")
    _check_key_env(vision_key_env, "SPRITEGEN_VISION_API_KEY")

    return Pack(
        name="make",
        base_url=resolved_base,
        key_env=key_env,
        model=resolved_model,
        style_prefix="",
        plate_prompt="",
        assets=[],
        out_root=Path(out_root),
        transport=resolved_transport,
        vision_base_url=(
            vision_base_url
            or os.environ.get("SPRITEGEN_VISION_BASE_URL")
            or resolved_base
        ),
        vision_key_env=vision_key_env,
        vision_model=vision_model or os.environ.get("SPRITEGEN_VISION_MODEL"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_config.py`
Expected: all pass, including the seven new `test_env_pack_*` ones

- [ ] **Step 5: Commit**

```bash
git add config.py test_config.py
git commit -m "feat: build an ephemeral Pack from the environment"
```

---

### Task 4: `gen.py make`

**Files:**
- Modify: `gen.py`
- Test: `test_make.py`

**Interfaces:**
- Consumes: `config.env_pack`, `config.SpecError`, `config.BG_CLAUSE`; `vision.analyze`, `vision.object_prompt`, `vision.AnalysisError`; `orclient.generate`, `orclient.ApiError`, `orclient.ImageMissing`; `post.cut_background`, `post.trim_and_pad`.
- Produces: `slugify(text: str, limit: int = 40) -> str`; `cmd_make(args) -> int`; a `make` subparser.

**Flow:** validate input → (image only) analyze → assemble prompt → generate n variants → post-process → write PNG + sidecar JSON.

- [ ] **Step 1: Write the failing tests**

Create `test_make.py`:

```python
"""`make` command tests. No network, no rembg. Run: python3 test_make.py"""
import json
import os
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image

import gen


def _png(color=(10, 20, 30)):
    buf = BytesIO()
    Image.new("RGB", (32, 32), color).save(buf, format="PNG")
    return buf.getvalue()


SCHEMA = {
    "style": {
        "render": "soft 3D render, glossy plastic",
        "camera": "3/4 front view",
        "lighting": "top-left key light",
        "palette": "#FF6B4A #4ECDC4",
        "linework": "no outline, rounded geometry",
        "realism": "stylized cartoon",
    },
    "form": "two stacked parts, a ribbed panel above a rounded box",
    "detail": "thick bevelled rim",
    "subject": "a small launcher chute",
}


class _Img:
    """Stands in for a PIL image: records whether trim ran, writes a file."""

    def __init__(self, data, trimmed=False):
        self.data = data
        self.trimmed = trimmed

    def save(self, path):
        Path(path).write_bytes(self.data + (b"-trimmed" if self.trimmed else b""))


class _Stubs:
    """Swaps vision.analyze, orclient.generate and both post functions."""

    def __init__(self, schema=SCHEMA, outcomes=None, analyze_error=None):
        self.schema = schema
        self.outcomes = list(outcomes or [(b"IMG", 0.05)])
        self.analyze_error = analyze_error
        self.analyze_calls = []
        self.prompts = []
        self.references = []
        self.seeds = []
        self.cut_calls = 0
        self.trim_calls = 0

    def __enter__(self):
        self._orig = (gen.vision.analyze, gen.orclient.generate,
                      gen.post.cut_background, gen.post.trim_and_pad)
        # A real .env in the project root would silently fill variables these
        # tests deliberately leave empty, so point the loader at nothing.
        import envfile
        self._orig_env_path = envfile.DEFAULT_ENV_PATH
        envfile.DEFAULT_ENV_PATH = Path(tempfile.mkdtemp()) / "absent.env"

        def fake_analyze(pack, image_bytes, user_text=None, **kw):
            self.analyze_calls.append({"bytes": image_bytes, "user_text": user_text})
            if self.analyze_error:
                raise self.analyze_error
            return self.schema, json.dumps(self.schema)

        def fake_generate(pack, prompt, aspect_ratio=None, reference_png=None,
                          seed=None, **kw):
            self.prompts.append(prompt)
            self.references.append(reference_png)
            self.seeds.append(seed)
            outcome = self.outcomes.pop(0) if self.outcomes else (b"IMG", 0.05)
            if isinstance(outcome, Exception):
                raise outcome
            data, cost = outcome
            return data, cost, {"stub": True}

        def fake_cut(data):
            self.cut_calls += 1
            return _Img(data)

        def fake_trim(img, **kw):
            self.trim_calls += 1
            return _Img(img.data, trimmed=True)

        gen.vision.analyze = fake_analyze
        gen.orclient.generate = fake_generate
        gen.post.cut_background = fake_cut
        gen.post.trim_and_pad = fake_trim
        return self

    def __exit__(self, *exc):
        (gen.vision.analyze, gen.orclient.generate,
         gen.post.cut_background, gen.post.trim_and_pad) = self._orig
        import envfile
        envfile.DEFAULT_ENV_PATH = self._orig_env_path


def _env():
    os.environ.update({
        "SPRITEGEN_MODEL": "img/model",
        "SPRITEGEN_VISION_MODEL": "vis/model",
        "SPRITEGEN_API_KEY": "sk-test",
    })


def _clear():
    for k in ("SPRITEGEN_MODEL", "SPRITEGEN_VISION_MODEL", "SPRITEGEN_API_KEY",
              "SPRITEGEN_BASE_URL", "SPRITEGEN_TRANSPORT"):
        os.environ.pop(k, None)


def _image_file(tmp):
    p = Path(tmp) / "ref.png"
    p.write_bytes(_png())
    return p


# --- slug -------------------------------------------------------------------

def test_slugify_lowercases_and_replaces_runs():
    assert gen.slugify("A Small Launcher Chute!") == "a-small-launcher-chute"


def test_slugify_truncates_and_has_no_trailing_dash():
    s = gen.slugify("x" * 80)
    assert len(s) <= 40 and not s.endswith("-")


def test_slugify_falls_back_when_nothing_survives():
    assert gen.slugify("!!!") == "sprite"


# --- input validation -------------------------------------------------------

def test_neither_image_nor_text_is_an_error():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            assert gen.main(["make", "--out-root", tmp]) == 1
            assert s.analyze_calls == []
            assert s.prompts == []
    finally:
        _clear()


def test_text_only_makes_no_vision_call():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            code = gen.main(["make", "-t", "a glossy blue button", "--out-root", tmp])
        assert code == 0
        assert s.analyze_calls == []                 # nothing to analyse, nothing to pay for
        assert "a glossy blue button" in s.prompts[0]
        assert s.references == [None]
    finally:
        _clear()


def test_image_only_analyses_without_user_text():
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    try:
        with _Stubs() as s:
            code = gen.main(["make", "-i", str(img), "--out-root", tmp])
        assert code == 0
        assert len(s.analyze_calls) == 1
        assert s.analyze_calls[0]["user_text"] is None
        assert SCHEMA["subject"] in s.prompts[0]
    finally:
        _clear()


def test_image_plus_text_passes_the_text_to_analyze():
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    try:
        with _Stubs() as s:
            gen.main(["make", "-i", str(img), "-t", "make it red", "--out-root", tmp])
        assert s.analyze_calls[0]["user_text"] == "make it red"
    finally:
        _clear()


def test_missing_image_file_exits_cleanly():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            code = gen.main(["make", "-i", str(Path(tmp) / "nope.png"),
                             "--out-root", tmp])
        assert code == 1
        assert s.prompts == []
    finally:
        _clear()


# --- prompt + reference -----------------------------------------------------

def test_the_image_is_sent_as_a_generation_reference():
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    try:
        with _Stubs() as s:
            gen.main(["make", "-i", str(img), "--out-root", tmp])
        assert s.references[0] == img.read_bytes()
    finally:
        _clear()


def test_backdrop_clause_is_appended_by_default():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            gen.main(["make", "-t", "a coin", "--out-root", tmp])
        assert "#808080" in s.prompts[0]
    finally:
        _clear()


def test_no_cutout_skips_backdrop_and_post_processing():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs() as s:
            gen.main(["make", "-t", "a seamless sky", "--no-cutout", "--out-root", tmp])
        assert "#808080" not in s.prompts[0]
        assert s.cut_calls == 0 and s.trim_calls == 0
    finally:
        _clear()


# --- output -----------------------------------------------------------------

def test_output_png_and_sidecar_are_written():
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    try:
        with _Stubs():
            gen.main(["make", "-i", str(img), "--out-root", tmp])
        pngs = list((Path(tmp) / "make").glob("*.png"))
        jsons = list((Path(tmp) / "make").glob("*.json"))
        assert len(pngs) == 1 and len(jsons) == 1
        side = json.loads(jsons[0].read_text())
        assert side["schema"] == SCHEMA
        assert SCHEMA["subject"] in side["prompt"]
        assert side["model"] == "img/model"
        assert side["cost"] == 0.05
    finally:
        _clear()


def test_filename_carries_the_subject_slug():
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    try:
        with _Stubs():
            gen.main(["make", "-i", str(img), "--out-root", tmp])
        name = next((Path(tmp) / "make").glob("*.png")).name
        assert "launcher" in name
    finally:
        _clear()


def test_n_variants_write_n_files_with_distinct_seeds():
    tmp = tempfile.mkdtemp(); _env()
    try:
        with _Stubs(outcomes=[(b"A", 0.05), (b"B", 0.05), (b"C", 0.05)]) as s:
            code = gen.main(["make", "-t", "a coin", "-n", "3", "--out-root", tmp])
        assert code == 0
        assert len(list((Path(tmp) / "make").glob("*.png"))) == 3
        assert len(set(s.seeds)) == 3
    finally:
        _clear()


def test_dry_run_writes_nothing_and_makes_no_image_request():
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    try:
        with _Stubs() as s:
            code = gen.main(["make", "-i", str(img), "--dry-run", "--out-root", tmp])
        assert code == 0
        assert s.prompts == []                       # no generation
        assert not (Path(tmp) / "make").exists()     # not even a directory
    finally:
        _clear()


# --- failures ---------------------------------------------------------------

def test_analysis_failure_exits_one_and_generates_nothing():
    tmp = tempfile.mkdtemp(); _env()
    img = _image_file(tmp)
    err = gen.vision.AnalysisError("no JSON object found in the reply", raw="nope")
    try:
        with _Stubs(analyze_error=err) as s:
            code = gen.main(["make", "-i", str(img), "--out-root", tmp])
        assert code == 1
        assert s.prompts == []
        assert (img.parent / "ref.png.analysis-error.txt").read_text() == "nope"
    finally:
        _clear()


def test_one_failed_variant_still_writes_the_others():
    tmp = tempfile.mkdtemp(); _env()
    import orclient
    outcomes = [(b"A", 0.05), orclient.ApiError("HTTP 429", 429), (b"C", 0.05)]
    try:
        with _Stubs(outcomes=outcomes):
            code = gen.main(["make", "-t", "a coin", "-n", "3", "--out-root", tmp])
        assert code == 1                                            # something failed
        assert len(list((Path(tmp) / "make").glob("*.png"))) == 2    # the rest survived
    finally:
        _clear()


def test_missing_image_model_exits_cleanly():
    tmp = tempfile.mkdtemp()
    _clear()
    os.environ["SPRITEGEN_VISION_MODEL"] = "vis/model"
    try:
        with _Stubs() as s:
            code = gen.main(["make", "-t", "a coin", "--out-root", tmp])
        assert code == 1
        assert s.prompts == []
    finally:
        _clear()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all make tests passed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_make.py`
Expected: FAIL with `AttributeError: module 'gen' has no attribute 'slugify'`

- [ ] **Step 3: Add `make` to `gen.py`**

Add these imports at the top:

```python
import re
import time
```

Add `slugify` and `cmd_make` above `_add_endpoint_flags`:

```python
def slugify(text: str, limit: int = 40) -> str:
    """A filesystem-safe fragment of `text` for the output filename."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-")
    return s or "sprite"


def cmd_make(args):
    if not args.image and not args.text:
        print("error: give an image (-i), a text (-t), or both", file=sys.stderr)
        return 1

    try:
        pack = config.env_pack(
            base_url=args.base_url, model=args.model, transport=args.transport,
            vision_base_url=args.vision_base_url, vision_model=args.vision_model,
            out_root=Path(args.out_root),
        )
    except config.SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    image_bytes = None
    if args.image:
        image_path = Path(args.image)
        try:
            image_bytes = image_path.read_bytes()
        except OSError as exc:
            print(f"error: cannot read {image_path}: {exc}", file=sys.stderr)
            return 1

    schema = None
    if image_bytes is not None:
        try:
            schema, _raw = vision.analyze(pack, image_bytes, user_text=args.text)
        except vision.AnalysisError as exc:
            if exc.raw:
                dump = image_path.with_suffix(image_path.suffix + ".analysis-error.txt")
                try:
                    dump.write_text(exc.raw, encoding="utf-8")
                    print(f"error: {exc} (raw reply written to {dump})", file=sys.stderr)
                except Exception:
                    print(f"error: {exc}", file=sys.stderr)
            else:
                print(f"error: {exc}", file=sys.stderr)
            return 1
        except orclient.ApiError as exc:
            print(f"error: vision request failed: {exc}", file=sys.stderr)
            return 1
        body = vision.object_prompt(schema)
        slug = slugify(schema.get("subject") or args.text or "sprite")
    else:
        # Text only: nothing to analyse, so no vision call and no vision cost.
        body = args.text.strip()
        slug = slugify(args.text)

    prompt = body if args.no_cutout else f"{body} {config.BG_CLAUSE}"

    if schema is not None:
        print("analysis:")
        for field in vision.PROMPT_ORDER:
            value = (schema.get(field) if field in vision.SUBJECT_FIELDS
                     else (schema.get("style") or {}).get(field))
            if value:
                print(f"  {field:<9} {value}")
        print()
    print(f"prompt:\n{prompt}\n")

    if args.dry_run:
        print("dry run: nothing written")
        return 0

    out_dir = pack.out_dir
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"error: cannot create {out_dir}: {exc}", file=sys.stderr)
        return 1

    stamp = time.strftime("%Y%m%d-%H%M%S")
    spent = 0.0
    written = failed = 0

    for i in range(args.n):
        if spent >= args.max_cost:
            print(f"stopped: cost ceiling ${args.max_cost:.2f} reached")
            break
        suffix = f"-{i}" if args.n > 1 else ""
        name = f"{stamp}-{slug}{suffix}"
        try:
            png, cost, _raw = orclient.generate(
                pack, prompt, aspect_ratio=args.aspect_ratio,
                reference_png=image_bytes, seed=i,
            )
        except (orclient.ApiError, orclient.ImageMissing) as exc:
            print(f"[{name}] failed — {exc}", file=sys.stderr)
            failed += 1
            continue
        except Exception as exc:
            print(f"[{name}] failed — {type(exc).__name__}: {exc}", file=sys.stderr)
            failed += 1
            continue

        target = out_dir / f"{name}.png"
        try:
            if args.no_cutout:
                target.write_bytes(png)
            else:
                img = post.cut_background(png)
                img = post.trim_and_pad(img)
                img.save(target)
        except Exception as exc:
            raw_path = out_dir / f"{name}.raw.png"
            try:
                raw_path.write_bytes(png)
            except OSError:
                pass
            print(f"[{name}] post-processing failed — {exc} "
                  f"(raw kept as {raw_path.name})", file=sys.stderr)
            failed += 1
            continue

        sidecar = {
            "prompt": prompt, "schema": schema, "model": pack.model,
            "transport": pack.transport, "base_url": pack.base_url,
            "aspect_ratio": args.aspect_ratio, "seed": i, "cost": cost,
            "user_text": args.text, "reference": str(args.image) if args.image else None,
            "file": str(target),
        }
        try:
            (out_dir / f"{name}.json").write_text(
                json.dumps(sidecar, indent=2), encoding="utf-8")
        except OSError as exc:
            print(f"[{name}] warning: sidecar not written: {exc}", file=sys.stderr)

        print(f"[{name}] ok -> {target}")
        written += 1
        if cost:
            spent += cost

    print(f"\ndone: {written} written, {failed} failed  (${spent:.2f})")
    return 0 if failed == 0 and written > 0 else 1
```

Register the subparser in `main`, after the `analyze` parser:

```python
    make = subs.add_parser(
        "make", help="generate one sprite from an image, a text, or both")
    make.add_argument("-i", "--image", default=None, help="reference image")
    make.add_argument("-t", "--text", default=None,
                      help="what to make; overrides the image where they conflict")
    make.add_argument("-n", type=int, default=1, help="number of variants")
    make.add_argument("--aspect-ratio", default="1:1")
    make.add_argument("--no-cutout", action="store_true",
                      help="whole-image output: no backdrop, no alpha cut, no trim")
    make.add_argument("--dry-run", action="store_true",
                      help="print the analysis and prompt, generate nothing")
    make.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST,
                      help=f"USD ceiling (default {DEFAULT_MAX_COST})")
    _add_endpoint_flags(make)
    make.set_defaults(func=cmd_make)
```

Note `_add_endpoint_flags` already supplies `--base-url`, `--model`, `--transport`, `--vision-base-url`, `--vision-model` and `--out-root`, so `make` inherits all of them.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_make.py`
Expected: eighteen `ok  test_...` lines, then `all make tests passed`

- [ ] **Step 5: Run the whole suite**

Run: `python3 test_post.py && python3 test_config.py && python3 test_client.py && python3 test_build.py && python3 test_packwriter.py && python3 test_vision.py && python3 test_env.py && python3 test_make.py`
Expected: every suite prints its pass line

- [ ] **Step 6: Commit**

```bash
git add gen.py test_make.py
git commit -m "feat: add make, a pack-less one-shot sprite command"
```

---

### Task 5: `.env.example` and docs

**Files:**
- Create: `.env.example`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:** Consumes the finished CLI. Nothing consumes this task.

- [ ] **Step 1: Write `.env.example`**

```bash
# Copy to .env and fill in. .env is gitignored; .env.example is not.
# A real environment variable always wins over this file.

# --- image generation ---
SPRITEGEN_BASE_URL=https://openrouter.ai/api/v1
SPRITEGEN_API_KEY=sk-or-v1-...
SPRITEGEN_MODEL=black-forest-labs/flux.2-max
# images (OpenRouter) or chat (local OpenAI-compatible proxy)
SPRITEGEN_TRANSPORT=images

# --- image understanding (only needed for `make -i` and `analyze`) ---
# Omit any of these to reuse the image-generation endpoint above.
SPRITEGEN_VISION_BASE_URL=http://localhost:20128/v1
SPRITEGEN_VISION_API_KEY=sk-...
SPRITEGEN_VISION_MODEL=cc/claude-sonnet-5
```

- [ ] **Step 2: Add `.env` to `.gitignore`**

Append the line `.env` (the existing `*.toml.bak` entry stays). Verify `.env.example` is **not** ignored:

Run: `git check-ignore -v .env .env.example; echo "exit=$?"`
Expected: `.env` is listed as ignored; `.env.example` is not.

- [ ] **Step 3: Document `make` in `README.md`**

Add this section immediately after the "Use" section:

````markdown
## One-shot: `make`

No pack file. Give an image, a text, or both:

```bash
python3 gen.py make -i ref.png                      # reproduce what's in the image
python3 gen.py make -i ref.png -t "make it red"     # the text overrides the image
python3 gen.py make -t "a glossy blue button"       # text only
python3 gen.py make -i ref.png -n 3                 # three variants
```

With an image, it is analysed into nine fields — `subject`, `form`, `detail`, plus the six
style fields — and those become the prompt. Text given alongside an image **overrides it
field by field**: where your words conflict with what the model sees, your words win;
everything you did not mention comes from the image. The image is also sent to the
generator as a reference, so it matches shape as well as description.

Text alone makes no vision call at all — there is nothing to analyse and nothing to pay
for.

Output goes to `out/make/<timestamp>-<slug>.png` with a `.json` beside it recording the
schema, the full prompt, the model, the seed and the cost — `make` has no pack file, so
that sidecar is the only record of how a result was produced.

`--dry-run` prints the analysis and prompt and generates nothing. `--no-cutout` skips the
backdrop clause, the alpha cut and the trim, for full-bleed backgrounds and tiles.

### Configuration

`make` reads its endpoints from `.env` in the project root (copy `.env.example`). A real
environment variable always wins over the file, so `export SPRITEGEN_MODEL=...` still
overrides it for one run, and a CLI flag overrides both.

Unlike pack files — which hold the *name* of an env var and are meant to be shared —
`.env` holds real key values and is gitignored.

### When to use which

| goal | command |
|---|---|
| One object, quick iteration | `make` |
| A consistent set of 30 assets | `build` with a pack |
| Derive a pack's style from a reference | `analyze` |
````

Also add `test_env.py` and `test_make.py` to the Tests section's command.

- [ ] **Step 4: Verify the documented commands exist**

Run: `python3 gen.py make --help`
Expected: usage shows `-i/--image`, `-t/--text`, `-n`, `--aspect-ratio`, `--no-cutout`, `--dry-run`, `--max-cost`, and the endpoint flags

Run: `python3 gen.py build packs/hc_v1.toml --dry-run`
Expected: still 8 assets — the pack flow is untouched

- [ ] **Step 5: Commit**

```bash
git add .env.example .gitignore README.md
git commit -m "docs: document make and .env configuration"
```

---

## Notes for the implementer

**Do not "improve" these while implementing:**

- `.env` loading into `os.environ` via `setdefault` is the whole trick: it makes the
  existing `key_env` indirection work unchanged and keeps `export` winning. Returning a
  config dict instead would require special-casing every key lookup.
- `form` and `detail` must stay out of `style_prefix`. They describe one object; a pack
  prefix is applied to every asset.
- Text-only input must not call the vision endpoint. It costs money and there is nothing
  to analyse.
- `--dry-run` must not create the output directory. An empty directory is still a write.
- The sidecar JSON is not optional polish — `make` has no pack file, so it is the only
  provenance a result has.

**Deliberately not implemented** (from the spec's out-of-scope list): `make` writing pack
files, automatic object detection/cropping from a screenshot, per-asset references in the
pack flow, a variant-selection UI, and `.env` encryption.
