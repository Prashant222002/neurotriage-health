"""ROUND 3 TEST - research engine, script lock + handoff memory, logo, no top bar, short-only default / long on demand.
No network, no API keys. Run: python tests/test_round3.py"""
import json, os, shutil, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
for k in list(os.environ):
    if any(h in k for h in ("GROQ", "GEMINI", "ELEVEN", "UNLOCK", "APPROVE", "VIDEO_TYPE", "FORCE_LONG", "AUTO_LONG", "LOGO")):
        del os.environ[k]
os.environ.update(GROQ_API_KEY="x", QUEUE_MODE="on", RENDER_PRESET="ultrafast", LONG_FPS="8", LONG_PRESET="ultrafast", PRIVACY="public",
                  QUEUE_MANIFEST_DIR=str(tmp / "queue"), CAPTION_STYLE="box", QUEUE_LOCAL_DIR=str(tmp / "artifacts"), MUSIC="off")
import numpy as np
import project_state as ps, research, brand_logo
n = 0
def check(name, cond):
    global n
    print(("PASS " if cond else "FAIL ") + name); n += 1
    assert cond, name

def S(*texts):
    return {"title": "T", "scenes": [{"text": t, "text_en": t + " en", "queries": ["x"]} for t in texts]}

# =============================================================== 1. SCRIPT LOCK
live, arch = tmp / "live", tmp / "arch"
st = ps.ProjectState("2026-11-02", "short", live, arch, log=lambda *a: None)
a = S("hook line one", "second line", "third line")
check("not locked at start", not st.locked)
got = st.lock_script(a, source="gemini")
check("first script is locked as v1", st.locked and st.d["script"]["version"] == 1 and got["scenes"][0]["text"] == "hook line one")
b = S("TOTALLY different hook", "other", "stuff")
got = st.lock_script(b, source="groq")
check("a different script from another AI is IGNORED, locked one returned", got["scenes"][0]["text"] == "hook line one"
      and st.d["script"]["version"] == 1)
check("ignored script is kept as a pending proposal (not applied)", len(st.d["pending"]) == 1 and st.d["pending"][0]["source"] == "groq")
check("same script again is a no-op", st.lock_script(a)["scenes"][1]["text"] == "second line" and len(st.d["pending"]) == 1)
check("verify() true for the approved text", st.verify(a["scenes"]))
check("verify() true when CTA scene is appended after", st.verify(a["scenes"] + [{"text": "cta", "text_en": "cta"}]))
check("verify() false if a scene changed", not st.verify([dict(a["scenes"][0], text="edited")] + a["scenes"][1:]))
# persistence = resume after a killed run
st2 = ps.ProjectState("2026-11-02", "short", live, arch, log=lambda *a: None)
check("state survives a restart (live cache)", st2.locked and st2.d["script"]["hash"] == st.d["script"]["hash"])
shutil.rmtree(live)
st3 = ps.ProjectState("2026-11-02", "short", live, arch, log=lambda *a: None)
check("state also restored from the committed archive copy", st3.locked)
check("another day / kind does not inherit the lock",
      not ps.ProjectState("2026-11-03", "short", live, arch).locked and not ps.ProjectState("2026-11-02", "long", live, arch).locked)
# owner permission
os.environ["UNLOCK_SCRIPT"] = "1"
got = st3.lock_script(b, source="owner-rerun")
del os.environ["UNLOCK_SCRIPT"]
check("UNLOCK_SCRIPT=1 (owner) -> new script v2, old one archived in history",
      got["scenes"][0]["text"] == "TOTALLY different hook" and st3.d["script"]["version"] == 2
      and st3.d["script"]["history"][0]["version"] == 1)
st3.propose_change(S("proposal a", "b", "c"), "better hook", "gemini")
check("propose_change does not change the locked script", st3.locked_script()["scenes"][0]["text"] == "TOTALLY different hook")
ap = st3.approve_pending()
check("approve_pending applies it as v3 and keeps history", ap["scenes"][0]["text"] == "proposal a" and st3.d["script"]["version"] == 3
      and len(st3.d["script"]["history"]) == 2 and st3.d["approved_changes"])
r = st3.restore(1)
check("restore(1) brings the first approved script back (as v4)", r["scenes"][0]["text"] == "hook line one" and st3.d["script"]["version"] == 4)

# =============================================================== 2. HANDOFF MEMORY
st = ps.ProjectState("2026-11-04", "short", tmp / "l2", tmp / "a2", log=lambda *a: None)
st.set_request(kind="short", mode="student")
st.set_research({"topic": "Sleep and memory", "verified": ["Sleep helps memory consolidation", "REM supports learning"], "sources": []})
st.stage_done("research", "gemini", "verified")
st.record_call("research", "gemini", "gemini-x", "GEMINI_API_KEY_2", "topic chosen")
st.lock_script(S("one", "two"), source="gemini")
hb = st.handoff_block("voice")
check("handoff names the FINAL topic + verified facts", "Sleep and memory" in hb and "Sleep helps memory consolidation" in hb)
check("handoff says script is LOCKED and must not be rewritten", "SCRIPT LOCKED v1" in hb and "MUST NOT rewrite" in hb)
check("handoff tells the next AI what the previous AI did", "previous AI: gemini gemini-x" in hb and "completed stages: research(gemini)" in hb)
check("handoff has only key LABELS, never key values", "GEMINI_API_KEY_2" not in hb and "sk-" not in hb)
check("handoff is bounded in size", len(hb) <= 1900)
check("last_provider tracked", st.last_provider() == "gemini")

import bot
sent = []
def fake_inner(prompt, search=False, json_mode=False, image=None):
    sent.append(prompt); bot.LAST_CALL.update(provider="groq", model="m1", key="GROQ_API_KEY"); return "answer text"
bot._ask_inner = fake_inner
ps._CUR["state"] = None
bot.ask("plain prompt")
check("no state active -> prompt untouched", sent[-1] == "plain prompt")
ps._CUR["state"] = st
out = bot.ask("write captions", task="packaging")
check("state active -> prompt carries the project-state block", sent[-1].startswith("[PROJECT STATE") and sent[-1].endswith("write captions"))
check("answering provider recorded in memory", st.d["handoff"][-1]["provider"] == "groq" and st.d["handoff"][-1]["stage"] == "packaging")
bot.ask("look", image=b"jpgbytes")
check("vision calls skip the block", sent[-1] == "look")
check("next provider (gemini after groq switch) would again see groq's work", "previous AI: groq m1" in st.handoff_block("x"))
ps._CUR["state"] = None

# =============================================================== 3. RESEARCH ENGINE
EV_PUBMED_XML = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>111</PMID><Article><ArticleTitle>Sleep loss and memory</ArticleTitle>
<Abstract><AbstractText>Sleep deprivation raised cortisol by 21% and reduced recall in students.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""
def http_ok(url, params=None, timeout=15):
    if "esearch" in url: return json.dumps({"esearchresult": {"idlist": ["111"]}})
    if "efetch" in url: return EV_PUBMED_XML
    if params and params.get("action") == "opensearch": return json.dumps(["q", ["Sleep"], [], []])
    return json.dumps({"query": {"pages": {"1": {"title": "Sleep", "extract": "Sleep is a naturally recurring state of mind and body."}}}})
def http_down(url, params=None, timeout=15): raise RuntimeError("no internet")

CLAIMS = ["Sleep deprivation raised cortisol by 21% in students.", "Sleeping 4 hours makes you 73% smarter.",
          "Sleep loss reduces recall.", "Sleep is a natural recurring state.", "Cold showers cure depression."]
def make_ask(verdicts):
    def ask(prompt, search=False, json_mode=False, image=None):
        if "extract a structured fact sheet" in prompt:
            return json.dumps({"topic": "Sleep and memory", "search_terms": ["sleep deprivation cortisol students"], "claims": CLAIMS,
                               "hook": "Tune ka sach", "tip": "Sleep 7-8 hours", "structure": "hook-fact-fact-tip"})
        if "strict fact-checker" in prompt:
            return json.dumps({"results": verdicts})
        return "TOPIC: x"
    return ask
V = [{"i": 0, "verdict": "supported", "cites": [0]},
     {"i": 1, "verdict": "supported", "cites": [0]},                  # LLM LIES: 73% is nowhere in the evidence
     {"i": 2, "verdict": "supported", "cites": [0]},
     {"i": 3, "verdict": "supported", "cites": [1]},
     {"i": 4, "verdict": "unsupported", "cites": []}]
rec = research.run(make_ask(V), [], "student", "SAFE", brief_fn=lambda *a: "BRIEF", http_get=http_ok, log=lambda *a: None)
vt = " | ".join(rec["verified"])
check("level verified, PubMed + Wikipedia evidence used", rec["level"] == "verified" and len(rec["sources"]) >= 1)
check("supported + number present in evidence (21%) is kept", "21%" in vt)
check("HARD FILTER: LLM said 'supported' but 73% is not in evidence -> dropped", "73%" not in vt and any("number not in cited" in d[1] for d in rec["dropped"]))
check("unsupported claim dropped", "Cold showers" not in vt)
check("sources are real PubMed/Wikipedia URLs", all(s["url"].startswith("https://") for s in rec["sources"]) and any("pubmed" in s["url"] for s in rec["sources"]))
check("fact sheet text tells the writer to use only verified facts", "VERIFIED FACTS" in rec["facts_text"] and "RESEARCH LEVEL: verified" in rec["facts_text"]
      and "73%" not in rec["facts_text"])
rec2 = research.run(make_ask(V), [], "student", "SAFE", brief_fn=lambda *a: "BRIEF", http_get=http_down, log=lambda *a: None)
check("no internet -> NOT a crash: level llm_only, claims with numbers stripped", rec2["level"] == "llm_only"
      and all(not research._numbers(f) for f in rec2["verified"]) and len(rec2["verified"]) >= 3)
check("number_supported edge cases", research.number_supported("no numbers here", []) and research.number_supported("21% rise", ["rose 21%"])
      and not research.number_supported("21% rise", ["rose 12%"]) and not research.number_supported("2 hours", ["12 hours"]))
rec3 = research.run(lambda *a, **k: None, [], "student", "SAFE", brief_fn=lambda *a: None, http_get=http_ok, log=lambda *a: None)
check("AI completely down -> None (bot falls back to its old path)", rec3 is None)
rec4 = research.run(lambda p, **k: "just text, no json", [], "student", "SAFE", brief_fn=lambda *a: "BRIEF TEXT", http_get=http_ok, log=lambda *a: None)
check("AI returns non-JSON -> old plain fact sheet kept", rec4["level"] == "unstructured" and rec4["facts_text"] == "BRIEF TEXT")

# ---- 3b. real bot.research() wiring: engine -> project memory -> fact sheet -> description sources
import virality
real_research = bot.research
research.default_http_get = http_ok
virality.viral_brief = lambda ask, done, mode, safety, yt_key=None: "BRIEF"
bot._ask_inner = lambda prompt, search=False, json_mode=False, image=None: (bot.LAST_CALL.update(provider="gemini", model="g", key="GEMINI_API_KEY") or make_ask(V)(prompt))
rs = ps.begin("2026-12-01", "research", live_dir=tmp / "l3", archive_dir=tmp / "a3", log=lambda *a: None)
bot.RS["state"] = rs
facts = real_research([], "student")
check("bot.research returns the VERIFIED fact sheet", "VERIFIED FACTS" in facts and "73%" not in facts and "21%" in facts)
rr = rs.d["research"]
check("research stored in project memory (topic, verified, level, sources, dropped)", rr["topic"] == "Sleep and memory" and rr["level"] == "verified"
      and rr["sources"] and rr["dropped"])
check("research stage recorded with the provider that did it", rs.d["stages"]["research"]["provider"] == "gemini")
check("description gets a Sources: line with real URLs", bot._sources_line().startswith("Sources: https://"))
bot.RS["state"] = None; ps.end()

# =============================================================== 4. LOGO
from PIL import Image
d = tmp / "assets"; d.mkdir()
check("missing logo -> gate says no", not brand_logo.gate(d / "logo.png")[0])
Image.new("RGB", (100, 100), (200, 0, 0)).save(d / "logo.png")
check("too small logo rejected", "too small" in brand_logo.gate(d / "logo.png")[1])
Image.new("RGB", (600, 200), (200, 0, 0)).save(d / "logo.png")
check("non-square logo rejected", "not square" in brand_logo.gate(d / "logo.png")[1])
Image.new("RGB", (400, 400), (10, 10, 10)).save(d / "logo.png")
check("blank logo rejected", "blank" in brand_logo.gate(d / "logo.png")[1])
check("real logo passes the gate", brand_logo.gate(ROOT / "assets" / "logo.png")[0])
arr = brand_logo.circle(ROOT / "assets" / "logo.png", 100)
pad = brand_logo.pad_of(100)
check("circle: square corners are NOT logo (only faint shadow), centre opaque", arr[pad + 2, pad + 2, 3] < 40 and arr[pad + 50, pad + 50, 3] == 255)
check("circle: edge midpoints inside (ring visible)", arr[pad + 50, pad + 4, 3] > 200)
check("logo cached", brand_logo.load(76, ROOT / "assets") is brand_logo.load(76, ROOT / "assets"))
os.environ["LOGO"] = "off"; check("LOGO=off -> None", brand_logo.load(60, ROOT / "assets") is None); del os.environ["LOGO"]
check("fade: hidden in the hook, visible later, never above 82%", brand_logo.fade(0.5) == 0 and 0.8 < brand_logo.fade(5) <= 0.82)

# =============================================================== 5. SHORT HUD: logo yes, top loading bar no
bot.ASSETS = ROOT / "assets"
hud = bot.HUD("BRAIN", [], 45.0)
f0 = np.zeros((bot.H, bot.W, 3), np.uint8); hud.draw(f0, 8.0)
check("NO loading bar: rows 40-80 (where it used to be) stay black", int(f0[40:80].max()) == 0)
check("logo drawn top-right after the hook", int(f0[100:230, bot.W - 160:].max()) > 60)
f1 = np.zeros_like(f0); hud.draw(f1, 0.5)
check("logo not drawn during the first second", int(f1[100:230, bot.W - 160:].max()) == 0)
f2 = np.zeros_like(f0); hud.draw(f2, 20.0); f3 = np.zeros_like(f0); hud.draw(f3, 40.0)
check("nothing moves along the top as time passes (bar gone)", int(f2[40:80].max()) == 0 and int(f3[40:80].max()) == 0)
import long_render
lh = long_render.LongHUD("NeuroTriage", ["a", "b"], 300.0, ROOT / "assets")
lf = np.zeros((long_render.H, long_render.W, 3), np.uint8); lh.draw(lf, 100.0, 1, 0.0, [0, 150])
check("long video: no bottom progress bar / ticks either", int(lf[long_render.H - 40:].max()) == 0)
th = tmp / "t.jpg"; long_render.make_thumbnail(["list", "input"], th, "NeuroTriage", None)
check("thumbnail still builds with the logo (list input too)", th.exists() and th.stat().st_size > 1000)

# =============================================================== 6. PLAN: short only unless asked
import publisher
from datetime import date
os.environ["CYCLE_START"] = "2026-11-01"
day7 = date(2026, 11, 7)
check("default: day 7 is a SHORT only now", publisher.today_plan(day7)["long"] is False)
os.environ["AUTO_LONG"] = "on"; check("AUTO_LONG=on brings back day-7 long", publisher.today_plan(day7)["long"] is True); del os.environ["AUTO_LONG"]
os.environ["FORCE_LONG"] = "1"; check("FORCE_LONG=1 any day", publisher.today_plan(date(2026, 11, 3))["long"] is True); del os.environ["FORCE_LONG"]
y = open(ROOT / ".github/workflows/build.yml").read()
check("workflow: publish_when / publish_time_ist / unlock_script inputs exist (build.yml and build_long.yml)",
      all(k in y and k in open(ROOT / ".github/workflows/build_long.yml").read() for k in ("publish_when:", "publish_time_ist:", "unlock_script:")))
check("workflow: publish_when=now -> queue off + public", "publish_when == 'now' && 'off' || 'on'" in y and "publish_when == 'now' && 'public' || 'private'" in y)
check("workflow: state/ committed as audit trail", "git add topics_done.txt queue/ state/" in y)

# =============================================================== 7. END-TO-END: short only / long only / lock across a retry
import virality, scheduler, publish_due, ckpt
bot.ROOT = tmp
bot.WORK, bot.OUT = tmp / "work", tmp / "output"
ckpt.DIR = tmp / "work" / "ckpt"
ps.LIVE_DIR, ps.ARCHIVE_DIR = tmp / "work" / "ckpt" / "state", tmp / "state"
publish_due.WORK = tmp / "work" / "queue"
bot.HISTORY = tmp / "topics_done.txt"
SR = bot.SR
spoken = []
def fake_voice(scenes, max_total=52.0, **kw):
    spoken.append([s["text"] for s in scenes]); res = []
    for sc in scenes:
        ws = sc["text"].split(); dd = 0.9 + 0.12 * len(ws); t = np.arange(int(dd * SR)) / SR
        res.append(((0.2 * np.sin(2 * np.pi * 180 * t)).astype(np.float32), dd, [(w, i * dd / len(ws), (i + 1) * dd / len(ws)) for i, w in enumerate(ws)]))
    return res, "FAKE", "hinglish"
class FakeSplash:
    def __init__(self, p): pass
    def frame(self, t): return np.full((bot.H, bot.W, 3), 250, np.uint8)
def sc(text, ch=None, emph=""):
    d = {"text": text, "text_en": text, "queries": ["x"], "emphasis": emph}
    if ch: d["chapter"] = ch
    return d
gen = {"n": 0}
def write_script(facts):
    gen["n"] += 1
    return {"title": "T", "title_en": "Test topic", "kicker": "Brain", "hashtags": ["#a", "#b"], "description": "d",
            "scenes": [sc(f"Version {gen['n']} dimaag ka hook", emph="HOOK"), sc("Doosra scene yahan hai"), sc("Ye hai fix")]}
bot.discover_models = lambda: []; bot.pick_mode = lambda: "student"
bot.research = lambda done, mode: "FACTS"
bot.write_script = write_script
virality.improve_script = lambda ask, d, safety: d
virality.packaging = lambda ask, d, mode, long=False: {"title": "Viral title", "hashtags": ["#x"], "yt_description": "desc", "ig_caption": "cap",
        "thumb_text": "Dopamine ka sach", "keyword": "k", "first_comment": "c", "titles": ["a"]}
virality.long_script = lambda ask, facts, safety, target_minutes=7: {"title": "Long T", "chapters": [{"name": "Hook"}, {"name": "Fix"}],
        "scenes": [sc("Pehle hook sunlo dhyan se", 1, "HOOK"), sc("Reward system ka kaam", 2), sc("Dusra scene yahan", 2), sc("Ab fix ka time hai", 2)]}
bot.make_voice = fake_voice; bot.pick_clips = lambda *a, **k: []; bot.pick_clips_batch = lambda items, *a, **k: [[] for _ in items]; bot.Splash = FakeSplash
(bot.ASSETS / "neurotriage_splash.json").exists() or (bot.ASSETS / "neurotriage_splash.json").write_text("{}")
yt_calls = []
publisher.youtube = lambda video, title, desc, tags, privacy="private", thumb=None, category="27", publish_at=None: (yt_calls.append((Path(video).name, privacy, publish_at)) or {"ok": True, "id": "YT", "scheduled": publish_at is not None})
publisher.facebook_reel = lambda video, d, publish_at=None: {"ok": True, "id": "FB", "scheduled": True}
publisher.instagram_reel = lambda video, caption: {"ok": True, "id": "IG"}
key = scheduler.now_ist().date().isoformat()
def manifests(): return sorted(p.stem for p in (tmp / "queue").glob("*.json"))

bot.VIDEO_TYPE = "short"; bot.main()
check("automatic run (video_type=short): ONLY the short was built", manifests() == [f"{key}-short"])
stf = json.loads((tmp / "state" / f"{key}_short.json").read_text())
check("project memory written + script locked v1", stf["script"]["locked"] and stf["script"]["version"] == 1 and "script" in stf["stages"])
check("shared research memory file exists next to the short/long ones", (tmp / "state" / f"{key}_research.json").exists())
# simulate a killed run: script checkpoint lost, AI would now write a DIFFERENT script
for p in ckpt.DIR.glob(f"{key}_short_*.pkl"): p.unlink()
before = gen["n"]; spoken.clear()
bot.FORCE_REBUILD = True; bot.QUEUE_MODE = False
bot.main()
check("retry after lost checkpoint: NO new script was generated (lock reused)", gen["n"] == before)
check("retry narrates the ORIGINAL approved script", spoken and spoken[0][0] == "Version 1 dimaag ka hook")
bot.FORCE_REBUILD = False; bot.QUEUE_MODE = True
# on-demand long, no short
shutil.rmtree(tmp / "queue"); (tmp / "queue").mkdir()
bot.VIDEO_TYPE = "long"; bot.main()
check("video_type=long: ONLY the long video was built (no short)", manifests() == [f"{key}-long"])
lg = json.loads((tmp / "queue" / f"{key}-long.json").read_text())
check("long manifest has a future publish time and a thumbnail", lg["files"].get("thumb") and lg["platforms"]["youtube"]["status"] in ("scheduled", "pending"))
# publish now: queue off -> immediate upload, public
yt_calls.clear(); shutil.rmtree(tmp / "queue"); (tmp / "queue").mkdir()
bot.VIDEO_TYPE = "long"; bot.QUEUE_MODE = False; bot.FORCE_REBUILD = True; bot.PRIVACY = "public"; bot.main()
check("publish_now: long video uploaded immediately as public, no publishAt", yt_calls and yt_calls[-1][1] == "public" and yt_calls[-1][2] is None)
print(f"\nALL {n} ROUND-3 CHECKS PASSED")
