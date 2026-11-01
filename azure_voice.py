"""v17: Azure Speech (English) fallback. Keys: AZURE_SPEECH_KEY (+ _2 .. _4 optional), AZURE_SPEECH_REGION (e.g. centralindia).
REST only (no SDK). No word timestamps -> bot's proportional caption timing is used. Returns (mp3_bytes, [])."""
import os
from xml.sax.saxutils import escape

import requests

VOICE = os.environ.get("AZURE_VOICE", "en-US-AndrewMultilingualNeural")
RATE = os.environ.get("AZURE_RATE", "+4%")


def _keys():
    out = []
    for n in ("AZURE_SPEECH_KEY", "AZURE_SPEECH_KEY_1", "AZURE_SPEECH_KEY_2", "AZURE_SPEECH_KEY_3", "AZURE_SPEECH_KEY_4"):
        x = os.environ.get(n, "").strip()
        if x and x not in out:
            out.append(x)
    return out


def available():
    return bool(_keys()) and bool(os.environ.get("AZURE_SPEECH_REGION", "").strip())


def tts(text, voice=None):
    region = os.environ["AZURE_SPEECH_REGION"].strip()
    voice = voice or VOICE
    ssml = (f"<speak version='1.0' xml:lang='en-US'><voice name='{voice}'><prosody rate='{RATE}'>"
            f"{escape(text)}</prosody></voice></speak>")
    err = ""
    for k in _keys():
        r = requests.post(f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
                          headers={"Ocp-Apim-Subscription-Key": k, "Content-Type": "application/ssml+xml",
                                   "X-Microsoft-OutputFormat": "audio-24khz-96kbitrate-mono-mp3",
                                   "User-Agent": "neurotriage"}, data=ssml.encode("utf-8"), timeout=60)
        if r.status_code == 200 and r.content:
            return r.content, []
        err = f"{r.status_code} {r.text[:80]}"
    raise RuntimeError("azure tts failed: " + err)
