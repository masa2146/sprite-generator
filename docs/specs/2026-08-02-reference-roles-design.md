# Rollü referans görselleri — Tasarım Dokümanı

**Tarih:** 2026-08-02
**Durum:** Onaylandı, uygulamaya hazır
**Bağlam:** Aynı oturumda yapılan prompt bloğu + ikinci referans görsel çalışmasının üstüne

## Amaç

`spritegen build`'in gönderdiği iki referans görselinin, yerel spritepipe backend'inde
**gerçekten kullanılmasını** sağlamak. Bugün ikisi de sessizce atılıyor.

## Sorun

spritepipe (`D:\PythonProjects\lora_work`) `input_references` içindeki her öğenin `role`
alanına bakıyor:

| `role` | Ne yapar |
|---|---|
| `structure` | Yeniden çizilecek nesne. Workflow'un `image1` slotuna gider. |
| `style` | Rengi, gölgelemesi, çizgisi ödünç alınacak görsel. `image2` slotuna gider. |
| `init` | Görseli olduğu gibi dönüştür (img2img). |

Rolü olmayan referans `style` sayılıyor, ve **çıplak bir style referansı asla img2img
kaynağı olarak kullanılmıyor** — spritepipe bunu kasten yapıyor: metin-görsel backend'lerin
stil koşullama girdisi yok, style ipucunu dönüştürmek onun kopyasını döndürür. spritepipe'ın
README'sindeki not tam olarak bu projeden çıkmış: "üç farklı prompt, sprite-generator'ın
style bible'ının üç kopyası olarak döndü."

spritegen `role` hiç göndermiyor. Sonuç: crop da ekran görüntüsü de tele çıkıyor, ComfyUI'a
hiç ulaşmıyor, üretim düz metin-görsel olarak yapılıyor.

Backend tarafı hazır: `projects/pixelflow/profile.json` `control_workflow_file` olarak
`workflows/qwen_edit_multi_api.json` gösteriyor (Qwen-Image-Edit-2511,
`TextEncodeQwenImageEditPlus`) ve `control_workflow_map` bir `style_image` slotu tanımlıyor.
Eksik olan tek şey spritegen'in `role` yazması.

## Kapsam

Bu tur **yalnızca kaynak oyunun görünümünü yeniden üretmeyi** hedefler: `[style] reference`
ekran görüntüsüdür, `structure` referansı ondan kesilmiş crop'tur.

Kapsam dışı, bilinçli olarak:

- **Re-skin** (kaynaktan sadece şekli alıp kendi stiline çevirme). Qwen-Edit structure
  görselinin çizim stilini de siluetiyle beraber aldığı için bu mod, crop'un önce
  düzleştirilmesini (rembg + tek renge boyama) gerektirir. İhtiyaç doğduğunda ayrı bir tur.
- **Alfa kesimi yerinin değişmesi.** `BG_CLAUSE` ve yerel `post.py` kesimi aynen kalır;
  spritepipe'ın `background: "transparent"` sprite hattı bu turda kullanılmaz.
- **Üçüncü bir transport** (OpenAI'ın gerçek `/v1/images/edits` multipart şekli).
  Taşınabilirlik ihtiyaç doğduğunda ele alınır; bu tasarım onu zorlaştırmaz.
- **`control_strength`.** pixelflow'un `control_workflow_map`'inde `strength` anahtarı yok;
  göndermek etkisiz olurdu.

## Mimari

### `generate()` imzası: iki adlandırılmış slot

Bugün tek bir `reference_png` parametresi üç ayrı işi taşıyor — asset'in kendi crop'u,
style bible, ve `analyze` akışının kaynak görseli. Bunlar aynı şey değil, ve hangisinin
gönderildiğini çağıran biliyor. İmza bunu görünür kılar:

```python
orclient.generate(pack, prompt, aspect_ratio=None,
                  structure_png=None, style_png=None, seed=None, ...)
```

- **`structure_png`** — yeniden çizilecek nesne. Yalnızca asset kendi crop'unu getirdiğinde.
- **`style_png`** — görünüm kaynağı.

Bu ayrım style bible'ı doğru kutuya koyar: style bible bir siluet değil, bir görünüm
örneğidir, ve onu structure sanmak yukarıda anılan "üç kopya" hatasının ta kendisiydi.

### `build_one` seçim tablosu

| asset'in kendi crop'u | pack'in `[style] reference`'ı | `structure_png` | `style_png` |
|---|---|---|---|
| var | var | crop | ekran görüntüsü |
| var | yok | crop | — |
| yok | (fark etmez) | — | style bible |

Son satır bugünkü davranışın korunması: kendi crop'u olmayan asset zaten style bible'ı
alıyordu; değişen tek şey artık doğru rolle gitmesi. Pack'in `[style] reference`'ı olsa
bile bu satırda style bible kazanır — asset'in kendi crop'u yokken gönderilecek ikinci bir
görsel yoktur, ve bugünkü davranış budur.

`build` dışındaki tek `generate()` çağrısı `analyze` akışının aday üretimidir; kullanıcının
kaynak görselini `style_png` olarak gönderir. Orada da bir siluet değil, taklit edilecek bir
görünüm vardır.

`[style] reference` okunamazsa asset başarısız olur (yumuşak geçiş değil): `full_prompt` o
noktada modele zaten bir `image2` vaat etmiştir, tek görselle göndermek yalan olur.

### Transport'lara göre tel şekli

**`images`** (spritepipe ve OpenRouter) — sıra korunur ama anlamı artık `role` taşır:

```jsonc
"input_references": [
  {"type": "image_url", "image_url": {"url": "data:..."}, "role": "structure"},
  {"type": "image_url", "image_url": {"url": "data:..."}, "role": "style"}
]
```

**`chat`** — `role` diye bir kavram yok; etiketi metin taşır, o yüzden parçalar
serpiştirilir ve her etiket kendi görselinin hemen önünde durur:

```jsonc
"content": [
  {"type": "text", "text": "image1:"}, {"type": "image_url", "image_url": {...}},
  {"type": "text", "text": "image2:"}, {"type": "image_url", "image_url": {...}},
  {"type": "text", "text": "<prompt blokları>"}
]
```

Tek görsel gönderildiğinde etiket yazılmaz — ortada çözülecek belirsizlik yoktur ve
bugünkü ölçülmüş şekil korunur.

### Prompt sözcükleri

`REFERENCES` bloğu `image1` / `image2` token'larını birebir kullanır. Bunlar
`TextEncodeQwenImageEditPlus`'ın slot adlarıdır; spritepipe'ın README'sindeki örnek prompt
da "Redraw the object from image1 ... colours and outline from image2" der.

```
REFERENCES
- image1 — the object to redraw. Reproduce THIS object.
- image2 — the reference screenshot. Use it ONLY for art style, palette
  and lighting. Do not copy any object from it.
```

Metin `config.py`'de tek yerde durur; `brief.html`'in figür başlıkları da aynı sözcüğü
kullanır, böylece ekranda yazan ile prompt'ta yazan ayrışmaz.

## Testler

Birim testler payload şeklini kanıtlar:

- `role` alanları ve sıra; tek görsel halinin bugünkü şekli koruması
- `build_one`'ın hangi baytı hangi slota koyduğu — özellikle style bible'ın `style` slotunda
  olması, `structure`'da değil
- `REFERENCES` bloğunun yalnızca iki görsel gerçekten tele çıktığında yazılması

## Doğrulama

Birim testler görselin iyi olduğunu kanıtlamaz. Kabul testi elle yapılır: spritepipe ayakta
(`spritepipe-comfyui` + `spritepipe-serve`), `packs/pf_extracted.toml`'dan birkaç asset
build edilir ve çıktıya bakılır. Üç soru:

1. **structure devrede mi?** Siluet crop'a benziyor mu. Bugün hiç kullanılmadığı için fark
   bariz olmalı; olmazsa `role` backend'e ulaşmamış demektir.
2. **image2 sahneyi sürüklüyor mu?** Kalabalık bir ekran görüntüsü style slotunda risk.
   Sürüklerse `[style] reference`'ı tek nesneli bir plakaya çevirmek tek satırlık düzeltme.
3. **`#808080` arka plan hâlâ geliyor mu?** En kritik bilinmeyen. Edit modeli `image1`'i
   yeniden çiziyor ve crop'un arka planı ekran görüntüsünün arka planı, gri değil.
   `BG_CLAUSE` bu yolda tutmazsa yerel `rembg`'in keseceği düz zemin olmaz. Tutmadığı
   ölçülürse ayrı bir karar gerekir (prompt'u güçlendirmek ya da spritepipe'ın
   `background: "transparent"` hattına geçmek) — bu tasarım o kararı vermez, sadece
   ölçümü zorunlu kılar.

## Bilinen risk

`role`, OpenRouter'ın `input_references` şemasında tanımlı bir alan değil. spritepipe
bilinmeyen alanları yutuyor ("Unknown fields are ignored rather than rejected"); hosted
OpenRouter katı davranıp 400 dönerse orada görülür. Rolsüz göndermek yerel backend'de hiç
çalışmadığı için göndermemek seçenek değil.
