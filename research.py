"""Round 3 - RESEARCH ENGINE: pick a topic, collect claims, check them against real sources, keep only what holds.

Old flow:  one LLM call "research this topic"  ->  facts that sounded right (numbers sometimes invented).
New flow:  1. topic + proven structure   (virality.viral_brief, unchanged - it already uses real YouTube outliers)
           2. claims                      (LLM turns the brief into short structured claims + search terms)
           3. evidence                    (PubMed abstracts + Wikipedia intro, free, no API key)
           4. verification                (LLM judges each claim against the evidence it was given)
           5. HARD filter in plain python (a claim that contains a number is dropped unless that number really appears
                                           in the evidence it cites - the LLM cannot talk its way past this)
Result: a plain-text fact sheet (same shape the script writer already expects) + a structured record for project memory.

Never fatal: no internet / empty answers -> level "llm_only" (numbers stripped) instead of a crashed build.
All network access goes through `http_get` so tests run offline."""
import json
import re
import xml.etree.ElementTree as ET

import requests

UA = {"User-Agent": "NeuroTriageBot/8 (educational video research)"}
NUM = re.compile(r"\d+(?:[.,]\d+)?")
MIN_FACTS = 3


def _log(*a):
    print(*a, flush=True)


def _json(txt):
    if not txt:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", str(txt).strip()).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def default_http_get(url, params=None, timeout=15):
    r = requests.get(url, params=params, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.text


# --------------------------------------------------------------------------- evidence fetchers
def fetch_pubmed(query, http_get, n=4):
    """PubMed E-utilities (free, no key). -> [{'kind','title','url','text'}]"""
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    ids = _json(http_get(base + "esearch.fcgi", {"db": "pubmed", "term": query, "retmax": n, "sort": "relevance",
                                                  "retmode": "json"}))
    ids = ((ids or {}).get("esearchresult") or {}).get("idlist") or []
    if not ids:
        return []
    xml = http_get(base + "efetch.fcgi", {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"})
    out = []
    root = ET.fromstring(xml)
    for art in root.iter("PubmedArticle"):
        pmid = (art.findtext(".//PMID") or "").strip()
        title = "".join(art.find(".//ArticleTitle").itertext()).strip() if art.find(".//ArticleTitle") is not None else ""
        abst = " ".join("".join(a.itertext()).strip() for a in art.findall(".//Abstract/AbstractText"))
        if pmid and (title or abst):
            out.append({"kind": "pubmed", "title": title[:160], "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        "text": (title + ". " + abst)[:1500]})
    return out


def fetch_wikipedia(query, http_get, n=2):
    """Wikipedia intro paragraphs (good for definitions / basic anatomy). -> same shape"""
    api = "https://en.wikipedia.org/w/api.php"
    s = _json(http_get(api, {"action": "opensearch", "search": query, "limit": n, "format": "json"}))
    titles = (s[1] if isinstance(s, list) and len(s) > 1 else []) or []
    out = []
    for t in titles[:n]:
        d = _json(http_get(api, {"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "redirects": 1,
                                 "titles": t, "format": "json"}))
        for pg in ((d or {}).get("query") or {}).get("pages", {}).values():
            ex = (pg.get("extract") or "").strip()
            if ex:
                out.append({"kind": "wikipedia", "title": pg.get("title", t), "text": ex[:1500],
                            "url": "https://en.wikipedia.org/wiki/" + str(pg.get("title", t)).replace(" ", "_")})
    return out


def gather_evidence(terms, http_get, log=_log):
    ev, seen = [], set()
    for term in terms[:3]:
        for fn in (fetch_pubmed, fetch_wikipedia):
            try:
                for e in fn(term, http_get):
                    if e["url"] not in seen:
                        seen.add(e["url"])
                        ev.append(e)
            except Exception as ex:
                log(f"[research] {fn.__name__}('{term[:40]}') failed: {str(ex)[:80]}")
    return ev[:10]


# --------------------------------------------------------------------------- steps 2-5
def extract_claims(ask, brief, mode, safety):
    prompt = f"""From this research brief extract a structured fact sheet for a short educational video.
{brief}
{safety}
Return ONLY JSON:
{{"topic":"one line","search_terms":["2-3 short ENGLISH search phrases that would find the studies/definitions on PubMed or Wikipedia (e.g. 'sleep deprivation cortisol students')"],
"claims":["5-7 short, single-idea factual claims; each must be checkable; keep any number the brief gave"],
"hook":"the hook line or formula named in the brief","tip":"one practical, safe takeaway","structure":"the proven structure to follow, one line"}}"""
    d = _json(ask(prompt, json_mode=True))
    if not isinstance(d, dict):
        return None
    claims = [str(c).strip() for c in (d.get("claims") or []) if str(c).strip()]
    terms = [str(t).strip() for t in (d.get("search_terms") or []) if str(t).strip()]
    if not claims:
        return None
    topic = str(d.get("topic") or "").strip()
    if not terms and topic:
        terms = [topic]
    return {"topic": topic, "terms": terms, "claims": claims[:8], "hook": str(d.get("hook") or "").strip(),
            "tip": str(d.get("tip") or "").strip(), "structure": str(d.get("structure") or "").strip()}


def _numbers(s):
    return [n.replace(",", ".") for n in NUM.findall(s or "")]


def number_supported(claim, evidence_texts):
    """True if the claim has no numbers, or EVERY number in it appears in the cited evidence text."""
    nums = _numbers(claim)
    if not nums:
        return True
    blob = " ".join(evidence_texts).replace(",", ".")
    return all(re.search(r"(?<![\d.])" + re.escape(n) + r"(?![\d])", blob) for n in nums)


def verify_claims(ask, claims, evidence, log=_log):
    """-> list of {'claim','verdict','cites':[idx],'fix'}. Verdict from the LLM, then the python number filter."""
    if not evidence:
        return [{"claim": c, "verdict": "unchecked", "cites": [], "fix": ""} for c in claims]
    ev_txt = "\n".join(f"[{i}] ({e['kind']}) {e['title']}: {e['text'][:700]}" for i, e in enumerate(evidence))
    cl_txt = "\n".join(f"{i}. {c}" for i, c in enumerate(claims))
    prompt = f"""You are a strict fact-checker. Judge each CLAIM using ONLY the EVIDENCE below (do not use memory).
EVIDENCE:
{ev_txt}

CLAIMS:
{cl_txt}

For each claim: "supported" (evidence clearly backs it), "uncertain" (related but not clearly backed - give a safer, hedged
rewording in "fix"), or "unsupported" (contradicted or not backed). Cite evidence numbers. Never keep a number the evidence does not contain.
Return ONLY JSON: {{"results":[{{"i":0,"verdict":"supported","cites":[1],"fix":""}}]}}"""
    d = _json(ask(prompt, json_mode=True))
    res = {}
    for r in ((d or {}).get("results") or []):
        try:
            res[int(r.get("i"))] = r
        except Exception:
            continue
    out = []
    for i, c in enumerate(claims):
        r = res.get(i)
        if not r:
            out.append({"claim": c, "verdict": "unchecked", "cites": [], "fix": ""})
            continue
        v = str(r.get("verdict", "")).lower()
        cites = [int(x) for x in (r.get("cites") or []) if str(x).isdigit() and int(x) < len(evidence)]
        fix = str(r.get("fix") or "").strip()
        out.append({"claim": c, "verdict": v if v in ("supported", "uncertain", "unsupported") else "unchecked",
                    "cites": cites, "fix": fix})
    return out


def finalize(claims_checked, evidence, level_hint):
    """Hard python filter. Returns (verified_texts, dropped, used_evidence_idx)."""
    verified, dropped, used = [], [], []
    for r in claims_checked:
        text, v = r["claim"], r["verdict"]
        cited = [evidence[i]["text"] + " " + evidence[i]["title"] for i in r["cites"]] if evidence else []
        if v == "supported":
            if number_supported(text, cited):
                verified.append(text)
                used += r["cites"]
            else:
                dropped.append((text, "number not in cited evidence"))
        elif v == "uncertain" and r["fix"]:
            if number_supported(r["fix"], cited):
                verified.append(r["fix"])
                used += r["cites"]
            else:
                dropped.append((text, "uncertain + number not backed"))
        elif v == "unchecked":
            if not _numbers(text):                      # nothing could be checked: keep numberless claims only
                verified.append(text)
            else:
                dropped.append((text, "number, could not be checked"))
        else:
            dropped.append((text, "unsupported"))
    return verified, dropped, sorted(set(used))


def run(ask, done, mode, safety, brief_fn=None, http_get=None, log=_log, directive=""):
    """-> dict(topic, facts_text, verified, dropped, sources, level, hook, tip) or None (caller uses the old path)."""
    http_get = http_get or default_http_get
    brief = brief_fn(ask, done, mode, safety) if brief_fn else None
    if not brief:
        prompt = (f"{directive or 'Pick ONE fresh topic'} for an Indian Hinglish short-video channel ({mode}); already covered: {done[-40:]}.\n{safety}\n"
                  "Return plain text: TOPIC; HOOK; 5-6 facts; one practical tip.")
        brief = ask(prompt, search=True) or ask(prompt)
    if not brief:
        return None
    ex = extract_claims(ask, brief, mode, safety)
    if not ex:
        log("[research] could not structure the brief -> old plain fact sheet")
        return {"topic": "", "facts_text": str(brief), "verified": [], "dropped": [], "sources": [], "level": "unstructured",
                "hook": "", "tip": ""}
    evidence = gather_evidence(ex["terms"], http_get, log)
    log(f"[research] topic: {ex['topic'][:80]} | {len(ex['claims'])} claims | {len(evidence)} evidence passages "
        f"({sum(1 for e in evidence if e['kind'] == 'pubmed')} PubMed)")
    checked = verify_claims(ask, ex["claims"], evidence, log)
    verified, dropped, used = finalize(checked, evidence, "")
    if len(verified) < MIN_FACTS:                          # keep the build alive with numberless claims
        for r in checked:
            if len(verified) >= MIN_FACTS:
                break
            if r["verdict"] != "unsupported" and not _numbers(r["claim"]) and r["claim"] not in verified:
                verified.append(r["claim"])
    if not verified:
        log("[research] nothing survived verification -> old plain fact sheet")
        return {"topic": ex["topic"], "facts_text": str(brief), "verified": [], "dropped": dropped, "sources": [],
                "level": "unstructured", "hook": ex["hook"], "tip": ex["tip"]}
    if not evidence:
        level = "llm_only"
    elif any(r["verdict"] == "supported" for r in checked) and len(verified) >= MIN_FACTS and used:
        level = "verified"
    else:
        level = "partial"
    sources = [{"title": evidence[i]["title"], "url": evidence[i]["url"]} for i in used][:6]
    lines = [f"TOPIC: {ex['topic']}",
             "VERIFIED FACTS (the script may use ONLY these facts; do not add numbers, studies or statistics of your own):"]
    lines += [f"{i}. {f}" for i, f in enumerate(verified, 1)]
    lines += [f"HOOK: {ex['hook']}", f"PRACTICAL TIP: {ex['tip']}", f"PROVEN STRUCTURE: {ex['structure']}",
              "SOURCES: " + ("; ".join(f"{s['title'][:70]} ({s['url']})" for s in sources) or "general medical consensus (no direct citation found)"),
              f"RESEARCH LEVEL: {level}"]
    log(f"[research] level={level}: {len(verified)} facts kept, {len(dropped)} dropped, {len(sources)} sources")
    return {"topic": ex["topic"], "facts_text": "\n".join(lines), "verified": verified, "dropped": dropped,
            "sources": sources, "level": level, "hook": ex["hook"], "tip": ex["tip"]}
