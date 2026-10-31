"""ROUND 4 TEST - speed + control: batched vision, parallel search/download, footage cache, separate Short/Long workflows.
No network. Run: python tests/test_round4.py"""
import json, os, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
for k in list(os.environ):
    if any(h in k for h in ("GROQ", "GEMINI", "ELEVEN", "VISION", "PREFETCH", "FOOTAGE")):
        del os.environ[k]
os.environ.update(GROQ_API_KEY="x", GEMINI_API_KEY="y")
import bot
bot.WORK = tmp / "work"
n = 0
def check(name, cond):
    global n
    print(("PASS " if cond else "FAIL ") + name); n += 1
    assert cond, name

# ------------------------------------------------ 1. search cache
calls = []
def fake_search(q):
    calls.append(q); return [{"id": "px1", "thumb": "t", "url": "u"}] if q != "empty" else []
r1 = bot.cached_search("pexels", "brain", fake_search); r2 = bot.cached_search("pexels", "brain", fake_search)
check("2nd identical search served from cache (1 API call, same result)", calls == ["brain"] and r1 == r2)
bot.cached_search("pexels", "empty", fake_search); bot.cached_search("pexels", "empty", fake_search)
check("EMPTY results are never cached (rate-limited key can't poison it)", calls.count("empty") == 2)
bot.LANDSCAPE = True; bot.cached_search("pexels", "brain", fake_search); bot.LANDSCAPE = False
check("portrait vs landscape cached separately", calls.count("brain") == 2)

# ------------------------------------------------ 2. no-repeat history
bot.mark_used("px1"); bot.mark_used("pb9")
check("recently used clips remembered", {"px1", "pb9"} <= bot.used_recent())
old = json.loads(bot._used_file().read_text()); old["px_old"] = time.time() - 20 * 86400; bot._used_file().write_text(json.dumps(old))
check("clips used > 14 days ago are allowed again", "px_old" not in bot.used_recent())
bot._pexels = lambda q, n=10: [{"id": "px1", "thumb": "t", "dur": 8, "w": 1080, "h": 1920, "portrait": True},
                               {"id": "px2", "thumb": "t", "dur": 8, "w": 1080, "h": 1920, "portrait": True}]
bot._pixabay = lambda q, n=12: []
bot.USED.clear()
c = bot.gather_candidates(["fresh query"], 4)
check("gather skips yesterday's clip (px1) but keeps the fresh one", [x["id"] for x in c] == ["px2"])

# ------------------------------------------------ 3. cache pruning
d = bot.footage_dir()
for i in range(5):
    f = d / f"clip_t{i}.mp4"; f.write_bytes(b"x" * 400_000); os.utime(f, (1000 + i, 1000 + i))
left = bot.prune_footage(max_mb=1.0)
names = sorted(p.name for p in d.glob("clip_t*.mp4"))
check("prune deletes OLDEST clips first until under the limit", names == ["clip_t3.mp4", "clip_t4.mp4"] and left <= 1.0)

# ------------------------------------------------ 4. batched vision
bot.USED.clear(); bot._used_file().write_text("{}")
def mk_cands(i): return [{"id": f"s{i}c{k}", "thumb": "t", "url": "u", "dur": 8, "w": 1080, "h": 1920, "portrait": True} for k in range(3)]
bot.gather_candidates = lambda queries, need: mk_cands(int(queries[0]))
bot.contact_sheet = lambda cands: b"JPG" + cands[0]["id"].encode()
ask_calls = []
def fake_ask(prompt, search=False, json_mode=False, image=None, task=None):
    ask_calls.append(image)
    if isinstance(image, list):
        k = len(image); nm = sum(1 for c in ask_calls if isinstance(c, list))
        res = [{"scene": i + 1, "best": [2, 1], "relevant": True} for i in range(k)]
        if nm == 1: res = res[:-1]                                # model forgets the last scene of batch 1
        if nm == 2: res[0]["relevant"] = False                    # batch 2, first scene (scene 5): nothing fits
        return json.dumps({"scenes": res})
    return json.dumps({"best": [3], "relevant": True})            # single-scene fallback answer
bot.ask = fake_ask
dl = []
active = [0, 0]
def fake_dl(c):
    dl.append(c["id"]); active[0] += 1; active[1] = max(active[1], active[0]); time.sleep(0.05); active[0] -= 1
    if c["id"] == "s5c1": raise RuntimeError("404")
    return Path(tmp / f"{c['id']}.mp4"), (1080, 1920, 8.0)
bot.download_clip = fake_dl
items = [({"text": f"line {i}", "queries": [str(i)]}, 4.0, 1) for i in range(9)]
t0 = time.time(); out = bot.pick_clips_batch(items, "topic"); el = time.time() - t0
multi = [c for c in ask_calls if isinstance(c, list)]
check("9 scenes -> 3 batched vision calls (+1 single fallback), not 9", len(multi) == 3 and len(ask_calls) == 4)
check("each batched call carries one image per scene (multi-image)", [len(c) for c in multi] == [4, 4, 1] or sorted(len(c) for c in multi) == [1, 4, 4])
check("scene the model skipped got the single-scene fallback pick (3rd clip)", out[3][0]["id"] == "s3c2")
check("relevant=false scene -> [] (motion graphic), others fine", out[4] == [] and all(out[i] for i in (0, 1, 2, 3, 5, 6, 7, 8)))
check("a failed download falls through to the next candidate", out[5] and out[5][0]["id"] == "s5c0")
check("downloads ran in parallel (up to 4 at once)", 2 <= active[1] <= 4)
check("picked clips are recorded as used", "s0c1" in bot.used_recent())
bot.download_clip = lambda c: (_ for _ in ()).throw(RuntimeError("all dead"))
out = bot.pick_clips_batch(items[:2], "topic")
check("every download failing -> [] per scene, no crash", out == [[], []])
bot.gather_candidates = lambda q, need: (_ for _ in ()).throw(RuntimeError("search boom")) if q[0] == "1" else mk_cands(0)
bot.download_clip = fake_dl
out = bot.pick_clips_batch(items[:3], "topic")
check("one scene's search crashing does not stop the others", out[1] == [] and out[0] and out[2])
bot.ask = bot.ask  # restore not needed

# ------------------------------------------------ 5. Groq payload really contains several images
import requests
sent = {}
class R:
    status_code = 200; headers = {}
    def json(self): return {"choices": [{"message": {"content": "ok"}}]}
    text = ""
import importlib; importlib.reload(bot) if False else None
real_post = requests.post
requests.post = lambda url, headers=None, json=None, timeout=0: (sent.update(body=json) or R())
import keyring; keyring.reset()
b2 = importlib.reload(bot)
b2.GROQ_VISION_MODELS = ["vision-m"]
out = b2.ask_groq("p", json_mode=True, image=[b"a", b"b", b"c"])
cont = sent["body"]["messages"][-1]["content"]
check("ask_groq sends 3 image_url parts for 3 images", out == "ok" and sum(1 for x in cont if x["type"] == "image_url") == 3)
sent.clear(); b2.ask_groq("p", image=b"single")
check("single image still works (backwards compatible)", sum(1 for x in sent["body"]["messages"][-1]["content"] if x["type"] == "image_url") == 1)
requests.post = real_post

# ------------------------------------------------ 6. workflows
import yaml
W = ROOT / ".github/workflows"
S, L = (yaml.safe_load((W / f).read_text()) for f in ("build.yml", "build_long.yml"))
st, lt = (W / "build.yml").read_text(), (W / "build_long.yml").read_text()
check("Short workflow: cron schedule + manual, VIDEO_TYPE fixed to short", "schedule" in S[True] and "VIDEO_TYPE: short" in st and "video_type" not in S[True]["workflow_dispatch"]["inputs"])
check("Long workflow: manual only (no cron), VIDEO_TYPE long, FORCE_LONG 1", "workflow_dispatch" in L[True] and "VIDEO_TYPE: long" in lt and 'FORCE_LONG: "1"' in lt)
check("both share ONE concurrency group (never two videos at once), no cancel", S["concurrency"] == L["concurrency"] and S["concurrency"]["cancel-in-progress"] is False)
check("long has its own checkpoint cache prefix", "ckptlong-" in lt and "ckptlong-" not in st)
check("both restore + save the footage cache", all("work/footage" in t and "Save footage cache" in t for t in (st, lt)))
check("long: scheduled publish default 19:00, input overrides", "publish_time_ist || '19:00'" in lt)
print(f"\nALL {n} ROUND-4 CHECKS PASSED")
