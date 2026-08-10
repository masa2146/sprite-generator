---
name: image-style
description: Analyse a reference image (or a user's own words, when there is no image) into a fixed style schema — render, camera, lighting, palette, linework, realism — plus what the image depicts, and turn them into a style prefix and a ready reproduction prompt. Use when the user shares an image and wants its look described or reproduced, or when a sprite job needs its style fields resolved for analysis.json.
---

# Image Style Analysis

Read whatever is available for a sprite job — a style image, one or more
reference images, the user's own words, any combination, or none of them —
and resolve the six style fields into a fixed schema, then turn that schema
into two pieces of prompt text. It does not crop, it does not draw, and it
does not write to disk; resolving the fields and reporting them is the whole
job.

## What to do

1. **Read what's given.** A style image and reference image(s) if present,
   and the user's own words always — words are an input even when there is no
   image at all.
2. **Resolve every field of the schema below**, one at a time, following the
   precedence order. If a field genuinely cannot be determined by anything —
   no words, no picture — say so rather than inventing detail; it gets
   stamped `varsayılan`.
3. **Print the blocks** in the Output section.

**Write nothing to disk and run no commands.** This skill only reads and
reports.

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

`camera` is read by two different consumers and only one of them wants it. The
procedural path turns it into the shared camera-tilt constant every asset in
the set renders with. The hand-generation prompt leaves it out, because that
prompt carries its own VIEW line per object and an angle in the style line
contradicts it on every view but front. Fill the field either way — dropping
it is `prompts.style_line`'s job, not yours.

## Precedence: the user's words win, field by field

This skill runs on every sprite job, with or without a style image. Each of
the six fields is resolved on its own:

    the user's words  >  the style image  >  the reference image(s)  >  default

A field the user did not touch keeps what the image said. If the picture is
jelly-cartoon and the user asked for pixel art, `render` and `realism` come
from the user while `camera`, `lighting`, `palette` and `linework` stay with
the picture. If the user only said "darker palette", only `palette` moves.

Record where each field came from — `kullanıcı`, `stil görseli`, `referans`,
`ölçüm`, `varsayılan` — and emit it as `style_source`. The review page prints
it beside each field, which is what makes an override that landed on the wrong
field visible instead of silent. A field nobody claimed and no picture shows
is stamped `varsayılan`; never invent one quietly.

## Output

### 1. Metrics table

The six style fields and the subject, one per row, with `style_source` beside
each style field.

### 2. Style prefix

The style fields joined in this exact order, comma-separated, subject excluded:

```
render, camera, lighting, linework, realism, palette
```

The order is fixed so that every job's style line carries the same axes in the
same sequence.

### 3. Reproduction prompt

`subject` first, then the style prefix — a ready prompt for regenerating this
image or a close sibling:

```
<subject>, <style prefix>
```

### 4. JSON

If the user asks for JSON, emit exactly this shape:

```json
{
  "style": {
    "render": "...", "camera": "...", "lighting": "...",
    "palette": "...", "linework": "...", "realism": "..."
  },
  "style_source": {
    "render": "kullanıcı", "camera": "stil görseli", "lighting": "stil görseli",
    "palette": "ölçüm", "linework": "varsayılan", "realism": "kullanıcı"
  }
}
```

This is the `style` block of `analysis.json`. `sprite-brief` writes it into
the file; on its own this skill still only reads and reports.
</content>
