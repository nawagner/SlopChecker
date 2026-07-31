"""Plain-URL fetcher: gray literature (blog posts, gov reports, preprints).

Last-resort fetcher for references that carry only a ``url``. We do a
plain HTTP GET (no cookies, no auth, no captcha solving), and extract text
from HTML or PDF responses. A 403/429/paywall body reads as
``source_unavailable`` — we don't circumvent paywalls (#10). Whether the
URL genuinely serves gray literature or a paywalled paper is left to the
publisher's response.
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


class UrlFetcher:
    """Fetch and extract text from a reference's plain URL."""

    def __init__(self, client: httpx.Client | None = None):
        self._client = build_client(client)

    @staticmethod
    def applies_to(ref: ReferenceEntry) -> bool:
        return bool(ref.url)

    def fetch(self, ref: ReferenceEntry) -> str | None:
        if not ref.url:
            return None
        response = safe_get(self._client, ref.url)
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
