"""Identifier validity (#8), offline half — no network in this file.

Structural validity is decidable without asking anyone, so these are ordinary
unit tests. The network lives in ``test_checks_live.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from slopchecker.checks.identifiers import (
    identifiers_in,
    malformed_reason,
    normalize_arxiv_id,
    normalize_doi,
    valid_arxiv_id,
    valid_doi,
    valid_isbn,
    valid_url,
)
from slopchecker.pipeline.citations import extract_citations

FIXTURE = Path(__file__).parent / "fixtures" / "checks" / "citations-proposal.md"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("10.1038/nature12373", "10.1038/nature12373"),
        ("doi:10.1038/nature12373", "10.1038/nature12373"),
        ("DOI: 10.1038/NATURE12373", "10.1038/nature12373"),
        ("https://doi.org/10.1038/nature12373", "10.1038/nature12373"),
        ("http://dx.doi.org/10.1038/nature12373", "10.1038/nature12373"),
        # Trailing sentence punctuation belongs to the prose, not the DOI.
        ("10.1038/nature12373.", "10.1038/nature12373"),
        ("not a doi at all", None),
    ],
)
def test_normalize_doi(raw: str, expected: str | None) -> None:
    assert normalize_doi(raw) == expected


@pytest.mark.parametrize(
    "raw,ok",
    [
        ("10.1038/nature12373", True),
        ("10.1234/jams.2023.0142", True),  # well-formed; it just doesn't exist
        ("10.1000/xyz(123)/abc", True),  # parens and slashes are legal suffixes
        ("10.1234", False),  # prefix with no suffix
        ("10.12/x", False),  # prefix too short
        ("11.1234/x", False),
        ("", False),
    ],
)
def test_valid_doi(raw: str, ok: bool) -> None:
    assert valid_doi(raw) is ok


@pytest.mark.parametrize(
    "raw,ok",
    [
        ("2107.04321", True),
        ("arXiv:2107.04321v2", True),
        ("math.GT/0309136", True),
        ("2113.04321", False),  # month 13 does not exist
        ("2107.043", False),
        ("nonsense", False),
    ],
)
def test_valid_arxiv_id(raw: str, ok: bool) -> None:
    assert valid_arxiv_id(raw) is ok


def test_normalize_arxiv_strips_prefix() -> None:
    assert normalize_arxiv_id("arXiv:2107.04321v2") == "2107.04321v2"


@pytest.mark.parametrize(
    "raw,ok",
    [
        ("978-0-306-40615-7", True),
        ("9780306406157", True),
        ("0-306-40615-2", True),
        ("0306406152", True),
        ("080442957X", True),  # ISBN-10 with an X check digit
        ("978-0-306-40615-8", False),  # checksum off by one
        ("0-306-40615-3", False),
        ("12345", False),
    ],
)
def test_valid_isbn(raw: str, ok: bool) -> None:
    assert valid_isbn(raw) is ok


@pytest.mark.parametrize(
    "raw,ok",
    [
        ("https://example.org/a/b?c=d", True),
        ("http://example.org", True),
        # Structurally fine; it will simply never resolve. That distinction is
        # the whole point of splitting validity from resolution.
        ("https://reports.example.invalid/2024-review", True),
        ("example.org/a", False),
        ("ftp://example.org/a", False),
        ("https://", False),
        ("https://localhost", False),
        ("", False),
    ],
)
def test_valid_url(raw: str, ok: bool) -> None:
    assert valid_url(raw) is ok


def test_malformed_reason_reads_as_a_clause() -> None:
    """The report renders "<DOI> as written: <reason>." — no "is is" stutter."""
    assert malformed_reason("doi", "10.1234") == "not DOI-shaped (expected 10.NNNN/suffix)"
    assert malformed_reason("isbn", "978-0-306-40615-8") == "checksum does not match"
    assert malformed_reason("isbn", "12345") == "5 digits (expected 10 or 13)"


def _references():
    return {ref.key: ref for ref in extract_citations(FIXTURE.read_text()).references}


def test_identifiers_found_on_each_reference() -> None:
    refs = _references()
    assert len(refs) == 7

    found = {key: identifiers_in(ref) for key, ref in refs.items()}
    kinds = {key: sorted(i.kind for i in idents) for key, idents in found.items()}
    assert kinds == {
        "1": ["doi"],
        "2": ["doi"],
        "3": ["doi"],
        "4": ["url"],
        "5": ["url"],
        "6": ["isbn"],
        "7": ["doi"],
    }
    assert found["1"][0].value == "10.1038/nature12373"
    assert found["6"][0].value == "9780306406158"


def test_malformed_identifiers_are_the_planted_two() -> None:
    """Only refs [6] and [7] are structurally broken in the fixture."""
    from slopchecker.checks.identifiers import valid

    broken = {
        ref.key
        for ref in _references().values()
        for ident in identifiers_in(ref)
        if not valid(ident.kind, ident.value)
    }
    assert broken == {"6", "7"}


def test_identifier_span_points_at_the_document_text() -> None:
    """Spans must index the real text so findings stay quote-anchored."""
    text = FIXTURE.read_text()
    ident = identifiers_in(_references()["1"])[0]
    assert ident.span is not None
    assert text[ident.span.start : ident.span.end] == ident.raw


def test_a_doi_url_is_not_also_counted_as_a_url() -> None:
    """https://doi.org/10.x is one identifier, not a DOI plus a URL."""
    from slopchecker.models import Span
    from slopchecker.pipeline.citations import ReferenceEntry

    ref = ReferenceEntry(
        key="1",
        raw="A. Author, 'Title,' 2020. https://doi.org/10.1038/nature12373",
        span=Span(start=0, end=61),
    )
    kinds = [i.kind for i in identifiers_in(ref)]
    assert kinds == ["doi"]
