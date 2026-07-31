"""`slopcheck run` (#6). Offline: built-in checks only, plus fake registrations."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from slopchecker.cli import app
from slopchecker.models import Check, EvidenceReport
from slopchecker.pipeline import RegisteredCheck
from slopchecker.pipeline import registry as registry_mod

runner = CliRunner()

SAMPLE = "Prebunking achieves durable inoculation [1].\n\n[1] Doe, J. (2025)."


@pytest.fixture
def sample_md(tmp_path):
    p = tmp_path / "sample.md"
    p.write_text(SAMPLE)
    return p


@pytest.fixture
def scratch_registry(monkeypatch):
    """A copy of the real registry (built-ins included) tests may add fakes to."""
    monkeypatch.setattr(registry_mod, "_REGISTRY", dict(registry_mod._REGISTRY))


def test_run_writes_json_report_and_summary(sample_md, tmp_path):
    out = tmp_path / "reports"
    result = runner.invoke(app, ["run", str(sample_md), "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert "Recommendation" in result.output
    assert "human_review" in result.output

    report_path = out / "sample.report.json"
    report = EvidenceReport.model_validate_json(report_path.read_text())
    rows = {row.check: row for row in report.ledger}
    assert rows["has_text"].result is True
    assert rows["word_count"].status == "ok"
    assert report.run.date is not None


def test_run_html_format(sample_md, tmp_path):
    out = tmp_path / "reports"
    result = runner.invoke(app, ["run", str(sample_md), "--out", str(out), "--format", "json,html"])

    assert result.exit_code == 0, result.output
    assert (out / "sample.report.json").exists()
    html = (out / "sample.report.html").read_text()
    assert "sample.md" in html
    assert "Prebunking" in html


def test_findings_never_fail_the_exit_code(tmp_path):
    """An empty doc fails has_text — that's evidence, not a tool failure."""
    blank = tmp_path / "blank.md"
    blank.write_text("   ")
    out = tmp_path / "reports"
    result = runner.invoke(app, ["run", str(blank), "--out", str(out)])

    assert result.exit_code == 0, result.output
    report = EvidenceReport.model_validate_json((out / "blank.report.json").read_text())
    rows = {row.check: row for row in report.ledger}
    assert rows["has_text"].result is False


def test_dry_run_lists_checks_and_calls_nothing(sample_md, tmp_path, scratch_registry):
    def paid(doc, ctx):  # pragma: no cover — the point is that it never runs
        raise AssertionError("--dry-run must not execute checks")

    registry_mod._REGISTRY["pangram_document"] = RegisteredCheck(
        meta=Check(
            id="pangram_document",
            name="AI detection (Pangram)",
            tier="api",
            est_cost_usd=1.25,
            needs_network=True,
        ),
        fn=paid,
    )
    out = tmp_path / "reports"
    result = runner.invoke(app, ["run", str(sample_md), "--out", str(out), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "has_text" in result.output
    assert "pangram_document" in result.output
    assert "$1.2500" in result.output  # total estimated spend, 1 doc
    assert "No checks were run" in result.output
    assert not out.exists()  # nothing written


def test_tier_and_skip_selection(sample_md, tmp_path):
    out = tmp_path / "reports"
    result = runner.invoke(
        app,
        [
            "run",
            str(sample_md),
            "--out",
            str(out),
            "--tier",
            "deterministic",
            "--skip",
            "word_count",
        ],
    )
    assert result.exit_code == 0, result.output
    report = EvidenceReport.model_validate_json((out / "sample.report.json").read_text())
    assert [row.check for row in report.ledger] == ["has_text"]


def test_unknown_check_id_is_tool_failure(sample_md):
    result = runner.invoke(app, ["run", str(sample_md), "--only", "nope"])
    assert result.exit_code == 2
    assert "unknown check id" in result.output


def test_bad_format_is_tool_failure(sample_md):
    result = runner.invoke(app, ["run", str(sample_md), "--format", "docx"])
    assert result.exit_code == 2


def test_unsupported_extension_points_at_ingestion(tmp_path):
    pdf = tmp_path / "proposal.pdf"
    pdf.write_bytes(b"%PDF-1.4 not really")
    result = runner.invoke(app, ["run", str(pdf)])
    assert result.exit_code == 1
    assert "#4" in result.output


def test_batch_ranks_by_concerns(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "clean.md").write_text(SAMPLE)
    (docs / "empty.md").write_text("  ")  # has_text fails -> 1 concern
    (docs / "also_clean.txt").write_text(SAMPLE)
    (docs / "notes.rst").write_text("ignored suffix")

    out = tmp_path / "reports"
    result = runner.invoke(app, ["run", str(docs), "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert "Batch summary" in result.output
    for stem in ("clean", "empty", "also_clean"):
        assert (out / f"{stem}.report.json").exists()
    assert not (out / "notes.report.json").exists()

    csv_lines = (out / "summary.csv").read_text().strip().splitlines()
    assert len(csv_lines) == 4  # header + 3 docs
    # empty.md has the most concerns -> ranked first
    assert csv_lines[1].startswith("empty.md,1")


def test_batch_empty_dir_is_tool_failure(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(app, ["run", str(empty)])
    assert result.exit_code == 1


def test_report_json_feeds_render_command(sample_md, tmp_path):
    """The #5/#6 output is valid input for Emerson's existing `render` (#19)."""
    out = tmp_path / "reports"
    assert runner.invoke(app, ["run", str(sample_md), "--out", str(out)]).exit_code == 0
    result = runner.invoke(app, ["render", str(out / "sample.report.json")])
    assert result.exit_code == 0, result.output
    assert (out / "sample.report.html").exists()


def test_help_is_readable(sample_md):
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    for phrase in ("proposal", "--dry-run", "--tier", "human"):
        assert phrase in result.output


def test_solicitation_recorded(sample_md, tmp_path):
    out = tmp_path / "reports"
    result = runner.invoke(
        app, ["run", str(sample_md), "--out", str(out), "--solicitation", "NSF-26-501"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads((out / "sample.report.json").read_text())
    assert data["solicitation"] == "NSF-26-501"
