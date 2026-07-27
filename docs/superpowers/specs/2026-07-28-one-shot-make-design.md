# Tek Atışlık `make` Akışı — Tasarım Dokümanı

**Tarih:** 2026-07-28
**Durum:** Onaylandı, uygulamaya hazır
**Bağlam:** [2026-07-26-sprite-generator-design.md](2026-07-26-sprite-generator-design.md) ve
[2026-07-27-image-analysis-design.md](2026-07-27-image-analysis-design.md) üzerine ekleme

## Amaç

TOML yazmadan tek komutla sprite üretmek. Kullanıcı bir görsel, bir metin ya da ikisini
birden verir; araç görseli detaylıca yorumlar, kullanıcı metnini üstüne bindirir ve
görüntü modeline hazır bir prompt gönderir.

Mevcut `build`/`init`/`pick`/`analyze` akışı bir *set* üretmek için tasarlandı ve elle
yazılmış bir pack dosyası gerektiriyor. Tek bir nesne denemek isteyen kullanıcı için bu
ağır: pack yaz, style bible seç, sonra üret. `make` o adımların hepsini atlar.

## Neden bu ekleme gerekli — ölçülmüş başarısızlık

İlk canlı denemede bir oyun ekran görüntüsünden dört nesne üretildi ve dördü de
referanstan uzak çıktı. Sebep üç katmanlıydı:

1. **Asset prompt'ları elle, referansa bakılarak *yorumlanarak* yazıldı.** Referanstaki
   bloklar dikey kapsül şeklindeyken prompt "dört studlu yuvarlak küp" diyordu. Model
   yanlış tarifi sadakatle üretti.
2. **Referans olarak tüm ekran görüntüsü gönderildi.** Model 704×1526'lık kalabalık bir
   UI'a bakıp tek bir nesne üretmeye çalıştı; hangi piksellere bakacağını söyleyen bir
   şey yoktu.
3. **Şema tek nesne için fazla dardı.** `subject` tek satırlık bir cümleydi; dispenser'ın
   iki parçalı yapısı, blokların kapsül geometrisi o satıra sığmadı.

`make` üçünü de hedefliyor: prompt elle yazılmaz (görselden çıkar), referans tek nesnedir
(kullanıcının verdiği görselin kendisi), şema genişler.

## Şema genişlemesi

Mevcut altı stil alanı + `subject` korunuyor, iki alan ekleniyor:

| alan | ne yakalar |
|---|---|
| `render` | render tekniği ve materyal |
| `camera` | açı ve çerçeveleme |
| `lighting` | ışık yönü, yumuşaklık, gölge |
| `palette` | baskın renkler, hex |
| `linework` | outline ve geometri |
| `realism` | stilizasyon ekseni |
| **`form`** | **geometrik yapı: kaç parça, oranlar, belirgin özellikler** |
| **`detail`** | **ayırt edici küçük özellikler: kenar payı, kalınlık, yüzey işlemesi, rozet** |
| `subject` | nesnenin ne olduğu |

`form` olmadan model "bir dispenser" duyar ve geometriyi kendi uydurur. `form` ile "üstte
yivli panel, altta yuvarlak köşeli kutuda dikey yuva" duyar. Ölçülmüş başarısızlığın
doğrudan karşılığı bu alan.

**Bu genişlemenin `analyze` üzerindeki etkisi.** Şema `vision.py`'de tek yerde tanımlı, o
yüzden `analyze` de artık `form` ve `detail` ister — eksikse analiz reddedilir, tıpkı
diğer alanlarda olduğu gibi. Ama pack'in `[style] prefix`'i **değişmez**: `style_prefix`
yalnızca altı stil alanından kurulur. `form` ve `detail` özneye aittir, stile değil — pack
prefix'ine girerlerse her asset o tek nesnenin geometrisine kayar, ki bu tam olarak
`subject`'i prefix'ten uzak tutma sebebinin aynısı.

**Prompt birleştirme sırası** (sabit):

```
subject, form, detail, render, camera, lighting, linework, realism, palette
```

Özne önce, sonra geometri, sonra yüzey, en sonda palet — genelden özele değil, önemliden
önemsize.

## Metin ve görselin birleşmesi

Kullanıcı metni **alan bazında önceliklidir**: gördüğüyle çeliştiği alanlarda metin
kazanır, çelişmediği alanlar görselden dolar.

Bu **tek bir vision çağrısında** çözülür. İki ayrı çağrı yapıp sonuçları programatik
olarak birleştirmek daha kırılgan olurdu: "kırmızı olsun" ifadesinin `palette` alanını mı
yoksa `subject` alanını mı ezdiğine karar vermek, modelin zaten yaptığı bir iş.

```
[görsel] + ANALYSIS_PROMPT + USER_OVERRIDE_CLAUSE
```

`USER_OVERRIDE_CLAUSE` yalnızca metin verildiğinde eklenir ve şunu söyler: kullanıcı şunu
istedi; gördüğünle çeliştiği her alanda kullanıcıyı takip et, çelişmediği alanları
görselden doldur.

| girdi | davranış |
|---|---|
| sadece görsel | görselin kendi öznesi + stili → "aynısını yap" |
| görsel + metin | metin ezdiği alanları ezer, kalanı görselden gelir |
| sadece metin | vision çağrısı yok; metin doğrudan prompt olur, stil alanları boş |
| ikisi de yok | hata, çıkış kodu 1 |

Sadece metin verildiğinde vision endpoint'ine hiç gidilmez — analiz edilecek bir şey yok
ve boşuna ücret ödenmez.

**Input görseli ayrıca görüntü modeline referans olarak da gider** (`input_references`).
Model hem tarifi okur hem orijinali görür. Bu, "aynısını yap" senaryosunun asıl
dayanağı — metin tarifi tek başına yeterli olsaydı ilk deneme başarısız olmazdı.

## Konfigürasyon: `.env`

Yeni bağımlılık yok. `python-dotenv` yerine ~15 satırlık bir okuyucu: `KEY=value`
satırları, `#` yorumları, boş satırlar. Tırnak varsa soyulur. Değerin içindeki `=`
korunur (ilk `=` ayırıcıdır, sonrakiler değere aittir).

Dosya proje kökünde aranır (`gen.py`'nin yanında), çalışılan dizinde değil — araç başka
bir dizinden çağrıldığında da aynı yapılandırmayı bulsun diye.

```bash
SPRITEGEN_BASE_URL=https://openrouter.ai/api/v1
SPRITEGEN_API_KEY=sk-or-v1-...
SPRITEGEN_MODEL=black-forest-labs/flux.2-max
SPRITEGEN_VISION_BASE_URL=http://localhost:20128/v1
SPRITEGEN_VISION_API_KEY=sk-...
SPRITEGEN_VISION_MODEL=cc/claude-sonnet-5
```

**Precedence:** CLI bayrağı > gerçek ortam değişkeni > `.env` dosyası > yerleşik
varsayılan. `.env` gerçek ortamı **ezmez** — CI'da veya `export` ile geçici bir değer
verildiğinde dosyanın onu sessizce geçersiz kılması sürpriz olurdu.

`.env` `.gitignore`'a girer, yanına `.env.example` konur.

**Anahtarlar burada değer olarak durur** — bu, pack dosyalarındaki `key_env` kuralının
istisnası değil, tamamlayıcısı: `.env` git'e girmez ve tek amacı budur. Pack dosyaları
paylaşılmak için var, `.env` değil.

## Komut

```
gen.py make [-i IMAGE] [-t TEXT] [-n N] [--dry-run] [--max-cost N] [--no-cutout]
```

```bash
python3 gen.py make -i dispanser.png                     # aynısını yap
python3 gen.py make -i dispanser.png -t "kırmızı olsun"  # metin ezer
python3 gen.py make -t "glossy mavi buton"               # sadece metin
python3 gen.py make -i ref.png -n 3                      # 3 varyant
```

**Akış:**

```
görsel ve/veya metin
  → (görsel varsa) vision çağrısı → 9 alanlı şema
  → prompt = birleştirme sırası + BG_CLAUSE
  → POST {base_url}/images   (input_references: görsel varsa)
  → alpha kes → trim → kare pad
  → out/make/<timestamp>-<slug>.png  +  aynı adla .json
```

`<slug>` şemanın `subject` alanından türetilir (küçük harf, alfanümerik olmayan → `-`,
ilk 40 karakter). Sadece metin verildiyse metinden türetilir.

`--no-cutout` mevcut `cutout=false` semantiğinin tek atışlık karşılığı: arka plan
istemez, alpha kesmez, kırpmaz — tam kare arka plan/tile üretmek için.

**Yan dosya `.json`** çıkarılan şemayı, tam prompt'u, modeli, transport'u, seed'i ve
maliyeti taşır. Beğenilen bir çıktının nasıl üretildiği geri izlenebilir olmalı; `make`'in
pack dosyası olmadığı için provenance'ın tek yeri burası.

## TOML akışı korunuyor

`build`, `init`, `pick`, `analyze` aynen kalır. `make` onların yerine geçmez:

| iş | komut |
|---|---|
| Tek nesne, hızlı deneme | `make` |
| 30 asset'lik tutarlı set | `build` (pack ile) |
| Referanstan pack stili çıkarma | `analyze` |

`make` pack dosyası okumaz ve yazmaz. Bu sınır bilinçli: pack'in değeri tekrarlanabilir
bir *set* tanımlaması, `make`'in değeri hiçbir şey tanımlamadan tek çıktı vermesi.

## Hata yönetimi

| durum | davranış |
|---|---|
| `-i` ve `-t` ikisi de yok | net hata, çıkış 1 |
| `-i` dosyası okunamıyor | net hata, çıkış 1 |
| vision modeli tanımsız (görsel verilmişken) | net hata, hangi değişkenin eksik olduğunu söyler |
| görüntü modeli tanımsız | net hata, çıkış 1 |
| vision yanıtı ayrıştırılamıyor | ham yanıt `<image>.analysis-error.txt`, çıkış 1 |
| `n > 1` ve bazıları başarısız | başarılı olanlar diske yazılır, özet başarısızları sayar, çıkış 1 |
| bütçe tavanı aşıldı | sıradaki istek gönderilmeden durur |

`n > 1` için her varyant ayrı seed alır (`0..n-1`), böylece aynı komut tekrar
çalıştırıldığında aynı varyantlar gelir.

## Test

Mevcut düzen: framework yok, `assert` bazlı, `python3 test_make.py`.

```
.env okuyucu:
  KEY=value, tırnaklı değer, # yorum, boş satır, = içeren değer
  gerçek ortam değişkeni .env'i ezer
  dosya yoksa sessizce geçilir

girdi doğrulama:
  ikisi de boş → hata
  sadece metin → vision çağrısı YAPILMAZ
  sadece görsel → vision çağrılır, override clause YOK
  görsel + metin → vision çağrılır, override clause VAR

prompt kurma:
  birleştirme sırası sabit
  eksik alanlar atlanır, ayırıcı bozulmaz
  BG_CLAUSE eklenir; --no-cutout ile eklenmez

çıktı:
  slug subject'ten türer, dosya adı güvenli
  yan .json şemayı ve prompt'u taşır
  --no-cutout ile cut_background/trim_and_pad çağrılmaz
  n>1 → n dosya, farklı seed
```

**Canlı doğrulama:** `dispanser.png` ile `make -i` çalıştır, çıkan sprite'ı referansla
karşılaştır. Sonra `-t "kırmızı olsun"` ekleyip metnin gerçekten ezdiğini doğrula.

## Bilerek kapsam dışı

| şey | neden |
|---|---|
| `make`'in pack yazması | Pack'in değeri bir set tanımlaması; tek atışlık çıktı ona ait değil |
| Otomatik nesne tespiti (bir ekran görüntüsünden N nesneyi bulup kırpma) | Bounding-box güvenilirliği düşük; kırpmayı kullanıcı yapar |
| Asset başına referans (pack akışında) | Ayrı bir özellik; `make` tek nesne çalıştığı için burada gerekmiyor |
| Varyantlar arası seçim arayüzü | `n` dosya diske yazılır, seçim kullanıcının |
| `.env` şifreleme / keyring | `.gitignore` + dosya izinleri bu iş için yeterli |
