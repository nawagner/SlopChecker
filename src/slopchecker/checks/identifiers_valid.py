"""Check: are the citation identifiers structurally well-formed? (#8)

Offline half of #8. No network, no key, no excuses — this one runs on a
laptop in airplane mode, and it is the check that separates "malformed" from
the three network outcomes so the resolution checks never have to guess
whether a failure was the document's fault or ours.
"""

from __future__ import annotations

from slopchecker.checks.identifiers import Identifier, malformed_reason, valid
from slopchecker.checks.refs import (
    anchor_for,
    identifiers_for,
    no_references_row,
    nothing_to_check_row,
    references_for,
)
from slopchecker.models import CheckResult, Finding, FlattenedDoc, LedgerRow
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register

CHECK_ID = "citation_identifiers_valid"
LABEL = "Citation identifiers well-formed"

_KIND_LABEL = {"doi": "DOI", "arxiv": "arXiv id", "isbn": "ISBN", "url": "URL"}


@register(id=CHECK_ID, name=LABEL, tier="deterministic", timeout_s=15.0)
def citation_identifiers_valid(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    """Every DOI, arXiv id, ISBN, and URL in the reference list, pattern-checked."""
    if not references_for(doc):
        return CheckOutput(ledger=[no_references_row(CHECK_ID, LABEL, doc)])

    pairs = identifiers_for(doc)
    total = sum(len(idents) for _, idents in pairs)
    if total == 0:
        return CheckOutput(
            ledger=[nothing_to_check_row(CHECK_ID, LABEL, "DOIs, URLs, ISBNs, or arXiv ids")]
        )

    findings: list[Finding] = []
    for ref, idents in pairs:
        for ident in idents:
            if valid(ident.kind, ident.value):
                continue
            findings.append(_malformed_finding(doc, ref, ident, len(findings) + 1))

    detail = f"{total - len(findings)} / {total} well-formed"
    if findings:
        detail += " — " + _breakdown(findings)
    return CheckOutput(
        ledger=[LedgerRow(check=CHECK_ID, label=LABEL, result=not findings, detail=detail)],
        findings=findings,
    )


def _breakdown(findings: list[Finding]) -> str:
    counts: dict[str, int] = {}
    for finding in findings:
        kind = str(finding.evidence.get("kind", "identifier"))
        counts[kind] = counts.get(kind, 0) + 1
    return ", ".join(f"{n} malformed {_KIND_LABEL.get(k, k)}" for k, n in sorted(counts.items()))


def _malformed_finding(doc: FlattenedDoc, ref, ident: Identifier, n: int) -> Finding:
    reason = malformed_reason(ident.kind, ident.value)
    return Finding(
        id=f"FMT{n}",
        target=ident.target,
        label=f"Malformed {_KIND_LABEL.get(ident.kind, ident.kind)}",
        anchor=anchor_for(doc, ref),
        checks=[CheckResult(name=CHECK_ID, result=False)],
        evidence={"kind": ident.kind, "as_written": ident.raw, "problem": reason},
        note=f"{_KIND_LABEL.get(ident.kind, ident.kind)} as written: {reason}.",
    )
