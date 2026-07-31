"""Tagging check (#15): topics, document type, submitter type. Offline, no LLM.

Covers the acceptance criteria: a replaceable config file drives the tags,
document-type detection is the seam other checks gate on, submitter-type
inference reports low confidence rather than guessing, and the tags land in the
report JSON (via findings) for the batch summary to sort on.
"""

from __future__ import annotations

import textwrap

import pytest

from slopchecker.checks.tagging import (
    DEFAULT_TAXONOMY,
    detect_doc_type,
    infer_submitter_type,
    load_taxonomy,
    tag_topics,
    tagging,
)
from slopchecker.models import FlattenedDoc
from slopchecker.pipeline.registry import CheckContext

GRANT = FlattenedDoc(
    file="proposal.pdf",
    text=(
        "Project Narrative\n\nThe Regents of the University of California propose a study of "
        "machine learning applied to biosecurity and pathogen surveillance. Specific Aims: ... "
        "Budget Justification: personnel and compute. Principal Investigator: Dr. Vega. "
        "EIN 94-1234567."
    ),
    pages=1,
    page_offsets=[0],
)

BLOG = FlattenedDoc(file="post.md", text="A quick take on the grid and renewable energy policy.")


def _ctx() -> CheckContext:
    return CheckContext()


# --- document type ----------------------------------------------------------


def test_doc_type_grant_application_from_structural_markers():
    res = detect_doc_type(GRANT)
    assert res.kind == "grant_application"
    assert res.confidence >= 0.75  # several distinct markers
    assert {m.phrase for m in res.matches} >= {"project narrative", "specific aims"}


def test_doc_type_blog_fallback_only_when_short():
    assert detect_doc_type(BLOG).kind == "blog_post"
    # Same absence of markers but long → unknown, not a blog post.
    long_unmarked = FlattenedDoc(file="x.txt", text="word " * 2000)
    assert detect_doc_type(long_unmarked).kind == "unknown"


def test_doc_type_is_the_applies_to_seam():
    # The exact predicate shape other checks use to route themselves.
    def applies(doc):
        return detect_doc_type(doc).kind in {"grant_application", "think_tank_report"}

    assert applies(GRANT) is True
    assert applies(BLOG) is False


# --- submitter type ---------------------------------------------------------


def test_submitter_type_university_with_ein_bump_is_capped():
    res = infer_submitter_type(GRANT)
    assert res.kind == "university"
    assert 0.0 < res.confidence <= 0.9
    assert any(m.phrase == "ein" for m in res.matches)  # EIN attached as evidence


def test_submitter_type_unknown_reports_low_confidence_not_a_guess():
    res = infer_submitter_type(BLOG)
    assert res.kind == "unknown"
    assert res.confidence == 0.0


# --- topics -----------------------------------------------------------------


def test_topics_are_multi_label_and_sorted():
    topics = [h.topic for h in tag_topics(GRANT)]
    assert "ai" in topics and "biosecurity" in topics
    assert tag_topics(FlattenedDoc(file="e.txt", text="nothing relevant here")) == []


# --- configurable taxonomy (AC: user can replace the vocabulary) ------------


def test_custom_taxonomy_file_overrides_default(tmp_path, monkeypatch):
    custom = tmp_path / "tax.toml"
    custom.write_text(
        textwrap.dedent(
            """
            [topics]
            housing = ["zoning", "affordable housing"]
            [doc_types]
            blog_post = []
            [submitter_types]
            individual = []
            """
        )
    )
    monkeypatch.setenv("SLOPCHECKER_TAXONOMY", str(custom))
    tax = load_taxonomy()
    assert tax["topics"] == {"housing": ["zoning", "affordable housing"]}

    doc = FlattenedDoc(file="h.md", text="A note on zoning and affordable housing.")
    assert [h.topic for h in tag_topics(doc)] == ["housing"]
    # A default topic is gone now that the vocabulary was replaced.
    assert tag_topics(GRANT) == [] or all(h.topic == "housing" for h in tag_topics(GRANT))


def test_missing_taxonomy_file_raises_not_silently_ignored(monkeypatch):
    monkeypatch.setenv("SLOPCHECKER_TAXONOMY", "/no/such/taxonomy.toml")
    with pytest.raises(FileNotFoundError):
        load_taxonomy()


def test_string_value_instead_of_list_fails_loudly(tmp_path, monkeypatch):
    # A bare string would otherwise iterate into single characters and match
    # nearly everything — must raise, not silently corrupt the vocabulary.
    bad = tmp_path / "bad.toml"
    bad.write_text('[topics]\nhousing = "zoning"\n')
    monkeypatch.setenv("SLOPCHECKER_TAXONOMY", str(bad))
    with pytest.raises(ValueError, match=r"\[topics\].housing must be a list"):
        load_taxonomy()


@pytest.mark.parametrize(
    "text, embedded_in",
    [
        ("gridlock in congress delayed the vote", "gridlock"),  # not energy ('grid')
        ("the computer science department", "computer"),  # not ai ('compute')
        ("the energetic crowd cheered", "energetic"),  # not energy ('energy')
    ],
)
def test_substring_false_positives_are_not_tagged(text, embedded_in):
    from slopchecker.models import FlattenedDoc

    assert tag_topics(FlattenedDoc(file="x.txt", text=text)) == [], (
        f"token matched inside '{embedded_in}' — needs whole-word boundaries"
    )


def test_whole_words_and_punctuated_phrases_still_match():
    from slopchecker.models import FlattenedDoc

    # Standalone tokens match...
    assert [h.topic for h in tag_topics(FlattenedDoc(file="a.txt", text="the power grid"))] == [
        "energy"
    ]
    # ...and punctuated submitter phrases (parens, dots) survive boundary matching.
    ngo = FlattenedDoc(file="b.txt", text="Acme Research, a 501(c)(3) nonprofit.")
    assert infer_submitter_type(ngo).kind == "nonprofit"


def test_default_matches_shipped_example_shape():
    assert set(DEFAULT_TAXONOMY) == {"topics", "doc_types", "submitter_types"}


# --- the registered check: ledger rollups + tags-as-findings ----------------


def test_check_emits_rollups_and_quote_anchored_findings():
    out = tagging(GRANT, _ctx())
    rows = {row.check: row for row in out.ledger}

    assert rows["doc_type_confidence"].result >= 0.75
    assert "grant_application" in rows["doc_type_confidence"].detail
    assert isinstance(rows["topic_tags"].result, int) and rows["topic_tags"].result >= 2
    # Submitter type deliberately absent from the report surface (2026-07-31):
    # a row that is almost always "unknown" informs no decision. The pure
    # function and taxonomy remain, tested above.
    assert "submitter_type_confidence" not in rows
    assert not any(f.id == "tag-submitter-type" for f in out.findings)

    tags = {f.id: f for f in out.findings}
    assert tags["tag-doc-type"].evidence["kind"] == "grant_application"
    # Every finding with an anchor is quote-anchored to verbatim source text.
    for f in out.findings:
        if f.anchor is not None:
            assert f.anchor.quote and f.anchor.quote in GRANT.text


def test_check_survives_empty_document():
    out = tagging(FlattenedDoc(file="blank.pdf", text=""), _ctx())
    rows = {row.check: row for row in out.ledger}
    assert rows["doc_type_confidence"].result == 0.0
    assert rows["topic_tags"].result == 0
