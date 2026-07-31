"""Tests for CheckContext's batch + similarity_index extension (#14)."""

from __future__ import annotations

from slopchecker.models import FlattenedDoc
from slopchecker.pipeline import CheckContext, build_context
from slopchecker.similarity.index import SimilarityIndex


def _doc(name: str, text: str) -> FlattenedDoc:
    return FlattenedDoc(file=name, text=text)


class TestCheckContextDefaults:
    def test_batch_defaults_to_empty(self) -> None:
        ctx = CheckContext()
        assert tuple(ctx.batch) == ()
        assert ctx.similarity_index is None

    def test_existing_kwargs_still_work(self) -> None:
        # Backwards-compat: existing call sites should not break.
        ctx = CheckContext(solicitation="RFP-42")
        assert ctx.solicitation == "RFP-42"
        assert ctx.similarity_index is None


class TestBuildContext:
    def test_batch_of_one_leaves_index_none(self) -> None:
        # Single-doc batch: similarity check will emit a skipped ledger row
        # rather than attempt a self-only index.
        ctx = build_context([_doc("a.txt", "hello world")])
        assert ctx.similarity_index is None
        assert len(ctx.batch) == 1

    def test_batch_of_two_builds_index(self) -> None:
        docs = [
            _doc("a.txt", "hello world one two three"),
            _doc("b.txt", "goodbye world four five six"),
        ]
        ctx = build_context(docs)
        assert isinstance(ctx.similarity_index, SimilarityIndex)
        assert set(ctx.similarity_index.doc_ids()) == {"a.txt", "b.txt"}

    def test_passes_solicitation_through(self) -> None:
        ctx = build_context([_doc("a.txt", "x")], solicitation="RFP-99")
        assert ctx.solicitation == "RFP-99"

    def test_empty_batch_returns_context_with_empty_batch(self) -> None:
        ctx = build_context([])
        assert tuple(ctx.batch) == ()
        assert ctx.similarity_index is None
