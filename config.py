"""Spec loading and configuration resolution."""

from __future__ import annotations

import os
import re
import tomllib
import zlib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_KEY_ENV = "OPENROUTER_API_KEY"
# "images" matches the default base_url (OpenRouter): it reaches far more image
# models than /chat/completions does there. A local OpenAI-compatible proxy
# needs transport = "chat".
DEFAULT_TRANSPORT = "images"
VALID_TRANSPORTS = ("images", "chat")

_VALID_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Hosted models do not emit reliable alpha, so we ask for a flat backdrop we can
# cut locally. Edge quality comes from this clause, not from the model.
# Neutral grey, not a chroma-key colour. rembg does alpha matting, not chroma
# keying: edge pixels come out as a blend of subject and backdrop, so a
# saturated backdrop bleeds visible colour into the cutout's edge. Measured on
# a synthetic sprite across four subject colours: #FF00FF left 610-2079 tinted
# edge pixels every time, #808080 left zero, with segmentation quality
# unchanged (rembg keys on salience, not colour contrast).
BG_CLAUSE = "isolated on flat solid #808080 neutral grey background, no shadow, no ground plane"


class SpecError(Exception):
    """The spec file is malformed or incomplete."""


@dataclass
class Asset:
    id: str
    prompt: str
    aspect_ratio: str = "1:1"
    cutout: bool = True  # sprite-with-subject vs. whole-image (background/tile)


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
    transport: str = DEFAULT_TRANSPORT
    default_aspect_ratio: str = "1:1"  # [defaults] aspect_ratio — style plates use this
    vision_base_url: str = ""
    vision_key_env: str = ""
    vision_model: str | None = None

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

    def vision_api_key(self) -> str | None:
        """Vision may use a different endpoint and key than image generation."""
        return os.environ.get(self.vision_key_env) if self.vision_key_env else None

    def full_prompt(self, asset: Asset) -> str:
        """Prompt wording only — no aspect-ratio text. How aspect ratio is
        carried is the transport's job: the images transport passes it as a
        structured field, the chat transport appends it to the prompt text."""
        prefix = self.style_prefix.strip()
        body = asset.prompt.strip()
        if asset.cutout:
            # This asset is a sprite with a subject: ask for a flat backdrop so
            # it can be cut out locally (see BG_CLAUSE).
            return f"{prefix} {body} {BG_CLAUSE}"
        # This asset IS the whole image (a background, a seamless tile) — there
        # is nothing to isolate, so no backdrop clause and no cutout later.
        return f"{prefix} {body}"

    def plate_full_prompt(self) -> str:
        return f"{self.style_prefix.strip()} {self.plate_prompt.strip()} {BG_CLAUSE}"

    def seed_for(self, asset_id: str) -> int:
        """Deterministic across processes, unlike builtin hash()."""
        return zlib.crc32(asset_id.encode()) % (2**31)


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


def load_pack(
    spec_path,
    base_url: str | None = None,
    model: str | None = None,
    transport: str | None = None,
    vision_base_url: str | None = None,
    vision_model: str | None = None,
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

    resolved_transport = (
        transport
        or api.get("transport")
        or os.environ.get("SPRITEGEN_TRANSPORT")
        or DEFAULT_TRANSPORT
    )
    if resolved_transport not in VALID_TRANSPORTS:
        raise SpecError(
            f"invalid transport {resolved_transport!r}: must be 'images' or 'chat' "
            "(set [api] transport, pass --transport, or set SPRITEGEN_TRANSPORT)"
        )

    # key_env may be explicitly "" to mean "this endpoint needs no key".
    key_env = api["key_env"] if "key_env" in api else DEFAULT_KEY_ENV
    _check_key_env(key_env, "[api]")

    vision = raw.get("vision", {})
    resolved_vision_base = (
        vision_base_url or vision.get("base_url") or resolved_base
    )
    resolved_vision_model = vision_model or vision.get("model")
    vision_key_env = vision["key_env"] if "key_env" in vision else key_env
    _check_key_env(vision_key_env, "[vision]")

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
                cutout=row.get("cutout", True),
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
        transport=resolved_transport,
        default_aspect_ratio=default_ratio,
        vision_base_url=resolved_vision_base,
        vision_key_env=vision_key_env,
        vision_model=resolved_vision_model,
    )
