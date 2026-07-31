"""Post-ingest mutation for the validation harness (#71).

Sibling of tests/test_harness.py: exercises the post-ingest mutation path
(mutate `FlattenedDoc.text` after the loader runs, then run checks). Keeps
the injector-style discipline (missing-original is a hard error, deletion
via empty `mutated`, first-occurrence match) but adds mechanical span
shifting for `references`, `sections`, and `page_offsets`.

Offline, deterministic, part of the normal pytest run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "harness"))

pytest.importorskip("yaml")

from post_ingest import mutate_ingest_result  # noqa: E402
from run import run_harness  # noqa: E402

from slopchecker.ingest import ingest  # noqa: E402
from slopchecker.ingest.types import IngestResult, Section  # noqa: E402
from slopchecker.models import FlattenedDoc, Span  # noqa: E402

# --- Helpers ---------------------------------------------------------------


def _ingest_result(
    text: str,
    *,
    references: Span | None = None,
    sections: list[Section] | None = None,
    page_offsets: list[int] | None = None,
) -> IngestResult:
    """Small factory so tests read as scenarios, not object construction."""
    return IngestResult(
        status="ok",
        document=FlattenedDoc(file="fake.md", text=text, page_offsets=page_offsets),
        sections=sections or [],
        references=references,
    )


# --- Core mutation semantics -----------------------------------------------


def test_mutate_replaces_text_in_flattened_doc():
    result = _ingest_result("hello world")
    mutated, manifest = mutate_ingest_result(
        result, [{"id": "d1", "original": "world", "mutated": "mars"}]
    )
    assert mutated.document.text == "hello mars"
    assert manifest[0]["id"] == "d1"


def test_mutate_deletion_via_empty_mutated_string():
    result = _ingest_result("keep this. DELETE THIS. keep this too.")
    mutated, _ = mutate_ingest_result(
        result, [{"id": "d1", "original": "DELETE THIS. ", "mutated": ""}]
    )
    assert mutated.document.text == "keep this. keep this too."


def test_mutate_missing_original_is_hard_error():
    """A silently unplanted defect would count as MISS forever and drag
    recall for a reason unrelated to check quality."""
    result = _ingest_result("hello world")
    with pytest.raises(ValueError, match="original text not found"):
        mutate_ingest_result(result, [{"id": "phantom", "original": "not here", "mutated": "x"}])


def test_mutate_records_line_number_of_original():
    result = _ingest_result("line one\nline two\nDEFECT here\nline four")
    _, manifest = mutate_ingest_result(
        result, [{"id": "d1", "original": "DEFECT", "mutated": "FIXED"}]
    )
    assert manifest[0]["line"] == 3


def test_mutate_applies_multiple_defects_sequentially():
    """Each subsequent defect sees the already-mutated text — matches the
    pre-ingest injector's contract so recall scoring rules stay identical."""
    result = _ingest_result("alpha beta gamma")
    mutated, _ = mutate_ingest_result(
        result,
        [
            {"id": "d1", "original": "alpha", "mutated": "ALPHA"},
            {"id": "d2", "original": "gamma", "mutated": "GAMMA"},
        ],
    )
    assert mutated.document.text == "ALPHA beta GAMMA"


def test_mutate_passes_through_match_and_pending_fields():
    """Manifest entries carry the same recall-scoring metadata as the
    pre-ingest injector's manifest."""
    result = _ingest_result("hello world")
    _, manifest = mutate_ingest_result(
        result,
        [
            {
                "id": "d1",
                "original": "world",
                "mutated": "mars",
                "match": {"kind": "unlinked_citation_number", "number": 9},
                "check_expected": "citation_has_reference",
                "description": "swap [1] for [9]",
                "pending_lens": None,
            }
        ],
    )
    entry = manifest[0]
    assert entry["match"] == {"kind": "unlinked_citation_number", "number": 9}
    assert entry["check_expected"] == "citation_has_reference"
    assert entry["description"] == "swap [1] for [9]"


# --- Span shifting ---------------------------------------------------------


def test_mutate_shifts_downstream_references_span_when_body_grows():
    """References span sits after the mutation; a length-changing mutation
    in the body must shift the references span by the same delta or the
    quote-check will read the wrong region."""
    text = "body text with WORD here.\n\nReferences\n[1] paper."
    refs_start = text.index("References")
    result = _ingest_result(text, references=Span(start=refs_start, end=len(text)))

    mutated, _ = mutate_ingest_result(
        result, [{"id": "d1", "original": "WORD", "mutated": "LONGER_WORD"}]
    )

    delta = len("LONGER_WORD") - len("WORD")
    assert mutated.references.start == refs_start + delta
    assert mutated.references.end == len(text) + delta
    # The shifted span still points at the same textual region.
    assert (
        mutated.document.text[mutated.references.start : mutated.references.end]
        == "References\n[1] paper."
    )


def test_mutate_leaves_upstream_span_unchanged():
    """A span entirely before the mutation gets no shift."""
    text = "Header\n\nbody with WORD.\n"
    header_span = Span(start=0, end=len("Header"))
    result = _ingest_result(
        text,
        sections=[Section(title="Header", level=1, span=header_span)],
    )

    mutated, _ = mutate_ingest_result(
        result, [{"id": "d1", "original": "WORD", "mutated": "LONGER_WORD"}]
    )

    assert mutated.sections[0].span.start == 0
    assert mutated.sections[0].span.end == len("Header")


def test_mutate_extends_containing_section_span():
    """When the mutation lands inside a section, that section's end must
    grow/shrink by delta so the span keeps enclosing its heading region."""
    text = "Introduction\n\nWORD inside intro.\n\nReferences\n[1] paper."
    intro_start = 0
    intro_end = text.index("References")
    refs_start = intro_end
    result = _ingest_result(
        text,
        sections=[
            Section(title="Introduction", level=1, span=Span(start=intro_start, end=intro_end)),
            Section(title="References", level=1, span=Span(start=refs_start, end=len(text))),
        ],
        references=Span(start=refs_start, end=len(text)),
    )

    mutated, _ = mutate_ingest_result(
        result, [{"id": "d1", "original": "WORD", "mutated": "LONGER_WORD"}]
    )

    delta = len("LONGER_WORD") - len("WORD")
    intro = mutated.sections[0]
    refs = mutated.sections[1]
    assert intro.span.start == intro_start
    assert intro.span.end == intro_end + delta
    assert refs.span.start == refs_start + delta
    assert refs.span.end == len(text) + delta


def test_mutate_shifts_page_offsets_downstream_of_mutation():
    """FlattenedDoc.page_offsets index into text and must shift like spans."""
    text = "page one WORD text\fpage two text"
    page1_start = 0
    page2_start = text.index("\f") + 1
    result = _ingest_result(text, page_offsets=[page1_start, page2_start])

    mutated, _ = mutate_ingest_result(
        result, [{"id": "d1", "original": "WORD", "mutated": "LONGER_WORD"}]
    )

    delta = len("LONGER_WORD") - len("WORD")
    assert mutated.document.page_offsets == [page1_start, page2_start + delta]


def test_mutate_partial_span_overlap_is_hard_error():
    """A mutation whose `original` straddles a span boundary is a garbage
    defect: recall scoring would be meaningless, so refuse it loudly."""
    text = "abcSPAN_END|SPAN_START_xyz"
    # A span ending inside the boundary word.
    span = Span(start=0, end=text.index("|"))
    result = _ingest_result(
        text,
        sections=[Section(title="s", level=1, span=span)],
    )

    with pytest.raises(ValueError, match="span boundary"):
        mutate_ingest_result(
            result,
            [{"id": "d1", "original": "END|SPAN_START", "mutated": "X"}],
        )


# --- End-to-end via a real PDF loader ---------------------------------------


def _real_grant_pdf() -> Path:
    """A grant-application PDF from the synthetic corpus. `human` is chosen
    deliberately: it carries no baked-in defects, so any HIT the harness
    reports came from the mutation the test planted, not from the corpus."""
    return REPO / "tests" / "fixtures" / "synthetic" / "files" / "grant_application__human.pdf"


def test_post_ingest_mutation_on_real_pdf_survives_the_loader():
    """The whole point of #71: mutating FlattenedDoc.text lets us plant a
    defect on text that has already flowed through the PDF loader, so the
    checks are exercised against real extraction characteristics (dropped
    whitespace, mis-ordered columns, footnote handling)."""
    pdf = _real_grant_pdf()
    if not pdf.exists():
        pytest.skip(f"synthetic PDF corpus not present: {pdf}")

    result = ingest(pdf)
    assert result.status == "ok", result.reason
    original_text = result.document.text
    # Pick a token that actually made it through the PDF loader; if this
    # ever fails, the loader has changed, which is itself news.
    needle = original_text.split()[10]

    mutated, manifest = mutate_ingest_result(
        result,
        [{"id": "d1", "original": needle, "mutated": needle + "_MUTATED"}],
    )
    assert mutated.document.text != original_text
    assert needle + "_MUTATED" in mutated.document.text
    assert manifest[0]["id"] == "d1"


def test_post_ingest_harness_recovers_planted_defect_through_pdf_loader(tmp_path):
    """Full harness run on a real PDF substrate. Plants an orphan citation
    marker in the body text (insertion, not substitution — the human-grant
    fixture has no in-body markers to swap, which is itself a real property
    of the corpus). Confirms the citation check surfaces it: same recall
    shape as the pre-ingest canary in test_harness.py, but the recall is
    now measured on text that has flowed through the real PDF loader."""
    pdf = _real_grant_pdf()
    if not pdf.exists():
        pytest.skip(f"synthetic PDF corpus not present: {pdf}")

    substrates_dir = tmp_path / "substrates"
    substrates_dir.mkdir()
    import shutil

    shutil.copy(pdf, substrates_dir / pdf.name)

    # Insert [99] before the ":" in the first Aim heading. [99] has no
    # matching reference entry in the corpus (numbered 1..N, coverage.json
    # caps well below 99), so citation_has_reference must flag it.
    defects_file = tmp_path / "defects.yaml"
    defects_file.write_text(
        f"""\
- id: cite-orphan-real-pdf
  substrate: {pdf.name}
  original: "Aim 1:"
  mutated: "Aim 1 [99]:"
  check_expected: citation_has_reference
  match:
    kind: unlinked_citation_number
    number: 99
  description: >
    Insert an orphan [99] marker into the first Aim heading. No reference
    entry exists for [99]; a working citation check must surface the
    orphan marker.
"""
    )

    summary = run_harness(
        fixtures_dir=None,
        defects_file=defects_file,
        sources_dir=tmp_path / "sources_empty",  # unused for this defect kind
        out_dir=tmp_path / "out",
        today="0000-00-00",
        substrates_dir=substrates_dir,
    )

    outcomes = {d["id"]: d["outcome"] for d in summary["per_defect"]}
    assert outcomes == {"cite-orphan-real-pdf": "HIT"}
    assert summary["hits"] == 1
    assert summary["misses"] == 0

    # The recall report file was written and mentions the substrate PDF.
    report_text = summary["report_path"].read_text()
    assert "Recall (deterministic tier): 1/1" in report_text
    assert pdf.name in report_text
