"""Canonical metadata providers behind one interface (#9).

Crossref is authoritative for DOIs; OpenAlex substitutes when Crossref has no
record (it needs no key either, and covers a lot of what Crossref misses);
arXiv answers for preprints. They sit behind :class:`MetadataProvider` so
adding a fourth is a class, not a rewrite of the check.

The coverage gap is deliberate and named: books, reports, and gray literature
— think tank output especially — are largely absent from all three. A source
none of them knows is reported as *unknown to our providers*, which is a
statement about our coverage, not about the source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol
from xml.etree import ElementTree

import httpx

from slopchecker.checks.cache import Cache, NullCache
from slopchecker.checks.identifiers import Identifier
from slopchecker.checks.net import get_json, get_text

CROSSREF_API = "https://api.crossref.org/works"
OPENALEX_API = "https://api.openalex.org/works"
ARXIV_API = "http://export.arxiv.org/api/query"

_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}


@dataclass(frozen=True)
class SourceRecord:
    """The canonical record for a cited work, normalized across providers."""

    provider: str
    doi: str | None = None
    title: str | None = None
    authors: tuple[str, ...] = ()
    surnames: tuple[str, ...] = ()
    year: int | None = None
    venue: str | None = None
    type: str | None = None
    url: str | None = None
    extra: dict = field(default_factory=dict)

    def as_evidence(self) -> dict:
        """What the report shows so a reviewer can compare by eye."""
        return {
            "provider": self.provider,
            "title": self.title,
            "authors": list(self.authors[:5]),
            "year": self.year,
            "venue": self.venue,
            "doi": self.doi,
            "url": self.url,
            "type": self.type,
        }


class MetadataProvider(Protocol):
    """Lookup by identifier, plus reverse lookup by title (#9's key move)."""

    name: str

    def lookup(self, client: httpx.Client, ident: Identifier) -> SourceRecord | None: ...

    def search(
        self,
        client: httpx.Client,
        *,
        title: str,
        surname: str | None = None,
        year: int | None = None,
    ) -> SourceRecord | None: ...


def _surname(name: str) -> str:
    """Last whitespace-separated token, minus initials — good enough to compare."""
    cleaned = re.sub(r"\b[A-Z]\.", "", name).strip(" ,")
    parts = [p for p in cleaned.split() if p]
    return parts[-1] if parts else ""


class CrossrefProvider:
    """Authoritative for Crossref-registered DOIs (most journal literature)."""

    name = "crossref"

    def lookup(self, client: httpx.Client, ident: Identifier) -> SourceRecord | None:
        if ident.kind != "doi":
            return None
        payload = get_json(client, f"{CROSSREF_API}/{ident.value}")
        message = (payload or {}).get("message")
        return self._record(message) if isinstance(message, dict) else None

    def search(
        self,
        client: httpx.Client,
        *,
        title: str,
        surname: str | None = None,
        year: int | None = None,
    ) -> SourceRecord | None:
        query = title if surname is None else f"{title} {surname}"
        payload = get_json(client, CROSSREF_API, params={"query.bibliographic": query, "rows": "3"})
        items = ((payload or {}).get("message") or {}).get("items") or []
        for item in items:
            record = self._record(item)
            if record is not None and record.title:
                return record
        return None

    def _record(self, message: dict) -> SourceRecord | None:
        titles = message.get("title") or []
        authors = [
            " ".join(p for p in (a.get("given"), a.get("family")) if p)
            for a in message.get("author") or []
        ]
        surnames = [
            a.get("family") or _surname(a.get("name", "")) for a in message.get("author") or []
        ]
        venues = message.get("container-title") or message.get("institution") or []
        return SourceRecord(
            provider=self.name,
            doi=(message.get("DOI") or "").lower() or None,
            title=titles[0] if titles else None,
            authors=tuple(a for a in authors if a),
            surnames=tuple(s for s in surnames if s),
            year=_year_from_parts(message),
            venue=venues[0] if isinstance(venues, list) and venues else None,
            type=message.get("type"),
            url=message.get("URL"),
        )


class OpenAlexProvider:
    """No key, wide coverage — the substitute when Crossref has no record."""

    name = "openalex"

    def lookup(self, client: httpx.Client, ident: Identifier) -> SourceRecord | None:
        if ident.kind == "doi":
            payload = get_json(client, f"{OPENALEX_API}/doi:{ident.value}")
        elif ident.kind == "arxiv":
            base = ident.value.split("v")[0]
            payload = get_json(client, f"{OPENALEX_API}/doi:10.48550/arxiv.{base}")
        else:
            return None
        return self._record(payload) if payload else None

    def search(
        self,
        client: httpx.Client,
        *,
        title: str,
        surname: str | None = None,
        year: int | None = None,
    ) -> SourceRecord | None:
        params = {"filter": f"title.search:{title}", "per-page": "3"}
        payload = get_json(client, OPENALEX_API, params=params)
        for item in (payload or {}).get("results") or []:
            record = self._record(item)
            if record is not None and record.title:
                return record
        return None

    def _record(self, work: dict) -> SourceRecord | None:
        if not isinstance(work, dict) or not work.get("id"):
            return None
        authorships = work.get("authorships") or []
        authors = [a.get("author", {}).get("display_name") for a in authorships]
        source = (work.get("primary_location") or {}).get("source") or {}
        doi = (work.get("doi") or "").replace("https://doi.org/", "").lower() or None
        return SourceRecord(
            provider=self.name,
            doi=doi,
            title=work.get("display_name") or work.get("title"),
            authors=tuple(a for a in authors if a),
            surnames=tuple(_surname(a) for a in authors if a),
            year=work.get("publication_year"),
            venue=source.get("display_name"),
            type=work.get("type"),
            url=work.get("id"),
        )


class ArxivProvider:
    """Preprints. Answers for arXiv ids; Atom, so no JSON helper here."""

    name = "arxiv"

    def lookup(self, client: httpx.Client, ident: Identifier) -> SourceRecord | None:
        if ident.kind != "arxiv":
            return None
        return self._query(client, {"id_list": ident.value, "max_results": "1"})

    def search(
        self,
        client: httpx.Client,
        *,
        title: str,
        surname: str | None = None,
        year: int | None = None,
    ) -> SourceRecord | None:
        return self._query(client, {"search_query": f'ti:"{title}"', "max_results": "1"})

    def _query(self, client: httpx.Client, params: dict[str, str]) -> SourceRecord | None:
        payload = get_text(client, ARXIV_API, params)
        if payload is None:
            return None
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError:
            return None
        entry = root.find("atom:entry", _ARXIV_NS)
        if entry is None:
            return None
        title_el = entry.find("atom:title", _ARXIV_NS)
        published = entry.find("atom:published", _ARXIV_NS)
        authors = [
            (a.findtext("atom:name", default="", namespaces=_ARXIV_NS) or "").strip()
            for a in entry.findall("atom:author", _ARXIV_NS)
        ]
        year = None
        if published is not None and published.text:
            year = int(published.text[:4])
        return SourceRecord(
            provider=self.name,
            title=" ".join((title_el.text or "").split()) if title_el is not None else None,
            authors=tuple(a for a in authors if a),
            surnames=tuple(_surname(a) for a in authors if a),
            year=year,
            venue="arXiv",
            type="preprint",
            url=entry.findtext("atom:id", default=None, namespaces=_ARXIV_NS),
        )


def _year_from_parts(message: dict) -> int | None:
    """Crossref's date-parts, preferring the print/online issue date."""
    for key in ("issued", "published-print", "published-online", "published", "created"):
        parts = (message.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def _safely(call, *args, **kwargs) -> SourceRecord | None:
    """Run one provider. A provider that raises is a provider that has no
    answer — fall through to the next one.

    ``MetadataProvider`` is a public Protocol (the whole point of #9's "one
    interface" criterion), so the chain cannot assume every implementation
    returns None politely. Without this, one malformed API payload — a
    ``TypeError`` deep in a record parser — propagates out through the
    ThreadPoolExecutor in metadata_match and takes down the check for the
    entire document, which is precisely what "degrade to gaps, never crash"
    exists to prevent.
    """
    try:
        return call(*args, **kwargs)
    except Exception:  # noqa: BLE001 — isolation is the point
        return None


class ProviderChain:
    """Try each provider in order; first record wins. Results are cached.

    Caching lives here rather than in each provider so a cache hit costs one
    dict lookup no matter which provider originally answered.
    """

    def __init__(self, providers: list[MetadataProvider] | None = None, cache: Cache | None = None):
        self.providers = providers or [CrossrefProvider(), OpenAlexProvider(), ArxivProvider()]
        self.cache = cache or NullCache()

    def lookup(self, client: httpx.Client, ident: Identifier) -> SourceRecord | None:
        key = f"{ident.kind}:{ident.value}"
        cached = self.cache.get("metadata", key)
        if cached is not None:
            return _from_cache(cached)
        for provider in self.providers:
            record = _safely(provider.lookup, client, ident)
            if record is not None and record.title:
                self.cache.set("metadata", key, _to_cache(record))
                return record
        self.cache.set("metadata", key, _to_cache(None))
        return None

    def search(
        self,
        client: httpx.Client,
        *,
        title: str,
        surname: str | None = None,
        year: int | None = None,
    ) -> SourceRecord | None:
        key = f"title:{title.casefold()[:200]}|{(surname or '').casefold()}"
        cached = self.cache.get("metadata_search", key)
        if cached is not None:
            return _from_cache(cached)
        for provider in self.providers:
            record = _safely(provider.search, client, title=title, surname=surname, year=year)
            if record is not None and record.title:
                self.cache.set("metadata_search", key, _to_cache(record))
                return record
        self.cache.set("metadata_search", key, _to_cache(None))
        return None


def _to_cache(record: SourceRecord | None) -> dict:
    """Wrapped in a ``record`` key so "nobody has this" caches as a real hit
    rather than as an indistinguishable miss that re-queries every run."""
    if record is None:
        return {"record": None}
    return {
        "record": {
            "provider": record.provider,
            "doi": record.doi,
            "title": record.title,
            "authors": list(record.authors),
            "surnames": list(record.surnames),
            "year": record.year,
            "venue": record.venue,
            "type": record.type,
            "url": record.url,
        }
    }


def _from_cache(payload: dict) -> SourceRecord | None:
    record = payload.get("record") if isinstance(payload, dict) else None
    if not record:
        return None
    return SourceRecord(
        provider=record.get("provider", "cache"),
        doi=record.get("doi"),
        title=record.get("title"),
        authors=tuple(record.get("authors") or ()),
        surnames=tuple(record.get("surnames") or ()),
        year=record.get("year"),
        venue=record.get("venue"),
        type=record.get("type"),
        url=record.get("url"),
    )
