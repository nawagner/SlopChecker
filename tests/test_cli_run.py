"""`slopcheck run` (#6). Offline: built-in checks only, plus fake registrations.

PDF-format tests build fixtures in-test via pymupdf (importorskip pattern
from tests/test_ingest.py) so no binary blobs live in the repo.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slopchecker.cli import app
from slopchecker.models import Check, EvidenceReport, LedgerRow
from slopchecker.pipeline import CheckOutput, RegisteredCheck
from slopchecker.pipeline import registry as registry_mod

runner = CliRunner()

SAMPLE = "Prebunking achieves durable inoculation [1].\n\n[1] Doe, J. (2025)."

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(result) -> str:
    """result.output with ANSI style codes stripped. On CI rich emits color
    codes that split tokens mid-word ("--dry" + "-run", "$" + "1.2500"), so
    every substring assertion goes through this."""
    return _ANSI.sub("", result.output)


@pytest.fixture
def sample_md(tmp_path):
    p = tmp_path / "sample.md"
    p.write_text(SAMPLE)
    return p


@pytest.fixture
def scratch_registry(monkeypatch):
    """A copy of the real registry (built-ins included) tests may add fakes to.

    discover() first: with the real check modules already imported, a test
    overwriting an id (e.g. a fake pangram_document) can't collide with a
    later import-time register() when the CLI calls discover() itself.
    """
    registry_mod.discover()
    monkeypatch.setattr(registry_mod, "_REGISTRY", dict(registry_mod._REGISTRY))


def make_pdf(path: Path, pages: list[str]) -> None:
    """Fabricated PDF fixture (same pattern as tests/test_ingest.py::make_pdf)."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for content in pages:
        page = doc.new_page()
        page.insert_text((72, 72), content)
    doc.save(str(path))
    doc.close()


def test_run_writes_json_report_and_summary(sample_md, tmp_path):
    out = tmp_path / "reports"
    result = runner.invoke(app, ["run", str(sample_md), "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert "Recommendation" in plain(result)
    assert "human_review" in plain(result)

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


def test_findings_never_fail_the_exit_code(sample_md, tmp_path, scratch_registry):
    """A failing check is evidence, not a tool failure — exit stays 0.

    (Empty-document scenarios are now caught at the ingest layer per #4/#58,
    so we register a fake always-fails check to still exercise the invariant.)
    """

    def always_fails(doc, ctx):
        return CheckOutput(
            ledger=[LedgerRow(check="always_fails", label="Contrived failure", result=False)]
        )

    registry_mod._REGISTRY["always_fails"] = RegisteredCheck(
        meta=Check(id="always_fails", name="Contrived failure", tier="deterministic"),
        fn=always_fails,
    )
    out = tmp_path / "reports"
    result = runner.invoke(app, ["run", str(sample_md), "--out", str(out)])

    assert result.exit_code == 0, result.output
    report = EvidenceReport.model_validate_json((out / "sample.report.json").read_text())
    rows = {row.check: row for row in report.ledger}
    assert rows["always_fails"].result is False


def test_dry_run_lists_checks_and_calls_nothing(sample_md, tmp_path, scratch_registry, monkeypatch):
    # Pin the console wide: at narrow widths rich shrinks the id column and
    # folds/ellipsizes "pangram_document", failing the substring asserts for
    # rendering reasons only (legacy Windows consoles are ~1 char narrower
    # than CI, which is why this only ever broke locally).
    import rich.console

    from slopchecker import cli as cli_mod

    monkeypatch.setattr(cli_mod, "console", rich.console.Console(width=200))

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
    # --only pins the table to two short rows: with the full registry the id
    # column can get width-truncated (locally and as more checks register),
    # which breaks the substring assertions for rendering reasons only.
    only = ["--only", "has_text", "--only", "pangram_document"]
    result = runner.invoke(app, ["run", str(sample_md), "--out", str(out), "--dry-run", *only])

    assert result.exit_code == 0, result.output
    assert "has_text" in plain(result)
    assert "pangram_document" in plain(result)
    assert "$1.2500" in plain(result)  # total estimated spend, 1 doc
    assert "No checks were run" in plain(result)
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
    checks = [row.check for row in report.ledger]
    # Intent: --tier deterministic keeps a deterministic check and --skip drops
    # word_count. Assert that intent, not the exact set — new deterministic
    # checks (e.g. tagging, #15) legitimately add rows here.
    assert "has_text" in checks
    assert "word_count" not in checks


def test_unknown_check_id_is_tool_failure(sample_md):
    result = runner.invoke(app, ["run", str(sample_md), "--only", "nope"])
    assert result.exit_code == 2
    assert "unknown check id" in plain(result)


def test_bad_format_is_tool_failure(sample_md):
    result = runner.invoke(app, ["run", str(sample_md), "--format", "docx"])
    assert result.exit_code == 2


def test_unsupported_extension_reports_ingest_error(tmp_path):
    """A file whose suffix isn't in LOADERS gets an actionable ingest error."""
    rst = tmp_path / "notes.rst"
    rst.write_text("Content is fine, but .rst isn't a supported proposal format.")
    result = runner.invoke(app, ["run", str(rst)])
    assert result.exit_code == 1
    out = plain(result)
    assert "notes.rst" in out
    assert "unsupported format" in out


def test_corrupt_pdf_reports_ingest_error(tmp_path):
    """A .pdf whose bytes don't parse: ingest catches it, CLI surfaces the gap."""
    pytest.importorskip("pymupdf")
    pdf = tmp_path / "corrupt.pdf"
    pdf.write_bytes(b"%PDF-1.7 this is not really a pdf")
    result = runner.invoke(app, ["run", str(pdf)])
    assert result.exit_code == 1
    out = plain(result)
    assert "corrupt.pdf" in out
    assert "could not open as PDF" in out


def test_run_reads_pdf_end_to_end(tmp_path):
    """PDF ingest -> checks -> report.json, with page count preserved (#58)."""
    pdf = tmp_path / "proposal.pdf"
    make_pdf(
        pdf,
        [
            "Fabricated proposal about llamas.\nInvented for testing.",
            "References\n[1] Doe, J. (2025). Fabricated Llama Studies.",
        ],
    )
    out = tmp_path / "reports"
    result = runner.invoke(app, ["run", str(pdf), "--out", str(out)])

    assert result.exit_code == 0, result.output
    report_path = out / "proposal.report.json"
    assert report_path.exists()
    report = EvidenceReport.model_validate_json(report_path.read_text())
    assert report.document.file == "proposal.pdf"
    assert report.document.media_type == "application/pdf"
    assert report.document.pages == 2
    rows = {row.check: row for row in report.ledger}
    assert rows["has_text"].result is True


def test_batch_ranks_by_concerns(tmp_path, scratch_registry):
    """Batch mode ranks by concerns descending; unsupported suffixes are filtered."""

    def flag_bad(doc, ctx):
        ok = "bad" not in doc.text.lower()
        return CheckOutput(ledger=[LedgerRow(check="flag_bad", label="No bad phrases", result=ok)])

    registry_mod._REGISTRY["flag_bad"] = RegisteredCheck(
        meta=Check(id="flag_bad", name="No bad phrases", tier="deterministic"),
        fn=flag_bad,
    )

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "high_concern.md").write_text("This is bad.\n\n" + SAMPLE)
    (docs / "low_concern.txt").write_text(SAMPLE)
    (docs / "notes.rst").write_text("ignored suffix — not in LOADERS")

    out = tmp_path / "reports"
    # --only: pin the check set so the ranking assertions don't break every
    # time a new check gets registered (they assert exact concern counts).
    result = runner.invoke(app, ["run", str(docs), "--out", str(out), "--only", "flag_bad"])

    assert result.exit_code == 0, result.output
    assert "Batch summary" in plain(result)
    for stem in ("high_concern", "low_concern"):
        assert (out / f"{stem}.report.json").exists()
    assert not (out / "notes.report.json").exists()

    csv_lines = (out / "summary.csv").read_text().strip().splitlines()
    assert len(csv_lines) == 3  # header + 2 readable docs (.rst filtered pre-ingest)
    # high_concern.md fails flag_bad -> 1 concern; low_concern has 0 -> high first
    assert csv_lines[1].startswith("high_concern.md,1")
    assert csv_lines[2].startswith("low_concern.txt,0")


def test_batch_records_ingest_gaps_alongside_reports(tmp_path):
    """A batch with a mix of readable and unreadable files: readable ones get
    reports, unreadable ones show up as 'not read' gap rows in the summary."""
    pytest.importorskip("pymupdf")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "clean.md").write_text(SAMPLE)
    (docs / "empty.md").write_text("   ")  # ingest -> errored (no text)
    (docs / "corrupt.pdf").write_bytes(b"%PDF-1.7 nope")

    out = tmp_path / "reports"
    result = runner.invoke(app, ["run", str(docs), "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert "Batch summary" in plain(result)
    # readable file got a report
    assert (out / "clean.report.json").exists()
    # unreadable ones did NOT
    assert not (out / "empty.report.json").exists()
    assert not (out / "corrupt.report.json").exists()
    # both gaps are surfaced in the on-screen summary
    out_text = plain(result)
    assert "empty.md" in out_text and "not read" in out_text
    assert "corrupt.pdf" in out_text

    csv_lines = (out / "summary.csv").read_text().strip().splitlines()
    assert len(csv_lines) == 4  # header + 3 docs
    # every gap row has its 'error' column populated with the ingest reason
    joined = "\n".join(csv_lines[1:])
    assert "no text" in joined
    assert "could not open as PDF" in joined


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
        assert phrase in plain(result)


def test_solicitation_recorded(sample_md, tmp_path):
    out = tmp_path / "reports"
    result = runner.invoke(
        app, ["run", str(sample_md), "--out", str(out), "--solicitation", "NSF-26-501"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads((out / "sample.report.json").read_text())
    assert data["solicitation"] == "NSF-26-501"
