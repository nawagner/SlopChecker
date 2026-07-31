"""Evidence report rendering (#19): report.json in, self-contained HTML/PDF out."""

from slopchecker.report.batch import render_batch, summarize_for_batch
from slopchecker.report.html import render_file, render_report
from slopchecker.report.pdf import render_pdf

__all__ = ["render_batch", "render_file", "render_pdf", "render_report", "summarize_for_batch"]
