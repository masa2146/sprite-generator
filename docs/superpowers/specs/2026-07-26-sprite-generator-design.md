# Sprite Generator — Tasarım Dokümanı

**Tarih:** 2026-07-26
**Durum:** Onaylandı, uygulamaya hazır

## Amaç

Hyper-casual mobil oyunlar için Unity'de kullanılabilir sprite'ları (UI element, karakter,
environment) prompt ve/veya referans görselden üreten bir komut satırı aracı. Çıktı
doğrudan kullanılabilir olmalı: RGBA PNG, temiz alpha kenarı, boş kenar boşluğu kırpılmış.

Asıl problem tek bir görselin kalitesi değil, **bir oyunun 40 asset'inin aynı oyundan
çıkmış gibi görünmesi**. Tasarımın merkezinde bu var.

## Kapsam dışı

- Pixel art. Hosted modeller gerçek piksel grid üretmiyor; bu bir lokal model + palet
  quantization problemi ve ayrı bir proje.
- Spritesheet / atlas paketleme. Unity'nin kendi Sprite Atlas'ı zaten yapıyor.
- Unity `.meta` dosyası üretimi. İleride eklenebilir, ilk sürümde yok.
- Animasyon, frame dizisi.

## Sanat stili hedefi

Hand-painted / stylized 2D, flat / vector UI ve 3D-render görünümlü 2D. Hepsi hosted
image modellerinin güçlü olduğu alanlar.

---

## Mimari

**Yığın:** Python 3.11+, stdlib ağırlıklı.
**Bağımlılıklar:** `requests`, `rembg[gpu]` (BiRefNet session'ı paket içinde geliyor,
ayrı kurulum gerekmiyor), `pillow`. Spec formatı `tomllib` — stdlib, sıfır bağımlılık.

```
sprite_generator/
  gen.py         # CLI: init | pick | build
  orclient.py    # chat/completions sarmalayıcı + yanıt ayrıştırma
  post.py        # bg removal + trim + pad + kaydet
  packs/hc_v1.toml
  out/hc_v1/
    style_bible.png
    manifest.json
    *.png
```

### Komutlar

| komut | ne yapar |
|---|---|
| `gen.py init packs/hc_v1.toml` | 4 aday style plate üretir (her biri buton + ikon + karakter aynı karede), contact sheet açar |
| `gen.py pick hc_v1 2` | seçilen plate'i `style_bible.png` olarak kilitler |
| `gen.py build packs/hc_v1.toml` | tüm asset'leri bible'a referansla üretir, post-process eder, manifest yazar |

Ek flag'ler: `--only id1,id2`, `--dry-run`, `--max-cost`, `--base-url`, `--model`.

### Asset başına akış

```
spec satırı
  → prompt = style.prefix + asset.prompt + BG_CLAUSE + ", aspect ratio N:M"
  → POST {base_url}/chat/completions   (modalities: ["image","text"])
      messages: [text prompt, image_url: data:image/png;base64,<style_bible>]
  → yanıttan görsel bytes ayrıştır
  → rembg(birefnet-general)  → RGBA
  → alpha bbox trim → kare pad
  → out/<pack>/<id>.png + manifest satırı
```

**Trim ve pad tanımı:** alpha > 0 olan piksellerin sınırlayıcı kutusuna kırpılır, sonra
uzun kenarın %4'ü kadar şeffaf margin eklenir ve sonuç kareye tamamlanır (özne ortalanmış).
Kare kenar uzunluğu = `max(w, h) * 1.08`, yukarı yuvarlanmış çift sayı. Yeniden
boyutlandırma yok — sadece kırpma ve şeffaf dolgu, yani hiçbir piksel yeniden örneklenmiyor.

**`cutout` alanı — asset'in türünü belirler:**

| değer | anlamı | pipeline |
|---|---|---|
| `cutout = true` (varsayılan) | Bu asset bir *özne* içeriyor: buton, ikon, karakter | `BG_CLAUSE` eklenir → `cut_background` → `trim_and_pad` |
| `cutout = false` | Bu asset *görselin kendisi*: arka plan, seamless tile | Hiçbiri. `BG_CLAUSE` eklenmez, alpha kesilmez, kırpılmaz |

Bu tek alan, "kırpılsın mı" değil "bu ne tür bir görsel" sorusunu yanıtlıyor — ve pipeline'ın
üç adımını birden yönetiyor. Full-bleed bir gökyüzüne "magenta zeminde izole et" demek ve
sonra arka planını silmeye çalışmak anlamsız; alan bunu yapısal olarak imkânsız kılıyor.

### Stil tutarlılığı — style-seed + referans zinciri

İki fazlı:

1. **Bir kez:** `init` dört aday style plate üretir. Her plate aynı karede bir buton,
   bir ikon ve bir karakter gösterir — böylece stilin asset tipleri arasında tutarlı
   olup olmadığı tek bakışta görülür. Kullanıcı birini seçer, o pack'in style-bible'ı olur.
2. **Her asset için:** style-bible `image_url` olarak isteğe eklenir, ayrıca ortak
   `style.prefix` metni prompt'un başına konur.

Dışarıdan hazır bir referans görsel de doğrudan `style_bible.png` olarak konabilir;
`init`/`pick` zorunlu değil.

### İki tasarım kararı

**1. `BG_CLAUSE` zorunlu sabit.** Her prompt'a şu eklenir:

```
isolated on flat solid #FF00FF background, no shadow, no ground plane
```

Hosted modeller güvenilir alpha kanalı üretmiyor — "şeffaf" istendiğinde damalı zemini
*çiziyorlar*. Buna karşı düz tek renk magenta zemin istemek rembg'nin işini neredeyse
deterministik hale getiriyor. **Kenar kalitesi buradan geliyor, modelden değil.**

**2. `seed = hash(asset.id)`.** Destekleyen sağlayıcılarda aynı spec'i iki kez
çalıştırmak aynı çıktıyı verir.

### Paralellik

`ThreadPoolExecutor(max_workers=4)` — API çağrıları I/O bound. rembg ana thread'de
sıralı çalışır (tek GPU).

---

## Transport ve konfigürasyon

### Neden `/chat/completions`

OpenAI şemasının üç yüzeyi var ve referans görsel açısından eşit değiller:

| yüzey | referans image | OpenRouter | local proxy'ler |
|---|---|---|---|
| `/v1/images/generations` | yok (sadece text→image) | var | değişken |
| `/v1/images/edits` | var, ama multipart form | belirsiz | çoğunda yok |
| `/v1/chat/completions` + `modalities` | var, base64 `image_url` | var | en yaygın |

Style-bible her istekte referans olarak gitmek zorunda olduğu için `generations` tek
başına yetmiyor. `edits` multipart istiyor ve local servislerde desteği belirsiz.
Chat completions üçünü de çözüyor ve hâlâ OpenAI şeması. **Tek transport olarak o seçildi.**

### Config

```toml
[api]
base_url = "https://openrouter.ai/api/v1"   # → "http://localhost:8080/v1"
key_env  = "OPENROUTER_API_KEY"             # → "OMNIROUTER_KEY"

[pack]
model = "google/gemini-3.1-flash-image"
```

Öncelik: CLI flag → spec dosyası → env (`SPRITEGEN_BASE_URL`) → OpenRouter default.

API anahtarı **her zaman** env değişkeninden okunur, spec dosyasına asla yazılmaz.
`key_env` boş veya değişken tanımsızsa `Authorization` header hiç gönderilmez — anahtar
istemeyen local servisler böyle çalışır.

### İstek gövdesi

```json
POST {base_url}/chat/completions
{
  "model": "...",
  "modalities": ["image", "text"],
  "messages": [{"role": "user", "content": [
    {"type": "text", "text": "<prefix> <asset.prompt> <BG_CLAUSE>, aspect ratio 3:4"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,<style_bible>"}}
  ]}],
  "usage": {"include": true}
}
```

### Chat completions'ın iki kaybı

1. **`aspect_ratio` yapısal alan değil** → prompt'a metin olarak enjekte ediliyor.
   Çıktı zaten trim + pad'den geçtiği için birkaç piksellik sapma önemsiz.
2. **`seed` her sağlayıcıda desteklenmiyor** → gönderilir, destekleyen kullanır,
   desteklemeyen yok sayar. Yeniden üretilebilirlik "garanti" değil "mümkünse"
   seviyesinde. Manifest prompt'un tam metnini sakladığı için elle tekrar üretim yine mümkün.

### Yanıt ayrıştırma

Görsel `choices[0].message.images[0].image_url.url` (data URI) alanından okunur.
Bulunamazsa `content` içindeki data URI'lar taranır. Sağlayıcılar arasında en çok burası
kaydığı için ayrıştırma toleranslı; hiçbir görsel bulunamazsa ham JSON `<id>.error.json`
olarak yazılır.

---

## Spec dosyası formatı

```toml
[api]
base_url = "https://openrouter.ai/api/v1"
key_env  = "OPENROUTER_API_KEY"

[pack]
model = "google/gemini-3.1-flash-image"

[style]
prefix = """
hypercasual mobile game asset, soft 3D render look, glossy plastic material,
rounded geometry, no outline, top-left key light, soft ambient occlusion,
palette #FF6B4A #4ECDC4 #FFE66D #2C3E50
"""
plate_prompt = "a play button, a coin icon, and a small round character, side by side"

[defaults]
aspect_ratio = "1:1"

[[assets]]
id     = "btn_play"
prompt = "play button, rounded rectangle, white triangle glyph"

[[assets]]
id     = "hero_idle"
prompt = "small round blue character, idle pose, front view"
aspect_ratio = "3:4"

[[assets]]
id     = "bg_sky"
prompt = "seamless pastel sky gradient with soft clouds"
cutout = false                # görselin kendisi, özne değil
```

**Kategori enum'u (ui / char / env) bilerek yok.** Kategori yalnızca iki şeyi
değiştiriyordu: `aspect_ratio` ve pipeline davranışı. İkisi de zaten asset seviyesinde alan
(`aspect_ratio` ve `cutout`). Enum, üstlerine bir soyutlama katmanı eklemekten başka iş
yapmazdı.

---

## Hata yönetimi

**Tek kural: kısmi başarı asla tüm batch'i düşürmez.**

| durum | davranış |
|---|---|
| HTTP 429 / 5xx | 3 deneme, 2/4/8 sn bekleme. Sonra asset `failed`, sıradakine geç |
| HTTP 4xx (kötü prompt, model yok) | retry yok, anlamsız. `failed`, sebep manifest'e |
| rembg hatası | ham PNG `<id>.raw.png` olarak saklanır, `failed` işaretlenir — harcanan para çöpe gitmez |
| yanıtta görsel yok | ham JSON `<id>.error.json`, `failed` |
| `style_bible.png` yok | `build` en başta reddeder: "önce `init` + `pick` çalıştır" |
| API anahtarı yok (ve `key_env` dolu) | hemen çık |

### Bütçe koruması

`--max-cost` varsayılan olarak açık (5 USD). Her yanıtın `usage.cost` alanı toplanır;
sınır aşılırsa **sıradaki istek gönderilmeden** durulur ve o ana kadarki manifest yazılır.
200 satırlık bir spec'te tek bir yazım hatası pahalıya patlar, o yüzden burada
sadeleştirme yapılmıyor. Sınır `init` için de geçerlidir — dört style plate de aynı
sayaçtan düşer.

`usage.cost` OpenRouter'a özel bir alan. Local bir serviste gelmezse `--max-cost`
uygulanamaz; araç bir kez uyarı basar (`cost reporting unavailable, --max-cost disabled`)
ve devam eder. Sessizce koruma varmış gibi davranmaz. Local servis zaten para harcamaz.

### Build sonu özeti

```
done: 10 ok, 2 failed  ($0.47 / $2.00)
failed: hero_run (429 x3), bg_sky (rembg: shape error → bg_sky.raw.png)
retry: python gen.py build packs/hc_v1.toml --only hero_run,bg_sky
```

---

## Manifest

Üretilen her asset için bir JSON satırı: `id`, tam prompt metni, model, base_url, seed,
`usage.cost` (yoksa `null`), çıktı dosya yolu, durum (`ok` / `failed`) ve hata sebebi.
Neyin nasıl üretildiğini geri izlemeyi ve elle yeniden üretmeyi sağlar.

---

## Test ve doğrulama

Framework yok, fixture yok. `assert` bazlı, `python test_post.py` ile doğrudan çalışır.

### `test_post.py`

Pipeline'ın tek gerçek algoritmik parçası burası; bozulursa her asset sessizce bozulur.

```
sentetik 512x512: #FF00FF zemin + merkezde 200x200 mavi kare
  → post.process(trim=True)
assert köşe pikseli alpha == 0          # zemin gitti
assert merkez pikseli alpha == 255      # özne bozulmadı
assert çıktı kare                       # pad doğru
assert 200 <= w <= 240                  # trim kırptı ama aşırı kırpmadı
  → post.process(trim=False)
assert boyut 512x512 korundu            # env asset'i kırpılmadı
```

### `test_client.py`

Sağlayıcı farkları en çok burayı kırar. Ağa çıkmadan, sahte JSON ile:

```
assert parse(images alanı olan yanıt) → doğru bytes
assert parse(sadece content'te data URI olan yanıt) → fallback çalıştı
assert parse(görsel içermeyen yanıt) → raise + .error.json yazıldı
assert 429 → 3 deneme sonra failed, süreç devam etti
assert config precedence: CLI > spec > env > default
assert key_env boş → Authorization header yok
```

### Ağa çıkmayan smoke test

`gen.py build --dry-run` tüm spec'i parse eder, her prompt'un tam metnini ve tahmini
maliyeti basar, tek istek atmaz. Spec yazım hataları buradan yakalanır.

### Canlı doğrulama (tek seferlik, ~$0.04)

`gen.py build packs/hc_v1.toml --only btn_play` → çıkan PNG Unity'ye atılır,
`Alpha Is Transparency` davranışı ve kenar halo'su gözle kontrol edilir. Bu adım
otomatikleştirilemez; gerçek kalite kararı burada verilir.

### Bilerek test edilmeyenler

rembg'nin kendi doğruluğu (upstream sorumluluğu), gerçek API çağrıları (para +
kırılgan), Unity import (manuel).

---

## Bilerek ertelenenler

| şey | neden ertelendi | ne zaman eklenir |
|---|---|---|
| CLIP drift kontrolü | torch + CLIP ağırlığı; style-bible referansı işin büyük kısmını zaten yapıyor | gözle bakınca gerçekten stil kayması yaşanırsa |
| Unity `.meta` üretimi | ~60 satır YAML template, ilk sürüm için gerekli değil | elle import ayarı yapmak sıkıcı hale gelince |
| Atlas / spritesheet packing | Unity Sprite Atlas zaten yapıyor | muhtemelen hiç |
| Varyant seçimi (n=4 + contact sheet) | 4x maliyet, batch otomatikliğini kırar | tek geçişte kabul oranı düşük çıkarsa |
| Lokal LoRA / Flux | GPU + saatlerce eğitim; hosted çözüm önce kanıtlansın | tutarlılık hosted ile yeterli olmazsa |

## Referanslar

- [OpenRouter Unified Image API duyurusu](https://openrouter.ai/blog/announcements/image-api/)
- [OpenRouter image generation dokümanı](https://openrouter.ai/docs/guides/overview/multimodal/image-generation)
- [BiRefNet vs rembg vs U2Net karşılaştırması](https://dev.to/om_prakash_3311f8a4576605/birefnet-vs-rembg-vs-u2net-which-background-removal-model-actually-works-in-production-4830)
- [rembg](https://github.com/danielgatis/rembg)
- [Unity AI Sprite Generator](https://unity.com/blog/unity-ai-sprite-generator) — kıyas noktası
