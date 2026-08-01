"""Spec loading and configuration resolution."""

from __future__ import annotations

import os
import re
import tomllib
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from . import envfile

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
BG_CLAUSE = ("isolated on flat solid #808080 neutral grey background, no shadow, "
             "no ground plane, no gradient, no scene, no props")

# A sprite prompt is labelled blocks rather than one sentence. The manual path
# (brief.py) was built that way after the run-on form lost its constraints: the
# clauses a model skips are the ones buried mid-sentence, and the measured
# failures were twelve balls instead of one and HUD labels that kept their text.
# The blocks live here, not in either caller, so the paid and manual paths
# cannot drift apart.
# Image 1 needs both halves of its instruction. "Reproduce THIS object" alone
# got the object reproduced faithfully -- including the fact that the crop is a
# 52x60 lift from a phone screenshot. The render came back as hard-outlined
# pixel art against a style prefix asking in so many words for "flat
# vector-style, no hard outlines": shown pixel art and told to reproduce it, the
# model reproduces pixel art, because image evidence beats a text style block.
# Smoothly upscaling the crop before sending it did not help -- the model
# resamples to its own latent resolution anyway, so what carries is the
# reference's content, not its pixel dimensions. Naming the artefacts is what
# separates identity from rendering.
REFERENCES_BLOCK = (
    "REFERENCES\n"
    "- Image 1 — the object to redraw. Take its IDENTITY from this and nothing\n"
    "  else: silhouette, proportions, colours, markings, features.\n"
    "  Do NOT take its rendering. Image 1 is a small low-resolution screen\n"
    "  capture; its pixellation, blocky stair-stepped edges and colour banding\n"
    "  are capture artefacts, not design. Redraw the object cleanly at full\n"
    "  resolution in the ART STYLE below.\n"
    "- Image 2 — the reference screenshot. Use it ONLY for art style, palette\n"
    "  and lighting. Do not copy any object from it."
)

def output_block(subject: str = "of the object described above") -> str:
    """The OUTPUT block. `subject` names the thing when the caller knows it.

    The count is what matters — an unqualified prompt produced twelve balls in
    one image — but naming it is stronger where a name exists. A pack's asset id
    ("coin-front") is not one, so the build path leans on the default, which
    points at the OBJECT line the prompt already carries.
    """
    return (
        "OUTPUT\n"
        f"- Exactly one {subject}, on its own. Not a set, not a grid, not a sheet.\n"
        "- Centred and complete, nothing touching or cut off at the edges.\n"
        "- Small even margin on all sides.\n"
        f"- {BG_CLAUSE}"
    )


FIXED_BANS = (
    "- any text, numbers, labels or logos\n"
    "- any other object from the reference image\n"
    "- more than one copy of the object"
)


def do_not_draw(exclude: str = "") -> str:
    """The DO NOT DRAW block: this asset's own exclusions, then the fixed bans.

    `exclude` is what a framing object's crop shows but must not be redrawn —
    see extract.exclusion_clause. Empty for an asset whose crop shows only
    itself, which is most of them.
    """
    lines = ["DO NOT DRAW"]
    if exclude and exclude.strip():
        lines.append(f"- {exclude.strip()}")
    lines.append(FIXED_BANS)
    return "\n".join(lines)


class SpecError(Exception):
    """The spec file is malformed or incomplete."""


@dataclass
class Asset:
    id: str
    prompt: str
    aspect_ratio: str = "1:1"
    cutout: bool = True  # sprite-with-subject vs. whole-image (background/tile)
    reference: Path | None = None   # per-asset reference image, resolved absolute
    # What this asset's reference image shows but the generated sprite must not
    # (a tray's crop necessarily shows what sits in the tray). Data, not prose,
    # so it can be hand-edited in the pack; full_prompt files it under DO NOT DRAW.
    exclude: str = ""


@dataclass
class Pack:
    name: str
    base_url: str
    key_env: str
    model: str
    style_prefix: str
    plate_prompt: str
    # The image the whole pack was derived from, sent as Image 2 beside each
    # asset's own crop. Text alone loses the palette: the manual path measured a
    # generic grey object from the version that sent no style image.
    style_reference: Path | None = None
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
        if not asset.cutout:
            # This asset IS the whole image (a background, a seamless tile) —
            # there is nothing to isolate, so no backdrop clause, no cutout
            # later, and none of the single-subject blocks below.
            return f"{prefix} {body}".strip()

        blocks = []
        # Only when two images actually go on the wire — build_one sends the
        # style image beside an asset's own reference, never instead of one.
        if asset.reference is not None and self.style_reference is not None:
            blocks.append(REFERENCES_BLOCK)
        blocks.append(body)
        if prefix:
            blocks.append(f"ART STYLE  {prefix}")
        blocks += [output_block(), do_not_draw(asset.exclude)]
        return "\n\n".join(blocks)

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


def _resolve_ref(raw_ref, spec_path: Path, where: str) -> Path | None:
    """A reference path from the spec, resolved relative to the spec file.

    Relative to the pack file, not the cwd: a pack carries its refs with it.
    """
    if raw_ref is None:
        return None
    if not isinstance(raw_ref, str) or not raw_ref.strip():
        raise SpecError(f"{where}: 'reference' must be a non-empty string")
    ref_path = Path(raw_ref)
    return (ref_path if ref_path.is_absolute() else spec_path.parent / ref_path).resolve()


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
    # load_pack already reads SPRITEGEN_BASE_URL/MODEL/TRANSPORT from
    # os.environ below — the same variables .env.example documents for
    # `make`. Loading .env here too means a user who sets one in .env gets
    # the same behaviour from both build and make, instead of make honouring
    # it and build claiming it isn't set.
    envfile.load_env()
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
                reference=_resolve_ref(row.get("reference"), spec_path, f"assets[{i}]"),
                exclude=row.get("exclude", ""),
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
        style_reference=_resolve_ref(style.get("reference"), spec_path, "[style]"),
        assets=assets,
        out_root=Path(out_root),
        transport=resolved_transport,
        default_aspect_ratio=default_ratio,
        vision_base_url=resolved_vision_base,
        vision_key_env=vision_key_env,
        vision_model=resolved_vision_model,
    )


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

    # Store the name of whichever key variable is actually populated. An
    # explicitly empty SPRITEGEN_API_KEY means "this endpoint needs no key",
    # matching what [api] key_env = "" already means in a pack. Treating empty
    # as unset instead put a keyless local endpoint out of reach of `make`: the
    # empty value is falsy, so OPENROUTER_API_KEY was demanded and generation
    # against a local server failed before it sent a single request.
    if "SPRITEGEN_API_KEY" in os.environ:
        key_env = "SPRITEGEN_API_KEY" if os.environ["SPRITEGEN_API_KEY"] else ""
    else:
        key_env = DEFAULT_KEY_ENV
    vision_key_env = (
        "SPRITEGEN_VISION_API_KEY"
        if os.environ.get("SPRITEGEN_VISION_API_KEY")
        else key_env
    )
    # Unlike load_pack's key_env, these are always one of three hardcoded
    # literals above — never untrusted TOML — so _check_key_env can never
    # fire here. No guard needed (load_pack's guard stays: it validates a
    # value read from the spec file).

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
