# API KEYS - naming chart (Round 2)

**Rule:** `NAME`, `NAME_2`, `NAME_3` ... up to `NAME_10`.  (`NAME` and `NAME_1` both mean key #1.)
Same key pasted under two names = counted once, so two secrets can never fight each other.
Add them in GitHub: Repo -> Settings -> Secrets and variables -> Actions -> New repository secret.
Adding `GROQ_API_KEY_6` etc. needs **no workflow edit** (workflow passes all secrets).

| Provider | Secret names (exact) | Needed? | Used for |
|---|---|---|---|
| Groq | `GROQ_API_KEY`, `GROQ_API_KEY_2` ... | one of Groq/Gemini | script, research, clip choice (primary) |
| Gemini | `GEMINI_API_KEY`, `GEMINI_API_KEY_2` ... | one of Groq/Gemini | fallback LLM + vision |
| ElevenLabs | `ELEVEN_API_KEY_1` ... `ELEVEN_API_KEY_10`, `ELEVEN_VOICE_IDS` (comma list, Hinglish voice first) | optional | Reel Hinglish voice |
| Pexels | `PEXELS_API_KEY`, `PEXELS_API_KEY_2` ... | Pexels or Pixabay | stock video |
| Pixabay | `PIXABAY_API_KEY`, `PIXABAY_API_KEY_2` ... | Pexels or Pixabay | stock video |
| YouTube Data | `YT_API_KEY` | optional | viral research |
| Grok (xAI) | `XAI_API_KEY`, `XAI_API_KEY_2` ... | slot only | used from a later round |
| Canva | `CANVA_API_KEY` ... | slot only | later round |
| Runway / Luma | `RUNWAY_API_KEY` ..., `LUMA_API_KEY` ... | slot only | later round (no free quota guaranteed) |

Also accepted (so old names keep working): `ELEVENLABS_API_KEY`, `XI_API_KEY`, `GOOGLE_API_KEY`, `GROK_API_KEY`.
Anything else that looks like a key but is named differently is **reported by the health check** as "WRONGLY NAMED".

## Settings (in build.yml `env:`)
- `LONG_VOICE: local` -> Long video uses free English TTS (ElevenLabs credits saved). `eleven` -> Hinglish ElevenLabs.
- `ELEVEN_FALLBACK: english` -> if ElevenLabs fails, English TTS **with a loud WARNING**. `fail` -> stop instead.

## Check it
Actions -> Midnight Build -> first step "API key health check" (also shown in the run Summary): per key OK / DEAD / LIMIT, ElevenLabs credits + a 3-character test voice, wrongly-named secrets.
Local: `python healthcheck.py`.
