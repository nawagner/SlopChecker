"""Lens execution runtime (#13).

Runs a landed lens prompt pack (see ``slopchecker/lenses/``) against a
``FlattenedDoc`` via a real LLM call, parses the strict-JSON response,
and mechanically quote-anchors every emitted claim against the source —
items whose ``quote`` is not a verbatim substring of ``doc.text`` are
dropped, not surfaced.

Shape mirrors ``detect/pangram.py``: an injectable transport-style
``LLMClient`` protocol at the boundary, typed transport exceptions per
HTTP failure class, and a private ``_call_with_retry`` that retries only
transients. Prompt assembly (``assemble_messages``) is deliberately
separate from the call site so a future "reframed" prompt is a sibling
function, not an edit — one of the two shape decisions locked in on
#37's 2026-07-31 design comment. The second: every successful call
tags ``LensRunResult.provider`` / ``.model``, so the registered check
can drop them into ``Finding.evidence`` and later gain a ``rung`` key
without a schema-version bump.

Missing ``ANTHROPIC_API_KEY`` → ``status="skipped"`` with the env-var
name in the reason (degrade-to-gaps, per CLAUDE.md).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from slopchecker import config as _config
from slopchecker.lenses import Lens
from slopchecker.models import FlattenedDoc

DEFAULT_MAX_OUTPUT_TOKENS = 8192
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_INITIAL_BACKOFF_SECONDS = 0.5


# --- Transport layer -------------------------------------------------------


class TransportError(Exception):
    """Base for LLM transport errors, retryable or not."""


class TransportAuthError(TransportError):
    """401 / 402 — invalid key or exhausted credits. Not retried."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


class TransportClientError(TransportError):
    """400 / 413 / 422 — client-side. Not retried (retry won't fix it)."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


class TransportRateLimit(TransportError):
    """429 — retry with exponential backoff."""


class TransportServerError(TransportError):
    """5xx / connection failure. Retry with backoff."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


# --- LLM client boundary ---------------------------------------------------


@runtime_checkable
class LLMClient(Protocol):
    """The one boundary ``run_lens`` calls. Injectable for tests."""

    def complete(self, system: str, user: str, *, model: str, max_tokens: int) -> str:
        """Return the assistant's text, or raise a ``TransportError``."""
        ...


class AnthropicClient:
    """Real ``anthropic.Anthropic`` wrapper, mapping SDK exceptions to
    typed transport errors so the retry loop can decide by class."""

    def __init__(self, api_key: str) -> None:
        # Imported lazily so a checkout without the ``llm`` extra
        # doesn't fail at import time — only when a real call is made.
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)

    def complete(self, system: str, user: str, *, model: str, max_tokens: int) -> str:
        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # noqa: BLE001 — remap to typed transport errors
            raise _map_anthropic_error(exc) from exc
        for block in response.content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                return text
        raise TransportServerError(500, "response contained no text block")


def _map_anthropic_error(exc: Exception) -> TransportError:
    """Best-effort remap from anthropic SDK exceptions to our transport types."""
    from anthropic import (
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
        AuthenticationError,
        BadRequestError,
        InternalServerError,
        NotFoundError,
        PermissionDeniedError,
        RateLimitError,
        UnprocessableEntityError,
    )

    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return TransportAuthError(getattr(exc, "status_code", 401), str(exc))
    if isinstance(exc, RateLimitError):
        return TransportRateLimit(f"[429] {exc}")
    if isinstance(exc, (BadRequestError, NotFoundError, UnprocessableEntityError)):
        return TransportClientError(getattr(exc, "status_code", 400), str(exc))
    if isinstance(exc, (InternalServerError, APIConnectionError, APITimeoutError)):
        code = getattr(exc, "status_code", 500)
        return TransportServerError(code, str(exc))
    if isinstance(exc, APIStatusError):
        code = getattr(exc, "status_code", 500)
        if code in (401, 402):
            return TransportAuthError(code, str(exc))
        if code == 429:
            return TransportRateLimit(f"[429] {exc}")
        if 400 <= code < 500:
            return TransportClientError(code, str(exc))
        return TransportServerError(code, str(exc))
    # Unknown — treat as transient so it gets retried once or twice.
    return TransportServerError(500, str(exc))


# --- Config + result -------------------------------------------------------


@dataclass(frozen=True)
class LensRunConfig:
    """Knobs for ``run_lens``.

    - ``model`` — Anthropic model id. Defaults to ``config.llm_model()``.
    - ``max_output_tokens`` — SDK cap for the response.
    - ``max_attempts`` — retry ceiling for 429 / 5xx.
    - ``initial_backoff_seconds`` — exponential base; attempt N sleeps
      ``base * 2**N`` before retrying.
    - ``cache_dir`` — content-hash cache root; ``None`` disables. Cache
      key covers ``(model, lens.id, doc.text)`` so a model change or
      a different lens invalidates.
    """

    model: str = ""  # empty → resolved to config.llm_model() at call time
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    initial_backoff_seconds: float = DEFAULT_INITIAL_BACKOFF_SECONDS
    cache_dir: Path | None = None


@dataclass(frozen=True)
class LensRunResult:
    """One lens execution's outcome for one document.

    Same status discipline as ``CheckResult`` / ``LedgerRow``: ``ok``
    carries a ``payload`` (the parsed, quote-anchored JSON);
    ``skipped``/``errored`` carry a ``reason``. ``provider`` / ``model``
    are always present so downstream ``Finding.evidence`` can advertise
    them.
    """

    status: Literal["ok", "skipped", "errored"]
    payload: dict[str, Any] | None = None
    reason: str | None = None
    provider: str = "anthropic"
    model: str | None = None


# --- Prompt assembly (separate from the call site) ------------------------


def assemble_messages(lens: Lens, doc: FlattenedDoc) -> tuple[str, str]:
    """Build (system, user) for the LLM call.

    ``system`` = lens system prompt + the lens's output-format contract,
    so the model has the JSON schema even when the pack is fetched
    without its markdown wrapper.

    ``user`` = ``doc.text``, with ``[[page N]]`` markers inserted before
    each page's first character when ``doc.page_offsets`` is available
    (matches the convention documented in ``lenses/claims.md``). Markers
    are NOT in ``doc.text``, so quote-anchoring against ``doc.text`` is
    unaffected.
    """
    system = lens.system_prompt.strip() + "\n\n## Output format\n\n" + lens.output_format.strip()
    user = _with_page_markers(doc)
    return system, user


def _with_page_markers(doc: FlattenedDoc) -> str:
    if not doc.page_offsets:
        return doc.text
    parts: list[str] = []
    prev = 0
    for i, offset in enumerate(doc.page_offsets):
        parts.append(doc.text[prev:offset])
        parts.append(f"[[page {i + 1}]]\n")
        prev = offset
    parts.append(doc.text[prev:])
    return "".join(parts)


# --- Retry loop ------------------------------------------------------------


def _call_with_retry(
    client: LLMClient, system: str, user: str, config: LensRunConfig, model: str
) -> str:
    last_transient: TransportError | None = None
    for attempt in range(config.max_attempts):
        try:
            return client.complete(system, user, model=model, max_tokens=config.max_output_tokens)
        except (TransportRateLimit, TransportServerError) as exc:
            last_transient = exc
            if attempt < config.max_attempts - 1 and config.initial_backoff_seconds > 0:
                time.sleep(config.initial_backoff_seconds * (2**attempt))
        except (TransportAuthError, TransportClientError):
            # Permanent — surface immediately.
            raise
    assert last_transient is not None
    raise last_transient


# --- JSON parse (tolerates markdown fences) --------------------------------


def _parse_json_strict(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.index("\n")
        stripped = stripped[first_newline + 1 :]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]
    result = json.loads(stripped)
    if not isinstance(result, dict):
        raise ValueError(f"expected top-level JSON object, got {type(result).__name__}")
    return result


# --- Quote anchoring -------------------------------------------------------


def _quote_anchor(payload: dict[str, Any], source_text: str) -> dict[str, Any]:
    """Drop items in ``payload['claims']`` whose ``quote`` isn't a verbatim
    substring of ``source_text``. Non-mutating: returns a new payload dict.
    """
    claims = payload.get("claims", [])
    if not isinstance(claims, list):
        raise ValueError("payload['claims'] must be a list")
    kept = [c for c in claims if isinstance(c, dict) and c.get("quote", "") in source_text]
    return {**payload, "claims": kept}


# --- Cache -----------------------------------------------------------------


def _cache_path(config: LensRunConfig, lens: Lens, doc: FlattenedDoc, model: str) -> Path | None:
    if config.cache_dir is None:
        return None
    h = hashlib.sha256()
    h.update(model.encode())
    h.update(b"\x00")
    h.update(lens.id.encode())
    h.update(b"\x00")
    h.update(doc.text.encode())
    return config.cache_dir / f"{h.hexdigest()}.json"


def _cache_read(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _cache_write(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# --- Public entry point ----------------------------------------------------


def run_lens(
    lens: Lens,
    doc: FlattenedDoc,
    config: LensRunConfig | None = None,
    *,
    client: LLMClient | None = None,
) -> LensRunResult:
    """Execute ``lens`` against ``doc`` via ``client`` (or a real Anthropic
    client if unset), returning the parsed, quote-anchored JSON payload."""
    config = config or LensRunConfig()
    model = config.model or _config.llm_model()

    # Missing key + no injected client → skipped gap row, never a crash.
    if client is None:
        try:
            api_key = _config.require("ANTHROPIC_API_KEY")
        except _config.MissingCredential as exc:
            return LensRunResult(
                status="skipped",
                reason=f"missing {exc.env_var}",
                provider="anthropic",
                model=None,
            )
        client = AnthropicClient(api_key=api_key)

    cache_path = _cache_path(config, lens, doc, model)
    cached = _cache_read(cache_path)
    if cached is not None:
        return LensRunResult(status="ok", payload=cached, provider="anthropic", model=model)

    system, user = assemble_messages(lens, doc)
    try:
        raw = _call_with_retry(client, system, user, config, model)
    except TransportError as exc:
        return LensRunResult(
            status="errored",
            reason=f"lens transport error: {exc}",
            provider="anthropic",
            model=model,
        )

    try:
        payload = _parse_json_strict(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return LensRunResult(
            status="errored",
            reason=f"lens output not valid json: {exc}",
            provider="anthropic",
            model=model,
        )

    if "claims" not in payload:
        return LensRunResult(
            status="errored",
            reason="lens output missing 'claims' key",
            provider="anthropic",
            model=model,
        )

    try:
        anchored = _quote_anchor(payload, doc.text)
    except ValueError as exc:
        return LensRunResult(
            status="errored",
            reason=f"lens output failed quote-anchoring: {exc}",
            provider="anthropic",
            model=model,
        )

    _cache_write(cache_path, anchored)
    return LensRunResult(status="ok", payload=anchored, provider="anthropic", model=model)
