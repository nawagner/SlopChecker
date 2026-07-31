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
import time
from pathlib import Path

from slopchecker.report.html import render_file

_WINDOWS_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# macOS app bundles are never on PATH, so `shutil.which` can't see them.
_MACOS_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


def find_browser() -> str | None:
    """Locate a Chromium-family binary; CHROMIUM env var wins."""
    env = os.environ.get("CHROMIUM")
    if env and Path(env).exists():
        return env
    # google-chrome/chrome before chromium: on Ubuntu, `chromium` is usually a
    # snap wrapper whose confinement rejects a /tmp --user-data-dir and hangs
    # headless (exactly what happened on CI runners, which have both).
    for name in ("google-chrome", "chrome", "msedge", "chromium-browser", "chromium"):
        path = shutil.which(name)
        if path:
            return path
    for path in _WINDOWS_CANDIDATES + _MACOS_CANDIDATES:
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
        stderr_path = Path(profile) / "browser-stderr.log"
        cmd = [
            browser,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            # No crashpad/breakpad children: they inherit our stdout/stderr
            # handles and outlive the browser process; keeping stderr in a
            # file (not a pipe) makes that survivable everywhere.
            "--disable-crash-reporter",
            "--disable-breakpad",
            "--no-first-run",
            "--disable-dev-shm-usage",
            f"--user-data-dir={profile}",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            Path(html_path).resolve().as_uri(),
        ]
        # Chrome's "new headless" (>=132) can finish the print but never
        # exit — observed on macOS with Chrome 150 (main + gpu/utility
        # helpers park indefinitely after the PDF is written; no flag set
        # prevents it). So completion is judged by the artifact, not the
        # exit: poll for a size-stable PDF, then reap the browser.
        out = Path(pdf_path)
        with stderr_path.open("wb") as stderr_file:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=stderr_file)
            deadline = time.monotonic() + timeout
            last_size = -1
            try:
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        break
                    size = out.stat().st_size if out.exists() else -1
                    if size > 0 and size == last_size:
                        break  # PDF written and stable; browser is just lingering
                    last_size = size
                    time.sleep(0.25)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
        if not out.exists() or out.stat().st_size == 0:
            tail = stderr_path.read_bytes()[-2000:].decode(errors="replace")
            raise RuntimeError(
                f"Browser produced no PDF at {pdf_path} "
                f"(exit code {proc.returncode}). stderr tail:\n{tail}"
            )
    return out


def render_pdf(report_path: Path, out_path: Path | None = None) -> Path:
    """Render a report.json to PDF (via the HTML renderer + headless print)."""
    out = Path(out_path) if out_path else Path(report_path).with_suffix(".pdf")
    with tempfile.TemporaryDirectory() as tmp:
        html_path = render_file(report_path, Path(tmp) / "report.html")
        html_to_pdf(html_path, out)
    return out
