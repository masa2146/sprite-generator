"""Box geometry and crop tests. No network, no vision, no prompts."""
import tempfile
from pathlib import Path

from PIL import Image

import crops


def _img(w=400, h=600):
    return Image.new("RGB", (w, h), (30, 30, 50))


def _objects():
    return [
        {"id": "alpha", "bbox": [10, 10, 110, 110], "animated": True,
         "views": ["front", "side"], "subject": "a thing",
         "form": "a round thing", "detail": "shiny"},
        {"id": "beta", "bbox": [200, 300, 260, 380], "animated": False,
         "views": ["front"], "subject": "another thing",
         "form": "a boxy thing", "detail": "matte"},
    ]


# --- bbox validation --------------------------------------------------------

def test_a_normal_box_is_accepted():
    assert crops.reject_reason([10, 10, 110, 110], 400, 600) is None


def test_a_box_outside_the_image_is_rejected():
    assert "outside" in crops.reject_reason([380, 10, 460, 110], 400, 600)
    assert "outside" in crops.reject_reason([-5, 10, 110, 110], 400, 600)


def test_a_zero_or_inverted_box_is_rejected():
    assert "empty" in crops.reject_reason([100, 100, 100, 200], 400, 600)
    assert "empty" in crops.reject_reason([200, 100, 100, 200], 400, 600)


def test_a_box_covering_the_whole_image_is_rejected():
    assert "whole image" in crops.reject_reason([0, 0, 400, 600], 400, 600)


def test_a_tiny_box_is_rejected():
    assert "too small" in crops.reject_reason([10, 10, 20, 110], 400, 600)


def test_a_malformed_box_is_rejected():
    assert crops.reject_reason("nope", 400, 600) is not None
    assert crops.reject_reason([1, 2, 3], 400, 600) is not None
    assert crops.reject_reason([1, 2, "x", 4], 400, 600) is not None


# --- cropping ---------------------------------------------------------------

def test_crop_objects_writes_one_file_per_object():
    d = Path(tempfile.mkdtemp())
    kept, rejected = crops.crop_objects(_img(), _objects(), d)
    assert [o["id"] for o in kept] == ["alpha", "beta"]
    assert rejected == []
    assert (d / "alpha.png").exists() and (d / "beta.png").exists()
    assert kept[0]["crop"] == d / "alpha.png"


def test_crop_dimensions_match_the_padded_box():
    d = Path(tempfile.mkdtemp())
    kept, _ = crops.crop_objects(_img(), _objects(), d)
    x1, y1, x2, y2 = crops.padded_box(_objects()[0]["bbox"], 400, 600)
    with Image.open(kept[0]["crop"]) as im:
        assert im.size == (x2 - x1, y2 - y1)


def test_a_rejected_box_is_reported_and_skipped():
    d = Path(tempfile.mkdtemp())
    objs = _objects() + [{"id": "bad", "bbox": [0, 0, 400, 600], "animated": False,
                          "views": ["front"], "subject": "s", "form": "f", "detail": "d"}]
    kept, rejected = crops.crop_objects(_img(), objs, d)
    assert [o["id"] for o in kept] == ["alpha", "beta"]
    assert [r[0] for r in rejected] == ["bad"]
    assert "whole image" in rejected[0][1]
    assert not (d / "bad.png").exists()


def test_an_object_without_an_id_is_rejected_not_crashed():
    d = Path(tempfile.mkdtemp())
    kept, rejected = crops.crop_objects(_img(), [{"bbox": [10, 10, 50, 50]}], d)
    assert kept == []
    assert len(rejected) == 1


def test_a_duplicate_id_is_rejected_and_the_first_crop_survives():
    """Critical 3: two objects sharing an id used to overwrite each other's
    crop on disk and produce an unloadable pack (config.load_pack rejects
    duplicate asset ids). The second occurrence must be rejected, and the
    first object's crop (its real dimensions) must be left untouched."""
    d = Path(tempfile.mkdtemp())
    objs = [
        {"id": "block", "bbox": [10, 10, 110, 110], "animated": False, "views": ["front"]},
        {"id": "block", "bbox": [200, 300, 260, 380], "animated": False, "views": ["front"]},
    ]
    kept, rejected = crops.crop_objects(_img(), objs, d)
    assert [o["id"] for o in kept] == ["block"]
    assert rejected == [("block", "duplicate id")]
    x1, y1, x2, y2 = crops.padded_box([10, 10, 110, 110], 400, 600)
    with Image.open(d / "block.png") as im:
        # the first box's padded dims, not the second box's
        assert im.size == (x2 - x1, y2 - y1)
        assert im.size != (60, 80)


def test_an_id_that_would_escape_the_refs_dir_is_rejected():
    """Important 4: the model's id becomes a path (refs_dir / f"{id}.png") and,
    downstream, an asset id used the same way in cli.py's out_dir. An id like
    "../escaped" must be rejected before it ever reaches Path(), not silently
    written outside refs_dir."""
    d = Path(tempfile.mkdtemp())
    objs = [{"id": "../escaped", "bbox": [10, 10, 110, 110], "animated": False,
             "views": ["front"]}]
    kept, rejected = crops.crop_objects(_img(), objs, d)
    assert kept == []
    assert rejected == [("../escaped", "unusable id")]
    assert not (d.parent / "escaped.png").exists()


def test_an_id_with_a_slash_is_rejected():
    d = Path(tempfile.mkdtemp())
    objs = [{"id": "a/b", "bbox": [10, 10, 110, 110], "animated": False, "views": ["front"]}]
    kept, rejected = crops.crop_objects(_img(), objs, d)
    assert kept == []
    assert rejected == [("a/b", "unusable id")]


def test_ids_differing_only_in_case_are_rejected_as_duplicates():
    """A case-insensitive filesystem maps both to one crop file, so the second
    would silently overwrite the first and the sheet would show it twice."""
    objs = [
        {"id": "Block", "bbox": [10, 10, 110, 110], "views": ["front"]},
        {"id": "block", "bbox": [200, 300, 260, 380], "views": ["front"]},
    ]
    with tempfile.TemporaryDirectory() as td:
        refs = Path(td) / "refs"
        kept, rejected = crops.crop_objects(_img(), objs, refs)
    assert [k["id"] for k in kept] == ["Block"]
    assert rejected == [("block", "duplicate id")]


# --- contact sheet ----------------------------------------------------------

def test_labelled_sheet_is_written_and_readable():
    d = Path(tempfile.mkdtemp())
    kept, _ = crops.crop_objects(_img(), _objects(), d)
    out = crops.labelled_sheet(kept, d / "_contact_sheet.png")
    assert out.exists()
    with Image.open(out) as im:
        assert im.width > 0 and im.height > 0


def test_labelled_sheet_handles_a_single_entry():
    d = Path(tempfile.mkdtemp())
    kept, _ = crops.crop_objects(_img(), _objects()[:1], d)
    assert crops.labelled_sheet(kept, d / "s.png").exists()


# --- padding ------------------------------------------------------------

def test_the_crop_is_padded_beyond_the_model_s_box():
    """Vision boxes clip: the first live run cut the ears off every rabbit.
    Extra background is free, a clipped silhouette is not."""
    assert crops.padded_box([100, 100, 200, 300], 704, 1526) == (88, 76, 212, 324)


def test_padding_is_clamped_to_the_image():
    assert crops.padded_box([0, 0, 100, 100], 704, 1526) == (0, 0, 112, 112)
    assert crops.padded_box([604, 1426, 704, 1526], 704, 1526) == (592, 1414, 704, 1526)


def test_crop_objects_writes_the_padded_region():
    objs = [{"id": "alpha", "bbox": [100, 100, 200, 300], "views": ["front"]}]
    with tempfile.TemporaryDirectory() as td:
        kept, _ = crops.crop_objects(_img(400, 600), objs, Path(td) / "refs")
        assert Image.open(kept[0]["crop"]).size == (124, 248)   # not the raw 100x200


def test_one_huge_crop_does_not_blow_up_the_contact_sheet():
    """A near-full-playfield box (the live run produced 704x1004) used to size
    every cell, giving a sheet of thousands of pixels of empty space."""
    d = Path(tempfile.mkdtemp())
    objs = [
        {"id": "small", "bbox": [10, 10, 60, 60], "animated": False, "views": ["front"]},
        {"id": "huge", "bbox": [0, 0, 380, 520], "animated": False, "views": ["front"]},
    ]
    kept, rejected = crops.crop_objects(_img(400, 600), objs, d)
    assert rejected == [] and len(kept) == 2
    sheet = crops.labelled_sheet(kept, d / "sheet.png")
    with Image.open(sheet) as im:
        assert im.width <= 2 * (crops._CELL + 32)
        assert im.height <= crops._CELL + 64


# --- containment ------------------------------------------------------------

def _boxed(**kw):
    return [{"id": k, "bbox": v} for k, v in kw.items()]


def test_a_framing_box_reports_what_it_swallows():
    """A conveyor loop, a tray, a panel: its box contains what it frames, so
    its crop shows the contents too."""
    objs = _boxed(frame=[0, 0, 300, 300], brick=[50, 50, 90, 90], bunny=[100, 100, 140, 140])
    assert crops.find_contents(objs) == {"frame": ["brick", "bunny"]}


def test_a_neighbouring_box_is_not_contained():
    objs = _boxed(left=[0, 0, 100, 100], right=[120, 0, 220, 100])
    assert crops.find_contents(objs) == {}


def test_a_box_overlapping_only_at_its_edge_is_not_contained():
    """Model boxes clip their neighbours by a few pixels routinely; that must
    not read as containment."""
    objs = _boxed(big=[0, 0, 200, 200], edge=[190, 190, 290, 290])
    assert crops.find_contents(objs) == {}


def test_equal_boxes_do_not_contain_each_other():
    objs = _boxed(a=[0, 0, 100, 100], b=[0, 0, 100, 100])
    assert crops.find_contents(objs) == {}


# --- blanking -----------------------------------------------------------

def test_blank_contents_paints_a_framed_object_out_of_its_container_crop():
    """`exclude` says it in words and words lose: REFERENCES tells the model to
    take identity from Picture 1, so a loop crop still showing the brick field
    gets the brick field drawn back in. The crop has to agree with the text."""
    tmp = Path(tempfile.mkdtemp())
    image = Image.new("RGB", (400, 400), (20, 20, 40))
    # A bright inner object, entirely inside the outer object's box.
    for x in range(150, 250):
        for y in range(150, 250):
            image.putpixel((x, y), (255, 0, 0))
    objects = [
        {"id": "loop", "bbox": [50, 50, 350, 350], "views": ["front"]},
        {"id": "brick", "bbox": [150, 150, 250, 250], "views": ["front"]},
    ]
    kept, _ = crops.crop_objects(image, objects, tmp / "refs")
    contents = crops.find_contents(kept)
    assert contents == {"loop": ["brick"]}

    before = Image.open(kept[0]["crop"]).convert("RGB")
    assert (255, 0, 0) in before.getdata()
    before.close()

    # Both crops are rewritten now: the container loses what it frames, and the
    # framed object loses the container's wall its own padding dragged in.
    assert crops.blank_contents(kept, contents, image) == ["loop", "brick"]

    after = Image.open(kept[0]["crop"]).convert("RGB")
    try:
        assert (255, 0, 0) not in after.getdata()
        # Filled with the crop's own surroundings, not a foreign colour that
        # would just become a new marking to copy.
        assert after.getpixel((after.width // 2, after.height // 2)) == (20, 20, 40)
    finally:
        after.close()
    # The framed object keeps its identity; only its padding ring is cleared.
    inner = Image.open(kept[1]["crop"]).convert("RGB")
    try:
        assert (255, 0, 0) in inner.getdata()
    finally:
        inner.close()


def test_a_framed_object_loses_the_wall_its_padding_dragged_in():
    """Blanking ran one way only: a dispenser's crop lost the projectile inside
    it while the projectile's crop kept half a dispenser. On a 26px object the
    walls are most of what the model is shown, and it drew them."""
    tmp = Path(tempfile.mkdtemp())
    image = Image.new("RGB", (400, 400), (20, 20, 40))
    for x in range(100, 300):                      # the housing's wall
        for y in range(100, 300):
            image.putpixel((x, y), (200, 200, 200))
    for x in range(180, 220):                      # the object inside it
        for y in range(180, 220):
            image.putpixel((x, y), (255, 0, 0))
    objects = [
        {"id": "housing", "bbox": [100, 100, 300, 300], "views": ["front"]},
        {"id": "pellet", "bbox": [180, 180, 220, 220], "views": ["front"]},
    ]
    kept, _ = crops.crop_objects(image, objects, tmp / "refs")
    contents = crops.find_contents(kept)
    crops.blank_contents(kept, contents, image)

    pellet = Image.open(kept[1]["crop"]).convert("RGB")
    try:
        assert (255, 0, 0) in pellet.getdata(), "the object itself must survive"
        assert (200, 200, 200) not in pellet.getdata(), "the wall must not"
    finally:
        pellet.close()


def test_hand_written_blank_boxes_are_painted_out():
    """The escape hatch for what is not itself a listed object: a value printed
    on a body, a neighbour the padding caught. Whatever the model must not copy
    has to leave the picture, because forbidding it in words loses."""
    tmp = Path(tempfile.mkdtemp())
    image = Image.new("RGB", (400, 400), (20, 20, 40))
    for x in range(60, 160):
        for y in range(60, 160):
            image.putpixel((x, y), (30, 200, 90))
    for x in range(90, 130):                       # a number printed on it
        for y in range(90, 130):
            image.putpixel((x, y), (255, 255, 255))
    objects = [{"id": "piece", "bbox": [60, 60, 160, 160], "views": ["front"],
                "blank": [[90, 90, 130, 130]]}]
    kept, _ = crops.crop_objects(image, objects, tmp / "refs")
    crops.blank_contents(kept, crops.find_contents(kept), image)

    piece = Image.open(kept[0]["crop"]).convert("RGB")
    try:
        assert (255, 255, 255) not in piece.getdata()
        assert (30, 200, 90) in piece.getdata()
    finally:
        piece.close()


def test_a_blanked_box_is_filled_from_its_own_surroundings():
    """One fill for the whole image cannot serve a number printed on a pink body
    and a tile sitting on a dark board at once — and taking that one fill from
    the image's border served neither: a phone screenshot's border is its
    letterbox bars, so every blanked box came back a black slab."""
    tmp = Path(tempfile.mkdtemp())
    image = Image.new("RGB", (300, 300), (0, 0, 0))          # letterboxed source
    for x in range(40, 260):
        for y in range(40, 260):
            image.putpixel((x, y), (30, 30, 60))             # the board
    for x in range(100, 180):
        for y in range(100, 180):
            image.putpixel((x, y), (200, 60, 140))           # a pink body
    for x in range(125, 155):
        for y in range(125, 155):
            image.putpixel((x, y), (255, 255, 255))          # a value printed on it

    objects = [{"id": "piece", "bbox": [100, 100, 180, 180], "views": ["front"],
                "blank": [[125, 125, 155, 155]]}]
    kept, _ = crops.crop_objects(image, objects, tmp / "refs")
    crops.blank_contents(kept, crops.find_contents(kept), image)

    piece = Image.open(kept[0]["crop"]).convert("RGB")
    try:
        assert (255, 255, 255) not in piece.getdata(), "the value must go"
        assert (0, 0, 0) not in piece.getdata(), "and must not be replaced by letterbox"
        # Filled with the body it was printed on.
        assert piece.getpixel((piece.width // 2, piece.height // 2)) == (200, 60, 140)
    finally:
        piece.close()
