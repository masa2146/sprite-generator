# SDF şeridinin tavanı: malzeme, temas, göz, gölgeleme rampası — Tasarım Dokümanı

**Tarih:** 2026-08-11
**Durum:** Onaylandı, plana hazır
**Kapsam:** Spec 2/3. Spec 1 skill-first pipeline'ı kurdu; Spec 3 Blender şeridini ekleyecek.

## Amaç

`procedural-sprites`'ın SDF şeridinden çıkan her şey aynı plastik parlaklıkta.
Bu doküman o tavanı kaldırır: parça başına yüzey, gerçek temas gölgesi, geometri
olan gözler, bantlı (cel) gölgeleme seçeneği ve iç kontur.

Kütüphane teknik verir, stil vermez — skill'in kendi ilkesi. Bu spec anatomi
şablonu, oran sistemi ya da hazır karakter üretmez; farklı görünüşlerin
**mümkün olmasını** sağlar.

## Bağlam: iki script ve bir karşılaştırma

Şeridin bugünkü hâli iki gerçek asset'ten okundu.

**`make_bull_totem.py`** (44×52 px'e çizilen taş obstacle) — teknik doğru
kullanılmış: parçalar `smooth_union` ile birleşiyor, burun kaynağı bilinçli
sıkılaştırılmış (0.028; 0.055'te kaynak iyileşip burun kayboluyormuş),
`part_color` ile kafa/boynuz/kaide/halka ayrı renk alıyor, sonunda elle yazılmış
gerçek bir kabul testi var. Yüzün 2D bindirilmesi de gerekçeli: o boyutta yüz
zaten düz yüksek kontrast şekil, SDF'ten oymak saydamlığa delik açardı.

**`make_bunny.py`** (5 renk × 4 view) — istenen turnaround zaten çalışıyor:
`spots()` ile object-space yüz, `yaw` ile view'lar, ve ışığın kamerayla
dönmesi (sabit ışıkta yaw 180'de arka view düz ambient bulamaç oluyormuş).

Yani **teknik eksik değil.** Eksik olan, o iki dosyanın elle keşfettiği
idiomların kütüphanede olmaması ve dört gerçek yeteneğin hiç bulunmaması.

**Kod çıktısı ile AI referansının karşılaştırması** (`bull_ai.png` ↔
`bull_totem.png`) farkları sıraladı. Karakteri öldüren üçü:

1. **Gözler** — AI'da beyaz sklera + koyu bebek + parlama, kaşın altında bir
   yuvada. Kodda iki düz koyu şekil, kaş barına kaynamış. Bakan bir şey yok.
2. **Halka septumdan geçmiyor** — AI'da halka bir U, üst yayı burnun içinde.
   Kodda tam bir simit, hiçbir yeri gömülü değil.
3. **Alt üçte bir kaymış** — AI'da burun kafanın ortasında, kaide ayrı bir
   levha. Kodda burun kafanın alt kenarından sarkıyor ve arkasında kaide
   başlıyor.

Yüzeyi ucuzlatan dördü:

4. **Kontur yumuşak ve değişken** — antialiaslı alfanın dilate'i alınmış.
5. **Tek malzeme** — boynuz, halka ve kafa aynı `shininess=46` ile çıkıyor.
6. **Buhar başka görsel dilde** — gaussian bulamaç, silueti kenarlardan bozuyor.
7. **Kaş 2D** — göz yuvasına gölge düşüremiyor.

Bunlardan **1, 4, 5 ve 7 kütüphane işi** ve bu spec'in konusu. **2, 3 ve 6 o
asset'in yerleşim/sanat yönü hataları** — kütüphane onları çözmez ve çözmeye
çalışmamalı.

## Kararlar

| konu | karar |
|---|---|
| kapsam | yalnızca teknik taban; anatomi ve oran asset'in işi |
| yerleşim | `sdf3d.py` (ışık/yüzey) · yeni `character_lib.py` (karakter) · `sprite_lib.py` (teslim/QC) |
| malzeme | parça başına renk **ve** yüzey; `part_color`'ın yerine `surface()` |
| gölgeleme modeli | difüz **rampa**; varsayılan doğrusal = bugünkü çıktı, bantlı rampa = cel |
| temas gölgesi | opsiyonel, kısa menzilli, varsayılan kapalı |
| iç kontur | derinlik + normal tamponlarından, alfa konturuna ek |
| geri uyum | primitif imzaları değişmez; mevcut scriptler kırılmaz |
| yazılmayacaklar | düz-vektör/kil/painterly modelleri, doku, gürültü, saç, anatomi şablonu |

## Kapsam dışı

- Saç, kumaş kıvrımı, boyanmış yüz — **bu şeritte yok ve olmayacak**. Spec 3
  (Blender, ayrı süreç) ve elle üretim yolu bunlar içindir. GitHub'a çıkacağı
  için bu sınır README'de de açık yazılır.
- Pixel şeridi. Araştırma Dead Cells'in hattının aynı makineye dayandığını
  gösterdi (3D kare + normal haritası + toon shader), yani kapı kapalı değil —
  ama palet indirgeme, sert kenar ve ızgara hizalaması kendi spec'idir.
- Animasyon kareleri, gövde planı şablonları, oran sistemi.
- Boğanın yeniden çizilmesi.
- Doku (triplanar), gürültüyle yüzey bozma, kümeli saç. Değerlendirildi ve
  bilerek ertelendi: araştırmada doğrulamayı geçen kaynak çıkmadı, ve asıl
  ihtiyaç duyulan yer Spec 3'ün şeridi.

## 1. Taşıyıcı kural

> Malzeme kimliği en yakın parçadan seçilir. Bu seçim yalnızca **sert**
> birleşimde doğrudur: `smooth_union` yüzeyi dışarı çeker, karışım bandındaki
> noktalar hiçbir parçaya ait değildir, kimlik seçimi orada patlar.
>
> **Aynı malzemeyi paylaşanları yumuşak birleştir; kendi kimliği olması
> gerekeni sert birleştir.**

iq'nun karakteri bunu aynen yapıyor: göz küresi kafaya `smin` ile kaynıyor ama
**malzeme kimliği taşımıyor** (yuva çıkıntısını yapar, deri rengini paylaşır);
iris ve bebek sert union ile ekleniyor, çünkü kendi renkleri olmalı.

Bu kural `make_bunny.py`'deki `GAP = 0.055` hilesinin açıklaması: orada her
malzeme parçası derinin altına gömülmek zorunda kalmış, çünkü parçalar yumuşak
birleşiyor. Yeni tasarımda hile gerekmez.

## 2. `sdf3d.py`

### 2.1 Malzeme

```python
material(color, spec=0.5, shininess=40, rim=0.10, spec_color=(255, 255, 255),
         spec_hard=None)
surface([(part_sdf, material(...)), ...])
```

`render()` her isabet noktasında en yakın parçanın kimliğini bulur ve
`spec`/`shininess`/`rim`/`spec_color`/`spec_hard` değerlerini **dizi olarak**
toplar. Tek march, ikinci geçiş yok. Tek malzemeli çağrılar bugünkü skaler
parametrelerle çalışmaya devam eder.

`part_color` kaldırılır — `surface()` onun yerini alır ve yüzeyi de taşır.
Mevcut setler kendi kopyalarını çalıştırdığı için kırılmaz.

### 2.2 Difüz rampa

Sabit `ambient + diffuse*lam` yerine rampa araması:

```python
ramp_linear()                    # varsayılan; bugünkü çıktı bit bit aynı
ramp_bands([0.35, 0.75])         # iki eşik, üç bant — cel
```

`N·L` `[0,1]`'e taşınır ve rampaya koordinat olur. Bant sayısı, genişlikleri ve
uçları kodda değil rampada: endüstri pratiği bu, ve bant sayısını koda gömmek
tam olarak sanatçının elinden alınan şey.

### 2.3 Spekülerin sert hâli

`spec_hard` verilmişse spekülerin üssü yükseltilir ve sonuç
`smoothstep(t, t+0.01)` ile düz renkli sert lekeye çevrilir. Işık kapısı
`pow`'un **tabanının içinde** çarpılır (`pow(NdotH * lit, e)`), böylece gölgede
spekülerin kökü kazınır.

İki incelik yorumda kayıtlı kalır: eşik genişliği bir **antialias epsilon'u**,
yumuşaklık ayarı değil; ve üs değerleri (kaynaklarda 32²=1024 ve 400) iki
yazarın keyfi seçimi, genelleştirilebilir olan "yüksek üs + eşikleme".

### 2.4 AO

Bugünkü tek örnek yerine 5 örneklemeli:

```
occ = 0; sca = 1
for i in 1..5:
    h = 0.01 + ao_radius * i/5
    occ += (h - sdf(p + n*h)) * sca
    sca *= 0.95
ao = clamp(1 - 3*occ, 0, 1)
```

`ao_radius` sahne ölçeğine bağlı olduğu için parametredir (varsayılan 0.12; bu
dünyada `x,y ∈ [-1,1]`). Maliyet: isabet piksellerinde 5 ek SDF çağrısı —
normaller zaten 6 yapıyor.

### 2.5 Temas gölgesi

```
res = 1; t = 0.02
12 adım: h = sdf(p + L*t); res = min(res, k*h/t); t += clamp(h, 0.01, 0.1)
```

Kaşın göz yuvasına, boynuz kökünün kafaya, kafanın kaideye düşürdüğü gölge.
**Varsayılan kapalı**, menzil kısa (~0.35, sadece temas). İkinci bir march
demek ve boğa `OVERSAMPLE=3`'te zaten dakikalar sürüyor: açıkken ve kapalıyken
süre ölçülmeden varsayılan değişmez.

Bilinen arıza: keskin köşeli gölge verenlerde adım kuantizasyonundan bantlanma.
Düzeltmesi (Aaltonen, GDC 2018) yazılmaz; arıza ve çıkış yolu yorumda kalır.

### 2.6 İç kontur

Raymarcher `t` (derinlik) ve `n` (normal) tamponlarını hesaplayıp atıyor.
Komşu farkı eşiğiyle bunlardan iç çizgi çıkarılır — kolun gövdeyi, boynuzun
kafayı kestiği yerdeki çizgi. Alfa konturunun yerine değil, yanına.

### 2.7 Kütüphanenin borcu

`torus_z` sadece bir setin kopyasında yaşıyor, skill'de yok. `squash`/`scale_y`
iki yerde ayrı tanımlı. İkisi de kaynağa iner: asset'in ihtiyacı kopyada değil
kütüphanede durmalı.

## 3. `character_lib.py` (yeni)

### 3.1 Göz

```python
eye(center, look, r=0.09, iris=0.045, pupil=0.022, glint=0.018)
```

Dört parça, iki farklı birleşim: **küre** kafaya yumuşak kaynar ve kendi
malzemesi yoktur (yuva çıkıntısı, deri rengi); **sklera**, **iris** ve **bebek**
sert union ile eklenir ve kendi malzemelerini taşır; **glint** decal'dir, çünkü
o bir parlama, geometri değil.

Parametreler sıfırlanınca noktasal göz çıkar — stil dayatmaz.

### 3.2 Decal araçları

```python
stroke(points, width, color)   # eğri boyunca decal serisi — ağız, kaş çizgisi
mirrored(fn)                   # tek tanım, iki yan
```

`make_bunny.py`'de ağız 20+ elle yazılmış decal noktası; `stroke` onun yerine
geçer. `mirrored` zorunlu değil: tavşanın kulakları kasten farklı derinlikte,
yandan bakışta iki kulak görünsün diye. Simetri araçtır, kural değil.

### 3.3 Işık ve turnaround

```python
light_for(yaw, base_light)
turnaround(shape, views={'front': 0, 'three_quarter': 38, 'side': 82, 'back': 180}, **kw)
```

Işık kamerayla döner. Gerekçe ölçülmüş: sabit ışıkta yaw 180'de ışık tamamen
nesnenin arkasına düşer ve arka view düz ambient bulamaç olur.

### 3.4 İfade

Yüz sayısal parametrelerle kurulur; bir ifade bunların üzerine yazılan bir
sözlüktür:

```python
FACE  = dict(eye_open=1.0, pupil=(0, 0), mouth=+0.15, brow=-4)
ANGRY = FACE | dict(brow=+16, eye_open=0.7, mouth=-0.25)
```

Sınıf hiyerarşisi yok, iskelet yok.

## 4. `sprite_lib.py`

### 4.1 Kontur

Konturun bugün skill'de karşılığı **yok**: iki script de sete ait yerel bir
`draw.py`'den alıyor ve ikisi farklı çağırıyor.

```python
contour(img, width, color, threshold=110, ss=3)
```

Tavşanınki doğru olan: büyüt → alfayı **sert eşikle** → genişlet → tek seferde
küçült. Sert eşik olmadan kontur genişliği kenarın yumuşaklığına göre değişir —
boğanın boynuz uçlarındaki bulanıklığın sebebi bu.

### 4.2 Okunurluk

```python
readability(img, size=(44, 52))   # koyu piksel, açık piksel, kaplama oranı
silhouette(img)                   # alfası siyah doldurulmuş kopya
qc_strip(img, sizes, bg)          # oyun boyutlarında şerit, oyunun zemininde
```

Ölçer ve gösterir, karar vermez. Boğanın `dark >= 14, pale >= 30` eşikleri o
asset'in kendi kabul kriterleridir ve orada kalır.

Siluet testi bilerek **metrik değil, resim**: doldur ve bak. Araştırmada bu
teste dair doğrulamayı geçen kaynak çıkmadı; klasik bir atölye pratiği olarak
durur ve öyle yazılır.

## 5. Doğrulama ve testler

`procedural-sprites/scripts/` bugün **hiç test edilmiyor** — `conftest.py`
yalnızca `sprite-brief/scripts`'i `sys.path`'e koyuyor. Bu spec onu genişletir.

| test | ne kanıtlar |
|---|---|
| iki malzemeli küre çifti | parlak olanın speküleri gerçekten daha güçlü |
| çukur vs düz yüzey | AO çukuru koyulaştırır |
| temas gölgesi açık/kapalı | açıkken altta koyulaşma, kapalıyken hiç değişiklik |
| `ramp_linear` | çıktı bu spec'ten önceki render ile aynı |
| `ramp_bands` | histogramda ayrık kademeler |
| `spec_hard` | spekülerin kenarı sert, gölge tarafında hiç yok |
| kontur | her kenarda aynı kalınlık |
| iç kontur | kesişen iki parça arasında çizgi çıkar |
| `eye()` | çıktıda sklera/iris/bebek üç ayrı renk |
| `turnaround` | dört view'da da ışık karakterin aynı tarafında |

Testler `OVERSAMPLE=1` ve 32×32 render ile çalışır. Suite bugün ~1 saniye;
bu iş onu saniyeler mertebesinde tutmalı.

Ayrıca **bir demo karakter**: dört view ve iki ifade üreten tek script,
kütüphanenin kendi QC'si. Bu bir test fikstürüdür, stil önerisi değil.

## 6. Hata ve kenar durumları

| durum | davranış |
|---|---|
| iki malzeme parçası eşit yakın | kimlik seçimi keyfi; belgede yazılı |
| bir malzeme parçası yüzeyin kendisi | eski `GAP` tuzağı; kural belgede |
| `eye()` kafanın içine gömülü | sklera görünmez; test yakalar |
| temas gölgesi kapalı | ikinci march hiç çalışmaz |
| keskin köşede gölge bantlanması | bilinen arıza, yorumda kayıtlı |
| `ramp_bands` boş liste | doğrusal rampaya eşdeğer, sessiz sürpriz değil |

## 7. Belge borcu

`procedural-sprites/SKILL.md`'nin karakter merdiveninde bugün "ölçülmüş tavan"
olarak duran maddeler güncellenir: hangileri artık kütüphanede çözülü, hangileri
hâlâ elle kontrol edilecek sanat yönü. Ayrıca kaşın gölge düşürmesi
gerekiyorsa **geometri** olması gerektiği kuralı eklenir — bu bir yardımcı
fonksiyon değil, bir tercih.

README'ye şeridin sınırı yazılır: saç, kumaş, boyanmış yüz bu şeritte yoktur.

## Kabul kriterleri

1. Tek malzemeli, `ramp_linear` kullanan bir sahne, bu spec'ten **önceki**
   renderer ile üretilmiş altın görüntüyle piksel piksel aynı çıkar. Altın
   görüntü işe başlamadan alınır ve teste gömülür — sonradan üretilirse neyi
   koruduğunu kanıtlamaz.
2. `surface()` ile iki malzeme verilen bir sahnede, iki parçanın speküleri
   ölçülebilir biçimde farklı.
3. Temas gölgesi kapalıyken render süresi bu spec'ten önceki süreyle aynı
   mertebede. Açıkken süre ölçülür ve uygulama raporuna yazılır; varsayılanı
   değiştirme kararı o ölçüme bakılarak verilir.
4. `python3 -m pytest` yeşil ve toplam süre 10 saniyenin altında.
5. Demo karakter dört view ve iki ifade üretir; QC şeridi oyun boyutunda
   okunur.
6. `procedural-sprites/scripts/` altındaki her yeni fonksiyonun en az bir testi
   var.

## Kaynaklar

Bu tasarımın kanıta dayanan kısımları:

- **Malzeme yükü ve sert/yumuşak birleşim kuralı** — Inigo Quilez, *Happy
  Jumping* (Shadertoy `3lsSzf`): `vec4 map()` ile mesafe + malzeme kimliği +
  iki ek kanal; göz küresi kimliksiz `smin`, iris/bebek sert union. Electric
  Square raymarching workshop: `vec2 opU(d1, d2)`.
- **Kaynak radyusu** — aynı shader'ın çalışan değerleri: kafa 0.1, göz 0.03,
  kulak 0.01, bacak 0.07; uzuv boyunca değişen `k = 0.01 + 0.04*(1-h)^3`.
- **AO ve yumuşak gölge** — Quilez'in 5 örneklemeli AO'su ve tek march'lık
  `res = min(res, k*h/t)` gölgesi; bantlanma düzeltmesi Aaltonen, GDC 2018.
- **Cel rampası** — Roystan ve Daniel Ilett: `N·L` `[0,1]`'e taşınıp 1D rampa
  dokusuna koordinat olur; bant sayısı ve uçlar sanat olarak yazılır.
- **Cel speküleri** — IronWarrior/Roystan (`pow(NdotH * lightIntensity, 32²)`,
  `smoothstep(0.005, 0.01, ...)`) ve Ilett (`_Glossiness = 400`,
  `smoothstep(0, 0.01 * _Antialiasing, ...)`).
- **İç kontur** — Ronja: derinlik ve normal tamponlarında komşu farkı.
- **Pixel şeridinin aynı makineye dayandığı** — Motion Twin, *Dead Cells* art
  design deep dive: her kare 3D iskeletten PNG + normal haritası olarak
  çıkarılıp "basit bir toon shader" ile render ediliyor.

Doğrulamayı **geçemeyen** ve bu yüzden tasarıma girmeyen konular: oran
sistemleri, ifade parametreleştirmesi, siluet testleri, palet kuralları,
gölgede renk kayması, ve düz-vektör/kil/painterly ailelerinin gereksinimleri.
