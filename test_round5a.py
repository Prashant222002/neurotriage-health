"""ROUND 5a TEST - trending-first topic plan + rotation, caption fix, hook text from frame 0, share rules, AI flag.
No network. Run: python tests/test_round5a.py"""
import json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for k in list(os.environ):
    if any(h in k for h in ("GROQ", "GEMINI", "ELEVEN")):
        del os.environ[k]
os.environ.update(GROQ_API_KEY="x", GEMINI_API_KEY="y")
import numpy as np
import topics, caption_styles, hook_intro, virality, bot
tmp = Path(tempfile.mkdtemp())
SP = tmp / "rot.json"
n = 0
def check(name, cond):
    global n
    print(("PASS " if cond else "FAIL ") + name); n += 1
    assert cond, name

RSS = """<rss><channel><item><title>NEET result 2026</title></item><item><title>Man killed in blast</title></item>
<item><title>Dream11 tips today</title></item><item><title>Sleep challenge viral</title></item><item><title>Better sleep</title></item></channel></rss>"""
def http_ok(url, params=None, timeout=10): return RSS
def http_dead(url, params=None, timeout=10): raise RuntimeError("offline")

# 1. trends: parsed, tragedy/betting removed, never raises
tr = topics.fetch_trends(http_ok)
check("sensitive trends dropped (blast, betting)", tr == ["NEET result 2026", "Sleep challenge viral", "Better sleep"])
check("trend fetch survives a dead network", topics.fetch_trends(http_dead) == [])

# 2. trending is ALWAYS first priority when something fits
ask_fit = lambda p, **k: json.dumps({"fit": True, "trend": "NEET result 2026", "angle": "result stress", "mode": "awareness", "audience": "NEET aspirant"})
p = topics.plan(ask_fit, http_ok, state_path=SP, log=lambda *a: None)
check("trending wins over rotation", p["kind"] == "trending" and p["trend"] == "NEET result 2026" and p["mode"] == "awareness")
check("directive names the trend and says MANDATORY", "MANDATORY" in p["directive"] and "NEET result 2026" in p["directive"])
ask_invent = lambda p, **k: json.dumps({"fit": True, "trend": "Made up trend", "angle": "x", "mode": "student", "audience": "y"})
check("LLM cannot invent a trend that is not in the list", topics.judge_trend(ask_invent, tr) is None)
check("fit=false -> no trend", topics.judge_trend(lambda p, **k: '{"fit": false}', tr) is None)
check("forced MODE overrides trend mode", topics.judge_trend(ask_fit, tr, "student")["mode"] == "student")

# 3. a trend is used once, then 3-day cooldown
topics.record(p, SP)
p2 = topics.plan(ask_fit, http_ok, state_path=SP, log=lambda *a: None)
check("same trend not reused within cooldown (falls to rotation)", p2["kind"] == "disorder" and p2["trend"] == "")
check("trending day does not burn a rotation slot", topics.load_state(SP)["n_regular"] == 0)

# 4. no trend -> rotation: disorder first, then habit, alternating; never the same subject twice in a row
ask_none = lambda p, **k: '{"fit": false}'
seq, st_path = [], tmp / "rot2.json"
for _ in range(60):
    q = topics.plan(ask_none, http_dead, state_path=st_path, log=lambda *a: None)
    seq.append(q); topics.record(q, st_path)
check("first regular topic is a psychiatric disorder", seq[0]["kind"] == "disorder" and seq[0]["mode"] == "awareness")
check("alternates disorder / habit", [s["kind"] for s in seq[:6]] == ["disorder", "habit"] * 3)
check("habit days use student mode", seq[1]["mode"] == "student")
subs = [s["subject"] for s in seq]
check("never the same subject back to back (60 runs, incl. cycle wrap)", all(a != b for a, b in zip(subs, subs[1:])))
check("every disorder used once before any repeats", len(set(subs[0:56:2])) == len(topics.DISORDERS))
auds = [s["audience"] for s in seq]
check("every student type gets a turn, never twice in a row", set(auds[:12]) == set(topics.STUDENTS) and all(a != b for a, b in zip(auds, auds[1:])))
check("forced MODE=student keeps habits only", topics.pick_regular(topics.load_state(tmp / "none.json"), "student")[0] == "habit")

# 5. state: bad file does not crash
(tmp / "bad.json").write_text("{not json")
check("corrupt rotation file -> fresh state", topics.load_state(tmp / "bad.json")["n_regular"] == 0)

# 6. caption fix: no page ends in 'MOVE-'
w = [("Jab", 0, .2), ("padhai", .2, .5), ("karo", .5, .7), ("then", .7, .9), ("move-", .9, 1.1), ("on", 1.1, 1.3), ("to", 1.3, 1.5), ("next", 1.5, 1.7)]
pg = caption_styles.paginate(w)
check("no caption page ends with a dangling hyphen", all(not p_[-1][0].endswith("-") for p_ in pg[:-1]))
check("'MOVE-' stays with 'ON'", any([c[0] for c in p_][:2] == ["MOVE-", "ON"] for p_ in pg))
w3 = [("ek", 0, .2), ("do", .2, .4), ("teen", .4, .6), ("char", .6, .8), ("move-", .8, 1.0), ("on", 1.0, 1.2)]
check("dash at the page limit still glued", [[c[0] for c in p_] for p_ in caption_styles.paginate(w3)][-1][-2:] == ["MOVE-", "ON"])
check("both caption engines share paginate()", "caption_styles.paginate" in (ROOT / "bot.py").read_text() and "paginate(words" in (ROOT / "caption_styles.py").read_text())
cap = caption_styles.StyledCaptions(w, "box"); old = bot.Captions(w)
check("StyledCaptions + old Captions page identically", [[c[0] for c in p_] for p_ in cap.pages] == [[c[0] for c in p_] for p_ in old.pages])

# 7. hook text from frame 0
ht = hook_intro.HookText("YE HABIT TUMHE THAKA RAHI HAI")
f0 = np.full((1920, 1080, 3), 255, np.uint8)
ht.draw(f0, 0.0)
check("frame 0 is NOT plain white any more (hook drawn)", int((f0 != 255).sum()) > 50000)
f_late = np.full((1920, 1080, 3), 255, np.uint8); ht.draw(f_late, 3.0)
check("hook gone after ~2.3s", (f_late == 255).all())
check("hook stays clear of captions (y<1000) and HUD chip (y>360)", (f0[:360] == 255).all() and (f0[1000:] == 255).all())
check("hook_words falls back to title", hook_intro.hook_words({"title_en": "Why you cannot focus at night anymore"}) == "WHY YOU CANNOT FOCUS AT NIGHT")
check("white flash removed from render loop", "white-flash intro" not in (ROOT / "bot.py").read_text() and "np.full((H, W, 3), 255" not in (ROOT / "bot.py").read_text())

# 8. script prompt + AI flag
check("share-bait rules exist and are kind", "send-this" in virality.SHARE_RULES and "Never guilt" in virality.SHARE_RULES)
src = (ROOT / "bot.py").read_text()
check("short script prompt carries hook_text + SHARE_RULES + topic directive", '"hook_text"' in src and "{virality.SHARE_RULES}" in src and "DIRECTIVE[0]" in src)
check("YouTube upload sets AI/synthetic label", '"containsSyntheticMedia": bool(synthetic)' in (ROOT / "publisher.py").read_text() and "synthetic=True" in (ROOT / "publisher.py").read_text())
check("topic rotation only recorded after a good build", src.count("topics.record(PLAN)") == 1 and src.index("topics.record(PLAN)") > src.index("topic tabhi 'done'"))
check("planner failure falls back, never stops the build", "old alternate-day mode" in src)
print(f"\nALL {n} ROUND-5a CHECKS PASSED")
