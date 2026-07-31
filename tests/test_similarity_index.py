"""Tests for SimilarityIndex — MinHash+LSH over a batch of FlattenedDocs (#14)."""

from __future__ import annotations

import pytest

from slopchecker.models import FlattenedDoc
from slopchecker.similarity.index import SimilarityIndex


def _doc(name: str, text: str) -> FlattenedDoc:
    return FlattenedDoc(file=name, text=text)


# A pair of highly similar docs (small edit) and a distinct doc, useful across
# tests. The two similar docs share ~all their word-5-shingles.
SIMILAR_A = (
    "The quick brown fox jumps over the lazy dog. "
    "Now is the time for all good citizens to come to the aid of their country. "
    "In the beginning God created the heaven and the earth."
)
SIMILAR_B = (
    "The quick brown fox jumps over the lazy dog. "
    "Now is the time for all good citizens to come to the aid of their country. "
    "In the beginning God created heaven and the earth."  # dropped one "the"
)
DISTINCT = (
    "Photosynthesis converts sunlight into chemical energy in plants. "
    "The Krebs cycle is a series of chemical reactions used by all aerobic organisms. "
    "Mitochondria are the powerhouses of the cell."
)


class TestBuild:
    def test_empty_batch_returns_empty_clusters(self) -> None:
        idx = SimilarityIndex([], threshold=0.5)
        assert idx.clusters() == {}

    def test_single_doc_batch_returns_one_singleton(self) -> None:
        idx = SimilarityIndex([_doc("a.txt", SIMILAR_A)], threshold=0.5)
        # A singleton by convention gets cluster id 0.
        clusters = idx.clusters()
        assert set(clusters) == {"a.txt"}
        # A singleton doc has no neighbours.
        assert idx.top_neighbors("a.txt") == []

    def test_duplicate_file_names_raise(self) -> None:
        # Ambiguous doc ids are a caller error, not something to silently pick.
        with pytest.raises(ValueError, match="duplicate"):
            SimilarityIndex(
                [_doc("dup.txt", SIMILAR_A), _doc("dup.txt", DISTINCT)],
                threshold=0.5,
            )


class TestNeighbours:
    def test_similar_docs_are_neighbours_with_high_jaccard(self) -> None:
        idx = SimilarityIndex(
            [_doc("a.txt", SIMILAR_A), _doc("b.txt", SIMILAR_B)],
            threshold=0.5,
        )
        nb_a = idx.top_neighbors("a.txt")
        assert len(nb_a) == 1
        assert nb_a[0].doc_id == "b.txt"
        assert nb_a[0].jaccard > 0.6

    def test_distinct_docs_have_no_neighbours(self) -> None:
        idx = SimilarityIndex(
            [_doc("a.txt", SIMILAR_A), _doc("c.txt", DISTINCT)],
            threshold=0.5,
        )
        assert idx.top_neighbors("a.txt") == []
        assert idx.top_neighbors("c.txt") == []

    def test_top_neighbors_sorted_by_jaccard_descending(self) -> None:
        # Two near-copies of A plus one edited-more variant — verify ordering.
        very_similar = SIMILAR_A  # identical to a
        somewhat_similar = SIMILAR_B  # small edit
        idx = SimilarityIndex(
            [
                _doc("a.txt", SIMILAR_A),
                _doc("very.txt", very_similar),
                _doc("some.txt", somewhat_similar),
            ],
            threshold=0.3,
        )
        nb = idx.top_neighbors("a.txt")
        assert len(nb) == 2
        assert [n.doc_id for n in nb] == ["very.txt", "some.txt"]
        assert nb[0].jaccard >= nb[1].jaccard

    def test_unknown_doc_id_raises(self) -> None:
        idx = SimilarityIndex([_doc("a.txt", SIMILAR_A)], threshold=0.5)
        with pytest.raises(KeyError):
            idx.top_neighbors("does-not-exist.txt")


class TestClusters:
    def test_similar_pair_shares_a_cluster(self) -> None:
        idx = SimilarityIndex(
            [_doc("a.txt", SIMILAR_A), _doc("b.txt", SIMILAR_B), _doc("c.txt", DISTINCT)],
            threshold=0.5,
        )
        clusters = idx.clusters()
        assert clusters["a.txt"] == clusters["b.txt"]
        assert clusters["c.txt"] != clusters["a.txt"]

    def test_transitive_pairs_join_via_union_find(self) -> None:
        # A~=B and B~=C, but A vs C's Jaccard could dip below threshold. Under
        # union-find they should still land in one connected component — that's
        # the "template group" story: everything transitively linked collapses.
        # Construct by tiny per-hop edits.
        a = "alpha beta gamma delta epsilon zeta eta theta " * 5
        b = a.replace("alpha", "alfa", 3)  # small edit
        c = b.replace("beta", "beeta", 3)  # small edit atop b
        idx = SimilarityIndex(
            [_doc("a.txt", a), _doc("b.txt", b), _doc("c.txt", c)],
            threshold=0.5,
        )
        clusters = idx.clusters()
        assert clusters["a.txt"] == clusters["b.txt"] == clusters["c.txt"]

    def test_deterministic_across_builds(self) -> None:
        # Same input twice = same neighbour structure (and jaccard estimates).
        # Bit-identical clusters aren't guaranteed under set-iteration order,
        # but the partition into equivalence classes must match.
        docs = [
            _doc("a.txt", SIMILAR_A),
            _doc("b.txt", SIMILAR_B),
            _doc("c.txt", DISTINCT),
        ]
        idx1 = SimilarityIndex(docs, threshold=0.5)
        idx2 = SimilarityIndex(docs, threshold=0.5)

        def partition(idx: SimilarityIndex) -> set[frozenset[str]]:
            groups: dict[int, set[str]] = {}
            for doc_id, cid in idx.clusters().items():
                groups.setdefault(cid, set()).add(doc_id)
            return {frozenset(g) for g in groups.values()}

        assert partition(idx1) == partition(idx2)
        # Jaccard estimates should also be identical (fixed seed).
        j1 = idx1.top_neighbors("a.txt")[0].jaccard
        j2 = idx2.top_neighbors("a.txt")[0].jaccard
        assert j1 == j2


class TestThreshold:
    def test_higher_threshold_isolates_more_docs(self) -> None:
        # SIMILAR_A vs SIMILAR_B is a small edit; estimated Jaccard is ~0.77.
        # Threshold 0.3 pairs them; threshold 0.9 does not. (Thresholds very
        # close to 1.0 can't be bucketed by LSH at num_perm=128 — see
        # datasketch's _optimal_param; that's an intrinsic LSH property, not a
        # cliff worth testing here.)
        low = SimilarityIndex([_doc("a.txt", SIMILAR_A), _doc("b.txt", SIMILAR_B)], threshold=0.3)
        high = SimilarityIndex([_doc("a.txt", SIMILAR_A), _doc("b.txt", SIMILAR_B)], threshold=0.9)
        assert low.top_neighbors("a.txt")  # some neighbour above 0.3
        assert not high.top_neighbors("a.txt")  # nothing above 0.9
