# Research log — 17-budget-lens

Index for this branch. Newest entries first.

## Sessions

- **2026-07-31** — [budget-feasibility lens design](convos/20260731_budget_feasibility_lens_design.md) — Dan (air). Design-only session, no code. Split #17 into feasibility lens (this branch) + arithmetic checks (#109, Nick). Scoped lens to pure extraction + pairing; Python evaluator (`pipeline/budget_feasibility/`) applies US benchmarks (wide 20th–80th percentile ranges) and emits shortfall findings. Two-artifact design following `claim_support` precedent. Live end-to-end tests deferred to #130. Implementation plan written at [plans/20260731_budget_feasibility_lens_implementation.md](plans/20260731_budget_feasibility_lens_implementation.md) for the next agent to pick up.

## Branch summary

Ships the LLM feasibility lens for #17. Lens does semantic scope↔budget pairing; a companion Python evaluator does bounded US-only benchmark evaluation. Arithmetic half (#109) is a separate branch owned by Nick.
