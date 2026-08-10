"""One run of the whole local half: analysis in, review page and crops out,
then a hand-generated PNG cut. No skill, no subagent, no network — this is the
part that has to work before either of those is worth invoking."""
import json
import tempfile
from pathlib import Path

from PIL import Image

import brief
import cut

STYLE = {"render": "soft 3D render", "camera": "3/4 front view",
         "lighting": "top-left key", "palette": "#5A5A78",
         "linework": "dark contour", "realism": "stylized cartoon"}


def test_a_screenshot_and_a_description_become_a_reviewable_brief():
    d = Path(tempfile.mkdtemp())
    shot = d / "shot.png"
    img = Image.new("RGB", (300, 200), (90, 90, 120))
    for x in range(30, 130):
        for y in range(30, 130):
            img.putpixel((x, y), (200, 70, 40))
    img.save(shot)

    (d / "analysis.json").write_text(json.dumps({
        "style": STYLE,
        "style_source": {"render": "stil görseli", "realism": "kullanıcı"},
        "style_image": "shot.png",
        "objects": [
            {"id": "block", "subject": "a rounded block", "form": "one piece",
             "bbox": [30, 30, 130, 130], "views": ["front", "three_quarter"]},
            {"id": "idea", "subject": "a thing the user only described"},
        ],
    }), encoding="utf-8")

    out = d / "set" / "brief"
    assert brief.main(["--analysis", str(d / "analysis.json"),
                       "--out-dir", str(out), "--no-open"]) == 0

    page = (out / "review.html").read_text(encoding="utf-8")
    assert "block" in page and "idea" in page
    assert page.count("DO NOT DRAW") == 3          # 2 views + 1 text-only object
    assert "stil görseli" in page and "kullanıcı" in page
    assert (out / "refs" / "block.png").exists()
    assert (out / "refs" / "_style.png").exists()
    assert (out / "refs" / "_contact_sheet.png").exists()
    assert not (out / "refs" / "idea.png").exists()


def test_a_hand_generated_png_on_flat_grey_comes_back_with_alpha():
    d = Path(tempfile.mkdtemp())
    downloads, sprites = d / "downloads", d / "out"
    downloads.mkdir()
    SIZE, SUBJECT = 128, 50           # frame, and the painted square inside it
    img = Image.new("RGB", (SIZE, SIZE), (128, 128, 128))
    for x in range(40, 40 + SUBJECT):
        for y in range(40, 40 + SUBJECT):
            img.putpixel((x, y), (200, 70, 40))
    src = downloads / "block.png"
    img.save(src)

    assert cut.main([str(downloads), "--out-dir", str(sprites)]) == 0
    with Image.open(sprites / "block.png") as done:
        assert done.mode == "RGBA"
        assert done.getpixel((0, 0))[3] == 0
        assert done.width == done.height
        # A working key trims to roughly the subject plus a small margin
        # (~54px here). Keying that removed nothing pads the whole untouched
        # SIZE x SIZE frame instead, which comes out *larger* than SIZE
        # (~140px). SUBJECT * 2 sits well below that and above the true size,
        # so only a real cut can pass this.
        assert done.width < SUBJECT * 2

    # The size bound alone only proves something was cropped; pin the keying
    # itself too: a pixel that was backdrop in the original frame must come
    # back transparent, and a pixel that was subject must come back opaque.
    keyed = cut.key_background(src.read_bytes())
    assert keyed.getpixel((10, 10))[3] == 0      # backdrop
    assert keyed.getpixel((60, 60))[3] == 255    # inside the subject square
