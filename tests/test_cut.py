"""Background-cut tests. Pure numpy and PIL: no matting model, no downloads."""
import tempfile
from pathlib import Path

from PIL import Image

import cut


def _png_bytes(img) -> bytes:
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_key_clears_the_flat_backdrop_and_keeps_the_subject():
    img = Image.new("RGB", (64, 64), (128, 128, 128))
    for x in range(20, 44):
        for y in range(20, 44):
            img.putpixel((x, y), (200, 40, 40))
    out = cut.key_background(_png_bytes(img))
    assert out.getpixel((2, 2))[3] == 0, "backdrop not cleared"
    assert out.getpixel((32, 32))[3] == 255, "subject was eaten"


def test_key_keeps_a_dark_seam_inside_the_subject():
    # A seam the same colour as the backdrop but not reachable from the border
    # must survive: that is the whole reason this is a flood, not a colour test.
    img = Image.new("RGB", (64, 64), (128, 128, 128))
    for x in range(16, 48):
        for y in range(16, 48):
            img.putpixel((x, y), (200, 40, 40))
    for y in range(20, 44):
        img.putpixel((32, y), (128, 128, 128))
    out = cut.key_background(_png_bytes(img))
    assert out.getpixel((32, 32))[3] == 255, "an enclosed seam was flooded"


def test_tol_widens_what_counts_as_backdrop():
    img = Image.new("RGB", (32, 32), (128, 128, 128))
    img.putpixel((0, 1), (136, 136, 136))          # 8 away
    tight = cut.key_background(_png_bytes(img), tol=2.0)
    wide = cut.key_background(_png_bytes(img), tol=30.0)
    assert tight.getpixel((0, 1))[3] == 255
    assert wide.getpixel((0, 1))[3] == 0


def test_glow_takes_alpha_from_brightness():
    img = Image.new("L", (32, 32), 0).convert("RGB")
    img.putpixel((16, 16), (255, 255, 255))
    out = cut.cut_glow(_png_bytes(img))
    assert out.getpixel((16, 16))[3] == 255
    assert out.getpixel((0, 0))[3] == 0


def test_trim_and_pad_centres_the_subject_on_a_square():
    img = Image.new("RGBA", (80, 40), (0, 0, 0, 0))
    for x in range(4, 20):
        for y in range(4, 12):
            img.putpixel((x, y), (255, 0, 0, 255))
    out = cut.trim_and_pad(img)
    assert out.width == out.height
    assert out.getpixel((0, 0))[3] == 0
    assert out.getpixel((out.width // 2, out.height // 2))[3] == 255


def test_iter_pngs_walks_dirs_and_skips_the_sheets():
    d = Path(tempfile.mkdtemp())
    (d / "a.png").write_bytes(_png_bytes(Image.new("RGB", (4, 4))))
    (d / "_contact_sheet.png").write_bytes(_png_bytes(Image.new("RGB", (4, 4))))
    found = [p.name for p in cut.iter_pngs([d])]
    assert found == ["a.png"]


def test_key_is_the_default_mode():
    d = Path(tempfile.mkdtemp())
    src, out_dir = d / "in", d / "out"
    src.mkdir()
    img = Image.new("RGB", (32, 32), (128, 128, 128))
    for x in range(10, 22):
        for y in range(10, 22):
            img.putpixel((x, y), (10, 200, 90))
    img.save(src / "blob.png")
    assert cut.main([str(src), "--out-dir", str(out_dir)]) == 0
    with Image.open(out_dir / "blob.png") as done:
        assert done.mode == "RGBA"
        assert done.getpixel((0, 0))[3] == 0
