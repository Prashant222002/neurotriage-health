# Round 7 (v8.6 -> v8.7)
NEW: analytics.py + .github/workflows/analytics.yml - weekly best posting time (moves Short/Long slot max 1h/week, window 07-22 IST); scheduler.py reads state/best_time.json (BEST_TIME=off ignores)
     dashboard/ - Vercel PWA (build Short/Long with voice choice, edit raw, publish, status, download); README.md inside
     KEYS_CHART.pdf, tests/test_round7.py (2 error-test rounds)
NOT done: Whisper/TTS router, extra transitions. Dashboard + analytics never run on real GitHub/Vercel yet.
