"""Round 12 - AI router. Chain: groq -> gemini (-> any OpenAI-compatible 'extra') -> None (caller uses local rules).
Uses keyring cooldowns (quota/429 is NOT retried on the same key), bounded backoff+jitter only for 5xx/timeouts,
validates JSON, caches by prompt hash. Never raises. Extra provider: LLM_EXTRA_URL / LLM_EXTRA_KEY / LLM_EXTRA_MODEL."""
import hashlib, json, os, random, re, time
from pathlib import Path
import keyring

CFG = {"retries": 2, "timeout": 60, "base": 1.5, "max_wait": 15, "max_calls": int(os.environ.get("AI_MAX_CALLS", "6"))}
MODELS = {"groq": "llama-3.3-70b-versatile", "gemini": "gemini-2.5-flash"}
STATS = {"calls": 0, "by": {}}


def _http(url, headers, body, params, timeout):
    import requests
    r = requests.post(url, headers=headers, json=body, params=params, timeout=timeout)
    try: js = r.json()
    except Exception: js = None
    return r.status_code, js, r.text[:300], dict(r.headers)


def _request(provider, key, prompt):
    if provider == "groq":
        return _http("https://api.groq.com/openai/v1/chat/completions", {"Authorization": f"Bearer {key}"},
                     {"model": MODELS["groq"], "temperature": 0.2, "response_format": {"type": "json_object"},
                      "messages": [{"role": "user", "content": prompt}]}, None, CFG["timeout"])
    if provider == "gemini":
        return _http(f"https://generativelanguage.googleapis.com/v1beta/models/{MODELS['gemini']}:generateContent", {}, 
                     {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}},
                     {"key": key}, CFG["timeout"])
    return _http(os.environ["LLM_EXTRA_URL"], {"Authorization": f"Bearer {key}"},
                 {"model": os.environ.get("LLM_EXTRA_MODEL", ""), "temperature": 0.2,
                  "messages": [{"role": "user", "content": prompt}]}, None, CFG["timeout"])


def _text(provider, js):
    if provider == "gemini": return js["candidates"][0]["content"]["parts"][0]["text"]
    return js["choices"][0]["message"]["content"]


def _parse(txt):
    txt = re.sub(r"^```(?:json)?|```$", "", (txt or "").strip(), flags=re.M).strip()
    try: return json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}|\[.*\]", txt, re.S)
        return json.loads(m.group(0)) if m else None


def _slots(provider):
    if provider == "extra":
        k = os.environ.get("LLM_EXTRA_KEY"); 
        return [type("S", (), {"label": "extra", "value": k})()] if k and os.environ.get("LLM_EXTRA_URL") else []
    try: return keyring.ring(provider).candidates(MODELS[provider])
    except Exception: return []


def ask_json(prompt, validate=None, cache_dir=None, order=("groq", "gemini", "extra")):
    """-> (data, provider) or (None, 'local'). validate(data)->cleaned or raises/returns None => try next provider."""
    key = hashlib.sha1(prompt.encode()).hexdigest()[:16]
    cf = Path(cache_dir) / f"ai_{key}.json" if cache_dir else None
    if cf and cf.exists():
        try: return json.loads(cf.read_text()), "cache"
        except Exception: pass
    for prov in order:
        for slot in _slots(prov):
            for attempt in range(CFG["retries"] + 1):
                if STATS["calls"] >= CFG["max_calls"]: return None, "local"      # hard per-run budget (free-tier safety)
                STATS["calls"] += 1; STATS["by"][prov] = STATS["by"].get(prov, 0) + 1
                try:
                    st, js, body, hd = _request(prov, slot.value, prompt)
                except Exception:
                    st, js, body, hd = 0, None, "timeout/network", {}
                if st == 200 and js:
                    try:
                        data = _parse(_text(prov, js))
                        data = validate(data) if validate else data
                        if data is None: raise ValueError("invalid")
                        if prov != "extra": keyring.ring(prov).ok(slot, MODELS[prov])
                        if cf:
                            try: cf.write_text(json.dumps(data))
                            except Exception: pass
                        return data, prov
                    except Exception:
                        break                                                    # bad content: next key/provider, no retry
                kind = "server"
                if prov != "extra":
                    try: kind = keyring.ring(prov).fail(slot, st, body, hd, MODELS[prov])
                    except Exception: pass
                if kind in ("server", "other") and attempt < CFG["retries"]:
                    time.sleep(min(CFG["max_wait"], CFG["base"] * 2 ** attempt + random.random())); continue
                break                                                            # rate/dead/model/bad_request: never retry same key
    return None, "local"
