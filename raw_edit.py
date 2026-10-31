"""Round 5c: RAW VIDEO EDITOR. Takes a raw clip (e.g. an AI video with a platform watermark) and turns it into a branded Short.

  1. finds a STATIC watermark by itself (edges that stay in the same place in >=90% of 12 sampled frames, in a corner or
     top/bottom strip, much denser than in the rest of the picture). Moving watermarks and static scenes are NOT flagged.
  2. removes it: zoom-crop (only if the zoom stays <= 1.28x) or, otherwise, blur the box + our circle logo on top.
  3. fits 1080x1920 (landscape/square -> blurred fill + fitted video), adds hook text from frame 0, brand logo,
     end card (Like/Share/Follow + Try NeuroTriage), loop-join dissolve.
  4. audio: your own file (looped/trimmed, faded) or the clip's own sound; loudness -14 LUFS.
  5. writes final_raw.mp4 + _4k + _ig files and raw_report.json.
Usage: python raw_edit.py --video raw/in.mp4 [--audio my.mp3] [--hook "TEXT"] [--method auto|crop|blur|none] [--box x,y,w,h]
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import brand_logo
import endcard
import hook_intro
import variants
from gfx import blit

ROOT = Path(__file__).parent
W, H, FPS = 1080, 1920, 30
MAX_ZOOM = 1.28
END_SEC, LOOP_N = 2.8, 15
N_SAMPLES, SAMPLE_W = 12, 480
PERSIST = 0.9          # share of sampled frames in which an edge must be present at the same pixel
REG = {"top_left": (0, 0, .36, .16), "top_right": (.64, 0, .36, .16), "bottom_left": (0, .84, .36, .16),
       "bottom_right": (.64, .84, .36, .16), "bottom_center": (.25, .86, .5, .14), "top_center": (.25, 0, .5, .12)}


def sh(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def probe(path):
    j = json.loads(sh(["ffprobe", "-v", "error", "-show_entries",
                       "stream=codec_type,width,height,duration:stream_tags=rotate:stream_side_data=rotation:format=duration",
                       "-of", "json", str(path)]).stdout)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    dur = float(v.get("duration") or j["format"].get("duration") or 0)
    w, h = int(v["width"]), int(v["height"])
    rot = v.get("tags", {}).get("rotate")                      # phone videos: stored landscape + rotation flag (ffmpeg auto-rotates)
    for sd in v.get("side_data_list", []):
        if "rotation" in sd:
            rot = sd["rotation"]
    if rot is not None and int(float(rot)) % 180 == 90:
        w, h = h, w
    return {"w": w, "h": h, "dur": dur, "audio": any(s["codec_type"] == "audio" for s in j["streams"])}


# ---------------------------------------------------------------- 1. detect
def sample_frames(path, info, n=N_SAMPLES):
    sw = SAMPLE_W
    shh = max(2, int(round(info["h"] * sw / info["w"] / 2)) * 2)
    r = sh(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={n / max(info['dur'], 0.5):.4f},scale={sw}:{shh}",
            "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "gray", "-"])
    a = np.frombuffer(r.stdout, np.uint8)
    k = len(a) // (sw * shh)
    return [a[i * sw * shh:(i + 1) * sw * shh].reshape(shh, sw) for i in range(k)]


def detect_watermark(frames):
    """frames: list of gray arrays. -> list of boxes (x, y, w, h) in frame coordinates (<=2), best first. [] = none."""
    if len(frames) < 6:
        return []
    h, w = frames[0].shape
    k3 = np.ones((3, 3), np.uint8)
    E = np.stack([cv2.dilate(cv2.Canny(cv2.GaussianBlur(f, (3, 3), 0), 50, 140), k3) > 0 for f in frames])
    P = E.mean(0) >= PERSIST
    cy0, cy1, cx0, cx1 = int(h * .2), int(h * .8), int(w * .2), int(w * .8)
    rest = max(float(P[cy0:cy1, cx0:cx1].mean()), 0.002)
    found = []
    for name, (fx, fy, fw, fh) in REG.items():
        x0, y0, x1, y1 = int(fx * w), int(fy * h), int((fx + fw) * w), int((fy + fh) * h)
        m = P[y0:y1, x0:x1]
        closed = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 15), np.uint8))
        n, _, stats, _ = cv2.connectedComponentsWithStats(closed)
        comps, need = [], max(.12, 4 * rest)          # a real mark is a COMPACT dense blob; chance speckle is ~1% dense
        for s_ in stats[1:]:
            sub = m[s_[1]:s_[1] + s_[3], s_[0]:s_[0] + s_[2]]
            cnt, fill = int(sub.sum()), float(sub.mean())
            if cnt >= max(40, 0.00025 * w * h) and fill >= need:
                comps.append((cnt, fill, s_))
        if not comps:
            continue
        big = max(c[0] for c in comps)
        comps = [c for c in comps if c[0] >= .25 * big]
        cnt, dens = sum(c[0] for c in comps), max(c[1] for c in comps)
        comps = [c[2] for c in comps]
        bx0, by0 = min(s[0] for s in comps), min(s[1] for s in comps)
        bx1, by1 = max(s[0] + s[2] for s in comps), max(s[1] + s[3] for s in comps)
        pw, ph = max(4, int((bx1 - bx0) * .15)), max(4, int((by1 - by0) * .15))
        bx0, by0, bx1, by1 = max(0, bx0 - pw + x0), max(0, by0 - ph + y0), min(w, bx1 + pw + x0), min(h, by1 + ph + y0)
        found.append((cnt * dens, (bx0, by0, bx1 - bx0, by1 - by0), name))
    found.sort(key=lambda t: -t[0])
    out = []
    for _, b, name in found:
        if all(b[0] >= o[0] + o[2] or o[0] >= b[0] + b[2] or b[1] >= o[1] + o[3] or o[1] >= b[1] + b[3] for o, _n in out):
            out.append((b, name))
        if len(out) == 2:
            break
    return [b for b, _ in out]


def scale_boxes(boxes, src_w, src_h, W0, H0):
    sx, sy = W0 / src_w, H0 / src_h
    return [(int(b[0] * sx), int(b[1] * sy), int(np.ceil(b[2] * sx)), int(np.ceil(b[3] * sy))) for b in boxes]


# ---------------------------------------------------------------- 2. remove
def plan_crop(W0, H0, boxes, max_zoom=MAX_ZOOM):
    """zoom-crop that keeps the aspect ratio and excludes every box. -> (x, y, w, h, zoom) or None."""
    ux0, uy0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    ux1, uy1 = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
    opts = []
    for f, side in ((uy0 / H0, "bottom"), ((H0 - uy1) / H0, "top"), (ux0 / W0, "right"), ((W0 - ux1) / W0, "left")):
        if f <= 0 or 1 / f > max_zoom * 1.0001:
            continue
        ww, hh = int(W0 * f) // 2 * 2, int(H0 * f) // 2 * 2
        x = {"right": 0, "left": W0 - ww}.get(side, (W0 - ww) // 2 // 2 * 2)
        y = {"bottom": 0, "top": H0 - hh}.get(side, (H0 - hh) // 2 // 2 * 2)
        opts.append((1 / f, (x, y, ww, hh)))
    if not opts:
        return None
    z, r = min(opts)
    return r + (round(z, 3),)


def logo_png(size, tmp):
    spr = brand_logo.load(size, ROOT / "assets") if brand_logo.enabled() else None
    if spr is None:
        return None
    p = Path(tmp) / f"logo_{size}.png"
    Image.fromarray(spr, "RGBA").save(p)
    return p


def build_filter(info, boxes, method, crop, logo, fit=True):
    """-> (filter_complex string, uses_logo_input)."""
    parts, cur, uses_logo = [], "0:v", False
    if method == "crop" and crop:
        x, y, w, h, _ = crop
        parts.append(f"[{cur}]crop={w}:{h}:{x}:{y}[c]")
        cur, sw, shh = "c", w, h
    else:
        sw, shh = info["w"], info["h"]
        if method == "blur":
            for i, (bx, by, bw, bh) in enumerate(boxes):
                bx, by = max(0, bx) // 2 * 2, max(0, by) // 2 * 2
                bw, bh = min(bw, info["w"] - bx) // 2 * 2, min(bh, info["h"] - by) // 2 * 2
                r = int(max(1, min(30, min(bw, bh) // 4 - 1)))      # chroma plane is half size: radius must fit there too
                parts.append(f"[{cur}]split=2[a{i}][b{i}];[b{i}]crop={bw}:{bh}:{bx}:{by},boxblur={r}:3[bl{i}];"
                             f"[a{i}][bl{i}]overlay={bx}:{by}[f{i}]")
                cur = f"f{i}"
                if logo is not None:
                    ls = int(min(max(bh * 1.05, 64), 220)) // 2 * 2
                    parts.append(f"[1:v]scale={ls}:{ls}[lg{i}];[{cur}][lg{i}]overlay={bx + (bw - ls) // 2}:{by + (bh - ls) // 2}[g{i}]")
                    cur, uses_logo = f"g{i}", True
    if abs(sw / shh - 9 / 16) < 0.03:
        parts.append(f"[{cur}]scale={W}:{H}:flags=lanczos,fps={FPS},format=yuv420p[out]")
    else:                                              # landscape/square: blurred fill behind the fitted video
        parts.append(f"[{cur}]split=2[s1][s2];[s1]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=28:5[bg];"
                     f"[s2]scale={W}:-2:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={FPS},format=yuv420p[out]")
    return ";".join(parts), uses_logo


def stage1(video, info, boxes, method, crop, out, tmp):
    logo = None
    if method == "blur" and boxes:
        logo = logo_png(160, tmp)
    fc, uses_logo = build_filter(info, boxes, method, crop, logo)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video)] + (["-i", str(logo)] if uses_logo else []) + \
          ["-filter_complex", fc, "-map", "[out]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", str(out)]
    sh(cmd)


# ---------------------------------------------------------------- 3. brand pass
def stage2(src, dst, hook_text, with_endcard=True, log=print):
    hook = hook_intro.HookText(hook_text, W)
    ec = endcard.EndCard(W) if with_endcard else None
    logo = brand_logo.load(76, ROOT / "assets") if brand_logo.enabled() else None
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(src), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                            "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                            "-profile:v", "high", "-movflags", "+faststart", str(dst)], stdin=subprocess.PIPE)
    fsz, g, last, first0, tail = W * H * 3, 0, None, None, []
    pad = brand_logo.pad_of(76) if logo is not None else 0

    def emit(fr):
        enc.stdin.write(fr.tobytes())

    while True:
        buf = dec.stdout.read(fsz)
        if len(buf) < fsz:
            break
        fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
        t = g / FPS
        if logo is not None:
            a = brand_logo.fade(t)
            if a > 0:
                blit(fr, logo, W - 44 - 76 - pad, 128 - pad, a)
        hook.draw(fr, t)
        if g == 0:
            first0 = fr.copy()
        last, g = fr, g + 1
        emit(fr)
    dec.wait()
    if last is None:
        raise RuntimeError("no frames decoded")
    n_end = int(END_SEC * FPS)
    base = cv2.GaussianBlur(last, (0, 0), 14)
    base = (base * 0.42).astype(np.uint8)
    for i in range(n_end):
        fr = base.copy()
        if ec is not None:
            ec.draw(fr, i / FPS)
        if i >= n_end - LOOP_N and first0 is not None:                    # loop-join: dissolve into frame 0
            wl = (i - (n_end - LOOP_N) + 1) / float(LOOP_N)
            fr = cv2.addWeighted(fr, 1 - wl, first0, wl, 0)
        emit(fr)
    enc.stdin.close()
    enc.wait()
    if enc.returncode != 0:
        raise RuntimeError("brand pass encode failed")
    return g / FPS + n_end / FPS


# ---------------------------------------------------------------- 4. audio + mux
def mux(vid, raw_video, info, audio, total, out):
    af = f"afade=t=out:st={max(0, total - 0.8):.2f}:d=0.8,loudnorm=I=-14:TP=-1.5:LRA=11"
    if audio:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(vid), "-stream_loop", "-1", "-i", str(audio), "-map", "0:v", "-map", "1:a"]
        src = "own"
    elif info["audio"]:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(vid), "-i", str(raw_video), "-map", "0:v", "-map", "1:a:0"]
        af, src = "apad," + af, "clip"
    else:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(vid), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v", "-map", "1:a"]
        src = "silent"
    sh(cmd + ["-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{total:.2f}",
              "-movflags", "+faststart", str(out)])
    return src


# ---------------------------------------------------------------- run
def process(video, out_dir="output/raw", audio=None, hook="", method="auto", box=None, with_endcard=True, log=print):
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "tmp"
    tmp.mkdir(exist_ok=True)
    info = probe(video)
    rep = {"input": str(video), "size": f"{info['w']}x{info['h']}", "duration": round(info["dur"], 2)}
    if box:
        boxes, how = [tuple(int(v) for v in box)], "manual"
    else:
        fr = sample_frames(video, info)
        sb = detect_watermark(fr)
        boxes = scale_boxes(sb, fr[0].shape[1], fr[0].shape[0], info["w"], info["h"]) if sb else []
        how = "auto"
    rep["watermark_boxes"], rep["detect"] = boxes, how
    log(f"[raw] {info['w']}x{info['h']} {info['dur']:.1f}s | watermark: {boxes or 'none found'}")
    crop, chosen = None, "none"
    if boxes and method != "none":
        if method in ("auto", "crop"):
            crop = plan_crop(info["w"], info["h"], boxes, MAX_ZOOM if method == "auto" else 1.6)
        chosen = "crop" if (crop and method in ("auto", "crop")) else "blur"
    rep["method"], rep["crop"] = chosen, crop
    log(f"[raw] removal: {chosen}" + (f" (zoom {crop[4]}x)" if chosen == "crop" else ""))
    s1, s2 = tmp / "s1.mp4", tmp / "s2.mp4"
    stage1(video, info, boxes, chosen, crop, s1, tmp)
    total = stage2(s1, s2, hook, with_endcard, log)
    final = out_dir / "final_raw.mp4"
    rep["audio"] = mux(s2, video, info, audio, total, final)
    rep["variants"] = {k: Path(v).name for k, v in variants.make_variants(final, log).items()}
    rep["total_sec"], rep["took_sec"] = round(total, 2), round(time.time() - t0, 1)
    (out_dir / "raw_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    for p in tmp.glob("*"):
        p.unlink(missing_ok=True)
    tmp.rmdir()
    log("[raw] done:", final)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--audio", default="")
    ap.add_argument("--hook", default="")
    ap.add_argument("--method", default="auto", choices=["auto", "crop", "blur", "none"])
    ap.add_argument("--box", default="", help="x,y,w,h in source pixels (skip auto detect)")
    ap.add_argument("--out", default="output/raw")
    ap.add_argument("--no-endcard", action="store_true")
    a = ap.parse_args(argv)
    if not Path(a.video).exists():
        sys.exit(f"video not found: {a.video}")
    box = [int(v) for v in a.box.split(",")] if a.box else None
    process(a.video, a.out, a.audio or None, a.hook.upper(), a.method, box, not a.no_endcard)


if __name__ == "__main__":
    main()
