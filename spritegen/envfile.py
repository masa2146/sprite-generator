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

# The repo root, beside .env.example -- which is where .env.example's own header
# tells you to copy it. This used to point one level down, inside the package
# directory, so the file every user actually writes was never read: `make` would
# report "no image model" with a fully populated .env sitting right there. Packs
# hid it, because a pack carries base_url/model in its own [api] table.
DEFAULT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


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
