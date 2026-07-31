# Synthetic funding-document corpus (#22)

A labeled corpus of synthetic funding documents for testing SlopChecker's checks.
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

## Document types

The `document_type` dimension covers all three types #22 asks for:

- **`grant_application`** — Specific Aims, Background, Approach, Innovation, Budget Justification.
- **`blog_post`** — dek, intro, body, takeaway.
- **`think_tank_report`** — Executive Summary, Background, Findings, Recommendations.

## What each authorship class exercises

- **`human`** — human-written baseline (fabricated in this committed set; the generator can instead seed the grant class from public NIH RePORTER abstracts). No defects. A check that flags these is a false positive.
- **`ai_clean`** — machine-written, well-formed, no defects. Tests the AI-detection lane in isolation.
- **`ai_laundered`** — an AI document paraphrased and section-shuffled to evade detectors. The evasion case.
- **`slop`** — AI-written with a planted defect (see below). The primary target.

## Planted defects (slop only)

Each is a ground-truth column in `manifest.csv`:

- `has_fabricated_citations` — one or more cited DOIs do not resolve. **All doc types.**
- `overclaims` — grandiose, unsupported claims. **All doc types.**
- `budget_inflated` — an implausibly large budget. **Grant applications only.**
- `missing_methods` — a vague, hand-waved methods section. **Grant applications only.**

The `all` defect sets every *applicable* flag for that document type at once.

## Mapping to the data model

These fixtures are *inputs*: a loader or the ingestion module (#4) turns each
document into a `FlattenedDoc`, and a checker's output is an `EvidenceReport`
(`report.json`). The canonical contract is `docs/DATA_MODEL.md`; the ground-truth
columns here are the eval answer key, separate from the report.

Each ground-truth column maps to a `CheckResult.name` in that contract:

| corpus ground truth | check (per DATA_MODEL.md) |
|---|---|
| `has_fabricated_citations` | `doi_resolves` (false) |
| `ai_generated` | `pangram_span` / `pangram_document` (score lane) |
| `overclaims`, `budget_inflated`, `missing_methods` | quality-tier checks |

The "valid DOI pointing to the wrong paper" case maps to a `Finding.verdict` of
`overstated` / `unsupported` (with `quote_in_source` / `metadata_match`); not
generated yet — see Open items.

## Provenance and license

Every document in this committed set is **fully synthetic** (`seed_source: builtin`
in each record) — no real applicant material, per #22. The generator's default
mode instead seeds the grant `human` class from public NIH RePORTER abstracts;
that mode is for local use and is intentionally not committed here.

## Regenerate

Deterministic with the seed. From the repo root:

```bash
python3 scripts/synth/synth_proposals.py --n 120 --offline --seed 42 --out tests/fixtures/synthetic
```

Restrict to some document types with `--doctypes grant_application blog_post`.
Add `--backend anthropic --model claude-sonnet-5` (needs `ANTHROPIC_API_KEY`) for
realistic prose instead of templated text; same labels and citation logic.

## Score a check against it

```bash
python3 scripts/synth/score.py --corpus tests/fixtures/synthetic --demo
```

`--demo` runs a deliberately naive baseline. Point `--predictions FILE` at a real
check's output (JSONL/CSV of `{id, <boolean fields>}`) to score it. Note: the
naive baseline scores well on grant templates but drops sharply on blog/report
prose and model-backed text — a check that only passes on templates has not been
tested against realistic slop.

## Open items (tracked on #22)

- PDF and DOCX rendering of fixtures.
- "Valid DOI pointing to the wrong paper" case.
- Explicit near-duplicate pairs with linked provenance.
- A budget with a deliberate arithmetic error.
