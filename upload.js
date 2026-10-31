const { API, repo, hdr, auth } = require("./_gh");
// Small files only (Vercel body limit 4.5 MB): your own audio / short clip -> raw/<name> in the repo. Big videos: paste a direct link instead.
module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(405).end();
  if (!auth(req, res)) return;
  const { name, b64 } = req.body || {};
  const safe = String(name || "").replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 80);
  if (!safe || !b64 || b64.length > 4.2e6) return res.status(400).json({ error: "file missing or over ~3 MB (use a link)" });
  const u = `${API}/repos/${repo()}/contents/raw/${safe}`;
  const ex = await fetch(u, { headers: hdr() });
  const sha = ex.ok ? (await ex.json()).sha : undefined;
  const r = await fetch(u, { method: "PUT", headers: { ...hdr(), "Content-Type": "application/json" },
    body: JSON.stringify({ message: "upload " + safe, content: b64, sha, branch: process.env.GH_REF || "main" }) });
  res.status(r.ok ? 200 : r.status).json(r.ok ? { ok: true, path: "raw/" + safe } : { error: (await r.text()).slice(0, 300) });
};
