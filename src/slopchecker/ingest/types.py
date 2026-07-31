"""Ingest-local types (#4): what a loader returns beyond the FlattenedDoc.

``Section`` and the reference-region span are deliberately NOT in
``models.py`` — the report contract (#3) only carries ``FlattenedDoc``.
They live here until a second consumer needs them in the report itself;
promotion goes through a comment on #3 first.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from slopchecker.models import FlattenedDoc, Span

IngestStatus = Literal["ok", "errored"]


class Section(BaseModel):
    """One heading-delimited region of the flattened text.

    ``span`` runs from the start of the heading itself to the start of the
    next heading of the same or higher level (or end of document) —
    half-open, indexing into ``FlattenedDoc.text``.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    level: int = Field(ge=1)
    span: Span


class IngestResult(BaseModel):
    """What ``ingest()`` returns: document + structure, or a first-class error.

    Mirrors the ``CheckResult`` status discipline from models.py: an ingest
    that failed is ``errored`` with a mandatory, actionable ``reason`` —
    never a silent empty document ("degrade to gaps, never crash").
    """

    model_config = ConfigDict(extra="forbid")

    status: IngestStatus
    document: FlattenedDoc | None = None
    sections: list[Section] = Field(default_factory=list)
    references: Span | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _status_consistent(self) -> IngestResult:
        if self.status == "ok" and self.document is None:
            raise ValueError("ingest status 'ok' requires a document")
        if self.status == "errored" and self.reason is None:
            raise ValueError("ingest status 'errored' requires a reason")
        if self.status == "errored" and self.document is not None:
            raise ValueError("ingest status 'errored' cannot carry a document")
        return self

    def find_section(self, title: str) -> Section | None:
        """Case-insensitive lookup so the compliance check can ask
        'is there a Methods section?'"""
        needle = title.strip().casefold()
        for section in self.sections:
            if section.title.strip().casefold() == needle:
                return section
        return None
