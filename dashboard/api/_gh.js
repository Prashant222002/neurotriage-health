// Shared helpers. Vercel env: GH_TOKEN (fine-grained: Actions r/w + Contents r/w), GH_REPO ("owner/repo"), DASH_PASSWORD, GH_REF (default main)
const API = "https://api.github.com";
const repo = () => process.env.GH_REPO;
const hdr = () => ({ Authorization: "Bearer " + process.env.GH_TOKEN, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "neurotriage-dash" });
function auth(req, res) {
  const ok = process.env.DASH_PASSWORD && req.headers["x-pass"] === process.env.DASH_PASSWORD;
  if (!ok) { res.status(401).json({ error: "wrong password" }); return false; }
  if (!process.env.GH_TOKEN || !repo()) { res.status(500).json({ error: "GH_TOKEN / GH_REPO not set in Vercel" }); return false; }
  return true;
}
const ALLOWED = ["build.yml", "build_long.yml", "edit_raw.yml", "talking_head.yml", "th_publish.yml", "publish.yml", "analytics.yml"];
module.exports = { API, repo, hdr, auth, ALLOWED };
// Studio (round 9): public page, no dashboard password for editing. Only needs GH_TOKEN + GH_REPO.
module.exports.ready = (res) => (process.env.GH_TOKEN && repo()) ? true : (res.status(500).json({ error: "GH_TOKEN / GH_REPO not set in Vercel" }), false);
module.exports.safeJob = (j) => String(j || "").toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 16);
// One password for the whole Studio (Vercel env STUDIO_PASSWORD). Checked on the server only.
module.exports.pwOk = (pw, res) => (process.env.STUDIO_PASSWORD && pw === process.env.STUDIO_PASSWORD) ? true : (res.status(401).json({ error: "Galat password" }), false);
