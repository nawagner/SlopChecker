"""Shared HTTP + text-extraction helpers for the #10 network fetchers.

Deliberately thin: one client factory, one HTML-to-text pass, one PDF
extraction pass, one best-effort GET. No retries — that ladder is #37's
job, and it wraps this layer rather than duplicating it.

The layer's contract: any transport error, any non-2xx, any parse failure
degrades to ``None``. Fetchers turn ``None`` into ``source_unavailable`` at
the ``SourceFetcher`` boundary (see ``pipeline/quotes/check.py``), never
into a false ``not_found``.
"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

import httpx

USER_AGENT = "SlopChecker/0.1 (+https://github.com/nawagner/SlopChecker)"
DEFAULT_TIMEOUT = 10.0

log = logging.getLogger(__name__)

# Tags whose content we drop entirely (chrome, scripts, side-nav).
_SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "head", "nav", "header", "footer", "aside"}
)
# Tags that force a line break in the extracted text (paragraph structure).
_BLOCK_TAGS = frozenset(
    {
        "p", "div", "section", "article", "li", "tr", "br",
        "h1", "h2", "h3", "h4", "h5", "h6",
    }
)


def build_client(client: httpx.Client | None = None) -> httpx.Client:
    """Return the caller's client or a polite default one.

    Passing a client is the seam tests use to inject ``httpx.MockTransport``
    — no monkeypatching, no real network in the suite.
    """
    if client is not None:
        return client
    return httpx.Client(
        timeout=DEFAULT_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


class _TextExtractor(HTMLParser):
    """Strip HTML to plain text, dropping script/style/nav/etc."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._out.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._out.append(data)

    def as_text(self) -> str:
        raw = "".join(self._out)
        lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in raw.splitlines()]
        # Collapse runs of blank lines but keep one as paragraph separator.
        out: list[str] = []
        blank = False
        for ln in lines:
            if ln:
                out.append(ln)
                blank = False
            elif not blank:
                out.append("")
                blank = True
        return "\n".join(out).strip()


def html_to_text(html: str) -> str:
    """Strip HTML markup to plain text; keep paragraph breaks."""
    parser = _TextExtractor()
    parser.feed(html)
    return parser.as_text()


def pdf_to_text(pdf_bytes: bytes) -> str | None:
    """Extract text from a PDF via pymupdf, or ``None`` if unavailable.

    pymupdf is an optional extra (``[pdf]``); without it, PDF-only sources
    degrade to ``source_unavailable`` rather than failing the run.
    """
    try:
        import pymupdf  # type: ignore[import-not-found]
    except ImportError:
        log.info("pdf_to_text: pymupdf not installed; treating source as unavailable")
        return None
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            pages = [page.get_text() for page in doc]
    except Exception as exc:  # pymupdf raises RuntimeError on garbage input
        log.warning("pdf_to_text: extraction failed: %s", exc)
        return None
    text = "\n\n".join(p for p in pages if p).strip()
    return text or None


def content_type(response: httpx.Response) -> str:
    """Bare content-type (no charset), lowercased."""
    return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def safe_get(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, str] | None = None,
    accept: str | None = None,
) -> httpx.Response | None:
    """Best-effort GET: any transport error or non-2xx returns ``None``.

    A 404/410 and a bot-wall (403/429) look the same at this layer — both
    mean "we couldn't retrieve OA text." The check layer turns that into a
    skipped check with a reason.
    """
    headers = {"Accept": accept} if accept else None
    try:
        response = client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        log.info("safe_get %s: transport error %s", url, exc)
        return None
    if response.status_code >= 400:
        log.info("safe_get %s: HTTP %s", url, response.status_code)
        return None
    return response
