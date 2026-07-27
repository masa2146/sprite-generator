# Çoklu Nesne Çıkarma (`extract`) — Tasarım Dokümanı

**Tarih:** 2026-07-28
**Durum:** Onaylandı, uygulamaya hazır
**Bağlam:** [2026-07-28-one-shot-make-design.md](2026-07-28-one-shot-make-design.md) üzerine ekleme

## Amaç

Bir görselden **tüm** sprite'ları çıkarmak: içindeki her ayrı nesneyi bulmak, hareketli
olanlar için oyunda kullanılacak açı varyasyonlarını üretmek, ve bunların hepsini tek
komutla üretilebilir hale getirmek.

## Şu anki davranış ve neden yetmiyor

`make -i görsel` görseli **tek nesne** varsayar. Tek şema çıkarır (`subject` tekil), tek
prompt kurar, tek sprite üretir. `-n 3` aynı nesnenin üç farklı seed'idir — farklı açı
değil, farklı nesne değil.

Bir oyun ekran görüntüsü verildiğinde `subject` alanı tüm sahneyi anlatır ("mobil bulmaca
oyunu ekran görüntüsü, blok kümeleri, tavşan kuyruğu..."), çünkü şema tek nesne için
tasarlandı. Ekrandaki altı ayrı nesne hiç ayrılmaz.

## Mimari kararı: yeni üretim yolu yok

`extract` **hiçbir görsel üretmez.** Analiz eder, kırpar ve bir pack dosyası yazar. Üretim
mevcut `build` komutunun işi.

```
gen.py extract -i screen.png --pack packs/bunny.toml
   → tek vision çağrısı: nesneler + bbox + hareketlilik + açı önerisi
   → her nesneyi kırp → refs/<id>.png
   → contact sheet aç (numaralı, etiketli)
   → packs/bunny.toml yaz — her varyasyon ayrı [[assets]]

kullanıcı contact sheet'e bakar, istemediği asset'leri pack'ten siler

gen.py build packs/bunny.toml --dry-run    # maliyet
gen.py build packs/bunny.toml              # üretim
```

Bu ayrım iki şey kazandırıyor:

**`build`'in olgunluğu bedavaya geliyor** — `--only`, `--max-cost`, manifest, kısmi hata
toleransı, paralellik, transport seçimi. Yeni bir üretim döngüsü yazılmıyor.

**Maliyet kararı ayrı bir adım.** 6 nesne × 4 varyasyon = 24 görsel ≈ **$3.12**. Tek
komutun bunu sessizce harcaması kabul edilemez. `extract` ucuzdur (tek vision çağrısı),
üretim ayrı komuttur ve `--dry-run` ile maliyeti önce gösterir.

Kullanıcı TOML yazmıyor — araç yazıyor, kullanıcı okuyup buduyor. Bu, "TOML dosyasını ben
mi oluşturacağım" itirazının cevabı: hayır, ama üretilmiş bir dosyayı gözden geçirmek
üretimden önceki doğal duraktır.

## Asset başına referans

Pack'te bugün tek bir style bible var ve her asset'e aynı referans gidiyor. Çoklu nesnede
her asset **kendi kırpmasını** görmeli:

```toml
[[assets]]
id        = "bunny_white-side"
prompt    = "plump ball-shaped white rabbit, ..., seen from directly the side, full profile"
reference = "refs/bunny_white.png"     # yoksa style_bible'a düşer
```

Bu alan daha önce bilerek kapsam dışı bırakılmıştı. Artık gerekli: ilk canlı denemedeki en
büyük hata, modelin 704×1526'lık kalabalık bir ekrana bakıp tek bir nesne üretmeye
çalışmasıydı. Kırpılmış referans o hatanın doğrudan karşılığı.

`reference` yolu pack dosyasına **göreli** çözülür, çalışılan dizine değil — pack'i taşıyan
kullanıcı referanslarını da yanında taşır. Çözüm `config.load_pack` içinde yapılır (pack'in
kendi yolu orada bilinir) ve `Asset.reference` mutlak bir `Path` olarak taşınır; `gen`
tarafı yol mantığı bilmez.

## Analiz şeması genişlemesi

Tek vision çağrısı bir nesne listesi döndürür. Her nesne mevcut dokuz alanı taşır, artı
üçü:

| alan | ne yakalar |
|---|---|
| `id` | dosya/asset adı için slug (`bunny_white`) |
| `bbox` | `[x1, y1, x2, y2]` piksel koordinatları |
| `animated` | `true` ise oyunda hareket eden bir nesne |
| `views` | varyasyon havuzundan adlar; statikte tek eleman |
| *(mevcut dokuz)* | `subject`, `form`, `detail` + altı stil alanı |

Stil alanları **görselin bütününden** bir kez çıkarılır ve pack'in `[style] prefix`'i olur —
her nesne için ayrı stil çıkarmak anlamsız, hepsi aynı oyundan.

## Varyasyon havuzu

Sabit havuz. Model yalnızca buradan seçebilir:

| ad | prompt'a eklenen ifade |
|---|---|
| `front` | `seen from directly the front` |
| `three_quarter` | `seen from a three-quarter front angle` |
| `side` | `seen from directly the side, full profile` |
| `back` | `seen from directly behind` |
| `top_down` | `seen from directly above, top-down` |

Havuz dışı bir ad atılır ve `front`'a düşülür. Sabit havuzun sebebi öngörülebilirlik: dosya
adları tahmin edilebilir kalır ve aynı komut iki kez çalıştırıldığında aynı seti verir.
Serbest metin bunu veremezdi.

`animated: false` olan nesne tek `front` alır — statik bir ray parçası için dört açı üretip
para harcamak anlamsız.

## Bbox güvenilirliği

Bu tasarımın en zayıf noktası. Bounding box doğruluğu modelden modele değişir ve **yanlış
bir kutu sessizce yanlış bir sprite üretir** — fark edilmesi en zor hata türü. Üç önlem:

**Contact sheet numaralı ve etiketli.** Her kırpmanın altında `3 · bunny_white · ANIMATED ·
front,side,back` yazar. Yanlış kırpma gözle görülür.

**Kırpmalar diskte kalır** (`refs/`). Biri yanlışsa o dosya elle düzeltilip `build`
çalıştırılabilir — yeniden analiz ve yeniden ücret gerekmez.

**Bbox doğrulaması, sessiz geçiş yok.** Şunlar atılır ve raporlanır:

| durum | neden |
|---|---|
| Görsel sınırları dışına taşan | koordinat hatası |
| Sıfır ya da negatif alanlı | bozuk kutu |
| Görselin %90'ından büyük | model "tüm ekran" döndürmüş |
| 16 pikselden küçük kenar | sprite olamayacak kadar küçük |

Atılan her kutu, hangi nesne ve hangi sebeple atıldığı yazılarak raporlanır. Sessizce
düşürmek, kullanıcının eksik bir pack'i tam sanmasına yol açar.

## Komut

```
gen.py extract -i <image> --pack <spec.toml> [--refs-dir DIR] [--max-objects N]
               [--no-open] [--dry-run] [--vision-model M] ...
```

- `--refs-dir` varsayılan: pack dosyasının yanında `refs/`
- `--max-objects` varsayılan 12 — model bir ekranda otuz nesne bulursa pack kullanılamaz
  hale gelir; sınır aşılırsa ilk N alınır ve kalan sayısı raporlanır
- `--dry-run` analizi yapar ve ne yazacağını basar, hiçbir dosyaya dokunmaz (vision çağrısı
  yine de yapılır ve ücretlidir — `make --dry-run` ile aynı sözleşme)

**Var olan bir pack'in üzerine yazma:** `extract` hedef pack varsa reddeder. `packwriter`'ın
güvenli yazma disiplini burada da geçerli — ama bu komut bir pack *oluşturur*, güncellemez.
Üzerine yazmak istenirse dosya elle silinir. Kullanıcının elle bududuğu bir pack'i ikinci
bir `extract` çağrısının sessizce ezmesi, bu akışta kaybedilebilecek en değerli şeydir.

## Çıktı yapısı

```
packs/bunny.toml            # üretilen pack
refs/
  bunny_white.png           # kırpmalar
  launcher.png
  block_capsule.png
  _contact_sheet.png        # numaralı, etiketli
```

Pack içeriği:

**`[api]` yazılmaz, `[pack] model` yazılır.** Bu ayrım bilinçli: endpoint ve anahtar
*ortama* aittir ve `build` onları zaten `.env`'den okur; model ise bir *içerik* kararıdır —
pack'i paylaşan kişi hangi modelle üretildiğini bilmeli ve aynısını alabilmelidir.

```toml
[pack]
model = "black-forest-labs/flux.2-max"

[style]
prefix = "<görselin bütününden çıkarılan stil>"
plate_prompt = "..."

[defaults]
aspect_ratio = "1:1"

[[assets]]
id        = "bunny_white-front"
prompt    = "<subject, form, detail>, seen from directly the front"
reference = "refs/bunny_white.png"

[[assets]]
id        = "bunny_white-side"
prompt    = "<subject, form, detail>, seen from directly the side, full profile"
reference = "refs/bunny_white.png"

[[assets]]
id        = "launcher-front"
prompt    = "<subject, form, detail>, seen from directly the front"
reference = "refs/launcher.png"
```

Asset id'si `<nesne>-<görünüm>` biçiminde. Tek görünümlü statik nesnede de son ek korunur —
tutarlılık, sonradan bir açı eklendiğinde ad değişmesin diye.

## Hata yönetimi

| durum | davranış |
|---|---|
| Görsel okunamıyor | net hata, çıkış 1 |
| Vision yanıtı ayrıştırılamıyor | ham yanıt `<image>.analysis-error.txt`, çıkış 1 |
| Hiç geçerli nesne yok | net hata, pack yazılmaz, çıkış 1 |
| Bazı bbox'lar geçersiz | atılanlar raporlanır, kalanlarla devam |
| Hedef pack zaten var | reddet, çıkış 1 |
| `refs/` yazılamıyor | net hata, pack yazılmaz, çıkış 1 |
| Bir kırpma kaydedilemiyor | o nesne atlanır ve raporlanır, diğerleriyle devam |

Pack yazımı **en son** yapılır: kırpmalar başarıyla diske indikten sonra. Yarısı eksik
referanslara işaret eden bir pack, hiç pack olmamasından kötüdür.

## Test

Mevcut düzen: framework yok, `assert` bazlı, `python3 test_extract.py`.

```
bbox doğrulama:
  sınır dışı / sıfır alan / %90'dan büyük / 16px'den küçük → atılır, raporlanır
  geçerli kutu → kırpılır

varyasyon havuzu:
  havuz dışı ad atılır, front'a düşülür
  animated=false → tek front
  havuzdaki her adın ifadesi prompt'a giriyor

pack üretimi:
  her nesne × her görünüm = bir [[assets]]
  reference yolu pack'e göreli
  id biçimi <nesne>-<görünüm>
  var olan pack reddediliyor
  kırpma yazılamazsa pack yazılmıyor

--max-objects:
  sınır aşılınca ilk N alınıyor, kalan sayısı raporlanıyor

--dry-run:
  hiçbir dosya yazılmıyor, refs/ oluşturulmuyor
```

**Canlı doğrulama:** `reference.png` (altı ayrı nesne içeren oyun ekranı) ile `extract`
çalıştır, contact sheet'teki kırpmaları gözle doğrula, pack'i buda, `build --dry-run` ile
maliyeti gör, sonra üret. Bu akışın asıl sınavı budur.

## Bilerek kapsam dışı

| şey | neden |
|---|---|
| Kırpmaları düzenlemek için arayüz | Dosyalar diskte; kullanıcının kendi editörü yeterli |
| Spritesheet/atlas paketleme | Unity Sprite Atlas zaten yapıyor |
| Animasyon karesi üretimi (walk cycle vb.) | Açı varyasyonundan farklı bir problem; tutarlı kare dizisi ayrı bir tasarım ister |
| `extract`'in üretim yapması | Maliyet kararı ayrı adım olmalı |
| Var olan pack'e ekleme | `extract` oluşturur; ekleme `analyze --add-asset`'in işi |
| Otomatik arka plan temizleme öncesi kırpma iyileştirme | Kırpma referans içindir, çıktı değil — kaba olması yeterli |
