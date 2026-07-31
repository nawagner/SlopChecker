# 2026-07-31 — etbrooking — #27 landing page

Session: Fable via Claude Code (two sessions; the first died to a hook/cwd
issue — hooks resolve `scripts/` relative to cwd, so don't leave the session
cd'd into `worker/`).

- **Landed:** `worker/public/index.html` (full landing page replacing the
  scaffold stub) + `worker/public/demo-report.html` (pre-rendered sample
  evidence report, the upload flow's fallback target).
- **Design:** the hero is an annotated specimen — the product demonstrated on
  its own copy ("cites a study that does not exist… scores 0.96 on an AI
  detector") with evidence chips, reusing the report renderer's exact design
  tokens (same CSS vars as `report/assets/report.css`), so site and report
  read as one artifact. Then: upload box, three-lane explainer
  (red/green/purple), how-it-works, live "API live · v0.1.0" strip at the
  bottom that hits `/api/health` through the Worker proxy to prove the
  Railway backend is up.
- **Upload flow degrades honestly:** the pipeline endpoint doesn't exist yet,
  so Run checks says so and drops you into the sample report. No fake
  processing.
- **Verified:** under `wrangler dev` on :8788 (real Worker runtime, so the
  /api proxy and status strip were exercised), reviewed by Emerson.
- **Deploy:** nothing to do — Nick's Cloudflare Git integration (#42) deploys
  main → production on merge.
- **Left:** wire the upload flow to the real pipeline endpoint once the
  runner/CLI (#5/#6) grows an API surface; demo copy pass (#25).
