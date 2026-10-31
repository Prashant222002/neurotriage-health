"""ElevenLabs voice for the NeuroTriage bot.

- 10 API keys (ELEVEN_API_KEY_1 .. _12): the key with the most credits left goes first;
  a key that fails (401 quota / unusual activity / invalid) is skipped for the whole run.
- Model fallback (ELEVEN_MODELS) and voice fallback (ELEVEN_VOICE_IDS).
- Uses /with-timestamps so captions stay word-synced. Output is converted to the same
  (audio_bytes, events) shape edge-tts gives, so bot.synth_scene needs only 3 changed lines.
- Any total failure raises ElevenError -> bot falls back to edge-tts with ENGLISH text.
"""
import base64
import os
import time
from datetime import date

import requests

API = "https://api.elevenlabs.io/v1"


class ElevenError(RuntimeError):
    pass


def _env_list(name, default):
    v = os.environ.get(name, "").strip()
    return [x.strip() for x in v.split(",") if x.strip()] if v else list(default)


def load_keys():
    """Round 2: names come from keyring.py (ELEVEN_API_KEY, ELEVEN_API_KEY_1..10 + aliases such as ELEVENLABS_API_KEY,
    XI_API_KEY; also read from ALL_SECRETS_JSON). Duplicates merged."""
    import keyring
    slots = keyring.load("elevenlabs")
    _LABEL.update({sl.value: sl.label for sl in slots})
    return [sl.value for sl in slots]


_LABEL = {}                       # key value -> secret name (for logs; the key itself is never printed)


MODELS = _env_list("ELEVEN_MODELS", ["eleven_multilingual_v2", "eleven_v3",
                                     "eleven_turbo_v2_5", "eleven_flash_v2_5"])
# Rachel + George are ElevenLabs premade voices (work on free keys). Put your Indian/Hindi
# voice id FIRST in ELEVEN_VOICE_IDS.
VOICES = _env_list("ELEVEN_VOICE_IDS", ["21m00Tcm4TlvDq8ikWAM", "JBFqnCBsd6RMkjVDRZzb"])
SPEED = [1.0]          # bot raises this (1.0 -> 1.08 -> 1.15) when narration runs too long

_KEYS = load_keys()
_BAD = set()           # keys dead for this run
_REMAIN = {}           # key -> credits left (best effort)
_state = {"checked": False, "last_error": ""}


def available():
    return bool(_KEYS) and len(_BAD) < len(_KEYS)


def _remaining(key):
    try:
        r = requests.get(f"{API}/user/subscription", headers={"xi-api-key": key}, timeout=20)
        if r.status_code == 200:
            j = r.json()
            return int(j.get("character_limit", 0)) - int(j.get("character_count", 0))
        if r.status_code in (401, 403):
            return -1
    except Exception:
        pass
    return None           # unknown -> still try it


def _check_balances():
    if _state["checked"]:
        return
    _state["checked"] = True
    for k in _KEYS:
        rem = _remaining(k)
        if rem is not None and rem <= 0:
            _BAD.add(k)
        elif rem is not None:
            _REMAIN[k] = rem


def _ordered_keys(need_chars):
    _check_balances()
    live = [k for k in _KEYS if k not in _BAD]
    # most credits first; unknown balance counts as "plenty"; rotate ties by day
    off = date.today().toordinal() % max(1, len(live))
    live = live[off:] + live[:off]
    return sorted(live, key=lambda k: -(_REMAIN.get(k, 10 ** 6)))


def _settings(model):
    if model == "eleven_v3":                 # v3 only accepts stability 0 / 0.5 / 1
        return {"stability": 0.5}
    s = {"stability": 0.42, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True}
    if model in ("eleven_multilingual_v2", "eleven_turbo_v2_5", "eleven_flash_v2_5"):
        s["speed"] = max(0.7, min(1.2, SPEED[0]))
    return s


def _call(key, voice, model, text):
    r = requests.post(
        f"{API}/text-to-speech/{voice}/with-timestamps",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        json={"text": text, "model_id": model, "voice_settings": _settings(model)},
        timeout=90)
    return r


def _words_from_alignment(al):
    """character alignment -> [('WordBoundary', start, dur, word)] (edge-tts event shape)."""
    ch = al["characters"]
    st = al["character_start_times_seconds"]
    en = al["character_end_times_seconds"]
    ev, cur, t0, t1 = [], "", None, None
    for c, a, b in zip(ch, st, en):
        if c.isspace():
            if cur:
                ev.append(("WordBoundary", t0, max(0.05, t1 - t0), cur))
                cur, t0 = "", None
            continue
        if t0 is None:
            t0 = a
        cur += c
        t1 = b
    if cur:
        ev.append(("WordBoundary", t0, max(0.05, t1 - t0), cur))
    return ev


def tts(text):
    """Returns (mp3_bytes, events). Raises ElevenError if every key/model/voice failed."""
    if not available():
        raise ElevenError("no usable ElevenLabs key")
    errors = []
    for model in MODELS:
        for voice in VOICES:
            skip_voice = False
            for key in _ordered_keys(len(text)):
                if skip_voice:
                    break
                if key in _BAD:
                    continue
                tag = f"{_LABEL.get(key, 'key')}/{model}/{voice[:6]}"
                for attempt in range(2):
                    try:
                        r = _call(key, voice, model, text)
                    except requests.RequestException as e:
                        errors.append(f"{tag}: net {str(e)[:60]}")
                        time.sleep(1.5)
                        continue
                    if r.status_code == 200:
                        j = r.json()
                        al = j.get("alignment") or j.get("normalized_alignment")
                        if not al:
                            errors.append(f"{tag}: no alignment")
                            break
                        _REMAIN[key] = _REMAIN.get(key, 10 ** 6) - len(text)
                        return base64.b64decode(j["audio_base64"]), _words_from_alignment(al)
                    body = r.text[:160].replace("\n", " ")
                    errors.append(f"{tag}: {r.status_code} {body}")
                    if r.status_code == 429:          # too many concurrent requests -> wait, retry
                        time.sleep(3)
                        continue
                    if r.status_code in (401, 402, 403):
                        if "voice" in body.lower() or "paid_plan" in body.lower():
                            skip_voice = True          # voice problem, not the key -> next voice
                            break
                        _BAD.add(key)                  # quota / unusual activity / invalid key
                    break
    _state["last_error"] = " | ".join(errors[-6:])
    raise ElevenError(_state["last_error"] or "ElevenLabs failed")


def status():
    return {"keys": len(_KEYS), "dead": len(_BAD), "last_error": _state["last_error"]}


def health(test_voice=True):
    """Dashboard / CLI check. Per key: valid? credits left? Then ONE tiny real generation (3 characters) with the
    first usable key + first voice + first model, so a wrong voice id / model id is caught BEFORE a long build.
    Never returns or prints a key."""
    _check_balances()
    rows = []
    for k in _KEYS:
        lab = _LABEL.get(k, "key")
        rem = _REMAIN.get(k)
        if k in _BAD:
            rows.append({"key": lab, "status": "dead/no-credit", "credits_left": rem})
        else:
            rows.append({"key": lab, "status": "ok", "credits_left": rem})
    test = None
    if test_voice and _KEYS:
        live = [k for k in _KEYS if k not in _BAD]
        if not live:
            test = {"ok": False, "why": "no key with credits"}
        else:
            try:
                r = _call(live[0], VOICES[0], MODELS[0], "Hi.")
                if r.status_code == 200 and (r.json().get("alignment") or r.json().get("normalized_alignment")):
                    test = {"ok": True, "voice": VOICES[0], "model": MODELS[0]}
                else:
                    test = {"ok": False, "http": r.status_code, "why": r.text[:140].replace("\n", " "),
                            "voice": VOICES[0], "model": MODELS[0]}
            except Exception as e:
                test = {"ok": False, "why": str(e)[:120]}
    return {"configured_keys": len(_KEYS), "keys": rows, "test_generation": test,
            "voices": VOICES, "models": MODELS}
