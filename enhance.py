"""Round 12 - enhancement orchestrator: motion blocks -> Claude-Effects -> quality gate. Never raises; final file always playable.
final_th.mp4 is the shipped file; final_th_clean.mp4 is the untouched pre-enhancement render (kept only if enhancements were applied)."""
import os, shutil
from pathlib import Path
import ai_router, fx_bridge, motion_blocks as mb, quality_gate as qg


def run(final, nw, total, events, land, work, log=print):
    final = Path(final); out = final.parent; clean = out / "final_th_clean.mp4"; rep = {"steps": []}
    if os.environ.get("TH_ENHANCE_ALL", "on") == "off": rep["status"] = "disabled"; return rep
    try: shutil.copy2(final, clean)
    except Exception as e: rep["status"] = f"skipped:cannot-backup({type(e).__name__})"; return rep
    text = " ".join(w[0] for w in nw); busy = [(float(e.get("at", 0)), float(e.get("at", 0)) + float(e.get("dur", 3.5))) for e in events if e.get("at") is not None]
    use_ai = os.environ.get("TH_FX_LLM") == "1"
    # 1) motion blocks (portrait only)
    try:
        if not land and os.environ.get("TH_BLOCKS", "on") != "off":
            plan = mb.validate(mb.plan_from_words(nw, total), total, text, busy); src = "rules"
            if use_ai:
                stamped = " ".join(f"{w[0]}@{w[1]:.1f}" for w in nw[::2])[:3500]
                data, prov = ai_router.ask_json(
                    f"Video {total:.0f}s. Pick <=2 data visuals ONLY from numbers literally spoken. JSON {{\"blocks\":[{{\"block\":\"stat_counter\",\"start\":s,\"end\":s,\"value\":\"70%\",\"label\":\"..\"}},"
                    f"{{\"block\":\"bar_chart\",\"start\":s,\"end\":s,\"title\":\"..\",\"items\":[[\"A\",30],[\"B\",50]]}}]}}. Words@time: {stamped}",
                    validate=lambda d: d.get("blocks") if isinstance(d, dict) and isinstance(d.get("blocks"), list) else None, cache_dir=work)
                ai = mb.validate(data, total, text, busy) if data else []
                if ai: plan, src = ai, prov
            if plan:
                tmp = out / "final_th_blocks.mp4"
                try:
                    done = mb.composite(final, tmp, plan)
                    if qg.measure(tmp).get("ok"): tmp.replace(final); rep["steps"].append({"blocks": [{k: b[k] for k in ("block", "start", "end")} for b in done], "planner": src, "status": "applied"})
                    else: raise RuntimeError("bad-output")
                except Exception as e:
                    rep["steps"].append({"blocks": "skipped", "reason": str(e)[:100]}); tmp.unlink(missing_ok=True)
    except Exception as e: rep["steps"].append({"blocks": "error", "reason": type(e).__name__})
    # 2) Claude effects
    try:
        fplan, fsrc = fx_bridge.plan_effects(nw, total, (lambda p: ai_router.ask_json(p, cache_dir=work)[0]) if use_ai else None, work)
        # keep fx away from cards/inserts and data blocks (they overlapped before)
        _busy = list(busy) + [(float(b['start']) - .3, float(b['end']) + .3) for b in (locals().get('plan') or []) if isinstance(b, dict) and 'start' in b]
        fplan = [f for f in fplan if not any(f['start'] < be and f['end'] > bs for bs, be in _busy)]
        if fplan:
            tmp = out / "final_th_fx.mp4"; res, st = fx_bridge.apply_effects(final, tmp, fplan, {})
            if Path(res) == tmp and tmp.exists(): tmp.replace(final)
            rep["steps"].append({"fx": fplan, "planner": fsrc, "status": st})
    except Exception as e: rep["steps"].append({"fx": "error", "reason": type(e).__name__})
    # 3) quality gate: keep enhancements only if not worse than clean
    try:
        rep["quality"] = qg.review(final, clean, True, not land, total)
        if clean.exists() and not rep["quality"].get("reverted_to_clean") and not any(s.get("status") in ("applied",) or str(s.get("status", "")).startswith("fallback") for s in rep["steps"]):
            clean.unlink(missing_ok=True)                 # nothing was applied -> no duplicate file
    except Exception as e: rep["quality"] = {"ok": False, "verdict": "GATE-ERROR", "err": type(e).__name__}
    rep["ai_calls"] = dict(ai_router.STATS); rep["status"] = "done"
    log("[th] enhance:", rep.get("status"), rep.get("quality", {}).get("verdict"), rep.get("quality", {}).get("score"))
    return rep
