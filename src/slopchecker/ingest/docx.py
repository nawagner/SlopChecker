"""DOCX loader (#4), via python-docx.

Paragraphs are joined with blank lines; ``Heading N`` styles feed the
section map. DOCX has no fixed pagination (pages depend on the renderer),
so ``pages``/``page_offsets`` stay ``None`` — structure for Word docs is
headings, per the issue scope.
"""

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

_HEADING_STYLE = re.compile(r"^Heading (\d+)$")


def load_docx(path: Path) -> IngestResult:
    try:
        from docx import Document as open_docx
        from docx.opc.exceptions import PackageNotFoundError
    except ImportError:
        return errored(
            f"{path.name}: DOCX support not installed — install the extra: "
            'pip install "slopchecker[docx]" (python-docx).'
        )

    try:
        docx = open_docx(str(path))
    except PackageNotFoundError:
        return errored(f"{path.name}: not a valid .docx package (is it an old binary .doc?).")

    blocks: list[str] = []
    headings: list[tuple[int, str, int]] = []  # (level, title, block_index)
    doc_title: str | None = None
    for paragraph in docx.paragraphs:
        block = normalize(paragraph.text).strip()
        if not block:
            continue
        style = paragraph.style.name if paragraph.style is not None else ""
        if style == "Title" and doc_title is None:
            doc_title = block
        match = _HEADING_STYLE.match(style)
        if match:
            headings.append((int(match.group(1)), block, len(blocks)))
        blocks.append(block)

    if not blocks:
        return errored(f"{path.name}: document contains no text — nothing to check.")

    text = "\n\n".join(blocks)
    offsets: list[int] = []
    cursor = 0
    for block in blocks:
        offsets.append(cursor)
        cursor += len(block) + 2  # the "\n\n" separator

    positioned = [(level, title, offsets[i]) for level, title, i in headings]
    sections = build_sections(text, positioned)
    core_title = docx.core_properties.title or None
    document = FlattenedDoc(
        file=path.name,
        text=text,
        sha256=sha256_file(path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        title=core_title or doc_title,
    )
    return IngestResult(
        status="ok",
        document=document,
        sections=sections,
        references=find_references(text, sections),
    )
