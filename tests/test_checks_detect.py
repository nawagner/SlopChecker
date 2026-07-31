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
