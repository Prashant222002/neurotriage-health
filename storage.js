const { API, repo, hdr, auth } = require("./_gh");
// Storage manager (header x-pass = DASH_PASSWORD).
//   GET  -> {github:{total_mb, items:[{id,name,mb,age_h,keep,why}]}, blob:{ok,count,total_mb}}
//   POST {action:"delete_artifact", id, manifest, force} | {action:"clean_github"} | {action:"clean_blob"}
// GitHub artifacts = the built videos. Vercel Blob = raw files uploaded in the Studio page.
// Rule: a queue video is KEPT while any platform still needs a manual upload or is pending; only "all done" ones are auto-cleaned.
const ref = () => process.env.GH_REF || "main";
const g = (u, extra, method) => fetch(API + u, { method: method || "GET", headers: { ...hdr(), ...(extra || {}) } });

async function manifestFor(artName) {
  const m = /^queue-(\d{4}-\d\d-\d\d)(?:-(m\w+))?-(short|long)$/.exec(artName || "");
  if (!m) return null;
  const id = `${m[1]}-${m[3]}${m[2] ? "-" + m[2] : ""}`;
  const r = await g(`/repos/${repo()}/contents/queue/${id}.json?ref=${encodeURIComponent(ref())}`, { Accept: "application/vnd.github.raw+json" });
  if (!r.ok) return null;
  try { return await r.json().catch(async () => JSON.parse(await r.text())); } catch (e) { return null; }
}
const needsMe = (m) => !m || Object.values(m.platforms || {}).some(p => !["done", "scheduled"].includes(p.status));

async function listArtifacts() {
  const r = await g(`/repos/${repo()}/actions/artifacts?per_page=100`);
  if (!r.ok) throw new Error("artifacts read failed (HTTP " + r.status + ")");
  return ((await r.json()).artifacts || []).filter(a => !a.expired);
}
async function classify(a) {
  const age_h = (Date.now() - Date.parse(a.created_at)) / 36e5;
  const base = { id: a.id, name: a.name, mb: +(a.size_in_bytes / 1e6).toFixed(1), age_h: Math.round(age_h * 10) / 10 };
  if (/^queue-/.test(a.name)) {
    const m = await manifestFor(a.name);
    if (!m) return { ...base, keep: true, why: "manifest nahi mila, safe side par rakha" };
    return needsMe(m) ? { ...base, keep: true, why: "kisi platform par abhi upload baaki / manual hai" } : { ...base, keep: false, why: "sab platform par ho chuka" };
  }
  return age_h < 1 ? { ...base, keep: true, why: "abhi bana hai" } : { ...base, keep: false, why: "extra copy (queue wali file hi kaafi hai)" };
}
async function delArt(id) {
  const r = await g(`/repos/${repo()}/actions/artifacts/${String(id).replace(/\D/g, "")}`, {}, "DELETE");
  return r.status === 204 || r.status === 404;
}
async function blobList() {
  if (!process.env.BLOB_READ_WRITE_TOKEN) return { ok: false, note: "Blob store connect nahi hai", blobs: [] };
  const { list } = require("@vercel/blob");
  let cursor, blobs = [];
  for (let i = 0; i < 10; i++) { const r = await list({ cursor, limit: 1000 }); blobs = blobs.concat(r.blobs); if (!r.hasMore) break; cursor = r.cursor; }
  return { ok: true, blobs };
}

module.exports = async (req, res) => {
  if (!auth(req, res)) return;
  try {
    if (req.method === "GET") {
      const arts = await listArtifacts();
      const items = await Promise.all(arts.map(classify));
      let blob = { ok: false, count: 0, total_mb: 0 };
      try { const b = await blobList(); blob = { ok: b.ok, note: b.note || "", count: b.blobs.length, total_mb: +(b.blobs.reduce((s, x) => s + x.size, 0) / 1e6).toFixed(1) }; } catch (e) { blob.note = String(e.message || e).slice(0, 120); }
      return res.json({ github: { total_mb: +items.reduce((s, x) => s + x.mb, 0).toFixed(1), items }, blob });
    }
    if (req.method !== "POST") return res.status(405).end();
    const { action, id, manifest, force } = req.body || {};
    if (action === "delete_artifact") {
      const ar = await g(`/repos/${repo()}/actions/artifacts/${String(id).replace(/\D/g, "")}`);
      if (!ar.ok) return res.status(404).json({ error: "artifact nahi mila (expire ho chuka?)" });
      const a = await ar.json();
      if (!force && /^queue-/.test(a.name) && needsMe(await manifestFor(a.name)))
        return res.status(409).json({ error: "Is video ka upload abhi baaki hai (pending/manual). Pehle download karke upload kar lo, phir 'Phir bhi delete' dabao.", need_force: true });
      return res.json({ ok: await delArt(a.id), freed_mb: +(a.size_in_bytes / 1e6).toFixed(1) });
    }
    if (action === "clean_github") {
      const items = (await Promise.all((await listArtifacts()).map(async a => ({ a, c: await classify(a) })))).filter(x => !x.c.keep);
      let freed = 0, n = 0;
      for (const x of items) if (await delArt(x.a.id)) { n++; freed += x.a.size_in_bytes; }
      return res.json({ ok: true, deleted: n, freed_mb: +(freed / 1e6).toFixed(1) });
    }
    if (action === "clean_blob") {
      const b = await blobList();
      if (!b.ok) return res.status(400).json({ error: b.note });
      const old = b.blobs.filter(x => Date.now() - Date.parse(x.uploadedAt) > 3600e3);   // keep the last hour: an edit may be running
      const { del } = require("@vercel/blob");
      for (let i = 0; i < old.length; i += 100) await del(old.slice(i, i + 100).map(x => x.url));
      return res.json({ ok: true, deleted: old.length, freed_mb: +(old.reduce((s, x) => s + x.size, 0) / 1e6).toFixed(1) });
    }
    res.status(400).json({ error: "unknown action" });
  } catch (e) { res.status(500).json({ error: String(e.message || e).slice(0, 220) }); }
};
