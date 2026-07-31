"""Tests for the registered ``similar_documents`` check (#14)."""

from __future__ import annotations

from slopchecker.models import FlattenedDoc
from slopchecker.pipeline import CheckContext, all_checks, build_context, discover, run_checks

discover()  # ensure the check is registered

SIMILAR_A = (
    "The quick brown fox jumps over the lazy dog. "
    "Now is the time for all good citizens to come to the aid of their country. "
    "In the beginning God created the heaven and the earth. "
    "Four score and seven years ago our fathers brought forth on this continent a new nation. "
    "We hold these truths to be self-evident that all men are created equal."
)
SIMILAR_B = (
    "The quick brown fox jumps over the lazy dog. "
    "Now is the time for all good citizens to come to the aid of their country. "
    "In the beginning God created heaven and the earth. "  # dropped one "the"
    "Four score and seven years ago our fathers brought forth on this continent a new nation. "
    "We hold these truths to be self-evident that all men are created equal."
)
SIMILAR_C = (
    "The quick brown fox jumps over the lazy dog. "
    "Now is the time for all good citizens to come to the aid of their country. "
    "In the beginning God created heaven, and the earth. "  # different variation
    "Four score and seven years ago our fathers brought forth on this continent a nation. "
    "We hold these truths to be self-evident that all men are created equal."
)
DISTINCT = (
    "Photosynthesis converts sunlight into chemical energy in plants. "
    "The Krebs cycle is a series of chemical reactions used by all aerobic organisms. "
    "Mitochondria are the powerhouses of the cell. "
    "DNA replication requires helicase to unwind the double helix. "
    "Ribosomes assemble proteins from amino acids according to mRNA templates."
)


def _run_similarity(doc: FlattenedDoc, ctx: CheckContext) -> dict[str, list]:
    """Isolate the similar_documents check and return its ledger + findings."""
    checks = [rc for rc in all_checks() if rc.meta.id == "similar_documents"]
    assert checks, "similar_documents check is not registered"
    report = run_checks(doc, checks, context=ctx)
    return {
        "ledger": [
            row for row in report.ledger if row.check in {"similar_documents", "template_cluster"}
        ],
        "findings": report.findings,
    }


class TestSingleDocRun:
    def test_no_batch_emits_skipped(self) -> None:
        # A CheckContext with no batch (or a batch of one) means we can't do
        # any cross-doc comparison. The check emits a `skipped` ledger row with
        # a clear reason rather than pretending to succeed.
        doc = FlattenedDoc(file="a.txt", text=SIMILAR_A)
        ctx = build_context([doc])
        result = _run_similarity(doc, ctx)
        assert len(result["ledger"]) == 1
        row = result["ledger"][0]
        assert row.check == "similar_documents"
        assert row.status == "skipped"
        assert row.reason and "batch" in row.reason.lower()

    def test_missing_batch_context_emits_skipped(self) -> None:
        # A bare CheckContext (no batch, e.g. from web/single-file callers who
        # haven't switched to build_context) should also cleanly skip.
        doc = FlattenedDoc(file="a.txt", text=SIMILAR_A)
        result = _run_similarity(doc, CheckContext())
        assert len(result["ledger"]) == 1
        assert result["ledger"][0].status == "skipped"


class TestBatchWithoutMatches:
    def test_zero_matches_when_docs_are_distinct(self) -> None:
        docs = [
            FlattenedDoc(file="a.txt", text=SIMILAR_A),
            FlattenedDoc(file="c.txt", text=DISTINCT),
        ]
        ctx = build_context(docs)
        result = _run_similarity(docs[0], ctx)
        # similar_documents present with result=0; no template_cluster (singleton).
        matches = [r for r in result["ledger"] if r.check == "similar_documents"]
        assert len(matches) == 1
        assert matches[0].result == 0
        # No findings from this check when there are no matches.
        assert result["findings"] == []
        # No template_cluster row for a lone doc.
        clusters = [r for r in result["ledger"] if r.check == "template_cluster"]
        assert clusters == []


class TestBatchWithMatches:
    def test_matches_emit_ledger_count_and_findings(self) -> None:
        docs = [
            FlattenedDoc(file="a.txt", text=SIMILAR_A),
            FlattenedDoc(file="b.txt", text=SIMILAR_B),
            FlattenedDoc(file="c.txt", text=DISTINCT),
        ]
        ctx = build_context(docs)
        result = _run_similarity(docs[0], ctx)
        matches = [r for r in result["ledger"] if r.check == "similar_documents"]
        assert len(matches) == 1
        assert matches[0].result == 1  # a matches b
        assert len(result["findings"]) == 1

    def test_finding_quote_is_verbatim_in_source(self) -> None:
        docs = [
            FlattenedDoc(file="a.txt", text=SIMILAR_A),
            FlattenedDoc(file="b.txt", text=SIMILAR_B),
        ]
        ctx = build_context(docs)
        result = _run_similarity(docs[0], ctx)
        f = result["findings"][0]
        assert f.anchor is not None
        # Ground rule: quote must be mechanically grounded in FlattenedDoc.text.
        assert f.anchor.quote in SIMILAR_A
        assert f.anchor.span is not None
        assert SIMILAR_A[f.anchor.span.start : f.anchor.span.end] == f.anchor.quote

    def test_finding_evidence_carries_counterparty_and_jaccard(self) -> None:
        docs = [
            FlattenedDoc(file="a.txt", text=SIMILAR_A),
            FlattenedDoc(file="b.txt", text=SIMILAR_B),
        ]
        ctx = build_context(docs)
        result = _run_similarity(docs[0], ctx)
        f = result["findings"][0]
        assert f.evidence.get("matched_document_id") == "b.txt"
        j = f.evidence.get("jaccard")
        assert isinstance(j, float) and 0.5 < j <= 1.0


class TestCluster:
    def test_three_doc_cluster_emits_template_cluster_row(self) -> None:
        # A ≈ B ≈ C should form one cluster of 3 (any two above threshold).
        docs = [
            FlattenedDoc(file="a.txt", text=SIMILAR_A),
            FlattenedDoc(file="b.txt", text=SIMILAR_B),
            FlattenedDoc(file="c.txt", text=SIMILAR_C),
            FlattenedDoc(file="d.txt", text=DISTINCT),
        ]
        ctx = build_context(docs)
        # a should see 2 matches (b, c) and belong to a multi-doc cluster.
        result_a = _run_similarity(docs[0], ctx)
        matches = [r for r in result_a["ledger"] if r.check == "similar_documents"]
        assert matches[0].result >= 1
        clusters = [r for r in result_a["ledger"] if r.check == "template_cluster"]
        assert len(clusters) == 1  # a is in a multi-doc cluster
        # d (distinct) should not get a template_cluster row.
        result_d = _run_similarity(docs[3], ctx)
        clusters_d = [r for r in result_d["ledger"] if r.check == "template_cluster"]
        assert clusters_d == []
