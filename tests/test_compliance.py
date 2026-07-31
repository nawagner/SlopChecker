"""Solicitation compliance check (#16): YAML spec drives section presence,
narrative length, budget ceiling, and attachment-mention checks. Deterministic
tier, no LLM. Ground truth for the two real fixtures below is hand-verified
against fixtures/rubrics/*-rfp.md and harness/fixtures/proposal_*.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from slopchecker.checks.compliance import (
    HeadingMatch,
    NarrativeLimit,
    RequiredAttachment,
    RequiredSection,
    SolicitationSpec,
    attachment_mentioned,
    find_budget_total,
    find_headings,
    load_spec,
    resolve_spec,
    section_present,
    solicitation_compliance,
)
from slopchecker.models import FlattenedDoc
from slopchecker.pipeline.registry import CheckContext

FIXTURES = Path(__file__).parent / "fixtures" / "solicitations"
ALDERGROVE_SPEC = FIXTURES / "aldergrove-cca.yaml"
HARTWELL_SPEC = FIXTURES / "hartwell-eig.yaml"
PROPOSAL_CLIMATE = Path(__file__).parent.parent / "harness" / "fixtures" / "proposal_climate.md"
PROPOSAL_EDU = Path(__file__).parent.parent / "harness" / "fixtures" / "proposal_edu.md"


def _doc(path: Path) -> FlattenedDoc:
    return FlattenedDoc(file=path.name, text=path.read_text(), media_type="text/markdown")


def _row(report, check_id):
    return next((r for r in report.ledger if r.check == check_id), None)


# --- load_spec / resolve_spec ------------------------------------------------


def test_load_spec_parses_real_aldergrove_spec():
    spec = load_spec(ALDERGROVE_SPEC)
    assert spec.id == "aldergrove-cca-2026"
    assert len(spec.required_sections) == 9
    assert spec.narrative.max_pages == 8
    assert spec.narrative.max_words is None
    assert spec.budget_ceiling_usd == 75000
    assert len(spec.required_attachments) == 4


def test_load_spec_parses_real_hartwell_spec():
    spec = load_spec(HARTWELL_SPEC)
    assert spec.id == "hartwell-eig-2026f"
    assert spec.narrative.max_words == 3000
    assert spec.budget_ceiling_usd == 85000
    assert len(spec.required_attachments) == 3


def test_load_spec_minimal_well_formed(tmp_path):
    p = tmp_path / "minimal.yaml"
    p.write_text(
        "id: minimal\nname: Minimal Spec\n"
        "required_sections:\n  - name: Title\n    aliases: [title]\n"
    )
    spec = load_spec(p)
    assert spec.id == "minimal"
    assert spec.narrative is None
    assert spec.budget_ceiling_usd is None
    assert spec.required_attachments == ()


def test_load_spec_missing_required_key_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("name: No Id\n")
    with pytest.raises(ValueError):
        load_spec(p)


def test_load_spec_narrative_without_a_limit_raises(tmp_path):
    p = tmp_path / "bad_narrative.yaml"
    p.write_text(
        "id: x\nname: X\nrequired_sections: []\n"
        "narrative:\n  start_section: Abstract\n  end_section: Approach\n"
    )
    with pytest.raises(ValueError):
        load_spec(p)


def test_resolve_spec_none_and_blank_return_none():
    assert resolve_spec(None) is None
    assert resolve_spec("") is None
    assert resolve_spec("   ") is None


def test_resolve_spec_nonexistent_path_returns_none():
    assert resolve_spec("/no/such/file.yaml") is None


def test_resolve_spec_existing_yaml_path_loads():
    spec = resolve_spec(str(ALDERGROVE_SPEC))
    assert isinstance(spec, SolicitationSpec)
    assert spec.id == "aldergrove-cca-2026"


# --- find_headings / section_present -----------------------------------------


def test_find_headings_skips_fenced_code_blocks():
    text = "# Title\n\n```\n# not a heading\n```\n\n## Real Section\nbody\n"
    headings = find_headings(text)
    titles = [h.title for h in headings]
    assert titles == ["Title", "Real Section"]


def test_section_present_word_boundary_not_substring():
    section = RequiredSection(name="CV", aliases=("cv",))
    no_match = [HeadingMatch(level=2, title="Active Learning", start=0)]
    assert section_present(no_match, section) is None
    match = [HeadingMatch(level=2, title="CV", start=0)]
    assert section_present(match, section) is not None


def test_section_present_matches_any_alias_case_insensitive():
    section = RequiredSection(name="Specific Aims", aliases=("specific aims", "aims"))
    headings = [HeadingMatch(level=2, title="AIMS", start=10)]
    found = section_present(headings, section)
    assert found is not None
    assert found.title == "AIMS"


# --- find_budget_total --------------------------------------------------------


def test_find_budget_total_markdown_table_row():
    text = "| Line item | Amount |\n|---|---|\n| Travel | $5,000 |\n| **Total** | **$90,000** |\n"
    m = find_budget_total(text)
    assert m is not None
    assert m.amount == 90000
    assert text[m.start : m.end] == m.quote


def test_find_budget_total_labeled_phrase():
    text = "Personnel: $40,000. Total requested support is $90,000."
    m = find_budget_total(text)
    assert m is not None
    assert m.amount == 90000


def test_find_budget_total_last_of_several_wins():
    text = "Subtotal: $10,000\nSubtotal: $20,000\nTotal: $30,000"
    m = find_budget_total(text)
    assert m.amount == 30000


def test_find_budget_total_none_when_absent():
    assert find_budget_total("No dollar figures in this document at all.") is None


# --- attachment_mentioned -----------------------------------------------------


def test_attachment_mentioned_true_and_false():
    attachment = RequiredAttachment(name="Biosketch", signals=("biosketch", "curriculum vitae"))
    assert attachment_mentioned("See attached biosketch for the PI.", attachment) is True
    assert attachment_mentioned("No such document is attached.", attachment) is False


# --- solicitation_compliance: hand-built fully-compliant case ----------------


def test_fully_compliant_synthetic_doc_all_pass_no_findings():
    text = (
        "## Title\nA Study\n\n"
        "## Abstract\n" + ("word " * 50) + "\n\n"
        "## Approach\n" + ("word " * 50) + "\n\n"
        "## Budget\nTotal: $1,000\n\n"
        "We attach a signed letter of support.\n"
    )
    doc = FlattenedDoc(file="ok.md", text=text, media_type="text/markdown")
    spec = SolicitationSpec(
        id="mini",
        name="Mini",
        required_sections=(
            RequiredSection(name="Title", aliases=("title",)),
            RequiredSection(name="Abstract", aliases=("abstract",)),
            RequiredSection(name="Approach", aliases=("approach",)),
            RequiredSection(name="Budget", aliases=("budget",)),
        ),
        narrative=NarrativeLimit(
            start_section="Abstract", end_section="Approach", max_words=1000, max_pages=None
        ),
        budget_ceiling_usd=5000,
        required_attachments=(RequiredAttachment(name="Letter", signals=("letter of support",)),),
    )
    from slopchecker.checks.compliance import _evaluate

    out = _evaluate(doc, spec)

    sections_row = next(r for r in out.ledger if r.check == "compliance_sections")
    assert sections_row.result is True
    length_row = next(r for r in out.ledger if r.check == "compliance_narrative_length")
    assert length_row.result is True
    budget_row = next(r for r in out.ledger if r.check == "compliance_budget")
    assert budget_row.result is True
    attach_row = next(r for r in out.ledger if r.check == "compliance_attachments")
    assert attach_row.result is True
    assert out.findings == []


# --- solicitation_compliance: no spec resolves --------------------------------


def test_no_solicitation_given_is_a_single_skipped_row():
    doc = _doc(PROPOSAL_CLIMATE)
    out = _run(doc, CheckContext(solicitation=None))
    assert len(out.ledger) == 1
    row = out.ledger[0]
    assert row.check == "compliance"
    assert row.status == "skipped"
    assert row.reason is not None
    assert "solicitation" in row.reason.lower()


def test_solicitation_path_not_found_is_a_single_skipped_row():
    doc = _doc(PROPOSAL_CLIMATE)
    out = _run(doc, CheckContext(solicitation="/no/such/spec.yaml"))
    assert len(out.ledger) == 1
    assert out.ledger[0].status == "skipped"


def _run(doc, ctx):
    return solicitation_compliance(doc, ctx)


# --- end-to-end: Aldergrove spec vs proposal_climate.md -----------------------


def test_aldergrove_vs_climate_missing_data_management_plan():
    doc = _doc(PROPOSAL_CLIMATE)
    out = _run(doc, CheckContext(solicitation=str(ALDERGROVE_SPEC)))

    sections_row = _row(out, "compliance_sections")
    assert sections_row.result is False
    missing = {f.evidence["section"] for f in out.findings if "section" in f.evidence}
    assert missing == {"Data Management Plan"}


def test_aldergrove_vs_climate_page_limit_is_skipped_no_page_count():
    doc = _doc(PROPOSAL_CLIMATE)
    out = _run(doc, CheckContext(solicitation=str(ALDERGROVE_SPEC)))
    length_row = _row(out, "compliance_narrative_length")
    assert length_row.status == "skipped"
    assert length_row.result is None
    assert "page count" in length_row.reason
    assert "boundaries" not in length_row.reason


def test_aldergrove_vs_climate_budget_over_ceiling():
    doc = _doc(PROPOSAL_CLIMATE)
    out = _run(doc, CheckContext(solicitation=str(ALDERGROVE_SPEC)))
    budget_row = _row(out, "compliance_budget")
    assert budget_row.result is False
    finding = next(f for f in out.findings if f.id == "compliance-budget-over-ceiling")
    assert finding.evidence["total_usd"] == 90000
    assert finding.evidence["ceiling_usd"] == 75000
    assert finding.anchor is not None
    assert finding.anchor.quote in doc.text


def test_aldergrove_vs_climate_all_attachments_missing():
    doc = _doc(PROPOSAL_CLIMATE)
    out = _run(doc, CheckContext(solicitation=str(ALDERGROVE_SPEC)))
    attach_row = _row(out, "compliance_attachments")
    assert attach_row.result is False
    missing = {f.evidence["attachment"] for f in out.findings if "attachment" in f.evidence}
    assert missing == {
        "Letters of Institutional Commitment",
        "Budget Justification Narrative",
        "Biosketch or CV for the PI",
        "Current and Pending Support statement",
    }


# --- end-to-end: Hartwell spec vs proposal_edu.md -----------------------------


def test_hartwell_vs_edu_missing_evaluation_plan_only():
    doc = _doc(PROPOSAL_EDU)
    out = _run(doc, CheckContext(solicitation=str(HARTWELL_SPEC)))
    sections_row = _row(out, "compliance_sections")
    assert sections_row.result is False
    missing = {f.evidence["section"] for f in out.findings if "section" in f.evidence}
    assert missing == {"Evaluation Plan"}


def test_hartwell_vs_edu_narrative_within_word_limit():
    doc = _doc(PROPOSAL_EDU)
    out = _run(doc, CheckContext(solicitation=str(HARTWELL_SPEC)))
    length_row = _row(out, "compliance_narrative_length")
    assert length_row.status == "ok"
    assert length_row.result is True


def test_hartwell_vs_edu_budget_over_ceiling():
    doc = _doc(PROPOSAL_EDU)
    out = _run(doc, CheckContext(solicitation=str(HARTWELL_SPEC)))
    budget_row = _row(out, "compliance_budget")
    assert budget_row.result is False
    finding = next(f for f in out.findings if f.id == "compliance-budget-over-ceiling")
    assert finding.evidence["total_usd"] == 97000
    assert finding.evidence["ceiling_usd"] == 85000


def test_hartwell_vs_edu_all_attachments_missing():
    doc = _doc(PROPOSAL_EDU)
    out = _run(doc, CheckContext(solicitation=str(HARTWELL_SPEC)))
    attach_row = _row(out, "compliance_attachments")
    assert attach_row.result is False
    missing = {f.evidence["attachment"] for f in out.findings if "attachment" in f.evidence}
    assert missing == {
        "IRB Approval Letter or Exempt-Determination Letter",
        "Letter of Support from each partner district",
        "One-page CV for the PI",
    }


# --- registry wiring -----------------------------------------------------------


def test_solicitation_compliance_is_registered_deterministic():
    from slopchecker.pipeline.registry import discover

    discover()
    from slopchecker.pipeline.registry import all_checks

    entry = next(rc for rc in all_checks() if rc.meta.id == "solicitation_compliance")
    assert entry.meta.tier == "deterministic"
    assert entry.applies_to is not None
    html_doc = FlattenedDoc(file="x.html", text="hi", media_type="text/html")
    assert entry.applies_to(html_doc) is False
    md_doc = FlattenedDoc(file="x.md", text="hi", media_type="text/markdown")
    assert entry.applies_to(md_doc) is True
