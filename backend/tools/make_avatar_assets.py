"""Generate the built-in 2D avatar package (PRD §11.4) with Pillow — no downloads, no AI art.

Writes backend/app/assets/avatars/:
  characters/<id>/  chair.png body.png eyes_closed.png mouth_0..3.png front.png outfit_mask.png preview.png config.json
  backgrounds/<id>_16x9.png, <id>_9x16.png, <id>_1x1.png, <id>_preview.png

The renderer (app/create/avatar.py) only reads these PNGs + config.json, so the drawings can be
replaced with real artwork later without code changes. Deterministic: re-running gives the same files.

Run:  backend/.venv/Scripts/python.exe backend/tools/make_avatar_assets.py
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "app" / "assets" / "avatars"
W, H = 1000, 1300          # character canvas (final pixels)
S = 2                      # supersampling factor while drawing
GRAY = (200, 200, 200)     # outfit base tone: tinted at render time via outfit_mask
GRAY_DARK = (165, 165, 165)
GRAY_LIGHT = (222, 222, 222)

OUTFITS = [
    {"id": "blue", "label": "नीला", "color": [62, 104, 190]},
    {"id": "maroon", "label": "मैरून", "color": [150, 46, 62]},
    {"id": "mustard", "label": "सरसों", "color": [208, 156, 44]},
]


def sc(v):
    """Scale base coordinates (number, tuple, or list of tuples) to the supersampled canvas."""
    if isinstance(v, (int, float)):
        return v * S
    if isinstance(v, tuple):
        return tuple(x * S for x in v)
    return [sc(p) for p in v]


def darker(c, f=0.75):
    return tuple(max(0, int(x * f)) for x in c[:3])


def layer():
    return Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))


def finish(img: Image.Image) -> Image.Image:
    return img.resize((W, H), Image.LANCZOS)


def ell(d: ImageDraw.ImageDraw, cx, cy, rx, ry, fill, outline=None, width=0):
    d.ellipse(sc((cx - rx, cy - ry, cx + rx, cy + ry)), fill=fill, outline=outline, width=sc(width) if width else 0)


def poly(d, pts, fill, outline=None, width=0):
    d.polygon(sc(pts), fill=fill, outline=outline, width=sc(width) if width else 1)


def rrect(d, box, r, fill, outline=None, width=0):
    d.rounded_rectangle(sc(box), radius=sc(r), fill=fill, outline=outline, width=sc(width) if width else 0)


def smooth_poly(pts, steps=10):
    """Closed Catmull-Rom spline through pts → smooth organic outlines."""
    out = []
    n = len(pts)
    for i in range(n):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        for s in range(steps):
            t = s / steps
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
                                    + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3) for k in range(2)))
    return out


# --- character spec -----------------------------------------------------------------------------
CHARACTERS = {
    "aarav": {"label": "आरव", "desc": "युवा, छोटे बाल", "skin": (226, 172, 128), "hair": (34, 28, 28),
              "pants": (238, 232, 220), "shoe": (118, 76, 44), "style": "short", "sash": None},
    "meera": {"label": "मीरा", "desc": "युवती, लंबे बाल", "skin": (204, 146, 108), "hair": (28, 22, 24),
              "pants": (236, 226, 214), "shoe": (150, 60, 70), "style": "long", "sash": (238, 214, 196)},
    "dadaji": {"label": "दादाजी", "desc": "कहानी सुनाने वाले बुज़ुर्ग", "skin": (196, 142, 106), "hair": (226, 226, 222),
               "pants": (242, 240, 234), "shoe": (96, 64, 40), "style": "elder", "sash": None},
}

CX = 500
FACE = (500, 330, 118, 142)      # cx, cy, rx, ry
EYES = [(452, 318), (548, 318)]
MOUTH = (500, 412)


def draw_chair(d):
    wood, dark = (126, 78, 44), (88, 52, 28)
    rrect(d, (268, 420, 732, 990), 70, wood, dark, 5)          # back rest
    rrect(d, (300, 452, 700, 960), 52, (140, 90, 52))          # inner panel
    for x in range(330, 690, 60):                               # cane texture
        d.line(sc([(x, 470), (x + 30, 940)]), fill=(118, 72, 40), width=sc(3))
    rrect(d, (240, 925, 760, 985), 18, (112, 68, 38), dark, 4)  # seat front edge
    for x in (262, 704):                                         # legs
        rrect(d, (x, 975, x + 34, 1288), 10, wood, dark, 4)
    d.line(sc([(296, 1180), (704, 1180)]), fill=dark, width=sc(10))  # stretcher


def draw_body(spec, d, mask_d):
    skin, sdark = spec["skin"], darker(spec["skin"], 0.82)
    out = darker(spec["skin"], 0.55)

    # long hair falls behind the shoulders
    if spec["style"] == "long":
        hair = spec["hair"]
        poly(d, smooth_poly([(372, 230), (500, 160), (628, 230), (660, 420), (684, 640), (600, 668), (500, 640),
                             (400, 668), (316, 640), (340, 420)]), hair)

    # legs (seated, facing camera: knees toward us, shins down)
    pants, pdark = spec["pants"], darker(spec["pants"], 0.85)
    for x0 in (372, 522):
        rrect(d, (x0, 960, x0 + 106, 1236), 40, pants, pdark, 4)
        d.line(sc([(x0 + 53, 1010), (x0 + 53, 1220)]), fill=pdark, width=sc(3))
        ell(d, x0 + 53, 1250, 66, 26, spec["shoe"], darker(spec["shoe"]), 3)

    # kurta torso (outfit, tinted later)
    torso = smooth_poly([(352, 568), (392, 522), (458, 504), (542, 504), (608, 522), (648, 568), (662, 760),
                         (668, 1012), (500, 1030), (332, 1012), (338, 760)], 8)
    poly(d, torso, GRAY, (120, 120, 120), 4)
    poly(mask_d, torso, 255)
    for x0, x1 in ((420, 400), (580, 600)):                    # cloth folds
        d.line(sc([(x0, 620), (x1, 1000)]), fill=GRAY_DARK, width=sc(5))
    d.line(sc([(500, 520), (500, 700)]), fill=GRAY_DARK, width=sc(4))   # placket
    for y in (560, 600, 640):
        ell(d, 500, y, 6, 6, GRAY_LIGHT)

    # dupatta / sash (not tinted)
    if spec["sash"]:
        sash = [(372, 530), (430, 515), (650, 900), (640, 1000), (590, 1000)]
        poly(d, sash, spec["sash"], darker(spec["sash"], 0.8), 3)
        poly(mask_d, sash, 0)

    # arms: sleeve to elbow, forearm toward the lap, hands on knees
    for sgn in (-1, 1):
        def X(x):
            return CX + sgn * (x - CX)
        sleeve = [(X(352), 566), (X(408), 590), (X(404), 812), (X(334), 818), (X(324), 640)]
        fore = [(X(334), 790), (X(400), 784), (X(458), 944), (X(398), 966)]
        for p in (sleeve, fore):
            poly(d, p, GRAY, (120, 120, 120), 4)
            poly(mask_d, p, 255)
        ell(d, X(432), 966, 40, 30, skin, out, 3)                # hand
        ell(mask_d, X(432), 966, 42, 32, 0)                      # hands are skin, never tinted
        d.line(sc([(X(412), 960), (X(450), 958)]), fill=sdark, width=sc(3))

    # neck + collar
    rrect(d, (458, 430, 542, 530), 22, skin)
    poly(d, [(458, 492), (542, 492), (500, 532)], sdark)
    d.arc(sc((448, 470, 552, 548)), 20, 160, fill=GRAY_DARK, width=sc(5))

    # ears, face
    for ex in (382, 618):
        ell(d, ex, 338, 26, 42, skin, out, 3)
        ell(d, ex, 338, 12, 24, sdark)
    cx, cy, rx, ry = FACE
    poly(d, smooth_poly([(cx - rx, cy - 30), (cx - rx + 10, cy - ry + 40), (cx, cy - ry), (cx + rx - 10, cy - ry + 40),
                         (cx + rx, cy - 30), (cx + rx - 22, cy + 70), (cx + 40, cy + ry - 6), (cx, cy + ry + 4),
                         (cx - 40, cy + ry - 6), (cx - rx + 22, cy + 70)], 12), skin, out, 3)

    # cheeks
    blush = layer()
    bd = ImageDraw.Draw(blush)
    for bx in (428, 572):
        ell(bd, bx, 384, 30, 18, (*darker(skin, 0.9)[:2], min(255, skin[2] + 10), 70))
    blush = blush.filter(ImageFilter.GaussianBlur(sc(6)))
    return blush


def draw_hair_front(spec, d):
    hair = spec["hair"]
    st = spec["style"]
    if st == "short":
        poly(d, smooth_poly([(378, 318), (376, 240), (410, 196), (468, 176), (540, 176), (598, 196), (628, 244),
                             (624, 318), (606, 262), (560, 236), (500, 244), (446, 250), (404, 276)], 10), hair)
    elif st == "long":
        poly(d, smooth_poly([(380, 330), (382, 236), (430, 190), (500, 176), (570, 190), (618, 236), (620, 330),
                             (600, 262), (548, 226), (500, 232), (452, 226), (400, 262)], 10), hair)
        d.line(sc([(500, 182), (500, 232)]), fill=darker(hair, 0.6) if sum(hair) > 120 else (60, 50, 50), width=sc(3))
    else:  # elder: bald crown, white sides
        for sgn in (-1, 1):
            poly(d, smooth_poly([(CX + sgn * 112, 220), (CX + sgn * 128, 270), (CX + sgn * 124, 330),
                                 (CX + sgn * 104, 310), (CX + sgn * 100, 250)], 8), hair)


def draw_face_details(spec, d):
    skin = spec["skin"]
    brow = spec["hair"] if spec["style"] != "elder" else (150, 146, 140)
    for (ex, ey) in EYES:
        # eyebrow
        d.line(sc([(ex - 30, ey - 34), (ex, ey - 42), (ex + 30, ey - 34)]), fill=brow, width=sc(8), joint="curve")
        # eye white, iris, pupil, highlight, upper lash line
        ell(d, ex, ey, 27, 17, (250, 248, 244), darker(skin, 0.5), 2)
        ell(d, ex, ey + 1, 13, 13, (74, 46, 30))
        ell(d, ex, ey + 1, 7, 7, (18, 12, 10))
        ell(d, ex + 5, ey - 4, 4, 4, (255, 255, 255))
        d.arc(sc((ex - 28, ey - 18, ex + 28, ey + 16)), 195, 345, fill=(30, 22, 20), width=sc(4))
    # nose
    d.line(sc([(498, 336), (490, 372), (504, 378)]), fill=darker(skin, 0.7), width=sc(4), joint="curve")
    if spec["style"] == "long":
        ell(d, 500, 270, 6, 6, (200, 30, 50))                   # bindi
        for ex in (382, 618):
            ell(d, ex, 384, 8, 8, (230, 180, 60), (170, 120, 30), 2)  # earrings
    if spec["style"] == "elder":
        for (ex, ey) in EYES:                                    # round glasses
            ell(d, ex, ey, 38, 34, None, (60, 50, 44), 5)
        d.line(sc([(490, 316), (510, 316)]), fill=(60, 50, 44), width=sc(5))
        d.line(sc([(414, 312), (388, 318)]), fill=(60, 50, 44), width=sc(5))
        d.line(sc([(586, 312), (612, 318)]), fill=(60, 50, 44), width=sc(5))


def draw_front(spec, d):
    """Layer drawn above the mouth (moustache/beard)."""
    if spec["style"] != "elder":
        return
    beard = (232, 232, 228)
    poly(d, smooth_poly([(400, 400), (430, 446), (470, 470), (500, 474), (530, 470), (570, 446), (600, 400),
                         (588, 452), (548, 492), (500, 504), (452, 492), (412, 452)], 8), beard)
    poly(d, smooth_poly([(446, 398), (474, 386), (500, 392), (526, 386), (554, 398), (540, 404), (500, 400),
                         (460, 404)], 6), (244, 244, 240), (190, 190, 186), 2)


def mouth_sprite(spec, level: int) -> Image.Image:
    """Mouth states drawn as vector shapes tinted from the skin tone. Sprite 160×110, anchor = centre."""
    w, h = 160, 110
    img = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin = spec["skin"]
    lip = (min(255, int(skin[0] * 0.85 + 20)), int(skin[1] * 0.55), int(skin[2] * 0.55))
    inner, teeth, tongue = (86, 28, 36), (250, 246, 240), (214, 96, 104)
    cx, cy = 80, 55
    if level == 0:
        d.arc(sc((cx - 32, cy - 20, cx + 32, cy + 10)), 20, 160, fill=lip, width=sc(6))
    else:
        rx, ry = [(0, 0), (20, 8), (26, 16), (30, 25)][level]
        d.ellipse(sc((cx - rx - 4, cy - ry - 4, cx + rx + 4, cy + ry + 4)), fill=lip)
        d.ellipse(sc((cx - rx, cy - ry, cx + rx, cy + ry)), fill=inner)
        if level >= 2:
            d.chord(sc((cx - rx + 4, cy - ry, cx + rx - 4, cy + ry)), 200, 340, fill=teeth)
            d.chord(sc((cx - rx + 6, cy, cx + rx - 6, cy + ry + 2)), 20, 160, fill=tongue)
    return img.resize((w, h), Image.LANCZOS)


def eyes_closed(spec) -> Image.Image:
    img = layer()
    d = ImageDraw.Draw(img)
    for (ex, ey) in EYES:
        ell(d, ex, ey, 30, 20, spec["skin"])
        d.arc(sc((ex - 26, ey - 14, ex + 26, ey + 8)), 15, 165, fill=(30, 22, 20), width=sc(4))
    return finish(img)


def tinted(body: Image.Image, mask: Image.Image, color) -> Image.Image:
    import numpy as np

    a = np.asarray(body).astype(np.float32)
    m = (np.asarray(mask).astype(np.float32) / 255.0)[..., None]
    t = np.clip(a[..., :3] / 200.0 * np.array(color, np.float32), 0, 255)
    a[..., :3] = a[..., :3] * (1 - m) + t * m
    return Image.fromarray(a.astype("uint8"))


def make_character(cid: str, spec: dict) -> None:
    d_out = OUT / "characters" / cid
    d_out.mkdir(parents=True, exist_ok=True)

    chair = layer()
    draw_chair(ImageDraw.Draw(chair))
    body = layer()
    mask = Image.new("L", (W * S, H * S), 0)
    bd = ImageDraw.Draw(body)
    blush = draw_body(spec, bd, ImageDraw.Draw(mask))
    body = Image.alpha_composite(body, blush)
    bd = ImageDraw.Draw(body)
    draw_hair_front(spec, bd)
    draw_face_details(spec, bd)
    front = layer()
    draw_front(spec, ImageDraw.Draw(front))

    chair, body, front = finish(chair), finish(body), finish(front)
    mask = mask.resize((W, H), Image.LANCZOS)
    chair.save(d_out / "chair.png", optimize=True)
    body.save(d_out / "body.png", optimize=True)
    front.save(d_out / "front.png", optimize=True)
    mask.save(d_out / "outfit_mask.png", optimize=True)
    eyes_closed(spec).save(d_out / "eyes_closed.png", optimize=True)
    for lv in range(4):
        mouth_sprite(spec, lv).save(d_out / f"mouth_{lv}.png", optimize=True)

    # preview card: default outfit on a soft backdrop
    prev = Image.new("RGBA", (W, H), (46, 52, 70, 255))
    full = Image.alpha_composite(prev, chair)
    full = Image.alpha_composite(full, tinted(body, mask, OUTFITS[0]["color"]))
    m0 = mouth_sprite(spec, 0)
    full.alpha_composite(m0, (MOUTH[0] - m0.width // 2, MOUTH[1] - m0.height // 2))
    full = Image.alpha_composite(full, front)
    full.convert("RGB").resize((300, 390), Image.LANCZOS).save(d_out / "preview.png", optimize=True)

    config = {
        "id": cid, "label": spec["label"], "description": spec["desc"], "canvas": [W, H],
        "layers": ["chair.png", "body.png", "<mouth>", "front.png"],
        "static_layers": ["chair.png"],
        "mouth_anchor": list(MOUTH), "mouth_sprites": [f"mouth_{i}.png" for i in range(4)],
        "eyes_closed": "eyes_closed.png", "eye_anchors": [list(e) for e in EYES],
        "outfit_mask": "outfit_mask.png", "outfit_base_gray": 200, "outfits": OUTFITS,
        "head_box": [360, 150, 640, 540],        # for thumbnails
        "seat_y": 960,
        "license": "Generated by backend/tools/make_avatar_assets.py (project-owned, no third-party art).",
    }
    (d_out / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


# --- backgrounds ----------------------------------------------------------------------------------
def vgrad(w, h, top, bottom) -> Image.Image:
    import numpy as np

    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    arr = np.array(top, np.float32) * (1 - t) + np.array(bottom, np.float32) * t
    return Image.fromarray(np.repeat(arr, w, axis=1).astype("uint8"))


def books(d, x0, y0, x1, y1, rng):
    palette = [(176, 58, 46), (40, 96, 146), (52, 120, 82), (196, 150, 52), (120, 70, 140), (210, 210, 196),
               (86, 60, 44), (160, 90, 60)]
    x = x0
    while x < x1 - 10:
        bw = rng.randint(14, 30) * (y1 - y0) // 200
        bh = rng.randint(70, 98) * (y1 - y0) // 100
        bw = max(8, min(bw, x1 - x))
        c = rng.choice(palette)
        d.rectangle((x, y1 - bh, x + bw - 2, y1), fill=c)
        d.line((x + 3, y1 - bh + 8, x + bw - 5, y1 - bh + 8), fill=darker(c, 0.7), width=2)
        x += bw
        if rng.random() < 0.08:
            x += bw  # gap


def shelf(d, x0, y0, x1, y1, rows, rng):
    wood, dark = (104, 66, 40), (70, 42, 24)
    d.rectangle((x0, y0, x1, y1), fill=(58, 36, 22))
    rh = (y1 - y0) / rows
    for r in range(rows):
        top = int(y0 + r * rh)
        books(d, x0 + 12, top + 10, x1 - 12, int(top + rh - 14), rng)
        d.rectangle((x0, int(top + rh - 14), x1, int(top + rh)), fill=wood)
    d.rectangle((x0, y0, x1, y1), outline=dark, width=10)


def bg_study(w, h) -> Image.Image:
    rng = random.Random(7)
    img = vgrad(w, h, (236, 220, 196), (214, 192, 162))
    d = ImageDraw.Draw(img)
    floor_y = int(h * 0.80)
    d.rectangle((0, floor_y, w, h), fill=(150, 104, 70))
    for x in range(0, w, max(60, w // 14)):
        d.line((x, floor_y, x - w * 0.1, h), fill=(132, 90, 60), width=3)
    portrait = h > w
    # window
    wx0, wy0 = int(w * 0.06), int(h * (0.08 if portrait else 0.12))
    ww, wh = int(w * (0.40 if portrait else 0.26)), int(h * (0.22 if portrait else 0.44))
    sky = vgrad(ww, wh, (150, 200, 236), (214, 236, 246))
    img.paste(sky, (wx0, wy0))
    d.rectangle((wx0, wy0, wx0 + ww, wy0 + wh), outline=(250, 246, 238), width=max(10, w // 90))
    d.line((wx0 + ww // 2, wy0, wx0 + ww // 2, wy0 + wh), fill=(250, 246, 238), width=max(8, w // 120))
    d.line((wx0, wy0 + wh // 2, wx0 + ww, wy0 + wh // 2), fill=(250, 246, 238), width=max(8, w // 120))
    # shelf
    sx0 = int(w * (0.56 if portrait else 0.70))
    sy0 = int(h * (0.08 if portrait else 0.10))
    shelf(d, sx0, sy0, int(w * 0.96), int(h * (0.36 if portrait else 0.74)), 3 if portrait else 4, rng)
    # plant
    px, py = int(w * (0.12 if portrait else 0.08)), floor_y
    d.rectangle((px - 34, py - 70, px + 34, py), fill=(180, 96, 60))
    for i in range(9):
        ang = math.radians(200 + i * 18)
        d.ellipse((px + 80 * math.cos(ang) - 26, py - 90 + 70 * math.sin(ang) - 14,
                   px + 80 * math.cos(ang) + 26, py - 90 + 70 * math.sin(ang) + 14), fill=(66, 134, 72))
    # frame on wall
    fx, fy = int(w * (0.36 if not portrait else 0.30)), int(h * (0.14 if not portrait else 0.30))
    d.rectangle((fx, fy, fx + int(w * 0.10), fy + int(w * 0.07)), fill=(246, 236, 210), outline=(120, 80, 50), width=8)
    return img.filter(ImageFilter.GaussianBlur(2.2))


def bg_library(w, h) -> Image.Image:
    rng = random.Random(11)
    img = vgrad(w, h, (70, 46, 32), (40, 26, 18))
    d = ImageDraw.Draw(img)
    cols = 3 if w > h else 2
    gap = int(w * 0.02)
    cw = (w - gap * (cols + 1)) // cols
    for c in range(cols):
        x0 = gap + c * (cw + gap)
        shelf(d, x0, int(h * 0.04), x0 + cw, int(h * 0.82), 6 if h > w else 5, rng)
    d.rectangle((0, int(h * 0.82), w, h), fill=(92, 54, 34))
    img = img.filter(ImageFilter.GaussianBlur(2.6))
    # warm vignette
    import numpy as np

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    v = np.clip(1.15 - 0.45 * r, 0.55, 1.0)[..., None]
    a = np.asarray(img).astype(np.float32) * v
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"))


def bg_studio(w, h) -> Image.Image:
    rng = random.Random(3)
    img = vgrad(w, h, (58, 44, 112), (18, 22, 52))
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for _ in range(14):
        x, y, r = rng.randint(0, w), rng.randint(0, int(h * 0.7)), rng.randint(w // 40, w // 12)
        c = rng.choice([(255, 140, 180), (140, 160, 255), (255, 210, 140), (150, 255, 220)])
        gd.ellipse((x - r, y - r, x + r, y + r), fill=tuple(int(k * 0.22) for k in c))
    glow = glow.filter(ImageFilter.GaussianBlur(w // 60))
    from PIL import ImageChops

    img = ImageChops.add(img, glow)
    d = ImageDraw.Draw(img)
    d.ellipse((int(w * 0.15), int(h * 0.80), int(w * 0.85), int(h * 1.05)), fill=(30, 30, 64))
    return img.filter(ImageFilter.GaussianBlur(1.5))


BACKGROUNDS = {"study": ("पढ़ाई का कमरा", bg_study), "library": ("लाइब्रेरी", bg_library), "studio": ("स्टूडियो", bg_studio)}
SIZES = {"16x9": (1280, 720), "9x16": (720, 1280), "1x1": (1080, 1080)}


def make_backgrounds() -> None:
    d_out = OUT / "backgrounds"
    d_out.mkdir(parents=True, exist_ok=True)
    meta = {}
    for bid, (label, fn) in BACKGROUNDS.items():
        for tag, (w, h) in SIZES.items():
            fn(w, h).save(d_out / f"{bid}_{tag}.jpg", quality=90, optimize=True)
        fn(1280, 720).resize((320, 180), Image.LANCZOS).save(d_out / f"{bid}_preview.jpg", quality=85)
        meta[bid] = {"label": label, "files": {t: f"{bid}_{t}.jpg" for t in SIZES}, "preview": f"{bid}_preview.jpg"}
    (d_out / "backgrounds.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    for cid, spec in CHARACTERS.items():
        make_character(cid, spec)
    make_backgrounds()
    print("written:", OUT)
