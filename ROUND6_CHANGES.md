# Round 6 (v8.5c -> v8.6)
NEW: flute.py (calming flute music, per-video melody; MUSIC_STYLE=pad = old music)
     long_render.py: zoom pops every ~3.4 s (ZOOM_POPS=off to disable)
     bot.py: LONG_VOICE = auto (default: ElevenLabs 2.5-min long video while credits last, then free TTS) | eleven | local (7 min free)
             LONG_ELEVEN_MIN (2.5), LONG_MINUTES (7)
     build_long.yml: weekly auto Long (Sunday 00:00 IST), manual inputs: voice_engine, eleven_voice_id, edge_voice
     tests/test_round6.py (9 checks, offline)
NOT done: Whisper/TTS router, extra transitions, documentary-style polish (next round). Not run on GitHub yet.
