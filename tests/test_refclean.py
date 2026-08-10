"""Crop cleanup tests. A crop lifted from a phone screenshot carries three
defects that were each measured coming back in the generated sprite: pixel
steps, a top-to-bottom lighting ramp, and letterbox bars."""
import tempfile
from pathlib import Path

import refclean
from PIL import Image


def test_refclean_removes_what_a_screenshot_adds():
    """Three defects came back measured in generated sprites: the capture's
    pixel steps as pixel art, its lighting ramp as a piece dark at one end, and
    the phone's letterbox bars as black slabs. The prompt calls all three
    capture artefacts and loses to the picture, so they go here."""
    im = Image.new("RGB", (60, 40), (70, 70, 120))
    for x in range(0, 4):                       # letterbox down the left
        for y in range(40):
            im.putpixel((x, y), (0, 0, 0))
    out = refclean.strip_letterbox(im)
    assert out.getpixel((1, 20)) != (0, 0, 0)
    assert out.getpixel((30, 20)) == (70, 70, 120)

    big = refclean.upscale(im, 240)
    assert max(big.size) == 240
    assert big.width / big.height == im.width / im.height
    assert refclean.upscale(big, 100).size == big.size   # never downscales


def test_row_flatten_erases_along_the_run_and_spares_the_rails():
    """A straight run is one cross-section extruded sideways, so every row is
    one colour. A median *filter* wide enough to erase the direction chevrons
    ate a rail; this cannot, because a rail is a row."""
    im = Image.new("RGB", (40, 12), (60, 60, 110))
    for x in range(40):
        im.putpixel((x, 3), (230, 230, 255))    # a rail: a whole row
    for x in range(8, 12):
        im.putpixel((x, 7), (120, 120, 170))    # a chevron: part of a row
    out = refclean.row_flatten(im)
    assert out.getpixel((0, 3)) == (230, 230, 255)
    assert out.getpixel((39, 3)) == (230, 230, 255)
    assert out.getpixel((9, 7)) == (60, 60, 110)


def test_palette_reports_colours_that_are_really_there():
    im = Image.new("RGB", (40, 40), (67, 67, 117))
    for y in range(0, 8):
        for x in range(40):
            im.putpixel((x, y), (228, 233, 255))
    hexes = refclean.palette(im, 2)
    assert "#434375" in hexes
    assert all(h.startswith("#") and len(h) == 7 for h in hexes)


def test_flattened_rows_skip_the_flat_field():
    """row_flatten has already removed every variation along the run, so the
    only variation left is the cross-section — the design, not a lighting ramp.
    Correcting it anyway tinted the top of a conveyor run green: per-channel
    gain on a near-neutral dark row amplifies whichever channel leads."""
    im = Image.new("RGB", (40, 12), (58, 62, 99))
    for x in range(40):
        im.putpixel((x, 5), (228, 233, 255))
    out = refclean.clean(im, flatten_rows=True, min_long=40)
    assert out.getpixel((20, 0)) == (58, 62, 99), "an untouched row must stay untouched"


def test_row_flatten_never_invents_a_colour():
    """Per-channel medians can name a colour that is nowhere in the row. A strip
    padded far enough up to catch a blue HUD badge took its red and green from
    the badge and its blue from the track, and the row came out green."""
    im = Image.new("RGB", (10, 1))
    im.putdata([(45, 150, 242)] * 4 + [(60, 60, 110)] * 6)   # badge, then track
    out = refclean.row_flatten(im)
    assert out.getpixel((5, 0)) in {(45, 150, 242), (60, 60, 110)}


def test_clean_crops_records_the_measured_palette_on_each_entry():
    d = Path(tempfile.mkdtemp())
    crop = d / "brick.png"
    Image.new("RGB", (40, 40), (67, 67, 117)).save(crop)
    entries = [{"id": "brick", "crop": crop}]
    refclean.clean_crops(entries)
    assert entries[0]["palette"], "no palette recorded"
    top = entries[0]["palette"][0]
    assert top.startswith("#") and len(top) == 7
    # The dominant colour is the one that is really there. Compared with a
    # tolerance, not for equality: flat_field divides by a blurred copy of the
    # image before the palette is measured, so an exact match would be a test
    # of the correction's rounding rather than of the palette.
    rgb = tuple(int(top[i:i + 2], 16) for i in (1, 3, 5))
    assert all(abs(a - b) <= 12 for a, b in zip(rgb, (67, 67, 117))), top
