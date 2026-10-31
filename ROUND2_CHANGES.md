# Round 2 - Multi-key engine
NEW:      keyring.py (naming, aliases, dedupe, cooldown/backoff/dead-key logic), healthcheck.py, KEYS.md
MODIFIED: bot.py          Groq+Gemini rewritten on keyring: verified models only (primary/fallback/recovery), per-(key,model)
                          cooldown, Retry-After, jitter, JSON-400 salvage, wait-once-if-all-rate-limited; Pexels/Pixabay key
                          rotation; make_voice(engine=) + ELEVEN_FALLBACK policy + loud warnings; Long video LONG_VOICE=local
          eleven_voice.py keys via keyring (aliases), logs secret NAME not key text, health()
          build.yml       health-check step, ALL_SECRETS_JSON, LONG_VOICE, ELEVEN_FALLBACK
TESTS:    test_round2.py (33 checks), test_round2_health.py; older tests updated for new make_voice signature
