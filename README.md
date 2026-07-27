# Sprite Generator

Turns a TOML list of prompts into Unity-ready RGBA sprite PNGs, keeping the whole
set visually consistent by sending a locked style-reference image with every request.

## Install

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY=sk-...
```

Python 3.11 or newer. The first run downloads the `birefnet-general` background
removal weights to `~/.u2net/` (a few hundred MB, once).

## Use

If you already have a reference image, skip `init`/`pick` entirely — analyse it
instead. That writes the style prefix *and* locks the image as the style bible,
saving the four style-plate generations:

```bash
python3 gen.py analyze ref.png --pack packs/hc_v1.toml
```

```bash
# 1. Generate four candidate style plates and open them as a contact sheet
python3 gen.py init packs/hc_v1.toml

# 2. Lock the one you like as this pack's style bible
python3 gen.py pick packs/hc_v1.toml 2

# 3. Generate everything
python3 gen.py build packs/hc_v1.toml
```

Output lands in `out/<pack>/`: one RGBA PNG per asset plus `manifest.json`.

Useful flags:

| flag | effect |
|---|---|
| `--dry-run` | print every prompt and the estimated cost, make no requests |
| `--only id1,id2` | regenerate just these assets |
| `--max-cost 2.00` | stop before exceeding this USD total (default 5.00) |
| `--base-url` / `--model` / `--transport` | override the spec for one run |

## Transport: `images` vs `chat`

Two HTTP transports talk to two different endpoints:

| transport | endpoint | notes |
|---|---|---|
| `images` (default) | `POST {base_url}/images` | OpenRouter-specific. `aspect_ratio` and `seed` are structured JSON fields, and `input_references` carries up to 14 reference images. |
| `chat` | `POST {base_url}/chat/completions` | Any OpenAI-schema endpoint with `modalities: ["image", "text"]`. The aspect ratio is appended to the prompt text since there is no structured field for it. |

**The default is `images`**, matching the default `base_url`
(`https://openrouter.ai/api/v1`). Measured against the live API, `/images`
reaches far more OpenRouter image models than `/chat/completions` does —
including models whose `output_modalities` is `["image"]` only, which
`/chat/completions` 404s on. If you point `base_url` at a **local
OpenAI-compatible proxy**, set `transport = "chat"` — those proxies typically
only speak the chat surface.

```toml
[api]
transport = "chat"
base_url  = "http://localhost:8080/v1"
key_env   = ""     # empty: no Authorization header is sent
```

Set it with `[api] transport` in the spec, `--transport`, or the
`SPRITEGEN_TRANSPORT` env var. Precedence is CLI flag > spec file > environment
(`SPRITEGEN_BASE_URL`, `SPRITEGEN_MODEL`, `SPRITEGEN_TRANSPORT`) > default. An
unrecognised value fails immediately at load time rather than as a confusing
404 later.

**API keys are read from environment variables only** — the spec file's
`key_env` holds the variable's *name*, never its value. A `key_env` that looks
like a pasted key (starts with `sk-`, or contains a character no environment
variable name may contain) is rejected at load time.

The `usage.cost` field is an OpenRouter extension. Against an endpoint that omits
it, `--max-cost` cannot be enforced; the tool warns once and continues rather
than pretending the ceiling is active.

## Analysing a reference image

```bash
python3 gen.py analyze <image> --pack <spec.toml> [--add-asset <id>] [--dry-run]
```

Sends the image to a vision model and extracts six style fields — render,
camera, lighting, palette, linework, realism — plus what the image depicts.
The style fields become the pack's `[style] prefix`; the image is copied to
`out/<pack>/style_bible.png`; with `--add-asset <id>` the detected subject is
appended as a new asset. `--dry-run` prints everything and writes nothing.
`analyze` also accepts the same endpoint override flags as the other
subcommands — `--base-url`, `--model`, `--transport`, `--vision-base-url`,
`--vision-model`, `--out-root`.

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

Omit the section to reuse `[api]`'s endpoint and key. `base_url` and `key_env`
each fall back on their own, so you can override just one.

**`model` is the exception: it has no fallback.** `[api]` has no model, and
`[pack] model` is deliberately not inherited — that is the image-generation
model, which is the wrong kind of model to describe a picture. Set `[vision]
model` or pass `--vision-model`; without one, `analyze` stops with a clear
error and the other commands are unaffected.

Precedence: `--vision-base-url` > `[vision] base_url` > `[api] base_url`, and
`--vision-model` > `[vision] model` (no further fallback).

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

## Why the grey backdrop

Hosted image models do not reliably emit an alpha channel — asked for
transparency, they tend to *paint* a checkerboard. So every prompt requests a flat
`#808080` background and alpha is cut locally with rembg. Edge quality comes from
that clause, not from the model.

**Why neutral grey and not a chroma-key colour.** rembg does alpha *matting*, not
chroma keying: the pixels along a cutout's edge come out as a blend of subject and
backdrop, so a saturated backdrop bleeds visible colour into that edge. Measured on
a synthetic sprite across four subject colours (teal, white, grey, gold), a
`#FF00FF` backdrop left 610–2079 tinted edge pixels every time — a visible purple
rim — while `#808080` left zero. Segmentation quality was identical in both cases,
including a grey subject on the grey backdrop, because rembg keys on salience
rather than colour contrast. If you ever do see a rim, changing this colour in
`config.BG_CLAUSE` is the first thing to try.

This only applies to assets that *have* a subject to isolate. Set `cutout = false`
on an asset that IS the whole image — a full-bleed background, a seamless tile —
and the backdrop clause, background removal, and trim/pad are all skipped; the
model's output is saved as-is. `cutout` defaults to `true`.

## Unity import

Set on each imported sprite: Texture Type `Sprite (2D and UI)`, `Alpha Is
Transparency` checked, Mesh Type `Tight`. Generating `.meta` files automatically
is not implemented.

## Tests

```bash
python3 test_post.py && python3 test_config.py && python3 test_client.py && python3 test_build.py && python3 test_packwriter.py && python3 test_vision.py
```

No network, no rembg model download, runs in about a second.
