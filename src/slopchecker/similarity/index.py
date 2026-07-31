"""MinHash+LSH index over a batch of documents (#14).

Wraps ``datasketch`` for the pure primitives (MinHash signatures, LSH bucketing)
and adds:

- **Union-find clustering** over pairs above threshold: transitive template
  groups collapse into a single component, which is the "mass-generated from
  one template" acceptance criterion.
- **Deterministic output**: fixed MinHash seed + stable per-doc iteration order,
  so a rerun on the same input produces identical Jaccard estimates and
  identical cluster partitions.
- **Caller-safe errors**: unknown doc ids raise ``KeyError``, duplicate file
  names raise ``ValueError`` at build time — a batch with two docs sharing an
  id is a caller bug, not something for us to silently pick.

Threshold is Jaccard-estimated on MinHash signatures. Real Jaccard is bounded
above by 1.0; the MinHash estimator has variance ~ sqrt(J*(1-J)/num_perm) so
the default ``num_perm=128`` puts one-sigma error at ~4pp near J=0.5. Bump
``num_perm`` for tighter estimates at the cost of proportional memory.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from datasketch import MinHash, MinHashLSH

from slopchecker.models import FlattenedDoc
from slopchecker.similarity.shingles import char_shingles, word_shingles

DEFAULT_NUM_PERM = 128
DEFAULT_THRESHOLD = 0.5
DEFAULT_K = 5
MINHASH_SEED = 42  # fixed so builds are reproducible

ShingleKind = Literal["word", "char"]


@dataclass(frozen=True)
class Neighbor:
    """One near-neighbour of a query doc, with the estimated Jaccard."""

    doc_id: str
    jaccard: float


class SimilarityIndex:
    """MinHash+LSH index over a batch of ``FlattenedDoc``s.

    Build once per run, query per doc. ``doc.file`` is used as the identifier;
    duplicate file names raise. ``clusters()`` returns a doc-id -> cluster-id
    map covering every input doc (singletons get their own cluster id).
    """

    def __init__(
        self,
        docs: Sequence[FlattenedDoc],
        *,
        threshold: float = DEFAULT_THRESHOLD,
        num_perm: int = DEFAULT_NUM_PERM,
        k: int = DEFAULT_K,
        shingle_kind: ShingleKind = "word",
    ) -> None:
        if not 0.0 < threshold <= 1.0:
            raise ValueError(f"threshold must be in (0, 1], got {threshold}")
        self._threshold = threshold
        self._num_perm = num_perm
        self._k = k
        self._shingle_kind = shingle_kind
        self._doc_ids: list[str] = []
        self._signatures: dict[str, MinHash] = {}
        for doc in docs:
            if doc.file in self._signatures:
                raise ValueError(f"duplicate doc id in batch: {doc.file!r}")
            self._doc_ids.append(doc.file)
            self._signatures[doc.file] = self._sign(doc.text)

        # LSH bucketing so top-K queries stay ~O(N) instead of O(N^2).
        self._lsh: MinHashLSH | None
        if len(self._signatures) >= 2:
            self._lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
            for doc_id, sig in self._signatures.items():
                self._lsh.insert(doc_id, sig)
        else:
            self._lsh = None

    def _sign(self, text: str) -> MinHash:
        shingles = (
            word_shingles(text, k=self._k)
            if self._shingle_kind == "word"
            else char_shingles(text, n=self._k)
        )
        sig = MinHash(num_perm=self._num_perm, seed=MINHASH_SEED)
        for sh in shingles:
            sig.update(sh.encode("utf-8"))
        return sig

    def top_neighbors(self, doc_id: str) -> list[Neighbor]:
        """All docs above threshold, sorted by estimated Jaccard descending.

        Excludes the query doc itself. Empty list when the doc has no
        above-threshold peers. Ties break on ``doc_id`` for determinism.
        """
        if doc_id not in self._signatures:
            raise KeyError(doc_id)
        if self._lsh is None:
            return []
        sig = self._signatures[doc_id]
        candidates = [c for c in self._lsh.query(sig) if c != doc_id]
        scored = [
            Neighbor(doc_id=c, jaccard=float(sig.jaccard(self._signatures[c]))) for c in candidates
        ]
        # LSH returns candidates that PROBABLY meet the threshold; verify with
        # the MinHash estimate and drop false positives before returning.
        scored = [n for n in scored if n.jaccard >= self._threshold]
        scored.sort(key=lambda n: (-n.jaccard, n.doc_id))
        return scored

    def clusters(self) -> dict[str, int]:
        """Union-find cluster of each doc: transitive near-dup components.

        Singletons get their own unique cluster id, so every input doc appears
        exactly once in the returned map.
        """
        parent: dict[str, str] = {d: d for d in self._doc_ids}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        # Iterate deterministically so a rerun produces the same partition
        # (union-find output can depend on order under path-compression).
        for doc_id in self._doc_ids:
            for neighbour in self.top_neighbors(doc_id):
                union(doc_id, neighbour.doc_id)

        # Compact roots to sequential integer ids in first-seen order.
        root_to_cluster: dict[str, int] = {}
        result: dict[str, int] = {}
        for doc_id in self._doc_ids:
            root = find(doc_id)
            if root not in root_to_cluster:
                root_to_cluster[root] = len(root_to_cluster)
            result[doc_id] = root_to_cluster[root]
        return result

    @property
    def threshold(self) -> float:
        return self._threshold

    def doc_ids(self) -> Iterable[str]:
        return iter(self._doc_ids)
