---
name: sprite-brief
description: Turn a screenshot, a set of reference images, or a plain description into cropped references and a review page — the input a procedural sprite build or a hand-generated one both run from. Use when the user wants sprites from a picture or a description, before any drawing happens.
---

# Sprite Brief

Read what the user gave you — a screenshot, several separate pictures, one
clean reference, or nothing but words — and produce a folder that two
different ways of making the sprite both run from: `procedural-sprites`,
which writes Python that draws them, and hand generation in Gemini or
ChatGPT, which pastes the prompts.

You see the images yourself. There is no vision API in this flow and it costs
nothing, which is why you can afford to check your own work before asking the
user anything.

## What to do

### 1. Read the inputs

Look at every picture the user gave you, and read their words — words are an
input even when there is no picture at all. Their own description is ground
truth about what exists: an object they name must appear in your list at the
position they gave, even one you would otherwise have merged into a neighbour
or read as background. Their description adds to your list — keep finding
what they did not mention.

Where their description conflicts with a default below, follow the
description.

### 2. Resolve style with `image-style`

Invoke `image-style` with whatever style or reference images exist and the
user's own words. It hands back the six style fields — `render`, `camera`,
`lighting`, `palette`, `linework`, `realism` — and a `style_source` for each
one. Copy both straight into `analysis.json`; do not re-derive them here.
`image-style` does not crop and does not draw, and this skill does not
resolve style on its own — that division is deliberate, and rewriting it here
would let the two drift.

### 3. Decide the crop shape, per object

Cropping is a decision, not a default, and it has exactly three shapes:

| the object has | its reference is |
|---|---|
| a `bbox` | cut from its own `source`, or the shared `style_image` when it names none — the screenshot-holding-a-set case |
| a `source` but no `bbox` | that whole picture, cleaned but uncut |
| neither | carried by its description alone, no reference image at all |

The third row holds even when the analysis has a `style_image`: a shield icon
the user wants drawn in this screen's style, but that is not itself in the
screenshot, gets no picture. This is deliberate — the shared style image is
what boxes are cut from, not a default reference every object falls back to.
An object that genuinely wants the whole shared picture has to say so, by
naming it explicitly in its own `source`.

### 4. Write `analysis.json`

```json
{
  "style": {
    "render": "...", "camera": "...", "lighting": "...",
    "palette": "...", "linework": "...", "realism": "..."
  },
  "style_source": {
    "render": "kullanıcı", "camera": "stil görseli", "lighting": "stil görseli",
    "palette": "ölçüm", "linework": "varsayılan", "realism": "kullanıcı"
  },
  "style_image": "screenshot.png",
  "objects": [
    {
      "id": "conveyor_belt_frame",
      "source": "screenshot.png",
      "bbox": [30, 140, 690, 1010],
      "views": ["top_down", "three_quarter"],
      "subject": "what this object IS, briefly",
      "form": "its construction: how many parts, arrangement, proportions",
      "detail": "distinguishing smaller features",
      "state": "optional — 'empty, without the object it normally holds'",
      "flatten_rows": false,
      "blank": [[x1, y1, x2, y2]]
    }
  ]
}
```

Image paths (`style_image`, each object's `source`) resolve against
`analysis.json` itself, not against your working directory — write them
relative to wherever the file will live, or absolute.

Rules, carried over because every one of them was measured:

- `id` must match `^[A-Za-z0-9][A-Za-z0-9_-]*$`. It becomes a filename.
- `bbox` is `[x1, y1, x2, y2]` in the source image's own pixels, top-left
  origin. It must contain the object's **full** extent — every ear, spike and
  overhang — plus a little margin. A box that clips is a failure; extra
  background is fine.
- `views` may only contain: `front`, `three_quarter`, `side`, `back`,
  `top_down`, `rotated_45`, `rotated_90`, `rotated_135`. One view for anything
  that does not move. Three or more for a character or anything the game
  animates. The `rotated_*` names turn the object in the picture plane instead
  of moving the camera — use those, not camera angles, for anything that spins
  or tumbles in flight. They cost nothing and never drift: a rotated frame is
  turned from the front frame by the script rather than generated, because a
  generator asked for three rotated frames returned three upright ones that
  differed only in finish, and even one that obeyed would be drawing the
  object afresh each time.
- `views` is the only place a pose belongs. A rotation, an angle, a frame count
  or a sheet layout written into `subject`, `form` or `detail` asks one image to
  be four — each view is generated on its own.
- One entry per distinct sprite **shape**, not per copy on screen. Same shape in
  another colour is one entry — say so in `detail`. When a shape repeats, the
  box must enclose **one representative copy**, never all of them together.
- Default to the smallest reusable unit: one brick, not the brick field; one
  ball, not the trail of balls. This is the single most common way this flow
  goes wrong.
- **Check the unit against the scale.** Whatever makes an object recognisable
  has to fit in the generated picture. If it would land on less than roughly a
  tenth of the canvas, the generator cannot draw it and will substitute
  something it can. A conveyor loop boxed whole gave its track about 80px of a
  1024px image, and came back — every single time, under every wording — as a
  picture frame: the channel, the two lips, the highlight on each lip and the
  shadow they throw had nowhere to exist. Box one straight run and one corner
  instead and each fills its own canvas. Anything long and thin that rings or
  borders the playfield is this case: rails, belts, pipes, fences, walls,
  progress bars. Give the pieces `flatten_rows: true` in the entry when they
  are one cross-section extruded sideways, and say in `subject` that the piece
  runs edge to edge.
- `style` describes HOW the whole set looks and must never name an object —
  `image-style` already keeps this boundary; do not let a hand edit blur it.
- `style_source` should carry `image-style`'s own answer for all six fields.
  A key you leave out shows up as `belirtilmemiş`, which just means nobody
  claimed it — it is not itself a valid provenance, so do not rely on it in
  place of calling `image-style`.
- `blank` is boxes in **source-image** pixels, painted out of this object's own
  crop before anything sees it. Use it for whatever the padding dragged in and
  for whatever is printed on the object: a value on a body, a neighbouring
  tile, a label under a housing. Words cannot do this job — a ban that
  contradicts the picture loses every time — and this is the only lever that
  can. Boxes that belong to another listed object are handled automatically,
  in both directions; `blank` is for everything else. It only takes effect on
  an object that is cut from a box (the `bbox` shape from step 3) — a
  `source`-only whole picture is used as it is, `blank` and all. Putting one on
  a whole or text-only object is not rejected, but does nothing; the script
  says so in its notes rather than staying quiet about it.
- Numbers, letters and labels printed on an object are gameplay variables, not
  design — the game draws its own value over the finished sprite, and the
  prompt these fields feed bans text outright. Never put a glyph, a numeral or
  its value in `subject`, `form` or `detail`; the two halves of the prompt then
  contradict each other and the number comes back baked into the sprite.
  Describe the blank surface that carries it and say it is empty — "a slightly
  darker oval patch across the belly, left blank", not "a white 40 on the
  belly". An object that is nothing but text: describe its plate or badge as
  empty, and if it has no plate, leave it out.

### 5. Run the script

```bash
python3 .claude/skills/sprite-brief/scripts/brief.py \
    --analysis analysis.json --out-dir sprites-generated/<set>/brief --no-open
```

There is no `--image` flag — every image path lives inside the analysis and
resolves against it, so the file travels with its own pictures.

Plain `python3` needs `pillow` and `numpy` importable, and this step can run
before `procedural-sprites` has ever created the workspace venv that
guarantees them — a fresh machine, or the moment this skill is symlinked into
another project, tracebacks with `ModuleNotFoundError` here otherwise. If the
command above fails that way, fall back to the same workspace venv
`procedural-sprites` uses:

```bash
[ -x sprites-generated/.venv/bin/python ] || {
  python3 -m venv sprites-generated/.venv
  sprites-generated/.venv/bin/pip install -q pillow numpy
}
sprites-generated/.venv/bin/python .claude/skills/sprite-brief/scripts/brief.py \
    --analysis analysis.json --out-dir sprites-generated/<set>/brief --no-open
```

If the venv cannot be created either, stop and show the user the commands
above. Do not guess at a fix.

It validates every box, crops or copies each object's reference per the shape
decided in step 3, blanks out of each crop anything it frames or that `blank`
names, cleans the crops, and renders `<out-dir>/review.html`. Anything it
rejects is printed with a reason, and anything it silently ignored otherwise —
today, a `blank` on an object that was not cut from a box — is printed as a
note naming the object. Relay both to the user, never drop them.

Cleaning is not cosmetic and is not optional. A crop lifted from a phone
screenshot carries the capture's pixel steps, the screen's top-to-bottom
lighting ramp and the phone's letterbox bars, and all three were measured
coming back *in the generated sprite* — as pixel art, as a piece dark at one
end, as black slabs. The prompt calls them capture artefacts and loses,
because a picture outargues a sentence. So the script strips the bars,
flattens the ramp (or the row, for a `flatten_rows` piece), upscales past the
stair-stepping, and reads each crop's real colours into a `PALETTE` line in
the prompt. That last part matters on its own: a vision model called a
conveyor's channel "pale lilac-white" when it is `#434375`, and the sprite
stayed pale until the measured value was in the prompt.

Also written: `<out-dir>/analysis.json` — the copy the review loop re-runs
from, with every image path stamped absolute — `refs/<id>.png` for every
object that has a picture, `refs/_style.png` when the analysis has a
`style_image`, and `refs/_contact_sheet.png` when at least one object has a
crop.

Re-running is free and is the review loop: edit `<out-dir>/analysis.json`,
then run again with `--analysis` pointing at that same copy. The script
refuses to overwrite a `review.html` it did not itself produce from that
copy — pick a different `--out-dir`, or edit forward from the one it wrote.

### 6. Check your own crops — always, without being asked

Read `<out-dir>/refs/_contact_sheet.png` (when the run wrote one — an
analysis with no crops at all has nothing to check here) and compare every
cell against what it claims to be. The question for each is: *does this crop
contain exactly the thing its label names, and nothing else that matters?*

A crop labelled `launch_ball` that shows a streak of twelve balls and some
bricks is a defect, not a detail. Flag those before asking the user anything.

### 7. Ask, in one round

Ask only where the answer changes a crop or the brief. Batch every question
into one message.

| trigger | ask |
|---|---|
| the box holds several copies of the same shape | one unit, or the cluster? |
| the script reported the box contains other objects | whole, or a tileable piece? |
| the box covers more than a quarter of the screen | one object, or a composition? |
| the user said "empty" / "blank" / "without text" | which state should be drawn? |
| you could not find something they named | say so, and ask where it is |
| an object has neither `bbox` nor `source` and this is not obviously deliberate | describe it from words alone, or is there a picture for it? |

Then edit `<out-dir>/analysis.json` — the copy the script wrote, not the
original — and run the script again with `--analysis` pointing at that copy.
Re-running is free and takes seconds, so iterate until the sheet is right.

### 8. Hand over

Show the user `review.html` and say what is in it. Then ask **once**:

> Draw the sprites now, in code? (`procedural-sprites`)

If yes, invoke `procedural-sprites` with `sprites-generated/<set>/`. If no,
the prompt section of the same page is the hand-generation path: one message
per sprite, both pictures uploaded with every message, a fresh chat per set,
and the download cut with:

```bash
python3 .claude/skills/sprite-brief/scripts/cut.py <downloads> --out-dir sprites-generated/<set>/out
```

`cut.py` keys the flat backdrop out by default, floodfilling from the border
inward; pass `--glow` instead for a soft additive effect with no hard edge to
matte against.

Every message must carry both pictures: the image model does not see the chat
history, so a screenshot uploaded once at the top never reaches the later
generations and the style drifts. This was measured — the version that sent no
style image produced a generic grey object where the version that sent one
matched the game's palette.

## What not to do

- Do not generate images yourself, by hand or through any other tool. The
  brief is the deliverable; drawing them is `procedural-sprites`'s job or the
  user's, by hand, from the prompt page.
- Do not hand back a set of known-broken crops as a finished brief. Fix what
  you can see — adjust the box, add a `blank`, change the shape decision — and
  name only what you genuinely could not.
- Do not invent objects the inputs do not contain.
- Do not silently drop anything — a rejected box, an unfound request, a
  question you decided not to ask.
