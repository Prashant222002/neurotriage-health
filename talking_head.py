"""Round 8: TALKING-HEAD MODERN EDIT. Raw talking-head clip -> reel with word-by-word glow captions, silence cuts,
zoom punch-ins, topic-matched cards / screen-recording inserts (glow border) and shard / whip transitions.

  1. transcribe  : Groq Whisper (word times) -> fallback faster-whisper (local) -> or --words words.json
  2. silence cut : gaps > GAP_CUT removed (jump-cut rhythm, alternate 1.0x / 1.09x framing)
  3. plan        : LLM (Groq -> Gemini) reads the transcript and decides emphasis words + which card / insert goes WHERE
                   (title / terminal / profile / graph / insert). No key or LLM down -> keyword heuristic.
  4. render      : captions + punch zoom + cards + inserts + shard/whip + logo + end card, loudnorm -14 LUFS
Usage: python talking_head.py --video raw/clip.mp4 [--inserts a.mp4,b.png] [--style red|white] [--hook TEXT] [--handle @x]
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import brand_logo
import endcard
import hook_intro
import keyring
import variants
from caption_styles import paginate
from gfx import blit, clamp01, ease_in_out, ease_out, ease_out_back, font, rounded, scaled, wrap_lines
from raw_edit import probe, sh

ROOT = Path(__file__).parent
W, H, FPS = 1080, 1920, 30
GAP_CUT, PAD_A, PAD_B, MIN_SEG = 0.38, 0.07, 0.14, 0.45     # silence rule (s)
RED, RED2, WHITE = (255, 38, 64), (255, 110, 120), (255, 255, 255)
PANEL_CY, CAP_CY, PANEL_W, PANEL_H = int(H * .385), int(H * .745), 920, 1000
CHIP_TOP = int(H * .118)
KINDS = ("title", "terminal", "profile", "graph", "insert")
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def log(*a):
    print(*a, flush=True)


# ================================================================ 1. transcribe
def extract_audio(video, out):
    sh(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(out)])


def whisper_groq(audio, lang=""):
    import requests
    ring = keyring.ring("groq")
    for slot in ring.slots:
        try:
            with open(audio, "rb") as f:
                data = {"model": "whisper-large-v3-turbo", "response_format": "verbose_json",
                        "timestamp_granularities[]": "word", "temperature": "0",
                        "prompt": "Hinglish, Roman script. English tech words stay English."}
                if lang:
                    data["language"] = lang
                r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                  headers={"Authorization": f"Bearer {slot.value}"}, files={"file": f}, data=data, timeout=180)
            if r.status_code == 200:
                ws = [(w["word"].strip(), float(w["start"]), float(w["end"])) for w in r.json().get("words", []) if w["word"].strip()]
                if ws:
                    return ws
            log("[whisper] groq", r.status_code, r.text[:100])
        except Exception as e:
            log("[whisper] groq error:", str(e)[:100])
    return []


def whisper_local(audio, lang=""):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return []
    m = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = m.transcribe(str(audio), word_timestamps=True, language=lang or None,
                           initial_prompt="Hinglish, Roman script. English tech words stay English.")
    return [(w.word.strip(), float(w.start), float(w.end)) for s in segs for w in (s.words or []) if w.word.strip()]


def transcribe(video, tmp, lang="", words_json=""):
    if words_json:
        return [(w[0], float(w[1]), float(w[2])) for w in json.loads(Path(words_json).read_text(encoding="utf-8"))]
    a = Path(tmp) / "a.mp3"
    extract_audio(video, a)
    return whisper_groq(a, lang) or whisper_local(a, lang)


# ================================================================ 2. silence cut
def keep_segments(words, dur):
    segs = []
    for _, s, e in words:
        a, b = max(0, s - PAD_A), min(dur, e + PAD_B)
        if segs and a - segs[-1][1] <= GAP_CUT - PAD_A:
            segs[-1][1] = max(segs[-1][1], b)
        else:
            segs.append([a, b])
    out = []
    for s in segs:                                       # too-short segment joins its neighbour
        if out and s[1] - s[0] < MIN_SEG:
            out[-1][1] = s[1]
        else:
            out.append(s)
    return [tuple(s) for s in out]


def remap(words, segs):
    offs, o = [], 0.0
    for a, b in segs:
        offs.append(o)
        o += b - a
    res = []
    for t, s, e in words:
        for (a, b), off in zip(segs, offs):
            if a - 1e-6 <= s <= b + 1e-6:
                res.append((t, s - a + off, min(e, b) - a + off))
                break
    return res, offs, o


def enhance_filter(video):
    """Round 10: measure the footage (8 sampled frames) and lift only what is weak: dim / flat / soft picture.
    Well-lit footage gets just a light sharpen. TH_ENHANCE=off disables. Returns an ffmpeg filter snippet (starts with ',')."""
    if os.environ.get("TH_ENHANCE", "on").lower() == "off":
        return ""
    try:
        r = sh(["ffmpeg", "-v", "error", "-i", str(video), "-vf", "fps=2,scale=160:-2", "-frames:v", "8", "-f", "rawvideo", "-pix_fmt", "gray", "-"])
        a = np.frombuffer(r.stdout, np.uint8).astype(np.float32)
        if a.size < 1000:
            return ""
        m, p5, p95 = float(a.mean()), float(np.percentile(a, 5)), float(np.percentile(a, 95))
    except Exception:
        return ""
    br, gm, ct, sat = 0.0, 1.0, 1.0, 1.05
    if m < 125:                                   # dim: brighten (capped so skin does not wash out)
        d = (125 - m) / 255.0
        br, gm = min(0.10, d * .45), 1.0 + min(0.22, d * .9)
    elif m > 190:                                 # blown out
        gm = 0.92
    if p95 - p5 < 140:                            # flat: add contrast
        ct = 1.0 + min(0.14, (140 - (p95 - p5)) / 600.0)
    log(f"[th] enhance: luma {m:.0f} range {p5:.0f}-{p95:.0f} -> brightness {br:.3f} gamma {gm:.2f} contrast {ct:.2f}")
    return f",eq=brightness={br:.3f}:gamma={gm:.3f}:contrast={ct:.3f}:saturation={sat:.2f},unsharp=5:5:0.5:5:5:0.0"


def cut_video(video, info, segs, out, tmp):
    n = len(segs)
    f = ["[0:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d%s,fps=%d,split=%d%s" %
         (W, H, W, H, enhance_filter(video), FPS, n, "".join(f"[v{i}]" for i in range(n)))]
    if info["audio"]:
        f.append("[0:a]aresample=48000,asplit=%d%s" % (n, "".join(f"[a{i}]" for i in range(n))))
    cat = ""
    for i, (a, b) in enumerate(segs):
        f.append(f"[v{i}]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[tv{i}]")
        cat += f"[tv{i}]"
        if info["audio"]:
            f.append(f"[a{i}]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[ta{i}]")
            cat += f"[ta{i}]"
    f.append(f"{cat}concat=n={n}:v=1:a={1 if info['audio'] else 0}[ov]" + ("[oa]" if info["audio"] else ""))
    script = Path(tmp) / "cut.fc"
    script.write_text(";\n".join(f), encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-filter_complex_script", str(script), "-map", "[ov]"]
    cmd += ["-map", "[oa]", "-c:a", "aac", "-b:a", "192k"] if info["audio"] else ["-an"]
    sh(cmd + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "15", "-pix_fmt", "yuv420p", str(out)])


# ================================================================ 3. plan (topic-aware)
def _llm(prompt):
    import requests
    for slot in keyring.ring("groq").slots:
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {slot.value}"},
                              json={"model": "llama-3.3-70b-versatile", "temperature": 0.3, "response_format": {"type": "json_object"},
                                    "messages": [{"role": "user", "content": prompt}]}, timeout=90)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log("[plan] groq error:", str(e)[:90])
    for slot in keyring.ring("gemini").slots:
        try:
            r = requests.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                              params={"key": slot.value}, timeout=90,
                              json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}})
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            log("[plan] gemini error:", str(e)[:90])
    return None


def sentences(words):
    out, cur = [], []
    for w in words:
        if cur and (w[1] - cur[-1][2] > 0.5 or re.search(r"[.?!]$", cur[-1][0])):
            out.append(cur)
            cur = []
        cur.append(w)
    return out + ([cur] if cur else [])


H_RULES = [("profile", r"follow|subscribe|instagram|insta|page|channel|profile|handle|link in bio"),
           ("terminal", r"terminal|command|code|install|prompt|claude|bot|script|github|python|api|cursor|agent"),
           ("graph", r"\d+\s?%|percent|growth|badh|increase|revenue|results?|data|rank|views|score|fast|speed|zyada"),
           ("insert", r"screen|dekho|dekh|demo|app\b|website|dashboard|tool|result|example|yeh dekho|ye dekho")]
STOP = set("the and for you that this with have from your are was not but what when they will can all into just like then than also very kuch yeh woh hai hain nahi mera tera apna aap kaise kyun lekin toh bhi aur".split())


def heuristic_plan(words, dur, media, handle):
    ev, last = [], -9
    for s in sentences(words):
        txt = " ".join(w[0] for w in s).lower()
        t = s[0][1]
        if t < 2.0 or t > dur - 3 or t - last < 5.0:
            continue
        for kind, rx in H_RULES:
            if re.search(rx, txt):
                if kind == "insert" and not media:
                    continue
                e = {"at": t, "type": kind, "dur": min(3.2, max(2.0, s[-1][2] - t + 0.6)), "title": " ".join(w[0] for w in s[:4]).upper(),
                     "sub": "", "lines": [], "name": "NeuroTriage", "handle": handle, "values": [], "label": "", "media": ""}
                if kind == "terminal":
                    e["lines"] = ["$ " + " ".join(w[0] for w in s[:5]).lower(), "thinking...", "done"]
                ev.append(e)
                last = t
                break
    emph, lastw = [], -9
    for t, s, e in words:
        w = re.sub(r"\W", "", t).lower()
        if (len(w) >= 7 or re.search(r"\d", w)) and w not in STOP and s - lastw > 1.8:
            emph.append(w)
            lastw = s
    return {"hook": "", "emphasis": emph, "events": ev}


def make_plan(words, dur, media, handle):
    sents = sentences(words)
    tr = "\n".join(f"[{s[0][1]:.1f}s] " + " ".join(w[0] for w in s) for s in sents)
    names = ", ".join(m.name for m in media) or "(none)"
    prompt = f"""You edit a vertical talking-head reel ({dur:.1f}s). Transcript with start times:
{tr}

User screen-recording / image files available: {names}
Return ONLY JSON: {{"hook":"max 5 word hook or empty","emphasis":["important spoken words, max 1 per 2s"],
"events":[{{"at":seconds,"type":"title|terminal|profile|graph|insert","dur":2.0-3.4,"media":"filename (insert only)",
"title":"","sub":"","lines":["terminal lines, first starts with $"],"name":"","handle":"","values":[6 rising numbers],"label":""}}]}}
Rules: place each card EXACTLY when the spoken topic matches it (tool/AI/code -> terminal, follow/page/channel -> profile,
growth/numbers/results -> graph, product/app/demo shown by user file -> insert with the best matching filename, a named
topic/tool intro -> title). Max 1 event per 5s, none before 2s or in the last 3s, max {max(1, int(dur // 6))} events.
Roman-script text only. Do not invent stats; graph label must be generic."""
    raw = _llm(prompt)
    plan = None
    try:
        plan = json.loads(re.sub(r"^```json|```$", "", (raw or "").strip()).strip())
    except Exception:
        plan = None
    if not plan or not isinstance(plan.get("events"), list):
        log("[plan] LLM unavailable -> keyword heuristic")
        return heuristic_plan(words, dur, media, handle)
    plan["_by"] = "llm"
    return plan


def clean_events(plan, dur, media, handle):
    by = {m.name.lower(): m for m in media}
    out, last = [], -9
    for e in sorted(plan.get("events", []), key=lambda e: float(e.get("at", 0))):
        try:
            t, k = float(e["at"]), str(e.get("type", "")).lower()
        except Exception:
            continue
        if k == "title":                                  # Round 15: title/star card removed (looked cheap)
            continue
        if k not in KINDS or t < 1.8 or t > dur - 2.5 or t - last < 4.6:
            continue
        m = by.get(str(e.get("media", "")).lower())
        if k == "insert":
            if m is None and media:
                m = media[len([x for x in out if x["type"] == "insert"]) % len(media)]
            if m is None:
                continue
        e = dict(e)
        e.update(at=t, type=k, dur=min(3.6, max(1.8, float(e.get("dur") or 2.4))), media=m)
        e.setdefault("handle", handle)
        e["handle"] = e.get("handle") or handle
        out.append(e)
        last = t
    return out


GREET = {"namaste", "namaskar", "hello", "hi", "hey", "doston", "dosto", "friends", "guys", "welcome", "swagat", "aaj", "to", "toh", "so", "and", "ok", "okay", "chalo", "bhai", "dost"}


def auto_hook(words):
    """Round 10: a hook must be on screen from frame 0, so when neither the user nor the LLM gave one, build it from the first
    real sentence (greetings stripped, max 6 words). Last resort: generic curiosity line."""
    for s_ in sentences(words)[:2]:
        ws = [re.sub(r"[^\w']", "", w[0]) for w in s_]
        ws = [w for w in ws if w]
        while ws and ws[0].lower() in GREET:
            ws.pop(0)
        if len(ws) >= 2:
            return " ".join(ws[:6]).upper()
    return "END TAK DEKHO"


_STOP = set("this that with have from your there what when where which about would could should their they them then than into just like also very more most some been were being does done dont cant will yeh woh hai hain tha thi kya koi kuch aur lekin isliye mein main apne apna aapko hum tum aap kar karo karna raha rahi bahut sab abhi jaise toh".split())


def auto_tags(words, handle="", have=(), n=12):
    """Tags that always exist: AI tags first, then top spoken keywords, then base tags. Dedup, <=30 chars, total <=450 chars."""
    from collections import Counter
    cnt = Counter(re.sub(r"[^a-z0-9]", "", w[0].lower()) for w in words)
    kw = [k for k, c in cnt.most_common(40) if len(k) >= 5 and k not in _STOP and not k.isdigit()]
    base = ["shorts", "reels", re.sub(r"[^a-z0-9]", "", handle.lower())]
    out, tot = [], 0
    for t in [*have, *kw, *base]:
        t = str(t).lstrip("#").strip()[:30]
        if t and t.lower() not in [o.lower() for o in out] and tot + len(t) < 450:
            out.append(t); tot += len(t) + 1
        if len(out) >= n: break
    return out


def make_meta(words, plan, handle):
    """YouTube title / description / tags from what was actually said (LLM, else heuristic)."""
    txt = " ".join(w[0] for w in words)[:3500]
    raw = _llm(f"""Transcript of a short vertical video:\n{txt}\nReturn ONLY JSON {{"title":"max 70 chars, curiosity but honest, Roman script, no emoji spam",
"description":"2 short lines about the video + 'Follow {handle} for more' + 5 hashtags incl #Shorts","tags":["8-12 tags, no #"]}}""")
    try:
        m = json.loads(re.sub(r"^```json|```$", "", (raw or "").strip()).strip())
        if m.get("title"):
            return {"title": str(m["title"])[:95], "description": str(m.get("description", ""))[:4000],
                    "tags": auto_tags(words, handle, [str(t).lstrip("#")[:30] for t in m.get("tags", [])])}
    except Exception:
        pass
    first = (sentences(words) or [[("Video", 0, 0)]])[0]
    t = " ".join(w[0] for w in first)[:80].strip(" .,")
    return {"title": (t or "New video") + " #Shorts", "description": f"{t}\n\nFollow {handle} for more.\n#Shorts #ai #learning",
            "tags": auto_tags(words, handle, ["ai", "learning"])}


# ================================================================ 4. cards
_GP = {}


def glow_panel(img, glow=RED, r=34, bw=6):
    """RGB card art -> RGBA panel: rounded corners, red border, soft outer glow (glow+border layer cached per size)."""
    img = img.convert("RGB")
    w, h = img.size
    pad = 56
    key = (w, h, r, bw, glow)
    if key not in _GP:
        m = Image.new("L", (w * 2, h * 2), 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, w * 2 - 1, h * 2 - 1], r * 2, fill=255)
        g = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
        ImageDraw.Draw(g).rounded_rectangle([pad - 2, pad - 2, pad + w + 2, pad + h + 2], r + 2, outline=glow + (255,), width=bw + 10)
        base = Image.alpha_composite(Image.new("RGBA", g.size, (0, 0, 0, 0)), g.filter(ImageFilter.GaussianBlur(16)))
        bd = Image.new("RGBA", g.size, (0, 0, 0, 0))
        ImageDraw.Draw(bd).rounded_rectangle([pad - bw, pad - bw, pad + w + bw, pad + h + bw], r + bw, fill=glow + (255,))
        _GP[key] = (Image.alpha_composite(base, bd), m.resize((w, h), Image.LANCZOS))
    base, m = _GP[key]
    out = base.copy()
    card = img.convert("RGBA")
    card.putalpha(m)
    out.alpha_composite(card, (pad, pad))
    return np.array(out)


def _mono(size):
    from PIL import ImageFont
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
              "C:/Windows/Fonts/consolab.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return font(size)


def _bg(w, h, c1=(22, 16, 20), c2=(8, 6, 10)):
    a = np.linspace(0, 1, h)[:, None, None]
    arr = (np.array(c1) * (1 - a) + np.array(c2) * a) * np.ones((1, w, 1))
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def _star(d, cx, cy, r, col, rot=0.0):
    for i in range(6):                                    # 6-arm burst mark (generic, not a brand logo)
        a = rot + i * math.pi / 3
        d.line([cx - r * math.cos(a), cy - r * math.sin(a), cx + r * math.cos(a), cy + r * math.sin(a)], fill=col, width=max(6, int(r * .26)))
    d.ellipse([cx - r * .22, cy - r * .22, cx + r * .22, cy + r * .22], fill=col)


class TitleCard:
    w, h = 880, 470

    def __init__(self, title, sub="", **_):
        self.title, self.sub = (title or "").upper()[:28], (sub or "")[:44]

    def render(self, t):
        im = _bg(self.w, self.h, (30, 14, 18), (10, 6, 10))
        d = ImageDraw.Draw(im)
        _star(d, self.w // 2, 130, 62 * (0.8 + 0.2 * ease_out_back(t / .5)), RED, rot=t * 0.9)
        size = 84
        while font(size).getlength(self.title) > self.w - 90 and size > 36:
            size -= 4
        f = font(size)
        n = int(len(self.title) * clamp01((t - .15) / .7)) + 1
        shown = self.title[:n]
        d.text(((self.w - f.getlength(self.title)) / 2, 235), shown, font=f, fill=WHITE)
        if self.sub:
            fs = font(38, False)
            d.text(((self.w - fs.getlength(self.sub)) / 2, 350), self.sub, font=fs, fill=(255, 170, 175))
        bw = int((self.w - 220) * ease_out(clamp01((t - .4) / .6)))
        d.rounded_rectangle([110, 425, 110 + bw, 433], 4, fill=RED)
        return glow_panel(im)


class TerminalCard:
    w, h = 880, 560

    def __init__(self, lines, **_):
        self.lines = [str(x)[:38] for x in (lines or ["$ claude", "thinking...", "done"])][:6]

    def render(self, t):
        im = _bg(self.w, self.h, (14, 14, 18), (8, 8, 12))
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, self.w, 62], fill=(34, 34, 42))
        for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
            d.ellipse([28 + i * 40, 20, 50 + i * 40, 42], fill=c)
        f = _mono(40)
        y, tt = 100, t - 0.2
        for i, ln in enumerate(self.lines):
            cmd = ln.startswith("$")
            n = int(max(0, tt) * (26 if cmd else 40))
            shown = ln[:n]
            tt -= len(ln) / (26 if cmd else 40) + 0.12
            d.text((36, y), shown, font=f, fill=(126, 240, 196) if cmd else (225, 225, 235))
            if tt > -0.12 - len(ln) / 40 and n < len(ln) + 1 and int(t * 3) % 2 == 0 or (i == len(self.lines) - 1 and tt > 0 and int(t * 3) % 2 == 0):
                d.rectangle([36 + f.getlength(shown), y + 4, 36 + f.getlength(shown) + 20, y + 46], fill=RED)
            y += 76
            if tt < -0.2:
                break
        return glow_panel(im)


class ProfileCard:
    w, h = 880, 640

    def __init__(self, name="NeuroTriage", handle="@neurotriage", bio="", **_):
        self.name, self.handle, self.bio = (name or "NeuroTriage")[:22], (handle or "@neurotriage")[:26], (bio or "Roz ek naya concept")[:40]
        self.logo = None
        p = ROOT / "assets" / "logo.png"
        if p.exists():
            try:
                self.logo = Image.open(p).convert("RGBA").resize((170, 170), Image.LANCZOS)
            except Exception:
                pass

    def render(self, t):
        im = _bg(self.w, self.h, (250, 250, 252), (240, 240, 245))
        d = ImageDraw.Draw(im)
        av = Image.new("RGBA", (176, 176), (0, 0, 0, 0))
        ImageDraw.Draw(av).ellipse([0, 0, 175, 175], fill=RED + (255,))
        if self.logo is not None:
            m = Image.new("L", (170, 170), 0)
            ImageDraw.Draw(m).ellipse([0, 0, 169, 169], fill=255)
            av.paste(self.logo, (3, 3), m)
        else:
            ImageDraw.Draw(av).text((58, 38), self.name[0], font=font(96), fill=WHITE)
        im.paste(av, (50, 50), av)
        d.text((260, 70), self.name, font=font(50), fill=(20, 20, 28))          # no invented follower numbers
        d.text((260, 140), self.handle, font=font(34, False), fill=(110, 110, 125))
        d.text((50, 378), self.bio, font=font(32, False), fill=(40, 40, 52))
        followed = t > 1.5
        pulse = 1 + 0.04 * math.sin(t * 9) if not followed else 1
        bw, bh = int(780 * pulse), int(100 * pulse)
        x0, y0 = (self.w - bw) // 2, 470 + (100 - bh) // 2
        d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], 24, fill=(225, 225, 232) if followed else (0, 149, 246))
        lab = "Following" if followed else "Follow"
        f = font(44)
        d.text(((self.w - f.getlength(lab)) / 2, y0 + 24), lab, font=f, fill=(20, 20, 28) if followed else WHITE)
        return glow_panel(im)


class GraphCard:
    w, h = 880, 560

    def __init__(self, values=None, label="", title="", **_):
        v = [float(x) for x in (values or []) if isinstance(x, (int, float))]
        self.v = v if len(v) >= 4 else [10, 14, 13, 22, 30, 44, 58]
        self.label = (label or title or "GROWTH").upper()[:24]

    def render(self, t):
        im = _bg(self.w, self.h, (16, 12, 16), (8, 6, 10))
        d = ImageDraw.Draw(im)
        d.text((44, 30), self.label, font=font(40), fill=(255, 170, 175))
        x0, y0, x1, y1 = 60, 120, self.w - 50, self.h - 60
        for i in range(5):
            y = y0 + (y1 - y0) * i / 4
            d.line([x0, y, x1, y], fill=(48, 36, 44), width=2)
        lo, hi = min(self.v), max(self.v)
        pts = [(x0 + (x1 - x0) * i / (len(self.v) - 1), y1 - (y1 - y0) * (val - lo) / max(1e-6, hi - lo)) for i, val in enumerate(self.v)]
        p = ease_in_out(clamp01((t - .15) / 1.3)) * (len(pts) - 1)
        i = int(p)
        path = pts[:i + 1] + ([(pts[i][0] + (pts[i + 1][0] - pts[i][0]) * (p - i), pts[i][1] + (pts[i + 1][1] - pts[i][1]) * (p - i))] if i < len(pts) - 1 else [])
        gl = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(gl).line(path, fill=RED + (255,), width=18, joint="curve")
        im = Image.alpha_composite(im.convert("RGBA"), gl.filter(ImageFilter.GaussianBlur(12)))
        d = ImageDraw.Draw(im)
        d.line(path, fill=(255, 235, 235, 255), width=8, joint="curve")
        ex, ey = path[-1]
        d.ellipse([ex - 15, ey - 15, ex + 15, ey + 15], fill=RED + (255,), outline=WHITE + (255,), width=4)
        return glow_panel(im)


class InsertCard:
    """User's screen recording / image inside a glow border; video loops from its first frame at event start."""

    def __init__(self, media, **_):
        self.path, self.cap, self.img, self.fps, self.n = Path(media), None, None, 30.0, 0
        if self.path.suffix.lower() in IMG_EXT:
            self.img = cv2.cvtColor(cv2.imread(str(self.path)), cv2.COLOR_BGR2RGB)
        else:
            self.cap = cv2.VideoCapture(str(self.path))
            self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
            self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    def render(self, t):
        fr = self.img
        if self.cap is not None:
            idx = int(t * self.fps) % max(1, self.n)
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, bgr = self.cap.read()
            if not ok:
                return None
            fr = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w = fr.shape[:2]
        k = min(PANEL_W / w, PANEL_H / h)
        fr = cv2.resize(fr, (int(w * k) // 2 * 2, int(h * k) // 2 * 2), interpolation=cv2.INTER_AREA)
        return soft_panel(Image.fromarray(fr))


from cards_v2 import TitleCard, TerminalCard, ProfileCard, GraphCard, glass, soft_panel   # Round 15: glass chips (override the old big boxes above)


def make_card(e):
    k = e["type"]
    a = {key: e.get(key) for key in ("title", "sub", "lines", "name", "handle", "values", "label", "bio")}
    if k == "insert":
        return InsertCard(e["media"])
    return {"title": TitleCard, "terminal": TerminalCard, "profile": ProfileCard, "graph": GraphCard}[k](**a)


# ================================================================ 5. fx (shard / whip / zoom / captions)
def shard_fx(fr, p, seed):
    """Red glass shards: pop in, then fly apart (p 0..1)."""
    h, w = fr.shape[:2]
    rng = np.random.RandomState(seed)
    layer, mask = np.zeros_like(fr), np.zeros((h, w), np.uint8)
    for _ in range(22):
        cx, cy = rng.uniform(.03, .97) * w, rng.uniform(.05, .95) * h
        ang, size = rng.uniform(0, 6.28), rng.uniform(170, 460)
        drift, delay = rng.uniform(-1, 1, 2) * 620, rng.uniform(0, .3)
        q = clamp01((p - delay) / .7)
        grow = ease_out_back(clamp01(q * 2.4)) if q < .45 else 1.0
        fly = ease_in_out(clamp01((q - .45) / .55))
        a = [ang, ang + rng.uniform(1.7, 2.4), ang + rng.uniform(3.6, 4.6)]
        pts = np.array([[cx + drift[0] * fly + size * grow * math.cos(x), cy + drift[1] * fly + size * grow * math.sin(x)] for x in a], np.int32)
        col = tuple(int(c) for c in (np.array(RED) * rng.uniform(.55, 1.0)))
        cv2.fillConvexPoly(layer, pts, col)
        cv2.fillConvexPoly(mask, pts, int(255 * (1 - fly)))
        cv2.polylines(layer, [pts], True, (255, 220, 225), 3)
    al = cv2.GaussianBlur(mask, (0, 0), 1.6).astype(np.float32)[..., None] / 255 * .93
    glow = cv2.GaussianBlur(layer, (0, 0), 22)
    out = fr.astype(np.float32) * (1 - al) + layer.astype(np.float32) * al + glow.astype(np.float32) * .35 * (1 - ease_in_out(p))
    return np.clip(out, 0, 255).astype(np.uint8)


def whip_fx(fr, p, sign=1):
    k = int(220 * (1 - clamp01(p)) ** 1.5) | 1
    if k < 5:
        return fr
    return cv2.blur(np.roll(fr, int(sign * 60 * (1 - p)), axis=1), (k, 1))


def zoom_fx(fr, z, cy=.43):
    """Round 15: sub-pixel affine zoom (the old integer crop+resize made the picture wobble during punch-ins)."""
    if z <= 1.002:
        return fr
    h, w = fr.shape[:2]
    x0 = w / 2 - w / (2 * z)
    y0 = min(max(cy * h - h / (2 * z), 0), h - h / z)
    M = np.float32([[z, 0, -z * x0], [0, z, -z * y0]])
    return cv2.warpAffine(fr, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


class GlowCaptions:
    """Word-by-word captions: each spoken word appears and glows (style red: active red, rest white; white: active white, rest red)."""

    def __init__(self, words, style="red", size=104):
        self.style, self.size = style, size
        self.pages = paginate(words, max_words=3, max_chars=19, upper=True)
        self.starts = [p[0][1] for p in self.pages]
        self.ends = []
        for i, p in enumerate(self.pages):
            nxt = self.starts[i + 1] if i + 1 < len(self.pages) else 1e9
            self.ends.append(min(nxt, p[-1][2] + 0.25))
        self._c = {}

    def _spr(self, pi, k):
        key = (pi, k)
        if key in self._c:
            return self._c[key]
        words = [w[0] for w in self.pages[pi]]          # full page layout => words never shift when the next one appears
        size = self.size
        while True:
            f = font(size)
            sp = f.getlength(" ")
            wd = [f.getlength(x) for x in words]
            lines = wrap_lines(words, wd, sp, int(W * .86))
            if lines or size < 50:
                lines = lines or [list(range(len(words)))]
                break
            size -= 6
        lh, pad = int(size * 1.3), 50
        img = Image.new("RGBA", (W, lh * len(lines) + 2 * pad), (0, 0, 0, 0))
        gl = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d, dg = ImageDraw.Draw(img), ImageDraw.Draw(gl)
        act_c, rest_c = (RED, WHITE) if self.style == "red" else (WHITE, RED2)
        for li, idx in enumerate(lines):
            lw = sum(wd[i] for i in idx) + sp * (len(idx) - 1)
            x, y = (W - lw) / 2, pad + li * lh
            for i in idx:
                if i > k:
                    x += wd[i] + sp
                    continue
                act = i == k
                c = act_c if act else rest_c
                dg.text((x, y), words[i], font=f, fill=(RED if self.style == "red" or act else RED) + (255,), stroke_width=8 if act else 3,
                        stroke_fill=RED + (255,))
                d.text((x, y), words[i], font=f, fill=c + (255,), stroke_width=6, stroke_fill=(14, 4, 8, 255))
                x += wd[i] + sp
        g1, g2 = gl.filter(ImageFilter.GaussianBlur(20)), gl.filter(ImageFilter.GaussianBlur(7))
        img = Image.alpha_composite(Image.alpha_composite(g1, g2), img)
        arr = np.array(img)
        ys, xs = np.where(arr[..., 3] > 4)
        if len(xs):
            x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
        else:
            x0, x1, y0, y1 = 0, 2, 0, 2
        out = (arr[y0:y1, x0:x1].copy(), (x0 + x1) / 2 - arr.shape[1] / 2, (y0 + y1) / 2 - arr.shape[0] / 2)
        self._c[key] = out
        return out

    def draw(self, fr, t, cy=None):
        cy = CAP_CY if cy is None else cy
        pi = None
        for i in range(len(self.pages)):
            if self.starts[i] - 0.02 <= t < self.ends[i]:
                pi = i
        if pi is None:
            return
        pg = self.pages[pi]
        k = max([j for j, w in enumerate(pg) if t >= w[1] - 0.02] or [0])
        u = (t - max(pg[k][1], self.starts[pi])) * FPS
        arr, dx, dy = self._spr(pi, k)
        spr = scaled(arr, 1.0 + 0.16 * (1 - ease_out_back(clamp01(u / 6.0), 2.2)))
        blit(fr, spr, W / 2 + dx - spr.shape[1] / 2, cy + dy - spr.shape[0] / 2, clamp01(u / 2.0 + .35))


# ================================================================ 6. render
def pick_emphasis(plan, words):
    wanted = {re.sub(r"\W", "", str(x)).lower() for x in plan.get("emphasis", []) if x}
    out, last = [], -9
    for t, s, e in words:
        if re.sub(r"\W", "", t).lower() in wanted and s - last > 1.5:
            out.append(s)
            last = s
    return out


def render(cut, words, events, emph, offs, out, hook, style, with_endcard, handle, cover=None):
    cap = GlowCaptions(words, style)
    hk = hook_intro.HookText(hook, W) if hook else None
    logo = brand_logo.load(76, ROOT / "assets") if brand_logo.enabled() else None
    ec = endcard.EndCard(W) if with_endcard else None
    cards = [make_card(e) for e in events]
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(cut), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
                           stdin=subprocess.PIPE)
    fsz, g, last, first0, ccache = W * H * 3, 0, None, None, {}
    while True:
        buf = dec.stdout.read(fsz)
        if len(buf) < fsz:
            break
        fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
        t = g / FPS
        seg = max([i for i, o in enumerate(offs) if t >= o - 1e-6] or [0])
        if len(offs) <= 1:
            seg = int(t // 4.5)                                                  # no cuts -> still alternate zoom-in / zoom-out every ~4.5s
        z = 1.0 + (0.09 if seg % 2 else 0.0)                                     # jump-cut rhythm
        for te in emph:                                                           # emphasis punch-in
            u = t - te
            if 0 <= u < .65:
                z += .11 * (ease_out(u / .1) if u < .1 else 1 - ease_in_out((u - .1) / .55))
        fr = zoom_fx(fr, z)
        for e, c in zip(events, cards):
            u = t - e["at"]
            if -0.01 <= u < e["dur"] + .3:
                a_in, a_out = ease_out(clamp01((u - .05) / .28)), clamp01((e["dur"] - u) / .25)
                a = min(a_in, a_out)
                if a <= 0:
                    continue
                cf = getattr(c, "fps", 15)
                q = int(max(0, u - .05) * cf)
                if ccache.get(id(c), (None,))[0] != q:
                    ccache[id(c)] = (q, c.render(q / float(cf)))
                spr = ccache[id(c)][1]
                if spr is None:
                    continue
                if os.environ.get("TH_TRANSITIONS", "on") != "off":   # Round 15: shard / whip transitions back ON
                    if u < .42:
                        fr = shard_fx(fr, u / .42, int(e["at"] * 100)) if e["_tr"] == "shard" else whip_fx(fr, u / .42, e["_sign"])
                    elif e["dur"] - u < .22:
                        fr = whip_fx(fr, clamp01((e["dur"] - u) / .22), -e["_sign"])
                if getattr(c, "glass", False):                    # chip: slides down from the top safe area, no dimming
                    ch, cw = spr.shape[:2]
                    slide = -54 * (1 - ease_out_back(clamp01((u - .05) / .45), 1.3)) if u < e["dur"] - .25 else -34 * (1 - a_out)
                    cx0, cy0 = (W - cw) // 2, int(CHIP_TOP + slide)
                    glass(fr, cx0, cy0, cw, ch, c.r, a)
                    blit(fr, spr, cx0, cy0, a)
                else:                                              # user's screen recording / photo
                    fr = cv2.convertScaleAbs(fr, alpha=1 - .22 * a)
                    s2 = scaled(spr, .94 + .06 * ease_out_back(clamp01((u - .05) / .35), 1.3))
                    blit(fr, s2, (W - s2.shape[1]) / 2, PANEL_CY - s2.shape[0] / 2, a)
        if logo is not None:
            al = brand_logo.fade(t)
            if al > 0:
                pad = brand_logo.pad_of(76)
                blit(fr, logo, W - 44 - 76 - pad, 128 - pad, al)
        if hk is not None:
            hk.draw(fr, t)
        cap.draw(fr, t)
        if g == 0:
            first0 = fr.copy()
        if cover is not None and g == int(0.5 * FPS):          # cover/thumbnail: hook still fully visible, face in frame
            Image.fromarray(fr).save(str(cover), quality=92)
        last, g = fr, g + 1
        enc.stdin.write(fr.tobytes())
    dec.wait()
    if last is None:
        raise RuntimeError("no frames decoded")
    n_end = int(2.8 * FPS)
    base = (cv2.GaussianBlur(last, (0, 0), 14) * 0.42).astype(np.uint8)
    for i in range(n_end):
        fr = base.copy()
        if ec is not None:
            ec.draw(fr, i / FPS)
        enc.stdin.write(fr.tobytes())
    enc.stdin.close()
    enc.wait()
    if enc.returncode != 0:
        raise RuntimeError("encode failed")
    return g / FPS + n_end / FPS


VOICE_FX = ("highpass=f=80,afftdn=nr=8:nf=-45,acompressor=threshold=-20dB:ratio=3:attack=8:release=120:makeup=3,"
            "equalizer=f=3000:t=q:w=1.2:g=2")


def make_sfx(tmp):
    """Round 10: tiny synthetic whoosh (card transitions) and pop (end card). No asset files needed."""
    w, p = Path(tmp) / "whoosh.wav", Path(tmp) / "pop.wav"
    sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=0.5:c=pink:a=0.6:r=48000", "-af",
        "highpass=f=350,lowpass=f=7000,afade=t=in:d=0.22,afade=t=out:st=0.22:d=0.28,volume=1.4", str(w)])
    sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "aevalsrc=0.8*sin(2*PI*(520+900*t)*t):d=0.16:s=48000", "-af",
        "afade=t=out:st=0.04:d=0.12", str(p)])
    return w, p


def mux(vid, cut, total, out, audio=None, vol=0.22, whoosh_at=(), pop_at=None, tmp="."):
    """voice (cleaned: de-noise, compress, presence) + optional background track (looped/trimmed, ducked under speech)
    + optional whoosh/pop sound effects, then fade-out and -14 LUFS."""
    fade = f"afade=t=out:st={max(0, total - 0.8):.2f}:d=0.8,loudnorm=I=-14:TP=-1.5:LRA=11"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(vid), "-i", str(cut)]
    fc, k = [f"[1:a]aresample=48000,{VOICE_FX},apad[v]"], 2
    if audio and Path(audio).exists():
        cmd += ["-stream_loop", "-1", "-i", str(audio)]
        fc += ["[v]asplit=2[v1][v2]",
               f"[{k}:a]aresample=48000,volume={float(vol):.3f},afade=t=in:d=0.6[m]",
               "[m][v1]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=450[md]",
               "[v2][md]amix=inputs=2:duration=first:normalize=0[mix]"]
        k += 1
    else:
        fc.append("[v]anull[mix]")
    ws = [max(0.0, float(t)) for t in whoosh_at]
    if ws or pop_at is not None:
        wav, pop = make_sfx(tmp)
        parts = ["[mix]"]
        if ws:
            cmd += ["-i", str(wav)]
            fc.append(f"[{k}:a]volume=0.30,asplit={len(ws)}" + "".join(f"[w{i}]" for i in range(len(ws))) if len(ws) > 1 else f"[{k}:a]volume=0.30[w0]")
            for i, t in enumerate(ws):
                fc.append(f"[w{i}]adelay={int(t * 1000)}|{int(t * 1000)}[dw{i}]")
                parts.append(f"[dw{i}]")
            k += 1
        if pop_at is not None:
            cmd += ["-i", str(pop)]
            ms = int(max(0.0, pop_at) * 1000)
            fc.append(f"[{k}:a]volume=0.35,adelay={ms}|{ms}[dp]")
            parts.append("[dp]")
            k += 1
        fc.append("".join(parts) + f"amix=inputs={len(parts)}:duration=first:normalize=0[mix2]")
        fc.append(f"[mix2]{fade}[aout]")
    else:
        fc.append(f"[mix]{fade}[aout]")
    cmd += ["-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[aout]"]
    sh(cmd + ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{total:.2f}", "-movflags", "+faststart", str(out)])


def set_canvas(land):
    """Landscape input (long video) keeps 16:9; everything else is 9:16."""
    global W, H, PANEL_CY, CAP_CY, PANEL_W, PANEL_H, CHIP_TOP
    if land:
        W, H, PANEL_W, PANEL_H = 1920, 1080, 1100, 700
        PANEL_CY, CAP_CY, CHIP_TOP = int(H * .42), int(H * .87), int(H * .08)
    else:
        W, H, PANEL_W, PANEL_H = 1080, 1920, 920, 1000
        PANEL_CY, CAP_CY, CHIP_TOP = int(H * .385), int(H * .745), int(H * .118)


def _jd(p, o):
    Path(p).write_text(json.dumps(o, ensure_ascii=False, default=str), encoding="utf-8")


def _jl(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def stage1(video, work, lang="", words_json="", no_cuts=False):
    """transcribe + silence cut. Writes work/state.json, work/cut.mp4, work/progress.json (for the page's time estimate)."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    info = probe(video)
    if not info["audio"] and not words_json:
        raise RuntimeError("clip has no audio: cannot caption")
    land = info["w"] > info["h"]
    set_canvas(land)
    words = transcribe(video, work, lang, words_json)
    if not words:
        raise RuntimeError("no speech found (check GROQ_API_KEY or install faster-whisper)")
    segs = [(0.0, info["dur"])] if no_cuts else keep_segments(words, info["dur"])
    nw, offs, dur = remap(words, segs)
    log(f"[th] {info['w']}x{info['h']} {info['dur']:.1f}s | {len(words)} words | cut {len(segs)} segs -> {dur:.1f}s | {'LONG 16:9' if land else 'SHORT 9:16'}")
    cut_video(video, info, segs, work / "cut.mp4", work)
    kind = "long" if (land or dur > 180) else "short"
    _jd(work / "state.json", {"land": land, "words": nw, "raw_words": words, "offs": offs, "dur": dur, "in_dur": info["dur"], "nseg": len(segs), "kind": kind})
    _jd(work / "progress.json", {"state": "running", "kind": kind, "dur_in": round(info["dur"], 1), "dur_out": round(dur, 1)})


def stage2(work, inserts=(), handle="@neurotriage", plan_json="", hook=""):
    """topic plan (cards/inserts/emphasis) + YouTube meta."""
    work = Path(work)
    st = _jl(work / "state.json")
    set_canvas(st["land"])
    nw = [tuple(w) for w in st["words"]]
    media = [Path(p) for p in inserts if Path(p).exists()]
    plan = _jl(plan_json) if plan_json else make_plan(nw, st["dur"], media, handle)
    events = clean_events(plan, st["dur"], media, handle)
    for i, e in enumerate(events):
        e["_tr"], e["_sign"] = ("shard" if i % 2 == 0 else "whip"), (1 if i % 3 else -1)
    emph = pick_emphasis(plan, nw) or [w[1] for w in nw if len(re.sub(r"\W", "", w[0])) >= 8][:: 3]
    meta = make_meta(nw, plan, handle)
    meta["kind"] = st["kind"]
    log(f"[th] plan: {len(events)} events {[(round(e['at'], 1), e['type']) for e in events]} | {len(emph)} punch-ins")
    _jd(work / "plan2.json", {"events": events, "emph": emph, "meta": meta, "hook": (hook or plan.get("hook") or auto_hook(nw)).upper(),
                              "planner": plan.get("_by", "heuristic")})


def stage3(work, out_dir="output/th", style="red", with_endcard=True, handle="@neurotriage", audio="", audio_vol=0.22, sfx=True):
    t0 = time.time()
    work, out_dir = Path(work), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    st, p2 = _jl(work / "state.json"), _jl(work / "plan2.json")
    set_canvas(st["land"])
    nw = [tuple(w) for w in st["words"]]
    events = p2["events"]
    for e in events:
        if e.get("media"):
            e["media"] = Path(e["media"])
    s2 = work / "s2.mp4"
    has_end = bool(with_endcard and not st["land"])
    total = render(work / "cut.mp4", nw, events, p2["emph"], st["offs"], s2, p2["hook"], style, has_end, handle, out_dir / "cover.jpg")
    final = out_dir / "final_th.mp4"
    wh = [e["at"] - 0.05 for e in events] if sfx else []
    pop = (total - 2.8 + 0.12) if (sfx and has_end) else None
    mux(s2, work / "cut.mp4", total, final, audio or None, audio_vol, wh, pop, work)
    fxrep = {}
    try:                                                 # Round 11/12: blocks + effects + quality gate. Never raises.
        import enhance
        fxrep = enhance.run(final, nw, total, events, st["land"], work, log)
    except Exception as ex:
        fxrep = {"status": f"skipped:{type(ex).__name__}"}; log("[th] enhance skipped:", str(ex)[:90])
    vr = {}                                              # Studio posts final_th.mp4 as-is (already 1080 H.264); skipping variants saves ~2x time
    rep = {"meta": p2["meta"], "duration_in": round(st["in_dur"], 2), "duration_out": round(total, 2), "segments": st["nseg"],
           "events": [{k: str(v) for k, v in e.items() if not k.startswith("_")} for e in events], "emphasis": [round(x, 2) for x in p2["emph"]],
           "planner": p2["planner"], "music": bool(audio and Path(audio).exists()), "sfx": len(wh) + (1 if pop is not None else 0), "hook": p2["hook"], "fx": fxrep, "variants": vr, "render_sec": round(time.time() - t0, 1)}
    _jd(out_dir / "th_report.json", rep)
    _jd(out_dir / "words.json", st["raw_words"])
    log("[th] done:", final)
    return rep


def process(video, out_dir="output/th", inserts=(), style="red", hook="", handle="@neurotriage", lang="", words_json="",
            plan_json="", no_cuts=False, with_endcard=True, work="work_th", audio="", audio_vol=0.22, sfx=True):
    stage1(video, work, lang, words_json, no_cuts)
    stage2(work, inserts, handle, plan_json, hook)
    return stage3(work, out_dir, style, with_endcard, handle, audio, audio_vol, sfx)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="")
    ap.add_argument("--inserts", default="", help="comma list: your screen recordings / images (file name = topic hint)")
    ap.add_argument("--style", default="red", choices=["red", "white"])
    ap.add_argument("--hook", default="")
    ap.add_argument("--handle", default="@neurotriage")
    ap.add_argument("--lang", default="")
    ap.add_argument("--words", default="", help="words.json [[text,start,end],..] (skips Whisper)")
    ap.add_argument("--plan", default="", help="plan.json (skips LLM planner)")
    ap.add_argument("--audio", default="", help="background music / extra audio file: mixed UNDER your voice (auto-ducked), looped/trimmed to the video")
    ap.add_argument("--audio-vol", type=float, default=0.22, help="music level before ducking (0.05-0.6)")
    ap.add_argument("--no-sfx", action="store_true", help="no whoosh/pop sound effects")
    ap.add_argument("--no-cuts", action="store_true")
    ap.add_argument("--no-endcard", action="store_true")
    ap.add_argument("--out", default="output/th")
    ap.add_argument("--stage", default="all", choices=["all", "1", "2", "3"])
    ap.add_argument("--work", default="work_th")
    ap.add_argument("--topic", default="", help="Round 13: topic of SILENT footage (engine writes script + voice + music)")
    ap.add_argument("--script", default="", help="Round 13: your own voiceover text for silent footage")
    a = ap.parse_args(argv)
    ins = [x.strip() for x in a.inserts.split(",") if x.strip()]
    if a.stage in ("all", "1"):
        if not Path(a.video).exists():
            sys.exit(f"video not found: {a.video}")
        if not a.words and os.environ.get("TH_SILENT", "auto") != "off" and a.stage == "all":
            import silent_mode                           # Round 13: footage without speech -> auto voice + music
            if silent_mode.is_silent(a.video):
                pr = silent_mode.prepare(a.video, a.work, a.topic, a.script, a.hook)
                if pr["mode"] == "voiceover":
                    a.video, a.words, a.no_cuts, a.hook = pr["video"], pr["words_json"], True, a.hook or pr["hook"]
                    a.audio = a.audio or pr["music"] or ""
                else:
                    Path(a.out).mkdir(parents=True, exist_ok=True); fin = Path(a.out) / "final_th.mp4"
                    if not pr["music"]: sys.exit("silent footage: no script and no music possible: " + "; ".join(pr["notes"]))
                    silent_mode.music_only(a.video, pr["music"], fin)
                    _jd(Path(a.out) / "th_report.json", {"mode": "music-only", "notes": pr["notes"], "final": str(fin)}); log("[th] music-only:", fin); return
        stage1(a.video, a.work, a.lang, a.words, a.no_cuts)
    if a.stage in ("all", "2"):
        stage2(a.work, ins, a.handle, a.plan, a.hook.upper())
    if a.stage in ("all", "3"):
        stage3(a.work, a.out, a.style, not a.no_endcard, a.handle, a.audio, min(max(a.audio_vol, 0.02), 1.0), not a.no_sfx)


if __name__ == "__main__":
    main()
