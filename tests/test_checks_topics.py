"""Tests for the LLM topic-classification check (#15 upgrade).

No network: a fake ``LLMClient`` is injected by monkeypatching the
``AnthropicClient`` factory bound to ``checks_topics``, same seam pattern as
``test_checks_detect``.
"""

from __future__ import annotations

import json

import pytest

import slopchecker.pipeline.checks_topics as checks_topics
from slopchecker.models import FlattenedDoc
from slopchecker.pipeline.registry import CheckContext, all_checks, discover

DOC_TEXT = (
    "We propose a frontier model evaluation hub. Machine learning systems "
    "now shape science funding decisions across agencies."
)


class FakeClient:
    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, model: str, max_tokens: int) -> str:
        self.calls.append((system, user))
        return self._reply


def _install(monkeypatch: pytest.MonkeyPatch, reply: str) -> FakeClient:
    fake = FakeClient(reply)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(checks_topics, "AnthropicClient", lambda api_key: fake)
    return fake


def _doc() -> FlattenedDoc:
    return FlattenedDoc(file="p.md", text=DOC_TEXT)


def test_missing_key_is_a_skipped_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = checks_topics.topic_classification(_doc(), CheckContext())
    row = out.ledger[0]
    assert row.status == "skipped"
    assert "ANTHROPIC_API_KEY" in row.reason
    assert out.findings == []


def test_ok_path_classifies_with_anchored_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = json.dumps(
        {
            "primary": {
                "topic": "ai",
                "confidence": 0.92,
                "quote": "frontier model evaluation hub",
            },
            "secondary": [
                {
                    "topic": "science_policy",
                    "confidence": 0.55,
                    "quote": "science funding decisions across agencies",
                }
            ],
        }
    )
    fake = _install(monkeypatch, reply)

    out = checks_topics.topic_classification(_doc(), CheckContext())

    row = out.ledger[0]
    assert row.result == pytest.approx(0.92)
    assert "primary: ai" in row.detail and "science_policy" in row.detail

    assert [f.evidence["topic"] for f in out.findings] == ["ai", "science_policy"]
    primary = out.findings[0]
    assert primary.anchor is not None
    assert primary.anchor.quote in DOC_TEXT  # verbatim by the quotecheck rule
    # The fixed taxonomy reached the prompt: the model was constrained, not free.
    system = fake.calls[0][0]
    assert "- ai" in system and "- other: none of the above fits" in system


def test_invented_topic_is_rejected_not_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = json.dumps(
        {"primary": {"topic": "blockchain", "confidence": 0.9, "quote": "x"}, "secondary": []}
    )
    _install(monkeypatch, reply)
    out = checks_topics.topic_classification(_doc(), CheckContext())
    row = out.ledger[0]
    assert row.status == "errored"
    assert "no valid primary topic" in row.reason


def test_unanchorable_quote_drops_anchor_keeps_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = json.dumps(
        {
            "primary": {"topic": "ai", "confidence": 0.8, "quote": "not in the document"},
            "secondary": [],
        }
    )
    _install(monkeypatch, reply)
    out = checks_topics.topic_classification(_doc(), CheckContext())
    assert out.ledger[0].result == pytest.approx(0.8)
    assert out.findings[0].anchor is None
    assert out.findings[0].evidence["topic"] == "ai"


def test_non_json_reply_is_an_errored_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, "The primary topic is AI.")
    out = checks_topics.topic_classification(_doc(), CheckContext())
    row = out.ledger[0]
    assert row.status == "errored"
    assert "not valid json" in row.reason


def test_registered_via_discovery() -> None:
    discover()
    matches = [rc for rc in all_checks() if rc.meta.id == "topic_classification"]
    assert len(matches) == 1
    assert matches[0].meta.tier == "llm"
    assert matches[0].meta.needs_network is True
