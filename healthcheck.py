"""API key health check.   python healthcheck.py            (also runs as a step in build.yml)

Per provider: which secret names were found, does each key really work, credits (ElevenLabs), and which secrets
look like API keys but are NAMED WRONG (so the bot silently ignores them).
Also live-checks the publishing side: Instagram, Facebook Page, YouTube upload (OAuth refresh token) and
YouTube research (YT_API_KEY). Never prints a key. Exits 0 unless --strict and no LLM provider works."""
import json
import os
import sys
from pathlib import Path

import requests

import keyring

T = 20
GRAPH = os.environ.get("META_GRAPH_VERSION", "v21.0")   # keep this equal to GRAPH in publisher.py
ICON = {"ok": "OK  ", "dead": "DEAD", "rate": "LIMIT", "error": "ERR ", "unchecked": "--  ", "missing": "NOT SET"}


# --------------------------------------------------------------------------- helpers
def _secret(name):
    """Env var first, then ALL_SECRETS_JSON (the build.yml health step only passes that one)."""
    v = os.environ.get(name, "")
    if not v and os.environ.get("ALL_SECRETS_JSON"):
        try:
            v = json.loads(os.environ["ALL_SECRETS_JSON"]).get(name, "")
        except Exception:
            v = ""
    return (v or "").strip()


def _clean(text, secrets=()):
    """Short one-line text with every secret value masked."""
    t = str(text)
    for s in secrets:
        if s:
            t = t.replace(s, "***")
    return " ".join(t.split())[:140]


def _http_state(r, secrets=()):
    """requests response -> (state, note)."""
    if r.status_code == 200:
        return "ok", ""
    body = _clean(r.text[:400], secrets)
    low = body.lower()
    if r.status_code == 429:
        return "rate", f"HTTP 429 {body[:80]}"
    if r.status_code in (401, 403) or (r.status_code == 400 and any(
            w in low for w in ("invalid", "expired", "oauth", "api key", "unauthorized", "token"))):
        return "dead", f"HTTP {r.status_code} {body[:100]}"
    return "error", f"HTTP {r.status_code} {body[:100]}"


def _row(label, state, note=""):
    return {"key": label, "state": state, "note": note}


# --------------------------------------------------------------------------- LLM / stock / research keys
def _live(provider, key):
    """-> (state, note).  state: ok | dead | rate | error | unchecked"""
    s = (key,)
    try:
        if provider == "groq":
            r = requests.get("https://api.groq.com/openai/v1/models",
                             headers={"Authorization": f"Bearer {key}"}, timeout=T)
        elif provider == "gemini":
            r = requests.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                             headers={"x-goog-api-key": key}, timeout=T)
        elif provider == "xai":
            r = requests.get("https://api.x.ai/v1/models",
                             headers={"Authorization": f"Bearer {key}"}, timeout=T)
        elif provider == "pexels":
            r = requests.get("https://api.pexels.com/videos/search", params={"query": "sky", "per_page": 1},
                             headers={"Authorization": key}, timeout=T)
        elif provider == "pixabay":
            r = requests.get("https://pixabay.com/api/videos/",
                             params={"key": key, "q": "sky", "per_page": 3}, timeout=T)
        elif provider == "youtube_data":
            r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                             params={"part": "id", "chart": "mostPopular", "regionCode": "IN",
                                     "maxResults": 1, "key": key}, timeout=T)
        else:
            return "unchecked", "present (no live check for this provider)"
    except Exception as e:
        return "error", f"network: {_clean(e, s)[:60]}"
    return _http_state(r, s)


# --------------------------------------------------------------------------- publishing side
def _meta_row(label, url, params, secrets):
    try:
        r = requests.get(url, params=params, timeout=T)
    except Exception as e:
        return _row(label, "error", f"network: {_clean(e, secrets)[:60]}")
    st, note = _http_state(r, secrets)
    if st == "ok":
        try:
            j = r.json()
            note = "-> " + str(j.get("username") or j.get("name") or j.get("id") or "ok")
        except Exception:
            pass
    return _row(label, st, note)


def check_instagram():
    uid, tok = _secret("IG_USER_ID"), _secret("META_ACCESS_TOKEN")
    host = _secret("IG_GRAPH_HOST") or "graph.instagram.com"   # same default as publisher.py
    if not (uid and tok):
        return {"purpose": "Instagram Reels upload",
                "keys": [_row("IG_USER_ID / META_ACCESS_TOKEN", "missing", "not set")]}
    row = _meta_row("IG_USER_ID + META_ACCESS_TOKEN", f"https://{host}/{GRAPH}/{uid}",
                    {"fields": "username", "access_token": tok}, (tok,))
    return {"purpose": "Instagram Reels upload", "keys": [row]}


def check_facebook():
    pid, ptok = _secret("FB_PAGE_ID"), _secret("FB_PAGE_TOKEN")
    if not (pid and ptok):
        return {"purpose": "Facebook Reels upload",
                "keys": [_row("FB_PAGE_ID / FB_PAGE_TOKEN", "missing", "not set")]}
    row = _meta_row("FB_PAGE_ID + FB_PAGE_TOKEN", f"https://graph.facebook.com/{GRAPH}/{pid}",
                    {"fields": "name", "access_token": ptok}, (ptok,))
    return {"purpose": "Facebook Reels upload", "keys": [row]}


def check_youtube_upload():
    cid, sec, ref = _secret("YT_CLIENT_ID"), _secret("YT_CLIENT_SECRET"), _secret("YT_REFRESH_TOKEN")
    if not (cid and sec and ref):
        return {"purpose": "YouTube upload (OAuth)",
                "keys": [_row("YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN", "missing", "not set")]}
    s = (cid, sec, ref)
    try:
        r = requests.post("https://oauth2.googleapis.com/token", timeout=T, data={
            "client_id": cid, "client_secret": sec, "refresh_token": ref, "grant_type": "refresh_token"})
    except Exception as e:
        return {"purpose": "YouTube upload (OAuth)", "keys": [_row("YT OAuth", "error", f"network: {_clean(e, s)[:60]}")]}
    if r.status_code == 200 and r.json().get("access_token"):
        return {"purpose": "YouTube upload (OAuth)", "keys": [_row("YT OAuth", "ok", "access token issued")]}
    body = _clean(r.text[:300], s)
    if "invalid_grant" in body:
        note = "refresh token expired/revoked (apps in Testing mode expire after 7 days)"
        return {"purpose": "YouTube upload (OAuth)", "keys": [_row("YT OAuth", "dead", note)]}
    return {"purpose": "YouTube upload (OAuth)",
            "keys": [_row("YT OAuth", "dead", f"HTTP {r.status_code} {body[:100]}")]}


def check_extra(live=True):
    """Publishing / OAuth checks. Returned as {section_name: {purpose, keys}}."""
    sections = {
        "instagram": ("Instagram Reels upload", check_instagram),
        "facebook": ("Facebook Reels upload", check_facebook),
        "youtube_upload": ("YouTube upload (OAuth)", check_youtube_upload),
    }
    out = {}
    for name, (purpose, fn) in sections.items():
        if live:
            out[name] = fn()
        else:
            out[name] = {"purpose": purpose, "keys": [_row(name, "unchecked", "offline run")]}
    return out


# --------------------------------------------------------------------------- main run
def run(live=True, eleven_test=True):
    keyring.reset()
    report = {"providers": {}, "extra": {}, "misnamed": [], "missing_required": []}
    for p, (base, aliases, purpose) in keyring.PROVIDERS.items():
        slots = keyring.load(p)
        rows = []
        if p == "elevenlabs" and live and slots:
            import eleven_voice
            h = eleven_voice.health(test_voice=eleven_test)
            rows = [{"key": r["key"], "state": "ok" if r["status"] == "ok" else "dead",
                     "note": f"credits left: {r['credits_left']}" if r["credits_left"] is not None else ""}
                    for r in h["keys"]]
            report["elevenlabs_test"] = h["test_generation"]
        else:
            for sl in slots:
                st, note = _live(p, sl.value) if live else ("unchecked", "")
                rows.append({"key": sl.label, "state": st, "note": note})
        report["providers"][p] = {"purpose": purpose, "primary_name": base, "keys": rows}

    report["extra"] = check_extra(live=live)
    report["misnamed"] = [{"found": n, "looks_like": p, "rename_to": f"{b} / {b}_2 ..."}
                          for n, p, b in keyring.misnamed_secrets()]

    def ok(p):
        return any(r["state"] == "ok" for r in report["providers"][p]["keys"])

    if not ok("groq") and not ok("gemini"):
        report["missing_required"].append("NO working LLM key (need at least one GROQ_API_KEY or GEMINI_API_KEY)")
    if not ok("pexels") and not ok("pixabay"):
        report["missing_required"].append("NO stock-video key (PEXELS_API_KEY or PIXABAY_API_KEY) - videos will be plain")
    if report["extra"]["instagram"]["keys"][0]["state"] != "ok" and report["extra"]["facebook"]["keys"][0]["state"] != "ok":
        report["missing_required"].append("NO working Meta key - Instagram/Facebook Reels will not post")
    if report["extra"]["youtube_upload"]["keys"][0]["state"] != "ok":
        report["missing_required"].append("YouTube upload OAuth not working - nothing will publish to YouTube")
    return report


def _block(name, purpose, rows, good=None):
    n = len(rows)
    if good is None:
        head = f"{name:14s}   ({purpose})"
    else:
        unch = sum(1 for r in rows if r["state"] == "unchecked")
        head = f"{name:14s} {good}/{n} working" + (f" ({unch} not live-checked)" if unch else "") + f"   ({purpose})"
    lines = [head]
    for r in rows:
        lines.append(f"    [{ICON.get(r['state'], r['state'])}] {r['key']} {r['note']}".rstrip())
    return lines


def render(rep):
    L = ["=== API KEY HEALTH ==="]
    for p, d in rep["providers"].items():
        rows = d["keys"]
        if not rows:
            L.append(f"{p:14s} not set      ({d['purpose']})  -> name: {d['primary_name']}, {d['primary_name']}_2 ...")
            continue
        good = sum(1 for r in rows if r["state"] == "ok")
        L += _block(p, d["purpose"], rows, good=good)

    L.append("\n=== PUBLISHING ===")
    for name, d in rep["extra"].items():
        L += _block(name, d["purpose"], d["keys"])

    t = rep.get("elevenlabs_test")
    if t is not None:
        L.append("\nElevenLabs test voice: " + ("OK" if t.get("ok") else f"FAILED {t}"))
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
