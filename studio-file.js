const { API, repo, hdr, ready, safeJob } = require("./_gh");
// GET ?job=<id> -> redirects to a signed link of the edited mp4 (works for <video> preview and for download)
module.exports = async (req, res) => {
  if (!ready(res)) return;
  const rel = await fetch(`${API}/repos/${repo()}/releases/tags/th-${safeJob(req.query.job)}`, { headers: hdr() });
  if (!rel.ok) return res.status(404).json({ error: "video not ready or expired" });
  const a = ((await rel.json()).assets || []).find(x => x.name === "final_th.mp4");
  if (!a) return res.status(404).json({ error: "file missing" });
  const r = await fetch(`${API}/repos/${repo()}/releases/assets/${a.id}`, { headers: { ...hdr(), Accept: "application/octet-stream" }, redirect: "manual" });
  const loc = r.headers.get("location");
  if (!loc) return res.status(404).json({ error: "no link" });
  res.redirect(302, loc);
};
