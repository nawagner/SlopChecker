"""Citation-linkage check (#7): wires ``extract_citations`` into the registry.

Document-internal tier only — no network, no source retrieval. This checks
that every in-text marker resolves to a reference-list entry; it says
nothing about whether the cited source actually supports the claim (that's
quote-vs-source, #10, which stays unregistered until source retrieval
exists).
"""

from __future__ import annotations

from slopchecker.models import FlattenedDoc, LedgerRow
from slopchecker.pipeline.citations import extract_citations
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register

_MAX_LISTED_UNLINKED = 5


@register(
    id="citations_linked",
    name="In-text citations link to references",
    tier="deterministic",
)
def citations_linked(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    ext = extract_citations(doc.text)
    total = len(ext.citations)
    unlinked = [c for c in ext.citations if c.reference is None]
    linked = total - len(unlinked)

    if total == 0:
        detail = "no in-text citations found"
    elif not unlinked:
        detail = f"{total} / {total} markers linked, {len(ext.references)} references"
    else:
        targets = [f"[{c.number}]" if c.number is not None else c.mention.marker for c in unlinked]
        shown = targets[:_MAX_LISTED_UNLINKED]
        if len(targets) > _MAX_LISTED_UNLINKED:
            shown.append("...")
        detail = f"{linked} / {total} markers linked; unlinked: " + ", ".join(shown)

    return CheckOutput(
        ledger=[
            LedgerRow(
                check="citations_linked",
                label="In-text citations link to references",
                result=len(unlinked) == 0,
                detail=detail,
            )
        ],
        findings=ext.findings,
    )
