"""Publishing + posting cycle.

CYCLE (assumption, change in one line): 7-day loop. Days 1-6 = 1 Short. Day 7 = 1 Short + 1 Long.
  Short -> YouTube + Instagram Reels + Facebook Reels.   Long -> YouTube only.
Each platform is optional and isolated: a failure on one never stops the others.
"""
import variants
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

GRAPH = os.environ.get("GRAPH_VERSION", "v25.0")


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------- cycle
def today_plan(today=None):
    """{'day': 1..7, 'short': True, 'long': bool}.
    Round 3: automatic runs make a SHORT only. A long video is made when you ask (FORCE_LONG=1 / VIDEO_TYPE=long|both).
    AUTO_LONG=on brings back the old rhythm (day 7 of the CYCLE_START loop = short + long)."""
    ist = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    today = today or ist
    start = date.fromisoformat(os.environ.get("CYCLE_START", "2026-11-01"))
    day = ((today - start).days % 7) + 1
    force = os.environ.get("FORCE_LONG", "").lower() in ("1", "true", "yes")
    auto = os.environ.get("AUTO_LONG", "off").lower() in ("1", "true", "yes", "on")
    return {"day": day, "short": True, "long": force or (auto and day == 7)}


# --------------------------------------------------------------------------- YouTube
def youtube(video, title, desc, tags, privacy="private", thumb=None, category="27", publish_at=None, synthetic=True):
    need = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
    if not all(os.environ.get(k) for k in need):
        return {"ok": False, "skipped": "YouTube secrets missing"}
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                        scopes=["https://www.googleapis.com/auth/youtube.upload"])
    yt = build("youtube", "v3", credentials=creds)
    body = {"snippet": {"title": title[:95], "description": desc[:4900], "tags": [t.lstrip("#") for t in tags][:15],
                        "categoryId": category},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                       "containsSyntheticMedia": bool(synthetic)}}      # round 5a: "Altered or synthetic content" (AI voice/visuals) label
    scheduled = False
    if publish_at is not None and privacy == "public":     # YouTube publishes by itself at publishAt (needs private)
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        scheduled = True
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]
    if thumb and Path(thumb).exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
        except Exception as e:
            log("[yt] thumbnail skipped:", str(e)[:100])
    return {"ok": True, "id": vid, "url": f"https://youtube.com/watch?v={vid}", "scheduled": scheduled}


# --------------------------------------------------------------------------- Instagram Reels (resumable upload)
def instagram_reel(video, caption):
    uid, tok = os.environ.get("IG_USER_ID"), os.environ.get("META_ACCESS_TOKEN")
    if not (uid and tok):
        return {"ok": False, "skipped": "IG_USER_ID / META_ACCESS_TOKEN missing"}
    size = os.path.getsize(video)
    r = requests.post(f"https://graph.facebook.com/{GRAPH}/{uid}/media", timeout=60, data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption[:2200],
        "share_to_feed": "true", "access_token": tok})
    j = r.json()
    if "id" not in j:
        return {"ok": False, "error": f"container: {str(j)[:200]}"}
    cid = j["id"]
    uri = j.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{GRAPH}/{cid}"
    with open(video, "rb") as f:
        up = requests.post(uri, timeout=600, data=f, headers={
            "Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)})
    if up.status_code != 200:
        return {"ok": False, "error": f"upload {up.status_code}: {up.text[:200]}"}
    for _ in range(40):                                   # wait for processing (max ~6 min)
        st = requests.get(f"https://graph.facebook.com/{GRAPH}/{cid}", timeout=30,
                          params={"fields": "status_code,status", "access_token": tok}).json()
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            return {"ok": False, "error": f"processing {code}: {st.get('status')}"}
        time.sleep(9)
    pub = requests.post(f"https://graph.facebook.com/{GRAPH}/{uid}/media_publish", timeout=60,
                        data={"creation_id": cid, "access_token": tok}).json()
    if "id" not in pub:
        return {"ok": False, "error": f"publish: {str(pub)[:200]}"}
    return {"ok": True, "id": pub["id"]}


# --------------------------------------------------------------------------- Facebook Page Reels
def facebook_reel(video, description, publish_at=None):
    pid, tok = os.environ.get("FB_PAGE_ID"), os.environ.get("FB_PAGE_TOKEN")
    if not (pid and tok):
        return {"ok": False, "skipped": "FB_PAGE_ID / FB_PAGE_TOKEN missing"}
    size = os.path.getsize(video)
    s = requests.post(f"https://graph.facebook.com/{GRAPH}/{pid}/video_reels", timeout=60,
                      json={"upload_phase": "start", "access_token": tok}).json()
    if "video_id" not in s:
        return {"ok": False, "error": f"start: {str(s)[:200]}"}
    vid = s["video_id"]
    url = s.get("upload_url") or f"https://rupload.facebook.com/video-upload/{GRAPH}/{vid}"
    with open(video, "rb") as f:
        up = requests.post(url, timeout=600, data=f, headers={
            "Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)})
    if up.status_code != 200:
        return {"ok": False, "error": f"upload {up.status_code}: {up.text[:200]}"}
    fin = requests.post(f"https://graph.facebook.com/{GRAPH}/{pid}/video_reels", timeout=60, params={
        "access_token": tok, "video_id": vid, "upload_phase": "finish",
        **({"video_state": "SCHEDULED", "scheduled_publish_time": int(publish_at.timestamp())}
           if publish_at is not None else {"video_state": "PUBLISHED"}),
        "description": description[:2000]}).json()
    if not fin.get("success", False) and "id" not in fin:
        return {"ok": False, "error": f"finish: {str(fin)[:200]}"}
    return {"ok": True, "id": vid, "scheduled": publish_at is not None}


# --------------------------------------------------------------------------- orchestrator
def post_one(name, video, meta, privacy="private", publish_at=None, kind="short", thumb=None):
    """Post to ONE platform. publish_at=None -> immediately. Never raises."""
    tags = meta.get("hashtags", [])
    caption = meta.get("ig_caption") or meta["yt_description"]
    try:
        if kind == "short":                                  # round 5b: 4K file for YouTube, own 1080 file for IG/FB
            video = variants.pick(name, video)
        if name == "youtube":
            return youtube(video, meta["title"], meta["yt_description"], tags, privacy, thumb, publish_at=publish_at)
        if name == "instagram":
            return instagram_reel(video, caption)
        if name == "facebook":
            return facebook_reel(video, caption, publish_at)
        return {"ok": False, "error": f"unknown platform {name}"}
    except Exception as e:                                   # one platform must never kill the run
        return {"ok": False, "error": str(e)[:200]}


def publish_short(video, meta, privacy="private", publish_at=None, platforms=("youtube", "instagram", "facebook")):
    """YouTube + IG + FB, each isolated. With publish_at: YouTube/Facebook are scheduled natively right now;
    Instagram has no native scheduling, so it is returned as {'deferred': True} for publish_due.py."""
    res = {}
    for name in platforms:
        if publish_at is not None and name == "instagram":
            res[name] = {"ok": False, "deferred": True}
            continue
        res[name] = post_one(name, video, meta, privacy, publish_at)
        log(f"[publish] {name}: {res[name]}")
    return res


def publish_long(video, meta, privacy="private", thumb=None, publish_at=None):
    res = {"youtube": post_one("youtube", video, meta, privacy, publish_at, "long", thumb)}
    log("[publish] long:", res)
    return res


def save_report(path, report):
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
