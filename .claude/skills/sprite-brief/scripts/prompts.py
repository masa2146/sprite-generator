"""The text of the hand-generation prompt.

Pure strings, pasted into Gemini or ChatGPT by hand — no I/O, no PIL, no
filesystem. Structured blocks rather than a paragraph: on the paid path (the
package this skill replaced) the constraints were buried in a run-on sentence
and the clauses a model skipped were the ones that mattered, measured as
twelve balls in one image and HUD labels that kept their text.
"""

from __future__ import annotations

# Hosted models do not emit reliable alpha, so we ask for a flat backdrop we can
# cut locally. Edge quality comes from this clause, not from the model.
# Neutral grey, not a chroma-key colour. The local cutout step does alpha
# matting, not chroma keying: edge pixels come out as a blend of subject and
# backdrop, so a saturated backdrop bleeds visible colour into the cutout's
# edge. Measured on a synthetic sprite across four subject colours: #FF00FF
# left 610-2079 tinted edge pixels every time, #808080 left zero, with
# segmentation quality unchanged (matting keys on salience, not colour
# contrast).
BG_CLAUSE = ("isolated on flat solid #808080 neutral grey background, no shadow, "
             "no ground plane, no gradient, no scene, no props")

# A sprite prompt is labelled blocks rather than one sentence. The manual path
# (brief.py) was built that way after the run-on form lost its constraints: the
# clauses a model skips are the ones buried mid-sentence, and the measured
# failures were twelve balls instead of one and HUD labels that kept their text.
# The blocks live here, not in either caller, so the paid and manual paths
# cannot drift apart.
# image1 needs both halves of its instruction. "Reproduce THIS object" alone
# got the object reproduced faithfully -- including the fact that the crop is a
# 52x60 lift from a phone screenshot. The render came back as hard-outlined
# pixel art against a style prefix asking in so many words for "flat
# vector-style, no hard outlines": shown pixel art and told to reproduce it, the
# model reproduces pixel art, because image evidence beats a text style block.
# Smoothly upscaling the crop before sending it did not help -- the model
# resamples to its own latent resolution anyway, so what carries is the
# reference's content, not its pixel dimensions. Naming the artefacts is what
# separates identity from rendering.
# The images are named the way the *model* sees them, not the way the graph's
# input sockets are named. ComfyUI's TextEncodeQwenImageEditPlus prepends
# "Picture 1: <image>Picture 2: <image>" to the prompt before tokenising, so
# "image1" refers to a label that never reaches the model and cannot bind to
# anything. The socket is called image1; what the model reads is Picture 1.
_PICTURE_1 = (
    "REFERENCES\n"
    "- Picture 1 — the object to redraw. Take its IDENTITY from this and nothing\n"
    "  else: silhouette, proportions, colours, markings, features.\n"
    "  Do NOT take its rendering. Picture 1 is a small low-resolution screen\n"
    "  capture; its pixellation, blocky stair-stepped edges and colour banding\n"
    "  are capture artefacts, not design. Redraw the object cleanly at full\n"
    "  resolution in the ART STYLE below."
)
_PICTURE_2 = (
    "\n- Picture 2 — the reference screenshot. Use it ONLY for art style, palette\n"
    "  and lighting. Do not copy any object from it."
)


def references_block(style_image: bool = True) -> str:
    """The REFERENCES block, naming only the pictures actually being sent.

    Picture 1's paragraph is the part that separates identity from rendering,
    and it applies to any asset that sends a crop at all. Emitting the whole
    block only when a style image went too left single-image assets with no
    guidance whatsoever: dropping the style reference from a pack brought back
    the sleepers a DO NOT DRAW bullet had been holding off and left the model
    rendering the crop's own screen-capture look.
    """
    return _PICTURE_1 + (_PICTURE_2 if style_image else "")


REFERENCES_BLOCK = references_block()


def output_block(subject: str = "copy of the object described above",
                  square: bool = False) -> str:
    """The OUTPUT block. `subject` names the thing when the caller knows it.

    The count is what matters — an unqualified prompt produced twelve balls in
    one image — but naming it is stronger where a name exists. A pack's asset id
    ("coin-front") is not one, so the build path leans on the default, which
    points at the OBJECT line the prompt already carries.

    `square` appends "Square image." to the margin bullet. False by default so
    the build path is unaffected: it carries aspect ratio as a structured field
    and has a 4:1 status-bar asset, so it must never ask for a square canvas.
    asset_prompt passes True — pasting into Gemini/ChatGPT by hand has no
    aspect-ratio field, so that clause is the only thing asking for a square
    canvas on that path.
    """
    margin = "- Small even margin on all sides." + (" Square image." if square else "")
    return (
        "OUTPUT\n"
        f"- Exactly one {subject}, on its own. Not a set, not a grid, not a sheet.\n"
        "- Centred and complete, nothing touching or cut off at the edges.\n"
        f"{margin}\n"
        # Capitalised for display only — BG_CLAUSE itself (the single source of
        # this wording) stays untouched.
        f"- {BG_CLAUSE[0].upper()}{BG_CLAUSE[1:]}"
    )


# Every one of these was a measured failure, and the ban on text is why none of
# them is speculative: that clause lives here, rides on every prompt from both
# paths, and held on five straight assets in a live run where a "keep it flat"
# left to each pack's own style line held on none. A rule that matters cannot
# depend on what a human happened to type into `style`.
FIXED_BANS = (
    "- any text, numbers, labels or logos\n"
    "- any other object from the reference image\n"
    "- more than one copy of the object\n"
    # Worded against the VIEW line rather than against angles in general: an
    # outright ban on turning the object would contradict the three_quarter and
    # top_down views the same prompt can ask for, which is the exact shape of
    # bug this block keeps catching.
    "- any perspective, tilt or isometric projection the VIEW line above did\n"
    "  not ask for; the object sits flat and square to the viewer otherwise\n"
    "- any colour that is neither in the reference nor named above; do not\n"
    "  recolour parts, do not introduce a second hue, do not brighten the\n"
    "  palette\n"
    "- any panel, stud, bolt, rivet, seam, light, glint or marking that the\n"
    "  description above does not ask for"
)


def do_not_draw(exclude: str = "") -> str:
    """The DO NOT DRAW block: this asset's own exclusions, then the fixed bans.

    `exclude` is what a framing object's crop shows but must not be redrawn —
    see exclusion_clause below. Empty for an asset whose crop shows only
    itself, which is most of them.
    """
    lines = ["DO NOT DRAW"]
    if exclude and exclude.strip():
        lines.append(f"- {exclude.strip()}")
    lines.append(FIXED_BANS)
    return "\n".join(lines)


# Closed set of view variations. Closed rather than free-form so file names stay
# predictable and the same command twice yields the same set.
VIEW_POOL = {
    "front": "seen from directly the front",
    "three_quarter": "seen from a three-quarter front angle",
    "side": "seen from directly the side, full profile",
    "back": "seen from directly behind",
    "top_down": "seen from directly above, top-down",
    # Spin frames, not camera moves: the camera stays put and the object turns
    # in the picture plane. A tumbling projectile needs these — asking for its
    # side and top_down instead produces four pictures of a symmetrical slab
    # that all look the same, and the rotation request ends up smuggled into
    # "detail" as "needs four frames", which then fights OUTPUT's "exactly one".
    "rotated_45": "seen from directly the front, the object itself rotated 45 degrees clockwise within the picture plane",
    "rotated_90": "seen from directly the front, the object itself rotated 90 degrees clockwise within the picture plane",
    "rotated_135": "seen from directly the front, the object itself rotated 135 degrees clockwise within the picture plane",
}
DEFAULT_VIEW = "front"

# A plane rotation is arithmetic, not art, and the backend does not do it: asked
# for three rotated frames of a projectile it returned three upright ones with
# different finishes. Rotating the front frame instead is exact, free, and
# guarantees the frames are the same object — which generating them separately
# never can.
ROTATION_DEGREES = {"rotated_45": 45, "rotated_90": 90, "rotated_135": 135}

# Labelled lines, one field per line, because a model skips a clause buried in a
# sentence but answers a field it can see. "state" only exists on hand-written
# analyses (brief.py); it is simply absent from a vision reply and dropped here.
FIELD_LABELS = (
    ("subject", "OBJECT"), ("form", "FORM"), ("detail", "DETAIL"), ("state", "STATE"),
)


def field_block(obj: dict, view: str) -> str:
    """One object's fields as labelled lines, ending with its VIEW line.

    Shared by the review page and the hand-generation prompt, so the two
    produce the same prompt body.
    """
    lines = [
        f"{label:<10} {obj[key].strip()}"
        for key, label in FIELD_LABELS
        if isinstance(obj.get(key), str) and obj[key].strip()
    ]
    # Measured off the crop, not described. A vision model called a conveyor's
    # channel "pale lilac-white" when it is #434375, and the sprite came back
    # pale until the real value was in the prompt.
    swatches = [c for c in (obj.get("palette") or []) if isinstance(c, str)]
    if swatches:
        lines.append("{:<10} {}".format("PALETTE", ", ".join(swatches)
                                        + " — the colours actually present in Picture 1"))
    phrase = VIEW_POOL.get(view, VIEW_POOL[DEFAULT_VIEW])
    lines.append("{:<10} {}".format("VIEW", phrase))
    return "\n".join(lines)


def normalise_views(views) -> list[str]:
    """Pool members only, in pool order, never empty.

    Closed pool so file names stay predictable and the same analysis twice
    yields the same set. A name outside it is dropped rather than passed
    through, because an unknown view would silently get the `front` phrase.
    """
    wanted = {v for v in views if isinstance(v, str)} if isinstance(views, list) else set()
    ordered = [v for v in VIEW_POOL if v in wanted]
    # A rotated frame is turned from the front frame; without it there is
    # nothing to turn.
    if (any(v in ROTATION_DEGREES for v in ordered)
            and DEFAULT_VIEW not in ordered):
        ordered = [DEFAULT_VIEW] + ordered
    return ordered or [DEFAULT_VIEW]


# Beyond this many, the prompt clause stops being a description and becomes a
# list. The count is still reported in full.
MAX_NAMED_CONTENTS = 4


def exclusion_names(ids) -> list[str]:
    """Humanised names for the ids a box swallows, capped and summarised.

    Public for exclusion_clause below, its one caller. Kept as its own function
    anyway because the capping and pluralisation is the part that has been
    wrong once already — worth testing in isolation from the sentence it ends
    up in.
    """
    named = [i.replace("_", " ") for i in ids[:MAX_NAMED_CONTENTS]]
    rest = len(ids) - MAX_NAMED_CONTENTS
    if rest > 0:
        named.append(f"and {rest} other element" + ("s" if rest > 1 else ""))
    return named


def exclusion_clause(ids) -> str:
    """What a crop shows but the sprite must not — this asset's `exclude` value.

    Phrased as one DO NOT DRAW bullet, which is where do_not_draw files it.
    """
    return ("the " + ", ".join(exclusion_names(ids))
            + " visible inside it in the reference image")


# The order the fields read best in, and deliberately not the schema's order:
# palette last, after the visual description it tints.
_STYLE_ORDER = ("render", "lighting", "linework", "realism", "palette")


def style_line(style: dict) -> str:
    """The ART STYLE line: the style fields joined, camera excluded.

    Camera is excluded here and only here. The prompt carries its own VIEW line
    per object, so an angle in the style line contradicts it on every view but
    front — the exact bug this ordering was pulled apart to fix. The field is
    still read, by the procedural path, which turns it into the shared camera
    tilt constant rather than into prompt text.
    """
    parts = [str(style[field]).strip() for field in _STYLE_ORDER
             if isinstance(style.get(field), str) and style[field].strip()]
    return ", ".join(parts)


def asset_prompt(obj: dict, view: str, style: dict, contents=None,
                 style_image: bool = True) -> str:
    """One paste-ready prompt for this object in this view.

    Structured blocks rather than a paragraph: in the run-on form the clauses a
    model skips were the ones buried mid-sentence, and the measured failures
    were twelve balls instead of one and HUD labels that kept their text.
    """
    return "\n\n".join([
        references_block(style_image),
        field_block(obj, view),
        f"ART STYLE  {style_line(style)}",
        output_block(obj["id"].replace("_", " "), square=True),
        do_not_draw(exclusion_clause(contents) if contents else ""),
    ])
