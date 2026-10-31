const { API, repo, hdr, ready, safeJob, pwOk } = require("./_gh");
const OK = /^https:\/\/([a-z0-9-]+\.public\.blob\.vercel-storage\.com\/|(www\.|m\.)?youtube\.com\/|youtu\.be\/)/i;
module.exports = async (req, res) => {
  if (req.method !== "POST" || !ready(res)) return;
  const { video, inserts = [], audio = "", audio_vol, job, style, hook, password } = req.body || {};
  if (!pwOk(password, res)) return;
  const j = safeJob(job);
  if (!j || !OK.test(String(video || ""))) return res.status(400).json({ error: "video link must be an uploaded file or a YouTube link" });
  const ins = (Array.isArray(inserts) ? inserts : []).filter(u => OK.test(u)).slice(0, 6).join(",");
  const aud = OK.test(String(audio || "")) ? String(audio) : "";
  const vol = Math.min(0.6, Math.max(0.05, Number(audio_vol) || 0.22)).toFixed(2);
  const r = await fetch(`${API}/repos/${repo()}/actions/workflows/talking_head.yml/dispatches`, {
    method: "POST", headers: { ...hdr(), "Content-Type": "application/json" },
    body: JSON.stringify({ ref: process.env.GH_REF || "main", inputs: { job: j, video, inserts: ins, audio: aud, audio_vol: vol, style: style === "white" ? "white" : "red", hook: String(hook || "").slice(0, 60) } }) });
  res.status(r.ok ? 200 : r.status).json(r.ok ? { ok: true, job: j } : { error: (await r.text()).slice(0, 300) });
};
