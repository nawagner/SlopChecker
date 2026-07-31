# 2026-07-31 — etbrooking — #19 skipped/errored rendering

Session: Fable via Claude Code (same session as the #27 landing-page log).
Picks up Dan's flag from PR #45: a `skipped` ledger row carries no `result`,
and the renderer showed class `score` with literal text "None".

- **Landed:** status-aware rendering in `report/html.py` + `report.css`, a
  skipped row in `tests/fixtures/sample_report.json`, three new renderer
  tests.
- **Design decision — one muted lane for both `skipped` and `errored`:**
  neither is a statement about the document, so neither may look like a pass
  (green), a fail (red), or a score (purple). Gray chip (`SKIPPED` / `ERROR`),
  reason in the ledger's detail column, `(reason)` inline in finding cards.
  Distinguishing skip vs error visually didn't earn a fifth color; the chip
  text carries the difference.
- **Bug fixed on the way:** summary tallies counted every ledger row's
  `result`, so a not-run row (`result: None`, non-bool) silently inflated
  the *scores* count. Tallies now count only `status: ok` rows; not-run rows
  get their own `not run ×N` count and a "N checks could not run — reported
  as coverage gaps, not passes" sentence in the verdict block. This is the
  "we report our own blind spots" demo line, rendered.
- **Findings:** a finding whose checks all failed to run gets a gray mark
  (`_finding_lane` → `skip`, weakest on overlap), not purple.
- **Left:** regenerate `worker/public/demo-report.html` from the updated
  fixture so the live sample shows the gap lane (needs both #57 and this PR
  merged first).
