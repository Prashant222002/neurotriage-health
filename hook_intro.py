"""Round 5a: hook text from the very first frame (replaces the white flash intro).
Frame 0 already shows the hook on top of the first clip, so the feed preview / thumbnail is never white."""
import re

import numpy as np

from gfx import MINT, blit, clamp01, ease_out, font, scaled, text_sprite

HOLD = 2.3        # seconds the hook stays
FADE = 0.4
Y_TOP, Y_BOT = 430, 900


def hook_words(data):
    """best on-screen hook: script's hook_text -> kicker-less title start. 3-7 words, upper case."""
    h = re.sub(r"\s+", " ", str((data or {}).get("hook_text") or "")).strip(" .")
    if len(h.split()) < 2:
        h = str((data or {}).get("title_en") or (data or {}).get("title") or "")
        h = " ".join(re.sub(r"[#\"]", "", h).split()[:6])
    return h.upper()[:46]


def _lines(text, size, maxw):
    f = font(size)
    words, lines, cur = text.split(), [], []
    for w in words:
        if cur and f.getlength(" ".join(cur + [w])) > maxw:
            lines.append(" ".join(cur))
            cur = []
        cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


class HookText:
    def __init__(self, text, W=1080, size=112, maxw=900):
        self.W, self.text = W, (text or "").strip()
        self.sprites = []
        if not self.text:
            return
        lines = _lines(self.text, size, maxw)
        while len(lines) > 3 and size > 64:
            size -= 8
            lines = _lines(self.text, size, maxw)
        for i, ln in enumerate(lines):
            col = MINT if i == len(lines) - 1 and len(lines) > 1 else (255, 255, 255)
            self.sprites.append(text_sprite(ln, size, col, stroke=8))
        self.h = sum(s.shape[0] for s in self.sprites)

    def active(self, t):
        return bool(self.sprites) and t < HOLD + 0.05

    def draw(self, frame, t):
        if not self.active(t):
            return frame
        a = 1.0 - clamp01((t - (HOLD - FADE)) / FADE)               # full strength at t=0
        H = frame.shape[0]
        band = frame[Y_TOP - 60:Y_BOT + 60].astype(np.float32)       # soft dark scrim = readable on bright clips
        frame[Y_TOP - 60:Y_BOT + 60] = np.clip(band * (1 - 0.38 * a), 0, 255).astype(np.uint8)
        k = 1.0 + 0.07 * (1 - ease_out(t / 0.3))
        y = (Y_TOP + Y_BOT) / 2 - self.h * k / 2
        for s in self.sprites:
            s2 = scaled(s, k)
            blit(frame, s2, (self.W - s2.shape[1]) / 2, y, a)
            y += s2.shape[0]
        return frame
