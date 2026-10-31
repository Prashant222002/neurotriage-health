"""Stage checkpoints. Midnight build can be slow or get killed (busy runner, timeout, OOM). Every expensive stage
(research, script, voice, clips, render) is saved after it finishes, so a retry resumes where it stopped instead of
re-spending API credits / ElevenLabs characters. Files live in work/ckpt (the workflow also caches that folder)."""
import pickle
import time
from pathlib import Path

DIR = Path(__file__).parent / "work" / "ckpt"


def stage(name, fn, key="", validate=None, log=print):
    DIR.mkdir(parents=True, exist_ok=True)
    p = DIR / f"{key}_{name}.pkl"
    if p.exists():
        try:
            with open(p, "rb") as f:
                v = pickle.load(f)
            if validate is None or validate(v):
                log(f"[ckpt] {name}: resumed from checkpoint")
                return v
            log(f"[ckpt] {name}: checkpoint stale -> redo")
        except Exception as e:
            log(f"[ckpt] {name}: unreadable ({str(e)[:60]}) -> redo")
        p.unlink(missing_ok=True)
    t0 = time.time()
    v = fn()
    tmp = p.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(v, f, protocol=4)
    tmp.replace(p)
    log(f"[ckpt] {name}: done in {time.time() - t0:.0f}s, saved")
    return v


def cleanup(keep_key, days=3):
    """delete old checkpoints (other days)."""
    if not DIR.exists():
        return
    for p in DIR.glob("*.pkl"):
        if not p.name.startswith(f"{keep_key}_") and time.time() - p.stat().st_mtime > days * 86400:
            p.unlink(missing_ok=True)
