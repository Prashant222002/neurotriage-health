# Round 8 (v8.7 -> v8.8): Talking-head modern edit
NEW talking_head.py + .github/workflows/talking_head.yml + dashboard card + tests/test_round8.py
Flow: Whisper (Groq, else faster-whisper) word times -> silence cut (gap>0.38s) + jump-cut zoom 1.0/1.09x -> LLM (Groq->Gemini) reads transcript and
places cards/inserts WHERE the topic is spoken (keyword fallback if no LLM) -> word-by-word red/white glow captions, emphasis punch-in,
title/terminal/profile/graph cards, your screen recordings in glow border (file name = topic hint), red-shard + whip transitions, logo, end card.
Run: python talking_head.py --video raw/clip.mp4 [--inserts a.mp4,b.png] [--style red|white] [--hook X] [--no-cuts]
NOT done: whoosh/sound effects, Devanagari captions (Whisper asked for Roman script), real Whisper/LLM never run here (no network) - first real run = check th_report.json.

# Round 9 (v8.8 -> v8.9): Studio page
dashboard/index.html = Studio (Blob upload or YouTube link -> talking_head.yml -> release th-<job> -> preview/download -> password -> th_publish.yml -> YouTube).
api/studio-{upload,run,status,file,publish}.js, th_publish.py, th_publish.yml; old panel moved to /control. talking_head writes meta (title/desc/tags) from the transcript.
Needs: Blob store, STUDIO_PASSWORD env, YT_* secrets (already used by publisher). yt-dlp on GitHub IPs can be blocked by YouTube -> upload the file instead.

# Round 9b
talking_head.py split into --stage 1/2/3 (live progress); landscape input = 16:9 LONG mode (no end card); render ~2x faster (cached glow/cards, trimmed captions); variants skipped in Studio.
Studio: calm UI, password on edit/upload/publish, progress % + time left, Short -> YT+IG+FB, Long -> YT only. th_publish.py reports per-platform result.
