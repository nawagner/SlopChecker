"""Tests for #90's first rubric-dependent check: rubric_budget_ceiling."""

from __future__ import annotations

from pathlib import Path

import slopchecker.pipeline.checks_rubric  # noqa: F401  (runs @register regardless of order)
from slopchecker import ingest
from slopchecker.models import FlattenedDoc
from slopchecker.pipeline.checks_rubric import rubric_budget_ceiling
from slopchecker.pipeline.registry import CheckContext, all_checks, discover

REPO = Path(__file__).resolve().parents[1]
RUBRICS = REPO / "fixtures" / "rubrics"
HARNESS_FIXTURES = REPO / "harness" / "fixtures"

RUBRIC_TEXT = (
    "## Award Size\n\n"
    "The maximum award is $50,000 in total costs.\n"
    "Budgets exceeding the $50,000 ceiling will not be considered.\n"
)

DOC_OVER = (
    "## Budget\n"
    "| Line item | Amount |\n"
    "| Staff | $40,000 |\n"
    "| Travel | $20,000 |\n"
    "| **Total** | **$60,000** |\n"
)

DOC_UNDER = "## Budget\n| Staff | $30,000 |\n| **Total** | **$45,000** |\n"


def _rubric(text: str = RUBRIC_TEXT) -> FlattenedDoc:
    return FlattenedDoc(file="rubric.md", text=text)


def test_no_rubric_is_a_skipped_gap():
    out = rubric_budget_ceiling(FlattenedDoc(file="p.md", text=DOC_OVER), CheckContext())
    row = out.ledger[0]
    assert row.status == "skipped"
    # Surface-neutral wording: this row is read on the website too (#148), so
    # it names the missing document, not the CLI flag that would supply it.
    assert row.reason == "no solicitation or rubric supplied — compliance not checked"
    assert "--rubric" not in row.reason
    assert out.findings == []


def test_over_ceiling_fails_with_anchored_finding():
    doc = FlattenedDoc(file="p.md", text=DOC_OVER)
    out = rubric_budget_ceiling(doc, CheckContext(rubric=_rubric()))

    row = out.ledger[0]
    assert row.result is False
    assert "$60,000" in row.detail and "$50,000" in row.detail

    assert len(out.findings) == 1
    finding = out.findings[0]
    assert finding.anchor.quote in doc.text  # verbatim by construction
    assert "$60,000" in finding.anchor.quote
    assert finding.evidence["ceiling_usd"] == 50000.0
    assert finding.evidence["budget_total_usd"] == 60000.0
    assert "$50,000" in finding.evidence["rubric_quote"]


def test_under_ceiling_passes_with_no_findings():
    out = rubric_budget_ceiling(
        FlattenedDoc(file="p.md", text=DOC_UNDER), CheckContext(rubric=_rubric())
    )
    assert out.ledger[0].result is True
    assert out.findings == []


def test_rubric_without_cap_language_is_a_gap():
    rubric = _rubric("## Overview\n\nWe fund projects. Budgets of $10,000 are typical.\n")
    ctx = CheckContext(rubric=rubric)
    out = rubric_budget_ceiling(FlattenedDoc(file="p.md", text=DOC_OVER), ctx)
    row = out.ledger[0]
    assert row.status == "skipped"
    assert "ceiling" in row.reason


def test_ambiguous_cap_amounts_are_a_gap_not_a_guess():
    rubric = _rubric(
        "Tier A awards may not exceed $50,000.\nTier B awards may not exceed $100,000.\n"
    )
    ctx = CheckContext(rubric=rubric)
    out = rubric_budget_ceiling(FlattenedDoc(file="p.md", text=DOC_OVER), ctx)
    assert out.ledger[0].status == "skipped"


def test_doc_without_total_is_a_gap():
    doc = FlattenedDoc(file="p.md", text="## Narrative\n\nNo budget table here at all.\n")
    out = rubric_budget_ceiling(doc, CheckContext(rubric=_rubric()))
    row = out.ledger[0]
    assert row.status == "skipped"
    assert "budget total" in row.reason


def test_registered_via_discovery():
    discover()
    matches = [rc for rc in all_checks() if rc.meta.id == "rubric_budget_ceiling"]
    assert len(matches) == 1
    assert matches[0].meta.tier == "deterministic"


# --- ground truth: the planted violations in the committed fixtures (#90) ---


def test_aldergrove_catches_planted_climate_violation():
    """proposal_climate ($90k) vs the Aldergrove ceiling ($75k) — planted, must fail."""
    rubric = ingest.ingest(RUBRICS / "aldergrove-community-climate-rfp.md").document
    doc = ingest.ingest(HARNESS_FIXTURES / "proposal_climate.md").document

    out = rubric_budget_ceiling(doc, CheckContext(rubric=rubric))
    row = out.ledger[0]
    assert row.result is False
    assert "$90,000" in row.detail and "$75,000" in row.detail
    assert out.findings[0].anchor.quote in doc.text


def test_hartwell_catches_planted_edu_violation():
    """proposal_edu ($97k) vs the Hartwell ceiling ($85k) — planted, must fail."""
    rubric = ingest.ingest(RUBRICS / "hartwell-education-innovation-rfp.md").document
    doc = ingest.ingest(HARNESS_FIXTURES / "proposal_edu.md").document

    out = rubric_budget_ceiling(doc, CheckContext(rubric=rubric))
    assert out.ledger[0].result is False


# --- CLI plumbing: --rubric reaches the context and the report ---


def test_cli_rubric_flag_end_to_end(tmp_path):
    import json

    from typer.testing import CliRunner

    from slopchecker.cli import app

    out = tmp_path / "reports"
    result = CliRunner().invoke(
        app,
        [
            "run",
            str(HARNESS_FIXTURES / "proposal_climate.md"),
            "--rubric",
            str(RUBRICS / "aldergrove-community-climate-rfp.md"),
            "--only",
            "rubric_budget_ceiling",
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output

    report = json.loads((out / "proposal_climate.report.json").read_text("utf-8"))
    rows = {r["check"]: r for r in report["ledger"]}
    assert rows["rubric_budget_ceiling"]["result"] is False
    assert report["solicitation"] == "aldergrove-community-climate-rfp.md"


def test_cli_bad_rubric_path_fails_fast(tmp_path):
    from typer.testing import CliRunner

    from slopchecker.cli import app

    result = CliRunner().invoke(
        app,
        [
            "run",
            str(HARNESS_FIXTURES / "proposal_climate.md"),
            "--rubric",
            str(tmp_path / "nope.md"),
            "--out",
            str(tmp_path / "reports"),
        ],
    )
    assert result.exit_code == 1
