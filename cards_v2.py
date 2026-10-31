"""Round 15: glass chips. Small frosted cards that sit in the top safe area (never on the face) instead of the big boxes.
Each chip renders a transparent RGBA content sprite (w x h); glass() blurs + darkens the video underneath it, adds a hairline
border + soft shadow. Same class names / constructor args as before, so make_card() and the planners are unchanged."""
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from gfx import clamp01, ease_in_out, ease_out, ease_out_back, font

ROOT = Path(__file__).parent
RED, WHITE = (255, 38, 64), (255, 255, 255)
CHIP_W = 800
_M = {}


def _mono(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
              "C:/Windows/Fonts/consolab.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return font(size)


def _masks(w, h, r):
    k = (w, h, r)
    if k not in _M:
        big = Image.new("L", (w * 3, h * 3), 0)
        ImageDraw.Draw(big).rounded_rectangle([0, 0, w * 3 - 1, h * 3 - 1], r * 3, fill=255)
        m = np.array(big.resize((w, h), Image.LANCZOS)).astype(np.float32) / 255
        ring = m - cv2.erode(m, np.ones((5, 5), np.uint8))
        _M[k] = (m[..., None], np.clip(ring, 0, 1)[..., None])
    return _M[k]


def glass(fr, x, y, w, h, r, a):
    """Frosted-glass rectangle with soft shadow, blended in place on RGB frame fr. Clip-safe."""
    if a <= 0:
        return
    H, W = fr.shape[:2]
    pad = 36
    xa, ya, xb, yb = max(x - pad, 0), max(y - pad, 0), min(x + w + pad, W), min(y + h + pad, H)
    if xb <= xa or yb <= ya:
        return
    roi = fr[ya:yb, xa:xb].astype(np.float32)
    m, ring = _masks(w, h, r)
    full_m = np.zeros((yb - ya, xb - xa, 1), np.float32)
    full_r = np.zeros_like(full_m)
    ox, oy = x - xa, y - ya                                       # chip origin inside roi (may be negative if clipped)
    sx0, sy0 = max(0, -ox), max(0, -oy)
    sx1, sy1 = min(w, (xb - xa) - ox), min(h, (yb - ya) - oy)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    full_m[oy + sy0:oy + sy1, ox + sx0:ox + sx1] = m[sy0:sy1, sx0:sx1]
    full_r[oy + sy0:oy + sy1, ox + sx0:ox + sx1] = ring[sy0:sy1, sx0:sx1]
    sh = cv2.GaussianBlur(full_m, (0, 0), 14)[..., None] if full_m.ndim == 2 else cv2.GaussianBlur(full_m[..., 0], (0, 0), 14)[..., None]
    roi = roi * (1 - 0.30 * a * sh)                                # shadow
    blur = cv2.GaussianBlur(roi, (0, 0), 16)
    yy = np.linspace(1, 0, roi.shape[0], dtype=np.float32)[:, None, None]
    tint = blur * 0.42 + np.array([10, 8, 14], np.float32) + 9 * yy   # dark glass + faint top sheen
    mm = full_m * a
    roi = roi * (1 - mm) + tint * mm
    roi = roi + (255 - roi) * (full_r * 0.30 * a)                  # hairline border
    fr[ya:yb, xa:xb] = np.clip(roi, 0, 255).astype(np.uint8)


def _canvas(w, h):
    return Image.new("RGBA", (w, h), (0, 0, 0, 0))


def _fit(text, maxw, size, lo=28, heavy=True):
    while size > lo and font(size, heavy).getlength(text) > maxw:
        size -= 2
    return font(size, heavy)


class Chip:
    glass = True
    fps = 30
    r = 34
    w, h = CHIP_W, 150


class TitleCard(Chip):
    def __init__(self, title, sub="", **_):
        self.title, self.sub = (title or "").upper()[:28], (sub or "")[:44]
        self.h = 150 if self.sub else 112

    def render(self, t):
        im = _canvas(self.w, self.h)
        d = ImageDraw.Draw(im)
        bar_h = int((self.h - 44) * ease_out(clamp01(t / .45)))
        d.rounded_rectangle([34, (self.h - bar_h) // 2, 42, (self.h + bar_h) // 2], 4, fill=RED + (255,))
        f = _fit(self.title, self.w - 190, 58)
        n = int(len(self.title) * clamp01((t - .12) / .5)) + 1
        ty = 26 if self.sub else (self.h - f.size) // 2 - 4
        d.text((68, ty), self.title[:n], font=f, fill=WHITE + (255,))
        if self.sub:
            d.text((70, ty + f.size + 14), self.sub, font=font(30, False), fill=(255, 190, 195, 235))
        return np.array(im)


class TerminalCard(Chip):
    def __init__(self, lines, **_):
        ls = [str(x)[:34] for x in (lines or ["$ claude", "thinking...", "done"])][:6]
        self.lines = [ls[0]] + ([ls[-1]] if len(ls) > 1 else [])
        self.h = 70 + 46 * len(self.lines) + 14

    def render(self, t):
        im = _canvas(self.w, self.h)
        d = ImageDraw.Draw(im)
        for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
            d.ellipse([30 + i * 28, 26, 46 + i * 28, 42], fill=c + (255,))
        f = _mono(34)
        y, tt = 66, t - 0.15
        for i, ln in enumerate(self.lines):
            cmd = ln.startswith("$")
            speed = 28 if cmd else 40
            n = int(max(0, tt) * speed)
            shown = ln[:n]
            d.text((32, y), shown, font=f, fill=(126, 240, 196, 255) if cmd else (232, 232, 240, 255))
            if 0 < n <= len(ln) and int(t * 4) % 2 == 0:
                x = 32 + f.getlength(shown)
                d.rectangle([x + 3, y + 5, x + 17, y + 38], fill=RED + (255,))
            tt -= len(ln) / speed + 0.18
            y += 46
            if tt < -0.2:
                break
        return np.array(im)


class ProfileCard(Chip):
    h = 170

    def __init__(self, name="NeuroTriage", handle="@neurotriage", bio="", **_):
        self.name, self.handle = (name or "NeuroTriage")[:22], (handle or "@neurotriage")[:26]
        self.logo = None
        p = ROOT / "assets" / "logo.png"
        if p.exists():
            try:
                self.logo = Image.open(p).convert("RGBA").resize((104, 104), Image.LANCZOS)
            except Exception:
                pass

    def render(self, t):
        im = _canvas(self.w, self.h)
        d = ImageDraw.Draw(im)
        ring = Image.new("RGBA", (116, 116), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse([0, 0, 115, 115], fill=(255, 255, 255, 235))
        im.alpha_composite(ring, (28, 27))
        if self.logo is not None:
            m = Image.new("L", (104, 104), 0)
            ImageDraw.Draw(m).ellipse([0, 0, 103, 103], fill=255)
            im.paste(self.logo, (34, 33), m)
        else:
            d.text((62, 50), self.name[0], font=font(60), fill=RED + (255,))
        d.text((164, 40), self.name, font=_fit(self.name, 330, 40), fill=WHITE + (255,))
        d.text((166, 96), self.handle, font=font(28, False), fill=(200, 200, 215, 255))
        followed = t > 1.4
        pulse = 1 if followed else 1 + 0.05 * math.sin(t * 9)
        bw, bh = int(196 * pulse), int(66 * pulse)
        x0, y0 = self.w - 30 - 196 + (196 - bw) // 2, (self.h - bh) // 2
        d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], 33, fill=(235, 235, 242, 255) if followed else (0, 149, 246, 255))
        lab = "Following" if followed else "Follow"
        f = font(30)
        d.text((x0 + (bw - f.getlength(lab)) / 2, y0 + (bh - 30) / 2 - 3), lab, font=f, fill=(20, 20, 28, 255) if followed else WHITE + (255,))
        return np.array(im)


class GraphCard(Chip):
    h = 300

    def __init__(self, values=None, label="", title="", **_):
        v = [float(x) for x in (values or []) if isinstance(x, (int, float))]
        self.v = v if len(v) >= 4 else [10, 14, 13, 22, 30, 44, 58]
        self.label = (label or title or "GROWTH").upper()[:24]

    def render(self, t):
        S = 2                                                          # supersample for smooth line
        W2, H2 = self.w * S, self.h * S
        im = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.text((40 * S, 26 * S), self.label, font=font(30 * S), fill=(255, 190, 195, 255))
        x0, y0, x1, y1 = 44 * S, 92 * S, (self.w - 44) * S, (self.h - 40) * S
        for i in range(4):
            y = y0 + (y1 - y0) * i / 3
            d.line([x0, y, x1, y], fill=(255, 255, 255, 34), width=S)
        lo, hi = min(self.v), max(self.v)
        pts = [(x0 + (x1 - x0) * i / (len(self.v) - 1), y1 - (y1 - y0) * (val - lo) / max(1e-6, hi - lo)) for i, val in enumerate(self.v)]
        p = ease_in_out(clamp01((t - .12) / 1.1)) * (len(pts) - 1)
        i = int(p)
        path = pts[:i + 1] + ([(pts[i][0] + (pts[i + 1][0] - pts[i][0]) * (p - i), pts[i][1] + (pts[i + 1][1] - pts[i][1]) * (p - i))] if i < len(pts) - 1 else [])
        if len(path) >= 2:
            fill = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
            ImageDraw.Draw(fill).polygon(path + [(path[-1][0], y1), (path[0][0], y1)], fill=RED + (70,))
            im.alpha_composite(fill)
            d = ImageDraw.Draw(im)
            d.line(path, fill=(255, 240, 240, 255), width=5 * S, joint="curve")
        ex, ey = path[-1]
        d.ellipse([ex - 11 * S, ey - 11 * S, ex + 11 * S, ey + 11 * S], fill=RED + (255,), outline=WHITE + (255,), width=3 * S)
        return np.array(im.resize((self.w, self.h), Image.LANCZOS))


def soft_panel(img, r=30):
    """Opaque media (screen recording / photo) -> RGBA with rounded corners, hairline border and soft shadow (no red glow box)."""
    img = img.convert("RGB")
    w, h = img.size
    pad = 44
    m = Image.new("L", (w * 3, h * 3), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * 3 - 1, h * 3 - 1], r * 3, fill=255)
    m = m.resize((w, h), Image.LANCZOS)
    out = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("L", out.size, 0)
    sh.paste(m.point(lambda v: int(v * .55)), (pad, pad + 10))
    sh = Image.fromarray(cv2.GaussianBlur(np.array(sh), (0, 0), 16))
    out.paste(Image.new("RGBA", out.size, (0, 0, 0, 255)), (0, 0), sh)
    card = img.convert("RGBA")
    card.putalpha(m)
    out.alpha_composite(card, (pad, pad))
    ring = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(ring).rounded_rectangle([0, 0, w - 1, h - 1], r, outline=(255, 255, 255, 120), width=2)
    out.alpha_composite(ring, (pad, pad))
    return np.array(out)
