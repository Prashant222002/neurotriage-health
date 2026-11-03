"""Round 15: own topic from the dashboard (MANUAL_TOPIC) never collides with the daily video."""
import os, subprocess, sys
from pathlib import Path
R = Path(__file__).parent.parent
def run(env, code):
    e = {**os.environ, "GROQ_API_KEY": "x", **env}
    return subprocess.run([sys.executable, "-c", code], cwd=R, env=e, capture_output=True, text=True, timeout=90).stdout.strip().splitlines()[-1]
# daily id unchanged
assert run({"MANUAL_TOPIC": "", "MANUAL_ID": ""}, "import scheduler;print(scheduler.item_id('short','2026-11-03' and __import__('datetime').date(2026,11,3)))") == "2026-11-03-short"
# manual id gets a unique suffix for both kinds
assert run({"MANUAL_TOPIC": "x", "MANUAL_ID": "m77"}, "import scheduler,datetime;print(scheduler.item_id('long',datetime.date(2026,11,3)))") == "2026-11-03-long-m77"
# manual plan: directive carries the topic, notes, and never a trend/rotation
out = run({"MANUAL_TOPIC": "Brain rot kya hai", "MANUAL_NOTES": "students", "MANUAL_ID": "m1"},
          "import bot;p=bot.manual_plan();print(p['kind'],p['mode'],'Brain rot kya hai' in p['directive'],'students' in p['directive'],bot.MANUAL_ID)")
assert out == "manual student True True m1", out
out = run({"MANUAL_TOPIC": "Panic attacks", "MANUAL_ID": ""}, "import bot;print(bot.manual_plan()['mode'],bot.MANUAL_ID)")
assert out == "awareness manual", out
print("round15 OK")
