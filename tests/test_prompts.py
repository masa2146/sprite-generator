"""Prompt text tests. Pure strings: no I/O, no images, no network."""
import prompts

STYLE = {
    "render": "soft 3D render, glossy plastic",
    "camera": "3/4 front view, slight high angle",
    "lighting": "top-left key light, soft AO",
    "palette": "#FF6B4A #4ECDC4",
    "linework": "dark contour, rounded geometry",
    "realism": "stylized cartoon",
}


def test_references_names_only_the_pictures_actually_sent():
    assert "Picture 2" not in prompts.references_block(style_image=False)
    assert "Picture 2" in prompts.references_block(style_image=True)
    assert "Picture 1" in prompts.references_block(style_image=False)


def test_output_block_asks_for_exactly_one_on_flat_grey():
    block = prompts.output_block("bull totem", square=True)
    assert "Exactly one bull totem" in block
    assert "Square image." in block
    assert "#808080" in block


def test_do_not_draw_puts_this_assets_exclusion_before_the_fixed_bans():
    block = prompts.do_not_draw("the coins stacked behind it")
    lines = block.splitlines()
    assert lines[0] == "DO NOT DRAW"
    assert lines[1] == "- the coins stacked behind it"
    assert "any text, numbers, labels or logos" in block


def test_do_not_draw_without_an_exclusion_still_carries_the_bans():
    assert "more than one copy of the object" in prompts.do_not_draw()


def test_field_block_ends_with_view_and_carries_the_measured_palette():
    block = prompts.field_block(
        {"subject": "a bull totem", "form": "head over a plinth",
         "palette": ["#434375", "#FFFFFF"]},
        "three_quarter")
    assert block.startswith("OBJECT")
    assert "#434375" in block
    last = block.splitlines()[-1]
    assert last.startswith("VIEW")
    assert "three-quarter" in last


def test_style_line_drops_the_camera():
    # The prompt already carries a VIEW line per object; a camera angle in the
    # style line contradicts it on every view but front.
    line = prompts.style_line(STYLE)
    assert "3/4 front view" not in line
    assert line.startswith("soft 3D render")
    assert line.endswith("#FF6B4A #4ECDC4")


def test_style_line_skips_a_missing_field_without_leaving_a_gap():
    line = prompts.style_line({"render": "flat vector", "palette": "#000"})
    assert line == "flat vector, #000"


def test_normalise_views_keeps_pool_order_and_never_returns_empty():
    assert prompts.normalise_views(["side", "front"]) == ["front", "side"]
    assert prompts.normalise_views(["nope"]) == ["front"]
    assert prompts.normalise_views([]) == ["front"]


def test_a_rotation_pulls_in_the_front_frame_it_is_turned_from():
    assert prompts.normalise_views(["rotated_90"]) == ["front", "rotated_90"]


def test_asset_prompt_orders_the_blocks():
    obj = {"id": "bull_totem", "subject": "a bull totem", "palette": ["#434375"]}
    text = prompts.asset_prompt(obj, "front", STYLE)
    # ART STYLE is looked up as "\n\nART STYLE" (its actual heading, preceded by
    # the blank line every block join leaves) rather than the bare word: the
    # preserved REFERENCES prose says "...redraw the object cleanly at full
    # resolution in the ART STYLE below", a forward reference that contains the
    # same words and sits earlier in the text than the real heading. A bare
    # substring search finds that phrase first and misreports the block order.
    markers = {"REFERENCES": "REFERENCES", "OBJECT": "OBJECT",
               "ART STYLE": "\n\nART STYLE", "OUTPUT": "OUTPUT",
               "DO NOT DRAW": "DO NOT DRAW"}
    for earlier, later in [("REFERENCES", "OBJECT"), ("OBJECT", "ART STYLE"),
                           ("ART STYLE", "OUTPUT"), ("OUTPUT", "DO NOT DRAW")]:
        assert text.index(markers[earlier]) < text.index(markers[later]), f"{earlier} after {later}"


def test_asset_prompt_names_one_picture_when_there_is_no_style_image():
    obj = {"id": "bull_totem", "subject": "a bull totem"}
    text = prompts.asset_prompt(obj, "front", STYLE, style_image=False)
    assert "Picture 2" not in text


def test_a_contained_object_becomes_a_do_not_draw_line():
    obj = {"id": "tray", "subject": "a tray"}
    text = prompts.asset_prompt(obj, "front", STYLE, contents=["puck"])
    assert "puck" in text.split("DO NOT DRAW")[1]


def test_a_long_contained_list_is_summarised_not_dumped():
    names = [f"obj_{i}" for i in range(9)]
    clause = prompts.exclusion_clause(names)
    assert "obj_8" not in clause
    assert "5 other" in clause or "others" in clause
