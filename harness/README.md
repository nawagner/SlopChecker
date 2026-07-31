# harness/ — planted-defect validation (#29)

Answers the question "how do you know your checks work?" with a number
instead of a shrug. Copies `harness/fixtures/` to a mutated directory,
applies every defect in `defects.yaml` (first-occurrence substring replace),
runs the currently-available checks, and scores recall.

## Run it

```bash
uv pip install -e ".[harness]"      # adds pyyaml
uv run python harness/run.py        # -> harness/out/harness_YYYY-MM-DD.md
```

Recall report is a markdown table (per-defect HIT/MISS/PENDING) plus an
"extras" list of findings that matched no planted defect. `harness/out/`
is gitignored — no per-run report clutter on `main`.

The tiny end-to-end regression that guards the harness itself lives in
`tests/test_harness.py` and runs as part of the normal pytest suite
(offline, deterministic, ~0.15 s).

## The MVP defect set

MVP ships 5 defects: 3 catchable now by the deterministic checks, 2
`pending_lens: claims` (blocked on the LLM-client work in #37 — they will
convert to catchable automatically the day that lands, no code change).

| defect | file | caught by |
|---|---|---|
| `cite-orphan-climate` | proposal_climate.md | `extract_citations` (unlinked marker) |
| `cite-missing-ref-climate` | proposal_climate.md | `extract_citations` (references deleted) |
| `quote-mutated-edu` | proposal_edu.md | `check_quotes` (fuzzy match fails against source) |
| `unsupported-claim-climate` | proposal_climate.md | pending (needs claims lens) |
| `misattr-edu` | proposal_edu.md | pending (needs claims lens) |

DOI-resolution defects are a natural fit but no DOI-resolution check has
landed yet (Nick's #8). They'd be MISS-by-construction and would drag the
recall number for an uninformative reason, so they're deferred to the same
follow-up as the check.

## Fixtures

- `fixtures/*.md` — fabricated grant proposals. Repo rule: no real
  applicant material, ever. If you add a fixture, keep it fabricated.
- `sources/*.txt` — fabricated source-of-truth text for `check_quotes` to
  match verbatim quotes against. Filename follows
  `slopchecker.pipeline.quotes.fetch.source_keys(ref)[0]` — e.g.
  `doi-10.9999_fake-5580-1902.txt` for DOI `10.9999/fake-5580-1902`. Each
  file's first two lines are a fabrication disclaimer.

## Adding a defect

1. Pick a fixture that contains the exact text you want to mutate. If your
   `original` string spans multiple lines, use YAML block scalar (`|-`) so
   the newlines are preserved literally — the injector does a raw
   substring match.
2. Add a `defects.yaml` entry: `id`, `file`, `original`, `mutated`,
   `check_expected`, `match`, `description`. `mutated: ""` deletes the
   span (used by `cite-missing-ref-*`).
3. Pick a `match.kind` from `MATCHERS` in `run.py`. If your defect needs
   a new match shape (a new check's evidence dict), add the matcher there.
4. Run `uv run python harness/run.py` and confirm your defect scores HIT.
   Update the assertion in `tests/test_harness.py` to include it.

## Extending to more defect types

The follow-up ticket for **post-ingest mutation + real-source fixtures**
(#71 as of 2026-07-31) covers the harness B path: mutate
`FlattenedDoc.text` after ingest, so mutations run against real PDF
fixtures (once #22 lands) and Dan's Task Exposure paper is usable as a
real source. The current pre-ingest MD-mutation path stays as the CI-safe
default.

## Design decisions

- **`.md` fixtures, not PDF.** MVP measures check recall; PDF ingest
  fidelity is #22's job. Conflating them makes a bad recall number
  ambiguous. See #71 for the PDF path.
- **Deterministic matcher, not LLM judge.** Pat-helper (the port target)
  uses an LLM judge because its findings are prose. SlopChecker's checks
  return `bool | int | float` with structured `evidence` dicts — matching
  is naturally mechanical. LLM judge slot is reserved for when claims-lens
  defects become runnable and prose judgment is genuinely needed.
- **Pending defects report as PENDING, not MISS.** A defect that requires
  an unlanded check would drag recall for a reason unrelated to check
  quality. Reporting it as a coverage gap keeps the recall number
  honest.
- **Injector is a hard error on `original not found`.** A silently
  unplanted defect would count as MISS forever — a false signal that
  masks real check regressions.
