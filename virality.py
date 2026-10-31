"""Virality brain for the NeuroTriage bot (research -> outliers -> script rules -> audit -> packaging).

Every function takes `ask` = bot.ask (prompt, search=False, json_mode=False) so any LLM works.
Real data: YouTube Data API v3 (YT_API_KEY) finds videos that beat their channel's size
("outliers"). Without a key it falls back to LLM web-search research.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests

YT = "https://www.googleapis.com/youtube/v3"

# --------------------------------------------------------------------------- 21 hook formulas
FORMULAS = [
    ("nobody_tells", "Nobody tells you...", "Koi nahi batata ki {X} se pehle {Y} hota hai"),
    ("i_was_wrong", "I was wrong about...", "Main {X} ke baare mein poora galat tha"),
    ("real_reason", "The real reason...", "{Problem} ka real reason {common cause} nahi hai"),
    ("stop_if", "Stop doing this if...", "Agar tum {habit} karte ho, toh ruk jao"),
    ("lost_x", "I lost X because...", "Maine {cost} {mistake} ki wajah se kho diya"),
    ("harsh_truth", "Harsh truth", "Harsh truth: {uncomfortable fact}"),
    ("myth_fact", "Myth vs fact", "Myth: {A}. Fact: {B}"),
    ("n_signs", "N signs/checklist", "{N} signs ki tumhara {system} toot raha hai (not a diagnosis)"),
    ("before_after", "Before / after", "{N} din pehle vs ab: {change}"),
    ("wish_knew", "Wish I knew earlier", "Kaash MBBS ke pehle saal pata hota"),
    ("counterintuitive", "Counterintuitive", "Zyada padhna = kam yaad. Here's why"),
    ("pattern_interrupt", "Pattern-interrupt question", "Kabhi notice kiya raat 2 baje tumhe sab yaad kyun aata hai?"),
    ("time_boxed", "Specific number / time box", "{N} minute mein {result}"),
    ("authority", "Authority + study", "{Institute} ki research kehti hai {surprising finding}"),
    ("confession", "Relatable confession", "Mujhe bhi lagta tha main lazy hoon"),
    ("blame_shift", "Blame the system, not you", "Tum lazy nahi ho, tumhara {routine/system} galat hai"),
    ("open_loop", "Open loop / teaser", "End tak ruko, #{k} wala sabse important hai"),
    ("topper_myth", "Topper myth-bust", "Toppers ye nahi karte jo tum sochte ho"),
    ("mini_challenge", "Mini challenge", "Aaj raat sirf ye 1 kaam try karo"),
    ("story_3_lines", "Story in 3 lines", "Ek intern tha. Raat ki duty. {twist}"),
    ("permission", "Permission / relief", "Agar tum bhi ye karte ho, toh tum akele nahi ho"),
]


def formulas_text():
    return "\n".join(f"{i + 1}. {n} -> e.g. \"{ex}\"" for i, (_, n, ex) in enumerate(FORMULAS))


SHARE_RULES = """SHARE-WORTHY WRITING (apply all):
- ONE 'send-this' moment in scenes 4-8: a line that makes the viewer think of a specific friend/sibling/batchmate
  (e.g. "Ye line us dost ko bhejo jo raat bhar jaagta hai."). It is a natural line, not a pushy ask.
- Make at least one line relatable enough to screenshot/save (a rule of thumb, a 3-step mini-plan, a before/after).
- A mid-video open loop ("aur teesra point sabse zaroori hai") so people stay to the end and replay.
- The last scene before the CTA must end in a way that connects to the first scene (a loop).
- Never guilt, never shame, never claim to diagnose; share-bait must stay kind and calm."""

VIRAL_RULES = f"""VIRALITY RULES (apply all):
- Hook = one of these 21 proven formulas (name it in "formula"):
{formulas_text()}
- First spoken line <= 9 words, creates curiosity or a named pain in the first 2 seconds. Never start with "Hi/Hello/Aaj hum".
- Specific > generic: Indian MBBS/medical-student life (hostel, night duty, exam cycles, family pressure) or young-professional life.
- Open loop in scene 2 or 3 ("aur #3 sabse zaroori hai"), a pattern-interrupt/new fact every 2-3 scenes.
- Educational, never diagnose ("research suggests", "often"). Soft NeuroTriage mention only at the end (added automatically).
- Ends with ONE practical action + a comment keyword CTA is added by the packager.
"""

AUDIT_MIN = int(os.environ.get("AUDIT_MIN", "75"))


# --------------------------------------------------------------------------- helpers
def _json(raw):
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _iso_secs(d):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


# --------------------------------------------------------------------------- 1. outlier finder (real data)
QUERIES = {
    "awareness": ["adult ADHD india", "ADHD medical student", "exam anxiety students hindi",
                  "burnout mbbs", "overthinking sleep student", "mental health screening test"],
    "student": ["study tips mbbs", "active recall hindi", "ADHD study techniques",
                "pomodoro focus student", "exam preparation routine india", "procrastination students"],
}


def find_outliers(yt_key, queries, days=120, per_query=15, min_subs=1000, max_subs=800000, top=8):
    """Videos from the last `days` whose views are far above what the channel size predicts."""
    if not yt_key:
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = {}
    for q in queries:
        try:
            r = requests.get(f"{YT}/search", timeout=25, params={
                "part": "snippet", "type": "video", "order": "viewCount", "q": q, "key": yt_key,
                "publishedAfter": since, "regionCode": "IN", "maxResults": per_query})
            if r.status_code != 200:
                continue
            for it in r.json().get("items", []):
                ids[it["id"]["videoId"]] = it["snippet"]
        except Exception:
            continue
    if not ids:
        return []
    vids = []
    idl = list(ids)
    for i in range(0, len(idl), 50):
        r = requests.get(f"{YT}/videos", timeout=25, params={
            "part": "statistics,contentDetails,snippet", "id": ",".join(idl[i:i + 50]), "key": yt_key})
        if r.status_code == 200:
            vids += r.json().get("items", [])
    chs = {}
    cl = list({v["snippet"]["channelId"] for v in vids})
    for i in range(0, len(cl), 50):
        r = requests.get(f"{YT}/channels", timeout=25, params={
            "part": "statistics", "id": ",".join(cl[i:i + 50]), "key": yt_key})
        if r.status_code == 200:
            for c in r.json().get("items", []):
                chs[c["id"]] = int(c["statistics"].get("subscriberCount", 0) or 0)
    out = []
    for v in vids:
        subs = chs.get(v["snippet"]["channelId"], 0)
        views = int(v["statistics"].get("viewCount", 0) or 0)
        if subs < min_subs or subs > max_subs or views < 5000:
            continue
        secs = _iso_secs(v["contentDetails"].get("duration"))
        out.append({"id": v["id"], "title": v["snippet"]["title"], "channel": v["snippet"]["channelTitle"],
                    "views": views, "subs": subs, "ratio": round(views / subs, 1), "secs": secs,
                    "short": secs <= 180, "published": v["snippet"]["publishedAt"][:10],
                    "desc": v["snippet"].get("description", "")[:300]})
    out.sort(key=lambda x: -x["ratio"])
    return out[:top]


def transcript(video_id, limit=900):
    """Optional: first ~900 chars of captions (needs youtube-transcript-api; silently skipped)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        try:
            t = YouTubeTranscriptApi().fetch(video_id, languages=["hi", "en"])
            txt = " ".join(s.text if hasattr(s, "text") else s["text"] for s in t)
        except AttributeError:
            t = YouTubeTranscriptApi.get_transcript(video_id, languages=["hi", "en"])
            txt = " ".join(s["text"] for s in t)
        return txt[:limit]
    except Exception:
        return ""


# --------------------------------------------------------------------------- 2. breakdown + better version
def analyze_outliers(ask, outliers, mode, safety=""):
    lines = []
    for o in outliers:
        tr = transcript(o["id"]) if o["short"] else ""
        lines.append(f'- "{o["title"]}" | {o["views"]:,} views on a {o["subs"]:,}-sub channel '
                     f'({o["ratio"]}x) | {o["secs"]}s | {o["published"]}'
                     + (f' | opening words: "{tr[:350]}"' if tr else ""))
    prompt = f"""You are a virality analyst for Indian mental-health / ADHD / student-productivity content.
These videos massively beat their channel size in the last 4 months (real data):
{chr(10).join(lines)}

For the 3 strongest: give the hook formula (from the list below), the emotional trigger, the structure
(hook -> first 15s -> middle -> CTA) and why it was shareable. Then invent ONE better video concept that keeps
the winning trigger, is more specific to Indian medical students / young professionals, and is safe for
NeuroTriage to follow with a soft mention.
Formulas:
{formulas_text()}
{safety}
Return ONLY JSON: {{"patterns":[{{"title":"","formula":"","trigger":"","structure":"","why_shared":""}}],
"gaps":["underused angles"],"concept":{{"topic":"","angle":"","hook_formula":"","opening_line":"","why_better":""}}}}"""
    return _json(ask(prompt, json_mode=True))


def viral_brief(ask, done, mode, safety="", yt_key=None, directive=""):
    """Replacement for bot.research(): topic + facts + proven structure. Returns plain text."""
    yt_key = yt_key or os.environ.get("YT_API_KEY", "").strip()
    ctx = ""
    try:
        outs = find_outliers(yt_key, QUERIES["awareness" if mode == "awareness" else "student"])
        if outs:
            an = analyze_outliers(ask, outs, mode, safety)
            if an:
                ctx = ("PROVEN OUTLIER ANALYSIS (real, last 120 days):\n" + json.dumps(an, ensure_ascii=False)[:3500])
    except Exception as e:
        print("[virality] outlier step failed:", str(e)[:100])
    focus = ("mental health / adult ADHD / burnout / sleep awareness" if mode == "awareness"
             else "study productivity and exam preparation (active recall, spacing, focus, sleep, ADHD-friendly study)")
    prompt = f"""You research for an Indian short-video channel (Hinglish) about {focus}, audience: Indian medical students and young professionals.
Already covered (do NOT repeat): {done[-40:]}
{safety}
{ctx or "Search what is trending right now on YouTube/Instagram in this niche in India (last 90 days) and which angles are underused."}
{directive or "Pick ONE fresh topic with high viral potential and low competition."} Use reliable sources only (peer-reviewed, WHO, NIMH, NIMHANS, APA).
Return plain text: TOPIC; ANGLE (why it is underused); HOOK FORMULA to use (one of the 21); 5-6 accurate facts; one practical tip; one-line sources note; PROVEN STRUCTURE to follow."""
    return ask(prompt, search=True) or ask(prompt)


# --------------------------------------------------------------------------- 3. audit (cross-check)
def audit_script(ask, data):
    scenes = "\n".join(f'{i + 1}. {s["text"]}' for i, s in enumerate(data["scenes"]))
    prompt = f"""You are a strict virality auditor for Indian Shorts/Reels. Score this script 0-100.
TITLE: {data.get("title")}
SCENES:
{scenes}
Check: hook strength in first line (<=9 words, curiosity/pain), open loop by scene 3, a new beat every 2-3 scenes,
specific Indian student/professional detail (not generic), one clear action at the end, no diagnosing/medical claims, no filler.
Return ONLY JSON: {{"score":0,"hook":0,"retention":0,"specificity":0,"safety_ok":true,"fixes":["max 4 concrete fixes"]}}"""
    return _json(ask(prompt, json_mode=True)) or {}


def improve_script(ask, data, safety="", rounds=1):
    """If audit < AUDIT_MIN, rewrite once using the auditor's fixes. Never returns a broken script."""
    for _ in range(rounds):
        rep = audit_script(ask, data)
        score = int(rep.get("score", 100) or 100)
        print(f"[audit] score {score}  fixes: {rep.get('fixes')}")
        data["audit"] = rep
        if score >= AUDIT_MIN and rep.get("safety_ok", True):
            break
        fixes = "; ".join(rep.get("fixes", [])) or "stronger hook, more specific, tighter"
        prompt = f"""Rewrite this reel script JSON applying these fixes: {fixes}.
Keep the SAME JSON keys/structure, same number of scenes (+-1), same fields per scene (text, text_en, queries, emphasis).
Hinglish "text" and English "text_en" must say the same thing. {safety}
JSON:
{json.dumps({k: data[k] for k in data if k != "audit"}, ensure_ascii=False)}
Return ONLY the JSON."""
        new = _json(ask(prompt, json_mode=True))
        ok = (isinstance(new, dict) and isinstance(new.get("scenes"), list) and len(new["scenes"]) >= 6
              and all(isinstance(s, dict) and s.get("text") and (s.get("queries") or s.get("query"))
                      for s in new["scenes"]))
        if ok:
            for k in ("kicker", "description", "hashtags", "title", "title_en"):
                new.setdefault(k, data.get(k))
            for s in new["scenes"]:
                s.setdefault("text_en", s["text"])
                s.setdefault("emphasis", "")
                if isinstance(s.get("queries"), str):
                    s["queries"] = [s["queries"]]
                if not s.get("queries"):
                    s["queries"] = [s.pop("query")]
            new["audit"] = rep
            data = new
    return data


# --------------------------------------------------------------------------- 4. packaging
def packaging(ask, data, mode, long=False, site="www.neurotriage.in"):
    base = data.get("title") or ""
    prompt = f"""Create high-CTR packaging for a {'LONG YouTube video' if long else 'Short/Reel'}, Indian medical-student audience, Hinglish.
Video title idea: {base}
Hook line: {data["scenes"][0]["text"] if data.get("scenes") else ""}
Rules: 7 title options ranked by CTR (<=70 chars, specific pain/number/contrast/curiosity; no 'Amazing/Secret/Best tips'; no false claims;
never say the viewer 'has' a disorder). Thumbnail text must NOT repeat the title (<=4 words).
Also: one comment keyword (single word, e.g. FOCUS) with a CTA line, a pinned first comment, a YouTube description (3 lines, no link spam),
an Instagram caption (first 125 chars must hook; natural Hinglish), exactly 5 hashtags.
Return ONLY JSON: {{"titles":["ranked best first"],"thumb_text":["","",""],"keyword":"","cta_line":"","first_comment":"",
"yt_description":"","ig_caption":"","hashtags":["#a","#b","#c","#d","#e"]}}"""
    p = _json(ask(prompt, json_mode=True)) or {}
    titles = [t for t in p.get("titles", []) if isinstance(t, str) and 8 < len(t) <= 95]
    p["title"] = titles[0] if titles else base
    p.setdefault("hashtags", data.get("hashtags", [])[:5])
    p["hashtags"] = [h if h.startswith("#") else "#" + h for h in p["hashtags"]][:5]
    return p


# --------------------------------------------------------------------------- 5. long video (script kit)
def long_script(ask, brief, safety="", target_minutes=7):
    """Outline (6 chapters) then scenes per chapter. Returns dict with chapters/scenes."""
    outline = _json(ask(f"""From this research, plan ONE long YouTube video (~{target_minutes} min, Hinglish, Indian medical students).
{brief}
{VIRAL_RULES}
Return ONLY JSON: {{"title":"","hook_formula":"","chapters":[{{"name":"short chapter title","goal":"","beats":["3-4 beats"]}}]}} with 6 chapters
(1 = hook + promise, last = practical system + soft NeuroTriage mention).""", json_mode=True))
    if not outline or not outline.get("chapters"):
        return None
    scenes = []
    for ci, ch in enumerate(outline["chapters"]):
        d = _json(ask(f"""Write chapter {ci + 1} "{ch['name']}" of the long video "{outline.get('title')}".
Beats: {ch.get('beats')}. {safety}
8-10 scenes. Each scene: "text" (Hinglish, 14-24 words, spoken, natural senior-to-junior tone), "text_en" (same meaning in simple English),
"queries" (3 concrete stock-video search phrases), "emphasis" (1-3 key words or "").
Include one open loop and one pattern-interrupt in this chapter. Return ONLY JSON: {{"scenes":[...]}}""", json_mode=True))
        for s in (d or {}).get("scenes", []):
            if s.get("text") and s.get("queries"):
                s.setdefault("text_en", s["text"])
                s["chapter"] = ci + 1
                scenes.append(s)
    outline["scenes"] = scenes
    return outline if len(scenes) >= 20 else None
