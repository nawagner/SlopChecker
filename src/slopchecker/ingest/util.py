"""Shared helpers for the format loaders (#4)."""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_right
from pathlib import Path

from slopchecker.ingest.types import IngestResult, Section
from slopchecker.models import FlattenedDoc, Span

# Headings that mark a reference/bibliography section. Anchored to the whole
# (stripped) title/line so a sentence mentioning "references" doesn't match.
REFERENCE_HEADING = re.compile(
    r"^(?:references|bibliography|works\s+cited|literature\s+cited|references\s+cited)\s*[:.]?\s*$",
    re.IGNORECASE,
)


# Typographic ligatures, which PDF extraction preserves verbatim: a
# browser-printed PDF yields "nonpro\ufb01t" as a single character, so a
# checker searching for "nonprofit" finds nothing and a quote anchored on it
# can't be grounded. Expanded to their component letters at load, before any
# offset is computed.
_LIGATURES = str.maketrans(
    {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\ufb05": "st",
        "\ufb06": "st",
    }
)


def normalize(text: str) -> str:
    """Line-ending, BOM, and ligature normalization. Offsets are computed
    AFTER this, so every span indexes into exactly the text the caller
    receives."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    return text.translate(_LIGATURES)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def page_for_offset(document: FlattenedDoc, offset: int) -> int | None:
    """1-based page number containing ``offset`` — so a finding can say
    "page 4", not just "offset 18322". None if the doc doesn't track pages."""
    if not document.page_offsets:
        return None
    return bisect_right(document.page_offsets, offset)


def errored(reason: str) -> IngestResult:
    return IngestResult(status="errored", reason=reason)


def build_sections(text: str, headings: list[tuple[int, str, int]]) -> list[Section]:
    """Turn (level, title, offset) heading hits into half-open sections.

    A section runs from its heading's start to the next heading of the same
    or higher level, or end of text.
    """
    headings = sorted(headings, key=lambda h: h[2])
    sections: list[Section] = []
    for i, (level, title, start) in enumerate(headings):
        end = len(text)
        for next_level, _, next_start in headings[i + 1 :]:
            if next_level <= level:
                end = next_start
                break
        sections.append(Section(title=title, level=level, span=Span(start=start, end=end)))
    return sections


def find_references(text: str, sections: list[Section]) -> Span | None:
    """Locate the reference/bibliography region.

    Prefer the section map (DOCX/MD/HTML give real headings). Fallback for
    formats without headings (PDF, plain text): the LAST line that is nothing
    but a reference-heading word starts the region, which runs to end of text.
    """
    for section in reversed(sections):
        if REFERENCE_HEADING.match(section.title.strip()):
            return section.span

    offset = 0
    hit: int | None = None
    for line in text.splitlines(keepends=True):
        if REFERENCE_HEADING.match(line.strip()):
            hit = offset
        offset += len(line)
    if hit is not None:
        return Span(start=hit, end=len(text))
    return None
