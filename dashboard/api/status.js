const { API, repo, hdr, auth } = require("./_gh");
// GET /api/status             -> {runs:[...]}  (recent runs + artifacts)   [used by control.html]
// GET /api/status?view=build  -> {runs:[...]}  (live loading-screen data)  [used by auto.html; was /api/build-status]
// Merged into one file to stay within Vercel Hobby's 12 serverless-function limit.
const WF = { "build.yml": { kind: "short", est: 30 * 60 }, "build_long.yml": { kind: "long", est: 75 * 60 }, "publish.yml": { kind: "publish", est: 4 * 60 } };
async function buildStatus(req, res) {
  try {
    const g = async (u) => { const r = await fetch(API + u, { headers: hdr() }); return r.ok ? r.json() : {}; };
    const out = [];
    await Promise.all(Object.keys(WF).map(async (wf) => {
      const runs = ((await g(`/repos/${repo()}/actions/workflows/${wf}/runs?per_page=4`)).workflow_runs || []);
      for (const r of runs) {
        const live = r.status !== "completed";
        const ageH = (Date.now() - Date.parse(r.created_at)) / 36e5;
        if (!live && ageH > 30) continue;                      // only recent finished runs
        const item = { id: r.id, wf, kind: WF[wf].kind, title: r.display_title || r.name, url: r.html_url, at: r.created_at,
          state: live ? (r.status === "queued" ? "queued" : "running") : (r.conclusion === "success" ? "done" : (r.conclusion === "cancelled" ? "cancelled" : "failed")),
          pct: live ? 3 : 100, eta: 0, stage: "" };
        if (r.status === "in_progress") {
          const jobs = ((await g(`/repos/${repo()}/actions/runs/${r.id}/jobs`)).jobs || []);
          const steps = (jobs[0] && jobs[0].steps) || [];
          const isBuild = (s) => /^Build \(|^Publish what is due/.test(s.name);
          const others = steps.filter(s => !isBuild(s)), main = steps.find(isBuild);
          const t0 = Date.parse(r.run_started_at || r.created_at), est = WF[wf].est;
          let frac = 0.15 * (others.filter(s => s.status === "completed").length / Math.max(1, others.length));
          const cur = steps.find(s => s.status === "in_progress");
          if (main && main.status === "completed") frac += 0.85;
          else if (main && main.status === "in_progress") frac += 0.85 * Math.min(0.95, (Date.now() - Date.parse(main.started_at || new Date())) / 1000 / est);
          item.pct = Math.max(4, Math.min(98, Math.round(frac * 100)));
          item.eta = Math.max(30, Math.round(est * (1 - frac)));
          item.stage = !cur ? "Chal raha hai" : (isBuild(cur) ? (WF[wf].kind === "publish" ? "Upload ho raha hai" : "Research, script, awaaz, stock footage, render (bot chal raha hai)") : cur.name.replace(/^Run /, ""));
        } else if (r.status === "queued") item.stage = "GitHub worker ka wait (queue mein)";
        out.push(item);
      }
    }));
    out.sort((a, b) => String(b.at).localeCompare(String(a.at)));
    res.json({ runs: out.slice(0, 8) });
  } catch (e) { res.status(500).json({ error: String(e.message || e).slice(0, 200) }); }
}
async function runsStatus(req, res) {
  const j = async (u) => (await fetch(API + u, { headers: hdr() })).json();
  const runs = (await j(`/repos/${repo()}/actions/runs?per_page=8`)).workflow_runs || [];
  const out = [];
  for (const r of runs.slice(0, 6)) {
    let arts = [];
    if (r.status === "completed" && r.conclusion === "success") {
      arts = ((await j(`/repos/${repo()}/actions/runs/${r.id}/artifacts`)).artifacts || []).filter(a => !a.expired).map(a => ({ id: a.id, name: a.name, mb: +(a.size_in_bytes / 1e6).toFixed(1) }));
    }
    out.push({ id: r.id, name: r.name, status: r.status, conclusion: r.conclusion, at: r.created_at, url: r.html_url, arts });
  }
  res.json({ runs: out });
}
module.exports = async (req, res) => {
  if (!auth(req, res)) return;
  const view = (req.query && req.query.view) || "";
  return view === "build" ? buildStatus(req, res) : runsStatus(req, res);
};
