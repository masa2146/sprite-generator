# Recipes

Working patterns for common asset archetypes. All assume
`from sprite_lib import *` and a palette dict like:

```python
PAL = {'pink': ((246,115,211),(255,168,231),(206,70,164)),   # base, light, dark
       'aqua': ((41,197,210),(128,231,240),(21,148,161))}
BACKDROP = (51, 48, 79, 255)
```

Sizes below are final pixels; everything is drawn at `SS`× internally.

## Glossy candy tile (match-3 brick)

```python
def brick(variant='pink', size=256):
    base, light, dark = PAL[variant]
    im = canvas(size, size); s = size*SS
    m, rad = int(0.045*s), int(0.19*s)
    box = (m, m, s-m, s-m)
    mask = rr_mask(im.size, box, rad)
    drop_shadow(im, mask, offset=(0,4), alpha=110)
    fill_grad(im, mask, [(0,light),(0.28,base),(1,dark)])
    sheen(im, (m+int(0.06*s), m+int(0.045*s), s-m-int(0.06*s), m+int(0.20*s)),
          rad//2, alpha=110, blur=3, clip=mask)
    return down(im, size, size)
```

## Blob / jellybean mascot (simple character)

Compound silhouette with `union`, then the standard 4-layer light stack.
Ears, tails, feet are just more rounded rects/ellipses in the union. Keep the
character faceless-simple or hand the face to an image model; geometry +
gloss is where code shines.

```python
def bunny(variant='pink', size=256):
    base, light, dark = PAL[variant]
    im = canvas(size, size); s = size*SS
    bw, bh = int(0.62*s), int(0.60*s); bx, by = (s-bw)//2, s-int(0.06*s)-bh
    ew, eh, gap = int(0.17*s), int(0.34*s), int(0.10*s)
    e1x, e2x, ey = s//2-gap//2-ew, s//2+gap//2, by-eh+int(0.10*s)
    body = rr_mask(im.size, (bx,by,bx+bw,by+bh), int(0.20*s))
    ears = [rr_mask(im.size, (ex,ey,ex+ew,by+int(0.2*s)), ew//2) for ex in (e1x,e2x)]
    sil = union(body, *ears)
    drop_shadow(im, sil, offset=(0,5), alpha=110, blur=5)
    fill_grad(im, sil, [(0,light),(0.35,base),(1,dark)])
    inner_shadow(im, sil, offset=(0,7), alpha=90, blur=5)
    sheen(im, (bx+int(0.08*s),by+int(0.03*s),bx+bw-int(0.08*s),by+int(0.16*s)),
          int(0.08*s), alpha=100, blur=4, clip=body)
    return down(im, size, size)
```

## Pill badge with inset plate (level indicator)

Outer pill with under-lip for depth, inner dark plate for text, sheen, sparkle.

```python
def badge(w=640, h=256):
    im = canvas(w, h); W, H = w*SS, h*SS
    mx, my = int(0.03*W), int(0.06*H); rad = (H-2*my)//2
    ImageDraw.Draw(im).rounded_rectangle(          # under-lip = depth
        (mx, my+int(0.05*H), W-mx, H-my+int(0.05*H)), radius=rad, fill=(23,84,141,255))
    paste = rr_mask(im.size, (mx,my,W-mx,H-my), rad)
    fill_grad(im, paste, [(0,(126,216,255)),(0.45,(64,164,236)),(1,(37,120,199))])
    ins = int(0.10*H)
    inner = rr_mask(im.size, (mx+ins,my+ins,W-mx-ins,H-my-ins), rad-ins)
    fill_grad(im, inner, [(0,(31,34,66)),(1,(43,46,84))])
    sheen(im, (mx+int(0.05*W),my+int(0.06*H),W-mx-int(0.05*W),my+int(0.22*H)),
          rad//2, alpha=80, blur=3, clip=paste)
    return down(im, w, h)
```

## Coin / currency bar

Dark pill + coin circle overlapping the left end + accent button at the right.
Coin = rim ellipse, face ellipse at 0.78 r, blurred highlight crescent
(ellipse shifted up-left). Button = rounded square with under-lip, gradient,
white glyph drawn from two rounded rectangles (a plus) or a polygon.

## Gear / icon button

Circle button: rim ring (darker fill, smaller inner circle), radial or
vertical gradient face, sheen on the upper half. Gear glyph: polygon from
polar coordinates —

```python
def gear_points(cx, cy, r_out, r_in, teeth=6, tooth_frac=0.5):
    pts = []
    for i in range(teeth*2):
        a0 = i*math.pi/teeth
        r = r_out if i % 2 == 0 else r_in
        for da in (-tooth_frac/teeth, tooth_frac/teeth):
            pts.append((cx+r*math.cos(a0+da), cy+r*math.sin(a0+da)))
    return pts
```

then `poly_mask` + a centered hole (paste 0 with an `ellipse_mask`). Keep the
glyph a single flat color with a thin dark under-offset copy for depth.

## Ribbed capsule (slug, battery, canister)

Rounded rect + vertical gradient, then on a separate layer: groove lines
(thin dark rounded rects) and per-rib highlight bands (soft light rects,
low alpha), blurred slightly, pasted through the body mask.

## Tileable track / pipe / border set

1. If a reference exists: `measure_section('ref_strip.png')`, print the
   profile, identify bands (shadow, highlight line, channel, lip...), write
   them as `piecewise_section([(t0,t1,color), ...])`.
2. `straight = sweep_straight(fn, width, length)`
3. `corner = sweep_corner(fn, width, r_in)` — same `fn`, same `width`.
4. Assembly proof: paste corner at (0,0); straight at (S, 0) horizontally;
   vertical straight (`horizontal=False`) at (0, S). View it: the joints must
   be invisible. If a joint shows, the two pieces are not using the same
   section function — fix that, do not retouch pixels.

Orientation contract: `t=0` is the straight piece's top edge (or left edge
when vertical); in the corner, `t=0` is the outer radius. The corner's flush
ends sit on its bottom and right canvas edges — the horizontal run continues
to the right of it, the vertical run below it. Other corner orientations are
`corner.rotate(90/180/270)`.

## Nine-slice panels

Draw one panel with `rr_mask` + gradient + border ring at a generous size and
let the engine nine-slice it. Keep corner radius ≤ the slice margin so
stretching never touches a curve.
