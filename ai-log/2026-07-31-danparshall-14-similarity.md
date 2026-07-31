# #14 — Corpus similarity (MinHash + LSH) MVP

**Session:** Dan (fable) on Air, 2026-07-31, ~14:00–16:00 EDT
**Branch:** `danparshall/14-similarity` (worktree `.worktrees/dan-14-similarity`)
**Issue:** [#14](https://github.com/nawagner/SlopChecker/issues/14) — "Similarity: compare a submission against the existing proposal corpus"
**Related:** design comment on #14 (posted early in session); depends on Alex's #94 for ground-truth pair labels (still open).

## What landed

**Engine (`src/slopchecker/similarity/`, Dan-owned):**

- `shingles.py` — word and character k-shingles from lowercased, punctuation-stripped tokens. `word_shingles(text, k=5)` returns `set[str]`; short-text policy returns a single whole-doc shingle rather than an empty signature.
- `index.py` — `SimilarityIndex(docs, threshold, num_perm=128, k=5)` wraps `datasketch.MinHash` + `MinHashLSH`. Query methods: `top_neighbors(doc_id) -> list[Neighbor]`, `clusters() -> dict[doc_id, cluster_id]` (union-find over above-threshold pairs; singletons get their own ids). Fixed MinHash seed for deterministic Jaccard estimates across runs.
- `passages.py` — `shared_passage(a, b, k=5) -> SharedPassage | None`. Finds the longest run of consecutive matching k-shingles in A whose windows all appear in B, returns the verbatim slice from A with char span. Shares the `WORD_RE` tokenizer with `shingles.py` so shingle strings match exactly across both.

**Check + wiring:**

- `pipeline/checks_similarity.py` — registered check `similar_documents` (deterministic tier). Emits `LedgerRow(check="similar_documents", result=<n_matches>)`; when the doc is in a ≥2-doc cluster also emits `LedgerRow(check="template_cluster", result=<cluster_id>)`. Per-neighbour `Finding` with anchor = shared passage from the current doc, `evidence = {matched_document_id, matched_document_file, jaccard}`, and a one-line `note` ("shares ~77% of shingles with b.txt"). Top-5 findings per doc (cap for readability); ledger count is uncapped.
- `pipeline/registry.py` — extended `CheckContext` with `batch: Sequence[FlattenedDoc] = ()` and `similarity_index: Any = None`. Added `slopchecker.pipeline.checks_similarity` to `CHECK_PACKAGES` so the check auto-registers.
- `pipeline/__init__.py` — new `build_context(docs, *, solicitation=None)` factory. Builds the `SimilarityIndex` when `len(docs) >= 2`; single-doc / empty batches leave `similarity_index=None` and the check emits a `skipped` ledger row.
- `cli.py` — batch `run` restructured as two-pass: ingest every target and collect the `FlattenedDoc`s first, then `build_context(all_docs, ...)`, then per-doc `run_checks` + write output. Failed ingests become gap rows and don't participate in the batch. Single-file mode still works (batch of one → `similarity_index=None` → clean skip).
- `pyproject.toml` — added `[project.optional-dependencies].similarity = ["datasketch>=1.6"]`. Adds `datasketch`, `numpy`, `scipy`.

**Docs / hygiene:**

- CLAUDE.md ownership table: added `src/slopchecker/similarity/` row.
- STATUS.md: log line for the branch landing.
- Design comment on #14 with module placement rationale, `CheckContext` extension shape, and the fixture-corpus threshold analysis.

## Decisions and why

- **MinHash over embeddings for MVP.** Pure-Python, deterministic, testable without a model, and hits three of #14's four acceptance criteria on its own (500-doc laptop-time index, passage-level matches, batch clustering surfaces templates). Embeddings + `sqlite-vec` are a natural follow-up — better recall on paraphrase, worse ergonomics (model download, chunking policy, ANN indexing). Ties in cleanly with Alex's forthcoming near-dup pair ground truth (#94) for real precision/recall.
- **`datasketch` as an optional extra.** Standard, well-tested (Apache 2.0), pure-Python. `LSH` matters for the 500-doc laptop AC — O(N) query instead of O(N²). Rolling our own would be ~150 lines including LSH banding; not worth reinventing.
- **Batch-aware `CheckContext` rather than a separate corpus-check protocol.** Similarity is inherently cross-doc but the check registry is per-`FlattenedDoc`. Extending `CheckContext` with `batch` + `similarity_index` is a small, targeted change that keeps the check protocol unchanged. Other corpus-level checks (dedup, reviewer COI) can reuse the seam.
- **Punctuation-stripping tokenizer (`\w+`).** Early test failure exposed that "overall" vs "overall." defeated shingle equality. Near-dup detection wants punctuation-robust normalization — this is standard for the domain. Kept the tokenizer definition (`WORD_RE`) in `shingles.py` and shared it with `passages.py` so both produce identical shingle strings.
- **Default threshold 0.5.** Fixture corpus probe showed same-topic same-doctype pairs at Jaccard 0.17–0.33 (topic phrase + shared template scaffold), true near-dups at 0.6+ (e.g., planted E2E test). 0.5 is conservative and defensible: false-negative on scaffold-only overlap, catches real paraphrase pairs. Users can tune via a CLI flag in a follow-up.
- **Renderer left alone.** `report/` is Emerson's; similarity findings render adequately as-is (one-line note + anchored quote highlight). Filing a follow-up for side-by-side matched-doc UI + jaccard badge.

## Dead ends / gotchas

- **`ai_laundered` fixtures on main are NOT paired with `ai_clean` originals.** Initial assumption was wrong; different topics. Explicit pair ground truth lives in Alex's open #94. Chose to build against current main anyway and score-by-inspection on the template groups; proper precision/recall waits on #94.
- **LSH threshold cliff.** `datasketch.MinHashLSH(threshold=0.99, num_perm=128)` fails to bucket (b<2 in `_optimal_param`). Adjusted one test to use 0.9 as "high" instead of 0.99; the near-cliff behaviour is intrinsic to LSH and not worth working around.
- **Rich table truncated `pangram_document` id.** My new check widened the "Name" column, pushing "Check id" narrower. Fix: `no_wrap=True` on the Check id column in `cli._dry_run`. Real usability improvement (IDs are what users pass to `--only`/`--skip`), plus unblocks the test.

## Testing

- 32 new tests across `test_similarity_shingles.py`, `test_similarity_index.py`, `test_similarity_passages.py`, `test_similarity_context.py`, `test_similarity_check.py`. Cover: shingling edge cases (short/empty/case/whitespace), MinHash+LSH build/query/cluster/threshold/determinism/duplicate-id error, shared-passage verbatim + longest-run + case preservation + none-case, `CheckContext` defaults + `build_context` factory, check skip-on-single-doc + zero-matches + matches + finding-quote-verbatim + evidence-carries-counterparty + cluster-row-emission.
- End-to-end verified via CLI: two planted-similar docs + one distinct in a batch → both similar docs get `similar_documents=1`, `template_cluster` row, and a `Finding` with counterparty file, Jaccard 0.60, and anchor quote verbatim from the source.
- Full suite: **251 unit passed, 9 integration passed, 0 failures, ruff clean.**

## Follow-ups (to file after merge)

- Local embeddings + `sqlite-vec` for paraphrase-robust semantic near-dups; needs Alex's #94 paired ground truth for precision/recall scoring.
- Reviewer-pool conflict-of-interest signal (COI lane per #14, kept separate from slop signals).
- Renderer support for cross-doc findings (Emerson): side-by-side matched-passage view, Jaccard score badge, batch-cluster summary panel.
- CLI `--similarity-threshold` flag for users who want to tune.
