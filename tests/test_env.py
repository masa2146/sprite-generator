"""`.env` loading tests. Run: python3 -m pytest tests/test_env.py"""
import os
import tempfile
from pathlib import Path

from spritegen.envfile import load_env, parse_env

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


def test_default_path_is_the_repo_root_not_the_package_dir():
    """The .env users are told to write sits beside .env.example at the repo
    root. Pointing the default inside spritegen/ meant a fully populated .env
    was silently never read, and `make` claimed no model was set."""
    import importlib.util

    from spritegen import envfile

    # Loaded fresh rather than read off the imported module: several tests
    # repoint envfile.DEFAULT_ENV_PATH at a temp file to isolate themselves and
    # do not put it back, so the live global says nothing about the default.
    spec = importlib.util.spec_from_file_location("_envfile_probe", envfile.__file__)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    root = Path(envfile.__file__).resolve().parent.parent
    assert probe.DEFAULT_ENV_PATH == root / ".env"
    assert probe.DEFAULT_ENV_PATH.parent.name != "spritegen"
    # .env itself is gitignored, but the example it is copied from is not.
    assert (root / ".env.example").is_file()


def test_missing_file_is_not_an_error():
    assert load_env(Path(tempfile.mkdtemp()) / "nope.env") == {}


def test_unreadable_file_is_not_an_error():
    d = Path(tempfile.mkdtemp())
    assert load_env(d) == {}          # a directory, not a file

