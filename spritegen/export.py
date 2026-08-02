"""Write one self-contained HTML file showing exactly what each asset sends.

The point is portability to a different model: open the file, copy the prompt,
save the reference image, paste both into Gemini or ChatGPT, and compare their
output against ours on identical input. So the prompt shown here must be the
*wire* prompt — what orclient actually sends — not a readable approximation of
it. Anything else makes the comparison meaningless.

Images are inlined as data URIs so the file survives being moved or mailed on
its own; the refs directory does not travel with it otherwise.
"""

from __future__ import annotations

import base64
import html
from pathlib import Path

from . import orclient

_CSS = """
body { font: 15px/1.55 -apple-system, Segoe UI, sans-serif; margin: 0 auto;
       max-width: 60rem; padding: 2rem 1.25rem; background: #16161c; color: #e8e8ef; }
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
.meta { color: #9a9ab0; font-size: .85rem; margin-bottom: 2rem; }
.asset { border-top: 1px solid #2c2c3a; padding: 1.5rem 0; }
.asset h2 { font-size: 1.05rem; margin: 0 0 .75rem; font-family: ui-monospace, monospace; }
.row { display: flex; gap: 1.25rem; align-items: flex-start; flex-wrap: wrap; }
img { max-width: 220px; max-height: 220px; background: #22222c; border-radius: 6px; }
pre { flex: 1 1 22rem; margin: 0; padding: .85rem; background: #1e1e28;
      border-radius: 6px; white-space: pre-wrap; word-break: break-word;
      font: 13px/1.5 ui-monospace, monospace; }
.note { color: #9a9ab0; font-size: .8rem; margin-top: .5rem; }
.missing { color: #ff9d9d; }
.pair { color: #9a9ab0; font-size: .85rem; margin: 0; align-self: center; }
"""


def _data_uri(path: Path) -> str:
    raw = path.read_bytes()
    return f"data:{orclient._sniff_mime(raw)};base64,{base64.b64encode(raw).decode()}"


def wire_prompt(pack, asset) -> str:
    """The prompt text as it goes on the wire, transport included.

    The chat transport has no structured aspect-ratio field so the ratio is
    appended to the text; the images transport sends it separately. Showing the
    same string for both would misrepresent one of them.
    """
    prompt = pack.full_prompt(asset)
    if pack.transport == "chat":
        return orclient.chat_prompt_with_ratio(prompt, asset.aspect_ratio)
    return prompt


def _image_or_missing(path, alt: str, download: str) -> str:
    """A clickable inlined image, or a note naming the missing file.

    Say which file is missing rather than showing a blank frame: a silently
    image-less entry reads as "this asset needs no reference".
    """
    if path and path.exists():
        return (f"<a href='{_data_uri(path)}' download='{html.escape(download)}'>"
                f"<img src='{_data_uri(path)}' alt='{html.escape(alt)}'></a>")
    shown = str(path) if path else "none set"
    return f"<p class='missing'>no reference image ({html.escape(shown)})</p>"


def page(pack, assets, title: str) -> str:
    """The whole HTML document as a string."""
    # Same condition build_one uses to decide whether an asset gets both
    # images: its own reference AND a pack-level style reference to go beside
    # it. wire_prompt's REFERENCES block names image1/image2 exactly for this
    # set — every other asset gets the single-image treatment it always did.
    two_image = {a.id for a in assets
                 if a.reference is not None and pack.style_reference is not None}

    out = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body>",
        f"<h1>{html.escape(title)}</h1>",
        f"<p class='meta'>model <b>{html.escape(pack.model)}</b> · transport "
        f"<b>{html.escape(pack.transport)}</b> · {len(assets)} assets</p>",
    ]

    if two_image:
        # Drawn once, at the top, not per matching asset: repeating it inlines
        # the same base64 blob once per asset (brief.py's page() measured 55 MB
        # for a 2.4 MB screenshot across 17 assets). Every matching asset below
        # still names it, so the "two images" fact survives without the bytes.
        out += [
            "<div class='asset'>",
            "<h2>image2 — style reference</h2><div class='row'>",
            _image_or_missing(pack.style_reference, "style reference",
                              "image2" + pack.style_reference.suffix),
            "<p class='note'>sent alongside every asset below marked image1 + "
            "image2, for art style, palette and lighting only.</p>",
            "</div></div>",
        ]

    for asset in assets:
        out.append("<div class='asset'>")
        out.append(f"<h2>{html.escape(asset.id)}</h2><div class='row'>")
        if asset.id in two_image:
            out.append(_image_or_missing(asset.reference, f"{asset.id} — image1",
                                         f"{asset.id}-image1.png"))
            out.append("<p class='pair'>+ image2 — style reference "
                       "(shown once, above)</p>")
        else:
            reference = asset.reference or pack.style_bible
            out.append(_image_or_missing(reference, asset.id, f"{asset.id}.png"))
        out.append(f"<pre>{html.escape(wire_prompt(pack, asset))}</pre>")
        out.append("</div>")
        if pack.transport == "images":
            out.append(f"<p class='note'>aspect_ratio <b>{html.escape(asset.aspect_ratio)}</b> "
                       "is sent as a separate field, not in the prompt text. "
                       "Click an image to save it.</p>")
        else:
            out.append("<p class='note'>Click an image to save it.</p>")
        out.append("</div>")
    out.append("</body></html>")
    return "\n".join(out)
