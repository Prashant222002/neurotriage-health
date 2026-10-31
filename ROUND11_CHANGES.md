# Round 11: Claude Video Effects layer (additive)
- NEW fx_bridge.py + vendor/claude_fx/ (fx.py, fonts, models; MIT). talking_head.stage3 calls it after mux, wrapped in try/except.
- Safe set by default: backdrop-word, spotlight, moody. Camera/zoom effects (lean-in, locked-on) opt-in: TH_FX_CAMERA=1 (they would push captions out of the safe area).
- Planner: local rules by default (0 API calls). TH_FX_LLM=1 -> ONE batched call per video via existing _llm (Groq->Gemini), cached in work/, output validated against REGISTRY, never executed.
- Max 4 effects, >=2.5s apart, none in first 1.3s (hook) or last 3.2s (endcard), 1.2-2.6s long.
- Failure policy: full plan -> simpler fallback plan -> original video untouched. Output accepted only if duration (+-0.35s), audio presence and size check out. Original saved as final_th_clean.mp4 when effects applied. th_report.json has "fx".
- TH_FX=off disables. Requires mediapipe (added to requirements.txt).
- Tests: tests/test_round11.py (offline). Verified: validation, LLM-garbage fallback, forced render failure, real render on synthetic 360x640 clip.
- NOT verified: real face footage look, long (>5 min) videos, Gemini live call, HyperFrames (see below).
- HyperFrames NOT integrated: it is a Node/headless-browser renderer; needs Node+Chromium that this sandbox lacks. Planned as a separate adapter (HTML scene -> mp4 -> ffmpeg overlay), not started.
