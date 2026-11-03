"""Topic planner (single file). One niche per day (IST). A topic MAY come back, but never with the same angle.

  Psychiatry / mental-health day  <->  study-productivity day   (alternates by date)
Inside a niche: a TRENDING topic that fits the niche, otherwise the least-used subject of its pool, each time with
a NEW ANGLE (myth-vs-fact, early signs, story, brain science, how to support a friend ...). A (subject, angle) pair is
never used twice, so no two scripts on the same topic start from the same idea. The angle and the angles already
used for that subject are written into the directive that bot.py hands to the script writer.
State: state/topic_rotation.json ("history": subject -> angles used). Subjects are reserved while a video is being
built (short + long on one day never share a subject) and are recorded only in record(), after a good build.
Public API unchanged: plan(), record(), directive(), fetch_trends(), judge_trend(), DISORDERS, HABITS, STUDENTS, BLOCK.
"""
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE = Path(__file__).parent / "state" / "topic_rotation.json"
HISTORY = Path(__file__).parent / "topics_done.txt"        # old log, imported once (counts as "covered once")
TRENDS_RSS = "https://trends.google.com/trending/rss?geo=IN"
TREND_COOLDOWN_DAYS = 30                                    # a trending topic is not reused for a month
RESERVE_HOURS = 24
# Round 16: trends are a SPICE, not the menu. Default: only every 5th video may be a trending topic (0 = never).
TREND_EVERY = int(os.environ.get("TREND_EVERY", "5") or 0)
IST = timezone(timedelta(hours=5, minutes=30))

DISORDERS = [
    "Generalized anxiety (constant worry)", "Panic attacks", "Social anxiety", "Depression vs normal sadness",
    "ADHD in adults and students", "OCD (it is not just being neat)", "Burnout", "Insomnia and racing thoughts",
    "Bipolar disorder basics", "PTSD and trauma response", "Health anxiety", "Exam / test anxiety",
    "Perfectionism and anxiety", "Persistent low mood (dysthymia)", "Specific phobias", "Imposter syndrome",
    "Internet and gaming overuse", "Autism in adults (myths vs facts)", "Schizophrenia myths", "Body image worries",
    "Loneliness and its effect on the brain", "Chronic stress and the body", "Anger and emotional regulation",
    "Dissociation and feeling numb", "Adjustment disorder (big life change)", "Procrastination and ADHD overlap",
    "Seasonal low mood", "Panic vs anxiety: how to tell the difference",
    "Overthinking and rumination", "Low self-esteem and self-worth", "Grief and loss", "Social media and mental health",
    "Work stress and burnout in professionals", "Postpartum and new-parent mental health", "Teen mental health basics",
    "Substance use and mental health (awareness only)", "Sleep problems and mental health", "Emotional numbness and anhedonia",
    "Fear of failure and performance anxiety", "Homesickness and moving abroad (international students)",
    "Stress in caregivers and carers", "Anxiety vs excitement: reading body signals",
]
# the app side of mental health: screening, AI psychologist, professionals, therapy, how to get help
CARE = [
    "What a mental health screening test is (and what it cannot tell you)",
    "Psychologist vs psychiatrist vs counsellor: who to see for what",
    "AI psychologist / AI mental-health chat: what it can do, what it cannot, how to use it safely",
    "How to prepare for your first therapy session",
    "Types of therapy explained simply (CBT, talk therapy and others)",
    "Psychiatric medicines: myths and facts (no doses, no advice to start or stop)",
    "Signs it is time to talk to a professional",
    "Online therapy vs in-person therapy",
    "How to talk to your family about mental health",
    "Self-assessment vs diagnosis: why a score is not a label",
    "What happens in a psychiatric evaluation",
    "Mindfulness and meditation: what research really says",
    "Journaling for mental health",
    "Grounding and breathing techniques for anxiety (gentle, safe ones)",
    "Mental health apps: how to choose one safely",
    "Building a support system around you",
    "Mental health first aid: helping a friend who is struggling",
    "Mood tracking: why it helps and how to start",
    "Therapy myths that stop people from getting help",
    "How to find affordable mental health support",
    "Questions to ask a therapist or doctor",
    "Why regular mental check-ins matter, even when you feel fine",
]
HABITS = [
    "Active recall", "Spaced repetition", "Pomodoro and focus blocks", "Sleep and memory", "Phone distraction",
    "Morning routine", "Deep work", "Habit stacking", "The 2-minute rule", "Feynman technique", "Exercise and focus",
    "Note-taking that works", "Beating procrastination", "Digital detox", "Revision timetable", "Mock-test analysis",
    "Morning sunlight and body clock", "Eat the frog (hardest task first)", "Single-tasking", "Interleaved practice",
    "Breaks and rest", "Implementation intentions (if-then plans)", "Social media comparison", "Breathing before an exam",
    "Study environment design", "Saying no and boundaries", "Consistency over motivation", "Learning from failure",
    "Time blocking with a calendar", "To-do list systems that actually work", "Eisenhower matrix (urgent vs important)",
    "Weekly review habit", "Focus apps and website blockers", "AI tools for studying and work (use them without losing your skills)",
    "Digital note-taking and a second brain", "Flashcard apps and spaced practice", "Goal setting that does not burn you out",
    "Batching similar tasks", "Working and learning from home", "Perfectionism vs progress", "Energy management, not just time management",
    "Starting before you feel ready", "Reducing decision fatigue", "Learning a new skill in 30 days",
]
STUDENTS = [
    "school student (middle / high school)", "college or university student", "graduate or PhD student",
    "medical / nursing / health-science student", "engineering / computer-science student", "law / business / commerce student",
    "competitive-exam aspirant (any exam, any country)", "international student living abroad", "self-learner building skills online",
    "fresher or young working professional", "gap-year student or career switcher", "freelancer / creator working alone",
    "teenager balancing school and life", "student who also works part-time",
]

# trends we never touch (tragedy, politics, religion, crime, betting) - dropped BEFORE any LLM sees them
BLOCK = re.compile(
    r"\b(?:suicid|died|dies|death|dead\b|murder|rape|kill|accident|crash|blast|attack|riot|war\b|terror|"
    r"arrest|scam|fraud|leak|election|poll\b|vote|bjp|congress|modi|rahul|minister|party|"
    r"temple|mosque|church|hindu|muslim|religio|caste|"
    r"bet\b|betting|casino|lottery|dream11|fantasy|trading|stock|crypto|bitcoin|nifty|sensex|"
    r"porn|sex|nude|weather|earthquake|flood|cyclone|sale\b|offer\b)", re.I)

MENTAL_ANGLES = [
    "MYTH vs FACT: bust 3 myths that families and friends commonly believe about it",
    "EARLY SIGNS: 3 to 5 early signs in students that are easy to miss or to blame on laziness",
    "A DAY IN THE LIFE: a short, relatable made-up story of a student living with it (no real person, no diagnosis)",
    "WHAT HAPPENS INSIDE: the simple brain/body science explained with one everyday analogy",
    "HOW TO SUPPORT SOMEONE: what to say and what NOT to say to a friend or family member",
    "WHEN TO SEE A DOCTOR: normal vs needs-professional-help, and what a psychiatrist or psychologist actually does",
    "COMMON MISTAKES: 3 things people do that quietly make it worse",
    "PRESSURE-TIME VERSION: how it shows up before exams, deadlines, interviews or results day",
    "SMALL DAILY HABITS: 3 science-backed micro-habits that help (support, not a cure)",
    "STIGMA: why people hide it in many cultures, and how to start the conversation at home",
    "TREATMENT WITHOUT FEAR: therapy and medicines explained simply (educational, no doses, no advice to start or stop)",
    "REFLECTION QUESTIONS: 3 questions to think about (NOT a diagnosis) and the next step if the answers worry you",
    "THE 3 AM QUESTIONS: answer the 3 things people secretly search at night about it",
    "WHAT RECOVERY REALLY LOOKS LIKE: realistic progress, setbacks included, without false promises",
]
STUDY_ANGLES = [
    "MYTH vs FACT: bust 3 study myths students believe about it",
    "THE 5-MINUTE START: the smallest possible version a tired student can begin today",
    "COMMON MISTAKES: 3 mistakes that waste hours while feeling productive",
    "A REAL DAY: a step-by-step routine with times for a student or young professional",
    "THE SCIENCE: why it works, explained with one everyday analogy",
    "30 DAYS TO A DEADLINE: how to apply it before an exam, project or interview when time is short",
    "ONLY ONE HOUR A DAY: a version for students with very little time",
    "TRACK IT: how to measure whether it is working, with a simple weekly check",
    "TOPPERS vs MYTH: what high scorers actually do versus what people assume",
    "WHEN IT STOPS WORKING: troubleshooting the 3 common reasons it fails",
    "PHONE-PROOF VERSION: using it when distractions are everywhere",
    "7-DAY EXPERIMENT: a small trial the viewer can run this week and judge themselves",
    "SLEEP AND BREAKS: combining it with rest so it sticks",
    "BEGINNER CHECKLIST: a short do-and-avoid list for first-timers",
]
CARE_ANGLES = [
    "MYTH vs FACT: bust 3 myths people believe about it",
    "WHAT TO EXPECT: a simple step-by-step of what actually happens, so it feels less scary",
    "WHO IT IS FOR (and who it is NOT for): clear limits, honest about what it cannot do",
    "QUESTIONS TO ASK: 3 to 5 smart questions to ask before, during or after",
    "COMMON MISTAKES: 3 things people get wrong about it",
    "A SHORT STORY: a relatable made-up student or young adult using it (no real person, no diagnosis)",
    "HOW TO CHOOSE: a short checklist for picking a safe, good option",
    "SAFETY FIRST: what to watch out for, and when to get urgent in-person help instead",
    "THE 5-MINUTE VERSION: the single most useful takeaway someone can act on today",
    "FIRST STEP TODAY: one tiny, realistic action the viewer can take, no pressure",
]
# 3-day cycle by date: mental-health conditions -> mental-health care (screening, AI psychologist, professionals) -> productivity
NICHE_ORDER = ["mental_health", "mental_care", "productivity"]
NICHES = {
    "mental_health": {"label": "Mental health conditions and awareness (all common problems)", "mode": "awareness", "pool": DISORDERS,
                      "angles": MENTAL_ANGLES,
                      "fit": "anxiety, panic, depression, ADHD, OCD, burnout, insomnia, loneliness, stress, exam stress, mood, overthinking"},
    "mental_care": {"label": "Mental health care: screening, AI psychologist, psychologist and psychiatrist, therapy, getting help",
                    "mode": "awareness", "pool": CARE, "angles": CARE_ANGLES,
                    "fit": "mental health screening, AI psychologist, therapy, psychologist vs psychiatrist, getting help, self-care tools, mental health apps"},
    "productivity": {"label": "Productivity, study and work habits (students worldwide)", "mode": "student", "pool": HABITS,
                     "angles": STUDY_ANGLES,
                     "fit": "study technique, productivity tools and apps, focus, phone addiction, sleep and memory, time management, procrastination, daily routine, exams and deadlines"},
}
FORCED_TO_NICHE = {"awareness": "mental_health", "student": "productivity"}   # forced awareness alternates conditions/care, see plan()


def _now():
    return time.time()


def _norm(t):
    return " ".join(re.findall(r"[\w\u0900-\u097F]+", (t or "").lower()))


def today_niche(now=None):
    return NICHE_ORDER[(now or datetime.now(IST)).date().toordinal() % len(NICHE_ORDER)]


def audience_for(now=None):
    return STUDENTS[(now or datetime.now(IST)).date().toordinal() % len(STUDENTS)]


# ---------------------------------------------------------------- state (one file)
def load_state(path=None):
    p = Path(path or STATE)
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(s, dict):
            raise ValueError
    except Exception:
        s = {}
    s.setdefault("history", {})          # subject -> [angles already used]
    s.setdefault("trends", [])
    s.setdefault("reserved", {})
    s.setdefault("slot", 0)
    if not s.get("migrated_v3"):         # one-time: whatever the older versions already covered counts as "once"
        old = [_norm(x) for x in s.get("used", [])]
        old += [_norm(x) for v in (s.get("subjects") or {}).values() for x in v]
        if HISTORY.exists() and Path(path or STATE) == STATE:
            old += [_norm(x) for x in HISTORY.read_text(encoding="utf-8").splitlines()]
        old = {x for x in old if x}
        for subj in DISORDERS + HABITS:
            if _norm(subj) in old and subj not in s["history"]:
                s["history"][subj] = ["legacy"]
        s["migrated_v3"] = True
    return s


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
    """-> trend titles (India), sensitive ones removed. Never raises."""
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


def judge_trend(ask, trends, niche="mental_health"):
    """One small LLM call -> {"trend","angle","mode","audience"} or None when no trend fits THIS niche."""
    if not trends:
        return None
    if niche not in NICHES:
        niche = FORCED_TO_NICHE.get(niche, "mental_health")
    cfg = NICHES[niche]
    prompt = f"""Today's trending searches/videos in India:
{json.dumps(trends, ensure_ascii=False)}
This video is for the channel topic: {cfg['label']} (covers: {cfg['fit']}).
Pick ONE trend with a DIRECT, natural link to that topic (e.g. results day -> exam stress; a viral sleep challenge -> sleep and memory).
Reject everything else: sports, films, music, celebrities, games, politics, religion, tragedies, crime, gambling,
shopping, and anything where mental health would be mocked or exploited. If none fits, return {{"fit": false}}.
Return ONLY JSON: {{"fit":true,"trend":"exact trend text","angle":"one line: the angle for our topic",
"audience":"which student type this is most relevant for"}}"""
    try:
        raw = ask(prompt, json_mode=True)
        d = json.loads(re.sub(r"^```(?:json)?|```$", "", (raw or "").strip()).strip())
    except Exception:
        return None
    if not isinstance(d, dict) or not d.get("fit") or not str(d.get("trend") or "").strip():
        return None
    if str(d["trend"]).strip() not in trends:                # model must pick from the real list
        match = [t for t in trends if str(d["trend"]).strip().lower() in t.lower()]
        if not match:
            return None
        d["trend"] = match[0]
    return {"trend": str(d["trend"]).strip(), "angle": str(d.get("angle") or "").strip()[:200],
            "mode": cfg["mode"], "audience": str(d.get("audience") or "").strip()[:80]}


# ---------------------------------------------------------------- subject + angle
def _pick_subject(niche, history, taken):
    """least-used subject first (pool order breaks ties) -> every subject is used once before any returns."""
    pool = [s for s in NICHES[niche]["pool"] if s not in taken]
    if not pool:
        return None
    return min(pool, key=lambda s: (len(history.get(s, [])), NICHES[niche]["pool"].index(s)))


def _pick_angle(niche, subject, history):
    angles = NICHES[niche]["angles"]
    used = history.get(subject, [])
    start = sum(ord(c) for c in subject) % len(angles)      # each subject starts at a different angle
    for i in range(len(angles)):
        a = angles[(start + i) % len(angles)]
        if a not in used:
            return a
    return None


def _fresh_angle(ask, niche, subject, used):
    """all built-in angles used for this subject -> ask the LLM for one genuinely new angle."""
    prompt = (f"Subject: \"{subject}\" ({NICHES[niche]['label']}). A short video was already made from these angles: "
              f"{json.dumps(used, ensure_ascii=False)}. Suggest ONE completely different angle for a new video "
              f"(different hook, different examples). Return ONLY JSON: {{\"angle\": \"...\"}}")
    try:
        d = json.loads(re.sub(r"^```(?:json)?|```$", "", (ask(prompt, json_mode=True) or "").strip()).strip())
        a = str(d.get("angle", "")).strip()[:200]
    except Exception:
        return None
    return a if a and a not in used else None


def directive(p):
    label = NICHES[p["niche"]]["label"]
    if p["kind"] == "trending":
        return (f"MANDATORY TOPIC: today's trending topic in India is \"{p['trend']}\". Angle: {p['angle']}. "
                f"Connect it to {label} respectfully (no mocking, no exploitation, no news claims you cannot verify). "
                f"Open with the trend so the viewer stops scrolling. Target viewer: {p['audience']}.")
    prev = [a for a in p.get("previous_angles", []) if a != "legacy"]
    avoid = (f" Earlier videos on this topic already used these angles, so do NOT reuse their hook, examples or "
             f"wording: {' | '.join(prev)}." if prev else "")
    return (f"MANDATORY TOPIC ({label}): \"{p['subject']}\". MANDATORY ANGLE: {p['angle']}. "
            f"Build the whole script around this angle with a fresh hook, new examples and new wording.{avoid} "
            f"Target viewer: {p['audience']} - make the examples fit their daily life. The audience is students and young people "
            f"worldwide, so keep examples universal (do not assume only Indian exams like JEE/NEET unless the topic is about them).")


# ---------------------------------------------------------------- plan / record
def plan(ask, http_get, yt_key="", forced_mode=None, state_path=None, log=print, now=None):
    dt = now or datetime.now(IST)
    ts = dt.timestamp()
    st = load_state(state_path)
    st["reserved"] = {k: v for k, v in st["reserved"].items() if ts - float(v) < RESERVE_HOURS * 3600}
    taken = set(st["reserved"])
    niche = FORCED_TO_NICHE.get(forced_mode) or today_niche(dt)
    if forced_mode == "awareness" and dt.date().toordinal() % 2:
        niche = "mental_care"
    recent = {t["t"].lower() for t in st["trends"] if ts - t.get("ts", 0) < TREND_COOLDOWN_DAYS * 86400}

    trend = None
    slot = int(st.get("slot", 0))
    trend_turn = TREND_EVERY > 0 and slot % TREND_EVERY == TREND_EVERY - 1     # only every Nth video may be a trending one
    if not trend_turn:
        log(f"[topics] rotation turn (trend allowed every {TREND_EVERY or 'never'} videos, slot {slot})")
    else:
        try:
            trends = [t for t in fetch_trends(http_get, yt_key) if t.lower() not in recent and t not in taken]
            log(f"[topics] {niche}: {len(trends)} usable trends")
            trend = judge_trend(ask, trends, niche) if trends else None
        except Exception as e:
            log("[topics] trend step failed:", str(e)[:100])

    if trend:
        p = {"kind": "trending", "niche": niche, "mode": NICHES[niche]["mode"], "trend": trend["trend"],
             "angle": trend["angle"], "subject": trend["trend"], "audience": trend["audience"] or audience_for(dt),
             "previous_angles": []}
    else:
        subject = _pick_subject(niche, st["history"], taken)
        angle = _pick_angle(niche, subject, st["history"]) if subject else None
        if subject and not angle:
            angle = _fresh_angle(ask, niche, subject, st["history"].get(subject, []))
        if not subject or not angle:
            save_state(st, state_path)
            raise RuntimeError(f"no unused topic+angle left for {niche}")      # bot.py falls back; logged
        p = {"kind": "evergreen", "niche": niche, "mode": NICHES[niche]["mode"], "subject": subject, "angle": angle,
             "audience": audience_for(dt), "trend": "", "previous_angles": list(st["history"].get(subject, []))}
    st["reserved"][p["subject"]] = ts
    save_state(st, state_path)
    p["directive"] = directive(p)
    log(f"[topics] {p['kind']} | {niche}: {p['subject']} | angle: {p['angle'][:60]} | {p['audience']}")
    return p


def record(p, state_path=None):
    """call ONLY after the video was built/queued OK: this (subject, angle) is then used forever."""
    st = load_state(state_path)
    h = st["history"].setdefault(p["subject"], [])
    if p.get("angle") and p["angle"] not in h:
        h.append(p["angle"])
    st["reserved"].pop(p["subject"], None)
    st["slot"] = int(st.get("slot", 0)) + 1
    if p.get("kind") == "trending":
        st["trends"].append({"t": p["trend"], "ts": _now()})
        st["trends"] = st["trends"][-60:]
    save_state(st, state_path)
