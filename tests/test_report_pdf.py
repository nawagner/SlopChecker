"""Tests for PDF output.

Split deliberately (#118). Printing a PDF means launching headless Chrome,
which cost ~11s of a 16s CI unit run — two cold browser starts, only one of
which was actually about rendering:

- **Path/plumbing tests stub the browser.** Deriving `r.json` → `r.pdf` is our
  logic, not Chrome's. Stubbing makes them instant *and* makes them run on
  machines with no browser at all, where they previously skipped — so the path
  logic is now tested in more places, not fewer.
- **The one real render is marked `integration`**, so the default unit suite
  never launches a browser. It still runs in CI on every PR, in the `test`
  job's `pytest -m integration` step — deliberately inside the required check
  rather than a parallel job, because trading gate coverage for a few seconds
  is the mistake #114's review caught.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from slopchecker.report import pdf as pdf_module
from slopchecker.report.pdf import find_browser, render_pdf

FIXTURE = Path(__file__).parent / "fixtures" / "sample_report.json"

needs_browser = pytest.mark.skipif(
    find_browser() is None, reason="no Chromium-family browser installed"
)


@pytest.fixture
def stub_browser(monkeypatch):
    """Replace the headless-print step; everything above it stays real.

    `render_file` still renders the HTML for real, so this exercises all of
    `render_pdf` except the subprocess we don't want to pay for.
    """
    calls: list[tuple[Path, Path, str]] = []

    def fake_html_to_pdf(html_path, pdf_path, timeout=60):
        # Read the HTML *now*: render_pdf builds it inside a TemporaryDirectory
        # that is gone by the time the test body runs.
        calls.append((Path(html_path), Path(pdf_path), Path(html_path).read_text("utf-8")))
        Path(pdf_path).write_bytes(b"%PDF-1.4\nstub\n")
        return Path(pdf_path)

    monkeypatch.setattr(pdf_module, "html_to_pdf", fake_html_to_pdf)
    return calls


# --------------------------------------------------------------------------
# Plumbing — no browser required
# --------------------------------------------------------------------------


def test_render_pdf_defaults_to_a_sibling_pdf_path(tmp_path, stub_browser) -> None:
    """`r.json` → `r.pdf` beside it. Our path logic, so no browser needed.

    This used to skip wherever Chrome was absent, which meant the default
    output path went unverified on exactly the machines most likely to get it
    wrong.
    """
    src = tmp_path / "r.json"
    src.write_text(FIXTURE.read_text("utf-8"), encoding="utf-8")

    out = render_pdf(src)

    assert out == tmp_path / "r.pdf"
    assert out.exists()
    _, printed_to, _ = stub_browser[0]
    assert printed_to == tmp_path / "r.pdf"


def test_render_pdf_honours_an_explicit_out_path(tmp_path, stub_browser) -> None:
    src = tmp_path / "r.json"
    src.write_text(FIXTURE.read_text("utf-8"), encoding="utf-8")
    target = tmp_path / "nested" / "custom.pdf"
    target.parent.mkdir()

    out = render_pdf(src, target)

    assert out == target
    _, printed_to, _ = stub_browser[0]
    assert printed_to == target


def test_render_pdf_prints_the_rendered_html_not_the_json(tmp_path, stub_browser) -> None:
    """The browser must be handed HTML the renderer produced, not report.json."""
    src = tmp_path / "r.json"
    src.write_text(FIXTURE.read_text("utf-8"), encoding="utf-8")

    render_pdf(src)

    html_path, _, html_text = stub_browser[0]
    assert html_path.suffix == ".html"
    assert "<html" in html_text.lower()


def test_missing_browser_is_a_clear_error(tmp_path, monkeypatch) -> None:
    """Degrade to a legible message, never a bare FileNotFoundError."""
    monkeypatch.setattr(pdf_module, "find_browser", lambda: None)
    with pytest.raises(RuntimeError, match="No Chromium-family browser"):
        pdf_module.html_to_pdf(tmp_path / "in.html", tmp_path / "out.pdf")


# --------------------------------------------------------------------------
# The real thing — one browser launch, off the unit critical path
# --------------------------------------------------------------------------


@pytest.mark.integration
@needs_browser
def test_render_pdf_from_fixture(tmp_path) -> None:
    """The only test in the suite that actually launches a browser."""
    out = render_pdf(FIXTURE, tmp_path / "report.pdf")
    data = out.read_bytes()
    assert data[:5] == b"%PDF-"
    assert len(data) > 10_000  # a real multi-page render, not an empty shell
