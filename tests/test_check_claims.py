"""Tests for the registered claims check (#13, runtime half).

Boundary: (FlattenedDoc, CheckContext) → CheckOutput, with the LLM
faked at the ``run_lens`` seam so the check runs offline. The check is
the glue between ``lens_runtime`` and the pipeline; it maps claims →
Findings per the table documented in ``lenses/claims.md``.
"""

# ruff: noqa: E501 — the load-bearing test quote runs past 100 chars.

from __future__ import annotations

from typing import Any

import pytest

from slopchecker.models import FlattenedDoc
from slopchecker.pipeline.checks_llm import claims as claims_check
from slopchecker.pipeline.lens_runtime import LensRunResult
from slopchecker.pipeline.registry import CheckContext


@pytest.fixture
def sample_doc() -> FlattenedDoc:
    text = (
        "Meridian will deliver twelve regional trainings within the first grant year. "
        "The information environment has degraded rapidly [1]."
    )
    return FlattenedDoc(file="fake.pdf", text=text)


def _patch_runtime(monkeypatch, payload: dict[str, Any], model: str = "claude-test") -> None:
    def fake_run_lens(lens, doc, config=None, *, client=None):
        return LensRunResult(status="ok", payload=payload, provider="anthropic", model=model)

    monkeypatch.setattr("slopchecker.pipeline.checks_llm.run_lens", fake_run_lens)


def test_claims_check_maps_each_claim_to_a_finding(monkeypatch, sample_doc):
    payload = {
        "claims": [
            {
                "id": "CL1",
                "type": "outcome",
                "page": 1,
                "quote": "Meridian will deliver twelve regional trainings within the first grant year",
                "quantitative": True,
                "citation": None,
            },
            {
                "id": "CL2",
                "type": "prior-work",
                "page": 1,
                "quote": "The information environment has degraded rapidly",
                "quantitative": False,
                "citation": "[1]",
            },
        ]
    }
    _patch_runtime(monkeypatch, payload)

    out = claims_check(sample_doc, CheckContext())

    assert len(out.findings) == 2
    f1, f2 = out.findings
    assert f1.id == "CL1"
    assert f1.label == "Claim (outcome)"
    assert f1.anchor is not None
    assert f1.anchor.quote == payload["claims"][0]["quote"]
    assert f1.anchor.page == 1
    # Every finding advertises its provider/model in evidence.
    assert f1.evidence["provider"] == "anthropic"
    assert f1.evidence["model"] == "claude-test"


def test_claims_check_emits_derived_bool_checks_per_mapping_table(monkeypatch, sample_doc):
    payload = {
        "claims": [
            {
                "id": "CL1",
                "type": "outcome",
                "page": 1,
                "quote": "Meridian will deliver twelve regional trainings within the first grant year",
                "quantitative": True,
                "citation": None,  # → quant_unsourced: True
            },
            {
                "id": "CL2",
                "type": "prior-work",
                "page": 1,
                "quote": "The information environment has degraded rapidly",
                "quantitative": False,
                "citation": "[1]",  # → quant_unsourced: False
            },
        ]
    }
    _patch_runtime(monkeypatch, payload)

    out = claims_check(sample_doc, CheckContext())

    def _get(finding, name):
        return next(c.result for c in finding.checks if c.name == name)

    f1, f2 = out.findings
    assert _get(f1, "claim_quantitative") is True
    assert _get(f1, "claim_cited") is False
    assert _get(f1, "quant_unsourced") is True

    assert _get(f2, "claim_quantitative") is False
    assert _get(f2, "claim_cited") is True
    assert _get(f2, "quant_unsourced") is False


def test_claims_check_emits_doc_level_quant_unsourced_ledger_row(monkeypatch, sample_doc):
    """The acceptance-criterion number on #13 — the report summary count."""
    payload = {
        "claims": [
            {
                "id": "CL1",
                "type": "outcome",
                "page": 1,
                "quote": "Meridian will deliver twelve regional trainings within the first grant year",
                "quantitative": True,
                "citation": None,
            },
            {
                "id": "CL2",
                "type": "outcome",
                "page": 1,
                "quote": "Meridian will deliver twelve regional trainings",
                "quantitative": True,
                "citation": None,
            },
            {
                "id": "CL3",
                "type": "prior-work",
                "page": 1,
                "quote": "The information environment has degraded rapidly",
                "quantitative": False,
                "citation": "[1]",
            },
        ]
    }
    _patch_runtime(monkeypatch, payload)

    out = claims_check(sample_doc, CheckContext())

    row = next(r for r in out.ledger if r.check == "claims_quant_unsourced")
    assert row.status == "ok"
    assert row.result == 2  # Both quantitative claims lacked a citation.


def test_claims_check_skipped_when_runtime_skips(monkeypatch, sample_doc):
    def fake_run_lens(lens, doc, config=None, *, client=None):
        return LensRunResult(
            status="skipped", reason="missing ANTHROPIC_API_KEY", provider="anthropic", model=None
        )

    monkeypatch.setattr("slopchecker.pipeline.checks_llm.run_lens", fake_run_lens)

    out = claims_check(sample_doc, CheckContext())

    assert not out.findings
    row = next(r for r in out.ledger if r.check == "claims")
    assert row.status == "skipped"
    assert "ANTHROPIC_API_KEY" in row.reason


def test_claims_check_errored_when_runtime_errors(monkeypatch, sample_doc):
    def fake_run_lens(lens, doc, config=None, *, client=None):
        return LensRunResult(
            status="errored", reason="transport 500", provider="anthropic", model="claude-test"
        )

    monkeypatch.setattr("slopchecker.pipeline.checks_llm.run_lens", fake_run_lens)

    out = claims_check(sample_doc, CheckContext())

    assert not out.findings
    row = next(r for r in out.ledger if r.check == "claims")
    assert row.status == "errored"
    assert "500" in row.reason


def test_claims_check_emits_ok_status_row_under_registered_id(monkeypatch, sample_doc):
    """Registry convention (registry.py:96): id must match ledger.check on every path.

    Before this test the ok-path emitted only ``claims_quant_unsourced`` — downstream
    "did the claims check run?" queried by the registered id got no answer on success.
    """
    payload = {
        "claims": [
            {
                "id": "CL1",
                "type": "outcome",
                "page": 1,
                "quote": "Meridian will deliver twelve regional trainings",
                "quantitative": True,
                "citation": None,
            }
        ]
    }
    _patch_runtime(monkeypatch, payload)

    out = claims_check(sample_doc, CheckContext())

    row = next(r for r in out.ledger if r.check == "claims")
    assert row.status == "ok"
    assert row.result is True
    assert "1 claims" in row.detail


def test_claims_check_registered_and_discoverable():
    """The check is picked up by ``discover()`` under a stable id."""
    from slopchecker.pipeline import all_checks, discover

    discover()
    ids = {rc.meta.id for rc in all_checks()}
    assert "claims" in ids
    rc = next(rc for rc in all_checks() if rc.meta.id == "claims")
    assert rc.meta.tier == "llm"


def test_claims_check_page_defaults_to_none_when_missing(monkeypatch, sample_doc):
    """A claim with no page (no page_offsets on the doc) still produces a valid Finding."""
    payload = {
        "claims": [
            {
                "id": "CL1",
                "type": "outcome",
                "quote": "Meridian will deliver twelve regional trainings",
                "quantitative": True,
                "citation": None,
                # no "page" key
            },
        ]
    }
    _patch_runtime(monkeypatch, payload)

    out = claims_check(sample_doc, CheckContext())
    assert len(out.findings) == 1
    assert out.findings[0].anchor.page is None
