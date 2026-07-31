"""Post-ingest planted-defect mutation for the validation harness (#71).

Sibling of `harness/injector.py`: injector.py mutates fixture files *before*
they hit the loader, so it can only exercise formats we author by hand
(markdown). This module mutates `FlattenedDoc.text` *after* the loader
runs, so a defect lands on text that has actually been extracted from a
real PDF/DOCX/HTML fixture. Loader-visible artifacts (dropped whitespace,
mis-ordered columns, footnote handling) are then in the path of the
checks, which is what the harness is supposed to measure.

Contract mirrors injector.inject():

- Each defect: {id, original, mutated, ...}. First occurrence of `original`
  in the current text is replaced by `mutated`. Missing `original` is a
  hard error — a silently unplanted defect would count as MISS forever
  and drag recall for a reason unrelated to check quality.
- `mutated == ""` is deletion.
- Multiple defects apply sequentially against the already-mutated text
  (same order-matters rule as injector.py).

Beyond injector.inject(), this module also shifts:

- `IngestResult.references` (Span)
- `IngestResult.sections` (list[Section] with Spans)
- `FlattenedDoc.page_offsets` (list[int])

so downstream consumers (quotecheck, section lookups, page attribution)
keep seeing the right regions after mutation. A mutation whose `original`
straddles a span boundary is rejected: partial overlap means the mutation
isn't cleanly inside or outside the span, and recall scoring against such
a defect would be meaningless.
"""

from __future__ import annotations

from typing import Any

from slopchecker.ingest.types import IngestResult, Section
from slopchecker.models import FlattenedDoc, Span


def mutate_ingest_result(
    result: IngestResult,
    defects: list[dict[str, Any]],
) -> tuple[IngestResult, list[dict[str, Any]]]:
    """Apply `defects` to `result.document.text`, returning (new_result, manifest).

    Manifest entries carry `id`, `line`, `original`, `mutated`, plus the
    same pass-through fields as `injector.inject`'s manifest (`match`,
    `pending_lens`, `check_expected`, `description`) so recall scoring in
    run.py doesn't care whether a defect came from the pre- or post-ingest
    path.

    Raises ValueError if:
      - `result.status != "ok"` (nothing to mutate)
      - a defect's `original` isn't in the current text
      - a defect straddles a span boundary
    """
    if result.status != "ok" or result.document is None:
        raise ValueError(
            f"mutate_ingest_result: cannot mutate a non-ok IngestResult "
            f"(status={result.status!r}, reason={result.reason!r})"
        )

    text = result.document.text
    references = result.references
    sections = list(result.sections)
    page_offsets = list(result.document.page_offsets) if result.document.page_offsets else None

    manifest: list[dict[str, Any]] = []
    for defect in defects:
        pos = text.find(defect["original"])
        if pos == -1:
            raise ValueError(
                f"defect {defect['id']!r}: original text not found in flattened document"
            )
        end = pos + len(defect["original"])
        line = text.count("\n", 0, pos) + 1

        # Reject partial-overlap defects BEFORE mutating anything, so a
        # failure mid-list doesn't leave a half-mutated document behind.
        for section in sections:
            _reject_partial_overlap(pos, end, section.span, f"section {section.title!r}")
        if references is not None:
            _reject_partial_overlap(pos, end, references, "references")
        if page_offsets is not None:
            for offset in page_offsets:
                _reject_page_offset_inside_mutation(pos, end, offset)

        delta = len(defect["mutated"]) - len(defect["original"])
        text = text[:pos] + defect["mutated"] + text[end:]
        sections = [
            Section(title=s.title, level=s.level, span=_shift_span(s.span, pos, end, delta))
            for s in sections
        ]
        if references is not None:
            references = _shift_span(references, pos, end, delta)
        if page_offsets is not None:
            page_offsets = [_shift_offset(o, pos, end, delta) for o in page_offsets]

        manifest.append(
            {
                "id": defect["id"],
                "file": defect.get("file"),
                "line": line,
                "original": defect["original"],
                "mutated": defect["mutated"],
                "match": defect.get("match", {"kind": "pending"}),
                "pending_lens": defect.get("pending_lens"),
                "check_expected": defect.get("check_expected"),
                "description": defect.get("description"),
            }
        )

    new_doc = FlattenedDoc(
        file=result.document.file,
        text=text,
        sha256=None,  # invalidated by mutation
        pages=result.document.pages,
        page_offsets=page_offsets,
        media_type=result.document.media_type,
        title=result.document.title,
        byline=result.document.byline,
        submitter=result.document.submitter,
    )
    new_result = IngestResult(
        status="ok",
        document=new_doc,
        sections=sections,
        references=references,
    )
    return new_result, manifest


# --- Span/offset shifting ---------------------------------------------------


def _shift_span(span: Span, pos: int, end: int, delta: int) -> Span:
    """Mechanically shift `span` under a mutation at [pos, end) with `delta`.

    Half-open span semantics. Cases (assumes no partial overlap — that
    check runs before mutation, so this is unreachable here):

    - span entirely before mutation (span.end <= pos): no change
    - span entirely after mutation (span.start >= end): shift both by delta
    - mutation entirely inside span (span.start <= pos AND end <= span.end):
      extend span.end by delta; span.start unchanged
    """
    if span.end <= pos:
        return span
    if span.start >= end:
        return Span(start=span.start + delta, end=span.end + delta)
    # mutation is inside the span
    return Span(start=span.start, end=span.end + delta)


def _shift_offset(offset: int, pos: int, end: int, delta: int) -> int:
    """Shift a bare int offset (e.g. `page_offsets` entry) under mutation."""
    if offset <= pos:
        return offset
    # `_reject_page_offset_inside_mutation` guarantees offset >= end here.
    return offset + delta


def _reject_partial_overlap(pos: int, end: int, span: Span, label: str) -> None:
    """Refuse mutations that cross a span boundary: recall on such a defect
    would be meaningless."""
    entirely_before = span.end <= pos
    entirely_after = span.start >= end
    entirely_inside = span.start <= pos and end <= span.end
    if entirely_before or entirely_after or entirely_inside:
        return
    raise ValueError(
        f"defect straddles span boundary ({label}: [{span.start}, {span.end})) — "
        f"mutation region [{pos}, {end}) is partially outside the span; "
        f"either narrow the defect to sit inside the span or replace the span entirely"
    )


def _reject_page_offset_inside_mutation(pos: int, end: int, offset: int) -> None:
    """A page boundary that falls strictly inside the mutation region would
    be destroyed by the mutation. Boundaries exactly at `pos` or `end` are
    fine — they mark the mutation's start/end respectively."""
    if pos < offset < end:
        raise ValueError(
            f"defect straddles span boundary (page offset at {offset}) — "
            f"mutation region [{pos}, {end}) would erase a page boundary"
        )
