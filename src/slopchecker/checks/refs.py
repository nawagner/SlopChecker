"""Shared plumbing for the deterministic checks. Registers nothing.

Every check in this package starts from the same place — the reference list
parsed by #7 — so parsing happens once per document text and is reused across
the four checks the runner fires in parallel.

Also home to the anchoring rule: a finding about a reference is anchored to
the reference entry as it appears in the document. That keeps every finding
quote-anchored (CLAUDE.md) with a quote that is by construction a verbatim
slice of ``FlattenedDoc.text``.
"""

from __future__ import annotations

from functools import lru_cache

from slopchecker.checks.identifiers import Identifier, identifiers_in
from slopchecker.models import Anchor, FlattenedDoc, LedgerRow, Span
from slopchecker.pipeline.citations import CitationExtraction, ReferenceEntry, extract_citations

# Small: a batch run holds one document at a time, and the entries are the
# parse of a text we already have in memory.
_CACHE_SIZE = 4


@lru_cache(maxsize=_CACHE_SIZE)
def _extract(text: str) -> CitationExtraction:
    return extract_citations(text)


def extraction_for(doc: FlattenedDoc) -> CitationExtraction:
    """Citation extraction (#7) for this document, parsed at most once."""
    return _extract(doc.text)


def references_for(doc: FlattenedDoc) -> list[ReferenceEntry]:
    """Parsed reference entries, empty when the document has no reference list."""
    return list(extraction_for(doc).references)


def identifiers_for(doc: FlattenedDoc) -> list[tuple[ReferenceEntry, list[Identifier]]]:
    """Each reference entry paired with the identifiers found on it."""
    return [(ref, identifiers_in(ref)) for ref in references_for(doc)]


def anchor_for(doc: FlattenedDoc, ref: ReferenceEntry) -> Anchor:
    """Anchor a finding to the reference entry, on its page when known.

    Stripping has to move ``span.start`` with it. Trimming the quote while
    leaving the offset put kept the leading whitespace inside the span and
    chopped an equal number of real characters off the end — so on any
    hanging-indent bibliography (routine, and exactly what the numbered-entry
    parser captures) ``text[span] != quote`` and the anchor pointed at a
    window that merely overlapped the reference.
    """
    raw = doc.text[ref.span.start : ref.span.end]
    lead = len(raw) - len(raw.lstrip())
    quote = raw.strip()
    start = ref.span.start + lead
    span = Span(start=start, end=start + len(quote))
    return Anchor(page=page_of(doc, start), quote=quote, span=span)


def page_of(doc: FlattenedDoc, offset: int) -> int | None:
    """1-based page containing ``offset``, when the loader tracked pages (#4)."""
    offsets = doc.page_offsets
    if not offsets:
        return None
    page = 0
    for index, start in enumerate(offsets):
        if start <= offset:
            page = index
        else:
            break
    return page + 1


def no_references_row(check_id: str, label: str) -> LedgerRow:
    """The gap row for a document whose reference list we couldn't parse.

    "Degrade to gaps, never crash": a proposal with no bibliography section
    is a document we could not check, which is a different report row from a
    document whose citations all check out.
    """
    return LedgerRow(
        check=check_id,
        label=label,
        status="skipped",
        reason="no reference list found in the document",
    )


def nothing_to_check_row(check_id: str, label: str, what: str) -> LedgerRow:
    """The gap row for "references parsed, but none carry a ``what``"."""
    return LedgerRow(
        check=check_id, label=label, status="skipped", reason=f"no {what} in the reference list"
    )
