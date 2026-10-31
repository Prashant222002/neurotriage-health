# Round 4 - Speed + control (v8.3 -> v8.4)
NEW:      .github/workflows/build_long.yml   Long video, manual only. Same concurrency group as build.yml => never two videos at once.
          tests/test_round4.py (24 checks)
MODIFIED: build.yml     now SHORT ONLY (cron 00:00 + catch-ups + manual). video_type/force_long inputs removed. Footage cache.
          bot.py        pick_clips_batch(): parallel stock search -> vision in batches of 4 scenes (multi-image call) -> parallel download.
                        Search cache (7 days), clip cache (work/footage, pruned to 1500 MB), no-repeat of clips used in the last 14 days.
                        ask_groq / Gemini accept several images in one call.
Settings (env): VISION_BATCH=4, PREFETCH_THREADS=4, FOOTAGE_CACHE_MB=1500, FOOTAGE_NO_REPEAT_DAYS=14
Secrets: none new.
