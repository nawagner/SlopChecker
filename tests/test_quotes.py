"""Tests for #10: quote matching engine + check layer. Fully offline.

The retrieval half of #10 is deliberately stubbed: tests use
``LocalFileFetcher`` over ``tests/fixtures/sources/`` (fabricated docs).
The invariant under test throughout: an uncheckable quote is a *skipped*
check (``source_unavailable``), never a pass and never a plain fail.
"""

from __future__ import annotations

from pathlib import Path

from slopchecker.pipeline.citations import extract_citations
from slopchecker.pipeline.quotes import (
    CachingFetcher,
    LocalFileFetcher,
    QuoteStatus,
    check_quotes,
    find_quoted_passages,
    match_quote,
    split_fragments,
)

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = FIXTURES / "sources"

SOURCE = (
    "The committee found — after two “contentious” sessions — that the\n"
    "proposal understated its maintenance burden, and that the stated\n"
    "timeline was optimistic by roughly a factor of two.\n"
)


# ------------------------------------------------------------ match_quote


def test_verbatim_match_survives_normalization():
    # straight quotes, collapsed whitespace, hyphen for em-dash in the quote
    m = match_quote('found - after two "contentious" sessions', SOURCE)
    assert m.status is QuoteStatus.found_verbatim
    assert m.score == 1.0
    assert m.span is not None
    assert "contentious" in m.window


def test_minor_variation_scores_below_one():
    # one-word edit ("understates" for "understated") in a sentence-length quote
    m = match_quote(
        "the proposal understates its maintenance burden, and that the stated "
        "timeline was optimistic",
        SOURCE,
    )
    assert m.status is QuoteStatus.found_minor_variation
    assert 0.85 <= m.score < 1.0
    assert m.window is not None


def test_not_found_is_not_found():
    m = match_quote("the proposal was praised for its fiscal restraint", SOURCE)
    assert m.status is QuoteStatus.not_found
    assert m.score < 0.85
    assert m.span is None and m.window is None


def test_ellipsis_fragments_match_in_order():
    m = match_quote("the committee found ... optimistic by roughly a factor of two", SOURCE)
    assert m.status is QuoteStatus.found_verbatim
    assert len(m.fragments) == 2
    assert all(f.found for f in m.fragments)
    # window spans from first fragment to last
    assert m.window.startswith("The committee found")
    assert m.window.rstrip().endswith("factor of two")


def test_ellipsis_fragments_out_of_order_fail():
    m = match_quote("a factor of two ... the committee found", SOURCE)
    assert m.status is QuoteStatus.not_found


def test_sic_and_editorial_brackets_are_stripped():
    assert split_fragments("timeline was optimistic [sic] by roughly") == [
        "timeline was optimistic by roughly"
    ]
    assert split_fragments("[T]he committee found") == ["The committee found"]
    m = match_quote("the stated timeline was optimistic [sic] by roughly a factor of two", SOURCE)
    assert m.status is QuoteStatus.found_verbatim


def test_match_quote_never_says_source_unavailable():
    # that status belongs to the check layer; empty source is just not_found
    assert match_quote("anything at all here", "").status is QuoteStatus.not_found


# --------------------------------------------------- passages and check layer


def test_find_quoted_passages_spans_are_verbatim():
    text = (FIXTURES / "citations" / "apa.txt").read_text()
    passages = find_quoted_passages(text)
    assert len(passages) == 2
    for p in passages:
        assert text[p.span.start : p.span.end] == p.text


def test_check_quotes_end_to_end_apa():
    text = (FIXTURES / "citations" / "apa.txt").read_text()
    findings = check_quotes(text, extract_citations(text), LocalFileFetcher(SOURCES))
    assert len(findings) == 2
    smith, delacroix = findings

    assert smith.evidence["source_ref"] == "smith-2021"
    assert smith.evidence["quote_status"] == "found_verbatim"
    assert smith.checks[0].name == "quote_in_source"
    assert smith.checks[0].result is True
    assert smith.checks[1].name == "quote_match_score"
    assert smith.checks[1].result == 1.0

    # ellipsis-spanning quote, matched fragment-by-fragment in order
    assert delacroix.evidence["source_ref"] == "delacroix-2023"
    assert delacroix.evidence["quote_status"] == "found_verbatim"
    assert delacroix.checks[0].result is True
    # report carries only the matched window, not the full source text
    full_source = (SOURCES / "doi-10.1234_jams.2023.0142.txt").read_text()
    assert delacroix.evidence["matched_window"] in full_source
    assert len(delacroix.evidence["matched_window"]) < len(full_source)


def test_check_quotes_minor_variation_chicago():
    text = (FIXTURES / "citations" / "chicago.txt").read_text()
    findings = check_quotes(text, extract_citations(text), LocalFileFetcher(SOURCES))
    assert len(findings) == 1
    f = findings[0]
    assert f.evidence["source_ref"] == "whitfield-2020"
    assert f.evidence["quote_status"] == "found_minor_variation"
    assert f.checks[0].result is True
    assert 0.85 <= f.checks[1].result < 1.0


def test_unavailable_source_is_skipped_never_a_result(tmp_path):
    text = (FIXTURES / "citations" / "apa.txt").read_text()
    for fetcher in (None, LocalFileFetcher(tmp_path / "empty")):
        findings = check_quotes(text, extract_citations(text), fetcher)
        assert len(findings) == 2
        for f in findings:
            assert f.evidence["quote_status"] == "source_unavailable"
            [check] = f.checks
            assert check.status == "skipped"
            assert check.result is None
            assert check.reason


def test_fabricated_quote_is_found_false():
    text = (
        'Smith claims that "the effect is permanent and requires no further '
        'exposure of any kind" (Smith, 2021).\n\n'
        "References\n\n"
        "Smith, J. (2021). Inoculation theory in synthetic media environments. "
        "arXiv:2107.04321.\n"
    )
    findings = check_quotes(text, extract_citations(text), LocalFileFetcher(SOURCES))
    assert len(findings) == 1
    f = findings[0]
    assert f.evidence["quote_status"] == "not_found"
    assert f.checks[0].result is False
    assert "matched_window" not in f.evidence


def test_caching_fetcher_hits_disk_once(tmp_path):
    text = (FIXTURES / "citations" / "apa.txt").read_text()
    ref = next(r for r in extract_citations(text).references if r.key == "smith-2021")

    calls = []

    class CountingFetcher:
        def fetch(self, r):
            calls.append(r.key)
            return "counted source text"

    fetcher = CachingFetcher(CountingFetcher(), tmp_path / "cache")
    assert fetcher.fetch(ref) == "counted source text"
    assert fetcher.fetch(ref) == "counted source text"
    assert calls == ["smith-2021"]
    # cache is keyed by the most specific identifier (arXiv ID here)
    assert (tmp_path / "cache" / "arxiv-2107.04321.txt").is_file()
