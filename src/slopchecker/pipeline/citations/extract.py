"""extract_citations: the #7 entry point — parse, link, surface defects.

Operates on plain flattened text (ingestion, #4, wires in later). Unlinked
in-text citations come back as report-ready ``Finding`` objects: a marker
that points at no reference entry is a real defect worth surfacing.
"""

from __future__ import annotations

from slopchecker.models import Anchor, CheckResult, Finding, Span
from slopchecker.pipeline.citations.intext import find_intext_citations
from slopchecker.pipeline.citations.models import (
    Citation,
    CitationExtraction,
    InTextCitation,
    ReferenceEntry,
)
from slopchecker.pipeline.citations.references import (
    find_reference_region,
    first_surname,
    parse_references,
)


def extract_citations(text: str, ref_region: Span | None = None) -> CitationExtraction:
    """Parse references + in-text markers from flattened text and link them.

    ``ref_region`` overrides heading detection when the caller (ingest)
    already knows where the bibliography lives. No reference section at all
    degrades to "every mention is unlinked" — a gap, not a crash.
    """
    region = ref_region if ref_region is not None else find_reference_region(text)
    references = parse_references(text, region) if region is not None else []
    mentions = find_intext_citations(text, exclude=region)
    citations = _link(mentions, references)
    findings = _unlinked_findings(citations, text)
    return CitationExtraction(
        ref_region=region,
        references=references,
        mentions=mentions,
        citations=citations,
        findings=findings,
    )


def _link(mentions: list[InTextCitation], references: list[ReferenceEntry]) -> list[Citation]:
    by_number = {int(r.key): r for r in references if r.key.isdigit()}
    citations: list[Citation] = []
    for m in mentions:
        if m.style == "numeric":
            for n in m.numbers:
                citations.append(Citation(mention=m, reference=by_number.get(n), number=n))
        else:
            citations.append(Citation(mention=m, reference=_match_author_year(m, references)))
    return citations


def _match_author_year(
    mention: InTextCitation, references: list[ReferenceEntry]
) -> ReferenceEntry | None:
    if mention.surname is None or mention.year is None:
        return None
    candidates = [
        r
        for r in references
        if r.year == mention.year
        and (first_surname(r) or "").casefold() == mention.surname.casefold()
    ]
    if mention.year_suffix:
        exact = [r for r in candidates if r.year_suffix == mention.year_suffix]
        return exact[0] if exact else None
    no_suffix = [r for r in candidates if not r.year_suffix]
    if no_suffix:
        return no_suffix[0]
    return candidates[0] if len(candidates) == 1 else None


def _unlinked_findings(citations: list[Citation], text: str) -> list[Finding]:
    findings: list[Finding] = []
    for c in citations:
        if c.reference is not None:
            continue
        m = c.mention
        target = f"[{c.number}]" if c.number is not None else m.marker
        evidence: dict = {"marker": m.marker, "style": m.style}
        if c.number is not None:
            evidence["number"] = c.number
        if m.surname:
            evidence["surname"] = m.surname
        if m.year:
            evidence["year"] = m.year
        findings.append(
            Finding(
                id=f"CIT{len(findings) + 1}",
                target=target,
                label="Unlinked in-text citation",
                anchor=Anchor(quote=text[m.claim_span.start : m.claim_span.end], span=m.claim_span),
                checks=[CheckResult(name="citation_has_reference", result=False)],
                evidence=evidence,
                note="In-text citation has no matching entry in the reference list.",
            )
        )
    return findings
