const { API, repo, hdr, auth } = require("./_gh");
// GET /api/build-status  (header x-pass) -> {runs:[{id, wf, kind, title, state, pct, eta, stage, url, at}]}
// Live "loading screen" for the dashboard: latest runs of build.yml (Short) and build_long.yml (Long) + publish.yml.
// Percent is an honest estimate: the bot step is ~85% of the work, its time is guessed from the video type.
const WF = { "build.yml": { kind: "short", est: 30 * 60 }, "build_long.yml": { kind: "long", est: 75 * 60 }, "publish.yml": { kind: "publish", est: 4 * 60 } };
module.exports = async (req, res) => {
  if (!auth(req, res)) return;
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
};
