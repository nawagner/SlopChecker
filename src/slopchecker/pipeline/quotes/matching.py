"""#10 matching engine: does a quoted passage appear in the source text?

Port of pat-helper's quotecheck (github.com/danparshall/pat-helper,
``pat_helper/quotecheck.py``): unicode/whitespace normalization with an
offset map back into the original text, exact substring match first, then
a fuzzy fallback (difflib ratio over anchored candidate windows, 0.85
threshold). Extended here with ellipsis-spanning quotes — fragments are
matched left-to-right in source order — and ``[sic]`` / short editorial
bracket handling. Zero API cost, fully offline.

Status semantics (the load-bearing rule from #10): ``source_unavailable``
is produced by the *check* layer when there is no source text at all
(``check.py``); ``match_quote`` itself only ever answers
``found_verbatim`` / ``found_minor_variation`` / ``not_found``. An
uncheckable quote must never look like a quote that passed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import StrEnum

from slopchecker.models import Span

FUZZY_THRESHOLD = 0.85

# Single-char replacements applied during normalization
_CHAR_MAP = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "«": '"',
    "»": '"',
    "–": "-",  # en dash
    "—": "-",  # em dash
    "−": "-",  # minus sign
}
# Multi-char sequences, longest first
_SEQ_MAP = [("---", "-"), ("--", "-"), ("``", '"'), ("''", '"')]

_SIC_RE = re.compile(r"\s*[\[(]\s*sic\.?\s*[\])]", re.IGNORECASE)
# "[T]he" -> "The": short editorial capitalization/case brackets
_EDIT_BRACKET_RE = re.compile(r"\[([A-Za-z]{1,3})\]")
_ELLIPSIS_RE = re.compile(r"\s*(?:\[\s*(?:\.\.\.|…)\s*\]|\.\.\.|…|\.\s+\.\s+\.)\s*")


class QuoteStatus(StrEnum):
    found_verbatim = "found_verbatim"
    found_minor_variation = "found_minor_variation"
    not_found = "not_found"
    source_unavailable = "source_unavailable"


@dataclass
class FragmentMatch:
    """One ellipsis-delimited fragment of the quote, matched (or not)."""

    text: str
    found: bool
    score: float
    span: Span | None  # offsets into the original source text


@dataclass
class QuoteMatch:
    """Outcome of matching one quote against one source text.

    ``window`` is the source text between the first and last matched
    fragment — the only source excerpt callers may put in a report
    (retrieved full text is cached, never redistributed).
    """

    status: QuoteStatus
    score: float
    span: Span | None
    window: str | None
    fragments: list[FragmentMatch] = field(default_factory=list)


def split_fragments(quote: str) -> list[str]:
    """Split a quote on ellipses; strip [sic] and short editorial brackets."""
    q = _SIC_RE.sub("", quote)
    parts = [p for p in _ELLIPSIS_RE.split(q) if p.strip()]
    return [_EDIT_BRACKET_RE.sub(r"\1", p) for p in parts]


def _normalize(s: str) -> tuple[str, list[int]]:
    """Normalize text; return (normalized, map from normalized index -> original offset)."""
    out: list[str] = []
    offsets: list[int] = []
    i = 0
    n = len(s)
    while i < n:
        matched_seq = False
        for seq, repl in _SEQ_MAP:
            if s.startswith(seq, i):
                for ch in repl:
                    out.append(ch)
                    offsets.append(i)
                i += len(seq)
                matched_seq = True
                break
        if matched_seq:
            continue
        ch = _CHAR_MAP.get(s[i], s[i])
        if ch.isspace():
            # collapse whitespace runs to a single space
            if out and out[-1] != " ":
                out.append(" ")
                offsets.append(i)
        else:
            out.append(ch.casefold())
            offsets.append(i)
        i += 1
    # trim leading/trailing space
    if out and out[0] == " ":
        out.pop(0)
        offsets.pop(0)
    if out and out[-1] == " ":
        out.pop()
        offsets.pop()
    return "".join(out), offsets


def _fuzzy_best(nq: str, nt: str, offset: int = 0) -> tuple[float, int]:
    """Best (ratio, start) of nq against windows of nt[offset:], anchored on
    a distinctive word. Returned start is an index into the full nt."""
    hay = nt[offset:]
    words = sorted(nq.split(), key=len, reverse=True)
    candidates: set[int] = set()
    for w in words[:3]:
        w_pos_in_quote = nq.find(w)
        start = 0
        while (idx := hay.find(w, start)) != -1:
            # align the window so the anchor word lines up with its position in the quote
            candidates.add(max(0, idx - w_pos_in_quote))
            start = idx + 1
        if candidates:
            break
    if not candidates:
        # coarse scan fallback
        step = max(1, len(nq) // 4)
        candidates = set(range(0, max(1, len(hay) - len(nq) + 1), step))
    best_score, best_start = 0.0, 0
    wlen = len(nq) + 10
    for anchor_start in candidates:
        for start in {anchor_start, max(0, anchor_start - 5), anchor_start + 5}:
            window = hay[start : start + wlen]
            sm = SequenceMatcher(None, nq, window, autojunk=False)
            if sm.real_quick_ratio() < best_score or sm.quick_ratio() < best_score:
                continue
            r = sm.ratio()
            if r > best_score:
                best_score, best_start = r, start
    return best_score, best_start + offset


def _orig_span(tmap: list[int], idx: int, length: int, source_len: int) -> Span:
    start = tmap[idx]
    last = tmap[min(idx + max(length, 1) - 1, len(tmap) - 1)]
    return Span(start=start, end=min(last + 1, source_len))


def match_quote(quote: str, source_text: str, threshold: float = FUZZY_THRESHOLD) -> QuoteMatch:
    """Match a quote (possibly ellipsis-spanning) against source text.

    Fragments must appear in order; each is matched exactly first, then
    fuzzily. Overall score is the weakest fragment's score.
    """
    nt, tmap = _normalize(source_text)
    fragments: list[FragmentMatch] = []
    cursor = 0
    for frag in split_fragments(quote):
        nq, _ = _normalize(frag)
        if not nq:
            continue
        idx = nt.find(nq, cursor)
        if idx != -1:
            fragments.append(
                FragmentMatch(frag, True, 1.0, _orig_span(tmap, idx, len(nq), len(source_text)))
            )
            cursor = idx + len(nq)
            continue
        score, start = _fuzzy_best(nq, nt, cursor)
        if score >= threshold:
            fragments.append(
                FragmentMatch(frag, True, score, _orig_span(tmap, start, len(nq), len(source_text)))
            )
            cursor = start + len(nq)
        else:
            fragments.append(FragmentMatch(frag, False, score, None))

    if not fragments:
        return QuoteMatch(QuoteStatus.not_found, 0.0, None, None, [])
    score = min(f.score for f in fragments)
    if not all(f.found for f in fragments):
        return QuoteMatch(QuoteStatus.not_found, score, None, None, fragments)
    span = Span(start=fragments[0].span.start, end=fragments[-1].span.end)  # type: ignore[union-attr]
    window = source_text[span.start : span.end]
    status = QuoteStatus.found_verbatim if score >= 1.0 else QuoteStatus.found_minor_variation
    return QuoteMatch(status, score, span, window, fragments)
