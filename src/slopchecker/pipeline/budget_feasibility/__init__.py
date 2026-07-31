"""#17 budget-feasibility check.

Two artifacts, split following the ``claim_support`` precedent:

- ``lenses/budget_feasibility.md`` — the LLM prompt pack, pure
  extraction + pairing, no arithmetic and no judgment in the model.
- ``pipeline/budget_feasibility/`` — Python that joins the lens output
  against ``benchmarks_us.US_2026``, computes shortfall factors and
  pairing ratios, and emits ``Finding`` records with the benchmark
  assumption printed in ``evidence``.

US-only scope for v1 — the design convo's decision, directly answering
#17's failure-mode note about flagging unfamiliar-but-legitimate cost
structures. Other jurisdictions get their own benchmark table later.

See ``evaluate.py`` for the pure-function evaluator (Phase 2) and
``check.py`` for the LLM orchestrator that wires the lens to the
evaluator (Phase 3).
"""

from __future__ import annotations
