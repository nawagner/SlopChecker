"""DOAJ fetcher: verify OA status by DOI, then follow the fulltext URL.

DOAJ (Directory of Open Access Journals) doesn't host full text — it
indexes OA articles and links out to publisher-hosted full text. That
makes it useful here as an *OA gate*: if DOAJ knows the DOI, we know the
article is OA-licensed and it's safe to follow its ``fulltext`` link. If
DOAJ doesn't know the DOI, we don't try — that keeps us off paywalled
sites entirely (see #10: no paywall circumvention).
"""

from __future__ import annotations

import httpx

from slopchecker.pipeline.citations.models import ReferenceEntry
from slopchecker.pipeline.quotes.fetchers._http import (
    build_client,
    content_type,
    html_to_text,
    pdf_to_text,
    safe_get,
)

_DOAJ_SEARCH = "https://doaj.org/api/search/articles/doi:"


class DoajFetcher:
    """Look a DOI up in DOAJ; follow its fulltext link when found."""

    def __init__(self, client: httpx.Client | None = None):
        self._client = build_client(client)

    @staticmethod
    def applies_to(ref: ReferenceEntry) -> bool:
        return bool(ref.doi)

    def fetch(self, ref: ReferenceEntry) -> str | None:
        if not ref.doi:
            return None
        fulltext_url = self._doaj_fulltext_url(ref.doi)
        if fulltext_url is None:
            return None
        return _fetch_and_extract(self._client, fulltext_url)

    def _doaj_fulltext_url(self, doi: str) -> str | None:
        response = safe_get(self._client, f"{_DOAJ_SEARCH}{doi}")
        if response is None:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        results = payload.get("results") or []
        if not results:
            return None
        links = results[0].get("bibjson", {}).get("link") or []
        for link in links:
            if link.get("type") == "fulltext" and link.get("url"):
                return link["url"]
        return None


def _fetch_and_extract(client: httpx.Client, url: str) -> str | None:
    """GET ``url`` and reduce to plain text; understand HTML, PDF, text/*."""
    response = safe_get(client, url)
    if response is None:
        return None
    ctype = content_type(response)
    if ctype == "text/html":
        text = html_to_text(response.text)
        return text or None
    if ctype == "application/pdf":
        return pdf_to_text(response.content)
    if ctype.startswith("text/"):
        return response.text or None
    return None
