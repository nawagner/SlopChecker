# lens-eval — before/after eval for claims-lens tuning (#144)

`run_eval.py` runs the pre-tune lens (branch point) and the working-tree
lens over the synthetic corpus + the two `pending_lens: claims` harness
defects (injected), checkpointing every run to `results.jsonl` (append-only,
resume-safe, conditions per row). `analyze.py [versionA versionB]`
summarizes counts, scope splits, and planted-defect recall.

Seed of the #107 stability eval.

## results.jsonl version-label provenance

- `v0.1` — genuine pre-tune lens (sha `39437adacc57`), rounds 1–2.
- `v0.2` — intermediate tuned prompt (specificity gate, pre-scope), round 2.
- `v0.3` — shipped prompt: scope taxonomy (sha `023bd5775dd3`), round 2,
  **before** the whitespace-tolerant anchoring fix.
- `v0.3r2` — same v0.3 lens **after** the anchoring fix.
- `v0.1r2` — **MISLABELED, actually the v0.3 lens** (sha `023bd5775dd3`):
  the baseline was extracted from `HEAD`, which by round 3 contained the
  tuned lens. Rows kept per append-only discipline; treat them as extra
  v0.3r2 replicates. `materialize_v01` is now pinned to
  `merge-base(HEAD, origin/main)` so this can't recur.
- `v0.1r3` — genuine pre-tune lens re-run with the anchoring fix (the
  diagnostic `v0.1r2` was meant to be).

Trust `lens_sha`, not the label, when in doubt — that's why it's recorded.
