const { API, repo, hdr, auth, ALLOWED } = require("./_gh");
module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(405).end();
  if (!auth(req, res)) return;
  const { workflow, inputs } = req.body || {};
  if (!ALLOWED.includes(workflow)) return res.status(400).json({ error: "unknown workflow" });
  const clean = {};
  for (const [k, v] of Object.entries(inputs || {})) if (v !== "" && v != null) clean[k] = String(v).slice(0, 500);
  const r = await fetch(`${API}/repos/${repo()}/actions/workflows/${workflow}/dispatches`, {
    method: "POST", headers: { ...hdr(), "Content-Type": "application/json" },
    body: JSON.stringify({ ref: process.env.GH_REF || "main", inputs: clean }) });
  if (r.status === 204) return res.json({ ok: true });
  res.status(r.status).json({ error: (await r.text()).slice(0, 300) });
};
