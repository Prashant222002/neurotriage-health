"""ROUND 2 TEST - multi-key engine. No network: requests is mocked. Run: python tests/test_round2.py"""
import json, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for k in list(os.environ):
    if any(h in k for h in ("GROQ", "GEMINI", "ELEVEN", "XAI", "PEXELS", "PIXABAY", "CANVA", "RUNWAY", "LUMA", "GOOGLE", "XI_")):
        del os.environ[k]
import keyring

n = 0
def check(name, cond):
    global n
    print(("PASS " if cond else "FAIL ") + name); n += 1
    assert cond, name

# ---------- 1. naming / loading / dedupe / aliases / ALL_SECRETS_JSON
os.environ.update(GROQ_API_KEY="g1", GROQ_API_KEY_2="g2", GROQ_API_KEY_3="g1",        # g1 duplicated under _3
                  ELEVENLABS_API_KEY="e1", XI_API_KEY="e2", ELEVEN_API_KEY_1="e1")    # aliases + dup
os.environ["ALL_SECRETS_JSON"] = json.dumps({"GROQ_API_KEY_7": "g7", "ELEVEN_API_KEY_5": "e5", "PEXELS_API_KEY": "p1",
                                              "GROK_API_KEY": "x1", "ELEVENLABS_KEY_OLD": "zzz", "GEMINI_API_KEY": "${{ secrets.X }}"})
keyring.reset()
check("groq: 3 unique keys (dup merged), _7 read from ALL_SECRETS_JSON", [s.value for s in keyring.load("groq")] == ["g1", "g2", "g7"])
check("elevenlabs aliases + ALL_SECRETS_JSON, dup merged", sorted(s.value for s in keyring.load("elevenlabs")) == ["e1", "e2", "e5"])
check("grok alias -> xai", [s.value for s in keyring.load("xai")] == ["x1"])
check("unresolved '${{ secrets.X }}' placeholder ignored", keyring.load("gemini") == [])
check("misnamed secret detected, correct ones not flagged",
      [m[0] for m in keyring.misnamed_secrets()] == ["ELEVENLABS_KEY_OLD"])
check("key values never in repr", "g1" not in repr(keyring.load("groq")[0]))

# ---------- 2. cooldown / backoff / retry-after / dead / model-missing
clock = [1000.0]
R = keyring.Ring("groq", slots=[keyring.Slot("K1", "a"), keyring.Slot("K2", "b")], now=lambda: clock[0])
check("both keys candidates", [s.label for s in R.candidates("m")] == ["K1", "K2"])
kind = R.fail(R.slots[0], 429, "rate limit", {"Retry-After": "30"}, scope="m")
check("429 -> rate, K1 cooling for model m only", kind == "rate" and [s.label for s in R.candidates("m")] == ["K2"]
      and [s.label for s in R.candidates("other")] == ["K1", "K2"])
check("Retry-After respected (30-38s)", 30 <= R.until[("K1", "m")] - clock[0] <= 38)
clock[0] += 40
check("after cooldown K1 usable again", [s.label for s in R.candidates("m")] == ["K1", "K2"])
for _ in range(4): R.fail(R.slots[0], 429, "rate limit", scope="m")
check("exponential backoff grows, capped at 15min (+jitter)", 150 <= R.until[("K1", "m")] - clock[0] <= 1125)
R.ok(R.slots[0], "m")
check("success resets cooldown", R.candidates("m")[0].label == "K1")
R.fail(R.slots[1], 401, "invalid_api_key")
check("401 -> key dead everywhere", [s.label for s in R.candidates("anything")] == ["K1"] and dict(R.status())["K2"] == "dead")
R.fail(R.slots[0], 404, "model_not_found", scope="llama-x")
check("404 -> model marked bad", "llama-x" in R.bad_models)
R.fail(R.slots[0], 429, "Limit per day reached", scope="d")
check("'per day' quota -> long cooldown (>=3h)", R.until[("K1", "d")] - clock[0] >= 3 * 3600)
check("classify parses 'try again in 2.5s'", keyring.classify(429, "Please try again in 2.5s")[1] == 2.5)
check("classify json-400", keyring.classify(400, "Failed to validate JSON")[0] == "bad_request")
check("wait_needed all-dead -> None", keyring.Ring("x", slots=[keyring.Slot("a", "1")]).wait_needed() is not None)

# ---------- 3. bot LLM layer with mocked Groq/Gemini
os.environ.update(GROQ_API_KEY="g1", GROQ_API_KEY_2="g2", GEMINI_API_KEY="gm1", PEXELS_API_KEY="p1", PEXELS_API_KEY_2="p2")
os.environ.pop("ALL_SECRETS_JSON")
keyring.reset()
import types as _t
_g = _t.ModuleType("google"); _ge = _t.ModuleType("google.genai"); _ty = _t.ModuleType("google.genai.types")
class _Cfg:                                   # stand-ins so the offline test needs no google SDK
    def __init__(self, **kw): self.kw = kw
_ty.GenerateContentConfig = _Cfg; _ty.Tool = lambda **k: k; _ty.GoogleSearch = lambda: 1
_ty.Part = type("Part", (), {"from_bytes": staticmethod(lambda **k: k)})
_ge.types = _ty; _g.genai = _ge
sys.modules.update({"google": _g, "google.genai": _ge, "google.genai.types": _ty})
import bot, requests

class Resp:
    def __init__(self, code, js=None, text=""):
        self.status_code, self._js, self.text, self.headers = code, js, text or json.dumps(js or {}), {}
    def json(self): return self._js
calls = []
def okjson(txt): return Resp(200, {"choices": [{"message": {"content": txt}}]})
def mk(behaviour):
    def post(url, headers=None, json=None, timeout=0):
        key = headers["Authorization"].split()[-1]; calls.append((json["model"], key))
        return behaviour(json["model"], key, json)
    return post
def get_models(url, headers=None, timeout=0, **kw):
    return Resp(200, {"data": [{"id": "openai/gpt-oss-120b"}, {"id": "openai/gpt-oss-20b"}, {"id": "whisper-large-v3"}]})
requests.get = get_models
bot.requests = requests
bot.groq_discover()
check("discovery: only verified models kept, no vision/search 404 cycling",
      bot.GROQ_TEXT_MODELS == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"] and bot.GROQ_VISION_MODELS == [] and bot.GROQ_SEARCH_MODELS == [])

# 3a. primary 429 on key1 -> key2 same model works
requests.post = mk(lambda m, k, j: Resp(429, text="rate limit, try again in 10s") if k == "g1" else okjson("hello"))
check("429 on key1 -> key2 answers", bot.ask("hi") == "hello")
calls.clear()
check("key1 now cooling: next call skips it (no wasted request)", bot.ask("hi") == "hello" and all(k == "g2" for _, k in calls))

# 3b. both keys 429 on primary -> fallback model
bot.keyring.reset(); bot.GRQ = bot.keyring.ring("groq"); calls.clear()
requests.post = mk(lambda m, k, j: Resp(429, text="rate limit") if m.endswith("120b") else okjson("from-20b"))
check("primary rate-limited -> fallback model used", bot.ask("hi") == "from-20b")
calls.clear()
bot.ask("hi")
check("primary not hammered again while cooling", calls and calls[0][0].endswith("20b"))

# 3c. JSON validation 400 -> raw failed_generation used, script not replaced by another model
bot.keyring.reset(); bot.GRQ = bot.keyring.ring("groq"); calls.clear()
fg = '{"title":"X","scenes":[1,2,3]} trailing'
requests.post = mk(lambda m, k, j: Resp(400, {"error": {"message": "Failed to validate JSON", "code": "json_validate_failed",
                                                       "failed_generation": fg}}))
check("JSON-400 returns model's own output, 1 request only", bot.ask("x", json_mode=True) == fg and len(calls) == 1)

# 3d. Groq dead + Gemini rate-limited short -> waits once, then answers (no failing the build)
bot.keyring.reset(); bot.GRQ = bot.keyring.ring("groq"); bot.GEM = bot.keyring.ring("gemini")
requests.post = mk(lambda m, k, j: Resp(401, text="invalid_api_key"))
slept = []
def fake_sleep(sec):                                   # pretend time passed: age every cooldown by the sleep
    slept.append(sec)
    for rg in (bot.GEM, bot.GRQ):
        for k in rg.until: rg.until[k] -= sec
bot.time.sleep = fake_sleep
state = {"n": 0}
class FakeModels:
    def generate_content(self, model, contents, config):
        state["n"] += 1
        if state["n"] == 1: raise Exception("429 RESOURCE_EXHAUSTED. quota. retry in 20s")
        class R_: text = "gem-ok"
        return R_()
class FakeClient: models = FakeModels()
bot._CLIENTS["gm1"] = FakeClient(); bot.MODELS = ["gemini-x"]
check("all Groq keys dead -> Gemini; rate-limited once -> waited, retried, answered",
      bot.ask("q") == "gem-ok" and any(15 < s < 40 for s in slept))
check("dead Groq keys reported as dead", all(st == "dead" for _, st in bot.GRQ.status()))

# 3e. Pexels rotation
bot.keyring.reset(); bot.PXR = bot.keyring.ring("pexels")
seen = []
def pget(url, timeout=0, headers=None, params=None):
    seen.append(headers["Authorization"])
    return Resp(429, text="rate") if headers["Authorization"] == "p1" else Resp(200, {"videos": []})
requests.get = pget
r = bot._stock_get(bot.PXR, "https://api.pexels.com/videos/search", lambda k: {"headers": {"Authorization": k}, "params": {}}, "pexels")
check("pexels key1 429 -> key2 used", r is not None and seen == ["p1", "p2"])

# ---------- 4. ElevenLabs: key loading, labels, fallback policy, health (mocked)
for k in list(os.environ):
    if k.startswith("ELEVEN") or k in ("XI_API_KEY",): del os.environ[k]
os.environ["ELEVENLABS_API_KEY"] = "ek1"; os.environ["ELEVEN_API_KEY_2"] = "ek2"
import importlib, eleven_voice; keyring.reset(); importlib.reload(eleven_voice)
check("eleven keys loaded from alias + numbered name", sorted(eleven_voice._KEYS) == ["ek1", "ek2"])
check("eleven labels (not key text) used for logs", set(eleven_voice._LABEL.values()) == {"ELEVENLABS_API_KEY", "ELEVEN_API_KEY_2"})
def eget(url, headers=None, timeout=0, **kw):
    k = headers["xi-api-key"]
    return Resp(200, {"character_limit": 10000, "character_count": 9990 if k == "ek1" else 100})
requests.get = eget; eleven_voice.requests = requests
def epost(url, params=None, headers=None, json=None, timeout=0):
    import base64
    return Resp(200, {"audio_base64": base64.b64encode(b"x").decode(), "alignment": {"characters": ["H"], "character_start_times_seconds": [0], "character_end_times_seconds": [0.1]}})
requests.post = epost
h = eleven_voice.health()
check("health: credits per key + test generation ok, no key text anywhere",
      sorted(r["credits_left"] for r in h["keys"]) == [10, 9900] and h["test_generation"]["ok"] and "ek1" not in json.dumps(h) and "ek2" not in json.dumps(h))

# fallback policy
bot.eleven_voice = eleven_voice
eleven_voice._BAD.update(eleven_voice._KEYS)           # every key out of credit
bot._make_voice_edge = lambda scenes, mt: ([("r", 1, [])], "EDGE")
sc = [{"text": "hinglish", "text_en": "english"}]
res, v, lang = bot.make_voice([dict(s) for s in sc])
check("keys dead + policy english -> English fallback (warned)", lang == "english")
bot.ELEVEN_FALLBACK = "fail"
try:
    bot.make_voice([dict(s) for s in sc]); check("policy fail must raise", False)
except RuntimeError:
    check("policy fail -> stops instead of silent fallback", True)
bot.ELEVEN_FALLBACK = "english"
res, v, lang = bot.make_voice([dict(s) for s in sc], engine="local")
check("engine=local skips ElevenLabs entirely (Long video)", lang == "english")

print(f"\nALL {n} ROUND-2 CHECKS PASSED")
