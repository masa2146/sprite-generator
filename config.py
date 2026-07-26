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
        prefix = self.style_prefix.strip()
        body = asset.prompt.strip()
        if asset.cutout:
            # This asset is a sprite with a subject: ask for a flat backdrop so
            # it can be cut out locally (see BG_CLAUSE).
            return f"{prefix} {body} {BG_CLAUSE}, aspect ratio {asset.aspect_ratio}"
        # This asset IS the whole image (a background, a seamless tile) — there
        # is nothing to isolate, so no backdrop clause and no cutout later.
        return f"{prefix} {body}, aspect ratio {asset.aspect_ratio}"

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
    )
