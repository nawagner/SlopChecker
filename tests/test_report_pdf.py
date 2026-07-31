"""Tests for PDF output. Skipped when no Chromium-family browser is installed."""

from __future__ import annotations

from pathlib import Path

import pytest

from slopchecker.report.pdf import find_browser, render_pdf

FIXTURE = Path(__file__).parent / "fixtures" / "sample_report.json"

needs_browser = pytest.mark.skipif(
    find_browser() is None, reason="no Chromium-family browser installed"
)


@needs_browser
def test_render_pdf_from_fixture(tmp_path):
    out = render_pdf(FIXTURE, tmp_path / "report.pdf")
    data = out.read_bytes()
    assert data[:5] == b"%PDF-"
    assert len(data) > 10_000  # a real multi-page render, not an empty shell


def test_render_pdf_default_sibling_path(tmp_path):
    src = tmp_path / "r.json"
    src.write_text(FIXTURE.read_text("utf-8"), encoding="utf-8")
    if find_browser() is None:
        pytest.skip("no Chromium-family browser installed")
    out = render_pdf(src)
    assert out == tmp_path / "r.pdf"
