"""#10 check layer: quoted passages -> citations -> source match -> Findings.

The status discipline that matters: a quote whose source text can't be
retrieved is a ``skipped`` check with a reason (``source_unavailable`` in
the evidence), never a pass and never a bare fail. In report.json terms
that's ``CheckResult(status="skipped")`` — first-class, per the #3 contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from slopchecker.models import Anchor, CheckResult, Finding, Span
from slopchecker.pipeline.citations.models import Citation, CitationExtraction
from slopchecker.pipeline.quotes.fetch import SourceFetcher
from slopchecker.pipeline.quotes.matching import FUZZY_THRESHOLD, QuoteStatus, match_quote

# How far (chars) a citation marker may sit from a quote and still claim it.
_LINK_WINDOW = 300
_MIN_QUOTE_CHARS = 15
_MAX_WINDOW_IN_REPORT = 500

_QUOTED_RE = re.compile(
    rf"“(?P<curly>[^“”]{{{_MIN_QUOTE_CHARS},600}}?)”"
    rf"|\"(?P<straight>[^\"]{{{_MIN_QUOTE_CHARS},600}}?)\""
)


@dataclass
class QuotedPassage:
    """A quoted span in the submission (span covers the inner text only)."""

    text: str
    span: Span


def find_quoted_passages(text: str, limit: int | None = None) -> list[QuotedPassage]:
    """Double-quoted passages of at least _MIN_QUOTE_CHARS chars."""
    scan_end = limit if limit is not None else len(text)
    passages = []
    for m in _QUOTED_RE.finditer(text, 0, scan_end):
        group = "curly" if m.group("curly") is not None else "straight"
        if "\n\n" in m.group(group):  # crossed a paragraph break: unbalanced quote marks
            continue
        passages.append(
            QuotedPassage(text=m.group(group), span=Span(start=m.start(group), end=m.end(group)))
        )
    return passages


def nearest_citation(passage: QuotedPassage, citations: list[Citation]) -> Citation | None:
    """The citation whose marker sits closest to the quote (within the window)."""
    best: tuple[int, Citation] | None = None
    for c in citations:
        s = c.mention.span
        gap = max(s.start - passage.span.end, passage.span.start - s.end, 0)
        if gap <= _LINK_WINDOW and (best is None or gap < best[0]):
            best = (gap, c)
    return best[1] if best else None


def check_quotes(
    text: str,
    extraction: CitationExtraction,
    fetcher: SourceFetcher | None = None,
    threshold: float = FUZZY_THRESHOLD,
) -> list[Finding]:
    """One Finding per quoted passage in the submission.

    Findings are evidence, not verdicts: ``quote_in_source`` is a bool,
    ``quote_match_score`` a number in its own lane, and unavailable source
    text is a skipped check with a reason.
    """
    scan_end = extraction.ref_region.start if extraction.ref_region else None
    findings: list[Finding] = []
    for i, passage in enumerate(find_quoted_passages(text, limit=scan_end), start=1):
        citation = nearest_citation(passage, extraction.citations)
        anchor = Anchor(quote=passage.text, span=passage.span)
        evidence: dict = {"quote": passage.text}
        checks: list[CheckResult]
        note: str

        if citation is None or citation.reference is None:
            evidence["quote_status"] = str(QuoteStatus.source_unavailable)
            reason = (
                "no citation near the quote"
                if citation is None
                else f"citation '{citation.mention.marker}' has no reference entry"
            )
            checks = [CheckResult(name="quote_in_source", status="skipped", reason=reason)]
            note = "Quote could not be checked: no linked source."
        else:
            ref = citation.reference
            evidence["source_ref"] = ref.key
            source = fetcher.fetch(ref) if fetcher is not None else None
            if source is None:
                evidence["quote_status"] = str(QuoteStatus.source_unavailable)
                checks = [
                    CheckResult(
                        name="quote_in_source",
                        status="skipped",
                        reason=f"source text unavailable for reference '{ref.key}'",
                    )
                ]
                note = "Quote could not be checked: source text unavailable."
            else:
                match = match_quote(passage.text, source, threshold=threshold)
                evidence["quote_status"] = str(match.status)
                checks = [
                    CheckResult(
                        name="quote_in_source",
                        result=match.status
                        in (QuoteStatus.found_verbatim, QuoteStatus.found_minor_variation),
                    ),
                    CheckResult(name="quote_match_score", result=round(match.score, 3)),
                ]
                if match.window is not None:
                    evidence["matched_window"] = match.window[:_MAX_WINDOW_IN_REPORT]
                if match.status is QuoteStatus.found_verbatim:
                    note = "Quote found verbatim in source."
                elif match.status is QuoteStatus.found_minor_variation:
                    note = "Quote found in source with minor variation."
                else:
                    note = "Quote not found in retrieved source text."

        findings.append(
            Finding(
                id=f"Q{i}",
                target=evidence.get("source_ref"),
                label="Quotation check",
                anchor=anchor,
                checks=checks,
                evidence=evidence,
                note=note,
            )
        )
    return findings
