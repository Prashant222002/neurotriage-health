"""Phase 2: build at midnight, publish on schedule.

Flow
  00:00 IST  build.yml  -> bot.py builds Short (+ Long on day 7) slowly, with retries + resumable segments
                         -> files go to a private Actions artifact "queue-<date>", a small manifest to queue/<id>.json
                         -> YouTube (privacy private + publishAt) and Facebook (SCHEDULED) get the video right away
                            and publish themselves at the scheduled time, no server needed
  at publish time  publish.yml -> publish_due.py posts what is still pending (Instagram has no native scheduling)

This module = schedule maths + manifest files + artifact download. Pure python, testable offline.
"""
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).parent
QUEUE_DIR = Path(os.environ.get("QUEUE_MANIFEST_DIR", str(ROOT / "queue")))
MIN_LEAD = timedelta(minutes=int(os.environ.get("MIN_LEAD_MIN", "25")))   # Facebook/YouTube need a little lead time
MAX_ATTEMPTS = 3


def log(*a):
    print(*a, flush=True)


def now_ist():
    return datetime.now(IST)


def _hhmm(s, default):
    try:
        h, m = (s or default).strip().split(":")
        return int(h), int(m)
    except Exception:
        h, m = default.split(":")
        return int(h), int(m)


def schedule_for(kind, built_at=None):
    """Next publish moment (IST) for 'short' or 'long'.
    PUBLISH_TIME_SHORT_IST (default 10:00) / PUBLISH_TIME_LONG_IST (default 19:00).
    PUBLISH_ASAP=1 -> now + MIN_LEAD (used when a build ran late / manual run)."""
    built_at = built_at or now_ist()
    if os.environ.get("PUBLISH_ASAP", "").lower() in ("1", "true", "yes"):
        return built_at + MIN_LEAD
    best = None
    try:
        import analytics                      # Round 7: weekly best-time shift (state/best_time.json); BEST_TIME=off ignores it
        if not os.environ.get("PUBLISH_TIME_" + kind.upper() + "_FORCE"):
            best = analytics.load_best(kind)
    except Exception:
        best = None
    h, m = _hhmm(best or os.environ.get("PUBLISH_TIME_SHORT_IST" if kind == "short" else "PUBLISH_TIME_LONG_IST"),
                 "10:00" if kind == "short" else "19:00")
    t = built_at.replace(hour=h, minute=m, second=0, microsecond=0)
    while t < built_at + MIN_LEAD:                 # build finished too late for today's slot -> next day's slot
        t += timedelta(days=1)
    return t


def item_id(kind, day=None):
    return f"{(day or now_ist().date()).isoformat()}-{kind}"


def manifest_path(iid):
    return QUEUE_DIR / f"{iid}.json"


def already_built(kind, day=None):
    p = manifest_path(item_id(kind, day))
    if not p.exists():
        return False
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("built", True)
    except Exception:
        return True


def new_manifest(kind, meta, files, publish_at, privacy, artifact, platforms):
    return {
        "id": item_id(kind), "kind": kind, "built": True,
        "built_at": now_ist().isoformat(timespec="seconds"),
        "publish_at": publish_at.isoformat(timespec="minutes"),
        "publish_at_utc": publish_at.astimezone(timezone.utc).isoformat(timespec="minutes"),
        "privacy": privacy, "artifact": artifact, "files": files, "meta": meta,
        "platforms": {p: {"status": "pending", "attempts": 0} for p in platforms},
        "status": "pending",
    }


def save_manifest(m):
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path(m["id"]).write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")


def load_pending():
    out = []
    for p in sorted(QUEUE_DIR.glob("*.json")):
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if m.get("status") != "complete":
            out.append(m)
    return out


def is_due(m, now=None, grace_min=3):
    now = now or datetime.now(timezone.utc)
    pa = datetime.fromisoformat(m["publish_at_utc"])
    return now >= pa - timedelta(minutes=grace_min)


def needs_action(m):
    """platform names that still have to be posted by publish_due.py."""
    out = []
    for name, st in m["platforms"].items():
        if st["status"] == "pending" or (st["status"] == "failed" and st.get("attempts", 0) < MAX_ATTEMPTS):
            out.append(name)
    return out


def finalize(m):
    done = all(st["status"] in ("done", "scheduled", "skipped") or
               (st["status"] == "failed" and st.get("attempts", 0) >= MAX_ATTEMPTS)
               for st in m["platforms"].values())
    if done:
        m["status"] = "complete"
    return m


# ------------------------------------------------------------------ artifact download (GitHub REST, no gh CLI)
def download_artifact(name, dest, repo=None, token=None, local_dir=None):
    """Fetch artifact `name` of this repo into dest/. local_dir (env QUEUE_LOCAL_DIR) is used by tests/offline."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    local_dir = local_dir or os.environ.get("QUEUE_LOCAL_DIR")
    if local_dir:
        src = Path(local_dir) / name
        if not src.exists():
            raise FileNotFoundError(f"local artifact {src} missing")
        import shutil
        shutil.copytree(src, dest, dirs_exist_ok=True)
        return dest
    import requests
    repo = repo or os.environ["GITHUB_REPOSITORY"]
    token = token or os.environ["GITHUB_TOKEN"]
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = requests.get(f"https://api.github.com/repos/{repo}/actions/artifacts", headers=h, timeout=60,
                     params={"name": name, "per_page": 5})
    r.raise_for_status()
    arts = [a for a in r.json().get("artifacts", []) if not a.get("expired")]
    if not arts:
        raise FileNotFoundError(f"artifact {name} not found / expired")
    z = requests.get(f"https://api.github.com/repos/{repo}/actions/artifacts/{arts[0]['id']}/zip", headers=h,
                     timeout=600, stream=True)
    z.raise_for_status()
    zp = dest / "_a.zip"
    with open(zp, "wb") as f:
        for chunk in z.iter_content(1 << 20):
            f.write(chunk)
    with zipfile.ZipFile(zp) as zf:
        zf.extractall(dest)
    zp.unlink()
    return dest
