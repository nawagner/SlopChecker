# Budget-feasibility lens — Implementation Plan

**Goal:** Ship the LLM lens + Python evaluator scaffolding for #17, so the check runs end-to-end on fabricated fixtures with US-benchmark shortfall flags.

**Originating conversation:** [convos/20260731_budget_feasibility_lens_design.md](../convos/20260731_budget_feasibility_lens_design.md) — read this first. It carries the full schema rationale, the worked few-shot, the evaluator interface, and the design-time debate (including the failure-mode analysis that motivated the US-only scope).

**Context:** #17 asks for a budget-and-achievability review. The issue mixes deterministic arithmetic with LLM-driven feasibility judgment. Design session split those: arithmetic moved to #109 (Nick, `checks/`), and this branch scopes to the LLM feasibility lens plus a bounded Python evaluator that applies US benchmarks. This split is what makes "evaluate feasibility" defensible against the failure mode #17 explicitly warns about — flagging unfamiliar-but-legitimate non-US cost structures.

**Confidence:** High on the lens schema and evaluator interface (both locked with the user in the design conversation, following the `claim_support` precedent that shipped this morning). Medium on the specific numbers in `benchmarks_us.py` — those should be verified against the cited sources before the check runs on any demo material.

**Architecture:** Two-artifact split following `pipeline/claim_support/` precedent — `lenses/budget_feasibility.md` (LLM prompt pack, pure extraction + pairing) plus `pipeline/budget_feasibility/` (Python that runs the lens, joins against `benchmarks_us.py`, computes shortfall factors, emits `Findings`). Lens does no arithmetic and no judgment; evaluator does bounded US-only judgment with the assumption printed in every `Finding.evidence`.

**Branch:** `danparshall/17-budget-lens` (worktree at `/Users/dan/code/SlopChecker/.worktrees/dan-17-budget-lens/`).

**Tech Stack:** Python 3.11+, `pytest`, `ruff`. LLM call goes through whatever `pipeline/claim_support/llm.py` uses — mirror that shape. No new third-party deps beyond what the repo already carries.

---

## Testing Plan

**I will add all tests before writing implementation code.**

### Unit tests — `tests/test_budget_feasibility.py` (new)

Behavior tests for `evaluate.py` pure functions with hand-crafted `LensOutput` dataclasses (no LLM calls, no I/O):

- **`shortfall_factor` math** — given a `PersonnelLine` with `roles_named=[pi @ 0.25 FTE, postdoc @ 1.0 FTE ×2]`, `period_yrs=1`, `amount_usd=40000`, and the `US_2026` benchmark table with `fringe_rate_default=0.28`, `expected_p20 = (0.25×95_000 + 2×1.0×52_000) × 1.28 = ~163_840` and `shortfall_factor_p20 = 163_840/40_000 = ~4.1`. Assert those specific numbers.
- **`personnel_underfunded` flag rule** — a personnel line whose `shortfall_factor_p20 >= 3.0` (default threshold) → flag fires. One whose factor is `2.9` → flag does not fire. One whose factor is `3.0` (exactly the boundary) → flag fires (`>=` not `>`). Explicit boundary tests.
- **`unpaired_scope` derivation** — given `scope_commitments=[SC1, SC2, SC3, SC4]` and `pairings=[(SC1, PL1), (SC2, PL1)]`, `unpaired_scope` returns `{SC3, SC4}`. Given `scope_commitments=[SC1]` with `quantity=0`, `SC1` does NOT surface as `unfunded_quantitative_commitment` (quantity>0 gate).
- **`pairing_ratio_usd_per_unit`** — given SC1 with `quantity=40, unit=country` paired to PL1 with `amount_usd=40000`, ratio is `1000.0`. When multiple budget lines pair to one scope, ratio is `sum(paired_amounts) / quantity`.
- **`sum_of_lines_matches_stated_total`** — sum of `personnel_lines.amount_usd + non_personnel_lines.amount_usd` equals `project.stated_total_usd` within a small tolerance (e.g. ±$1 for rounding) → true; larger delta → false; `stated_total_usd is null` → check not emitted at all.
- **Missing / null-safe cases** — a `PersonnelLine` with `roles_named=[]` (unbucketable roles) emits no `personnel_underfunded` finding, only `pairing_ratio_usd_per_unit`. A `role="other"` line in `roles_named` skips salary math (band is `None`) but still contributes to sums as if band = 0. Document whichever behavior we pick.

### Check orchestrator test — `tests/test_budget_feasibility.py` (same file, separate section)

Follows `test_claim_support.py` shape:

- **`check_budget_feasibility` end-to-end with `llm.py` mocked** — mock the LLM call to return a fixed valid JSON blob (the few-shot output from the convo doc); verify that quotecheck runs against the doc text, the evaluator is invoked, and the returned `Findings` include the expected checks (`personnel_underfunded`, `pairing_ratio_usd_per_unit`, `unfunded_quantitative_commitment`). Assert `Finding.evidence` carries the benchmark assumption fields (`amount_expected_p20_usd`, `benchmark_source`, etc.).
- **Quotecheck failure path** — mock LLM returns a `personnel_lines[0].quote` that isn't a substring of `doc.text`. The line is dropped from downstream evaluation; a `lens_quote_unverified` coverage-gap row is emitted (mirror whatever `claim_support` does for the same failure). Never crash; never produce a `personnel_underfunded` finding grounded on an unverified quote.
- **LLM error / retry exhaustion** — mock LLM raises after N retries; check emits a `skipped: llm_unavailable` gap row and no findings. No stack trace escapes.

### Generic lens format test — automatic

`tests/test_lenses.py` runs the shared frontmatter / required-sections / quote-verbatim checks on every `lenses/*.md`. Adding `budget_feasibility.md` inherits all of that for free. Verify by running the file after the lens .md exists.

### Live tests — DEFERRED

Tracked in [#130](https://github.com/nawagner/SlopChecker/issues/130). Do NOT ship live end-to-end tests in this PR — they need a stable LLM interface and fabricated fixtures beyond the scope of the lens PR itself.

NOTE: I will write *all* tests before I add any implementation behavior.

---

## Bite-sized steps

### Phase 1 — Lens prompt pack

1. Read `lenses/README.md` and `lenses/claims.md` — the format spec and the working precedent.
2. Read `docs/active/17-budget-lens/convos/20260731_budget_feasibility_lens_design.md` — the locked schema, few-shot, and rationale.
3. Create `src/slopchecker/lenses/budget_feasibility.md` — copy the `claims.md` skeleton, fill frontmatter (`id: budget-feasibility`, `issue: 17`, `version: 0.1`, `output: json`).
4. Draft the `## Purpose` section — one paragraph: "Extract the budget lines, scope commitments, and their pairings from a proposal so a downstream Python evaluator can compare implied cost against US benchmarks. Extraction and pairing only — this lens does not judge feasibility."
5. Draft the `## System prompt` section — list the extraction targets, the role enum, the many-to-many pairing rule, the "no arithmetic in the model" rule, the "no invented nullables" rule (mirror `claims.md` rule #5 for `citation: null`).
6. Draft the `## Output format` section — paste the JSON schema block from the convo doc; add the mapping-to-`Finding` table (the evaluator emits, not the lens, but document the pipeline so the reader knows where each field lands).
7. Draft the `## Example` section — paste the Meridian fabricated proposal and the expected output JSON from the convo doc into `### Input` / `### Output` fenced blocks. Verify every `quote` value in the expected output appears verbatim in the input.
8. Run `pytest tests/test_lenses.py -k budget_feasibility` — must pass the generic format + quote-verbatim gates. Fix any failures before moving on.
9. Commit: `#17 lens: draft budget_feasibility.md`

### Phase 2 — Evaluator scaffolding (tests-first)

10. Create `tests/test_budget_feasibility.py` with the unit-test cases from the Testing Plan section above (behavior tests, not type/mock tests). Write them as failing tests against imports that don't exist yet.
11. Create `src/slopchecker/pipeline/budget_feasibility/__init__.py` — empty package.
12. Create `src/slopchecker/pipeline/budget_feasibility/benchmarks_us.py` — the `BenchmarkTable` dataclass + `US_2026` instance with the salary bands from the convo doc. Include the citation strings. Include a module-level `__doc__` explaining "these numbers came from cited public data; verify before shipping to any demo run."
13. Create `src/slopchecker/pipeline/budget_feasibility/evaluate.py` — implement `shortfall_factor()`, `pairing_ratios()`, `unpaired_scope_ids()`, `unpaired_budget_ids()`, `sum_of_lines_matches_stated_total()`, `evaluate_lens_output()`. Match the signatures in the convo doc.
14. Iteratively make the unit tests pass, one at a time. Do NOT modify tests to match code; modify code to satisfy tests. If a test's assertion turns out to be numerically wrong, verify the math on paper first, then update the test with a comment explaining the correction.
15. Commit: `#17 evaluator: benchmarks_us + evaluate.py + unit tests`

### Phase 3 — Check orchestrator

16. Read `src/slopchecker/pipeline/claim_support/{check.py, llm.py, prompts.py}` — this is the pattern to mirror. Note the retry/refuter logic, the `CheckContext` usage, the coverage-gap emit pattern.
17. Create `src/slopchecker/pipeline/budget_feasibility/llm.py` — thin wrapper around whatever LLM client `claim_support/llm.py` uses. Same retry-and-JSON-schema-repair shape. Prompt assembly (lens → LLM input) mirrors `claim_support/prompts.py`.
18. Create `src/slopchecker/pipeline/budget_feasibility/check.py` — the registered check. Signature: `@register("budget_feasibility") def check_budget_feasibility(doc: FlattenedDoc, ctx: CheckContext) -> list[Finding]`. Wire lens invocation → quotecheck → evaluator → return.
19. Add the orchestrator tests from the Testing Plan section to `tests/test_budget_feasibility.py`. Iterate to pass.
20. Run the full unit suite: `pytest tests/ -m "not integration and not live"` (or whatever the repo's default marker set is — check `pyproject.toml` and existing test files). Must be 0 failures.
21. Commit: `#17 check: register budget_feasibility with LLM orchestration`

### Phase 4 — Fixtures + smoke check

22. Create `harness/fixtures/proposal_underfunded_meridian.md` — the Meridian few-shot from the convo doc, verbatim. This is the planted-defect proposal.
23. Create `harness/fixtures/proposal_reasonable_climate.md` — sibling proposal with the same scope shape but budget priced against p50 salary bands (2 postdocs × 1 yr @ $65K + 25% PI @ $150K × 1 yr × 1.28 fringe = ~$215K personnel, not $40K). Should produce zero `_underfunded` flags. Guards against a check that just says "everything is underfunded."
24. Optional (nice-to-have; skip if time tight): document the fixtures in `harness/README.md` or wherever the harness inventory lives.
25. Manually invoke on the underfunded fixture with a mocked or real LLM — verify the planted `personnel_underfunded` finding actually appears with the expected `evidence.shortfall_factor_p20`. Snapshot the output JSON somewhere in `docs/active/17-budget-lens/results/` for provenance.
26. Commit: `#17 fixtures: underfunded + reasonable Meridian variants`

### Phase 5 — Wrap and PR

27. Update `ai-log/` — write a session summary file `ai-log/2026-XX-XX-danparshall-17-budget-feasibility.md` (see repo convention: date-handle-slug, session-scoped, decisions made, dead ends, what's left).
28. Add STATUS.md line — the append-only shared log (see `STATUS.md` header for format).
29. Update the module ownership table in `CLAUDE.md` if `pipeline/budget_feasibility/` isn't already covered by the `pipeline/` row (it should be — Dan's module).
30. Push, open PR referencing `#17` in title, cross-link `#109` and `#130` in the PR body.

---

**Testing Details:** Unit tests target the evaluator's pure functions with hand-crafted `LensOutput` dataclasses — they exercise the arithmetic (shortfall factor, ratios, sums) and the threshold boundaries directly. The orchestrator tests mock the LLM call and assert on the emitted `Findings` — they verify the wiring (lens → quotecheck → evaluator → finding emit) without hitting the network. The generic `test_lenses.py` suite catches any drift in the lens .md format for free. Live end-to-end tests are deliberately deferred to #130 so the lens PR ships small and reviewable.

**Implementation Details:**
- Every `Finding` from `personnel_underfunded` MUST carry `assumed_bands_usd`, `assumed_fringe_rate`, `benchmark_source`, and `flagged_because` in `evidence`. The reviewer sees the assumption and can override.
- The flag rule is `stated < expected_p20 / threshold`, default threshold = 3.0. Explained in the convo doc; do not tighten to `stated < expected_p20` without discussing — that would produce false positives on merely-tight budgets.
- Roles that bucket to `role: "other"` skip salary math (no band defined). Personnel lines with `roles_named=[]` also skip — `pairing_ratio_usd_per_unit` still emits.
- The lens re-reads the doc; it does NOT consume `claims.json`. Decision recorded in the convo doc.
- The `project.stated_total_usd` field overlaps with #109's arithmetic remit. Coordinate on the exact field name with @nawagner before either PR merges — cheaper to align now than migrate `report.json` schemas later.
- Fringe rate captured per personnel line when stated inline; indirect rate captured when stated inline OR as its own `non_personnel_lines` entry with `category: "indirect"`. Evaluator looks in both places.
- The lens few-shot is intentionally the Meridian proposal from `claims.md` for continuity — same fabricated org, different aperture. Do not switch fabricated orgs.
- Do NOT bake specific salary numbers into the lens prompt itself. All benchmarks live in `benchmarks_us.py` (Python, version-controlled, testable). Lens is bench-agnostic.
- `benchmarks_us.py` numbers are drafts; verify against BLS OEWS May 2024 + Chronicle 2024 + NIH FY 2024 before demo. Widening a band later is cheap; narrowing is not.
- If in doubt about whether a check's output belongs in the lens or the evaluator, put it in the evaluator. Model output is expensive to schema-migrate; Python is not.

**What could change:**
- The salary bands in `benchmarks_us.py` — expect to widen them once we run against real US proposals and see which legitimate-but-low-band cases we're accidentally flagging. Threshold might also move (3.0x default may prove too generous or too tight).
- The `roles_named` enum — a role we didn't anticipate (e.g. `program_manager`, `field_coordinator`) may need adding. Keep `other` as the escape valve until we have data.
- The `pairing_basis` field we dropped as YAGNI — if `unpaired_scope` produces too many false positives (real pairings the model missed), we may need to reintroduce it so the model states its pairing reasoning explicitly.
- Coordination with #109's schema for `project.stated_total_usd` — if Nick picks a different field name, this must match. Loop him in before merge.
- Whether the check consumes `claims.json` (currently no) may flip if the standalone lens's scope-extraction quality is worse than the claims lens's.

**Questions**
- Does the `CheckContext` object already expose an LLM client, or does each `pipeline/<check>/llm.py` construct its own? Check `pipeline/claim_support/llm.py` before Phase 3.
- Does `test_lenses.py` require the few-shot input/output pair to round-trip through a JSON-schema validator, or does it only check quote-verbatim? Behavior matters for how strictly the example JSON must match the schema.
- What's the convention for `Finding.check` naming? Prior art suggests snake-case verbs (`all_dois_resolve`, `pangram_document`) — use `personnel_underfunded`, `unfunded_quantitative_commitment`, `unallocated_budget_line`, `pairing_ratio_usd_per_unit`, `sum_of_lines_matches_stated_total`. Verify against `docs/DATA_MODEL.md` before locking.

---
