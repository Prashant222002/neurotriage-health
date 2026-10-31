"""Offline end-to-end test of the v8 flow (no network, no API keys, tiny videos).
Run:  python tests/test_phase2.py
Covers: midnight build (queue mode) -> manifest -> native-schedule calls -> publish_due (Instagram) -> idempotency,
        checkpoint resume, long video (chapters, thumbnail, description), caption styles, schedule maths."""
import json, os, shutil, sys, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ.update(GROQ_API_KEY="x", QUEUE_MODE="on", RENDER_PRESET="ultrafast", LONG_FPS="8", LONG_PRESET="ultrafast",
                  PRIVACY="public", FORCE_LONG="1", QUEUE_MANIFEST_DIR=str(tmp / "queue"), CAPTION_STYLE="box",
                  QUEUE_LOCAL_DIR=str(tmp / "artifacts"), MUSIC="off")
import numpy as np
import bot, virality, publisher, scheduler, publish_due, ckpt

bot.ROOT = tmp
bot.WORK, bot.OUT = tmp / "work", tmp / "output"
ckpt.DIR = tmp / "work" / "ckpt"
publish_due.WORK = tmp / "work" / "queue"
bot.HISTORY = tmp / "topics_done.txt"
bot.ASSETS = ROOT / "assets"

SR = bot.SR
calls = []

def fake_voice(scenes, max_total=52.0):
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

# ---- 1. midnight build
bot.main()
key = scheduler.now_ist().date().isoformat()
ms = {p.stem: json.loads(p.read_text()) for p in (tmp / "queue").glob("*.json")}
print("manifests:", list(ms))
assert f"{key}-short" in ms and f"{key}-long" in ms
s = ms[f"{key}-short"]
assert s["platforms"]["youtube"]["status"] == "scheduled", s["platforms"]
assert s["platforms"]["facebook"]["status"] == "scheduled"
assert s["platforms"]["instagram"]["status"] == "pending"
assert yt_calls and yt_calls[0][1] == "public" and yt_calls[0][2] is not None   # publishAt passed
assert fb_calls[0] is not None
pa = datetime.fromisoformat(s["publish_at"]); assert pa.tzinfo and pa > scheduler.now_ist()
lg = ms[f"{key}-long"]; assert "Chapters:" in lg["meta"]["yt_description"] and "00:00 Hook" in lg["meta"]["yt_description"]
for f in ("short/final_reel.mp4", "long/long_final.mp4", "long/thumb.jpg"):
    assert (bot.OUT / "queue" / key / f).stat().st_size > 1000, f
print("build OK. long desc:\n", lg["meta"]["yt_description"][:200])

# ---- 2. idempotent re-run (catch-up cron) does nothing
n = len(yt_calls); bot.main(); assert len(yt_calls) == n; print("idempotent OK")

# ---- 3. publish_due before the time -> nothing
shutil.copytree(bot.OUT / "queue" / key / "short", tmp / "artifacts" / f"queue-{key}-short")
assert publish_due.run(now=datetime.now(timezone.utc)) == 0 and not ig_calls
# ---- 4. at publish time -> Instagram posted, manifest completes, YouTube/FB not re-posted
later = datetime.fromisoformat(s["publish_at_utc"]) + timedelta(minutes=5)
publish_due.run(now=later)
assert ig_calls == ["final_reel.mp4"], ig_calls
s2 = json.loads((tmp / "queue" / f"{key}-short.json").read_text())
assert s2["status"] == "complete" and s2["platforms"]["instagram"]["status"] == "done"
assert len(yt_calls) == n
publish_due.run(now=later); assert ig_calls == ["final_reel.mp4"]
print("publish_due OK (instagram once, idempotent)")

# ---- 5. failure + retry accounting
m = scheduler.new_manifest("short", {"title": "t", "yt_description": "d", "hashtags": []}, {"video": "final_reel.mp4"},
                           scheduler.now_ist() - timedelta(minutes=1), "public", f"queue-{key}-short", ["instagram"])
m["id"] = "x-fail"; scheduler.save_manifest(m)
publisher.instagram_reel = lambda v, c: {"ok": False, "error": "boom"}
for _ in range(4): publish_due.run()
mf = json.loads((tmp / "queue" / "x-fail.json").read_text())
assert mf["platforms"]["instagram"]["attempts"] == 3 and mf["status"] == "complete", mf
print("retry cap OK")

# ---- 6. checkpoints exist for resume
assert list(ckpt.DIR.glob(f"{key}_short_voice.pkl")) and list(ckpt.DIR.glob(f"{key}_long_voice.pkl"))
print("ALL TESTS PASSED")
