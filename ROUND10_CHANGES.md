# Round 10 (v8.9 -> v9.0): polish pass on the talking-head editor
All in talking_head.py unless noted. New test: tests/test_round10.py (+ test_round9c.py).
1. Rotation fix (raw_edit.probe): phone clips stored 1920x1080 + rotate flag are now portrait 1080x1920 (was: LONG mode, face cropped).
2. Music/audio file mixed under the voice, auto-ducked, looped/trimmed (--audio, --audio-vol; workflow inputs audio/audio_vol; Studio picker).
3. Auto hook: when neither you nor the LLM gives a hook, one is built from the first real sentence (greetings stripped, max 6 words); last resort "END TAK DEKHO". Hook is on screen from frame 0.
4. Footage enhance: samples 8 frames, lifts only dim/flat/blown footage (eq brightness/gamma/contrast) + light sharpen. TH_ENHANCE=off disables. Well-lit clips are left almost untouched.
5. Voice clean-up: high-pass, light de-noise, compressor, presence EQ, then -14 LUFS.
6. Sound effects: synthetic whoosh at every card transition and a pop at the end card (no asset files). --no-sfx disables.
7. cover.jpg (hook + face at 0.5s) is written, uploaded to the release and used as the YouTube thumbnail by th_publish.py.
8. th_report.json now also has hook, music, sfx.
9. tests/test_round5a.py: stale assertion updated (publisher uses bool(synthetic); Studio uploads pass synthetic=False because it is a real person).
Known, pre-existing: tests/test_round4.py "Long workflow: manual only..." fails on the original upload too (not touched).
NOT verified here (no network): real Whisper accuracy, LLM planner, Studio page + workflows on GitHub/Vercel, ducking balance on a long real clip.
