# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
python3 -m pytest                                       # whole suite: no network, no model download, ~3s
python3 -m pytest tests/test_prompts.py -k style_line    # one file / one test

python3 .claude/skills/sprite-brief/scripts/brief.py \
    --analysis analysis.json --out-dir sprites-generated/<set>/brief --no-open

python3 .claude/skills/sprite-brief/scripts/cut.py <downloads> --out-dir sprites-generated/<set>/out
```

`pyproject.toml` holds only pytest settings — there is no package and no
install step anywhere in this repo. `tests/conftest.py` puts
`.claude/skills/sprite-brief/scripts` on `sys.path` itself, so a test imports
the exact modules the skill runs, not a copy. No linter or formatter is
configured.

## Architecture

Three Claude Code skills under `.claude/skills/`, no package, no CLI:

- **`sprite-brief/`** (`SKILL.md` + `scripts/brief.py`, `crops.py`,
  `refclean.py`, `prompts.py`, `cut.py`) — turns a screenshot, a set of
  images, or plain words into `analysis.json`, cropped `refs/`, and
  `review.html`.
- **`image-style/`** (`SKILL.md` only, no scripts) — resolves the six style
  fields. `sprite-brief` calls it on every job; it never runs standalone in
  the pipeline.
- **`procedural-sprites/`** (`SKILL.md` + `scripts/sprite_lib.py`,
  `sdf3d.py`, `references/recipes.md`) — draws the sprites a brief describes.
  Its `sprite_lib.py`/`sdf3d.py` get *copied*, not imported, into each
  generated set's own `scripts/`, so the set keeps running months after the
  skill has moved on.

Chain: `image-style` resolves the look → `sprite-brief` decides each object's
crop shape, cleans it, measures its real palette, and writes `analysis.json` +
`review.html` → either `procedural-sprites` draws from that file in Python, or
the user pastes `review.html`'s prompt blocks by hand and cuts the downloads
with `cut.py`. Both drawing paths read the same `analysis.json`; nothing
before that split belongs to one generation method more than the other.

Everything a job produces lives under `sprites-generated/<set>/` (gitignored):
`brief/` (`analysis.json` + `review.html` + `refs/`), `scripts/` (`style.py` +
one script per asset), `out/`, `qc/`.

## Invariants worth knowing before editing

- **The prompt text has one source: `prompts.py`.** `review.html`'s prompt
  section and the hand-generation path both call `prompts.asset_prompt` and
  read the same block strings — `BG_CLAUSE`, `FIXED_BANS`, `VIEW_POOL`. A
  second copy of any of that wording is how the two paths drift apart from
  each other; the failures the blocks guard against (twelve balls in one
  image, HUD labels that kept their text) were measured once and must not be
  measured again. The `REFERENCES` block itself calls the crop "Picture 1"
  and the style image "Picture 2" — the words the model actually reads before
  it tokenises the prompt, not a graph tool's socket name.
- **Nothing is ever dropped silently.** A rejected box (`crops.reject_reason`)
  is printed with its reason, never just skipped. An object the user named
  but the brief could not find gets asked about, not omitted. A `blank`
  written on an object that was not cut from a box does nothing — and
  `brief.py` says so as a note, rather than looking accepted while quietly
  doing nothing.
- **Measured colour beats described colour.** `refclean.palette` reads a
  crop's real colours by quantizing it, because a vision model once called a
  conveyor's channel "pale lilac-white" when it is `#434375` — the sprite
  stayed pale until the measured hex was in the prompt instead of the
  description.
- **Cropping is a decision with three shapes** (`crop_mode` in `brief.py`): a
  `bbox` is cut from its own `source` or the shared `style_image`; a `source`
  alone is used whole; neither means the object is carried by words with no
  picture at all. Containment between two boxes (`crops.find_contents`) is
  judged only within one source image — two boxes in two different
  screenshots have no spatial relationship to compare.
- **`prompts.style_line` drops `camera` from the prompt on purpose.** The
  hand-generation prompt carries its own `VIEW` line per object, and an angle
  named in the style line would contradict it on every view but `front`. The
  field is still resolved and still stored in `analysis.json` — the
  procedural path reads that same field as the shared camera-tilt constant
  for the whole set. Dropping it is `style_line`'s job alone; nothing
  upstream should pre-drop it.
- **The art direction has exactly one author.** `procedural-sprites` writes
  `scripts/style.py` once, before any asset exists, and no per-asset subagent
  may edit it — a set where every asset bent the shared palette, light or
  camera to its own need is a set that no longer looks like one game.
- **Every Python run inside a generated set's `scripts/` goes through
  `sprites-generated/.venv/bin/python`**, never the system interpreter, whose
  packages are not this project's business. `sprite-brief`'s own scripts —
  `brief.py`, `cut.py` — are the exception: they ship with the skill, not
  with a generated set, and run under plain `python3`. The venv is
  specifically for `style.py` and the per-asset scripts a job accumulates.
- **The flat `#808080` backdrop is a measured decision, from a cutter this
  pipeline no longer uses.** Cut with an alpha-matting model, a `#FF00FF`
  backdrop left 610–2079 tinted edge pixels across four subject colours while
  `#808080` left zero — matting blends subject and backdrop at the cut edge,
  and a saturated backdrop bled visible colour into that blend. That model is
  gone; `cut.py --key` floods the backdrop colour in from the border instead,
  and grey has never been re-measured against it. It stayed the default
  because a border flood still needs an unambiguous backdrop colour — the
  same reasoning the original test was measuring, not a new measurement of
  today's cutter.

## Tests

One file per module, plain functions, no fixtures or plugins beyond what
`conftest.py` sets up. None of these scripts ever reach the network, so there
is nothing to fake to keep a test offline — just call the functions.

## Conventions

- `docs/specs/YYYY-MM-DD-<topic>-design.md` and `docs/plans/YYYY-MM-DD-<topic>.md`
  are written in pairs before a feature and kept as written afterwards,
  unedited. Some are in Turkish. `docs/` is a historical record — even where
  an older one still describes endpoints this repo no longer has, it stays as
  written.
- Comments here explain *why*, usually citing a measured failure ("a
  `#FF00FF` backdrop left 610–2079 tinted edge pixels"). Match that when
  adding one; delete none of them casually.
- Commit subjects state the intent, not the file list: `fix: name the
  reference images the way the model reads them, not the graph`.
- `.claude/skills/` holds the three skills this repo is built around. If you
  change the analysis schema or a prompt block, the matching `SKILL.md` — and
  for `sprite-brief`, its scripts — is what has to change with it; there is
  no second implementation anywhere to fall out of sync.
