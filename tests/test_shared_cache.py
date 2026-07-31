"""Shared KV cache (#119), offline.

Two acceptance criteria drive these tests:

1. **A cache can never fail a run.** Every failure mode of the remote tier —
   unreachable, 401, 404, timeout, malformed body — must read as a plain miss.
2. **Only derived values leave the machine.** Document text must not appear in
   anything handed to the remote tier, and a cache hit must still produce
   quote-anchored findings.

`httpx.MockTransport` stands in for the Worker, so nothing here touches the
network and no new test dependency is needed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from slopchecker.checks.cache import (
    MAX_REMOTE_KEY_BYTES,
    DiskCache,
    HTTPCache,
    NullCache,
    TieredCache,
    cache_for,
    remote_cache,
)
from slopchecker.detect.pangram import CACHE_NAMESPACE as PANGRAM_NS
from slopchecker.detect.pangram import PangramConfig, PangramDetector, project
from slopchecker.lenses.loader import Lens
from slopchecker.models import FlattenedDoc
from slopchecker.pipeline.lens_runtime import _decode_payload, _encode_payload

BASE = "https://slop-checker.com"


class FakeWorker:
    """An in-memory stand-in for /api/cache. Records every request it sees."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != "Bearer test-token":
            return httpx.Response(401, json={"error": "unauthorized"})
        key = request.url.path.removeprefix("/api/cache/")
        if request.method == "GET":
            if key not in self.store:
                return httpx.Response(404, json={"error": "not found"})
            return httpx.Response(200, content=self.store[key])
        if request.method == "PUT":
            self.store[key] = request.content.decode()
            return httpx.Response(204)
        return httpx.Response(405)

    def cache(self, token: str = "test-token", **kwargs) -> HTTPCache:
        client = httpx.Client(
            transport=httpx.MockTransport(self.handler),
            headers={"authorization": f"Bearer {token}"},
        )
        return HTTPCache(BASE, token, client=client, **kwargs)


@pytest.fixture
def worker() -> FakeWorker:
    return FakeWorker()


def _lens(lens_id: str) -> Lens:
    """A Lens stub — only `id` reaches the cache key, so the rest is filler."""
    return Lens(
        id=lens_id,
        title=lens_id.title(),
        meta={},
        sections={"system prompt": "s", "output format": "f"},
        path=Path(f"{lens_id}.md"),
    )


# --- HTTPCache: the happy path --------------------------------------------


def test_roundtrip(worker) -> None:
    cache = worker.cache()
    cache.set("pangram", "abc123", {"fraction_ai": 0.9})
    assert cache.get("pangram", "abc123") == {"fraction_ai": 0.9}


def test_miss_on_absent_key(worker) -> None:
    assert worker.cache().get("pangram", "never-written") is None


def test_namespaces_are_independent(worker) -> None:
    cache = worker.cache()
    cache.set("pangram", "same", {"from": "pangram"})
    cache.set("lens", "same", {"from": "lens"})
    assert cache.get("pangram", "same") == {"from": "pangram"}
    assert cache.get("lens", "same") == {"from": "lens"}


def test_url_keys_do_not_leak_into_the_path(worker) -> None:
    """A URL key must not re-partition the path or lose its query string.

    Regression: percent-encoding the key is not enough — httpx re-normalizes
    `%2F` back to `/`, and a `?query` would be parsed off as a real query
    string, so two URLs differing only in their query would collide.
    """
    cache = worker.cache()
    a = "https://example.org/a/b?v=1"
    b = "https://example.org/a/b?v=2"
    cache.set("url", a, {"status": 200})
    cache.set("url", b, {"status": 404})

    assert cache.get("url", a) == {"status": 200}
    assert cache.get("url", b) == {"status": 404}, "query string must not be dropped"

    # Exactly two segments after /api/cache: namespace, then an opaque hash.
    path = worker.requests[-1].url.path
    assert re.fullmatch(r"/api/cache/url/[0-9a-f]{64}", path), f"key leaked into the path: {path}"


def test_ttl_is_sent_as_a_query_param(worker) -> None:
    worker.cache(ttl_s=600).set("pangram", "k", {"v": 1})
    assert worker.requests[-1].url.params["ttl"] == "600"


def test_keys_are_hashed_so_kv_never_sees_a_cited_identifier(worker) -> None:
    """Which DOIs a proposal cites is information about the proposal, so the
    shared namespace holds opaque keys — and stays under KV's 512-byte limit
    by construction."""
    cache = worker.cache()
    doi = "10.1234/some-very-specific-grant-proposal-reference"
    cache.set("doi", doi, {"resolves": True})

    assert cache.get("doi", doi) == {"resolves": True}
    assert doi not in str(worker.requests[-1].url)
    assert doi not in json.dumps(worker.store)
    stored_key = next(iter(worker.store))
    assert len(f"doi:{stored_key}".encode()) <= MAX_REMOTE_KEY_BYTES


# --- HTTPCache: every failure is a miss ------------------------------------


def test_unreachable_host_is_a_miss_not_an_exception() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    cache = HTTPCache(BASE, "t", client=httpx.Client(transport=httpx.MockTransport(boom)))
    assert cache.get("pangram", "k") is None
    cache.set("pangram", "k", {"v": 1})  # must not raise


def test_timeout_is_a_miss() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    cache = HTTPCache(BASE, "t", client=httpx.Client(transport=httpx.MockTransport(slow)))
    assert cache.get("pangram", "k") is None
    cache.set("pangram", "k", {"v": 1})


def test_wrong_token_is_a_miss(worker) -> None:
    cache = worker.cache(token="wrong-token")
    cache.set("pangram", "k", {"v": 1})
    assert cache.get("pangram", "k") is None


def test_malformed_response_body_is_a_miss() -> None:
    def garbage(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>")

    cache = HTTPCache(BASE, "t", client=httpx.Client(transport=httpx.MockTransport(garbage)))
    assert cache.get("pangram", "k") is None


def test_unserializable_value_is_dropped_not_raised(worker) -> None:
    worker.cache().set("pangram", "k", {"bad": object()})
    assert worker.cache().get("pangram", "k") is None


# --- TieredCache -----------------------------------------------------------


def test_local_hit_never_touches_remote(worker, tmp_path) -> None:
    local = DiskCache(tmp_path)
    local.set("pangram", "k", {"v": "local"})
    tiered = TieredCache(local, worker.cache())

    assert tiered.get("pangram", "k") == {"v": "local"}
    assert worker.requests == []


def test_remote_hit_backfills_local(worker, tmp_path) -> None:
    worker.cache().set("pangram", "k", {"v": "remote"})
    local = DiskCache(tmp_path)
    tiered = TieredCache(local, worker.cache())

    assert tiered.get("pangram", "k") == {"v": "remote"}
    # Second read is served locally — the point of the tier.
    before = len(worker.requests)
    assert tiered.get("pangram", "k") == {"v": "remote"}
    assert len(worker.requests) == before


def test_set_writes_through_to_both(worker, tmp_path) -> None:
    local = DiskCache(tmp_path)
    TieredCache(local, worker.cache()).set("pangram", "k", {"v": 1})
    assert local.get("pangram", "k") == {"v": 1}
    assert worker.cache().get("pangram", "k") == {"v": 1}


def test_broken_remote_still_serves_local(tmp_path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    remote = HTTPCache(BASE, "t", client=httpx.Client(transport=httpx.MockTransport(boom)))
    tiered = TieredCache(DiskCache(tmp_path), remote)
    tiered.set("pangram", "k", {"v": 1})
    assert tiered.get("pangram", "k") == {"v": 1}


# --- Wiring ----------------------------------------------------------------


def test_remote_cache_is_none_without_both_env_vars(monkeypatch) -> None:
    monkeypatch.delenv("SLOPCHECK_CACHE_URL", raising=False)
    monkeypatch.delenv("SLOPCHECK_CACHE_TOKEN", raising=False)
    assert remote_cache() is None

    monkeypatch.setenv("SLOPCHECK_CACHE_URL", BASE)
    assert remote_cache() is None, "a URL without a token would 401 on every call"

    monkeypatch.setenv("SLOPCHECK_CACHE_TOKEN", "t")
    assert isinstance(remote_cache(), HTTPCache)


def test_cache_for_layers_when_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("SLOPCHECK_CACHE_URL", raising=False)
    monkeypatch.delenv("SLOPCHECK_CACHE_TOKEN", raising=False)
    assert isinstance(cache_for(cache_dir=tmp_path), DiskCache)

    monkeypatch.setenv("SLOPCHECK_CACHE_URL", BASE)
    monkeypatch.setenv("SLOPCHECK_CACHE_TOKEN", "t")
    assert isinstance(cache_for(cache_dir=tmp_path), TieredCache)


def test_no_cache_disables_the_shared_tier_too(monkeypatch, tmp_path) -> None:
    """--no-cache means re-fetch; a shared hit would defeat it as thoroughly
    as a local one."""
    monkeypatch.setenv("SLOPCHECK_CACHE_URL", BASE)
    monkeypatch.setenv("SLOPCHECK_CACHE_TOKEN", "t")
    assert isinstance(cache_for(no_cache=True, cache_dir=tmp_path), NullCache)


# --- Privacy: Pangram ------------------------------------------------------

PANGRAM_TEXT = "The applicant proposes a resilience programme for coastal wetlands."


def _pangram_response() -> dict:
    return {
        "fraction_ai": 0.75,
        "headline": "Likely AI-generated",
        "windows": [
            {
                "label": "AI-Generated",
                "start_index": 0,
                "end_index": 30,
                "ai_assistance_score": 0.9,
                "confidence": "high",
                "word_count": 5,
                "token_length": 7,
                # Fields Pangram could add tomorrow. Neither is on the
                # whitelist, so neither may reach the shared cache.
                "text": PANGRAM_TEXT[:30],
                "excerpt": PANGRAM_TEXT[:30],
            }
        ],
    }


def test_project_drops_unlisted_fields() -> None:
    projected = project(_pangram_response())
    window = projected["windows"][0]
    assert "text" not in window
    assert "excerpt" not in window
    assert window["start_index"] == 0
    assert window["ai_assistance_score"] == 0.9
    assert projected["fraction_ai"] == 0.75


def test_no_document_text_reaches_the_shared_cache(worker) -> None:
    """The load-bearing privacy test: the stored bytes must not contain the
    document."""
    doc = FlattenedDoc(file="p.pdf", text=PANGRAM_TEXT)
    detector = PangramDetector(PangramConfig(cache=worker.cache()))
    detector._cache_write(doc, _pangram_response())

    stored = json.dumps(worker.store)
    assert PANGRAM_TEXT[:30] not in stored
    assert "resilience programme" not in stored


def test_cache_hit_still_produces_quote_anchored_findings(worker) -> None:
    """Quotes are re-sliced from doc.text, so anchoring survives the round trip
    even though no text was stored."""
    doc = FlattenedDoc(file="p.pdf", text=PANGRAM_TEXT)
    detector = PangramDetector(PangramConfig(cache=worker.cache()))
    detector._cache_write(doc, _pangram_response())

    cached = detector._cache_read(doc)
    assert cached is not None
    result = detector._to_result(doc, cached)

    assert len(result.findings) == 1
    quote = result.findings[0].anchor.quote
    assert quote == PANGRAM_TEXT[0:30]
    assert quote in doc.text, "quote must be mechanically grounded in the source"


def test_pangram_cache_key_covers_the_model(worker) -> None:
    doc = FlattenedDoc(file="p.pdf", text=PANGRAM_TEXT)
    a = PangramDetector(PangramConfig(cache=worker.cache(), model="pangram-4"))
    b = PangramDetector(PangramConfig(cache=worker.cache(), model="pangram-5"))
    a._cache_write(doc, _pangram_response())
    assert b._cache_read(doc) is None, "a model change must invalidate"


def test_pangram_disk_cache_is_unchanged(tmp_path) -> None:
    """The additive `cache` field must not disturb existing cache_dir users."""
    doc = FlattenedDoc(file="p.pdf", text=PANGRAM_TEXT)
    detector = PangramDetector(PangramConfig(cache_dir=tmp_path))
    detector._cache_write(doc, _pangram_response())
    assert detector._cache_read(doc) == _pangram_response()
    assert list(tmp_path.glob("*.json"))


# --- Privacy: lens payloads ------------------------------------------------

LENS_TEXT = "Coastal wetlands store 40% more carbon than upland forests, per Smith 2021."


def _lens_payload() -> dict:
    return {
        "claims": [
            {
                "id": "C1",
                "quote": "Coastal wetlands store 40% more carbon than upland forests",
                "quantitative": True,
                "citation": "Smith 2021",
                "type": "empirical",
            }
        ]
    }


def test_encode_replaces_quotes_with_spans() -> None:
    encoded = _encode_payload(_lens_payload(), LENS_TEXT)
    claim = encoded["claims"][0]
    assert "quote" not in claim
    assert claim["quote_span"] == [0, len(_lens_payload()["claims"][0]["quote"])]
    # Non-quote fields are preserved verbatim.
    assert claim["citation"] == "Smith 2021"
    assert claim["quantitative"] is True


def test_encoded_payload_contains_no_document_text() -> None:
    serialized = json.dumps(_encode_payload(_lens_payload(), LENS_TEXT))
    assert "Coastal wetlands" not in serialized
    assert "upland forests" not in serialized


def test_encode_decode_round_trips_exactly() -> None:
    encoded = _encode_payload(_lens_payload(), LENS_TEXT)
    decoded = _decode_payload(encoded, LENS_TEXT)
    assert decoded == _lens_payload()


def test_decoded_quote_is_grounded_in_the_source() -> None:
    decoded = _decode_payload(_encode_payload(_lens_payload(), LENS_TEXT), LENS_TEXT)
    assert decoded["claims"][0]["quote"] in LENS_TEXT


def test_decode_drops_out_of_range_spans() -> None:
    """Only reachable via a key collision or a hand-edited entry — but a wrong
    quote would breach the quote-anchoring contract, so drop it."""
    poisoned = {"claims": [{"id": "C1", "quote_span": [0, 99999]}]}
    assert _decode_payload(poisoned, LENS_TEXT)["claims"] == []


def test_decode_tolerates_a_malformed_span() -> None:
    for span in ([0], "0,5", [None, 5], [5, 0]):
        poisoned = {"claims": [{"id": "C1", "quote_span": span}]}
        assert _decode_payload(poisoned, LENS_TEXT)["claims"] == []


def test_encode_drops_a_claim_whose_quote_is_not_in_the_source() -> None:
    payload = {"claims": [{"id": "C1", "quote": "text that was never in the document"}]}
    assert _encode_payload(payload, LENS_TEXT)["claims"] == []


def test_lens_cache_round_trip_through_the_worker(worker) -> None:
    """End to end: run_lens's cache helpers, with the fake Worker in the middle."""
    from slopchecker.pipeline.lens_runtime import LensRunConfig, _cache_read, _cache_write

    doc = FlattenedDoc(file="p.pdf", text=LENS_TEXT)
    lens = _lens("claims")
    config = LensRunConfig(cache=worker.cache())

    _cache_write(config, lens, doc, "claude-opus-5", _lens_payload())
    assert LENS_TEXT[:20] not in json.dumps(worker.store)
    assert _cache_read(config, lens, doc, "claude-opus-5") == _lens_payload()


def test_lens_cache_key_covers_model_and_lens_id(worker) -> None:
    from slopchecker.pipeline.lens_runtime import LensRunConfig, _cache_read, _cache_write

    doc = FlattenedDoc(file="p.pdf", text=LENS_TEXT)
    config = LensRunConfig(cache=worker.cache())
    claims = _lens("claims")
    budget = _lens("budget")

    _cache_write(config, claims, doc, "claude-opus-5", _lens_payload())
    assert _cache_read(config, budget, doc, "claude-opus-5") is None
    assert _cache_read(config, claims, doc, "claude-sonnet-5") is None


def test_lens_namespace_is_distinct_from_pangram(worker) -> None:
    assert PANGRAM_NS != "lens"
