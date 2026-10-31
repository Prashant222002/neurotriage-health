"""Round 2 - API key health check.   python healthcheck.py            (also runs as a step in build.yml)
Per provider: which secret names were found, does each key really work, credits (ElevenLabs), and which secrets
look like API keys but are NAMED WRONG (so the bot silently ignores them). Never prints a key. Always exits 0 unless
--strict and no LLM provider works."""
import json
import os
import sys
from pathlib import Path

import requests

import keyring

T = 20


def _live(provider, key):
    """-> (state, note).  state: ok | dead | rate | error | unchecked"""
    try:
        if provider == "groq":
            r = requests.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=T)
        elif provider == "gemini":
            r = requests.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                             headers={"x-goog-api-key": key}, timeout=T)
        elif provider == "xai":
            r = requests.get("https://api.x.ai/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=T)
        elif provider == "pexels":
            r = requests.get("https://api.pexels.com/videos/search", params={"query": "sky", "per_page": 1},
                             headers={"Authorization": key}, timeout=T)
        elif provider == "pixabay":
            r = requests.get("https://pixabay.com/api/videos/", params={"key": key, "q": "sky", "per_page": 3}, timeout=T)
        else:
            return "unchecked", "present (live check not built yet)"
    except Exception as e:
        return "error", f"network: {str(e)[:60]}"
    if r.status_code == 200:
        return "ok", ""
    kind, _ = keyring.classify(r.status_code, r.text[:200], r.headers)
    return {"dead": "dead", "rate": "rate"}.get(kind, "error"), f"HTTP {r.status_code}"


def run(live=True, eleven_test=True):
    keyring.reset()
    report = {"providers": {}, "misnamed": [], "missing_required": []}
    for p, (base, aliases, purpose) in keyring.PROVIDERS.items():
        slots = keyring.load(p)
        rows = []
        if p == "elevenlabs" and live and slots:
            import eleven_voice
            h = eleven_voice.health(test_voice=eleven_test)
            rows = [{"key": r["key"], "state": "ok" if r["status"] == "ok" else "dead",
                     "note": f"credits left: {r['credits_left']}" if r["credits_left"] is not None else ""} for r in h["keys"]]
            report["elevenlabs_test"] = h["test_generation"]
        else:
            for sl in slots:
                st, note = _live(p, sl.value) if live else ("unchecked", "")
                rows.append({"key": sl.label, "state": st, "note": note})
        report["providers"][p] = {"purpose": purpose, "primary_name": base, "keys": rows}
    report["misnamed"] = [{"found": n, "looks_like": p, "rename_to": f"{b} / {b}_2 ..."} for n, p, b in keyring.misnamed_secrets()]
    ok = lambda p: any(r["state"] == "ok" for r in report["providers"][p]["keys"])
    for p in ("groq", "gemini"):
        pass
    if not ok("groq") and not ok("gemini"):
        report["missing_required"].append("NO working LLM key (need at least one GROQ_API_KEY or GEMINI_API_KEY)")
    if not ok("pexels") and not ok("pixabay"):
        report["missing_required"].append("NO stock-video key (PEXELS_API_KEY or PIXABAY_API_KEY) - videos will be plain")
    return report


def render(rep):
    icon = {"ok": "OK  ", "dead": "DEAD", "rate": "LIMIT", "error": "ERR ", "unchecked": "--  "}
    L = ["=== API KEY HEALTH ==="]
    for p, d in rep["providers"].items():
        n = len(d["keys"])
        good = sum(1 for r in d["keys"] if r["state"] == "ok")
        unch = sum(1 for r in d["keys"] if r["state"] == "unchecked")
        head = f"{p:12s} {good}/{n} working" + (f" ({unch} present, not live-checked)" if unch else "") + f"   ({d['purpose']})"
        L.append(head if n else f"{p:12s} not set      ({d['purpose']})  -> name: {d['primary_name']}, {d['primary_name']}_2 ...")
        for r in d["keys"]:
            L.append(f"    [{icon.get(r['state'], r['state'])}] {r['key']} {r['note']}")
    t = rep.get("elevenlabs_test")
    if t is not None:
        L.append("ElevenLabs test voice: " + ("OK" if t.get("ok") else f"FAILED {t}"))
    if rep["misnamed"]:
        L.append("\nWRONGLY NAMED SECRETS (bot ignores these):")
        for m in rep["misnamed"]:
            L.append(f"    {m['found']}  ->  rename to {m['rename_to']}")
    for m in rep["missing_required"]:
        L.append("\n!! " + m)
    return "\n".join(L)


if __name__ == "__main__":
    rep = run(live="--offline" not in sys.argv, eleven_test="--no-voice-test" not in sys.argv)
    txt = render(rep)
    print(txt)
    Path("work").mkdir(exist_ok=True)
    Path("work/key_health.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("```\n" + txt + "\n```\n")
    if "--strict" in sys.argv and any("LLM" in m for m in rep["missing_required"]):
        sys.exit(1)
