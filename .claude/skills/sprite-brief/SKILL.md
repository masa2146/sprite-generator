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
      "state": "optional — 'empty, without the object it normally holds'"
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
  `top_down`. One view for anything that does not move. Three or more for a
  character or anything the game animates.
- One entry per distinct sprite **shape**, not per copy on screen. Same shape in
  another colour is one entry — say so in `detail`. When a shape repeats, the
  box must enclose **one representative copy**, never all of them together.
- Default to the smallest reusable unit: one brick, not the brick field; one
  ball, not the trail of balls. This is the single most common way this flow
  goes wrong.
- `style` must describe HOW the image looks and must never name an object.
- `style` must never name a camera angle or viewpoint — the script always adds
  its own `VIEW` line per object, and a style line that names an angle too
  will contradict it on any view but `front`.
- Never write a label's text into `subject`, `form` or `detail`. The user
  generally wants HUD parts blank; text in the fields defeats the ban on text
  in the prompt.

### 3. Run the script

```bash
spritegen brief --image <screenshot> --analysis <analysis.json> \
                 --out-dir briefs/<name> --no-open
```

It validates the boxes, pads and writes the crops, copies the screenshot as
`refs/_style.png`, writes a labelled contact sheet, and renders `brief.html`.
Anything it rejects is printed with a reason — relay those to the user, never
drop them silently.

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

## What not to do

- Do not generate or download images. This skill produces prompts and crops.
- Do not write a TOML pack. That is `spritegen extract`'s job, on the paid path.
- Do not invent objects the screenshot does not contain.
- Do not silently drop anything — a rejected box, an unfound request, a
  question you decided not to ask.
