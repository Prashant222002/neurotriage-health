# Round 1 - Crash-proofing (v8 -> v8.1)
NEW:      safe.py                      type-safe helpers + soft() step isolation + step_report.json
MODIFIED: long_render.py               make_thumbnail() accepts str/list/None/dict/number
          bot.py                       AI fields normalised; thumbnail/meta/audio-mix isolated; short & long isolated;
                                       final long MP4 reused on resume; publish errors never lose the video
          .github/workflows/build.yml  step_report.json added to build-info artifact
TESTS:    tests/test_round1.py, tests/test_round1_isolation.py (new), test_resume.py (updated expectation)
Nothing else touched. No new secrets needed in Round 1.
