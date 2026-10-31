"""Round 12 - objective quality gate (no AI needed). Measures defects + basic look; score 0-100.
Honest scope: it catches broken/ugly output and decides 'effects version vs clean version'. It cannot judge taste."""
import json, re, subprocess
from pathlib import Path
import cv2, numpy as np

PASS_SCORE = 75
YUNET = Path(__file__).parent / "vendor" / "claude_fx" / "models" / "yunet.onnx"


def _run(cmd, timeout=300):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def measure(path, samples=6):
    m = {"ok": False}
    try:
        j = json.loads(_run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,avg_frame_rate:format=duration",
                             "-of", "json", str(path)], 30).stdout)
        v = next(s for s in j["streams"] if s["codec_type"] == "video")
        m.update(dur=float(j["format"]["duration"]), w=v["width"], h=v["height"], audio=any(s["codec_type"] == "audio" for s in j["streams"]))
    except Exception as e:
        m["err"] = f"unreadable:{type(e).__name__}"; return m
    r = _run(["ffmpeg", "-nostats", "-i", str(path), "-vf", "blackdetect=d=0.3:pix_th=0.10,freezedetect=n=-60dB:d=2", "-an", "-f", "null", "-"])
    m["black"] = round(sum(float(x) for x in re.findall(r"black_duration:([\d.]+)", r.stderr)), 2)
    m["freeze"] = round(sum(float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", r.stderr)), 2)
    if m["audio"]:
        r = _run(["ffmpeg", "-nostats", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"])
        s = r.stderr.split("Summary:")[-1]
        li = re.search(r"I:\s+(-?[\d.]+) LUFS", s); pk = re.search(r"Peak:\s+(-?[\d.]+) dBFS", s)
        m["lufs"] = float(li.group(1)) if li else None; m["peak"] = float(pk.group(1)) if pk else None
    cap = cv2.VideoCapture(str(path)); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    br, ct, sh, faces, got = [], [], [], 0, 0
    fd = None
    try:
        fd = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.6, 0.3, 5) if YUNET.exists() else None
    except Exception: fd = None
    for k in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (k + .5) / samples)); ok, fr = cap.read()
        if not ok: continue
        got += 1; sc = 540 / fr.shape[1]; fr = cv2.resize(fr, None, fx=sc, fy=sc); g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        br.append(float(g.mean())); ct.append(float(g.std())); sh.append(float(cv2.Laplacian(g, cv2.CV_64F).var()))
        if fd is not None:
            fd.setInputSize((fr.shape[1], fr.shape[0])); _, f = fd.detect(fr); faces += int(f is not None and len(f) > 0)
    cap.release()
    if got:
        m.update(bright=round(np.mean(br), 1), contrast=round(np.mean(ct), 1), sharp=round(float(np.median(sh)), 1),
                 face_ratio=round(faces / got, 2) if fd is not None else None)
    m["ok"] = got > 0
    return m


def score(m, expect_audio=True, expect_face=False, src_dur=None):
    if not m.get("ok"): return 0, ["unreadable"], True
    s, issues, hard = 100, [], False
    if m["dur"] < 1: s -= 100; hard = True; issues.append("too-short")
    if expect_audio and not m["audio"]: s -= 60; hard = True; issues.append("no-audio")
    if src_dur and abs(m["dur"] - src_dur) > 0.5: s -= 25; issues.append("duration-drift")
    if m["black"] > 0.6: s -= 15; issues.append(f"black-frames {m['black']}s")
    if m["freeze"] > 3: s -= 10; issues.append(f"frozen {m['freeze']}s")
    if m.get("lufs") is not None and not (-20 <= m["lufs"] <= -10): s -= 10; issues.append(f"loudness {m['lufs']} LUFS")
    if m.get("peak") is not None and m["peak"] > -0.5: s -= 8; issues.append("clipping")
    if "bright" in m:
        if not 45 <= m["bright"] <= 215: s -= 8; issues.append("exposure")
        if m["contrast"] < 25: s -= 6; issues.append("flat-contrast")
        if m["sharp"] < 40: s -= 8; issues.append("soft/blurry")
        if expect_face and m.get("face_ratio") is not None and m["face_ratio"] < 0.5: s -= 10; issues.append("face-often-missing")
    return max(0, s), issues, hard


def review(final, clean=None, expect_audio=True, expect_face=False, src_dur=None):
    """Compare final vs clean (pre-enhancement). Reverts final to clean if enhancement made it worse or broke it.
    Returns report dict; 'ok' False only if the file we ship is below PASS_SCORE or hard-failed."""
    final, rep = Path(final), {}
    mf = measure(final); sf, isf, hf = score(mf, expect_audio, expect_face, src_dur)
    rep.update(score=sf, issues=isf, metrics=mf)
    if clean and Path(clean).exists():
        mc = measure(clean); sc_, isc, hc = score(mc, expect_audio, expect_face, src_dur)
        rep["clean_score"] = sc_
        if hf or sf < sc_ - 1 or len(isf) > len(isc):
            Path(clean).replace(final); rep.update(reverted_to_clean=True, score=sc_, issues=isc, metrics=mc); sf, hf = sc_, hc
    rep["ok"] = bool(sf >= PASS_SCORE and not hf)
    rep["verdict"] = "PASS" if rep["ok"] else "NEEDS-REVIEW"
    return rep
