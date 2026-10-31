"""Round 14: auto tags, password-check endpoint, PWA files."""
import json, re, subprocess, sys
from pathlib import Path
R = Path(__file__).parent.parent; sys.path.insert(0, str(R))
import talking_head as th
w = [("Migraine", 0, 1)] * 4 + [("headache", 1, 2)] * 2 + [("yeh", 2, 3), ("treatment", 3, 4)]
t = th.auto_tags(w, "@neurotriage", ["AI", "ai"]); assert t.count("AI") + t.count("ai") == 1 and "migraine" in t and "yeh" not in t and "neurotriage" in t and len(",".join(t)) < 450
assert len(th.auto_tags([], "@x")) >= 2                                   # even with no words
m = json.loads((R / "dashboard/manifest.webmanifest").read_text()); assert m["display"] == "standalone" and any(i["purpose"] == "maskable" for i in m["icons"])
assert all((R / "dashboard" / i["src"]).exists() for i in m["icons"])
h = (R / "dashboard/index.html").read_text(encoding="utf-8")
for k in ("studio-check", "beforeinstallprompt", "autoTg", "pwOkV", "apple-touch-icon"): assert k in h, k
chk = subprocess.run(["node", "-e", '''const f=require("%s/dashboard/api/studio-check.js");process.env.STUDIO_PASSWORD="abc";
const r=(b)=>{let o={};const res={status(c){o.c=c;return res},json(j){o.j=j}};f({method:"POST",body:b},res);return o};
const a=r({password:"abc"}),b=r({password:"x"});if(a.j.ok!==true||b.c!==401)process.exit(1)''' % R], capture_output=True); assert chk.returncode == 0, chk.stderr
print("round14 OK")
