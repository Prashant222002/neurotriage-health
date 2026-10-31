"""Round 12: ai_router, quality_gate, motion_blocks, enhance. Offline."""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["TH_FX"] = "off"                       # fx renders covered in test_round11
import ai_router as r, quality_gate as qg, motion_blocks as mb, enhance
# --- router: groq 429 -> gemini garbage -> extra ok; all fail -> local; budget cap
os.environ.update(LLM_EXTRA_URL="x", LLM_EXTRA_KEY="k", GROQ_API_KEY="g", GEMINI_API_KEY="m")
calls = []
def fake(url, h, b, p, t):
    calls.append(url)
    if "groq" in url: return 429, None, "rate limit", {}
    if "google" in url: return 200, {"candidates": [{"content": {"parts": [{"text": "nope"}]}}]}, "", {}
    return 200, {"choices": [{"message": {"content": '```json\n{"a":1}\n```'}}]}, "", {}
r._http = fake
d, prov = r.ask_json("q1", validate=lambda x: x if isinstance(x, dict) and "a" in x else None)
assert d == {"a": 1} and prov == "extra" and sum("groq" in c for c in calls) == 1, (d, prov, calls)   # 429 NOT retried on same key
r._http = lambda *a: (500, None, "boom", {}); r.CFG["base"] = 0.01; r.STATS["calls"] = 0
assert r.ask_json("q2") == (None, "local")
r.STATS["calls"] = 99; assert r.ask_json("q3") == (None, "local")        # budget cap
# --- grounding: invented numbers rejected
words = [("sirf", 1.0, 1.3), ("70", 2.0, 2.3), ("percent", 2.4, 2.8), ("log", 2.9, 3.1), ("migraine", 3.2, 3.6), ("se", 3.7, 3.8), ("pareshan", 3.9, 4.3)] + [("baat", 5 + i * .4, 5.3 + i * .4) for i in range(10)]
txt = " ".join(w[0] for w in words)
plan = mb.plan_from_words(words, 14); assert plan and plan[0]["value"] == "70%", plan
assert mb.validate(plan, 14, txt) and not mb.validate([dict(plan[0], value="95%")], 14, txt)
assert not mb.validate([{"block": "bar_chart", "start": 3, "end": 7, "items": [["A", 70], ["B", 41]]}], 14, txt)
assert mb.validate([{"block": "bar_chart", "start": 3, "end": 7, "items": [["A", 70], ["B", 70]]}], 14, txt)
assert not mb.validate([{"block": "evil", "start": 3, "end": 7}], 14, txt) and mb.validate(None, 14, txt) == []
with tempfile.TemporaryDirectory() as td:
    td = Path(td); src = td / "s.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=540x960:r=30:d=12", "-f", "lavfi", "-i", "sine=f=300:d=12",
                    "-af", "volume=0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)], check=True)
    # --- quality gate
    bad = td / "bad.mp4"; bad.write_bytes(b"garbage"); assert qg.score(qg.measure(bad))[2] is True
    blk = td / "blk.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=540x960:r=30:d=12", "-f", "lavfi", "-i", "sine=f=300:d=12", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(blk)], check=True)
    sb = qg.score(qg.measure(blk)); sg = qg.score(qg.measure(src)); assert sb[0] < sg[0] and any("black" in i for i in sb[1]), (sb, sg)
    f2 = td / "f2.mp4"; shutil.copy(blk, f2); c2 = td / "c2.mp4"; shutil.copy(src, c2)
    rv = qg.review(f2, c2, True, False); assert rv.get("reverted_to_clean") and rv["score"] == sg[0]
    # --- composite with controlled face box: card drawn, audio+duration kept, other region identical
    mb.faces_at = lambda *a: [(200, 330, 340, 450)]
    o = td / "o.mp4"; act = mb.composite(src, o, mb.validate(plan, 12, txt))
    m = qg.measure(o); assert m["ok"] and abs(m["dur"] - 12) < .35 and m["audio"] and (m["w"], m["h"]) == (540, 960)
    import cv2, numpy as np
    def frame(p, t):
        c = cv2.VideoCapture(str(p)); c.set(cv2.CAP_PROP_POS_MSEC, t * 1000); ok, f = c.read(); c.release(); return f.astype(int)
    diff = np.abs(frame(o, 3.0) - frame(src, 3.0)).sum(2)
    y0 = act[0]["y"]; assert diff[y0:y0 + 150].mean() > 5 * diff[500:900].mean() and diff[500:900].mean() < 15, "card missing or spilled"   # mean: re-encode adds small noise
    assert np.abs(frame(o, 10.5) - frame(src, 10.5)).mean() < 6            # outside window untouched
    # --- enhance end-to-end (blocks + gate), original preserved on failure
    out = td / "final_th.mp4"; shutil.copy(src, out)
    rep = enhance.run(out, words, 12, [], False, td, lambda *a: None)
    assert rep["status"] == "done" and rep["quality"]["verdict"] in ("PASS", "NEEDS-REVIEW") and qg.measure(out)["ok"], rep
    assert any(s.get("blocks") and s.get("status") == "applied" for s in rep["steps"]), rep["steps"]
    mb.composite = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    out2 = td / "o2" / "final_th.mp4"; out2.parent.mkdir(); shutil.copy(src, out2)
    rep2 = enhance.run(out2, words, 12, [], False, td, lambda *a: None)
    assert rep2["status"] == "done" and qg.measure(out2)["ok"] and not (out2.parent / "final_th_blocks.mp4").exists(), rep2
print("round12 OK")
