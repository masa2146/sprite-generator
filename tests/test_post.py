"""Geometry tests for post.trim_and_pad. Run: python3 -m pytest tests/test_post.py"""
from PIL import Image

from spritegen.post import trim_and_pad


def _canvas(box, size=(512, 512), color=(0, 0, 255, 255)):
    """Transparent canvas with one opaque rectangle at `box` (l, t, r, b)."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    img.paste(color, box)
    return img


def test_square_subject_pads_to_exact_side():
    # 200x200 opaque square -> ceil(200 * 1.08 / 2) * 2 == 216
    out = trim_and_pad(_canvas((156, 156, 356, 356)))
    assert out.size == (216, 216), out.size


def test_output_corner_is_transparent_and_center_is_opaque():
    out = trim_and_pad(_canvas((156, 156, 356, 356)))
    assert out.getpixel((0, 0))[3] == 0
    assert out.getpixel((out.width // 2, out.height // 2))[3] == 255


def test_non_square_subject_pads_to_square_on_long_edge():
    # 200 wide x 300 tall -> ceil(300 * 1.08 / 2) * 2 == 324
    out = trim_and_pad(_canvas((100, 100, 300, 400)))
    assert out.size == (324, 324), out.size


def test_subject_is_centered():
    out = trim_and_pad(_canvas((100, 100, 300, 400)))
    # 324 wide canvas holding a 200-wide subject -> 62px transparent each side
    assert out.getpixel((30, out.height // 2))[3] == 0
    assert out.getpixel((out.width // 2, out.height // 2))[3] == 255


def test_offset_subject_gives_same_result_as_centered_one():
    """Trim must remove position information entirely."""
    a = trim_and_pad(_canvas((0, 0, 200, 200)))
    b = trim_and_pad(_canvas((300, 300, 500, 500)))
    assert a.size == b.size
    assert a.tobytes() == b.tobytes()


def test_fully_transparent_image_is_returned_unchanged():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    assert trim_and_pad(img).size == (64, 64)


def test_no_resampling_subject_pixels_are_untouched():
    out = trim_and_pad(_canvas((156, 156, 356, 356), color=(12, 34, 56, 255)))
    assert out.getpixel((out.width // 2, out.height // 2)) == (12, 34, 56, 255)



def test_backdrop_enclosed_by_the_subject_is_cleared():
    """rembg segments by salience, so a ring keeps its own centre — a conveyor
    loop came back as a frame with the backdrop still filling the hole. The
    colour decides what is backdrop, not whether the subject encloses it."""
    from PIL import Image
    from spritegen import post

    grey = (157, 157, 154)
    original = Image.new("RGB", (40, 40), grey)
    for x in range(10, 30):        # a coloured ring: border drawn, centre backdrop
        for y in (10, 29):
            original.putpixel((x, y), (200, 40, 160))
            original.putpixel((y, x), (200, 40, 160))

    # What rembg hands back: everything inside the outer edge kept opaque.
    cut = original.convert("RGBA")
    alpha = Image.new("L", (40, 40), 0)
    for x in range(10, 30):
        for y in range(10, 30):
            alpha.putpixel((x, y), 255)
    cut.putalpha(alpha)

    out = post._drop_enclosed_backdrop(cut, original)
    assert out.getpixel((20, 20))[3] == 0, "enclosed backdrop must be cleared"
    assert out.getpixel((10, 15))[3] == 255, "the subject itself must survive"
    assert out.getpixel((0, 0))[3] == 0


def test_border_median_reads_the_frame_not_the_middle():
    from PIL import Image
    from spritegen import post

    img = Image.new("RGB", (20, 20), (10, 20, 30))
    for x in range(5, 15):
        for y in range(5, 15):
            img.putpixel((x, y), (250, 0, 0))
    assert post.border_median(img) == (10, 20, 30)


def test_border_median_survives_a_subject_that_reaches_two_edges():
    """A tileable piece is asked to run from one edge of the picture to the
    other. Sampling the whole one-pixel frame then reads the subject as the
    backdrop, and the cut erases everything but a smear."""
    from PIL import Image
    from spritegen import post

    grey = (157, 157, 154)
    img = Image.new("RGB", (200, 100), grey)
    for y in range(40, 60):            # a strip spanning the full width
        for x in range(200):
            img.putpixel((x, y), (60, 60, 140))
    assert post.border_median(img) == grey


def test_match_palette_pulls_a_piece_onto_its_master():
    """Pieces of one object generated in separate requests drift: a conveyor
    corner butted perfectly against its straight run but with a paler channel
    and cream highlights. Geometry is what the model is for; the palette is
    already known from the piece that came out right."""
    from PIL import Image
    from spritegen import post

    master = Image.new("RGBA", (60, 60), (40, 40, 110, 255))
    for y in range(20, 40):
        for x in range(60):
            master.putpixel((x, y), (230, 235, 255, 255))

    # Same picture, washed out and warm — a channel too pale, highlights cream.
    piece = Image.new("RGBA", (60, 60), (110, 108, 150, 255))
    for y in range(20, 40):
        for x in range(60):
            piece.putpixel((x, y), (240, 238, 210, 255))

    out = post.match_palette(piece, master)
    assert out.size == piece.size
    for got, want in zip(out.getpixel((5, 5))[:3], (40, 40, 110)):
        assert abs(got - want) <= 3
    for got, want in zip(out.getpixel((5, 30))[:3], (230, 235, 255)):
        assert abs(got - want) <= 3


def test_match_palette_leaves_a_fully_transparent_image_alone():
    from PIL import Image
    from spritegen import post

    empty = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    master = Image.new("RGBA", (10, 10), (1, 2, 3, 255))
    assert post.match_palette(empty, master).getpixel((5, 5)) == (0, 0, 0, 0)
