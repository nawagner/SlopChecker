"""Tests for the evidence report renderer (#19), against the fixture report."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from slopchecker.report import render_file, render_report

FIXTURE = Path(__file__).parent / "fixtures" / "sample_report.json"


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(FIXTURE.read_text("utf-8"))


@pytest.fixture(scope="module")
def html(report: dict) -> str:
    return render_report(report)


def test_every_finding_gets_mark_and_card(report, html):
    for finding in report["findings"]:
        fid = finding["id"].lower()
        assert f'id="anno-{fid}"' in html
        assert re.search(rf'<mark[^>]+data-anno="[^"]*\b{fid}\b', html)


def test_lanes_reflect_results(html):
    # C1 all-true -> yes; C3 has a false -> no; D1 numeric-only -> score
    assert re.search(r'<mark class="yes" data-anno="c1"', html)
    assert re.search(r'<mark class="no" data-anno="c3"', html)
    assert re.search(r'<mark class="score" data-anno="d1"', html)


def test_ledger_and_summary_counts(report, html):
    for row in report["ledger"]:
        assert row["label"] in html
    # Derived from the ledger, not copied from the input: the mock's
    # hand-written counts (4/3/2) were actually wrong for its own table.
    assert "NO ×5 · YES ×2 · scores ×2" in html
    assert "5 checks failed — flag for human review" in html


def test_self_contained(html):
    assert "<link" not in html
    assert not re.search(r"<script[^>]+src=", html)
    assert not re.search(r"""(?:src|href)\s*=\s*["']https?://""", html)
    assert "@import" not in html


def test_print_fallback_present(html):
    assert "@media print" in html


def test_generated_from_report_alone(report, html):
    # The page embeds the exact input it was rendered from.
    assert report["document"]["sha256"] in html
    assert "report.json (this page is a render of this)" in html


def test_no_verdict_language(html):
    assert "Screening aid, not a determination" in html
    assert "AI-generated: yes" not in html


def _doc_text(html: str) -> str:
    """Extract the rendered document body and strip tags back to plain text."""
    doc = re.search(r'<div class="doc">(.*?)</div>\s*<div class="rail">', html, re.S).group(1)
    doc = re.sub(r"<[^>]+>", "", doc)
    return doc


def test_overlapping_and_adjacent_spans():
    text = "alpha beta gamma delta epsilon"
    rep = {
        "document": {"file": "t.txt", "text": text},
        "findings": [
            {
                "id": "A1",
                "anchor": {"quote": "alpha beta gamma"},
                "checks": [{"name": "x", "result": False}],
            },
            {
                "id": "B1",
                "anchor": {"quote": "beta gamma delta"},
                "checks": [{"name": "y", "result": True}],
            },
            {
                "id": "C1",
                "anchor": {"quote": " epsilon"},
                "checks": [{"name": "z", "result": 0.5}],
            },
        ],
        "ledger": [],
    }
    out = render_report(rep)
    # The overlap segment carries both ids and the strongest (failing) lane.
    assert '<mark class="no" data-anno="a1 b1">beta gamma</mark>' in out
    # Text survives segmentation byte-for-byte.
    body = re.sub(r"<[^>]+>", "", re.search(r"<p>(.*?)</p>", out, re.S).group(1))
    assert body == text


def test_span_across_paragraph_break():
    rep = {
        "document": {"file": "t.txt", "text": "one two\n\nthree four"},
        "findings": [
            {
                "id": "A1",
                "anchor": {"quote": "two\n\nthree"},
                "checks": [{"name": "x", "result": False}],
            }
        ],
        "ledger": [],
    }
    out = render_report(rep)
    # One finding, two mark segments (one per paragraph), same id.
    assert len(re.findall(r'data-anno="a1"', out)) == 2


def test_document_text_is_escaped():
    rep = {
        "document": {"file": "t.txt", "text": "evil <script>alert(1)</script> text"},
        "findings": [],
        "ledger": [],
    }
    out = render_report(rep)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out


def test_missing_anchor_quote_still_renders_card():
    rep = {
        "document": {"file": "t.txt", "text": "some text"},
        "findings": [
            {
                "id": "A1",
                "anchor": {"quote": "not present anywhere"},
                "checks": [{"name": "x", "result": False}],
            }
        ],
        "ledger": [],
    }
    out = render_report(rep)
    assert 'id="anno-a1"' in out
    assert "<mark" not in out.split('<div class="rail">')[0].split('<div class="doc">')[1]


def test_pdf_style_text_splits_into_pages_not_one_wall():
    # Real PDF extraction has NO blank lines: single \n per visual line,
    # \f between pages. One <p> per page, a divider between pages, and an
    # anchor on page 2 still lands.
    text = "PI: Liu\nTitle: something\nline three\fpage two starts\nwith a fake citation"
    rep = {
        "document": {"file": "t.pdf", "text": text},
        "findings": [
            {
                "id": "C1",
                "anchor": {"quote": "fake citation"},
                "checks": [{"name": "x", "result": False}],
            }
        ],
        "ledger": [],
    }
    out = render_report(rep)
    doc_pane = out.split('<div class="rail">')[0]
    assert doc_pane.count("<p>") == 2  # one block per page, not one wall
    assert '<div class="pgbrk">p. 2</div>' in out
    assert '<mark class="no" data-anno="c1">fake citation</mark>' in out
    # The form feed itself never reaches the markup.
    assert "\f" not in out


def test_pdf_line_wraps_reflow_but_structure_stays():
    # Mid-sentence newlines (PDF line-wrap artifacts) render as spaces;
    # heading/key-value newlines keep their hard break.
    text = "PI: Liu\nTitle: something\nfield trials show durable\ngains from prebunking [1]."
    rep = {"document": {"file": "t.pdf", "text": text}, "findings": [], "ledger": []}
    out = render_report(rep)
    assert "durable gains from prebunking" in out  # soft-joined
    assert "PI: Liu\nTitle: something" in out  # hard breaks kept


def test_anchor_across_soft_joined_newline_still_marks():
    text = "evidence shows durable\ngains at scale in trials."
    rep = {
        "document": {"file": "t.pdf", "text": text},
        "findings": [
            {
                "id": "A1",
                "anchor": {"quote": "durable\ngains"},
                "checks": [{"name": "x", "result": False}],
            }
        ],
        "ledger": [],
    }
    out = render_report(rep)
    # The mark wraps the same characters, newline rendered as a space.
    assert '<mark class="no" data-anno="a1">durable gains</mark>' in out


def test_headings_in_extracted_text_get_their_own_block():
    text = (
        "Specific Aims\n"
        "We will measure the labor-market effects of remote work policy using a\n"
        "field experiment.\n"
        "Background\n"
        "Prior work has established a partial understanding.\n"
    )
    rep = {"document": {"file": "t.pdf", "text": text}, "findings": [], "ledger": []}
    out = render_report(rep)
    assert '<p class="dh">Specific Aims</p>' in out
    assert '<p class="dh">Background</p>' in out


def test_form_fields_and_wrapped_lines_are_not_headings():
    text = (
        "PI: Liu, George Y\n"
        "Received: 04/10/2023\n"
        "the sentence continues\n"
        "onto the next line here.\n"
    )
    rep = {"document": {"file": "t.pdf", "text": text}, "findings": [], "ledger": []}
    out = render_report(rep)
    assert 'class="dh"' not in out


def test_heading_detection_switches_off_on_form_like_documents():
    # A federal face page is mostly short labelled fields; bolding 70% of the
    # lines is worse than bolding none, so the heuristic disables itself.
    text = "".join(f"Field {n}\n" for n in range(40))
    rep = {"document": {"file": "form.pdf", "text": text}, "findings": [], "ledger": []}
    out = render_report(rep)
    assert 'class="dh"' not in out


def test_heading_split_preserves_anchor_offsets():
    text = "Background\nthe fabricated claim appears here in body text.\n"
    rep = {
        "document": {"file": "t.pdf", "text": text},
        "findings": [
            {
                "id": "A1",
                "anchor": {"quote": "fabricated claim"},
                "checks": [{"name": "x", "result": False}],
            }
        ],
        "ledger": [],
    }
    out = render_report(rep)
    assert '<mark class="no" data-anno="a1">fabricated claim</mark>' in out
    assert '<p class="dh">Background</p>' in out


def test_paragraph_offsets_survive_mixed_separators():
    # \n\n and \f both split; offsets must stay exact so anchors that sit
    # after a page break still highlight (regression for the +2 arithmetic).
    text = "alpha\n\nbeta\fgamma delta"
    rep = {
        "document": {"file": "t.pdf", "text": text},
        "findings": [
            {
                "id": "A1",
                "anchor": {"quote": "gamma"},
                "checks": [{"name": "x", "result": 0.5}],
            }
        ],
        "ledger": [],
    }
    out = render_report(rep)
    assert '<mark class="score" data-anno="a1">gamma</mark>' in out


def test_skipped_check_renders_as_gap_not_pass(html):
    # The fixture's plagiarism_scan row didn't run: muted chip, reason in the
    # detail column, excluded from result tallies, called out as a gap.
    assert '<td class="r skip">SKIPPED</td>' in html
    assert "no API key configured" in html
    assert "NO ×5 · YES ×2 · scores ×2 · not run ×1" in html
    assert "1 check could not run" in html


def test_errored_check_gets_muted_lane_not_red():
    rep = {
        "document": {"file": "t.txt", "text": "alpha beta"},
        "findings": [
            {
                "id": "A1",
                "anchor": {"quote": "alpha"},
                "checks": [{"name": "x", "status": "errored", "reason": "timeout"}],
            }
        ],
        "ledger": [{"check": "x", "label": "X", "status": "errored", "reason": "timeout"}],
    }
    out = render_report(rep)
    # A check that failed to RUN must not look like the document failed a check.
    assert '<mark class="skip" data-anno="a1"' in out
    assert '<td class="r skip">ERROR</td>' in out
    assert "timeout" in out
    assert '<mark class="no"' not in out


def test_clean_report_with_gaps_says_so():
    rep = {
        "document": {"file": "t.txt", "text": "fine"},
        "findings": [],
        "ledger": [
            {"check": "x", "label": "X", "result": True},
            {"check": "y", "label": "Y", "status": "skipped", "reason": "offline"},
        ],
    }
    out = render_report(rep)
    assert "No checks failed" in out
    assert "1 check could not run" in out
    assert "NO ×0 · YES ×1 · scores ×0 · not run ×1" in out


def test_clean_report_gets_ok_verdict():
    rep = {
        "document": {"file": "t.txt", "text": "fine"},
        "findings": [],
        "ledger": [{"check": "x", "label": "X", "result": True}],
    }
    out = render_report(rep)
    assert 'class="verdict ok"' in out
    assert "No checks failed" in out


def test_render_file_writes_sibling_html(tmp_path):
    src = tmp_path / "r.json"
    src.write_text(FIXTURE.read_text("utf-8"), encoding="utf-8")
    out = render_file(src)
    assert out == tmp_path / "r.html"
    assert out.read_text("utf-8").startswith("<!doctype html>")
