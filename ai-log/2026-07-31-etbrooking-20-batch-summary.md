# 2026-07-31 — etbrooking — #20 batch summary view

Session: Fable via Claude Code. The gate ("after PDF output quality") cleared
with #136/#153, so this builds the triage layer on the CLI batch mode that
already existed (two-pass ingest, ranked rich table, summary.csv).

- **New `report/batch.py`:** `summarize_for_batch(report_dict, link)` — one
  report → one flat scalar row (counts + derived columns: doc type from the
  tagging ledger row, Pangram score, citation-flag count = findings with
  DOI/URL/CIT/MD ids carrying a failing check, similarity detail). And
  `render_batch(rows)` — a single self-contained HTML page: sortable
  columns (numeric-aware, click to toggle), text filter, client-side
  CSV/JSON export built from the embedded rows (exports = exactly the rows
  currently shown), each file linking into its evidence report. Reuses
  report.css so the batch page and the per-doc report read as one product.
- **CLI:** batch rows now come from `summarize_for_batch`; batch runs write
  `summary.html` + `summary.json` next to the existing `summary.csv` (CSV
  gains the derived columns after the original ones, so existing
  `file,concerns…` prefix assertions hold). Row links prefer the rendered
  `.report.html`, fall back to `.report.json` when `--format` is json-only.
- **Ingest-gap rows** (`{"file", "error"}`) render as "not read" with the
  reason as tooltip, sort under the numbered rows, never break the table.
- **Acceptance criteria walked:** static file opens directly (no backend);
  CSV export round-trips (quoting handled client-side); errored/skipped
  checks are just columns; a few hundred rows is trivial for the vanilla
  sort/filter (re-sorts a JS array + reorders <tr>s).
- Smoke-tested for real: 4 fixture PDFs through `slopcheck run … --format
  json,html` — ranked fabricated-citations docs on top, doc types and
  citation flags populated, links live. (Pangram column empty locally —
  no local key; populated on Railway.)
- 5 new tests in `tests/test_report_batch.py` + CLI batch tests green;
  full suite 568 passed (minus the pre-existing Windows symlink failure
  noted in STATUS 15:47).
