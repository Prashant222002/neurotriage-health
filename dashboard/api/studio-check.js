const { pwOk } = require("./_gh");
// POST {password} -> {ok:true} | 401. Lets the page confirm the password before a long upload.
module.exports = (req, res) => {
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });
  if (!pwOk((req.body || {}).password, res)) return;
  res.json({ ok: true });
};
