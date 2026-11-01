"""Shared small graphics helpers (easing, fonts, sprites, blit). Resolution independent:
nothing here reads global W/H, so the 9:16 Short code and the 16:9 Long code can both use it."""
import glob
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ASSETS = Path(__file__).parent / "assets"
BLUE, GREEN, MINT = (62, 126, 255), (46, 214, 160), (126, 240, 196)
NAVY = (10, 18, 40)
_FONTS = {}


def clamp01(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def ease_out(x):
    x = clamp01(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = clamp01(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def ease_out_back(x, s=1.9):
    x = clamp01(x)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def find_font(heavy=True):
    if heavy in _FONTS:
        return _FONTS[heavy]
    pats = [str(ASSETS / "font.ttf"), str(ASSETS / "font.otf"),
            "/usr/share/fonts/**/Montserrat-ExtraBold.*", "/usr/share/fonts/**/Montserrat-Bold.*",
            "/usr/share/fonts/**/Poppins-ExtraBold.ttf", "/usr/share/fonts/**/Poppins-Bold.ttf",
            "/usr/share/fonts/**/NotoSans-ExtraBold.ttf", "/usr/share/fonts/**/NotoSans-Bold.ttf",
            "/usr/share/fonts/**/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"]
    if not heavy:
        pats = ["/usr/share/fonts/**/Poppins-SemiBold.ttf", "/usr/share/fonts/**/Montserrat-SemiBold.*"] + pats
    for p in pats:
        hits = sorted(glob.glob(p, recursive=True))
        if hits:
            _FONTS[heavy] = hits[0]
            return hits[0]
    raise RuntimeError("No font found. Put a bold font at assets/font.ttf")


def font(size, heavy=True):
    return ImageFont.truetype(find_font(heavy), int(size))


def blit(frame, spr, x, y, alpha=1.0):
    """Blend an RGBA uint8 sprite onto an RGB frame at top-left (x, y); clip-safe."""
    H, W = frame.shape[:2]
    h, w = spr.shape[:2]
    x, y = int(round(x)), int(round(y))
    xa, ya, xb, yb = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if xb <= xa or yb <= ya or alpha <= 0:
        return
    s = spr[ya - y:yb - y, xa - x:xb - x].astype(np.float32)
    a = (s[..., 3:4] / 255.0) * alpha
    roi = frame[ya:yb, xa:xb].astype(np.float32)
    frame[ya:yb, xa:xb] = np.clip(roi * (1 - a) + s[..., :3] * a, 0, 255).astype(np.uint8)


def scaled(spr, k):
    if abs(k - 1) < 0.004:
        return spr
    return cv2.resize(spr, (max(2, int(spr.shape[1] * k)), max(2, int(spr.shape[0] * k))),
                      interpolation=cv2.INTER_LINEAR if k > 1 else cv2.INTER_AREA)


def rounded(w, h, c1, c2, radius, alpha=235):
    g = np.zeros((h, w, 4), np.uint8)
    for ch in range(3):
        g[..., ch] = np.linspace(c1[ch], c2[ch], w)[None, :]
    m = Image.new("L", (w * 3, h * 3), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * 3 - 1, h * 3 - 1], radius * 3, fill=alpha)
    g[..., 3] = np.array(m.resize((w, h), Image.LANCZOS))
    return g


def text_sprite(text, size, fill=(255, 255, 255), stroke=0, stroke_fill=(10, 16, 30), shadow=True, heavy=True):
    f = font(size, heavy)
    pad = 24
    bb = f.getbbox(text, stroke_width=stroke)
    w, h = bb[2] - bb[0] + 2 * pad, bb[3] - bb[1] + 2 * pad
    lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((pad - bb[0], pad - bb[1] + 5), text, font=f, fill=(0, 0, 0, 150),
                                stroke_width=stroke, stroke_fill=(0, 0, 0, 150))
        lay = Image.alpha_composite(lay, sh.filter(ImageFilter.GaussianBlur(8)))
    ImageDraw.Draw(lay).text((pad - bb[0], pad - bb[1]), text, font=f, fill=tuple(fill) + (255,),
                             stroke_width=stroke, stroke_fill=tuple(stroke_fill) + (255,))
    return np.array(lay)


def pill(text, size, c1=BLUE, c2=GREEN, padx=34, pady=18, alpha=240, tc=(255, 255, 255)):
    f = font(size)
    bb = f.getbbox(text)
    w, h = bb[2] - bb[0] + 2 * padx, bb[3] - bb[1] + 2 * pady
    base = Image.fromarray(rounded(w, h, c1, c2, h // 2, alpha), "RGBA")
    ImageDraw.Draw(base).text((padx - bb[0], pady - bb[1]), text, font=f, fill=tuple(tc) + (255,))
    pad = 20
    out = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    sh.paste((0, 0, 0, 110), (pad, pad + 6, pad + w, pad + h + 6), base.split()[3])
    out = Image.alpha_composite(out, sh.filter(ImageFilter.GaussianBlur(8)))
    out.alpha_composite(base, (pad, pad))
    return np.array(out)


def wrap_lines(words, widths, space, maxw, max_lines=2):
    """Greedy-balanced split of words into <= max_lines lines that fit maxw. Returns list of index lists or None."""
    n = len(words)
    total = sum(widths) + space * (n - 1)
    if total <= maxw or n == 1:
        return [list(range(n))]
    best = None
    for cut in range(1, n):
        a = sum(widths[:cut]) + space * (cut - 1)
        b = sum(widths[cut:]) + space * (n - cut - 1)
        m = max(a, b)
        if best is None or m < best[0]:
            best = (m, cut)
    if best[0] <= maxw:
        return [list(range(best[1])), list(range(best[1], n))]
    return None
