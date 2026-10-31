"""Round 9c: phone video (stored 1920x1080 + rotation 90) must probe as 1080x1920 portrait."""
import subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import raw_edit

d = Path(tempfile.mkdtemp())
src, rot = d / "land.mp4", d / "rot.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=1920x1080:d=1:r=30", "-f", "lavfi", "-i", "sine=d=1",
                "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)], check=True)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-display_rotation", "90", "-i", str(src), "-c", "copy", str(rot)], check=True)
a, b = raw_edit.probe(src), raw_edit.probe(rot)
assert (a["w"], a["h"]) == (1920, 1080), a
assert (b["w"], b["h"]) == (1080, 1920), b
print("round9c OK")
