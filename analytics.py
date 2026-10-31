"""Round 7: best posting time. Looks at your last uploads (views per day vs. the IST hour they went live) and moves the
publish slot by at most +-1 hour per weekly run toward the best hour (window 07:00-22:00 IST). Never raises.
Output: state/best_time.json {"short": "HH:MM", "long": "HH:MM"}. scheduler.schedule_for reads it (BEST_TIME=off to ignore)."""
import json, os, re, statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path

PATH = Path(__file__).parent / "state" / "best_time.json"
IST = timezone(timedelta(hours=5, minutes=30))
LO, HI = 7, 22
DEFAULT = {"short": 10, "long": 19}


def best_hour(rows, current, lo=LO, hi=HI, max_shift=1, min_rows=6):
    """rows: [{"hour": 0-23 IST, "views": n, "age_days": d}]. Returns the next slot hour (int)."""
    try:
        cur = int(current)
        by = {}
        for r in rows or []:
            h, v, a = int(r["hour"]), float(r["views"]), max(1.0, float(r["age_days"]))
            if lo <= h <= hi and v >= 0:
                by.setdefault(h, []).append(v / a)
        if sum(len(x) for x in by.values()) < min_rows:
            return cur                                      # too little data: keep the slot
        allv = [x for xs in by.values() for x in xs]
        prior = statistics.mean(allv)
        score = {h: (sum(xs) + prior * 2) / (len(xs) + 2) for h, xs in by.items()}   # shrink towards the mean
        target = max(score, key=score.get)
        step = max(-max_shift, min(max_shift, target - cur))
        return max(lo, min(hi, cur + step))
    except Exception:
        return int(current) if str(current).isdigit() else 10


def load():
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_best(kind):
    """'HH:MM' or None. Only trusted when it looks valid."""
    if os.environ.get("BEST_TIME", "on").strip().lower() in ("off", "0", "no", "false"):
        return None
    v = load().get(kind)
    try:
        h, m = str(v).split(":")
        return v if LO <= int(h) <= HI and 0 <= int(m) < 60 else None
    except Exception:
        return None


def fetch_rows(log=print):
    """Last 50 uploads -> rows per kind. Needs YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    c = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"], client_id=os.environ["YT_CLIENT_ID"],
                    client_secret=os.environ["YT_CLIENT_SECRET"], token_uri="https://oauth2.googleapis.com/token")
    yt = build("youtube", "v3", credentials=c, cache_discovery=False)
    up = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids = [i["contentDetails"]["videoId"] for i in yt.playlistItems().list(part="contentDetails", playlistId=up, maxResults=50).execute()["items"]]
    out = {"short": [], "long": []}
    now = datetime.now(timezone.utc)
    for v in yt.videos().list(part="snippet,statistics,contentDetails", id=",".join(ids)).execute()["items"]:
        t = datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00"))
        dur = v["contentDetails"]["duration"]
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur)
        secs = int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0) if m else 999
        is_short = secs <= 180
        out["short" if is_short else "long"].append({"hour": t.astimezone(IST).hour, "views": int(v["statistics"].get("viewCount", 0)),
                                                      "age_days": (now - t).total_seconds() / 86400})
    return out


def run(log=print, fetch=fetch_rows):
    cur = load()
    res = dict(cur)
    try:
        rows = fetch(log)
    except Exception as e:
        log("[analytics] skipped:", str(e)[:120])
        return cur
    for kind in ("short", "long"):
        try:
            c = int(str(cur.get(kind, f"{DEFAULT[kind]}:00")).split(":")[0])
            if not LO <= c <= HI:
                c = DEFAULT[kind]                       # saved slot is garbage -> start again from the default
        except Exception:
            c = DEFAULT[kind]
        h = best_hour(rows.get(kind, []), c)
        res[kind] = f"{h:02d}:00"
        log(f"[analytics] {kind}: {c:02d}:00 -> {h:02d}:00 ({len(rows.get(kind, []))} videos)")
    res["updated"] = datetime.now(IST).strftime("%Y-%m-%d")
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    run()
