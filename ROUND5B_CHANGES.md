# Round 5b - End card, loop-join, platform files (v8.5a -> v8.5b)
NEW:      endcard.py      Like / Share / Follow buttons + "Try NeuroTriage" pill, animated, inside the platform-safe area.
          variants.py     extra files per platform: Instagram/Facebook get their own 1080x1920 file (5 Mbps, 30 fps, AAC 44.1k).
                          4K YouTube file exists but is OFF by default (YT_4K=on to enable). 1080p master goes to YouTube.
          raw_edit.py, .github/workflows/edit_raw.yml, tests/test_round5bc.py (33 checks) - raw editor (detail in 5c notes).
MODIFIED: bot.py          render loop: end card, loop-join dissolve into frame 0 (LOOP_JOIN=off to disable), hook text from frame 0.
          publisher.py    picks the right file per platform (variants.pick).
Settings: YT_4K=off (default) | IG_FILE=on (default) | LOOP_JOIN=on | YT_4K_PRESET=veryfast
Checked offline only; no real GitHub run yet.

## 5b/5c fix pass
- variants.pick(): YouTube ab 4K file tabhi uthata hai jab YT_4K=on (purani _4k file se galti se upload nahi hoga).
- tests/test_round5bc.py: 4K default-off ke hisaab se; 4K check ab 1-sec clip par (test tez).
- Loop-join check kiya: 114 frames ~6 s (pehle 90 s wali slowness ab nahi). Raw editor 5 s clip ~50 s.
- Test chalane mein ~5 min lagte hain (video encode); offline hi test hua, GitHub par asli run abhi nahi.
