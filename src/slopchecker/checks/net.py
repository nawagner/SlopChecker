"""Shared HTTP layer for the deterministic tier (#8).

Two jobs: build one politely-identified client, and turn an HTTP exchange
into a classification the report can print. The classification vocabulary is
the acceptance criterion — *resolves / does not exist / unreachable-or-blocked
/ malformed* — and it exists because a paywalled source is not a fake source
and a 500 is not a missing paper.

Transport failures are tracked separately from HTTP answers so a check can
tell "the server said 404" from "we have no network", and report the second
as ``errored`` instead of quietly filing it under "citations don't resolve".
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum

import httpx

from slopchecker import __version__, config

DOI_RESOLVER = "https://doi.org/"
DEFAULT_TIMEOUT_S = 15.0
# Two retries on transient failures only (timeouts, 5xx, 429). Deliberately
# shallow: #37 owns the real retry ladder; this just absorbs a blip so one
# flaky endpoint doesn't read as a bad citation.
MAX_ATTEMPTS = 3
BACKOFF_S = (0.5, 1.5)
# Content negotiation formats offered to doi.org, in preference order. The
# resolver answers with the metadata itself when it recognises the Accept —
# no redirect to the publisher, so we sidestep the ACS/NEJM/Wiley bot walls
# that were reporting every DOI as "blocked" from the Railway datacenter IP.
# 406 on one format means "wrong registry, try the next" (Crossref DOIs
# don't have DataCite payloads and vice-versa).
_DOI_ACCEPT_FORMATS: tuple[str, ...] = (
    "application/vnd.citationstyles.csl+json",
    "application/vnd.crossref.unixref+xml",
    "application/vnd.datacite.datacite+json",
)
# arXiv's export API rate-limits bursts hard and 503s freely — their own docs
# ask clients to wait ~3s between calls and retry. A resolution-length ladder
# left an available record reading as "no record" whenever a run touched arXiv
# more than once in quick succession, so the XML path gets a patient one.
SLOW_BACKOFF_S = (1.0, 3.0, 5.0, 8.0)

_REPO = "https://github.com/nawagner/SlopChecker"


class Outcome(StrEnum):
    """What we learned about an identifier. Evidence, never a verdict."""

    resolves = "resolves"
    not_found = "not_found"
    blocked = "blocked"
    unreachable = "unreachable"
    malformed = "malformed"


# HTTP statuses that mean "there is no such record".
_NOT_FOUND = {404, 410}
# Statuses that mean "something answered, but not with the document": paywalls,
# bot walls, rate limits, legal blocks. Not evidence that the source is fake.
_BLOCKED = {401, 402, 403, 405, 406, 418, 423, 429, 451}


@dataclass(frozen=True)
class Resolution:
    """The result of trying to resolve one identifier."""

    url: str
    outcome: Outcome
    http_status: int | None = None
    final_url: str | None = None
    error: str | None = None
    # True when we never got an answer at all (DNS, TLS, timeout, refused).
    # A run where every identifier ends this way is a run with no network.
    transport_error: bool = False

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.resolves

    def as_evidence(self) -> dict[str, object]:
        """The raw supporting data a human needs to re-check this by hand."""
        evidence: dict[str, object] = {"outcome": str(self.outcome), "requested": self.url}
        if self.http_status is not None:
            evidence["http_status"] = self.http_status
        if self.final_url and self.final_url != self.url:
            evidence["resolved_to"] = self.final_url
        if self.error:
            evidence["error"] = self.error
        return evidence


def user_agent() -> str:
    """Identify the tool, and join Crossref's polite pool when a mailto is set.

    ``CROSSREF_MAILTO`` is a courtesy, not a credential: unset simply means
    the public pool. Never gate a check on it (see config.py).
    """
    mailto = config.get("CROSSREF_MAILTO")
    contact = f"; mailto:{mailto}" if mailto else ""
    return f"SlopChecker/{__version__} (+{_REPO}{contact})"


@contextmanager
def http_client(timeout_s: float = DEFAULT_TIMEOUT_S) -> Iterator[httpx.Client]:
    """A client with our User-Agent, redirects followed, and a hard timeout."""
    with httpx.Client(
        follow_redirects=True,
        timeout=timeout_s,
        headers={"User-Agent": user_agent(), "Accept": "*/*"},
    ) as client:
        yield client


def classify(status: int) -> Outcome:
    """HTTP status → report vocabulary."""
    if status < 400:
        return Outcome.resolves
    if status in _NOT_FOUND:
        return Outcome.not_found
    if status in _BLOCKED or status < 500:
        return Outcome.blocked
    return Outcome.unreachable


def _transient(response: httpx.Response | None) -> bool:
    return response is None or response.status_code == 429 or response.status_code >= 500


def fetch_status(client: httpx.Client, url: str) -> Resolution:
    """Classify whether ``url`` resolves.

    Two paths:

    * DOI resolver URLs (``https://doi.org/...``) go through content
      negotiation. doi.org answers metadata requests itself, so we never
      touch the publisher and never hit ACS/NEJM/Wiley bot walls.
    * Everything else (URLs, arXiv abstract pages) goes through HEAD-then-GET.
      Publishers commonly 403 or 405 a HEAD while serving GET fine, so a
      non-2xx HEAD is retried as a GET before it's believed. The GET body
      is never read — we want the status line, not the paper.
    """
    if url.startswith(DOI_RESOLVER):
        return _fetch_via_content_negotiation(client, url)
    return _fetch_via_head_then_get(client, url)


def _fetch_via_head_then_get(client: httpx.Client, url: str) -> Resolution:
    response: httpx.Response | None = None
    error: str | None = None

    for attempt in range(MAX_ATTEMPTS):
        response, error = _attempt(client, url)
        if not _transient(response):
            break
        if attempt < len(BACKOFF_S):
            time.sleep(BACKOFF_S[attempt])

    if response is None:
        return Resolution(url=url, outcome=Outcome.unreachable, error=error, transport_error=True)
    return Resolution(
        url=url,
        outcome=classify(response.status_code),
        http_status=response.status_code,
        final_url=str(response.url),
    )


def _fetch_via_content_negotiation(client: httpx.Client, url: str) -> Resolution:
    """Ask doi.org for the DOI's metadata directly via Accept headers.

    Walks the format list until one comes back without a 406, retrying only
    on transient failures. 200 means the DOI is registered (conclusive
    ``resolves``); 404 means no such DOI at any registry (conclusive
    ``not_found``); 406 across every format means the resolver can't answer
    in a shape we asked for (rare; treat as ``blocked`` — a coverage gap,
    not a citation defect).
    """
    response: httpx.Response | None = None
    error: str | None = None

    for accept in _DOI_ACCEPT_FORMATS:
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = client.get(url, headers={"Accept": accept})
                error = None
            except httpx.HTTPError as exc:
                response = None
                error = f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # noqa: BLE001 — a check must not take the run down
                response = None
                error = f"{type(exc).__name__}: {exc}"

            if not _transient(response):
                break
            if attempt < len(BACKOFF_S):
                time.sleep(BACKOFF_S[attempt])

        # 406 means "wrong Accept for this DOI's registry" — try the next
        # format. Anything else (200 / 404 / transient-exhausted / transport
        # error) is our answer, and we stop.
        if response is not None and response.status_code == 406:
            continue
        break

    if response is None:
        return Resolution(url=url, outcome=Outcome.unreachable, error=error, transport_error=True)
    return Resolution(
        url=url,
        outcome=classify(response.status_code),
        http_status=response.status_code,
        final_url=str(response.url),
    )


def _attempt(client: httpx.Client, url: str) -> tuple[httpx.Response | None, str | None]:
    """One HEAD (then GET on a non-2xx) exchange. Never raises."""
    try:
        response = client.head(url)
        if response.status_code < 400:
            return response, None
        head_status = response.status_code
        try:
            with client.stream("GET", url) as streamed:
                return streamed, None
        except httpx.HTTPError:
            # GET failed but HEAD did answer: the HEAD status is what we know.
            return response, f"HEAD {head_status}, GET failed"
    except httpx.HTTPError:
        try:
            with client.stream("GET", url) as streamed:
                return streamed, None
        except httpx.HTTPError as get_exc:
            return None, f"{type(get_exc).__name__}: {get_exc}"
    except Exception as exc:  # noqa: BLE001 — a check must not take the run down
        return None, f"{type(exc).__name__}: {exc}"


def resolve_doi(client: httpx.Client, doi: str) -> Resolution:
    """Resolve a bare DOI through doi.org (all registries, not just Crossref)."""
    return fetch_status(client, DOI_RESOLVER + doi)


def _get_with_retries(
    client: httpx.Client,
    url: str,
    params: dict[str, str] | None,
    accept: str,
    backoff: tuple[float, ...] = BACKOFF_S,
) -> httpx.Response | None:
    """GET with the transient-failure ladder. None means "gave up", and a 404
    means "this provider has no record" — both read as "ask the next one"."""
    for attempt in range(len(backoff) + 1):
        try:
            response = client.get(url, params=params, headers={"Accept": accept})
            if response.status_code == 404:
                return None
            if _transient(response):
                raise httpx.HTTPError(f"status {response.status_code}")
            response.raise_for_status()
            return response
        except httpx.HTTPError:
            if attempt < len(backoff):
                time.sleep(backoff[attempt])
                continue
            return None
    return None


def get_json(client: httpx.Client, url: str, params: dict[str, str] | None = None) -> dict | None:
    """GET JSON, or None for any failure — callers treat None as "no record".

    A 404 from a metadata API is a legitimate answer (that provider has no
    record); a timeout is not, but at this layer both mean "ask the next
    provider", and the resolution check is what reports network trouble.
    """
    response = _get_with_retries(client, url, params, "application/json")
    if response is None:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def get_text(client: httpx.Client, url: str, params: dict[str, str] | None = None) -> str | None:
    """Same ladder, for providers that answer in XML rather than JSON.

    arXiv's export API 503s freely under load — their documented ask is to
    back off and retry, so a single unretried GET made an available provider
    look like a missing record perhaps half the time.
    """
    response = _get_with_retries(
        client,
        url,
        params,
        "application/atom+xml, application/xml",
        backoff=SLOW_BACKOFF_S,
    )
    return response.text if response is not None else None
