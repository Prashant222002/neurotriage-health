"""Round 13 - SILENT / B-ROLL footage mode. Footage with no speech -> engine writes script, makes voice, picks music, then the normal pipeline edits it.
Order: user --script > AI (ai_router, needs --topic) > music-only (no invented narration). Voice: ElevenLabs (Hinglish) -> edge-tts (English) -> music-only.
Script rules for sensitive topics: no diagnosis, no cure claims. Never raises into the pipeline: any failure -> music-only or untouched flow."""
import asyncio, json, os, re, subprocess
from pathlib import Path
import numpy as np
import ai_router

WPS = 2.3                                    # spoken words per second (target)
CALM = re.compile(r"mental|anxiety|stress|sleep|depress|meditat|calm|health|therapy|migraine|neuro|brain|yoga|relax", re.I)


def _run(cmd, t=300): return subprocess.run(cmd, capture_output=True, text=True, timeout=t)


def probe(p):
    j = json.loads(_run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(p)]).stdout)
    return float(j["format"]["duration"]), any(s["codec_type"] == "audio" for s in j["streams"])


def is_silent(video):
    """No audio, or audio with no speech-like energy (mean < -45 dB, or <8% of time above -38 dB)."""
    try:
        dur, aud = probe(video)
        if not aud: return True
        r = _run(["ffmpeg", "-nostats", "-i", str(video), "-vn", "-af", "silencedetect=n=-38dB:d=0.3", "-f", "null", "-"]).stderr
        sil = sum(float(x) for x in re.findall(r"silence_duration: ([\d.]+)", r)); voiced = max(0.0, dur - sil)
        return voiced / max(dur, .1) < 0.08
    except Exception:
        return False


def make_script(topic, dur, hook="", cache_dir=None):
    """-> {'hook','en','hi'} or None. AI only; text length is forced to fit the footage."""
    n = max(8, int(dur * WPS * 0.85))
    p = (f"Write a short voiceover for a {dur:.0f}s vertical video about: {topic}. About {n} words. Simple conversational Hinglish (Roman script) AND an English version. "
         "Calm, human, no medical diagnosis, no cure/guarantee claims, no invented statistics; if health-related, gently suggest a professional when needed. "
         f'JSON only: {{"hook":"max 5 words","hi":"...","en":"..."}}. {("Hook must be: " + hook) if hook else ""}')
    def ok(d):
        if not isinstance(d, dict): return None
        en, hi = str(d.get("en", "")).strip(), str(d.get("hi", "")).strip()
        if not (n * .5 <= len(en.split()) <= n * 1.5): return None
        return {"hook": re.sub(r"[^\w ?!]", "", str(d.get("hook", "")))[:30].upper(), "en": en, "hi": hi if n * .5 <= len(hi.split()) <= n * 1.5 else en}
    return ai_router.ask_json(p, validate=ok, cache_dir=cache_dir)[0]


async def _edge(text, voice="en-IN-NeerjaNeural", rate="+0%"):
    import edge_tts
    c = edge_tts.Communicate(text, voice, rate=rate); audio, ev = bytearray(), []
    async for ch in c.stream():
        if ch["type"] == "audio": audio += ch["data"]
        elif ch["type"] == "WordBoundary": ev.append(("WordBoundary", ch["offset"] / 1e7, ch["duration"] / 1e7, ch["text"]))
    return bytes(audio), ev


def tts(script):
    """-> (mp3_bytes, [(word,start,end)]) or raises. ElevenLabs Hinglish first, then edge-tts English."""
    errs = []
    try:
        import eleven_voice
        if eleven_voice.available():
            a, ev = eleven_voice.tts(script["hi"]); return a, [(e[3], e[1], e[1] + e[2]) for e in ev]
    except Exception as e: errs.append(f"eleven:{type(e).__name__}")
    try:
        a, ev = asyncio.run(_edge(script["en"])); return a, [(e[3], e[1], e[1] + e[2]) for e in ev]
    except Exception as e: errs.append(f"edge:{type(e).__name__}")
    raise RuntimeError("tts-failed " + ",".join(errs))


def pad_synth(total, seed=3):
    """Soft warm pad + slow arpeggio (offline) for non-calm topics."""
    sr = 44100; t = np.arange(int(total * sr)) / sr; rng = np.random.default_rng(seed); out = np.zeros_like(t, np.float32)
    for k, ch in enumerate([(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)] * int(total // 8 + 1)):
        a, b = int(k * 2 * sr), int(min(len(t), (k + 1) * 2.4 * sr))
        if a >= len(t): break
        seg = t[a:b] - t[a]
        for m in ch: out[a:b] += (np.sin(2 * np.pi * 440 * 2 ** ((m - 69) / 12) * seg) * np.exp(-seg * .6) * .18).astype(np.float32)
        for j, m in enumerate(ch * 2):
            s = int(j * .33 * sr)
            if a + s < b: e = np.exp(-np.arange(min(sr // 2, b - a - s)) / (sr * .12)); out[a + s:a + s + len(e)] += (np.sin(2 * np.pi * 880 * 2 ** ((m - 69) / 12) * np.arange(len(e)) / sr) * e * .06).astype(np.float32)
    out *= np.minimum(1, t / 1.5) * np.minimum(1, (total - t) / 2.0); out /= (np.abs(out).max() + 1e-9) / 0.9
    return np.stack([out, out], 1)


def topic_hook(topic, n=4):
    """Clean short hook from the topic (never a mid-sentence cut)."""
    w = re.sub(r"[^\w ]", "", topic or "").upper().split()
    return " ".join(w[:n])


def make_music(topic, total, path):
    import flute, wave
    y = flute.synth(total + 1) if (not topic or CALM.search(topic)) else pad_synth(total + 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100); w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


def prepare(video, work, topic="", script_text="", hook="", log=print, tts_fn=None):
    """-> dict(video, words_json|None, music, mode, hook, script). mode: voiceover | music-only. Never raises."""
    work = Path(work); work.mkdir(parents=True, exist_ok=True); dur, _ = probe(video)
    res = {"video": str(video), "words_json": None, "mode": "music-only", "hook": hook, "script": None, "music": None, "notes": []}
    try: res["music"] = str(make_music(topic, dur, work / "auto_music.wav"))
    except Exception as e: res["notes"].append(f"music-failed:{type(e).__name__}")
    script = {"hook": hook, "en": script_text, "hi": script_text} if script_text else (make_script(topic, dur, hook, work) if topic else None)
    if not script: res["notes"].append("no-script (give --topic or --script; AI unavailable or no topic)"); return res
    try:
        audio, words = (tts_fn or tts)(script)
        (work / "voice.mp3").write_bytes(audio); vd = max(w[2] for w in words) if words else 0
        if not words or vd < 1: raise RuntimeError("empty-voice")
        speed = min(1.15, max(1.0, (vd + .4) / (dur * 1.0))); lead = 0.4; vend = vd / speed + lead
        pad = max(0.0, min(4.0, vend + .3 - dur)); out = work / "silent_prepped.mp4"
        r = _run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(work / "voice.mp3"), "-filter_complex",
                  f"[0:v]tpad=stop_mode=clone:stop_duration={pad:.2f}[v];[1:a]atempo={speed:.3f},adelay={int(lead * 1000)}|{int(lead * 1000)},apad[a]",
                  "-map", "[v]", "-map", "[a]", "-t", f"{dur + pad:.2f}", "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)])
        if r.returncode: raise RuntimeError(r.stderr[-120:])
        nw = [[w[0], round(w[1] / speed + lead, 3), round(w[2] / speed + lead, 3)] for w in words]
        (work / "words_auto.json").write_text(json.dumps(nw, ensure_ascii=False))
        res.update(video=str(out), words_json=str(work / "words_auto.json"), mode="voiceover", hook=script.get("hook") or hook or topic_hook(topic), script=script["hi"], speed=round(speed, 2), padded_sec=round(pad, 2))
    except Exception as e:
        res["notes"].append(f"voice-failed:{str(e)[:100]} -> music-only")
    log("[silent]", res["mode"], res["notes"]); return res


def music_only(video, music, out):
    """Footage + calm music, loudness-normalised (-16 LUFS). No fake narration."""
    dur, _ = probe(video)
    r = _run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(music), "-map", "0:v", "-map", "1:a", "-af", f"loudnorm=I=-16:TP=-1.5,afade=t=out:st={max(0, dur - 1.5):.2f}:d=1.5",
              "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", f"{dur:.2f}", "-movflags", "+faststart", str(out)])
    if r.returncode: raise RuntimeError(r.stderr[-150:])
    return out
