"""Round 3 - shared AI PROJECT MEMORY + SCRIPT LOCK.

Problem this solves: the pipeline hops between providers (Gemini -> Groq -> another key/model) and a build can be
resumed 3 times. Every hop used to be a blank slate, so the script got rewritten again and again.

What lives here (one JSON file per video: <key>_<kind>.json, kind = short | long):
  request      what this video is (mode, kind, date)
  research     verified facts, sources, dropped claims            (written by research.py)
  script       current locked script + version history             (SCRIPT LOCK)
  stages       which pipeline stages are finished, by whom
  handoff      one line per AI call: stage, provider, model, key label, summary  (key VALUE is never stored)
  pending      script-change proposals waiting for the owner's approval
  errors       last errors, so the next provider knows what already failed

SCRIPT LOCK (strict):
  * The first script that passes the audit is LOCKED (sha256 of every scene's text).
  * After that no AI call, retry, resume or fallback provider can replace it. A regenerated script is ignored and
    the locked one is returned, with a log line.
  * Packaging (title / hashtags / description) may be generated, but scene text is never touched.
  * A change needs the owner: either workflow input `unlock_script=1` (archive the old one, lock a new one),
    or `approve_pending=1` (apply the proposal that was saved in `pending`). Old versions stay in history and can be
    restored with restore(version).

Nothing here talks to the network. Pure python, fully testable offline."""
import hashlib
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).parent
LIVE_DIR = ROOT / "work" / "ckpt" / "state"      # cached between workflow attempts (build.yml caches work/ckpt)
ARCHIVE_DIR = ROOT / "state"                      # committed to the repo: permanent audit trail
MAX_HANDOFF = 40                                  # history lines kept
MAX_ERRORS = 10


class ScriptLockError(Exception):
    pass


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def _truthy(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def script_text(script):
    """The words that will be spoken: every scene's text AND text_en, in order. Order and wording both count."""
    out = []
    for sc in (script or {}).get("scenes", []) or []:
        if isinstance(sc, dict):
            out.append(str(sc.get("text", "")).strip())
            out.append(str(sc.get("text_en", "")).strip())
    return "\n".join(out)


def script_hash(script):
    return hashlib.sha256(script_text(script).encode("utf-8")).hexdigest()[:16]


def _atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class ProjectState:
    def __init__(self, key, kind, live_dir=None, archive_dir=None, log=print):
        self.key, self.kind, self.log = key, kind, log
        self.live = Path(live_dir or LIVE_DIR) / f"{key}_{kind}.json"
        self.archive = Path(archive_dir or ARCHIVE_DIR) / f"{key}_{kind}.json"
        self.d = {"key": key, "kind": kind, "created": _now(), "request": {}, "research": {},
                  "script": {"locked": False, "version": 0, "hash": "", "data": None, "history": []},
                  "stages": {}, "handoff": [], "pending": [], "errors": [], "approved_changes": [],
                  "stage_now": ""}
        self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self):
        for p in (self.live, self.archive):
            if p.exists():
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    if d.get("key") == self.key and d.get("kind") == self.kind:
                        for k, v in d.items():
                            self.d[k] = v
                        return
                except Exception as e:
                    self.log(f"[state] {p.name} unreadable ({str(e)[:60]}) -> starting fresh")

    def save(self):
        txt = json.dumps(self.d, ensure_ascii=False, indent=1)
        try:
            _atomic_write(self.live, txt)
        except Exception as e:
            self.log("[state] live save failed:", str(e)[:80])
        try:                                             # archive copy is small; script history included
            _atomic_write(self.archive, txt)
        except Exception as e:
            self.log("[state] archive save failed:", str(e)[:80])

    # ------------------------------------------------------------------ request / research / stages
    def set_request(self, **kw):
        self.d["request"].update(kw)
        self.save()

    def set_research(self, research):
        self.d["research"] = research
        self.save()

    def stage_done(self, name, provider="", note=""):
        self.d["stages"][name] = {"at": _now(), "provider": provider, "note": str(note)[:160]}
        self.save()

    def set_stage(self, name):
        self.d["stage_now"] = name

    def record_error(self, stage, msg):
        self.d["errors"] = (self.d["errors"] + [{"stage": stage, "at": _now(), "error": str(msg)[:200]}])[-MAX_ERRORS:]
        self.save()

    # ------------------------------------------------------------------ handoff (who did what)
    def record_call(self, stage, provider, model="", label="", summary=""):
        """One line per successful AI call. `label` is a key LABEL like GEMINI_API_KEY_2, never the key value."""
        h = self.d["handoff"]
        h.append({"at": _now(), "stage": stage or self.d.get("stage_now", ""), "provider": provider, "model": model,
                  "key": label, "summary": str(summary)[:140]})
        self.d["handoff"] = h[-MAX_HANDOFF:]
        self.save()

    def last_provider(self):
        h = self.d["handoff"]
        return h[-1]["provider"] if h else ""

    def handoff_block(self, task="", maxchars=1800):
        """Text put in front of a prompt so ANY provider continues from the exact project state instead of guessing.
        Contains decisions that are FINAL, what is done, what the provider may and may not change."""
        s = self.d["script"]
        lines = ["[PROJECT STATE - shared by every AI provider. Read before answering.]",
                 f"video: {self.kind} for {self.key}; your task now: {task or self.d.get('stage_now') or 'continue'}"]
        req = self.d["request"]
        if req:
            lines.append("request: " + ", ".join(f"{k}={v}" for k, v in req.items() if v not in ("", None)))
        r = self.d["research"]
        if r.get("topic"):
            lines.append(f"FINAL topic: {r['topic']} (do not change it)")
            vf = r.get("verified", [])[:6]
            if vf:
                lines.append("VERIFIED facts (use only these, no new numbers): " + " | ".join(str(x)[:140] for x in vf))
        done = ", ".join(f"{k}({v.get('provider') or 'local'})" for k, v in self.d["stages"].items())
        lines.append("completed stages: " + (done or "none yet"))
        if s["locked"]:
            lines.append(f"SCRIPT LOCKED v{s['version']} hash {s['hash']}: title \"{(s['data'] or {}).get('title', '')}\", "
                         f"{len((s['data'] or {}).get('scenes', []))} scenes. You MUST NOT rewrite, shorten, expand or "
                         "reorder it. Only add packaging/metadata around it.")
        else:
            lines.append("script: not locked yet (you are allowed to write it).")
        prev = self.d["handoff"][-1] if self.d["handoff"] else None
        if prev:
            lines.append(f"previous AI: {prev['provider']} {prev['model']} did '{prev['stage']}': {prev['summary']}")
        if self.d["errors"]:
            e = self.d["errors"][-1]
            lines.append(f"last problem: {e['stage']}: {e['error']}")
        return "\n".join(lines)[:maxchars] + "\n\n"

    # ------------------------------------------------------------------ SCRIPT LOCK
    @property
    def locked(self):
        return bool(self.d["script"]["locked"])

    def locked_script(self):
        return json.loads(json.dumps(self.d["script"]["data"])) if self.locked else None

    def lock_script(self, script, source=""):
        """Lock `script`. If a script is ALREADY locked, the locked one wins and is returned (the new one is ignored).
        Owner overrides: UNLOCK_SCRIPT=1 -> archive the old version and lock the new one; APPROVE_PENDING=1 is
        handled by approve_pending()."""
        s = self.d["script"]
        new_h = script_hash(script)
        if s["locked"]:
            if new_h == s["hash"]:
                return self.locked_script()
            if _truthy("UNLOCK_SCRIPT"):
                self.log(f"[lock] UNLOCK_SCRIPT=1 -> v{s['version']} archived, locking the new script")
                self._archive_current("unlocked by owner")
            else:
                self.d["pending"].append({"at": _now(), "source": source, "hash": new_h, "reason": "regenerated by an AI",
                                          "script": script})
                self.d["pending"] = self.d["pending"][-3:]
                self.save()
                self.log(f"[lock] SCRIPT IS LOCKED (v{s['version']}). A different script ({new_h}) from {source or 'an AI'} "
                         "was IGNORED and saved as a pending proposal; the approved script is used.")
                return self.locked_script()
        s["version"] += 1
        s["hash"] = new_h
        s["data"] = json.loads(json.dumps(script))
        s["locked"] = True
        s["locked_at"] = _now()
        s["source"] = source
        self.save()
        self.log(f"[lock] script v{s['version']} LOCKED ({new_h}, {len(script.get('scenes', []))} scenes, source: {source or '-'})")
        return self.locked_script()

    def _archive_current(self, why):
        s = self.d["script"]
        if s["data"] is not None:
            s["history"].append({"version": s["version"], "hash": s["hash"], "at": s.get("locked_at", ""),
                                 "why": why, "data": s["data"]})
        s["locked"] = False

    def propose_change(self, script, reason="", source=""):
        """An AI (or a later step) wants a different script: it is stored, NOT applied."""
        if not self.locked:
            raise ScriptLockError("nothing locked yet; just lock the script")
        self.d["pending"].append({"at": _now(), "source": source, "hash": script_hash(script), "reason": reason, "script": script})
        self.d["pending"] = self.d["pending"][-3:]
        self.save()
        return len(self.d["pending"])

    def approve_pending(self, index=-1):
        """Owner approval: apply a saved proposal as the next version (old version stays in history)."""
        if not self.d["pending"]:
            return None
        p = self.d["pending"].pop(index)
        self._archive_current("replaced by approved change")
        s = self.d["script"]
        s["version"] += 1
        s["hash"] = p["hash"]
        s["data"] = p["script"]
        s["locked"] = True
        s["locked_at"] = _now()
        s["source"] = "owner-approved:" + str(p.get("source", ""))
        self.d["approved_changes"].append({"at": _now(), "hash": p["hash"], "reason": p.get("reason", "")})
        self.save()
        self.log(f"[lock] owner approved a change -> v{s['version']}")
        return self.locked_script()

    def restore(self, version):
        """Bring back an earlier approved version (becomes the newest version, locked)."""
        for h in self.d["script"]["history"]:
            if h["version"] == version:
                self._archive_current("restored older version")
                s = self.d["script"]
                s["version"] += 1
                s["data"], s["hash"], s["locked"], s["locked_at"] = h["data"], h["hash"], True, _now()
                s["source"] = f"restored v{version}"
                self.save()
                return self.locked_script()
        raise ScriptLockError(f"version {version} not in history")

    def verify(self, scenes):
        """Call after voice/captions/render were built from `scenes`: True if the spoken text is still the locked one.
        `scenes` may carry extra appended scenes (CTA); only the first N, N = locked scene count, are compared."""
        if not self.locked:
            return True
        n = len(self.d["script"]["data"].get("scenes", []))
        cur = {"scenes": [{"text": sc.get("text", ""), "text_en": sc.get("text_en", "")} for sc in scenes[:n]]}
        locked = {"scenes": [{"text": sc.get("text", ""), "text_en": sc.get("text_en", "")}
                             for sc in self.d["script"]["data"]["scenes"]]}
        return script_hash(cur) == script_hash(locked)


# --------------------------------------------------------------------------- module-level current state
_CUR = {"state": None}


def begin(key, kind, **kw):
    st = ProjectState(key, kind, **kw)
    _CUR["state"] = st
    return st


def current():
    return _CUR["state"]


def end():
    _CUR["state"] = None
