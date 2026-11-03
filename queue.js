const { API, repo, hdr, auth } = require("./_gh");
// GET /api/queue  (header x-pass = DASH_PASSWORD)
// -> {items:[{id, kind, publish_at, privacy, meta:{title, yt_description, ig_caption, hashtags}, platforms:{name:status}, art:{id,name,mb}|null}]}
// Reads the manifests the bot commits to queue/*.json + the matching video artifact. Read-only, changes nothing.
module.exports = async (req, res) => {
  if (!auth(req, res)) return;
  try {
    const ref = process.env.GH_REF || "main";
    const g = (u, extra) => fetch(API + u, { headers: { ...hdr(), ...(extra || {}) } });
    const lr = await g(`/repos/${repo()}/contents/queue?ref=${encodeURIComponent(ref)}`);
    if (!lr.ok) return res.status(lr.status).json({ error: "queue folder read failed (HTTP " + lr.status + ")" });
    const names = (await lr.json()).map(f => f.name).filter(n => /^[\w.-]+\.json$/.test(n)).sort().reverse().slice(0, 14);
    const mans = await Promise.all(names.map(async n => {
      try {
        const r = await g(`/repos/${repo()}/contents/queue/${n}?ref=${encodeURIComponent(ref)}`, { Accept: "application/vnd.github.raw+json" });
        return r.ok ? JSON.parse(await r.text()) : null;
      } catch (e) { return null; }
    }));
    const ar = await g(`/repos/${repo()}/actions/artifacts?per_page=100`);
    const arts = ar.ok ? ((await ar.json()).artifacts || []).filter(a => !a.expired) : [];
    const items = mans.filter(Boolean).map(m => {
      const a = arts.find(x => x.name === m.artifact);
      const plats = {};
      for (const [k, v] of Object.entries(m.platforms || {})) plats[k] = (v && v.status) || "";
      const meta = m.meta || {};
      return {
        id: m.id, kind: m.kind, built: !!m.built, built_at: m.built_at || "", publish_at: m.publish_at || "",
        privacy: m.privacy || "", status: m.status || "",
        meta: { title: meta.title || "", yt_description: meta.yt_description || "", ig_caption: meta.ig_caption || "", hashtags: meta.hashtags || [] },
        platforms: plats,
        art: a ? { id: a.id, name: a.name, mb: +(a.size_in_bytes / 1e6).toFixed(1) } : null,
      };
    }).sort((x, y) => String(y.publish_at).localeCompare(String(x.publish_at)));
    res.json({ items });
  } catch (e) {
    res.status(500).json({ error: String(e.message || e).slice(0, 200) });
  }
};
