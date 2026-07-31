"""Integration tests: the full CLI chain on fabricated fixtures (#81).

    fabricated .pdf -> slopcheck run --format json,html -> report.json + report.html
    report.json     -> slopcheck render --pdf           -> paginated PDF

Opt-in: `pytest -m integration` (plain `pytest` deselects these via addopts,
so the default unit run stays fast). CI runs them as an explicit step.

Everything here drives the real CLI in a real subprocess (`python -m
slopchecker.cli`) — actual exit codes, actual entry point, and honest
"no Traceback" assertions. In-process CliRunner coverage of the same
commands lives in tests/test_cli_run.py; this file is chain plumbing.

Browser gate: `render --pdf` needs a Chromium-family browser. Where one is
*expected* (macOS dev machines, CI) a missing browser FAILS loudly — the
"2 skipped forever" trap is exactly what hid the bug PR #78 fixed (see
ai-log/2026-07-31-danparshall-pdf-macos-hang.md). Skips are legitimate only
on platforms with no browser expectation.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from slopchecker.models import EvidenceReport
from slopchecker.report.pdf import find_browser

pytestmark = pytest.mark.integration

pymupdf = pytest.importorskip("pymupdf", reason="pdf extra required for integration fixtures")

HARNESS_FIXTURES = Path(__file__).resolve().parents[1] / "harness" / "fixtures"

PAGE1 = (
    "Fabricated Proposal: Llama-Assisted Sensor Networks\n"
    "Invented for integration testing. Prebunking achieves durable "
    "inoculation against misinformation [1]."
)
PAGE2 = "References\n[1] Doe, J. (2025). Fabricated Llama Studies. Journal of Invented Results."


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the real CLI in a real subprocess."""
    return subprocess.run(
        [sys.executable, "-m", "slopchecker.cli", *args],
        capture_output=True,
        text=True,
        timeout=180,
    )


def assert_no_traceback(proc: subprocess.CompletedProcess[str]) -> None:
    combined = proc.stdout + proc.stderr
    assert "Traceback" not in combined, f"pipeline crashed instead of degrading:\n{combined}"


def make_pdf(path: Path, pages: list[str]) -> None:
    """Fabricated text-layer PDF (pattern from tests/test_ingest.py)."""
    doc = pymupdf.open()
    for content in pages:
        page = doc.new_page()
        page.insert_text((72, 72), content)
    doc.save(str(path))
    doc.close()


def make_scanned_pdf(path: Path) -> None:
    """A no-text-layer ("scanned") PDF: one page of drawn geometry, no text."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(50, 50, 300, 300), fill=(0.5, 0.5, 0.5))
    doc.save(str(path))
    doc.close()


def browser_expected() -> bool:
    """Platforms where a Chromium-family browser must be present: macOS dev
    machines (the whole team) and CI (ubuntu runners ship google-chrome)."""
    return sys.platform == "darwin" or os.environ.get("CI", "").lower() in {"1", "true"}


# --- run leg: PDF -> report.json + report.html -------------------------------


@pytest.fixture(scope="module")
def chain(tmp_path_factory: pytest.TempPathFactory):
    """Run the `run` leg once on a fabricated 2-page PDF; several tests
    assert different artifacts of the same invocation."""
    root = tmp_path_factory.mktemp("chain")
    pdf = root / "proposal.pdf"
    make_pdf(pdf, [PAGE1, PAGE2])
    out = root / "reports"
    proc = run_cli("run", str(pdf), "--out", str(out), "--format", "json,html")
    return proc, out


def test_run_leg_exits_cleanly(chain):
    proc, _ = chain
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert_no_traceback(proc)


def test_run_leg_report_json_validates_against_model(chain):
    """report.json is the contract (#3) — it must round-trip EvidenceReport."""
    _, out = chain
    report = EvidenceReport.model_validate_json((out / "proposal.report.json").read_text())
    assert report.document.file == "proposal.pdf"
    assert report.document.media_type == "application/pdf"
    assert report.document.pages == 2
    rows = {row.check: row for row in report.ledger}
    assert rows["has_text"].result is True


def test_run_leg_writes_html(chain):
    _, out = chain
    html = (out / "proposal.report.html").read_text()
    assert "proposal.pdf" in html
    assert "Llama-Assisted" in html


# --- render leg: report.json -> paginated PDF --------------------------------


def test_browser_is_findable_where_expected():
    """The loud-fail gate. On macOS and CI a missing browser is a FAILURE,
    not a skip — silent skips are how the PDF leg went dark for weeks (#78)."""
    if not browser_expected():
        pytest.skip("no browser expectation on this platform")
    assert find_browser() is not None, (
        "No Chromium-family browser found on a platform that should have one "
        "(macOS dev machine or CI). The PDF leg of the pipeline is dark. "
        "Install Chrome/Edge or set CHROMIUM — do not let this skip silently; "
        "see ai-log/2026-07-31-danparshall-pdf-macos-hang.md and PR #78."
    )


def test_render_leg_produces_pdf(chain, tmp_path):
    if find_browser() is None:
        if browser_expected():
            pytest.fail("browser expected here but not found — see the gate test above")
        pytest.skip("no Chromium-family browser installed (legitimate on this platform)")
    _, out = chain
    pdf_out = tmp_path / "evidence.pdf"
    proc = run_cli("render", str(out / "proposal.report.json"), "--pdf", "--out", str(pdf_out))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert_no_traceback(proc)
    data = pdf_out.read_bytes()
    assert data[:5] == b"%PDF-"
    assert len(data) > 1_000  # a real render, not an empty shell


# --- degrade to gaps, never crash --------------------------------------------


def test_scanned_pdf_degrades_single_file(tmp_path):
    """No text layer -> actionable gap (exit 1 + reason), never a stack trace."""
    scan = tmp_path / "scan.pdf"
    make_scanned_pdf(scan)
    proc = run_cli("run", str(scan), "--out", str(tmp_path / "reports"))
    assert proc.returncode == 1
    assert_no_traceback(proc)
    combined = proc.stdout + proc.stderr
    assert "scan.pdf" in combined
    assert "scanned" in combined


def test_corrupt_pdf_degrades_single_file(tmp_path):
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.7 these bytes do not parse")
    proc = run_cli("run", str(corrupt), "--out", str(tmp_path / "reports"))
    assert proc.returncode == 1
    assert_no_traceback(proc)
    assert "could not open as PDF" in proc.stdout + proc.stderr


def test_unsupported_suffix_degrades_single_file(tmp_path):
    rst = tmp_path / "notes.rst"
    rst.write_text("Fine content, unsupported proposal format.")
    proc = run_cli("run", str(rst), "--out", str(tmp_path / "reports"))
    assert proc.returncode == 1
    assert_no_traceback(proc)
    assert "unsupported format" in proc.stdout + proc.stderr


# --- batch mode: mixed folder -> per-file reports + gap rows ------------------


def test_batch_mixed_folder_reports_and_gaps(tmp_path):
    """Folder of mixed fixtures: readable docs get reports, duds become gap
    rows in summary.csv, the batch as a whole succeeds (exit 0, no crash)."""
    docs = tmp_path / "docs"
    docs.mkdir()
    # reuse the #79 harness corpus where it fits (fabricated by construction)
    (docs / "climate.md").write_text(
        (HARNESS_FIXTURES / "proposal_climate.md").read_text(), encoding="utf-8"
    )
    make_pdf(docs / "proposal.pdf", [PAGE1, PAGE2])
    (docs / "corrupt.pdf").write_bytes(b"%PDF-1.7 nope")
    make_scanned_pdf(docs / "scan.pdf")
    (docs / "notes.rst").write_text("unsupported suffix — filtered pre-ingest")

    out = tmp_path / "reports"
    proc = run_cli("run", str(docs), "--out", str(out))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert_no_traceback(proc)
    # readable docs got reports — and they validate against the model
    for stem in ("climate", "proposal"):
        EvidenceReport.model_validate_json((out / f"{stem}.report.json").read_text())
    # duds got no report...
    assert not (out / "corrupt.report.json").exists()
    assert not (out / "scan.report.json").exists()
    assert not (out / "notes.report.json").exists()
    # ...but are recorded as gaps in summary.csv with their ingest reason
    csv_text = (out / "summary.csv").read_text()
    csv_lines = csv_text.strip().splitlines()
    assert len(csv_lines) == 5  # header + 2 reports + 2 gap rows (.rst filtered)
    assert "could not open as PDF" in csv_text
    assert "scanned" in csv_text
