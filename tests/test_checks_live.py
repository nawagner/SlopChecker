"""Live-network tests for the deterministic tier (#8, #9).

These really call doi.org, Crossref, OpenAlex, and arXiv — no recorded
fixtures, no fake transport. That is a deliberate choice: the whole value of
this tier is that it agrees with the outside world, and a mocked resolver
agrees with our idea of the outside world instead.

The cost is real and worth naming: CI is a required status check on main, so
an outage or a rate limit at any of these four hosts turns the build red for
everyone. If that becomes routine, the fix is a marker that skips this file
unless ``SLOPCHECK_LIVE=1`` — the offline files (identifiers, compare, cache,
net) already cover every decision this module makes on its own.

Identifiers used here are stable on purpose:
- ``10.1038/nature12373`` — a real, long-published Nature paper
- ``10.1234/jams.2023.0142`` — the repo's fabricated fixture DOI, unregistered
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from slopchecker.checks.cache import DiskCache
from slopchecker.checks.compare import Grade, compare, title_similarity
from slopchecker.checks.identifiers import Identifier
from slopchecker.checks.net import Outcome, fetch_status, http_client
from slopchecker.checks.providers import (
    ArxivProvider,
    CrossrefProvider,
    OpenAlexProvider,
    ProviderChain,
)
from slopchecker.checks.resolution import resolve_one
from slopchecker.models import FlattenedDoc
from slopchecker.pipeline import CheckContext, all_checks, discover, run_checks, select_checks
from slopchecker.pipeline.citations import extract_citations

FIXTURE = Path(__file__).parent / "fixtures" / "checks" / "citations-proposal.md"

REAL_DOI = "10.1038/nature12373"
REAL_TITLE = "Nanometre-scale thermometry in a living cell"
UNREGISTERED_DOI = "10.1234/jams.2023.0142"


def _ident(kind: str, value: str, ref_key: str = "1") -> Identifier:
    return Identifier(kind=kind, value=value, raw=value, ref_key=ref_key)


@pytest.fixture(scope="module")
def client():
    with http_client() as c:
        yield c


@pytest.fixture(scope="module")
def chain():
    return ProviderChain()


# --------------------------------------------------------------------------
# Resolution (#8)
# --------------------------------------------------------------------------


def test_real_doi_resolves(client) -> None:
    resolution = fetch_status(client, f"https://doi.org/{REAL_DOI}")
    assert resolution.outcome is Outcome.resolves
    assert resolution.ok
    assert resolution.http_status is not None and resolution.http_status < 400
    # doi.org redirects to the publisher: that target is the evidence.
    assert resolution.final_url and "doi.org" not in resolution.final_url


def test_unregistered_doi_reports_not_found(client) -> None:
    """The headline number's basis: doi.org has no record for this DOI."""
    resolution = fetch_status(client, f"https://doi.org/{UNREGISTERED_DOI}")
    assert resolution.outcome is Outcome.not_found
    assert resolution.http_status == 404
    assert not resolution.transport_error


def test_unresolvable_host_is_a_gap_not_a_failure(client) -> None:
    """.invalid can never resolve (RFC 2606). That is our gap, not a defect."""
    resolution = fetch_status(client, "https://reports.example.invalid/2024-review")
    assert resolution.outcome is Outcome.unreachable
    assert resolution.outcome is not Outcome.not_found


# --------------------------------------------------------------------------
# Canonical metadata (#9)
# --------------------------------------------------------------------------


def test_crossref_returns_the_canonical_record(client) -> None:
    record = CrossrefProvider().lookup(client, _ident("doi", REAL_DOI))
    assert record is not None
    assert record.provider == "crossref"
    assert title_similarity(record.title, REAL_TITLE) >= 0.95
    assert record.year == 2013
    assert record.surnames[0] == "Kucsko"
    assert record.venue == "Nature"


def test_openalex_answers_the_same_doi(client) -> None:
    """The substitute provider (#9): same interface, no key, same shape."""
    record = OpenAlexProvider().lookup(client, _ident("doi", REAL_DOI))
    assert record is not None
    assert record.provider == "openalex"
    assert title_similarity(record.title, REAL_TITLE) >= 0.95
    assert record.year == 2013


def test_arxiv_provider_answers_an_arxiv_id(client) -> None:
    record = ArxivProvider().lookup(client, _ident("arxiv", "2107.04321"))
    assert record is not None
    assert record.provider == "arxiv"
    assert record.title
    assert record.venue == "arXiv"


def test_no_provider_has_the_unregistered_doi(client, chain) -> None:
    assert chain.lookup(client, _ident("doi", UNREGISTERED_DOI)) is None


def test_correct_citation_grades_as_a_match(client, chain) -> None:
    """End to end on real data: a correctly cited paper must come back clean."""
    ref = next(r for r in extract_citations(FIXTURE.read_text()).references if r.key == "1")
    record = chain.lookup(client, _ident("doi", REAL_DOI))
    assert compare(ref, record).grade is Grade.matches


def test_real_doi_with_an_invented_reference_grades_as_different(client, chain) -> None:
    """#9's whole reason to exist: ref [3] wears a real DOI from another paper."""
    ref = next(r for r in extract_citations(FIXTURE.read_text()).references if r.key == "3")
    record = chain.lookup(client, _ident("doi", REAL_DOI))
    match = compare(ref, record)
    assert match.grade is Grade.different
    assert match.canonical is not None and match.canonical.title


def test_reverse_lookup_finds_a_real_paper_by_title(client, chain) -> None:
    """ "Wrong DOI" vs "no such paper" — the distinction a reviewer needs."""
    found = chain.search(client, title=REAL_TITLE, surname="Kucsko", year=2013)
    assert found is not None
    assert found.doi == REAL_DOI
    assert title_similarity(found.title, REAL_TITLE) >= 0.95


def test_reverse_lookup_of_a_fabricated_title_stays_empty(client, chain) -> None:
    """No false "found it elsewhere" for a title nobody has published."""
    found = chain.search(
        client,
        title="Velocity of synthetic narratives in contested information environments",
        surname="Whitfield",
        year=2023,
    )
    assert found is None or title_similarity(found.title, "Velocity of synthetic narratives") < 0.80


# --------------------------------------------------------------------------
# Caching (#8)
# --------------------------------------------------------------------------


def test_cache_serves_the_second_lookup_without_the_network(client, tmp_path) -> None:
    """The second call gets ``None`` for a client: touching it would crash."""
    cache = DiskCache(tmp_path)
    ident = _ident("doi", REAL_DOI)
    first = resolve_one(client, cache, ident)
    assert first.outcome is Outcome.resolves
    assert cache.path_for("resolve", f"doi:{REAL_DOI}").is_file()

    second = resolve_one(None, DiskCache(tmp_path), ident)  # type: ignore[arg-type]
    assert second.outcome is first.outcome
    assert second.http_status == first.http_status


# --------------------------------------------------------------------------
# The whole tier, over the planted fixture
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def report():
    raw = FIXTURE.read_bytes()
    doc = FlattenedDoc(
        file=FIXTURE.name,
        text=raw.decode(),
        sha256=hashlib.sha256(raw).hexdigest(),
        media_type="text/markdown",
    )
    discover()
    return run_checks(
        doc,
        select_checks(all_checks(), tier="deterministic"),
        context=CheckContext(no_cache=True),
    )


def _row(report, check_id):
    return next(row for row in report.ledger if row.check == check_id)


def test_every_check_produced_a_row(report) -> None:
    ids = {row.check for row in report.ledger}
    assert {
        "citation_identifiers_valid",
        "all_dois_resolve",
        "all_urls_resolve",
        "metadata_match",
    } <= ids


def test_dois_row_counts_the_planted_unregistered_doi(report) -> None:
    row = _row(report, "all_dois_resolve")
    assert row.status == "ok"
    assert row.result is False
    assert row.detail == "2 / 3 resolved — 1 not found"


def test_identifier_row_counts_the_planted_malformed_pair(report) -> None:
    row = _row(report, "citation_identifiers_valid")
    assert row.result is False
    assert row.detail.startswith("5 / 7 well-formed")
    assert "malformed DOI" in row.detail and "malformed ISBN" in row.detail


def test_metadata_row_catches_the_borrowed_doi(report) -> None:
    row = _row(report, "metadata_match")
    assert row.result is False
    assert "different work" in row.detail


def test_urls_row_separates_dead_from_unreachable(report) -> None:
    """One URL 404s (a finding); one host cannot resolve (a gap)."""
    row = _row(report, "all_urls_resolve")
    assert "1 not found" in row.detail
    assert "1 could not be checked" in row.detail


def test_unreachable_url_is_reported_as_skipped_not_failed(report) -> None:
    finding = next(f for f in report.findings if "example.invalid" in (f.target or ""))
    assert [c.status for c in finding.checks] == ["skipped"]
    assert finding.checks[0].result is None
    assert "coverage gap" in (finding.note or "")


def test_findings_name_the_planted_defects(report) -> None:
    """One reference can raise findings from several checks — ref [2] raises
    two (the DOI doesn't resolve, and no provider has metadata for it), which
    is why this collects labels per target rather than assuming one each."""
    labels: dict[str, set[str]] = {}
    for finding in report.findings:
        labels.setdefault(finding.target or "", set()).add(finding.label or "")

    assert "DOI does not resolve" in labels[f"ref[2] · {UNREGISTERED_DOI}"]
    assert "Cited metadata describes a different work" in labels[f"ref[3] · {REAL_DOI}"]
    assert labels["ref[6] · 9780306406158"] == {"Malformed ISBN"}
    assert labels["ref[7] · doi:10.1234"] == {"Malformed DOI"}


def test_the_correctly_cited_reference_produces_no_finding(report) -> None:
    """No false positives on ref [1] — the honest citation in the fixture."""
    assert not [f for f in report.findings if (f.target or "").startswith("ref[1]")]


def test_every_finding_is_quote_anchored(report) -> None:
    """CLAUDE.md's rule: a finding's quote must be verbatim in the document."""
    text = report.document.text
    for finding in report.findings:
        assert finding.anchor is not None, finding.id
        assert finding.anchor.quote in text, finding.id
        span = finding.anchor.span
        assert span is not None
        assert text[span.start : span.end] == finding.anchor.quote, finding.id


def test_check_names_in_findings_are_registry_ids(report) -> None:
    """Report rows must trace back to registry entries (registry.py's rule)."""
    discover()
    known = {rc.meta.id for rc in all_checks()}
    for finding in report.findings:
        for check in finding.checks:
            assert check.name in known, check.name


def test_results_are_bools_or_numbers_never_prose(report) -> None:
    for row in report.ledger:
        assert row.result is None or isinstance(row.result, bool | int | float)
    for finding in report.findings:
        for check in finding.checks:
            assert check.result is None or isinstance(check.result, bool | int | float)


def test_report_serializes_for_the_renderer(report) -> None:
    payload = report.to_report_dict()
    assert payload["schema_version"]
    assert payload["summary"]["recommendation"] == "human_review"
    counts = report.counts()
    assert counts["failed"] >= 3  # identifiers, DOIs, metadata
    assert counts["skipped"] + counts["errored"] >= 0
