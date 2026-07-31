"""In-text citation markers + claim-sentence capture (#7).

Handles ``(Smith, 2021)`` / ``(Whitfield 2020)`` / ``(Smith, 2021; Vance,
2019)`` parentheticals, narrative ``Smith (2021)``, and numbered ``[14]`` /
``[3, 4]`` markers. Footnote-style superscript markers don't survive text
flattening reliably and are out of scope for the regex pass (noted on #7).
"""

from __future__ import annotations

import re

from slopchecker.models import Span
from slopchecker.pipeline.citations.models import InTextCitation

_NUMERIC_RE = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
_PAREN_RE = re.compile(r"\(([^()]{1,200})\)")
_SEG_PREFIX_RE = re.compile(r"^(?:see also|see|e\.g\.?,?|cf\.?,?|i\.e\.?,?)\s+", re.IGNORECASE)
_NAME = r"[A-Z][\w'’-]+"
_AUTHOR_YEAR_SEG_RE = re.compile(
    rf"^(?P<authors>{_NAME}(?:\s+et al\.?|(?:,?\s+(?:and|&)\s+{_NAME})*)?)"
    r",?\s+(?P<year>(?:1[89]|20)\d{2})(?P<suffix>[a-z])?"
    r"(?:,\s*pp?\.\s*[\d\s,–—-]+)?$"
)
_NARRATIVE_RE = re.compile(
    rf"\b(?P<authors>{_NAME}(?:\s+et al\.?|\s+(?:and|&)\s+{_NAME})?)"
    r"\s*\((?P<year>(?:1[89]|20)\d{2})(?P<suffix>[a-z])?"
    r"(?:,\s*pp?\.\s*[\d\s,–—-]+)?\)"
)

_ABBREVS = {"al", "e.g", "i.e", "cf", "vs", "fig", "no", "pp", "p", "dr", "mr", "ms", "prof"}
_BOUNDARY_RE = re.compile(r"(?P<punct>[.!?]+[)\"”']*)\s+")
_PARA_BREAK_RE = re.compile(r"\n[ \t\r]*\n")  # CRLF-tolerant blank line (#98)


def sentence_bounds(text: str, start: int, end: int) -> Span:
    """The sentence containing [start, end), clamped to its paragraph.

    Abbreviation-aware ("et al.", "e.g.", single initials) so claim
    sentences don't get chopped at a fake boundary.
    """
    para_start = 0
    for pb in _PARA_BREAK_RE.finditer(text, 0, start):
        para_start = pb.end()
    next_break = _PARA_BREAK_RE.search(text, end)
    para_end = len(text) if next_break is None else next_break.start()

    sent_start, sent_end = para_start, para_end
    for m in _BOUNDARY_RE.finditer(text, para_start, para_end):
        wm = re.search(r"([\w.]+)$", text[para_start : m.start()])
        token = wm.group(1).casefold().rstrip(".") if wm else ""
        if token in _ABBREVS or len(token) == 1:
            continue
        boundary_next = m.end()  # first char of the following sentence
        punct_end = m.start() + len(m.group("punct"))
        if boundary_next <= start:
            sent_start = boundary_next
        elif m.start() >= end and punct_end < sent_end:
            sent_end = punct_end
            break
    while sent_start < sent_end and text[sent_start].isspace():
        sent_start += 1
    while sent_end > sent_start and text[sent_end - 1].isspace():
        sent_end -= 1
    return Span(start=sent_start, end=sent_end)


def _with_claim(text: str, **kwargs) -> InTextCitation:
    span: Span = kwargs["span"]
    claim = sentence_bounds(text, span.start, span.end)
    return InTextCitation(claim_text=text[claim.start : claim.end], claim_span=claim, **kwargs)


def find_intext_citations(text: str, exclude: Span | None = None) -> list[InTextCitation]:
    """All in-text citation markers outside ``exclude`` (the ref region)."""
    scan_end = exclude.start if exclude else len(text)
    mentions: list[InTextCitation] = []
    claimed_parens: set[int] = set()  # offsets of "(" consumed by narrative markers

    for m in _NUMERIC_RE.finditer(text, 0, scan_end):
        numbers = [int(n) for n in re.split(r"\s*,\s*", m.group(1))]
        mentions.append(
            _with_claim(
                text,
                marker=m.group(0),
                span=Span(start=m.start(), end=m.end()),
                style="numeric",
                numbers=numbers,
            )
        )

    for m in _NARRATIVE_RE.finditer(text, 0, scan_end):
        claimed_parens.add(text.index("(", m.start("authors"), m.end()))
        mentions.append(
            _with_claim(
                text,
                marker=m.group(0),
                span=Span(start=m.start(), end=m.end()),
                style="narrative",
                surname=re.match(_NAME, m.group("authors")).group(0),  # type: ignore[union-attr]
                year=int(m.group("year")),
                year_suffix=m.group("suffix"),
            )
        )

    for pm in _PAREN_RE.finditer(text, 0, scan_end):
        if pm.start() in claimed_parens:
            continue
        content, base = pm.group(1), pm.start(1)
        pos = 0
        for seg in content.split(";"):
            seg_start, seg_text = pos, seg
            pos += len(seg) + 1
            stripped = seg_text.strip()
            if not stripped:
                continue
            lead = len(seg_text) - len(seg_text.lstrip())
            prefix = _SEG_PREFIX_RE.match(stripped)
            if prefix:
                lead += prefix.end()
                stripped = stripped[prefix.end() :]
            sm = _AUTHOR_YEAR_SEG_RE.match(stripped.rstrip())
            if not sm:
                continue
            start = base + seg_start + lead
            mentions.append(
                _with_claim(
                    text,
                    marker=sm.group(0),
                    span=Span(start=start, end=start + len(sm.group(0))),
                    style="author_year",
                    surname=re.match(_NAME, sm.group("authors")).group(0),  # type: ignore[union-attr]
                    year=int(sm.group("year")),
                    year_suffix=sm.group("suffix"),
                )
            )

    mentions.sort(key=lambda c: (c.span.start, c.span.end))
    return mentions
