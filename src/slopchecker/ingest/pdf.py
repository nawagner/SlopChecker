"""PDF loader (#4), via pymupdf.

Pages are joined with a form feed (``\\f``, the pdftotext convention);
``page_offsets[i]`` is the char offset in the flattened text where page
``i + 1`` starts, so a span maps back to "page 4", not just "offset 18322".

Image-only scans (no extractable text on any page) come back ``errored``
with an actionable message — OCR is explicitly out of scope for #4.
Heading extraction from PDFs (font-size heuristics) is also out of scope;
the structure map for PDFs is pages, and the reference region falls back
to line matching.
"""

from __future__ import annotations

from pathlib import Path

from slopchecker.ingest.types import IngestResult
from slopchecker.ingest.util import errored, find_references, normalize, sha256_file
from slopchecker.models import FlattenedDoc


def load_pdf(path: Path) -> IngestResult:
    try:
        import pymupdf
    except ImportError:
        return errored(
            f"{path.name}: PDF support not installed — install the extra: "
            'pip install "slopchecker[pdf]" (pymupdf).'
        )

    try:
        with pymupdf.open(path) as pdf:
            page_texts = [normalize(page.get_text("text")) for page in pdf]
            meta_title = (pdf.metadata or {}).get("title") or None
    except Exception as exc:  # pymupdf raises format-specific subclasses
        return errored(f"{path.name}: could not open as PDF ({exc}).")

    if not page_texts:
        return errored(f"{path.name}: PDF has no pages — nothing to check.")

    if not any(text.strip() for text in page_texts):
        return errored(
            f"{path.name}: no extractable text on any of {len(page_texts)} page(s) — "
            "likely a scanned/image-only PDF. OCR is out of scope; please provide a "
            "text-based export (e.g. save/print to PDF from the original document)."
        )

    page_offsets: list[int] = []
    cursor = 0
    for text in page_texts:
        page_offsets.append(cursor)
        cursor += len(text) + 1  # the "\f" separator
    flattened = "\f".join(page_texts)

    document = FlattenedDoc(
        file=path.name,
        text=flattened,
        sha256=sha256_file(path),
        pages=len(page_texts),
        page_offsets=page_offsets,
        media_type="application/pdf",
        title=meta_title,
    )
    return IngestResult(
        status="ok",
        document=document,
        references=find_references(flattened, []),
    )
