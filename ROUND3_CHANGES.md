# Round 3 - Research engine + Script Lock + AI memory (v8.2 -> v8.3)
NEW:      research.py        claims -> PubMed/Wikipedia evidence -> LLM fact-check -> HARD python number filter -> verified fact sheet + sources
          project_state.py   shared project memory per video (research, locked script + versions, stages, which AI did what) + SCRIPT LOCK
          brand_logo.py      circle logo (ring + shadow), asset gate, fade-in, one place for every use
          assets/logo.png    your logo (brain-heart-leaf)
          tests/test_round3.py (70 checks)
MODIFIED: bot.py             ask() adds the project-state block to every text prompt + records provider; research() uses the engine;
                             script locked in short AND long; VIDEO_TYPE (short|long|both); Sources line in descriptions; top loading bar removed
          long_render.py / motion_graphics.py   circle logo (corner, end card, thumbnail); bottom progress bar + ticks removed
          publisher.py       automatic runs = Short only (AUTO_LONG=off). Long only when asked.
          build.yml          inputs: video_type, publish_when (scheduled|now), publish_time_ist, unlock_script; state/ committed
          older tests        redirect project_state folders to tmp (no behaviour change)
Secrets: none new.
