"""TOML pack writer tests. Run: python3 -m pytest tests/test_packwriter.py"""
import tempfile
import tomllib
from pathlib import Path

from spritegen.packwriter import PackWriteError, update_pack

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

BRACKET_PACK = PACK.replace(
    'prefix = """\nold prefix line one,\nold prefix line two\n"""',
    'prefix = """\nold prefix line one,\n[not a real section]\nold prefix line two\n"""',
)

STYLE_IN_VALUE_PACK = PACK.replace(
    '[pack]\nmodel = "bytedance-seed/seedream-4.5"',
    '[pack]\nmodel = "bytedance-seed/seedream-4.5"\nnotes = """\n[style]\n"""',
)


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
    from spritegen import packwriter
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


def test_restore_failure_after_a_bad_write_still_raises_pack_write_error():
    """If the modified write fails verification AND the restore write also
    fails (e.g. disk full mid-write, so both writes hit the same failure), a
    bare OSError must not propagate in place of PackWriteError — that message
    is the only thing telling the user their file is recoverable from .bak."""
    from spritegen import packwriter
    p = _pack_file()
    original = p.read_text()
    broken_write = Path.write_text

    def sabotage_write(self, text, *args, **kwargs):
        # Every write to `p` fails — the modified write AND the restore that
        # follows it, as a disk-full condition would do to both.
        if self == p:
            raise OSError("simulated disk full")
        return broken_write(self, text, *args, **kwargs)

    Path.write_text = sabotage_write
    try:
        update_pack(p, prefix="whatever")
        raise AssertionError("expected PackWriteError")
    except PackWriteError as exc:
        assert "did not verify" in str(exc)
        assert "restoring the original ALSO FAILED" in str(exc)
        assert str(p.with_suffix(".toml.bak")) in str(exc)
    finally:
        Path.write_text = broken_write


def test_no_op_call_is_rejected():
    p = _pack_file()
    try:
        update_pack(p)
        raise AssertionError("expected PackWriteError")
    except PackWriteError:
        pass


def test_pack_write_failure_restores_file():
    """If path.write_text fails, the original file must be restored."""
    from spritegen import packwriter
    p = _pack_file()
    original = p.read_text()
    broken_write = Path.write_text
    write_count = [0]

    def sabotage_write(self, text, *args, **kwargs):
        if self == p and text != original:
            write_count[0] += 1
            if write_count[0] == 1:  # First write (the modified text) fails
                raise OSError("simulated write failure")
        return broken_write(self, text, *args, **kwargs)

    Path.write_text = sabotage_write
    try:
        update_pack(p, prefix="whatever")
        raise AssertionError("expected PackWriteError")
    except PackWriteError as exc:
        assert "did not verify" in str(exc)
    finally:
        Path.write_text = broken_write
    assert p.read_text() == original


def test_existing_prefix_containing_a_bracket_line_is_replaced_cleanly():
    """When existing prefix contains [bracket], replace it without creating duplicate prefix keys."""
    p = _pack_file(BRACKET_PACK)
    update_pack(p, prefix="new prefix text")
    d = _load(p)
    assert d["style"]["prefix"].strip() == "new prefix text"
    assert [a["id"] for a in d["assets"]] == ["btn_play", "bg_sky"]
    assert p.read_text().count("prefix =") == 1     # not two prefix keys


def test_new_prefix_with_bracket_line_works():
    """A new prefix containing a line starting with [ should round-trip correctly."""
    p = _pack_file()
    tricky_prefix = "line one\n[this looks like a section but is not]\nline three"
    update_pack(p, prefix=tricky_prefix)
    d = _load(p)
    assert d["style"]["prefix"].strip() == tricky_prefix


def test_bracket_in_earlier_section_does_not_confuse_style_search():
    """When [style] appears in a value before the real [style], find the real one."""
    p = _pack_file(STYLE_IN_VALUE_PACK)
    update_pack(p, prefix="new prefix text")
    d = _load(p)
    assert d["style"]["prefix"].strip() == "new prefix text"
    assert [a["id"] for a in d["assets"]] == ["btn_play", "bg_sky"]
    assert p.read_text().count("prefix =") == 1     # not two prefix keys

