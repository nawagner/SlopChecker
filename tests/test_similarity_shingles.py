"""Tests for shingling — text → hashable k-shingles for MinHash (#14)."""

from __future__ import annotations

from slopchecker.similarity.shingles import char_shingles, word_shingles


class TestWordShingles:
    def test_returns_correct_count_for_medium_text(self) -> None:
        # 7 tokens, k=5 → 7-5+1 = 3 shingles
        s = word_shingles("one two three four five six seven", k=5)
        assert len(s) == 3

    def test_respects_k_parameter(self) -> None:
        s3 = word_shingles("one two three four five", k=3)
        s2 = word_shingles("one two three four five", k=2)
        assert len(s3) == 3  # 5-3+1
        assert len(s2) == 4  # 5-2+1

    def test_returns_set_of_strings(self) -> None:
        # MinHash consumes a set of hashable items — verify the type and
        # that each shingle is a joined string, not a tuple/list.
        s = word_shingles("alpha beta gamma delta epsilon", k=3)
        assert isinstance(s, set)
        assert all(isinstance(sh, str) for sh in s)
        assert "alpha beta gamma" in s
        assert "beta gamma delta" in s
        assert "gamma delta epsilon" in s

    def test_normalizes_whitespace_and_case(self) -> None:
        a = word_shingles("Foo  bar\nbaz qux quux", k=3)
        b = word_shingles("foo bar baz qux quux", k=3)
        assert a == b

    def test_short_text_returns_single_shingle_of_whole_text(self) -> None:
        # A doc shorter than k words still needs a signature — otherwise
        # every short blog post has an empty signature and collides.
        s = word_shingles("one two three", k=5)
        assert s == {"one two three"}

    def test_empty_text_returns_empty_set(self) -> None:
        assert word_shingles("", k=5) == set()
        assert word_shingles("   \n  ", k=5) == set()

    def test_dedups_repeated_shingles_within_doc(self) -> None:
        # "a b a b a" k=2 → shingles are "a b", "b a", "a b", "b a", "a b"
        # After dedup: 2 unique shingles.
        s = word_shingles("a b a b a", k=2)
        assert s == {"a b", "b a"}


class TestCharShingles:
    def test_returns_correct_count_for_medium_text(self) -> None:
        # "abcdefghij" (10 chars) with n=9 → 10-9+1 = 2 shingles
        s = char_shingles("abcdefghij", n=9)
        assert len(s) == 2

    def test_returns_set_of_strings(self) -> None:
        s = char_shingles("hello world", n=5)
        assert isinstance(s, set)
        assert all(isinstance(sh, str) and len(sh) == 5 for sh in s)

    def test_normalizes_case(self) -> None:
        assert char_shingles("Hello World", n=5) == char_shingles("hello world", n=5)

    def test_short_text_returns_single_shingle_of_whole_text(self) -> None:
        s = char_shingles("abc", n=9)
        assert s == {"abc"}

    def test_empty_text_returns_empty_set(self) -> None:
        assert char_shingles("", n=9) == set()

    def test_dedups_repeated_shingles_within_doc(self) -> None:
        # "ababab" with n=2 → "ab", "ba", "ab", "ba", "ab" → {"ab", "ba"}
        s = char_shingles("ababab", n=2)
        assert s == {"ab", "ba"}
