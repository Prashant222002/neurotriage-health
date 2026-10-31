"""ROUND 5b+5c TEST - end card, loop-join, 4K/IG files, raw editor (watermark detect/remove, own audio), workflow.
Needs ffmpeg. No network. Run: python tests/test_round5bc.py"""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for k in list(os.environ):
    if any(h in k for h in ("GROQ", "GEMINI", "ELEVEN")):
        del os.environ[k]
os.environ.update(GROQ_API_KEY="x", GEMINI_API_KEY="y", YT_4K_PRESET="ultrafast")
import cv2, numpy as np
import endcard, variants, raw_edit, publisher
tmp = Path(tempfile.mkdtemp())
n = 0
def check(name, cond):
    global n
    print(("PASS " if cond else "FAIL ") + name); n += 1
    assert cond, name
def sh(c): return subprocess.run(c, check=True, capture_output=True)

# ---------- synthetic raw clips
def make_clip(path, w, h, secs=5, fps=24, mark=None, static_bg=False, audio=False):
    rng = np.random.RandomState(3)
    tex = cv2.GaussianBlur(rng.randint(0, 255, (h * 2, w * 3, 3), np.uint8), (0, 0), 6)
    tex = cv2.normalize(tex, None, 30, 170, cv2.NORM_MINMAX)
    for _ in range(80):
        cv2.line(tex, tuple(rng.randint(0, [w * 3, h * 2])), tuple(rng.randint(0, [w * 3, h * 2])), tuple(int(v) for v in rng.randint(0, 255, 3)), 3)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
                            "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    for i in range(secs * fps):
        ox, oy = (0, 0) if static_bg else (int(i * 9) % (w * 2), int(i * 5) % h)
        fr = tex[oy:oy + h, ox:ox + w].copy()
        if mark:
            ov = fr.copy()
            cv2.putText(ov, mark[0], mark[1], cv2.FONT_HERSHEY_DUPLEX, mark[2], (255, 255, 255), max(2, int(mark[2] * 2)))
            fr = cv2.addWeighted(fr, 0.45, ov, 0.55, 0)
        enc.stdin.write(fr.tobytes())
    enc.stdin.close(); enc.wait()
    if audio:
        a = tmp / "a.wav"
        sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=%d" % secs, str(a)])
        o = Path(str(path) + ".av.mp4")
        sh(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-i", str(a), "-c:v", "copy", "-c:a", "aac", "-shortest", str(o)])
        o.replace(path)

W0, H0 = 720, 1280
wm = tmp / "wm.mp4";  make_clip(wm, W0, H0, mark=("GROK", (470, 1235), 1.5), audio=True)
clean = tmp / "clean.mp4"; make_clip(clean, W0, H0)
static = tmp / "static.mp4"; make_clip(static, W0, H0, static_bg=True)
land = tmp / "land.mp4"; make_clip(land, 1280, 720, mark=("AIVID", (30, 60), 1.4))

# ---------- 5c detection
def det(p):
    info = raw_edit.probe(p); fr = raw_edit.sample_frames(p, info)
    return raw_edit.scale_boxes(raw_edit.detect_watermark(fr), fr[0].shape[1], fr[0].shape[0], info["w"], info["h"]), info
b, info = det(wm)
check("watermark found (bottom-right)", len(b) == 1 and b[0][0] > W0 * .5 and b[0][1] > H0 * .85)
gt = (470, 1235 - 45, 195, 65)                      # approximate text box
ix = max(0, min(b[0][0] + b[0][2], gt[0] + gt[2]) - max(b[0][0], gt[0])); iy = max(0, min(b[0][1] + b[0][3], gt[1] + gt[3]) - max(b[0][1], gt[1]))
check("detected box overlaps the real text", ix * iy > 0.3 * gt[2] * gt[3])
check("NO watermark on a clean moving clip -> nothing detected", det(clean)[0] == [])
check("NO false detection on a static-camera scene", det(static)[0] == [])
bl, _ = det(land)
check("landscape clip: top-left watermark found", len(bl) == 1 and bl[0][0] < 400 and bl[0][1] < 200)

# ---------- removal planning
c = raw_edit.plan_crop(720, 1280, [(500, 1215, 190, 55)])
check("small corner mark -> zoom-crop within 1.28x", c is not None and c[4] <= 1.28)
check("crop window excludes the mark", c[1] + c[3] <= 1215 or c[0] + c[2] <= 500)
check("big mark far from edge -> no crop (blur+logo instead)", raw_edit.plan_crop(720, 1280, [(200, 400, 300, 300)]) is None)

# ---------- full run: auto (crop), forced blur+logo, own audio
own = tmp / "own.wav"; sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=2", str(own)])
t0 = time.time()
rep = raw_edit.process(wm, tmp / "o1", audio=own, hook="YE HABIT TOD DO", log=lambda *a: None)
f1 = tmp / "o1" / "final_raw.mp4"
p1 = raw_edit.probe(f1)
check("auto method chose crop", rep["method"] == "crop" and rep["crop"][4] <= 1.28)
check("output is 1080x1920 with audio", (p1["w"], p1["h"]) == (1080, 1920) and p1["audio"])
check("length = clip + end card (5 s + 2.8 s)", abs(p1["dur"] - 7.8) < 0.4)
check("own audio used (looped to full length)", rep["audio"] == "own")
check("Instagram file made, 4K NOT made (off by default)", (tmp / "o1" / "final_raw_ig.mp4").exists() and not (tmp / "o1" / "final_raw_4k.mp4").exists())
pi = raw_edit.probe(tmp / "o1" / "final_raw_ig.mp4")
check("IG file is 1080x1920", (pi["w"], pi["h"]) == (1080, 1920))
os.environ["YT_4K"] = "off"        # 4K encode is slow: only the first run builds it
print("   raw edit took %.0fs" % (time.time() - t0))
def frame_at(p, t):
    r = sh(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(p), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    return np.frombuffer(r.stdout, np.uint8).reshape(1920, 1080, 3)
f0, fe = frame_at(f1, 0.0), frame_at(f1, 6.9)
check("first frame has hook text (not plain/white)", f0.std() > 20 and int((f0 > 250).all(axis=2).sum()) > 3000)
check("end card shows buttons (bright colored pixels in row y~1200-1290)", fe[1200:1290].std() > 25)
fl = frame_at(f1, 7.75)
check("loop-join: last frame ~ first frame", float(np.abs(fl.astype(int) - f0.astype(int)).mean()) < 30)

rep2 = raw_edit.process(wm, tmp / "o2", method="blur", log=lambda *a: None)
f2 = frame_at(tmp / "o2" / "final_raw.mp4", 1.5)
check("forced blur+logo works", rep2["method"] == "blur" and (tmp / "o2" / "final_raw.mp4").exists())
check("clip's own sound kept when no audio given", rep2["audio"] == "clip")
rep3 = raw_edit.process(clean, tmp / "o3", log=lambda *a: None)
check("clean clip: nothing removed, still branded", rep3["method"] == "none" and rep3["watermark_boxes"] == [])
rep4 = raw_edit.process(land, tmp / "o4", log=lambda *a: None)
check("landscape clip fitted to 1080x1920 with blurred fill", raw_edit.probe(tmp / "o4" / "final_raw.mp4")["h"] == 1920)
rep5 = raw_edit.process(clean, tmp / "o5", box=(500, 1215, 190, 55), method="blur", log=lambda *a: None)
check("manual --box respected", rep5["detect"] == "manual" and rep5["watermark_boxes"] == [(500, 1215, 190, 55)])
check("silent clip + no audio -> silent track added", rep3["audio"] == "silent")

# ---------- 5b pieces
ec = endcard.EndCard(); fr = np.full((1920, 1080, 3), 30, np.uint8); ec.draw(fr, 1.6)
check("end card draws 3 buttons + Try pill in safe area", fr[1190:1520].std() > 30 and (fr[:1150] == 30).all() and (fr[1600:] == 30).all())
check("end card animates in (t=0 almost empty)", (lambda f: (ec.draw(f, 0.0), int((f != 30).sum()))[1])(np.full((1920, 1080, 3), 30, np.uint8)) < 200000)
wm1 = tmp / "wm1.mp4"; sh(["ffmpeg", "-y", "-v", "error", "-i", str(wm), "-t", "1", "-an", str(wm1)])   # 1 s clip: 4K encode stays fast
os.environ["YT_4K"] = "on"
v = variants.make_variants(wm1, log=lambda *a: None)
check("variants for a master", set(v) == {"youtube", "instagram"})
check("publisher picks 4K for YouTube, IG file for Instagram/Facebook, master otherwise",
      variants.pick("youtube", wm1).name.endswith("_4k.mp4") and variants.pick("instagram", wm1).name.endswith("_ig.mp4")
      and variants.pick("facebook", wm1).name.endswith("_ig.mp4") and variants.pick("youtube", clean) == clean)
os.environ["YT_4K"] = "off"; os.environ["IG_FILE"] = "off"
check("YT_4K=off / IG_FILE=off skip both", variants.make_variants(clean, log=lambda *a: None) == {})
src = (ROOT / "bot.py").read_text()
check("render loop: end card + loop-join + switch", "ecard.draw(frame" in src and "first0" in src and "LOOP_JOIN" in src)
check("enqueue ships the 4K/IG siblings; publisher picks per platform", "variants.sibling(video" in src and "variants.pick(name, video)" in (ROOT / "publisher.py").read_text())

# ---------- workflow
import yaml
wf = ROOT / ".github/workflows/edit_raw.yml"
t = wf.read_text(); y = yaml.safe_load(t)
check("edit_raw.yml: manual only, button inputs", list(y[True]) == ["workflow_dispatch"] and {"video", "audio", "hook", "method"} <= set(y[True]["workflow_dispatch"]["inputs"]))
check("edit_raw.yml shares the build concurrency group, uploads artifact", y["concurrency"]["group"] == "midnight-build" and "upload-artifact" in t and "raw_edit.py" in t)
check("edit_raw.yml: no secrets needed, no publishing", "secrets." not in t and "publisher" not in t)
print(f"\nALL {n} ROUND-5b/5c CHECKS PASSED")
