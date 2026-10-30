"""Auto Reel Bot: research -> script -> Hindi voice -> stock video -> edit -> (upload)."""
import os, sys, json, math, random, re, time, asyncio
from pathlib import Path

import numpy as np
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont, features
from google import genai
from google.genai import types
from moviepy import (VideoFileClip, AudioFileClip, ImageClip,
                     CompositeVideoClip, CompositeAudioClip,
                     concatenate_videoclips)

# ---------- settings ----------
W, H = 1080, 1920
ROOT = Path(__file__).parent
ASSETS, WORK, OUT = ROOT / "assets", ROOT / "work", ROOT / "output"
HISTORY = ROOT / "topics_done.txt"

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
VOICE = os.environ.get("VOICE", "en-US-AndrewMultilingualNeural")
FALLBACK_VOICES = ["en-US-AriaNeural", "en-IN-NeerjaNeural"]
MODE = os.environ.get("MODE", "auto")        # auto | awareness | student
BRAND_NAME = os.environ.get("BRAND_NAME", "NeuroTriage")
SITE_URL = os.environ.get("SITE_URL", "https://www.neurotriage.in/")
SITE_SHORT = os.environ.get("SITE_SHORT", "neurotriage.in")
TAGLINE = os.environ.get("TAGLINE", "Free screening  |  Productivity tools")
CTA_AWARENESS = os.environ.get(
    "CTA_AWARENESS", "Try our website, NeuroTriage dot in, for a free screening.")
CTA_STUDENT = os.environ.get(
    "CTA_STUDENT", "Try our website, NeuroTriage dot in, to boost your productivity.")
HELPLINE = "If you are struggling, India's free 24x7 helpline Tele-MANAS: 14416."
DISCLAIMER = "This video is for education only. It is not medical advice or a diagnosis."

SAFETY = """Safety rules (must follow):
- Educational only. Never diagnose, never tell viewers they 'have' a disorder.
- Never advise starting, stopping or changing any medicine or treatment.
- No self-harm or suicide methods, no graphic detail, no fear-mongering, no miracle cures.
- Use cautious wording ("research suggests", "often"), never invent numbers or studies.
- Reduce stigma. For heavy topics (anxiety, depression, burnout) say gently that talking
  to a psychologist/psychiatrist or a trusted person helps."""
PRIVACY = os.environ.get("PRIVACY", "private")

client = genai.Client(api_key=GEMINI_KEY)


# ---------- 1. Gemini: research + script ----------
def ask(prompt, search=False, json_mode=False, retries=3):
    cfg = {}
    if search:
        cfg["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    if json_mode:
        cfg["response_mime_type"] = "application/json"
    for i in range(retries):
        try:
            r = client.models.generate_content(
                model=MODEL, contents=prompt,
                config=types.GenerateContentConfig(**cfg))
            if r.text:
                return r.text
        except Exception as e:
            print(f"[gemini] try {i+1} failed: {e}")
        time.sleep(5 * (i + 1))
    return None


def pick_mode():
    if MODE in ("awareness", "student"):
        return MODE
    return "awareness" if time.gmtime().tm_yday % 2 else "student"


def research(done, mode):
    if mode == "awareness":
        focus = ("mental health, psychology and psychiatry awareness for young Indian "
                 "viewers (e.g. how anxiety/stress/burnout/sleep affect the brain, myths vs facts, "
                 "healthy habits, when to seek help)")
    else:
        focus = ("study productivity and exam preparation for Indian students: evidence-based "
                 "techniques (active recall, spaced repetition, sleep, focus, handling exam "
                 "anxiety, time management)")
    prompt = f"""You are a researcher for an English Shorts channel for Indian viewers. Focus: {focus}.
Topics already covered (do NOT repeat): {done[-40:]}
{SAFETY}
Pick ONE fresh topic that would hook viewers. Research it using reliable sources
(peer-reviewed research, WHO, NIMH, NIMHANS, APA etc.).
Return plain text: the topic, 5-6 accurate key facts, one hook, one practical tip, and a one-line note of the sources."""
    txt = ask(prompt, search=True) or ask(prompt)
    if not txt:
        sys.exit("Research failed (Gemini). Key/model check karo.")
    return txt


def write_script(facts):
    prompt = f"""Using this research:
{facts}

{SAFETY}

Write a ~42 second English Reel script. Return ONLY JSON with keys:
"title": viral Shorts title in simple English, max 70 chars, no hashtags, no clickbait lies.
"voiceover_text": narration, 95-110 words, in simple conversational Indian-friendly English.
   Write it to be SPOKEN: short sentences, contractions (you're, it's), a friendly
   voice like a smart older sibling, commas and full stops where a human would pause.
   No jargon without a simple explanation, no lists, no emojis, no hashtags.
   First sentence is a strong hook, middle explains simply, end with one practical takeaway.
   Do NOT mention any website or app (it is added automatically). No emojis.
"keywords": list of 3 short ENGLISH stock-video search words (calm, non-graphic visuals,
   e.g. "student studying", "brain", "sunrise", "walking nature").
"description": 2-3 line English description.
"hashtags": list of 6 hashtags (with #)."""
    for _ in range(3):
        raw = ask(prompt, json_mode=True)
        if not raw:
            continue
        try:
            data = json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip()).strip())
            for k in ("title", "voiceover_text", "keywords", "description", "hashtags"):
                assert k in data
            return data
        except Exception as e:
            print("[script] bad JSON, retrying:", e)
    sys.exit("Script generation failed.")


# ---------- 2. Voice ----------
def make_voice(text, path):
    voices = [VOICE] + [v for v in FALLBACK_VOICES if v != VOICE]
    for voice in voices:
        for rate in ("+0%", "+10%"):   # lamba nikle to thoda tez
            try:
                asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(str(path)))
                a = AudioFileClip(str(path))
                dur = a.duration
                a.close()
            except Exception as e:
                print(f"[voice] {voice} failed: {e}")
                break
            print(f"[voice] {voice} rate {rate}: {dur:.1f}s")
            if dur <= 52:
                return dur
        else:
            return dur
    sys.exit("Voice generation failed.")


# ---------- 3. Stock footage (Pixabay) ----------
def fetch_clips(keywords, per_kw=2):
    paths = []
    for kw in keywords:
        got = 0
        try:
            r = requests.get("https://pixabay.com/api/videos/",
                             params={"key": PIXABAY_KEY, "q": kw, "per_page": 20,
                                     "safesearch": "true"}, timeout=30)
            hits = r.json().get("hits", [])
        except Exception as e:
            print("[pixabay]", kw, e)
            continue
        random.shuffle(hits)
        for h in hits:
            if got >= per_kw:
                break
            v = h.get("videos", {})
            pick = next((v[k] for k in ("large", "medium", "small")
                         if v.get(k, {}).get("url")), None)
            if not pick or h.get("duration", 0) < 5:
                continue
            p = WORK / f"clip{len(paths)}.mp4"
            try:
                data = requests.get(pick["url"], timeout=120).content
                p.write_bytes(data)
                paths.append(p)
                got += 1
            except Exception as e:
                print("[download]", e)
    if not paths:
        sys.exit("Koi stock clip nahi mili. Keywords/Pixabay key check karo.")
    return paths


def fit_vertical(c):
    s = max(W / c.w, H / c.h)
    c = c.resized((math.ceil(c.w * s), math.ceil(c.h * s)))
    return c.cropped(x_center=c.w / 2, y_center=c.h / 2, width=W, height=H)


# ---------- 4. Subtitles ----------
def find_font():
    cands = [ASSETS / "font.ttf", Path("C:/Windows/Fonts/arialbd.ttf")]
    fd = Path("/usr/share/fonts")
    if fd.exists():
        for pat in ("DejaVuSans-Bold.ttf", "NotoSans-Bold.ttf", "NotoSansDevanagari-Bold.ttf", "NotoSansDevanagari*Bold*.ttf",
                    "NotoSansDevanagari*.ttf", "*Devanagari*.ttf"):
            cands += list(fd.rglob(pat))
    for c in cands:
        if Path(c).exists():
            return str(c)
    sys.exit("Font nahi mila. assets/font.ttf mein koi bold font daalo.")


def caption_array(text, font_path, size=68):
    font = ImageFont.truetype(font_path, size)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if probe.textlength(t, font=font) <= W - 180:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    lh = int(size * 1.55)
    img = Image.new("RGBA", (W, lh * len(lines) + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, l in enumerate(lines):
        tw = d.textlength(l, font=font)
        d.text(((W - tw) / 2, 10 + i * lh), l, font=font, fill="white",
               stroke_width=7, stroke_fill="black")
    return np.array(img)


def caption_clips(text, total, font_path, words_per=5):
    words = text.split()
    chunks = [" ".join(words[i:i + words_per]) for i in range(0, len(words), words_per)]
    weights = [len(c) for c in chunks]
    t, clips = 0.0, []
    for c, w in zip(chunks, weights):
        d = total * w / sum(weights)
        clip = (ImageClip(caption_array(c, font_path)).with_start(t)
                .with_duration(d).with_position(("center", 1150)))
        clips.append(clip)
        t += d
    return clips


# ---------- 5. Edit ----------
def end_card(font_path, seconds=4.0):
    img = Image.new("RGB", (W, H), (14, 22, 40))
    d = ImageDraw.Draw(img)

    def center(text, y, size, fill):
        f = ImageFont.truetype(font_path, size)
        tw = d.textlength(text, font=f)
        d.text(((W - tw) / 2, y), text, font=f, fill=fill)

    center(BRAND_NAME, 720, 110, (255, 255, 255))
    if TAGLINE:
        center(TAGLINE[:48], 880, 52, (180, 200, 230))
    center(SITE_SHORT, 1010, 76, (110, 200, 255))
    center("Educational content, not medical advice", 1620, 38, (150, 160, 180))
    return ImageClip(np.array(img)).with_duration(seconds)



def build_video(audio_path, text, clips_paths, out_path):
    voice = AudioFileClip(str(audio_path))
    total = voice.duration + 0.6

    srcs = [VideoFileClip(str(p)).without_audio() for p in clips_paths]
    segs, t, i = [], 0.0, 0
    while t < total:
        c = srcs[i % len(srcs)]
        seg = min(4.0, total - t)
        start = 0.0 if i < len(srcs) else min(2.0 * (i // len(srcs)), max(0, c.duration - seg))
        seg = min(seg, c.duration - start)
        if seg <= 0.2:
            i += 1
            continue
        segs.append(fit_vertical(c.subclipped(start, start + seg)))
        t += seg
        i += 1
    base = concatenate_videoclips(segs, method="compose").with_duration(total)

    layers = [base]
    logo = ASSETS / "logo.png"
    if logo.exists():
        layers.append(ImageClip(str(logo)).resized(width=190)
                      .with_position((W - 190 - 40, 130)).with_duration(total))
    else:
        print("[warn] assets/logo.png nahi mila, logo skip.")
    layers += caption_clips(text, voice.duration, find_font())

    tracks = [voice]
    music = ASSETS / "music.mp3"
    if music.exists():
        try:
            from moviepy.audio.fx import AudioLoop
            m = AudioFileClip(str(music)).with_effects([AudioLoop(duration=total)])
            tracks.append(m.with_volume_scaled(0.08))
        except Exception as e:
            print("[warn] music skip:", e)

    main = (CompositeVideoClip(layers, size=(W, H)).with_duration(total)
            .with_audio(CompositeAudioClip(tracks).with_duration(total)))

    parts = [main]
    promo = ASSETS / "promo.mp4"
    if promo.exists():
        parts.append(fit_vertical(VideoFileClip(str(promo))))
    else:
        parts.append(end_card(find_font()))   # auto end card
    final = concatenate_videoclips(parts, method="compose")
    final.write_videofile(str(out_path), fps=30, codec="libx264", audio_codec="aac",
                          preset="medium", threads=4,
                          ffmpeg_params=["-pix_fmt", "yuv420p", "-crf", "20"])


# ---------- 6. YouTube upload ----------
def upload_youtube(video, title, desc, tags):
    need = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
    if not all(os.environ.get(k) for k in need):
        print("[upload] YouTube secrets nahi hain, upload skip (video output/ mein hai).")
        return
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YT_CLIENT_ID"],
                        client_secret=os.environ["YT_CLIENT_SECRET"],
                        scopes=["https://www.googleapis.com/auth/youtube.upload"])
    yt = build("youtube", "v3", credentials=creds)
    body = {"snippet": {"title": title[:95], "description": desc, "tags": tags[:15],
                        "categoryId": "27"},
            "status": {"privacyStatus": PRIVACY, "selfDeclaredMadeForKids": False}}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    print(f"[upload] done ({PRIVACY}): https://youtube.com/shorts/{resp['id']}")


# ---------- main ----------
def main():
    if not GEMINI_KEY or not PIXABAY_KEY:
        sys.exit("GEMINI_API_KEY aur PIXABAY_API_KEY set karo.")
    if not features.check("raqm"):
        print("[warn] Pillow mein raqm nahi: Hindi matras galat dikh sakte hain.")
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    done = HISTORY.read_text(encoding="utf-8").splitlines() if HISTORY.exists() else []

    mode = pick_mode()
    print("mode:", mode)
    print("1/5 research...")
    facts = research(done, mode)
    print("2/5 script...")
    data = write_script(facts)
    print("   title:", data["title"])
    print("3/5 voice...")
    audio = WORK / "audio.mp3"
    cta = CTA_AWARENESS if mode == "awareness" else CTA_STUDENT
    data["voiceover_text"] = data["voiceover_text"].strip() + " " + cta
    make_voice(data["voiceover_text"], audio)
    print("4/5 footage...")
    clips = fetch_clips(data["keywords"][:3])
    print("5/5 edit...")
    out = OUT / "final_reel.mp4"
    build_video(audio, data["voiceover_text"], clips, out)

    hashtags = data["hashtags"] + ["#Shorts"]
    brand = f"{BRAND_NAME}: {SITE_URL}" + (f" | {TAGLINE}" if TAGLINE else "")
    parts_desc = [data["description"], brand, DISCLAIMER]
    if mode == "awareness":
        parts_desc.append(HELPLINE)
    parts_desc.append(" ".join(hashtags))
    desc = "\n\n".join(parts_desc)
    (OUT / "meta.json").write_text(json.dumps(
        {"title": data["title"], "description": desc}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("\nTITLE:", data["title"], "\nDESCRIPTION:\n", desc)

    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(data["title"].replace("\n", " ") + "\n")
    upload_youtube(out, data["title"], desc, [h.lstrip("#") for h in hashtags])


if __name__ == "__main__":
    main()
