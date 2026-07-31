"""Offline coverage for the registered deterministic checks (#8, #9).

Why this file exists, since it overlaps `test_checks_live.py` on purpose:

When the live tests moved behind the `live` marker (#114), review found that
`metadata_match` and `citation_identifiers_valid` were named in **no test
outside the live file**. Both are registry entries that produce ledger rows
and quote-anchored findings, and both went dark in the default suite. Breaking
either — a borrowed DOI silently grading clean, malformed identifiers silently
not reported — left `pytest` green, with the only signal in an advisory job
that reviewers are told to expect red from third-party flakiness.

So: the live file keeps proving *our idea of Crossref still matches Crossref*.
This file proves *the checks do the right thing with a record in hand*, using a
stubbed provider chain and no network at all. Two different questions; only the
second one belongs in a merge gate.

The fixture is the same planted-defect document, so the assertions read against
the same references the live tests use:
  ref[1] correct citation           ref[3] real DOI, different paper (#9)
  ref[2] unregistered DOI           ref[6] malformed ISBN, ref[7] malformed DOI
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path

import pytest

from slopchecker.checks import identifiers_valid, metadata_match
from slopchecker.checks.providers import SourceRecord
from slopchecker.models import FlattenedDoc
from slopchecker.pipeline.registry import CheckContext

FIXTURE = Path(__file__).parent / "fixtures" / "checks" / "citations-proposal.md"

REAL_DOI = "10.1038/nature12373"

# The canonical record for REAL_DOI, as the providers really return it. Copied
# from the live tests' assertions so the two stay in agreement; if Crossref
# ever changes its answer, `pytest -m live` is what notices.
NATURE_RECORD = SourceRecord(
    provider="crossref",
    doi=REAL_DOI,
    title="Nanometre-scale thermometry in a living cell",
    surnames=("Kucsko", "Maurer", "Yao"),
    year=2013,
    venue="Nature",
)


@pytest.fixture
def doc() -> FlattenedDoc:
    raw = FIXTURE.read_bytes()
    return FlattenedDoc(
        file=FIXTURE.name,
        text=raw.decode(),
        sha256=hashlib.sha256(raw).hexdigest(),
        media_type="text/markdown",
    )


class StubChain:
    """A ProviderChain that answers from a dict instead of the network.

    Only REAL_DOI has a record, mirroring reality: the fabricated DOI in the
    fixture is registered nowhere, and the reverse title search finds nothing
    for an invented paper.
    """

    def __init__(self, *args, **kwargs) -> None:
        self.lookups: list[str] = []

    def lookup(self, client, ident):
        self.lookups.append(ident.value)
        return NATURE_RECORD if ident.value == REAL_DOI else None

    def search(self, client, *, title, surname=None, year=None):
        return None


@pytest.fixture
def offline_chain(monkeypatch) -> None:
    """Swap the provider chain and HTTP client out of `metadata_match`."""

    @contextmanager
    def no_client():
        yield None

    monkeypatch.setattr(metadata_match, "ProviderChain", StubChain)
    monkeypatch.setattr(metadata_match, "http_client", no_client)


def _row(output, check_id):
    return next(row for row in output.ledger if row.check == check_id)


def output_findings(doc):
    return metadata_match.metadata_match(doc, CheckContext(no_cache=True)).findings


# --------------------------------------------------------------------------
# metadata_match (#9) — the borrowed-DOI defect
# --------------------------------------------------------------------------


def test_borrowed_doi_grades_as_a_different_work(doc, offline_chain) -> None:
    """#9's whole reason to exist, gated offline.

    ref[3] wears a real DOI belonging to another paper. If this check stops
    comparing the canonical record against the reference, this is the test
    that goes red — previously nothing in the default suite did.
    """
    output = metadata_match.metadata_match(doc, CheckContext(no_cache=True))
    row = _row(output, "metadata_match")

    assert row.result is False
    assert "different work" in row.detail


def test_borrowed_doi_raises_a_quote_anchored_finding(doc, offline_chain) -> None:
    finding = next(f for f in output_findings(doc) if (f.target or "").startswith("ref[3]"))
    assert finding.label == "Cited metadata describes a different work"
    assert finding.anchor is not None
    assert finding.anchor.quote in doc.text
    span = finding.anchor.span
    assert span is not None and doc.text[span.start : span.end] == finding.anchor.quote


def test_the_correctly_cited_reference_produces_no_finding(doc, offline_chain) -> None:
    """No false positive on ref[1], the honest citation."""
    assert not [f for f in output_findings(doc) if (f.target or "").startswith("ref[1]")]


def test_malformed_identifiers_are_not_looked_up(doc, monkeypatch) -> None:
    """A typo'd DOI is citation_identifiers_valid's business, not a lookup.

    Looking it up here would report the same typo twice — once as a defect and
    once as a coverage gap — which reads like two independent problems.
    """
    chain = StubChain()

    @contextmanager
    def no_client():
        yield None

    monkeypatch.setattr(metadata_match, "ProviderChain", lambda *a, **k: chain)
    monkeypatch.setattr(metadata_match, "http_client", no_client)
    metadata_match.metadata_match(doc, CheckContext(no_cache=True))

    assert "10.1234" not in chain.lookups  # ref[7]'s malformed DOI
    assert REAL_DOI in chain.lookups


# --------------------------------------------------------------------------
# citation_identifiers_valid (#8) — no network involved at all
# --------------------------------------------------------------------------


def test_malformed_pair_is_counted_and_named(doc) -> None:
    """The registered check, not the `valid()` primitive underneath it.

    `test_checks_identifiers.py` covers the primitive exhaustively; nothing
    covered the check that consumes it until this test.
    """
    output = identifiers_valid.citation_identifiers_valid(doc, CheckContext())
    row = _row(output, "citation_identifiers_valid")

    assert row.result is False
    assert row.detail.startswith("5 / 7 well-formed")
    assert "malformed DOI" in row.detail
    assert "malformed ISBN" in row.detail


def test_malformed_findings_name_their_targets(doc) -> None:
    output = identifiers_valid.citation_identifiers_valid(doc, CheckContext())
    labels = {(f.target or ""): (f.label or "") for f in output.findings}

    assert labels["ref[6] · 9780306406158"] == "Malformed ISBN"
    assert labels["ref[7] · doi:10.1234"] == "Malformed DOI"


def test_every_malformed_finding_is_quote_anchored(doc) -> None:
    """CLAUDE.md's rule, enforced in the default suite rather than only live."""
    output = identifiers_valid.citation_identifiers_valid(doc, CheckContext())
    assert output.findings
    for finding in output.findings:
        assert finding.anchor is not None, finding.id
        assert finding.anchor.quote in doc.text, finding.id


def test_results_are_bools_or_numbers_never_prose(doc, offline_chain) -> None:
    for output in (
        identifiers_valid.citation_identifiers_valid(doc, CheckContext()),
        metadata_match.metadata_match(doc, CheckContext(no_cache=True)),
    ):
        for row in output.ledger:
            assert row.result is None or isinstance(row.result, bool | int | float)
