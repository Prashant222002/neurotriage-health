"""ROUND 1 TEST - crash-proofing. Run: python tests/test_round1.py"""
import sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np, cv2
import safe, long_render

tmp = Path(tempfile.mkdtemp())
ok = 0
def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok += bool(cond)
    assert cond, name

# 1-3 thumbnail: string / list (the exact production crash) / empty / None / dict / number
for i, v in enumerate(["90 Minute Study Hack", ["90 Minute", "Study Hack"], [], None, "", {"a": "Focus Now"}, 42, [["x", "y"], None]]):
    p = tmp / f"t{i}.jpg"
    long_render.make_thumbnail(v, p, "NeuroTriage", None)
    img = cv2.imread(str(p))
    check(f"thumbnail input {v!r}", img is not None and img.shape[:2] == (720, 1280))
# thumbnail with a real frame background + brand None
fr = np.random.randint(0, 255, (360, 640, 3), np.uint8)
long_render.make_thumbnail(["A", "B"], tmp / "f.jpg", None, fr)
check("thumbnail with frame + brand=None", (tmp / "f.jpg").exists())

# normalize_pack with every wrong type the AI could send
pk = safe.normalize_pack({"title": ["T1", "T2"], "thumb_text": ["Big", "Hook"], "hashtags": "#a #b, c",
                          "yt_description": None, "titles": "x"}, "Fallback")
check("pack title list->str", isinstance(pk["title"], str) and pk["title"])
check("pack thumb_text list->upper str", pk["thumb_text"] == "BIG HOOK")
check("pack hashtags str->list", pk["hashtags"] == ["#a", "#b", "#c"])
check("pack None desc -> ''", pk["yt_description"] == "")
check("pack garbage input", safe.normalize_pack("garbage", "F")["title"] == "F")
check("pack None input", safe.normalize_pack(None, "F")["thumb_text"] == "F")

# soft(): failing step is skipped, pipeline continues, recorded
def boom(): raise ValueError("boom")
logs = []
r = safe.soft("demo", boom, "fallback", logs.append)
check("soft returns fallback, no raise", r == "fallback" and "boom" in logs[0])
check("soft step recorded", safe.STEPS[-1]["status"] == "FAILED-skipped")
safe.save_steps(tmp / "s.json"); check("step_report written", (tmp / "s.json").exists())

print(f"\nALL {ok} CHECKS PASSED")
