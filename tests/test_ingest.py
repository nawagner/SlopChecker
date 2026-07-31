"""Ingestion tests (#4). All fixtures are FABRICATED (repo rule: no real
applicant material) and built programmatically — binary formats (PDF, DOCX)
are generated in-test so no blobs live in the repo. Fully offline.

Optional-dependency formats guard with importorskip so the suite degrades
when the pdf/docx extras aren't installed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from slopchecker.ingest import LOADERS, IngestResult, ingest, page_for_offset
from slopchecker.models import Span

# --- fabricated fixtures ----------------------------------------------------

MD_SAMPLE = """\
# Prebunking at Llama Scale

A fabricated proposal used only for testing. Nothing here is real.

## Introduction

We propose to inoculate 40,000 llamas against misinformation.

## Methods

Double-blind llama trials with a placebo pamphlet.

```python
# not a heading, just a comment in a code fence
```

## References

[1] Doe, J. (2025). Fabricated Llama Studies. doi:10.1/fabricated
"""

HTML_SAMPLE = """\
<html><head><title>Llama Grant</title><style>p { color: red }</style></head>
<body>
<h1>Llama Grant Proposal</h1>
<p>Fabricated for tests.</p>
<h2>Methods</h2>
<p>We will   survey <b>many</b> llamas.</p>
<script>var secretVar = 1;</script>
<h2>References</h2>
<p>[1] Doe, J. (2025). Fabricated Llama Studies.</p>
</body></html>
"""

TXT_SAMPLE = """\
Fabricated plain-text proposal.

The methods are entirely imaginary.

References

[1] Doe, J. (2025). Fabricated Llama Studies.
"""


def write(tmp_path: Path, name: str, content: str, newline: str = "\n") -> Path:
    path = tmp_path / name
    with open(path, "w", encoding="utf-8", newline=newline) as fh:
        fh.write(content)
    return path


# --- markdown ---------------------------------------------------------------


class TestMarkdown:
    def test_round_trip(self, tmp_path: Path) -> None:
        path = write(tmp_path, "proposal.md", MD_SAMPLE)
        result = ingest(path)
        assert result.status == "ok"
        assert result.document is not None
        assert result.document.text == MD_SAMPLE  # verbatim: offsets index the file
        assert result.document.media_type == "text/markdown"
        assert result.document.title == "Prebunking at Llama Scale"
        assert result.document.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()

    def test_span_slices_to_expected_snippet(self, tmp_path: Path) -> None:
        result = ingest(write(tmp_path, "proposal.md", MD_SAMPLE))
        assert result.document is not None
        text = result.document.text
        snippet = "Double-blind llama trials with a placebo pamphlet."
        span = Span(start=text.find(snippet), end=text.find(snippet) + len(snippet))
        assert text[span.start : span.end] == snippet

    def test_methods_section_findable(self, tmp_path: Path) -> None:
        result = ingest(write(tmp_path, "proposal.md", MD_SAMPLE))
        section = result.find_section("methods")  # case-insensitive
        assert section is not None
        assert section.level == 2
        assert result.document is not None
        body = result.document.text[section.span.start : section.span.end]
        assert body.startswith("## Methods")
        assert "placebo pamphlet" in body
        assert "[1] Doe" not in body  # section ends where References begins

    def test_code_fence_comment_is_not_a_heading(self, tmp_path: Path) -> None:
        result = ingest(write(tmp_path, "proposal.md", MD_SAMPLE))
        titles = [s.title for s in result.sections]
        assert titles == ["Prebunking at Llama Scale", "Introduction", "Methods", "References"]

    def test_references_region(self, tmp_path: Path) -> None:
        result = ingest(write(tmp_path, "proposal.md", MD_SAMPLE))
        assert result.references is not None
        assert result.document is not None
        region = result.document.text[result.references.start : result.references.end]
        assert region.startswith("## References")
        assert "doi:10.1/fabricated" in region

    def test_crlf_input_is_normalized(self, tmp_path: Path) -> None:
        result = ingest(write(tmp_path, "windows.md", MD_SAMPLE, newline="\r\n"))
        assert result.status == "ok"
        assert result.document is not None
        assert "\r" not in result.document.text
        assert result.find_section("Methods") is not None


# --- html -------------------------------------------------------------------


class TestHtml:
    def test_round_trip_and_structure(self, tmp_path: Path) -> None:
        result = ingest(write(tmp_path, "proposal.html", HTML_SAMPLE))
        assert result.status == "ok"
        assert result.document is not None
        assert result.document.media_type == "text/html"
        assert result.document.title == "Llama Grant"
        assert result.find_section("Methods") is not None

    def test_whitespace_collapsed_inline_markup_flattened(self, tmp_path: Path) -> None:
        result = ingest(write(tmp_path, "proposal.html", HTML_SAMPLE))
        assert result.document is not None
        snippet = "We will survey many llamas."
        text = result.document.text
        start = text.find(snippet)
        assert start != -1
        assert text[start : start + len(snippet)] == snippet

    def test_script_and_style_excluded(self, tmp_path: Path) -> None:
        result = ingest(write(tmp_path, "proposal.html", HTML_SAMPLE))
        assert result.document is not None
        assert "secretVar" not in result.document.text
        assert "color: red" not in result.document.text

    def test_references_region(self, tmp_path: Path) -> None:
        result = ingest(write(tmp_path, "proposal.html", HTML_SAMPLE))
        assert result.references is not None
        assert result.document is not None
        region = result.document.text[result.references.start : result.references.end]
        assert region.startswith("References")
        assert "Fabricated Llama Studies" in region


# --- plain text -------------------------------------------------------------


class TestText:
    def test_round_trip(self, tmp_path: Path) -> None:
        path = write(tmp_path, "proposal.txt", TXT_SAMPLE)
        result = ingest(path)
        assert result.status == "ok"
        assert result.document is not None
        assert result.document.text == TXT_SAMPLE
        assert result.document.media_type == "text/plain"

    def test_references_found_without_headings(self, tmp_path: Path) -> None:
        result = ingest(write(tmp_path, "proposal.txt", TXT_SAMPLE))
        assert result.references is not None
        assert result.document is not None
        region = result.document.text[result.references.start :]
        assert region.startswith("References")
        assert "[1] Doe" in region

    def test_empty_file_errors_with_reason(self, tmp_path: Path) -> None:
        result = ingest(write(tmp_path, "empty.txt", "  \n\n  "))
        assert result.status == "errored"
        assert result.document is None
        assert result.reason is not None
        assert "empty.txt" in result.reason


# --- pdf (optional dep: pymupdf) --------------------------------------------


def make_pdf(path: Path, pages: list[str]) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for content in pages:
        page = doc.new_page()
        page.insert_text((72, 72), content)
    doc.save(str(path))
    doc.close()


class TestPdf:
    PAGE1 = "Fabricated proposal about llamas.\nEntirely invented for testing."
    PAGE2 = "References\n[1] Doe, J. (2025). Fabricated Llama Studies."

    def test_two_page_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "proposal.pdf"
        make_pdf(path, [self.PAGE1, self.PAGE2])
        result = ingest(path)
        assert result.status == "ok"
        doc = result.document
        assert doc is not None
        assert doc.media_type == "application/pdf"
        assert doc.pages == 2
        assert doc.page_offsets is not None and len(doc.page_offsets) == 2
        assert doc.page_offsets[0] == 0
        assert doc.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()

    def test_span_slices_to_expected_snippet(self, tmp_path: Path) -> None:
        path = tmp_path / "proposal.pdf"
        make_pdf(path, [self.PAGE1, self.PAGE2])
        result = ingest(path)
        assert result.document is not None
        text = result.document.text
        snippet = "Fabricated proposal about llamas."
        span = Span(start=text.find(snippet), end=text.find(snippet) + len(snippet))
        assert span.start != -1
        assert text[span.start : span.end] == snippet

    def test_page_offsets_map_spans_to_pages(self, tmp_path: Path) -> None:
        path = tmp_path / "proposal.pdf"
        make_pdf(path, [self.PAGE1, self.PAGE2])
        result = ingest(path)
        assert result.document is not None and result.document.page_offsets is not None
        text = result.document.text
        page2_start = result.document.page_offsets[1]
        assert text.find("Fabricated proposal") < page2_start  # page 1 content
        assert text.find("[1] Doe") >= page2_start  # page 2 content
        assert page_for_offset(result.document, text.find("Fabricated proposal")) == 1
        assert page_for_offset(result.document, text.find("[1] Doe")) == 2

    def test_page_for_offset_none_without_pages(self, tmp_path: Path) -> None:
        result = ingest(write(tmp_path, "proposal.md", MD_SAMPLE))
        assert result.document is not None
        assert page_for_offset(result.document, 0) is None

    def test_references_region_via_line_fallback(self, tmp_path: Path) -> None:
        path = tmp_path / "proposal.pdf"
        make_pdf(path, [self.PAGE1, self.PAGE2])
        result = ingest(path)
        assert result.references is not None
        assert result.document is not None
        region = result.document.text[result.references.start :]
        assert region.startswith("References")
        assert "[1] Doe" in region

    def test_scanned_pdf_errors_actionably(self, tmp_path: Path) -> None:
        pymupdf = pytest.importorskip("pymupdf")
        path = tmp_path / "scan.pdf"
        doc = pymupdf.open()
        page = doc.new_page()
        page.draw_rect(pymupdf.Rect(50, 50, 300, 300), fill=(0.5, 0.5, 0.5))  # image-only-ish
        doc.save(str(path))
        doc.close()

        result = ingest(path)
        assert result.status == "errored"
        assert result.document is None
        assert result.reason is not None
        assert "scan.pdf" in result.reason
        assert "scanned" in result.reason
        assert "OCR" in result.reason

    def test_corrupt_pdf_errors_not_raises(self, tmp_path: Path) -> None:
        pytest.importorskip("pymupdf")
        path = tmp_path / "corrupt.pdf"
        path.write_bytes(b"%PDF-1.7 this is not really a pdf")
        result = ingest(path)
        assert result.status == "errored"
        assert result.reason is not None and "corrupt.pdf" in result.reason


# --- docx (optional dep: python-docx) ---------------------------------------


def make_docx(path: Path) -> None:
    docx_mod = pytest.importorskip("docx")
    doc = docx_mod.Document()
    doc.add_heading("Llama Grant Proposal", level=0)  # Title style
    doc.add_heading("Introduction", level=1)
    doc.add_paragraph("A fabricated proposal used only for testing.")
    doc.add_heading("Methods", level=1)
    doc.add_paragraph("Double-blind llama trials with a placebo pamphlet.")
    doc.add_heading("References", level=1)
    doc.add_paragraph("[1] Doe, J. (2025). Fabricated Llama Studies.")
    doc.save(str(path))


class TestDocx:
    def test_round_trip_and_structure(self, tmp_path: Path) -> None:
        path = tmp_path / "proposal.docx"
        make_docx(path)
        result = ingest(path)
        assert result.status == "ok"
        doc = result.document
        assert doc is not None
        assert doc.media_type == (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert doc.title == "Llama Grant Proposal"
        assert doc.pages is None  # DOCX has no fixed pagination
        assert doc.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()

    def test_span_slices_to_expected_snippet(self, tmp_path: Path) -> None:
        path = tmp_path / "proposal.docx"
        make_docx(path)
        result = ingest(path)
        assert result.document is not None
        text = result.document.text
        snippet = "Double-blind llama trials with a placebo pamphlet."
        span = Span(start=text.find(snippet), end=text.find(snippet) + len(snippet))
        assert text[span.start : span.end] == snippet

    def test_methods_section_findable(self, tmp_path: Path) -> None:
        path = tmp_path / "proposal.docx"
        make_docx(path)
        result = ingest(path)
        section = result.find_section("Methods")
        assert section is not None
        assert result.document is not None
        body = result.document.text[section.span.start : section.span.end]
        assert "placebo pamphlet" in body
        assert "[1] Doe" not in body

    def test_references_region(self, tmp_path: Path) -> None:
        path = tmp_path / "proposal.docx"
        make_docx(path)
        result = ingest(path)
        assert result.references is not None
        assert result.document is not None
        region = result.document.text[result.references.start : result.references.end]
        assert region.startswith("References")
        assert "Fabricated Llama Studies" in region


# --- dispatch + result invariants -------------------------------------------


class TestDispatch:
    def test_unsupported_extension(self, tmp_path: Path) -> None:
        path = write(tmp_path, "proposal.xyz", "whatever")
        result = ingest(path)
        assert result.status == "errored"
        assert result.reason is not None
        assert "proposal.xyz" in result.reason
        for suffix in LOADERS:
            assert suffix in result.reason  # message says what IS supported

    def test_missing_file(self, tmp_path: Path) -> None:
        result = ingest(tmp_path / "nope.pdf")
        assert result.status == "errored"
        assert result.reason is not None and "not found" in result.reason

    def test_accepts_str_paths(self, tmp_path: Path) -> None:
        path = write(tmp_path, "proposal.md", MD_SAMPLE)
        assert ingest(str(path)).status == "ok"


class TestResultInvariants:
    def test_ok_requires_document(self) -> None:
        with pytest.raises(ValueError, match="requires a document"):
            IngestResult(status="ok")

    def test_errored_requires_reason(self) -> None:
        with pytest.raises(ValueError, match="requires a reason"):
            IngestResult(status="errored")
