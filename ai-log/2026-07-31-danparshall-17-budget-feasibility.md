# ai-log — 2026-07-31 — #17 budget-feasibility Phases 1 and 2

**Issue:** #17 (budget & achievability review, feasibility half; the
arithmetic half is Nick's #109). **Branch:** `danparshall/17-budget-lens`.
**Agent:** Claude Code on Dans-MacBook-Air (commits attributed as
`Dan Parshall (air)`). **Started from:** the design convo landed as
commit `2ed0a90` + the implementation plan at
`docs/active/17-budget-lens/plans/20260731_budget_feasibility_lens_implementation.md`.

## What changed

Two commits landed:

- `655ab67` — `#17 lens: draft budget_feasibility.md`
  - New `src/slopchecker/lenses/budget_feasibility.md`. 327 lines.
    Follows the format spec in `lenses/README.md`; parametrized
    `test_lenses.py` gates (required sections, valid JSON, all `quote`
    fields verbatim in the input) pass automatically for the new lens.
  - Frontmatter `id: budget_feasibility` (underscore) — the plan said
    `budget-feasibility` (dash) but the README convention and
    working precedent (`claims.md` → `id: claims`) both match the
    filename stem. Not enforced by the loader today; consistency
    still matters.

- `7291630` — `#17 evaluator: benchmarks_us + evaluate.py + unit tests`
  - New `src/slopchecker/pipeline/budget_feasibility/` package with
    `__init__.py`, `benchmarks_us.py` (BenchmarkTable + US_2026 with
    citation strings), `evaluate.py` (LensOutput dataclasses mirroring
    the lens schema + `shortfall_factor`, `pairing_ratios`,
    `unpaired_scope_ids`, `unpaired_budget_ids`,
    `sum_of_lines_matches_stated_total`, `evaluate_lens_output`).
  - New `tests/test_budget_feasibility.py` — 24 unit tests, all pure
    (no LLM, no I/O). Test-first per the Nori TDD skill: tests
    written and failing on missing imports before any evaluator code
    existed; then the module built up to satisfy them one green
    parametrization at a time.
  - Full unit suite: 407 passed. Ruff check + format clean; mypy
    clean on the new files (5 pre-existing errors in
    `config.py/runner.py/resolution.py/web.py` untouched — non-blocking
    per `.github/workflows/ci.yml` line 29).

Both branches pushed to `origin/danparshall/17-budget-lens`. Not opened
as a PR — the plan has three more phases before it's PR-ready.

## Decisions made and why

- **Frontmatter id uses `_` not `-`.** README convention (`id`
  matches filename stem) + `claims.md` precedent. Plan doc's dashed
  form was a transcription slip. Loader doesn't enforce it yet, but
  future greppers will thank me.

- **`shortfall_factor` returns a frozen dataclass, not a dict.** The
  unit tests need to assert on named fields (`expected_p20_usd`,
  `shortfall_factor_p20`); typed access is cheaper to read than dict
  literals. `ShortfallEstimate` also documents the four-number
  contract in one place.

- **Roles bucketed to `other` contribute zero to expected cost.** Same
  behavior as a role the enum doesn't know about — the evaluator
  declines to reason about it rather than inventing a band. A line
  where ALL roles bucket to zero (`expected_p20_usd == 0`) is the
  gate the orchestrator uses to suppress `personnel_underfunded`;
  same rule as `roles_named=[]`.

- **`period_yrs` defaults to 1.0 when the lens didn't extract one.**
  Most grant lines are the funded year. Baking the default into
  `shortfall_factor` (not the dataclass) keeps the dataclass a
  faithful mirror of what the lens emitted; the code that applies
  the default is where the fallback belongs.

- **`sum_of_lines_matches_stated_total` returns `bool | None`.** `None`
  when `project.stated_total_usd` is null — no basis for comparison,
  no finding. Cleaner than raising or inventing a synthetic total.
  `evaluate_lens_output` checks the return and only emits when it's
  a real bool.

- **`pairing_ratio_usd_per_unit` is one finding per unique paired
  scope, not one per Pairing row.** Many-to-many pairings collapse
  into a summed numerator (Meridian: SC1 paired to PL1 + NL2 →
  numerator = $40K + $18K = $58K, one ratio finding for SC1). My
  first shape-assertion test had this wrong; corrected with a
  comment when it surfaced.

- **Flag rule boundary is `>=` inclusive.** Plan spec says `factor
  == 3.0` fires; design convo phrased it as `stated < expected_p20 /
  threshold` (strict `<`, which is equivalent to `factor > threshold`
  strict). Went with the plan's `>=` because (a) it's more recent
  and (b) it's the more-conservative-defensive choice: fires more,
  which is the failure mode a reviewer notices; the opposite failure
  is silent.

- **`benchmarks_us.py` is a frozen dataclass, not a module of
  constants.** Lets us pass a custom BenchmarkTable to
  `shortfall_factor` and `evaluate_lens_output` (used by
  `test_evaluate_respects_custom_shortfall_threshold`). Locked
  contract with the reviewer is enforced by
  `test_us_2026_bands_match_design_convo_lockdown` — silent widening
  fails the test.

## Corrections to the plan

- **Expected p20 arithmetic.** Plan quoted `expected_p20 = ... = ~163_840`
  but the correct product is 163,520 (`0.25 × 95000 + 2 × 52000 =
  127,750; × 1.28 = 163,520`). Off by $320 vs the plan's own arithmetic.
  Verified by hand; test uses the correct number with an inline
  comment. Qualitative story (shortfall factor ~4.1 vs threshold 3.0
  → fires) unchanged, both numbers round to 4.1.

## Dead ends / snags

- **Chain-hook bash prompts.** Tripped the `block_bash_chains.py` hook
  twice (habitually chained `cd ... && ...`). Solution is to split
  into separate Bash calls; cwd persists across calls. Also tripped
  the `\n#` anti-obfuscation heuristic once when passing a commit
  message via HEREDOC where the message body started with `#17`; fix
  is Write-to-file then `git commit -F`. Neither cost more than a
  minute but both are worth remembering.

- **`uv sync` in the worktree.** Worktree started with no `.venv`;
  had to `uv sync --project <worktree> --extra dev --extra pdf
  --extra docx --extra llm --extra web --extra harness` to get the
  full test suite (fastapi test client needs the `web` extra,
  pymupdf needs `pdf`, etc.) — otherwise `pytest tests/` chokes on
  collection of `test_web.py`.

- **`uv.lock` untracked.** Byproduct of the worktree venv setup, not
  currently tracked on the branch. Left untracked; not part of
  either commit. If Dan wants a lock file committed, that's a
  separate decision — didn't want to introduce it silently as part
  of this PR.

## What's left (Phases 3–5)

- **Phase 3** — LLM orchestrator: `pipeline/budget_feasibility/
  {llm.py, check.py, prompts.py}` mirroring `claim_support`. Mocked-
  transport tests for the LLM success path (with fixed JSON blob),
  quotecheck failure path (unverified quote drops the line), and
  transport error (emits `skipped` / `errored` gap row). Commit
  `#17 check: register budget_feasibility with LLM orchestration`.

- **Phase 4** — Fabricated fixtures: `harness/fixtures/proposal_
  underfunded_meridian.md` (the planted case, ~4.1x shortfall) and
  `harness/fixtures/proposal_reasonable_climate.md` (sibling proposal
  at p50 salary bands, should produce zero underfunded flags —
  guards against a "flags everything" bug). Optional: snapshot output
  JSON to `docs/active/17-budget-lens/results/` for provenance.

- **Phase 5** — Wrap and PR. This ai-log gets the session line;
  STATUS.md already updated; module ownership already covered by
  the existing `pipeline/` row (Dan). Push and open PR referencing
  #17 in the title, cross-linking #109 (Nick's arithmetic) and #130
  (live e2e tests deferred).

## Coordination

- **`project.stated_total_usd`** — this field name overlaps with
  #109's arithmetic remit (line-items-sum-to-stated-total is also
  what Nick will check). Cross-comment on #109 or #17 before either
  PR merges so we don't rename `report.json` schemas after the fact.
  Flagged in the STATUS entry and in the design convo's coordination
  note; carrying it forward here.
