---
name: sprite-brief
description: Turn one game screenshot into cropped reference images and paste-ready prompts for generating each sprite by hand in Gemini or ChatGPT. Use when the user shares a screenshot and wants its sprites extracted as prompts rather than generated through an API.
---

# Sprite Brief

Read a game screenshot, decide what the sprites are, and produce a folder the
user can generate from by hand: one crop per object, a copy of the screenshot,
and a structured prompt per object and view.

You see the image yourself — there is no vision API in this flow and it costs
nothing. That is also why you can afford to check your own work before asking
the user anything.

## What to do

### 1. Read the screenshot and the user's description

The user's own words are ground truth about what exists and where. An object
they name must appear in your list at the position they gave, even one you would
otherwise have merged into a neighbour or read as background. Their description
adds to your list — keep finding what they did not mention.

Where their description conflicts with the defaults below, follow the
description.

### 2. Write `analysis.json`

```json
{
  "style": "one line: render, lighting, linework, realism, then hex codes",
  "objects": [
    {
      "id": "conveyor_belt_frame",
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

Rules:

- `id` must match `^[A-Za-z0-9][A-Za-z0-9_-]*$`. It becomes a filename.
- `bbox` is `[x1, y1, x2, y2]` in pixels, top-left origin. It must contain the
  object's **full** extent — every ear, spike and overhang — plus a little
  margin. A box that clips is a failure; extra background is fine.
- `views` may only contain: `front`, `three_quarter`, `side`, `back`,
  `top_down`, `rotated_45`, `rotated_90`, `rotated_135`. One view for anything
  that does not move. Three or more for a character or anything the game
  animates. The `rotated_*` names turn the object in the picture plane instead
  of moving the camera — use those, not camera angles, for anything that spins
  or tumbles in flight. They cost nothing and never drift: a rotated frame is
  turned from the front frame by the script rather than generated, because a
  backend asked for three rotated frames returned three upright ones that
  differed only in finish, and even one that obeyed would be drawing the object
  afresh each time.
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
  progress bars. Give the pieces `flatten_rows = true` in the entry when they
  are one cross-section extruded sideways, and say in `subject` that the piece
  runs edge to edge.
- `style` must describe HOW the image looks and must never name an object.
- `style` must never name a camera angle or viewpoint — the script always adds
  its own `VIEW` line per object, and a style line that names an angle too
  will contradict it on any view but `front`.
- `blank` is boxes in **source-image** pixels, painted out of this object's own
  crop before anything sees it. Use it for whatever the padding dragged in and
  for whatever is printed on the object: a value on a body, a neighbouring
  tile, a label under a housing. Words cannot do this job — a ban that
  contradicts the picture loses every time — and this is the only lever that
  can. Boxes that belong to another listed object are handled automatically,
  in both directions; `blank` is for everything else.
- Numbers, letters and labels printed on an object are gameplay variables, not
  design — the game draws its own value over the finished sprite, and the
  prompt these fields feed bans text outright. Never put a glyph, a numeral or
  its value in `subject`, `form` or `detail`; the two halves of the prompt then
  contradict each other and the number comes back baked into the sprite.
  Describe the blank surface that carries it and say it is empty — "a slightly
  darker oval patch across the belly, left blank", not "a white 40 on the
  belly". An object that is nothing but text: describe its plate or badge as
  empty, and if it has no plate, leave it out.

### 3. Run the script

```bash
spritegen brief --image <screenshot> --analysis <analysis.json> \
                 --out-dir briefs/<name> --no-open
```

It validates the boxes, pads and writes the crops, blanks out of each crop
anything it frames, cleans the crops, copies the screenshot as
`refs/_style.png`, writes a labelled contact sheet, and renders `brief.html`.
Anything it rejects is printed with a reason — relay those to the user, never
drop them silently.

Cleaning is not cosmetic and is not optional. A crop lifted from a phone
screenshot carries the capture's pixel steps, the screen's top-to-bottom
lighting ramp and the phone's letterbox bars, and all three were measured
coming back *in the generated sprite* — as pixel art, as a piece dark at one
end, as black slabs. The prompt calls them capture artefacts and loses, because
a picture outargues a sentence. So the script strips the bars, flattens the
ramp, upscales past the stair-stepping, and reads each crop's real colours into
a `PALETTE` line in the prompt. That last part matters on its own: a vision
model called a conveyor's channel "pale lilac-white" when it is `#434375`, and
the sprite stayed pale until the measured value was in the prompt.

### 4. Check your own crops — always, without being asked

Read `<out-dir>/refs/_contact_sheet.png` and compare every cell against what it
claims to be. The question for each is: *does this crop contain exactly the
thing its label names, and nothing else that matters?*

A crop labelled `launch_ball` that shows a streak of twelve balls and some
bricks is a defect, not a detail. Flag those before asking the user anything.

### 5. Ask, in one round

Ask only where the answer changes a crop. Batch every question into one message.

| trigger | ask |
|---|---|
| the box holds several copies of the same shape | one unit, or the cluster? |
| the script reported the box contains other objects | whole, or a tileable piece? |
| the box covers more than a quarter of the screen | one object, or a composition? |
| the user said "empty" / "blank" / "without text" | which state should be drawn? |
| you could not find something they named | say so, and ask where it is |

Then edit `<out-dir>/analysis.json` — the copy the script wrote, not the
original — and run the script again with `--analysis` pointing at that copy.
Re-running is free and takes seconds, so iterate until the sheet is right.

### 6. Hand over

Tell the user:

- `<out-dir>/brief.html` holds one prompt per sprite
- upload **both** images from `<out-dir>/refs/` with **every** message: the
  object's crop and `_style.png`
- one message per sprite, and start a fresh chat per set

That last point matters and is not fussiness: the image model does not see the
chat history, so a screenshot uploaded once at the top does not reach later
generations. Every message must stand on its own. This was measured — the
version that sent no style image produced a generic grey object where the
version that sent one matched the game's palette.

### 7. Offer the local endpoint, once the brief is right

The brief above is the deliverable and does not depend on any of this. But the
same analysis, the same crops and the same prompt bodies also drive a local
generator, and if one is running the user can have both for no extra work.

Run:

```bash
spritegen check
```

Exit code 0 means reachable. **Only then**, ask once:

> The local sprite service is up. Want me to generate these through it as well?
> You keep the brief either way.

Do not ask when it is unreachable, and never start it yourself. If the answer
is yes, write the pack:

```bash
spritegen brief --image <screenshot> --analysis <out-dir>/analysis.json \
                 --out-dir <out-dir> --no-open --pack packs/<name>.toml
```

#### Build one asset at a time. Never the whole pack.

```bash
spritegen build packs/<name>.toml --jobs 1 --only <one asset id>
```

Always `--only`, always one id. A local GPU holds a diffusion model in memory
and dies unloading it; this backend crashed mid-batch repeatedly, and one run
lost twenty assets to a backend that had died on the first. `--jobs 1` alone is
not enough — it makes the requests sequential but still fires them back to back
with nothing checking in between.

So the loop is, per asset:

1. build that one asset
2. look at the image
3. if it is wrong, change **one** thing and rebuild that same asset
4. only when it is right, move to the next

Run `spritegen check` again after any failure. If it reports the backend gone,
stop the whole run and tell the user — every further build will fail and each
one takes minutes.

#### Fixing what comes back is your job, not the user's

Do not generate a set, list its faults and hand it over. A defect you can see
is a defect you can fix, and the user asked for sprites, not a report. Keep
going until each asset is either right or you have hit something the tool
genuinely cannot do — then say precisely which and why.

What actually moves a result, roughly in order of how often it is the answer:

- **Take it out of the crop, not the prompt.** A ban that contradicts the
  picture loses every time. Measured five separate ways: a brick field the
  loop's crop still showed, chevrons on a belt, sleepers across a track, a lane
  wide enough to decorate, a neighbouring tile row drawn in as a second course.
  The lever is `blank` in `analysis.json`, then re-run the brief.
- **One change per generation.** Two at once and a regression cannot be
  attributed. This is the rule that gets broken first and costs the most.
- **`--seed-offset N`** rerolls the same prompt. Reach for it before rewriting
  a prompt that is already correct — and before concluding an asset is
  impossible.
- **`structure_mode`**: `"edges"` traces the crop's outline and lets the prompt
  own colour and finish; `"copy"` clones the crop's render. A shape the prompt
  can describe wants edges; a surface treatment it cannot wants copy. Switching
  this is often what fixes an asset two prompt rewrites could not.
- **`palette_master = "<asset id>"`** when pieces of one object drift apart in
  colour. Build the best piece first, point the rest at it.
- **Check the box before blaming the model.** A 17px source object padded 12%
  reaches its neighbours; shrink or shift the box and the contamination goes.

#### Two failure modes this backend has, specifically

Watch for them on every asset, because they are quiet:

- **invented colour** — it recolours parts, adds a second hue, brightens the
  palette. A body that is one pink in the source came back pink head, blue
  body, cyan belly, orange feet.
- **isometric drift** — it tilts a flat sprite into a three-quarter box.

Both are banned in every prompt now, and the ban is not a guarantee. When
either shows up: reroll first, then try `structure_mode = "copy"` so the crop
carries the colour instead of the words.

#### Consistency is part of "done"

The set has to look like one game, not twelve. Before handing over, put the
finished sprites side by side and check they share a palette, a line weight and
a light direction. An asset that is fine alone and wrong beside its neighbours
is not finished — `palette_master` is the cheap fix.

## What not to do

- Do not generate images yourself, by hand or through any other tool. The
  script generates, or the user does.
- Do not run `build` without `--only` naming a single asset. A whole pack at
  once is how the backend dies and how twenty assets are lost at a stroke.
- Do not hand back a set of known-broken sprites as a finished report. Fix what
  you can see, and name only what you genuinely could not.
- Do not write a pack unless the user accepted the offer in step 7. Unasked,
  that is `spritegen extract`'s job on the paid path.
- Do not start, restart or install the local service, and do not offer it when
  `spritegen check` says it is down.
- Do not invent objects the screenshot does not contain.
- Do not silently drop anything — a rejected box, an unfound request, a
  question you decided not to ask.
