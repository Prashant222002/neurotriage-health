"""Round 16: topic rotation = 2 mental-health slots + 1 productivity slot, trends only rarely."""
import sys, tempfile
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import topics
tmp = Path(tempfile.mkdtemp()); SP = tmp / "r.json"
RSS = "<rss><channel><item><title>Sleep challenge viral</title></item></channel></rss>"
ask_fit = lambda p, **k: '{"fit": true, "trend": "Sleep challenge viral", "angle": "x", "audience": "student"}'
http = lambda u, p=None, t=10: RSS
base = datetime(2026, 11, 3, 12, tzinfo=topics.IST)
seq = []
for i in range(60):
    q = topics.plan(ask_fit, http, state_path=SP, log=lambda *a: None, now=base + timedelta(days=i))
    topics.record(q, SP); seq.append(q)
niches = [q["niche"] for q in seq]
assert set(niches) == {"mental_health", "mental_care", "productivity"}
assert all(len({niches[i + j] for j in range(3)}) == 3 for i in range(0, 57)), "3-day cycle"
assert niches.count("productivity") == 20 and niches.count("mental_health") + niches.count("mental_care") == 40
kinds = [q["kind"] for q in seq]
assert 1 <= kinds.count("trending") <= 12                                       # at most 1 in 5, never every day
assert all(kinds[i] != "trending" for i in range(len(kinds)) if i % 5 != 4)
subs = [q["subject"] for q in seq if q["kind"] != "trending"]
assert all(a != b for a, b in zip(subs, subs[1:]))
care = [q["subject"] for q in seq if q["niche"] == "mental_care" and q["kind"] != "trending"]
assert any("screening" in c.lower() for c in topics.CARE) and any("AI psychologist" in c for c in topics.CARE)
assert any("Psychologist vs psychiatrist" in c for c in topics.CARE) and len(set(care)) == len(care)
assert set(topics.STUDENTS) and not any("JEE" in s or "NEET" in s for s in topics.STUDENTS)
# trends off
topics.TREND_EVERY = 0
q = topics.plan(ask_fit, http, state_path=tmp / "n.json", log=lambda *a: None, now=base)
assert q["kind"] != "trending"
print("round16 OK")
