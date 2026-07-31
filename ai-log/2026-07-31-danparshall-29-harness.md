# 2026-07-31 — Dan (fable): #29 validation harness

## What landed

`harness/` — planted-defect validation, ports pat-helper's pattern to
SlopChecker's data model:

- `harness/injector.py` — copy fixtures + first-occurrence substring
  replace + manifest. Deletion via `mutated: ""`. Hard-errors on missing
  `original`.
- `harness/run.py` — orchestrator. Ingest each mutated fixture, run
  `extract_citations` + `check_quotes` directly (they're not registered
  yet — see follow-up), score recall against a per-defect `match.kind`.
  Writes `harness/out/harness_YYYY-MM-DD.md`.
- `harness/defects.yaml` — MVP defect corpus: 3 catchable (2 citation,
  1 quote) + 2 `pending_lens: claims`.
- `harness/fixtures/*.md` — two fabricated grant proposals authored this
  session by a subagent.
- `harness/sources/*.txt` — fabricated source-of-truth text for the
  Priestley reference (so `check_quotes` has something to fuzzy-match
  against).
- `harness/README.md` — run instructions, add-a-defect guide, design
  rationale.
- `tests/test_harness.py` — end-to-end canary (all outcomes asserted) +
  three injector correctness tests. Offline, 0.13 s.
- `.gitignore` — `harness/out/` added.
- `pyproject.toml` — new `harness` optional extra (`pyyaml`).

Recall on the current corpus: **3 / 3** on the runnable defects, plus 2
`PENDING` reported as coverage gaps.

## Key design decisions (with Dan, in-session)

1. **Fixture format A over B.** Mutate `.md` fixtures pre-ingest, not
   post-ingest `FlattenedDoc.text`. Rationale: MVP measures check recall,
   not ingest fidelity — those are different questions and conflating
   them makes a bad recall number ambiguous. B is filed as follow-up
   (#71), which also picks up Dan's Task Exposure paper as a real fixture
   via a `.tex` ingest path (currently unsupported) or compile-to-PDF +
   post-ingest mutation.

2. **Deterministic matcher over LLM judge.** Pat-helper uses an LLM
   judge because *its findings are prose*. SlopChecker's checks return
   `bool | int | float` with structured `evidence` dicts — matching is
   naturally mechanical. Match vocabulary lives in `MATCHERS` in `run.py`,
   named by `defects.yaml` — a check refactoring its evidence shape only
   touches one file. LLM judge slot is reserved for claims-lens defects
   once #37 unblocks them.

3. **`PENDING` is a first-class outcome, not `MISS`.** A defect that
   requires an unlanded check drags recall for a reason unrelated to
   check quality if reported as MISS. Reporting as coverage gap keeps
   the recall number honest.

## Dead ends / gotchas

- **First quote-mutated-edu defect scored 0.882 fuzzy** and passed the
  0.85 threshold, so the defect was MISS'd. Swapped a single phrase
  (~7% of the ~460-char quote) — not enough. Fix: replace the whole
  quoted content with fabricated text; also arguably more realistic
  (a fabricated attribution is usually whole-cloth, not one word).
  Noted in the defect's description so the next author doesn't
  repeat the mistake.
- **`misattr-edu`'s original string crossed a line-wrap** in the
  fixture and the injector's raw substring match failed at first. Fix:
  shorter original that stays on one line. Alternative would be YAML
  `|-` block scalars matching the wrapping — deferred until a defect
  genuinely needs to span multiple lines.
- **DOI-resolution defects deferred**, not because they're hard but
  because the DOI-resolution check (Nick's #8) hasn't landed. They'd
  be MISS-by-construction. Added once #8 registers.

## In-flight coordination

- Fired 3 parallel subagents at session start: fixture drafting,
  filing #71 (harness B follow-up), and a small PR (#72, merged) to
  add Alex's GH handle (`990991A`) to the CLAUDE.md team table.
- Dan mentioned #37 is starting soon in another session. When it lands
  the two `pending_lens: claims` defects convert to catchable without
  code changes.
- #12 (Pangram) is in flight in another Dan session; I did not touch
  detection code.

## What's next

- Wait for #7/#10's registry wiring to land, then swap `_run_checks` in
  `harness/run.py` for `run_checks(doc, all_checks())`. `MATCHERS` stays.
- Add DOI-resolution defect(s) once Nick's #8 lands.
- Expand the fixture corpus once #22 lands (Alex's synth PDF fixtures) —
  covered by #71.
