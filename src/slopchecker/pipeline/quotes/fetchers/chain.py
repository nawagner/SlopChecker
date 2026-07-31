"""Chain fetchers by applicability; first non-None wins.

Order matters: more-specific / more-trusted OA sources first, so the
plain-URL fetcher never fires against a URL we could have served through
arXiv or PMC (which are known-OA and give us cleaner text).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx

from slopchecker.pipeline.citations.models import ReferenceEntry
from slopchecker.pipeline.quotes.fetchers.arxiv import ArxivFetcher
from slopchecker.pipeline.quotes.fetchers.doaj import DoajFetcher
from slopchecker.pipeline.quotes.fetchers.pmc import PmcOAFetcher
from slopchecker.pipeline.quotes.fetchers.url import UrlFetcher


@runtime_checkable
class ApplicableFetcher(Protocol):
    """A SourceFetcher that also decides for itself when to engage."""

    def applies_to(self, ref: ReferenceEntry) -> bool: ...
    def fetch(self, ref: ReferenceEntry) -> str | None: ...


class ChainFetcher:
    """Try each fetcher whose ``applies_to`` returns True; first hit wins."""

    def __init__(self, fetchers: list[ApplicableFetcher]):
        self._fetchers = fetchers

    def fetch(self, ref: ReferenceEntry) -> str | None:
        for fetcher in self._fetchers:
            if not fetcher.applies_to(ref):
                continue
            text = fetcher.fetch(ref)
            if text is not None:
                return text
        return None


def build_default_fetcher(
    client: httpx.Client | None = None,
    email: str | None = None,
) -> ChainFetcher:
    """The standard wiring for #10 callers.

    Order: arXiv (most specific, cleanest text), PMC-OA (verified OA
    subset), DOAJ (OA index), plain URL (last resort for gray literature).
    Wrap this with ``CachingFetcher`` for a disk cache across runs.
    """
    return ChainFetcher(
        [
            ArxivFetcher(client=client),
            PmcOAFetcher(client=client, email=email),
            DoajFetcher(client=client),
            UrlFetcher(client=client),
        ]
    )
