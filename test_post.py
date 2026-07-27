"""Geometry tests for post.trim_and_pad. Run: python3 test_post.py"""
from PIL import Image

from post import trim_and_pad


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all post tests passed")
