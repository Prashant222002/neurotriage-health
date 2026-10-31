const { handleUpload } = require("@vercel/blob/client");
// Browser uploads straight to Vercel Blob (no 4.5 MB limit). Needs a Blob store connected to the project (BLOB_READ_WRITE_TOKEN).
module.exports = async (req, res) => {
  try {
    const out = await handleUpload({
      body: req.body, request: req,
      onBeforeGenerateToken: async (pathname, clientPayload) => {
        if (!process.env.STUDIO_PASSWORD || clientPayload !== process.env.STUDIO_PASSWORD) throw new Error("Galat password");
        return { allowedContentTypes: ["video/*", "image/*", "audio/*"], maximumSizeInBytes: 600 * 1024 * 1024, addRandomSuffix: true }; },
      onUploadCompleted: async () => {},
    });
    res.json(out);
  } catch (e) { res.status(400).json({ error: String(e.message || e) }); }
};
