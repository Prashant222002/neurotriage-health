const { API, repo, hdr, auth } = require("./_gh");
module.exports = async (req, res) => {
  if (!auth(req, res)) return;
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
};
