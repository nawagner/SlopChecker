"""Corpus similarity (#14): MinHash + shingling for near-duplicate detection.

Engine-first module. `shingles` turns document text into hashable k-shingles;
`index` builds a MinHash+LSH over a batch of documents and answers top-K near-
neighbour and cluster queries. The registered check (`checks/similarity.py`)
imports from here and emits ledger rows + quote-anchored findings.

Design (see comment on #14):

- **Batch-aware, per-doc emission.** Similarity is inherently corpus-level, but
  the check protocol is per-`FlattenedDoc`. The runner builds one
  `SimilarityIndex` per batch and injects it via `CheckContext.similarity_index`;
  the check queries the index for each doc. Single-file runs get a `skipped`
  ledger row with a clear reason.

- **MinHash + LSH.** Locality-sensitive hashing keeps top-K queries at O(N)
  instead of O(N^2), which the "500-doc corpus on a laptop" AC needs. We use
  `datasketch` (Apache 2.0), a well-tested pure-Python implementation.

- **Scores are evidence, not verdicts.** Jaccard estimates land in the ledger
  and in `Finding.evidence` — never as a pass/fail. The report displays
  similarity in its own visual lane per the ground rules.
"""
