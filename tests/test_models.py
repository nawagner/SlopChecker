"""Tests for the core data model (#3).

Covers the acceptance criteria: lossless JSON round-trip, first-class
skipped/errored, evidence payloads, schema version — plus the shipped
fixture (tests/fixtures/sample_report.json) validating unchanged and
feeding the existing renderer without modification.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from slopchecker.models import (
    SCHEMA_VERSION,
    Anchor,
    Check,
    CheckResult,
    Document,
    EvidenceReport,
    Finding,
    FlattenedDoc,
    LedgerRow,
    Report,
    RunInfo,
    Span,
    Summary,
    Verdict,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_report.json"


def assert_subset(original, dumped, path=""):
    """Every leaf in `original` must survive into `dumped` (lossless)."""
    if isinstance(original, dict):
        assert isinstance(dumped, dict), f"{path}: expected dict, got {type(dumped)}"
        for key, value in original.items():
            assert key in dumped, f"{path}.{key}: dropped in round-trip"
            assert_subset(value, dumped[key], f"{path}.{key}")
    elif isinstance(original, list):
        assert isinstance(dumped, list) and len(dumped) == len(original), f"{path}: list changed"
        for i, (o, d) in enumerate(zip(original, dumped, strict=True)):
            assert_subset(o, d, f"{path}[{i}]")
    else:
        assert dumped == original, f"{path}: {original!r} became {dumped!r}"


# --- The shipped fixture is the reference shape (#35/#40) -------------------


def test_fixture_validates_and_round_trips():
    original = json.loads(FIXTURE.read_text("utf-8"))
    report = EvidenceReport.model_validate(original)

    dumped = report.to_report_dict()
    assert_subset(original, dumped)  # nothing the fixture carried was lost

    again = EvidenceReport.model_validate(dumped)
    assert again == report  # serialization is a fixed point


def test_fixture_feeds_existing_renderer_unchanged():
    """The models are wireable into report/ with zero renderer changes."""
    from slopchecker.report.html import render_report

    report = EvidenceReport.model_validate(json.loads(FIXTURE.read_text("utf-8")))
    html = render_report(report.to_report_dict())
    assert "anno-c3" in html  # finding card rendered
    assert "prebunking interventions" in html  # anchor quote present


# --- Lossless JSON round-trip on a maximal report ---------------------------


def maximal_report() -> EvidenceReport:
    return EvidenceReport(
        document=FlattenedDoc(
            file="proposal.pdf",
            text="First page claim about prebunking.\n\n[1] Doe, J. (2025). doi:10.1/x",
            sha256="deadbeef",
            pages=2,
            page_offsets=[0, 36],
            media_type="application/pdf",
            title="A Proposal",
            byline="Response to TEST-001",
            submitter="Fabricated Org",
        ),
        solicitation="TEST-001",
        run=RunInfo(date="2026-07-31", seconds=12.5, version="0.1.0", cost_usd=0.04),
        findings=[
            Finding(
                id="C1",
                target="ref[1]",
                label="Citation [1]",
                anchor=Anchor(page=1, quote="claim about prebunking", span=Span(start=11, end=33)),
                checks=[
                    CheckResult(name="doi_resolves", result=False),
                    CheckResult(name="retries", result=3),
                    CheckResult(name="pangram_span", result=0.98),
                    CheckResult(name="quote_in_source", status="skipped", reason="paywalled"),
                ],
                verdict=Verdict.overstated,
                evidence={
                    "doi": "10.1/x",
                    "http_status": 404,
                    "source_excerpt": "reduced by 26.5%",
                },
                note="Source reports less than claimed.",
            )
        ],
        ledger=[
            LedgerRow(check="all_dois_resolve", result=False, detail="0 / 1"),
            LedgerRow(check="pangram_document", result=0.96),
            LedgerRow(check="claim_support", status="skipped", reason="ANTHROPIC_API_KEY not set"),
            LedgerRow(check="openalex_found", status="errored", reason="HTTP 500 from OpenAlex"),
        ],
        summary=Summary(recommendation="human_review"),
    )


def test_json_round_trip_is_lossless():
    report = maximal_report()
    again = EvidenceReport.model_validate_json(report.model_dump_json())
    assert again == report


def test_result_types_survive_round_trip():
    """bool stays bool, int stays int, float stays float — no coercion."""
    report = maximal_report()
    checks = EvidenceReport.model_validate_json(report.model_dump_json()).findings[0].checks
    results = {c.name: c.result for c in checks}
    assert results["doi_resolves"] is False
    assert results["retries"] == 3 and type(results["retries"]) is int
    assert results["pangram_span"] == 0.98 and type(results["pangram_span"]) is float


def test_schema_version_default_present():
    report = EvidenceReport(document=FlattenedDoc(file="x.pdf", text="t"))
    assert report.schema_version == SCHEMA_VERSION
    assert json.loads(report.model_dump_json())["schema_version"] == SCHEMA_VERSION


# --- Skipped/errored is first-class, never silent ---------------------------


def test_skipped_requires_reason():
    with pytest.raises(ValidationError):
        CheckResult(name="claim_support", status="skipped")
    with pytest.raises(ValidationError):
        LedgerRow(check="claim_support", status="errored")


def test_ok_requires_result():
    with pytest.raises(ValidationError):
        CheckResult(name="doi_resolves")  # status ok, no result: silent gap
    with pytest.raises(ValidationError):
        LedgerRow(check="doi_resolves")


def test_skipped_cannot_smuggle_a_result():
    with pytest.raises(ValidationError):
        CheckResult(name="x", status="skipped", reason="no key", result=True)


def test_skipped_and_errored_round_trip():
    row = LedgerRow(check="claim_support", status="skipped", reason="no API key")
    again = LedgerRow.model_validate_json(row.model_dump_json())
    assert again.status == "skipped" and again.reason == "no API key"
    assert again.result is None


def test_counts_derived_from_ledger():
    counts = maximal_report().counts()
    assert counts == {"passed": 0, "failed": 1, "scores": 1, "skipped": 1, "errored": 1}


# --- Evidence, not verdicts -------------------------------------------------


def test_result_rejects_free_text():
    with pytest.raises(ValidationError):
        CheckResult(name="doi_resolves", result="looks fine to me")
    with pytest.raises(ValidationError):
        CheckResult(name="doi_resolves", result="true")  # not even stringly bools


def test_verdict_is_closed_enum():
    finding = Finding(id="V1", verdict="contradicted")
    assert finding.verdict is Verdict.contradicted
    assert json.loads(finding.model_dump_json())["verdict"] == "contradicted"
    with pytest.raises(ValidationError):
        Finding(id="V2", verdict="probably AI slop")


def test_note_is_one_line():
    with pytest.raises(ValidationError):
        Finding(id="N1", note="line one\nline two")


def test_evidence_carries_raw_data():
    """Acceptance: a human can verify the claim from evidence alone."""
    finding = maximal_report().findings[0]
    dumped = json.loads(finding.model_dump_json())
    assert dumped["evidence"]["http_status"] == 404
    assert dumped["evidence"]["source_excerpt"] == "reduced by 26.5%"


# --- Structural validation --------------------------------------------------


def test_span_rejects_inverted_and_negative():
    assert Span(start=0, end=0).end == 0  # empty span allowed
    with pytest.raises(ValidationError):
        Span(start=10, end=5)
    with pytest.raises(ValidationError):
        Span(start=-1, end=5)


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        Finding(id="F1", is_ai_generated=True)  # verdict-shaped typo fails loudly


def test_check_definition():
    check = Check(id="doi_resolves", name="DOI resolves", tier="deterministic",
                  needs_network=True)
    assert check.est_cost_usd == 0.0
    assert Check.model_validate_json(check.model_dump_json()) == check
    with pytest.raises(ValidationError):
        Check(id="x", name="x", tier="vibes")


def test_issue_strawman_aliases():
    assert Document is FlattenedDoc
    assert Report is EvidenceReport
