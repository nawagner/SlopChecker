# 2026-07-31 — #17 budget-feasibility lens design (no code)

**Session:** Dan (air), fable (claude-sonnet). Design-only pass on `danparshall/17-budget-lens`.

## Issues worked

- **#17** — Budget and achievability review (feasibility lens half)
- **#109** — Filed this session: split from #17 for the deterministic arithmetic half, assigned to @nawagner
- **#130** — Filed this session: live end-to-end tests for the check, deferred out of scope

## What changed

Nothing in code. Session produced:

- `docs/active/17-budget-lens/RESEARCH_LOG.md` — branch index
- `docs/active/17-budget-lens/convos/20260731_budget_feasibility_lens_design.md` — full design convo with locked schema + few-shot + evaluator interface + rationale
- `docs/active/17-budget-lens/plans/20260731_budget_feasibility_lens_implementation.md` — step-by-step implementation plan for the next agent
- `STATUS.md` — session summary line
- Two new GH issues (#109 and #130)
- One issue comment on #17 explaining the split

## Decisions made (and why)

- **Split #17 into feasibility (lens, this branch) + arithmetic (#109, Nick).** Arithmetic is deterministic and belongs in `checks/`; feasibility is LLM-driven and belongs in `lenses/`. Ownership boundary matches the module table in `CLAUDE.md`. Filing #109 kept #17's original scope from becoming a mixed-module mega-PR that Nick and I would both have to maintain.
- **Lens does pure extraction+pairing, evaluator does judgment.** Followed the `claim_support` two-artifact precedent (lens .md + `pipeline/<name>/` package). Alternative was a beefier lens that emits verdicts directly — rejected because LLMs are unreliable at arithmetic + thresholds are unauditable in prose. Python is deterministic and testable.
- **US-only benchmarks for v1.** Directly answers #17's failure-mode note ("flagging unfamiliar-but-legitimate cost structures is the failure mode to design against") — we're not evaluating non-US structures because we're not looking at them. Other jurisdictions get their own `benchmarks_XX.py` later.
- **Wide 20th–80th percentile salary bands, not narrow medians.** Trades some sensitivity for confidence in every flag. Combined with the `stated < expected_p20 / threshold=3.0` flag rule (not `stated < expected_p20`), the check only fires when money makes no plausible sense — not when a budget is merely tight.
- **Every `Finding` carries the benchmark assumption in `evidence`.** Reviewer sees the numbers used, can override. Not just "underfunded" — always "underfunded assuming PI @ [95K–220K] band, postdoc @ [52K–82K] band, fringe 28%, threshold 3x below p20."
- **Model does no arithmetic.** The lens JSON schema deliberately excludes `raw_ratio` and other computed fields — Python computes those from what the model extracted. One less thing the model can get wrong.
- **`pairings` are many-to-many.** A scope can pair to several budget lines (personnel + travel for the same deliverable); a budget line can pair to several scopes (same postdocs cover multiple activities). Locked in the few-shot with the Meridian PL1 pairing to both SC1 (trainings) and SC2 (country network).
- **`unpaired_scope`/`unpaired_budget` derived by Python**, not model-emitted. Computed as `all_ids - paired_ids`. Fewer degrees of freedom for the model to disagree with itself.

## Dead ends we deliberately avoided

- **Consuming `claims.json`** as an input to the budget lens. Cleaner separation of concerns on paper, but adds an ordering constraint in the runner and schema-coupling between two independent lenses. YAGNI for hackathon-timeframe. If the standalone lens's scope extraction turns out worse than the claims lens's, revisit.
- **Reviewer-question generation.** Would violate the "no free text in evidence" rule and turn the lens into a text generator. Reviewer questions are the RENDERER's job (or the human's).
- **Salary-inference from stated proposal ranges.** Doable ("If PI is stated @ $150K/yr, use that") but adds prompt complexity for a small quality gain. Deferred.
- **`pairing_basis` enum on pairings** (explaining WHY the model paired them). Dropped as YAGNI — the quotes make the pairing inspectable. If we see too many spurious pairings in real docs, reintroduce.

## What's left / next agent

The implementation plan at `docs/active/17-budget-lens/plans/20260731_budget_feasibility_lens_implementation.md` is written for zero-context handoff. Five phases:

1. Draft `lenses/budget_feasibility.md` (primary artifact — unblocks everyone)
2. Evaluator scaffolding tests-first: `pipeline/budget_feasibility/{evaluate.py, benchmarks_us.py}` with unit tests for shortfall math, ratios, threshold boundaries
3. Check orchestrator: `check.py + llm.py` mirroring `pipeline/claim_support/`
4. Fixtures: `proposal_underfunded_meridian.md` (planted defect) + `proposal_reasonable_climate.md` (control)
5. Wrap: `ai-log/`, STATUS.md, PR referencing #17 + cross-linking #109/#130

## Coordination notes for the team

- **@nawagner** — `project.stated_total_usd` field overlaps with #109's line-items-sum-to-stated-total check. We're both about to write code that reads the same doc-stated total; let's pick one field name before either PR merges. Cheaper now than a `report.json` schema migration later.
- **CLAUDE.md was updated during this session** (new `worker/src/db/` row for Nick's #88 work) — noted, doesn't affect this branch (we're in `lenses/` + `pipeline/`).
- **`.slopcheck-transcript = 1`** on this machine (opted in previously) — transcript from this session will land in `ai-log/transcripts/` at SessionEnd per the checked-in hook.
