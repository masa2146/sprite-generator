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

Hair, cloth folds and painted faces are not in this lane and will not be:
they need strands, simulation and texture, none of which an analytic SDF
gives. Say so plainly rather than shipping a plastic approximation — the
brief's prompt section exists for exactly these.

## Setup: the workspace and its venv

Everything a job produces lives under `sprites-generated/<set>/`:

    brief/    analysis.json · review.html · refs/
    scripts/  style.py · <asset>.py · sprite_lib.py + sdf3d.py + character_lib.py (copied here)
    out/      the sprites themselves
    qc/       _qc_sheet.png · cmp_<id>.png

Copy `scripts/sprite_lib.py`, `scripts/sdf3d.py` and `scripts/character_lib.py`
from this skill into the set's `scripts/` on the first run. Copied, not
imported from the skill: the set has to keep running months later, after the
skill has moved on. Once copied, `from sprite_lib import *` (and, for the
soft-3D/character lanes, `from sdf3d import *` and `from character_lib import
*`) in every asset script. Requires `pillow` and `numpy` only — exactly what
the venv below installs. Between them the three files provide:

`sprite_lib.py` — flat 2D drawing and delivery:
`canvas/down` (supersampling), `vgrad/rgrad/fill_grad` (gradients),
`rr_mask/ellipse_mask/poly_mask/union` (silhouettes), `sheen/inner_shadow/
drop_shadow` (light accents), `shade_relief/apply_relief` (volume lighting),
`sweep_straight/sweep_corner/piecewise_section` (tileables),
`measure_section/dominant_colors` (reference measurement), `rotations`,
`contour` (the set's dark outline, one width the whole way round — `width`
is in FINAL pixels, already converted from the internal supersample),
`silhouette` (flat-filled shape check), `readability` (dark/pale/coverage
pixel counts at on-screen size), `contact_sheet`/`qc_strip` (QC sheets),
`side_by_side` (reference comparison).

`sdf3d.py` — the orthographic SDF raymarcher (see "Soft-3D volumes" below
for how to use it): primitives `sphere/rounded_box/capsule/cylinder_y/
torus_y/torus_z` (`torus_z` stands facing the camera, unlike `torus_y` which
lies flat and vanishes at `tilt=0`) and `squash`/`scale_y` (non-uniform
scale of an SDF); combinators `union/smooth_union/subtract/intersect`;
`render()` (the raymarcher itself — pass `buffers=True` to also get back the
per-pixel `depth`/`normal` the march already computed, at the same final
size as the image); `interior_edges(depth, normal)` (lines where one part
crosses another, from those buffers — the one thing an alpha `contour()`
cannot draw); materials via `material()`/`surface()`/`Surface` (per-part
colour AND spec/shininess/rim/spec_color/spec_hard — see "Soft-3D volumes");
`spots()` (object-space decals, dispatches to `Surface.painted()` when the
base already carries per-part materials, so decals never collapse a body's
materials down to the scene-wide scalars); shading ramps `ramp_linear()`
(the default arithmetic response) and `ramp_bands(thresholds)` (cel
quantisation).

`character_lib.py` — the character-specific parts `sdf3d` has no opinion
about: `eye()` builds a socket/whites/iris/pupil/glint as real geometry
(returned as an `Eye` with `.socket`, `.parts`, `.decals`) and needs a
`head_center` matching whatever centre you later pass to `spots()`, so its
glint decal's direction is built in the same global frame `spots()`
measures angles in — not the eye's own `look` frame. `stroke(points)`
samples a curve (arc-length weighted) into a line of decals, for mouths and
brows. `mirrored(fn)` folds an SDF onto `|x|` for one-sided-to-symmetric
parts; `mirror_decals(decals)` does the same for a decal list. `light_for
(yaw, base_light)` rotates the set's light with the camera yaw, so a
turnaround's back view isn't lit from behind the object; `turnaround(shape,
views=VIEWS, ...)` renders one shape at every named yaw with the light
turned to match. `VIEWS` is the front/three_quarter/side/back naming
convention `turnaround` defaults to — an opinion about file naming, not
about anatomy.

Every Python run goes through the workspace venv — never the system
interpreter, whose packages are not this project's business:

```bash
[ -x sprites-generated/.venv/bin/python ] || {
  python3 -m venv sprites-generated/.venv
  sprites-generated/.venv/bin/pip install -q pillow numpy
}
sprites-generated/.venv/bin/python sprites-generated/<set>/scripts/<asset>.py
```

If the venv cannot be created, stop and show the user the two commands. Do not
fall back to `python3`.

## If a reference exists, the reference is the boss

Input comes in one of two shapes. Either `sprite-brief` handed you a
`sprites-generated/<set>/brief/` — read its `analysis.json` for the six style
fields, the per-object `subject`/`form`/`detail`/`views` and the measured
palette, and its `refs/*.png` for the crops — or the user described what they
want directly, in which case their words take the place of every field and
there are no crops to measure. Neither is required by the other: a brief is
convenient, not a prerequisite.

`style.render` and `style.realism` pick the drawing lane: soft-3D (the SDF
raymarcher), flat vector/glossy 2D, or a pixel grid. Read them before choosing
a technique — the style analysis is a code-path decision, not a mood note.

Most real jobs come with a reference: a screenshot crop, a competitor's asset,
or a sprite brief; it is the "what", you are the "how". Then the loop is:

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

## One art direction file, one subagent per asset

Write `scripts/style.py` yourself, before any asset exists:

```python
PALETTE  = {"hide": "#B4522E", "horn": "#E8E8EF", "metal": "#E3B505"}
LIGHT    = (-0.45, -0.75, 0.5)     # one vector for the whole set
CAMERA   = 12.0                    # degrees of tilt, shared by every asset
MATERIALS = {"hide": dict(spec=0.25, spec_color="#FFE9C7"),
             "horn": dict(spec=0.60, spec_color="#FFFFFF")}   # both are render() kwargs
CONTOUR  = 6                       # dark outline width at SS scale
SS       = 4                       # supersample factor
```

That file is what makes thirty sprites look like one artist, so it has exactly
one author. Then dispatch **one subagent per asset**, independents in parallel.
Each subagent:

1. writes `scripts/<asset>.py`, importing `style.py` — and nothing else of its own
2. runs it through the venv python
3. produces `out/<asset>.png`, plus `qc/cmp_<asset>.png` when a crop exists
4. **looks at what it drew**, names the differences out loud, fixes the biggest
5. repeats, two to four rounds
6. returns a short receipt and nothing else:

```
asset:   bull_totem
files:   scripts/bull_totem.py, out/bull_totem.png, qc/cmp_bull_totem.png
rounds:  3
remaining: horn tip 10% shorter than the reference — deliberate, invisible at game size
blocked:  -
style_request: -
```

**A subagent never edits `style.py`.** If an asset needs a colour or a light
the file does not have, it says so in `style_request` and you decide — a set
where every asset bent the shared constants to its own need is a set that no
longer looks like one game.

Rendered PNGs stay in the subagent's context. What comes back to you is the
receipt, which is the whole point: you close the job on one QC sheet rather
than on twenty images.

## Closing the set

Render `qc/_qc_sheet.png` with every sprite at roughly on-screen size over the
game's backdrop colour, and look at it. Judge the set, not the sprites:
palette, line weight, light direction. A sprite that is fine alone and wrong
beside its neighbours is not finished. Open a second, targeted round of
subagents for whatever fails, then hand over — naming any asset you could not
deliver and why.

## Soft-3D volumes: use the SDF renderer, not painted layers

When the reference reads as a real 3D object — a jelly cube with a visible
top face, a coin with a recessed face, tilted views of a piece — painted 2D
layers plateau at "almost right", because the reference's shading follows
true geometry. Switch to `scripts/sdf3d.py`: compose the shape from SDF
primitives (`rounded_box`, `sphere`, `capsule`, `cylinder_y`, `torus_y`) and
combinators (`union`, `smooth_union` for organic joins, `subtract` for
insets/recesses), then `render()` it — an orthographic raymarcher with
Lambert + Blinn specular + soft AO. Two rules make a set consistent: ONE
light vector and ONE camera tilt shared by every asset (declare them once in
`scripts/style.py`, like the palette), and warm-tint the specular (`spec_color`) for
toy/jelly materials instead of pure white. Geometry edits are one-liners —
a recessed coin face is `subtract(coin, thin_cylinder)` — so iterate with
the same side-by-side compare loop as everything else. Typical render cost
is a few seconds per asset; keep `OVERSAMPLE=3`.

Materials carry a part's colour AND its surface — `material(colour, spec=,
shininess=, rim=, spec_hard=)`, collected with `surface([(sdf, material), ...])`.
One rule governs how you build the shape underneath them: **blend softly only
within one material, and hard-union anything that needs its own.** The material
at a surface point is the nearest part's, which is exact for a hard union and
wrong inside a `smooth_union`'s blend band, where the surface belongs to
neither part.

`spec_hard=<0..1>` turns the highlight into the flat, hard-edged patch a cel
look wants; leaving it out keeps the continuous falloff. It also wants a much
LOWER `shininess` than the default 40 — the exponent used for the gate is
`shininess**2` (squared, on purpose — see the comment beside it in
`sdf3d.render`), so the default needs `N·H > 0.99957` to fire at all. Measured
on a 256px sphere with `spec_hard=0.5`: `shininess=40` gives a highlight
around 20px, `20` around 80px, `12` around 200px, `5` around 1000px. Set
`shininess` in roughly the 5–12 range when using `spec_hard`; the default
alone reads as "the feature does nothing." Banded diffuse is a ramp you hand
in: `ramp_bands([0.35, 0.75])` against the default `ramp_linear()`.

## Characters: a routing ladder, not one technique

Characters are where procedural drawing has a real boundary — route by case,
in this order:

1. **Turnaround references already exist** (AI-generated or hand-drawn view
   sets): those ARE the masters. Don't redraw them — normalize (alpha, size,
   fill ratio) and derive recolors/variants in code.
2. **Blob-class character** (rounded body + simple appendages + flat kawaii
   face): the SDF lane handles it, via `character_lib.py` (see "Setup" above
   for its full export list). Build the body with `smooth_union` of
   spheres/capsules, then render every named view at once with
   `turnaround(shape, views=VIEWS, ...)` rather than looping `yaw` by hand —
   it calls `light_for(yaw)` for you, so the light turns with the camera and
   the back view isn't lit from behind the object. Two hard rules: facial
   features and inner-ear type markings go on as OBJECT-SPACE decals
   (`spots()` — they rotate and occlude with the head; screen-space stickers
   are exactly what breaks 3/4 and side views), and sub-part materials come
   from `surface()`/`material()` (see "Soft-3D volumes" above), not from
   geometry hacks. `spots()` keeps those materials even when decalling a
   `Surface` that already has them — it hands the base to
   `Surface.painted()` rather than collapsing it to one colour.

   Five of the things that used to have to be checked by hand are now the
   library's: an eye is `eye()` and comes with a white, an iris and a pupil
   (pass it the SAME `head_center` you'll later pass to `spots()` — its
   glint decal's direction is built in that global frame, not the eye's own
   `look` direction, or it lands off the eye entirely); a mouth or brow is
   `stroke(points)` sampling a curve into decals instead of hand-placed
   tuples, and `mirrored()`/`mirror_decals()` give a one-sided part or decal
   list its other half; `surface()` gives hide, bone and metal their own
   gloss instead of one plastic sheen; the five-tap AO darkens a join so
   parts read as joined; and `contour()` holds one width the whole way
   round, in final pixels. What is still yours to get right is everything
   the library has no opinion about — proportion, where the muzzle sits,
   whether the plinth is smaller than the head, and whether the silhouette
   says what the thing is when you fill it black (`silhouette()` draws it;
   you decide).

   A brow that should shade the eye under it has to be GEOMETRY. A flat decal
   brow cannot cast anything, and `shadow=True` is what makes the contact
   darkening appear once it is.
3. **Full characters, animation, many poses**: leave 2D code. Best practice
   is a 3D master — generate a mesh from the front view with an image-to-3D
   model (e.g. Microsoft TRELLIS, open source) or model it once in Blender,
   then script the turnaround with headless bpy (camera yaw loop, toon
   shading, N direction renders). Deterministic view consistency is the
   whole point; recommend this lane honestly instead of stretching lane 2.
4. **Painterly/complex rendering**: the master comes from the prompt section
   of the brief — `sprite-brief`'s hand-generation path, pasted into an image
   model by hand — not from any integration in this skill; code still does
   variants, rotations, normalization once that master exists.

## Light in 2D: build volume, don't stick stickers

A single global light direction per asset set, declared once as a constant.
For anything that should read as a 3D volume (candy pieces, buttons, mascots),
prefer `shade_relief`/`apply_relief`: it derives shading and a real specular
from a height field, so highlights curve around the form instead of floating
as flat sticker shapes. Reserve flat `sheen` bands for genuinely flat glossy
faces (glass bars, screens) — and clip them to the silhouette. `drop_shadow`
and `inner_shadow` still give grounding and recessed depth.

## The base method (always applies)

- **Art direction as data:** one shared `scripts/style.py` — palette, light,
  materials — every asset script imports; a subagent never edits it. That is
  what makes thirty sprites look like one artist (see "One art direction
  file, one subagent per asset" above).
- **Silhouette first:** compose it from primitives with `union` (body + ears
  + tail...). Shade inside the silhouette; never paint outside it.
- **Render big, downsample once:** draw at `SS`× (default 4×), one final
  `down()` with Lanczos. Never resize twice, never draw at final size.
- **Look at what you drew.** Render → view the PNG → adjust. You are the art
  director. Never ship the first render unseen.
- **QC at in-game size:** `contact_sheet()` with sprites at roughly on-screen
  size over the game's backdrop color — this is what becomes `qc/_qc_sheet.png`
  when closing a set (see "Closing the set"). A sprite that does not read at
  that size does not ship, however good it looks at 1024px. View the sheet
  too.

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

PNG-32 with real alpha (no baked background), written to `out/<asset>.png`.
One Python file per asset, importing the shared `style.py` for palette/light/
materials and keeping only its own constants (sizes, radii, view list) at the
top — the script is the deliverable as much as the PNG: the user re-runs and
tweaks it. `qc/_qc_sheet.png` and `qc/cmp_<id>.png` comparisons live in `qc/`,
not beside the assets. If the user wants editable vectors, the same geometry
can be emitted as SVG — offer it, but PNG via Pillow is the default.

For worked geometry starters (candy tile, pill badge, coin bar, gear button,
blob mascot, ribbed capsule, conveyor/pipe set, nine-slice panels) read
[references/recipes.md](references/recipes.md) — adapt the closest one, and
restyle it to the reference; the recipe's look is not the target.
