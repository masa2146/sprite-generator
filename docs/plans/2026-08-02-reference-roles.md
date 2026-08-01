# Rollü referans görselleri — Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `spritegen build`'in gönderdiği iki referans görselinin yerel spritepipe backend'inde gerçekten kullanılması — bugün ikisi de `role` alanı olmadığı için sessizce atılıyor.

**Architecture:** `orclient.generate()`'in tek `reference_png` parametresi iki adlandırılmış slota bölünür (`structure_png`, `style_png`). `images` transport'u her referansa `role` yazar; `chat` transport'u `role` kavramını bilmediği için etiketi metin olarak görselin hemen önüne serpiştirir. Prompt'un `REFERENCES` bloğu backend'in slot adlarını (`image1`/`image2`) birebir kullanır.

**Tech Stack:** Python 3.11, `requests`, `pytest`, PIL. Yeni bağımlılık yok.

**Spec:** [docs/specs/2026-08-02-reference-roles-design.md](../specs/2026-08-02-reference-roles-design.md)

## Global Constraints

- Python 3.11 taban; f-string içinde backslash kullanılamaz (`"{}".format(...)` ile kur).
- Yeni bağımlılık eklenmez.
- Kod ve kod yorumları İngilizce; `docs/` altındaki dokümanlar Türkçe.
- Commit başlıkları İngilizce, conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`).
- Her commit'in sonuna `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` satırı eklenir.
- Testler: `py -m pytest -q` (Windows) ya da `python3 -m pytest -q`.
- **Bilinen taban hatası:** `tests/test_config.py::test_an_absolute_reference_is_not_joined_to_the_pack_dir` Windows'ta zaten kırık (test POSIX `/tmp` yolu varsayıyor, sürücü harfi uyuşmuyor). Bu planla ilgisi yok; "tüm testler geçti" derken bu hariç sayılır.
- `BG_CLAUSE`, yerel `post.py` kesimi, pack şeması ve `control_strength` bu planda **değişmez**.

## Dosya yapısı

| Dosya | Sorumluluk | Bu planda ne oluyor |
|---|---|---|
| `spritegen/orclient.py` | HTTP taşıma, payload kurucular | İki slotlu imza, `reference_part()`, `role`, chat serpiştirme |
| `spritegen/cli.py` | Komutlar; `build_one` slot seçimi | Hangi baytın hangi slota gittiği |
| `spritegen/config.py` | Prompt blokları | `REFERENCES_BLOCK` sözcükleri |
| `spritegen/brief.py` | Elle üretim HTML'i | Figür başlıkları prompt'la aynı sözcüğü kullanır |
| `tests/test_client.py` | Payload şekli | Rol ve etiket testleri |
| `tests/test_build.py` | Uçtan uca build | Slot tablosu testleri |
| `tests/test_make.py`, `tests/test_extract.py` | Diğer akışların stub'ları | İmza değişikliğine uyum |
| `tests/test_brief.py`, `tests/test_config.py` | Prompt metni | Sözcük değişikliğine uyum |
| `README.md` | Kullanıcı dokümanı | Rol tablosu ve tel şekli |

---

### Task 1: `generate()` iki adlandırılmış slota bölünür

Bugün tek `reference_png` üç ayrı işi taşıyor: asset'in crop'u, style bible, `make`'in kaynak görseli. Bu görev onları ayırır ve style bible'ı doğru kutuya taşır. Davranış değişikliği: style bible artık `style_png` olarak gider (bugün `reference_png`), yani Task 2'de `role: "style"` alacak — `structure` değil.

**Files:**
- Modify: `spritegen/orclient.py:80-135` (`build_payload`, `build_payload_images`), `spritegen/orclient.py:243-290` (`generate`)
- Modify: `spritegen/cli.py:75-115` (`build_one`), `spritegen/cli.py:590-594` (`cmd_make`'in `generate` çağrısı)
- Test: `tests/test_build.py`, `tests/test_client.py`, `tests/test_make.py`, `tests/test_extract.py`

**Interfaces:**
- Produces: `orclient.build_payload(model, prompt, structure_png=None, seed=None, style_png=None) -> dict`
- Produces: `orclient.build_payload_images(model, prompt, aspect_ratio=None, structure_png=None, seed=None, style_png=None) -> dict`
- Produces: `orclient.generate(pack, prompt, aspect_ratio=None, structure_png=None, style_png=None, seed=None, retries=3, sleeper=time.sleep) -> tuple[bytes, float | None, dict]`
- Produces: `cli.build_one(pack, asset, bible_png) -> dict` — üçüncü parametre artık her zaman style bible'dır (ya da `None`), asset'in kendi crop'u değil.

- [ ] **Step 1: `_Stubs`'ı iki slotu ayrı kaydedecek hale getir**

`tests/test_build.py`, `_Stubs.__init__` içinde `self.references = []` satırını değiştir:

```python
        self.structures = []  # structure_png passed into generate(), in call order
        self.styles = []      # style_png passed into generate(), in call order
```

`self.style_pngs = []` satırını sil (Task 1 öncesi eklenmişti, yerini `self.styles` alıyor).

Aynı dosyada `fake_generate`'i değiştir:

```python
        def fake_generate(pack, prompt, aspect_ratio=None, structure_png=None, seed=None,
                          style_png=None, **kw):
            self.prompts.append(prompt)
            self.structures.append(structure_png)
            self.styles.append(style_png)
            self.aspect_ratios.append(aspect_ratio)
```

- [ ] **Step 2: Yeni davranışı pinleyen testi yaz**

`tests/test_build.py` içinde, `test_the_style_image_rides_along_with_an_assets_own_crop`'un hemen üstüne ekle:

```python
def test_the_style_bible_travels_as_a_style_reference_not_a_structure():
    """The bible is an example of the look, never a silhouette to trace.

    Sent as a structure it comes back copied: spritepipe's README records three
    different prompts returning three copies of exactly this image.
    """
    tmp = tempfile.mkdtemp()
    spec = _prepare(tmp)
    with _Stubs([(b"A", 0.0), (b"B", 0.0), (b"C", 0.0)]) as stubs:
        cli.main(["build", str(spec), "--out-root", tmp])
    assert stubs.structures == [None, None, None]
    assert stubs.styles == [b"BIBLE", b"BIBLE", b"BIBLE"]
```

- [ ] **Step 3: Testin doğru sebeple başarısız olduğunu gör**

Run: `py -m pytest tests/test_build.py::test_the_style_bible_travels_as_a_style_reference_not_a_structure -q`
Expected: FAIL — `TypeError: generate() got an unexpected keyword argument 'structure_png'` ya da `assert [b"BIBLE", b"BIBLE", b"BIBLE"] == [None, None, None]`.

- [ ] **Step 4: `orclient` imzalarını yeniden adlandır**

`spritegen/orclient.py` içinde üç imzada `reference_png` → `structure_png`:

```python
def build_payload(
    model: str,
    prompt: str,
    structure_png: bytes | None = None,
    seed: int | None = None,
    style_png: bytes | None = None,
) -> dict:
    # Order is the contract: the prompt's REFERENCES block calls the first image
    # "image1 — the object to redraw" and the second "image2 — style only".
    content: list[dict] = [{"type": "text", "text": prompt}]
    content += [image_part(img) for img in (structure_png, style_png) if img]
```

```python
def build_payload_images(
    model: str,
    prompt: str,
    aspect_ratio: str | None = None,
    structure_png: bytes | None = None,
    seed: int | None = None,
    style_png: bytes | None = None,
) -> dict:
```

`build_payload_images` gövdesindeki referans listesini de güncelle:

```python
    # Same order as build_payload: object first, style second.
    refs = [image_part(img) for img in (structure_png, style_png) if img]
    if refs:
        body["input_references"] = refs
```

`generate` imzası ve iki dallı çağrısı:

```python
def generate(
    pack,
    prompt: str,
    aspect_ratio: str | None = None,
    structure_png: bytes | None = None,
    style_png: bytes | None = None,
    seed: int | None = None,
    retries: int = 3,
    sleeper=time.sleep,
) -> tuple[bytes, float | None, dict]:
```

```python
        payload = build_payload_images(
            pack.model, prompt, aspect_ratio=aspect_ratio,
            structure_png=structure_png, seed=seed, style_png=style_png,
        )
        parse = parse_image_images
    else:
        url = pack.base_url.rstrip("/") + "/chat/completions"
        payload = build_payload(
            pack.model, chat_prompt_with_ratio(prompt, aspect_ratio),
            structure_png=structure_png, seed=seed, style_png=style_png,
        )
```

- [ ] **Step 5: `build_one`'ı slot tablosuna göre yeniden yaz**

`spritegen/cli.py:75` başlayan fonksiyonun baştan `orclient.generate(...)` çağrısına kadarki kısmını şununla değiştir:

```python
def build_one(pack, asset, bible_png):
    """Generate and post-process one asset. Returns a manifest record, never raises.

    Two named slots, because the two images do different jobs and the backend
    routes them by job, not by position:
      structure -- the object to redraw. Only an asset's own crop is ever this.
      style     -- what the result should look like. The pack's [style]
                   reference beside a crop, or the style bible when the asset
                   brought no crop of its own.
    A style image is never sent as a structure: a backend with no style-
    conditioning input transforms it instead, and returns a copy of it.
    """
    out_dir = pack.out_dir
    structure_png = None
    style_png = bible_png
    if asset.reference is not None:
        try:
            structure_png = asset.reference.read_bytes()
        except OSError as exc:
            # Fail this asset only — the pack's other assets are unaffected.
            return _record(pack, asset, "failed",
                           error=f"cannot read reference {asset.reference}: {exc}")
        # With its own crop the asset does not need the bible: the pack's own
        # style image is the better look source, and where there is none the
        # style prefix carries the look on words alone.
        style_png = None
        if pack.style_reference is not None:
            try:
                style_png = pack.style_reference.read_bytes()
            except OSError as exc:
                # full_prompt already promised the model an "image2", so
                # sending one image against that prompt would be a lie.
                return _record(pack, asset, "failed",
                               error=f"cannot read [style] reference "
                                     f"{pack.style_reference}: {exc}")
    try:
        png, cost, _raw = orclient.generate(
            pack,
            pack.full_prompt(asset),
            aspect_ratio=asset.aspect_ratio,
            structure_png=structure_png,
            style_png=style_png,
            seed=pack.seed_for(asset.id),
        )
```

Aynı dosyada `cmd_build` içinde bu bayta verilen yerel adı da düzelt (satır ~236) — artık her zaman style bible'dır:

```python
    bible_png = pack.style_bible.read_bytes() if needs_bible else None
```

ve altındaki `pool.submit(build_one, pack, a, reference)` çağrısında `reference` → `bible_png`.

- [ ] **Step 6: `cmd_make`'in çağrısını `style_png`'e taşı**

`spritegen/cli.py` içinde `cmd_make`'in `orclient.generate` çağrısını değiştir:

```python
            png, cost, _raw = orclient.generate(
                pack, prompt, aspect_ratio=args.aspect_ratio,
                # The prompt already describes the object in full; the image is
                # here as a likeness to match, not a silhouette to trace.
                style_png=image_bytes, seed=i,
            )
```

- [ ] **Step 7: Diğer testlerin stub ve iddialarını uydur**

`tests/test_build.py` içinde kalan `stubs.references` / `stubs.style_pngs` kullanımlarını değiştir:

- `test_build_sends_style_bible_as_reference_on_every_request` testini tümüyle sil — Step 2'deki `test_the_style_bible_travels_as_a_style_reference_not_a_structure` aynı şeyi iki slotu ayırarak söylüyor, ve adı artık yanlış.
- `assert stubs.references == [None, None, None, None]` → `assert stubs.structures == [None, None, None, None]`
- `assert stubs.references == [PLATES[1], PLATES[1], PLATES[1]]` → `assert stubs.styles == [PLATES[1], PLATES[1], PLATES[1]]`
- `assert stubs.references == [b"OWNREF"]      # not the style bible's b"BIBLE"` → `assert stubs.structures == [b"OWNREF"]` ve altına `assert stubs.styles == [None]`
- `test_the_style_image_rides_along_with_an_assets_own_crop` içinde:
  `assert stubs.references == [b"OWNREF"]` → `assert stubs.structures == [b"OWNREF"]`,
  `assert stubs.style_pngs == [b"SHOT"]` → `assert stubs.styles == [b"SHOT"]`
- `test_a_missing_asset_reference_fails_only_that_asset` içindeki `assert stubs.references == [b"OWNREF"]` → `assert stubs.structures == [b"OWNREF"]`

`test_no_style_image_is_sent_when_the_asset_has_no_crop_of_its_own` testini tümüyle şununla değiştir (adı ve iddiası artık yanlış — crop'u olmayan asset style bible'ı style slotunda alır):

```python
def test_an_asset_with_no_crop_gets_the_bible_as_its_style_image():
    """No structure image means nothing to redraw — the bible only says how the
    result should look, and the prompt must not promise an image2 that carries
    a different meaning."""
    tmp = tempfile.mkdtemp()
    spec, refs = _spec_with_style_reference(tmp)
    (refs / "_style.png").write_bytes(b"SHOT")
    with _Stubs({"icon_coin": (b"A", 0.04)}) as stubs:
        cli.main(["build", str(spec), "--out-root", tmp, "--only", "icon_coin"])
    assert stubs.structures == [None]
    assert stubs.styles == [b"BIBLE"]
    assert "REFERENCES" not in stubs.prompts[0]
```

`tests/test_client.py` içinde `reference_png=` geçen her çağrıyı `structure_png=` yap (satır 100, 110, 118, 128, 152, 167, 176).

`tests/test_make.py` içinde stub'ı ve alanı güncelle:

```python
        def fake_generate(pack, prompt, aspect_ratio=None, structure_png=None,
                          seed=None, style_png=None, **kw):
            self.prompts.append(prompt)
            self.references.append(style_png)
            self.seeds.append(seed)
```

(`self.references` adı burada kalır — `make` tek bir referans gönderiyor ve testler o adı okuyor.)

`tests/test_extract.py:503` stub'ını güncelle:

```python
        def fake_generate(pack_, prompt, aspect_ratio=None, structure_png=None,
                          seed=None, **kw):
            calls[seed_to_id[seed]] = structure_png
```

- [ ] **Step 8: Tüm testleri çalıştır**

Run: `py -m pytest -q`
Expected: PASS — yalnızca Global Constraints'te anılan `test_an_absolute_reference_is_not_joined_to_the_pack_dir` kırık kalır.

- [ ] **Step 9: Commit**

```bash
git add spritegen/orclient.py spritegen/cli.py tests/test_build.py tests/test_client.py tests/test_make.py tests/test_extract.py
git commit -m "refactor: two named reference slots, so the style bible stops posing as a structure"
```

---

### Task 2: `images` transport her referansa `role` yazar

spritepipe rolsüz referansı `style` sayar ve çıplak bir style referansını asla kullanmaz. Bu görev olmadan gönderilen iki görsel de ComfyUI'a hiç ulaşmaz.

**Files:**
- Modify: `spritegen/orclient.py` (`image_part`'ın hemen altı, `build_payload_images`)
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: Task 1'in `build_payload_images(model, prompt, aspect_ratio=None, structure_png=None, seed=None, style_png=None)` imzası
- Produces: `orclient.reference_part(data: bytes, role: str) -> dict` — `image_part`'ın çıktısına `"role"` anahtarı ekler

- [ ] **Step 1: Rol testlerini yaz**

`tests/test_client.py` içinde, `test_images_payload_sends_both_references_in_order`'un hemen altına ekle:

```python
def test_images_payload_declares_each_references_role():
    """The local backend routes by role, not by position: an unroled reference
    counts as a style hint and a bare style hint is never used at all."""
    jpeg = b"\xff\xd8\xff\xe0FAKEJPEGBYTES"
    refs = orclient.build_payload_images(
        "m/model", "hello", structure_png=PNG, style_png=jpeg
    )["input_references"]
    assert [r["role"] for r in refs] == ["structure", "style"]


def test_a_lone_style_reference_is_still_marked_style():
    refs = orclient.build_payload_images(
        "m/model", "hello", style_png=PNG
    )["input_references"]
    assert len(refs) == 1
    assert refs[0]["role"] == "style"


def test_a_lone_structure_reference_is_marked_structure():
    refs = orclient.build_payload_images(
        "m/model", "hello", structure_png=PNG
    )["input_references"]
    assert len(refs) == 1
    assert refs[0]["role"] == "structure"
```

- [ ] **Step 2: Testlerin başarısız olduğunu gör**

Run: `py -m pytest tests/test_client.py -q -k role`
Expected: FAIL — `KeyError: 'role'`.

- [ ] **Step 3: `reference_part` ekle ve `build_payload_images`'te kullan**

`spritegen/orclient.py`, `image_part`'ın hemen altına:

```python
def reference_part(data: bytes, role: str) -> dict:
    """One entry of input_references: an image plus the job it does.

    `role` is not in OpenRouter's schema, but the local backend routes on it and
    treats an unroled reference as a style hint — which it then never uses,
    because a text-to-image graph has no style-conditioning input and
    transforming a style hint just returns a copy of it. Sending no role at all
    is therefore the one option that is certainly wrong.
    """
    return {**image_part(data), "role": role}
```

`build_payload_images` gövdesindeki referans listesini değiştir:

```python
    # Same order as build_payload, but the meaning now travels in `role`, not
    # in the position: object first, style second.
    refs = [reference_part(img, role)
            for img, role in ((structure_png, "structure"), (style_png, "style"))
            if img]
    if refs:
        body["input_references"] = refs
```

- [ ] **Step 4: Testleri çalıştır**

Run: `py -m pytest tests/test_client.py -q`
Expected: PASS.

- [ ] **Step 5: Tüm testleri çalıştır**

Run: `py -m pytest -q`
Expected: PASS (bilinen taban hatası hariç).

- [ ] **Step 6: Commit**

```bash
git add spritegen/orclient.py tests/test_client.py
git commit -m "feat: declare each reference's role, so the backend stops discarding both images"
```

---

### Task 3: `chat` transport etiketi görselin yanına serpiştirir

`chat` şemasında `role` diye bir alan yok; eşleşmeyi ancak metin taşır. Tek görsel gönderildiğinde bugünkü ölçülmüş şekil korunur — çözülecek bir belirsizlik yoktur.

**Files:**
- Modify: `spritegen/orclient.py` (`build_payload`)
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: Task 1'in `build_payload(model, prompt, structure_png=None, seed=None, style_png=None)` imzası
- Produces: Aynı imza; yalnızca `content` listesinin şekli değişir

- [ ] **Step 1: Testleri yaz**

`tests/test_client.py` içinde `test_payload_sends_the_style_image_second` testini şununla değiştir:

```python
def test_two_images_are_labelled_beside_themselves_in_chat():
    """chat has no role field, so the label has to sit next to its own image.
    The names are the backend's slot names, which the prompt also uses."""
    jpeg = b"\xff\xd8\xff\xe0FAKEJPEGBYTES"
    content = orclient.build_payload(
        "m/model", "hello", structure_png=PNG, style_png=jpeg
    )["messages"][0]["content"]
    assert [c["text"] for c in content if c["type"] == "text"] == [
        "image1:", "image2:", "hello",
    ]
    assert content[1]["image_url"]["url"] == f"data:image/png;base64,{B64}"
    assert content[3]["image_url"]["url"].startswith("data:image/jpeg;base64,")
```

`test_a_style_image_alone_is_still_sent` testini şununla değiştir:

```python
def test_a_single_image_keeps_the_unlabelled_shape():
    """One image cannot be confused with another, and this shape is the measured
    one — labelling it would change a path that already works."""
    for kwargs in ({"structure_png": PNG}, {"style_png": PNG}):
        content = orclient.build_payload("m/model", "hello", **kwargs)["messages"][0]["content"]
        assert content[0] == {"type": "text", "text": "hello"}
        assert len(content) == 2
        assert content[1]["type"] == "image_url"
```

- [ ] **Step 2: Testlerin başarısız olduğunu gör**

Run: `py -m pytest tests/test_client.py -q -k "labelled or unlabelled"`
Expected: FAIL — `assert ['hello'] == ['image1:', 'image2:', 'hello']`.

- [ ] **Step 3: `build_payload`'ın gövdesini değiştir**

`spritegen/orclient.py`, `build_payload` içindeki `content` kurulumunu şununla değiştir:

```python
    # chat has no per-image role field, so the only thing that can tie an image
    # to its job is text sitting next to it. With one image there is nothing to
    # tie — that shape is left exactly as it was.
    present = [(img, label) for img, label in
               ((structure_png, "image1"), (style_png, "image2")) if img]
    if len(present) < 2:
        content: list[dict] = [{"type": "text", "text": prompt}]
        content += [image_part(img) for img, _ in present]
    else:
        content = []
        for img, label in present:
            content.append({"type": "text", "text": f"{label}:"})
            content.append(image_part(img))
        content.append({"type": "text", "text": prompt})
```

- [ ] **Step 4: Testleri çalıştır**

Run: `py -m pytest tests/test_client.py -q`
Expected: PASS.

- [ ] **Step 5: Tüm testleri çalıştır**

Run: `py -m pytest -q`
Expected: PASS (bilinen taban hatası hariç).

- [ ] **Step 6: Commit**

```bash
git add spritegen/orclient.py tests/test_client.py
git commit -m "feat: label each chat image beside itself, so image1 and image2 cannot swap"
```

---

### Task 4: Prompt `image1` / `image2` sözcüklerini kullanır

Backend `TextEncodeQwenImageEditPlus` sürüyor ve slotlarının adı `image1`/`image2`. Prompt bu adları birebir kullanmazsa iki görsel gitse bile model hangisinin ne olduğunu metinden okuyamaz.

**Files:**
- Modify: `spritegen/config.py` (`REFERENCES_BLOCK`)
- Modify: `spritegen/brief.py:165-182` (`page` fonksiyonunun figür başlıkları)
- Modify: `README.md`
- Test: `tests/test_config.py`, `tests/test_brief.py`

**Interfaces:**
- Consumes: `config.REFERENCES_BLOCK` (Task 1-3 boyunca değişmedi)
- Produces: Aynı sabit, yeni metinle

- [ ] **Step 1: Testleri yaz**

`tests/test_config.py` içinde, `test_the_references_block_appears_only_when_two_images_are_sent`'in hemen üstüne ekle:

```python
def test_the_references_block_uses_the_backends_slot_names():
    """image1/image2 are what TextEncodeQwenImageEditPlus calls its inputs; a
    prompt that says "Image 1" instead names nothing the graph knows."""
    assert "image1" in config.REFERENCES_BLOCK
    assert "image2" in config.REFERENCES_BLOCK
    assert "Image 1" not in config.REFERENCES_BLOCK
    assert "Image 2" not in config.REFERENCES_BLOCK
```

`tests/test_brief.py:138` satırını değiştir:

```python
    assert "image1" in text and "image2" in text
```

- [ ] **Step 2: Testlerin başarısız olduğunu gör**

Run: `py -m pytest tests/test_config.py -q -k slot_names`
Expected: FAIL — `assert 'image1' in 'REFERENCES\n- Image 1 — the object...'`.

- [ ] **Step 3: `REFERENCES_BLOCK`'ta yalnızca adları değiştir**

`spritegen/config.py`'deki blok, canlı bir denemeden sonra genişletildi: crop küçük ve düşük çözünürlüklü bir ekran yakalaması olduğu için model onun *pikselleşmesini* de kimliğinin parçası sanıp geri veriyordu. O metin korunacak — bu adımda **sadece iki ad** değişiyor, başka hiçbir kelime değil:

```python
REFERENCES_BLOCK = (
    "REFERENCES\n"
    "- image1 — the object to redraw. Take its IDENTITY from this and nothing\n"
    "  else: silhouette, proportions, colours, markings, features.\n"
    "  Do NOT take its rendering. image1 is a small low-resolution screen\n"
    "  capture; its pixellation, blocky stair-stepped edges and colour banding\n"
    "  are capture artefacts, not design. Redraw the object cleanly at full\n"
    "  resolution in the ART STYLE below.\n"
    "- image2 — the reference screenshot. Use it ONLY for art style, palette\n"
    "  and lighting. Do not copy any object from it."
)
```

Bloğun üstündeki yorumda geçen "Image 1 needs both halves of its instruction" cümlesini de `image1` yaz. Aynı dosyada `Pack.style_reference` alanının üstündeki yorumdaki `Image 2` ifadesini `image2` yap.

- [ ] **Step 4: `brief.py`'nin başlıklarını uydur**

`spritegen/brief.py`, `page` fonksiyonu içinde üç satır:

```python
        f"<figcaption>image2 — {html.escape(style_image.name)} — upload this "
        "with EVERY message, alongside the crop</figcaption>",
```

```python
            f"<figure><img src='{_data_uri(crop)}' alt=''>"
            f"<figcaption>image1 — {html.escape(crop.name)}</figcaption></figure>",
            f"<p class='pair'>+ image2 — {html.escape(style_image.name)}</p>",
```

- [ ] **Step 5: Kalan `Image 1` / `Image 2` yorumlarını uydur**

`spritegen/cli.py` içindeki `build_one` yorumlarında ve `spritegen/extract.py:287` yorumunda geçen `Image 2` ifadelerini `image2` yap. `spritegen/orclient.py`'de Task 1'de zaten güncellendi.

- [ ] **Step 6: Testleri çalıştır**

Run: `py -m pytest -q`
Expected: PASS (bilinen taban hatası hariç).

- [ ] **Step 7: README'yi güncelle**

`README.md` içindeki "### Per-asset references" bölümünün altına, `[style] reference` paragrafının ardına ekle:

```markdown
Each reference declares the job it does. The `images` transport sends
`role: "structure"` for the asset's own crop and `role: "style"` for the pack's
style image; the `chat` transport has no such field, so it labels each image
`image1:` / `image2:` in the text right before it. Those are the names the
prompt's `REFERENCES` block uses, and they are the input slot names of the local
backend's edit graph — a reference with no role is treated as a style hint and,
on a text-to-image graph, never used at all.
```

`### The prompt build sends` bölümündeki blok listesinde `REFERENCES` satırını güncelle:

```
REFERENCES     (image1 / image2 — only when two images go on the wire)
```

- [ ] **Step 8: Commit**

```bash
git add spritegen/config.py spritegen/brief.py spritegen/cli.py spritegen/extract.py tests/test_config.py tests/test_brief.py README.md
git commit -m "feat: name the reference images image1 and image2, matching the edit graph's slots"
```

---

### Task 5: Canlı doğrulama

Birim testler payload şeklini kanıtlar, görselin iyi olduğunu kanıtlamaz. Bu görev spec'in zorunlu kıldığı ölçümü yapar ve sonucu yazıya döker.

**Files:**
- Create: `docs/plans/2026-08-02-reference-roles-sonuc.md`

**Interfaces:**
- Consumes: Task 1-4'ün tamamı
- Produces: Ölçüm notu; `#808080` sorusunun cevabı sonraki turun girdisi

- [ ] **Step 1: Backend'i ayağa kaldır**

İki ayrı terminalde:

```bash
spritepipe-comfyui        # model arka ucu, :8188
spritepipe-serve          # OpenRouter şeklindeki endpoint, :8000
```

`spritepipe-serve` cevap verene kadar bekle.

- [ ] **Step 2: Tek asset'lik bir build çalıştır ve prompt'u gör**

```bash
py -m spritegen build packs/pf_extracted.toml --dry-run
```

Kontrol et: yazdırılan prompt `REFERENCES` bloğuyla başlıyor ve `image1` / `image2` sözcüklerini içeriyor mu. İçermiyorsa asset'in `reference`'ı ya da pack'in `[style] reference`'ı eksiktir — Task 4'e geri dön.

- [ ] **Step 3: Gerçek üretim**

```bash
py -m spritegen build packs/pf_extracted.toml --only <asset-id>
```

`<asset-id>` yerine pack'teki ilk üç asset'i tek tek dene.

- [ ] **Step 4: Çıktıya üç soruyu sor**

Üretilen PNG'leri `out/pf_extracted/` altında aç ve not al:

1. **structure devrede mi?** Siluet, `refs/<id>.png` crop'una benziyor mu. Bugüne kadar hiç kullanılmadığı için fark bariz olmalı. Benzemiyorsa `role` backend'e ulaşmamış demektir — `spritepipe-serve` loglarına bak.
2. **image2 sahneyi sürüklüyor mu?** Sonuçta ekran görüntüsünden başka nesneler beliriyor mu. Beliriyorsa `[style] reference`'ı tek nesneli bir plakaya çevirmek tek satırlık düzeltme.
3. **`#808080` arka plan geliyor mu?** Edit modeli `image1`'i yeniden çiziyor ve crop'un arka planı gri değil. Gelmiyorsa yerel `rembg`'in keseceği düz zemin yok demektir.

- [ ] **Step 5: Sonucu yaz**

`docs/plans/2026-08-02-reference-roles-sonuc.md` dosyasını oluştur; her üç soru için ne görüldüğünü, hangi asset'lerle denendiğini ve varsa bir sonraki adımın ne olması gerektiğini yaz. Üçüncü soru "hayır" çıkarsa bu dosya bir sonraki turun spec girdisidir — kararı burada verme, gözlemi yaz.

- [ ] **Step 6: Commit**

```bash
git add docs/plans/2026-08-02-reference-roles-sonuc.md
git commit -m "docs: record what the live two-image run actually produced"
```
