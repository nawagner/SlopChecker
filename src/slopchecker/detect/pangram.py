"""Pangram v3 AI-detection integration (#12).

Wraps Pangram's async text API (submit `/task`, poll `/task/{id}`) into a
`Detector` that emits one `Finding` per AI-labeled window plus a
document-level `LedgerRow` carrying `fraction_ai` as a plain number. The
score lives in its own visual lane in the report; it never becomes a
verdict (CLAUDE.md, "scores are not verdicts").

Degrades cleanly:

- Missing `PANGRAM_API_KEY` → `status="skipped"` + a skipped ledger row
  naming the env var. The rest of the run continues (#5's runner rule:
  "degrade to gaps, never crash").
- Permanent transport failure (4xx that isn't 401/402, retry ceiling on
  429/5xx) → `status="errored"` + an errored ledger row with an
  actionable reason. Still never raises past `check()`.
- 429 / 5xx up to `PangramConfig.max_attempts` with exponential backoff
  before giving up. #37 tracks a shared retry ladder; when that lands
  this local loop can be swapped for it without touching callers.

Pangram itself windows the text and returns segments with
`start_index`/`end_index` in the original string — we do not chunk
ourselves. Window offsets slice directly into `FlattenedDoc.text`, so
each finding's `Anchor.quote` is `text[start:end]` verbatim (the
quote-anchoring contract in DATA_MODEL.md).
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx

from slopchecker import config as _config
from slopchecker.checks.cache import Cache
from slopchecker.models import Anchor, CheckResult, Finding, FlattenedDoc, LedgerRow, Span

DEFAULT_BASE_URL = "https://text.external-api.pangram.com"
DEFAULT_MODEL = "pangram-3.3"

#: Cache namespace for detector responses (#119).
CACHE_NAMESPACE = "pangram"

#: Response fields allowed into a cache. A whitelist, not a blacklist: the
#: shared KV tier takes derived values only (#119), and Pangram can add a field
#: to its response without asking us. Anything unlisted is dropped rather than
#: forwarded, so a future `windows[].text` cannot silently publish document
#: text. Nothing here is text — `_windows_to_findings` re-slices every quote out
#: of `doc.text`, and the cache key is the hash of that same text, so a hit
#: guarantees the offsets still line up.
_CACHEABLE_TOP_LEVEL = ("fraction_ai", "headline")
_CACHEABLE_WINDOW = (
    "label",
    "start_index",
    "end_index",
    "ai_assistance_score",
    "confidence",
    "word_count",
    "token_length",
)


def project(response: dict[str, Any]) -> dict[str, Any]:
    """A Pangram response reduced to the fields the report actually reads.

    Applied on every cache write. `headline` is Pangram's own verdict string
    ("This document is likely AI-generated"), not document text — it is the one
    free-text field kept, and it is bounded by Pangram's own vocabulary.
    """
    projected: dict[str, Any] = {k: response[k] for k in _CACHEABLE_TOP_LEVEL if k in response}
    windows = response.get("windows")
    if isinstance(windows, list):
        projected["windows"] = [
            {k: w[k] for k in _CACHEABLE_WINDOW if k in w} for w in windows if isinstance(w, dict)
        ]
    return projected


# --- Transport layer -------------------------------------------------------


class TransportError(Exception):
    """Base for Pangram transport errors, retryable or not."""


class TransportAuthError(TransportError):
    """401 / 402 — invalid key or exhausted credits. Not retried."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


class TransportClientError(TransportError):
    """400 / 413 / 415 / 422 — client-side. Not retried (a retry won't fix it)."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


class TransportRateLimit(TransportError):
    """429 — retry with exponential backoff."""


class TransportServerError(TransportError):
    """5xx (or an unclassified transport failure). Retry with backoff."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


@runtime_checkable
class Transport(Protocol):
    """The one HTTP boundary the detector calls. Injectable for tests."""

    def predict(self, text: str, *, model: str) -> dict[str, Any]:
        """Submit `text` to Pangram and return the parsed v3 response dict."""
        ...


class HTTPTransport:
    """Real Pangram v3 transport: POST `/task`, then poll `/task/{id}`.

    Maps HTTP status codes to typed transport exceptions. Retries live
    one level up in `PangramDetector._call_with_retry` so they see the
    typed exception (retry 429 / 5xx, not 4xx).
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        poll_interval_seconds: float = 1.0,
        poll_timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._poll_interval = poll_interval_seconds
        self._poll_timeout = poll_timeout_seconds
        self._client = client or httpx.Client(timeout=30.0)

    def predict(self, text: str, *, model: str) -> dict[str, Any]:
        task_id = self._submit(text, model)
        return self._poll(task_id)

    def _submit(self, text: str, model: str) -> str:
        resp = self._client.post(
            f"{self._base_url}/task",
            headers={"x-api-key": self._api_key},
            json={"text": text, "model": model},
        )
        self._raise_for_status(resp)
        body = resp.json()
        for key in ("task_id", "id"):
            if key in body:
                return str(body[key])
        raise TransportServerError(500, f"submit response missing task id: {body}")

    def _poll(self, task_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self._poll_timeout
        while True:
            resp = self._client.get(
                f"{self._base_url}/task/{task_id}",
                headers={"x-api-key": self._api_key},
            )
            self._raise_for_status(resp)
            body = resp.json()
            stage = body.get("stage")
            if stage == "STAGE_SUCCESS":
                return body
            if stage == "STAGE_FAILED":
                raise TransportServerError(500, f"task {task_id} failed: {body}")
            if time.monotonic() > deadline:
                raise TransportServerError(504, f"task {task_id} timed out")
            time.sleep(self._poll_interval)

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.is_success:
            return
        code = resp.status_code
        try:
            payload = resp.json()
            message = payload.get("message") or payload.get("error") or resp.text
        except Exception:  # noqa: BLE001 — best-effort; body may not be JSON
            message = resp.text
        if code in (401, 402):
            raise TransportAuthError(code, message)
        if code == 429:
            raise TransportRateLimit(f"[429] {message}")
        if 400 <= code < 500:
            raise TransportClientError(code, message)
        raise TransportServerError(code, message)


# --- Detector interface + result ------------------------------------------


@runtime_checkable
class Detector(Protocol):
    """Structural interface for AI-detection providers.

    A detector inspects a `FlattenedDoc` and returns a `DetectorResult`
    containing per-passage findings and a document-level ledger row.
    """

    name: str

    def check(self, doc: FlattenedDoc) -> DetectorResult: ...

    def estimate_cost(self, doc: FlattenedDoc) -> float: ...


@dataclass(frozen=True)
class DetectorResult:
    """One detector's outcome for one document.

    Mirrors the `CheckResult` / `LedgerRow` status discipline: `ok`
    requires a `ledger_row`; `skipped`/`errored` require a `reason`. The
    ledger row is always present so the report shows what was
    attempted, even when nothing ran.
    """

    status: str  # "ok" | "skipped" | "errored"
    findings: list[Finding] = field(default_factory=list)
    ledger_row: LedgerRow | None = None
    cost_usd: float = 0.0
    reason: str | None = None


@dataclass(frozen=True)
class PangramConfig:
    """Knobs for `PangramDetector`.

    - `model` — default `"pangram-3.3"`; Pangram requires an explicit model
      after 2026-09-30.
    - `max_attempts` — retry ceiling for 429 / 5xx (client errors and
      auth errors are never retried).
    - `initial_backoff_seconds` — exponential base; attempt N sleeps
      `base * 2**N` before retrying.
    - `unit_price_usd` — dollars per 1000-word billable unit (Pangram
      bulk-billing shape; min 1 unit per document). Left at 0 by default;
      set once we know actual per-unit pricing.
    - `cache_dir` — content-hash cache root; `None` disables caching.
      Cache key covers (model, text) so a model change invalidates.
    - `cache` — a `Cache` (#119), used in preference to `cache_dir` when
      both are set. This is how the hosted service caches at all: the
      Railway filesystem is ephemeral, so `cache_dir` is useless there.
    - `ai_label_names` — which Pangram window labels get surfaced as
      passage findings. Human-labeled windows are counted at the
      document level but not turned into evidence cards.
    """

    model: str = DEFAULT_MODEL
    max_attempts: int = 3
    initial_backoff_seconds: float = 0.5
    unit_price_usd: float = 0.0
    cache_dir: Path | None = None
    cache: Cache | None = None
    ai_label_names: tuple[str, ...] = ("AI-Generated", "AI-Assisted")


class PangramDetector:
    """Pangram v3 AI-detection detector. See module docstring for behavior."""

    name = "pangram"

    def __init__(
        self,
        config: PangramConfig,
        transport: Transport | None = None,
    ) -> None:
        self._conf = config
        self._transport = transport  # lazily built when a real call is needed

    # ---- Public API ------------------------------------------------------

    def check(self, doc: FlattenedDoc) -> DetectorResult:
        try:
            api_key = _config.require("PANGRAM_API_KEY")
        except _config.MissingCredential as exc:
            return _skipped(f"missing {exc.env_var}")

        cached = self._cache_read(doc)
        if cached is not None:
            return self._to_result(doc, cached)

        transport = self._get_transport(api_key)
        try:
            response = self._call_with_retry(transport, doc.text)
        except TransportError as exc:
            reason = f"pangram transport error: {exc}"
            return DetectorResult(
                status="errored",
                reason=reason,
                ledger_row=LedgerRow(
                    check="pangram_document",
                    label="AI detection (Pangram)",
                    status="errored",
                    reason=reason,
                ),
            )

        self._cache_write(doc, response)
        return self._to_result(doc, response)

    def estimate_cost(self, doc: FlattenedDoc) -> float:
        """Estimated cost without touching the API — for `--dry-run`."""
        return self._compute_cost(word_count=len(doc.text.split()))

    # ---- Retry loop ------------------------------------------------------

    def _call_with_retry(self, transport: Transport, text: str) -> dict[str, Any]:
        last_transient: TransportError | None = None
        for attempt in range(self._conf.max_attempts):
            try:
                return transport.predict(text, model=self._conf.model)
            except (TransportRateLimit, TransportServerError) as exc:
                last_transient = exc
                if attempt < self._conf.max_attempts - 1:
                    time.sleep(self._conf.initial_backoff_seconds * (2**attempt))
            except (TransportAuthError, TransportClientError):
                # Permanent — surface immediately, no more attempts.
                raise
        assert last_transient is not None  # loop must have raised at least once
        raise last_transient

    def _get_transport(self, api_key: str) -> Transport:
        if self._transport is None:
            self._transport = HTTPTransport(api_key=api_key)
        return self._transport

    # ---- Response → model mapping ---------------------------------------

    def _to_result(self, doc: FlattenedDoc, response: dict[str, Any]) -> DetectorResult:
        findings = self._windows_to_findings(doc, response.get("windows", []))
        fraction_ai = float(response.get("fraction_ai", 0.0))
        headline = response.get("headline") or None
        ledger_row = LedgerRow(
            check="pangram_document",
            label="AI detection (Pangram)",
            result=fraction_ai,
            detail=headline,
            status="ok",
        )
        cost = self._compute_cost(word_count=self._sum_response_words(response))
        return DetectorResult(
            status="ok",
            findings=findings,
            ledger_row=ledger_row,
            cost_usd=cost,
        )

    def _windows_to_findings(
        self, doc: FlattenedDoc, windows: list[dict[str, Any]]
    ) -> list[Finding]:
        findings: list[Finding] = []
        text = doc.text
        for i, window in enumerate(windows):
            if window.get("label") not in self._conf.ai_label_names:
                continue
            start = int(window["start_index"])
            end = int(window["end_index"])
            # Trust Pangram's offsets against the text we sent — quote is the
            # verbatim slice, satisfying DATA_MODEL.md's quotecheck.
            quote = text[start:end]
            findings.append(
                Finding(
                    id=f"P{i + 1}",
                    target=f"passage@{start}",
                    label=window.get("label"),
                    anchor=Anchor(quote=quote, span=Span(start=start, end=end)),
                    checks=[
                        CheckResult(
                            name="pangram_window_ai_score",
                            result=float(window["ai_assistance_score"]),
                            status="ok",
                        )
                    ],
                    evidence={
                        "label": window.get("label"),
                        "confidence": window.get("confidence"),
                        "word_count": window.get("word_count"),
                        "token_length": window.get("token_length"),
                    },
                )
            )
        return findings

    def _compute_cost(self, *, word_count: int) -> float:
        units = max(1, math.ceil(word_count / 1000))
        return units * self._conf.unit_price_usd

    @staticmethod
    def _sum_response_words(response: dict[str, Any]) -> int:
        return sum(int(w.get("word_count", 0)) for w in response.get("windows", []))

    # ---- Cache -----------------------------------------------------------

    def _cache_key(self, doc: FlattenedDoc) -> str:
        h = hashlib.sha256()
        h.update(self._conf.model.encode())
        h.update(b"\x00")
        h.update(doc.text.encode())
        return h.hexdigest()

    def _cache_path(self, doc: FlattenedDoc) -> Path | None:
        if self._conf.cache_dir is None:
            return None
        return self._conf.cache_dir / f"{self._cache_key(doc)}.json"

    def _cache_read(self, doc: FlattenedDoc) -> dict[str, Any] | None:
        if self._conf.cache is not None:
            cached = self._conf.cache.get(CACHE_NAMESPACE, self._cache_key(doc))
            return cached if isinstance(cached, dict) else None
        path = self._cache_path(doc)
        if path is None or not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _cache_write(self, doc: FlattenedDoc, response: dict[str, Any]) -> None:
        if self._conf.cache is not None:
            # Projected, never raw: a `Cache` may be the shared KV namespace,
            # and #119 allows only derived values there.
            self._conf.cache.set(CACHE_NAMESPACE, self._cache_key(doc), project(response))
            return
        path = self._cache_path(doc)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(response), encoding="utf-8")


# --- Helpers ---------------------------------------------------------------


def _skipped(reason: str) -> DetectorResult:
    return DetectorResult(
        status="skipped",
        reason=reason,
        ledger_row=LedgerRow(
            check="pangram_document",
            label="AI detection (Pangram)",
            status="skipped",
            reason=reason,
        ),
    )
