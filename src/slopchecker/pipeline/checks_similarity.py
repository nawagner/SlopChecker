"""Corpus similarity check (#14).

Wraps ``slopchecker.similarity.SimilarityIndex`` (built once per batch by
``pipeline.build_context``) into a registered per-doc check that emits:

- ``similar_documents`` (int) — count of docs in the same batch whose Jaccard
  is above threshold with this doc.
- ``template_cluster`` (int) — union-find cluster id, present only when this
  doc is in a multi-doc component. Answers the "surfaces mass-generated
  submissions" acceptance criterion at the ledger level.
- One ``Finding`` per near-neighbour, quote-anchored on a shared passage from
  the current doc (grounded via ``similarity.passages.shared_passage``), with
  the counterparty file, id, and Jaccard estimate in ``evidence``.

Batches of one (or an unpopulated context) → single ``skipped`` ledger row with
a reason. Similarity is a corpus property; a single document has none.

Kept in ``pipeline/`` (Dan-owned) rather than Nick's ``checks/`` package
because the check is a thin wrapper over the batch-aware ``similarity/``
engine — same shape as the ``detect/`` module for Pangram.
"""

from __future__ import annotations

from slopchecker.models import Anchor, Finding, FlattenedDoc, LedgerRow, Span
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register
from slopchecker.similarity.passages import shared_passage

CHECK_ID = "similar_documents"
CLUSTER_CHECK_ID = "template_cluster"
_MAX_FINDINGS_PER_DOC = 5  # top-K near-neighbours to surface; keeps reports readable


@register(
    id=CHECK_ID,
    name="Near-duplicate documents in the same batch",
    tier="deterministic",
    timeout_s=15.0,
)
def similar_documents(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    """Emit near-duplicate matches for ``doc`` against the batch in ``ctx``."""
    index = ctx.similarity_index
    if index is None:
        return CheckOutput(
            ledger=[
                LedgerRow(
                    check=CHECK_ID,
                    label="Near-duplicates in batch",
                    status="skipped",
                    reason="requires a batch of >=2 documents",
                )
            ]
        )

    neighbours = index.top_neighbors(doc.file)
    # Rank has already sorted by Jaccard descending; cap the count of Findings
    # so the report doesn't drown when every doc in a big template cluster
    # links to every other. The ledger count is uncapped so the number is real.
    top = neighbours[:_MAX_FINDINGS_PER_DOC]

    findings: list[Finding] = []
    for i, nb in enumerate(top):
        matched_text = _text_for(ctx, nb.doc_id)
        anchor: Anchor | None = None
        if matched_text is not None:
            passage = shared_passage(doc.text, matched_text)
            if passage is not None:
                anchor = Anchor(
                    quote=passage.quote,
                    span=Span(start=passage.span_start, end=passage.span_end),
                )
        findings.append(
            Finding(
                id=f"similar-{i}",
                label="Near-duplicate document",
                anchor=anchor,
                evidence={
                    "matched_document_id": nb.doc_id,
                    "matched_document_file": nb.doc_id,
                    "jaccard": round(nb.jaccard, 4),
                },
                note=f"shares ~{nb.jaccard:.0%} of shingles with {nb.doc_id}",
            )
        )

    ledger: list[LedgerRow] = [
        LedgerRow(
            check=CHECK_ID,
            label="Near-duplicates in batch",
            result=len(neighbours),
            detail=(
                f"{len(neighbours)} near-duplicate(s) at Jaccard >= {index.threshold:.2f}"
                if neighbours
                else f"no near-duplicates at Jaccard >= {index.threshold:.2f}"
            ),
        )
    ]

    # Cluster row only when this doc is in a multi-doc component: the AC is
    # "surface groups", so a singleton has nothing meaningful to report.
    clusters = index.clusters()
    my_cluster = clusters[doc.file]
    cluster_size = sum(1 for c in clusters.values() if c == my_cluster)
    if cluster_size >= 2:
        ledger.append(
            LedgerRow(
                check=CLUSTER_CHECK_ID,
                label="Template cluster",
                result=my_cluster,
                detail=f"cluster of {cluster_size} documents (batch has {len(clusters)})",
            )
        )

    return CheckOutput(ledger=ledger, findings=findings)


def _text_for(ctx: CheckContext, doc_id: str) -> str | None:
    """Look up a peer's ``FlattenedDoc.text`` from the batch, if present."""
    for peer in ctx.batch:
        if peer.file == doc_id:
            return peer.text
    return None
