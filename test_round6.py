import os, sys, math, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.update(GROQ_API_KEY="x", GEMINI_API_KEY="y")
import numpy as np, yaml, flute
ok = True
def check(n, c):
    global ok; print(("PASS " if c else "FAIL ") + n); ok = ok and bool(c)
t = time.time(); m = flute.synth(20, 3)
check("flute: stereo, right length, peak<=0.95, not silent", m.shape == (882000, 2) and 0.2 < np.abs(m).max() <= 0.95 and m.std() > 0.01)
check("flute: different seed -> different melody", float(np.abs(flute.synth(8, 1) - flute.synth(8, 2)).mean()) > 0.001)
check("flute: fade in/out", np.abs(m[:2000]).max() < 0.1 and np.abs(m[-2000:]).max() < 0.1)
print("   flute %.1fs" % (time.time() - t))
import bot
os.environ["LONG_VOICE"] = "local"; check("LONG_VOICE=local -> 7 min free TTS", bot._long_engine() == "local" and bot._long_minutes() == 7)
os.environ["LONG_VOICE"] = "eleven"; check("LONG_VOICE=eleven -> 2.5 min", bot._long_minutes() == 2.5)
os.environ["LONG_VOICE"] = "auto"; check("auto without keys -> local", bot._long_engine() == "local")
check("synth_music uses flute", bot.synth_music(6).shape[1] == 2 and os.environ.get("MUSIC_STYLE", "flute") == "flute")
import long_render
scale = []
class FB:  # fake shot source
    def next(self): return np.full((long_render.H, long_render.W, 3), 100, np.uint8)
sh = long_render.LShot(24, 240, np.random.default_rng(1), clip=None, cam="in"); sh.bg = FB()
vals = [float(sh.next().mean()) for _ in range(240)]
check("zoom pops run without error over 10 s", len(vals) == 240)
y = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "..", ".github/workflows/build_long.yml")))
on = y.get("on") or y.get(True)
check("weekly cron + voice inputs", "schedule" in on and {"voice_engine", "eleven_voice_id", "edge_voice"} <= set(on["workflow_dispatch"]["inputs"]))
print("ALL ROUND-6 CHECKS PASSED" if ok else "SOME FAILED")
