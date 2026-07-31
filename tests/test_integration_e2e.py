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
SYNTH_FILES = Path(__file__).resolve().parent / "fixtures" / "synthetic" / "files"

# Checks that really talk to third-party hosts (doi.org, Crossref, ...). Tests
# that use fixtures containing identifiers --skip these so `pytest -m
# integration` (part of the required `test` CI job) stays offline; the live
# behavior belongs to `-m live` (#114).
NETWORK_CHECKS = ("all_dois_resolve", "all_urls_resolve", "metadata_match")

# Credentials scrubbed from every subprocess (#142). Set to "" rather than
# deleted: `config.get()` reads blank as absent, and `load_dotenv(override=
# False)` cannot resurrect a variable that exists — so a keyed dev machine
# (shell exports OR a repo .env) runs this suite exactly like keyless CI
# instead of silently making paid Pangram/Anthropic calls.
SCRUBBED_VARS = (
    "ANTHROPIC_API_KEY",
    "PANGRAM_API_KEY",
    "CANDID_API_KEY",
    "SLOPCHECK_CACHE_URL",
    "SLOPCHECK_CACHE_TOKEN",
    "SLOPCHECK_LENS_CACHE_DIR",
)

PAGE1 = (
    "Fabricated Proposal: Llama-Assisted Sensor Networks\n"
    "Invented for integration testing. Prebunking achieves durable "
    "inoculation against misinformation [1]."
)
PAGE2 = "References\n[1] Doe, J. (2025). Fabricated Llama Studies. Journal of Invented Results."


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the real CLI in a real subprocess, with credentials scrubbed."""
    env = {**os.environ, **{var: "" for var in SCRUBBED_VARS}}
    return subprocess.run(
        [sys.executable, "-m", "slopchecker.cli", *args],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
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
    report = EvidenceReport.model_validate_json((out / "proposal.report.json").read_text("utf-8"))
    assert report.document.file == "proposal.pdf"
    assert report.document.media_type == "application/pdf"
    assert report.document.pages == 2
    rows = {row.check: row for row in report.ledger}
    assert rows["has_text"].result is True


def test_run_leg_ledger_covers_every_registered_check(chain):
    """Full-roster invariant (#142): a default (--tier all) run yields at
    least one ledger row per registered check — none missing, none errored,
    every skip carrying a reason. This is the cheap tripwire for registration
    regressions (the #12/#96 class: a check that exists but never runs)."""
    from slopchecker.pipeline import all_checks, discover

    discover()
    registered = {rc.meta.id for rc in all_checks()}
    assert len(registered) >= 12  # the roster only grows; shrinkage is a red flag

    _, out = chain
    report = EvidenceReport.model_validate_json((out / "proposal.report.json").read_text("utf-8"))
    ledger_ids = {row.check for row in report.ledger}

    missing = registered - ledger_ids
    assert not missing, f"registered checks with no ledger row: {sorted(missing)}"
    errored = [(row.check, row.reason) for row in report.ledger if row.status == "errored"]
    assert not errored, f"checks errored on a clean fixture: {errored}"
    unexplained = [row.check for row in report.ledger if row.status == "skipped" and not row.reason]
    assert not unexplained, f"skipped without a reason: {unexplained}"


def test_run_leg_keyless_api_and_llm_tiers_degrade_to_gaps(chain):
    """With credentials scrubbed (as in CI), the api/llm tiers must be
    skip rows naming the missing key — never errors, never silent absence."""
    _, out = chain
    report = EvidenceReport.model_validate_json((out / "proposal.report.json").read_text("utf-8"))
    rows = {row.check: row for row in report.ledger}
    for check, var in (("pangram_document", "PANGRAM_API_KEY"), ("claims", "ANTHROPIC_API_KEY")):
        assert rows[check].status == "skipped", f"{check}: {rows[check]}"
        assert var in (rows[check].reason or ""), f"{check} skip reason: {rows[check].reason!r}"
    assert rows["claim_supported"].status == "skipped"


def test_run_leg_writes_html(chain):
    _, out = chain
    html = (out / "proposal.report.html").read_text("utf-8")
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


# --- citations from a real rendered PDF (#126 regression lock) ---------------


def test_citation_checks_run_on_rendered_pdf_fixture(tmp_path):
    """The format that funders actually upload must yield citation coverage.

    Pre-#126, PDF (and MD) uploads reported "no reference list found" while
    DOCX/HTML parsed 9 identifiers from the same document — zero citation
    findings on the demo path. This drives the committed rendered PDF through
    the real CLI and asserts the offline citation checks actually RAN.
    Network checks are --skip'd so the required CI job stays offline; their
    live behavior is `-m live`'s job.
    """
    src = SYNTH_FILES / "grant_application__fabricated_citations.pdf"
    out = tmp_path / "reports"
    skip_args = [arg for check in NETWORK_CHECKS for arg in ("--skip", check)]
    proc = run_cli("run", str(src), "--out", str(out), *skip_args)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert_no_traceback(proc)

    report = EvidenceReport.model_validate_json(
        (out / "grant_application__fabricated_citations.report.json").read_text("utf-8")
    )
    assert report.document.media_type == "application/pdf"
    rows = {row.check: row for row in report.ledger}
    for check in ("citation_identifiers_valid", "citations_linked"):
        assert check in rows, f"{check} missing from ledger"
        assert rows[check].status == "ok", (
            f"{check} did not run on a PDF with a visible References section "
            f"(the #126 regression): status={rows[check].status} reason={rows[check].reason!r}"
        )
    # The fixture's planted DOIs are fabricated but well-formed (9/9).
    assert rows["citation_identifiers_valid"].result is True


# --- batch similarity: planted near-duplicate pair (#14 through the CLI) ------


def test_batch_similarity_flags_planted_near_duplicates(tmp_path):
    """The two-pass batch wiring (ingest all -> build ctx -> run per doc) is
    the newest CLI plumbing; drive it end-to-end with a planted near-dup pair
    and assert `similar_documents` fires in both reports."""
    pytest.importorskip("datasketch", reason="similarity extra required")
    docs = tmp_path / "docs"
    docs.mkdir()
    base = (HARNESS_FIXTURES / "proposal_climate.md").read_text("utf-8")
    (docs / "original.md").write_text(base, encoding="utf-8")
    (docs / "clone.md").write_text(
        base + "\n\nAddendum: fabricated near-duplicate for the integration suite.\n",
        encoding="utf-8",
    )

    out = tmp_path / "reports"
    skip_args = [arg for check in NETWORK_CHECKS for arg in ("--skip", check)]
    proc = run_cli("run", str(docs), "--out", str(out), *skip_args)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert_no_traceback(proc)

    for stem in ("original", "clone"):
        report = EvidenceReport.model_validate_json(
            (out / f"{stem}.report.json").read_text("utf-8")
        )
        rows = {row.check: row for row in report.ledger}
        row = rows.get("similar_documents")
        assert row is not None, f"{stem}: no similar_documents ledger row"
        assert row.status == "ok", f"{stem}: {row.status} {row.reason!r}"
        assert isinstance(row.result, int | float) and row.result >= 1, (
            f"{stem}: planted near-duplicate not flagged: result={row.result!r}"
        )


# --- batch mode: mixed folder -> per-file reports + gap rows ------------------


def test_batch_mixed_folder_reports_and_gaps(tmp_path):
    """Folder of mixed fixtures: readable docs get reports, duds become gap
    rows in summary.csv, the batch as a whole succeeds (exit 0, no crash)."""
    docs = tmp_path / "docs"
    docs.mkdir()
    # reuse the #79 harness corpus where it fits (fabricated by construction)
    (docs / "climate.md").write_text(
        (HARNESS_FIXTURES / "proposal_climate.md").read_text("utf-8"), encoding="utf-8"
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
        EvidenceReport.model_validate_json((out / f"{stem}.report.json").read_text("utf-8"))
    # duds got no report...
    assert not (out / "corrupt.report.json").exists()
    assert not (out / "scan.report.json").exists()
    assert not (out / "notes.report.json").exists()
    # ...but are recorded as gaps in summary.csv with their ingest reason
    csv_text = (out / "summary.csv").read_text("utf-8")
    csv_lines = csv_text.strip().splitlines()
    assert len(csv_lines) == 5  # header + 2 reports + 2 gap rows (.rst filtered)
    assert "could not open as PDF" in csv_text
    assert "scanned" in csv_text
