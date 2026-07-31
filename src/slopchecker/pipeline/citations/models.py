"""Citation types for #7 — local to the pipeline module.

These deliberately live here, not in ``slopchecker.models``: the report
contract (#3) doesn't need them yet. If they prove general (e.g. #8 DOI
resolution wants the same shape), promotion goes through a comment on #3.

Spans index into the same flattened submission text as everything else
(``FlattenedDoc.text`` once #4 wires ingestion in).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from slopchecker.models import Finding, Span

CitationStyle = Literal["author_year", "narrative", "numeric"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReferenceEntry(_Model):
    """One parsed entry from the reference/bibliography section.

    ``key`` is the linkage handle: the bracket number for numbered styles
    (``"3"``), or ``surname-year[suffix]`` (``"smith-2021a"``) for
    author-date styles. Parsed fields are best-effort; ``raw`` and ``span``
    are always exact.
    """

    key: str
    raw: str
    span: Span
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    year_suffix: str | None = None
    title: str | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    arxiv_id: str | None = None
    pages: str | None = None


class InTextCitation(_Model):
    """One in-text citation marker plus the claim sentence it anchors.

    ``span`` covers the marker itself; ``claim_span`` covers the containing
    sentence (what the claim-support check, #11, will consume). Numeric
    markers may carry several reference numbers (``[1, 3]``).
    """

    marker: str
    span: Span
    style: CitationStyle
    claim_text: str
    claim_span: Span
    numbers: list[int] = Field(default_factory=list)
    surname: str | None = None
    year: int | None = None
    year_suffix: str | None = None


class Citation(_Model):
    """A mention linked (or not) to a reference entry.

    One numeric marker citing several references yields one ``Citation``
    per number (``number`` says which). ``reference is None`` means the
    marker points at nothing — a real defect, surfaced as a Finding.
    """

    mention: InTextCitation
    reference: ReferenceEntry | None = None
    number: int | None = None


class CitationExtraction(_Model):
    """Everything ``extract_citations`` learned about one document."""

    ref_region: Span | None = None
    references: list[ReferenceEntry] = Field(default_factory=list)
    mentions: list[InTextCitation] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
