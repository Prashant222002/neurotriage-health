"""Phase 2: procedural 3D + motion graphics (pure numpy / OpenCV / PIL, no extra dependencies).

  NeuralSphere   rotating 3D neuron network (perspective projection, depth fade, travelling signal pulses)
  perspective_floor(frame, t)   scrolling 3D grid floor with vanishing point
  Bars3D         isometric 3D bar chart that grows in
  StatCard       glass card with a counting-up number
  ChapterCard    full-frame chapter title animation (floor + sphere + sliding title)
  EndCard        outro (subscribe + site) for long videos
Every class draws onto an RGB uint8 frame of any size, so it works for 16:9 and 9:16.
"""
import math
import re

import cv2
import numpy as np
from PIL import Image, ImageDraw

from gfx import (BLUE, GREEN, MINT, NAVY, blit, clamp01, ease_in_out, ease_out, ease_out_back, font,
                 pill, rounded, text_sprite, wrap_lines)


# ----------------------------------------------------------------------------- 3D neural sphere
class NeuralSphere:
    def __init__(self, size=640, seed=1, n=84, k=3, c1=BLUE, c2=MINT):
        self.size, self.c1, self.c2 = size, np.array(c1, np.float32), np.array(c2, np.float32)
        r = np.random.default_rng(seed)
        i = np.arange(n) + 0.5
        phi = np.arccos(1 - 2 * i / n)
        th = math.pi * (1 + 5 ** 0.5) * i
        self.p = np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], 1).astype(np.float32)
        d = ((self.p[:, None] - self.p[None]) ** 2).sum(-1)
        edges = set()
        for a in range(n):
            for b in np.argsort(d[a])[1:k + 1]:
                edges.add((min(a, int(b)), max(a, int(b))))
        self.e = np.array(sorted(edges))
        self.phase = r.uniform(0, 1, len(self.e))
        self.spd = r.uniform(0.25, 0.7, len(self.e))
        self.seed = seed

    def _project(self, t, tilt):
        ay, ax = t * 0.38 + self.seed, tilt + 0.12 * math.sin(t * 0.5)
        cy_, sy_, cx_, sx_ = math.cos(ay), math.sin(ay), math.cos(ax), math.sin(ax)
        x, y, z = self.p[:, 0], self.p[:, 1], self.p[:, 2]
        x1, z1 = x * cy_ + z * sy_, -x * sy_ + z * cy_
        y2, z2 = y * cx_ - z1 * sx_, y * sx_ + z1 * cx_
        persp = 3.3 / (3.3 - z2)
        s = self.size
        return (s / 2 + x1 * persp * s * 0.33, s / 2 + y2 * persp * s * 0.33, z2)

    def render(self, t, tilt=0.35, strength=1.0):
        s = self.size
        img = np.zeros((s, s, 3), np.float32)
        px, py, pz = self._project(t, tilt)
        for (a, b), ph, sp in zip(self.e, self.phase, self.spd):
            depth = (pz[a] + pz[b]) / 2
            k = 0.25 + 0.75 * (depth + 1) / 2
            col = (self.c1 * (1 - (depth + 1) / 2) + self.c2 * ((depth + 1) / 2)) * k * 0.9
            cv2.line(img, (int(px[a]), int(py[a])), (int(px[b]), int(py[b])), tuple(float(c) for c in col), 1, cv2.LINE_AA)
            u = (t * sp + ph) % 1.0                                   # travelling signal
            qx, qy = px[a] + (px[b] - px[a]) * u, py[a] + (py[b] - py[a]) * u
            cv2.circle(img, (int(qx), int(qy)), 3, tuple(float(c) for c in (255 * k, 255 * k, 255 * k)), -1, cv2.LINE_AA)
        order = np.argsort(pz)
        for i in order:
            k = 0.3 + 0.7 * (pz[i] + 1) / 2
            rad = max(1, int(2 + 4 * k * s / 640))
            col = self.c2 * k + 40 * k
            cv2.circle(img, (int(px[i]), int(py[i])), rad, tuple(float(c) for c in col), -1, cv2.LINE_AA)
        glow = cv2.GaussianBlur(img, (0, 0), s / 55)
        out = np.clip(img + glow * 1.1, 0, 255)
        a = np.clip(out.max(-1) * 1.5, 0, 255) * strength
        rgba = np.dstack([out, a]).astype(np.uint8)
        return rgba


# ----------------------------------------------------------------------------- 3D floor grid
def perspective_floor(frame, t, horizon=0.58, color=(70, 140, 255), alpha=0.35, lines=16):
    h, w = frame.shape[:2]
    layer = np.zeros_like(frame)
    hy, vx = int(h * horizon), w // 2
    for i in range(-lines, lines + 1):
        cv2.line(layer, (vx, hy), (int(vx + i * w * 0.28), h), color, 1, cv2.LINE_AA)
    for j in range(14):                                               # horizontal lines scroll toward camera
        u = ((j + (t * 0.55) % 1.0) / 14.0) ** 2.2
        y = int(hy + u * (h - hy))
        cv2.line(layer, (0, y), (w, y), tuple(int(c * (0.25 + u)) for c in color), 1, cv2.LINE_AA)
    fade = np.linspace(0, 1, h - hy, dtype=np.float32)[:, None, None] ** 0.6
    sub = layer[hy:].astype(np.float32) * fade
    frame[hy:] = np.clip(frame[hy:].astype(np.float32) + sub * alpha * 2.2, 0, 255).astype(np.uint8)
    return frame


def gradient_bg(w, h, top=(12, 22, 52), bottom=(4, 8, 22)):
    g = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    img = np.array(top, np.float32) * (1 - g) + np.array(bottom, np.float32) * g
    return np.broadcast_to(img, (h, w, 3)).astype(np.uint8).copy()


# ----------------------------------------------------------------------------- 3D bars
class Bars3D:
    def __init__(self, labels, values, w=980, h=560, c1=BLUE, c2=GREEN):
        self.labels, self.values, self.w, self.h = labels, values, w, h
        self.c1, self.c2 = c1, c2

    def render(self, p):
        w, h, n = self.w, self.h, len(self.values)
        img = np.zeros((h, w, 4), np.uint8)
        vmax = max(self.values) or 1
        slot = (w - 80) / n
        bw = slot * 0.52
        dx, dy = bw * 0.38, bw * 0.30
        base_y = h - 90
        maxh = h - 190
        pil_labels = []
        for i, v in enumerate(self.values):
            u = ease_out_back(clamp01(p * 1.6 - i * 0.18), 1.2)
            bh = max(2, maxh * (v / vmax) * u)
            x0 = 40 + i * slot + (slot - bw) / 2
            t = i / max(1, n - 1)
            col = np.array(self.c1) * (1 - t) + np.array(self.c2) * t
            front = [int(c) for c in col] + [255]
            top = [int(min(255, c * 1.25 + 25)) for c in col] + [255]
            side = [int(c * 0.62) for c in col] + [255]
            xa, xb, yt = x0, x0 + bw, base_y - bh
            cv2.fillPoly(img, [np.int32([[xa, base_y], [xb, base_y], [xb, yt], [xa, yt]])], front, cv2.LINE_AA)
            cv2.fillPoly(img, [np.int32([[xa, yt], [xb, yt], [xb + dx, yt - dy], [xa + dx, yt - dy]])], top, cv2.LINE_AA)
            cv2.fillPoly(img, [np.int32([[xb, base_y], [xb + dx, base_y - dy], [xb + dx, yt - dy], [xb, yt]])], side, cv2.LINE_AA)
            pil_labels.append((x0 + bw / 2, yt - dy - 14, f"{v:g}", base_y + 30, self.labels[i], u))
        pim = Image.fromarray(img, "RGBA")
        d = ImageDraw.Draw(pim)
        fv, fl = font(34), font(26, False)
        for cx, vy, vt, ly, lt, u in pil_labels:
            if u > 0.55:
                tw = d.textlength(vt, font=fv)
                d.text((cx - tw / 2, vy - 36), vt, font=fv, fill=(255, 255, 255, int(255 * clamp01((u - 0.55) / 0.3))))
            tw = d.textlength(lt, font=fl)
            d.text((cx - tw / 2, ly), lt, font=fl, fill=(200, 210, 230, 255))
        return np.array(pim)


# ----------------------------------------------------------------------------- stat card
class StatCard:
    """label + big number that counts up. text like '73%', '2.5x', '1 in 20'."""

    def __init__(self, text, label, w=620, h=300):
        m = re.search(r"\d+(?:\.\d+)?", text)
        self.pre, self.post = (text[:m.start()], text[m.end():]) if m else (text, "")
        self.val = float(m.group()) if m else None
        self.dec = len(m.group().split(".")[1]) if m and "." in m.group() else 0
        self.label, self.w, self.h = label, w, h
        self.bg = Image.fromarray(rounded(w, h, (18, 30, 62), (10, 18, 40), 34, 225), "RGBA")
        ImageDraw.Draw(self.bg).rounded_rectangle([2, 2, w - 3, h - 3], 34, outline=BLUE + (255,), width=3)

    def render(self, p):
        u = ease_out(clamp01(p * 1.4))
        shown = self.pre + (f"{self.val * u:.{self.dec}f}" if self.val is not None else "") + self.post
        im = self.bg.copy()
        d = ImageDraw.Draw(im)
        f1 = font(120)
        while d.textlength(shown, font=f1) > self.w - 60 and f1.size > 50:
            f1 = font(f1.size - 8)
        d.text(((self.w - d.textlength(shown, font=f1)) / 2, 36), shown, font=f1, fill=MINT + (255,))
        f2 = font(36, False)
        lab = self.label
        d.text(((self.w - d.textlength(lab, font=f2)) / 2, self.h - 82), lab, font=f2, fill=(220, 228, 245, 255))
        return np.array(im)


# ----------------------------------------------------------------------------- chapter card
class ChapterCard:
    def __init__(self, w, h, index, total, title, seed=1):
        self.w, self.h, self.index, self.total, self.title = w, h, index, total, title
        sz = int(min(h * 0.92, w * 0.5))
        self.sphere = NeuralSphere(sz, seed=seed)
        self.bg = gradient_bg(w, h)
        self.tag = pill(f"CHAPTER {index:02d}", int(h * 0.034), BLUE, GREEN, 30, 14)
        words = title.upper().split()
        fs = int(h * 0.105)
        while True:
            f = font(fs)
            widths = [f.getlength(x) for x in words]
            lines = wrap_lines(words, widths, f.getlength(" "), w * 0.52)
            if lines or fs <= int(h * 0.05):
                break
            fs -= 6
        lines = lines or [list(range(len(words)))]
        self.lines = [text_sprite(" ".join(words[i] for i in ln), fs, (255, 255, 255), 0, shadow=True) for ln in lines]

    def render(self, t, dur):
        frame = self.bg.copy()
        perspective_floor(frame, t)
        sph = self.sphere.render(t, strength=0.95 * ease_out(t / 0.8))
        blit(frame, sph, self.w * 0.97 - sph.shape[1], (self.h - sph.shape[0]) / 2)
        x0 = self.w * 0.07
        ut = ease_out(t / 0.5)
        blit(frame, self.tag, x0 - 20 - (1 - ut) * 160, self.h * 0.27, ut)
        y = self.h * 0.27 + self.tag.shape[0] + 10
        for i, spr in enumerate(self.lines):
            u = ease_out((t - 0.18 - i * 0.12) / 0.55)
            blit(frame, spr, x0 - 24, y + (1 - u) * 50, u)
            y += spr.shape[0] * 0.86
        lw = int(self.w * 0.20 * ease_out((t - 0.5) / 0.7))                # accent line grows
        if lw > 2:
            cv2.line(frame, (int(x0), int(y + 18)), (int(x0) + lw, int(y + 18)), MINT, 5, cv2.LINE_AA)
        for i in range(self.total):                                        # progress dots
            cx = int(x0 + 18 + i * 44)
            cv2.circle(frame, (cx, int(self.h * 0.88)), 11 if i + 1 == self.index else 7,
                       MINT if i + 1 <= self.index else (90, 105, 140), -1, cv2.LINE_AA)
        out = ease_in_out((t - (dur - 0.35)) / 0.35)
        return (frame.astype(np.float32) * (1 - 0.0 * out)).astype(np.uint8)


class EndCard:
    def __init__(self, w, h, brand, site, line1="Subscribe karo", line2="Roz ek naya MBBS + brain concept", logo=None):
        self.w, self.h = w, h
        self.logo = logo
        self.bg = gradient_bg(w, h)
        self.sphere = NeuralSphere(int(h * 0.9), seed=5)
        self.l1 = text_sprite(line1.upper(), int(h * 0.11), (255, 255, 255))
        self.l2 = text_sprite(line2, int(h * 0.043), (205, 218, 240), shadow=False, heavy=False)
        self.site = pill(site, int(h * 0.045), BLUE, GREEN, 40, 18)
        self.brand = text_sprite(brand.upper(), int(h * 0.05), MINT, shadow=False)

    def render(self, t):
        f = self.bg.copy()
        perspective_floor(f, t)
        sph = self.sphere.render(t, strength=0.9)
        blit(f, sph, self.w * 0.97 - sph.shape[1], (self.h - sph.shape[0]) / 2)
        x0 = self.w * 0.07 - 24
        for i, (spr, y) in enumerate(((self.brand, 0.22), (self.l1, 0.32), (self.l2, 0.55), (self.site, 0.68))):
            u = ease_out((t - i * 0.18) / 0.5)
            blit(f, spr, x0, self.h * y + (1 - u) * 40, u)
        if self.logo is not None:                      # circle logo above the brand name, fades in first
            u = ease_out(t / 0.6)
            pad = int(self.logo.shape[0] * 0.22 / 1.44)
            blit(f, self.logo, x0 - pad + 8, self.h * 0.045 + (1 - u) * 30, u * 0.95)
        return f
