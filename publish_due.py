"""Runs by publish.yml at/after the scheduled time. Posts everything that is due and still pending
(Instagram always; YouTube/Facebook only if their native scheduling failed at build time).
Idempotent: safe to run every 30 minutes, safe if GitHub starts the cron late."""
import sys
from datetime import datetime, timezone
from pathlib import Path

import publisher
import scheduler

WORK = Path(__file__).parent / "work" / "queue"


def log(*a):
    print(*a, flush=True)


def record(m, name, res):
    st = m["platforms"][name]
    st["attempts"] = st.get("attempts", 0) + 1
    if res.get("skipped"):
        st["status"] = "skipped"
    elif res.get("ok"):
        st["status"] = "scheduled" if res.get("scheduled") else "done"
    elif res.get("deferred"):
        st["status"] = "pending"
        st["attempts"] -= 1
    else:
        st["status"] = "failed"
    st["result"] = {k: v for k, v in res.items() if k in ("id", "url", "error", "skipped", "scheduled")}
    st["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(now=None, dry=False):
    now = now or datetime.now(timezone.utc)
    acted = 0
    pend = scheduler.load_pending()
    if not pend:
        log("[due] queue empty")
    for m in pend:
        if not scheduler.is_due(m, now):
            log(f"[due] {m['id']}: not yet (publish_at {m['publish_at']})")
            continue
        todo = scheduler.needs_action(m)
        log(f"[due] {m['id']}: due. platforms to post: {todo or 'none'}")
        if todo and not dry:
            d = WORK / m["id"]
            try:
                scheduler.download_artifact(m["artifact"], d)
            except Exception as e:
                log(f"[due] {m['id']}: artifact download failed: {str(e)[:160]}")
                continue
            video = d / m["files"]["video"]
            thumb = d / m["files"]["thumb"] if m["files"].get("thumb") else None
            for name in todo:
                res = publisher.post_one(name, video, m["meta"], m["privacy"], None, m["kind"], thumb)
                log(f"[due] {m['id']} {name}: {res}")
                record(m, name, res)
                acted += 1
        scheduler.finalize(m)
        if not dry:
            scheduler.save_manifest(m)
    return acted


if __name__ == "__main__":
    run(dry="--dry" in sys.argv)
