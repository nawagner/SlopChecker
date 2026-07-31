# 2026-07-31 — danparshall — #3 core data model

Session: Fable via Claude Code, branch `danparshall/3-core-models`.

- **Landed:** `src/slopchecker/models.py` (Span, Anchor, Check, CheckResult,
  Finding, FlattenedDoc, LedgerRow, RunInfo, Summary, EvidenceReport, Verdict),
  `tests/test_models.py` (18 tests), `docs/DATA_MODEL.md` (the human-readable
  contract + how-to-run-tests).
- **Naming decision:** CLAUDE.md names (`FlattenedDoc`/`Finding`/`EvidenceReport`)
  over the issue-#3 strawman (`Document`/`Report`); module-level aliases keep the
  issue names importable. Field layout codifies the shipped #35/#40 fixture
  (`tests/fixtures/sample_report.json`) rather than the issue-body field list, so
  `report/` consumes `EvidenceReport.to_report_dict()` with zero renderer changes
  — verified by a wiring test that feeds the fixture through `render_report`.
- **Strawman fields dropped, deliberately:** `Finding.severity` (renderer derives
  lane from check results; a stored severity is a verdict by another name) and
  `Finding.confidence` (scores live in check results). Kept from the strawman:
  `Check` registry model (tier/cost/needs_network), `Span` offsets (optional,
  inside `Anchor`), `Finding.evidence` dict.
- **Added per issue thread:** first-class `status: ok|skipped|errored` + mandatory
  `reason` on CheckResult/LedgerRow (consistency enforced by validators), and
  Dan's optional `Verdict` enum (supported/overstated/unsupported/contradicted/
  unverifiable) for the #11 claim-support checks.
- **Strictness choices:** `result` is `StrictBool|StrictInt|StrictFloat` (rejects
  `"true"` and any prose); `extra="forbid"` everywhere (typos fail loudly);
  `note` enforced one-line.
- **Dead ends:** none real. Noted that pydantic was already an explicit dep in
  pyproject.toml (task assumed transitive-only), so no pyproject change needed.
- **Left for later:** section structure on FlattenedDoc (deferred until a loader
  needs it, #4); `page_offsets` is the per-page hook. Ledger `status` rendering
  (a skipped row currently has no `result`; renderer shows what it shows —
  Emerson/Dominique may want a "skipped" chip, flagged in PR).
