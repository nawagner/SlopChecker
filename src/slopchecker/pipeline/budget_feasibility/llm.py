"""Transport layer for the budget-feasibility check (#17).

Thin wrapper on the Anthropic Messages API. Mirrors ``claim_support/llm.py``
per the #37 design comment — same shape, private to this subpackage until a
second LLM caller wants to share it:

- Typed transport exceptions (401/403 → auth, 429 → rate-limit, 5xx →
  server, everything else 4xx → client). ``_call_with_retry`` in
  ``check.py`` retries 429/5xx with exponential backoff and surfaces
  auth/client errors immediately.
- ``Transport`` protocol so tests can inject a fake and never hit the
  network. Real HTTP path uses ``AnthropicTransport``.
- Structured output via ``output_config.format`` (JSON schema). The
  budget-feasibility lens returns a strict extraction JSON — free text
  is banned by the SlopChecker rules — so a closed JSON schema is the
  only shape that both the CLAUDE.md invariant and Opus 4.6+'s no-prefill
  contract accept.

The transport itself is role-agnostic: it takes ``system`` + ``user`` +
``schema`` + ``model`` and returns the validated JSON. The ``role``
argument is a diagnostic label passed through so tests can assert call
alignment, not a wire concept.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# --- Typed transport errors -------------------------------------------------


class TransportError(Exception):
    """Base for LLM transport errors, retryable or not."""


class TransportAuthError(TransportError):
    """401 / 402 / 403 — invalid key or permission denied. Never retried."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


class TransportClientError(TransportError):
    """400 / 404 / 413 / 422 — client-side. Not retried (won't fix on retry)."""

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


class TransportRefusal(TransportError):
    """``stop_reason == "refusal"`` from the model — surface as a gap.

    Distinct from a network refusal (auth/client). A policy refusal on a
    budget-extraction call is unusual but real; the check turns it into an
    errored ledger row rather than pretending the check ran.
    """


@runtime_checkable
class Transport(Protocol):
    """One method: run a system+user prompt with a JSON schema, get the parsed dict."""

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict,
        model: str,
        role: str,
    ) -> dict[str, Any]: ...


# --- Real Anthropic transport ----------------------------------------------


class AnthropicTransport:
    """The real transport. Uses the Anthropic SDK's client and
    ``output_config.format`` for structured output.

    Constructed lazily by the check so unit tests never import ``anthropic``.
    """

    def __init__(self, *, api_key: str, max_output_tokens: int = 4096) -> None:
        # Lazy import: keeps the ``anthropic`` package off the import path
        # for anyone running the deterministic tier or the unit tests.
        from anthropic import Anthropic  # noqa: PLC0415

        self._client = Anthropic(api_key=api_key)
        self._max_output_tokens = max_output_tokens
        # Provider name lands in Finding.evidence so a reader can trace the
        # verdict back to the tool that produced it.
        self.name = "anthropic"

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict,
        model: str,
        role: str,
    ) -> dict[str, Any]:
        # Late imports so unit tests never require the SDK to be installed.
        import json  # noqa: PLC0415

        import anthropic  # noqa: PLC0415

        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=self._max_output_tokens,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": schema},
                },
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.AuthenticationError as exc:
            raise TransportAuthError(401, str(exc)) from exc
        except anthropic.PermissionDeniedError as exc:
            raise TransportAuthError(403, str(exc)) from exc
        except anthropic.RateLimitError as exc:
            raise TransportRateLimit(f"[429] {exc}") from exc
        except anthropic.BadRequestError as exc:
            raise TransportClientError(400, str(exc)) from exc
        except anthropic.NotFoundError as exc:
            raise TransportClientError(404, str(exc)) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code and exc.status_code >= 500:
                raise TransportServerError(exc.status_code, str(exc)) from exc
            raise TransportClientError(exc.status_code or 400, str(exc)) from exc
        except anthropic.APIConnectionError as exc:
            raise TransportServerError(0, f"connection error: {exc}") from exc

        # A policy refusal is a successful HTTP 200 but has empty content —
        # code that indexes content[0] blindly breaks. Surface it as a
        # distinct transport error so the check records a gap.
        if response.stop_reason == "refusal":
            explanation = ""
            if response.stop_details is not None:
                explanation = getattr(response.stop_details, "explanation", "") or ""
            raise TransportRefusal(f"model refused: {explanation}") from None

        # output_config.format guarantees the first text block is valid JSON
        # matching the schema. Anthropic validates server-side.
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)  # type: ignore[no-any-return]
