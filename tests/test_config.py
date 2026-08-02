"""Spec parsing and precedence tests. Run: python3 -m pytest tests/test_config.py"""
import os
import tempfile
from pathlib import Path

from spritegen import config
from spritegen import envfile
# A Windows absolute path carries backslashes, which a raw TOML basic string
# would read as escapes — encode it the same way the pack writer does.
from spritegen.packwriter import toml_string

from spritegen.config import (
    BG_CLAUSE,
    DEFAULT_BASE_URL,
    DEFAULT_KEY_ENV,
    DEFAULT_TRANSPORT,
    SpecError,
    load_pack,
)

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
cutout = false
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


_ABSENT_ENV = Path(tempfile.mkdtemp()) / "absent.env"

_ENV_VARS = (
    "SPRITEGEN_BASE_URL", "SPRITEGEN_API_KEY", "SPRITEGEN_MODEL",
    "SPRITEGEN_TRANSPORT", "SPRITEGEN_VISION_BASE_URL",
    "SPRITEGEN_VISION_API_KEY", "SPRITEGEN_VISION_MODEL", "OPENROUTER_API_KEY",
    # SPEC_KEY / OMNIROUTE_API_KEY are [api]/[vision] key_env names used by
    # specs in this file; OMNIROUTE_API_KEY is also the one the README tells
    # users to export, so a test that fails only for users who followed the
    # README would be worse than no test.
    "SPEC_KEY", "OMNIROUTE_API_KEY",
)


def _clear_env():
    """Empty environment AND point envfile at a nonexistent .env.

    load_pack and env_pack both call envfile.load_env() now, so a real .env
    in the project root would otherwise leak into every test in this file.
    One helper for both entry points (rather than load_pack's and env_pack's
    own separate copies) means there's only one place that can go stale.
    """
    for k in _ENV_VARS:
        os.environ.pop(k, None)
    envfile.DEFAULT_ENV_PATH = _ABSENT_ENV


def test_pack_name_comes_from_spec_filename():
    _clear_env()
    assert load_pack(_write(FULL_SPEC)).name == "hc_v1"


def test_assets_parse_with_defaults_and_overrides():
    _clear_env()
    pack = load_pack(_write(FULL_SPEC))
    by_id = {a.id: a for a in pack.assets}
    assert by_id["btn_play"].aspect_ratio == "1:1"   # from [defaults]
    assert by_id["hero_idle"].aspect_ratio == "3:4"  # asset override
    assert by_id["btn_play"].cutout is True          # default
    assert by_id["bg_sky"].cutout is False           # asset override


def test_full_prompt_includes_prefix_asset_and_bg_clause_no_ratio():
    """aspect_ratio is no longer glued onto the prompt text — how it's carried
    is the transport's job (structured field for images, appended text for
    chat), not config's."""
    _clear_env()
    pack = load_pack(_write(FULL_SPEC))
    hero = {a.id: a for a in pack.assets}["hero_idle"]
    text = pack.full_prompt(hero)
    assert "ART STYLE  hypercasual asset, glossy" in text
    assert "round blue character" in text
    # Capitalised on its own bullet line (a lowercase fragment between two
    # capitalised bullets reads wrong); BG_CLAUSE itself is untouched.
    assert BG_CLAUSE[0].upper() + BG_CLAUSE[1:] in text
    assert "aspect ratio" not in text
    assert text.endswith(config.FIXED_BANS)


def test_a_sprite_prompt_carries_every_block_in_order():
    """The blocks are the point: a constraint buried in a run-on sentence is the
    one a model skips. REFERENCES is absent here — this pack sends one image."""
    _clear_env()
    pack = load_pack(_write(FULL_SPEC))
    text = pack.full_prompt({a.id: a for a in pack.assets}["hero_idle"])
    positions = [text.index(b) for b in ("ART STYLE", "OUTPUT", "DO NOT DRAW")]
    assert positions == sorted(positions)
    assert "REFERENCES" not in text
    assert "Exactly one" in text
    assert "any text, numbers, labels or logos" in text


def test_the_references_block_uses_the_backends_slot_names():
    """image1/image2 are what TextEncodeQwenImageEditPlus calls its inputs; a
    prompt that says "Image 1" instead names nothing the graph knows."""
    assert "image1" in config.REFERENCES_BLOCK
    assert "image2" in config.REFERENCES_BLOCK
    assert "Image 1" not in config.REFERENCES_BLOCK
    assert "Image 2" not in config.REFERENCES_BLOCK


def test_the_references_block_appears_only_when_two_images_are_sent():
    """build_one sends the style image beside an asset's own crop, never
    instead of one — so the block that names image1 and image2 must not
    promise a second image an asset without a crop will never get."""
    _clear_env()
    spec = _write(REF_SPEC)
    pack = load_pack(spec)
    by_id = {a.id: a for a in pack.assets}
    assert "REFERENCES" not in pack.full_prompt(by_id["with_ref"])

    pack.style_reference = spec.parent / "screenshot.png"
    assert "REFERENCES" in pack.full_prompt(by_id["with_ref"])
    assert "REFERENCES" not in pack.full_prompt(by_id["without_ref"])


def test_an_assets_exclude_is_filed_under_do_not_draw():
    _clear_env()
    pack = load_pack(_write(FULL_SPEC))
    hero = {a.id: a for a in pack.assets}["hero_idle"]
    assert "- the brick visible inside it" not in pack.full_prompt(hero)
    hero.exclude = "the brick visible inside it in the reference image"
    text = pack.full_prompt(hero)
    assert "DO NOT DRAW\n- the brick visible inside it" in text


def test_cutout_false_prompt_has_no_backdrop_clause():
    _clear_env()
    pack = load_pack(_write(FULL_SPEC))
    sky = {a.id: a for a in pack.assets}["bg_sky"]
    text = pack.full_prompt(sky)
    assert "#808080" not in text
    assert BG_CLAUSE not in text
    assert "seamless sky" in text


def test_plate_prompt_also_carries_prefix_and_bg_clause():
    _clear_env()
    text = load_pack(_write(FULL_SPEC)).plate_full_prompt()
    assert "hypercasual asset, glossy" in text
    assert "a button, an icon, a character" in text
    assert BG_CLAUSE in text


def test_output_block_asks_for_square_only_when_asked():
    """The build path carries aspect ratio as a structured field and has a 4:1
    status-bar asset, so its default must stay unaffected. brief.asset_prompt
    (the manual path, pasted into tools with no aspect-ratio field) opts in —
    "Square image." is the only thing asking for a square canvas there."""
    assert "Square image." not in config.output_block()
    assert "Square image." in config.output_block(square=True)


def test_precedence_cli_beats_spec_beats_env_beats_default():
    _clear_env()
    spec = _write(FULL_SPEC)
    assert load_pack(spec, base_url="http://cli/v1").base_url == "http://cli/v1"
    assert load_pack(spec).base_url == "https://spec.example/v1"

    bare = _write(MINIMAL_SPEC)
    try:
        os.environ["SPRITEGEN_BASE_URL"] = "http://env/v1"
        assert load_pack(bare).base_url == "http://env/v1"
    finally:
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


def test_transport_defaults_to_images():
    _clear_env()
    assert load_pack(_write(MINIMAL_SPEC)).transport == "images" == DEFAULT_TRANSPORT


def test_transport_precedence_cli_beats_spec_beats_env_beats_default():
    _clear_env()
    spec_chat = _write(FULL_SPEC.replace("[api]", '[api]\ntransport = "chat"'))
    assert load_pack(spec_chat, transport="images").transport == "images"
    assert load_pack(spec_chat).transport == "chat"

    bare = _write(MINIMAL_SPEC)
    try:
        os.environ["SPRITEGEN_TRANSPORT"] = "chat"
        assert load_pack(bare).transport == "chat"
    finally:
        del os.environ["SPRITEGEN_TRANSPORT"]
    assert load_pack(bare).transport == DEFAULT_TRANSPORT


def test_invalid_transport_is_rejected():
    _clear_env()
    bad = _write(MINIMAL_SPEC.replace("[pack]", '[api]\ntransport = "carrier-pigeon"\n[pack]'))
    try:
        load_pack(bad)
        raise AssertionError("expected SpecError")
    except SpecError as e:
        assert "images" in str(e) and "chat" in str(e)


def test_key_env_rejects_a_pasted_key_value():
    _clear_env()
    bad = _write(MINIMAL_SPEC.replace(
        "[pack]", '[api]\nkey_env = "sk-or-v1-abcdef1234567890"\n[pack]'
    ))
    try:
        load_pack(bad)
        raise AssertionError("expected SpecError")
    except SpecError as e:
        assert "key_env" in str(e)
        assert "name" in str(e).lower()


def test_key_env_rejects_a_value_with_characters_no_env_name_may_have():
    _clear_env()
    bad = _write(MINIMAL_SPEC.replace(
        "[pack]", '[api]\nkey_env = "not an env name!"\n[pack]'
    ))
    try:
        load_pack(bad)
        raise AssertionError("expected SpecError")
    except SpecError as e:
        assert "key_env" in str(e)


def test_key_env_rejects_a_non_string_value():
    """Finding 8: key_env = 42 used to crash with AttributeError ('int' object
    has no attribute 'startswith') instead of a clean SpecError — and cmd_build
    only catches SpecError, so this would have surfaced as a raw traceback."""
    _clear_env()
    bad = _write(MINIMAL_SPEC.replace("[pack]", '[api]\nkey_env = 42\n[pack]'))
    try:
        load_pack(bad)
        raise AssertionError("expected SpecError")
    except SpecError as e:
        assert "key_env" in str(e)


def test_api_key_read_from_named_env_var_only():
    _clear_env()
    pack = load_pack(_write(FULL_SPEC))
    assert pack.key_env == "SPEC_KEY"
    assert pack.api_key() is None
    try:
        os.environ["SPEC_KEY"] = "sk-test"
        assert pack.api_key() == "sk-test"
    finally:
        del os.environ["SPEC_KEY"]


def test_empty_key_env_means_no_key_at_all():
    _clear_env()
    spec = _write(MINIMAL_SPEC.replace("[pack]", '[api]\nkey_env = ""\n[pack]'))
    assert load_pack(spec).api_key() is None


def test_absent_key_env_uses_default():
    _clear_env()
    spec = _write(MINIMAL_SPEC)
    pack = load_pack(spec)
    assert pack.key_env == DEFAULT_KEY_ENV
    assert pack.api_key() is None
    try:
        os.environ["OPENROUTER_API_KEY"] = "sk-default-test"
        assert pack.api_key() == "sk-default-test"
    finally:
        del os.environ["OPENROUTER_API_KEY"]


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
    # crc32 is stable across processes; builtin hash() would not be — assert the
    # literal value (computed via `python3 -c "import zlib; print(zlib.crc32(b'btn_play') % (2**31))"`)
    # so a regression back to builtin hash() would actually be caught.
    assert pack.seed_for("btn_play") == 414956289
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


# --- env_pack ---------------------------------------------------------------

def test_env_pack_reads_the_environment():
    _clear_env()
    os.environ.update({
        "SPRITEGEN_BASE_URL": "http://env/v1",
        "SPRITEGEN_MODEL": "env/model",
        "SPRITEGEN_API_KEY": "sk-env",
        "SPRITEGEN_VISION_MODEL": "env/vision",
    })
    try:
        from spritegen.config import env_pack
        p = env_pack()
        assert p.base_url == "http://env/v1"
        assert p.model == "env/model"
        assert p.api_key() == "sk-env"
        assert p.vision_model == "env/vision"
        assert p.assets == []
    finally:
        _clear_env()


def test_env_pack_falls_back_to_openrouter_api_key():
    _clear_env()
    os.environ.update({"SPRITEGEN_MODEL": "m", "OPENROUTER_API_KEY": "sk-legacy"})
    try:
        from spritegen.config import env_pack
        assert env_pack().api_key() == "sk-legacy"
    finally:
        _clear_env()


def test_an_empty_api_key_means_the_endpoint_needs_none():
    """`SPRITEGEN_API_KEY=` is how a keyless local endpoint is declared, the
    same as [api] key_env = "" in a pack. Read as merely unset, it demanded
    OPENROUTER_API_KEY and `make` could not reach a local server at all."""
    _clear_env()
    os.environ.update({"SPRITEGEN_MODEL": "m", "SPRITEGEN_API_KEY": ""})
    try:
        from spritegen.config import env_pack
        pack = env_pack()
        assert pack.key_env == ""
        assert pack.api_key() is None      # and so no Authorization header
    finally:
        _clear_env()


def test_a_populated_api_key_is_still_preferred():
    _clear_env()
    os.environ.update({"SPRITEGEN_MODEL": "m", "SPRITEGEN_API_KEY": "sk-local"})
    try:
        from spritegen.config import env_pack
        assert env_pack().api_key() == "sk-local"
    finally:
        _clear_env()


def test_env_pack_vision_falls_back_to_the_main_endpoint_and_key():
    _clear_env()
    os.environ.update({
        "SPRITEGEN_BASE_URL": "http://main/v1",
        "SPRITEGEN_MODEL": "m",
        "SPRITEGEN_API_KEY": "sk-main",
    })
    try:
        from spritegen.config import env_pack
        p = env_pack()
        assert p.vision_base_url == "http://main/v1"
        assert p.vision_api_key() == "sk-main"
        assert p.vision_model is None
    finally:
        _clear_env()


def test_env_pack_cli_arguments_win():
    _clear_env()
    os.environ.update({"SPRITEGEN_MODEL": "env/model"})
    try:
        from spritegen.config import env_pack
        p = env_pack(model="cli/model", base_url="http://cli/v1",
                     vision_model="cli/vision")
        assert p.model == "cli/model"
        assert p.base_url == "http://cli/v1"
        assert p.vision_model == "cli/vision"
        # No --vision-base-url given: it falls back to the resolved base_url,
        # which is the CLI's, not the env's — untested until now.
        assert p.vision_base_url == "http://cli/v1"
    finally:
        _clear_env()


def test_env_pack_without_a_model_is_an_error():
    _clear_env()
    from spritegen.config import env_pack
    try:
        env_pack()
        raise AssertionError("expected SpecError")
    except SpecError as exc:
        assert "SPRITEGEN_MODEL" in str(exc)


def test_env_pack_rejects_an_invalid_transport():
    _clear_env()
    os.environ.update({"SPRITEGEN_MODEL": "m", "SPRITEGEN_TRANSPORT": "carrier-pigeon"})
    try:
        from spritegen.config import env_pack
        env_pack()
        raise AssertionError("expected SpecError")
    except SpecError as exc:
        assert "transport" in str(exc)
    finally:
        _clear_env()


def test_env_pack_defaults_transport_and_base_url():
    _clear_env()
    os.environ.update({"SPRITEGEN_MODEL": "m"})
    try:
        from spritegen.config import env_pack
        p = env_pack()
        assert p.transport == DEFAULT_TRANSPORT
        assert p.base_url == DEFAULT_BASE_URL
    finally:
        _clear_env()


def test_env_pack_ignores_a_dot_env_when_the_environment_is_explicit():
    """A .env must not override a variable the caller set."""
    _clear_env()
    d = Path(tempfile.mkdtemp())
    envpath = d / ".env"
    envpath.write_text("SPRITEGEN_MODEL=from-file\n", encoding="utf-8")
    envfile.DEFAULT_ENV_PATH = envpath
    os.environ["SPRITEGEN_MODEL"] = "from-environment"
    try:
        from spritegen.config import env_pack
        assert env_pack().model == "from-environment"
    finally:
        _clear_env()


# --- per-asset reference ----------------------------------------------------

REF_SPEC = """
[pack]
model = "m/model"
[style]
prefix = "p"
[[assets]]
id = "with_ref"
prompt = "q"
reference = "refs/thing.png"
[[assets]]
id = "without_ref"
prompt = "q2"
"""


def test_reference_resolves_relative_to_the_pack_file():
    _clear_env()
    spec = _write(REF_SPEC)
    pack = load_pack(spec)
    by_id = {a.id: a for a in pack.assets}
    assert by_id["with_ref"].reference == (spec.parent / "refs" / "thing.png").resolve()


def test_reference_is_none_when_absent():
    _clear_env()
    by_id = {a.id: a for a in load_pack(_write(REF_SPEC)).assets}
    assert by_id["without_ref"].reference is None


def test_an_absolute_reference_is_not_joined_to_the_pack_dir():
    """Absolute means absolute — it must not be resolved relative to the pack.

    The absolute path is built from a real temp directory rather than written
    as a "/tmp/..." literal: on Windows a leading slash with no drive letter is
    a *rooted* path, not an absolute one, so the literal exercised the joining
    branch on that platform and asserted a drive letter that came from the cwd.

    Both branches call .resolve(), so the expected value is resolved too; on
    macOS /tmp is a symlink to /private/tmp and an unresolved literal would not
    match either.
    """
    _clear_env()
    absolute = Path(tempfile.mkdtemp()).resolve() / "abs" / "thing.png"
    spec = _write(REF_SPEC.replace('"refs/thing.png"',
                                   toml_string(str(absolute))))
    ref = {a.id: a for a in load_pack(spec).assets}["with_ref"].reference
    assert ref == absolute
    assert spec.parent not in ref.parents      # the real invariant: no join happened


def test_style_reference_resolves_relative_to_the_pack_file():
    _clear_env()
    spec = _write(REF_SPEC.replace('prefix = "p"',
                                   'prefix = "p"\nreference = "refs/_style.png"'))
    pack = load_pack(spec)
    assert pack.style_reference == (spec.parent / "refs" / "_style.png").resolve()


def test_style_reference_is_none_when_absent():
    _clear_env()
    assert load_pack(_write(REF_SPEC)).style_reference is None


def test_reference_does_not_have_to_exist_at_load_time():
    """Loading must not require the file — build reports a missing one per asset."""
    _clear_env()
    pack = load_pack(_write(REF_SPEC))
    assert pack.assets[0].reference is not None      # no exception, no existence check

