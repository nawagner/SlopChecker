"""Quote checking (#10): matching engine + OA source fetchers."""

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
from slopchecker.pipeline.quotes.fetchers import (
    ArxivFetcher,
    ChainFetcher,
    DoajFetcher,
    PmcOAFetcher,
    UrlFetcher,
    build_default_fetcher,
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
    "ArxivFetcher",
    "CachingFetcher",
    "ChainFetcher",
    "DoajFetcher",
    "FragmentMatch",
    "LocalFileFetcher",
    "PmcOAFetcher",
    "QuoteMatch",
    "QuoteStatus",
    "QuotedPassage",
    "SourceFetcher",
    "UrlFetcher",
    "build_default_fetcher",
    "check_quotes",
    "find_quoted_passages",
    "match_quote",
    "nearest_citation",
    "source_keys",
    "split_fragments",
]
