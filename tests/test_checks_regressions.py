"""Regression tests for defects found by independent spec-derived review.

Each test here corresponds to a bug that shipped in the first cut of #8/#9 and
was found by reading the acceptance criteria rather than the implementation.
They are grouped by the invariant they protect, and every one of them failed
before its fix.

Offline and deterministic: the network paths are monkeypatched at
``resolution.fetch_status`` so the failure shapes (403, 503, timeout) can be
produced on demand instead of hoped for.
"""

from __future__ import annotations

import threading
import time

import pytest

from slopchecker.checks import resolution as resolution_mod
from slopchecker.checks.cache import DiskCache
from slopchecker.checks.compare import Grade, compare, grade_author, title_similarity
from slopchecker.checks.identifiers import identifiers_in
from slopchecker.checks.net import Outcome, Resolution
from slopchecker.checks.providers import ProviderChain, SourceRecord
from slopchecker.checks.refs import anchor_for
from slopchecker.checks.resolution import resolve_one, run_resolution_check
from slopchecker.models import FlattenedDoc, Span
from slopchecker.pipeline.citations import ReferenceEntry, extract_citations
from slopchecker.pipeline.registry import CheckContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry(raw: str) -> ReferenceEntry:
    return ReferenceEntry(key="1", raw=raw, span=Span(start=0, end=len(raw)))


def _doc_with_dois(dois: list[str], indent: str = "") -> FlattenedDoc:
    """A document whose reference list carries one DOI per entry."""
    lines = [
        f"{indent}[{i + 1}] Author, A. (2020). A Title. A Venue. doi:{doi}"
        for i, doi in enumerate(dois)
    ]
    text = "Body prose citing things [1].\n\nReferences\n\n" + "\n\n".join(lines) + "\n"
    return FlattenedDoc(file="doc.md", text=text)


def _run_dois(doc: FlattenedDoc, monkeypatch, outcomes: list[Resolution]):
    """Run all_dois_resolve with canned network answers, in call order."""
    answers = iter(outcomes)
    calls: list[str] = []

    def fake_fetch(client, url):
        calls.append(url)
        return next(answers)

    monkeypatch.setattr(resolution_mod, "fetch_status", fake_fetch)
    out = run_resolution_check(
        doc,
        CheckContext(no_cache=True),
        check_id="all_dois_resolve",
        label="All DOIs resolve",
        kind="doi",
        noun="DOI",
        prefix="DOI",
    )
    return out, calls


# ---------------------------------------------------------------------------
# The ledger must never claim a pass over nothing (#8 AC 1 and 2)
# ---------------------------------------------------------------------------


def test_all_blocked_is_not_a_pass(monkeypatch) -> None:
    """Five paywalled DOIs reported result=True, "All DOIs resolve", beside a
    detail reading "0 / 5 resolved". A bot wall is not evidence of soundness."""
    doc = _doc_with_dois([f"10.1234/a{i}" for i in range(5)])
    blocked = [Resolution(url="u", outcome=Outcome.blocked, http_status=403) for _ in range(5)]
    out, _ = _run_dois(doc, monkeypatch, blocked)

    row = out.ledger[0]
    assert row.result is not True
    assert row.status != "ok"
    assert row.reason and "blocked" in row.reason


def test_one_blocked_among_unreachable_is_not_a_pass(monkeypatch) -> None:
    """A single 403 among four network failures used to suppress the errored
    path entirely and report the batch as passing."""
    doc = _doc_with_dois([f"10.1234/b{i}" for i in range(5)])
    answers = [
        Resolution(url="u", outcome=Outcome.unreachable, http_status=503) for _ in range(4)
    ] + [Resolution(url="u", outcome=Outcome.blocked, http_status=403)]
    out, _ = _run_dois(doc, monkeypatch, answers)

    row = out.ledger[0]
    assert row.result is not True
    assert row.status == "errored"


def test_all_unreachable_is_errored_not_a_citation_defect(monkeypatch) -> None:
    """#8 AC 2, the boundary the two tests above were breaking."""
    doc = _doc_with_dois([f"10.1234/c{i}" for i in range(3)])
    answers = [Resolution(url="u", outcome=Outcome.unreachable, http_status=503) for _ in range(3)]
    out, _ = _run_dois(doc, monkeypatch, answers)

    row = out.ledger[0]
    assert row.status == "errored"
    assert row.result is None
    assert "network failure" in row.reason


def test_one_confirmed_answer_is_enough_to_grade(monkeypatch) -> None:
    """The other side of it: a single conclusive answer means the check ran."""
    doc = _doc_with_dois(["10.1234/d0", "10.1234/d1"])
    answers = [
        Resolution(url="u", outcome=Outcome.not_found, http_status=404),
        Resolution(url="u", outcome=Outcome.blocked, http_status=403),
    ]
    out, _ = _run_dois(doc, monkeypatch, answers)

    row = out.ledger[0]
    assert row.status == "ok"
    assert row.result is False  # the 404 is a real, observed defect


# ---------------------------------------------------------------------------
# A coverage gap is "we don't know", and must not be cached as if it were (#8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome,status",
    [(Outcome.unreachable, 503), (Outcome.blocked, 403)],
)
def test_gap_outcomes_are_not_cached(tmp_path, monkeypatch, outcome, status) -> None:
    """A transient 503 cached for the 7-day TTL is served as settled fact long
    after the source recovers — indistinguishable from asserting it's dead."""
    calls: list[str] = []

    def fake_fetch(client, url):
        calls.append(url)
        return Resolution(url=url, outcome=outcome, http_status=status)

    monkeypatch.setattr(resolution_mod, "fetch_status", fake_fetch)
    ident = identifiers_in(_entry("A. Author. Title. doi:10.1234/gap"))[0]

    resolve_one(None, DiskCache(tmp_path), ident)
    resolve_one(None, DiskCache(tmp_path), ident)
    assert len(calls) == 2, "a non-answer was cached and replayed as fact"


def test_conclusive_outcomes_are_cached(tmp_path, monkeypatch) -> None:
    """The cache still has to do its job for answers that mean something."""
    calls: list[str] = []

    def fake_fetch(client, url):
        calls.append(url)
        return Resolution(url=url, outcome=Outcome.not_found, http_status=404)

    monkeypatch.setattr(resolution_mod, "fetch_status", fake_fetch)
    ident = identifiers_in(_entry("A. Author. Title. doi:10.1234/real"))[0]

    resolve_one(None, DiskCache(tmp_path), ident)
    resolve_one(None, DiskCache(tmp_path), ident)
    assert len(calls) == 1


def test_one_fetch_per_distinct_identifier(monkeypatch) -> None:
    """A paper cited in both the intro and the methods is two references
    sharing one DOI; resolving them in parallel raced past the cache."""
    doc = _doc_with_dois(["10.1234/shared", "10.1234/shared", "10.1234/other"])
    answers = [Resolution(url="u", outcome=Outcome.resolves, http_status=200) for _ in range(3)]
    out, calls = _run_dois(doc, monkeypatch, answers)

    assert len(calls) == 2, f"expected one call per distinct DOI, got {calls}"
    # Both references are still accounted for in the ledger.
    assert out.ledger[0].detail.startswith("3 / 3 resolved")


def test_concurrent_resolution_of_one_identifier_is_coalesced(monkeypatch) -> None:
    """The race made concrete: without dedup both threads miss the cold cache
    before either writes, and both fetch."""
    calls: list[str] = []
    lock = threading.Lock()

    def slow_fetch(client, url):
        with lock:
            calls.append(url)
        time.sleep(0.2)  # long enough that both would be in flight together
        return Resolution(url=url, outcome=Outcome.resolves, http_status=200)

    monkeypatch.setattr(resolution_mod, "fetch_status", slow_fetch)
    doc = _doc_with_dois(["10.1234/same", "10.1234/same"])
    run_resolution_check(
        doc,
        CheckContext(no_cache=True),
        check_id="all_dois_resolve",
        label="All DOIs resolve",
        kind="doi",
        noun="DOI",
        prefix="DOI",
    )
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Identifier scanning must not invent or hide defects (#8)
# ---------------------------------------------------------------------------


def test_valid_isbn_followed_by_a_year_is_not_reported_malformed() -> None:
    """ISBNs group with spaces, so the scan can't stop at whitespace — and a
    bibliography that doesn't punctuate between fields swept the year in,
    producing a 17-digit "malformed ISBN" from a perfectly good one."""
    ref = _entry("M. Delgado, Handbook of Civic Resilience. ISBN: 978-0-306-40615-7 2020")
    isbns = [i for i in identifiers_in(ref) if i.kind == "isbn"]
    assert [i.value for i in isbns] == ["9780306406157"]


def test_genuinely_bad_isbn_checksum_still_reported() -> None:
    """The trimming must not become a way to launder a real defect."""
    ref = _entry("M. Delgado, Handbook. ISBN: 978-0-306-40615-8")
    from slopchecker.checks.identifiers import valid

    isbn = next(i for i in identifiers_in(ref) if i.kind == "isbn")
    assert isbn.value == "9780306406158"
    assert not valid("isbn", isbn.value)


def test_six_digit_arxiv_suffix_is_reported_not_truncated() -> None:
    """Capping the scan at 5 digits silently rewrote "2107.043210" into
    "2107.04321" — a different, real paper. We'd have hidden the malformation
    and then reported another author's metadata against this reference."""
    from slopchecker.checks.identifiers import valid

    ref = _entry("A. Author, Title. arXiv:2107.043210")
    arxiv = next(i for i in identifiers_in(ref) if i.kind == "arxiv")
    assert arxiv.value == "2107.043210"
    assert not valid("arxiv", arxiv.value)


def test_identifier_span_points_at_its_own_occurrence() -> None:
    """Re-finding the raw text located the *first* match, so a DOI that is a
    substring of an earlier one got the earlier one's offset — the slice still
    matched, which is why it looked right from every direction but the span."""
    raw = "See 10.1234/abc.2020.1 and also 10.1234/abc.2020 for details"
    idents = {i.value: i for i in identifiers_in(_entry(raw))}
    shorter = idents["10.1234/abc.2020"]
    assert shorter.span is not None
    assert shorter.span.start == raw.rindex("10.1234/abc.2020")


# ---------------------------------------------------------------------------
# Quote anchoring (CLAUDE.md: every finding is quote-anchored)
# ---------------------------------------------------------------------------


def test_anchor_span_is_exact_for_an_indented_reference() -> None:
    """Hanging-indent bibliographies are routine. Stripping the quote without
    moving span.start kept the whitespace inside the span and chopped an equal
    number of real characters off the end."""
    text = "Intro.\n\nReferences\n   [1] Smith, J. (2020). A Title. A Venue. 10.12/bad\n"
    doc = FlattenedDoc(file="d.md", text=text)
    ref = extract_citations(text).references[0]

    anchor = anchor_for(doc, ref)
    assert anchor.span is not None
    assert text[anchor.span.start : anchor.span.end] == anchor.quote
    assert not anchor.quote.startswith(" ")


def test_anchor_span_is_exact_through_the_whole_check(monkeypatch) -> None:
    """The same property, end to end, on an indented reference list."""
    doc = _doc_with_dois(["10.1234/x0", "10.1234/x1"], indent="   ")
    answers = [Resolution(url="u", outcome=Outcome.not_found, http_status=404) for _ in range(2)]
    out, _ = _run_dois(doc, monkeypatch, answers)

    assert out.findings
    for finding in out.findings:
        span = finding.anchor.span
        assert doc.text[span.start : span.end] == finding.anchor.quote, finding.id


# ---------------------------------------------------------------------------
# Metadata comparison (#9)
# ---------------------------------------------------------------------------

CANONICAL = SourceRecord(
    provider="crossref",
    doi="10.1234/x",
    title="Attention Is All You Need",
    authors=("A. Vaswani",),
    surnames=("Vaswani",),
    year=2017,
    venue="NeurIPS",
)


def _ref_for(canonical: SourceRecord, **over) -> ReferenceEntry:
    fields = {
        "key": "1",
        "raw": "placeholder",
        "span": Span(start=0, end=11),
        "authors": [f"A. {canonical.surnames[0]}"],
        "year": canonical.year,
        "title": canonical.title,
        "venue": canonical.venue,
    }
    fields.update(over)
    return ReferenceEntry(**fields)


def test_negated_title_does_not_grade_as_a_clean_match() -> None:
    """One inserted word barely moves any ratio on a short title, so
    "Attention Is Not All You Need" scored 0.93 and passed as a match — while
    being the opposite paper. Exactly #9's headline failure mode."""
    assert title_similarity("Attention Is Not All You Need", CANONICAL.title) >= 0.90
    match = compare(_ref_for(CANONICAL, title="Attention Is Not All You Need"), CANONICAL)
    assert match.grade is not Grade.matches


def test_negation_check_does_not_fire_on_substrings() -> None:
    """ "non" must not match inside "nonlinear" — the guard is token-based."""
    canonical = SourceRecord(provider="p", title="Nonlinear dynamics of coupled systems")
    ref = _ref_for(CANONICAL, title="Nonlinear dynamics of coupled systems")
    assert compare(ref, canonical).grade is Grade.matches


@pytest.mark.parametrize("cited", ["Berg", "van der Berg", "Van Der Berg"])
def test_surname_particles_are_not_a_different_author(cited: str) -> None:
    """Half the world's bibliographies alphabetize "van der Berg" under B."""
    canonical = SourceRecord(provider="p", surnames=("van der Berg",), title="T")
    assert grade_author(cited, canonical) is Grade.matches


def test_compound_ordinary_sloppiness_stays_below_different_work() -> None:
    """Two individually-tolerated quirks — an em-dash subtitle and a dropped
    name particle — compounded into a "different work entirely" verdict on a
    correctly cited paper."""
    canonical = SourceRecord(
        provider="crossref",
        title="Civic resilience: a measurement framework",
        authors=("J. van der Berg",),
        surnames=("van der Berg",),
        year=2021,
        venue="Journal of Civic Studies",
    )
    ref = ReferenceEntry(
        key="1",
        raw="placeholder",
        span=Span(start=0, end=11),
        authors=["J. Berg"],
        year=2021,
        title="Civic resilience — a measurement framework",
        venue="Journal of Civic Studies",
    )
    match = compare(ref, canonical)
    assert not match.is_different_work, match.fields


def test_em_dash_subtitle_is_tolerated_like_a_colon() -> None:
    assert title_similarity("Civic resilience — a framework", "Civic resilience") >= 0.90


# ---------------------------------------------------------------------------
# Provider isolation (#9 AC 4 + "degrade to gaps, never crash")
# ---------------------------------------------------------------------------


class _Exploding:
    name = "exploding"

    def lookup(self, client, ident):
        raise RuntimeError("malformed payload")

    def search(self, client, **kwargs):
        raise RuntimeError("malformed payload")


class _Working:
    name = "working"

    def lookup(self, client, ident):
        return CANONICAL

    def search(self, client, **kwargs):
        return CANONICAL


def test_chain_falls_through_a_raising_provider() -> None:
    """MetadataProvider is a public Protocol, so the chain can't assume every
    implementation declines politely. An unhandled payload shape used to
    propagate out through the thread pool and kill the check for the whole
    document."""
    ident = identifiers_in(_entry("A. Author. Title. doi:10.1234/x"))[0]
    chain = ProviderChain(providers=[_Exploding(), _Working()])
    assert chain.lookup(None, ident) is CANONICAL


def test_chain_search_falls_through_a_raising_provider() -> None:
    chain = ProviderChain(providers=[_Exploding(), _Working()])
    assert chain.search(None, title="Attention Is All You Need") is CANONICAL


def test_chain_returns_none_when_every_provider_raises() -> None:
    """No record is a coverage gap, which the check already knows how to say."""
    ident = identifiers_in(_entry("A. Author. Title. doi:10.1234/x"))[0]
    assert ProviderChain(providers=[_Exploding()]).lookup(None, ident) is None
