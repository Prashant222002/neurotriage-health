"""Round 11: fx_bridge (Claude Effects). Offline, no API."""
import os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import fx_bridge as b
os.environ['TH_FX_CAMERA'] = '0'     # Round 15: camera fx are ON by default; this block checks the opt-out
# validation: whitelist, overlap, head/tail, text rules, camera opt-in
v = b.validate([{"fx": "evil;rm", "start": 3, "end": 5}, {"fx": "backdrop-word", "start": 3, "end": 9, "text": "Hi <b>"},
                {"fx": "spotlight", "start": 4, "end": 6}, {"fx": "backdrop-word", "start": 5, "end": 7},
                {"fx": "lean-in", "start": 10, "end": 12}, {"fx": "moody", "start": 0, "end": 1}], 30)
assert [e["fx"] for e in v] == ["backdrop-word"] and v[0]["end"] - v[0]["start"] <= 2.6 and "<" not in v[0]["text"], v
del os.environ['TH_FX_CAMERA']
assert [e['fx'] for e in b.validate([{'fx': 'lean-in', 'start': 10, 'end': 12}], 30)] == ['lean-in']   # default ON
assert b.validate("garbage", 30) == [] and b.validate(None, 30) == []
# planner never needs an LLM; bad LLM output falls back to rules
words = [("intro", 0, .3)] + [("migraine", 10 + i, 10.5 + i) for i in range(0, 20, 5)]
assert b.plan_effects(words, 40, llm=lambda p: "not json")[1] == "rules"
assert b.plan_effects(words, 40, llm=lambda p: '{"effects":[{"fx":"moody","start":5,"end":9}]}')[1] == "llm"
assert b.plan_effects([], 40) == ([], "rules")
with tempfile.TemporaryDirectory() as td:
    td = Path(td); src = td / "s.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=360x640:r=30:d=8", "-f", "lavfi", "-i", "sine=d=8",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)], check=True)
    plan = [{"fx": "moody", "start": 2, "end": 5}]
    # unreadable source / empty plan / disabled -> original path, no raise
    assert b.apply_effects(td / "nope.mp4", td / "o.mp4", plan)[0] == td / "nope.mp4"
    assert b.apply_effects(src, td / "o.mp4", [])[1].startswith("skipped")
    os.environ["TH_FX"] = "off"; assert b.apply_effects(src, td / "o.mp4", plan)[1] == "skipped:disabled"; del os.environ["TH_FX"]
    # forced failure (broken fx.py) -> original returned, no partial file left
    real = b.FX_PY; b.FX_PY = td / "missing.py"
    assert b.apply_effects(src, td / "o.mp4", plan) == (src, "skipped:vendor-missing")
    bad = td / "bad.py"; bad.write_text("import sys; sys.exit(3)"); b.FX_PY = bad
    r, st = b.apply_effects(src, td / "o.mp4", plan)
    assert r == src and st == "skipped:all-attempts-failed" and not (td / "o.mp4").exists(), (r, st)
    b.FX_PY = real
    # real render: duration + audio preserved
    r, st = b.apply_effects(src, td / "o.mp4", plan)
    assert st == "applied" and abs(b.probe(r)["dur"] - 8) < .35 and b.probe(r)["audio"], st
print("round11 OK")
