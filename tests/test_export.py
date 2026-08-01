"""export mechanics tests. Run: python3 -m pytest tests/test_export.py"""
import tempfile
from pathlib import Path

from PIL import Image

from spritegen import config
from spritegen import export
from spritegen import orclient


def _pack(tmp, transport="images", reference=True):
    refs = Path(tmp) / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 20), (200, 30, 30)).save(refs / "alpha.png")
    spec = Path(tmp) / "p.toml"
    ref_line = 'reference = "refs/alpha.png"\n' if reference else ""
    spec.write_text(
        '[api]\nbase_url = "https://example.test/v1"\nkey_env = ""\n'
        f'transport = "{transport}"\n'
        '[pack]\nmodel = "m/model"\n'
        '[style]\nprefix = "glossy style"\nplate_prompt = "x"\n'
        '[[assets]]\nid = "alpha"\nprompt = "a red cube"\n' + ref_line
    )
    return config.load_pack(spec, out_root=Path(tmp) / "out"), spec


def test_the_prompt_shown_is_the_prompt_build_would_send():
    """The whole point is comparing another model on identical input, so a
    readable approximation of the prompt would make the comparison worthless."""
    with tempfile.TemporaryDirectory() as tmp:
        pack, _ = _pack(tmp)
        asset = pack.assets[0]
        assert export.wire_prompt(pack, asset) == pack.full_prompt(asset)


def test_the_chat_transport_shows_the_ratio_in_the_text():
    """chat has no structured aspect_ratio field, so it rides in the prompt.
    Showing the images-transport string for a chat pack would misrepresent it."""
    with tempfile.TemporaryDirectory() as tmp:
        pack, _ = _pack(tmp, transport="chat")
        asset = pack.assets[0]
        expected = orclient.chat_prompt_with_ratio(
            pack.full_prompt(asset), asset.aspect_ratio)
        assert export.wire_prompt(pack, asset) == expected
        assert export.wire_prompt(pack, asset) != pack.full_prompt(asset)


def test_the_page_inlines_the_reference_image():
    """Data URIs, not file paths: the file has to survive being moved or
    mailed on its own, and refs/ does not travel with it."""
    with tempfile.TemporaryDirectory() as tmp:
        pack, _ = _pack(tmp)
        html = export.page(pack, pack.assets, "t")
        assert "data:image/png;base64," in html
        assert "refs/alpha.png" not in html


def test_an_asset_without_a_reference_says_so():
    """A silently image-less entry reads as 'this asset needs no reference'."""
    with tempfile.TemporaryDirectory() as tmp:
        pack, _ = _pack(tmp, reference=False)
        html = export.page(pack, pack.assets, "t")
        assert "no reference image" in html
        assert "data:image/" not in html


def test_prompt_text_is_html_escaped():
    with tempfile.TemporaryDirectory() as tmp:
        pack, spec = _pack(tmp)
        spec.write_text(spec.read_text().replace(
            'prompt = "a red cube"', 'prompt = "a <script> & cube"'))
        pack = config.load_pack(spec, out_root=Path(tmp) / "out")
        html = export.page(pack, pack.assets, "t")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

