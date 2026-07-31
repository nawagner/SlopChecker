"""Evidence report rendering (#19): report.json in, self-contained HTML/PDF out."""

from slopchecker.report.html import render_file, render_report
from slopchecker.report.pdf import render_pdf

__all__ = ["render_file", "render_pdf", "render_report"]
