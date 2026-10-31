"""Round 5b: end card - LIKE / SHARE / FOLLOW buttons + 'Try NeuroTriage' pill. Drawn over the brand splash and reused
by the raw-video editor. Positions keep clear of the Shorts UI (bottom ~15%)."""
import math

import numpy as np
from PIL import Image, ImageDraw

from gfx import BLUE, GREEN, blit, clamp01, ease_out_back, font, pill, rounded, scaled, text_sprite

Y_ROW, Y_TRY = 1200, 1315     # all inside y<1600: clear of the Shorts bottom UI
BUTTONS = [("LIKE", "heart"), ("SHARE", "plane"), ("FOLLOW", "plus")]
ROW_COLORS = {"heart": ((235, 64, 110), (255, 120, 90)), "plane": (BLUE, (80, 150, 255)), "plus": (GREEN, (60, 210, 160))}


def _icon(d, kind, cx, cy, r):
    w = (255, 255, 255, 255)
    if kind == "heart":
        d.ellipse([cx - r, cy - r * .9, cx, cy + r * .1], fill=w)
        d.ellipse([cx, cy - r * .9, cx + r, cy + r * .1], fill=w)
        d.polygon([(cx - r * .98, cy - r * .22), (cx + r * .98, cy - r * .22), (cx, cy + r * .95)], fill=w)
    elif kind == "plane":
        d.polygon([(cx - r, cy - r * .1), (cx + r, cy - r), (cx + r * .25, cy + r), (cx - r * .05, cy + r * .2)], fill=w)
    else:
        t = r * .22
        d.rectangle([cx - r, cy - t, cx + r, cy + t], fill=w)
        d.rectangle([cx - t, cy - r, cx + t, cy + r], fill=w)


def button(label, kind, size=40, padx=30, pady=18):
    f = font(size)
    bb = f.getbbox(label)
    ic = int(size * 1.0)
    w, h = (bb[2] - bb[0]) + 2 * padx + ic + 14, (bb[3] - bb[1]) + 2 * pady
    c1, c2 = ROW_COLORS[kind]
    base = Image.fromarray(rounded(w, h, c1, c2, h // 2, 245), "RGBA")
    d = ImageDraw.Draw(base)
    _icon(d, kind, padx + ic // 2, h // 2, ic * .42)
    d.text((padx + ic + 14 - bb[0], pady - bb[1]), label, font=f, fill=(255, 255, 255, 255))
    pad = 20
    out = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    out.alpha_composite(base, (pad, pad))
    return np.array(out)


class EndCard:
    def __init__(self, W=1080, site="www.neurotriage.in", brand="NeuroTriage"):
        self.W = W
        self.btns = [button(l, k) for l, k in BUTTONS]
        self.try_pill = pill(f"Try {brand}", 58, BLUE, GREEN, 70, 26)
        self.site = text_sprite(site, 40, (235, 240, 250), 0, shadow=True)

    def draw(self, frame, t, alpha=1.0):
        """t = seconds since the end card started."""
        if t < 0 or alpha <= 0:
            return frame
        gap = 18
        total = sum(b.shape[1] for b in self.btns) + gap * (len(self.btns) - 1)
        x = (self.W - total) / 2
        for i, b in enumerate(self.btns):
            u = clamp01((t - 0.12 * i) / 0.45)
            if u > 0:
                s = scaled(b, max(0.05, ease_out_back(u)))
                blit(frame, s, x + (b.shape[1] - s.shape[1]) / 2, Y_ROW + (b.shape[0] - s.shape[0]) / 2, alpha * min(1, u * 3))
            x += b.shape[1] + gap
        u = clamp01((t - 0.45) / 0.5)
        if u > 0:
            k = ease_out_back(u) * (1 + 0.025 * math.sin(t * 5))
            s = scaled(self.try_pill, max(0.05, k))
            blit(frame, s, (self.W - s.shape[1]) / 2, Y_TRY + (self.try_pill.shape[0] - s.shape[0]) / 2, alpha * min(1, u * 3))
        u2 = clamp01((t - 0.8) / 0.4)
        if u2 > 0:
            blit(frame, self.site, (self.W - self.site.shape[1]) / 2, Y_TRY + self.try_pill.shape[0] - 6, alpha * u2)
        return frame
