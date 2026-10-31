const { API, repo, hdr, auth } = require("./_gh");
// GET /api/download?id=<artifact id>&p=<password>  -> redirects to GitHub's signed zip link (browser downloads it)
module.exports = async (req, res) => {
  req.headers["x-pass"] = req.headers["x-pass"] || req.query.p;
  if (!auth(req, res)) return;
  const id = String(req.query.id || "").replace(/\D/g, "");
  const r = await fetch(`${API}/repos/${repo()}/actions/artifacts/${id}/zip`, { headers: hdr(), redirect: "manual" });
  const loc = r.headers.get("location");
  if (!loc) return res.status(404).json({ error: "artifact expired or not found" });
  res.redirect(302, loc);
};
