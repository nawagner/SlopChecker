# Budget-feasibility lens — Phases 1 and 2 implementation

**Date:** 2026-07-31
**Branch:** danparshall/17-budget-lens
**Machine:** Dans-MacBook-Air

## Summary

Executed Phases 1 and 2 of the implementation plan from
[plans/20260731_budget_feasibility_lens_implementation.md](../plans/20260731_budget_feasibility_lens_implementation.md).
Phase 1 landed the LLM prompt pack at
`src/slopchecker/lenses/budget_feasibility.md`. Phase 2 landed the
Python evaluator at `src/slopchecker/pipeline/budget_feasibility/`
(package `__init__.py`, `benchmarks_us.py`, `evaluate.py`) plus a
24-test suite at `tests/test_budget_feasibility.py` covering the pure
arithmetic, the flag-rule boundary, unpaired-scope/budget derivation,
sum-of-lines tolerance, null-safe cases, and an end-to-end
Meridian-planted-defect assertion. Followed test-driven development
per the Nori workflow — all tests written and failing on missing
imports before any evaluator code existed.

Two commits landed on the branch:
- `655ab67` — `#17 lens: draft budget_feasibility.md`
- `7291630` — `#17 evaluator: benchmarks_us + evaluate.py + unit tests`

Both pushed to origin. Phases 3–5 (LLM orchestrator + tests, fabricated
fixtures + smoke check, PR wrap) remain.

## Topics Explored

- Precedent scan of `lenses/claims.md`, `lenses/README.md`,
  `lenses/loader.py`, and `tests/test_lenses.py` before writing the
  new lens — the loader enforces required sections and the generic
  test suite validates quote-verbatim automatically for every lens.
- Precedent scan of `pipeline/claim_support/{check.py, __init__.py}`
  and `pipeline/registry.py` for the two-artifact shape the evaluator
  will plug into during Phase 3.
- `models.py` for `Finding` / `CheckResult` / `Anchor` semantics —
  every emitted finding carries a `CheckResult(name=..., result=...)`
  and (where applicable) an anchor + evidence dict.
- Meridian planted-defect arithmetic verified by hand against the
  design convo's few-shot: 0.25 × $95K PI + 2 × $52K postdoc = $127,750
  base; × 1.28 fringe = **$163,520** expected_p20 (implementation plan
  quoted ~$163,840, off by $320 — arithmetic slip in the plan doc, not
  the design). Shortfall factor 163,520 / 40,000 = 4.088 ≈ 4.1. p80:
  0.25 × $220K + 2 × $82K = $219,000 × 1.28 = **$280,320**.

## Provisional Findings

- The generic `test_lenses.py` parametrized gates (format, valid JSON,
  quote-verbatim) picked up `budget_feasibility` automatically the
  moment the file existed — 3 new parametrized tests pass without any
  test-file edit. The lens README's "adding a lens" flow is real.
- The evaluator can be trivially exercised with hand-crafted
  `LensOutput` dataclasses. No mock LLM or transport is needed until
  Phase 3.
- Two shape decisions worth preserving:
  - `pairing_ratio_usd_per_unit` is one Finding per **unique paired
    scope**, not per Pairing row — many-to-many pairings collapse into
    a summed numerator. Meridian's 3 pairing rows produce 2 ratios
    (SC1 and SC2). My first version of the shape-assertion test had
    this wrong; corrected with a comment when the test surfaced it.
  - `sum_of_lines_matches_stated_total` returns `bool | None` — `None`
    when `project.stated_total_usd` is not stated (nothing to compare
    against, no finding emitted at all). Cleaner than raising or
    inventing a synthetic total.
- The flag rule boundary is `shortfall_factor_p20 >= threshold`
  (inclusive), matching the implementation plan's explicit "3.0
  fires / 2.9 doesn't" spec. The design convo's original phrasing
  (`stated < expected_p20 / threshold`) agrees everywhere except at
  the exact boundary; the `>=` reading is the more conservative
  (fires-more-often) choice, and the plan's spec was more recent.

## Decisions Made

- **Frontmatter `id` uses underscore, not dash.** The plan doc's
  `id: budget-feasibility` was a transcription slip — the lens
  README's convention and the working precedent (`claims.md` →
  `id: claims`) both use `<stem>` matching the filename. Used
  `id: budget_feasibility`. Loader doesn't enforce this yet (it uses
  `meta.get("id", path.stem)`), but staying consistent avoids
  surprising anyone who greps for `id: budget_feasibility` later.
- **`shortfall_factor` returns a dataclass, not a dict.** The tests
  need to assert on specific numbers, and the assumption fields are
  emitted separately in Finding evidence. `ShortfallEstimate` is a
  frozen dataclass with `expected_p20_usd`, `expected_p80_usd`,
  `shortfall_factor_p20`, `shortfall_factor_p80`.
- **Roles bucketed to `other` contribute zero, not None or an error.**
  A personnel line whose ALL roles bucket to `other` therefore gets
  `expected_p20_usd = 0` and the orchestrator suppresses the
  `personnel_underfunded` finding entirely (using `expected_p20 > 0`
  as the gate). Same rule for `roles_named=[]`: skip the finding, not
  emit `result=False` on a line we can't evaluate.
- **`period_yrs` and `fringe_rate` defaults belong in `shortfall_factor`,
  not the dataclass.** When the lens didn't extract a period,
  `shortfall_factor` uses 1.0 (matches the "first grant year" default
  case); fringe falls back to `benchmarks.fringe_rate_default` (0.28).
  Rationale: keeps the dataclass a faithful mirror of "what the lens
  emitted" and puts business-logic defaults in the code that applies
  them.
- **Emit `unallocated_budget_line` findings without severity.** The
  design convo doesn't classify indirect-cost lines as "allocated to
  everything." NL1 (equipment) and NL3 (indirect) both surface as
  unallocated in Meridian. The reviewer can dismiss NL3 as expected;
  no auto-suppression of indirect-category lines.

## Results

Two committed artifacts on this branch:

- `src/slopchecker/lenses/budget_feasibility.md` (commit `655ab67`) —
  327-line lens prompt pack, closed role enum, many-to-many pairings,
  Meridian few-shot, all quotes verbatim per the generic test suite.
- `src/slopchecker/pipeline/budget_feasibility/` +
  `tests/test_budget_feasibility.py` (commit `7291630`) — 1,194
  insertions total: `__init__.py`, `benchmarks_us.py` (BenchmarkTable
  + US_2026 with citations), `evaluate.py` (dataclasses + six pure
  functions), and 24 passing unit tests.

Test suite state: 407 passed, 9 deselected, 1 unrelated deprecation
warning (starlette httpx). `ruff check` and `ruff format --check`
clean on both src and tests; `mypy` clean on new code (5 pre-existing
errors elsewhere are non-blocking per `.github/workflows/ci.yml`
line 29).

## Open Questions

- **`project.stated_total_usd` field-name coordination with #109.** The
  design convo flagged this and the plan flagged it again. Nick's
  arithmetic checks (`checks/`, #109) will also want to touch this
  field. Cross-comment on #109 or #17 before either PR merges to avoid
  a rename cycle on `report.json`.
- **`benchmarks_us.py` numbers are drafts.** Values are locked with
  citation strings pointing at BLS OEWS May 2024, Chronicle 2024, and
  NIH NRSA FY 2024, but no one has walked back to the raw sources yet.
  Do that before the check runs on any real demo material — a
  citation string is a claim, not a verification. `test_us_2026_bands_
  match_design_convo_lockdown` guards against silent widening, but not
  against the initial values being off.
- **Phase 3 LLM plumbing decisions.** Whether the check constructs its
  own transport (mirroring `claim_support/llm.py`) or pulls one off
  `CheckContext` — the plan flagged this as a "check before Phase 3"
  question. Reading `claim_support/check.py` this session confirmed
  each check builds its own transport for now.
- **Whether `evaluate_lens_output` should also emit a
  `pairing_ratio_usd_per_unit` finding for scopes with `quantity == 0`.**
  Currently skipped (divide-by-zero avoidance). If those exist in
  practice, the reviewer might want to see them flagged as
  "commitment stated with no measurable unit" rather than silent.
  Defer to real fixtures.

## Next Session

Pick up Phase 3 (LLM orchestrator + mocked-transport tests) per the
implementation plan. The lens is available via `load_lens("budget_
feasibility")`; the evaluator is `evaluate_lens_output(lens_out,
benchmarks=US_2026)`. Mirror `claim_support/{check.py, llm.py,
prompts.py}` for the transport layer, retry policy, and orchestrator
shape.
