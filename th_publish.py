"""Round 9: publish an edited Studio video. Usage: python th_publish.py JOB TITLE DESC TAGS_COMMA PRIVACY PLATFORMS_COMMA
SHORT video -> YouTube + Instagram Reels + Facebook Reels (whichever are ticked and have keys). LONG video -> YouTube only (enforced here).
Each platform is isolated; results are written into the release notes so the page can show them."""
import json
import subprocess
import sys

import publisher


def gh(*a):
    return subprocess.run(["gh", *a], check=True, capture_output=True, text=True).stdout


def main():
    job, title, desc, tags, privacy, plats = sys.argv[1:7]
    tag = f"th-{job}"
    gh("release", "download", tag, "-p", "final_th.mp4", "-O", "final_th.mp4", "--clobber")
    thumb = None
    try:                                           # Round 10: cover.jpg (hook + face) is used as the YouTube thumbnail
        gh("release", "download", tag, "-p", "cover.jpg", "-O", "cover.jpg", "--clobber")
        thumb = "cover.jpg"
    except Exception:
        thumb = None
    try:
        notes = json.loads(gh("release", "view", tag, "--json", "body", "-q", ".body") or "{}")
    except Exception:
        notes = {}
    want = [p for p in plats.split(",") if p in ("youtube", "instagram", "facebook")] or ["youtube"]
    if notes.get("kind") == "long":
        want = ["youtube"]
    title = title.strip() or "New video"
    taglist = [t.strip() for t in tags.split(",") if t.strip()]
    caption = desc if desc else title
    res = {}
    for p in want:
        try:
            if p == "youtube":
                res[p] = publisher.youtube("final_th.mp4", title, desc, taglist, privacy if privacy in ("public", "unlisted", "private") else "private", thumb, synthetic=False)
            elif p == "instagram":
                res[p] = publisher.instagram_reel("final_th.mp4", caption)
            else:
                res[p] = publisher.facebook_reel("final_th.mp4", caption)
        except Exception as e:
            res[p] = {"ok": False, "error": str(e)[:200]}
        print(p, res[p], flush=True)
    notes["results"] = {k: {"ok": bool(v.get("ok")), "url": v.get("url", ""), "note": str(v.get("skipped") or v.get("error") or "")[:160]} for k, v in res.items()}
    if res.get("youtube", {}).get("url"):
        notes["yt"] = res["youtube"]["url"]
    open("notes.json", "w").write(json.dumps(notes, ensure_ascii=False))
    gh("release", "edit", tag, "--notes-file", "notes.json")
    if not any(v.get("ok") for v in res.values()):
        sys.exit("all uploads failed: " + json.dumps(notes["results"]))


if __name__ == "__main__":
    main()
