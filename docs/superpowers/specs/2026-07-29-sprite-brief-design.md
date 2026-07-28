# Sprite Brief (`sprite-brief` skill) — Tasarım Dokümanı

**Tarih:** 2026-07-29
**Durum:** Onaylandı, uygulamaya hazır
**Bağlam:** [2026-07-28-extract-design.md](2026-07-28-extract-design.md) üzerine yön değişikliği

## Amaç

Bir oyun ekran görüntüsünden, Gemini ya da ChatGPT arayüzünde **elle** sprite üretmek için
gereken her şeyi çıkarmak: kırpılmış referans görseller ve her biri için yapıştırmaya hazır,
kusursuz bir prompt.

Üretim ücretli API'den insan arayüzüne taşınıyor. Kalite artık modele ne kadar para
verdiğimizden değil, prompt'un ne kadar iyi yazıldığından geliyor.

## Neden bu yön değişikliği

`gen.py extract` + `build` akışı çalışıyor ama pahalı. Tek bir ekran görüntüsünden 17
asset'lik bir set üretmek bir denemede ~$1.8 tuttu ve o denemenin dördü kullanılamaz çıktı
— yani para, sonucu görmeden harcanıyor. Elle üretimde deneme bedava: beğenmezsen yeniden
üretirsin.

Ölçülmüş dört başarısızlık bu tasarımın gerekçesi:

| başarısızlık | sebep |
|---|---|
| `launch_ball` tek top yerine **on iki top** üretti | prompt'ta hiçbir yerde "tek bir tane" yazmıyordu |
| `block_cluster` tek tuğla yerine **tüm blok yerleşimini** üretti | kutu 608×496'ydı; granülerlik hiç sorulmadı |
| HUD'lar "yazısız hali" istenmesine rağmen **yazılı** çıktı | analiz yazıyı prompt'a yazdı, kimse fark etmedi |
| bir çalıştırma **tamamen çöpe gitti** | model `["front"]` yerine `「front"]` yazdı, JSON ayrıştırılamadı |

Sonuncusu bu tasarımda tamamen ortadan kalkıyor: Claude görseli doğrudan gördüğü için
ortada ayrıştırılacak model yanıtı yok.

## Mimari

**Skill:** `.claude/skills/sprite-brief/SKILL.md`, proje içinde. Mevcut `image-style` skill'i
durur — o tek görselin stilini okur, bu bir ekrandan çoklu sprite briefi çıkarır.

**Vision API yok.** Claude görseli kendi okur. Maliyet sıfır; `temperature`, yeniden deneme,
ham yanıt dosyaları, JSON toleransı — hepsi gereksiz.

**Kırpma için komut var**, çünkü Claude görsel kesemez. Yeni bir `brief.py` bunu yapar ve
`extract.py`'nin doğrulanmış yardımcılarını kullanır:

| yeniden kullanılan | neyi çözüyor |
|---|---|
| `padded_box` | kırpma kesikliği (%12 pay; tavşan kulakları bununla kurtuldu) |
| `screen_objects` | bozuk kutu, çakışan id, dizin dışına kaçan id |
| `find_contents` | kutunun yuttuğu nesneler → dışlama listesi |
| `labelled_sheet` | numaralı, etiketli inceleme sayfası |

**Sınır:** `gen.py` ücretli API akışı olarak **değişmeden** kalır. `brief.py` ayrı bir giriş
noktasıdır; ikisi de `extract.py`'yi kullanır, birbirini çağırmaz. API'ye dönmek istenirse
eski yol bozulmamış durur, yeni yol onun bagajını taşımaz.

## Akış

```
kullanıcı: görsel + serbest metin ("ortada conveyor var, ... tavşanı da çıkar")
  → Claude görseli okur, nesne listesini çıkarır          (ücretsiz)
  → analysis.json yazar
  → python3 brief.py --image X --analysis analysis.json --out-dir briefs/<ad>
       kutuları doğrular, pay ekleyip kırpar, contact sheet ve brief.html yazar
  → Claude contact sheet'i OKUR ve kendi kırpmalarını denetler   (otomatik)
  → belirsizlikleri tek turda sorar
  → cevaba göre analysis.json'u düzeltir, script tekrar çalışır  (bedava, saniyeler)
  → kullanıcı refs/'ten iki görseli yükler, brief.html'den prompt'u yapıştırır
```

Analizle kırpma arasında **kullanıcının gördüğü bir durak** vardır. `block_cluster`
faciasının üretime kadar gitmesinin sebebi bu durağın olmamasıydı.

## `analysis.json` şeması

Claude'un yazdığı, `brief.py`'nin okuduğu tek arayüz. Elle düzenlenebilir olması bilinçlidir.

```json
{
  "style": "smooth 2D vector cartoon render with soft gradients ..., #2e2c4a, #ffffff",
  "objects": [
    {
      "id": "conveyor_belt_frame",
      "bbox": [30, 140, 690, 1010],
      "views": ["top_down", "three_quarter"],
      "subject": "the full looping conveyor belt structure that frames the playfield",
      "form": "wide rounded-rectangle track running along all four inner edges ...",
      "detail": "arrow chevrons along its length, lighter inner rail line ...",
      "state": "empty — without the object it normally holds"
    }
  ]
}
```

| alan | zorunlu | not |
|---|---|---|
| `style` | evet | tek satır; her prompt'ta aynen tekrarlanır |
| `id` | evet | `^[A-Za-z0-9][A-Za-z0-9_-]*$`; dosya adı ve asset adı olur |
| `bbox` | evet | `[x1, y1, x2, y2]` piksel, sol-üst orijin |
| `views` | evet | `extract.py`'nin `VIEW_POOL`'undan; havuz dışı ad atılır ve `front`'a düşülür |
| `subject`, `form`, `detail` | hayır | eksikse prompt o satırı hiç yazmaz, ayırıcı kirlenmez |
| `state` | hayır | yalnızca varsa `STATE` satırı çıkar |

`style` tek bir metin alanıdır, altı ayrı stil alanı değil: bu akışta pack `[style] prefix`'i
yoktur, stil doğrudan prompt'a girer, bölünmesinin bir faydası kalmaz.

**Asset sayısı = nesne × görünüm.** Bir nesnenin iki görünümü iki ayrı prompt ve iki ayrı
`brief.html` bölümü üretir; ikisi de aynı kırpmayı gösterir, yalnızca `VIEW` satırı değişir.
`extract` ile aynı semantik.

## Komut

```
python3 brief.py --image <görsel> --analysis <analysis.json> --out-dir <dizin>
                 [--no-open]
```

- `--out-dir` zorunludur; klasör yapısı oradan başlar. Varsayılan tahmin edilmez —
  bir brief'in üzerine sessizce yazmak, bu akışta kaybedilebilecek en değerli şeydir.
- Dizin varsa ve içinde `brief.html` varsa **reddedilir**; kullanıcı ya siler ya başka ad verir.
  Tek istisna: `--analysis` aynı dizindeki `analysis.json` ise, bu bir yeniden çalıştırmadır
  ve izin verilir — inceleme döngüsünün tamamı buna dayanır.
- Kaynak görsel `refs/_style.png` olarak kopyalanır; yüklenecek iki dosya aynı klasörde olur.
- `--no-open` contact sheet'i açmaz.

## Prompt yapısı

Tek prompt, Gemini'nin sevdiği gibi detaylı ve teknik; ChatGPT'de de aynısı kullanılır.

```
REFERENCES
- Image 1 — the object to redraw. Reproduce THIS object.
- Image 2 — the game screenshot. Use it ONLY for art style, palette and
  lighting. Do not copy any object from it.

OBJECT     <subject>
FORM       <form>
DETAIL     <detail>
STATE      <yalnızca varsa: "empty — without the object it normally holds">
VIEW       <açı ifadesi>

ART STYLE  <stil satırı>

OUTPUT
- Exactly one <nesne>, on its own. Not a set, not a grid, not a sheet.
- Centred and complete, nothing touching or cut off at the edges.
- Small even margin on all sides. Square image.
- Flat solid #808080 background. No shadow, no ground plane, no gradient,
  no scene, no props.

DO NOT DRAW
- <find_contents'ten gelen dışlama listesi — yalnızca doluysa>
- any text, numbers, labels or logos
- any other object from the screenshot
- more than one copy of the object
```

Her bloğun gerekçesi ölçülmüş bir başarısızlıktır:

**`REFERENCES`** — API'de imkânsızdı; `input_references` görselleri etiketsiz gönderir ve
modelin hangisini kopyalayıp hangisinden sadece stil alacağını tahmin etmesi gerekir.
Arayüzde bu söylenebiliyor. Dispanser'in iki parçalı yapısını kaybetmesinin muhtemel sebebi
iki referansın dikkat için yarışmasıydı.

**`Exactly one ... Not a set, not a grid`** — `launch_ball` ve `block_cluster`'ın doğrudan
karşılığı.

**`any text, numbers, labels`** — HUD'ların yazısız hali. `OBJECT` alanı yazıyı hiç
anmayacak, `DO NOT DRAW` ayrıca yasaklayacak: iki katman, çünkü tek katman bugün tutmadı.

**`STATE`** — görselde kapalı olan varyantlar (boş dispanser, yazısız etiket) için ayrı alan.
Model bunu bugün dispanser için kendiliğinden yaptı, etiketler için yapmadı; ayrı alan olunca
tesadüfe kalmaz.

**Arka plan `#808080` kalır, şeffaf istenmez.** İndirilen dosya yerelde `post.py` ile
kesilebilir — bedava ve ölçülmüş: bu düz gri temiz kenar verir, `#FF00FF` kenarlara renk
sızdırıyordu. Şeffaf PNG istemek modele göre değişken ve güvenilmez.

## Oturum kuralı: her mesaj kendi kendine yeter

**Hiçbir mesaj, önceki mesajın içeriğinin hayatta kalmasına bağlı olamaz.**

Sebebi davranışsal: ChatGPT ve Gemini'de görseli üreten şey sohbet değil, ayrı bir görüntü
modelidir. Asistan son mesajdan bir prompt derleyip ona yollar; görüntü modeli sohbet
geçmişini görmez. İlk mesajda yüklenen ekran görüntüsü sonraki üretimlere çoğu zaman hiç
ulaşmaz, stil birkaç üretim sonra kayar.

Pratikte: **her asset mesajına iki görsel de eklenir ve stil satırı tekrar yazılır.** Stil
satırı ~40 kelimedir, tekrarı ucuzdur.

Bunun gerekliliği ölçüldü: stil görseli göndermeyen sürüm jenerik gri bir conveyor üretti;
gönderen sürüm oyunun paletini, chevron yönlerini ve dispanser ağzını tutturdu. İkinci
görsel süs değil, belirleyici.

Her set için ayrı sohbet önerilir — tutarlılık için değil, kirlenmeye karşı: uzun
sohbetlerde asistan kendi önceki çıktılarını bağlam sanıp onlara benzetmeye başlar ve bir kez
bozulan stil sonrakilere bulaşır.

## İnceleme döngüsü

**Otomatik öz-denetim.** Kırpmalar yazıldıktan sonra Claude contact sheet'i okur ve her
hücreyi iddiasıyla karşılaştırır: `launch_ball` etiketli kırpmada gerçekten tek bir top var
mı? Bu adım her çalıştırmada kendiliğinden yapılır. API akışında bunun bedeli kırpma başına
bir ücretli çağrıydı; Claude görebildiği için bedava.

**Sonra soru.** Yalnızca cevabın kırpmayı değiştireceği yerlerde. Tetikleyiciler kuraldır:

| tetikleyici | sorulan |
|---|---|
| kutuda aynı şeklin birden çok kopyası var | tek birim mi, küme mi? |
| `find_contents` boş değil | komple mi, döşenebilir parça mı? |
| kutu ekranın %25'inden büyük | tek nesne mi, kompozisyon mu? |
| kullanıcı metninde "boş hali / yazısız" geçiyor | hangi durum çıkarılsın? |
| metinde adı geçen bir şey bulunamadı | "şunu bulamadım, nerede?" |

Son satır zorunludur: bulunamayan ya da anlaşılmayan bir istek **sessizce düşürülemez**.

**Sorular tek turda toplanır.** Her tur kullanıcının dikkatini harcar.

**Düzeltme bedava ve anında.** Cevaba göre `analysis.json` güncellenir, script tekrar çalışır.
Üretim yok, para yok. Kullanıcı `refs/<id>.png`'yi elle de düzeltebilir; o durumda analiz hiç
tekrar çalışmaz, yalnızca brief yeniden üretilir.

## Çıktı yapısı

```
briefs/<ad>/
  analysis.json          # doğruluk kaynağı; elle düzeltilip yeniden çalıştırılabilir
  brief.html             # her asset: iki küçük görsel + kopyalanmaya hazır prompt
  refs/
    _style.png           # kaynak ekran görüntüsünün kopyası (2. yüklenecek görsel)
    _contact_sheet.png   # numaralı, etiketli
    conveyor_belt_frame.png
    dispenser_empty.png
```

Yüklenecek iki dosya aynı klasördedir. `brief.html` prompt'u taşır, dosya seçiciyi değil.

`analysis.json` bilinçli olarak kalıcıdır: kutu elle düzeltilip script tekrar çalıştırılabilir,
Claude'a dönmeye gerek kalmaz.

## Hata yönetimi

`extract`'in sözleşmesiyle aynıdır, çünkü aynı kod kullanılır.

| durum | davranış |
|---|---|
| görsel okunamıyor | net hata, hiçbir şey yazılmaz |
| `analysis.json` bozuk | hangi alanın hatalı olduğunu söyler, hiçbir şey yazılmaz |
| hiç geçerli nesne yok | net hata, hiçbir şey yazılmaz |
| bazı kutular geçersiz | atılanlar sebebiyle raporlanır, kalanlarla devam |
| id çakışması / dizin dışına kaçan id | reddedilir ve raporlanır |
| bir kırpma yazılamıyor | o nesne atlanır ve raporlanır, diğerleri yazılır |
| contact sheet yazılamıyor | uyarı; kırpmalar ve brief yine de yazılır |

Sessiz düşürme yoktur. Bu projedeki en pahalı hatalar sessiz olanlardı.

## Test

Mevcut düzen: framework yok, `assert` bazlı, `python3 test_brief.py`.

```
prompt kurulumu:
  her blok var; REFERENCES iki satır taşıyor
  "Exactly one" ve "more than one copy" HER prompt'ta, istisnasız
  STATE satırı yalnızca durum verilmişse çıkıyor
  find_contents dolu → DO NOT DRAW'a giriyor; boş → o satır hiç yok
  eksik subject/form/detail prompt'u bozmuyor, ayırıcı kirlenmiyor
  ART STYLE her prompt'ta tekrarlanıyor (oturum kuralının kod tarafındaki karşılığı)

brief.html:
  kendi kendine yeter (dış dosya referansı yok)
  prompt metni ve id'ler HTML kaçışından geçiyor
  her asset kendi kırpmasını ve stil görselini gösteriyor

analysis.json:
  bozuk alan net hata veriyor
  elle düzeltilmiş dosya tekrar çalışıyor
  kırpmalar ve _style.png beklenen yerlere yazılıyor
  havuz dışı görünüm adı atılıyor ve front'a düşülüyor

görünüm ve dizin:
  iki görünümlü nesne iki prompt üretiyor, ikisi de aynı kırpmayı gösteriyor,
    yalnızca VIEW satırı farklı
  dolu bir --out-dir reddediliyor; aynı dizindeki analysis.json ile yeniden
    çalıştırma kabul ediliyor (inceleme döngüsü buna dayanıyor)
```

`extract.py`'nin kırpma ve doğrulama testleri zaten vardır, tekrar yazılmaz.

**Canlı doğrulama:** `reference.png` ile skill'i uçtan uca çalıştır, contact sheet'i gözle
doğrula, granülerlik sorularını cevapla, üretilen prompt'u Gemini'ye elle yapıştır ve çıktıyı
referansla karşılaştır. Asıl sınav budur ve artık bedava olduğu için tekrarlanabilir.

## Bilerek kapsam dışı

| şey | neden |
|---|---|
| TOML pack yazmak | `build` çalıştırılmayacak; pack ölü ağırlık olur |
| `gen.py`'yi değiştirmek | ücretli akış bozulmadan kalsın; API'ye dönüş yolu açık |
| Otomatik alfa kesimi | indirilen dosya `post.py` ile kesilir; skill dosya indirmez |
| ChatGPT'ye ayrı prompt sürümü | tek prompt ikisinde de kullanılacak (kullanıcı kararı) |
| Animasyon karesi üretimi | açı varyasyonundan farklı bir problem, ayrı tasarım ister |
| Kırpmaları düzenleyecek arayüz | dosyalar diskte; kullanıcının kendi editörü yeterli |
