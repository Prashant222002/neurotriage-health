"""Round 10: auto hook, footage enhance, voice FX + sfx + music mux, cover."""
import json, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import talking_head as th

# auto hook: greetings stripped, never empty
w = [("Namaste", 0, .4), ("doston", .5, .9), ("yeh", 1.0, 1.2), ("tool", 1.3, 1.6), ("kamaal", 1.7, 2.0), ("hai.", 2.1, 2.4)]
h = th.auto_hook(w)
assert h and not h.startswith("NAMASTE"), h
assert th.auto_hook([("Hello", 0, .3), ("doston", .4, .8)]) == "END TAK DEKHO"

d = Path(tempfile.mkdtemp())
src = d / "c.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x303030:s=540x960:d=3:r=30", "-f", "lavfi", "-i", "sine=f=300:d=3",
                "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)], check=True)
f = th.enhance_filter(src)
assert "eq=" in f and "unsharp" in f, f           # dark clip gets lifted
th_env = th.os.environ; th_env["TH_ENHANCE"] = "off"; assert th.enhance_filter(src) == ""; th_env["TH_ENHANCE"] = "on"

# mux: voice + music + 2 whooshes + pop -> one audio stream of the right length
vid = d / "v.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=4:r=30", "-c:v", "libx264", str(vid)], check=True)
mus = d / "m.mp3"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=1", str(mus)], check=True)
out = d / "o.mp4"
th.mux(vid, src, 4.0, out, mus, 0.2, [0.5, 1.5], 3.0, d)
j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", str(out)], capture_output=True, text=True).stdout)
assert sorted(s["codec_type"] for s in j["streams"]) == ["audio", "video"], j
assert abs(float(j["streams"][0]["duration"]) - 4.0) < 0.2, j
# single whoosh, no music, no pop
th.mux(vid, src, 4.0, d / "o2.mp4", None, 0.2, [1.0], None, d)
assert (d / "o2.mp4").stat().st_size > 1000
print("round10 OK")
