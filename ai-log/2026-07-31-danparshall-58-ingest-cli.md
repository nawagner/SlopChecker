# 2026-07-31 — danparshall — #58 wire CLI seam to ingest (Fable session)

Issue: #58 (wire `slopcheck run` to `slopchecker.ingest.ingest()`).
Branch: `danparshall/58-ingest-cli`, off `main@a5a5f5c` post-#63.

## What landed

- `src/slopchecker/cli.py` — deleted the temporary `_load_document()`
  seam (plus `_TEXT_SUFFIXES` and `UnsupportedFormat`) and inlined
  `slopchecker.ingest.ingest()` in the `run()` loop.
  - `IngestResult.status != "ok"` → gap path: single-file → red +
    `typer.Exit(1)`; batch → yellow-skip + `{"file": …, "error": reason}`
    row (unchanged degrade shape from the seam era).
  - Batch directory suffix filter widened from `_TEXT_SUFFIXES` (.txt/.md
    only) to `ingest.LOADERS` (.pdf/.docx/.md/.markdown/.html/.htm/.txt).
  - Removed unused imports (`hashlib`, `FlattenedDoc`); dropped the
    `try/except (UnsupportedFormat, OSError)` shape now that ingest is
    a total function.
- `tests/test_cli_run.py`:
  - **New**: `test_run_reads_pdf_end_to_end` — 2-page fabricated PDF via
    `pytest.importorskip("pymupdf")` + `pymupdf.new_page().insert_text(...)`
    (same helper pattern as `tests/test_ingest.py::make_pdf`), asserts
    exit 0, media_type="application/pdf", pages=2, has_text=true.
  - **New**: `test_corrupt_pdf_reports_ingest_error` — `%PDF-1.7 nope`
    bytes, asserts exit 1 + "could not open as PDF" in output.
  - **Renamed & rewritten** `test_unsupported_extension_points_at_ingestion`
    → `test_unsupported_extension_reports_ingest_error` — uses `.rst`
    (no loader) instead of a fake `.pdf` header (which is now a real
    corrupt-PDF path).
  - **New**: `test_batch_records_ingest_gaps_alongside_reports` — mixed
    corpus (clean.md + empty.md + corrupt.pdf), asserts readable file
    gets a report.json, unreadable ones show as gap rows in summary.csv.
  - **Rewritten**: `test_findings_never_fail_the_exit_code` — old fixture
    (blank .md) no longer reaches checks (ingest errors it out at the
    text-normalization step, per #4). New fixture uses `scratch_registry`
    to register a contrived always-fails check on `sample_md`, so the
    "check failure ≠ tool failure" invariant is still tested.
  - **Rewritten**: `test_batch_ranks_by_concerns` — same reason. Old
    fixture used `empty.md` → `has_text=False` → concerns=1 as the
    high-concern doc. Post-#4 that's not reachable via built-ins.
    New fixture uses `scratch_registry` to add a `flag_bad` check that
    fires on "bad" in doc.text; two files with clearly-different concern
    counts still validates the sort.

## Decisions

- **Inlined the seam, didn't keep a passthrough wrapper.** The issue says
  "replace the seam." YAGNI on the wrapper — no test patches it. If a
  future check-side pre-processing hook is wanted, add it then.
- **Single-file mode: ingest-errored → exit 1.** Matches the seam-era
  behavior for unsupported files. It's a "we can't read your input"
  signal, not a "your proposal has issues" signal, so it belongs in
  the tool-failure lane (exit ≠ 0). Batch mode is where degrade-to-gaps
  applies — because "gap on doc N of 40" shouldn't kill the whole run.
- **Two failure-mode tests, not one** (per Dan's decision on the ask):
  unsupported-suffix and corrupt-PDF exercise distinct paths inside
  `ingest()` (loader lookup vs loader raise), so both are worth locking in.
- **Widened the batch directory scan.** The old `_TEXT_SUFFIXES` filter
  would silently drop PDFs from a batch directory even after the CLI
  learned to read them. Now the filter is `LOADERS` — one source of truth.

## Dead ends / gotchas

- Started with a plan to base off `origin/danparshall/5-runner-cli` since
  that's where `_load_document` originally lived. That branch turned out
  to be stale by ~2,800 lines vs main — merging it would have deleted
  Emerson's #19/#27 work and my own #7/#10. The parent session re-landed
  the CLI as PR #63 from a fresh main-based branch (`danparshall/6-cli`)
  and this fix built on top after #63 merged. Repo-convention takeaway
  already recorded in #63's body: always `--delete-branch` on merge so
  GitHub retargets stacked PRs.
- The `test_findings_never_fail_the_exit_code` and
  `test_batch_ranks_by_concerns` breakage was a real semantic shift: #4
  moved "empty document" from "check reports False" to "ingest reports
  gap." That's a strictly better design (an empty file can't tell you
  anything about the proposal), but it means those two tests had to be
  rewritten around a `scratch_registry` fake check instead of the
  empty-markdown trick they used before.
- pymupdf: `importorskip("pymupdf")` inside the corrupt-PDF and
  end-to-end PDF tests keeps the suite green on machines without the
  `pdf` extra. Suite counts skipped separately: 139 passed / 2 skipped
  locally on this worktree.

## What's left

- Nothing on #58 itself. Follow-ons that belong on their own issues:
  DOCX / HTML end-to-end CLI tests (this PR covers PDF; the shape would
  be identical); a "PDF with no text layer" CLI test (already covered
  at the ingest layer in `tests/test_ingest.py`).
