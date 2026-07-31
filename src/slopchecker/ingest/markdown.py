"""Markdown loader (#4): text passes through verbatim (offsets index the raw
normalized file), structure comes from ATX headings outside code fences."""

from __future__ import annotations

import re
from pathlib import Path

from slopchecker.ingest.types import IngestResult
from slopchecker.ingest.util import (
    build_sections,
    errored,
    find_references,
    normalize,
    sha256_file,
)
from slopchecker.models import FlattenedDoc

_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^(?:```|~~~)")


def load_markdown(path: Path) -> IngestResult:
    text = normalize(path.read_text(encoding="utf-8", errors="replace"))
    if not text.strip():
        return errored(f"{path.name}: file contains no text — nothing to check.")

    headings: list[tuple[int, str, int]] = []  # (level, title, offset)
    offset = 0
    in_fence = False
    for line in text.splitlines(keepends=True):
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            match = _ATX_HEADING.match(line.rstrip("\n"))
            if match:
                headings.append((len(match.group(1)), match.group(2), offset))
        offset += len(line)

    sections = build_sections(text, headings)
    title = next((h[1] for h in headings if h[0] == 1), None)
    document = FlattenedDoc(
        file=path.name,
        text=text,
        sha256=sha256_file(path),
        media_type="text/markdown",
        title=title,
    )
    return IngestResult(
        status="ok",
        document=document,
        sections=sections,
        references=find_references(text, sections),
    )
