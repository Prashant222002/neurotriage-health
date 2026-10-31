"""Round 2 - ONE place that knows every API key.

NAMING RULE (same for every provider):   <BASE>   <BASE>_1   <BASE>_2 ... <BASE>_10
  e.g. GROQ_API_KEY, GROQ_API_KEY_2 ... GROQ_API_KEY_10      (bare name == key 1, "_1" also accepted)
Duplicates (same value under two names) are merged, so two secrets can never fight over the same key.

Keys are read from normal env vars AND from ALL_SECRETS_JSON (the workflow passes toJSON(secrets)), so adding
GROQ_API_KEY_7 in GitHub needs NO workflow edit.

Each key has a state: ok / cooling (429, backoff + jitter, Retry-After respected) / dead (401/403/invalid).
A cooling or dead key is skipped instantly - no more hammering a provider that already said "quota exhausted".
Key VALUES are never logged; only labels such as GROQ_API_KEY_2."""
import json
import os
import random
import re
import time

# provider -> (primary base name, extra accepted base names (aliases), what it is for)
PROVIDERS = {
    "groq":       ("GROQ_API_KEY",    ["GROQ_KEY", "GROQ_API_TOKEN"],                      "LLM: research, script, clip choice"),
    "gemini":     ("GEMINI_API_KEY",  ["GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY", "GEMINI_KEY"], "LLM fallback + vision"),
    "elevenlabs": ("ELEVEN_API_KEY",  ["ELEVENLABS_API_KEY", "ELEVEN_LABS_API_KEY", "XI_API_KEY"], "Hinglish voice (Reels)"),
    "xai":        ("XAI_API_KEY",     ["GROK_API_KEY"],                                    "Grok LLM / image (slot, used in later rounds)"),
    "pexels":     ("PEXELS_API_KEY",  [],                                                  "stock video"),
    "pixabay":    ("PIXABAY_API_KEY", [],                                                  "stock video"),
    "canva":      ("CANVA_API_KEY",   ["CANVA_ACCESS_TOKEN"],                              "Canva thumbnails/design (slot, later rounds)"),
    "runway":     ("RUNWAY_API_KEY",  ["RUNWAYML_API_SECRET"],                             "AI video generation (slot, later rounds)"),
    "luma":       ("LUMA_API_KEY",    ["LUMAAI_API_KEY"],                                  "AI video generation (slot, later rounds)"),
    "youtube_data": ("YT_API_KEY",    [],                                                  "viral-outlier research"),
}
MAXKEYS = 10

_json_cache = {}


def _secret_json():
    raw = os.environ.get("ALL_SECRETS_JSON", "")
    if raw not in _json_cache:
        try:
            d = json.loads(raw) if raw else {}
            _json_cache[raw] = {k: str(v) for k, v in d.items() if isinstance(d, dict)}
        except Exception:
            _json_cache[raw] = {}
    return _json_cache[raw]


def _get(name):
    v = (os.environ.get(name) or "").strip()
    return v or (_secret_json().get(name) or "").strip()


def names_for(provider):
    base, aliases, _ = PROVIDERS[provider]
    out = []
    for b in [base] + aliases:
        out.append(b)
        out += [f"{b}_{i}" for i in range(1, MAXKEYS + 1)]
    return out


class Slot:
    __slots__ = ("label", "value")

    def __init__(self, label, value):
        self.label, self.value = label, value

    def __repr__(self):          # never reveals the key
        return f"<key {self.label}>"


def load(provider):
    """-> list[Slot] in stable order (primary naming first), duplicates merged."""
    seen, out = set(), []
    for n in names_for(provider):
        v = _get(n)
        if v and v not in seen and not v.startswith("${{"):
            seen.add(v)
            out.append(Slot(n, v))
    return out


def classify(status, body="", headers=None):
    """HTTP result -> (kind, retry_after_seconds|None).  kind: dead | rate | model | bad_request | server | other"""
    b = (body or "").lower()
    ra = None
    try:
        h = {k.lower(): v for k, v in (headers or {}).items()}
        if "retry-after" in h:
            ra = float(h["retry-after"])
    except Exception:
        ra = None
    if ra is None:
        m = re.search(r"try again in (\d+(?:\.\d+)?)\s*(ms|s|m)", b) or re.search(r"retry in (\d+(?:\.\d+)?)\s*(ms|s|m)", b)
        if m:
            ra = float(m.group(1)) * {"ms": 0.001, "s": 1, "m": 60}[m.group(2)]
    if status in (401, 403) or "invalid_api_key" in b or "api key not valid" in b:
        return "dead", None
    if status == 429 or "resource_exhausted" in b or "rate limit" in b or "quota" in b and status in (402, 429):
        return "rate", ra
    if status in (404, 410) or "model_not_found" in b or "decommission" in b:
        return "model", None
    if status == 400:
        return "bad_request", None
    if status and status >= 500:
        return "server", ra
    return "other", ra


class Ring:
    """Ordered keys of one provider with per-(key, scope) cooldowns. scope = model name (Groq/Gemini limits are
    per model) or '' for providers where the limit is per key."""

    def __init__(self, provider, slots=None, now=time.time):
        self.provider = provider
        self.slots = load(provider) if slots is None else slots
        self.now = now
        self.dead = set()            # labels
        self.until = {}              # (label, scope) -> ts
        self.fails = {}              # (label, scope) -> consecutive rate-limit count
        self.bad_models = set()

    def __len__(self):
        return len(self.slots)

    def alive(self):
        return [s for s in self.slots if s.label not in self.dead]

    def candidates(self, scope=""):
        t = self.now()
        return [s for s in self.alive() if self.until.get((s.label, scope), 0) <= t]

    def wait_needed(self, scope=""):
        """seconds until the soonest cooling key is usable again (None if no key will ever be)."""
        al = self.alive()
        if not al:
            return None
        t = self.now()
        return max(0.0, min(self.until.get((s.label, scope), 0) for s in al) - t)

    def ok(self, slot, scope=""):
        self.fails.pop((slot.label, scope), None)
        self.until.pop((slot.label, scope), None)

    def fail(self, slot, status, body="", headers=None, scope=""):
        """Record a failed call. Returns the kind. Applies dead / cooldown automatically."""
        kind, ra = classify(status, body, headers)
        k = (slot.label, scope)
        if kind == "dead":
            self.dead.add(slot.label)
        elif kind in ("rate", "server"):
            n = self.fails.get(k, 0) + 1
            self.fails[k] = n
            if "per day" in (body or "").lower() or "daily" in (body or "").lower():
                wait = 3 * 3600
            else:
                backoff = min(900, 20 * 2 ** (n - 1))                      # 20s, 40s, 80s ... 15 min
                wait = min(900, ra) if ra else backoff
                wait *= random.uniform(1.0, 1.25)                         # jitter
            self.until[k] = self.now() + wait
        elif kind == "model":
            self.bad_models.add(scope)
        return kind

    def status(self):
        t = self.now()
        out = []
        for s in self.slots:
            if s.label in self.dead:
                st = "dead"
            elif any(l == s.label and u > t for (l, _), u in self.until.items()):
                st = "cooling"
            else:
                st = "ok"
            out.append((s.label, st))
        return out


_RINGS = {}


def ring(provider):
    if provider not in _RINGS:
        _RINGS[provider] = Ring(provider)
    return _RINGS[provider]


def reset():
    _RINGS.clear()
    _json_cache.clear()


def misnamed_secrets():
    """Secrets/env vars that LOOK like an API key of a provider but do not follow the naming rule (typo finder)."""
    known = set()
    for p in PROVIDERS:
        known.update(names_for(p))
    hints = {"GROQ": "groq", "GEMINI": "gemini", "GOOGLE": "gemini", "ELEVEN": "elevenlabs", "XI_": "elevenlabs",
             "XAI": "xai", "GROK": "xai", "PEXELS": "pexels", "PIXABAY": "pixabay", "CANVA": "canva",
             "RUNWAY": "runway", "LUMA": "luma"}
    names = set(_secret_json()) | set(os.environ)
    skip = ("ELEVEN_VOICE", "ELEVEN_MODELS", "GROQ_SEARCH", "GROQ_TEXT", "GROQ_VISION", "ALL_SECRETS", "GITHUB")
    res = []
    for n in sorted(names):
        u = n.upper()
        if u in known or any(u.startswith(s) for s in skip):
            continue
        for h, p in hints.items():
            if h in u and any(w in u for w in ("KEY", "TOKEN", "SECRET")):
                res.append((n, p, PROVIDERS[p][0]))
                break
    return res
