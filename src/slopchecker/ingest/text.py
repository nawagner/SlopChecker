"""Plain-text loader (#4)."""

from __future__ import annotations

from pathlib import Path

from slopchecker.ingest.types import IngestResult
from slopchecker.ingest.util import errored, find_references, normalize, sha256_file
from slopchecker.models import FlattenedDoc


def load_text(path: Path) -> IngestResult:
    text = normalize(path.read_text(encoding="utf-8", errors="replace"))
    if not text.strip():
        return errored(f"{path.name}: file contains no text — nothing to check.")
    document = FlattenedDoc(
        file=path.name,
        text=text,
        sha256=sha256_file(path),
        media_type="text/plain",
    )
    return IngestResult(
        status="ok",
        document=document,
        references=find_references(text, []),
    )
