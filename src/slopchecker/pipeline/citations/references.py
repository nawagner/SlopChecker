"""Reference-section detection and entry parsing (#7).

Regex + heuristics, per the issue notes — good enough for APA, Chicago
(author-date), and numbered/IEEE styles. Parsed fields are best-effort;
``raw``/``span`` are exact. No LLM fallback in this pass.
"""

from __future__ import annotations

import re

from slopchecker.models import Span
from slopchecker.pipeline.citations.models import ReferenceEntry

_HEADING_RE = re.compile(
    r"^[ \t]*(?:\d+\.?\s+)?"
    r"(?:references|bibliography|works cited|reference list|literature cited)"
    # \r is in the trailing class because re.MULTILINE's $ matches before \n
    # but does not consume a preceding \r, so a CRLF heading line never
    # matched and the document read as having no bibliography at all.
    # ingest.normalize() strips CRLF before any loader builds a FlattenedDoc,
    # so this only bites callers passing raw text straight to
    # extract_citations() — but silently returning zero references is a bad
    # way to find that out.
    r"[ \t]*:?[ \t\r]*$",
    re.IGNORECASE | re.MULTILINE,
)

_NUMBERED_START = re.compile(r"^[ \t]*\[(\d{1,3})\][ \t]+", re.MULTILINE)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+")
_ARXIV_RE = re.compile(r"arxiv(?::|\.org/abs/)\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s<>\"]+")
_PAGES_RE = re.compile(r"\bpp?\.\s*(\d+(?:\s*[-–—]\s*\d+)?)")
_COLON_PAGES_RE = re.compile(r":\s*(\d+\s*[-–—]\s*\d+)")
# APA journal shape: "..., 14(2), 101-129."
_APA_PAGES_RE = re.compile(r",\s*(\d+\s*[-–—]\s*\d+)\s*[.,]")
_PAREN_YEAR_RE = re.compile(r"\((1[89]\d{2}|20\d{2})([a-z])?\)")
_BARE_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})([a-z])?\b")
_QUOTED_TITLE_RE = re.compile(r"[\"“]([^\"”]{4,}?)[\"”]")
_CHICAGO_RE = re.compile(
    r"^(?P<auth>[^.]+?)\.\s+(?P<year>(?:1[89]|20)\d{2})(?P<suffix>[a-z])?\.\s*"
)
# "Surname, I. I." (APA) and "I. I. Surname" (IEEE) author shapes
_APA_AUTHOR_RE = re.compile(r"([A-Z][\w'’-]+),\s*((?:[A-Z]\.[\s-]*)+)")
_IEEE_AUTHOR_RE = re.compile(r"((?:[A-Z]\.[\s-]*)+)([A-Z][\w'’-]+)")


def find_reference_region(text: str) -> Span | None:
    """Locate the reference/bibliography section (heading to end of text).

    Uses the *last* matching heading so a table of contents doesn't fool it.
    Returns None when there is no reference section — the caller reports
    that as a gap, never crashes.
    """
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return None
    return Span(start=matches[-1].end(), end=len(text))


def parse_references(text: str, region: Span) -> list[ReferenceEntry]:
    """Parse the reference region of ``text`` into structured entries."""
    block = text[region.start : region.end]
    entries = []
    for i, (offset, raw, number) in enumerate(_split_entries(block, region.start)):
        entries.append(_parse_entry(raw, offset, number, i))
    return entries


def _split_entries(block: str, base: int) -> list[tuple[int, str, int | None]]:
    """Split a reference block into (absolute offset, entry text, number)."""
    out: list[tuple[int, str, int | None]] = []
    numbered = list(_NUMBERED_START.finditer(block))
    if numbered:
        for i, m in enumerate(numbered):
            end = numbered[i + 1].start() if i + 1 < len(numbered) else len(block)
            raw = block[m.start() : end].rstrip()
            out.append((base + m.start(), raw, int(m.group(1))))
        return out
    # Same reason \r is allowed here: a CRLF blank line is "\r\n\r\n", so a
    # separator class of [ \t] alone saw no paragraph break and fell through
    # to the one-entry-per-line branch.
    if re.search(r"\n[ \t\r]*\n", block.strip()):
        for m in re.finditer(r"(?s)\S.*?(?=\n[ \t\r]*\n|\Z)", block):
            out.append((base + m.start(), m.group(0).rstrip(), None))
        return out
    # One entry per line; indented or lowercase-led lines continue the previous entry.
    pos = 0
    cur_start: int | None = None
    cur: list[str] = []
    for line in block.splitlines(keepends=True):
        stripped = line.strip()
        if stripped and re.match(r"[A-Z\[]", line):
            if cur:
                out.append((base + (cur_start or 0), "".join(cur).rstrip(), None))
            cur_start, cur = pos, [line]
        elif stripped and cur:
            cur.append(line)
        pos += len(line)
    if cur:
        out.append((base + (cur_start or 0), "".join(cur).rstrip(), None))
    return out


def _clean_match(rx: re.Pattern[str], body: str) -> str | None:
    m = rx.search(body)
    return m.group(0).rstrip(".,;)") if m else None


def _parse_authors(chunk: str) -> list[str]:
    chunk = chunk.strip().strip(",;: ")  # keep trailing periods — they end initials ("Chen, W.")
    if not chunk:
        return []
    ieee_first = bool(re.match(r"[A-Z]\.", chunk))
    for style in ("ieee", "apa") if ieee_first else ("apa", "ieee"):
        if style == "apa":
            found = _APA_AUTHOR_RE.findall(chunk)
            if found:
                return [f"{surname}, {initials.strip()}" for surname, initials in found]
        else:
            found = _IEEE_AUTHOR_RE.findall(chunk)
            if found:
                return [f"{initials.strip()} {surname}" for initials, surname in found]
    parts = re.split(r",\s+and\s+|\s+and\s+|\s*&\s*|;\s*", chunk)
    return [p.strip().strip(",. ") for p in parts if p.strip(",. ")]


def first_surname(entry: ReferenceEntry) -> str | None:
    """First author's surname — the author-date linkage handle."""
    if entry.authors:
        first = entry.authors[0]
        if "," in first:
            return first.split(",")[0].strip()
        return first.split()[-1] if first.split() else None
    m = re.match(r"\s*(?:\[\d+\]\s*)?([A-Z][\w'’-]+)", entry.raw)
    return m.group(1) if m else None


def _segments(rest: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", rest) if s.strip()]


def _clean_venue(seg: str | None) -> str | None:
    if not seg:
        return None
    if _ARXIV_RE.search(seg) or _URL_RE.search(seg) or _DOI_RE.search(seg):
        return None
    seg = re.sub(r"[,\s]*\bvol\..*$", "", seg)
    seg = re.sub(r",\s*\d.*$", "", seg)
    seg = re.sub(r"\s+\d[\d\s()]*:.*$", "", seg)  # "Journal 31 (2): 88-107"
    seg = seg.strip().rstrip(".,;:")
    return seg or None


def _bare_year(body: str, excluded: list[tuple[int, int]]) -> tuple[int | None, str | None]:
    year, suffix = None, None
    for m in _BARE_YEAR_RE.finditer(body):
        if any(s <= m.start() < e for s, e in excluded):
            continue
        year, suffix = int(m.group(1)), m.group(2)
    return year, suffix


def _parse_entry(raw: str, start: int, number: int | None, index: int) -> ReferenceEntry:
    span = Span(start=start, end=start + len(raw))
    body = " ".join(raw.split())
    if number is not None:
        body = re.sub(r"^\[\d{1,3}\]\s*", "", body)

    doi = _clean_match(_DOI_RE, body)
    arxiv_m = _ARXIV_RE.search(body)
    arxiv_id = arxiv_m.group(1) if arxiv_m else None
    url = _clean_match(_URL_RE, body)
    pages_m = _PAGES_RE.search(body) or _COLON_PAGES_RE.search(body) or _APA_PAGES_RE.search(body)
    pages = re.sub(r"\s+", "", pages_m.group(1)) if pages_m else None

    excluded = [m.span() for m in _DOI_RE.finditer(body)]
    excluded += [m.span() for m in _URL_RE.finditer(body)]

    authors: list[str] = []
    year: int | None = None
    suffix: str | None = None
    title: str | None = None
    venue: str | None = None

    apa_m = _PAREN_YEAR_RE.search(body)
    chicago_m = _CHICAGO_RE.match(body)
    quoted_m = _QUOTED_TITLE_RE.search(body)

    if apa_m:  # APA: Authors (year). Title. Venue, vol(iss), pages.
        authors = _parse_authors(body[: apa_m.start()])
        year, suffix = int(apa_m.group(1)), apa_m.group(2)
        segs = _segments(body[apa_m.end() :].lstrip(". "))
        if segs:
            title = segs[0].rstrip(".")
        if len(segs) > 1:
            venue = _clean_venue(segs[1])
    elif chicago_m:  # Chicago author-date: Authors. Year. Title/"Title." Venue.
        authors = _parse_authors(chicago_m.group("auth"))
        year, suffix = int(chicago_m.group("year")), chicago_m.group("suffix")
        rest = body[chicago_m.end() :]
        rq = _QUOTED_TITLE_RE.match(rest)
        if rq:
            title = rq.group(1).strip().rstrip(".,")
            segs = _segments(rest[rq.end() :].lstrip(". "))
        else:
            segs = _segments(rest)
            if segs:
                title = segs[0].rstrip(".")
                segs = segs[1:]
        if segs:
            venue = _clean_venue(segs[0])
    elif quoted_m:  # IEEE: I. Author, "Title," venue, vol., no., pp., year.
        authors = _parse_authors(body[: quoted_m.start()])
        title = quoted_m.group(1).strip().rstrip(".,")
        year, suffix = _bare_year(body, excluded)
        rest = body[quoted_m.end() :].lstrip(", ")
        rest = re.sub(r"^in\s+", "", rest)
        keep: list[str] = []
        for part in rest.split(","):
            if re.match(r"\s*(?:vol\.|no\.|pp?\.|\d)", part):
                break
            keep.append(part.strip())
        venue = ", ".join(keep).strip().rstrip(".,;:") or None
    else:  # Fallback: bare year, authors up to the year or first period.
        year, suffix = _bare_year(body, excluded)
        head = body.split(str(year))[0] if year else body.split(".")[0]
        authors = _parse_authors(re.sub(r"[,.\s]+$", "", head))

    if number is not None:
        key = str(number)
    else:
        entry = ReferenceEntry(key="", raw=raw, span=span, authors=authors)
        surname = first_surname(entry)
        if surname and year:
            key = f"{surname.casefold()}-{year}{suffix or ''}"
        else:
            key = f"entry-{index}"

    return ReferenceEntry(
        key=key,
        raw=raw,
        span=span,
        authors=authors,
        year=year,
        year_suffix=suffix,
        title=title,
        venue=venue,
        doi=doi,
        url=url,
        arxiv_id=arxiv_id,
        pages=pages,
    )
