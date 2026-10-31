import os, sys, json, importlib, tempfile, subprocess
from pathlib import Path
R = Path(__file__).parent.parent
sys.path.insert(0, str(R)); os.environ.update(GROQ_API_KEY="x", GEMINI_API_KEY="y")
import analytics, scheduler
ok = True
def check(n, c):
    global ok; print(("PASS " if c else "FAIL ") + n); ok = ok and bool(c)

def one_round(tag):
    print("--- error-test round", tag)
    rows = [{"hour": 20, "views": 900, "age_days": 3}] * 4 + [{"hour": 10, "views": 100, "age_days": 3}] * 4
    check("best hour moves 1h toward the winner (19 -> 20)", analytics.best_hour(rows, 19) == 20)
    check("never jumps more than 1h (10 -> 11)", analytics.best_hour(rows, 10) == 11)
    check("too little data -> unchanged", analytics.best_hour(rows[:2], 19) == 19)
    check("garbage rows -> no crash, unchanged", analytics.best_hour([{"x": 1}, None, "a"], 19) == 19)
    check("stays inside 07-22 window", 7 <= analytics.best_hour([{"hour": 23, "views": 9999, "age_days": 1}] * 9, 22) <= 22)
    tmp = Path(tempfile.mkdtemp()) / "best.json"; analytics.PATH = tmp
    check("missing file -> None", analytics.load_best("short") is None)
    tmp.write_text("{broken", encoding="utf-8"); check("corrupt file -> None, no crash", analytics.load_best("short") is None)
    tmp.write_text(json.dumps({"short": "25:99", "long": "20:00"})); check("invalid time ignored, valid kept", analytics.load_best("short") is None and analytics.load_best("long") == "20:00")
    res = analytics.run(log=lambda *a: None, fetch=lambda log: {"short": rows, "long": []})
    check("run() writes new slot", json.loads(tmp.read_text())["short"] in ("10:00", "11:00") and "updated" in res)
    check("run() survives fetch failure", isinstance(analytics.run(log=lambda *a: None, fetch=lambda log: 1 / 0), dict))
    tmp.write_text(json.dumps({"short": "12:00", "long": "20:00"}))
    os.environ.pop("PUBLISH_ASAP", None); os.environ["PUBLISH_TIME_SHORT_IST"] = "10:00"
    t = scheduler.schedule_for("short"); check("scheduler uses best-time file", (t.hour, t.minute) == (12, 0))
    os.environ["BEST_TIME"] = "off"; t = scheduler.schedule_for("short"); check("BEST_TIME=off -> env time", (t.hour, t.minute) == (10, 0)); os.environ.pop("BEST_TIME")
    os.environ["PUBLISH_ASAP"] = "1"; check("PUBLISH_ASAP still wins", scheduler.schedule_for("short") > scheduler.now_ist()); os.environ.pop("PUBLISH_ASAP")

for i in (1, 2):
    one_round(i)
D = R / "dashboard"
for f in ["index.html", "manifest.webmanifest", "sw.js", "icon.png", "vercel.json", "api/run.js", "api/status.js", "api/download.js", "api/upload.js", "api/_gh.js"]:
    check("dashboard/" + f + " exists", (D / f).exists())
for f in (D / "api").glob("*.js"):
    check(f.name + " syntax", subprocess.run(["node", "--check", str(f)]).returncode == 0)
src = (D / "api" / "run.js").read_text()
check("dashboard: only allow-listed workflows, password checked", "ALLOWED" in src and "auth(req, res)" in src and "x-pass" in (D / "api/_gh.js").read_text())
import yaml
a = yaml.safe_load((R / ".github/workflows/analytics.yml").read_text()); on = a.get("on") or a.get(True)
check("analytics.yml weekly + manual", "schedule" in on and "workflow_dispatch" in on)
print("ALL ROUND-7 CHECKS PASSED" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
