# Synthetic grant-proposal corpus (#22)

A labeled corpus of synthetic grant proposals for testing SlopChecker's checks.
Every document carries ground-truth labels, so the corpus doubles as an eval
set: a check either recovers the planted defect or it does not, measurably.

Built with the dimensions → tuples → generate method from Hamel Husain and
Shreya Shankar's evals guide (https://hamel.dev/blog/posts/evals-faq/): define
explicit facets, enumerate combinations for systematic coverage, then expand
each combination into a full document.

## Files

- `corpus.jsonl` — one record per document (full text, citations, dimensions, ground truth).
- `manifest.csv` — one row per document with the dimension and ground-truth columns; this is the file `score.py` reads.
- `coverage.json` — value counts per dimension, to confirm the grid is actually covered.
- `run_meta.json` — how this set was generated (informational).

Tooling lives in `scripts/synth/` (`synth_proposals.py`, `score.py`).

## What each class exercises

- **`human`** — human-written baseline (fabricated in this committed set; the generator can instead seed from public NIH RePORTER abstracts). No defects. A check that flags these is a false positive.
- **`ai_clean`** — machine-written, well-formed, no defects. Tests the AI-detection lane in isolation.
- **`ai_laundered`** — an AI proposal paraphrased and section-shuffled to evade detectors. The evasion case.
- **`slop`** — AI-written with a planted defect (see below). The primary target.

## Planted defects (slop only)

Each is a ground-truth column in `manifest.csv`:

- `has_fabricated_citations` — one or more cited DOIs do not resolve.
- `overclaims` — grandiose, unsupported guarantees of success.
- `budget_inflated` — an implausibly large budget for the scope.
- `missing_methods` — a vague, hand-waved methods section.

The `all` defect sets every flag at once.

## Mapping to the report contract

The ground-truth columns line up with checks in `tests/fixtures/sample_report.json`:

| corpus ground truth | report.json check |
|---|---|
| `has_fabricated_citations` | `doi_resolves` (false) |
| `ai_generated` | `pangram_span` / `pangram_document` |
| `overclaims`, `budget_inflated`, `missing_methods` | proposal-quality checks |

The "valid DOI pointing to the wrong paper" case (`metadata_match` / `quote_in_source`
in the report) is not generated yet — see Open items.

## Provenance and license

Every document in this committed set is **fully synthetic** (`seed_source: builtin`
in each record) — no real applicant material, per #22. The generator's default
mode instead seeds the `human` class from public NIH RePORTER abstracts; that
mode is for local use and is intentionally not committed here.

## Regenerate

Deterministic with the seed. From the repo root:

```bash
python3 scripts/synth/synth_proposals.py --n 60 --offline --seed 42 --out tests/fixtures/synthetic
```

Add `--backend anthropic --model claude-sonnet-5` (needs `ANTHROPIC_API_KEY`) for
realistic prose instead of templated text; same labels and citation logic.

## Score a check against it

```bash
python3 scripts/synth/score.py --corpus tests/fixtures/synthetic --demo
```

`--demo` runs a deliberately naive baseline. Point `--predictions FILE` at a real
check's output (JSONL/CSV of `{id, <boolean fields>}`) to score it. Note: the
naive baseline scores near-perfectly on this templated set but collapses on the
model-backed corpus — a check that only passes here has not been tested against
realistic slop.

## Open items (tracked on #22)

- Blog-post and think-tank-report document types (this covers grant applications).
- PDF and DOCX rendering of fixtures.
- "Valid DOI pointing to the wrong paper" case.
- Explicit near-duplicate pairs with linked provenance.
- A budget with a deliberate arithmetic error.
