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


def _claim(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "CL1",
        "type": "outcome",
        "scope": "specific",
        "page": 1,
        "quote": "Meridian will deliver twelve regional trainings within the first grant year",
        "quantitative": True,
        "citation": None,
    }
    return {**base, **overrides}


def test_claims_check_maps_only_flagged_claims_to_findings(monkeypatch, sample_doc):
    """Flagged = uncited AND specific AND needs-a-source (prior-work or
    quantitative) — #147's silence policy with #144's scope generalization.
    Everything else is silent: an ordinary claim is not a defect, and the
    first version's descriptive booleans made every claim render as a red
    failure."""
    payload = {
        "claims": [
            _claim(id="CL1"),  # quantitative + uncited → flagged
            _claim(
                id="CL2",
                type="prior-work",
                quantitative=False,
                citation="[1]",
                quote="The information environment has degraded rapidly",
            ),  # cited → no finding
            _claim(
                id="CL3",
                type="prior-work",
                quantitative=False,
                quote="The information environment has degraded rapidly",
            ),  # prior-work + uncited → flagged even though non-quantitative
            _claim(
                id="CL4",
                type="timeline",
                quantitative=False,
                quote="within the first grant year",
            ),  # uncited non-quant promise → no finding (can't cite your own future)
        ]
    }
    _patch_runtime(monkeypatch, payload)

    out = claims_check(sample_doc, CheckContext())

    assert [f.id for f in out.findings] == ["CL1", "CL3"]
    f1, f3 = out.findings
    assert f1.label == "Unsourced quantitative claim"
    assert f3.label == "Uncited prior-work claim"
    assert f1.anchor is not None
    assert f1.anchor.quote == payload["claims"][0]["quote"]
    assert f1.anchor.page == 1
    # Every finding advertises its provider/model in evidence.
    assert f1.evidence["provider"] == "anthropic"
    assert f1.evidence["model"] == "claude-test"
    assert f1.evidence["scope"] == "specific"
    assert f1.evidence["quantitative"] is True


def test_flagged_claim_check_polarity_renders_as_failure(monkeypatch, sample_doc):
    """False IS the flag: the renderer's failing lane keys off result=False,
    so the one check on a flagged claim must read ``claim_sourced: NO``."""
    payload = {"claims": [_claim()]}
    _patch_runtime(monkeypatch, payload)

    out = claims_check(sample_doc, CheckContext())

    (f1,) = out.findings
    assert [(c.name, c.result) for c in f1.checks] == [("claim_sourced", False)]


def test_claims_check_background_claims_are_silent(monkeypatch, sample_doc):
    """Background (context-setting) claims produce no Finding — they frame
    the argument rather than borrow evidential authority (#144)."""
    payload = {
        "claims": [
            _claim(
                type="prior-work",
                scope="background",
                quantitative=False,
                quote="The information environment has degraded rapidly",
            ),
        ]
    }
    _patch_runtime(monkeypatch, payload)

    out = claims_check(sample_doc, CheckContext())

    assert out.findings == []


def test_claims_check_missing_scope_defaults_to_specific(monkeypatch, sample_doc):
    """A payload without ``scope`` (schema drift) fails visible, not silent:
    the claim is treated as specific so a legitimate uncited narrow claim
    can't be muted by a parsing gap."""
    claim = _claim(quote="Meridian will deliver twelve regional trainings")
    del claim["scope"]
    _patch_runtime(monkeypatch, {"claims": [claim]})

    out = claims_check(sample_doc, CheckContext())

    (f1,) = out.findings
    assert [(c.name, c.result) for c in f1.checks] == [("claim_sourced", False)]
    assert f1.evidence["scope"] == "specific"


def test_claims_check_emits_doc_level_ledger_counts(monkeypatch, sample_doc):
    """``claims_quant_unsourced`` is #13's acceptance-criterion number;
    ``claims_specific_uncited`` is #144's generalization (= flagged count)."""
    payload = {
        "claims": [
            _claim(id="CL1"),  # quant + uncited: in both counts
            _claim(
                id="CL2", quote="Meridian will deliver twelve regional trainings"
            ),  # quant + uncited: in both counts
            _claim(
                id="CL3",
                type="prior-work",
                quantitative=False,
                citation="[1]",
                quote="The information environment has degraded rapidly",
            ),  # cited: in neither
            _claim(
                id="CL4",
                type="prior-work",
                quantitative=False,
                quote="The information environment has degraded rapidly",
            ),  # uncited prior-work, non-quant: flagged only
            _claim(
                id="CL5",
                type="prior-work",
                scope="background",
                quantitative=False,
                quote="The information environment has degraded rapidly",
            ),  # background: in neither
        ]
    }
    _patch_runtime(monkeypatch, payload)

    out = claims_check(sample_doc, CheckContext())

    row = next(r for r in out.ledger if r.check == "claims_quant_unsourced")
    assert row.status == "ok"
    assert row.result == 2  # CL1 + CL2

    row = next(r for r in out.ledger if r.check == "claims_specific_uncited")
    assert row.status == "ok"
    assert row.result == 3  # CL1 + CL2 + CL4

    row = next(r for r in out.ledger if r.check == "claims")
    assert row.detail == "5 claims extracted"  # full extraction still reported


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
    payload = {"claims": [_claim(quote="Meridian will deliver twelve regional trainings")]}
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
    claim = _claim(quote="Meridian will deliver twelve regional trainings")
    del claim["page"]
    _patch_runtime(monkeypatch, {"claims": [claim]})

    out = claims_check(sample_doc, CheckContext())
    assert len(out.findings) == 1
    assert out.findings[0].anchor.page is None
