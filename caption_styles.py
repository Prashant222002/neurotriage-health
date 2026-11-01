"""Phase 2: new caption styles. One class, many looks. Same API as bot.Captions: .draw(frame, t, alpha, cy).

Styles
  pop      white caps, active word mint, pop-in           (v7 look)
  box      active word sits on a solid mint box (black text)  - "hormozi" look
  karaoke  whole phrase on a dark glass bar, active word fills mint
  bounce   every word drops in with a bounce as it is spoken, past words stay
  glow     neon text, active word glows + scales up
  clean    long-video lower-third: sentence case, 2 lines, soft bar (use with position='bottom')
auto -> style rotates by day so the feed does not look repetitive.
"""
import re
from datetime import date

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from gfx import (MINT, blit, clamp01, ease_out, ease_out_back, font, scaled, wrap_lines)

STYLES = ["pop", "box", "karaoke", "bounce", "glow"]


def pick_style(name="auto", today=None):
    name = (name or "auto").lower()
    if name in STYLES + ["clean"]:
        return name
    d = today or date.today()
    return STYLES[d.toordinal() % len(STYLES)]

DASH_END = re.compile(r"[-\u2010-\u2014]$")      # word ends with a hyphen/dash  -> must stay with the next word
DASH_START = re.compile(r"^[-\u2010-\u2014]")


def paginate(words, max_words=4, max_chars=26, upper=True):
    """words: [(text, start, end)] -> pages of (shown_text, start, end, raw). Shared by every caption style.
    Round 5: a page never ends on 'MOVE-' (hyphen/dash glued to the next word), so no half-finished text on screen."""
    pages, cur = [], []
    for w in words:
        raw = w[0]
        txt = raw.rstrip(".,") if re.search(r"www|\.in", raw) else re.sub(r"[.,]+$", "", raw)
        if cur:
            gap = w[1] - cur[-1][2]
            chars = sum(len(c[0]) for c in cur) + len(txt)
            glued = bool(DASH_END.search(cur[-1][0]) or DASH_START.search(txt))
            hard = re.search(r"[.?!;:]$", cur[-1][3]) or gap > 0.45
            over = len(cur) >= max_words or chars > max_chars
            if hard or (over and not (glued and len(cur) < max_words + 2)):
                pages.append(cur)
                cur = []
        cur.append((txt.upper() if (upper and "." not in txt) else txt, w[1], w[2], raw))
    if cur:
        pages.append(cur)
    merged = []
    for pg in pages:                                 # no one-word orphans
        if (merged and len(pg) <= 2 and len(merged[-1]) <= max_words - 1      # v17: no 1-2 word orphans like "HAI" / "SE JODO"
                and sum(len(c[0]) for c in merged[-1]) + sum(len(c[0]) for c in pg) <= max_chars + 6
                and pg[0][1] - merged[-1][-1][2] < 0.9):
            merged[-1].extend(pg)
        else:
            merged.append(pg)
    for i in range(len(merged) - 1):                 # last safety net: a dangling dash joins the next page
        if DASH_END.search(merged[i][-1][0]) and merged[i + 1][0][1] - merged[i][-1][2] < 0.5:
            merged[i + 1] = merged[i] + merged[i + 1]
            merged[i] = []
    return [p for p in merged if p]


class StyledCaptions:
    def __init__(self, words, style="pop", W=1080, H=1920, max_words=4, max_chars=26, size=92, maxw=None, upper=True):
        """words: [(text, start, end)] in global seconds."""
        self.style, self.W, self.H, self.size = style, W, H, size
        self.maxw = maxw or int(W * 0.80)
        self.upper = upper and style != "clean"
        self.pages = paginate(words, max_words, max_chars, self.upper)
        self.starts = [p[0][1] for p in self.pages]
        self.ends = []
        for i, p in enumerate(self.pages):
            nxt = self.starts[i + 1] if i + 1 < len(self.pages) else 1e9
            self.ends.append(min(nxt, p[-1][2] + 0.22) if nxt - p[-1][2] > 0.35 else nxt)
        self._ck, self._cache = None, {}

    # ------------------------------------------------------------------ layout
    def _layout(self, words):
        size = self.size
        while True:
            f = font(size)
            sp = f.getlength(" ")
            widths = [f.getlength(w) for w in words]
            lines = wrap_lines(words, widths, sp, self.maxw)
            if lines:
                return f, sp, widths, lines, size
            size -= 6
            if size < 40:
                lines = [list(range(len(words) // 2 or 1)), list(range(len(words) // 2 or 1, len(words)))]
                return f, sp, widths, [l for l in lines if l], size

    def _sprite(self, pi, k, shown):
        """shown: how many words are visible (bounce style); k = active word index."""
        key = (pi, k, shown)
        if self._ck != pi:
            self._cache, self._ck = {}, pi
        if key in self._cache:
            return self._cache[key]
        words = [w[0] for w in self.pages[pi]]
        f, sp, widths, lines, size = self._layout(words)
        lh = int(size * 1.28)
        pad = 40
        st = self.style
        img = Image.new("RGBA", (self.W, lh * len(lines) + 2 * pad), (0, 0, 0, 0))
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d, dg = ImageDraw.Draw(img), ImageDraw.Draw(glow)
        if st in ("karaoke", "clean"):                    # one glass bar behind the whole phrase
            lw = max(sum(widths[i] for i in ln) + sp * (len(ln) - 1) for ln in lines)
            bx0, bx1 = (self.W - lw) / 2 - 36, (self.W + lw) / 2 + 36
            d.rounded_rectangle([bx0, pad - 10, bx1, pad + lh * len(lines) + 4], 38, fill=(8, 14, 30, 205))
        for li, idxs in enumerate(lines):
            lw = sum(widths[i] for i in idxs) + sp * (len(idxs) - 1)
            x, y = (self.W - lw) / 2, pad + li * lh
            for i in idxs:
                if st == "bounce" and i >= shown:
                    x += widths[i] + sp
                    continue
                act = i == k
                col, stroke = (255, 255, 255), 8
                if st == "pop":
                    col = MINT if act else col
                    d.text((x, y), words[i], font=f, fill=col + (255,), stroke_width=stroke, stroke_fill=(9, 14, 28, 255))
                elif st == "box":
                    if act:
                        d.rounded_rectangle([x - 16, y + 4, x + widths[i] + 16, y + size * 1.18], 22, fill=MINT + (255,))
                        d.text((x, y), words[i], font=f, fill=(8, 14, 28, 255))
                    else:
                        d.text((x, y), words[i], font=f, fill=(255, 255, 255, 255), stroke_width=stroke, stroke_fill=(9, 14, 28, 255))
                elif st == "karaoke":
                    col = MINT if act else (235, 240, 250)
                    d.text((x, y), words[i], font=f, fill=col + (255,))
                elif st == "bounce":
                    col = (255, 226, 90) if act else (255, 255, 255)
                    d.text((x, y), words[i], font=f, fill=col + (255,), stroke_width=stroke, stroke_fill=(9, 14, 28, 255))
                elif st == "glow":
                    col = MINT if act else (225, 235, 255)
                    if act:
                        dg.text((x, y), words[i], font=f, fill=MINT + (255,), stroke_width=6, stroke_fill=MINT + (255,))
                    d.text((x, y), words[i], font=f, fill=col + (255,), stroke_width=3, stroke_fill=(6, 12, 30, 255))
                else:  # clean
                    col = MINT if act else (255, 255, 255)
                    d.text((x, y), words[i], font=f, fill=col + (255,))
                x += widths[i] + sp
        if st == "glow":
            glow = glow.filter(ImageFilter.GaussianBlur(14))
            img = Image.alpha_composite(glow, img)
        elif st in ("pop", "bounce", "box"):
            sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
            sh.paste((0, 0, 0, 150), (0, 8), img.split()[3])
            img = Image.alpha_composite(sh.filter(ImageFilter.GaussianBlur(9)), img)
        out = np.array(img)
        self._cache[key] = out
        return out

    # ------------------------------------------------------------------ draw
    def draw(self, frame, t, alpha=1.0, cy=None):
        if not self.pages or alpha <= 0:
            return
        cy = cy if cy is not None else int(self.H * 0.63)
        pi = None
        for i in range(len(self.pages)):
            if self.starts[i] - 0.02 <= t < self.ends[i]:
                pi = i
        if pi is None:
            return
        page = self.pages[pi]
        k = 0
        for j, w in enumerate(page):
            if t >= w[1] - 0.02:
                k = j
        fps = 30.0
        u = (t - self.starts[pi]) * fps
        shown = k + 1 if self.style == "bounce" else len(page)
        spr = self._sprite(pi, k, shown)
        a = clamp01(u / 3.0) * alpha
        if self.style == "bounce":                              # newest word drops in with a bounce
            uw = (t - page[k][1]) * fps
            dy = (1 - ease_out_back(clamp01(uw / 8.0), 2.4)) * -34
            blit(frame, spr, (self.W - spr.shape[1]) / 2, cy - spr.shape[0] / 2 + dy, a)
            return
        if self.style == "glow":
            sc = 1.0
        elif self.style in ("karaoke", "clean"):
            sc = 1.0
            a = clamp01(u / 4.0) * alpha
        else:
            sc = 0.84 + 0.16 * ease_out_back(u / 7.0)
        spr = scaled(spr, sc)
        blit(frame, spr, (self.W - spr.shape[1]) / 2, cy - spr.shape[0] / 2, a)
