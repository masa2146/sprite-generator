# Görsel Analizi — Tasarım Dokümanı

**Tarih:** 2026-07-27
**Durum:** Onaylandı, uygulamaya hazır
**Bağlam:** [2026-07-26-sprite-generator-design.md](2026-07-26-sprite-generator-design.md) üzerine ekleme

## Amaç

Bir referans görselden onun görsel ve teknik özelliklerini çıkarmak — kamera açısı, ışık,
render tekniği, palet, realistik mi cartoon mu — ve bunu iki şeye dönüştürmek:

1. Pack'in `[style] prefix` metni: tüm asset'lere uygulanan stil tarifi.
2. O görselin kendisini/benzerini üretmeye yarayan tam prompt.

Bugün `style.prefix` elle yazılıyor. Elde bir referans görsel varken bunu elle tarif etmek
hem yorucu hem eksik: insan "top-left key light, soft ambient occlusion" demeyi akıl etmez.

## İki uygulama, tek şema

Aynı analiz iki yerden yapılabilir ve **ikisi de aynı şemayı üretir**, böylece biri
diğerinin yerine geçebilir:

| | Claude Code skill'i | CLI (`gen.py analyze`) |
|---|---|---|
| nasıl görür | Claude'un kendi vision yeteneği | `[vision]` endpoint'ine HTTP |
| maliyet | yok (oturum zaten açık) | vision çağrısı (~$0.01 altı) |
| yazar mı | hayır, sadece üretir | pack'e ve style_bible'a yazar |
| ne zaman | elde tek görsel varken, hızlıca | otomasyon, batch, tekrarlanabilirlik |

Skill'in API'ye gitmesine gerek yok: Claude Code görseli doğrudan okuyabiliyor.

## Analiz şeması

Altı stil alanı, artı bir `subject`. Serbest metin değil sabit şema, çünkü prefix'in her
pack'te aynı eksenleri taşıması tutarlılığın kaynağı — model "güzel bir ikon" yazamaz,
altı ekseni de doldurmak zorunda kalır.

```json
{
  "style": {
    "render":   "soft 3D render, glossy plastic material",
    "camera":   "3/4 front view, slight high angle, centered",
    "lighting": "top-left key light, soft ambient occlusion, no harsh shadow",
    "palette":  "#FF6B4A #4ECDC4 #FFE66D #2C3E50",
    "linework": "no outline, rounded geometry, soft bevels",
    "realism":  "stylized cartoon, not photorealistic"
  },
  "subject": "gold coin icon, front view, thick rim, subtle shine, star embossed on face"
}
```

**`style` ile `subject` neden ayrı.** `style` tüm asset'lere uygulanır; `subject` yalnızca
o görsele aittir. Subject prefix'e karışırsa pack'teki her asset o özneye benzemeye başlar
— buton da madeni paraya benzer. Ayrım yapısal, isteğe bağlı değil.

**Alan birleştirme sırası** (prefix ve yeniden üretim prompt'u için sabit):

```
render, camera, lighting, linework, realism, palette
```

Yeniden üretim prompt'u = `subject` + bu sıra.

---

## Claude Code skill'i

**Yer:** `.claude/skills/image-style/SKILL.md` — repoda, git'te versiyonlanır, elle
düzenlenebilir. Başka projelerden erişim için symlink:

```bash
ln -s <repo>/.claude/skills/image-style ~/.claude/skills/image-style
```

Kopyalamak yerine symlink, çünkü kopya iki nüshayı ayrı düşürür.

**Girdi:** bir görsel yolu.

**Çıktı — üç blok:**

1. **Metrik tablosu** — altı stil alanı ve subject, okunabilir biçimde.
2. **Style prefix** — bir pack'in `[style] prefix` alanına doğrudan yapıştırılabilir tek paragraf.
3. **Yeniden üretim prompt'u** — `subject` + stil alanları, o görselin kendisini/benzerini
   üretmeye hazır tam metin.

İstenirse ham JSON'u da basar, `gen.py analyze` çıktısıyla birebir aynı şemada.

**Skill hiçbir dosyaya yazmaz ve hiçbir komut çalıştırmaz.** Sadece okur ve üretir. Yazma
isteyen akış CLI'ın işi. Bu sınır bilinçli: skill'in yan etkisi olmaması, onu her yerde
güvenle çağrılabilir kılıyor.

---

## CLI: `gen.py analyze`

```
gen.py analyze <image> --pack <spec.toml> [--add-asset <id>] [--dry-run]
```

**Akış:**

```
ref.png
  → base64 data URI
  → POST {vision.base_url}/chat/completions
       messages: [{text: ANALYSIS_PROMPT}, {image_url: data URI}]
  → yanıttan JSON çıkar (toleranslı)
  → şemayı doğrula
  → [style] prefix'i pack'e yaz
  → --add-asset verilmişse subject'i yeni [[assets]] girdisi olarak ekle
  → ref.png → out/<pack>/style_bible.png
```

Referans görselin style bible olarak da kopyalanması, elde referans varken `init`/`pick`
adımlarını tamamen gereksiz kılıyor — 4 style plate ≈ $0.16 tasarruf. `init`/`pick`
referansı olmayanlar için durmaya devam ediyor.

### `[vision]` bölümü

```toml
[vision]
base_url = "http://localhost:4000/v1"      # omniroute / litellm
key_env  = "OMNIROUTE_API_KEY"
model    = "anthropic/claude-sonnet-5"
```

Tanımlı değilse `[api]` bölümüne düşer — tek endpoint kullananlar hiçbir şey yazmaz.
Precedence: CLI (`--vision-base-url`, `--vision-model`) > `[vision]` > `[api]` > default.
`key_env` mevcut credential guard'ından geçer: anahtar değeri yapıştırılırsa yükleme anında
durur.

İstek düz OpenAI `/chat/completions` — `modalities` yok, metin çıktısı. Görsel `image_url`
içinde data URI olarak gider, yani `orclient`'ın referans görsel taşıma biçiminin aynısı.

### Kod yerleşimi

Yeni `vision.py`: görsel → şema → prefix metni. `orclient.py`'den retry/backoff döngüsü
`_post_with_retry(url, payload, headers, sleeper)` olarak çıkarılır ve ikisi paylaşır —
vision'a ikinci bir retry kopyası yazılmaz.

---

## TOML'a yazma

`tomllib` stdlib'de **sadece okuma** var. Pack'i parse edip yeniden serialize etmek
dosyadaki bütün yorumları siler — `cutout = false`'un neden orada olduğunu anlatan satır,
transport açıklaması, hepsi.

**Çözüm: hedefli satır değişimi, yeniden serialize yok.**

| işlem | nasıl |
|---|---|
| `[style] prefix` güncelleme | `[style]` bölümündeki `prefix = """..."""` bloğunu bul, yalnızca içeriğini değiştir |
| `[[assets]]` ekleme | dosyanın sonuna yeni blok ekle — hiçbir mevcut satır kaymaz |
| `[style]` bölümü yoksa | ekle, ama `[[assets]]`'ten önceki bir konuma (TOML'da tablo sırası anlamlı) |

**Yazma güvenliği — üç adım, pazarlıksız:**

1. Yazmadan önce `<pack>.toml.bak` yedeği al.
2. Yaz.
3. `tomllib.load` ile geri oku ve doğrula: dosya hâlâ geçerli TOML mü, `prefix` beklenen
   metin mi, asset sayısı beklendiği gibi mi. **Doğrulama başarısızsa yedeği geri yükle**
   ve hata ver.

Bozuk bir TOML yazmak kullanıcının pack'ini kullanılamaz hale getirir. Bu üç adım onu
yapısal olarak imkânsız kılıyor.

---

## Hata yönetimi

| durum | davranış |
|---|---|
| Vision yanıtı JSON değil | toleranslı çıkarma: ` ```json ` bloğu → ilk `{...}` bloğu → başarısızsa ham yanıtı `<image>.analysis-error.txt` olarak yaz |
| Şemada alan eksik | eksik alanları say, **pack'e hiçbir şey yazma** — yarım bir prefix sessizce her asset'i bozar |
| `--add-asset <id>` zaten var | reddet. `load_pack` duplicate id'yi zaten hata sayıyor; yazmak pack'i kullanılamaz hale getirirdi |
| Görsel okunamıyor / desteklenmeyen format | net hata, çıkış kodu 1 |
| Vision endpoint 429/5xx | `orclient`'ın paylaşılan retry'ı: 3 deneme, 2/4 sn |
| Vision endpoint 4xx | retry yok, net hata |

`--dry-run` analizi yapar, üç bloğu basar, **hiçbir dosyaya dokunmaz**.

---

## Test ve doğrulama

Mevcut düzen: framework yok, `assert` bazlı, `python3 test_vision.py`.

**`test_vision.py`:**

```
şema çıkarma:
  düz JSON yanıt
  ```json ``` sarmalı yanıt
  metin içine gömülü JSON
  bozuk yanıt → hata + ham yanıt dosyaya yazıldı
  eksik alan → hata, pack'e yazılmadı

prefix metni kurma:
  alan sırası sabit (render, camera, lighting, linework, realism, palette)
  yeniden üretim prompt'u subject ile başlıyor

TOML yazma:
  yorumlar korunuyor (yazma öncesi/sonrası yorum satırları birebir aynı)
  dosya tekrar parse ediliyor
  prefix değişti, geri kalan satırlar dokunulmadı
  [style] bölümü yoksa ekleniyor, [[assets]]'ten önce

--add-asset:
  yeni asset ekleniyor, asset sayısı bir artıyor
  duplicate id reddediliyor, dosya değişmiyor

güvenlik:
  doğrulama başarısızsa yedekten geri dönülüyor

config:
  [vision] > [api] > default precedence
  key_env guard'ı vision bölümünde de çalışıyor
```

**Ağa çıkmayan smoke test:** `gen.py analyze ref.png --pack packs/hc_v1.toml --dry-run`
sahte bir vision yanıtıyla — üç bloğu basar, dosyaya dokunmaz.

**Canlı doğrulama:** gerçek bir referans görselle `analyze` çalıştır, çıkan prefix'i oku —
görseli gerçekten tarif ediyor mu? Sonra `build --only <id>` ile üretileni referansla
karşılaştır. Bu adım otomatikleştirilemez.

---

## Bilerek kapsam dışı

| şey | neden |
|---|---|
| Skill'in üretim yapması | Skill'in yan etkisiz kalması onu her yerde güvenle çağrılabilir kılıyor |
| Skill'in pack yazması | Aynı sebep. Yazma CLI'ın işi |
| Üretilen çıktının denetlenmesi (drift kontrolü) | Farklı bir özellik, farklı bir akış. Ana spec'te zaten ertelenmiş |
| Çoklu referans görselden ortak stil çıkarma | Tek görsel önce kanıtlansın |
| `subject`'ten otomatik asset id üretme | `--add-asset <id>` ile kullanıcı verir; isim seçimi insan işi |
