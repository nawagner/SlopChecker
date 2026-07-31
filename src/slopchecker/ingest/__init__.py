"""Document ingestion (#4): PDF / DOCX / MD / HTML / TXT -> normalized text
with stable character offsets.

Public interface::

    from slopchecker.ingest import ingest

    result = ingest("proposal.pdf")     # -> IngestResult, never raises
    if result.status == "ok":
        result.document                 # FlattenedDoc (models.py contract)
        result.sections                 # heading map (DOCX/MD/HTML)
        result.find_section("Methods")  # Section | None
        result.references               # Span of the bibliography region
    else:
        result.reason                   # actionable, human-readable

Failures — unsupported format, scanned/no-text-layer PDF, missing optional
dependency, unreadable file — are first-class ``errored`` results with a
mandatory reason, never exceptions and never silent empty documents
("degrade to gaps, never crash").
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from slopchecker.ingest.docx import load_docx
from slopchecker.ingest.html import load_html
from slopchecker.ingest.markdown import load_markdown
from slopchecker.ingest.pdf import load_pdf
from slopchecker.ingest.text import load_text
from slopchecker.ingest.types import IngestResult, IngestStatus, Section
from slopchecker.ingest.util import errored, page_for_offset

__all__ = [
    "IngestResult",
    "IngestStatus",
    "LOADERS",
    "Section",
    "ingest",
    "page_for_offset",
]

LOADERS: dict[str, Callable[[Path], IngestResult]] = {
    ".pdf": load_pdf,
    ".docx": load_docx,
    ".md": load_markdown,
    ".markdown": load_markdown,
    ".html": load_html,
    ".htm": load_html,
    ".txt": load_text,
}


def ingest(path: str | Path) -> IngestResult:
    """Load one document. Total function: always returns an IngestResult."""
    path = Path(path)
    if not path.is_file():
        return errored(f"{path}: file not found.")
    loader = LOADERS.get(path.suffix.lower())
    if loader is None:
        supported = ", ".join(sorted(LOADERS))
        return errored(
            f"{path.name}: unsupported format '{path.suffix or '(no extension)'}' — "
            f"supported: {supported}."
        )
    try:
        return loader(path)
    except Exception as exc:  # loaders handle their own known failures;
        # this is the never-crash backstop for the unknown ones.
        return errored(f"{path.name}: ingestion failed unexpectedly ({type(exc).__name__}: {exc}).")
