# Rollü referans görselleri — Canlı doğrulama sonucu

Bu doküman Task 5'in ölçüm çıktısıdır: `spritegen build`'in gerçek yerel
backend'e (`spritepipe-serve` + ComfyUI) karşı ürettiği görsellerin doğrudan
gözlemidir. Karar içermez, yalnızca ne görüldüğünü kaydeder.

## Ortam ve koşum

- Branch/HEAD: `fix/local-endpoint-config` @ `99d0a37`.
- Backend zaten ayaktaydı (`http://127.0.0.1:8000/v1/models` → `pixelflow`,
  `raw:pixelflow`; ComfyUI `:8188`).
- `packs/pf_extracted.toml` build'i çalıştırılamıyordu: 37. satırda kapanış
  `"""` hemen ardından yapışık bir `b` karakteri vardı (`"""b`), bu da TOML'u
  geçersiz kılıyordu. Bu dosya `.gitignore`'da (`packs/`), herhangi bir commit'e
  girmiyor; ölçümü açabilmek için satır `"""` olarak düzeltildi. Repodaki kod
  veya spec ile ilgisi yok, yerel pack dosyasının bozuk bir karakteriydi.
- `py -m spritegen build packs/pf_extracted.toml --dry-run` çalıştırıldı: her
  asset için basılan prompt `REFERENCES` bloğuyla başlıyor ve `image1` / `image2`
  sözcüklerini içeriyor. Task 1-4'ün ürettiği şekil doğru üretiliyor.

## Denenen asset'ler

Sırayla üç `--only <asset-id>` çağrısı planlandı; fiilen şu sonuçlar alındı:

1. `numbered_bunny-front` — **ComfyUI tarafında üretim tamamlandı**, ama
   son adımda `post-processing: No module named 'rembg' (raw kept as
   numbered_bunny-front.raw.png)` hatasıyla "failed" olarak işaretlendi.
   `rembg[gpu]>=2.0.75` `pyproject.toml`'da bağımlılık olarak tanımlı ama bu
   ortamda kurulu değil (`py -m pip show rembg` → "Package(s) not found").
   Ham (kesilmemiş) çıktı `out/pf_extracted/numbered_bunny-front.raw.png`
   olarak diskte kaldı ve aşağıdaki üç soru bu dosya üzerinden cevaplandı.
2. `brick_tile-front` — iki kez denendi, ikisinde de `HTTP 502`. İkinci
   denemenin tam sırasında ComfyUI'nin arka uç süreci çöktü (bkz. aşağı).
   Hiçbir görsel dosyası üretilmedi.
3. `track_direction_chevron-front` — **denenemedi**. ComfyUI süreci ikinci
   asset'teki çökmeden sonra `:8188` üzerinde cevap vermez oldu
   (`/v1/models` `:8000`'de hâlâ 200 dönüyor, ama `:8188/system_stats`
   bağlantı kuramıyor). Görevin talimatı ve izin sistemi backend'i yeniden
   başlatmamı engellediği için üçüncü asset'e hiç istek gönderilemedi.

Yani üç sorunun ampirik cevabı **yalnızca bir** üretilmiş görsele
(`numbered_bunny-front.raw.png`) dayanıyor; ikinci ve üçüncü asset planlanan
şekilde denenemedi. Bu, aşağıdaki cevapların örneklem büyüklüğünü sınırlıyor.

### ComfyUI çökmesi — ayrı bir bulgu

`D:\PythonProjects\lora_work\comfyui.log.err` (aynı makinede, backend'in
kendi log dosyası) üçüncü isteğin ortasında bir `Windows fatal exception:
access violation` gösteriyor. Yığın izi tamamen bellek/model yönetimi
kodunda: `model_management.py:model_unload` → `model_patcher.py:detach` →
`unpatch_model` → `comfy\ops.py:_apply` (`comfy_kitchen` tensor
dispatch'i). Referans görselleri, `role` alanı ya da `input_references`
şekliyle hiçbir ilgisi yok — çökme, örneği görmeden önce sıradaki modeli
GPU'ya yüklemek için bir öncekini boşaltırken oldu. Bu nedenle bu bir "backend
`role`'ü reddetti" durumu **değil**; ComfyUI'nin kendi bellek yönetiminde,
muhtemelen VRAM baskısı altında tetiklenen bağımsız bir kararsızlık.

Ayrıca `spritepipe`'ın kaynağına (`lora_work/spritepipe/api/openrouter.py`)
bakıldığında `role` alanının (`structure` / `style` / `init`) zaten
uygulandığı görüldü: `structure_image`, `style_image` ve `init_image`
property'leri `role` alanına göre yönlendiriyor, roller belirtilmemişse
pozisyona (ilk görsel = structure, ikinci = style) düşüyor. Yani "backend
ikisini de sessizce atıyordu" öncülü artık geçerli değil — kod bu tarafta
rolleri okuyor. Aşağıdaki gözlem bunu doğruluyor.

## Üç soru

### 1. Structure devrede mi?

**Evet, açıkça devrede — hatta beklenenden daha güçlü.** `numbered_bunny-front.raw.png`
ile `packs/refs/numbered_bunny.png` (crop) karşılaştırıldığında:

- Silüet birebir eşleşiyor: tek parça yumurta gövde, üstten yükselen iki
  uzun sivri kulak (kulak içleri koyu gölgeli), gövde tabanında iki küçük
  ayak çıkıntısı.
- Renk (camgöbeği/cyan) ve üstteki parlak highlight noktası aynı yerde.
- Crop'un kendi "40" rakamı **de** neredeyse birebir kopyalanmış — prompt'un
  "DO NOT DRAW any text, numbers, labels" maddesine ve `REFERENCES` bloğunun
  "Do NOT take its rendering... redraw cleanly... in the ART STYLE below"
  talimatına rağmen.
- Çıktının kendisi hâlâ crop'un kendi düşük çözünürlüklü / blok blok
  (pixel-art) görünümünü taşıyor; pack'in `ART STYLE` maddesinin istediği
  "flat vector-style... soft gradient fills... no texture noise" görünümü
  **uygulanmamış**. Yani `image1` sadece kimliği değil, render'ı da
  domine ediyor gibi görünüyor.

Kısacası: rol backend'e ulaşıyor ve şekli sürüklüyor — önceki (referanssız)
duruma göre fark bariz — ama etkisi prompt'un "yalnızca kimlik, render değil"
sınırının epey ötesine geçmiş görünüyor.

### 2. image2 sahneyi sürüklüyor mu?

**Hayır, bu örnekte değil.** Çıktıda tavşan dışında hiçbir şey yok: ne oyun
tahtasının karoları, ne üstteki ayarlar/seviye/coin arayüzü, ne de
`_style.png`'deki diğer tavşanlar. Tek nesne, düz zemin üzerinde, ortalı.
`[style] reference` (`refs/_style.png`) yalnızca palet/ışık kaynağı gibi
davranmış görünüyor; sahneden nesne sızması gözlenmedi.

(Not: yalnızca tek asset ölçüldüğü için bu "hayır" tek örneğe dayanıyor;
genelleme yapılmıyor.)

### 3. `#808080` arka plan geliyor mu?

**Evet, düz ve tekdüze bir gri zemin geliyor — ama tam `#808080` değil.**
Görsel 1024×1024, zeminden çok sayıda nokta örneklendi (kenarlardan,
köşelerden): RGB değerleri dar bir aralıkta, ortalama yaklaşık
`(155, 151, 150)` (R/G/B min-max: 154-157 / 150-153 / 148-151). İstenen
`#808080` (128, 128, 128) belirgin şekilde daha koyu; üretilen zemin daha
açık ve hafif sıcak tonlu (R biraz G/B'den yüksek), fakat düzlüğü/tekdüzeliği
yüksek — gradyan, doku ya da gölge yok.

Bu, yerel `rembg` için "temiz bir zemin var mı" sorusuna kısmen olumlu cevap:
zemin düz ve nesneyle yeterince kontrastlı, kesim için kullanılabilir bir aday.
Ancak uçtan uca doğrulanamadı — bu ortamda `rembg` paketi kurulu olmadığı için
(`ModuleNotFoundError`, bkz. yukarıda) post-processing adımı hiç çalışmadı;
raw dosya bu yüzden diskte kaldı. `rembg`'in bu zemini gerçekte nasıl kestiği
ölçülmedi.

## Sonraki turun girdisi olabilecek gözlemler (karar verilmedi)

- ComfyUI süreci bir isteğin ortasında `access violation` ile çöktü ve
  oturum boyunca kendiliğinden toparlanmadı; ikinci ve üçüncü asset bu yüzden
  hiç üretilemedi.
- Bu ortamda `rembg` kurulu değil; `pyproject.toml`'daki bağımlılık
  (`rembg[gpu]>=2.0.75`) fiilen karşılanmıyor, dolayısıyla post-processing
  adımı hiçbir başarılı üretimde tamamlanamıyor.
- Zemin rengi istenen `#808080`'den belirgin şekilde sapıyor (~`#9b9796`),
  düz olsa da hedef hex ile eşleşmiyor.
- `image1`'in etkisi, prompt'un istediği kimlik-only sınırının ötesine geçip
  render stilini (pixel-art blokluluk) ve yasaklanan metni (rakamlar) de
  taşıyor gibi görünüyor; pack'in `ART STYLE` maddesi bu tek örnekte
  uygulanmamış görünüyor.
