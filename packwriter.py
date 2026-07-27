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
_SECTION = re.compile(r"^\[\[?[A-Za-z0-9_.\-\"' ]+\]?\][ \t]*$", re.M)
# prefix = "..." or prefix = """...""" (multi-line), captured as one value.
_PREFIX = re.compile(
    r'^([ \t]*prefix[ \t]*=[ \t]*)("""(?:.|\n)*?"""|"(?:[^"\\]|\\.)*")',
    re.M,
)


def _mask_multiline_strings(text: str) -> str:
    """Blank out the contents of triple-quoted strings, preserving length and
    newlines, so a header regex cannot match a line inside a string value.

    No regex over raw text can distinguish `[foo]` as a section header from the
    same characters inside a prefix value — so the values are removed from
    consideration before the search rather than the pattern being tightened.
    """
    chars = list(text)
    for match in re.finditer(r'"""(?:.|\n)*?"""', text):
        for i in range(match.start() + 3, match.end() - 3):
            if chars[i] != "\n":
                chars[i] = "x"
    return "".join(chars)


def toml_string(value: str) -> str:
    """Encode a Python string as a TOML basic string.

    TOML basic strings use the same escapes as JSON, so json.dumps produces a
    valid one — and it handles embedded quotes, backslashes and newlines that
    would otherwise break the file.
    """
    return json.dumps(value)


_toml_string = toml_string      # existing internal callers


def prefix_literal(value: str) -> str:
    """Multi-line form when it is safe, quoted form when it is not."""
    if '"""' in value or "\\" in value:
        return toml_string(value)
    return f'"""\n{value.strip()}\n"""'


_prefix_literal = prefix_literal      # existing internal callers


def _section_body_span(text: str, header: str, masked: str) -> tuple[int, int] | None:
    """Character span of a section's body, from after its header to the next one.

    Args:
        text: Original TOML text
        header: Section header name (e.g., "style")
        masked: Text with multi-line strings blanked out; use for all regex searches
    """
    match = re.search(rf"^\[{re.escape(header)}\][ \t]*$", masked, re.M)
    if not match:
        return None
    start = match.end()
    nxt = _SECTION.search(masked, start)
    return start, (nxt.start() if nxt else len(text))


def _set_style_prefix(text: str, prefix: str) -> str:
    masked = _mask_multiline_strings(text)
    span = _section_body_span(text, "style", masked)
    literal = _prefix_literal(prefix)

    if span is None:
        # No [style] section. Insert one before the first [[assets]] — TOML
        # table order matters, and a [style] table after [[assets]] would be
        # parsed as belonging to the last asset.
        block = f"[style]\nprefix = {literal}\n\n"
        first_asset = re.search(r"^\[\[assets\]\]", masked, re.M)
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
        original = path.read_text(encoding="utf-8")
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

    try:
        backup.write_text(original, encoding="utf-8")
    except OSError as exc:
        raise PackWriteError(f"cannot write backup {backup}: {exc}")

    try:
        path.write_text(text, encoding="utf-8")
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
        try:
            path.write_text(original, encoding="utf-8")
        except OSError as restore_exc:
            # A partial write (disk full mid-write) is exactly the scenario
            # where the restore can fail for the same reason. Losing this
            # message would mean the user never learns `.bak` still holds
            # their pack — worse than the original verification failure.
            raise PackWriteError(
                f"write to {path} did not verify ({exc}); restoring the original "
                f"ALSO FAILED ({restore_exc}) — recover it from the backup at {backup}"
            )
        raise PackWriteError(
            f"write to {path} did not verify ({exc}); the original has been restored "
            f"(a copy is also at {backup})"
        )
