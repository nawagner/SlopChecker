"""HTML → PDF for the evidence report (#19 follow-on).

The shipping artifact is a PDF (CLAUDE.md design decisions). Rather than pull
in a rendering dependency, this shells out to an installed Chromium-family
browser (Chrome, Edge, Chromium) in headless mode and prints the report using
the @media print stylesheet already in report.css. Every Windows box has Edge;
CI/Railway needs a chromium package or the CHROMIUM env var pointed at one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from slopchecker.report.html import render_file

_WINDOWS_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_browser() -> str | None:
    """Locate a Chromium-family binary; CHROMIUM env var wins."""
    env = os.environ.get("CHROMIUM")
    if env and Path(env).exists():
        return env
    for name in ("chrome", "chromium", "chromium-browser", "msedge", "google-chrome"):
        path = shutil.which(name)
        if path:
            return path
    for path in _WINDOWS_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def html_to_pdf(html_path: Path, pdf_path: Path, timeout: int = 60) -> Path:
    """Print an HTML file to PDF via headless Chromium."""
    browser = find_browser()
    if browser is None:
        raise RuntimeError(
            "No Chromium-family browser found for PDF output. Install Chrome/Edge "
            "or set CHROMIUM to a chromium binary."
        )
    # ignore_cleanup_errors: the throwaway profile may still be written to by
    # exiting browser children when the context closes; leftover tmp files are
    # preferable to a spurious OSError.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        subprocess.run(
            [
                browser,
                "--headless",
                "--disable-gpu",
                "--no-sandbox",
                # No crashpad/breakpad children: they inherit our stdout/stderr
                # pipes and outlive the browser process, which deadlocks
                # capture_output on Linux CI until the timeout kills the run.
                "--disable-crash-reporter",
                "--disable-breakpad",
                "--no-first-run",
                "--disable-dev-shm-usage",
                f"--user-data-dir={profile}",
                "--no-pdf-header-footer",
                f"--print-to-pdf={pdf_path}",
                Path(html_path).resolve().as_uri(),
            ],
            check=True,
            timeout=timeout,
            capture_output=True,
        )
    if not Path(pdf_path).exists():
        raise RuntimeError(f"Browser exited cleanly but produced no PDF at {pdf_path}")
    return Path(pdf_path)


def render_pdf(report_path: Path, out_path: Path | None = None) -> Path:
    """Render a report.json to PDF (via the HTML renderer + headless print)."""
    out = Path(out_path) if out_path else Path(report_path).with_suffix(".pdf")
    with tempfile.TemporaryDirectory() as tmp:
        html_path = render_file(report_path, Path(tmp) / "report.html")
        html_to_pdf(html_path, out)
    return out
