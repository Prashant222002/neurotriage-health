import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import talking_head as th

WORDS = [("Aaj", .3, .5), ("Claude", .5, .9), ("Code", .9, 1.2), ("dekho", 3.0, 3.3), ("growth", 3.3, 3.8), ("300%", 3.8, 4.4),
         ("Follow", 9.0, 9.4), ("karo", 9.4, 9.7)]


def test_cut_and_remap():
    segs = th.keep_segments(WORDS, 12)
    assert len(segs) == 3 and segs[0][0] < .3
    nw, offs, dur = th.remap(WORDS, segs)
    assert len(nw) == len(WORDS) and dur < 6 and all(b[1] >= a[1] for a, b in zip(nw, nw[1:]))


def test_events_spacing_and_media():
    plan = {"events": [{"at": 1, "type": "title"}, {"at": 5, "type": "graph"}, {"at": 6, "type": "terminal"}, {"at": 11, "type": "insert"}, {"at": 9, "type": "x"}]}
    ev = th.clean_events(plan, 20, [Path("demo.png")], "@h")
    assert [e["type"] for e in ev] == ["graph", "insert"]
    assert th.clean_events({"events": [{"at": 6, "type": "insert"}]}, 20, [], "@h") == []


def test_heuristic_topic_match():
    p = th.heuristic_plan(WORDS, 14, [], "@h")
    assert {e["type"] for e in p["events"]} <= {"graph", "profile", "terminal"}


def test_cards_render():
    for c in (th.TitleCard("Claude Code"), th.TerminalCard(["$ a", "ok"]), th.ProfileCard(), th.GraphCard()):
        assert c.render(1.0).shape[2] == 4
