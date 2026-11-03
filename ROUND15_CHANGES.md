# Round 15: Auto dashboard on Vercel (`/auto`)

## Apna topic
- `build.yml` / `build_long.yml` have two new inputs: `topic`, `topic_notes`. Empty topic = old automatic behaviour.
- With a topic, `bot.py` skips trend/rotation and researches exactly that topic (`manual_plan()`), builds Short and/or Long.
- The run gets its own id (`<date>-<kind>-m<run_id>`), checkpoints and artifact, so the daily video is never overwritten
  and the daily topic rotation is not moved.
- `publish_time_ist` typed on the dashboard now beats the learned best-time (`PUBLISH_TIME_*_FORCE`).
- GitHub run title shows the topic (`run-name`).

## Dashboard `/auto` (dashboard/auto.html)
- Topic box, Short / Long / Dono, upload: schedule / ~25 min baad / turant.
- Live progress bar + ETA per build (`/api/build-status`).
- Per video: platform status. Platforms that did NOT auto-upload (failed / skipped, e.g. Instagram API blocked,
  Facebook secrets missing) get a "Manual upload" box: time (IST), title, description, tags, caption, each with Copy.
- Download button + Delete button (`/api/storage`). Delete asks before removing a video that still needs upload.
- "Storage khali karo": GitHub extra copies + finished videos, Vercel Blob raw uploads older than 1 hour.

## Vercel env (same as before, plus)
`DASH_PASSWORD`, `GH_TOKEN` (Actions r/w + Contents r), `GH_REPO`, `BLOB_READ_WRITE_TOKEN` (only for Blob cleanup).
