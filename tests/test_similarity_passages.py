"""Tests for shared-passage extraction (#14).

The similarity check needs a quote-anchored ``Finding`` per near-neighbour
pair. That means: given two docs above threshold, find a verbatim passage
from doc A that also appears in doc B, and return its exact char span in
A.text so ``Anchor.quote`` is mechanically grounded per the data model.
"""

from __future__ import annotations

from slopchecker.similarity.passages import shared_passage


def _find(needle: str, haystack: str) -> tuple[int, int]:
    """Char span of ``needle`` in ``haystack``, half-open."""
    i = haystack.index(needle)
    return i, i + len(needle)


class TestSharedPassage:
    def test_returns_shared_phrase_verbatim(self) -> None:
        # 8 tokens of shared prose, embedded in different surrounding text.
        shared = (
            "policymakers should prioritize investments in early-childhood education programs today"
        )
        a = f"In summary, {shared} at every level."
        b = f"The report argues that {shared} across the country."
        result = shared_passage(a, b, k=5)
        assert result is not None
        assert result.quote in a  # verbatim substring
        # The shared phrase should be the anchored quote (whole or a chunk).
        assert shared in result.quote or result.quote in shared

    def test_span_points_at_the_quote_in_a(self) -> None:
        shared = (
            "policymakers should prioritize investments in early-childhood education programs today"
        )
        a = f"In summary, {shared} at every level."
        b = f"The report argues that {shared} across the country."
        result = shared_passage(a, b, k=5)
        assert result is not None
        assert a[result.span_start : result.span_end] == result.quote

    def test_picks_longest_shared_run(self) -> None:
        # Two shared runs of unequal length — should return the longer one.
        long_run = "the quick brown fox jumps over the lazy dog on a sunny afternoon"
        short_run = "a very special number indeed"
        a = f"Introduction. {long_run} Later, {short_run}. End."
        b = f"Prologue. {short_run}, and also: {long_run}. Fin."
        result = shared_passage(a, b, k=5)
        assert result is not None
        # The long run should dominate; the returned quote should contain it or
        # be equal to it (may include leading/trailing shingle overlap).
        assert long_run in result.quote

    def test_returns_none_when_no_shingle_overlap(self) -> None:
        a = "Photosynthesis converts sunlight into chemical energy in green plants."
        b = "The Roman Empire fell in the fifth century after Christ."
        assert shared_passage(a, b, k=5) is None

    def test_preserves_original_case_in_quote(self) -> None:
        # Shingles are lowercased for matching, but the returned quote must be
        # the verbatim slice from A (so the anchor shows what the reviewer will
        # actually see in the source).
        shared_lower = "the framework guides funding officers toward better decisions overall"
        shared_original = "The framework guides funding officers toward better decisions overall"
        a = f"Preamble. {shared_original} in every review."
        b = (
            "THE FRAMEWORK GUIDES FUNDING OFFICERS TOWARD BETTER DECISIONS OVERALL."
            " Some other text here about something entirely different."
        )
        result = shared_passage(a, b, k=5)
        assert result is not None
        assert shared_original in result.quote  # original case preserved
        assert shared_lower not in a  # sanity: only the capitalized form is in A

    def test_short_matching_run_still_returned(self) -> None:
        # Two docs sharing just enough for one k-shingle to match — should
        # still return the shingle-length passage.
        a = (
            "totally unrelated intro material some more text"
            " alpha beta gamma delta epsilon and now a swerve to fresh material"
        )
        b = (
            "different opening context"
            " alpha beta gamma delta epsilon and completely different close"
        )
        result = shared_passage(a, b, k=5)
        assert result is not None
        assert "alpha beta gamma delta epsilon" in result.quote.lower()
