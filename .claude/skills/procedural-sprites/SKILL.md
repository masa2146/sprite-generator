---
name: procedural-sprites
description: Draw 2D game sprites, UI elements and tilesets procedurally with Python (Pillow + numpy) instead of an image-generation model — supersampled, vector-smooth, deterministic, instantly recolorable, and matched to a reference image when one exists. Use this whenever the user wants game assets, sprites, icons, buttons, badges, HUD elements, tiles, seamless/tileable pieces (tracks, pipes, borders), simple stylized characters (blob/jellybean mascots), sprite rotation frames, or wants assets that match a reference screenshot or a sprite brief (analysis.json), or complains that AI-generated game art is inconsistent, pixelated or off-style. Code beats diffusion for geometric and glossy-cartoon assets even when the user doesn't say "procedural".
---

# Procedural game sprites

Draw sprites with code, not with an image model. Computed gradients and curves
have no sampling noise, no style drift and no seams — which is why studios draw
UI and tile assets as vectors. This skill reproduces that quality in Python.

The skill gives you techniques and guardrails. It does NOT give you a style.
Style comes from the reference image, the brief, or the user's words — never
from a recipe in this skill. Invent whatever drawing technique the asset
needs; the recipes are geometry starters, not a look to conform to.

## When code wins, and when it loses

Code wins for: geometric UI (buttons, pills, badges, panels, slots), tiles and
anything tileable (tracks, pipes, walls — seams can be made mathematically
impossible), glossy/flat/candy-style pieces, simple mascots built from rounded
silhouettes (a jellybean body with ears is 20 lines), color variants (same
silhouette, swapped palette), and rotation/state frames (transform one master).

Code loses for: painterly texture, fur/hair, faces with expressions, complex
poses, photorealism. For those, generate one clean master with an image model,
then still do variants, rotations and recolors in code. Say so honestly rather
than producing a bad procedural approximation.

## Setup

Copy `scripts/sprite_lib.py` next to your working script and
`from sprite_lib import *`. It provides: `canvas/down` (supersampling),
`vgrad/rgrad/fill_grad` (gradients), `rr_mask/ellipse_mask/poly_mask/union`
(silhouettes), `sheen/inner_shadow/drop_shadow` (light accents),
`shade_relief/apply_relief` (volume lighting), `sweep_straight/sweep_corner/
piecewise_section` (tileables), `measure_section/dominant_colors`
(reference measurement), `rotations`, `contact_sheet` (QC), `side_by_side`
(reference comparison). Requires `pillow` and `numpy` only.

## If a reference exists, the reference is the boss

Most real jobs come with a reference: a screenshot crop, a competitor's asset,
or a sprite brief (e.g. an `analysis.json` with per-object `subject`/`form`/
`detail`/palette plus `refs/*.png` crops — consume that format directly; it is
the "what", you are the "how"). Then the loop is:

1. **Measure, don't guess.** `dominant_colors()` for palette,
   `measure_section()` for strip cross-sections, and read proportions off the
   crop (width/height ratios of each feature). Ignore the crop's pixelation
   and JPEG noise — that is capture artefact, not design.
2. **Draw** from those measurements.
3. **Compare:** `side_by_side(ref_crop, render, 'cmp.png')`, then actually
   view the file. Name the differences out loud — silhouette proportions,
   palette drift, light direction, highlight shape and position, edge
   softness — and fix the biggest one.
4. **Repeat** until the differences you can name are deliberate improvements
   (cleaner edges, higher res), not deviations. Two to four cycles is normal.

Without a reference, substitute the user's words for step 1 and still do the
look-and-fix cycles against their description.

## Soft-3D volumes: use the SDF renderer, not painted layers

When the reference reads as a real 3D object — a jelly cube with a visible
top face, a coin with a recessed face, tilted views of a piece — painted 2D
layers plateau at "almost right", because the reference's shading follows
true geometry. Switch to `scripts/sdf3d.py`: compose the shape from SDF
primitives (`rounded_box`, `sphere`, `capsule`, `cylinder_y`, `torus_y`) and
combinators (`union`, `smooth_union` for organic joins, `subtract` for
insets/recesses), then `render()` it — an orthographic raymarcher with
Lambert + Blinn specular + soft AO. Two rules make a set consistent: ONE
light vector and ONE camera tilt shared by every asset (declare them as
constants, like the palette), and warm-tint the specular (`spec_color`) for
toy/jelly materials instead of pure white. Geometry edits are one-liners —
a recessed coin face is `subtract(coin, thin_cylinder)` — so iterate with
the same side-by-side compare loop as everything else. Typical render cost
is a few seconds per asset; keep `OVERSAMPLE=3`.

## Characters: a routing ladder, not one technique

Characters are where procedural drawing has a real boundary — route by case,
in this order:

1. **Turnaround references already exist** (AI-generated or hand-drawn view
   sets): those ARE the masters. Don't redraw them — normalize (alpha, size,
   fill ratio) and derive recolors/variants in code.
2. **Blob-class character** (rounded body + simple appendages + flat kawaii
   face): the SDF lane handles it. Build the body with `smooth_union` of
   spheres/capsules, render each view with the `yaw` parameter (turntable —
   consistency across views is by construction). Two hard rules: facial
   features and inner-ear type markings go on as OBJECT-SPACE decals
   (`spots()` — they rotate and occlude with the head; screen-space stickers
   are exactly what breaks 3/4 and side views), and sub-part materials come
   from `part_color()`, not from geometry hacks.
3. **Full characters, animation, many poses**: leave 2D code. Best practice
   is a 3D master — generate a mesh from the front view with an image-to-3D
   model (e.g. Microsoft TRELLIS, open source) or model it once in Blender,
   then script the turnaround with headless bpy (camera yaw loop, toon
   shading, N direction renders). Deterministic view consistency is the
   whole point; recommend this lane honestly instead of stretching lane 2.
4. **Painterly/complex rendering**: diffusion generates the master; code
   still does variants, rotations, normalization.

## Light in 2D: build volume, don't stick stickers

A single global light direction per asset set, declared once as a constant.
For anything that should read as a 3D volume (candy pieces, buttons, mascots),
prefer `shade_relief`/`apply_relief`: it derives shading and a real specular
from a height field, so highlights curve around the form instead of floating
as flat sticker shapes. Reserve flat `sheen` bands for genuinely flat glossy
faces (glass bars, screens) — and clip them to the silhouette. `drop_shadow`
and `inner_shadow` still give grounding and recessed depth.

## The base method (always applies)

- **Art direction as data:** one palette dict + one light constant at the top
  of the file; every asset reads them. That is what makes thirty sprites look
  like one artist.
- **Silhouette first:** compose it from primitives with `union` (body + ears
  + tail...). Shade inside the silhouette; never paint outside it.
- **Render big, downsample once:** draw at `SS`× (default 4×), one final
  `down()` with Lanczos. Never resize twice, never draw at final size.
- **Look at what you drew.** Render → view the PNG → adjust. You are the art
  director. Never ship the first render unseen.
- **QC at in-game size:** `contact_sheet()` with sprites at roughly on-screen
  size over the game's backdrop color. A sprite that does not read at that
  size does not ship, however good it looks at 1024px. View the sheet too.

## Tileables: never draw both ends by hand

A straight piece and its corner join seamlessly only if they share the exact
same cross-section. Define the section once — `piecewise_section(bands)`, with
bands measured from the reference via `measure_section` — and sweep it:
`sweep_straight()` for runs, `sweep_corner()` for 90° turns (same section,
swept radially: the joint is identical by construction). Always render an
assembly image (corner + both straights composed) and view it to prove the
seam is invisible. If a joint shows, the pieces are not sharing one section
function — fix that, do not retouch pixels.

## Rotations, variants, states — derive, never redraw

- Rotation frames: `rotations(master, angles)`. One master, affine transforms.
- Color variants: same silhouette code, different palette entry — alpha
  channels stay byte-identical, so variants are guaranteed interchangeable.
- States (empty/full, on/off): one function with a flag, shared layout maths.

## Output conventions

PNG-32 with real alpha (no baked background). One Python file per asset set,
parameters (sizes, palette, radii, light) as named constants at the top — the
script is the deliverable as much as the PNGs: the user re-runs and tweaks it.
Save a `_qc_sheet.png` (and `cmp_*.png` comparisons when a reference exists)
beside the assets. If the user wants editable vectors, the same geometry can
be emitted as SVG — offer it, but PNG via Pillow is the default.

For worked geometry starters (candy tile, pill badge, coin bar, gear button,
blob mascot, ribbed capsule, conveyor/pipe set, nine-slice panels) read
[references/recipes.md](references/recipes.md) — adapt the closest one, and
restyle it to the reference; the recipe's look is not the target.
