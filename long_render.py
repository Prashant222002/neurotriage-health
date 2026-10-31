"""Phase 2: 16:9 long-video renderer (1920x1080).

Design goals
 * Built at midnight, slowly: renders chapter-by-chapter into separate segment files. If the run dies
   (timeout, OOM, busy runner) the retry skips every finished segment instead of starting over.
 * Chapter cards with 3D neural sphere + perspective floor, 3D bars, stat cards, end card (motion_graphics.py).
 * Clean lower-third captions (caption_styles.py), chapter chip, progress bar with chapter ticks.
Self-contained: only needs gfx / motion_graphics / caption_styles + ffmpeg.
"""
import hashlib
import json
import math
import random
import re
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import motion_graphics as mg
from caption_styles import StyledCaptions
from gfx import (BLUE, GREEN, MINT, blit, clamp01, ease_in_out, ease_out, ease_out_back, pill, rounded, scaled,
                 text_sprite)

W, H = 1920, 1080
STAT_RE = re.compile(r"(\d+(?:\.\d+)?)\s?(%|percent|x\b|X\b)")


def _log(*a):
    print(*a, flush=True)


# ----------------------------------------------------------------------------- timeline
def long_timeline(scenes, durs, card_sec=2.6, lead=0.25, outro_sec=7.0):
    """scenes: dicts with 'chapter'. durs: seconds of narration per scene.
    Returns starts[], segments[], total_t, voice_end. A chapter card is inserted before chapter 2, 3, ..."""
    starts = [0.0] * len(scenes)
    segs, t, cur_ch, cur = [], lead, None, None
    for i, (sc, d) in enumerate(zip(scenes, durs)):
        ch = sc.get("chapter", 1)
        if ch != cur_ch:
            if cur:
                cur["t1"] = t
                segs.append(cur)
            if cur_ch is not None:
                segs.append({"kind": "card", "t0": t, "t1": t + card_sec, "chapter": ch})
                t += card_sec
            cur = {"kind": "scenes", "t0": t if segs else 0.0, "t1": None, "idx": [], "chapter": ch}
            cur_ch = ch
        starts[i] = t
        cur["idx"].append(i)
        t += d + (0.28 if i + 1 < len(scenes) and scenes[i + 1].get("chapter", 1) == ch else 0.5)
    cur["t1"] = t
    segs.append(cur)
    voice_end = t
    segs.append({"kind": "outro", "t0": t, "t1": t + outro_sec})
    return starts, segs, t + outro_sec, voice_end


def chapters_text(chapters, scenes, starts):
    """YouTube chapter list ('00:00 Name'). Needs >=3 chapters; first at 00:00."""
    first = {}
    for i, sc in enumerate(scenes):
        first.setdefault(sc.get("chapter", 1), starts[i])
    lines = []
    for ci, name in enumerate(chapters, 1):
        if ci not in first:
            continue
        s = 0 if ci == 1 else int(first[ci])
        lines.append(f"{s // 60:02d}:{s % 60:02d} {name}")
    return "\n".join(lines) if len(lines) >= 3 else ""


# ----------------------------------------------------------------------------- shots
class FallbackBG:
    """No usable stock clip -> 3D motion-graphic background (floor + rotating neural sphere)."""

    def __init__(self, fps, seed):
        self.fps, self.i, self.seed = fps, 0, seed
        self.bg = mg.gradient_bg(W, H)
        self.sph = mg.NeuralSphere(int(H * 0.78), seed=seed)

    def next(self):
        t = self.i / self.fps
        self.i += 1
        f = self.bg.copy()
        mg.perspective_floor(f, t)
        s = self.sph.render(t, strength=0.9)
        x = W * (0.60 if self.seed % 2 else 0.04)
        blit(f, s, x, H * 0.08)
        return f


class LShot:
    CAMS = ["in", "out", "left", "right", "up"]

    def __init__(self, fps, frames, rng, clip=None, seed=0, cam=None):
        self.fps, self.n, self.i = fps, frames, 0
        self.cam = cam or rng.choice(self.CAMS)
        self.proc, self.bg, self.last = None, None, None
        self.lut = None
        if clip is None:
            self.bg = FallbackBG(fps, seed)
            return
        need = frames / fps + 0.15
        avail = max(0.2, clip["dur"] - 0.2)
        speed, loop = 1.0, False
        if avail < need:
            if avail / need >= 0.7:
                speed = avail / need
            else:
                loop = True
        start = 0.0 if loop else rng.uniform(0.1, max(0.1, clip["dur"] - need * speed - 0.15))
        vf = (f"setpts=PTS/{speed:.4f},fps={fps},scale={W}:{H}:force_original_aspect_ratio=increase:flags=bicubic,"
              f"crop={W}:{H}")
        cmd = (["ffmpeg", "-v", "error", "-threads", "2"] + (["-stream_loop", "-1"] if loop else []) +
               ["-ss", f"{start:.3f}", "-i", str(clip["path"]), "-vf", vf, "-frames:v", str(frames + 2), "-an",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=W * H * 3 * 2)

    def _read(self):
        if self.bg is not None:
            return self.bg.next()
        buf = self.proc.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            return self.last if self.last is not None else np.zeros((H, W, 3), np.uint8)
        return np.frombuffer(buf, np.uint8).reshape(H, W, 3)

    def next(self):
        raw = self._read()
        if self.lut is None:                         # match brightness of first frame to a common target
            lum = float(cv2.cvtColor(raw, cv2.COLOR_RGB2GRAY).mean()) / 255.0
            g = float(np.clip(math.log(0.44) / math.log(max(lum, 0.06)), 0.80, 1.22))
            self.lut = np.array([255 * ((x / 255.0) ** g) for x in range(256)], np.uint8)
        self.last = raw
        e = ease_in_out(self.i / max(1, self.n - 1))
        s, tx, ty = 1.0, 0.0, 0.0
        if self.cam == "in":
            s = 1.0 + 0.07 * e
        elif self.cam == "out":
            s = 1.07 - 0.07 * e
        elif self.cam == "left":
            s, tx = 1.06, (0.5 - e) * 0.04 * W
        elif self.cam == "right":
            s, tx = 1.06, (e - 0.5) * 0.04 * W
        else:
            s, ty = 1.06, (0.5 - e) * 0.035 * H
        s *= 1 + 0.05 * (1 - ease_out(self.i / (0.25 * self.fps)))
        M = np.float32([[s, 0, (1 - s) * W / 2 + tx], [0, s, (1 - s) * H / 2 + ty]])
        out = cv2.warpAffine(raw, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        self.i += 1
        return cv2.LUT(out, self.lut) if self.bg is None else out

    def close(self):
        if self.proc:
            try:
                self.proc.stdout.close()
                self.proc.kill()
                self.proc.wait(timeout=5)
            except Exception:
                pass


class LScene:
    def __init__(self, a, b, fps, clips, seed):
        self.a, self.b, self.n, self.fps = a, b, b - a, fps
        self.rng, self.seed, self.clips, self.cur = random.Random(seed), seed, clips, 0
        if len(clips) >= 2 and self.n >= int(4.5 * fps):
            n1 = int(self.n * self.rng.uniform(0.45, 0.58))
            self.plan = [(n1, clips[0]), (self.n - n1, clips[1])]
        else:
            self.plan = [(self.n, clips[0] if clips else None)]
        prev, self.cams = None, []
        for _ in self.plan:
            c = self.rng.choice([x for x in LShot.CAMS if x != prev])
            self.cams.append(c)
            prev = c
        self.shot, self.left = None, 0

    def frame(self):
        if self.shot is None or (self.left <= 0 and self.cur < len(self.plan)):
            if self.shot:
                self.shot.close()
            n, clip = self.plan[self.cur]
            self.shot = LShot(self.fps, n + 2, self.rng, clip, self.seed + self.cur, self.cams[self.cur])
            self.left, self.cur = n, self.cur + 1
        self.left -= 1
        return self.shot.next()

    def close(self):
        if self.shot:
            self.shot.close()
            self.shot = None


# ----------------------------------------------------------------------------- overlays
def _scrim():
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    x = np.linspace(-1, 1, W, dtype=np.float32)[None, :]
    m = 1.0 - 0.52 * np.clip((y - 0.55) / 0.45, 0, 1) ** 1.4 - 0.18 * np.clip(x ** 2, 0, 1) - 0.10 * np.clip(0.2 - y, 0, 1)
    return np.repeat(np.clip(m * 255, 0, 255).astype(np.uint8)[..., None], 3, axis=2)


class LongHUD:
    def __init__(self, brand, chapters, voice_end, assets):
        self.voice_end, self.chapters = voice_end, chapters
        self.chips = {i: pill(f"CH {i}/{len(chapters)}  \u2022  {n.upper()}", 30, BLUE, GREEN, 28, 13)
                      for i, n in enumerate(chapters, 1)}
        self.logo = None
        lp = Path(assets) / "logo.png"
        if lp.exists():
            self.logo = np.array(Image.open(lp).convert("RGBA").resize((92, 92), Image.LANCZOS))
        self.brand = text_sprite(brand.upper(), 30, (235, 242, 255), 0, shadow=True)
        self.bar_bg = np.full((7, W - 120, 4), (255, 255, 255, 60), np.uint8)
        self.bar_fg = np.zeros((7, W - 120, 4), np.uint8)
        for ch in range(3):
            self.bar_fg[..., ch] = np.linspace(BLUE[ch], MINT[ch], W - 120)[None, :]
        self.bar_fg[..., 3] = 255

    def draw(self, f, t, chapter, chapter_t0, ticks):
        bw = W - 120
        blit(f, self.bar_bg, 60, H - 34, 0.9)
        wpx = int(bw * clamp01(t / max(1e-6, self.voice_end)))
        if wpx > 2:
            blit(f, self.bar_fg[:, :wpx], 60, H - 34, 1.0)
        for tk in ticks:
            x = 60 + int(bw * tk / self.voice_end)
            f[H - 36:H - 25, x:x + 2] = 255
        if self.logo is not None:
            blit(f, self.logo, W - 60 - 92, 38, 0.85)
        else:
            blit(f, self.brand, W - 60 - self.brand.shape[1], 30, 0.8)
        u = t - chapter_t0
        if 0 <= u < 5.0 and chapter in self.chips:
            a = ease_out(u / 0.5) * (1 - clamp01((u - 4.4) / 0.6))
            chip = self.chips[chapter]
            blit(f, chip, 46 - (1 - ease_out(u / 0.5)) * 120, 34, a)


# ----------------------------------------------------------------------------- renderer
class LongRenderer:
    def __init__(self, scenes, res, starts, segs, total_t, voice_end, chapters, workdir, *, fps=24, brand="NeuroTriage",
                 site="neurotriage.in", assets="assets", caption_style="clean", preset="medium", crf=19,
                 end_line1="Subscribe karo", end_line2="Roz ek naya MBBS + brain concept", seed=11, log=_log):
        self.scenes, self.res, self.starts, self.segs = scenes, res, starts, segs
        self.total_t, self.voice_end, self.chapters = total_t, voice_end, chapters
        self.work = Path(workdir)
        self.work.mkdir(parents=True, exist_ok=True)
        self.fps, self.preset, self.crf, self.log, self.seed = fps, preset, crf, log, seed
        self.hud = LongHUD(brand, chapters, voice_end, assets)
        self.scrim = _scrim()
        self.end = mg.EndCard(W, H, brand, site, end_line1, end_line2)
        words = []
        for i, (_, _, ws) in enumerate(res):
            words += [(w, starts[i] + s, starts[i] + e) for (w, s, e) in ws]
        style = caption_style if caption_style != "auto" else "clean"
        self.caps = StyledCaptions(words, style, W, H, max_words=7, max_chars=44, size=54, maxw=1560, upper=False)
        self.ticks = [starts[next(i for i, s in enumerate(scenes) if s.get("chapter", 1) == c)]
                      for c in range(2, len(chapters) + 1)
                      if any(s.get("chapter", 1) == c for s in scenes)]
        self.cards = {}
        self.stats = {}
        for i, sc in enumerate(scenes):
            txt = sc.get("text_en") or sc["text"]
            m = STAT_RE.search(sc["text"]) or STAT_RE.search(txt)
            if m:
                unit = "%" if m.group(2) in ("%", "percent") else "x"
                label = (sc.get("emphasis") or "key number").strip()[:34]
                self.stats[i] = mg.StatCard(f"{m.group(1)}{unit}", label)
        self.emph = {}
        for i, sc in enumerate(scenes):
            if sc.get("emphasis"):
                self.emph[i] = pill(sc["emphasis"].upper()[:30], 52, BLUE, GREEN, 40, 20, 238)
        key = json.dumps([[round(s, 2) for s in starts], [round(r[1], 2) for r in res], fps, preset, crf,
                          [sc["text"] for sc in scenes]], ensure_ascii=False)
        self.key = hashlib.sha1(key.encode()).hexdigest()[:12]

    # -- helpers
    def _enc(self, out):
        return subprocess.Popen(
            ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(self.fps),
             "-i", "-", "-c:v", "libx264", "-preset", self.preset, "-crf", str(self.crf), "-pix_fmt", "yuv420p",
             "-profile:v", "high", "-g", str(self.fps * 2), "-threads", "0", str(out)], stdin=subprocess.PIPE)

    def _chapter_of(self, t):
        ch, t0 = 1, 0.0
        for i, sc in enumerate(self.scenes):
            if self.starts[i] <= t:
                ch, t0 = sc.get("chapter", 1), min(self.starts[j] for j, s in enumerate(self.scenes)
                                                    if s.get("chapter", 1) == sc.get("chapter", 1))
        return ch, t0

    def _overlays(self, f, t, scene_i):
        f[:] = cv2.multiply(f, self.scrim, scale=1 / 255.0)
        sc_t = t - self.starts[scene_i]
        if scene_i in self.stats and 0.5 <= sc_t < 4.2:
            u = sc_t - 0.5
            card = self.stats[scene_i].render(u / 1.2)
            k = 0.85 + 0.15 * ease_out_back(u / 0.5)
            a = ease_out(u / 0.3) * (1 - clamp01((u - 3.4) / 0.3))
            card = scaled(card, k * 0.8)
            blit(f, card, W - card.shape[1] - 90, H * 0.20, a)
        if scene_i in self.emph and 0.25 <= sc_t < 2.6:
            u = sc_t - 0.25
            spr = self.emph[scene_i]
            a = ease_out(u / 0.3) * (1 - clamp01((u - 1.9) / 0.4))
            blit(f, spr, 70 - (1 - ease_out(u / 0.4)) * 400, H * 0.66, a)
        self.caps.draw(f, t, 1.0, cy=int(H * 0.865))
        ch, t0 = self._chapter_of(t)
        self.hud.draw(f, t, ch, t0, self.ticks)

    def _dip(self, f, g, n, first, last):
        k = 5
        if not first and g < k:
            f[:] = (f.astype(np.float32) * (g + 1) / (k + 1)).astype(np.uint8)
        if not last and g >= n - k:
            f[:] = (f.astype(np.float32) * (n - g) / (k + 1)).astype(np.uint8)

    # -- segments
    def _frames_scenes(self, seg, first, last):
        fps = self.fps
        g0, g1 = int(round(seg["t0"] * fps)), int(round(seg["t1"] * fps))
        idx, half = seg["idx"], 3
        rs = []
        for j, i in enumerate(idx):
            a = g0 if j == 0 else int(round(self.starts[i] * fps))
            b = g1 if j + 1 == len(idx) else int(round(self.starts[idx[j + 1]] * fps))
            rs.append((i, LScene(max(g0, a - (half if j else 0)), min(g1, b + (half if j + 1 < len(idx) else 0)), fps,
                                 self.clips[i], self.seed + i * 7)))
        try:
            for g in range(g0, g1):
                active = [(i, r) for i, r in rs if r.a <= g < r.b]
                if not active:
                    active = [rs[-1]]
                fr = [(i, r.frame()) for i, r in active]
                if len(fr) == 1:
                    comp = fr[0][1]
                else:
                    p = clamp01((g - active[1][1].a + 1) / 7.0)
                    comp = cv2.addWeighted(fr[0][1], 1 - p, fr[1][1], p, 0)
                comp = np.ascontiguousarray(comp)
                cur_i = fr[-1][0] if len(fr) == 2 and g - active[1][1].a >= 3 else fr[0][0]
                self._overlays(comp, g / fps, cur_i)
                self._dip(comp, g - g0, g1 - g0, first, last)
                yield comp
                for i, r in rs:
                    if g == r.b - 1:
                        r.close()
        finally:
            for _, r in rs:
                r.close()

    def _frames_card(self, seg, first, last):
        fps = self.fps
        n = int(round((seg["t1"] - seg["t0"]) * fps))
        ci = seg["chapter"]
        card = mg.ChapterCard(W, H, ci, len(self.chapters), self.chapters[ci - 1], seed=ci)
        for g in range(n):
            f = card.render(g / fps, n / fps)
            self._dip(f, g, n, first, last)
            yield f

    def _frames_outro(self, seg, first, last):
        fps = self.fps
        n = int(round((seg["t1"] - seg["t0"]) * fps))
        for g in range(n):
            f = self.end.render(g / fps)
            if g < 8:
                f[:] = (f.astype(np.float32) * (g + 1) / 9).astype(np.uint8)
            yield f

    def render(self, clips, out_video):
        self.clips = clips
        marker_key = self.work / "seg_key.txt"
        if not marker_key.exists() or marker_key.read_text() != self.key:
            for p in self.work.glob("seg_*"):
                p.unlink()
            marker_key.write_text(self.key)
        parts, t_start = [], time.time()
        for k, seg in enumerate(self.segs):
            part = self.work / f"seg_{k:02d}.mp4"
            ok = self.work / f"seg_{k:02d}.ok"
            parts.append(part)
            if ok.exists() and part.exists():
                self.log(f"[long] segment {k + 1}/{len(self.segs)} already done -> skip")
                continue
            self.log(f"[long] segment {k + 1}/{len(self.segs)} ({seg['kind']}, {seg['t1'] - seg['t0']:.0f}s)...")
            gen = {"scenes": self._frames_scenes, "card": self._frames_card, "outro": self._frames_outro}[seg["kind"]]
            enc = self._enc(part)
            try:
                n = 0
                for f in gen(seg, k == 0, k == len(self.segs) - 1):
                    enc.stdin.write(f.tobytes())
                    n += 1
                    if n % 240 == 0:
                        self.log(f"   seg {k + 1}: {n} frames, {time.time() - t_start:.0f}s elapsed")
                enc.stdin.close()
                enc.wait()
            except BaseException:
                try:
                    enc.kill()
                except Exception:
                    pass
                part.unlink(missing_ok=True)
                raise
            if enc.returncode != 0:
                part.unlink(missing_ok=True)
                raise RuntimeError("ffmpeg segment encode failed")
            ok.write_text("ok")
        lst = self.work / "concat.txt"
        lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                        str(out_video)], check=True)
        self.log(f"[long] video-only ready: {out_video} ({time.time() - t_start:.0f}s)")
        return out_video


# ----------------------------------------------------------------------------- thumbnail
def make_thumbnail(text, out_path, brand="NeuroTriage", frame_rgb=None):
    """1280x720 thumbnail. text: <=4 words. frame_rgb optional background (any size)."""
    tw, th = 1280, 720
    if frame_rgb is not None:
        bg = cv2.resize(frame_rgb, (tw, th), interpolation=cv2.INTER_AREA)
        bg = (bg.astype(np.float32) * 0.55).astype(np.uint8)
    else:
        bg = mg.gradient_bg(tw, th)
    g = np.linspace(1.0, 0.0, tw, dtype=np.float32)[None, :, None]
    bg = np.clip(bg.astype(np.float32) * (0.45 + 0.55 * (1 - g)) , 0, 255).astype(np.uint8)
    s = mg.NeuralSphere(520, seed=3).render(1.3, strength=0.9)
    blit(bg, s, tw - 520 - 20, 100)
    words = text.upper().split()[:4]
    lines = [" ".join(words[:2]), " ".join(words[2:])] if len(words) > 2 else [" ".join(words)]
    y = 150 if len(lines) == 2 else 230
    for i, ln in enumerate(l for l in lines if l):
        spr = text_sprite(ln, 150 if len(ln) < 11 else 118, (255, 230, 90) if i else (255, 255, 255), stroke=8)
        blit(bg, spr, 40, y)
        y += spr.shape[0] * 0.78
    blit(bg, pill(brand.upper(), 34, BLUE, GREEN, 30, 12), 30, th - 100)
    cv2.imwrite(str(out_path), bg[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 90])
    return out_path
