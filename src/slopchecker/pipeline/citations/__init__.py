"""Citation extraction (#7): references + in-text markers + linkage."""

from slopchecker.pipeline.citations.extract import extract_citations
from slopchecker.pipeline.citations.intext import find_intext_citations, sentence_bounds
from slopchecker.pipeline.citations.models import (
    Citation,
    CitationExtraction,
    CitationStyle,
    InTextCitation,
    ReferenceEntry,
)
from slopchecker.pipeline.citations.references import (
    find_reference_region,
    first_surname,
    parse_references,
)

__all__ = [
    "Citation",
    "CitationExtraction",
    "CitationStyle",
    "InTextCitation",
    "ReferenceEntry",
    "extract_citations",
    "find_intext_citations",
    "find_reference_region",
    "first_surname",
    "parse_references",
    "sentence_bounds",
]
