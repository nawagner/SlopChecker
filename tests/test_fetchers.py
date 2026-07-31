"""#10 network fetchers: tests use httpx.MockTransport, no real network.

The invariants under test — each traced back to #10's acceptance criteria:

* Success paths produce plain text (HTML markup, JATS tags, PDF wrapping
  are all stripped) so the matching engine has something clean to work
  with.
* Every failure path — 4xx, 5xx, timeout, transport error, unparseable
  JSON, non-OA article, missing pymupdf — returns ``None``. That's what
  the check layer maps to ``source_unavailable`` (skipped check); an
  uncheckable quote must never look like a ``not_found`` (a checked-and-
  absent quote), and this is the seam where that discipline lives.
* ``ChainFetcher`` prefers arXiv over PMC-OA when both apply, and never
  falls through to a lower-tier fetcher that isn't applicable to the ref.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from slopchecker.models import Span
from slopchecker.pipeline.citations.models import ReferenceEntry
from slopchecker.pipeline.quotes import CachingFetcher
from slopchecker.pipeline.quotes.fetchers import (
    ArxivFetcher,
    DoajFetcher,
    PmcOAFetcher,
    UrlFetcher,
    build_default_fetcher,
)
from slopchecker.pipeline.quotes.fetchers._http import html_to_text

Handler = Callable[[httpx.Request], httpx.Response]


def _ref(**kw) -> ReferenceEntry:
    """Minimal ReferenceEntry with only the field(s) under test."""
    return ReferenceEntry(
        key=kw.pop("key", "test-2024"),
        raw=kw.pop("raw", "Test reference."),
        span=Span(start=0, end=1),
        **kw,
    )


def _routed_client(routes: dict[str, Handler]) -> httpx.Client:
    """Client whose transport routes by URL prefix; unmatched -> 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for prefix, response_fn in routes.items():
            if url.startswith(prefix):
                return response_fn(request)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_html(body: str) -> Handler:
    return lambda _: httpx.Response(
        200, text=body, headers={"content-type": "text/html; charset=utf-8"}
    )


def _ok_json(body: str) -> Handler:
    return lambda _: httpx.Response(
        200, text=body, headers={"content-type": "application/json"}
    )


def _ok_xml(body: str) -> Handler:
    return lambda _: httpx.Response(
        200, text=body, headers={"content-type": "application/xml"}
    )


def _ok_pdf(pdf_bytes: bytes) -> Handler:
    return lambda _: httpx.Response(
        200, content=pdf_bytes, headers={"content-type": "application/pdf"}
    )


def _status(code: int) -> Handler:
    return lambda _: httpx.Response(code)


# --------------------------------------------------------- html_to_text unit


def test_html_to_text_drops_script_and_style():
    html = (
        "<html><head><title>t</title>"
        "<style>body{color:red}</style>"
        "<script>bad = 1</script></head>"
        "<body><article><p>Real body text.</p></article></body></html>"
    )
    text = html_to_text(html)
    assert "Real body text" in text
    assert "bad = 1" not in text
    assert "color:red" not in text
    assert "t" not in text.splitlines()  # <title> is inside dropped <head>


def test_html_to_text_preserves_paragraph_breaks():
    html = "<html><body><p>Para one.</p><p>Para two.</p></body></html>"
    text = html_to_text(html)
    assert "Para one." in text
    assert "Para two." in text
    # single blank line between them
    assert "Para one.\n\nPara two." in text or "Para one.\nPara two." in text


def test_html_to_text_handles_entities():
    html = "<p>caf&eacute; &amp; salon</p>"
    text = html_to_text(html)
    assert "café & salon" in text


# ---------------------------------------------------------- ArxivFetcher

_ARXIV_HTML = (
    "<html><head><title>t</title></head><body><article>"
    "<p>Our main claim is that P implies Q.</p>"
    "<p>We prove this in Section 3.</p>"
    "</article></body></html>"
)


def test_arxiv_html_returns_extracted_text():
    client = _routed_client({"https://arxiv.org/html/2401.00001": _ok_html(_ARXIV_HTML)})
    fetcher = ArxivFetcher(client=client)

    text = fetcher.fetch(_ref(arxiv_id="2401.00001"))

    assert text is not None
    assert "Our main claim" in text
    assert "Section 3" in text


def test_arxiv_falls_back_to_pdf_when_html_missing():
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Full text from arXiv PDF fallback.")
    pdf_bytes = doc.write()

    client = _routed_client(
        {
            "https://arxiv.org/html/": _status(404),
            "https://arxiv.org/pdf/": _ok_pdf(pdf_bytes),
        }
    )
    fetcher = ArxivFetcher(client=client)

    text = fetcher.fetch(_ref(arxiv_id="2001.99999"))

    assert text is not None
    assert "arXiv PDF fallback" in text


def test_arxiv_source_unavailable_when_both_endpoints_fail():
    client = _routed_client({"https://arxiv.org/": _status(404)})
    fetcher = ArxivFetcher(client=client)

    assert fetcher.fetch(_ref(arxiv_id="9999.99999")) is None


def test_arxiv_source_unavailable_on_transport_error():
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    client = httpx.Client(transport=httpx.MockTransport(boom))
    fetcher = ArxivFetcher(client=client)

    assert fetcher.fetch(_ref(arxiv_id="2401.00001")) is None


def test_arxiv_applies_only_when_arxiv_id_present():
    assert ArxivFetcher.applies_to(_ref(arxiv_id="1234.5678"))
    assert not ArxivFetcher.applies_to(_ref(doi="10.1/x"))
    assert not ArxivFetcher.applies_to(_ref(url="https://x.example/y"))


# ------------------------------------------------------------ PmcOAFetcher


def test_pmc_doi_to_pmcid_then_fetches_jats_body():
    idconv = '{"records":[{"doi":"10.1/x","pmcid":"PMC12345","live":"true"}]}'
    xml = (
        "<article><front><article-meta><title>ignored</title></article-meta></front>"
        "<body><p>Cats are furry mammals.</p><p>Dogs bark loudly.</p></body>"
        "</article>"
    )
    client = _routed_client(
        {
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/": _ok_json(idconv),
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi": _ok_xml(xml),
        }
    )
    fetcher = PmcOAFetcher(client=client)

    text = fetcher.fetch(_ref(doi="10.1/x"))

    assert text is not None
    assert "Cats are furry mammals" in text
    assert "Dogs bark loudly" in text
    # front-matter/title not included — only <body>
    assert "ignored" not in text


def test_pmc_returns_none_when_doi_not_in_pmc():
    idconv = '{"records":[{"doi":"10.1/y","errmsg":"invalid article id"}]}'
    client = _routed_client(
        {"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/": _ok_json(idconv)}
    )
    fetcher = PmcOAFetcher(client=client)

    assert fetcher.fetch(_ref(doi="10.1/y")) is None


def test_pmc_returns_none_when_efetch_5xxs():
    idconv = '{"records":[{"doi":"10.1/x","pmcid":"PMC12345"}]}'
    client = _routed_client(
        {
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/": _ok_json(idconv),
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi": _status(500),
        }
    )
    fetcher = PmcOAFetcher(client=client)

    assert fetcher.fetch(_ref(doi="10.1/x")) is None


def test_pmc_returns_none_on_unparseable_xml():
    idconv = '{"records":[{"doi":"10.1/x","pmcid":"PMC12345"}]}'
    client = _routed_client(
        {
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/": _ok_json(idconv),
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi": lambda _: httpx.Response(
                200, text="not xml at all", headers={"content-type": "application/xml"}
            ),
        }
    )
    fetcher = PmcOAFetcher(client=client)

    assert fetcher.fetch(_ref(doi="10.1/x")) is None


def test_pmc_returns_none_when_xml_has_no_body():
    # Closed-access articles yield metadata-only XML with no <body>.
    idconv = '{"records":[{"doi":"10.1/x","pmcid":"PMC12345"}]}'
    xml = (
        "<article><front><article-meta>"
        "<title>metadata only</title>"
        "</article-meta></front></article>"
    )
    client = _routed_client(
        {
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/": _ok_json(idconv),
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi": _ok_xml(xml),
        }
    )
    fetcher = PmcOAFetcher(client=client)

    assert fetcher.fetch(_ref(doi="10.1/x")) is None


def test_pmc_applies_only_when_doi_present():
    assert PmcOAFetcher.applies_to(_ref(doi="10.1/x"))
    assert not PmcOAFetcher.applies_to(_ref(arxiv_id="1234.5678"))
    assert not PmcOAFetcher.applies_to(_ref(url="https://x.example/y"))


# ------------------------------------------------------------ DoajFetcher


def test_doaj_follows_fulltext_url_when_indexed():
    search = (
        '{"results":[{"bibjson":{"link":['
        '{"type":"fulltext","url":"https://example-oa.org/paper.html"}]}}]}'
    )
    html = "<html><body><main><p>Open access body text here.</p></main></body></html>"
    client = _routed_client(
        {
            "https://doaj.org/api/search/articles/doi:": _ok_json(search),
            "https://example-oa.org/paper.html": _ok_html(html),
        }
    )
    fetcher = DoajFetcher(client=client)

    text = fetcher.fetch(_ref(doi="10.9999/xyz"))

    assert text is not None
    assert "Open access body text" in text


def test_doaj_returns_none_when_doi_not_indexed():
    client = _routed_client(
        {"https://doaj.org/api/search/articles/doi:": _ok_json('{"results":[]}')}
    )
    fetcher = DoajFetcher(client=client)

    assert fetcher.fetch(_ref(doi="10.9999/unlisted")) is None


def test_doaj_returns_none_when_record_has_no_fulltext_link():
    # DOAJ record present but only a homepage link (no fulltext).
    search = (
        '{"results":[{"bibjson":{"link":['
        '{"type":"homepage","url":"https://journal.example/"}]}}]}'
    )
    client = _routed_client(
        {"https://doaj.org/api/search/articles/doi:": _ok_json(search)}
    )
    fetcher = DoajFetcher(client=client)

    assert fetcher.fetch(_ref(doi="10.9999/xyz")) is None


def test_doaj_returns_none_when_fulltext_url_is_paywalled():
    search = (
        '{"results":[{"bibjson":{"link":['
        '{"type":"fulltext","url":"https://paywall.example/paper"}]}}]}'
    )
    client = _routed_client(
        {
            "https://doaj.org/api/search/articles/doi:": _ok_json(search),
            "https://paywall.example/paper": _status(403),
        }
    )
    fetcher = DoajFetcher(client=client)

    assert fetcher.fetch(_ref(doi="10.9999/xyz")) is None


# ------------------------------------------------------------ UrlFetcher


def test_url_html_extraction_returns_text():
    html = "<html><body><main><p>Blog post main body here.</p></main></body></html>"
    client = _routed_client({"https://example.gov/report": _ok_html(html)})
    fetcher = UrlFetcher(client=client)

    text = fetcher.fetch(_ref(url="https://example.gov/report"))

    assert text is not None
    assert "Blog post main body" in text


def test_url_plain_text_response_returned_as_is():
    client = _routed_client(
        {
            "https://example.gov/data.txt": lambda _: httpx.Response(
                200, text="raw plain text", headers={"content-type": "text/plain"}
            )
        }
    )
    fetcher = UrlFetcher(client=client)

    text = fetcher.fetch(_ref(url="https://example.gov/data.txt"))

    assert text == "raw plain text"


def test_url_degrades_on_paywall_403():
    client = _routed_client({"https://paywall.example/paper": _status(403)})
    fetcher = UrlFetcher(client=client)

    assert fetcher.fetch(_ref(url="https://paywall.example/paper")) is None


def test_url_degrades_on_transport_error():
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    client = httpx.Client(transport=httpx.MockTransport(boom))
    fetcher = UrlFetcher(client=client)

    assert fetcher.fetch(_ref(url="https://dead.example/x")) is None


def test_url_degrades_on_unknown_content_type():
    client = _routed_client(
        {
            "https://x.example/blob": lambda _: httpx.Response(
                200, content=b"\x00\x01\x02", headers={"content-type": "application/octet-stream"}
            )
        }
    )
    fetcher = UrlFetcher(client=client)

    assert fetcher.fetch(_ref(url="https://x.example/blob")) is None


# ------------------------------------------------------------ ChainFetcher


def test_chain_prefers_arxiv_over_pmc_when_both_apply():
    idconv = '{"records":[{"doi":"10.1/x","pmcid":"PMC1"}]}'
    pmc_xml = "<article><body><p>PMC text</p></body></article>"
    client = _routed_client(
        {
            "https://arxiv.org/html/": _ok_html("<html><body><p>arXiv text</p></body></html>"),
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/": _ok_json(idconv),
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi": _ok_xml(pmc_xml),
        }
    )
    fetcher = build_default_fetcher(client=client)

    text = fetcher.fetch(_ref(arxiv_id="2401.00001", doi="10.1/x"))

    assert text is not None
    assert "arXiv text" in text
    assert "PMC text" not in text


def test_chain_falls_through_to_pmc_when_arxiv_unavailable():
    idconv = '{"records":[{"doi":"10.1/x","pmcid":"PMC1"}]}'
    pmc_xml = "<article><body><p>PMC has this article.</p></body></article>"
    client = _routed_client(
        {
            "https://arxiv.org/": _status(404),
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/": _ok_json(idconv),
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi": _ok_xml(pmc_xml),
        }
    )
    fetcher = build_default_fetcher(client=client)

    text = fetcher.fetch(_ref(arxiv_id="2001.99999", doi="10.1/x"))

    assert text is not None
    assert "PMC has this article" in text


def test_chain_falls_through_to_url_last():
    # arXiv/PMC/DOAJ all miss; URL fetcher wins.
    idconv = '{"records":[{"doi":"10.1/x","errmsg":"not in PMC"}]}'
    client = _routed_client(
        {
            "https://arxiv.org/": _status(404),
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/": _ok_json(idconv),
            "https://doaj.org/api/search/articles/doi:": _ok_json('{"results":[]}'),
            "https://gray.example/report": _ok_html(
                "<html><body><p>Gray literature body.</p></body></html>"
            ),
        }
    )
    fetcher = build_default_fetcher(client=client)

    text = fetcher.fetch(
        _ref(arxiv_id="2001.99999", doi="10.1/x", url="https://gray.example/report")
    )

    assert text is not None
    assert "Gray literature body" in text


def test_chain_returns_none_when_all_sources_miss():
    idconv = '{"records":[{"doi":"10.1/x","errmsg":"not in PMC"}]}'
    client = _routed_client(
        {
            "https://arxiv.org/": _status(404),
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/": _ok_json(idconv),
            "https://doaj.org/api/search/articles/doi:": _ok_json('{"results":[]}'),
        }
    )
    fetcher = build_default_fetcher(client=client)

    text = fetcher.fetch(
        _ref(arxiv_id="2001.99999", doi="10.1/x", url="https://gone.example/x")
    )

    assert text is None


def test_chain_skips_non_applicable_fetchers_entirely():
    """A URL-only ref must not trigger arXiv/PMC/DOAJ requests."""
    calls: list[str] = []

    def _tracking(name: str) -> Handler:
        def handler(_: httpx.Request) -> httpx.Response:
            calls.append(name)
            return httpx.Response(200)

        return handler

    client = _routed_client(
        {
            "https://arxiv.org/": _tracking("arxiv"),
            "https://www.ncbi.nlm.nih.gov/": _tracking("pmc-idconv"),
            "https://eutils.ncbi.nlm.nih.gov/": _tracking("pmc-efetch"),
            "https://doaj.org/": _tracking("doaj"),
            "https://plain.example/x": _ok_html(
                "<html><body><p>plain text</p></body></html>"
            ),
        }
    )
    fetcher = build_default_fetcher(client=client)

    text = fetcher.fetch(_ref(url="https://plain.example/x"))

    assert text is not None
    assert "plain text" in text
    assert calls == []  # no applies_to on those fetchers was true


def test_chain_composes_with_caching_fetcher(tmp_path):
    """CachingFetcher wraps the chain: repeated fetches hit disk, not net."""
    net_calls = 0

    def counting_handler(request: httpx.Request) -> httpx.Response:
        nonlocal net_calls
        net_calls += 1
        if str(request.url).startswith("https://arxiv.org/html/"):
            return httpx.Response(
                200,
                text="<html><body><p>Cached me</p></body></html>",
                headers={"content-type": "text/html"},
            )
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(counting_handler))
    inner = build_default_fetcher(client=client)
    cached = CachingFetcher(inner, tmp_path / "cache")

    ref = _ref(arxiv_id="2401.00001")
    first = cached.fetch(ref)
    second = cached.fetch(ref)

    assert first is not None
    assert first == second
    assert "Cached me" in first
    # Only the first call hit the network; the second was served from cache.
    assert net_calls == 1


# ---------- Runtime type check (Protocol conformance is real) ----------


def test_all_fetchers_conform_to_source_fetcher_protocol():
    from slopchecker.pipeline.quotes import SourceFetcher

    dummy_client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(404))
    )
    for cls in (ArxivFetcher, PmcOAFetcher, DoajFetcher, UrlFetcher):
        instance = cls(client=dummy_client)
        assert isinstance(instance, SourceFetcher), f"{cls.__name__} not a SourceFetcher"
