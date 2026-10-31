"""Round 1 - crash-proofing helpers.
AI models sometimes return the wrong TYPE (list instead of string, string instead of list, None, dict).
Every AI-generated field goes through these helpers, so one bad field can never kill a 40-minute build.
Also: soft() = run an optional step; if it fails, log it, record it, and carry on with a fallback."""
import json
import re
import time
from pathlib import Path

STEPS = []          # [{"step", "status", "sec", "error"}]  -> written to output/step_report.json


def as_text(x, fallback="", maxlen=None):
    """Anything -> clean single-line string. list -> joined, dict -> its values, None -> fallback."""
    if x is None:
        s = ""
    elif isinstance(x, str):
        s = x
    elif isinstance(x, (list, tuple, set)):
        s = " ".join(as_text(i) for i in x)
    elif isinstance(x, dict):
        s = " ".join(as_text(v) for v in x.values())
    else:
        s = str(x)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        s = fallback if isinstance(fallback, str) else as_text(fallback)
    return s[:maxlen].strip() if maxlen else s


def as_list(x, maxn=None):
    """Anything -> list of non-empty strings (a 'a #b #c' string is split into items)."""
    if x is None:
        out = []
    elif isinstance(x, str):
        out = re.split(r"[,\n]|\s(?=#)", x)
    elif isinstance(x, (list, tuple, set)):
        out = [as_text(i) for i in x]
    else:
        out = [as_text(x)]
    out = [o.strip() for o in out if o and o.strip()]
    return out[:maxn] if maxn else out


def hashtags(x, maxn=5):
    out = []
    for h in as_list(x):
        for t in h.split():
            t = "#" + re.sub(r"[^\w]", "", t.lstrip("#"))
            if len(t) > 1 and t not in out:
                out.append(t)
    return out[:maxn]


def thumb_words(x, fallback="WATCH THIS", maxwords=4):
    return " ".join(as_text(x, fallback).upper().split()[:maxwords]) or fallback


def normalize_pack(pk, title_fallback="NeuroTriage"):
    """Packaging dict from the AI -> guaranteed types. Never raises."""
    pk = pk if isinstance(pk, dict) else {}
    tf = as_text(title_fallback, "NeuroTriage")
    return {
        **pk,
        "title": as_text(pk.get("title"), tf, 100),
        "thumb_text": thumb_words(pk.get("thumb_text"), tf[:30]),
        "hashtags": hashtags(pk.get("hashtags")),
        "yt_description": as_text(pk.get("yt_description")),
        "ig_caption": as_text(pk.get("ig_caption")),
        "first_comment": as_text(pk.get("first_comment")),
        "keyword": as_text(pk.get("keyword")),
        "titles": as_list(pk.get("titles")),
    }


def soft(name, fn, default=None, log=print):
    """Run an optional step. On any error: log, record, return default. Never raises."""
    t0 = time.time()
    try:
        v = fn()
        STEPS.append({"step": name, "status": "ok", "sec": round(time.time() - t0, 1), "error": ""})
        return v
    except Exception as e:  # noqa
        msg = f"{type(e).__name__}: {str(e)[:160]}"
        STEPS.append({"step": name, "status": "FAILED-skipped", "sec": round(time.time() - t0, 1), "error": msg})
        log(f"[soft] {name} failed -> skipped, pipeline continues ({msg})")
        return default


def save_steps(path):
    try:
        Path(path).write_text(json.dumps(STEPS, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
