"""Tests for #12/#23: the `pangram_document` registered check.

No network calls: the ok and errored paths inject a `PangramDetector` wired
to a fake transport (reusing the response shape from `test_detect_pangram.py`)
via a factory monkeypatched onto `slopchecker.pipeline.checks_detect`.
"""

from __future__ import annotations

import pytest

from slopchecker.detect import PangramDetector
from slopchecker.detect.pangram import TransportClientError
from slopchecker.models import FlattenedDoc
from slopchecker.pipeline.registry import CheckContext
from test_detect_pangram import FakeTransport, pangram_response  # tests/ is the import root


@pytest.fixture
def doc() -> FlattenedDoc:
    return FlattenedDoc(file="t.txt", text="some words here")


def test_missing_key_produces_skipped_row(
    doc: FlattenedDoc, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PANGRAM_API_KEY", raising=False)

    from slopchecker.pipeline.checks_detect import pangram_document

    output = pangram_document(doc, CheckContext())

    assert len(output.ledger) == 1
    row = output.ledger[0]
    assert row.check == "pangram_document"
    assert row.status == "skipped"
    assert row.reason is not None and "PANGRAM_API_KEY" in row.reason
    assert row.result is None
    assert output.findings == []


def test_ok_path_maps_result_through(doc: FlattenedDoc, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PANGRAM_API_KEY", "test-key")
    transport = FakeTransport([pangram_response(fraction_ai=0.6)])

    import slopchecker.pipeline.checks_detect as checks_detect

    # Seam: the check function instantiates `PangramDetector(PangramConfig())`
    # itself, so the factory bound to the module is monkeypatched to ignore
    # the config it's given and return a detector wired to the fake
    # transport instead. This exercises the real mapping code in
    # `pangram_document` without touching the network.
    monkeypatch.setattr(
        checks_detect,
        "PangramDetector",
        lambda config: PangramDetector(config, transport=transport),
    )

    output = checks_detect.pangram_document(doc, CheckContext())

    assert len(output.ledger) == 1
    row = output.ledger[0]
    assert row.check == "pangram_document"
    assert row.status == "ok"
    assert isinstance(row.result, float)
    assert 0.0 <= row.result <= 1.0
    assert len(output.findings) == 2
    assert output.cost_usd == pytest.approx(0.0)


def test_errored_path_does_not_raise(doc: FlattenedDoc, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PANGRAM_API_KEY", "test-key")
    transport = FakeTransport([TransportClientError(422, "unprocessable text")])

    import slopchecker.pipeline.checks_detect as checks_detect

    monkeypatch.setattr(
        checks_detect,
        "PangramDetector",
        lambda config: PangramDetector(config, transport=transport),
    )

    output = checks_detect.pangram_document(doc, CheckContext())

    assert len(output.ledger) == 1
    row = output.ledger[0]
    assert row.check == "pangram_document"
    assert row.status == "errored"
    assert row.reason is not None
    assert output.findings == []


def test_check_is_discoverable_in_registry() -> None:
    import slopchecker.pipeline.checks_detect  # noqa: F401
    from slopchecker.pipeline.registry import all_checks

    matches = [rc for rc in all_checks() if rc.meta.id == "pangram_document"]
    assert len(matches) == 1
    meta = matches[0].meta
    assert meta.tier == "api"
    assert meta.needs_network is True


# --- most-AI passage ranking (last-minute demo change, 2026-07-31) ----------


def test_findings_ranked_by_score_and_relabeled(
    doc: FlattenedDoc, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PANGRAM_API_KEY", "test-key")
    transport = FakeTransport([pangram_response(fraction_ai=0.6)])

    import slopchecker.pipeline.checks_detect as checks_detect

    monkeypatch.setattr(
        checks_detect,
        "PangramDetector",
        lambda config: PangramDetector(config, transport=transport),
    )

    output = checks_detect.pangram_document(doc, CheckContext())

    # Ranked: 0.94 window first, 0.62 second, labels carry the rank.
    scores = [f.checks[0].result for f in output.findings]
    assert scores == sorted(scores, reverse=True)
    assert output.findings[0].label == "Most AI-like passage #1"
    assert output.findings[1].label == "Most AI-like passage #2"
    # Original Pangram label survives in the note alongside the score.
    assert "0.94" in output.findings[0].note
    assert "AI-Generated" in output.findings[0].note
    # Total score stays the ledger result; detail carries the top scores.
    row = output.ledger[0]
    assert row.result == pytest.approx(0.6)
    assert "0.94" in row.detail


def test_passage_cap_is_stated_not_silent(
    doc: FlattenedDoc, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = pangram_response(fraction_ai=0.9)
    base = dict(response["windows"][0])
    seg_len = base["end_index"] - base["start_index"]
    many = []
    for i in range(8):  # 8 AI windows > _MAX_AI_PASSAGES
        w = dict(base)
        w["start_index"], w["end_index"] = 0, seg_len
        w["ai_assistance_score"] = 0.99 - i * 0.01
        many.append(w)
    response["windows"] = many

    monkeypatch.setenv("PANGRAM_API_KEY", "test-key")
    transport = FakeTransport([response])

    import slopchecker.pipeline.checks_detect as checks_detect

    monkeypatch.setattr(
        checks_detect,
        "PangramDetector",
        lambda config: PangramDetector(config, transport=transport),
    )

    output = checks_detect.pangram_document(doc, CheckContext())

    assert len(output.findings) == checks_detect._MAX_AI_PASSAGES
    assert "showing top 5 of 8" in output.ledger[0].detail
