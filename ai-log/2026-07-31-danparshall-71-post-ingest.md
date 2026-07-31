# 2026-07-31 — Dan (fable) — #71 post-ingest mutation

Landing item 1 of [#71: Harness follow-up: post-ingest mutation + real-fixture
support](https://github.com/nawagner/SlopChecker/issues/71) — the follow-up
Dan filed alongside the #29 MVP harness.

Branch: `danparshall/71-post-ingest-mutation` (worktree at
`.worktrees/dan-71-post-ingest`).

## What landed

New module `harness/post_ingest.py`:

- `mutate_ingest_result(result, defects) -> (new_result, manifest)` —
  siblings of `harness/injector.py`'s `inject()`. Same defect-spec
  discipline (`{id, original, mutated, ...}`, first-occurrence match,
  missing-`original`-is-a-hard-error, deletion via empty `mutated`,
  sequential application against already-mutated text) but operates on
  `FlattenedDoc.text` post-ingest instead of on source files pre-ingest.
- Mechanical span shifting for `IngestResult.references`,
  `IngestResult.sections`, and `FlattenedDoc.page_offsets`. Rules
  (half-open):
  - span entirely before mutation → unchanged
  - span entirely after mutation → shift both endpoints by delta
  - mutation entirely inside span → extend `.end` by delta
  - partial overlap → hard-error (recall on such a defect would be
    meaningless; better to refuse the defect than silently corrupt spans)
- Manifest carries the same pass-through fields
  (`match`/`pending_lens`/`check_expected`/`description`) so the recall
  vocabulary in `harness/run.py` — `MATCHERS` and
  `_finding_matches_defect` — doesn't care which path a defect came
  from.

`harness/run.py` extended:

- `run_harness()` now accepts an optional `substrates_dir=` kwarg.
- Defects with a `substrate:` field (path relative to `substrates_dir`)
  route through the post-ingest path; defects with `file:` (no
  `substrate:`) keep going through the existing pre-ingest `inject()`
  path. Both merge back into the same `per_file_findings` map before
  recall scoring, so no changes to the scoring layer.
- CLI: new `--substrates` flag defaulting to `harness/substrates/`.
- Ingest failure on a substrate degrades to a gap row and manifests the
  affected defects with `line: 0`, so the report tells you what the
  loader couldn't handle rather than crashing the run.

`harness/defects.yaml` extended:

- New `cite-orphan-real-pdf` defect: insert an orphan `[99]` marker into
  the first `Aim 1:` heading of a real grant PDF. The synthetic corpus
  numbers references 1..~10; `[99]` has no matching reference entry, so
  `citation_has_reference` flags it. First shipped defect exercised on
  a real PDF loader in the harness recall measurement.

`harness/substrates/`:

- New directory holding real-document substrates for post-ingest defects.
- One relative symlink into `tests/fixtures/synthetic/files/` — no file
  duplication, harness dir stays self-contained. Ships with just the one
  grant PDF; teammates can drop in more substrates without moving the
  fixture corpus around.

## Tests

`tests/test_post_ingest.py` — 13 new tests:

- Core mutation semantics (5): text replacement, deletion via empty
  `mutated`, missing-original hard-error, line-number recording,
  sequential application.
- Manifest metadata pass-through (1).
- Span shifting (4): downstream references shift, upstream unchanged,
  containing-section extension, page-offset shift.
- Partial-overlap hard-error (1).
- End-to-end on a real PDF (2): mutation survives the loader; harness
  scores 1/1 recall on an orphan-citation defect through the PDF path.

`tests/test_harness.py` — canary updated to include the new
`cite-orphan-real-pdf` outcome. Expected: `HIT` (4/4 runnable recall, up
from 3/3). If the PDF loader or post-ingest mutation regresses, this
defect flips to `MISS` and the test tells you exactly which one broke.

Full suite: 444 passed, 9 deselected. Ruff + mypy clean on new code.
Manual `uv run python harness/run.py` writes a `4/4` recall report.

## Design decisions

**Why not refactor `injector.py` and `post_ingest.py` behind a common
base class.** Both modules have injector.py-style discipline for reasons
that will drift independently over time (path-based vs offset-based
diagnostics, file-format-specific vs loader-agnostic constraints). At 75
lines and 170 lines respectively, deduplicating now would be premature.

**Why in-place span shifting instead of re-parsing after mutation.**
The loaders take file paths and re-parse the file format; they don't
expose a "detect sections in this string" entry point. Adding one would
push refactor into the ingest module, which #71's scope specifically
avoids ("the change is *where* in the pipeline the mutation is spliced
in"). Mechanical shifting also gives predictable behavior:
delta-per-mutation, downstream by that delta — vs "re-parse and hope the
heading detector still agrees."

**Why hard-error on partial-span-overlap rather than making a best
effort.** A defect that straddles `[references_start]` (say, mutating
`"paragraph. References"` → something) leaves the recall system in a
state where "did the check catch this?" isn't well-defined — the check
sees a different references region than the mutation intended. Silently
resolving it either way corrupts recall for the wrong reason (same
argument as `injector.py`'s missing-original hard-error).

**Why insert `[99]` instead of swapping `[1]`→`[9]` for the real-PDF
defect.** Checked all 8 grant PDFs in
`tests/fixtures/synthetic/files/`: none have in-body `[N]` markers, only
references-region ones. Insertion is the natural mutation, and it also
tests the "grow text past a span boundary" path.

## Dead ends

None material. The end-to-end test initially failed (`MISS` instead of
`HIT`); root cause was picking the first `[N]` marker in the flattened
text, which was inside the references region, so `extract_citations`
excluded it. Fixed by switching to insertion. A 20-second debug loop
via a `/tmp/debug_71*.py` script confirmed the loader was preserving
text + refs region correctly — the mutation strategy just needed to
match the corpus.

## What's next

Item 2 of #71 (Task Exposure paper as real fixture source) is still
open. Two routes:

- **(a) `.tex` ingest path in slopchecker.** New loader in
  `src/slopchecker/ingest/`. Bigger change; would benefit other real
  academic writing too.
- **(b) Compile `.tex` → PDF, then use the post-ingest path from item
  1.** No new loader needed. Now unblocked by item 1 landing.

Route (b) is a small follow-up: symlink the compiled PDF into
`harness/substrates/`, add one or two defects, done. Not doing it in
this PR to keep the diff focused.
