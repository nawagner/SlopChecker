# 2026-07-31 — nawagner (Claude Sonnet 5) — Railway → GitHub deploy connection

**Issues worked:** #27.

## What changed

- No repo changes. Diagnosed and closed the deploy gap flagged in
  etbrooking's last #27 comment: `/check` was 404ing in production 15+
  minutes after the web-layer merge (#70), same as the Cloudflare Worker
  once was before its Git integration landed.
- `railway status --json` showed `"source": null` on the `slopchecker`
  service — it had never been connected to a GitHub repo. Every deploy so
  far went through manual `railway up` from whatever local checkout
  happened to be around; the live deployment's build command
  (`pip install -e '.[web]'`) was missing the `pdf,docx` extras current
  `railway.toml` adds, confirming it predated both that file and the
  `/check` route.
- Nick connected the Railway GitHub App to `nawagner/SlopChecker` by hand
  in the dashboard (Settings → Source → Connect Repo) — an OAuth grant,
  can't be done from a non-interactive session, same category as the
  `wrangler login` step flagged earlier in this issue. That connection
  alone triggered an automatic deploy of current `main`
  (`017d50e`, danparshall's #78 PDF-rendering fix).
- Verified live end-to-end rather than trusting the dashboard status:
  `/health` → 200, `/check` with a hand-built minimal PDF (no fixture PDF
  exists in `tests/fixtures/`, so I generated one with raw PDF syntax via
  Python, no external deps) → full `report.json` back
  (`"recommendation": "human_review"`), matching the pipeline's real
  output shape.

## Decisions

- Split the fix into "what I can do" vs. "what needs Nick": the GitHub App
  authorization is an OAuth/account-settings action I don't perform even
  with explicit ask — flagged it and gave exact dashboard steps + a direct
  deep link to the service settings page, then verified the result via
  `railway status --json` and live curls once he said he'd done it, rather
  than taking his word for it.
- Used the CLI (`railway status --json`) as the source of truth over the
  dashboard screenshot pattern from the Cloudflare session — Railway's CLI
  exposes `source`, `latestDeployment.meta.{branch,commitHash,repo}`
  directly, which is a cleaner signal than eyeballing a screenshot for
  "did the connect-repo click actually take."

## Dead ends

- Tried `textutil -convert pdf` (macOS built-in) to turn one of the
  citation fixture `.txt` files into a smoke-test PDF — this macOS version
  doesn't support PDF as a `-convert` output format. Fell back to writing
  a minimal valid PDF by hand (a handful of PDF objects + xref table) in
  ~30 lines of Python; pymupdf on the server parsed it fine.

## Left to do

- Nothing blocking on #27's deploy-connection gap. `CROSSREF_MAILTO` and
  `CANDID_API_KEY` are still unset on Railway (pre-existing, reported as a
  coverage gap by `/config`, not a deploy issue).
- Worth a glance after the next `main` push that touches Python source to
  confirm the auto-deploy fires again (this session only observed the
  one-time deploy triggered by connecting the source).
