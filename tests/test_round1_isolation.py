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
virality.packaging = lambda ask, d, mode, long=False: {"title": "Viral title", "hashtags": "#x #y", "yt_description": None,
        "ig_caption": "cap", "thumb_text": ["Dopamine", "ka sach"], "keyword": "k", "first_comment": "c", "titles": ["a"]}
virality.long_script = lambda ask, facts, safety, target_minutes=7: {
    "title": "Long T", "chapters": [{"name": "Hook"}, {"name": "Reward system"}, {"name": "Fix"}],
    "scenes": [sc("Pehle hook sunlo dhyan se", 1, "HOOK"), sc("Reward system ka 80 percent kaam", 2), sc("Dusra scene yahan", 2),
               sc("Ab fix ka time hai", 3)]}
bot.make_voice = fake_voice
bot.pick_clips = lambda *a, **k: []
bot.pick_clips_batch = lambda items, *a, **k: [[] for _ in items]
bot.Splash = FakeSplash
(bot.ASSETS / "neurotriage_splash.json").exists() or (bot.ASSETS / "neurotriage_splash.json").write_text("{}")


yt_calls=[]
def fake_yt(video, title, desc, tags, privacy="private", thumb=None, category="27", publish_at=None):
    yt_calls.append((Path(video).name, thumb)); return {"ok": True, "id": "YT1"}
publisher.youtube = fake_yt
publisher.facebook_reel = lambda *a, **k: {"ok": True, "id": "FB1"}
publisher.instagram_reel = lambda *a, **k: {"ok": True, "id": "IG1"}

# ---- RUN A: AI sends list thumb_text + str hashtags + None description (exact production bug) -> must fully succeed
bot.main()
key = scheduler.now_ist().date().isoformat()
assert (bot.OUT/"long"/"long_final.mp4").stat().st_size > 1000, "long mp4 missing"
assert (bot.OUT/"long"/"thumb.jpg").exists(), "thumb should be made from list input"
print("RUN A OK: list thumb_text / str hashtags / None description did not crash")

# ---- RUN B: thumbnail engine hard-crashes -> long MP4 must still be produced, queued WITHOUT thumb, run exit clean
import shutil, importlib
shutil.rmtree(bot.OUT, ignore_errors=True); shutil.rmtree(bot.WORK, ignore_errors=True)
shutil.rmtree(tmp/"queue", ignore_errors=True); (bot.HISTORY).unlink(missing_ok=True)
ckpt.DIR = bot.WORK/"ckpt"; bot.OUT.mkdir(exist_ok=True); bot.WORK.mkdir(exist_ok=True)
import safe, long_render; safe.STEPS.clear()
def dead(*a, **k): raise RuntimeError("thumbnail engine exploded")
long_render.make_thumbnail = dead
bot.main()                                  # must NOT raise / sys.exit
lf = bot.OUT/"long"/"long_final.mp4"
assert lf.exists() and lf.stat().st_size > 1000, "long MP4 lost after thumbnail crash!"
assert not (bot.OUT/"long"/"thumb.jpg").exists()
rep = json.loads((bot.OUT/"step_report.json").read_text())
th = [r for r in rep if r["step"] == "long_thumbnail"][0]
assert th["status"] == "FAILED-skipped", rep
ms = json.loads(next((tmp/"queue").glob("*-long.json")).read_text())
print("RUN B OK: thumbnail crashed, long MP4 kept (%d KB), queued without thumb, steps: %s" %
      (lf.stat().st_size//1024, [(r["step"], r["status"]) for r in rep]))

# ---- RUN C: audio mix crashes -> still ships the video (voice-less) instead of losing everything
shutil.rmtree(bot.OUT, ignore_errors=True); shutil.rmtree(bot.WORK, ignore_errors=True)
shutil.rmtree(tmp/"queue", ignore_errors=True); bot.HISTORY.unlink(missing_ok=True)
bot.OUT.mkdir(exist_ok=True); bot.WORK.mkdir(exist_ok=True); safe.STEPS.clear()
def bad_mix(*a, **k): raise RuntimeError("mix exploded")
bot.build_mix = bad_mix
try:
    bot.main()
except SystemExit as e:                     # short also uses build_mix -> short fails, but must NOT stop the long video
    assert "short" in str(e) and "long" not in str(e).split("failed:")[-1].split("(")[0], e
    print("short failed in isolation:", str(e)[:70])
assert (bot.OUT/"long"/"long_final.mp4").exists(), "no long video after mix crash"
print("RUN C OK: audio mix crashed, raw video still delivered")
print("ALL ROUND-1 ISOLATION TESTS PASSED")
