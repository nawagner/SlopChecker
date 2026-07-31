# 2026-07-31 — danparshall — #5 runner + #6 CLI (Fable session)

Issues: #5 (check registry + tiered runner), #6 (`slopcheck run`).
Branches: `danparshall/5-runner-cli` (PR #53), `danparshall/6-cli` stacked on it.

## What landed

- `src/slopchecker/pipeline/registry.py` — `@register(...)` decorator; metadata
  is `models.Check`; `discover()` auto-imports `pipeline/checks_builtin` and
  `slopchecker.checks` (tolerated-absent until Nick's package exists).
  `select_checks()` = `--tier/--only/--skip` semantics; unknown ids raise.
- `src/slopchecker/pipeline/runner.py` — deterministic → api → llm, parallel
  within a tier, per-check timeouts (absolute deadlines), error isolation:
  raise → `errored` row, `MissingCredential` → `skipped: missing X`, run continues.
- `src/slopchecker/pipeline/checks_builtin.py` — `has_text`, `word_count`.
- `src/slopchecker/cli.py` — `slopcheck run` beside the existing `render`/`config`:
  `--tier/--only/--skip/--out/--format json,html/--solicitation/--dry-run/--batch`;
  dir → batch with ranked table + `summary.csv`; exit nonzero only on tool failure.
- Tests: `tests/test_pipeline_runner.py` (15), `tests/test_cli_run.py` (13);
  all offline/fake checks; adds ~0.15s to the suite.

## Decisions (also on the issues/PRs)

- Check protocol is function + decorator, not a class Protocol: keeps
  one-file-one-decorator literally true. `applies_to` is a decorator kwarg.
- Checks return `CheckOutput(ledger, findings, cost_usd)`, not bare
  `list[Finding]` — the ledger needs a document-level row per check, and only
  the check knows its result value. Runner synthesizes gap rows for
  skipped/errored/timeout/not-applicable.
- Ingestion seam: `_load_document()` in cli.py reads .txt/.md only, clearly
  marked TEMPORARY for #4 to replace. Deliberately NOT in `pipeline/` to avoid
  colliding with the parallel #4 lane.
- `--dry-run` computes est spend as per-doc sum × doc count.
- "Concerns" in the batch ranking = failed + errored.

## Dead ends / gotchas

- `with ThreadPoolExecutor(...)` silently defeats per-check timeouts: the
  context exit calls `shutdown(wait=True)` and joins the lingering thread.
  Use explicit `shutdown(wait=False, cancel_futures=True)`.
- A timed-out check's thread still runs to completion in the background
  (Python can't kill threads); acceptable for screening runs, revisit if a
  hung network check ever holds the interpreter open at exit.

## What's left

- #4 replaces `_load_document()`; #8+ register real deterministic checks
  in `slopchecker.checks/` (auto-discovered, zero wiring).
- `--solicitation` is pass-through into the report only; compliance checking
  is #10's.
