"""Structural validity of citation identifiers (#8) — pure, offline, no network.

Everything here answers "is this identifier well-formed?", never "does it
exist?". A malformed DOI is a formatting defect; a well-formed DOI that
doesn't resolve is a different finding entirely (``doi_resolution.py``), and
conflating the two is exactly the sloppiness the report is supposed to avoid.

The reference parser (#7) already pulls ``doi`` / ``url`` / ``arxiv_id`` off
each entry; this module re-scans the raw entry text as well, so an identifier
the parser's field extraction missed (ISBNs, a second DOI, a DOI written as a
``dx.doi.org`` URL) still gets checked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from slopchecker.models import Span
from slopchecker.pipeline.citations.models import ReferenceEntry

IdentifierKind = Literal["doi", "arxiv", "isbn", "url"]

# Crossref's own recommended DOI pattern, anchored. Deliberately permissive
# about the suffix: DOIs in the wild carry parens, slashes, and semicolons.
_DOI_BODY = r"10\.\d{4,9}/[-._;()/:A-Za-z0-9<>\[\]+]+"
_DOI_RE = re.compile(rf"^{_DOI_BODY}$")
_DOI_IN_TEXT_RE = re.compile(
    rf"(?:doi:\s*|https?://(?:dx\.)?doi\.org/)?(?P<doi>{_DOI_BODY})", re.IGNORECASE
)
# A DOI that looks like a DOI but isn't: a bare "10.1234" with no suffix, or a
# prefix shorter than four digits. Caught so the finding can say what's wrong.
_DOI_NEAR_MISS_RE = re.compile(r"\b(?:doi:\s*)?10\.\d{1,9}(?:/\S*)?", re.IGNORECASE)

# arXiv: post-2007 "2107.04321v2" and legacy "math.GT/0309136".
_ARXIV_NEW_RE = re.compile(r"^(\d{2})(\d{2})\.(\d{4,5})(v\d+)?$")
_ARXIV_OLD_RE = re.compile(r"^[a-z-]+(?:\.[A-Z]{2})?/\d{7}(v\d+)?$")
# The scanner's suffix is \d{4,} — deliberately laxer than the validator's
# \d{4,5}. Capturing a 6-digit suffix means valid_arxiv_id can *reject* it as
# malformed; capping the scan at 5 instead silently truncated "2107.043210"
# to "2107.04321", which is a different real paper — we'd have hidden the
# defect and then reported another author's metadata against this reference.
_ARXIV_IN_TEXT_RE = re.compile(
    r"arxiv[:\s]*(?:preprint\s+)?(?:arxiv:)?\s*"
    r"(?P<id>\d{4}\.\d{4,}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)",
    re.IGNORECASE,
)

# Deliberately permissive: ISBNs group their digits with spaces or any of the
# unicode dashes, so the run can't be split on whitespace here. _isbn_in()
# below decides where the identifier actually ends.
_ISBN_IN_TEXT_RE = re.compile(
    r"isbn(?:-?1[03])?:?\s*([0-9][0-9\s‐-―-]{8,24}[0-9Xx])", re.IGNORECASE
)
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\"',]+")
# Trailing sentence punctuation is part of the prose, not the identifier.
_TRAILING_JUNK = ".,;:)]}>'\"”’"


@dataclass(frozen=True)
class Identifier:
    """One identifier found on one reference entry.

    ``value`` is normalized (lowercased bare DOI, arXiv id without the
    ``arXiv:`` prefix); ``raw`` is exactly what the document said, so a
    finding can quote the document rather than our cleanup of it.
    """

    kind: IdentifierKind
    value: str
    raw: str
    ref_key: str
    span: Span | None = None

    @property
    def target(self) -> str:
        """How this identifier is named in a report row: ``ref[3] · 10.x/y``."""
        return f"ref[{self.ref_key}] · {self.value}"


def normalize_doi(raw: str | None) -> str | None:
    """Bare, lowercased DOI from any of the usual wrappers, or None.

    Accepts ``10.1234/x``, ``doi:10.1234/x``, ``https://doi.org/10.1234/x``,
    and the ``dx.doi.org`` form. Returns None when there's no DOI-shaped
    substring at all — "not a DOI" and "a broken DOI" are distinguished by
    the caller via :func:`valid_doi`.
    """
    if not raw:
        return None
    candidate = raw.strip()
    match = _DOI_IN_TEXT_RE.search(candidate)
    if match is None:
        return None
    doi = match.group("doi").rstrip(_TRAILING_JUNK)
    return doi.lower() or None


def valid_doi(raw: str | None) -> bool:
    """True when ``raw`` is a structurally well-formed DOI."""
    doi = normalize_doi(raw)
    return doi is not None and _DOI_RE.match(doi) is not None


def normalize_arxiv_id(raw: str | None) -> str | None:
    """Bare arXiv id (version suffix preserved), or None."""
    if not raw:
        return None
    candidate = raw.strip().rstrip(_TRAILING_JUNK)
    match = _ARXIV_IN_TEXT_RE.search(candidate)
    if match is not None:
        return match.group("id")
    stripped = re.sub(r"^arxiv:\s*", "", candidate, flags=re.IGNORECASE)
    return stripped or None


def valid_arxiv_id(raw: str | None) -> bool:
    """True for a well-formed arXiv identifier, old or new style.

    The new style encodes YYMM, so an impossible month (``2113.00001``) is a
    malformed id and not merely an unknown one.
    """
    ident = normalize_arxiv_id(raw)
    if not ident:
        return False
    new = _ARXIV_NEW_RE.match(ident)
    if new is not None:
        month = int(new.group(2))
        return 1 <= month <= 12
    return _ARXIV_OLD_RE.match(ident) is not None


def normalize_isbn(raw: str | None) -> str | None:
    """Digits (and a trailing X) of an ISBN, hyphens and spaces removed."""
    if not raw:
        return None
    digits = re.sub(r"[^0-9Xx]", "", raw).upper()
    return digits or None


def valid_isbn(raw: str | None) -> bool:
    """True when the ISBN checksum holds (ISBN-10 mod 11, ISBN-13 mod 10)."""
    isbn = normalize_isbn(raw)
    if isbn is None:
        return False
    if len(isbn) == 10:
        if not re.match(r"^\d{9}[\dX]$", isbn):
            return False
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(isbn))
        return total % 11 == 0
    if len(isbn) == 13:
        if not isbn.isdigit():
            return False
        total = sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(isbn))
        return total % 10 == 0
    return False


def _isbn_in(run: str) -> tuple[str, str]:
    """(raw slice, normalized digits) for the ISBN inside a captured run.

    The capture has to be permissive — ISBNs group their digits with spaces
    and dashes, so the run can't simply stop at whitespace. That means a bare
    year following an ISBN ("…40615-7 2020", ordinary in a bibliography that
    doesn't punctuate between fields) gets swept in, and the result was a
    17-digit blob reported to a reviewer as a malformed ISBN when the ISBN
    was perfectly good.

    So: a run of exactly 10 or 13 digits is taken as-is — that keeps a real
    bad checksum reported as one. Only when there are *extra* digits do we cut
    back to a 13- or 10-digit prefix, and only if that prefix actually
    validates. Trying the 10-prefix of every 13-digit run would let a
    malformed ISBN-13 pass as an accidentally-valid ISBN-10.
    """
    marks = [i for i, c in enumerate(run) if c.isdigit() or c in "Xx"]
    if len(marks) not in (10, 13):
        for length in (13, 10):
            if len(marks) > length:
                candidate = run[: marks[length - 1] + 1]
                if valid_isbn(candidate):
                    return candidate, normalize_isbn(candidate) or ""
    # Nothing shorter validates: report the whole run, so a genuine defect
    # still surfaces rather than being trimmed away.
    return run, normalize_isbn(run) or ""


def valid_url(raw: str | None) -> bool:
    """True for a parseable absolute http(s) URL with a plausible host.

    Deliberately structural: ``https://example.invalid/x`` is a *valid* URL
    that will fail to resolve. Two different findings, two different rows.
    """
    if not raw:
        return False
    try:
        parts = urlsplit(raw.strip())
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    host = parts.netloc.split("@")[-1].split(":")[0]
    if any(c.isspace() for c in raw.strip()) or "." not in host.strip("."):
        return False
    return all(part for part in host.split("."))


def valid(kind: IdentifierKind, value: str) -> bool:
    """Dispatch to the right validator for ``kind``."""
    return {
        "doi": valid_doi,
        "arxiv": valid_arxiv_id,
        "isbn": valid_isbn,
        "url": valid_url,
    }[kind](value)


def malformed_reason(kind: IdentifierKind, value: str) -> str:
    """One line saying what's structurally wrong — never why it might be.

    Phrased to complete "<DOI> as written: …", so the report never produces
    the "is is" stutter of a sentence pasted into a sentence.
    """
    if kind == "doi":
        if normalize_doi(value) is None:
            return "not DOI-shaped (expected 10.NNNN/suffix)"
        return "prefix or suffix is malformed (expected 10.NNNN/suffix)"
    if kind == "arxiv":
        return "not a valid arXiv id (expected YYMM.NNNNN or archive/YYMMNNN)"
    if kind == "isbn":
        isbn = normalize_isbn(value) or ""
        if len(isbn) not in (10, 13):
            return f"{len(isbn)} digits (expected 10 or 13)"
        return "checksum does not match"
    return "not a parseable absolute http(s) address"


def _span_for(ref: ReferenceEntry, raw: str, offset: int | None = None) -> Span | None:
    """Offsets of ``raw`` inside the document, derived from the entry's span.

    ``offset`` is the position the scanner actually matched at. Falling back
    to ``ref.raw.find(raw)`` re-finds the *first* occurrence, which is a
    different place whenever one identifier's text is a substring of an
    earlier one ("10.1234/abc.2020" inside "10.1234/abc.2020.1") — the span
    then pointed into the wrong DOI while still slicing to the right string,
    so it looked correct from every direction except the offset.
    """
    if offset is None:
        offset = ref.raw.find(raw)
    if offset < 0:
        return None
    start = ref.span.start + offset
    return Span(start=start, end=start + len(raw))


def identifiers_in(ref: ReferenceEntry) -> list[Identifier]:
    """Every identifier on one reference entry, de-duplicated, in text order.

    Sources both the parser's structured fields (#7) and a rescan of the raw
    entry text, because the parser only keeps the first of each kind and a
    reference can carry several (a DOI *and* an arXiv id is routine).
    """
    found: list[Identifier] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: IdentifierKind, value: str | None, raw: str, offset: int | None = None) -> None:
        if not value:
            return
        key = (kind, value.lower())
        if key in seen:
            return
        seen.add(key)
        found.append(
            Identifier(
                kind=kind,
                value=value,
                raw=raw,
                ref_key=ref.key,
                span=_span_for(ref, raw, offset),
            )
        )

    for match in _DOI_IN_TEXT_RE.finditer(ref.raw):
        raw = match.group(0).rstrip(_TRAILING_JUNK)
        add("doi", normalize_doi(raw), raw, match.start())
    add("doi", normalize_doi(ref.doi), ref.doi or "")

    # A "10.1234" with no suffix never matches _DOI_IN_TEXT_RE, so it would
    # slip through as "no DOI here" rather than as the malformed DOI it is.
    for match in _DOI_NEAR_MISS_RE.finditer(ref.raw):
        raw = match.group(0).rstrip(_TRAILING_JUNK)
        if not valid_doi(raw) and normalize_doi(raw) is None:
            add("doi", raw.lower(), raw, match.start())

    for match in _ARXIV_IN_TEXT_RE.finditer(ref.raw):
        add("arxiv", match.group("id"), match.group(0), match.start())
    add("arxiv", normalize_arxiv_id(ref.arxiv_id), ref.arxiv_id or "")

    for match in _ISBN_IN_TEXT_RE.finditer(ref.raw):
        isbn_raw, isbn_value = _isbn_in(match.group(1))
        add("isbn", isbn_value, isbn_raw, match.start(1))

    for match in _URL_IN_TEXT_RE.finditer(ref.raw):
        raw = match.group(0).rstrip(_TRAILING_JUNK)
        # A DOI or arXiv URL is already covered by its own identifier row;
        # resolving it twice would double-count the same failure.
        if normalize_doi(raw) or "arxiv.org/abs/" in raw.lower():
            continue
        add("url", raw, raw)
    if ref.url and not normalize_doi(ref.url) and "arxiv.org/abs/" not in ref.url.lower():
        add("url", ref.url.rstrip(_TRAILING_JUNK), ref.url)

    return found
