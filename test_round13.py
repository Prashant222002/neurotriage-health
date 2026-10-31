"""Round 13: silent footage -> voice + music -> edited. Offline; TTS is mocked with a synthetic 'voice' (real TTS NOT tested here)."""
import json, os, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["TH_FX"] = "off"
import silent_mode as sm, talking_head as th, quality_gate as qg

def fake_tts(script):
    ws = script["en"].split(); sr = 22050; y = np.zeros(int((len(ws) * .42 + .3) * sr), np.float32); ev = []
    for i, w in enumerate(ws):
        a = i * .42; n = int(.32 * sr); t = np.arange(n) / sr
        y[int(a * sr):int(a * sr) + n] += (np.sin(2 * np.pi * 170 * t) * (np.sin(np.pi * t / .32) ** 2) * .4).astype(np.float32); ev.append((w, a, a + .32))
    p = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-", "-f", "mp3", "-"], input=y.tobytes(), capture_output=True, check=True)
    return p.stdout, ev

with tempfile.TemporaryDirectory() as td:
    td = Path(td); src = td / "raw.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=540x960:r=30:d=14", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
    assert sm.is_silent(src)                                               # no audio track
    loud = td / "loud.mp4"; subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-f", "lavfi", "-i", "sine=f=300:d=14", "-c:v", "copy", "-c:a", "aac", str(loud)], check=True)
    assert not sm.is_silent(loud)                                          # real audio untouched by the new mode
    # voiceover path (user script, no AI)
    sm.tts = fake_tts
    text = "Kabhi kabhi hum bas thoda ruk kar saans lena bhool jaate hain. Aaj ek minute apne liye nikaalo aur dheere se saans lo."
    th.main(["--video", str(src), "--script", text, "--topic", "mental health calm", "--out", str(td / "o1"), "--work", str(td / "w1"), "--no-endcard"])
    f = td / "o1" / "final_th.mp4"; m = qg.measure(f); rep = json.loads((td / "o1" / "th_report.json").read_text())
    assert m["ok"] and m["audio"] and m["lufs"] is not None and m["lufs"] > -30, m
    assert rep["fx"]["status"] == "done" and "quality" in rep["fx"] and (td / "w1" / "words_auto.json").exists() and (td / "w1" / "auto_music.wav").exists()
    # no script + no AI -> music-only (never fake narration), file valid + has audio
    th.main(["--video", str(src), "--topic", "mental health", "--out", str(td / "o2"), "--work", str(td / "w2")])
    m2 = qg.measure(td / "o2" / "final_th.mp4"); assert m2["ok"] and m2["audio"] and abs(m2["dur"] - 14) < .4
    assert json.loads((td / "o2" / "th_report.json").read_text())["mode"] == "music-only"
    # TTS failure -> music-only fallback, no crash
    sm.tts = lambda s: (_ for _ in ()).throw(RuntimeError("down"))
    th.main(["--video", str(src), "--script", text, "--out", str(td / "o3"), "--work", str(td / "w3")])
    assert json.loads((td / "o3" / "th_report.json").read_text())["mode"] == "music-only"
    # music choice by topic
    assert sm.topic_hook("customized photo album gift for her") == "CUSTOMIZED PHOTO ALBUM GIFT" and sm.topic_hook("") == ""
    assert sm.CALM.search("Mental health tips") and not sm.CALM.search("customized photo album")
print("round13 OK")
