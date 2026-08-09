# Skill-first pipeline — Tasarım Dokümanı

**Tarih:** 2026-08-10
**Durum:** Onaylandı, plana hazır
**Kapsam:** Spec 1/2. Spec 2 (`character_lib`) ayrı yazılacak.

## Amaç

Proje artık bir CLI değil, üç skill üzerinden kullanılacak. Sprite üretimi
diffusion modelinden (OpenRouter, yerel spritepipe) tamamen çıkıyor; üretimi
`procedural-sprites` Python koduyla yapıyor. Bu doküman diffusion kodunun
sökülmesini, hayatta kalan kodun skill'lerin içine taşınmasını, üç skill'in
birbirine bağlanmasını ve çalışma alanının yeniden düzenlenmesini tanımlar.

## Bağlam

Bugünkü hâl:

- `spritegen` paketi 13 modül, 10 alt komut. Bunların çoğu bir görsel üretim
  API'sine (OpenRouter `/images`, OpenAI-şema `/chat/completions`, yerel
  spritepipe) bağlı.
- `sprite-brief` skill'i `spritegen brief` çağırıyor (bu kısım API'siz: kırpma,
  temizlik, contact sheet), sonra Gemini/ChatGPT'ye elle yapıştırılacak
  prompt'lar üretiyor ve adım 7'de yerel diffusion backend'ini teklif ediyor.
- `image-style` skill'i hiçbir akışa bağlı değil: yalnızca rapor basıyor ve tek
  entegrasyonu ölecek olan `spritegen analyze`.
- `procedural-sprites` skill'i `analysis.json` formatını "doğrudan tüket" diyor
  ama kimse ona bu dosyayı vermiyor; kullanıcı elle çağırıyor.

Nesne, UI ve tile üretiminde prosedürel yol ölçülü biçimde iyi sonuç veriyor.
Karakterde yetersiz — o Spec 2'nin konusu.

## Kararlar

| konu | karar |
|---|---|
| paketleme | `spritegen` paketi ve console script silinir; hayatta kalan Python skill'lerin `scripts/` klasörlerine iner |
| brief çıktısı | `brief.html` → `review.html`: crop + ölçülen palet + alanlar. Image-model prompt blokları silinir |
| `cut` / rembg | silinir; bağımlılık `pillow` + `numpy`'a iner |
| `image-style` | ayrı skill kalır, **her akışta çalışır**, çıktısı `analysis.json`'un `style` bloğudur |
| girdi görselleri | opsiyonel; kırpma bir karar, zorunluluk değil |
| çalışma alanı | `sprites-generated/`, gitignore'da; her set için `brief/ scripts/ out/ qc/` |
| Python çalıştırma | `sprites-generated/.venv/bin/python` — zorunlu |
| kod yazımı | asset başına bir subagent; ortak sanat yönü ana thread'de |

## Kapsam dışı

- `character_lib.py` ve karakter kalitesi (Spec 2).
- Mevcut `sprites/` klasörü. Eski oyunun yerel işi, gitignore'da kalır, taşınmaz.
- `docs/plans/` ve `docs/specs/` altındaki eski dokümanlar. Tarihsel kayıt,
  yazıldığı gibi durur — diffusion'dan bahsetmeleri düzeltilecek bir hata değil.

## 1. Mimari: ne ölür, ne kalır

### Silinir

| dosya | sebep |
|---|---|
| `spritegen/orclient.py` | iki HTTP transport'u, retry, cost ayrıştırma |
| `spritegen/config.py` | pack/api/transport/key makinesi + image-model prompt blokları |
| `spritegen/cli.py` | 10 alt komutun tamamı |
| `spritegen/packwriter.py` | TOML pack düzenleme |
| `spritegen/export.py` | pack → image-model HTML'i |
| `spritegen/cutout.py`, `spritegen/post.py` | rembg kesme, trim/pad, palette match |
| `spritegen/envfile.py`, `.env`, `.env.example` | API anahtarı yükleme |
| `spritegen/vision.py` | API çağrısı yapan her şey (`analyze`, `analyze_objects`, prompt sabitleri) |
| `spritegen/extract.py` | pack yazan yarısı (`pack_text`, `exclusion_clause`, `exclusion_names`) |
| `tests/test_build.py`, `test_client.py`, `test_config.py`, `test_env.py`, `test_export.py`, `test_make.py`, `test_packwriter.py`, `test_post.py`, `test_cutout.py` | ölen kodun testleri |
| `pyproject.toml`: `[project]`, `[project.scripts]`, `requests`, `rembg`, setuptools | paket kalmıyor |

### Yaşar ve taşınır → `.claude/skills/sprite-brief/scripts/`

| yeni dosya | kaynağı | içeriği |
|---|---|---|
| `brief.py` | `spritegen/brief.py` (HTML kısmı yeniden yazılır) | analiz okuma, akış, `review.html` |
| `crops.py` | `spritegen/extract.py`'nin saf PIL yarısı | `reject_reason`, `screen_objects`, `padded_box` (`BOX_PAD = 0.12`), `crop_objects`, `find_contents`, `blank_contents`, `ring_median`, `labelled_sheet` |
| `refclean.py` | `spritegen/refclean.py` | aynen: letterbox şeridi, `flat_field`, `upscale`, `row_flatten`, `palette` ölçümü, `clean_crops` |

`spritegen/vision.py`'den yalnızca saf metin parçaları `brief.py` içine taşınır:
`VIEW_POOL`, `DEFAULT_VIEW`, `ROTATION_DEGREES`, `normalise_views`, alan
etiketleri. Bunların hiçbiri API'ye dokunmuyor.

### Sonuç ağaç

```
.claude/skills/
  sprite-brief/       SKILL.md + scripts/{brief.py, crops.py, refclean.py}
  image-style/        SKILL.md
  procedural-sprites/ SKILL.md + references/ + scripts/{sprite_lib.py, sdf3d.py}
tests/                test_brief.py, test_crops.py, test_refclean.py, conftest.py
docs/                 (dokunulmaz) + bu doküman
README.md  CLAUDE.md  LICENSE  pyproject.toml (yalnız pytest ayarı)
sprites-generated/    gitignored çalışma alanı
```

Kurulum adımı yok. Skill başka bir projeye symlink'lendiğinde `scripts/`
beraberinde gider; tek bağımlılık `pillow` + `numpy`.

## 2. `analysis.json` şeması (v2)

Tek girdi dosyası. `--image` flag'i kalkar: görsel yolları analizin içindedir,
çünkü iterasyon döngüsü zaten "analizi düzelt, script'i yeniden çalıştır".

```json
{
  "style": {
    "render": "soft 3D render, glossy plastic material",
    "camera": "3/4 front view, slight high angle",
    "lighting": "top-left key light, soft AO",
    "palette": "#FF6B4A #4ECDC4 #FFE66D",
    "linework": "dark contour, rounded geometry",
    "realism": "stylized cartoon"
  },
  "style_source": {
    "render": "kullanıcı", "camera": "stil görseli", "lighting": "stil görseli",
    "palette": "ölçüm", "linework": "stil görseli", "realism": "kullanıcı"
  },
  "style_image": "shot.png",
  "objects": [
    {
      "id": "bull_totem",
      "source": "shot.png",
      "bbox": [30, 140, 690, 1010],
      "subject": "...",
      "form": "...",
      "detail": "...",
      "views": ["front", "three_quarter"],
      "state": "empty, without the object it normally holds",
      "flatten_rows": false,
      "blank": [[x1, y1, x2, y2]]
    }
  ]
}
```

Değişenler:

- `style` tek satır değil, altı alanlı nesne (`image-style` şeması).
- `style_source` yeni: her alanın nereden geldiği — `kullanıcı`, `stil görseli`,
  `referans`, `ölçüm`, `varsayılan`. `review.html` bunu her alanın yanında basar.
- `style_image` opsiyonel.
- `source` yeni: nesnenin geldiği görsel. Yoksa `style_image`, o da yoksa nesne
  görselsizdir.
- `bbox` artık opsiyonel. Yoksa kaynak görselin tamamı kullanılır.
- `camera` alanı artık serbest — hatta gerekli (aşağı bakınız).

Korunan kurallar (bugünkü `sprite-brief` SKILL.md'den, aynen geçerli):
`id` deseni `^[A-Za-z0-9][A-Za-z0-9_-]*$`; `bbox` nesnenin tam kapsamını içerir;
`views` yalnızca havuzdaki adları alır; bir sprite **şekli** başına bir kayıt;
en küçük yeniden kullanılabilir birim; ölçek kontrolü; `style` nesne adı
içeremez; `blank` kaynak-görsel pikselleridir; rakam/harf/etiket asla
`subject`/`form`/`detail`'e yazılmaz.

Düşen kural: "`style` kamera açısı adlandıramaz". Sebebi prompt'taki VIEW
satırıyla çelişmesiydi; prompt yolu ölüyor ve kamera artık paylaşılan render
sabitini besliyor.

## 3. `sprite-brief`: girdiler opsiyonel, kırpma bir karar

**CLI:**

```bash
<venv>/bin/python .claude/skills/sprite-brief/scripts/brief.py \
    --analysis analysis.json --out-dir sprites-generated/<set>/brief [--no-open]
```

`style_image` ve `source` yolları **analiz dosyasına göre** çözülür, çalışma
dizinine göre değil: analiz kendi görselleriyle birlikte taşınabilir olmalı.

**Kırpma kararını skill verir:**

| girdi | davranış |
|---|---|
| görsel yok, yalnızca metin | `bbox` yok, `refs/` boş, kırpma çalışmaz; stil kullanıcının sözlerinden |
| tek görsel, tek nesne kadrajı dolduruyor | kırpma yok; görsel `refs/<id>.png` olur, yine temizlikten geçer |
| tek ekran görüntüsü, çok nesne | nesne başına `bbox`, her biri ayrı kırpılır (bugünkü davranış) |
| birden çok bağımsız görsel | her görsel kendi nesnesi (`source`), kırpma yok; içlerinden biri çok nesne taşıyorsa yalnız o kırpılır |

Temizlik her hâlde çalışır ve opsiyonel değildir: letterbox şeridi, ışık
rampasının düzlenmesi, upscale ve **crop'un gerçek renklerinin ölçülmesi**.
Ölçüm gerekçesi kayıtlı: bir konveyörün kanalına "soluk leylak-beyaz" denmişti,
gerçek değeri `#434375`.

**`review.html`** — `brief.html`'in yerine:

- üstte stil bloğu: altı alan, her birinin yanında `style_source` etiketi; varsa
  stil görseli
- her nesne için: crop (yoksa "görsel yok"), ölçülen palet swatch + hex,
  `subject`/`form`/`detail`/`state`, `views`, kaynak görsel adı
- image-model blokları (`REFERENCES`, `OBJECT`, `OUTPUT`, `DO NOT DRAW`,
  `#808080` backdrop, ban listesi) yok
- amacı tek: kod yazılmadan önce gözle onay

Reddedilen kutular sebebiyle basılır ve kullanıcıya aktarılır; sessizce
düşürülmez.

## 4. `image-style`: her akışta çalışır, alan bazında override

Skill artık akışın parçası. Stil görseli olsun olmasın çalışır.

**Alan bazında öncelik:** kullanıcının sözleri > stil görseli > referans
görsel(ler) > varsayılan.

Kullanıcının söyledikleri esastır ve **yalnızca dokundukları alanı** değiştirir.
Görsel jelly-cartoon iken kullanıcı "pixel" derse `render` ve `realism`
kullanıcıdan, `camera`/`lighting`/`palette`/`linework` görselden gelir.
Kullanıcı "daha koyu palet" derse yalnızca `palette` değişir.

Her alanın kaynağı `style_source`'a yazılır ve `review.html`'de görünür, böylece
yanlış override gözle yakalanır. Kullanıcının değinmediği ve görselden
okunamayan alan `varsayılan` damgasıyla görünür — sessizce uydurulmaz.

**Sonuç:** `render` + `realism` artık `procedural-sprites`'ın çizim şeridini
seçer — soft-3D (SDF raymarch), düz vektör/glossy 2D, ya da pixel-grid. Stil
analizi bir görünüş notu değil, kod yolu kararıdır.

`image-style` SKILL.md'den `spritegen analyze` bölümü silinir; yerine
`analysis.json`'un `style` + `style_source` bloklarını üretme talimatı gelir.

## 5. Çalışma alanı ve venv

```
sprites-generated/
  .venv/                      pillow + numpy — bir kez kurulur, tüm setler paylaşır
  <set-adı>/
    brief/    analysis.json · review.html · refs/{_style.png,_contact_sheet.png,<id>.png}
    scripts/  style.py · <asset>.py · sprite_lib.py + sdf3d.py kopyası
    out/      teslim edilecek PNG'ler
    qc/       _qc_sheet.png · cmp_<id>.png · _silhouette.png
```

`<set-adı>` kullanıcının verdiği addır; vermediyse analizin baskın nesnesinden
ya da kaynak görselin adından türetilir ve kullanıcıya söylenir.

`sprite_lib.py` / `sdf3d.py` sete **kopyalanır** — kopyalamayı
`procedural-sprites` ilk çalıştırmada yapar. Set kendi başına yeniden çalışır,
skill sonradan değişse bile.

**Venv zorunlu.** Her Python çalıştırması `sprites-generated/.venv/bin/python`
iledir. Yoksa skill kurar:

```bash
python3 -m venv sprites-generated/.venv
sprites-generated/.venv/bin/pip install -q pillow numpy
```

`.gitignore`: `sprites-generated/` eklenir. Ölü satırlar silinir: `packs`,
`out/`, `.env`, `briefs`, `*.toml.bak`. `sprites/` kalır.

## 6. Zincir

```
kullanıcı: [görsel(ler)] + [stil görseli] + metin
        │
        ├─ image-style  → style{6 alan} + style_source        (her zaman çalışır)
        ▼
   sprite-brief → brief/{analysis.json, review.html, refs/}
        │          kendi crop kontrolünü yapar, sorunları söyler
        │          sonra TEK soru: "şimdi koda dökelim mi?"
        ▼
   procedural-sprites
```

`procedural-sprites` brief'siz de çağrılabilir; girdisi ya
`brief/analysis.json`, ya doğrudan kullanıcı tarifi. Brief zorunlu değildir.

`sprite-brief` SKILL.md'den silinecek bölümler: adım 7 (yerel endpoint teklifi),
`spritegen check` / `build --only` döngüsü, `structure_mode` / `palette_master`
/ `--seed-offset` tavsiyeleri, backend'in "uydurulmuş renk" ve "izometrik kayma"
arıza modları, "her mesajda iki görseli yükle" talimatı. Yerine: kırpma karar
tablosu, `review.html` kontrolü ve `procedural-sprites`'a devir.

## 7. Subagent döngüsü

**Ana thread:**

1. Analizi okur (ya da kullanıcı tarifini alır).
2. `scripts/style.py` yazar — setin tamamının okuduğu tek sanat yönü dosyası:
   `PALETTE` sözlüğü, `LIGHT` vektörü, `CAMERA` eğimi, `MATERIALS` tablosu,
   `CONTOUR` kalınlığı, `SS` (supersample), hedef boyutlar.
3. Asset listesini ve her asset için görev tarifini çıkarır.
4. Subagent'ları açar: bağımsız asset'ler paralel.

**Asset başına bir subagent:**

1. `scripts/<asset>.py` yazar (yalnızca kendi dosyası).
2. `sprites-generated/.venv/bin/python` ile çalıştırır.
3. `out/<asset>.png` üretir; referans varsa `qc/cmp_<asset>.png`, ayrıca oyun
   boyutunda okunurluk kontrolü.
4. **Çıktıya kendisi bakar**, farkları adlandırır, en büyüğünü düzeltir; 2–4 tur.
5. Kısa makbuz döner:

```
asset:   bull_totem
files:   scripts/bull_totem.py, out/bull_totem.png, qc/cmp_bull_totem.png
rounds:  3
remaining: boynuz ucu referanstan %10 kısa — kasıtlı, oyun boyutunda fark okunmuyor
blocked:  -
style_request: -
```

Kural: subagent `style.py`'a **dokunamaz**. Farklı palet/ışık gerekiyorsa
`style_request` alanında bildirir; kararı ana thread verir. Sebebi: otuz sprite'ı
tek sanatçının işi gibi gösteren şey ortak sabitlerdir, ve onu her subagent'ın
kendi ihtiyacına göre eğmesi setin tamamını dağıtır.

**Ana thread kapanışta:** `qc/_qc_sheet.png` — hepsi bir arada, oyun boyutunda,
oyunun arkaplan renginde. Ona bakar; palet, çizgi kalınlığı ve ışık yönü
tutarlılığını karara bağlar; gerekiyorsa hedefli ikinci tur açar.

**Token gerekçesi:** render edilen PNG'ler subagent bağlamında kalır. Ana thread
yalnızca makbuzları ve tek QC sheet'i görür.

## 8. Hata yönetimi

| durum | davranış |
|---|---|
| kutu reddedildi (kadraj dışı, sıfır alan, >%90 alan, <16px kenar) | sebebiyle basılır ve kullanıcıya aktarılır; sessizce düşmez |
| `analysis.json` alanı eksik/bozuk | hangi nesnede ne eksik denerek durur; yarım çıktı yazmaz |
| kaynak görsel okunamıyor | o nesne başarısız, diğerleri devam eder |
| venv yok | skill kurar; kurulum başarısızsa durur ve komutu gösterir |
| script traceback verdi | subagent düzeltir; 3 denemede olmuyorsa makbuzda `blocked` + traceback |
| subagent farklı palet/ışık istiyor | `style.py`'a dokunmaz, `style_request` ile bildirir |
| bir asset teslim edilemedi | set yine teslim edilir; eksik olan adıyla ve sebebiyle söylenir |

## 9. Testler

`tests/` altında, ağ yok, model indirme yok (ikisi de kodda kalmıyor). Mevcut
kalıp korunur: düz fonksiyonlar, fixture yok, plugin yok.

| dosya | kapsam |
|---|---|
| `test_crops.py` | kutu doğrulama sınırları, `%12` padding, iç içe kutuların silinmesi, contact sheet üretimi *(mevcut `test_extract.py`'den devralınır)* |
| `test_brief.py` | dört kırpma hâli, `style_source` override önceliği, `review.html` render'ı, hatalı analizin raporlanması *(mevcut dosya genişletilir)* |
| `test_refclean.py` | letterbox şeridi, ışık rampası düzleme, ölçülen palet *(yeni — bugün testi yok)* |
| `conftest.py` | skill `scripts/` yolunu `sys.path`'e ekler; kurulum gerekmez |

`pyproject.toml` yalnızca `[tool.pytest.ini_options]` taşır.

## 10. Dokümantasyon

- `README.md` yeniden yazılır: paket/CLI/pack/transport/anahtar/maliyet
  bölümlerinin tamamı gider. Yerine üç skill, zincir, `sprites-generated`
  düzeni, venv ve `analysis.json` şeması.
- `CLAUDE.md` yeniden yazılır: mimari bölümü artık skill'leri ve `scripts/`
  yerleşimini anlatır; ölü değişmezler (transport, key_env, reference rolleri,
  `cutout=false`, grey backdrop, `build_one` sözleşmesi) silinir; kalanlar
  (kutu reddi sessiz olamaz, ölçülen palet, tek sanat yönü dosyası, subagent
  `style.py`'a dokunamaz) korunur.
- `docs/` altındaki eski plan ve tasarım dokümanlarına dokunulmaz.

## Kabul kriterleri

1. `spritegen/` klasörü yok; `pip install` adımı hiçbir yerde geçmiyor.
2. `.py` dosyalarında ve üç `SKILL.md`'de `openrouter`, `rembg`, `requests`,
   `transport`, `key_env`, `diffusion` geçmiyor (`docs/` hariç — tarihsel kayıt).
3. `python3 -m pytest` yeşil; ağ çağrısı yok.
4. Uçtan uca duman testi: bir ekran görüntüsü + metinden `review.html` üretilir,
   onaydan sonra `sprites-generated/<set>/out/` altında en az bir PNG ve
   `qc/_qc_sheet.png` oluşur; tüm Python çalıştırmaları venv üzerinden geçer.
5. `sprites-generated/` gitignore'da; repo çalışma çıktısı taşımıyor.
