# Skill-First Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Görsel üretim API'lerini (OpenRouter, yerel spritepipe) tamamen sök; hayatta kalan saf-PIL kodu skill'lerin `scripts/` klasörlerine taşı; üç skill'i tek zincire bağla; çalışma alanını `sprites-generated/` + venv düzenine geçir.

**Architecture:** `spritegen` Python paketi ve 10 alt komutlu CLI ölür. Prompt metinleri, kırpma/temizleme geometrisi ve zemin kesici saf string ve saf PIL olduğu için yaşar ve `.claude/skills/sprite-brief/scripts/` altına iner — skill başka projeye symlink'lendiğinde araçları beraberinde gider. `sprite-brief` tek girdi dosyası (`analysis.json` v2) okur, kırpmaya kendi karar verir, iki bölümlü `review.html` yazar (inceleme + elle üretim prompt'ları), sonra `procedural-sprites`'a devreder. `procedural-sprites` ortak sanat yönünü ana thread'de yazar, kodu asset başına bir subagent'a yazdırır.

**Tech Stack:** Python 3.11+, Pillow, numpy, pytest. Ağ kütüphanesi yok, model ağırlığı yok.

**Spec:** `docs/specs/2026-08-10-skill-first-pipeline-design.md`

## Global Constraints

- Python `>=3.11`. Bağımlılık **yalnızca** `pillow` + `numpy`. `requests`, `rembg` ve `tomllib` tabanlı pack okuma repoda kalmaz.
- Skill scripts'i kurulum gerektirmez: `python3 <skill>/scripts/<x>.py`. `pip install -e .` hiçbir yerde geçmez.
- Repo testleri geliştiricinin kendi `python3`'ü ile koşar (`pillow` + `numpy` kurulu olmalı). `sprites-generated/.venv` yalnızca **üretilen** sprite scriptleri içindir; testler onu kullanmaz.
- Testler ağ çağrısı yapmaz, model ağırlığı indirmez, `pytest` fixture/plugin kullanmaz — düz fonksiyonlar ve `try/finally` (mevcut kalıp).
- Kod, docstring, yorum ve commit mesajları **İngilizce**. Plan/spec dokümanları Türkçe.
- Yorumlar *neden*i anlatır ve mümkünse ölçülmüş bir hataya dayanır (repo kalıbı). Taşınan koddaki mevcut yorumlar silinmez.
- Hiçbir kutu, hiçbir nesne, hiçbir soru sessizce düşmez — reddedilen her şey sebebiyle basılır.
- Prompt metinleri (`REFERENCES`, `OBJECT`/`FORM`/`DETAIL`/`VIEW`, `ART STYLE`, `OUTPUT`, `DO NOT DRAW`, `#808080`) korunur. Ölen yalnızca onları bir endpoint'e gönderen katman.
- Skill dosyalarında ve `.py`'lerde şu kelimeler geçmez: `openrouter`, `rembg`, `requests`, `transport`, `key_env`, `base_url`, `api_key`. (`docs/` hariç — tarihsel kayıt.)

---

## File Structure

**Yaratılacak:**

| dosya | sorumluluğu |
|---|---|
| `.claude/skills/sprite-brief/scripts/prompts.py` | elle üretim prompt'unun tüm metni: bloklar, sabit banlar, view havuzu, stil satırı |
| `.claude/skills/sprite-brief/scripts/crops.py` | kutu doğrulama, padding, kırpma, iç içe kutuların silinmesi, etiketli contact sheet |
| `.claude/skills/sprite-brief/scripts/refclean.py` | crop temizliği: letterbox, ışık rampası, upscale, satır düzleme, palet ölçümü |
| `.claude/skills/sprite-brief/scripts/cut.py` | elle üretilmiş PNG'nin düz zeminini kesme (`--key` varsayılan, `--glow`), saydam kareye ortalama |
| `.claude/skills/sprite-brief/scripts/brief.py` | akış: analiz oku → kırpma kararı → temizle → `review.html` yaz |
| `tests/conftest.py` | skill `scripts/` yolunu `sys.path`'e ekler |
| `tests/test_prompts.py`, `test_crops.py`, `test_refclean.py`, `test_cut.py` | yukarıdakilerin testleri |

**Silinecek:** `spritegen/` (tamamı), `tests/test_build.py`, `test_client.py`, `test_config.py`, `test_env.py`, `test_export.py`, `test_make.py`, `test_packwriter.py`, `test_post.py`, `test_cutout.py`, `test_extract.py`, `.env`, `.env.example`.

**Değişecek:** üç `SKILL.md`, `README.md`, `CLAUDE.md`, `.gitignore`, `pyproject.toml`.

---

### Task 1: Test iskeleti ve `prompts.py`

Prompt metinlerinin tamamı tek dosyaya iner. Bu dosya saf string'dir; hiçbir yeri ağa, dosya sistemine veya PIL'e dokunmaz.

**Files:**
- Create: `.claude/skills/sprite-brief/scripts/prompts.py`
- Create: `tests/conftest.py`
- Create: `tests/test_prompts.py`
- Read (kaynak, henüz silinmez): `spritegen/config.py:24-158`, `spritegen/vision.py:204-258`, `spritegen/extract.py:180-245`, `spritegen/brief.py:37-51,108-124`

**Interfaces:**
- Produces: `prompts.BG_CLAUSE: str`, `prompts.references_block(style_image: bool = True) -> str`, `prompts.REFERENCES_BLOCK: str`, `prompts.output_block(subject: str = "copy of the object described above", square: bool = False) -> str`, `prompts.FIXED_BANS: str`, `prompts.do_not_draw(exclude: str = "") -> str`, `prompts.VIEW_POOL: dict[str, str]`, `prompts.DEFAULT_VIEW: str`, `prompts.ROTATION_DEGREES: dict[str, int]`, `prompts.normalise_views(views) -> list[str]`, `prompts.field_block(obj: dict, view: str) -> str`, `prompts.style_line(style: dict) -> str`, `prompts.exclusion_names(ids) -> list[str]`, `prompts.exclusion_clause(ids) -> str`, `prompts.asset_prompt(obj: dict, view: str, style: dict, contents=None) -> str`

- [ ] **Step 1: `tests/conftest.py`'yi yaz**

```python
"""Tests import the skill's scripts straight from the checkout.

There is no package and no install step any more, so the path the skill
itself uses at runtime is the path the tests must use too — anything else
would test a copy.
"""
import sys
from pathlib import Path

SCRIPTS = (Path(__file__).resolve().parent.parent
           / ".claude" / "skills" / "sprite-brief" / "scripts")
sys.path.insert(0, str(SCRIPTS))
```

- [ ] **Step 2: Failing test'leri yaz**

`tests/test_prompts.py`:

```python
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
    for earlier, later in [("REFERENCES", "OBJECT"), ("OBJECT", "ART STYLE"),
                           ("ART STYLE", "OUTPUT"), ("OUTPUT", "DO NOT DRAW")]:
        assert text.index(earlier) < text.index(later), f"{earlier} after {later}"


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
```

- [ ] **Step 3: Test'lerin doğru sebeple patladığını gör**

Run: `python3 -m pytest tests/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'prompts'`

- [ ] **Step 4: `prompts.py`'yi yaz**

`spritegen/config.py:24-158`'den `BG_CLAUSE`, `_PICTURE_1`, `_PICTURE_2`, `references_block`, `REFERENCES_BLOCK`, `output_block`, `FIXED_BANS`, `do_not_draw` **yorumlarıyla birlikte** kopyala. `TILE_OUTPUT` kopyalanmaz — yalnızca ölen pack yolundaki `cutout = false` asset'leri kullanıyordu.

`spritegen/vision.py:204-258`'den `VIEW_POOL`, `DEFAULT_VIEW`, `ROTATION_DEGREES`, `FIELD_LABELS`, `field_block` kopyala. `field_block`'un docstring'i "paid path" ve "brief" diyor — "the review page and the hand-generation prompt share this" olarak güncelle.

`spritegen/extract.py:180-245`'ten `CONTAINED_RATIO` hariç `MAX_NAMED_CONTENTS`, `exclusion_names`, `exclusion_clause` kopyala (`CONTAINED_RATIO` ve `find_contents` `crops.py`'a gidiyor — Task 2).

`spritegen/brief.py:37-51`'den `normalise_views`'i kopyala, `vision.` öneklerini kaldır.

Yeni yazılacak iki şey:

```python
# The order the fields read best in, and deliberately not the schema's order:
# palette last, after the visual description it tints.
_STYLE_ORDER = ("render", "lighting", "linework", "realism", "palette")


def style_line(style: dict) -> str:
    """The ART STYLE line: the style fields joined, camera excluded.

    Camera is excluded here and only here. The prompt carries its own VIEW line
    per object, so an angle in the style line contradicts it on every view but
    front — the exact bug this ordering was pulled apart to fix. The field is
    still read, by the procedural path, which turns it into the shared camera
    tilt constant rather than into prompt text.
    """
    parts = [str(style[field]).strip() for field in _STYLE_ORDER
             if isinstance(style.get(field), str) and style[field].strip()]
    return ", ".join(parts)


def asset_prompt(obj: dict, view: str, style: dict, contents=None,
                 style_image: bool = True) -> str:
    """One paste-ready prompt for this object in this view.

    Structured blocks rather than a paragraph: in the run-on form the clauses a
    model skips were the ones buried mid-sentence, and the measured failures
    were twelve balls instead of one and HUD labels that kept their text.
    """
    return "\n\n".join([
        references_block(style_image),
        field_block(obj, view),
        f"ART STYLE  {style_line(style)}",
        output_block(obj["id"].replace("_", " "), square=True),
        do_not_draw(exclusion_clause(contents) if contents else ""),
    ])
```

- [ ] **Step 5: Test'lerin geçtiğini gör**

Run: `python3 -m pytest tests/test_prompts.py -v`
Expected: PASS (14 test)

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/sprite-brief/scripts/prompts.py tests/conftest.py tests/test_prompts.py
git commit -m "feat: move the prompt text into the skill, away from the client

The blocks are plain strings and never needed an endpoint: they are what
gets pasted into Gemini or ChatGPT by hand. style_line drops camera, since
the prompt already carries a VIEW line that an angle would contradict."
```

---

### Task 2: `crops.py`

Kutu geometrisi ve contact sheet. Saf PIL; hiçbir yeri ağa dokunmaz.

**Files:**
- Create: `.claude/skills/sprite-brief/scripts/crops.py`
- Create: `tests/test_crops.py`
- Read (kaynak): `spritegen/extract.py:21-180,180-340`, `tests/test_extract.py:30-160,591-620,691-715,775-980`

**Interfaces:**
- Consumes: yok
- Produces: `crops.MIN_EDGE = 16`, `crops.MAX_AREA_RATIO = 0.9`, `crops.BOX_PAD = 0.12`, `crops.CONTAINED_RATIO = 0.9`, `crops.reject_reason(bbox, img_w, img_h) -> str | None`, `crops.screen_objects(objects, img_w, img_h) -> tuple[list[dict], list]`, `crops.padded_box(bbox, img_w, img_h) -> tuple[int,int,int,int]`, `crops.crop_objects(image, objects, refs_dir) -> tuple[list[dict], list]`, `crops.labelled_sheet(entries, out_path) -> Path`, `crops.find_contents(objects) -> dict`, `crops.blank_contents(kept, contents, image) -> list[str]`, `crops.ring_median(image, box, margin=6) -> tuple[int,int,int]`

- [ ] **Step 1: Failing test'leri yaz**

`tests/test_crops.py`. `tests/test_extract.py`'den şu testleri taşı — gövdeleri aynen, yalnızca `from spritegen import extract` importu `import crops` olur ve gövdelerdeki `extract.` çağrıları `crops.` yapılır (takma ad kullanma; dosya artık `crops` modülünü test ediyor ve iki isim taşımasının bir sebebi yok):

`test_a_normal_box_is_accepted`, `test_a_box_outside_the_image_is_rejected`, `test_a_zero_or_inverted_box_is_rejected`, `test_a_box_covering_the_whole_image_is_rejected`, `test_a_tiny_box_is_rejected`, `test_a_malformed_box_is_rejected`, `test_crop_objects_writes_one_file_per_object`, `test_crop_dimensions_match_the_padded_box`, `test_a_rejected_box_is_reported_and_skipped`, `test_an_object_without_an_id_is_rejected_not_crashed`, `test_a_duplicate_id_is_rejected_and_the_first_crop_survives`, `test_an_id_that_would_escape_the_refs_dir_is_rejected`, `test_an_id_with_a_slash_is_rejected`, `test_labelled_sheet_is_written_and_readable`, `test_labelled_sheet_handles_a_single_entry`, `test_ids_differing_only_in_case_are_rejected_as_duplicates`, `test_the_crop_is_padded_beyond_the_model_s_box`, `test_padding_is_clamped_to_the_image`, `test_crop_objects_writes_the_padded_region`, `test_one_huge_crop_does_not_blow_up_the_contact_sheet`, `test_a_framing_box_reports_what_it_swallows`, `test_a_neighbouring_box_is_not_contained`, `test_a_box_overlapping_only_at_its_edge_is_not_contained`, `test_equal_boxes_do_not_contain_each_other`, `test_blank_contents_paints_a_framed_object_out_of_its_container_crop`, `test_a_framed_object_loses_the_wall_its_padding_dragged_in`, `test_hand_written_blank_boxes_are_painted_out`, `test_a_blanked_box_is_filled_from_its_own_surroundings`.

Dosya başına şu import bloğunu koy:

```python
"""Box geometry and crop tests. No network, no vision, no prompts."""
import tempfile
from pathlib import Path

from PIL import Image

import crops
```

ve taşınan testlerdeki `extract.` çağrılarını `crops.` yap.

- [ ] **Step 2: Test'lerin patladığını gör**

Run: `python3 -m pytest tests/test_crops.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'crops'`

- [ ] **Step 3: `crops.py`'yi yaz**

`spritegen/extract.py`'den şunları **yorumlarıyla birlikte** kopyala: modül docstring'i (yeniden yazılır, aşağıda), `MIN_EDGE`, `MAX_AREA_RATIO`, `BOX_PAD`, `_LABEL_H`, `_PAD`, `_CELL`, `_ID_RE`, `reject_reason`, `screen_objects`, `padded_box`, `crop_objects`, `labelled_sheet`, `CONTAINED_RATIO`, `_area`, `find_contents`, `ring_median`, `blank_contents`.

Kopyalanmaz: `DEFAULT_MAX_OBJECTS`, `MAX_NAMED_CONTENTS`, `exclusion_names`, `exclusion_clause` (Task 1'de `prompts.py`'a gitti), `pack_text` (ölür).

`from . import packwriter/post/vision` importları silinir. `blank_contents` `post`'tan bir şey kullanıyorsa (kullanmıyor; `ring_median` dosyanın kendisinde) dokunma.

Yeni modül docstring'i:

```python
"""Box geometry: validate, pad, crop, blank and sheet.

Nothing here decides anything — it takes boxes someone else chose and turns
them into files on disk. A box that cannot be used is rejected with a reason
and reported; it is never dropped silently, because a crop that quietly went
missing is a defect nobody sees until the sprite is wrong.
"""
```

- [ ] **Step 4: Test'lerin geçtiğini gör**

Run: `python3 -m pytest tests/test_crops.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/sprite-brief/scripts/crops.py tests/test_crops.py
git commit -m "feat: move box geometry into the skill as crops.py

The half of extract.py that never touched a vision model: validate, pad,
crop, blank what a box swallowed, sheet it. The pack-writing half stays
behind to be deleted with the rest of the client."
```

---

### Task 3: `refclean.py`

Crop temizliği aynen taşınır; bugüne kadar kendi test dosyası yoktu — testleri `test_extract.py`'nin içinde duruyor.

**Files:**
- Create: `.claude/skills/sprite-brief/scripts/refclean.py` (git mv ile)
- Create: `tests/test_refclean.py`
- Read: `spritegen/refclean.py`, `tests/test_extract.py:817-902`

**Interfaces:**
- Consumes: yok
- Produces: `refclean.MIN_LONG_EDGE = 768`, `refclean.background_colour(img) -> tuple[int,int,int]`, `refclean.strip_letterbox(img, fill=None) -> Image`, `refclean.flat_field(img) -> Image`, `refclean.upscale(img, min_long=MIN_LONG_EDGE) -> Image`, `refclean.row_flatten(img) -> Image`, `refclean.palette(img, count=5) -> list[str]`, `refclean.clean(img, *, flatten_rows=False, min_long=MIN_LONG_EDGE) -> Image`, `refclean.clean_crops(entries, *, min_long=MIN_LONG_EDGE) -> None` — her girdiye `entry["palette"]` yazar

- [ ] **Step 1: Dosyayı taşı**

```bash
git mv spritegen/refclean.py .claude/skills/sprite-brief/scripts/refclean.py
```

İçinde `from . import` yok; değişiklik gerekmiyor.

- [ ] **Step 2: Test'leri taşı ve çalıştır**

`tests/test_refclean.py` — `tests/test_extract.py:817-902`'den şu testleri taşı: `test_refclean_removes_what_a_screenshot_adds`, `test_row_flatten_erases_along_the_run_and_spares_the_rails`, `test_palette_reports_colours_that_are_really_there`, `test_flattened_rows_skip_the_flat_field`, `test_row_flatten_never_invents_a_colour`. `from spritegen import refclean` → `import refclean`.

Dosya başı:

```python
"""Crop cleanup tests. A crop lifted from a phone screenshot carries three
defects that were each measured coming back in the generated sprite: pixel
steps, a top-to-bottom lighting ramp, and letterbox bars."""
import refclean
from PIL import Image
```

- [ ] **Step 3: Eksik testi ekle — ölçülen palet crop'a yazılıyor mu**

`clean_crops`'un `entry["palette"]`'i doldurduğunu hiçbir test doğrulamıyor; prompt'un `PALETTE` satırı buna dayanıyor.

Dosyanın import bloğu şu hâle gelir:

```python
import tempfile
from pathlib import Path

import refclean
from PIL import Image
```

```python
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
```

- [ ] **Step 4: Test'lerin geçtiğini gör**

Run: `python3 -m pytest tests/test_refclean.py -v`
Expected: PASS (6 test)

- [ ] **Step 5: Commit**

```bash
git add -A .claude/skills/sprite-brief/scripts/refclean.py tests/test_refclean.py spritegen/refclean.py
git commit -m "feat: move refclean into the skill, with tests of its own

Its tests were living inside test_extract.py, which is about to be deleted;
they move to a file named after what they cover, plus one the suite never
had: that clean_crops actually records the measured palette the PALETTE
line in every prompt depends on."
```

---

### Task 4: `cut.py` — saf numpy kesici, `--key` varsayılan

Matting modeli (rembg) gider. Prompt zaten düz `#808080` zemin garantiliyor; `--key` tam olarak o durumu kesiyor.

**Files:**
- Create: `.claude/skills/sprite-brief/scripts/cut.py`
- Create: `tests/test_cut.py`
- Read: `spritegen/cutout.py`, `spritegen/post.py:150-168`, `tests/test_post.py:14-57`, `tests/test_cutout.py`

**Interfaces:**
- Consumes: yok
- Produces: `cut.key_background(data: bytes, tol: float = 14.0) -> Image`, `cut.cut_glow(data: bytes) -> Image`, `cut.trim_and_pad(img, margin: float = 0.04) -> Image`, `cut.iter_pngs(paths) -> list[Path]`, `cut.main(argv=None) -> int`

- [ ] **Step 1: Failing test'leri yaz**

`tests/test_cut.py`:

```python
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
```

- [ ] **Step 2: Test'lerin patladığını gör**

Run: `python3 -m pytest tests/test_cut.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cut'`

- [ ] **Step 3: `cut.py`'yi yaz**

`spritegen/cutout.py`'yi kopyala, sonra:

- `from . import post` satırını sil; `spritegen/post.py:150-168`'deki `trim_and_pad`'i **docstring ve yorumlarıyla** bu dosyaya taşı.
- `main()` içindeki mod seçimini değiştir:

```python
    if args.glow:
        cut = cut_glow
    else:
        # Key by default: the prompt asks for a flat #808080 backdrop, which is
        # exactly the case a border flood cuts exactly. The matting model this
        # used to fall back on was for arbitrary backdrops and cost a few
        # hundred megabytes of weights to download.
        cut = lambda data: key_background(data, args.tol)
```

- `--key` argümanını `argparse`'ta bırak ama yardımını güncelle: `"(default) asset sheet on one flat colour: flood the background colour in from the border"`.
- `prog="spritegen cut"` → `prog="cut"`.
- Modül docstring'ini güncelle: "Cut the flat backdrop out of PNGs generated by hand. The prompt asks for `#808080` because hosted models do not emit reliable alpha."

- [ ] **Step 4: Test'lerin geçtiğini gör**

Run: `python3 -m pytest tests/test_cut.py -v`
Expected: PASS (7 test)

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/sprite-brief/scripts/cut.py tests/test_cut.py
git commit -m "feat: cut the backdrop with numpy alone, keying by default

The matting model existed for arbitrary backdrops; the prompt guarantees a
flat #808080 one, which a border flood cuts exactly and without a few
hundred megabytes of weights. --glow is unchanged."
```

---

### Task 5: `brief.py`'yi yeni modüllerin üstüne taşı (davranış aynı)

Bu task davranış değiştirmez — yalnızca ev değiştirir. Şema v2 Task 7'de gelir.

**Files:**
- Create: `.claude/skills/sprite-brief/scripts/brief.py`
- Modify: `tests/test_brief.py`
- Read: `spritegen/brief.py`

**Interfaces:**
- Consumes: `prompts.*` (Task 1), `crops.*` (Task 2), `refclean.clean_crops` (Task 3)
- Produces: `brief.BriefError`, `brief.load_analysis(path) -> tuple[str, list[dict]]`, `brief.page(entries, style_image, title) -> str`, `brief.main(argv=None) -> int`

- [ ] **Step 1: `tests/test_brief.py`'yi yeni importlara çevir ve ölen testleri at**

`from spritegen import brief` → `import brief`. Şu testleri sil (prompt'a taşındılar, Task 1'de karşılıkları var): `test_views_are_filtered_to_the_pool_and_ordered`, `test_a_view_outside_the_pool_is_dropped`, `test_no_usable_view_falls_back_to_front`, `test_the_prompt_labels_what_each_uploaded_image_is_for`, `test_every_prompt_forbids_more_than_one_copy`, `test_every_prompt_forbids_text`, `test_the_view_phrase_comes_from_the_pool`, `test_an_unknown_view_falls_back_to_front`, `test_the_state_line_appears_only_when_a_state_is_given`, `test_contained_objects_become_a_do_not_draw_line`, `test_no_contained_objects_means_no_such_line`, `test_a_long_contained_list_is_summarised`, `test_one_extra_contained_object_is_singular`, `test_missing_subject_fields_do_not_break_the_block`, `test_the_style_line_is_repeated_in_full`.

Kalan testlerde `brief.asset_prompt(...)` çağrısı varsa `prompts.asset_prompt(...)` yap ve dosyaya `import prompts` ekle.

- [ ] **Step 2: Test'lerin patladığını gör**

Run: `python3 -m pytest tests/test_brief.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'brief'`

- [ ] **Step 3: `brief.py`'yi taşı ve importlarını çevir**

```bash
git mv spritegen/brief.py .claude/skills/sprite-brief/scripts/brief.py
```

Sonra dosyada:

- `from . import config` / `extract` / `refclean` / `vision` → `import crops`, `import prompts`, `import refclean`
- `normalise_views` ve `asset_prompt` fonksiyonlarını sil (artık `prompts.py`'da)
- `extract.crop_objects` → `crops.crop_objects`, `extract.find_contents` → `crops.find_contents`, `extract.blank_contents` → `crops.blank_contents`, `extract.labelled_sheet` → `crops.labelled_sheet`
- `load_analysis` içinde `normalise_views(...)` → `prompts.normalise_views(...)`
- `asset_prompt(obj, view, style, contents.get(obj["id"]))` → `prompts.asset_prompt(obj, view, style, contents.get(obj["id"]))`
  — bu aşamada `style` hâlâ string; `prompts.style_line` bir dict bekliyor, o yüzden geçici olarak `asset_prompt`'a `{"render": style}` verme **yapma**: bunun yerine `main()` içindeki çağrıyı `style` bir dict'e sarmadan bırak ve Task 7'de şema v2 ile düzelt. Geçici köprü olarak `load_analysis` string style'ı `{"render": style}` dict'ine çevirsin ve şu yorumu taşısın:

```python
    # Schema v1 carries style as one line. v2 (the next task) replaces this
    # with the six-field object image-style produces; wrapping it here keeps
    # the move honest — one change at a time.
    style = {"render": style.strip()}
```

- `--pack` argümanını, `if args.pack:` bloğunu ve `config`/`extract.pack_text` kullanımını **sil**
- `prog="spritegen brief"` → `prog="brief"`
- `page()`'in `figcaption`'larındaki `image1`/`image2` metinleri `Picture 1`/`Picture 2` olarak düzelt (prompt'ta o adlar geçiyor; iki farklı ad aynı görsel için tam olarak bu akışın kaçındığı karışıklık)

- [ ] **Step 4: Test'lerin geçtiğini gör**

Run: `python3 -m pytest tests/test_brief.py -v`
Expected: PASS

- [ ] **Step 5: Tüm suite'i çalıştır**

Run: `python3 -m pytest tests/test_prompts.py tests/test_crops.py tests/test_refclean.py tests/test_cut.py tests/test_brief.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A .claude/skills/sprite-brief/scripts/brief.py tests/test_brief.py spritegen/brief.py
git commit -m "feat: run brief off the skill's own modules

Same behaviour, new home: prompts, crops and refclean now come from the
skill's scripts/ rather than from the package. The --pack flag goes with
the endpoint it was written for."
```

---

### Task 6: Ölü kodu sil

**Files:**
- Delete: `spritegen/` (kalan her şey), `tests/test_build.py`, `test_client.py`, `test_config.py`, `test_env.py`, `test_export.py`, `test_make.py`, `test_packwriter.py`, `test_post.py`, `test_cutout.py`, `test_extract.py`, `.env`, `.env.example`
- Modify: `pyproject.toml`, `.gitignore`

**Interfaces:**
- Consumes: Task 1-5'in tamamı (hepsi taşındıktan sonra çalışır)
- Produces: yok

- [ ] **Step 1: Kalan bağımlılığı doğrula**

Run: `grep -rn "spritegen" tests/ .claude/skills/ --include=*.py --include=*.md`
Expected: yalnızca dokümantasyon metni; hiçbir `import spritegen` kalmamalı. Kalan varsa önce onu düzelt.

- [ ] **Step 2: Sil**

```bash
git rm -r spritegen
git rm tests/test_build.py tests/test_client.py tests/test_config.py tests/test_env.py \
       tests/test_export.py tests/test_make.py tests/test_packwriter.py \
       tests/test_post.py tests/test_cutout.py tests/test_extract.py
git rm .env.example
rm -f .env
```

- [ ] **Step 3: `pyproject.toml`'u kırp**

Tüm dosya şu hâle gelir:

```toml
# No package and no console script: the skills carry their own scripts, so
# there is nothing to install. This file exists for pytest's settings alone.
[tool.pytest.ini_options]
testpaths = ["tests"]
```

`pythonpath` satırı gitmeli — `tests/conftest.py` yolu kendi ekliyor.

- [ ] **Step 4: `.gitignore`'u güncelle**

```gitignore
sprites-generated/
sprites
__pycache__/
*.pyc
.superpowers/
.gstack/
.DS_Store
.pytest_cache/
```

(`out/`, `packs`, `briefs`, `.env`, `*.toml.bak`, `*.egg-info/` satırları gider — hiçbiri artık üretilmiyor.)

- [ ] **Step 5: Suite'i çalıştır**

Run: `python3 -m pytest -v`
Expected: PASS — 5 dosya, ağ çağrısı yok

- [ ] **Step 6: Yasak kelime taraması**

Run: `grep -rniE "openrouter|rembg|requests|transport|key_env|base_url|api_key" --include=*.py --include=*.toml .claude tests pyproject.toml`
Expected: çıktı yok

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: delete the generation client and everything it carried

Ten subcommands, two HTTP transports, the pack format, the key handling and
the matting model all existed to reach an image endpoint. Nothing reaches
one any more. What survived moved into the skills in the previous commits."
```

---

### Task 7: `analysis.json` v2 — altı alanlı stil, kaynak başına görsel, opsiyonel bbox

**Files:**
- Modify: `.claude/skills/sprite-brief/scripts/brief.py`
- Modify: `tests/test_brief.py`

**Interfaces:**
- Consumes: `prompts.normalise_views`
- Produces: `brief.STYLE_FIELDS: tuple[str, ...]` = `("render", "camera", "lighting", "palette", "linework", "realism")`, `brief.load_analysis(path) -> Analysis` — burada `Analysis` bir dataclass:

```python
@dataclass
class Analysis:
    style: dict          # six fields, every one a non-empty string
    style_source: dict   # field -> "kullanıcı" | "stil görseli" | "referans" | "ölçüm" | "varsayılan"
    style_image: Path | None
    objects: list[dict]  # each with id, views, animated, source: Path|None, bbox: list|None
```

- [ ] **Step 1: Failing test'leri yaz**

`tests/test_brief.py`'ye ekle:

```python
import json
import tempfile
from pathlib import Path

from PIL import Image

FULL_STYLE = {
    "render": "soft 3D render", "camera": "3/4 front view",
    "lighting": "top-left key", "palette": "#FF6B4A",
    "linework": "dark contour", "realism": "stylized cartoon",
}


def _analysis_dir(payload, images=("shot.png",)):
    d = Path(tempfile.mkdtemp())
    for name in images:
        Image.new("RGB", (200, 200), (90, 90, 120)).save(d / name)
    path = d / "analysis.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_the_six_style_fields_are_read_as_an_object():
    path = _analysis_dir({
        "style": FULL_STYLE, "style_image": "shot.png",
        "objects": [{"id": "a", "subject": "a thing", "bbox": [10, 10, 90, 90]}],
    })
    parsed = brief.load_analysis(path)
    assert parsed.style["camera"] == "3/4 front view"
    assert parsed.style_image.name == "shot.png"


def test_a_missing_style_field_is_named_in_the_error():
    partial = dict(FULL_STYLE)
    del partial["lighting"]
    path = _analysis_dir({"style": partial,
                          "objects": [{"id": "a", "subject": "x"}]})
    try:
        brief.load_analysis(path)
        assert False, "a missing style field must not pass"
    except brief.BriefError as exc:
        assert "lighting" in str(exc)


def test_a_style_given_as_one_string_is_rejected_with_the_shape_it_wants():
    path = _analysis_dir({"style": "glossy cartoon",
                          "objects": [{"id": "a", "subject": "x"}]})
    try:
        brief.load_analysis(path)
        assert False, "schema v1 style must not pass"
    except brief.BriefError as exc:
        assert "render" in str(exc) and "camera" in str(exc)


def test_an_unspecified_style_source_reads_as_belirtilmemis():
    path = _analysis_dir({"style": FULL_STYLE,
                          "style_source": {"render": "kullanıcı"},
                          "objects": [{"id": "a", "subject": "x"}]})
    parsed = brief.load_analysis(path)
    assert parsed.style_source["render"] == "kullanıcı"
    assert parsed.style_source["palette"] == "belirtilmemiş"


def test_paths_resolve_against_the_analysis_file_not_the_cwd():
    path = _analysis_dir({"style": FULL_STYLE, "style_image": "shot.png",
                          "objects": [{"id": "a", "subject": "x"}]})
    parsed = brief.load_analysis(path)
    assert parsed.style_image.is_absolute()
    assert parsed.style_image.exists()


def test_an_object_falls_back_to_the_style_image_for_its_source():
    path = _analysis_dir({"style": FULL_STYLE, "style_image": "shot.png",
                          "objects": [{"id": "a", "subject": "x",
                                       "bbox": [10, 10, 90, 90]}]})
    obj = brief.load_analysis(path).objects[0]
    assert obj["source"].name == "shot.png"


def test_an_object_may_name_its_own_source():
    path = _analysis_dir({"style": FULL_STYLE, "style_image": "shot.png",
                          "objects": [{"id": "a", "subject": "x",
                                       "source": "other.png"}]},
                         images=("shot.png", "other.png"))
    assert brief.load_analysis(path).objects[0]["source"].name == "other.png"


def test_an_object_with_no_image_anywhere_is_allowed():
    path = _analysis_dir({"style": FULL_STYLE,
                          "objects": [{"id": "a", "subject": "x"}]},
                         images=())
    assert brief.load_analysis(path).objects[0]["source"] is None


def test_a_bbox_without_an_image_names_the_object():
    path = _analysis_dir({"style": FULL_STYLE,
                          "objects": [{"id": "a", "subject": "x",
                                       "bbox": [1, 1, 9, 9]}]},
                         images=())
    try:
        brief.load_analysis(path)
        assert False, "a box with nothing to cut it out of must not pass"
    except brief.BriefError as exc:
        assert "a" in str(exc) and "bbox" in str(exc)


def test_a_missing_source_file_names_the_path():
    path = _analysis_dir({"style": FULL_STYLE,
                          "objects": [{"id": "a", "subject": "x",
                                       "source": "gone.png"}]},
                         images=())
    try:
        brief.load_analysis(path)
        assert False, "a source that is not on disk must not pass"
    except brief.BriefError as exc:
        assert "gone.png" in str(exc)


def test_a_bbox_is_optional_now():
    path = _analysis_dir({"style": FULL_STYLE, "style_image": "shot.png",
                          "objects": [{"id": "a", "subject": "x"}]})
    assert brief.load_analysis(path).objects[0]["bbox"] is None
```

Eski v1 testlerini (`test_load_analysis_returns_style_and_objects`, `test_a_missing_style_is_named_in_the_error`, `test_a_bad_bbox_names_the_object_and_the_field`) yeni şemaya göre güncelle: `style` artık dict, `bbox` artık opsiyonel ama verildiğinde dört sayı olmalı.

- [ ] **Step 2: Test'lerin patladığını gör**

Run: `python3 -m pytest tests/test_brief.py -v -k style or source or bbox`
Expected: FAIL — `AttributeError: module 'brief' has no attribute 'STYLE_FIELDS'` / `Analysis`

- [ ] **Step 3: `load_analysis`'i v2'ye yaz**

```python
STYLE_FIELDS = ("render", "camera", "lighting", "palette", "linework", "realism")
UNSTATED = "belirtilmemiş"


@dataclass
class Analysis:
    style: dict
    style_source: dict
    style_image: Path | None
    objects: list[dict]


def _resolve(raw, base: Path, where: str) -> Path | None:
    """A path from the analysis, resolved against the analysis file.

    Against the file and not the cwd: the analysis carries its images with it,
    and the review loop runs it again from wherever the user happens to be.
    """
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise BriefError(f"{where}: image path must be a non-empty string")
    path = Path(raw)
    resolved = (path if path.is_absolute() else base / path).resolve()
    if not resolved.exists():
        raise BriefError(f"{where}: no such image: {raw}")
    return resolved


def load_analysis(path) -> Analysis:
    """Read and validate analysis.json. Every error names the offending field,
    and the object's id where there is one: this file is hand-edited between
    runs, and an error that only says "invalid" costs the user a hunt."""
    path = Path(path)
    base = path.parent.resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BriefError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(raw, dict):
        raise BriefError("analysis must be a JSON object")

    style = raw.get("style")
    if not isinstance(style, dict):
        raise BriefError(
            "'style' must be an object with the fields: " + ", ".join(STYLE_FIELDS))
    missing = [f for f in STYLE_FIELDS
               if not isinstance(style.get(f), str) or not style[f].strip()]
    if missing:
        raise BriefError(f"style is missing {len(missing)} field(s): "
                         + ", ".join(missing))
    style = {f: style[f].strip() for f in STYLE_FIELDS}

    raw_source = raw.get("style_source") or {}
    if not isinstance(raw_source, dict):
        raise BriefError("'style_source' must be an object when given")
    # A field nobody claimed is stamped, not guessed. The review page prints
    # this beside every field, so an override that landed on the wrong one is
    # visible instead of silent.
    style_source = {f: str(raw_source.get(f) or UNSTATED).strip() for f in STYLE_FIELDS}

    style_image = _resolve(raw.get("style_image"), base, "style_image")

    objects = raw.get("objects")
    if not isinstance(objects, list) or not objects:
        raise BriefError("'objects' is required and must be a non-empty list")

    out = []
    for index, obj in enumerate(objects):
        if not isinstance(obj, dict):
            raise BriefError(f"objects[{index}]: must be a JSON object")
        obj_id = obj.get("id")
        if not isinstance(obj_id, str) or not obj_id.strip():
            raise BriefError(f"objects[{index}]: 'id' is required")
        where = f"objects[{index}] ({obj_id})"

        entry = dict(obj)
        entry["source"] = _resolve(obj.get("source"), base, where) or style_image

        bbox = obj.get("bbox")
        if bbox is not None:
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                raise BriefError(f"{where}: 'bbox' must be [x1, y1, x2, y2]")
            if entry["source"] is None:
                raise BriefError(f"{where}: 'bbox' needs an image to cut out of — "
                                 "give the object a 'source' or the analysis a "
                                 "'style_image'")
        entry["bbox"] = list(bbox) if bbox is not None else None
        entry["views"] = prompts.normalise_views(obj.get("views"))
        entry["animated"] = len(entry["views"]) > 1
        out.append(entry)
    return Analysis(style, style_source, style_image, out)
```

`main()`'i yeni dönüş tipine uydur (`parsed = load_analysis(...)`, `parsed.style`, `parsed.objects`) ve Task 5'te bırakılan `{"render": style}` köprüsünü sil. `--image` argümanını sil; kaynak görseller artık analizden geliyor.

- [ ] **Step 4: Test'lerin geçtiğini gör**

Run: `python3 -m pytest tests/test_brief.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: analysis v2 — six style fields, per-object source, optional bbox

One input file instead of a file plus a flag, because the review loop is
already 'edit the analysis, run it again' and splitting the input across two
places breaks it. Paths resolve against the analysis, so it travels with its
images. style_source stamps where each field came from, which is what makes
a wrong override visible."
```

---

### Task 8: Kırpma kararı — dört hâl ve kaynak başına gruplama

`bbox` opsiyonel olduğu için kırpma artık bir karar. Ayrıca birden çok kaynak görsel varsa, iç içe kutu tespiti **yalnızca aynı görselin kutuları arasında** yapılmalı — farklı görsellerin kutularını karşılaştırmak anlamsız üstü örtme raporları üretir.

**Files:**
- Modify: `.claude/skills/sprite-brief/scripts/brief.py`
- Modify: `tests/test_brief.py`

**Interfaces:**
- Consumes: `brief.Analysis` (Task 7), `crops.crop_objects`, `crops.find_contents`, `crops.blank_contents`, `refclean.clean_crops`
- Produces: `brief.crop_mode(obj) -> str` — `"crop"` | `"whole"` | `"text"`; `brief.prepare_refs(analysis, refs_dir) -> tuple[list[dict], list, dict]` — `(kept, rejected, contents)`

- [ ] **Step 1: Failing test'leri yaz**

```python
def test_crop_mode_reads_the_three_cases():
    assert brief.crop_mode({"source": Path("a.png"), "bbox": [1, 2, 3, 4]}) == "crop"
    assert brief.crop_mode({"source": Path("a.png"), "bbox": None}) == "whole"
    assert brief.crop_mode({"source": None, "bbox": None}) == "text"


def test_a_whole_image_object_is_copied_not_cut():
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (120, 90), (40, 160, 90)).save(d / "one.png")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [{"id": "blob", "subject": "a blob", "source": "one.png"}],
    }), encoding="utf-8")
    kept, rejected, _ = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert not rejected
    assert kept[0]["crop"].name == "blob.png"
    with Image.open(kept[0]["crop"]) as done:
        # cleaned (upscaled past the capture's stair-stepping) but not cropped:
        # the aspect ratio of the source survives
        assert round(done.width / done.height, 2) == round(120 / 90, 2)


def test_a_text_only_object_gets_no_crop_and_is_not_rejected():
    d = Path(tempfile.mkdtemp())
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [{"id": "idea", "subject": "a thing I described"}],
    }), encoding="utf-8")
    kept, rejected, _ = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert not rejected
    assert kept[0].get("crop") is None
    assert kept[0].get("palette") in (None, [])


def test_boxes_are_only_compared_within_one_source_image():
    d = Path(tempfile.mkdtemp())
    for name in ("a.png", "b.png"):
        Image.new("RGB", (200, 200), (70, 70, 90)).save(d / name)
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [
            {"id": "big", "subject": "a frame", "source": "a.png",
             "bbox": [10, 10, 190, 190]},
            # identical box, different picture: it is NOT inside `big`
            {"id": "other", "subject": "a thing", "source": "b.png",
             "bbox": [20, 20, 120, 120]},
        ],
    }), encoding="utf-8")
    _, _, contents = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert "big" not in contents, "boxes from two different images were compared"


def test_a_box_inside_another_on_the_same_image_is_still_found():
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (200, 200), (70, 70, 90)).save(d / "a.png")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [
            {"id": "tray", "subject": "a tray", "source": "a.png",
             "bbox": [10, 10, 190, 190]},
            {"id": "puck", "subject": "a puck", "source": "a.png",
             "bbox": [60, 60, 120, 120]},
        ],
    }), encoding="utf-8")
    _, _, contents = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert contents.get("tray") == ["puck"]


def test_a_rejected_box_does_not_take_its_neighbours_down():
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (200, 200), (70, 70, 90)).save(d / "a.png")
    path = d / "analysis.json"
    path.write_text(json.dumps({
        "style": FULL_STYLE,
        "objects": [
            {"id": "good", "subject": "ok", "source": "a.png",
             "bbox": [10, 10, 90, 90]},
            {"id": "tiny", "subject": "too small", "source": "a.png",
             "bbox": [10, 10, 14, 14]},
        ],
    }), encoding="utf-8")
    kept, rejected, _ = brief.prepare_refs(brief.load_analysis(path), d / "refs")
    assert [o["id"] for o in kept] == ["good"]
    assert rejected and rejected[0][0] == "tiny"
```

- [ ] **Step 2: Test'lerin patladığını gör**

Run: `python3 -m pytest tests/test_brief.py -v -k crop_mode or prepare_refs or source_image`
Expected: FAIL — `AttributeError: module 'brief' has no attribute 'crop_mode'`

- [ ] **Step 3: `crop_mode` ve `prepare_refs`'i yaz**

```python
def crop_mode(obj: dict) -> str:
    """Which of the three shapes this object's reference takes.

    Cropping is a decision, not a step: one clean picture of one object needs
    no box, a screenshot holding a set needs one per object, and an object the
    user only described has no picture at all. Guessing wrong in either
    direction is expensive — a box around a whole playfield gave its track 80px
    of a 1024px picture and came back as a picture frame every single time.
    """
    if obj.get("source") is None:
        return "text"
    return "crop" if obj.get("bbox") else "whole"


def prepare_refs(analysis, refs_dir) -> tuple[list[dict], list, dict]:
    """Write every object's reference image. Returns (kept, rejected, contents).

    Boxes are compared for containment within one source image only: two boxes
    in two different screenshots have no spatial relationship, and reporting one
    as swallowing the other would blank a hole in a crop for no reason.
    """
    refs_dir = Path(refs_dir)
    refs_dir.mkdir(parents=True, exist_ok=True)

    kept: list[dict] = []
    rejected: list = []
    contents: dict = {}

    boxed: dict[Path, list[dict]] = {}
    for obj in analysis.objects:
        mode = crop_mode(obj)
        if mode == "text":
            kept.append(dict(obj))
        elif mode == "whole":
            entry = dict(obj)
            target = refs_dir / f"{obj['id']}.png"
            try:
                with Image.open(obj["source"]) as opened:
                    opened.convert("RGB").save(target)
            except OSError as exc:
                rejected.append((obj["id"], f"cannot read {obj['source']}: {exc}"))
                continue
            entry["crop"] = target
            kept.append(entry)
        else:
            boxed.setdefault(obj["source"], []).append(obj)

    for source, group in boxed.items():
        try:
            with Image.open(source) as opened:
                image = opened.convert("RGB")
        except OSError as exc:
            rejected.extend((o["id"], f"cannot read {source}: {exc}") for o in group)
            continue
        cut, dropped = crops.crop_objects(image, group, refs_dir)
        rejected.extend(dropped)
        inside = crops.find_contents(cut)
        crops.blank_contents(cut, inside, image)
        contents.update(inside)
        kept.extend(cut)

    # After blanking, which maps source-image boxes into crop coordinates that
    # the upscale in here would invalidate.
    refclean.clean_crops([o for o in kept if o.get("crop")])
    return kept, rejected, contents
```

`main()`'i `prepare_refs` kullanacak şekilde yeniden bağla; `_load_image` ve tek görsel varsayan kod yolu gider. `refs/_style.png` kopyası yalnızca `analysis.style_image` varsa yazılır. `labelled_sheet` yalnızca `crop`'u olan nesnelerle çağrılır; hiçbiri yoksa sheet yazılmaz ve bu bir hata değildir.

- [ ] **Step 4: Test'lerin geçtiğini gör**

Run: `python3 -m pytest tests/test_brief.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: decide whether to crop, per object and per source image

Three shapes: a box to cut, a whole picture to clean, or no picture at all.
Containment is judged within one source image, because two boxes in two
screenshots have no spatial relationship and blanking a hole for one would
be pure damage."
```

---

### Task 9: `review.html` — iki bölüm

**Files:**
- Modify: `.claude/skills/sprite-brief/scripts/brief.py`
- Modify: `tests/test_brief.py`

**Interfaces:**
- Consumes: `brief.Analysis`, `prompts.asset_prompt`
- Produces: `brief.page(analysis, kept, contents, title) -> str`; `brief.main` artık `<out-dir>/review.html` yazar

- [ ] **Step 1: Failing test'leri yaz**

Dosyaya `import re` ekle (yeni palet testi kullanıyor).

```python
def _rendered(objects, style_image="shot.png", images=("shot.png",)):
    d = Path(tempfile.mkdtemp())
    for name in images:
        Image.new("RGB", (200, 200), (90, 90, 120)).save(d / name)
    payload = {"style": FULL_STYLE, "style_source": {"render": "kullanıcı"},
               "objects": objects}
    if style_image:
        payload["style_image"] = style_image
    path = d / "analysis.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    parsed = brief.load_analysis(path)
    kept, _, contents = brief.prepare_refs(parsed, d / "refs")
    return brief.page(parsed, kept, contents, "t")


def test_the_review_section_prints_every_style_field_with_its_source():
    html = _rendered([{"id": "a", "subject": "x", "bbox": [10, 10, 90, 90]}])
    for field in brief.STYLE_FIELDS:
        assert field in html
    assert "kullanıcı" in html
    assert "belirtilmemiş" in html          # the fields nobody claimed


def test_the_review_section_shows_the_measured_palette_as_swatches():
    html = _rendered([{"id": "a", "subject": "x", "bbox": [10, 10, 90, 90]}])
    swatches = re.findall(r"class='swatch' style='background:(#[0-9A-Fa-f]{6})'", html)
    assert swatches, "no measured colour reached the page"
    # the crop is one flat colour, so its dominant swatch is that colour
    rgb = tuple(int(swatches[0][i:i + 2], 16) for i in (1, 3, 5))
    assert all(abs(a - b) <= 12 for a, b in zip(rgb, (90, 90, 120))), swatches[0]
    assert f"<code>{swatches[0]}</code>" in html


def test_the_prompt_section_carries_a_paste_ready_block_per_view():
    html = _rendered([{"id": "a", "subject": "x", "bbox": [10, 10, 90, 90],
                       "views": ["front", "side"]}])
    assert html.count("DO NOT DRAW") == 2
    assert "a-front" in html and "a-side" in html


def test_the_prompt_names_both_pictures_when_a_style_image_exists():
    html = _rendered([{"id": "a", "subject": "x", "bbox": [10, 10, 90, 90]}])
    assert "Picture 1" in html and "Picture 2" in html


def test_the_prompt_names_one_picture_when_there_is_no_style_image():
    html = _rendered([{"id": "a", "subject": "x", "source": "shot.png",
                       "bbox": [10, 10, 90, 90]}], style_image=None)
    assert "Picture 2" not in html


def test_a_text_only_object_still_gets_a_prompt_and_says_it_has_no_picture():
    html = _rendered([{"id": "idea", "subject": "a described thing"}],
                     style_image=None, images=())
    assert "idea-front" in html
    assert "görsel yok" in html
    assert "Picture 1" not in html


def test_the_style_image_is_inlined_once_no_matter_how_many_objects():
    html = _rendered([{"id": "a", "subject": "x", "bbox": [10, 10, 90, 90]},
                      {"id": "b", "subject": "y", "bbox": [100, 100, 190, 190]}])
    # Measured: repeating the same base64 blob per asset produced a 55 MB page
    # from a 2.4 MB screenshot across 17 assets.
    assert html.count("data:image/png;base64,") == 3   # style + two crops


def test_the_page_escapes_ids_and_prompt_text():
    html = _rendered([{"id": "a", "subject": "<script>alert(1)</script>",
                       "bbox": [10, 10, 90, 90]}])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_the_page_references_no_external_file():
    html = _rendered([{"id": "a", "subject": "x", "bbox": [10, 10, 90, 90]}])
    assert "http://" not in html and "https://" not in html
    assert 'src="refs/' not in html


def test_main_writes_review_html_and_the_inner_analysis():
    d = Path(tempfile.mkdtemp())
    Image.new("RGB", (200, 200), (90, 90, 120)).save(d / "shot.png")
    src = d / "analysis.json"
    src.write_text(json.dumps({
        "style": FULL_STYLE, "style_image": "shot.png",
        "objects": [{"id": "a", "subject": "x", "bbox": [10, 10, 90, 90]}],
    }), encoding="utf-8")
    out = d / "brief"
    assert brief.main(["--analysis", str(src), "--out-dir", str(out),
                       "--no-open"]) == 0
    assert (out / "review.html").exists()
    assert (out / "analysis.json").exists()
    assert (out / "refs" / "a.png").exists()
    assert (out / "refs" / "_style.png").exists()
```

Eski `page()` testlerini (`test_the_page_inlines_both_images`, `test_each_asset_gets_its_own_section_and_prompt`, `test_the_page_escapes_prompt_text_and_ids`, `test_the_page_references_no_external_file`, `test_a_run_writes_crops_the_style_copy_the_sheet_and_the_brief`) yukarıdakilerle değiştir.

- [ ] **Step 2: Test'lerin patladığını gör**

Run: `python3 -m pytest tests/test_brief.py -v -k review or prompt_section or page`
Expected: FAIL — `page()` yeni imzayı bilmiyor

- [ ] **Step 3: `page()`'i iki bölümlü yaz**

`_CSS`'e şu sınıfları ekle: `.style-grid` (iki sütun: alan adı, değer + kaynak rozeti), `.src` (rozet), `.swatch` (24px kare, `border-radius: 4px`), `.prompts` (bölüm başlığı).

```python
def _swatches(colours) -> str:
    """Measured colours as squares plus their hex, because a name is not
    reproducible: a conveyor's channel was called 'pale lilac-white' when it is
    #434375, and the sprite stayed pale until the real value was in the prompt."""
    return "".join(
        f"<span class='swatch' style='background:{html.escape(c)}'></span>"
        f"<code>{html.escape(c)}</code>"
        for c in colours or [])


def page(analysis, kept, contents, title: str) -> str:
    """The whole review as one self-contained document.

    Two sections, because the same analysis feeds two ways of making the
    sprite: the review is what gets checked before any code is written, and
    the prompts are what gets pasted into a chat when it is made by hand.
    """
    out = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body>",
        f"<h1>{html.escape(title)}</h1>",
        f"<p class='meta'>{len(kept)} nesne · inceleme + elle üretim prompt'ları</p>",
        "<h2>Stil</h2><div class='style-grid'>",
    ]
    for field in STYLE_FIELDS:
        out.append(
            f"<div><code>{field}</code></div>"
            f"<div>{html.escape(analysis.style[field])}"
            f"<span class='src'>{html.escape(analysis.style_source[field])}</span></div>")
    out.append("</div>")
    if analysis.style_image:
        out += ["<figure class='style'>",
                f"<img src='{_data_uri(analysis.style_image)}' alt=''>",
                f"<figcaption>Picture 2 — {html.escape(analysis.style_image.name)} — "
                "her mesajda crop'un yanında bunu da yükle</figcaption>", "</figure>"]

    out.append("<h2>Nesneler</h2>")
    for obj in kept:
        crop = obj.get("crop")
        out += ["<div class='asset'>", f"<h3>{html.escape(obj['id'])}</h3>",
                "<div class='row'>"]
        if crop:
            out.append(f"<figure><img src='{_data_uri(Path(crop))}' alt=''>"
                       f"<figcaption>Picture 1 — {html.escape(Path(crop).name)}"
                       "</figcaption></figure>")
        else:
            out.append("<p class='pair'>görsel yok — yalnızca tarif</p>")
        out.append(f"<div><p>{_swatches(obj.get('palette'))}</p>")
        for key, label in (("subject", "OBJECT"), ("form", "FORM"),
                           ("detail", "DETAIL"), ("state", "STATE")):
            if isinstance(obj.get(key), str) and obj[key].strip():
                out.append(f"<p><code>{label}</code> {html.escape(obj[key])}</p>")
        out.append("<p><code>VIEWS</code> {}</p></div>".format(
            html.escape(", ".join(obj["views"]))))
        out.append("</div></div>")

    out.append("<h2 class='prompts'>Elle üretim prompt'ları</h2>"
               "<p class='meta'>Her mesajda iki görseli de yükle · sprite başına tek "
               "mesaj · set başına yeni sohbet · indirileni <code>cut.py</code> ile kes</p>")
    for obj in kept:
        has_crop = obj.get("crop") is not None
        for view in obj["views"]:
            text = prompts.asset_prompt(
                obj, view, analysis.style, contents.get(obj["id"]),
                style_image=has_crop and analysis.style_image is not None)
            out += ["<div class='asset'>",
                    f"<h3>{html.escape(obj['id'])}-{html.escape(view)}</h3>",
                    f"<pre>{html.escape(text)}</pre>", "</div>"]
    out.append("</body></html>")
    return "\n".join(out)
```

`prompts.asset_prompt`'un `REFERENCES` bloğunu hiç basmaması gereken hâl (`crop` yok) için `prompts.py`'a küçük bir ekleme yap: `asset_prompt`'a `references: bool = True` parametresi; `False` iken blok atlanır. Testi Task 1'de yok, burada ekle:

```python
def test_a_text_only_object_gets_no_references_block():
    text = prompts.asset_prompt({"id": "a", "subject": "x"}, "front", STYLE,
                                references=False)
    assert "REFERENCES" not in text and "Picture 1" not in text
```

`main()` içinde `brief.html` adı `review.html` olur; üstteki "brief zaten var" koruması ve "kendi analysis.json'undan yeniden çalıştırma" istisnası aynen korunur.

- [ ] **Step 4: Test'lerin geçtiğini gör**

Run: `python3 -m pytest tests/ -v`
Expected: PASS (tüm dosyalar)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: review.html — the check above, the paste-ready prompts below

One file feeds both ways of making the sprite. The review section is what
gets looked at before any code is written; the prompt section is what goes
into a chat by hand, with the two-picture rule printed beside it."
```

---

### Task 10: `sprite-brief` SKILL.md

**Files:**
- Modify: `.claude/skills/sprite-brief/SKILL.md`

**Interfaces:**
- Consumes: `brief.py` CLI (Task 7-9)
- Produces: skill talimatı

- [ ] **Step 1: Silinecek bölümleri çıkar**

`### 7. Offer the local endpoint, once the brief is right` başlığından `## What not to do` başlığına kadar olan her şey (adım 7, `spritegen check`, `build --only` döngüsü, `structure_mode` / `palette_master` / `--seed-offset`, backend arıza modları) silinir.

`## What not to do` listesinden şunlar silinir: "Do not run `build` without `--only`...", "Do not write a pack unless...", "Do not start, restart or install the local service...".

- [ ] **Step 2: Frontmatter ve giriş yeniden yazılır**

```markdown
---
name: sprite-brief
description: Turn a screenshot, a set of reference images, or a plain description into cropped references and a review page — the input a procedural sprite build or a hand-generated one both run from. Use when the user wants sprites from a picture or a description, before any drawing happens.
---

# Sprite Brief

Read what the user gave you — a screenshot, several separate pictures, one
clean reference, or nothing but words — and produce a folder that two
different ways of making the sprite both run from: `procedural-sprites`,
which writes Python that draws them, and hand generation in Gemini or
ChatGPT, which pastes the prompts.

You see the images yourself. There is no vision API in this flow and it costs
nothing, which is why you can afford to check your own work before asking the
user anything.
```

- [ ] **Step 3: Yeni adımları yaz**

Adım sırası: (1) girdileri oku, (2) **`image-style` skill'ini çağır** ve altı stil alanını + `style_source`'u üret, (3) kırpma kararını ver — dört hâlin tablosu spec'ten alınır, (4) `analysis.json` yaz (v2 şeması, alan kuralları bugünkü listeden aynen korunur), (5) script'i çalıştır, (6) contact sheet'i kendi gözünle kontrol et, (7) tek turda sor, (8) devret.

Script çağrısı:

```bash
python3 .claude/skills/sprite-brief/scripts/brief.py \
    --analysis analysis.json --out-dir sprites-generated/<set>/brief --no-open
```

Devir bölümü:

```markdown
### 8. Hand over

Show the user `review.html` and say what is in it. Then ask **once**:

> Sprite'ları şimdi koda dökelim mi? (`procedural-sprites`)

If yes, invoke `procedural-sprites` with `sprites-generated/<set>/`. If no,
the prompt section of the same page is the hand-generation path: one message
per sprite, both pictures uploaded with every message, a fresh chat per set,
and the download cut with:

```bash
python3 .claude/skills/sprite-brief/scripts/cut.py <downloads> --out-dir sprites-generated/<set>/out
```

Every message must carry both pictures: the image model does not see the chat
history, so a screenshot uploaded once at the top never reaches the later
generations and the style drifts. This was measured — the version that sent no
style image produced a generic grey object where the version that sent one
matched the game's palette.
```

- [ ] **Step 4: Doğrula**

Run: `grep -niE "openrouter|rembg|spritegen|transport|key_env|structure_mode|seed-offset" .claude/skills/sprite-brief/SKILL.md`
Expected: çıktı yok

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/sprite-brief/SKILL.md
git commit -m "docs: rewrite sprite-brief around the crop decision and the handover

The endpoint section goes with the endpoint. What replaces it is the part
that was never written down: when to crop and when not to, and that the
review page feeds both the procedural build and the hand-generated one."
```

---

### Task 11: `image-style` SKILL.md

**Files:**
- Modify: `.claude/skills/image-style/SKILL.md`

**Interfaces:**
- Consumes: yok
- Produces: `analysis.json`'un `style` + `style_source` blokları

- [ ] **Step 1: `spritegen analyze` bölümünü sil**

`## Using it with the sprite generator` başlığı ve altındaki her şey gider. `Write nothing to disk and run no commands` kuralındaki "that is `spritegen analyze`'s job" cümlesi de.

- [ ] **Step 2: "Her akışta çalışır" ve alan bazlı override'ı yaz**

```markdown
## Precedence: the user's words win, field by field

This skill runs on every sprite job, with or without a style image. Each of
the six fields is resolved on its own:

    the user's words  >  the style image  >  the reference image(s)  >  default

A field the user did not touch keeps what the image said. If the picture is
jelly-cartoon and the user asked for pixel art, `render` and `realism` come
from the user while `camera`, `lighting`, `palette` and `linework` stay with
the picture. If the user only said "darker palette", only `palette` moves.

Record where each field came from — `kullanıcı`, `stil görseli`, `referans`,
`ölçüm`, `varsayılan` — and emit it as `style_source`. The review page prints
it beside each field, which is what makes an override that landed on the wrong
field visible instead of silent. A field nobody claimed and no picture shows
is stamped `varsayılan`; never invent one quietly.
```

- [ ] **Step 3: `camera` kuralını düzelt ve çıktı şeklini `analysis.json`'a bağla**

Mevcut "`style` must never name a camera angle" uyarısı yoktu ama şemada camera var; şu paragrafı ekle:

```markdown
`camera` is read by two different consumers and only one of them wants it. The
procedural path turns it into the shared camera-tilt constant every asset in
the set renders with. The hand-generation prompt leaves it out, because that
prompt carries its own VIEW line per object and an angle in the style line
contradicts it on every view but front. Fill the field either way — dropping
it is `prompts.style_line`'s job, not yours.
```

Ve `## Output`'un JSON bölümünü şu hâle getir:

```json
{
  "style": {
    "render": "...", "camera": "...", "lighting": "...",
    "palette": "...", "linework": "...", "realism": "..."
  },
  "style_source": {
    "render": "kullanıcı", "camera": "stil görseli", "lighting": "stil görseli",
    "palette": "ölçüm", "linework": "varsayılan", "realism": "kullanıcı"
  }
}
```

açıklamasıyla: "This is the `style` block of `analysis.json`. `sprite-brief`
writes it into the file; on its own this skill still only reads and reports."

- [ ] **Step 4: Doğrula**

Run: `grep -niE "spritegen|pack|openrouter" .claude/skills/image-style/SKILL.md`
Expected: çıktı yok

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/image-style/SKILL.md
git commit -m "docs: image-style runs on every job, overridden field by field

It used to be a report with one integration, and that integration is gone.
Now it produces the style block of analysis.json, with a stamp per field
saying whether the user, the picture or a default decided it."
```

---

### Task 12: `procedural-sprites` SKILL.md — venv, düzen, `style.py`, subagent döngüsü

**Files:**
- Modify: `.claude/skills/procedural-sprites/SKILL.md`

**Interfaces:**
- Consumes: `brief/analysis.json` (Task 7), `scripts/sprite_lib.py`, `scripts/sdf3d.py`
- Produces: skill talimatı; `sprites-generated/<set>/{scripts,out,qc}` düzeni

- [ ] **Step 1: `## Setup` bölümünü venv ve klasör düzeniyle değiştir**

```markdown
## Setup: the workspace and its venv

Everything a job produces lives under `sprites-generated/<set>/`:

    brief/    analysis.json · review.html · refs/
    scripts/  style.py · <asset>.py · sprite_lib.py + sdf3d.py (copied here)
    out/      the sprites themselves
    qc/       _qc_sheet.png · cmp_<id>.png · _silhouette.png

Copy `scripts/sprite_lib.py` and `scripts/sdf3d.py` from this skill into the
set's `scripts/` on the first run. Copied, not imported from the skill: the
set has to keep running months later, after the skill has moved on.

Every Python run goes through the workspace venv — never the system
interpreter, whose packages are not this project's business:

```bash
[ -x sprites-generated/.venv/bin/python ] || {
  python3 -m venv sprites-generated/.venv
  sprites-generated/.venv/bin/pip install -q pillow numpy
}
sprites-generated/.venv/bin/python sprites-generated/<set>/scripts/<asset>.py
```

If the venv cannot be created, stop and show the user the two commands. Do not
fall back to `python3`.
```

- [ ] **Step 2: Girdi bölümünü `analysis.json` ile bağla**

`## If a reference exists, the reference is the boss` bölümünün başına:

```markdown
Input comes in one of two shapes. Either `sprite-brief` handed you a
`sprites-generated/<set>/brief/` — read its `analysis.json` for the six style
fields, the per-object `subject`/`form`/`detail`/`views` and the measured
palette, and its `refs/*.png` for the crops — or the user described what they
want directly, in which case their words take the place of every field and
there are no crops to measure. Neither is required by the other: a brief is
convenient, not a prerequisite.

`style.render` and `style.realism` pick the drawing lane: soft-3D (the SDF
raymarcher), flat vector/glossy 2D, or a pixel grid. Read them before choosing
a technique — the style analysis is a code-path decision, not a mood note.
```

- [ ] **Step 3: `style.py` ve subagent döngüsünü yaz (yeni bölüm)**

```markdown
## One art direction file, one subagent per asset

Write `scripts/style.py` yourself, before any asset exists:

```python
PALETTE  = {"hide": "#B4522E", "horn": "#E8E8EF", "metal": "#E3B505"}
LIGHT    = (-0.45, -0.75, 0.5)     # one vector for the whole set
CAMERA   = 12.0                    # degrees of tilt, shared by every asset
MATERIALS = {"hide": dict(rough=0.55, spec=0.25, spec_color="#FFE9C7"),
             "horn": dict(rough=0.30, spec=0.60, spec_color="#FFFFFF")}
CONTOUR  = 6                       # dark outline width at SS scale
SS       = 4                       # supersample factor
```

That file is what makes thirty sprites look like one artist, so it has exactly
one author. Then dispatch **one subagent per asset**, independents in parallel.
Each subagent:

1. writes `scripts/<asset>.py`, importing `style.py` — and nothing else of its own
2. runs it through the venv python
3. produces `out/<asset>.png`, plus `qc/cmp_<asset>.png` when a crop exists
4. **looks at what it drew**, names the differences out loud, fixes the biggest
5. repeats, two to four rounds
6. returns a short receipt and nothing else:

```
asset:   bull_totem
files:   scripts/bull_totem.py, out/bull_totem.png, qc/cmp_bull_totem.png
rounds:  3
remaining: horn tip 10% shorter than the reference — deliberate, invisible at game size
blocked:  -
style_request: -
```

**A subagent never edits `style.py`.** If an asset needs a colour or a light
the file does not have, it says so in `style_request` and you decide — a set
where every asset bent the shared constants to its own need is a set that no
longer looks like one game.

Rendered PNGs stay in the subagent's context. What comes back to you is the
receipt, which is the whole point: you close the job on one QC sheet rather
than on twenty images.

## Closing the set

Render `qc/_qc_sheet.png` with every sprite at roughly on-screen size over the
game's backdrop colour, and look at it. Judge the set, not the sprites:
palette, line weight, light direction. A sprite that is fine alone and wrong
beside its neighbours is not finished. Open a second, targeted round of
subagents for whatever fails, then hand over — naming any asset you could not
deliver and why.
```

- [ ] **Step 4: `## Characters` ladder'ına Spec 2 notu koy**

Lane 2'nin sonuna:

```markdown
   Known ceiling, measured on a bull totem: parts stacked instead of blended,
   a face made of screen-space stickers, no contact occlusion at the joins,
   one plastic material for hide, bone and metal alike, and a silhouette so
   symmetric it does not read when filled black. A `character_lib` that fixes
   these by construction is specified separately; until it lands, check each
   of them by hand.
```

- [ ] **Step 5: Doğrula**

Run: `grep -niE "openrouter|rembg|diffusion generates|spritegen" .claude/skills/procedural-sprites/SKILL.md`
Expected: yalnızca lane 4'teki "diffusion generates the master" satırı — bu bir yönlendirme, entegrasyon değil; onu şu hâle getir: "an image model generates the master by hand, through the prompt section of the brief".

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/procedural-sprites/SKILL.md
git commit -m "docs: workspace, venv and the one-subagent-per-asset loop

The shared art direction has exactly one author and the assets have one
writer each, so the rendered images never reach the thread that judges the
set. Also records the ceiling the bull totem measured, for the character
library that comes next."
```

---

### Task 13: `README.md` ve `CLAUDE.md`

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: `README.md`'yi yeniden yaz**

Silinen bölümler: Install (`pip install -e .`, `OPENROUTER_API_KEY`), `init`/`pick`/`build`/`analyze`/`make`/`extract`/`export`/`check`, pack format, Transport, Configuration, "Why the grey backdrop"un rembg yarısı, "When to use which" tablosu.

Yeni iskelet:

```markdown
# Sprite Generator

Üç skill: bir ekran görüntüsünü, birkaç referans görselini ya da düz bir tarifi
alır, ondan sprite üretir. Görsel üretim API'si yok — sprite'lar ya Python
koduyla çizilir, ya da elle Gemini/ChatGPT'de üretilip yerel olarak kesilir.

## Skiller
| skill | işi |
| `sprite-brief` | girdiyi analysis.json + crops + review.html'e çevirir |
| `image-style` | görselin/kullanıcının stilini altı alana indirger |
| `procedural-sprites` | sprite'ı çizen Python'u yazar |

## Zincir  (spec'teki diyagram)
## analysis.json  (v2 şeması, alan tablosu)
## Çalışma alanı ve venv  (sprites-generated düzeni + bootstrap komutu)
## Elle üretim yolu  (review.html'in prompt bölümü, iki görsel kuralı, cut.py --key)
## Neden düz gri zemin  (ölçüm: #FF00FF 610-2079 renkli kenar pikseli, #808080 sıfır)
## Testler  (python3 -m pytest — ağ yok, saniyeler)
## Unity import  (mevcut bölüm aynen kalır)
```

- [ ] **Step 2: `CLAUDE.md`'yi yeniden yaz**

Silinecek değişmezler: transport/precedence, key_env, reference rolleri (structure/style, image1/image2 wire kuralı `prompts.py` bağlamında yeniden yazılır), `cutout = false`, `build_one` sözleşmesi, packwriter, extract/build maliyet ayrımı, seed'ler.

Korunacak/yeniden yazılacak değişmezler:

```markdown
- **Prompt metninin tek kaynağı `prompts.py`.** review.html'in prompt bölümü
  ve elle üretim aynı stringlerden beslenir; ikinci bir kopya iki yolun
  birbirinden kayması demektir.
- **Reddedilen hiçbir şey sessizce düşmez** — kutu, nesne, soru.
- **Ölçülen palet tarif edilen paleti yener.** refclean.palette crop'tan okur;
  bir vision modeli #434375'e "soluk leylak-beyaz" demişti.
- **Kırpma bir karar** (crop/whole/text) ve iç içe kutu tespiti yalnızca aynı
  kaynak görsel içinde yapılır.
- **`style_line` camera'yı düşürür**, çünkü prompt kendi VIEW satırını taşıyor;
  camera'yı prosedürel taraf kamera sabiti olarak okur.
- **Sanat yönünün tek yazarı var** (`style.py`); subagent ona dokunamaz.
- **Her Python çalıştırması venv'den geçer.**
- **Düz #808080 zemin** ölçülmüş bir karardır; `cut.py --key` onu keser.
```

Commands bölümü: `python3 -m pytest`, tek test dosyası, `brief.py` ve `cut.py` çağrıları. Architecture bölümü: üç skill + `scripts/` yerleşimi + zincir.

- [ ] **Step 3: Doğrula**

Run: `grep -niE "pip install|openrouter|rembg|spritegen [a-z]+ " README.md CLAUDE.md`
Expected: çıktı yok

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: rewrite the README and CLAUDE.md around the three skills

Both described a CLI that no longer exists. What replaces them is the chain,
the analysis schema, the workspace layout, and the invariants that are still
true — measured palette beats described palette, nothing is dropped silently,
one author for the art direction."
```

---

### Task 14: Uçtan uca duman testi

**Files:**
- Create: `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: `brief.main`, `cut.main`

- [ ] **Step 1: Testi yaz**

```python
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
    img = Image.new("RGB", (128, 128), (128, 128, 128))
    for x in range(40, 90):
        for y in range(40, 90):
            img.putpixel((x, y), (200, 70, 40))
    img.save(downloads / "block.png")

    assert cut.main([str(downloads), "--out-dir", str(sprites)]) == 0
    with Image.open(sprites / "block.png") as done:
        assert done.mode == "RGBA"
        assert done.getpixel((0, 0))[3] == 0
        assert done.width == done.height
```

- [ ] **Step 2: Çalıştır**

Run: `python3 -m pytest tests/test_end_to_end.py -v`
Expected: PASS (2 test)

- [ ] **Step 3: Tüm suite + kabul kriterleri**

Run: `python3 -m pytest -v`
Expected: PASS

Run: `grep -rniE "openrouter|rembg|requests|transport|key_env|base_url|api_key" --include=*.py --include=*.md --include=*.toml . | grep -v "^./docs/"`
Expected: çıktı yok

Run: `ls spritegen 2>&1`
Expected: `No such file or directory`

- [ ] **Step 4: Commit**

```bash
git add tests/test_end_to_end.py
git commit -m "test: one run of the whole local half, end to end

A screenshot plus a description in, a reviewable brief out — including the
object that has no picture at all — and a flat-grey download cut back to
alpha. This is what has to hold before a subagent is worth dispatching."
```

---

## Self-Review

**Spec kapsam kontrolü:**

| spec bölümü | task |
|---|---|
| 1. Silinir / yaşar | 1, 2, 3, 4, 5, 6 |
| 2. `analysis.json` v2 | 7 |
| 3. `sprite-brief` davranışı, `review.html` | 8, 9, 10 |
| 4. `image-style` her akışta + override | 11 (skill), 7 (`style_source` alanı) |
| 5. Çalışma alanı + venv + `.gitignore` | 6 (gitignore), 12 (venv + düzen) |
| 6. Zincir | 10 (devir sorusu), 12 (girdi) |
| 7. Subagent döngüsü | 12 |
| 8. Hata yönetimi | 7 (analiz hataları), 8 (okunamayan görsel, reddedilen kutu), 12 (venv, traceback, `style_request`) |
| 9. Testler | 1, 2, 3, 4, 9, 14 |
| 10. Dokümantasyon | 10, 11, 12, 13 |
| Kabul kriterleri 1-6 | 6 (Step 6), 14 (Step 3) |

**Spec'e eklenmesi gereken bir satır:** `style_line` prompt metninde `camera`'yı düşürüyor (Task 1, Task 11 Step 3). Spec "camera artık serbest" diyor ama prompt'un VIEW satırıyla çelişme sorununun devam ettiğini söylemiyor. Task 13'ten önce spec'e tek cümle eklenmeli — planı uygulayan kişi bunu Task 11'de zaten uyguluyor, çelişki değil eksik kayıt.

**Tip tutarlılığı:** `load_analysis` Task 7'de `Analysis` dataclass'ı döndürüyor; Task 8 `prepare_refs(analysis, refs_dir)` ve Task 9 `page(analysis, kept, contents, title)` aynı nesneyi alıyor. `asset_prompt(obj, view, style, contents=None, style_image=True, references=True)` — `style_image` Task 1'de, `references` Task 9'da ekleniyor, ikisi de aynı imzada. `crop_mode` üç string döndürüyor ve yalnızca `prepare_refs` okuyor.

**Placeholder taraması:** temiz — her adımda çalıştırılacak komut, beklenen sonuç ve gerçek kod var.

---

## Execution Handoff

**Plan complete and saved to `docs/plans/2026-08-10-skill-first-pipeline.md`.**
