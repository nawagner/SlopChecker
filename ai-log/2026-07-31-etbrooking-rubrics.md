# 2026-07-31 — etbrooking — rubrics: naming, fixtures, R2, ingest verification

Session: Claude Fable 5 (orchestrator) + one Sonnet subagent (fixture authoring).
Issues: #90 (filed and claimed this session), touching #16, #27, #74.

## What happened

- Earlier in the session: landing-page refinement handed to Dominique as #74
  (worker/public statics only; #27 infra stays with Emerson), ownership table
  updated, merged as PR #76.
- Named the concept: **rubric** = funder-side reference document set a
  submission is checked against (solicitation/RFP, evaluation criteria).
  Deliberately excludes cited-source texts (SourceFetcher, #10/#11) and the
  similarity corpus (#14). Filed #90 with the architecture strawman: rubrics
  are ordinary documents → existing ingest → FlattenedDoc; R2 storage under
  `rubrics/`; `--rubric` CLI flag; optional `rubric` multipart field on
  `POST /check` (coordinate with #27); #16's YAML spec is the *compiled*
  form of a rubric.
- Three fabricated rubric fixtures written (Sonnet subagent) into
  `fixtures/rubrics/`, each pairing with an existing harness proposal and
  carrying planted, verified compliance violations (map in that dir's
  README): Aldergrove RFP (3 violations vs proposal_climate), Aldergrove
  scoring rubric (table-heavy shape), Hartwell RFP (2 violations vs
  proposal_edu). All violations were independently verified against the
  proposals before accepting (budget totals, missing headings, zero IRB
  mentions).
- Rendered PDFs (pymupdf Story, letter, 0.75in margins) and uploaded md+pdf
  (6 objects) to R2 `slopchecker-docs/rubrics/synthetic/` using the
  bucket-scoped token from `.env`. Listing verified.
- Ingest verification on all six files: status=ok everywhere; markdown
  yields full section structure (11–14 sections); PDF text layer intact
  (all planted facts found verbatim) but **sections=0 — the PDF loader does
  no heading detection**. Consequence: rubric→spec drafting from a funder
  PDF works off raw text, or prefer the md when we have it.

## Decisions

- `harness/fixtures/` is NOT the home for rubrics: the harness mutates and
  checks everything there, so a rubric would be scored as a proposal. New
  top-level `fixtures/rubrics/` instead; ownership row added.
- Repo copy is canonical; R2 is the mirror. Re-upload after editing.

## Dead ends / gotchas

- `IngestResult` fields are `document`/`sections` (not `doc`); a first
  verification pass silently probed missing attrs via getattr and printed
  all-zeros with status=ok — misleading. Assert on the real fields.
- Merge of PR #76 hit the expected STATUS.md keep-both conflict with Nick's
  simultaneous entry; resolved per house convention.

## Left to do (#90 checklist)

- `slopcheck run --rubric <path>` plumbing
- `rubric` upload slot on `POST /check` (with the #27 session)
- Spec-drafting bridge to #16 (rubric doc → draft YAML → human review)

## Second slice (same day, later session state): CLI plumbing + first check

- `CheckContext.rubric: FlattenedDoc | None` (registry.py — Dan's module,
  one additive field; flagged on #90 and in STATUS).
- `--rubric <path>` on `slopcheck run`: ingested once per run, fail-fast on
  a bad path (unlike batch files it applies to every target); rubric
  filename stamps `report.solicitation` when no explicit label given. The
  pre-existing `--solicitation` string stays as the label-only channel —
  nothing consumed `ctx.solicitation` before and nothing does now.
- `pipeline/checks_rubric.py` — `rubric_budget_ceiling`, deterministic:
  two-tier cap-phrase parse (strong "may not exceed / maximum award /
  ceiling", weak "up to") over rubric lines; multiple distinct cap amounts
  = skipped "ambiguous", not a guess. Proposal side: max $ on a
  "total"-containing line, span = whole line so the anchor quote
  string-matches uniquely. Findings carry rubric_quote + both numbers in
  evidence.
- Ground truth: tests run the real committed fixtures — Aldergrove vs
  proposal_climate and Hartwell vs proposal_edu both planted budget
  violations caught (2/2 of the budget plants; the other 3 planted
  violations need section/attachment checks, which need the #16 spec).
- Fallout: none observed; 484 passed, ruff clean. `datasketch` needed a
  local pip install (Dan's #14 similarity dep) — pre-existing, not mine.
