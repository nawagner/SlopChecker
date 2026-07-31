"""Shared-passage extraction for quote-anchored findings (#14).

Given two documents A and B, ``shared_passage(a, b, k)`` returns the longest
verbatim run in A whose k-word shingles all appear as k-word shingles of B.
The returned quote is sliced from A.text (original case, original whitespace),
with its char span so the ``Anchor`` can pin exact offsets.

Method: tokenize A into (token, char_start, char_end) triples; slide a k-window
across A's tokens forming the same lowercased single-space shingle strings
``word_shingles`` uses; check membership in the precomputed set of B's shingles;
runs of consecutive matches merge into one span. This mirrors the shingling used
to build the MinHash — so a positive here is by construction a shared shingle,
not a MinHash false positive.
"""

from __future__ import annotations

from dataclasses import dataclass

from slopchecker.similarity.shingles import WORD_RE, word_shingles


@dataclass(frozen=True)
class SharedPassage:
    """A verbatim passage from doc A that also appears in doc B (as shingles).

    ``quote`` is the exact slice ``a[span_start:span_end]``. Case and internal
    whitespace are preserved so the reviewer sees what's actually in A.
    """

    quote: str
    span_start: int
    span_end: int


def _tokenize_with_spans(text: str) -> list[tuple[str, int, int]]:
    """Return ``(lowercased_token, start, end)`` triples.

    Uses the same word-token regex as ``shingles.tokenize`` so shingle strings
    computed here match those in ``word_shingles(b)`` exactly.
    """
    return [(m.group(0).lower(), m.start(), m.end()) for m in WORD_RE.finditer(text)]


def shared_passage(a: str, b: str, k: int = 5) -> SharedPassage | None:
    """Longest verbatim run in ``a`` whose k-word shingles all appear in ``b``.

    Returns ``None`` when no k-shingle is shared. Ties among equally-long runs
    break toward the earliest occurrence in A, which is deterministic and puts
    the anchor near the top of the doc.
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")

    b_shingles = word_shingles(b, k=k)
    if not b_shingles:
        return None

    tokens_a = _tokenize_with_spans(a)
    if not tokens_a:
        return None

    # Short-A case (fewer than k tokens): shingle is the whole doc; either it
    # matches B or nothing does.
    if len(tokens_a) < k:
        whole = " ".join(tok for tok, _, _ in tokens_a)
        if whole in b_shingles:
            start = tokens_a[0][1]
            end = tokens_a[-1][2]
            return SharedPassage(quote=a[start:end], span_start=start, span_end=end)
        return None

    # Positions i where the k-window tokens_a[i:i+k] forms a shingle present in
    # B. Consecutive matched positions describe an overlap-merged run.
    matches: list[int] = []
    for i in range(len(tokens_a) - k + 1):
        shingle = " ".join(tok for tok, _, _ in tokens_a[i : i + k])
        if shingle in b_shingles:
            matches.append(i)

    if not matches:
        return None

    # Group matches into runs of consecutive integers, then pick the longest.
    best: tuple[int, int] | None = None  # (first_match_i, last_match_i)
    run_start = matches[0]
    prev = matches[0]
    for m in matches[1:]:
        if m == prev + 1:
            prev = m
            continue
        # Close the previous run.
        if best is None or (prev - run_start) > (best[1] - best[0]):
            best = (run_start, prev)
        run_start = m
        prev = m
    # Close the final run.
    if best is None or (prev - run_start) > (best[1] - best[0]):
        best = (run_start, prev)

    first_i, last_i = best
    # Char span: from the start of tokens_a[first_i] to the end of the last
    # token in the last window, which is tokens_a[last_i + k - 1].
    start = tokens_a[first_i][1]
    end = tokens_a[last_i + k - 1][2]
    return SharedPassage(quote=a[start:end], span_start=start, span_end=end)
