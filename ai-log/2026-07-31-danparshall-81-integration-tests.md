# 2026-07-31 — danparshall — 81-integration-tests (Fable session)

Issue: #81 — turn the 2026-07-31 e2e smoke (PR #78, see
`ai-log/2026-07-31-danparshall-pdf-macos-hang.md`) into repeatable
integration tests for the full CLI chain.

## What landed

- `tests/test_integration_e2e.py` — 9 tests behind `@pytest.mark.integration`,
  all driving the real CLI as a subprocess (`python -m slopchecker.cli`):
  - **run leg:** fabricated 2-page PDF → `run --format json,html` → exit 0,
    `report.json` validates against `EvidenceReport` (pages preserved,
    `has_text` true), HTML written with doc content.
  - **render leg:** `render <json> --pdf --out` → `%PDF-` magic + >1 KB.
  - **loud-fail browser gate:** on macOS/CI, `find_browser() is None` is a
    test FAILURE with a pointed message, not a skip — the "2 skipped forever"
    trap is exactly what hid the #78 bug. Render test skips only where a
    browser is legitimately absent (non-mac, non-CI).
  - **degrade-to-gaps singles:** scanned/no-text-layer PDF, corrupt PDF,
    unsupported suffix → exit 1 + actionable reason, `Traceback` asserted
    absent.
  - **batch:** mixed folder (harness `proposal_climate.md`, fabricated PDF,
    corrupt PDF, scanned PDF, `.rst`) → per-file reports that validate,
    gap rows with reasons in `summary.csv`, exit 0.
- `pyproject.toml` — `integration` marker registered; `addopts = "-m 'not
  integration'"` so plain `pytest` stays the fast unit run (5s).
- `.github/workflows/ci.yml` — explicit `pytest -m integration` step; without
  it the deselected tests would never run anywhere (the exact silent-dark
  failure mode this issue exists to close).

## Decisions (also posted on #81)

1. Deselect-by-default + explicit CI step, rather than letting plain `pytest`
   include integration (keeps dev loop fast, keeps CI honest).
2. Browser "expected" ⇔ `darwin or $CI` — gate fails there, skips elsewhere.
3. Subprocess over `CliRunner`: unit tests already cover these flows
   in-process (`test_cli_run.py`); the marginal value here is real exit
   codes, real entry point, and faithful no-Traceback assertions.

## Verification

- `pytest -m integration`: 9 passed, 4.4s (macOS, real Chrome render).
- Plain `pytest`: 176 passed, 9 deselected — default run unaffected.
- Gate can actually fire: verified `find_browser()` returns `None` under
  empty PATH + no CHROMIUM + no app bundles (so the gate assert would fail
  loudly in a browserless macOS/CI env, not vacuously pass).
- `ruff check` + `ruff format --check` clean.

## Dead ends / notes for the next person

- None substantive. One nuance worth knowing: CLI `-m integration` cleanly
  overrides the `addopts` deselection (pytest last-`-m`-wins), so no
  `--override-ini` gymnastics are needed.
- Not touched (per #81 non-scope): `src/slopchecker/report/`,
  `src/slopchecker/checks/`, recall scoring (#79 owns that).

## What's left

- Nothing on #81 once the PR merges. If CI's chrome ever regresses, the gate
  test will say so loudly instead of skipping.
