"""NeuroTriage Auto Reel Bot v7 (Hinglish + ElevenLabs + virality + multi-platform)
research -> script -> per-scene voice -> relevant stock (Gemini picks) -> pro edit
(grade, camera moves, motion-blur transitions, kinetic captions, motion graphics,
ambient music, Lottie end splash) -> YouTube.

GROQ_API_KEY (primary) + GEMINI_API_KEY (fallback). Koi ek bhi chalega. PEXELS / PIXABAY optional (stock clips ke liye).
Editing moviepy se nahi, seedha numpy + OpenCV + ffmpeg se hoti hai (zyada control, kam RAM).
"""
import os, sys, io, re, json, math, random, time, asyncio, subprocess, wave, base64, glob
from pathlib import Path

import numpy as np
import cv2
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

cv2.setNumThreads(2)

import eleven_voice, azure_voice, virality, publisher      # v7 modules (same folder)
import ckpt, scheduler, long_render, caption_styles, publish_due   # v8 modules
import safe                                                         # round 1: crash-proofing
import brand_logo, project_state, research as research_engine      # round 3
import topics, hook_intro                                          # round 5a
import endcard, variants                                           # round 5b

# ------------------------------------------------------------------ settings
W, H, FPS = 1080, 1920, 30
ROOT = Path(__file__).parent
ASSETS, WORK, OUT = ROOT / "assets", ROOT / "work", ROOT / "output"
HISTORY = ROOT / "topics_done.txt"
LOOP_JOIN = os.environ.get("LOOP_JOIN", "off").lower() not in ("off", "0", "no")
LOOP_SEC = 0.5
DIRECTIVE = [""]                 # round 5a: topic order from topics.plan() (trending > disorder/habit rotation)
PLAN = {}

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "")
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
VOICE = os.environ.get("VOICE", "en-US-AndrewMultilingualNeural")
FALLBACK_VOICES = ["en-US-AvaMultilingualNeural", "en-US-BrianMultilingualNeural",
                   "en-US-AriaNeural", "en-IN-NeerjaNeural"]
MODE = os.environ.get("MODE", "auto")          # auto | awareness | student
PRIVACY = os.environ.get("PRIVACY", "private")
MUSIC_ON = os.environ.get("MUSIC", "on").lower() != "off"
SEED = os.environ.get("SEED")
RENDER_PRESET = os.environ.get("RENDER_PRESET", "medium")        # midnight build uses "slow" (better quality, no rush)
CAPTION_STYLE = os.environ.get("CAPTION_STYLE", "auto")          # auto | pop | box | karaoke | bounce | glow
QUEUE_MODE = os.environ.get("QUEUE_MODE", "off").lower() == "on"  # on = build now, publish at scheduled time
NATIVE_SCHEDULE = os.environ.get("NATIVE_SCHEDULE", "on").lower() != "off"
LONG_RENDER = os.environ.get("LONG_RENDER", "on").lower() != "off"   # on = real 16:9 long video (else script kit only)
LONG_VISION = os.environ.get("LONG_VISION", "on").lower() != "off"   # Gemini picks best stock clip per scene
VIDEO_TYPE = (os.environ.get("VIDEO_TYPE", "short").strip().lower() or "short")   # short | long | both
if VIDEO_TYPE not in ("short", "long", "both"):
    VIDEO_TYPE = "short"
FORCE_REBUILD = os.environ.get("FORCE_REBUILD", "").lower() in ("1", "true", "yes")
LANDSCAPE = False                                                # set True while picking clips for the 16:9 long video
BRAND_NAME = os.environ.get("BRAND_NAME", "NeuroTriage")
SITE_URL = os.environ.get("SITE_URL", "https://www.neurotriage.in/")
SITE_SHORT = os.environ.get("SITE_SHORT", "neurotriage.in")
SITE_WWW = "www.neurotriage.in"
TAGLINE = os.environ.get("TAGLINE", "Free screening  |  Productivity tools")
HELPLINE = "If you are struggling, India's free 24x7 helpline Tele-MANAS: 14416."
DISCLAIMER = "This video is for education only. It is not medical advice or a diagnosis."

# [display|spoken] : screen par www.neurotriage.in dikhta hai, awaaz mein "W W W dot neuro triage dot in"
SPOKEN_URL = "W W W dot neuro triage dot in"
CTA_AWARENESS = os.environ.get(
    "CTA_AWARENESS", f"Take a free screening at [{SITE_WWW}|{SPOKEN_URL}].")
CTA_STUDENT = os.environ.get(
    "CTA_STUDENT", f"Boost your productivity at [{SITE_WWW}|{SPOKEN_URL}].")

CTA_AWARENESS_HI = f"Free screening ke liye [{SITE_WWW}|{SPOKEN_URL}] par jao."
CTA_STUDENT_HI = f"Apni productivity badhane ke liye [{SITE_WWW}|{SPOKEN_URL}] par jao."

SAFETY = """Safety rules (must follow):
- Educational only. Never diagnose, never tell viewers they 'have' a disorder.
- Never advise starting, stopping or changing any medicine or treatment.
- No self-harm or suicide methods, no graphic detail, no fear-mongering, no miracle cures.
- Use cautious wording ("research suggests", "often"), never invent numbers or studies.
- Reduce stigma. For heavy topics (anxiety, depression, burnout) say gently that talking
  to a psychologist/psychiatrist or a trusted person helps."""

# brand colours (RGB) - splash wale hi
BLUE, GREEN, NAVY = (59, 111, 224), (31, 177, 132), (11, 31, 58)
MINT = (126, 240, 196)       # active caption word
SPLASH_SECONDS = 4.8
HOOK_INTRO = os.environ.get("HOOK_INTRO", "off").lower() in ("on", "1", "yes")   # v16: no hook box / dark band at start (video starts directly)
XFADE = 12                    # transition length (frames) = 0.4 s


def log(*a):
    print(*a, flush=True)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def ffprobe(path):
    """width, height, duration (sec) of first video stream."""
    try:
        r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=width,height,duration:format=duration", "-of", "json", str(path)])
        j = json.loads(r.stdout)
        st = j["streams"][0]
        dur = float(st.get("duration") or j["format"].get("duration") or 0)
        return int(st["width"]), int(st["height"]), dur
    except Exception:
        return None


# ------------------------------------------------------------------ easing
def clamp01(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def ease_out(x):          # cubic out
    x = clamp01(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def ease_out_back(x, s=1.9):
    x = clamp01(x) - 1
    return 1 + (s + 1) * x ** 3 + s * x ** 2


def cubic_bezier(x1, y1, x2, y2):
    def f(t):
        if t <= 0:
            return 0.0
        if t >= 1:
            return 1.0
        lo, hi = 0.0, 1.0
        for _ in range(28):
            m = (lo + hi) / 2
            x = 3 * (1 - m) ** 2 * m * x1 + 3 * (1 - m) * m * m * x2 + m ** 3
            if x < t:
                lo = m
            else:
                hi = m
        u = (lo + hi) / 2
        return 3 * (1 - u) ** 2 * u * y1 + 3 * (1 - u) * u * u * y2 + u ** 3
    return f


# ================================================================== LOTTIE splash
class Splash:
    """Tumhari neurotriage_splash.json ko seedha render karta hai (koi extra library nahi).
    Is file mein jo kuch hai (shape paths, ellipse, rect, linear/radial gradient, image layer,
    bezier easing, hold keyframes) sab supported hai. 512x512 design -> 1080x1920 canvas par,
    white background poore frame mein (glow ka kata hua kinara bhi nahi dikhta)."""

    def __init__(self, path):
        self.d = json.loads(Path(path).read_text(encoding="utf-8"))
        self.fr = float(self.d.get("fr", 60))
        self.op = float(self.d.get("op", 192))
        self.lw, self.lh = float(self.d.get("w", 512)), float(self.d.get("h", 512))
        self.S = W / self.lw
        self.ox, self.oy = W / 2 - self.lw / 2 * self.S, H / 2 - self.lh / 2 * self.S
        self.duration = self.op / self.fr
        self.imgs = {}
        for a in self.d.get("assets", []):
            p = a.get("p", "")
            if p.startswith("data:"):
                raw = base64.b64decode(p.split(",", 1)[1])
                im = np.array(Image.open(io.BytesIO(raw)).convert("RGBA"), np.float32) / 255.0
                im[..., :3] *= im[..., 3:4]            # premultiply
                self.imgs[a["id"]] = im
        self.layers = list(reversed(self.d["layers"]))   # neeche wala pehle
        self._cache = {}

    # ---- animated property
    @staticmethod
    def val(prop, f, default=0.0):
        if prop is None:
            return [default]
        k = prop.get("k")
        if not prop.get("a"):
            return list(k) if isinstance(k, list) else [k]
        kfs = k
        if f <= kfs[0]["t"]:
            return list(kfs[0]["s"])
        for a, b in zip(kfs, kfs[1:]):
            if f < b["t"]:
                if a.get("h"):
                    return list(a["s"])
                p = (f - a["t"]) / (b["t"] - a["t"])
                if "o" in a and "i" in a:
                    e = cubic_bezier(a["o"]["x"][0], a["o"]["y"][0],
                                     a["i"]["x"][0], a["i"]["y"][0])(p)
                else:
                    e = p
                bs = b.get("s", a["s"])
                return [x + (y - x) * e for x, y in zip(a["s"], bs)]
        last = kfs[-1]
        return list(last.get("s", kfs[-2]["s"]))

    def _layer_matrix(self, ks, f, anchor_override=None):
        """lottie units -> canvas pixels (3x3)."""
        p = self.val(ks.get("p"), f, 0.0)
        a = self.val(ks.get("a"), f, 0.0)
        s = self.val(ks.get("s"), f, 100.0)
        r = self.val(ks.get("r"), f, 0.0)[0]
        px, py = p[0], p[1] if len(p) > 1 else 0.0
        ax, ay = a[0], a[1] if len(a) > 1 else 0.0
        sx, sy = s[0] / 100.0, (s[1] if len(s) > 1 else s[0]) / 100.0
        c, sn = math.cos(math.radians(r)), math.sin(math.radians(r))
        # local -> comp:  T(p) R S T(-a)
        M = np.array([[1, 0, px], [0, 1, py], [0, 0, 1]], np.float64)
        R = np.array([[c, -sn, 0], [sn, c, 0], [0, 0, 1]], np.float64)
        Sm = np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1]], np.float64)
        A = np.array([[1, 0, -ax], [0, 1, -ay], [0, 0, 1]], np.float64)
        comp = M @ R @ Sm @ A
        to_px = np.array([[self.S, 0, self.ox], [0, self.S, self.oy], [0, 0, 1]], np.float64)
        return to_px @ comp

    @staticmethod
    def _path_points(v, i, o, closed, n=10):
        pts = []
        cnt = len(v)
        segs = cnt if closed else cnt - 1
        for k in range(segs):
            p0, p1 = np.array(v[k]), np.array(v[(k + 1) % cnt])
            c1 = p0 + np.array(o[k])
            c2 = p1 + np.array(i[(k + 1) % cnt])
            for t in np.linspace(0, 1, n, endpoint=False):
                u = 1 - t
                pts.append(u ** 3 * p0 + 3 * u * u * t * c1 + 3 * u * t * t * c2 + t ** 3 * p1)
        return np.array(pts)

    def _group_polys(self, items, f):
        """returns list of polygons (lottie local units)."""
        polys = []
        for it in items:
            ty = it.get("ty")
            if ty == "sh":
                k = it["ks"]["k"]
                if it["ks"].get("a"):
                    k = self.val(it["ks"], f)
                    k = k[0] if isinstance(k, list) and isinstance(k[0], dict) else k
                polys.append(self._path_points(k["v"], k["i"], k["o"], k.get("c", True)))
            elif ty == "el":
                s = self.val(it.get("s"), f)
                p = self.val(it.get("p"), f)
                t = np.linspace(0, 2 * math.pi, 72, endpoint=False)
                polys.append(np.stack([p[0] + s[0] / 2 * np.cos(t), p[1] + s[1] / 2 * np.sin(t)], 1))
            elif ty == "rc":
                s = self.val(it.get("s"), f)
                p = self.val(it.get("p"), f)
                x0, y0, x1, y1 = p[0] - s[0] / 2, p[1] - s[1] / 2, p[0] + s[0] / 2, p[1] + s[1] / 2
                polys.append(np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]))
        return polys

    @staticmethod
    def _grad_stops(g):
        n = int(g["p"])
        arr = g["k"]["k"]
        cols = [(arr[j * 4], arr[j * 4 + 1:j * 4 + 4]) for j in range(n)]
        rest = arr[n * 4:]
        alph = [(rest[j * 2], rest[j * 2 + 1]) for j in range(len(rest) // 2)] or [(0, 1), (1, 1)]
        return cols, alph

    def _fill_layer(self, canvas, polys, fill, M, f, layer_op):
        if not polys:
            return
        if abs(np.linalg.det(M[:2, :2])) < 1e-9:
            return
        Mi = np.linalg.inv(M)
        allp = np.concatenate([(M @ np.c_[p, np.ones(len(p))].T).T[:, :2] for p in polys])
        x0, y0 = np.floor(allp.min(0)).astype(int) - 2
        x1, y1 = np.ceil(allp.max(0)).astype(int) + 2
        x0c, y0c, x1c, y1c = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
        if x1c <= x0c or y1c <= y0c:
            return
        SS = 3
        mw, mh = (x1c - x0c) * SS, (y1c - y0c) * SS
        mask = np.zeros((mh, mw), np.uint8)
        cvp = []
        for p in polys:
            q = (M @ np.c_[p, np.ones(len(p))].T).T[:, :2]
            q = (q - [x0c, y0c]) * SS
            cvp.append(np.round(q * 16).astype(np.int32))
        cv2.fillPoly(mask, cvp, 255, lineType=cv2.LINE_AA, shift=4)
        m = cv2.resize(mask, (x1c - x0c, y1c - y0c), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        op = self.val(fill.get("o"), f, 100.0)[0] / 100.0 * layer_op
        if fill["ty"] == "fl":
            c = np.array(self.val(fill["c"], f)[:3], np.float32)
            col = np.broadcast_to(c, (y1c - y0c, x1c - x0c, 3))
            a = m * op
        else:   # gf gradient
            ys, xs = np.mgrid[y0c:y1c, x0c:x1c].astype(np.float32)
            lx = Mi[0, 0] * xs + Mi[0, 1] * ys + Mi[0, 2]
            ly = Mi[1, 0] * xs + Mi[1, 1] * ys + Mi[1, 2]
            s = self.val(fill["s"], f)
            e = self.val(fill["e"], f)
            if fill.get("t", 1) == 1:
                dx, dy = e[0] - s[0], e[1] - s[1]
                tt = ((lx - s[0]) * dx + (ly - s[1]) * dy) / max(dx * dx + dy * dy, 1e-6)
            else:
                rad = max(math.hypot(e[0] - s[0], e[1] - s[1]), 1e-6)
                tt = np.hypot(lx - s[0], ly - s[1]) / rad
            tt = np.clip(tt, 0, 1)
            cols, alph = self._grad_stops(fill["g"])
            offs = [c_[0] for c_ in cols]
            col = np.stack([np.interp(tt, offs, [c_[1][ch] for c_ in cols]) for ch in range(3)], -1)
            ga = np.interp(tt, [a_[0] for a_ in alph], [a_[1] for a_ in alph])
            a = m * op * ga.astype(np.float32)
        roi = canvas[y0c:y1c, x0c:x1c]
        roi *= (1 - a[..., None])
        roi += col * a[..., None]

    def _draw_image(self, canvas, layer, M, op):
        im = self.imgs.get(layer.get("refId"))
        if im is None or op <= 0:
            return
        h, w = im.shape[:2]
        corners = (M @ np.array([[0, 0, 1], [w, 0, 1], [w, h, 1], [0, h, 1]]).T).T[:, :2]
        x0, y0 = np.floor(corners.min(0)).astype(int) - 1
        x1, y1 = np.ceil(corners.max(0)).astype(int) + 1
        x0c, y0c, x1c, y1c = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
        if x1c <= x0c or y1c <= y0c:
            return
        T = M.copy()
        T[0, 2] -= x0c
        T[1, 2] -= y0c
        warped = cv2.warpAffine(im, T[:2], (x1c - x0c, y1c - y0c), flags=cv2.INTER_CUBIC,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        warped = np.clip(warped, 0, 1) * op
        roi = canvas[y0c:y1c, x0c:x1c]
        roi *= (1 - warped[..., 3:4])
        roi += warped[..., :3]

    def frame(self, t):
        """t seconds -> RGB uint8 (H, W, 3)."""
        f = min(t * self.fr, self.op - 0.01)
        canvas = np.ones((H, W, 3), np.float32)
        for L in self.layers:
            if not (L.get("ip", 0) <= f < L.get("op", 1e9)):
                continue
            ks = L.get("ks", {})
            lop = self.val(ks.get("o"), f, 100.0)[0] / 100.0
            ty = L.get("ty")
            if ty == 1:
                c = L.get("sc", "#ffffff").lstrip("#")
                rgb = np.array([int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)
                canvas *= (1 - lop)
                canvas += rgb * lop
                continue
            if lop <= 0.001:
                continue
            M = self._layer_matrix(ks, f)
            if ty == 2:
                self._draw_image(canvas, L, M, lop)
            elif ty == 4:
                for grp in L.get("shapes", []):
                    items = grp.get("it", [])
                    polys = self._group_polys(items, f)
                    gM = M
                    for it in items:
                        if it.get("ty") == "tr":
                            gp = self.val(it.get("p"), f)
                            if abs(gp[0]) + abs(gp[1]) > 1e-6:
                                gM = M @ np.array([[1, 0, gp[0]], [0, 1, gp[1]], [0, 0, 1]])
                    for it in items:
                        if it.get("ty") in ("fl", "gf"):
                            self._fill_layer(canvas, polys, it, gM, f, lop)
        return (np.clip(canvas, 0, 1) * 255 + 0.5).astype(np.uint8)


# ================================================================== 1. GEMINI (research + script + clip picking)
import keyring                                           # round 2: all keys, naming, cooldowns live in keyring.py
GEM = keyring.ring("gemini")
GRQ = keyring.ring("groq")
KEYS = [sl.value for sl in GEM.slots]                    # kept for old code paths (len / truthiness)
PREFERRED = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
             "gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
MODELS, BAD, _CLIENTS = [], set(), {}


def clients():
    return _CLIENTS


def _gclient(slot):
    if slot.value not in _CLIENTS:
        from google import genai
        _CLIENTS[slot.value] = genai.Client(api_key=slot.value)
    return _CLIENTS[slot.value]


def discover_models():
    if not GEM.slots:
        return []
    names = [MODEL] + PREFERRED
    try:
        for m in _gclient(GEM.slots[0]).models.list():
            n = m.name.replace("models/", "")
            skip = ("image", "live", "tts", "audio", "embed", "native", "robotics", "computer")
            if "flash" in n and not any(x in n for x in skip):
                names.append(n)
    except Exception as e:
        log("[gemini] model list failed:", str(e)[:120])
    out = []
    for n in names:
        if n not in out:
            out.append(n)
    log("[gemini] models to try:", out[:8])
    return out[:8]


# ---------------------------------------------------------------- GROQ (primary) -> Gemini (fallback)
GROQ_KEYS = [sl.value for sl in GRQ.slots]


def _models(env, default):
    v = os.environ.get(env, "").strip()
    return [m.strip() for m in v.split(",") if m.strip()] if v else default


# Verified at start-up against Groq's live model list (see groq_discover). Defaults = what worked in the real log.
_TEXT_PREF = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"]   # primary, fallback, recovery
GROQ_SEARCH_MODELS = _models("GROQ_SEARCH_MODELS", [])
GROQ_TEXT_MODELS = _models("GROQ_TEXT_MODELS", _TEXT_PREF[:2])
GROQ_VISION_MODELS = _models("GROQ_VISION_MODELS", [])
GROQ_BAD = GRQ.bad_models


def groq_discover():
    """Ask Groq which models this key can really use, then keep: 1 primary + 1 fallback + 1 recovery for text,
    and vision/search models ONLY if they exist. No more cycling through IDs that return 404."""
    global GROQ_TEXT_MODELS, GROQ_VISION_MODELS, GROQ_SEARCH_MODELS
    if not GRQ.slots:
        return
    avail = None
    for sl in GRQ.alive():
        try:
            r = requests.get("https://api.groq.com/openai/v1/models",
                             headers={"Authorization": f"Bearer {sl.value}"}, timeout=20)
            if r.status_code == 200:
                avail = [m.get("id", "") for m in r.json().get("data", []) if m.get("active", True)]
                break
            GRQ.fail(sl, r.status_code, r.text[:200], r.headers)
            log(f"[groq] model list via {sl.label}: HTTP {r.status_code}")
        except Exception as e:
            log("[groq] model list failed:", str(e)[:100])
    if not avail:
        log("[groq] could not verify models -> using defaults", GROQ_TEXT_MODELS)
        return
    if not os.environ.get("GROQ_TEXT_MODELS"):
        pick = [m for m in _TEXT_PREF if m in avail]
        if not pick:                                              # preferred list gone -> any chat model
            junk = ("whisper", "tts", "guard", "embed", "orpheus", "playai", "safeguard", "compound", "distil")
            pick = [m for m in avail if not any(j in m.lower() for j in junk)][:3]
        GROQ_TEXT_MODELS = pick[:3]
    if not os.environ.get("GROQ_VISION_MODELS"):
        GROQ_VISION_MODELS = [m for m in avail if any(w in m.lower() for w in ("llama-4", "vision", "scout", "maverick"))][:2]
    if not os.environ.get("GROQ_SEARCH_MODELS"):
        GROQ_SEARCH_MODELS = [m for m in avail if "compound" in m.lower()][:2]
    log(f"[groq] verified models: text={GROQ_TEXT_MODELS} vision={GROQ_VISION_MODELS or 'none (Gemini does vision)'} "
        f"search={GROQ_SEARCH_MODELS or 'none'}")


def _failed_generation(body):
    """Groq 'Failed to validate JSON' carries the model's raw output in failed_generation -> callers can still use it."""
    try:
        j = json.loads(body)
        fg = (j.get("error") or {}).get("failed_generation")
        return fg.strip() if isinstance(fg, str) and len(fg.strip()) > 20 else None
    except Exception:
        return None


LAST_CALL = {}          # round 3: which provider/model/key label answered the latest ask() (labels only, never key values)


def ask_groq(prompt, search=False, json_mode=False, image=None):
    """Groq answer. Walks verified models x healthy keys; cooling/dead keys are skipped instantly.
    None => caller falls back to Gemini."""
    if not GRQ.slots:
        return None
    if image is not None:
        models = GROQ_VISION_MODELS
    elif search:
        models = GROQ_SEARCH_MODELS + GROQ_TEXT_MODELS
    else:
        models = GROQ_TEXT_MODELS
    if image is not None:
        imgs = image if isinstance(image, (list, tuple)) else [image]        # round 4: several sheets in ONE call
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(i).decode()}} for i in imgs]
    else:
        content = prompt
    sys_msg = "Return ONLY valid JSON. No markdown, no commentary." if json_mode else None
    for model in models:
        if model in GROQ_BAD:
            continue
        for slot in GRQ.candidates(model):
            use_rf = json_mode and not model.startswith("groq/compound") and not model.startswith("qwen")
            for attempt in range(2):
                body = {"model": model, "temperature": 0.7,
                        "messages": ([{"role": "system", "content": sys_msg}] if sys_msg else [])
                                    + [{"role": "user", "content": content}]}
                if use_rf:
                    body["response_format"] = {"type": "json_object"}
                try:
                    r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                                      headers={"Authorization": f"Bearer {slot.value}"}, json=body, timeout=120)
                except Exception as e:
                    log(f"[groq] {model} {slot.label} net error: {str(e)[:100]}")
                    time.sleep(2)
                    continue
                if r.status_code == 200:
                    txt = (r.json()["choices"][0]["message"].get("content") or "").strip()
                    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()
                    if txt:
                        GRQ.ok(slot, model)
                        LAST_CALL.update(provider="groq", model=model, key=slot.label)
                        log(f"[groq] ok: {model} ({slot.label})")
                        return txt
                    break
                msg = r.text[:300].replace("\n", " ")
                if r.status_code == 400 and json_mode:
                    fg = _failed_generation(r.text)
                    if fg:                                   # the model DID answer; JSON mode just disliked it
                        log(f"[groq] {model}: JSON validation failed -> using its raw output (caller repairs/validates)")
                        return fg
                    if use_rf and attempt == 0:
                        use_rf = False                       # retry once without json mode
                        continue
                kind = GRQ.fail(slot, r.status_code, msg, r.headers, scope=model)
                wait = GRQ.until.get((slot.label, model), 0) - time.time()
                log(f"[groq] {model} {slot.label} HTTP {r.status_code} -> {kind}" + (f", cooling {wait:.0f}s" if kind in ("rate", "server") else ""))
                break
    return None


def _gem_status(msg):
    m = re.search(r"\b(4\d\d|5\d\d)\b", msg)
    st = int(m.group(1)) if m else 0
    if "RESOURCE_EXHAUSTED" in msg:
        st = 429
    if "NOT_FOUND" in msg:
        st = 404
    if "API_KEY_INVALID" in msg or "PERMISSION_DENIED" in msg:
        st = st or 403
    return st


def _ask_once(prompt, search, json_mode, image):
    out = ask_groq(prompt, search=search, json_mode=json_mode, image=image)
    if out:
        return out
    if not GEM.slots:
        return None
    from google.genai import types
    cfg = {}
    if search:
        cfg["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    if json_mode and not search:
        cfg["response_mime_type"] = "application/json"
    contents = prompt
    if image is not None:
        imgs = image if isinstance(image, (list, tuple)) else [image]
        contents = [types.Part.from_bytes(data=i, mime_type="image/jpeg") for i in imgs] + [prompt]
    tried = False
    for model in MODELS:
        if model in GEM.bad_models:
            continue
        for slot in GEM.candidates(model):
            if not tried:
                log("[llm] Groq unavailable -> Gemini fallback")
                tried = True
            try:
                r = _gclient(slot).models.generate_content(model=model, contents=contents,
                                                           config=types.GenerateContentConfig(**cfg))
                if r.text:
                    GEM.ok(slot, model)
                    LAST_CALL.update(provider="gemini", model=model, key=slot.label)
                    log(f"[gemini] ok: {model} ({slot.label})")
                    return r.text
            except Exception as e:
                msg = str(e)
                st = _gem_status(msg)
                kind = GEM.fail(slot, st, msg[:300], scope=model)
                wait = GEM.until.get((slot.label, model), 0) - time.time()
                log(f"[gemini] {model} {slot.label} {st or 'error'} -> {kind}" + (f", cooling {wait:.0f}s" if kind in ("rate", "server") else f": {msg[:90]}"))
                if kind == "other":
                    time.sleep(2)
    return None


def _ask_inner(prompt, search=False, json_mode=False, image=None):
    """Groq first, then Gemini. Healthy-key rotation + cooldowns. If EVERYTHING is merely cooling (rate-limited,
    not dead) and the wait is short, wait once and try again instead of failing the whole build."""
    out = _ask_once(prompt, search, json_mode, image)
    if out:
        return out
    waits = []
    for ring_, scopes in ((GRQ, GROQ_TEXT_MODELS), (GEM, MODELS)):
        for sc in scopes:
            w = ring_.wait_needed(sc)
            if w is not None:
                waits.append(w)
    if waits and min(waits) <= 75:
        w = min(waits) + 1
        log(f"[llm] all providers rate-limited -> waiting {w:.0f}s then retrying once")
        time.sleep(w)
        return _ask_once(prompt, search, json_mode, image)
    return None


def ask(prompt, search=False, json_mode=False, image=None, task=None):
    """Round 3 wrapper around the provider walk. Every text call is prefixed with the shared PROJECT STATE
    (final topic, verified facts, locked-script rules, what the previous AI already did), so a fallback provider
    continues instead of restarting. After the call the answering provider is written to the project memory.
    Vision calls (clip choice) skip the block: they decide nothing about the script."""
    st = project_state.current()
    if st is not None and image is None:
        prompt = st.handoff_block(task) + prompt
    LAST_CALL.clear()
    out = _ask_inner(prompt, search=search, json_mode=json_mode, image=image)
    if out and st is not None and image is None and LAST_CALL:
        try:
            st.record_call(task or st.d.get("stage_now", ""), LAST_CALL.get("provider", ""), LAST_CALL.get("model", ""),
                           LAST_CALL.get("key", ""), summary=re.sub(r"\s+", " ", out)[:120])
        except Exception as e:
            log("[state] record_call failed:", str(e)[:80])
    return out


def pick_topic_plan():
    forced = MODE if MODE in ("awareness", "student") else None
    try:
        return topics.plan(ask, research_engine.default_http_get, os.environ.get("YT_API_KEY", "").strip(), forced, log=log)
    except Exception as e:                                  # topic planner must never stop the build
        log("[topics] failed, old alternate-day mode:", str(e)[:100])
        m = pick_mode()
        return {"kind": "disorder" if m == "awareness" else "habit", "mode": m, "subject": "", "audience": "",
                "trend": "", "angle": "", "directive": ""}


def pick_mode():
    if MODE in ("awareness", "student"):
        return MODE
    return "awareness" if time.gmtime().tm_yday % 2 else "student"


def _brief(a, d, m, s):
    try:
        return virality.viral_brief(a, d, m, s, directive=DIRECTIVE[0])
    except TypeError:                                # older viral_brief without the directive argument
        return virality.viral_brief(a, d, m, s)


def research(done, mode):
    st = project_state.current()
    if st is not None:
        st.set_stage("research")
    try:                                             # round 3: claims -> PubMed/Wikipedia evidence -> verified facts only
        rec = research_engine.run(ask, done, mode, SAFETY, log=log, directive=DIRECTIVE[0],
                                  brief_fn=_brief)
    except Exception as e:
        log("[research] engine failed, old research:", str(e)[:100])
        rec = None
    if rec and rec.get("facts_text"):
        if st is not None:
            st.set_research({k: rec.get(k) for k in ("topic", "verified", "sources", "level", "hook", "tip")}
                            | {"dropped": [d[0][:100] + " (" + d[1] + ")" for d in rec.get("dropped", [])][:8]})
            st.stage_done("research", LAST_CALL.get("provider", ""), rec.get("level", ""))
        return rec["facts_text"]
    try:                                             # v7: real outlier data + 21 formulas
        t = _brief(ask, done, mode, SAFETY)
        if t:
            return t
    except Exception as e:
        log("[research] viral brief failed, old research:", str(e)[:100])
    if mode == "awareness":
        focus = ("mental health, psychology and psychiatry awareness for young Indian "
                 "viewers (e.g. how anxiety/stress/burnout/sleep affect the brain, myths vs facts, "
                 "healthy habits, when to seek help)")
    else:
        focus = ("study productivity and exam preparation for Indian students: evidence-based "
                 "techniques (active recall, spaced repetition, sleep, focus, handling exam "
                 "anxiety, time management)")
    prompt = f"""You are a researcher for an English Shorts channel for Indian viewers. Focus: {focus}.
Topics already covered (do NOT repeat): {done[-40:]}
{SAFETY}
{DIRECTIVE[0] or "Pick ONE fresh topic that would hook viewers."} Research it using reliable sources
(peer-reviewed research, WHO, NIMH, NIMHANS, APA etc.).
Return plain text: the topic, 5-6 accurate key facts, one hook, one practical tip, and a one-line note of the sources."""
    txt = ask(prompt, search=True) or ask(prompt)
    if not txt:
        sys.exit("Research failed (Groq + Gemini dono). Keys/quota check karo.")
    return txt


def write_script(facts):
    prompt = f"""Using this research:
{facts}

{SAFETY}

Write a ~45 second HINGLISH Reel as a list of SCENES. Return ONLY JSON with keys:
"title": viral Shorts title in natural Hinglish (Roman script), max 70 chars, no hashtags, no clickbait lies.
"title_en": the same title in simple English.
"formula": name of the hook formula used (from the 21).
"kicker": 2-3 word UPPERCASE label shown on screen at the start (e.g. "BRAIN SCIENCE", "STUDY HACK").
"hook_text": 3-6 word UPPERCASE hook shown BIG on screen in the first 2 seconds (curiosity or a bold claim, e.g. "YE HABIT TUMHE THAKA RAHI HAI"). Must not repeat scene 1 word for word.
"scenes": a list of 11 to 13 scenes. Each scene is an object with:
   "text": ONE short spoken sentence or part of a sentence (7-12 words) in natural HINGLISH written in
      Roman script (Hindi words in English letters, the way an Indian senior talks to juniors; no Devanagari,
      no emojis, no jargon), written to be SPOKEN. Simple everyday Hindi, short clear sentences.
   "text_hi": the SAME line written in DEVANAGARI script (pure natural spoken Hindi; common English words such as
      study, focus, challenge may stay in English letters). Same meaning, same word order as "text". Used by the
      Hindi voice, so it must read naturally aloud.
   "text_en": the SAME line in simple conversational English (used only if the Hindi voice is unavailable).
      Scene 1 is a strong hook (a question or a surprising fact). The last scene is one practical takeaway.
      Do NOT mention any website or app (added automatically).
   "queries": a list of 3 stock-VIDEO search phrases (2-4 plain English words each) for what is
      literally shown while that line is spoken: concrete visible things that exist in stock libraries
      (e.g. "student studying night", "woman yawning bed", "alarm clock ringing", "brain scan",
      "walking forest path", "coffee steam desk"). Most specific first, most generic last.
      NEVER abstract words (willpower, mindset, anxiety). Every scene must show something DIFFERENT.
      Calm, bright or warm, non-graphic, non-stigmatising visuals; never a person in visible distress.
   "emphasis": OPTIONAL, only in 3-4 scenes: the 1-3 most important words of that line, to be
      shown big on screen (e.g. "FREEZE RESPONSE"). Use "" for the other scenes.
STORY RULES (very important): the video must make complete sense to someone who has never heard of the topic.
   Scene order = hook question -> the relatable problem -> ONE clear idea explained in plain words ->
   2-3 concrete steps said in order ("pehle... phir... last mein...") -> one-line takeaway.
   Every line must follow from the previous one. No filler, no repeated points, no jargon, no "send this to a friend"
   in the middle (at most in the last scene). Do not invent statistics. If the topic is a social-media trend, say
   exactly what the trend is in scene 2 in one plain sentence.
Total narration across all scenes: 100-112 words (in each language).
{virality.VIRAL_RULES}
{virality.SHARE_RULES}
"description": 2-3 line English description.
"hashtags": list of 6 hashtags (with #).
Facts must be accurate; do not invent numbers."""
    for _ in range(3):
        raw = ask(prompt, json_mode=True)
        if not raw:
            continue
        try:
            data = json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip()).strip())
            for k in ("title", "scenes", "description", "hashtags"):
                assert k in data
            sc = []
            for x in data["scenes"]:
                q = x.get("queries") or x.get("query") or []
                if isinstance(q, str):
                    q = [q]
                q = [str(z).strip() for z in q if str(z).strip()]
                if x.get("fallback"):
                    q.append(str(x["fallback"]))
                if x.get("text") and q:
                    sc.append({"text": str(x["text"]).strip(), "queries": q,
                               "text_en": str(x.get("text_en") or x["text"]).strip(),
                               "text_hi": re.sub(r"\s+", " ", str(x.get("text_hi") or "")).strip(),
                               "emphasis": str(x.get("emphasis") or "").strip().upper()[:28]})
            assert len(sc) >= 6
            data["scenes"] = sc
            data["kicker"] = str(data.get("kicker") or "DID YOU KNOW").upper()[:24]
            data["title_en"] = str(data.get("title_en") or data["title"])
            data["hook_text"] = re.sub(r"\s+", " ", str(data.get("hook_text") or "")).strip().upper()[:46]
            return data
        except Exception as e:
            log("[script] bad JSON, retrying:", e)
    sys.exit("Script generation failed.")


# ================================================================== 2. VOICE (har scene alag => exact sync)
SR = 48000
TOK = re.compile(r"\[([^\]|]+)\|([^\]]+)\]")


def parse_text(text):
    """'Visit [www.x.in|W W W dot x dot in].' -> [(display, [spoken words]), ...]"""
    items, pos = [], 0

    def plain(chunk):
        for w in chunk.split():
            if items and not re.search(r"[A-Za-z0-9]", w):     # akeli punctuation: pichle shabd se jodo
                d, s = items[-1]
                items[-1] = (d + w, s[:-1] + [s[-1] + w])
            else:
                items.append((w, [w]))
    for m in TOK.finditer(text):
        plain(text[pos:m.start()])
        items.append((m.group(1), m.group(2).split()))
        pos = m.end()
    plain(text[pos:])
    return items


async def _tts(text, voice, rate):
    import edge_tts
    try:
        comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    except TypeError:
        comm = edge_tts.Communicate(text, voice, rate=rate)
    audio, ev = bytearray(), []
    async for ch in comm.stream():
        if ch["type"] == "audio":
            audio += ch["data"]
        elif ch["type"] in ("WordBoundary", "SentenceBoundary"):
            ev.append((ch["type"], ch["offset"] / 1e7, ch["duration"] / 1e7, ch.get("text", "")))
    return bytes(audio), ev


def decode_audio(data):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "f32le", "-ac", "1",
                        "-ar", str(SR), "pipe:1"], input=data, capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.float32).copy()


def syllables(w):
    return max(1, len(re.findall(r"[aeiouy]+", w.lower())))


def proportional_times(words, t0, t1):
    """shabdon ko [t0,t1] mein syllable + punctuation pause ke hisaab se baantna."""
    wts, pauses = [], []
    for w in words:
        wts.append(0.55 + syllables(w))
        pauses.append(0.9 if re.search(r"[.!?]$", w) else 0.5 if re.search(r"[,;:]$", w) else 0.0)
    total = sum(wts) + sum(pauses[:-1])
    unit = (t1 - t0) / max(total, 1e-6)
    out, t = [], t0
    for w, ww, pz in zip(words, wts, pauses):
        out.append((t, t + ww * unit))
        t += (ww + pz) * unit
    return out


def spoken_word_times(spoken, ev, a0, a1):
    """spoken: list of words. ev: edge-tts boundary events. returns [(start,end)] in trimmed audio time."""
    wev = [e for e in ev if e[0] == "WordBoundary"]
    if len(wev) >= max(2, int(0.8 * len(spoken))):
        out = []
        for i in range(len(spoken)):
            e = wev[min(len(wev) - 1, int(i * len(wev) / len(spoken)))]
            out.append((max(0.0, e[1] - a0), max(0.0, e[1] + e[2] - a0)))
        # monotonic + gaps
        for i in range(len(out) - 1):
            if out[i][1] > out[i + 1][0]:
                out[i] = (out[i][0], out[i + 1][0])
        return out
    sev = [e for e in ev if e[0] == "SentenceBoundary"]
    if len(sev) >= 2:      # sentence ke andar proportional
        out, idx = [], 0
        sent_words = [s[3].split() for s in sev]
        if sum(len(x) for x in sent_words) == len(spoken):
            for e, sw in zip(sev, sent_words):
                s0, s1 = max(0.0, e[1] - a0), max(0.0, e[1] + e[2] - a0)
                out += proportional_times(sw, s0, s1)
            return out
    return proportional_times(spoken, 0.0, a1 - a0 if a1 > a0 else 1.0)


def synth_scene(text, voice, rate, tts_text=None):
    """text = Roman words shown as captions. tts_text = same line in Devanagari (v16): that is what the voice reads,
    so a real Hindi pronunciation comes out; caption timing maps word-by-word (spoken_word_times scales by index)."""
    items = parse_text(text)
    spoken = [w for _, s in items for w in s]
    say = (tts_text or "").strip() or " ".join(spoken)
    if voice == "ELEVEN":
        audio, ev = eleven_voice.tts(say)
    elif voice == "AZURE":
        audio, ev = azure_voice.tts(say)
    else:
        audio, ev = asyncio.run(_tts(say, voice, rate))
    x = decode_audio(audio)
    env = np.abs(x)
    idx = np.where(env > 0.012)[0]
    if len(idx) == 0:
        raise RuntimeError("silent audio")
    s0 = max(0, idx[0] - int(0.05 * SR))
    s1 = min(len(x), idx[-1] + int(0.14 * SR))
    y = x[s0:s1]
    a0 = s0 / SR                              # trim ka offset (events isi se shift honge)
    dur = len(y) / SR
    sp_times = spoken_word_times(spoken, ev, a0, dur + a0)
    words, k = [], 0
    for disp, sp in items:
        ts = sp_times[k:k + len(sp)]
        k += len(sp)
        st, en = ts[0][0], ts[-1][1]
        words.append((disp, min(st, dur), min(max(en, st + 0.08), dur)))
    return y, dur, words


def _make_voice_edge(scenes, max_total=52.0, voices=None, use_hi=False):
    voices = voices or [VOICE] + [v for v in FALLBACK_VOICES if v != VOICE]
    for voice in voices:
        for rate in ("+0%", "+7%", "+13%"):
            try:
                res = []
                for i, sc in enumerate(scenes):
                    for attempt in range(3):
                        try:
                            res.append(synth_scene(sc["text"], voice, rate, sc.get("text_hi") if use_hi else None))
                            break
                        except Exception as e:
                            if attempt == 2:
                                raise
                            log(f"[voice] retry scene {i + 1}: {str(e)[:80]}")
                            time.sleep(2)
            except Exception as e:
                log(f"[voice] {voice} failed: {str(e)[:100]}")
                break
            total = sum(r[1] for r in res) + 0.2 * len(res)
            log(f"[voice] {voice} rate {rate}: {total:.1f}s")
            if total <= max_total or rate == "+13%":
                return res, voice
    sys.exit("Voice generation failed.")


ELEVEN_FALLBACK = os.environ.get("ELEVEN_FALLBACK", "hindi").strip().lower()   # hindi (free Hindi neural voice) | english | fail
HINDI_VOICES = [v for v in os.environ.get("HINDI_VOICES", "hi-IN-MadhurNeural,hi-IN-SwaraNeural").split(",") if v]


def _eleven_pass(scenes, max_total, hindi):
    for sp in (1.05, 1.12, 1.18):
        eleven_voice.SPEED[0] = sp
        res = [synth_scene(sc["text"], "ELEVEN", "+0%", sc.get("text_hi") if hindi else None) for sc in scenes]
        total = sum(r[1] for r in res) + 0.2 * len(res)
        log(f"[voice] ElevenLabs {'HINDI-PRO' if hindi else 'English'} speed {sp}: {total:.1f}s")
        if total <= max_total or sp == 1.18:
            return res
    return res


def make_voice(scenes, max_total=52.0, engine="auto"):
    """v17 policy (Hindi only from a verified PROFESSIONAL Hindi ElevenLabs voice):
       1) ElevenLabs Hindi-pro voice (ELEVEN_HINDI_VOICE_IDS, verified)  -> Hindi (Devanagari) voice, Roman captions
       2) otherwise the WHOLE video is ENGLISH (text_en):  ElevenLabs English voice -> Azure English -> edge-tts English.
    Returns (res, voice_name, lang)."""
    hindi = None
    if engine != "local" and eleven_voice.available() and all(sc.get("text_hi") for sc in scenes):
        hindi = eleven_voice.find_hindi_pro_voice()
    if hindi:
        eleven_voice.ACTIVE.update(voices=[hindi], lang="hi")
        try:
            return _eleven_pass(scenes, max_total, True), "ELEVEN", "hinglish"
        except Exception as e:
            log("[voice] Hindi-pro voice failed:", str(e)[:160], "-> ENGLISH content")
    else:
        log("[voice] no verified professional Hindi ElevenLabs voice -> ENGLISH content (set ELEVEN_HINDI_VOICE_IDS)")
    for sc in scenes:                                   # English from here on: captions + voice both use text_en
        sc["text"] = sc.get("text_en") or sc["text"]
    if engine != "local" and eleven_voice.available():
        eleven_voice.ACTIVE.update(voices=None, lang="en")
        try:
            return _eleven_pass(scenes, max_total, False), "ELEVEN", "english"
        except Exception as e:
            log("[voice] ElevenLabs English failed:", str(e)[:160])
    if azure_voice.available():
        try:
            res = [synth_scene(sc["text"], "AZURE", "+0%") for sc in scenes]
            log(f"[voice] Azure English: {sum(r[1] for r in res):.1f}s")
            return res, "AZURE", "english"
        except Exception as e:
            log("[voice] Azure failed:", str(e)[:160])
    res, voice = _make_voice_edge(scenes, max_total)
    return res, voice, "english"


def audio_filter(x, af, sr=SR, ch=1):
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", str(ch),
                        "-i", "pipe:0", "-af", af, "-f", "f32le", "-ar", str(sr), "-ac", str(ch),
                        "pipe:1"], input=x.astype(np.float32).tobytes(), capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.float32).copy()


# ================================================================== 3. MUSIC + SFX (offline, synth)
def _hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def _reverb(x, sr=SR, secs=2.4, seed=1):
    rng = np.random.default_rng(seed)
    n = int(secs * sr)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / sr * 3.2)
    ir = np.convolve(ir, np.ones(24) / 24, "same")          # naram (lowpass) tail
    ir[: int(0.012 * sr)] *= np.linspace(0, 1, int(0.012 * sr))
    ir /= np.sqrt((ir ** 2).sum())
    N = 1 << int(np.ceil(np.log2(len(x) + len(ir))))
    y = np.fft.irfft(np.fft.rfft(x, N) * np.fft.rfft(ir, N), N)[: len(x)]
    return y.astype(np.float32)


def synth_music(total, seed=7):
    """Naram ambient pad + dheemi bell notes (focus music). Stereo float32 (n,2), peak ~0.9."""
    if os.environ.get("MUSIC_STYLE", "flute").strip().lower() == "flute":      # Round 6: calming flute (MUSIC_STYLE=pad = old pad)
        try:
            import flute
            return flute.synth(total, seed)
        except Exception as e:
            log("[music] flute failed, pad instead:", str(e)[:80])
    rng = np.random.default_rng(seed)
    n = int(total * SR)
    t = np.arange(n) / SR
    chords = [[45, 57, 60, 64, 71], [41, 57, 60, 65, 69], [48, 55, 59, 64, 67], [43, 55, 59, 62, 69]]
    seg = 8.0
    out = np.zeros((n, 2), np.float32)
    for ch_i in range(2):
        pad = np.zeros(n, np.float32)
        for ci, notes in enumerate(chords * int(total / (seg * 4) + 2)):
            c0 = ci * seg - 1.5
            if c0 > total:
                break
            win = np.clip((t - c0) / 2.5, 0, 1) * np.clip((c0 + seg + 1.5 - t) / 2.5, 0, 1)
            win = np.sin(win * np.pi / 2) ** 2
            if not win.any():
                continue
            lo, hi = max(0, int(c0 * SR)), min(n, int((c0 + seg + 3) * SR))
            tt = t[lo:hi]
            acc = np.zeros(hi - lo, np.float32)
            for j, m in enumerate(notes):
                f = _hz(m)
                for det in (-0.0016, 0.0, 0.0016):
                    ph = rng.uniform(0, 6.28)
                    f2 = f * (1 + det * (1 if ch_i else -1))
                    lfo = 0.75 + 0.25 * np.sin(2 * np.pi * (0.07 + 0.03 * j) * tt + ph)
                    acc += (np.sin(2 * np.pi * f2 * tt + ph) + 0.28 * np.sin(4 * np.pi * f2 * tt + ph)
                            + 0.1 * np.sin(6 * np.pi * f2 * tt)) * lfo * (0.18 if m < 50 else 0.1)
            pad[lo:hi] += acc * win[lo:hi]
        out[:, ch_i] = pad
    # dheemi bells (A minor pentatonic), har ~1.5 s par
    bells = np.zeros((n, 2), np.float32)
    scale = [69, 72, 74, 76, 79, 81, 84]
    pos = 3.0
    while pos < total - 2:
        if rng.random() < 0.75:
            f = _hz(rng.choice(scale))
            L = int(2.2 * SR)
            tt = np.arange(L) / SR
            env = np.exp(-tt * 2.6) * np.minimum(1, tt / 0.01)
            tone = (np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(2 * np.pi * f * 2.76 * tt) * np.exp(-tt * 5)) * env
            s = int(pos * SR)
            e = min(n, s + L)
            pan = rng.uniform(0.3, 0.7)
            bells[s:e, 0] += tone[: e - s] * 0.07 * (1 - pan) * 2
            bells[s:e, 1] += tone[: e - s] * 0.07 * pan * 2
        pos += 1.5
    mix = out + bells
    for c in range(2):
        mix[:, c] = mix[:, c] + 0.55 * _reverb(mix[:, c], seed=3 + c)
    # lowpass ~5 kHz (naram) + fade
    spec = np.fft.rfft(mix, axis=0)
    fr = np.fft.rfftfreq(n, 1 / SR)
    spec *= (1 / (1 + (fr / 5200.0) ** 4))[:, None] * (1 / (1 + (55.0 / np.maximum(fr, 1.0)) ** 4))[:, None]
    mix = np.fft.irfft(spec, n, axis=0).astype(np.float32)
    mix *= np.minimum(1, t / 2.0)[:, None] * np.minimum(1, (total - t) / 1.8)[:, None]
    mix /= max(1e-6, np.abs(mix).max()) / 0.9
    return mix


def sfx_whoosh(dur=0.55, up=True, seed=0):
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    noise = rng.standard_normal(n).astype(np.float32)
    x = np.linspace(0, 1, n)
    cut = (350 + 5200 * (x if up else x[::-1]) ** 1.6) / SR * 2 * np.pi
    a = np.clip(cut, 0.01, 1.2)
    y = np.zeros(n, np.float32)
    s = 0.0
    k = 0.0
    for i in range(n):         # 2-pole lowpass, cutoff sweep
        s += a[i] * (noise[i] - s)
        k += a[i] * (s - k)
        y[i] = k
    env = np.sin(np.pi * np.clip(x, 0, 1)) ** 2
    y *= env.astype(np.float32)
    y /= max(1e-6, np.abs(y).max())
    return y * 0.9


def sfx_ding(dur=1.6):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    y = np.zeros(n, np.float32)
    for f, g in ((1318.5, 1.0), (1975.5, 0.6), (2637.0, 0.35), (3951.0, 0.15)):
        y += g * np.sin(2 * np.pi * f * tt) * np.exp(-tt * (2.8 + f / 2500))
    y += 0.8 * np.sin(2 * np.pi * 62 * tt) * np.exp(-tt * 4.5)       # halka thump
    y *= np.minimum(1, tt / 0.004)
    return (y / np.abs(y).max() * 0.9).astype(np.float32)


def sfx_pop(dur=0.18):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    y = np.sin(2 * np.pi * (520 - 700 * tt) * tt) * np.exp(-tt * 28)
    return (y * 0.8).astype(np.float32)


def build_mix(voice, total, whooshes, ding_at, voice_mask, music_path=None):
    """voice: mono float32 (n). returns stereo float32."""
    n = int(total * SR)
    v = np.zeros(n, np.float32)
    v[: min(n, len(voice))] = voice[:n]
    stereo = np.stack([v, v], 1) * 1.0
    # music
    music = None
    if MUSIC_ON:
        if music_path and Path(music_path).exists():
            try:
                r = run(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", str(music_path), "-t",
                         f"{total:.2f}", "-f", "f32le", "-ac", "2", "-ar", str(SR), "pipe:1"])
                music = np.frombuffer(r.stdout, np.float32).reshape(-1, 2).copy()
                music = music[:n]
                fade = np.minimum(1, np.arange(len(music)) / (2 * SR))
                music *= fade[:, None] * np.minimum(1, (len(music) - np.arange(len(music))) / (1.8 * SR))[:, None]
            except Exception as e:
                log("[music] file skip:", str(e)[:100])
        if music is None:
            music = synth_music(total)
        if len(music) < n:
            music = np.pad(music, ((0, n - len(music)), (0, 0)))
        env = np.convolve(np.abs(v), np.ones(int(0.05 * SR)) / int(0.05 * SR), "same")
        env = np.clip(env / 0.08, 0, 1)
        # smooth: tez attack, dheema release
        sm = np.zeros(n, np.float32)
        a_att, a_rel, cur = 1 - math.exp(-1 / (0.08 * SR)), 1 - math.exp(-1 / (0.5 * SR)), 0.0
        step = 480
        for i in range(0, n, step):
            tgt = env[i:i + step].max()
            cur += (tgt - cur) * (1 - (1 - (a_att if tgt > cur else a_rel)) ** step)
            sm[i:i + step] = cur
        gain = 0.34 - 0.20 * sm          # awaaz ke waqt ~ -19 dB, khaali mein upar
        stereo += music[:n] * gain[:, None] * 0.55
    for at, kind, g in whooshes:
        w = {"up": sfx_whoosh(0.5, True, int(at * 10)), "down": sfx_whoosh(0.5, False, int(at * 10) + 1),
             "pop": sfx_pop()}[kind]
        s = int(max(0, at) * SR)
        e = min(n, s + len(w))
        if e > s:
            stereo[s:e] += (w[: e - s] * g)[:, None]
    if ding_at is not None:
        d = sfx_ding()
        s = int(ding_at * SR)
        e = min(n, s + len(d))
        stereo[s:e] += (d[: e - s] * 0.35)[:, None]
    return stereo


def write_wav(path, stereo):
    pcm = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())


# ================================================================== 4. STOCK FOOTAGE (relevant clips, Gemini vision se chunav)
USED = set()
FOOTAGE_KEEP_DAYS = int(os.environ.get("FOOTAGE_NO_REPEAT_DAYS", "14"))   # same clip is not reused within N days (variety)
FOOTAGE_MAX_MB = int(os.environ.get("FOOTAGE_CACHE_MB", "1500"))
_FLOCK = __import__("threading").Lock()


def footage_dir():
    d = WORK / "footage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _used_file():
    return footage_dir() / "used.json"


def used_recent():
    """{clip id: date} of clips already shipped lately, so tomorrow's video does not look like today's."""
    try:
        d = json.loads(_used_file().read_text())
        cut = time.time() - FOOTAGE_KEEP_DAYS * 86400
        return {k for k, v in d.items() if v >= cut}
    except Exception:
        return set()


def mark_used(cid):
    with _FLOCK:
        try:
            d = json.loads(_used_file().read_text()) if _used_file().exists() else {}
        except Exception:
            d = {}
        d[cid] = time.time()
        d = {k: v for k, v in d.items() if v >= time.time() - 60 * 86400}
        _used_file().write_text(json.dumps(d))


def cached_search(src, q, fn):
    """Stock search results cached for 7 days (same query on a retry / resume / next run = zero API calls).
    Empty results are not cached (a rate-limited key must not poison the cache)."""
    import hashlib
    p = footage_dir() / ("s_" + hashlib.md5(f"{src}|{q}|{LANDSCAPE}".encode()).hexdigest()[:16] + ".json")
    try:
        if p.exists() and time.time() - p.stat().st_mtime < 7 * 86400:
            return json.loads(p.read_text())
    except Exception:
        pass
    out = fn(q)
    if out:
        try:
            p.write_text(json.dumps(out))
        except Exception:
            pass
    return out


def prune_footage(max_mb=None):
    """Keep the cache folder small (GitHub cache limit): delete oldest clips first. Returns MB left."""
    d = footage_dir()
    files = sorted((f for f in d.glob("clip_*.mp4")), key=lambda f: f.stat().st_mtime)
    total = sum(f.stat().st_size for f in files) / 1e6
    lim = max_mb or FOOTAGE_MAX_MB
    for f in files:
        if total <= lim:
            break
        total -= f.stat().st_size / 1e6
        f.unlink(missing_ok=True)
    return total


PXR = keyring.ring("pexels")
PBR = keyring.ring("pixabay")


def _stock_get(rg, url, make_kwargs, tag):
    """GET with key rotation: a rate-limited / dead key is skipped, next key is used. None if all keys failed."""
    for slot in rg.candidates():
        try:
            r = requests.get(url, timeout=30, **make_kwargs(slot.value))
        except Exception as e:
            log(f"[{tag}] {slot.label} net error: {str(e)[:80]}")
            continue
        if r.status_code == 200:
            rg.ok(slot)
            return r
        kind = rg.fail(slot, r.status_code, r.text[:200], r.headers)
        log(f"[{tag}] {slot.label} HTTP {r.status_code} -> {kind}; trying next key")
    return None


def _pexels(q, n=10):
    if not PXR.slots:
        return []
    out = []
    sets = ({"orientation": "landscape", "size": "large"},) if LANDSCAPE else (
        {"orientation": "portrait", "size": "medium"}, {"size": "large"})
    for params in sets:
        try:
            r = _stock_get(PXR, "https://api.pexels.com/videos/search",
                           lambda k: {"headers": {"Authorization": k}, "params": {"query": q, "per_page": n, **params}}, "pexels")
            if r is None:
                break
            for v in r.json().get("videos", []):
                files = [f for f in v.get("video_files", [])
                         if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")]
                if not files:
                    continue
                port = [f for f in files if f["height"] > f["width"]]
                if LANDSCAPE:
                    land = [f for f in files if f["width"] > f["height"]]
                    ok = [f for f in land if f["width"] <= 2600] or land or files
                    f = min(ok, key=lambda f: abs(f["width"] - 1920))
                elif port:
                    f = min(port, key=lambda f: abs(f["height"] - 1920))
                else:
                    ok = [f for f in files if f["height"] <= 2200] or files
                    f = max(ok, key=lambda f: f["height"])
                out.append({"id": f"px{v['id']}", "src": "pexels", "url": f["link"],
                            "thumb": v.get("image"), "dur": float(v.get("duration", 0)),
                            "w": f["width"], "h": f["height"], "portrait": f["height"] > f["width"]})
        except Exception as e:
            log("[pexels]", q, str(e)[:100])
        if not LANDSCAPE and len([o for o in out if o["portrait"]]) >= 4:
            break
    return out


def _pixabay(q, n=12):
    if not PBR.slots:
        return []
    try:
        r = _stock_get(PBR, "https://pixabay.com/api/videos/",
                       lambda k: {"params": {"key": k, "q": q, "per_page": n, "safesearch": "true", "video_type": "film"}}, "pixabay")
        if r is None:
            return []
        out = []
        for h in r.json().get("hits", []):
            v = h.get("videos", {})
            pick = next((v[k] for k in ("large", "medium", "small")
                         if v.get(k, {}).get("url") and v[k].get("size", 0) < 80e6), None)
            if not pick:
                continue
            out.append({"id": f"pb{h['id']}", "src": "pixabay", "url": pick["url"],
                        "thumb": pick.get("thumbnail"), "dur": float(h.get("duration", 0)),
                        "w": pick.get("width", 0), "h": pick.get("height", 0),
                        "portrait": pick.get("height", 0) > pick.get("width", 0)})
        return out
    except Exception as e:
        log("[pixabay]", q, str(e)[:100])
        return []


def gather_candidates(queries, need):
    seen, cands = set(), []
    recent = used_recent()
    for qi, q in enumerate(queries[:4]):
        for c in cached_search("pexels", q, _pexels) + cached_search("pixabay", q, _pixabay):
            if c["id"] in seen or c["id"] in USED or c["id"] in recent or not c.get("thumb"):
                continue
            seen.add(c["id"])
            c["qrank"] = qi
            if LANDSCAPE:
                fit = 2.0 if not c["portrait"] else -3.0
                res_ = 0.7 if c["w"] >= 1900 else 0.4 if c["w"] >= 1280 else -1.0
            else:
                fit = 2.5 if c["portrait"] else 0
                res_ = 0.7 if c["h"] >= 1900 else 0.4 if c["h"] >= 1440 else 0.1 if c["h"] >= 1080 else -1.0
            c["score"] = fit + min(c["dur"] / max(need, 0.5), 1.6) + res_ + 0.6 / (1 + qi)
            cands.append(c)
    cands.sort(key=lambda c: -c["score"])
    return cands[:6]


def contact_sheet(cands):
    """candidates ke thumbnails ko number laga ke ek image mein (Gemini ko ek hi image bhejna sasta hai)."""
    tiles = []
    for i, c in enumerate(cands):
        try:
            im = Image.open(io.BytesIO(requests.get(c["thumb"], timeout=20).content)).convert("RGB")
        except Exception:
            im = Image.new("RGB", (320, 180), (30, 30, 30))
        im.thumbnail((420, 300))
        tile = Image.new("RGB", (420, 300), (20, 20, 20))
        tile.paste(im, ((420 - im.width) // 2, (300 - im.height) // 2))
        d = ImageDraw.Draw(tile)
        d.rectangle([0, 0, 54, 54], fill=(0, 0, 0))
        d.text((12, 6), str(i + 1), fill=(255, 255, 0), font=ImageFont.truetype(find_font(), 40))
        tiles.append(tile)
    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (420 * cols, 300 * rows), (0, 0, 0))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * 420, (i // cols) * 300))
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def vision_pick(text, topic, cands):
    """Gemini image dekh ke best 2 clips chunta hai. returns (ordered idx list, relevant: bool)."""
    if not cands or not (KEYS or GROQ_VISION_MODELS) or (LANDSCAPE and not LONG_VISION):
        return list(range(len(cands))), True
    prompt = f"""These are {len(cands)} stock-video preview frames numbered 1..{len(cands)}.
A calm educational mental-health/study reel for young Indian viewers (topic: {topic}) says this line:
"{text}"
Pick the 2 clips that BEST visually match what is being said (a concrete subject match matters most),
that look high quality, bright/warm/calm, with no visible text, logos or watermarks, no one in visible
distress, nothing graphic, scary or unsafe. Reject stern/angry/staring faces and elderly people unless the line is about them; prefer young Indian-looking students, desks, books, phones, walking, calm nature. Reply ONLY JSON: {{"best":[first_choice, second_choice],"relevant":true}}
Use "relevant": false if none of them really fits the line."""
    raw = ask(prompt, json_mode=True, image=contact_sheet(cands))
    time.sleep(1)
    try:
        j = json.loads(re.sub(r"^```(?:json)?|```$", "", (raw or "").strip()).strip())
        order = [int(i) - 1 for i in j.get("best", []) if 0 < int(i) <= len(cands)]
        order += [i for i in range(len(cands)) if i not in order]
        return order, bool(j.get("relevant", True))
    except Exception:
        return list(range(len(cands))), True


def download_clip(c):
    p = footage_dir() / f"clip_{c['id']}.mp4"
    if p.exists():
        os.utime(p, None)                                   # cache hit: keep it fresh for pruning
    if not p.exists():
        with requests.get(c["url"], stream=True, timeout=(10, 120)) as r:
            r.raise_for_status()
            size = 0
            with open(p, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    size += len(chunk)
                    if size > 95e6:
                        raise RuntimeError("clip too big")
    info = ffprobe(p)
    if not info or info[2] < 1.0:
        p.unlink(missing_ok=True)
        raise RuntimeError("bad clip")
    return p, info


def pick_clips(scene, topic, need_sec, want):
    """scene ke liye 1-2 sabse relevant clips. [] => procedural motion-graphic background."""
    cands = gather_candidates(scene["queries"], need_sec)
    if not cands:
        return []
    order, relevant = vision_pick(scene["text"], topic, cands)
    if not relevant:
        log(f"[clip] '{scene['text'][:40]}': koi relevant nahi -> motion graphic")
        return []
    got = []
    for i in order:
        c = cands[i]
        if len(got) >= want:
            break
        try:
            p, info = download_clip(c)
        except Exception as e:
            log("[download]", c["id"], str(e)[:90])
            continue
        USED.add(c["id"])
        mark_used(c["id"])
        got.append({"path": p, "w": info[0], "h": info[1], "dur": info[2], "id": c["id"]})
        log(f"[clip] '{scene['text'][:36]}' -> {c['id']} ({info[0]}x{info[1]}, {info[2]:.1f}s)")
    return got


VISION_BATCH = max(1, int(os.environ.get("VISION_BATCH", "4")))      # scenes judged per Gemini/Groq call
PREFETCH_THREADS = max(1, int(os.environ.get("PREFETCH_THREADS", "4")))


def _batch_vision(items, topic):
    """items: [(scene, cands)] -> {index: (order, relevant)} from ONE multi-image call. Scenes the model skips or
    garbles are simply missing (caller falls back to the single-scene picker)."""
    sheets = [contact_sheet(c) for _, c in items]
    lines = "\n".join(f'Image {i + 1} = scene {i + 1}: "{sc["text"]}" ({len(c)} numbered clips)' for i, (sc, c) in enumerate(items))
    prompt = f"""{len(items)} images follow, one per scene of a calm educational mental-health/study reel for young Indian
viewers (topic: {topic}). Each image is a contact sheet of numbered stock-video preview frames.
{lines}
For EACH scene pick the 2 clips that BEST visually match the line (concrete subject match matters most), high quality,
bright/warm/calm, no visible text/logos/watermarks, nobody in visible distress, nothing graphic or unsafe.
Reply ONLY JSON: {{"scenes":[{{"scene":1,"best":[first,second],"relevant":true}}]}}. relevant=false if none fits that line."""
    raw = ask(prompt, json_mode=True, image=sheets)
    out = {}
    try:
        j = json.loads(re.sub(r"^```(?:json)?|```$", "", (raw or "").strip()).strip())
        for r in j.get("scenes", []):
            k = int(r.get("scene")) - 1
            if not 0 <= k < len(items):
                continue
            n = len(items[k][1])
            order = [int(i) - 1 for i in r.get("best", []) if 0 < int(i) <= n]
            order += [i for i in range(n) if i not in order]
            out[k] = (order, bool(r.get("relevant", True)))
    except Exception as e:
        log("[vision-batch] unreadable answer:", str(e)[:80])
    return out


def pick_clips_batch(items, topic, log_prefix="clip"):
    """items: [(scene, need_sec, want)] -> [clips per scene]. Round 4 speed-up:
      1. stock search for all scenes in parallel (cached 7 days)
      2. vision choice in batches of VISION_BATCH scenes (13 scenes -> 4 calls instead of 13)
      3. downloads in parallel (cached; same clip on a retry = no download)
    A failing scene gives [] (motion-graphic background) and never stops the others."""
    from concurrent.futures import ThreadPoolExecutor
    n = len(items)
    land = LANDSCAPE

    def search(i):
        global LANDSCAPE
        LANDSCAPE = land
        try:
            return gather_candidates(items[i][0]["queries"], items[i][1])
        except Exception as e:
            log(f"[{log_prefix}] scene {i + 1} search error:", str(e)[:100])
            return []
    with ThreadPoolExecutor(PREFETCH_THREADS) as ex:
        cands = list(ex.map(search, range(n)))
    # one clip id may be proposed to two scenes: first scene keeps it, the next one drops it
    taken = set()
    for i in range(n):
        cands[i] = [c for c in cands[i] if c["id"] not in taken] or []
        taken |= {c["id"] for c in cands[i][:2]}
    use_vision = bool(KEYS or GROQ_VISION_MODELS) and not (LANDSCAPE and not LONG_VISION)
    choice = {}
    if use_vision:
        todo = [i for i in range(n) if cands[i]]
        for b in range(0, len(todo), VISION_BATCH):
            grp = todo[b:b + VISION_BATCH]
            got = _batch_vision([(items[i][0], cands[i]) for i in grp], topic)
            for k, i in enumerate(grp):
                if k in got:
                    choice[i] = got[k]
                else:                                             # model skipped this scene: single-scene fallback
                    choice[i] = vision_pick(items[i][0]["text"], topic, cands[i])
    for i in range(n):
        choice.setdefault(i, (list(range(len(cands[i]))), True))
    log(f"[{log_prefix}] {n} scenes: {sum(1 for c in cands if c)} with candidates, vision calls ~{-(-sum(1 for c in cands if c) // VISION_BATCH) if use_vision else 0}")

    def fetch(i):
        sc, need, want = items[i]
        order, relevant = choice[i]
        if not cands[i] or not relevant:
            return []
        got = []
        for k in order:
            if len(got) >= want:
                break
            c = cands[i][k]
            try:
                p, info = download_clip(c)
            except Exception as e:
                log("[download]", c["id"], str(e)[:90])
                continue
            with _FLOCK:
                USED.add(c["id"])
            mark_used(c["id"])
            got.append({"path": p, "w": info[0], "h": info[1], "dur": info[2], "id": c["id"]})
            log(f"[{log_prefix}] '{sc['text'][:36]}' -> {c['id']} ({info[0]}x{info[1]}, {info[2]:.1f}s)")
        return got
    with ThreadPoolExecutor(PREFETCH_THREADS) as ex:
        res = list(ex.map(lambda i: _safe_fetch(fetch, i, log_prefix), range(n)))
    prune_footage()
    return res


def _safe_fetch(fn, i, tag):
    try:
        return fn(i)
    except Exception as e:
        log(f"[{tag}] scene {i + 1} error:", str(e)[:100])
        return []


# ================================================================== 5. EDIT ENGINE
_FONT_CACHE = {}


def find_font(heavy=True):
    key = heavy
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    pats = ([str(ASSETS / "font.ttf"), str(ASSETS / "font.otf")] +
            ["/usr/share/fonts/**/Montserrat-ExtraBold.*", "/usr/share/fonts/**/Montserrat-Bold.*",
             "/usr/share/fonts/**/Poppins-ExtraBold.ttf", "/usr/share/fonts/**/Poppins-Bold.ttf",
             "/usr/share/fonts/**/NotoSans-ExtraBold.ttf", "/usr/share/fonts/**/NotoSans-Bold.ttf",
             "/usr/share/fonts/**/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"])
    if not heavy:
        pats = ["/usr/share/fonts/**/Poppins-SemiBold.ttf", "/usr/share/fonts/**/Montserrat-SemiBold.*"] + pats
    for pat in pats:
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            _FONT_CACHE[key] = hits[0]
            return hits[0]
    sys.exit("Font nahi mila. assets/font.ttf mein koi bold font daalo.")


def make_lut(gamma=1.0):
    """Brand colour grade: halka S-curve, shadows mein navy/teal, highlights mein warm-soft, lifted blacks."""
    x = np.linspace(0, 1, 256)
    y = x ** gamma
    y = y + 0.55 * ((y * y * (3 - 2 * y)) - y)             # S-curve (contrast)
    y = 0.018 + y * (1 - 0.018 - 0.01)                       # lift blacks / soft whites
    sh = np.array([-0.020, 0.006, 0.030])                   # shadow tint  (R,G,B)
    hi = np.array([0.018, 0.008, -0.014])                   # highlight tint
    ch = [np.clip(y + sh[c] * (1 - x) ** 2 + hi[c] * x ** 2, 0, 1) for c in range(3)]
    lut = np.stack(ch, 1)                                    # (256,3)
    return (lut * 255 + 0.5).astype(np.uint8).reshape(256, 1, 3)


def saturate(img, s=1.10):
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    g3 = cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)
    return cv2.addWeighted(img, s, g3, 1 - s, 0)


def build_overlay_mask():
    """vignette + neeche/upar dark scrim (caption aur logo ki readability). uint8 HxWx3, multiply."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H * 0.46) / (H * 0.62)) ** 2)
    vig = 1 - 0.34 * np.clip(r, 0, 1.4) ** 2.4
    yn = yy / H
    bot = np.clip((yn - 0.50) / 0.42, 0, 1)
    scr_b = 1 - 0.52 * (bot * bot * (3 - 2 * bot))
    top = np.clip((0.20 - yn) / 0.20, 0, 1)
    scr_t = 1 - 0.30 * (top * top * (3 - 2 * top))
    m = np.clip(vig * scr_b * scr_t, 0, 1)
    return np.repeat((m * 255).astype(np.uint8)[..., None], 3, 2)


class ProcBG:
    """Stock na mile to brand-colour 'aurora' motion graphic (loop-free, hamesha chalta)."""

    def __init__(self, seed):
        r = random.Random(seed)
        pal = [BLUE, GREEN, (118, 84, 224), (40, 172, 204), (70, 130, 240)]
        self.blobs = [(r.choice(pal), r.uniform(0.7, 1.4), r.uniform(0, 6.3), r.uniform(0, 6.3),
                       r.uniform(0.05, 0.13), r.uniform(0.04, 0.10), r.uniform(0.22, 0.38)) for _ in range(5)]
        lw, lh = 108, 192
        self.yy, self.xx = np.mgrid[0:lh, 0:lw].astype(np.float32)
        self.xx /= lw
        self.yy /= lh
        self.base = (np.array(NAVY, np.float32) * (1 - 0.6 * self.yy[..., None]) + 8)
        self.i = 0

    def next(self):
        t = self.i / FPS
        self.i += 1
        img = self.base.copy()
        for col, amp, p1, p2, f1, f2, sig in self.blobs:
            cx = 0.5 + 0.35 * math.sin(2 * math.pi * f1 * t * 3 + p1)
            cy = 0.5 + 0.38 * math.cos(2 * math.pi * f2 * t * 3 + p2)
            d2 = ((self.xx - cx) ** 2 + ((self.yy - cy) * 0.56) ** 2) / (sig * sig)
            img += np.array(col, np.float32) * (0.75 * amp * np.exp(-d2))[..., None]
        img = np.clip(img, 0, 255).astype(np.uint8)
        return cv2.resize(img, (W, H), interpolation=cv2.INTER_CUBIC)

    def close(self):
        pass


class Shot:
    """Ek clip ka tukda: ffmpeg se frames padhta hai, camera move + punch-in lagata hai, grade karta hai."""

    CAMS = ["in", "out", "left", "right", "up"]

    def __init__(self, frames, rng, clip=None, seed=0, punch=True, cam=None):
        self.n, self.i, self.punch = frames, 0, punch
        self.cam = cam or rng.choice(self.CAMS)
        self.proc = None
        self.bg = None
        self.last = None
        self.lut = make_lut(1.0)
        need = frames / FPS + 0.15
        if clip is None:
            self.bg = ProcBG(seed)
            return
        avail = max(0.2, clip["dur"] - 0.2)
        speed, loop = 1.0, False
        if avail < need:
            if avail / need >= 0.7:
                speed = avail / need
            else:
                loop = True
        start = rng.uniform(0.1, max(0.1, clip["dur"] - need * speed - 0.15)) if not loop else 0.0
        vf = (f"setpts=PTS/{speed:.4f},fps={FPS},"
              f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=bicubic,crop={W}:{H}")
        cmd = (["ffmpeg", "-v", "error", "-threads", "2"] + (["-stream_loop", "-1"] if loop else []) +
               ["-ss", f"{start:.3f}", "-i", str(clip["path"]), "-vf", vf, "-frames:v", str(frames + 2),
                "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
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
        if self.i == 0:        # pehle frame ki roshni se gamma (clips ek jaisi dikhein)
            lum = float(cv2.cvtColor(raw, cv2.COLOR_RGB2GRAY).mean()) / 255.0
            g = float(np.clip(math.log(0.46) / math.log(max(lum, 0.06)), 0.80, 1.22))
            self.lut = make_lut(g)
        self.last = raw
        u = self.i / max(1, self.n - 1)
        e = ease_in_out(u)
        s, tx, ty = 1.0, 0.0, 0.0
        if self.cam == "in":
            s = 1.0 + 0.16 * e
        elif self.cam == "out":
            s = 1.16 - 0.16 * e
        elif self.cam == "left":
            s, tx = 1.12, (0.5 - e) * 0.08 * W
        elif self.cam == "right":
            s, tx = 1.12, (e - 0.5) * 0.08 * W
        else:
            s, ty = 1.10, (0.5 - e) * 0.06 * H
        if self.punch:
            s *= 1 + 0.085 * (1 - ease_out(self.i / (0.30 * FPS)))
        M = np.float32([[s, 0, (1 - s) * W / 2 + tx], [0, s, (1 - s) * H / 2 + ty]])
        out = cv2.warpAffine(raw, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        out = cv2.LUT(out, self.lut)
        out = saturate(out, 1.10)
        self.i += 1
        return out

    def close(self):
        if self.proc:
            try:
                self.proc.stdout.close()
                self.proc.kill()
                self.proc.wait(timeout=5)
            except Exception:
                pass


class Ambient:
    """halke floating light particles + film grain + vignette/scrim."""

    def __init__(self, seed=3):
        r = np.random.default_rng(seed)
        self.mask = build_overlay_mask()
        self.grain = r.integers(0, 256, (6, H, W, 3), dtype=np.uint8)
        self.parts = []
        for _ in range(20):
            size = int(r.integers(14, 46))
            yy, xx = np.mgrid[-size:size + 1, -size:size + 1].astype(np.float32)
            spr = np.exp(-(xx * xx + yy * yy) / (2 * (size * 0.45) ** 2))
            col = np.array(r.choice([[255, 255, 255], list(MINT), [170, 205, 255]]), np.float32)
            self.parts.append(dict(x=r.uniform(0, W), y=r.uniform(0, H), v=r.uniform(18, 55),
                                   sw=r.uniform(10, 40), ph=r.uniform(0, 6.3), a=r.uniform(0.10, 0.28),
                                   spr=spr, col=col, size=size))

    def apply(self, img, g):
        t = g / FPS
        img = cv2.multiply(img, self.mask, scale=1 / 255.0)
        for p in self.parts:
            cx = (p["x"] + p["sw"] * math.sin(t * 0.8 + p["ph"])) % W
            cy = (p["y"] - p["v"] * t) % (H + 100) - 50
            s = p["size"]
            x0, y0 = int(cx) - s, int(cy) - s
            xa, ya, xb, yb = max(x0, 0), max(y0, 0), min(x0 + 2 * s + 1, W), min(y0 + 2 * s + 1, H)
            if xb <= xa or yb <= ya:
                continue
            spr = p["spr"][ya - y0:yb - y0, xa - x0:xb - x0, None]
            roi = img[ya:yb, xa:xb].astype(np.float32) + spr * p["a"] * p["col"]
            img[ya:yb, xa:xb] = np.clip(roi, 0, 255).astype(np.uint8)
        return cv2.addWeighted(img, 1.0, self.grain[g % 6], 0.05, -0.05 * 128)


def blit(frame, spr, x, y, alpha=1.0):
    """RGBA uint8 sprite ko (x,y) top-left par blend (clip-safe)."""
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


def text_sprite(text, size, fill, stroke=0, stroke_fill=(10, 16, 30), shadow=True, heavy=True):
    font = ImageFont.truetype(find_font(heavy), size)
    pad = 28
    bb = font.getbbox(text, stroke_width=stroke)
    w, h = bb[2] - bb[0] + 2 * pad, bb[3] - bb[1] + 2 * pad
    lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    if shadow:
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((pad - bb[0], pad - bb[1] + 6), text, font=font, fill=(0, 0, 0, 150),
                                stroke_width=stroke, stroke_fill=(0, 0, 0, 150))
        lay = Image.alpha_composite(lay, sh.filter(ImageFilter.GaussianBlur(9)))
        d = ImageDraw.Draw(lay)
    d.text((pad - bb[0], pad - bb[1]), text, font=font, fill=fill + (255,),
           stroke_width=stroke, stroke_fill=stroke_fill + (255,))
    return np.array(lay)


def rounded_sprite(w, h, c1, c2, radius, alpha=235):
    """left->right gradient wali pill, RGBA uint8."""
    grad = np.zeros((h, w, 4), np.uint8)
    for ch in range(3):
        grad[..., ch] = np.linspace(c1[ch], c2[ch], w)[None, :]
    m = Image.new("L", (w * 3, h * 3), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * 3 - 1, h * 3 - 1], radius * 3, fill=alpha)
    grad[..., 3] = np.array(m.resize((w, h), Image.LANCZOS))
    return grad


class Captions:
    """Word-by-word kinetic captions: 2-3 shabd ke pages, bolte shabd par highlight, pop-in animation."""

    def __init__(self, words):
        # words: [(text, start, end)] global seconds
        self.pages = caption_styles.paginate(words, 4, 26, True)
        self.starts = [p[0][1] for p in self.pages]
        self.ends = []
        for i, p in enumerate(self.pages):
            nxt = self.starts[i + 1] if i + 1 < len(self.pages) else 1e9
            self.ends.append(min(nxt, p[-1][2] + 0.22) if nxt - p[-1][2] > 0.35 else nxt)
        self.cache_key, self.cache = None, {}

    def _page_sprite(self, pi, k):
        key = (pi, k)
        if self.cache_key != pi:
            self.cache, self.cache_key = {}, pi
        if key in self.cache:
            return self.cache[key]
        words = [w[0] for w in self.pages[pi]]
        size = 92
        maxw = 860
        while True:
            font = ImageFont.truetype(find_font(True), size)
            space = font.getlength(" ") * 1.0
            widths = [font.getlength(w) for w in words]
            total = sum(widths) + space * (len(words) - 1)
            if total <= maxw or len(words) == 1:
                lines = [list(range(len(words)))]
                break
            # 2 lines: sabse balanced split
            best = None
            for cut in range(1, len(words)):
                a = sum(widths[:cut]) + space * (cut - 1)
                b = sum(widths[cut:]) + space * (len(words) - cut - 1)
                m = max(a, b)
                if best is None or m < best[0]:
                    best = (m, cut)
            if best[0] <= maxw:
                lines = [list(range(best[1])), list(range(best[1], len(words)))]
                break
            size -= 6
            if size < 56:
                lines = [list(range(best[1])), list(range(best[1], len(words)))]
                break
        lh = int(size * 1.22)
        pad = 34
        img = Image.new("RGBA", (W, lh * len(lines) + 2 * pad), (0, 0, 0, 0))
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d, ds = ImageDraw.Draw(img), ImageDraw.Draw(shadow)
        for li, idxs in enumerate(lines):
            lw = sum(widths[i] for i in idxs) + space * (len(idxs) - 1)
            x = (W - lw) / 2
            y = pad + li * lh
            for i in idxs:
                col = MINT if i == k else (255, 255, 255)
                ds.text((x, y + 7), words[i], font=font, fill=(0, 0, 0, 170), stroke_width=9, stroke_fill=(0, 0, 0, 170))
                d.text((x, y), words[i], font=font, fill=col + (255,), stroke_width=9, stroke_fill=(9, 14, 28, 255))
                x += widths[i] + space
        shadow = shadow.filter(ImageFilter.GaussianBlur(10))
        out = np.array(Image.alpha_composite(shadow, img))
        self.cache[key] = out
        return out

    def draw(self, frame, t, alpha=1.0, cy=1215):
        if not self.pages or alpha <= 0:
            return
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
        spr = self._page_sprite(pi, k)
        u = (t - self.starts[pi]) * FPS
        sc = 0.84 + 0.16 * ease_out_back(u / 7.0)
        a = clamp01(u / 3.0) * alpha
        spr = scaled(spr, sc)
        blit(frame, spr, (W - spr.shape[1]) / 2, cy - spr.shape[0] / 2, a)


CAPTION_USED = ["pop"]


def make_captions(words):
    st = caption_styles.pick_style(CAPTION_STYLE, scheduler.now_ist().date())
    CAPTION_USED[0] = st
    log("   caption style:", st)
    if st == "pop":
        return Captions(words)                       # v7 look
    return caption_styles.StyledCaptions(words, st, W, H)


def pill(text, size, c1, c2, padx=34, pady=18, alpha=240, tc=(255, 255, 255)):
    font = ImageFont.truetype(find_font(True), size)
    bb = font.getbbox(text)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    w, h = tw + 2 * padx, th + 2 * pady
    base = Image.fromarray(rounded_sprite(w, h, c1, c2, h // 2, alpha), "RGBA")
    ImageDraw.Draw(base).text((padx - bb[0], pady - bb[1]), text, font=font, fill=tuple(tc) + (255,))
    # halki shadow
    pad = 22
    out = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    sh.paste((0, 0, 0, 110), (pad, pad + 6, pad + w, pad + h + 6), base.split()[3])
    out = Image.alpha_composite(out, sh.filter(ImageFilter.GaussianBlur(9)))
    out.alpha_composite(base, (pad, pad))
    return np.array(out)


class HUD:
    """Circle logo, kicker chip, key-term sticker - sab motion ke saath (top loading bar hata diya)."""

    def __init__(self, kicker, emph_events, voice_end):
        self.voice_end = voice_end
        self.logo_size = 76                                   # ~7% of the 1080 px width: small, tasteful
        self.logo = brand_logo.load(self.logo_size, ASSETS)    # circle + ring + shadow; None if asset gate fails
        self.kicker = pill(f"{BRAND_NAME.upper()}  \u2022  {kicker}", 40, (255, 196, 0), (255, 82, 82), 38, 20, 250, tc=(20, 12, 40))   # v16: warm gold->coral, dark text = stands out from the blue/green UI
        self.kicker_glow = pill(f"{BRAND_NAME.upper()}  \u2022  {kicker}", 40, (255, 230, 120), (255, 120, 120), 38, 20, 120, tc=(255, 255, 255))
        self.emph = []
        for s, e, txt in emph_events:
            size = 78
            while ImageFont.truetype(find_font(True), size).getlength(txt) > 840 and size > 44:
                size -= 4
            self.emph.append((s, e, pill(txt, size, BLUE, GREEN, 46, 26, 238)))

    def draw(self, frame, t, alpha=1.0):
        if alpha <= 0:
            return
        # v16: thin progress bar at the top is back (like the old videos)
        if self.voice_end > 0:
            pr = clamp01(t / self.voice_end)
            x0, x1, yb, hb = 40, W - 40, 62, 8
            frame[yb:yb + hb, x0:x1] = (frame[yb:yb + hb, x0:x1].astype(np.float32) * (1 - 0.35 * alpha) + 255 * 0.35 * alpha * 0.4).astype(np.uint8)
            xe = x0 + int((x1 - x0) * pr)
            if xe > x0:
                seg = np.linspace(BLUE, GREEN, xe - x0)[None].astype(np.float32)
                frame[yb:yb + hb, x0:xe] = (frame[yb:yb + hb, x0:xe] * (1 - alpha) + seg * alpha).astype(np.uint8)
        # logo: invisible during the hook, fades in to 82%, top-right (clear of platform buttons), circle with ring
        if self.logo is not None:
            a = brand_logo.fade(t) * alpha
            if a > 0:
                pad = brand_logo.pad_of(self.logo_size)
                blit(frame, self.logo, W - 44 - self.logo_size - pad, 128 - pad, a)
        # kicker chip: slide-in, hold, slide-out
        tin, tout = 0.20, 5.2
        if t < tout + 0.6:
            u = ease_out((t - tin) / 0.55)
            v = ease_in_out((t - tout) / 0.5)
            x = -self.kicker.shape[1] + (self.kicker.shape[1] + 40) * u - v * (self.kicker.shape[1] + 80)
            pulse = 0.5 + 0.5 * math.sin(t * 6.0)
            blit(frame, self.kicker_glow, x, 126, alpha * (0.25 + 0.35 * pulse) * u)       # pulsing glow behind
            blit(frame, self.kicker, x, 126, alpha)
        # key-term sticker
        for s, e, spr in self.emph:
            if s <= t < e:
                u = (t - s) * FPS
                k = 0.7 + 0.3 * ease_out_back(u / 9.0)
                a = clamp01(u / 3.0) * (1 - clamp01((t - (e - 0.25)) / 0.25)) * alpha
                sp = scaled(spr, k)
                blit(frame, sp, (W - sp.shape[1]) / 2, 940 - sp.shape[0] / 2, a)


def _dir_blur(img, L, horizontal):
    L = int(L) | 1
    if L < 3:
        return img
    return cv2.blur(img, (L, 1) if horizontal else (1, L), borderType=cv2.BORDER_REPLICATE)


def _zoom(img, s):
    M = np.float32([[s, 0, (1 - s) * W / 2], [0, s, (1 - s) * H / 2]])
    return cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def transition(kind, A, B, p):
    """A -> B, p in (0,1]. Push/zoom mein asli directional motion-blur."""
    e = ease_in_out(p)
    if kind == "dissolve":
        out = cv2.addWeighted(A, 1 - e, B, e, 0)
        sg = 4.5 * math.sin(math.pi * p)
        return cv2.GaussianBlur(out, (0, 0), sg) if sg > 0.8 else out
    if kind in ("push_left", "push_up"):
        hor = kind == "push_left"
        dim = W if hor else H
        off = int(round(e * dim))
        v = (ease_in_out(min(1, p + 0.05)) - ease_in_out(max(0, p - 0.05))) / 0.10 / XFADE * dim
        L = min(110, v * 0.6)
        A2, B2 = _dir_blur(A, L, hor), _dir_blur(B, L, hor)
        out = np.empty_like(A)
        if hor:
            out[:, :W - off], out[:, W - off:] = A2[:, off:], B2[:, :off]
        else:
            out[:H - off], out[H - off:] = A2[off:], B2[:off]
        return out
    if kind in ("push_right", "push_down"):                   # v17: same slide, other directions
        hor = kind == "push_right"
        dim = W if hor else H
        off = int(round(e * dim))
        L = min(110, math.sin(math.pi * p) * 90)
        A2, B2 = _dir_blur(A, L, hor), _dir_blur(B, L, hor)
        out = np.empty_like(A)
        if hor:
            out[:, off:], out[:, :off] = A2[:, :W - off], B2[:, W - off:]
        else:
            out[off:], out[:off] = A2[:H - off], B2[H - off:]
        return out
    if kind == "flash":                                       # v17: quick white flash cut
        k = math.sin(math.pi * clamp01(p))
        base = A if p < 0.5 else B
        return np.clip(base.astype(np.float32) * (1 - 0.85 * k) + 255 * 0.85 * k, 0, 255).astype(np.uint8)
    if kind == "glitch":                                      # v17: RGB split + sliced shift
        base = (A if p < 0.5 else B).copy()
        k = math.sin(math.pi * clamp01(p))
        sh = int(48 * k)
        out = base.copy()
        out[..., 0] = np.roll(base[..., 0], sh, axis=1)
        out[..., 2] = np.roll(base[..., 2], -sh, axis=1)
        gr = np.random.default_rng(int(p * 1000))
        for _ in range(7):
            y0 = int(gr.integers(0, H - 80)); hh = int(gr.integers(20, 80)); dx = int(gr.integers(-90, 90) * k)
            out[y0:y0 + hh] = np.roll(out[y0:y0 + hh], dx, axis=1)
        return out
    if kind == "whip":                                        # v17: fast diagonal whip pan
        off = int(round(e * W))
        L = min(130, math.sin(math.pi * p) * 130 + 6)
        A2, B2 = _dir_blur(A, L, True), _dir_blur(B, L, True)
        out = np.empty_like(A)
        out[:, :W - off], out[:, W - off:] = A2[:, off:], B2[:, :off]
        M = np.float32([[1, 0, 0], [math.sin(math.pi * p) * 0.05, 1, 0]])
        return cv2.warpAffine(out, M, (W, H), borderMode=cv2.BORDER_REPLICATE)
    if kind == "spin_zoom":                                   # v17: punch-in with a small rotation
        ang = 6 * math.sin(math.pi * p) * (1 if p < 0.5 else -1)
        sc = (1 + 0.5 * p) if p < 0.5 else (1.5 - 0.5 * ease_out((p - 0.5) * 2 + 0.0))
        M = cv2.getRotationMatrix2D((W / 2, H / 2), ang, max(1.0, sc))
        src = A if p < 0.5 else B
        out = cv2.warpAffine(src, M, (W, H), borderMode=cv2.BORDER_REPLICATE)
        return cv2.GaussianBlur(out, (0, 0), 2.5 * math.sin(math.pi * p) + 0.1)
    # zoom_blur: A andar ghusta hai, B bahar se settle hota hai; 5-sample radial-ish blur
    K = 5
    sa, sb = 1 + 0.6 * p * p, 1.5 - 0.5 * ease_out(p)
    spread = 0.10 * math.sin(math.pi * clamp01(p)) + 0.01
    wb = ease_in_out(clamp01((p - 0.2) / 0.6))
    accA = np.zeros(A.shape, np.float32)
    accB = np.zeros(A.shape, np.float32)
    for j in range(K):
        f = 1 + spread * (j / (K - 1) - 0.5)
        accA += _zoom(A, sa * f)
        accB += _zoom(B, sb * f)
    out = (accA * (1 - wb) + accB * wb) / K
    return np.clip(out, 0, 255).astype(np.uint8)


class SceneRenderer:
    def __init__(self, a, b, clips, seed):
        self.a, self.b, self.n = a, b, b - a
        self.rng = random.Random(seed)
        self.seed = seed
        self.clips = clips
        self.shots = []
        if len(clips) >= 2 and self.n >= int(2.4 * FPS):          # v17: more cuts (was 3.3 s)
            n1 = int(self.n * self.rng.uniform(0.45, 0.58))
            self.plan = [(n1, clips[0]), (self.n - n1, clips[1])]
        else:
            self.plan = [(self.n, clips[0] if clips else None)]
        self.cur = 0
        self.shot = None
        self.shot_left = 0
        prev = None
        self.cams = []
        for _ in self.plan:                # alag camera move, ek ke baad ek alag
            c = self.rng.choice([x for x in Shot.CAMS if x != prev])
            self.cams.append(c)
            prev = c

    def _open_next(self):
        if self.shot:
            self.shot.close()
        n, clip = self.plan[self.cur]
        self.shot = Shot(n + 2, self.rng, clip, seed=self.seed + self.cur, punch=True, cam=self.cams[self.cur])
        self.shot_left = n
        self.cur += 1

    def frame(self, g):
        if self.shot is None or (self.shot_left <= 0 and self.cur < len(self.plan)):
            self._open_next()
        self.shot_left -= 1
        return self.shot.next()

    def close(self):
        if self.shot:
            self.shot.close()
            self.shot = None


def plan_transitions(n, rng):
    pool = ["zoom_blur", "push_left", "push_right", "push_up", "push_down", "flash", "glitch", "spin_zoom", "whip", "dissolve"]   # v17: many more
    seq, prev = [], None
    for _ in range(n):
        k = rng.choice([x for x in pool if x != prev])
        seq.append(k)
        prev = k
    return seq


def build_timeline(res):
    """per-scene voice durations -> scene start times (sec)."""
    starts, cur = [], 0.12
    for i, (_, dur, _) in enumerate(res):
        starts.append(cur)
        gap = 0.30 if i == 0 else 0.10 if i == len(res) - 1 else 0.17
        cur += dur + gap
    return starts, cur        # cur = splash start


def render_video(scenes, res, starts, splash_start, clips_per_scene, kicker, splash, out_video, rng, hook_text=""):
    total_t = splash_start + SPLASH_SECONDS + 0.4
    n_total = int(round(total_t * FPS))
    fb = [int(round(s * FPS)) for s in starts] + [int(round(splash_start * FPS))]
    half = XFADE // 2
    SPL_PRE = 9
    clips_per_scene = list(clips_per_scene)                    # v17: no more empty gradient scenes -> borrow the nearest scene's clips
    for i in range(len(clips_per_scene)):
        if not clips_per_scene[i]:
            for d in range(1, len(clips_per_scene)):
                alt = [j for j in (i - d, i + d) if 0 <= j < len(clips_per_scene) and clips_per_scene[j]]
                if alt:
                    clips_per_scene[i] = list(reversed(clips_per_scene[alt[0]]))
                    break
    renderers = []
    for i in range(len(scenes)):
        a = fb[i] - (half if i > 0 else 0)
        b = fb[i + 1] + (half if i < len(scenes) - 1 else SPL_PRE)
        renderers.append(SceneRenderer(max(0, a), b, clips_per_scene[i], seed=1000 + i * 7))
    kinds = plan_transitions(len(scenes) - 1, rng)
    # captions / emphasis (global time)
    words = []
    for i, (_, _, ws) in enumerate(res):
        words += [(w, starts[i] + s, starts[i] + e) for (w, s, e) in ws]
    caps = make_captions(words)
    emph = []
    for i, sc in enumerate(scenes):
        if sc.get("emphasis"):
            emph.append((starts[i] + 0.2, starts[i] + res[i][1] + 0.1, sc["emphasis"]))
    hud = HUD(kicker, emph, splash_start)
    hook = hook_intro.HookText(hook_text if HOOK_INTRO else "", W)
    ecard = endcard.EndCard(W, SITE_WWW, BRAND_NAME)
    ec_t0 = splash_start + 1.7        # v16: logo + neurotriage.in alone first, then buttons, then www
    first0, loop_n = None, (int(LOOP_SEC * FPS) if LOOP_JOIN else 0)
    amb = Ambient()
    cap_g = np.zeros((H, 1, 1), np.float32)                    # v17: smooth (no hard edge) dark gradient behind captions
    yy = np.arange(1000, 1520)
    cap_g[1000:1520, 0, 0] = 0.34 * np.sin(np.pi * (yy - 1000) / 520.0) ** 1.5
    spl_fb = int(round(splash_start * FPS))
    disc = text_sprite("Educational content \u2022 not medical advice", 30, (150, 160, 178), 0, shadow=False, heavy=False)

    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-c:v", "libx264", "-preset", RENDER_PRESET, "-crf", "18", "-pix_fmt", "yuv420p",
         "-profile:v", "high", "-movflags", "+faststart", str(out_video)],
        stdin=subprocess.PIPE)
    t0 = time.time()
    try:
        for g in range(n_total):
            t = g / FPS
            active = [i for i, r in enumerate(renderers) if r.a <= g < r.b]
            if len(active) == 0:
                frame = None
            else:
                fr = {i: renderers[i].frame(g) for i in active}
                if len(active) == 1:
                    comp = fr[active[0]]
                else:
                    i, j = active[0], active[1]
                    p = (g - renderers[j].a + 1) / float(XFADE)
                    comp = transition(kinds[i], fr[i], fr[j], clamp01(p))
                comp = amb.apply(comp, g)
                comp = (comp.astype(np.float32) * (1 - cap_g)).astype(np.uint8)
                frame = comp
            # splash
            w_spl = 0.0
            if g >= spl_fb - SPL_PRE:
                w_spl = clamp01((g - (spl_fb - SPL_PRE) + 1) / (SPL_PRE + 4))
                w_spl = ease_in_out(w_spl)
                sf = splash.frame(max(0.0, (g - spl_fb) / FPS)) if g >= spl_fb else splash.frame(0.0)
                a_d = clamp01((t - splash_start - 3.0) / 0.5) * 0.9
                if a_d > 0:
                    blit(sf, disc, (W - disc.shape[1]) / 2, 1480, a_d)
                if frame is None:
                    frame = sf
                else:
                    frame = cv2.addWeighted(frame, 1 - w_spl, sf, w_spl, 0)
            if frame is None:
                frame = np.full((H, W, 3), NAVY, np.uint8)
            frame = np.ascontiguousarray(frame)
            if t < splash_start + 0.2:
                hud_a = 1 - w_spl
                caps.draw(frame, t, hud_a)
                hud.draw(frame, t, hud_a)
            if t < splash_start:                         # v17: expanding mint ring at every scene start = motion accent
                for st in starts:
                    dt = t - st
                    if 0 <= dt < 0.45:
                        u = dt / 0.45
                        ov = frame.copy()
                        cv2.circle(ov, (W // 2, 960), int(120 + 700 * ease_out(u)), (126, 240, 196), 10, cv2.LINE_AA)
                        cv2.addWeighted(ov, 0.5 * (1 - u), frame, 1 - 0.5 * (1 - u), 0, frame)
            hook.draw(frame, t)                          # round 5a: hook text from frame 0 (no white flash)
            if t >= ec_t0:                               # round 5b: Like / Share / Follow + Try NeuroTriage
                ecard.draw(frame, t - ec_t0)
            if loop_n:                                   # round 5b: loop-join = last 0.5 s dissolves into frame 0 (cheap, ~0 s)
                if g == 0:
                    first0 = frame.copy()
                elif first0 is not None and g >= n_total - loop_n:
                    wl = (g - (n_total - loop_n) + 1) / float(loop_n)
                    frame = cv2.addWeighted(frame, 1 - wl, first0, wl, 0)
            enc.stdin.write(frame.tobytes())
            for i, r in enumerate(renderers):
   
