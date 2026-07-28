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

import orclient

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


def page(pack, assets, title: str) -> str:
    """The whole HTML document as a string."""
    out = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body>",
        f"<h1>{html.escape(title)}</h1>",
        f"<p class='meta'>model <b>{html.escape(pack.model)}</b> · transport "
        f"<b>{html.escape(pack.transport)}</b> · {len(assets)} assets</p>",
    ]
    for asset in assets:
        reference = asset.reference or pack.style_bible
        out.append("<div class='asset'>")
        out.append(f"<h2>{html.escape(asset.id)}</h2><div class='row'>")
        if reference and reference.exists():
            out.append(
                f"<a href='{_data_uri(reference)}' download='{html.escape(asset.id)}.png'>"
                f"<img src='{_data_uri(reference)}' alt='{html.escape(asset.id)}'></a>"
            )
        else:
            # Say which file is missing rather than showing a blank frame: a
            # silently image-less entry reads as "this asset needs no reference".
            shown = str(reference) if reference else "none set"
            out.append(f"<p class='missing'>no reference image ({html.escape(shown)})</p>")
        out.append(f"<pre>{html.escape(wire_prompt(pack, asset))}</pre>")
        out.append("</div>")
        if pack.transport == "images":
            out.append(f"<p class='note'>aspect_ratio <b>{html.escape(asset.aspect_ratio)}</b> "
                       "is sent as a separate field, not in the prompt text. "
                       "Click the image to save it.</p>")
        else:
            out.append("<p class='note'>Click the image to save it.</p>")
        out.append("</div>")
    out.append("</body></html>")
    return "\n".join(out)
