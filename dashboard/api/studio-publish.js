const { API, repo, hdr, ready, safeJob, pwOk } = require("./_gh");
// Password is checked on the SERVER against Vercel env STUDIO_PASSWORD (never stored in the page or repo).
module.exports = async (req, res) => {
  if (req.method !== "POST" || !ready(res)) return;
  const { job, password, title, description, tags, privacy, platforms } = req.body || {};
  if (!pwOk(password, res)) return;
  const j = safeJob(job);
  if (!j || !String(title || "").trim()) return res.status(400).json({ error: "title chahiye" });
  const r = await fetch(`${API}/repos/${repo()}/actions/workflows/th_publish.yml/dispatches`, {
    method: "POST", headers: { ...hdr(), "Content-Type": "application/json" },
    body: JSON.stringify({ ref: process.env.GH_REF || "main", inputs: {
      job: j, title: String(title).slice(0, 95), description: String(description || "").slice(0, 4500),
      tags: (Array.isArray(tags) ? tags.join(",") : String(tags || "")).slice(0, 450), platforms: (Array.isArray(platforms) ? platforms : ["youtube"]).filter(x => ["youtube", "instagram", "facebook"].includes(x)).join(",") || "youtube", privacy: ["public", "unlisted", "private"].includes(privacy) ? privacy : "public" } }) });
  res.status(r.ok ? 200 : r.status).json(r.ok ? { ok: true } : { error: (await r.text()).slice(0, 300) });
};
