"""Tests for the batch summary view (#20): rows in, one triage page out."""

from __future__ import annotations

import json
import re
from pathlib import Path

from slopchecker.report import render_batch, summarize_for_batch

FIXTURE = Path(__file__).parent / "fixtures" / "sample_report.json"


def _report(**over) -> dict:
    rep = {
        "document": {"file": "a.pdf", "text": "alpha beta"},
        "findings": [
            {
                "id": "DOI1",
                "anchor": {"quote": "alpha"},
                "checks": [{"name": "all_dois_resolve", "result": False}],
            },
            {
                "id": "P1",
                "anchor": {"quote": "beta"},
                "checks": [{"name": "pangram_document", "result": 0.93}],
            },
        ],
        "ledger": [
            {"check": "all_dois_resolve", "label": "DOIs", "result": False},
            {"check": "has_text", "label": "Text", "result": True},
            {"check": "pangram_document", "label": "Pangram", "result": 0.93},
            {
                "check": "doc_type_confidence",
                "label": "Doc type",
                "result": 0.75,
                "detail": "grant_application — budget justification",
            },
            {
                "check": "similar_documents",
                "label": "Similar",
                "status": "skipped",
                "reason": "batch of 1",
            },
            {
                "check": "metadata_match",
                "label": "Metadata",
                "status": "errored",
                "reason": "timeout",
            },
        ],
    }
    rep.update(over)
    return rep


def test_summarize_counts_and_derived_columns():
    row = summarize_for_batch(_report(), link="a.report.html")
    assert row["file"] == "a.pdf"
    assert row["concerns"] == 2  # 1 failed + 1 errored
    assert row["failed"] == 1
    assert row["passed"] == 1
    assert row["skipped"] == 1
    assert row["errored"] == 1
    assert row["pangram"] == 0.93
    assert row["doc_type"] == "grant_application"
    assert row["citation_flags"] == 1  # DOI1 has a failing check; P1 is a score
    assert row["similarity"] == ""  # skipped rows contribute nothing
    assert row["link"] == "a.report.html"


def test_render_batch_one_row_per_document_with_links():
    rows = [
        summarize_for_batch(_report(), link="a.report.html"),
        {"file": "broken.pdf", "error": "could not open as PDF"},
    ]
    out = render_batch(rows)
    assert '<a href="a.report.html">a.pdf</a>' in out
    # The gap row renders, labeled, without breaking the table.
    assert "broken.pdf" in out
    assert "not read" in out
    assert "could not open as PDF" in out  # surfaced as the row tooltip
    assert out.count("<tr>") + out.count("<tr ") == 3  # header + 2 rows


def test_render_batch_is_self_contained_and_embeds_rows():
    rows = [summarize_for_batch(_report(), link="a.report.html")]
    out = render_batch(rows)
    assert "<link" not in out
    assert not re.search(r"<script[^>]+src=", out)
    assert not re.search(r"""(?:src|href)\s*=\s*["']https?://""", out)
    # Exports are built from the embedded rows, not scraped from the DOM.
    embedded = json.loads(re.search(r'id="rows-json">(.*?)</script>', out, re.S).group(1))
    assert embedded == rows
    assert "Export CSV" in out and "Export JSON" in out


def test_render_batch_no_verdict_language():
    out = render_batch([summarize_for_batch(_report())])
    assert "Screening aid, not a determination" in out


def test_summarize_real_fixture_report_round_trips():
    rep = json.loads(FIXTURE.read_text("utf-8"))
    row = summarize_for_batch(rep)
    # Everything the exports carry is scalar — straight into CSV/JSON.
    assert all(isinstance(v, (str, int, float)) for v in row.values())
    render_batch([row])  # and it renders without blowing up
