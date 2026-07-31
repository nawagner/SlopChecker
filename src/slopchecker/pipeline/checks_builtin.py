"""Built-in trivial checks (#5): the registry's proof of life.

These exist so a fresh checkout produces a real (if thin) evidence report
with zero keys and zero network. Real deterministic checks (DOI resolution,
metadata, dedup) are Nick's, in ``slopchecker.checks`` (#8+), registered
against the same decorator.
"""

from __future__ import annotations

from slopchecker.models import FlattenedDoc, LedgerRow
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register


@register(
    id="has_text",
    name="Document has extractable text",
    tier="deterministic",
    timeout_s=5.0,
)
def has_text(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    """False for an empty/whitespace-only text layer — the classic scanned-PDF gap."""
    ok = bool(doc.text.strip())
    return CheckOutput(
        ledger=[
            LedgerRow(
                check="has_text",
                label="Document has extractable text",
                result=ok,
                detail=None if ok else "no text layer — most checks have nothing to read",
            )
        ]
    )


@register(
    id="word_count",
    name="Word count",
    tier="deterministic",
    timeout_s=5.0,
)
def word_count(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    """A number in the score lane, not a pass/fail — length is context, not a verdict."""
    n = len(doc.text.split())
    return CheckOutput(
        ledger=[LedgerRow(check="word_count", label="Word count", result=n, detail="words")]
    )
