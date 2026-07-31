"""Quote checking (#10): matching engine + stubbed retrieval interface."""

from slopchecker.pipeline.quotes.check import (
    QuotedPassage,
    check_quotes,
    find_quoted_passages,
    nearest_citation,
)
from slopchecker.pipeline.quotes.fetch import (
    CachingFetcher,
    LocalFileFetcher,
    SourceFetcher,
    source_keys,
)
from slopchecker.pipeline.quotes.matching import (
    FUZZY_THRESHOLD,
    FragmentMatch,
    QuoteMatch,
    QuoteStatus,
    match_quote,
    split_fragments,
)

__all__ = [
    "FUZZY_THRESHOLD",
    "CachingFetcher",
    "FragmentMatch",
    "LocalFileFetcher",
    "QuoteMatch",
    "QuoteStatus",
    "QuotedPassage",
    "SourceFetcher",
    "check_quotes",
    "find_quoted_passages",
    "match_quote",
    "nearest_citation",
    "source_keys",
    "split_fragments",
]
