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
| `--base-url` / `--model` | override the spec for one run |

## Pointing at another endpoint

Any OpenAI-schema endpoint that supports `modalities: ["image", "text"]` on
`/chat/completions` works. Set it in the spec:

```toml
[api]
base_url = "http://localhost:8080/v1"
key_env  = ""     # empty: no Authorization header is sent
```

Precedence is CLI flag > spec file > environment (`SPRITEGEN_BASE_URL`,
`SPRITEGEN_MODEL`) > OpenRouter default. **API keys are read from environment
variables only** — the spec file holds the variable's *name*, never its value.

The `usage.cost` field is an OpenRouter extension. Against an endpoint that omits
it, `--max-cost` cannot be enforced; the tool warns once and continues rather
than pretending the ceiling is active.

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
python3 test_post.py && python3 test_config.py && python3 test_client.py && python3 test_build.py
```

No network, no rembg model download, runs in about a second.
