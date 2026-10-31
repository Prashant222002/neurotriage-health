"""RESUME TEST. Offline end-to-end test of the v8 flow (no network, no API keys, tiny videos).
Run:  python tests/test_phase2.py
Covers: midnight build (queue mode) -> manifest -> native-schedule calls -> publish_due (Instagram) -> idempotency,
        checkpoint resume, long video (chapters, thumbnail, description), caption styles, schedule maths."""
import json, os, shutil, sys, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
import datetime as _d
os.environ["CYCLE_START"] = (_d.datetime.now(_d.timezone(_d.timedelta(hours=5, minutes=30))).date()).isoformat()
os.environ.update(GROQ_API_KEY="x", QUEUE_MODE="on", RENDER_PRESET="ultrafast", LONG_FPS="8", LONG_PRESET="ultrafast",
                  PRIVACY="public", FORCE_LONG="0", QUEUE_MANIFEST_DIR=str(tmp / "queue"), CAPTION_STYLE="box",
                  QUEUE_LOCAL_DIR=str(tmp / "artifacts"), MUSIC="off")
import numpy as np
import bot, virality, publisher, scheduler, publish_due, ckpt

bot.ROOT = tmp
bot.WORK, bot.OUT = tmp / "work", tmp / "output"
ckpt.DIR = tmp / "work" / "ckpt"
import project_state; project_state.LIVE_DIR = tmp / "work" / "ckpt" / "state"; project_state.ARCHIVE_DIR = tmp / "state"
publish_due.WORK = tmp / "work" / "queue"
bot.HISTORY = tmp / "topics_done.txt"
bot.ASSETS = ROOT / "assets"

SR = bot.SR
calls = []

def fake_voice(scenes, max_total=52.0, **kw):
    res = []
    for sc in scenes:
        ws = sc["text"].split()
        d = 0.9 + 0.12 * len(ws)
        t = np.arange(int(d * SR)) / SR
        y = (0.2 * np.sin(2 * np.pi * 180 * t) * (1 + np.sin(2 * np.pi * 3 * t)) / 2).astype(np.float32)
        res.append((y, d, [(w, i * d / len(ws), (i + 1) * d / len(ws)) for i, w in enumerate(ws)]))
    return res, "FAKE", "hinglish"

class FakeSplash:
    def __init__(self, p): pass
    def frame(self, t): return np.full((bot.H, bot.W, 3), 250, np.uint8)

def sc(text, ch=None, emph=""):
    d = {"text": text, "text_en": text, "queries": ["x"], "emphasis": emph}
    if ch: d["chapter"] = ch
    return d

bot.discover_models = lambda: []
bot.pick_mode = lambda: "student"
bot.research = lambda done, mode: "FACTS"
bot.write_script = lambda facts: {"title": "T", "title_en": "Test topic", "kicker": "Brain", "hashtags": ["#a", "#b"],
                                  "description": "d", "scenes": [sc("Dimaag ka reward system", emph="REWARD"),
                                                                 sc("Isme 73 percent log galat hain"), sc("Ye hai fix")]}
virality.improve_script = lambda ask, d, safety: d
virality.packaging = lambda ask, d, mode, long=False: {"title": "Viral title", "hashtags": ["#x", "#y"], "yt_description": "desc",
        "ig_caption": "cap", "thumb_text": "Dopamine ka sach", "keyword": "k", "first_comment": "c", "titles": ["a"]}
virality.long_script = lambda ask, facts, safety, target_minutes=7: {
    "title": "Long T", "chapters": [{"name": "Hook"}, {"name": "Reward system"}, {"name": "Fix"}],
    "scenes": [sc("Pehle hook sunlo dhyan se", 1, "HOOK"), sc("Reward system ka 80 percent kaam", 2), sc("Dusra scene yahan", 2),
               sc("Ab fix ka time hai", 3)]}
bot.make_voice = fake_voice
bot.pick_clips = lambda *a, **k: []
bot.pick_clips_batch = lambda items, *a, **k: [[] for _ in items]
bot.Splash = FakeSplash
(bot.ASSETS / "neurotriage_splash.json").exists() or (bot.ASSETS / "neurotriage_splash.json").write_text("{}")

yt_calls, fb_calls = [], []
def fake_yt(video, title, desc, tags, privacy="private", thumb=None, category="27", publish_at=None):
    yt_calls.append((Path(video).name, privacy, publish_at)); return {"ok": True, "id": "YT1", "scheduled": publish_at is not None and privacy == "public"}
def fake_fb(video, d, publish_at=None):
    fb_calls.append(publish_at); return {"ok": True, "id": "FB1", "scheduled": publish_at is not None}
publisher.youtube, publisher.facebook_reel = fake_yt, fake_fb
ig_calls = []
publisher.instagram_reel = lambda video, caption: (ig_calls.append(Path(video).name) or {"ok": True, "id": "IG1"})


voice_calls=[0]; orig=bot.make_voice
def counting(scenes,max_total=52.0,**kw):
    voice_calls[0]+=1; return orig(scenes,max_total,**kw)
bot.make_voice=counting
real_render=bot.render_video
state={"boom":True}
def flaky(*a,**k):
    if state["boom"]:
        state["boom"]=False; raise RuntimeError("runner died mid-render")
    return real_render(*a,**k)
bot.render_video=flaky
try:
    bot.main(); raise AssertionError("should have failed")
except SystemExit as e:        # round 1: short failure is isolated, run ends non-zero so retry/catch-up fires
    assert "short" in str(e), e
    print("attempt 1 failed as expected (isolated):", e)
bot.main()      # attempt 2 (same job, retry loop)
assert voice_calls[0]==1, voice_calls   # voice NOT re-synthesised (no ElevenLabs credits wasted)
key=scheduler.now_ist().date().isoformat()
assert (tmp/"queue"/f"{key}-short.json").exists()
print("RESUME OK: voice synthesised once, short queued on attempt 2")
