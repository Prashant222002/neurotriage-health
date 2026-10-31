"""Round 5a: topic planner.

Priority every run:
  1. TRENDING  - what India is searching today (Google Trends RSS + optional YouTube trending), kept ONLY if it can be
                 tied to mental health / study / habits naturally and safely. Always tried first.
  2. DISORDER  - psychiatric / mental-health topics (awareness mode)      } alternate, disorders first
  3. HABIT     - productivity / study / habits (student mode)             }
Rules: never the same subject twice in a row (a subject returns only after the whole list was used), the student type
(school, JEE, NEET, UPSC, college ...) rotates too, a trend is never reused for 3 days.
Cost: 0 LLM calls on days without a trend, 1 small call when there are trends to judge.
"""
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

STATE = Path(__file__).parent / "state" / "topic_rotation.json"
TRENDS_RSS = "https://trends.google.com/trending/rss?geo=IN"
TREND_COOLDOWN_DAYS = 3

DISORDERS = [
    "Generalized anxiety (constant worry)", "Panic attacks", "Social anxiety", "Depression vs normal sadness",
    "ADHD in adults and students", "OCD (it is not just being neat)", "Burnout", "Insomnia and racing thoughts",
    "Bipolar disorder basics", "PTSD and trauma response", "Health anxiety", "Exam / test anxiety",
    "Perfectionism and anxiety", "Persistent low mood (dysthymia)", "Specific phobias", "Imposter syndrome",
    "Internet and gaming overuse", "Autism in adults (myths vs facts)", "Schizophrenia myths", "Body image worries",
    "Loneliness and its effect on the brain", "Chronic stress and the body", "Anger and emotional regulation",
    "Dissociation and feeling numb", "Adjustment disorder (big life change)", "Procrastination and ADHD overlap",
    "Seasonal low mood", "Panic vs anxiety: how to tell the difference",
]
HABITS = [
    "Active recall", "Spaced repetition", "Pomodoro and focus blocks", "Sleep and memory", "Phone distraction",
    "Morning routine", "Deep work", "Habit stacking", "The 2-minute rule", "Feynman technique", "Exercise and focus",
    "Note-taking that works", "Beating procrastination", "Digital detox", "Revision timetable", "Mock-test analysis",
    "Morning sunlight and body clock", "Eat the frog (hardest task first)", "Single-tasking", "Interleaved practice",
    "Breaks and rest", "Implementation intentions (if-then plans)", "Social media comparison", "Breathing before an exam",
    "Study environment design", "Saying no and boundaries", "Consistency over motivation", "Learning from failure",
]
STUDENTS = [
    "school student (class 9-12)", "board-exam student", "JEE aspirant", "NEET aspirant",
    "UPSC / SSC / government-exam aspirant", "college student", "MBBS / medical student", "CA / CS / law student",
    "self-learner building skills", "fresher or working professional", "gap-year student", "placement / coding aspirant",
]

# trends we never touch (tragedy, politics, religion, crime, betting) - dropped BEFORE any LLM sees them
BLOCK = re.compile(
    r"\b(?:suicid|died|dies|death|dead\b|murder|rape|kill|accident|crash|blast|attack|riot|war\b|terror|"
    r"arrest|scam|fraud|leak|election|poll\b|vote|bjp|congress|modi|rahul|minister|party|"
    r"temple|mosque|church|hindu|muslim|religio|caste|"
    r"bet\b|betting|casino|lottery|dream11|fantasy|trading|stock|crypto|bitcoin|nifty|sensex|"
    r"porn|sex|nude|weather|earthquake|flood|cyclone|sale\b|offer\b)", re.I)


def _now():
    return time.time()


# ---------------------------------------------------------------- state
def load_state(path=None):
    p = Path(path or STATE)
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(s, dict):
            return s
    except Exception:
        pass
    return {"n_regular": 0, "subjects": {"disorder": [], "habit": []}, "students": [], "trends": [], "last_kind": ""}


def save_state(s, path=None):
    p = Path(path or STATE)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


# ---------------------------------------------------------------- trends
def parse_trends_rss(xml_text):
    out = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return out
    for it in root.iter("item"):
        t = (it.findtext("title") or "").strip()
        if t:
            out.append(t)
    return out


def fetch_trends(http_get, yt_key="", n=25):
    """-> list of trend titles (India), sensitive ones removed. Never raises."""
    found = []
    try:
        found += parse_trends_rss(http_get(TRENDS_RSS, None, 12))
    except Exception:
        pass
    if yt_key:
        try:
            raw = http_get("https://www.googleapis.com/youtube/v3/videos",
                           {"part": "snippet", "chart": "mostPopular", "regionCode": "IN", "maxResults": 15,
                            "key": yt_key}, 12)
            for it in json.loads(raw).get("items", []):
                t = (it.get("snippet", {}).get("title") or "").strip()
                if t:
                    found.append(t[:80])
        except Exception:
            pass
    seen, clean = set(), []
    for t in found:
        k = t.lower()
        if k in seen or BLOCK.search(t):
            continue
        seen.add(k)
        clean.append(t)
    return clean[:n]


def judge_trend(ask, trends, forced_mode=None):
    """One small LLM call. -> {"trend","angle","mode","audience"} or None when nothing fits naturally."""
    if not trends:
        return None
    prompt = f"""Today's trending searches/videos in India:
{json.dumps(trends, ensure_ascii=False)}
Our channel: calm educational mental-health awareness + study/productivity/habit videos for Indian students.
Pick the ONE trend that can be connected to our niche naturally, respectfully and safely (e.g. exam results ->
exam stress, a big match -> handling pressure, a viral challenge -> habits/focus, a festival -> sleep/routine).
Reject: tragedies, politics, religion, crime, celebrity gossip, gambling, anything where mental health would be
exploited or someone mocked. If nothing fits, return {{"fit": false}}.
Return ONLY JSON: {{"fit":true,"trend":"exact trend text","angle":"one line: the mental-health/study angle",
"mode":"awareness" or "student","audience":"which student type this is most relevant for"}}"""
    try:
        raw = ask(prompt, json_mode=True)
        d = json.loads(re.sub(r"^```(?:json)?|```$", "", (raw or "").strip()).strip())
    except Exception:
        return None
    if not isinstance(d, dict) or not d.get("fit") or not str(d.get("trend") or "").strip():
        return None
    if str(d["trend"]).strip() not in trends:                       # model must pick from the real list
        match = [t for t in trends if str(d["trend"]).strip().lower() in t.lower()]
        if not match:
            return None
        d["trend"] = match[0]
    mode = forced_mode if forced_mode in ("awareness", "student") else d.get("mode")
    return {"trend": str(d["trend"]).strip(), "angle": str(d.get("angle") or "").strip()[:200],
            "mode": mode if mode in ("awareness", "student") else "student",
            "audience": str(d.get("audience") or "").strip()[:80]}


# ---------------------------------------------------------------- rotation
def _next_from(pool, used):
    """first item not used in the current cycle; when the cycle is complete start a new one (never the last item)."""
    left = [x for x in pool if x not in used]
    if left:
        return left[0], False
    last = used[-1] if used else None
    left = [x for x in pool if x != last]
    return left[0], True


def pick_regular(state, forced_mode=None):
    """-> (kind, subject, audience). Disorders first, then habits, alternating."""
    n = int(state.get("n_regular", 0))
    kind = "disorder" if n % 2 == 0 else "habit"
    if forced_mode == "awareness":
        kind = "disorder"
    elif forced_mode == "student":
        kind = "habit"
    pool = DISORDERS if kind == "disorder" else HABITS
    used = list(state.get("subjects", {}).get(kind, []))
    subject, _ = _next_from(pool, used)
    aud, _ = _next_from(STUDENTS, list(state.get("students", [])))
    return kind, subject, aud


def directive(plan):
    if plan["kind"] == "trending":
        return (f"MANDATORY TOPIC: today's TRENDING topic in India is \"{plan['trend']}\". Angle: {plan['angle']}. "
                f"Tie it to our niche respectfully (no mocking, no exploitation, no news claims you cannot verify) "
                f"and open the video with the trend so the viewer stops scrolling. Target viewer: {plan['audience']}.")
    what = "a psychiatric / mental-health condition" if plan["kind"] == "disorder" else "a study-productivity / habit topic"
    return (f"MANDATORY TOPIC: {what}: \"{plan['subject']}\". Pick a fresh, specific angle on it. "
            f"Target viewer: {plan['audience']} - make the examples fit their daily life.")


def plan(ask, http_get, yt_key="", forced_mode=None, state_path=None, log=print):
    st = load_state(state_path)
    recent = {t["t"].lower() for t in st.get("trends", []) if _now() - t.get("ts", 0) < TREND_COOLDOWN_DAYS * 86400}
    trend = None
    try:
        trends = [t for t in fetch_trends(http_get, yt_key) if t.lower() not in recent]
        log(f"[topics] {len(trends)} usable trends")
        trend = judge_trend(ask, trends, forced_mode)
    except Exception as e:
        log("[topics] trend step failed:", str(e)[:100])
    if trend:
        p = {"kind": "trending", "mode": trend["mode"], "trend": trend["trend"], "angle": trend["angle"],
             "subject": trend["trend"], "audience": trend["audience"] or STUDENTS[0]}
    else:
        kind, subject, aud = pick_regular(st, forced_mode)
        p = {"kind": kind, "mode": "awareness" if kind == "disorder" else "student", "subject": subject,
             "audience": aud, "trend": "", "angle": ""}
    p["directive"] = directive(p)
    log(f"[topics] {p['kind']}: {p['subject']} | {p['audience']}")
    return p


def record(p, state_path=None):
    """call ONLY after the video was built/queued OK, so a failed day does not burn a subject."""
    st = load_state(state_path)
    if p.get("kind") == "trending":
        st.setdefault("trends", []).append({"t": p["trend"], "ts": _now()})
        st["trends"] = st["trends"][-30:]
    else:
        st["n_regular"] = int(st.get("n_regular", 0)) + 1
        pool = DISORDERS if p["kind"] == "disorder" else HABITS
        used = st.setdefault("subjects", {}).setdefault(p["kind"], [])
        if len(used) >= len(pool) - 1:
            used.clear()                                           # cycle complete; keep the last one out of the next pick
            used.append(p["subject"])
        elif p["subject"] not in used:
            used.append(p["subject"])
    if p.get("audience"):
        stu = st.setdefault("students", [])
        if p["audience"] in STUDENTS:
            if len(stu) >= len(STUDENTS) - 1:
                stu.clear()
            stu.append(p["audience"])
    save_state(st, state_path)
