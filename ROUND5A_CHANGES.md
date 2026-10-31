# Round 5a - Topics + opening + caption fix (v8.4 -> v8.5a)
NEW:      topics.py        trending-first planner: Google Trends India (+YouTube trending if YT_API_KEY) -> tragedy/politics/betting filtered
                           -> 1 small LLM call judges fit. No fit => rotation: psychiatric disorder, habit, disorder, habit...
                           28 disorders + 28 habits, each used once per cycle; 12 student types rotate; never same subject twice in a row;
                           a trend is not reused for 3 days. State: state/topic_rotation.json (already committed by build.yml).
          hook_intro.py    big hook text from frame 0 (2.3 s) - white flash removed, fallback frame is navy not white.
          tests/test_round5a.py (32 checks)
MODIFIED: caption_styles.py  one shared paginate(): a caption page never ends with "MOVE-" (dash stays with next word). bot.Captions uses it too.
          bot.py             topic plan stage (checkpointed) -> MANDATORY topic directive in research; hook_text in script JSON; share-bait rules;
                             rotation recorded only after a good build; planner failure falls back to old alternate-day mode.
          virality.py        SHARE_RULES; viral_brief(directive=)
          research.py        run(directive=)
          publisher.py       YouTube "altered/synthetic content" flag (containsSyntheticMedia). Instagram/Facebook have no API flag.
Secrets: none new (YT_API_KEY optional, already used).
NOT in 5a (next): 5b end card + fast loop-join + 4K/IG files, 5c raw editor + edit_raw.yml.
