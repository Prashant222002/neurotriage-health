"""Round 11 - Claude Video Effects bridge (additive; nothing existing is replaced).
plan_effects(): local rules (+ optional ONE batched LLM call, validated against REGISTRY) -> safe effect plan.
apply_effects(): runs the vendored fx.py with timeout; on failure retries simpler, else returns the ORIGINAL video untouched.
Never raises. TH_FX=off disables. Output is accepted only if ffprobe confirms duration/size/audio."""
import hashlib, json, os, re, subprocess, sys, tempfile
from pathlib import Path

FX_PY = Path(__file__).parent / "vendor" / "claude_fx" / "scripts" / "fx.py"
# id -> defaults. camera=True effects zoom the whole frame (would push captions out of safe area) so they are opt-in (TH_FX_CAMERA=1).
REGISTRY = {
    "backdrop-word": {"max": 2.6, "needs_text": True, "camera": False, "fallback": "spotlight"},
    "spotlight":     {"max": 2.6, "needs_text": False, "camera": False, "fallback": "moody"},
    "moody":         {"max": 4.0, "needs_text": False, "camera": False, "fallback": None},
    "lean-in":       {"max": 2.0, "needs_text": False, "camera": True,  "fallback": "moody"},
    "locked-on":     {"max": 3.0, "needs_text": False, "camera": True,  "fallback": "spotlight"},
}
CFG = {"timeout_per_min": 240, "max_fx": 4, "min_gap": 2.5, "head_safe": 1.3, "tail_safe": 3.2, "min_len": 1.2}
STOP = set("the a an is are was to of and in on for it this that you your yeh hai ka ki ke ko se me mein aur toh ek hi".split())


def _log(*a): print("[fx]", *a, flush=True)


def probe(p):
    j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                                   "-of", "json", str(p)], capture_output=True, text=True, timeout=30, check=True).stdout)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    return {"dur": float(j["format"]["duration"]), "w": v["width"], "h": v["height"],
            "audio": any(s["codec_type"] == "audio" for s in j["streams"])}


def _allowed():
    cam = os.environ.get("TH_FX_CAMERA", "1") != "0"       # Round 15: zoom-in/lock-on camera effects ON by default (TH_FX_CAMERA=0 turns off)
    return {k for k, v in REGISTRY.items() if cam or not v["camera"]}


def validate(plan, dur):
    """Whitelist ids, clamp times/length, drop overlaps + head/tail zones. Returns clean list (maybe empty)."""
    ok, last = [], -99.0
    allowed = _allowed()
    for e in sorted((x for x in (plan or []) if isinstance(x, dict)), key=lambda x: float(x.get("start", 0) or 0)):
        try:
            fx = str(e["fx"]).lower().strip()
            if fx not in allowed: continue
            s = max(float(e["start"]), CFG["head_safe"]); en = min(float(e["end"]), dur - CFG["tail_safe"], s + REGISTRY[fx]["max"])
            if en - s < CFG["min_len"] or s < last + CFG["min_gap"]: continue
            d = {"fx": fx, "start": round(s, 2), "end": round(en, 2)}
            txt = re.sub(r"[^\w \-!?%&]", "", str(e.get("text", ""))).strip().upper()[:18]
            if REGISTRY[fx]["needs_text"]:
                if not txt: continue
                d["text"] = txt
            elif txt and fx == "spotlight": d["text"] = txt
            ok.append(d); last = en
        except Exception:
            continue
        if len(ok) >= CFG["max_fx"]: break
    return ok


def heuristic_plan(words, dur):
    """words: [(text,start,end)]. Round 15: rotates backdrop-word / lean-in (zoom punch) / spotlight / locked-on (camera follows face)
    over the clip. Text effects sit on the longest nearby content word; camera effects just need a time slot."""
    if not words or dur < 8: return []
    cands = [(len(re.sub(r"\W", "", w[0])), w[1], re.sub(r"\W", "", w[0])) for w in words
             if len(re.sub(r"\W", "", w[0])) >= 6 and w[0].lower().strip(".,!?") not in STOP]
    order = ["backdrop-word", "lean-in", "spotlight", "locked-on"] if _allowed() >= {"lean-in", "locked-on"} else ["backdrop-word", "spotlight"] * 2
    fracs = (0.2, 0.4, 0.6, 0.8) if len(order) == 4 else (0.25, 0.5, 0.75)
    plan = []
    for i, sl in enumerate([dur * f for f in fracs]):
        fx = order[i % len(order)]
        near = [c for c in cands if abs(c[1] - sl) < dur * 0.1]
        n, t, txt = max(near) if near else (0, sl, "")
        if REGISTRY[fx]["needs_text"] and not txt: continue
        plan.append({"fx": fx, "start": t - 0.1, "end": t + (2.0 if fx in ("lean-in", "locked-on") else 2.2), "text": txt})
    return plan


def llm_plan(words, dur, llm, cache_dir=None):
    """ONE batched call for the whole video (free-tier safe), cached by content hash. Output is validated, never executed."""
    if llm is None or not words: return None
    txt = " ".join(w[0] for w in words)[:3500]
    key = hashlib.sha1((txt + f"{dur:.0f}" + ",".join(sorted(_allowed()))).encode()).hexdigest()[:16]
    cf = Path(cache_dir) / f"fx_plan_{key}.json" if cache_dir else None
    if cf and cf.exists():
        try: return json.loads(cf.read_text())
        except Exception: pass
    stamped = " ".join(f"{w[0]}@{w[1]:.1f}" for w in words[::3])[:3500]
    prompt = (f"Video {dur:.0f}s. Choose at most {CFG['max_fx']} restrained visual effects, spaced >{CFG['min_gap']}s, only on key words. "
              f"Allowed fx: {sorted(_allowed())}. backdrop-word needs short 'text' (<=18 chars). Return JSON "
              f'{{"effects":[{{"fx":"..","start":s,"end":s,"text":".."}}]}}. Words@time: {stamped}')
    try:
        raw = llm(prompt)
        data = json.loads(raw) if isinstance(raw, str) else raw
        plan = data.get("effects") if isinstance(data, dict) else data
        if isinstance(plan, list) and cf:
            cf.write_text(json.dumps(plan))
        return plan if isinstance(plan, list) else None
    except Exception as ex:
        _log("llm plan failed ->", type(ex).__name__); return None


def plan_effects(words, dur, llm=None, cache_dir=None):
    plan = validate(llm_plan(words, dur, llm, cache_dir), dur)
    src = "llm"
    if not plan: plan, src = validate(heuristic_plan(words, dur), dur), "rules"
    return plan, src


def _run(src, dst, plan, info, timeout):
    with tempfile.TemporaryDirectory() as td:
        pj = Path(td) / "plan.json"; pj.write_text(json.dumps({"effects": plan}))
        short = min(1080, min(info["w"], info["h"]))
        r = subprocess.run([sys.executable, str(FX_PY), "--plan", str(pj), "--width", str(short - short % 2), str(src), str(dst)],
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0: raise RuntimeError((r.stderr or r.stdout)[-200:])


def _good(dst, info):
    o = probe(dst)
    return abs(o["dur"] - info["dur"]) < 0.35 and o["audio"] == info["audio"] and o["h"] > 0 and Path(dst).stat().st_size > 10_000


def apply_effects(src, dst, plan, report=None):
    """Returns (path_to_use, status). status: applied | fallback:<fx> | skipped:<reason>. Always a playable path (src if all fails)."""
    rep = report if report is not None else {}
    src, dst = Path(src), Path(dst)
    if os.environ.get("TH_FX", "auto") == "off": return src, "skipped:disabled"
    if not plan: return src, "skipped:empty-plan"
    if not FX_PY.exists(): return src, "skipped:vendor-missing"
    try: info = probe(src)
    except Exception as ex: return src, f"skipped:unreadable-source({type(ex).__name__})"
    tmo = max(60, int(CFG["timeout_per_min"] * info["dur"] / 60) + 60)
    attempts = [("full", plan)]
    simple = [dict(e, fx=(REGISTRY[e["fx"]]["fallback"] or e["fx"])) for e in plan]
    simple = [e for e in validate(simple, info["dur"]) if e["fx"] in REGISTRY]
    if simple and simple != plan: attempts.append(("fallback", simple))
    rep["attempts"] = []
    for name, p in attempts:
        try:
            if dst.exists(): dst.unlink()
            _run(src, dst, p, info, tmo)
            if _good(dst, info):
                rep["attempts"].append({"try": name, "ok": True, "effects": p})
                return dst, "applied" if name == "full" else "fallback:" + ",".join(e["fx"] for e in p)
            raise RuntimeError("output failed integrity check")
        except Exception as ex:
            rep["attempts"].append({"try": name, "ok": False, "error": str(ex)[:200]}); _log(name, "failed:", str(ex)[:120])
            try: dst.unlink()
            except Exception: pass
    return src, "skipped:all-attempts-failed"
