"""arXiv fetcher: OA HTML full text, PDF fallback via pymupdf.

arXiv publishes HTML full text at ``https://arxiv.org/html/{arxiv_id}`` for
LaTeX-source papers (most 2023+ submissions). Older papers only exist as
PDF at ``https://arxiv.org/pdf/{arxiv_id}.pdf``; we extract those via
pymupdf when it's installed. Either endpoint is pure OA — no auth, no
paywall. If both fail (or pymupdf is missing for a PDF-only paper), we
return ``None`` and the check layer degrades to ``source_unavailable``.
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


class ArxivFetcher:
    """Fetch OA full text from arXiv when the reference carries an arxiv_id."""

    def __init__(self, client: httpx.Client | None = None):
        self._client = build_client(client)

    @staticmethod
    def applies_to(ref: ReferenceEntry) -> bool:
        return bool(ref.arxiv_id)

    def fetch(self, ref: ReferenceEntry) -> str | None:
        if not ref.arxiv_id:
            return None
        text = self._try_html(ref.arxiv_id)
        if text:
            return text
        return self._try_pdf(ref.arxiv_id)

    def _try_html(self, arxiv_id: str) -> str | None:
        response = safe_get(
            self._client,
            f"https://arxiv.org/html/{arxiv_id}",
            accept="text/html",
        )
        if response is None or content_type(response) != "text/html":
            return None
        text = html_to_text(response.text)
        return text or None

    def _try_pdf(self, arxiv_id: str) -> str | None:
        response = safe_get(
            self._client,
            f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            accept="application/pdf",
        )
        if response is None:
            return None
        return pdf_to_text(response.content)
