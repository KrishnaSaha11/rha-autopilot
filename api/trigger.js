// Triggers the GitHub Actions workflow with optional product + force inputs
// Vercel env vars: GH_PAT_ACTIONS (fine-grained PAT, Actions RW on rha-autopilot), TRIGGER_KEY, GH_REPO
export default async function handler(req, res) {
  const key = (req.query.k || "").toString();
  if (!process.env.TRIGGER_KEY || key !== process.env.TRIGGER_KEY) {
    return res.status(401).json({ ok: false, error: "wrong key" });
  }
  const repo = process.env.GH_REPO || "KrishnaSaha11/rha-autopilot";
  const inputs = {};
  if (req.query.product) inputs.product = req.query.product.toString();
  if (req.query.force === "1") inputs.force = "true";
  if (req.query.format) inputs.format = req.query.format.toString();
  const r = await fetch(
    `https://api.github.com/repos/${repo}/actions/workflows/daily.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.GH_PAT_ACTIONS}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main", inputs }),
    }
  );
  if (r.status === 204) return res.status(200).json({ ok: true });
  const text = await r.text();
  return res.status(500).json({ ok: false, error: r.status + ": " + text.slice(0, 200) });
}
