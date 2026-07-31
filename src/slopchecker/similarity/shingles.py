"""Text -> hashable k-shingles for MinHash signing (#14).

Two flavours, both returning ``set[str]`` (MinHash sees each unique shingle once):

- ``word_shingles`` — k consecutive word-tokens, lowercased, punctuation stripped.
  Preferred for medium/long documents (grants, reports); robust to punctuation
  and whitespace variations (matches "overall" with "overall.").
- ``char_shingles`` — n consecutive characters, lowercased. Preferred for
  shorter documents (blog posts) or when we want to catch light rewrites that
  preserve character-level structure.

Short-text policy: a document with fewer than k tokens (or n chars) returns a
single shingle wrapping the whole thing, rather than an empty set. An empty
signature would make short documents collide with each other and with any other
short document — a worse failure mode than a slightly under-informative
signature.

Empty or whitespace-only input returns ``set()`` — the caller can then emit a
skipped/errored ledger row rather than silently signing garbage.
"""

from __future__ import annotations

import re

# Word tokens for shingling: Unicode word chars, no punctuation. Sharing this
# regex with ``passages._tokenize_with_spans`` keeps membership checks aligned.
WORD_RE = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Lowercased word tokens (no punctuation) — the shingle vocabulary."""
    return WORD_RE.findall(text.lower())


def word_shingles(text: str, k: int = 5) -> set[str]:
    """Return the set of ``k``-word shingles in ``text``.

    Tokens are Unicode word runs (``\\w+``) from the lowercased text — punctuation
    is stripped so "overall" and "overall." shingle to the same thing. Duplicate
    shingles are deduped by the set. Text with fewer than ``k`` tokens yields a
    single shingle containing all available tokens.
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    tokens = tokenize(text)
    if not tokens:
        return set()
    if len(tokens) < k:
        return {" ".join(tokens)}
    return {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def char_shingles(text: str, n: int = 9) -> set[str]:
    """Return the set of character ``n``-shingles in ``text``.

    Text is lowercased first. Text shorter than ``n`` chars yields a single
    shingle of the lowercased whole text. Empty text yields the empty set.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    low = text.lower()
    if not low:
        return set()
    if len(low) < n:
        return {low}
    return {low[i : i + n] for i in range(len(low) - n + 1)}
