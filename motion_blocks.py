"""Round 12 - HyperFrames-style motion blocks, native Python (no Node/Chrome). Portrait/9:16.
Blocks: stat_counter, bar_chart. Data must be GROUNDED in the transcript (numbers are never invented).
Placement avoids face, caption zone and insert-card windows; if no safe spot -> block skipped."""
import json, re, subprocess
from pathlib import Path
import cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont

FD = Path(__file__).parent / "vendor" / "claude_fx" / "fonts"
YUNET = Path(__file__).parent / "vendor" / "claude_fx" / "models" / "yunet.onnx"
ACCENT = (255, 72, 72)
CFG = {"max_blocks": 2, "min_gap": 6.0, "head": 1.5, "tail": 3.2, "len": (2.4, 4.5)}
NUM = re.compile(r"^\(?(\d[\d,]*(?:\.\d+)?)(%?)\)?[.,!?]*$")
UNITS = {"percent": "%", "%": "%", "lakh": " Lakh", "crore": " Cr", "million": "M", "billion": "B", "times": "x", "x": "x", "saal": " yrs", "years": " yrs"}


def F(name, px): return ImageFont.truetype(str(FD / name), max(8, int(px)))
def ease(x): x = min(1, max(0, x)); return 1 - (1 - x) ** 3


def grounded(value, transcript):
    d = re.sub(r"[^\d.]", "", str(value)).strip(".")
    return bool(d) and re.search(r"(?<![\d.])" + re.escape(d.replace(",", "")) + r"(?![\d])", transcript.replace(",", "")) is not None


def plan_from_words(words, dur):
    """Rules: a number (+ optional unit word) in speech -> stat_counter, label = the next few spoken words. No invented data."""
    out, last = [], -99
    for i, w in enumerate(words):
        m = NUM.match(w[0].strip())
        if not m: continue
        val = m.group(1); unit = m.group(2)
        nxt = [re.sub(r"\W", "", x[0]) for x in words[i + 1:i + 5]]
        if not unit and nxt and nxt[0].lower() in UNITS: unit = UNITS[nxt[0].lower()]; nxt = nxt[1:]
        if float(val.replace(",", "")) < 2 and not unit: continue                 # "1 thing" is not a stat
        if w[1] < last + CFG["min_gap"]: continue
        label = " ".join(x for x in nxt if x)[:28].upper() or "KEY NUMBER"
        out.append({"block": "stat_counter", "start": w[1] - 0.2, "end": w[1] + 3.2, "value": val + unit, "label": label}); last = w[1] + 3.2
    return out


def validate(blocks, dur, transcript, busy=()):
    ok, last = [], -99
    for b in sorted((x for x in (blocks or []) if isinstance(x, dict)), key=lambda x: float(x.get("start", 0) or 0)):
        try:
            kind = b["block"]
            if kind not in ("stat_counter", "bar_chart"): continue
            s = max(float(b["start"]), CFG["head"]); e = min(float(b["end"]), dur - CFG["tail"], s + CFG["len"][1])
            if e - s < CFG["len"][0] or s < last + CFG["min_gap"]: continue
            if any(s < be and e > bs for bs, be in busy): continue
            c = {"block": kind, "start": round(s, 2), "end": round(e, 2)}
            if kind == "stat_counter":
                if not grounded(b["value"], transcript): continue
                c.update(value=str(b["value"])[:10], label=re.sub(r"[^\w %&\-]", "", str(b.get("label", ""))).upper()[:28])
            else:
                items = [(re.sub(r"[^\w %&\-]", "", str(k))[:14].upper(), float(str(v).replace(",", "").rstrip("%"))) for k, v in b["items"]][:5]
                if len(items) < 2 or not all(grounded(v if v % 1 else int(v), transcript) for _, v in items): continue
                c.update(title=re.sub(r"[^\w %&\-]", "", str(b.get("title", "")))[:30].upper(), items=items)
            ok.append(c); last = e
        except Exception:
            continue
        if len(ok) >= CFG["max_blocks"]: break
    return ok


# ---------- drawing ----------
def card_base(w, h, t, dur):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], int(w * 0.045), fill=(12, 14, 22, 218), outline=(255, 255, 255, 70), width=max(2, w // 300))
    d.rounded_rectangle([int(w * .05), int(h * .09), int(w * .05) + max(6, w // 90), int(h * .91)], 4, fill=ACCENT + (255,))
    return im, d


def draw_stat(b, t, dur, W):
    w, h = int(W * .84), int(W * .30); im, d = card_base(w, h, t, dur); x0 = int(w * .11)
    d.text((x0, h * .14), b["label"], font=F("ArchivoBlack-Regular.ttf", w * .040), fill=(210, 214, 225, 255))
    m = re.match(r"([\d,]*\.?\d+)(.*)", b["value"]); num = float(m.group(1).replace(",", "")); suf = m.group(2)
    dec = len(m.group(1).split(".")[1]) if "." in m.group(1) else 0; cur = num * ease(t / 1.1)
    txt = (f"{cur:,.{dec}f}" if "," in m.group(1) else f"{cur:.{dec}f}") + suf
    f = F("Anton-Regular.ttf", h * .50)
    while (d.textlength(txt, font=f) > w * .82 or d.textbbox((0, 0), txt, font=f)[3] > h * .70) and f.size > 20: f = F("Anton-Regular.ttf", f.size - 4)
    bb = d.textbbox((0, 0), txt, font=f); d.text((x0, h * .30 - bb[1]), txt, font=f, fill=(255, 255, 255, 255)); return im


def draw_bars(b, t, dur, W):
    n = len(b["items"]); w, h = int(W * .86), int(W * (.17 + .105 * n)); im, d = card_base(w, h, t, dur); x0 = int(w * .11)
    d.text((x0, h * .06), b["title"] or "COMPARISON", font=F("ArchivoBlack-Regular.ttf", w * .038), fill=(210, 214, 225, 255))
    mx = max(v for _, v in b["items"]) or 1; row = (h * .80) / n; tr = w * .50
    for i, (k, v) in enumerate(b["items"]):
        y = h * .17 + i * row; p = ease((t - 0.25 - i * 0.15) / 0.8)
        d.text((x0, y + row * .08), k, font=F("ArchivoBlack-Regular.ttf", w * .033), fill=(255, 255, 255, 255))
        bx = x0 + w * .27; d.rounded_rectangle([bx, y + row * .12, bx + tr, y + row * .62], 8, fill=(255, 255, 255, 28))
        if p > 0: d.rounded_rectangle([bx, y + row * .12, bx + max(10, tr * v / mx * p), y + row * .62], 8, fill=ACCENT + (255,))
        d.text((bx + tr + 14, y + row * .08), f"{v * p:g}"[:6], font=F("Anton-Regular.ttf", w * .05), fill=(255, 255, 255, 255))
    return im


def layer(b, t, dur, W):
    im = (draw_stat if b["block"] == "stat_counter" else draw_bars)(b, t, dur, W)
    a = min(ease(t / 0.3), ease((dur - t) / 0.3)); arr = np.asarray(im, np.float32).copy(); arr[..., 3] *= a
    return arr, int((1 - ease(t / 0.3)) * 24)


# ---------- placement ----------
def faces_at(path, t, w, h):
    try:
        cap = cv2.VideoCapture(str(path)); cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000); ok, fr = cap.read(); cap.release()
        fd = cv2.FaceDetectorYN.create(str(YUNET), "", (fr.shape[1], fr.shape[0]), 0.6, 0.3, 5); _, f = fd.detect(fr)
        return [(r[0], r[1], r[0] + r[2], r[1] + r[3]) for r in (f if f is not None else [])]
    except Exception:
        return None


def place(path, b, W, H, cap_zone):
    """-> (x, y) or None. Tries top / middle / bottom slots; rejects overlap with face(s) or caption zone."""
    ch = int(W * .30) if b["block"] == "stat_counter" else int(W * (.17 + .105 * len(b.get("items", [])))); cw = int(W * (.84 if b["block"] == "stat_counter" else .86))
    x = (W - cw) // 2
    fs = faces_at(path, (b["start"] + b["end"]) / 2, W, H)
    if fs is None or not fs: fs = [(W * .25, H * .12, W * .75, H * .42)]               # unknown -> assume face in upper-middle
    for ty in (.05, .46, .84):
        y = int(H * ty)
        if y + ch > H * .97 or (y < cap_zone[1] and y + ch > cap_zone[0]): continue
        if any(x < fx1 + 20 and x + cw > fx0 - 20 and y < fy1 + 40 and y + ch > fy0 - 40 for fx0, fy0, fx1, fy1 in fs): continue
        return x, y, ch
    return None


def composite(src, dst, blocks, cap_zone_frac=(.64, .84)):
    """Stream frames, blend blocks, keep audio untouched. Raises on failure (caller falls back)."""
    j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
                                   "-of", "json", str(src)], capture_output=True, text=True, check=True).stdout)["streams"][0]
    W, H = j["width"], j["height"]; n_, d_ = j["r_frame_rate"].split("/"); fps = min(30.0, float(n_) / float(d_ or 1)); fr_arg = str(round(fps, 3))
    cz = (H * cap_zone_frac[0], H * cap_zone_frac[1]); act = []
    for b in blocks:
        p = place(src, b, W, H, cz)
        if p: act.append(dict(b, x=p[0], y=p[1]))
    if not act: raise RuntimeError("no-safe-placement")
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(src), "-vf", f"fps={fr_arg},format=rgb24", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", fr_arg, "-i", "-", "-i", str(src),
                            "-map", "0:v", "-map", "1:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                            "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(dst)], stdin=subprocess.PIPE)
    fsz, i = W * H * 3, 0
    try:
        while True:
            buf = dec.stdout.read(fsz)
            if len(buf) < fsz: break
            t = i / fps; i += 1
            for b in act:
                if b["start"] <= t < b["end"]:
                    arr, dy = layer(b, t - b["start"], b["end"] - b["start"], W); h_, w_ = arr.shape[:2]; y = b["y"] + dy
                    if y < 0 or y + h_ > H: continue
                    fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy(); a = arr[..., 3:4] / 255.0
                    reg = fr[y:y + h_, b["x"]:b["x"] + w_].astype(np.float32); fr[y:y + h_, b["x"]:b["x"] + w_] = (reg * (1 - a) + arr[..., :3] * a).astype(np.uint8)
                    buf = fr.tobytes()
            enc.stdin.write(buf)
        enc.stdin.close()
    finally:
        if dec.poll() is None: dec.kill()
    if enc.wait() != 0: raise RuntimeError("encode-failed")
    return act
