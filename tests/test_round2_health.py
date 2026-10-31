"""healthcheck.py end-to-end with mocked network: finds keys, flags dead/limited, flags mis-named secrets, never prints a key."""
import io, json, os, sys, contextlib
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for k in list(os.environ):
    if any(h in k for h in ("GROQ", "GEMINI", "ELEVEN", "XAI", "PEXELS", "PIXABAY", "GOOGLE", "XI_", "GROK")): del os.environ[k]
os.environ.update(GROQ_API_KEY="SECRETGROQ1", GROQ_API_KEY_2="SECRETGROQ2", PEXELS_API_KEY="SECRETPEX",
                  GROK_KEY_NEW="SECRETXAI", ELEVENLABS_APIKEY_TYPO="SECRETELEVEN", RUNWAY_API_KEY="SECRETRUN")
import requests, healthcheck
class R:
    def __init__(s, c): s.status_code, s.text, s.headers = c, "", {}
def fake_get(url, headers=None, params=None, timeout=0):
    auth = json.dumps(headers or {}) + json.dumps(params or {})
    if "SECRETGROQ2" in auth: return R(401)
    if "SECRETPEX" in auth: return R(429)
    return R(200)
requests.get = fake_get
rep = healthcheck.run(live=True)
out = healthcheck.render(rep)
print(out)
g = {r["key"]: r["state"] for r in rep["providers"]["groq"]["keys"]}
assert g == {"GROQ_API_KEY": "ok", "GROQ_API_KEY_2": "dead"}, g
assert rep["providers"]["pexels"]["keys"][0]["state"] == "rate"
assert rep["providers"]["runway"]["keys"][0]["state"] == "unchecked"
assert {m["found"] for m in rep["misnamed"]} == {"GROK_KEY_NEW", "ELEVENLABS_APIKEY_TYPO"}, rep["misnamed"]
assert any("stock-video" in m for m in rep["missing_required"])
assert not any(s in out + json.dumps(rep) for s in ("SECRETGROQ", "SECRETPEX", "SECRETXAI", "SECRETELEVEN", "SECRETRUN")), "KEY LEAKED"
print("\nHEALTHCHECK TEST PASSED (no key printed)")
