# Round 12: AI router + quality gate + HyperFrames-style motion blocks (additive)
Pipeline in stage3 (enhance.py, never raises): mux -> backup final_th_clean.mp4 -> motion blocks -> Claude-Effects -> quality gate -> report["fx"].
- ai_router.py: groq -> gemini -> optional OpenAI-compatible extra (LLM_EXTRA_URL/KEY/MODEL, e.g. OpenRouter/Mistral free). Uses keyring cooldowns; 429/quota NOT retried on same key; 5xx/timeout bounded backoff+jitter; JSON validated; cached; AI_MAX_CALLS (default 6) per run; all fail -> local rules.
- AI is OFF by default (TH_FX_LLM=1 turns on). Core never depends on it.
- motion_blocks.py: stat_counter, bar_chart (9:16 only). Numbers must literally appear in the transcript (no invented data). Placement avoids face, caption zone, insert cards; no safe spot -> skipped. Max 2 blocks, >=6s apart. TH_BLOCKS=off disables.
- quality_gate.py: integrity, duration drift, audio present, black frames, freeze, loudness (-20..-10 LUFS), clipping, exposure, contrast, sharpness, face presence. Score 0-100, PASS>=75. Enhanced version is kept ONLY if not worse than clean; otherwise reverted automatically. Verdict in th_report.json fx.quality.
- TH_ENHANCE_ALL=off disables everything above.
- Tests: tests/test_round12.py (offline). NOT verified: real face footage, >5 min videos, live APIs, real HyperFrames (Node+Chrome unavailable here; its blocks have fixed content, so only styles were re-created natively).

# Round 13: silent / B-roll footage mode (silent_mode.py)
Footage with no speech (no audio or <8% voiced) no longer stops the engine: `--topic "..."` and/or `--script "..."`.
Script: your --script > AI (ai_router, needs --topic; length-fit, no diagnosis/cure/stat claims) > none. Voice: ElevenLabs Hinglish -> edge-tts English. Music by topic: calm/mental-health -> flute, else soft pad (offline).
Fallback: no script or TTS down -> music-only (footage + normalised music, NO invented narration). Hook = AI hook or clean topic words. TH_SILENT=off disables. Real-speech clips are untouched.
Test: tests/test_round13.py (TTS mocked). NOT verified: real ElevenLabs/edge-tts voice, real AI script quality, footage-aware (vision) scripting.
Known: hook panel can cover the face in frame 0-2s (pre-existing design); quality gate does not yet check that.
