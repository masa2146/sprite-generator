---
name: image-style
description: Analyse a reference image into a fixed style schema — render, camera, lighting, palette, linework, realism — plus what the image depicts, and turn them into a style prefix and a ready reproduction prompt. Use when the user shares an image and wants its look described, reproduced, or turned into a sprite-generator pack's style prefix.
---

# Image Style Analysis

Read a reference image and describe it in a fixed schema, then turn that schema
into two pieces of prompt text.

This produces the same schema as `gen.py analyze` in the sprite_generator
project, so output from either can be used in place of the other. Unlike the
CLI, this skill needs no API endpoint or key — you can see the image directly.

## What to do

1. **Read the image** the user points at.
2. **Fill in the schema below.** Every field. If something genuinely cannot be
   determined, say so in that field rather than leaving it blank or inventing
   detail.
3. **Print the three blocks** in the Output section.

**Write nothing to disk and run no commands.** This skill only reads and
reports. If the user wants the result written into a pack file, that is
`gen.py analyze`'s job — tell them the command rather than editing the file
yourself.

## Schema

Six style fields plus a subject:

| field | what it captures |
|---|---|
| `render` | render technique and material — *soft 3D render, glossy plastic material* |
| `camera` | angle and framing — *3/4 front view, slight high angle, centered* |
| `lighting` | direction, softness, shadows — *top-left key light, soft ambient occlusion, no harsh shadow* |
| `palette` | dominant colours as hex codes — *#FF6B4A #4ECDC4 #FFE66D* |
| `linework` | outlines and geometry — *no outline, rounded geometry, soft bevels* |
| `realism` | stylisation axis — *stylized cartoon, not photorealistic* |
| `subject` | what it depicts, phrased as a generation prompt would |

**`style` describes HOW the image looks and must never name the subject.**
`subject` describes WHAT it depicts. Keeping them apart matters: the style
fields get applied to a whole set of assets, and a subject that leaks into them
makes every asset drift toward that one object — the button starts looking like
the coin.

Give hex codes in `palette`, not colour names. "Warm orange" is not
reproducible; `#FF6B4A` is.

## Output

### 1. Metrics table

The six style fields and the subject, one per row.

### 2. Style prefix

The style fields joined in this exact order, comma-separated, subject excluded:

```
render, camera, lighting, linework, realism, palette
```

This is what goes in a pack's `[style] prefix`. The order is fixed so that
every pack's prefix carries the same axes in the same sequence.

### 3. Reproduction prompt

`subject` first, then the style prefix — a ready prompt for regenerating this
image or a close sibling:

```
<subject>, <style prefix>
```

If the user asks for JSON, emit exactly this shape so it matches the CLI:

```json
{
  "style": {
    "render": "...", "camera": "...", "lighting": "...",
    "palette": "...", "linework": "...", "realism": "..."
  },
  "subject": "..."
}
```

## Using it with the sprite generator

To write the result into a pack instead of copying by hand:

```bash
python3 gen.py analyze <image> --pack packs/<name>.toml
```

That writes the `[style] prefix`, copies the image to
`out/<pack>/style_bible.png`, and with `--add-asset <id>` appends the subject as
a new asset. Add `--dry-run` to preview without writing.
