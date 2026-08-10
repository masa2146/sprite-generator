# SDF Lane Ceiling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Her parçanın kendi yüzeyi, gerçek temas gölgesi, geometri olan gözler, bantlı (cel) gölgeleme seçeneği ve iç kontur — SDF şeridinden çıkan her şeyin aynı plastik parlaklıkta olmasını bitirmek.

**Architecture:** `sdf3d.py` ışığı ve yüzeyi büyütür (malzeme yükü, difüz rampa, sert speküler, 5 örneklemeli AO, opsiyonel temas gölgesi, derinlik+normal tamponlarından iç kontur). Yeni `character_lib.py` karaktere özgü olanı taşır (geometri olan göz, decal araçları, ışığın yaw ile dönmesi, turnaround). `sprite_lib.py` teslim ve denetimi alır (sabit genişlikte kontur, okunurluk ölçümü). Primitif imzaları değişmez; mevcut setler kendi kopyalarını çalıştırdığı için kırılmaz.

**Tech Stack:** Python 3.11+, numpy, Pillow, pytest. Ağ yok, ek bağımlılık yok.

**Spec:** `docs/specs/2026-08-11-character-lib-design.md`

## Global Constraints

- Python `>=3.11`. Bağımlılık **yalnızca** `pillow` + `numpy`. Kurulum adımı yok.
- Kod, docstring, yorum ve commit mesajları **İngilizce**. Plan/spec Türkçe.
- Yorumlar *neden*i anlatır ve mümkünse ölçülmüş bir hataya dayanır. Taşınan koddaki mevcut yorumlar silinmez.
- **Taşıyıcı kural:** aynı malzemeyi paylaşanlar yumuşak birleşir, kendi kimliği olması gereken sert birleşir. Malzeme kimliği en yakın parçadan seçilir ve bu seçim yalnızca sert birleşimde doğrudur.
- Testler `OVERSAMPLE = 1` ve **32×32** render ile çalışır. Tüm suite **10 saniyenin altında** kalmalı (bugün ~1 sn).
- Testler pytest fixture/plugin kullanmaz — düz fonksiyonlar, gerçek dosyalar (repo kalıbı).
- `docs/` tarihsel kayıttır, düzenlenmez.
- `sprites/` altındaki yerel setler bu planın konusu değildir; onlara dokunulmaz.
- Kütüphane teknik verir, stil vermez: anatomi şablonu, oran sistemi, hazır karakter yazılmaz.

---

## File Structure

**Yaratılacak:**

| dosya | sorumluluğu |
|---|---|
| `.claude/skills/procedural-sprites/scripts/character_lib.py` | geometri olan göz, decal araçları, ışık/turnaround |
| `tests/test_sdf3d.py` | renderer: altın görüntü, malzeme, rampa, AO, gölge, kenar |
| `tests/test_sprite_lib.py` | kontur ve okunurluk |
| `tests/test_character_lib.py` | göz, decal, turnaround |
| `tests/fixtures/golden_soft_sphere.png` | değişmemesi gereken çıktı, **iş başlamadan** alınır |

**Değişecek:** `.claude/skills/procedural-sprites/scripts/sdf3d.py`, `sprite_lib.py`, `tests/conftest.py`, `.claude/skills/procedural-sprites/SKILL.md`, `README.md`.

---

### Task 1: Test iskelesi ve altın görüntü

Bu görev **her şeyden önce** gelir. Altın görüntü, renderer'a dokunulmadan alınır — sonradan üretilirse neyi koruduğunu kanıtlamaz.

**Files:**
- Modify: `tests/conftest.py`
- Create: `tests/test_sdf3d.py`
- Create: `tests/fixtures/golden_soft_sphere.png`

**Interfaces:**
- Consumes: mevcut `sdf3d.render`, `sdf3d.sphere`, `sdf3d.flat`
- Produces: `tests/fixtures/golden_soft_sphere.png` — sonraki her görevin bozmaması gereken çıktı; `tests/test_sdf3d.py::test_the_soft_path_still_renders_exactly_as_it_did`

- [ ] **Step 1: `conftest.py`'ye ikinci scripts dizinini ekle**

```python
"""Tests import the skills' scripts straight from the checkout.

There is no package and no install step, so the path the skills themselves
use at runtime is the path the tests must use too — anything else would
test a copy.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for scripts in (ROOT / ".claude" / "skills" / "sprite-brief" / "scripts",
                ROOT / ".claude" / "skills" / "procedural-sprites" / "scripts"):
    sys.path.insert(0, str(scripts))
```

- [ ] **Step 2: Altın görüntüyü üret**

`sdf3d.py`'ye **hiç dokunmadan** çalıştır:

```bash
mkdir -p tests/fixtures
python3 - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, ".claude/skills/procedural-sprites/scripts")
import sdf3d
from sdf3d import sphere, render, flat

sdf3d.OVERSAMPLE = 1
img = render(sphere(0.7), size=(32, 32), tilt=15,
             color=flat((240, 160, 20)), ao=0.0, rim=0.0)
img.save("tests/fixtures/golden_soft_sphere.png")
print(img.size, img.mode)
PY
```

`ao=0.0` ve `rim=0.0` bilerek: AO bu planda değişiyor (Görev 4), rim ise malzeme başına diziye dönüşüyor. Altın görüntü **difüz + speküler + rampa** yolunu sabitler, değişmesi planlanan iki terimi değil. Bunu teste yorum olarak yaz.

- [ ] **Step 3: Altın görüntü testini yaz**

`tests/test_sdf3d.py`:

```python
"""Renderer tests. Everything renders at OVERSAMPLE=1 and 32x32 — the point
is to pin behaviour, not to look at anything."""
from pathlib import Path

import numpy as np
from PIL import Image

import sdf3d
from sdf3d import flat, render, sphere

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _small(sdf, **kw):
    """A render small enough to run in a test. OVERSAMPLE is module state, so
    it is set and restored around every call rather than left mutated."""
    before = sdf3d.OVERSAMPLE
    sdf3d.OVERSAMPLE = 1
    try:
        return render(sdf, size=(32, 32), tilt=15, **kw)
    finally:
        sdf3d.OVERSAMPLE = before


def test_the_soft_path_still_renders_exactly_as_it_did():
    """The golden was captured from the renderer as it stood before any of
    this work, with ao and rim off: those two terms are the ones this plan
    deliberately changes, and pinning them would pin the wrong thing. What
    this test protects is the diffuse and specular path — the default ramp
    must reproduce it arithmetic-for-arithmetic."""
    got = _small(sphere(0.7), color=flat((240, 160, 20)), ao=0.0, rim=0.0)
    want = Image.open(FIXTURES / "golden_soft_sphere.png")
    assert np.array_equal(np.asarray(got), np.asarray(want))
```

- [ ] **Step 4: Testin geçtiğini gör**

Run: `python3 -m pytest tests/test_sdf3d.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Tüm suite'i çalıştır**

Run: `python3 -m pytest -q`
Expected: PASS, süre 10 saniyenin altında

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/test_sdf3d.py tests/fixtures/golden_soft_sphere.png
git commit -m "test: pin the renderer's soft path before changing it

The procedural-sprites scripts have never had a test. This adds the path
and one golden image, captured from the renderer as it stands, so the
diffuse and specular arithmetic can be proven unchanged after the ramp
seam lands. ao and rim are off in the golden because this plan changes
both on purpose."
```

---

### Task 2: `sdf3d` — kütüphanenin borcu (`torus_z`, `squash`)

**Files:**
- Modify: `.claude/skills/procedural-sprites/scripts/sdf3d.py`
- Modify: `tests/test_sdf3d.py`

**Interfaces:**
- Consumes: yok
- Produces: `sdf3d.torus_z(R, r, center=(0,0,0)) -> fn(p)->dist`, `sdf3d.squash(fn, sx, sy, sz) -> fn(p)->dist`; `sdf3d.scale_y(fn, s)` korunur ve `squash`'a delege eder

- [ ] **Step 1: Failing testleri yaz**

`tests/test_sdf3d.py`'ye ekle:

```python
from sdf3d import squash, torus_z, torus_y, scale_y


def test_torus_z_stands_in_the_xy_plane():
    """torus_y lies flat and vanishes at tilt=0, which is why a set that
    needed a ring standing towards the camera grew its own torus_z rather
    than using the library."""
    ring = torus_z(0.5, 0.1)
    p = np.array([[0.5, 0.0, 0.0], [0.0, 0.5, 0.0], [0.0, 0.0, 0.5]])
    d = ring(p)
    assert abs(d[0] + 0.1) < 1e-6, d       # on the ring, x axis
    assert abs(d[1] + 0.1) < 1e-6, d       # on the ring, y axis
    assert d[2] > 0.3, d                   # z axis is off the ring entirely


def test_squash_scales_each_axis():
    s = squash(sphere(1.0), 2.0, 1.0, 1.0)
    p = np.array([[2.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    d = s(p)
    assert abs(d[0]) < 1e-6, d             # stretched to x=2
    assert abs(d[1]) < 1e-6, d             # untouched on y


def test_scale_y_still_works_through_squash():
    a = scale_y(sphere(1.0), 2.0)
    p = np.array([[0.0, 2.0, 0.0]])
    assert abs(a(p)[0]) < 1e-6, a(p)
```

- [ ] **Step 2: Testlerin patladığını gör**

Run: `python3 -m pytest tests/test_sdf3d.py -v -k "torus_z or squash or scale_y"`
Expected: FAIL — `ImportError: cannot import name 'torus_z'`

- [ ] **Step 3: İkisini de yaz**

`sdf3d.py`'de `torus_y`'nin hemen altına:

```python
def torus_z(R, r, center=(0, 0, 0)):
    """Ring standing in the XY plane, facing the camera.

    torus_y lies flat and disappears at tilt=0, so an asset that needs a ring
    seen face-on — a septum ring, a hoop, a portal — cannot use it. This lived
    in one set's private copy of the library until it was moved here.
    """
    c = np.array(center, float)
    def f(p):
        q = p - c
        dxy = np.sqrt(q[..., 0]**2 + q[..., 1]**2) - R
        return np.sqrt(dxy**2 + q[..., 2]**2) - r
    return f
```

`scale_y`'yi değiştir ve `squash`'ı ekle:

```python
def squash(fn, sx, sy, sz):
    """Non-uniform scale of an SDF, Lipschitz-corrected by the smallest factor.

    Approximate, which is all a sprite needs: an ear has to be flat
    front-to-back like its reference's, and a capsule alone is a round stick.
    Two character scripts each defined their own copy of this before it was
    moved here.
    """
    inv = np.array([1.0 / sx, 1.0 / sy, 1.0 / sz])
    k = min(sx, sy, sz)
    return lambda p: fn(p * inv) * k


def scale_y(fn, s):
    """Squash/stretch a primitive along Y."""
    return squash(fn, 1.0, s, 1.0)
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `python3 -m pytest tests/test_sdf3d.py -v`
Expected: PASS (4 test), altın görüntü testi dahil

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/procedural-sprites/scripts/sdf3d.py tests/test_sdf3d.py
git commit -m "feat: give the library the primitives its assets already needed

torus_z lived in one set's private copy because torus_y lies flat and
vanishes at tilt=0; squash was defined twice, once per character script.
An asset's need belongs in the library, not in the copy."
```

---

### Task 3: `sdf3d` — malzeme (`material`, `surface`)

`part_color` kaldırılır. Parça artık rengiyle birlikte **yüzeyini** de taşır.

**Files:**
- Modify: `.claude/skills/procedural-sprites/scripts/sdf3d.py`
- Modify: `tests/test_sdf3d.py`

**Interfaces:**
- Consumes: Görev 2'nin primitifleri
- Produces: `sdf3d.material(color, spec=0.5, shininess=40, rim=0.10, spec_color=(255,255,255), spec_hard=None) -> Material`; `sdf3d.surface(parts) -> Surface` burada `parts = [(sdf_fn, Material), ...]`; `render(..., color=<Surface|callable|Material>)`

- [ ] **Step 1: Failing testleri yaz**

```python
from sdf3d import material, surface, union


def _two_balls(left_mat, right_mat):
    l = sphere(0.42, (-0.45, 0.0, 0.0))
    r = sphere(0.42, (0.45, 0.0, 0.0))
    return union(l, r), surface([(l, left_mat), (r, right_mat)])


def test_each_part_keeps_its_own_colour():
    shape, surf = _two_balls(material((220, 40, 40)), material((40, 80, 220)))
    a = np.asarray(_small(shape, color=surf, ao=0.0, rim=0.0)).astype(int)
    left = a[16, 6, :3]
    right = a[16, 25, :3]
    assert left[0] > left[2] + 60, left
    assert right[2] > right[0] + 60, right


def test_each_part_keeps_its_own_specular():
    """This is the one part_color could not do: it varied colour only, so a
    gold ring came out with the same gloss as the stone it hung on."""
    dull = material((200, 200, 200), spec=0.0, shininess=40)
    shiny = material((200, 200, 200), spec=1.0, shininess=40)
    shape, surf = _two_balls(dull, shiny)
    a = np.asarray(_small(shape, color=surf, ao=0.0, rim=0.0)).astype(int)
    lit = a[..., :3].max(axis=-1)
    assert lit[:, 16:].max() > lit[:, :16].max() + 25, (
        lit[:, :16].max(), lit[:, 16:].max())


def test_a_plain_colour_function_still_renders():
    """The single-material call is what every existing asset makes."""
    img = _small(sphere(0.7), color=flat((240, 160, 20)), ao=0.0, rim=0.0)
    assert img.mode == "RGBA" and img.size == (32, 32)


def test_part_color_is_gone():
    assert not hasattr(sdf3d, "part_color")


def test_a_surface_can_be_the_base_of_a_decal_stack():
    """spots() calls its base as base(p, n). Face decals paint over a body
    that already has materials, so a Surface has to answer that call with its
    colour."""
    from sdf3d import spots
    _, surf = _two_balls(material((220, 40, 40)), material((40, 80, 220)))
    painted = spots(surf, [((0.0, 0.0, 1.0), 40.0, 2.0, (10, 240, 10))],
                    center=(0.45, 0.0, 0.0))
    a = np.asarray(_small(sphere(0.42, (0.45, 0.0, 0.0)), color=painted,
                          ao=0.0, rim=0.0)).astype(int)
    green = ((a[..., 1] > 180) & (a[..., 0] < 120) & (a[..., 3] > 250)).sum()
    assert green > 0, "the decal never reached the surface"
```

- [ ] **Step 2: Testlerin patladığını gör**

Run: `python3 -m pytest tests/test_sdf3d.py -v -k "part or colour or specular"`
Expected: FAIL — `ImportError: cannot import name 'material'`

- [ ] **Step 3: `Material`, `surface` ve `render`'ın toplama adımını yaz**

`part_color`'ı sil, yerine:

```python
class Material:
    """A part's colour AND its surface. Splitting these was the ceiling: the
    old part_color varied colour alone, so bone, hide and metal came out of
    one render with the same gloss."""
    __slots__ = ("color", "spec", "shininess", "rim", "spec_color", "spec_hard")

    def __init__(self, color, spec, shininess, rim, spec_color, spec_hard):
        self.color = color
        self.spec = spec
        self.shininess = shininess
        self.rim = rim
        self.spec_color = spec_color
        self.spec_hard = spec_hard


def material(color, spec=0.5, shininess=40, rim=0.10,
             spec_color=(255, 255, 255), spec_hard=None):
    return Material(color, spec, shininess, rim, spec_color, spec_hard)


class Surface:
    """Materials keyed by nearest part.

    At each surface point the part whose SDF reads closest to zero wins. That
    is exact for a hard `union` and WRONG inside a `smooth_union` band, where
    the surface belongs to neither part — so blend softly only within one
    material, and hard-union anything that needs its own.
    """
    def __init__(self, parts):
        self.parts = list(parts)

    def resolve(self, p, n):
        ds = np.stack([np.abs(f(p)) for f, _ in self.parts], axis=-1)
        idx = ds.argmin(axis=-1)
        rows = p.shape[0]
        base = np.zeros((rows, 3))
        spec = np.zeros(rows)
        shin = np.zeros(rows)
        rim = np.zeros(rows)
        scol = np.zeros((rows, 3))
        hard = np.full(rows, np.nan)
        for i, (_, m) in enumerate(self.parts):
            msk = idx == i
            if not msk.any():
                continue
            c = m.color
            base[msk] = c(p[msk], n[msk]) if callable(c) else np.array(c, float)
            spec[msk] = m.spec
            shin[msk] = m.shininess
            rim[msk] = m.rim
            scol[msk] = np.array(m.spec_color, float)
            if m.spec_hard is not None:
                hard[msk] = m.spec_hard
        return base, spec, shin, rim, scol, hard


def surface(parts):
    return Surface(parts)
```

`Surface` ayrıca `spots()`'un `base` parametresi olarak geçilebilmeli — yüz
decal'leri malzemeli bir gövdenin üstüne biniyor ve `spots` `base`'i
`base(p, n)` diye çağırıyor. Bu yüzden `Surface`'a yalnızca rengi döndüren bir
`__call__` eklenir:

```python
    def __call__(self, p, n):
        """Colour only, so a Surface can be the base of spots(): face decals
        paint over a body that already has materials."""
        return self.resolve(p, n)[0]
```

`render()` içinde, `base = color(ph, nh)` satırının yerine:

```python
    if isinstance(color, Surface):
        base, spec_a, shin_a, rim_a, scol_a, hard_a = color.resolve(ph, nh)
    else:
        base = color(ph, nh)
        rows = ph.shape[0]
        spec_a = np.full(rows, float(spec))
        shin_a = np.full(rows, float(shininess))
        rim_a = np.full(rows, float(rim))
        scol_a = np.broadcast_to(np.array(spec_color, float), (rows, 3))
        hard_a = np.full(rows, np.nan)
```

ve gölgeleme satırlarını dizilerle çalışacak şekilde güncelle:

```python
        sp = np.clip(nh @ Hv, 0, 1) ** shin_a
        rimterm = rim_a * np.clip(1 - nh[:, 2], 0, 1)**2
        c = base*(ambient + diffuse*lam[:, None])*aoterm[:, None] \
            + scol_a*(spec_a*sp)[:, None] + rimterm[:, None]*255.0
```

**Dikkat:** eski kod `rc*rimterm[:, None]` kullanıyordu (`rim_color` çarpanı). `rim_color` parametresi korunur ve `scol_a` gibi diziye çevrilir; yukarıdaki satırı `+ rcol_a*rimterm[:, None]` olarak yaz ve `rcol_a`'yı `rim_color`'dan üret. Malzeme başına rim rengi **yok** — `Material.rim` yalnızca şiddettir; rim rengi sahne geneli kalır.

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `python3 -m pytest tests/test_sdf3d.py -v`
Expected: PASS — altın görüntü testi dahil (skaler yol aritmetiği değişmedi)

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/procedural-sprites/scripts/sdf3d.py tests/test_sdf3d.py
git commit -m "feat: give every part its own surface, not just its own colour

part_color varied colour and nothing else, so one render gave hide, bone
and metal the same gloss. Materials now carry spec, shininess, rim and
specular colour, gathered per hit point from the nearest part."
```

---

### Task 4: `sdf3d` — 5 örneklemeli AO

**Files:**
- Modify: `.claude/skills/procedural-sprites/scripts/sdf3d.py`
- Modify: `tests/test_sdf3d.py`

**Interfaces:**
- Consumes: Görev 3
- Produces: `render(..., ao=0.55, ao_radius=0.12)`

- [ ] **Step 1: Failing testi yaz**

```python
def test_ao_darkens_a_crease_more_than_a_flat_face():
    """Two spheres pushed into each other make a crease along the seam. With
    ao off the seam shades like everything else; with ao on it has to go
    darker, which is what makes parts read as joined rather than stacked."""
    a = sphere(0.45, (-0.28, 0.0, 0.0))
    b = sphere(0.45, (0.28, 0.0, 0.0))
    shape = union(a, b)
    off = np.asarray(_small(shape, color=flat((200, 200, 200)), ao=0.0,
                            rim=0.0)).astype(int)
    on = np.asarray(_small(shape, color=flat((200, 200, 200)), ao=0.8,
                           rim=0.0)).astype(int)
    seam_off = off[16, 16, :3].mean()
    seam_on = on[16, 16, :3].mean()
    edge_on = on[16, 4, :3].mean()
    assert seam_on < seam_off - 12, (seam_on, seam_off)
    assert seam_on < edge_on, (seam_on, edge_on)
```

- [ ] **Step 2: Testin patladığını gör**

Run: `python3 -m pytest tests/test_sdf3d.py -v -k ao_darkens`
Expected: FAIL — tek örneklemeli AO çukuru yeterince koyulaştırmıyor

- [ ] **Step 3: AO'yu değiştir**

`render()`'ın imzasına `ao_radius=0.12` ekle. `occ`/`aoterm` satırlarının yerine:

```python
        # Five taps marched along the normal, Quilez's estimator: each sample
        # asks how much closer the surface is than the step that was taken,
        # which is exactly how concave the neighbourhood is. The single sample
        # this replaced could not tell a crease from a gentle curve.
        occ = np.zeros(ph.shape[0])
        sca = 1.0
        for i in range(1, 6):
            hstep = 0.01 + ao_radius * i / 5.0
            occ += (hstep - sdf(ph + nh*hstep)) * sca
            sca *= 0.95
        aoterm = np.clip(1.0 - 3.0*ao*occ, 0, 1)
```

`ao_radius` parametredir çünkü sahne ölçeğine bağlı: bu dünyada görünen çerçeve kabaca `x,y ∈ [-1,1]`.

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `python3 -m pytest tests/test_sdf3d.py -v`
Expected: PASS — altın görüntü `ao=0.0` ile alındığı için etkilenmez

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/procedural-sprites/scripts/sdf3d.py tests/test_sdf3d.py
git commit -m "feat: five-tap ambient occlusion, so a crease reads as a join

One sample along the normal cannot tell a crease from a gentle curve, which
is why parts came out looking stacked rather than joined."
```

---

### Task 5: `sdf3d` — difüz rampa

**Files:**
- Modify: `.claude/skills/procedural-sprites/scripts/sdf3d.py`
- Modify: `tests/test_sdf3d.py`

**Interfaces:**
- Consumes: Görev 4
- Produces: `sdf3d.ramp_linear() -> fn(lam)->float array`, `sdf3d.ramp_bands(thresholds) -> fn(lam)->float array`, `render(..., ramp=None)` — `None` ise `ramp_linear()` kullanılır

- [ ] **Step 1: Failing testleri yaz**

```python
from sdf3d import ramp_bands, ramp_linear


def test_the_default_ramp_is_the_old_arithmetic():
    lam = np.linspace(0, 1, 9)
    assert np.allclose(ramp_linear()(lam), 0.42 + 0.62*lam)


def test_bands_quantise_the_response():
    lam = np.linspace(0, 1, 101)
    out = ramp_bands([0.35, 0.75])(lam)
    assert len(np.unique(np.round(out, 6))) == 3, np.unique(out)


def test_an_empty_band_list_is_the_linear_ramp():
    lam = np.linspace(0, 1, 9)
    assert np.allclose(ramp_bands([])(lam), ramp_linear()(lam))


def test_a_banded_render_has_flat_steps():
    """Cel shading is not a look this library picks — it is a ramp the asset
    hands in. What the renderer must guarantee is that the steps come out
    flat rather than smeared."""
    img = _small(sphere(0.7), color=flat((200, 200, 200)),
                 ramp=ramp_bands([0.35, 0.75]), ao=0.0, rim=0.0, spec=0.0)
    a = np.asarray(img).astype(int)
    lit = a[..., :3].max(axis=-1)[a[..., 3] > 250]
    assert len(np.unique(lit)) <= 4, np.unique(lit)
```

- [ ] **Step 2: Testlerin patladığını gör**

Run: `python3 -m pytest tests/test_sdf3d.py -v -k ramp or band`
Expected: FAIL — `ImportError: cannot import name 'ramp_linear'`

- [ ] **Step 3: Rampaları ve `render`'ın kullanımını yaz**

```python
def ramp_linear(ambient=0.42, diffuse=0.62):
    """The response this renderer has always had: ambient plus a linear
    diffuse term. It is the default so that adding the seam changes nothing."""
    return lambda lam: ambient + diffuse*lam


def ramp_bands(thresholds, ambient=0.42, diffuse=0.62):
    """Cel shading: N-L quantised at the given thresholds.

    The band count, the band widths and the endpoints are the ramp's, not the
    renderer's — that is how the technique is authored in practice, and
    burying a band count in code is precisely what takes it away from whoever
    is directing the look.
    """
    t = np.asarray(sorted(thresholds), float)
    if t.size == 0:
        return ramp_linear(ambient, diffuse)
    def f(lam):
        step = np.searchsorted(t, lam) / float(t.size)
        return ambient + diffuse*step
    return f
```

`render()` imzasına `ramp=None` ekle; `lam` hesaplandıktan sonra:

```python
        shade_t = (ramp or ramp_linear(ambient, diffuse))(lam)
```

ve renk satırında `(ambient + diffuse*lam[:, None])` yerine `shade_t[:, None]` kullan.

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `python3 -m pytest tests/test_sdf3d.py -v`
Expected: PASS — **altın görüntü testi dahil**; varsayılan rampa aynı aritmetik

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/procedural-sprites/scripts/sdf3d.py tests/test_sdf3d.py
git commit -m "feat: put the diffuse response behind a ramp

The default ramp is the arithmetic this renderer already had, so nothing
moves; a banded ramp gives cel shading. Band count and endpoints belong to
the ramp because that is where whoever directs the look can reach them."
```

---

### Task 6: `sdf3d` — sert speküler ve ışık kapısı

**Files:**
- Modify: `.claude/skills/procedural-sprites/scripts/sdf3d.py`
- Modify: `tests/test_sdf3d.py`

**Interfaces:**
- Consumes: Görev 3 (`Material.spec_hard`), Görev 5
- Produces: `material(..., spec_hard=<float|None>)` davranışı

- [ ] **Step 1: Failing testleri yaz**

```python
def test_a_hard_specular_has_a_crisp_edge():
    """A soft highlight fades over many values; a cel one is a flat patch of
    one colour with an anti-aliased boundary. Counting distinct brightnesses
    inside the lit region separates them."""
    soft = surface([(sphere(0.7), material((120, 120, 120), spec=0.9,
                                           shininess=40))])
    hard = surface([(sphere(0.7), material((120, 120, 120), spec=0.9,
                                           shininess=40, spec_hard=0.5))])
    s = np.asarray(_small(sphere(0.7), color=soft, ao=0.0, rim=0.0))
    h = np.asarray(_small(sphere(0.7), color=hard, ao=0.0, rim=0.0))
    inside = (s[..., 3] > 250)
    assert len(np.unique(h[..., 0][inside])) < len(np.unique(s[..., 0][inside]))


def test_a_hard_specular_never_appears_on_the_shadowed_side():
    """The lit gate multiplies inside the pow's base, so an unlit point
    raises zero to a large power and the highlight is gone rather than dim."""
    hard = surface([(sphere(0.7), material((60, 60, 60), spec=1.0,
                                           shininess=40, spec_hard=0.5))])
    a = np.asarray(_small(sphere(0.7), color=hard, ao=0.0, rim=0.0,
                          light=(-0.9, 0.2, 0.3))).astype(int)
    lit_side = a[16, 6, :3].mean()
    dark_side = a[16, 25, :3].mean()
    assert dark_side < lit_side, (dark_side, lit_side)
    assert dark_side < 80, dark_side
```

- [ ] **Step 2: Testlerin patladığını gör**

Run: `python3 -m pytest tests/test_sdf3d.py -v -k hard_specular`
Expected: FAIL — `spec_hard` henüz hiçbir şey yapmıyor

- [ ] **Step 3: Sert speküleri yaz**

`render()` içinde `sp` hesabının yerine:

```python
        ndh = np.clip(nh @ Hv, 0, 1)
        soft_sp = ndh ** shin_a
        # The cel highlight: a very high exponent, then a threshold, so the
        # result is a flat patch with an anti-aliased boundary rather than a
        # falloff. The lit term multiplies INSIDE the base — an unlit point
        # raises zero to a large power, so the highlight is absent in shadow
        # rather than merely dim. The 0.01 width is an anti-aliasing epsilon,
        # not a softness knob.
        lit = np.clip(lam, 0, 1)
        hot = (ndh * lit) ** np.maximum(shin_a * shin_a, 1.0)
        edge = np.clip((hot - hard_a) / 0.01, 0, 1)
        sp = np.where(np.isnan(hard_a), soft_sp, edge)
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `python3 -m pytest tests/test_sdf3d.py -v`
Expected: PASS — altın görüntü testi dahil (`spec_hard` yok, `soft_sp` yolu)

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/procedural-sprites/scripts/sdf3d.py tests/test_sdf3d.py
git commit -m "feat: a hard specular for the cel lane, gated by lit-ness

High exponent then threshold gives the flat highlight patch; multiplying
the lit term inside the pow's base is what keeps it off the shadowed side
entirely rather than leaving a dim ghost there."
```

---

### Task 7: `sdf3d` — temas gölgesi (varsayılan kapalı)

**Files:**
- Modify: `.claude/skills/procedural-sprites/scripts/sdf3d.py`
- Modify: `tests/test_sdf3d.py`

**Interfaces:**
- Consumes: Görev 6
- Produces: `render(..., shadow=False, shadow_k=8.0, shadow_max=0.35, shadow_steps=12)`

- [ ] **Step 1: Failing testleri yaz**

```python
def test_contact_shadow_darkens_what_sits_under_an_overhang():
    """A ball resting on a slab: with the shadow on, the slab right beneath
    the ball has to go darker than the slab far from it."""
    slab = rounded_box((0.8, 0.06, 0.5), 0.03, (0.0, -0.45, 0.0))
    ball = sphere(0.30, (0.0, -0.10, 0.0))
    shape = union(slab, ball)
    kw = dict(color=flat((200, 200, 200)), ao=0.0, rim=0.0, spec=0.0,
              light=(0.0, 1.0, 0.25))
    off = np.asarray(_small(shape, **kw)).astype(int)
    on = np.asarray(_small(shape, shadow=True, **kw)).astype(int)
    row = 26                       # on the slab, below the ball
    under = on[row, 16, :3].mean()
    away = on[row, 2, :3].mean()
    assert under < away - 10, (under, away)
    assert under < off[row, 16, :3].mean() - 10


def test_the_shadow_costs_nothing_when_it_is_off():
    """Off must mean the second march never runs, not that it runs and is
    discarded — the renderer already takes minutes at full size."""
    kw = dict(color=flat((200, 200, 200)), ao=0.0, rim=0.0)
    a = np.asarray(_small(sphere(0.7), **kw))
    b = np.asarray(_small(sphere(0.7), shadow=False, **kw))
    assert np.array_equal(a, b)
```

`rounded_box`'ı dosyanın import satırına ekle.

- [ ] **Step 2: Testlerin patladığını gör**

Run: `python3 -m pytest tests/test_sdf3d.py -v -k contact_shadow or shadow_costs`
Expected: FAIL — `render() got an unexpected keyword argument 'shadow'`

- [ ] **Step 3: Gölgeyi yaz**

```python
def _contact_shadow(sdf, p, L, k, tmax, steps):
    """Quilez's single-march soft shadow, cut short.

    Range is deliberately small: what a sprite needs is the darkening where
    parts touch — a brow over an eye socket, a horn root against a skull —
    not a shadow thrown across the scene. It is a SECOND march per lit pixel,
    which is why it is off by default.

    Known failure: on sharply cornered casters the stepping quantises and
    bands. The published fix (Aaltonen, GDC 2018) triangulates the closest
    approach; it is not implemented here because nothing in this project has
    hit the banding yet.
    """
    res = np.ones(p.shape[0])
    t = np.full(p.shape[0], 0.02)
    for _ in range(steps):
        h = sdf(p + L*t[:, None])
        res = np.minimum(res, k*h/np.maximum(t, 1e-6))
        t += np.clip(h, 0.01, 0.1)
        if (t > tmax).all():
            break
    return np.clip(res, 0.0, 1.0)
```

`render()` imzasına `shadow=False, shadow_k=8.0, shadow_max=0.35, shadow_steps=12` ekle; `aoterm` hesabından sonra:

```python
        if shadow:
            aoterm = aoterm * _contact_shadow(sdf, ph + nh*0.01, L, shadow_k,
                                              shadow_max, shadow_steps)
```

- [ ] **Step 4: Testlerin geçtiğini gör ve süreyi ölç**

Run: `python3 -m pytest tests/test_sdf3d.py -v`
Expected: PASS

Sonra ölç ve raporuna yaz:

```bash
python3 - <<'PY'
import sys, time
sys.path.insert(0, ".claude/skills/procedural-sprites/scripts")
import sdf3d
from sdf3d import sphere, render, flat, rounded_box, union
sdf3d.OVERSAMPLE = 2
shape = union(rounded_box((0.8, 0.06, 0.5), 0.03, (0.0, -0.45, 0.0)),
              sphere(0.30, (0.0, -0.10, 0.0)))
for on in (False, True):
    t0 = time.time()
    render(shape, size=(192, 192), color=flat((200, 200, 200)), shadow=on)
    print("shadow", on, round(time.time() - t0, 2), "s")
PY
```

Varsayılanı **değiştirme** — ölçümü raporla, karar ölçüme bakan insanın.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/procedural-sprites/scripts/sdf3d.py tests/test_sdf3d.py
git commit -m "feat: an optional contact shadow, off by default

What a sprite needs is the darkening where parts touch, not a shadow across
a scene, so the march is short. It is a second march per lit pixel and this
renderer already takes minutes at full size — the default stays off until
someone has looked at the measurement."
```

---

### Task 8: `sdf3d` — derinlik ve normal tamponlarından iç kontur

**Files:**
- Modify: `.claude/skills/procedural-sprites/scripts/sdf3d.py`
- Modify: `tests/test_sdf3d.py`

**Interfaces:**
- Consumes: Görev 7
- Produces: `render(..., buffers=False)` — `True` iken `(img, depth, normal)` döner; `depth` `(H, W)` float, isabetsiz pikseller `np.inf`; `normal` `(H, W, 3)` float. `sdf3d.interior_edges(depth, normal, depth_eps=0.02, normal_eps=0.25) -> PIL 'L'`

- [ ] **Step 1: Failing testleri yaz**

```python
from sdf3d import interior_edges


def test_buffers_come_back_at_the_final_size():
    img, depth, normal = _small(sphere(0.7), color=flat((200, 200, 200)),
                                buffers=True)
    assert img.size == (32, 32)
    assert depth.shape == (32, 32)
    assert normal.shape == (32, 32, 3)
    assert np.isinf(depth[0, 0])           # a corner ray misses


def test_an_interior_edge_appears_where_two_parts_cross():
    """The alpha contour can only draw the outside. Where an arm crosses a
    body — or a horn crosses a skull — the line has to come from the depth
    and normal buffers, which the renderer already computes and used to
    throw away."""
    front = sphere(0.34, (-0.12, 0.0, 0.45))
    back = sphere(0.46, (0.14, 0.0, -0.2))
    _, depth, normal = _small(union(front, back),
                              color=flat((200, 200, 200)), buffers=True)
    edges = np.asarray(interior_edges(depth, normal))
    assert edges.max() == 255
    # the line is inside the silhouette, not on its rim
    inner = edges[6:26, 6:26]
    assert inner.max() == 255, inner.max()
```

- [ ] **Step 2: Testlerin patladığını gör**

Run: `python3 -m pytest tests/test_sdf3d.py -v -k buffers or interior_edge`
Expected: FAIL — `render() got an unexpected keyword argument 'buffers'`

- [ ] **Step 3: Tamponları döndür ve kenarı çıkar**

`render()` imzasına `buffers=False` ekle. Downsample'dan **önce** tamponları son boyuta indir:

```python
    if buffers:
        d2 = np.where(hit, t, np.inf).reshape(h, w)
        n2 = n.reshape(h, w, 3)
        if OVERSAMPLE > 1:
            d2 = d2[::OVERSAMPLE, ::OVERSAMPLE]
            n2 = n2[::OVERSAMPLE, ::OVERSAMPLE]
        return out, d2, n2
    return out
```

`bg_alpha` yolu da aynı üçlüyü döndürmeli — iki dönüş noktası varsa ikisini de güncelle.

```python
def interior_edges(depth, normal, depth_eps=0.02, normal_eps=0.25):
    """Lines where depth or normal jumps between neighbouring pixels.

    This is how the technique is done in practice, and it gives the one thing
    an alpha contour cannot: the line INSIDE the silhouette, where one part
    crosses another. Both buffers are needed — two parts at the same depth
    still differ in normal, and a smooth fold differs in depth but not much
    in normal.
    """
    d = np.where(np.isinf(depth), np.nanmax(depth[~np.isinf(depth)]) + 1.0,
                 depth)
    edge = np.zeros(d.shape, bool)
    for axis in (0, 1):
        dd = np.abs(np.diff(d, axis=axis, prepend=d.take([0], axis=axis)))
        nn = np.linalg.norm(
            np.diff(normal, axis=axis,
                    prepend=normal.take([0], axis=axis)), axis=-1)
        edge |= (dd > depth_eps) | (nn > normal_eps)
    inside = ~np.isinf(depth)
    return Image.fromarray((edge & inside).astype(np.uint8) * 255, "L")
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `python3 -m pytest tests/test_sdf3d.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/procedural-sprites/scripts/sdf3d.py tests/test_sdf3d.py
git commit -m "feat: interior lines from the depth and normal buffers

The renderer computed both and threw them away. An alpha contour can only
draw the outside, which is why a head and the plinth under it had no line
between them."
```

---

### Task 9: `sprite_lib` — sabit genişlikte kontur

**Files:**
- Modify: `.claude/skills/procedural-sprites/scripts/sprite_lib.py`
- Create: `tests/test_sprite_lib.py`

**Interfaces:**
- Consumes: yok
- Produces: `sprite_lib.contour(img, width=2, color=(26,26,46), threshold=110, ss=3) -> PIL RGBA`

- [ ] **Step 1: Failing testleri yaz**

`tests/test_sprite_lib.py`:

```python
"""2D delivery helpers: the contour every set wears, and the readability
measurements that decide whether a sprite ships."""
import numpy as np
from PIL import Image

from sprite_lib import contour


def _disc(size=64, r=20):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    a = np.zeros((size, size), np.uint8)
    yy, xx = np.mgrid[0:size, 0:size]
    a[(xx - size//2)**2 + (yy - size//2)**2 <= r*r] = 255
    rgb = np.zeros((size, size, 3), np.uint8)
    rgb[a > 0] = (220, 90, 60)
    return Image.fromarray(np.dstack([rgb, a]), "RGBA")


def test_the_contour_is_the_same_width_all_the_way_round():
    out = np.asarray(contour(_disc(), width=3, color=(20, 20, 40)))
    ink = (out[..., :3].sum(axis=-1) < 200) & (out[..., 3] > 128)
    widths = []
    for row in (32,):
        on = np.where(ink[row])[0]
        left = on[on < 32]
        right = on[on > 32]
        widths += [left.max() - left.min() + 1, right.max() - right.min() + 1]
    for col in (32,):
        on = np.where(ink[:, col])[0]
        top = on[on < 32]
        bot = on[on > 32]
        widths += [top.max() - top.min() + 1, bot.max() - bot.min() + 1]
    assert max(widths) - min(widths) <= 1, widths


def test_the_subject_survives_under_the_contour():
    out = np.asarray(contour(_disc(), width=3, color=(20, 20, 40)))
    assert tuple(out[32, 32, :3]) == (220, 90, 60)
```

- [ ] **Step 2: Testlerin patladığını gör**

Run: `python3 -m pytest tests/test_sprite_lib.py -v`
Expected: FAIL — `ImportError: cannot import name 'contour'`

- [ ] **Step 3: `contour`'u yaz**

`sprite_lib.py`'nin çıktı bölümüne ekle (`ImageChops`'u import et):

```python
def contour(img, width=2, color=(26, 26, 46), threshold=110, ss=3):
    """The set's dark outline, at one width the whole way round.

    The alpha is HARD-THRESHOLDED before it is grown. Dilating an
    anti-aliased alpha instead makes the line's width follow how soft the
    edge happens to be, which is why one asset's horn tips came out blurred
    while its flat sides came out crisp.
    """
    big = img.resize((img.width*ss, img.height*ss), Image.LANCZOS)
    a = big.getchannel("A").point(lambda v: 255 if v > threshold else 0)
    grown = a.filter(ImageFilter.MaxFilter(width*2 + 1))
    ring = ImageChops.subtract(grown, a)
    layer = Image.new("RGBA", big.size, tuple(color) + (0,))
    layer.putalpha(ring)
    out = Image.new("RGBA", big.size, (0, 0, 0, 0))
    out.alpha_composite(layer)
    out.alpha_composite(big)
    return out.resize(img.size, Image.LANCZOS)
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `python3 -m pytest tests/test_sprite_lib.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/procedural-sprites/scripts/sprite_lib.py tests/test_sprite_lib.py
git commit -m "feat: one contour helper, at one width the whole way round

Both character scripts reached into a set-local draw.py for this and called
it differently. Hard-thresholding the alpha before growing it is what keeps
the width from following how soft each edge happens to be."
```

---

### Task 10: `sprite_lib` — okunurluk

**Files:**
- Modify: `.claude/skills/procedural-sprites/scripts/sprite_lib.py`
- Modify: `tests/test_sprite_lib.py`

**Interfaces:**
- Consumes: mevcut `contact_sheet`
- Produces: `readability(img, size=(44,52)) -> dict(dark, pale, coverage)`, `silhouette(img, color=(0,0,0)) -> PIL RGBA`, `qc_strip(img, sizes, path, bg) -> PIL`

- [ ] **Step 1: Failing testleri yaz**

```python
from sprite_lib import qc_strip, readability, silhouette


def test_readability_counts_dark_and_pale_pixels_at_game_size():
    img = _disc(size=256, r=90)
    r = readability(img, size=(44, 52))
    assert r["pale"] == 0                  # the disc is mid-toned
    assert 0.0 < r["coverage"] < 1.0


def test_silhouette_keeps_the_shape_and_drops_the_colour():
    s = np.asarray(silhouette(_disc()))
    assert tuple(s[32, 32, :3]) == (0, 0, 0)
    assert s[32, 32, 3] == 255
    assert s[0, 0, 3] == 0


def test_qc_strip_writes_a_sheet(tmp_path=None):
    import tempfile
    from pathlib import Path
    out = Path(tempfile.mkdtemp()) / "qc.png"
    qc_strip(_disc(), [(44, 52), (88, 104)], out, bg=(56, 54, 92, 255))
    assert out.exists()
    assert Image.open(out).width > 44
```

- [ ] **Step 2: Testlerin patladığını gör**

Run: `python3 -m pytest tests/test_sprite_lib.py -v -k readability or silhouette or qc_strip`
Expected: FAIL — `ImportError: cannot import name 'readability'`

- [ ] **Step 3: Üçünü yaz**

```python
def readability(img, size=(44, 52)):
    """What survives the shrink to on-screen size, as numbers.

    This measures and reports; it does not decide. Which counts are enough is
    the asset's own acceptance criterion and belongs in the asset's script —
    one obstacle needs its brow bar to survive, a UI pill needs nothing of
    the sort.
    """
    small = np.asarray(img.resize(size, Image.LANCZOS))
    rgb = small[..., :3].astype(int)
    on = small[..., 3].astype(int) > 100
    return dict(dark=int(((rgb.max(axis=-1) < 90) & on).sum()),
                pale=int(((rgb.min(axis=-1) > 170) & on).sum()),
                coverage=round(float(on.mean()), 3))


def silhouette(img, color=(0, 0, 0)):
    """The sprite filled flat, for the oldest readability test there is: look
    at the shape alone and see whether it still says what the thing is."""
    out = Image.new("RGBA", img.size, tuple(color) + (0,))
    out.putalpha(img.getchannel("A"))
    return out


def qc_strip(img, sizes, path, bg=(128, 128, 128, 255)):
    """The sprite at the sizes the game actually draws it, on the game's own
    backdrop colour. A sprite that does not read here does not ship, however
    good it looks at 1024."""
    return contact_sheet([(img.resize(s, Image.LANCZOS), None) for s in sizes],
                         path, bg=bg)
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `python3 -m pytest tests/test_sprite_lib.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/procedural-sprites/scripts/sprite_lib.py tests/test_sprite_lib.py
git commit -m "feat: measure readability, and draw the silhouette to look at

One asset hand-rolled the shrink-and-count check and every other asset did
without. The numbers move to the library; which numbers are enough stays
with the asset, because that is a property of the asset and not of the tool."
```

---

### Task 11: `character_lib` — geometri olan göz

**Files:**
- Create: `.claude/skills/procedural-sprites/scripts/character_lib.py`
- Create: `tests/test_character_lib.py`

**Interfaces:**
- Consumes: `sdf3d.sphere`, `sdf3d.material`, `sdf3d.surface`, `sdf3d.union`, `sdf3d.smooth_union`
- Produces: `character_lib.Eye` — `socket` (SDF, malzemesiz), `parts` (`[(sdf, Material), ...]`), `decals` (`[(dir3, radius_deg, soft_deg, rgb), ...]`); `character_lib.eye(center, look, r=0.09, iris=0.045, pupil=0.022, glint=0.018, sclera=(250,250,255), iris_color=(60,40,30), pupil_color=(20,18,28)) -> Eye`

- [ ] **Step 1: Failing testleri yaz**

`tests/test_character_lib.py`:

```python
"""Character helpers. Small renders only — these pin construction, not looks."""
import numpy as np

import sdf3d
from sdf3d import flat, material, render, sphere, smooth_union, surface, union

from character_lib import eye


def _small(sdf, **kw):
    before = sdf3d.OVERSAMPLE
    sdf3d.OVERSAMPLE = 1
    try:
        return render(sdf, size=(48, 48), tilt=0, **kw)
    finally:
        sdf3d.OVERSAMPLE = before


def test_an_eye_shows_sclera_iris_and_pupil_as_three_colours():
    """A single dark shape is what the old face decals gave, and it reads as
    part of the brow rather than as an eye. Three tones are the difference."""
    head = sphere(0.62)
    e = eye((0.0, 0.05, 0.60), (0.0, 0.05, 1.0), r=0.22, iris=0.11,
            pupil=0.055)
    shape = union(smooth_union(0.05, head, e.socket),
                  *[s for s, _ in e.parts])
    surf = surface([(head, material((190, 120, 90)))] + e.parts)
    a = np.asarray(_small(shape, color=surf, ao=0.0, rim=0.0, spec=0.0))
    inside = a[..., 3] > 250
    tones = np.unique(a[..., :3][inside].sum(axis=-1) // 40)
    assert len(tones) >= 3, tones


def test_the_socket_carries_no_material_of_its_own():
    """It is smooth-unioned into the head, so it sits inside the blend band
    where a nearest-part material select is simply wrong. It shares the
    head's material by having none."""
    e = eye((0.0, 0.0, 0.6), (0.0, 0.0, 1.0))
    ids = [s for s, _ in e.parts]
    assert e.socket not in ids


def test_a_glint_is_a_decal_not_geometry():
    e = eye((0.0, 0.0, 0.6), (0.0, 0.0, 1.0))
    assert len(e.decals) == 1
    assert len(e.parts) == 3            # sclera, iris, pupil


def test_zeroed_parameters_give_a_plain_dot_eye():
    """The library must not insist on a cartoon eye — a dot is a legitimate
    style and comes from the same call."""
    e = eye((0.0, 0.0, 0.6), (0.0, 0.0, 1.0), iris=0.0, glint=0.0)
    assert len(e.parts) == 2            # sclera and pupil only
    assert e.decals == []
```

- [ ] **Step 2: Testlerin patladığını gör**

Run: `python3 -m pytest tests/test_character_lib.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'character_lib'`

- [ ] **Step 3: `character_lib.py`'yi ve `eye`'ı yaz**

```python
"""character_lib - the parts of a character a raymarched sprite needs and the
renderer has no opinion about: eyes built as geometry, decals along a curve,
a light that turns with the camera, and a turnaround.

It gives no anatomy. Body plans, proportions and stance are the asset's, and
a library that shipped them would make every character come out of the same
mould.
"""
import math

import numpy as np

from sdf3d import material, sphere


class Eye:
    """socket: smooth-unioned into the head, carrying NO material of its own.
    parts:  hard-unioned, each with its own material.
    decals: passed to spots() alongside the rest of the face.

    The split is the whole point. A nearest-part material select is exact for
    a hard union and wrong inside a smooth_union's blend band, so the piece
    that blends must share the head's material, and the pieces that need
    their own colour must not blend.
    """
    __slots__ = ("socket", "parts", "decals")

    def __init__(self, socket, parts, decals):
        self.socket = socket
        self.parts = parts
        self.decals = decals


def eye(center, look, r=0.09, iris=0.045, pupil=0.022, glint=0.018,
        sclera=(250, 250, 255), iris_color=(60, 40, 30),
        pupil_color=(20, 18, 28), glint_color=(255, 255, 255)):
    """An eye as geometry: a socket bulge, a white, an iris, a pupil, a glint.

    Flat dark shapes stuck on a face read as part of the brow above them —
    the whites are what make a character look back at you. Setting iris to 0
    drops it and gives a plain dot eye, so this does not force a style.
    """
    c = np.array(center, float)
    d = np.array(look, float)
    d = d / (np.linalg.norm(d) + 1e-9)

    socket = sphere(r, tuple(c))
    parts = [(sphere(r*0.92, tuple(c + d*0.02)), material(sclera, spec=0.35,
                                                          shininess=60))]
    if iris > 0:
        parts.append((sphere(iris, tuple(c + d*(r*0.80))),
                      material(iris_color, spec=0.30, shininess=50)))
    parts.append((sphere(max(pupil, 1e-4), tuple(c + d*(r*0.88))),
                  material(pupil_color, spec=0.20, shininess=40)))

    decals = []
    if glint > 0:
        off = np.array([-0.35, 0.35, 0.0])
        gd = d + off
        decals.append((tuple(gd / (np.linalg.norm(gd) + 1e-9)),
                       math.degrees(glint*8), 0.7, glint_color))
    return Eye(socket, parts, decals)
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `python3 -m pytest tests/test_character_lib.py -v`
Expected: PASS (4 test)

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/procedural-sprites/scripts/character_lib.py tests/test_character_lib.py
git commit -m "feat: an eye built as geometry, with a white to look back with

Flat dark shapes on a face read as part of the brow. The socket blends into
the head and carries no material; the sclera, iris and pupil hard-union so
they keep their own."
```

---

### Task 12: `character_lib` — decal araçları

**Files:**
- Modify: `.claude/skills/procedural-sprites/scripts/character_lib.py`
- Modify: `tests/test_character_lib.py`

**Interfaces:**
- Consumes: Görev 11
- Produces: `character_lib.stroke(points, radius_deg=2.3, soft_deg=0.9, color=(0,0,0), samples=16) -> [decal, ...]`; `character_lib.mirrored(fn) -> fn`; `character_lib.mirror_decals(decals) -> [decal, ...]`

- [ ] **Step 1: Failing testleri yaz**

```python
from character_lib import mirror_decals, mirrored, stroke


def test_a_stroke_samples_the_curve_into_decals():
    """A mouth used to be twenty hand-written decal tuples in the asset."""
    pts = [(0.0, -0.2, 1.0), (0.2, -0.4, 1.0), (0.4, -0.2, 1.0)]
    out = stroke(pts, samples=12)
    assert len(out) == 12
    assert all(len(d) == 4 for d in out)
    first = np.array(out[0][0])
    assert abs(np.linalg.norm(first) - 1.0) < 1e-6   # directions are unit


def test_mirrored_evaluates_at_the_absolute_x():
    f = mirrored(sphere(0.2, (0.5, 0.0, 0.0)))
    p = np.array([[0.5, 0.0, 0.0], [-0.5, 0.0, 0.0]])
    d = f(p)
    assert abs(d[0] - d[1]) < 1e-9


def test_mirror_decals_flips_x_and_keeps_the_rest():
    src = [((0.3, 0.1, 0.9), 8.0, 1.0, (10, 20, 30))]
    out = mirror_decals(src)
    assert out[0][0][0] == -0.3
    assert out[0][1:] == src[0][1:]
```

- [ ] **Step 2: Testlerin patladığını gör**

Run: `python3 -m pytest tests/test_character_lib.py -v -k stroke or mirror`
Expected: FAIL — `ImportError: cannot import name 'stroke'`

- [ ] **Step 3: Üçünü yaz**

```python
def stroke(points, radius_deg=2.3, soft_deg=0.9, color=(0, 0, 0), samples=16):
    """A line of decals along a curve through `points`.

    Piecewise-linear resampling on purpose: a caller that wants a bezier
    passes its own sampled points, and this stays the one thing it says it
    is. Directions are normalised because spots() measures the angle from the
    decal's direction to the surface point.
    """
    pts = np.array(points, float)
    if len(pts) < 2:
        raise ValueError("stroke needs at least two points")
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    want = np.linspace(0.0, cum[-1], samples)
    out = []
    for w in want:
        i = int(np.clip(np.searchsorted(cum, w) - 1, 0, len(seg) - 1))
        t = 0.0 if seg[i] == 0 else (w - cum[i]) / seg[i]
        p = pts[i] + (pts[i+1] - pts[i])*t
        out.append((tuple(p / (np.linalg.norm(p) + 1e-9)), radius_deg,
                    soft_deg, color))
    return out


def mirrored(fn):
    """Evaluate an SDF at |x|, so one definition gives both sides.

    A helper, never a rule: one character's ears sit at deliberately
    different depths so that the side view shows two of them instead of one
    perfectly overlapping spike. Symmetry is a choice the asset makes.
    """
    def f(p):
        q = np.stack([np.abs(p[..., 0]), p[..., 1], p[..., 2]], axis=-1)
        return fn(q)
    return f


def mirror_decals(decals):
    """The same decals on the other side of x."""
    return [((-d[0][0], d[0][1], d[0][2]),) + tuple(d[1:]) for d in decals]
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `python3 -m pytest tests/test_character_lib.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/procedural-sprites/scripts/character_lib.py tests/test_character_lib.py
git commit -m "feat: strokes and mirroring for face decals

A mouth was twenty hand-written decal tuples in the asset that needed one.
Mirroring is offered, not imposed: a character whose ears sit at different
depths on purpose still needs to say so."
```

---

### Task 13: `character_lib` — ışık ve turnaround

**Files:**
- Modify: `.claude/skills/procedural-sprites/scripts/character_lib.py`
- Modify: `tests/test_character_lib.py`

**Interfaces:**
- Consumes: Görev 12, `sdf3d.render`
- Produces: `character_lib.light_for(yaw, base_light) -> (lx, ly, lz)`; `character_lib.VIEWS = {'front': 0, 'three_quarter': 38, 'side': 82, 'back': 180}`; `character_lib.turnaround(shape, views=VIEWS, light=None, **render_kw) -> dict[str, PIL]`

- [ ] **Step 1: Failing testleri yaz**

```python
from character_lib import VIEWS, light_for, turnaround


def test_the_light_turns_with_the_camera():
    """A world-fixed light is physically right and useless here: at yaw 180
    it falls entirely behind the object and the back view comes out flat
    ambient mush."""
    base = (-0.35, 0.75, 0.55)
    assert light_for(0, base) == base
    turned = light_for(180, base)
    assert abs(turned[0] + base[0]) < 1e-9
    assert abs(turned[1] - base[1]) < 1e-9


def test_a_turnaround_renders_every_named_view():
    out = turnaround(sphere(0.6), views={"front": 0, "side": 82},
                     size=(24, 24), color=flat((200, 160, 40)), ao=0.0)
    assert set(out) == {"front", "side"}
    assert all(im.size == (24, 24) for im in out.values())


def test_every_view_is_lit_from_the_same_side_of_the_character():
    """The measurable version of the rule: the lit half stays the lit half."""
    out = turnaround(sphere(0.6), views=VIEWS, size=(32, 32),
                     color=flat((200, 200, 200)), ao=0.0, rim=0.0, spec=0.0)
    for name, im in out.items():
        a = np.asarray(im)[..., :3].astype(int).sum(axis=-1)
        left = a[:, :16].max()
        right = a[:, 16:].max()
        assert left > right, (name, left, right)
```

`turnaround` içinde `OVERSAMPLE`'ı testin ayarlaması gerekiyorsa `_small` kalıbını kullan; `turnaround` `sdf3d.OVERSAMPLE`'a dokunmaz.

- [ ] **Step 2: Testlerin patladığını gör**

Run: `python3 -m pytest tests/test_character_lib.py -v -k light or turnaround or view`
Expected: FAIL — `ImportError: cannot import name 'light_for'`

- [ ] **Step 3: İkisini yaz**

```python
from sdf3d import LIGHT, render

VIEWS = {"front": 0, "three_quarter": 38, "side": 82, "back": 180}


def light_for(yaw, base_light=LIGHT):
    """Turn the light with the camera so it stays on the character's upper
    left in every view.

    A world-fixed light is physically right and useless here: at yaw 180 it
    falls entirely behind the object and the back view comes out flat ambient
    mush. Every other asset in a set is lit from the upper left, so this is
    what keeps a turnaround matching them.
    """
    a = math.radians(yaw)
    c, s = math.cos(a), math.sin(a)
    lx, ly, lz = base_light
    return (c*lx + s*lz, ly, -s*lx + c*lz)


def turnaround(shape, views=VIEWS, light=None, **render_kw):
    """One shape, every named view, each lit to match the others.

    Consistency across views is by construction: it is the same object at a
    different camera yaw, not the same character drawn again.
    """
    base = light if light is not None else LIGHT
    return {name: render(shape, yaw=yaw, light=light_for(yaw, base),
                         **render_kw)
            for name, yaw in views.items()}
```

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `python3 -m pytest tests/test_character_lib.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/procedural-sprites/scripts/character_lib.py tests/test_character_lib.py
git commit -m "feat: a turnaround whose light turns with the camera

Every character script rediscovered this. A world-fixed light puts the back
view entirely in shadow, so the one view that most needs to match the set
is the one that matches it least."
```

---

### Task 14: Demo karakter — kütüphanenin kendi QC'si

**Files:**
- Create: `.claude/skills/procedural-sprites/scripts/demo_character.py`
- Modify: `tests/test_character_lib.py`

**Interfaces:**
- Consumes: Görev 11-13, `sprite_lib.contour`, `sprite_lib.qc_strip`
- Produces: `demo_character.build(expression) -> (shape, surface, decals)`; `demo_character.FACE`, `demo_character.ANGRY`; `demo_character.main()` dört view × iki ifade yazar

- [ ] **Step 1: Failing testi yaz**

```python
import demo_character


def test_an_expression_is_a_dict_the_asset_merges():
    """No rig and no class hierarchy: the library takes numbers, and an
    expression is the dict of numbers you hand it."""
    assert demo_character.ANGRY["brow"] != demo_character.FACE["brow"]
    assert set(demo_character.ANGRY) == set(demo_character.FACE)


def test_the_two_expressions_render_differently():
    calm = demo_character.render_one(demo_character.FACE, yaw=0, size=(32, 32))
    angry = demo_character.render_one(demo_character.ANGRY, yaw=0,
                                      size=(32, 32))
    assert not np.array_equal(np.asarray(calm), np.asarray(angry))
```

- [ ] **Step 2: Testin patladığını gör**

Run: `python3 -m pytest tests/test_character_lib.py -v -k expression`
Expected: FAIL — `ModuleNotFoundError: No module named 'demo_character'`

- [ ] **Step 3: Demo'yu yaz**

```python
"""demo_character - the library's own QC, not a style to copy.

It exists so that every piece of character_lib is exercised end to end by
something that renders: an eye built as geometry, a mouth from a stroke, a
turnaround whose light follows the camera, and an expression that is nothing
but a dict of numbers merged over another dict of numbers.

The shape is deliberately plain. A demo that looked designed would become
the thing everybody copies, and this library gives technique, not style.
"""
import sys

import numpy as np

import sdf3d
from sdf3d import flat, material, render, smooth_union, sphere, surface, union
from sprite_lib import contour, qc_strip

from character_lib import VIEWS, eye, mirror_decals, stroke, turnaround

FACE = dict(eye_open=1.0, pupil_x=0.0, mouth=0.16, brow=-4.0)
ANGRY = FACE | dict(brow=16.0, eye_open=0.7, mouth=-0.22)

BODY = (200, 120, 90)
INK = (26, 26, 46)


def build(expr):
    """Returns (shape, surface, decals) for one expression."""
    head = sphere(0.62)
    r = 0.17 * expr["eye_open"]
    look = (expr["pupil_x"], 0.05, 1.0)
    left = eye((-0.24, 0.10, 0.52), look, r=r, iris=r*0.5, pupil=r*0.25)
    right = eye((0.24, 0.10, 0.52), look, r=r, iris=r*0.5, pupil=r*0.25)

    shape = union(smooth_union(0.06, head, left.socket, right.socket),
                  *[s for s, _ in left.parts + right.parts])
    surf = surface([(head, material(BODY, spec=0.25, shininess=22))]
                   + left.parts + right.parts)

    mouth = stroke([(-0.22, -0.30 + expr["mouth"], 0.9),
                    (0.0, -0.34, 0.9),
                    (0.22, -0.30 + expr["mouth"], 0.9)],
                   radius_deg=3.0, color=INK, samples=14)
    brow = stroke([(-0.34, 0.34, 0.85),
                   (-0.14, 0.34 + expr["brow"]/100.0, 0.9)],
                  radius_deg=3.4, color=INK, samples=8)
    decals = mouth + brow + mirror_decals(brow) + left.decals + right.decals
    return shape, surf, decals


HEAD_CENTRE = (0.0, 0.10, 0.0)      # every decal aims at this


def _painted(expr):
    """The body's materials with the face decals over them."""
    from sdf3d import spots
    shape, surf, decals = build(expr)
    return shape, spots(surf, decals, center=HEAD_CENTRE)


def render_one(expr, yaw=0, size=(320, 320)):
    shape, painted = _painted(expr)
    img = render(shape, size=size, tilt=12, yaw=yaw, color=painted,
                 light=light_for(yaw), ao=0.5, rim=0.06)
    return contour(img, width=2, color=INK)


def main():
    for label, expr in (("calm", FACE), ("angry", ANGRY)):
        shape, painted = _painted(expr)
        views = turnaround(shape, views=VIEWS, size=(320, 320), tilt=12,
                           color=painted, ao=0.5, rim=0.06)
        for name, img in views.items():
            out = contour(img, width=2, color=INK)
            out.save(f"demo_{label}_{name}.png")
            print("wrote", f"demo_{label}_{name}.png")
        qc_strip(contour(views["front"], width=2, color=INK),
                 [(48, 48), (96, 96)], f"demo_{label}_qc.png",
                 bg=(56, 54, 92, 255))


if __name__ == "__main__":
    sys.exit(main())
```

`light_for`'u import listesine ekle. `spots(surf, ...)` Görev 3'te eklenen
`Surface.__call__` sayesinde çalışır: decal'ler malzemeli gövdenin üstüne
biner.

- [ ] **Step 4: Testlerin geçtiğini gör ve demoyu bir kez çalıştır**

Run: `python3 -m pytest tests/test_character_lib.py -v`
Expected: PASS

Run: `cd /tmp && python3 /path/to/.claude/skills/procedural-sprites/scripts/demo_character.py`
Expected: sekiz PNG + iki QC şeridi. **Bunlara bak** — göz beyazı görünüyor mu, ağız iki ifadede farklı mı, dört view aynı karakter mi.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/procedural-sprites/scripts/demo_character.py tests/test_character_lib.py
git commit -m "test: a demo character that exercises the whole library

Deliberately plain: a demo that looked designed would become the thing
everybody copies, and this library gives technique, not style. An
expression is a dict merged over another dict — no rig, no hierarchy."
```

---

### Task 15: Belgeler

**Files:**
- Modify: `.claude/skills/procedural-sprites/SKILL.md`
- Modify: `README.md`

- [ ] **Step 1: `SKILL.md`'nin `## Setup` bölümünü güncelle**

Kopyalanacak dosya listesi üçe çıkar: `sprite_lib.py`, `sdf3d.py`, `character_lib.py`.

- [ ] **Step 2: Malzeme kuralını yaz**

`## Soft-3D volumes` bölümüne, `part_color`'dan bahseden her cümleyi `surface()`/`material()` ile değiştirerek:

```markdown
Materials carry a part's colour AND its surface — `material(colour, spec=,
shininess=, rim=, spec_hard=)`, collected with `surface([(sdf, material), ...])`.
One rule governs how you build the shape underneath them: **blend softly only
within one material, and hard-union anything that needs its own.** The material
at a surface point is the nearest part's, which is exact for a hard union and
wrong inside a `smooth_union`'s blend band, where the surface belongs to
neither part.

`spec_hard=<0..1>` turns the highlight into the flat, hard-edged patch a cel
look wants; leaving it out keeps the continuous falloff. Banded diffuse is a
ramp you hand in: `ramp_bands([0.35, 0.75])` against the default
`ramp_linear()`.
```

- [ ] **Step 3: Karakter merdivenini güncelle**

Lane 2'deki "ölçülmüş tavan" notunu, artık kütüphanede çözülü olanları ayırarak yeniden yaz:

```markdown
   Four of the things that used to have to be checked by hand are now the
   library's: an eye is `eye()` and comes with a white, an iris and a pupil;
   `surface()` gives hide, bone and metal their own gloss instead of one
   plastic sheen; the five-tap AO darkens a join so parts read as joined;
   and `contour()` holds one width the whole way round. What is still yours
   to get right is everything the library has no opinion about — proportion,
   where the muzzle sits, whether the plinth is smaller than the head, and
   whether the silhouette says what the thing is when you fill it black
   (`silhouette()` draws it; you decide).

   A brow that should shade the eye under it has to be GEOMETRY. A flat decal
   brow cannot cast anything, and `shadow=True` is what makes the contact
   darkening appear once it is.
```

- [ ] **Step 4: Şeridin sınırını yaz**

`## When code wins, and when it loses` bölümüne:

```markdown
Hair, cloth folds and painted faces are not in this lane and will not be:
they need strands, simulation and texture, none of which an analytic SDF
gives. Say so plainly rather than shipping a plastic approximation — the
brief's prompt section exists for exactly these.
```

Aynı sınır `README.md`'nin `procedural-sprites` satırının altına bir cümle olarak girer.

- [ ] **Step 5: Doğrula ve commit**

Run: `grep -n "part_color" .claude/skills/procedural-sprites/SKILL.md README.md`
Expected: çıktı yok

```bash
git add .claude/skills/procedural-sprites/SKILL.md README.md
git commit -m "docs: record what the library now owns and what it never will

Four of the character ladder's hand-checked items became library calls; the
rest stayed art direction and now says so. Hair, cloth and painted faces are
named as out of this lane for good, not deferred."
```

---

## Self-Review

**Spec kapsam kontrolü:**

| spec bölümü | task |
|---|---|
| 1. Taşıyıcı kural | 3 (kod), 11 (Eye'ın ayrımı), 15 (belge) |
| 2.1 Malzeme | 3 |
| 2.2 Difüz rampa | 5 |
| 2.3 Sert speküler | 6 |
| 2.4 AO | 4 |
| 2.5 Temas gölgesi | 7 |
| 2.6 İç kontur | 8 |
| 2.7 Kütüphanenin borcu | 2 |
| 3.1 Göz | 11 |
| 3.2 Decal araçları | 12 |
| 3.3 Işık ve turnaround | 13 |
| 3.4 İfade | 14 |
| 4.1 Kontur | 9 |
| 4.2 Okunurluk | 10 |
| 5. Doğrulama ve testler | 1 (iskele + altın), 14 (demo) |
| 6. Hata ve kenar durumları | 5 (boş bant listesi), 7 (kapalı = sıfır maliyet), 11 (gömülü göz) |
| 7. Belge borcu | 15 |
| Kabul kriterleri 1-6 | 1 (altın), 3 (speküler farkı), 7 (süre ölçümü), 1+15 (suite süresi), 14 (demo), tümü (her fonksiyonun testi) |

**Spec ile çelişen bir nokta, bilerek çözüldü:** spec'in 1. kabul kriteri "tek malzemeli, `ramp_linear` kullanan bir sahne altın görüntüyle piksel piksel aynı" diyor, ama aynı spec AO'yu da değiştiriyor — AO açıkken bu iki şart aynı anda sağlanamaz. Görev 1 altın görüntüyü `ao=0.0, rim=0.0` ile alır ve bunu teste yorum olarak yazar: korunan şey difüz+speküler+rampa yolu, plan gereği değişen iki terim değil.

**Tip tutarlılığı:** `material()` → `Material`, `surface()` → `Surface`, `render(color=...)` üçünü de kabul eder (callable, `Material` değil — `Material` tek başına `color` olarak geçilmez, `surface()` içinde geçer). `eye()` → `Eye(socket, parts, decals)`; `parts` her yerde `[(sdf, Material), ...]`; `decals` her yerde `(dir3, radius_deg, soft_deg, rgb)`. `turnaround` → `dict[str, PIL.Image]`. `interior_edges` → PIL `'L'`.

**Placeholder taraması:** ilk yazımda iki kusur çıktı ve ikisi de düzeltildi. Görev 9'un test adında boşluk vardı (sözdizimi hatası). Görev 14'ün `render_one`'ı yarım bir ifade taşıyor ve kararı uygulama anına bırakıyordu — `spots()` ile `Surface`'ın kesiştiği yer. Karar plana alındı: `Surface.__call__` yalnızca rengi döndürür, Görev 3'te testiyle birlikte iner, ve Görev 14 onu düz çağırır. Plan bir kararı uygulayana devrederse o bir placeholder'dır, adı ne olursa olsun.

---

## Execution Handoff

**Plan complete and saved to `docs/plans/2026-08-11-character-lib.md`.**
