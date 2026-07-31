"""Tests for #12: Pangram AI-detection integration.

Tests the boundary behavior of `PangramDetector`: given a fake `Transport`
that returns canned Pangram v3 responses (or raises typed errors), the
detector produces a `DetectorResult` whose findings are quote-anchored,
whose ledger row carries the document-level score, and whose status
degrades cleanly (`skipped` when no key, `errored` on client failure).

Fabricated fixture only — no real applicant text, per CLAUDE.md.
"""

from __future__ import annotations

import pytest

from slopchecker.detect import Detector, PangramConfig, PangramDetector
from slopchecker.detect.pangram import (
    TransportClientError,
    TransportRateLimit,
    TransportServerError,
)
from slopchecker.models import FlattenedDoc

# --- Fabricated sample -----------------------------------------------------

# Three segments joined with single spaces. Offsets are computed in
# `build_sample()` so the fixture and its `windows` metadata can never drift
# out of sync (hand-counted offsets are how quote-anchoring bugs sneak in).
_SEGMENTS: tuple[tuple[str, str, float], ...] = (
    (
        "Prebunking achieves durable inoculation against misinformation.",
        "AI-Generated",
        0.94,
    ),
    (
        "Recent large-scale field trials demonstrate persistent effects up "
        "to six months post-intervention.",
        "AI-Assisted",
        0.62,
    ),
    (
        "We propose to extend this paradigm to health-adjacent domains.",
        "Human Written",
        0.08,
    ),
)


def build_sample() -> tuple[str, list[dict]]:
    """Assemble the sample text and windows with mechanically-consistent offsets."""
    parts: list[str] = []
    windows: list[dict] = []
    cursor = 0
    for i, (segment, label, score) in enumerate(_SEGMENTS):
        if i > 0:
            parts.append(" ")
            cursor += 1
        start = cursor
        parts.append(segment)
        cursor += len(segment)
        end = cursor
        windows.append(
            {
                "text": segment,
                "label": label,
                "ai_assistance_score": score,
                "confidence": "High",
                "start_index": start,
                "end_index": end,
                "word_count": len(segment.split()),
                "token_length": len(segment.split()),
            }
        )
    return "".join(parts), windows


SAMPLE_TEXT, SAMPLE_WINDOWS = build_sample()


def pangram_response(fraction_ai: float = 0.52) -> dict:
    """Fabricated v3 response mirroring what the API returns on success."""
    return {
        "stage": "STAGE_SUCCESS",
        "text": SAMPLE_TEXT,
        "version": "3.0",
        "headline": "Mixed signals",
        "prediction": "Some AI-generated content detected",
        "prediction_short": "mixed",
        "fraction_ai": fraction_ai,
        "fraction_ai_assisted": 0.32,
        "fraction_human": max(0.0, 1.0 - fraction_ai - 0.32),
        "num_ai_segments": 1,
        "num_ai_assisted_segments": 1,
        "num_human_segments": 1,
        "windows": SAMPLE_WINDOWS,
    }


# --- Fake transport --------------------------------------------------------


class FakeTransport:
    """Records calls; returns canned responses or raises typed transport errors.

    Injected in place of the real httpx-based transport. Tests the
    detector's *behavior*, not the mock — assertions check the resulting
    `DetectorResult`, and call count is only asserted where retry
    semantics are the behavior under test.
    """

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def predict(self, text: str, *, model: str) -> dict:
        self.calls.append((text, model))
        if not self._responses:
            raise AssertionError("FakeTransport out of scripted responses")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# --- Shared fixtures -------------------------------------------------------


@pytest.fixture
def doc() -> FlattenedDoc:
    return FlattenedDoc(file="fake_proposal.pdf", text=SAMPLE_TEXT)


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = "test-key-1234"
    monkeypatch.setenv("PANGRAM_API_KEY", key)
    return key


# --- Tests -----------------------------------------------------------------


def test_check_returns_ok_with_findings_and_ledger_on_success(
    doc: FlattenedDoc, api_key: str
) -> None:
    transport = FakeTransport([pangram_response(fraction_ai=0.60)])
    detector = PangramDetector(config=PangramConfig(), transport=transport)

    result = detector.check(doc)

    assert result.status == "ok"
    assert result.ledger_row is not None
    assert result.ledger_row.check == "pangram_document"
    assert result.ledger_row.result == pytest.approx(0.60)
    # AI-labeled windows surface as findings; the human window does not.
    assert len(result.findings) == 2
    scores = {f.checks[0].result for f in result.findings}
    assert scores == {0.94, 0.62}


def test_check_returns_skipped_when_api_key_missing(
    doc: FlattenedDoc, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PANGRAM_API_KEY", raising=False)
    transport = FakeTransport([])
    detector = PangramDetector(config=PangramConfig(), transport=transport)

    result = detector.check(doc)

    assert result.status == "skipped"
    assert result.reason is not None
    assert "PANGRAM_API_KEY" in result.reason
    assert transport.calls == []
    assert result.findings == []
    assert result.ledger_row is not None
    assert result.ledger_row.status == "skipped"


def test_check_returns_errored_on_client_error_without_retry(
    doc: FlattenedDoc, api_key: str
) -> None:
    transport = FakeTransport([TransportClientError(422, "unprocessable text")])
    detector = PangramDetector(
        config=PangramConfig(max_attempts=3, initial_backoff_seconds=0.0),
        transport=transport,
    )

    result = detector.check(doc)

    assert result.status == "errored"
    assert result.reason is not None and "422" in result.reason
    assert result.findings == []
    assert result.ledger_row is not None
    assert result.ledger_row.status == "errored"
    # Client errors are permanent — never retried.
    assert len(transport.calls) == 1


def test_check_retries_on_rate_limit_then_returns_ok(doc: FlattenedDoc, api_key: str) -> None:
    transport = FakeTransport(
        [
            TransportRateLimit("try again"),
            TransportRateLimit("try again"),
            pangram_response(fraction_ai=0.42),
        ]
    )
    detector = PangramDetector(
        config=PangramConfig(max_attempts=5, initial_backoff_seconds=0.0),
        transport=transport,
    )

    result = detector.check(doc)

    assert result.status == "ok"
    assert result.ledger_row is not None
    assert result.ledger_row.result == pytest.approx(0.42)
    assert len(transport.calls) == 3


def test_check_returns_errored_after_retry_ceiling_on_server_errors(
    doc: FlattenedDoc, api_key: str
) -> None:
    transport = FakeTransport([TransportServerError(500, "boom") for _ in range(5)])
    detector = PangramDetector(
        config=PangramConfig(max_attempts=3, initial_backoff_seconds=0.0),
        transport=transport,
    )

    result = detector.check(doc)

    assert result.status == "errored"
    assert result.reason is not None and "500" in result.reason
    # Exactly `max_attempts` transport calls before giving up.
    assert len(transport.calls) == 3


def test_finding_quotes_are_grounded_in_flattened_text(doc: FlattenedDoc, api_key: str) -> None:
    """Quotecheck contract (#3): every quote must slice out of doc.text."""
    transport = FakeTransport([pangram_response()])
    detector = PangramDetector(config=PangramConfig(), transport=transport)

    result = detector.check(doc)

    assert result.findings, "expected at least one finding for quote grounding check"
    for finding in result.findings:
        assert finding.anchor is not None
        assert finding.anchor.span is not None
        span = finding.anchor.span
        # Quote is verbatim slice of the flattened text (quotecheck contract).
        assert doc.text[span.start : span.end] == finding.anchor.quote
        # And the finding must actually reference real text — the (0,0) trap
        # would satisfy the equality above with two empty strings.
        assert len(finding.anchor.quote) > 0
        assert span.end > span.start


def test_cache_hit_avoids_second_api_call(doc: FlattenedDoc, api_key: str, tmp_path) -> None:
    transport = FakeTransport([pangram_response(fraction_ai=0.1)])
    detector = PangramDetector(
        config=PangramConfig(cache_dir=tmp_path),
        transport=transport,
    )

    first = detector.check(doc)
    second = detector.check(doc)

    assert first.status == "ok"
    assert second.status == "ok"
    assert first.ledger_row is not None and second.ledger_row is not None
    assert first.ledger_row.result == second.ledger_row.result
    # Second call served from cache — transport called exactly once.
    assert len(transport.calls) == 1


def test_detector_conforms_to_protocol(api_key: str) -> None:
    detector = PangramDetector(config=PangramConfig(), transport=FakeTransport([]))
    # Structural: PangramDetector must satisfy the runtime-checkable Detector
    # protocol so a future runner can register multiple detectors uniformly.
    assert isinstance(detector, Detector)


def test_cost_reflects_word_count_billing(doc: FlattenedDoc, api_key: str) -> None:
    """Cost = ceil(words / 1000) × unit_price (min 1 unit per item, per Pangram bulk billing)."""
    transport = FakeTransport([pangram_response()])
    detector = PangramDetector(
        config=PangramConfig(unit_price_usd=0.05),
        transport=transport,
    )
    result = detector.check(doc)
    # Sample is ~25 words → 1 billable unit × $0.05.
    assert result.cost_usd == pytest.approx(0.05)


def test_estimate_cost_does_not_touch_transport(doc: FlattenedDoc, api_key: str) -> None:
    """Acceptance criterion: cost per document is visible without spending it."""
    transport = FakeTransport([])  # would fail loudly if the estimator called it
    detector = PangramDetector(
        config=PangramConfig(unit_price_usd=0.05),
        transport=transport,
    )
    estimated = detector.estimate_cost(doc)
    assert estimated == pytest.approx(0.05)
    assert transport.calls == []


def test_model_defaults_to_pangram_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unpinned config sends "default" — Pangram resolves the current model
    for the key. Pinning rots: on 2026-07-31 a pinned model was rewritten
    key-side to a retired id and 422'd in production (#142)."""
    monkeypatch.delenv("PANGRAM_MODEL", raising=False)
    assert PangramConfig().model == "default"


def test_model_env_pin_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PANGRAM_MODEL", "pangram-4")
    assert PangramConfig().model == "pangram-4"
    monkeypatch.setenv("PANGRAM_MODEL", "  ")  # blank reads as unset (config.get)
    assert PangramConfig().model == "default"
