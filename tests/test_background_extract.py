"""Tests for the rules-first entity extractor (#18, Phase 1).

The extractor takes a ``FlattenedDoc`` and returns ``list[Entity]`` — people
and orgs named in the proposal that a downstream registry lookup could try
to verify. Rules-first because it's auditable and covers the common
proposal shape (a ``PI/Institution`` header naming one person and one
institution). An LLM-based fallback is a follow-up ticket, not this PR.

Behavior under test:

- Explicit ``## PI/Institution`` (or ``## PI`` / ``## Principal Investigator``
  / ``## Team`` / ``## Personnel``) section drives extraction — the
  extractor doesn't guess at names in body prose.
- One person + one institution per PI line, with the institution attached
  to the person as ``affiliation`` (the corroboration hook the
  registry-lookup layer needs for common-name disambiguation).
- Every ``Entity`` carries an ``Anchor`` pointing at where it appeared in
  ``FlattenedDoc.text`` — the quote is a verbatim substring, matching the
  same discipline as every other anchor in the model.
- No matching section => empty list. A blog post or think-tank report is
  not a proposal and produces no entities; the runner registers this as a
  skip, not a silent success.
- ``ids`` are unique per document (stable, so runs are diffable).
"""

from __future__ import annotations

from pathlib import Path

from slopchecker.background.extract import extract_entities
from slopchecker.models import EntityKind, FlattenedDoc

REPO_ROOT = Path(__file__).parent.parent
HARNESS_FIXTURES = REPO_ROOT / "harness" / "fixtures"


# --- Small inline fixtures --------------------------------------------------


PROPOSAL_ONE_PI = """\
## Title
A Study of Widgets

## PI/Institution
Dr. Alice Kimura, Department of Materials Science, Riverbend Institute of Technology

## Abstract
Widgets are important.
"""

PROPOSAL_MULTIPLE_PERSONNEL = """\
## Title
Multi-Site Widget Study

## PI/Institution
Dr. Alice Kimura, Department of Materials Science, Riverbend Institute of Technology

## Co-Investigators
- Dr. Bertram Nkomo, School of Engineering, Oakhaven University
- Dr. Chen Wei, Center for Advanced Studies, Fjordmark College

## Abstract
Multiple sites participating.
"""

PROPOSAL_NO_PI_SECTION = """\
## Title
Widgets Rule

## Abstract
Absolutely nothing about who wrote this.

## Approach
We approach widgets from many angles.
"""

BLOG_POST = """\
# Why widgets matter

By an anonymous friend of widgets.

## The core insight
Widgets are the future.
"""


def _doc(text: str, file: str = "proposal.md") -> FlattenedDoc:
    return FlattenedDoc(file=file, text=text)


# --- Section-driven extraction ---------------------------------------------


def test_pi_institution_line_yields_person_plus_org_pair():
    """A ``## PI/Institution`` header with one comma-separated line yields
    one Person (affiliated with the org) and one Org."""
    entities = extract_entities(_doc(PROPOSAL_ONE_PI))

    persons = [e for e in entities if e.kind is EntityKind.person]
    orgs = [e for e in entities if e.kind is EntityKind.org]

    assert len(persons) == 1, f"expected 1 person, got {[e.name for e in persons]}"
    assert persons[0].name == "Dr. Alice Kimura"
    assert persons[0].affiliation == "Riverbend Institute of Technology"

    assert len(orgs) == 1
    assert orgs[0].name == "Riverbend Institute of Technology"


def test_multiple_personnel_all_extracted():
    """A dedicated team/co-investigator list yields every name."""
    entities = extract_entities(_doc(PROPOSAL_MULTIPLE_PERSONNEL))
    names = {e.name for e in entities if e.kind is EntityKind.person}
    assert names == {
        "Dr. Alice Kimura",
        "Dr. Bertram Nkomo",
        "Dr. Chen Wei",
    }


def test_person_carries_affiliation_from_same_line():
    """Common-name disambiguation depends on affiliation being attached —
    if we lose it, the ORCID/OpenAlex lookup can't corroborate."""
    entities = extract_entities(_doc(PROPOSAL_MULTIPLE_PERSONNEL))
    by_name = {e.name: e for e in entities if e.kind is EntityKind.person}
    assert by_name["Dr. Bertram Nkomo"].affiliation == "Oakhaven University"
    assert by_name["Dr. Chen Wei"].affiliation == "Fjordmark College"


# --- No PI section => empty result ----------------------------------------


def test_proposal_with_no_personnel_section_returns_empty():
    """No named section => no entities. We don't guess at names in body prose."""
    entities = extract_entities(_doc(PROPOSAL_NO_PI_SECTION))
    assert entities == []


def test_blog_post_returns_empty():
    """A non-proposal shape produces no entities; the runner turns this
    into ``skipped: no entities extracted`` rather than silent success."""
    entities = extract_entities(_doc(BLOG_POST, file="blog.md"))
    assert entities == []


# --- Anchor discipline: every entity points into the source text ----------


def test_every_person_entity_has_anchor_grounded_in_text():
    """Same discipline as every other Anchor in the model — the quote must be
    a verbatim substring of ``FlattenedDoc.text``."""
    doc = _doc(PROPOSAL_ONE_PI)
    entities = extract_entities(doc)
    for entity in entities:
        assert entity.anchor is not None, f"{entity.name}: missing anchor"
        assert entity.anchor.quote in doc.text, (
            f"{entity.name}: anchor quote {entity.anchor.quote!r} not in doc text"
        )


def test_anchor_span_matches_quote():
    """When span is set, doc.text[span.start:span.end] must equal quote."""
    doc = _doc(PROPOSAL_ONE_PI)
    entities = extract_entities(doc)
    for entity in entities:
        assert entity.anchor is not None
        if entity.anchor.span is not None:
            span = entity.anchor.span
            assert doc.text[span.start : span.end] == entity.anchor.quote


# --- Stable ids ------------------------------------------------------------


def test_entity_ids_unique_per_document():
    ids = [e.id for e in extract_entities(_doc(PROPOSAL_MULTIPLE_PERSONNEL))]
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"


def test_extraction_is_deterministic():
    doc = _doc(PROPOSAL_MULTIPLE_PERSONNEL)
    first = extract_entities(doc)
    second = extract_entities(doc)
    assert first == second


# --- End-to-end smoke on a real harness fixture ---------------------------


def test_real_climate_proposal_extracts_expected_pi_and_org():
    """proposal_climate.md is the demo-shaped fixture. Rules must land the
    PI and their institution — this is the load-bearing case for the
    structured lane."""
    fixture = HARNESS_FIXTURES / "proposal_climate.md"
    doc = _doc(fixture.read_text("utf-8"), file=str(fixture.name))
    entities = extract_entities(doc)

    persons = [e for e in entities if e.kind is EntityKind.person]
    orgs = [e for e in entities if e.kind is EntityKind.org]

    assert any("Halsey" in p.name for p in persons), (
        f"expected Dr. Halsey in extracted persons, got {[p.name for p in persons]}"
    )
    assert any("Blackwood State" in o.name for o in orgs), (
        f"expected Blackwood State University in extracted orgs, got {[o.name for o in orgs]}"
    )
    halsey = next(p for p in persons if "Halsey" in p.name)
    assert halsey.affiliation is not None
    assert "Blackwood State" in halsey.affiliation
