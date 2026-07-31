"""Real ``SourceFetcher`` implementations for #10 (OA-only network sources).

Each fetcher exposes ``applies_to(ref)`` + ``fetch(ref)``; ``ChainFetcher``
routes by applicability with first-hit-wins semantics. All fetchers accept
an optional ``httpx.Client`` so tests can inject ``httpx.MockTransport``
and the suite stays fully offline.

Callers should almost always use ``build_default_fetcher()`` and wrap it
with ``CachingFetcher`` (from the parent module) for a disk cache.
"""

from slopchecker.pipeline.quotes.fetchers.arxiv import ArxivFetcher
from slopchecker.pipeline.quotes.fetchers.chain import (
    ApplicableFetcher,
    ChainFetcher,
    build_default_fetcher,
)
from slopchecker.pipeline.quotes.fetchers.doaj import DoajFetcher
from slopchecker.pipeline.quotes.fetchers.pmc import PmcOAFetcher
from slopchecker.pipeline.quotes.fetchers.url import UrlFetcher

__all__ = [
    "ApplicableFetcher",
    "ArxivFetcher",
    "ChainFetcher",
    "DoajFetcher",
    "PmcOAFetcher",
    "UrlFetcher",
    "build_default_fetcher",
]
