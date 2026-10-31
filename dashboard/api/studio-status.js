const { API, repo, hdr, ready, safeJob } = require("./_gh");
// GET ?job=<id>&kind=edit|publish -> {state, pct, eta, stage, kind, meta?, results?, url}
const LBL = { A: "Setup (tools, video download)", 1: "Awaaz sunna + silence katna", 2: "Topic samajhna, cards plan karna", 3: "Captions, zoom, cards render", 4: "Final video save" };
module.exports = async (req, res) => {
  if (!ready(res)) return;
  const job = safeJob(req.query.job), pub = req.query.kind === "publish";
  const wf = pub ? "th_publish.yml" : "talking_head.yml", title = (pub ? "THP " : "TH ") + job;
  const g = (u) => fetch(API + u, { headers: hdr() });
  const runs = (await (await g(`/repos/${repo()}/actions/workflows/${wf}/runs?per_page=30`)).json()).workflow_runs || [];
  const r = runs.find(x => x.display_title === title);
  if (!r) return res.json({ state: "waiting", pct: 2, eta: 0 });
  const rel = await g(`/repos/${repo()}/releases/tags/th-${job}`);
  let notes = {}; if (rel.ok) { try { notes = JSON.parse((await rel.json()).body || "{}"); } catch (e) {} }
  if (r.status === "completed") {
    if (r.conclusion !== "success") return res.json({ state: "failed", url: r.html_url, results: notes.results || null });
    return res.json({ state: "done", pct: 100, eta: 0, meta: notes, yt: notes.yt || "", results: notes.results || null, url: r.html_url });
  }
  const now = Date.now(), t0 = Date.parse(r.run_started_at || r.created_at);
  if (r.status === "queued") return res.json({ state: "queued", pct: 3, eta: 0, stage: "Queue mein (GitHub worker ka wait)" });
  if (pub) {   // upload: no inner steps worth tracking -> time based estimate
    const est = 150, el = (now - t0) / 1000;
    return res.json({ state: "running", pct: Math.min(95, Math.round(100 * el / est)), eta: Math.max(15, Math.round(est - el)), stage: "Platforms par upload ho raha hai" });
  }
  const jobs = (await (await g(`/repos/${repo()}/actions/runs/${r.id}/jobs`)).json()).jobs || [];
  const steps = (jobs[0] && jobs[0].steps) || [];
  const R = notes.dur_out ? Math.round(notes.dur_out * 2.4 + 25) : 90;
  const est = { A: 100, 1: 45, 2: 20, 3: R, 4: 25 };
  const grp = (s) => /^[1-4] /.test(s.name) ? s.name[0] : (/^(Post |Complete job|Run actions\/upload)/.test(s.name) ? "Z" : "A");
  let done = 0, total = 0, stage = LBL.A, cur = "A";
  for (const k of ["A", "1", "2", "3", "4"]) {
    const ss = steps.filter(s => grp(s) === k);
    const fin = ss.length && ss.every(s => s.status === "completed");
    const run = ss.find(s => s.status === "in_progress");
    total += est[k];
    if (fin) done += est[k];
    else if (run || (k === "A" && ss.some(s => s.status === "completed"))) {
      const st = k === "A" ? t0 : Date.parse(run.started_at || new Date());
      done += Math.min((now - st) / 1000, est[k] * 0.95); stage = LBL[k]; cur = k;
    }
  }
  const pct = Math.min(98, Math.max(4, Math.round(100 * done / total)));
  res.json({ state: "running", pct, eta: Math.max(15, Math.round(total - done)), stage, kind: notes.kind || "", dur_out: notes.dur_out || 0, url: r.html_url });
};
