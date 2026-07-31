"""Tests for the BackgroundReport shape (#18 structured lane).

Contract goals:

- Every ``BackgroundFinding`` carries a ``source_url`` (no unsourced findings).
- ``confidence`` is a closed 3-value vocabulary; ``unverified`` never reaches
  the shipping report — the ``BackgroundReport`` validator rejects it.
- ``EntityNotFound`` is a first-class outcome, distinct from a coverage
  ``BackgroundGap``, both distinct from silent absence.
- Every ``finding``/``not_found``/``gap`` references a real ``Entity`` in the
  same report (referential integrity — enforced at construction time).
- ``EvidenceReport.background`` is optional and round-trips losslessly, so
  the shape can ship independently of the runner integration.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from slopchecker.models import (
    Anchor,
    BackgroundConfidence,
    BackgroundFinding,
    BackgroundGap,
    BackgroundReport,
    Entity,
    EntityKind,
    EntityNotFound,
    EvidenceReport,
    FlattenedDoc,
    Span,
)

# --- Fixtures ---------------------------------------------------------------


def _org_entity() -> Entity:
    return Entity(
        id="e-org-1",
        kind=EntityKind.org,
        name="Institute for X",
        anchor=Anchor(page=1, quote="Institute for X", span=Span(start=0, end=15)),
    )


def _person_entity() -> Entity:
    return Entity(
        id="e-person-1",
        kind=EntityKind.person,
        name="Jane Smith",
        affiliation="Institute for X",
    )


def _propublica_finding(entity_id: str = "e-org-1") -> BackgroundFinding:
    return BackgroundFinding(
        id="bf-1",
        entity_id=entity_id,
        registry="propublica",
        source_url="https://projects.propublica.org/nonprofits/organizations/123456789",
        confidence=BackgroundConfidence.verified,
        label="501(c)(3) since 2011",
        data={"ein": "12-3456789", "ntee_code": "B90"},
    )


# --- Structural: required fields --------------------------------------------


def test_finding_requires_source_url():
    """A finding with no source URL cannot exist — the model rejects it."""
    with pytest.raises(ValidationError):
        BackgroundFinding(
            id="bf-x",
            entity_id="e-org-1",
            registry="propublica",
            confidence=BackgroundConfidence.verified,
        )


def test_entity_requires_name_and_kind():
    """Entities need at minimum an id, kind, and name."""
    with pytest.raises(ValidationError):
        Entity(id="x", kind=EntityKind.org)  # missing name
    with pytest.raises(ValidationError):
        Entity(id="x", name="Whatever")  # missing kind


def test_gap_requires_reason():
    """A coverage gap without a reason is a silent skip — rejected."""
    with pytest.raises(ValidationError):
        BackgroundGap(registry="propublica")


def test_not_found_requires_query_url():
    """EntityNotFound must record the URL we hit — evidence for the negative."""
    with pytest.raises(ValidationError):
        EntityNotFound(entity_id="e-org-1", registry="propublica")


# --- Confidence is a closed 3-value vocabulary ------------------------------


def test_confidence_is_closed_enum():
    finding = _propublica_finding()
    assert finding.confidence is BackgroundConfidence.verified
    assert json.loads(finding.model_dump_json())["confidence"] == "verified"
    with pytest.raises(ValidationError):
        BackgroundFinding(
            id="bf-x",
            entity_id="e-org-1",
            registry="propublica",
            source_url="https://example.org/x",
            confidence="strongly-verified",  # not in the enum
        )


def test_confidence_accepts_all_three():
    for level in ("verified", "probable", "unverified"):
        finding = BackgroundFinding(
            id=f"bf-{level}",
            entity_id="e-org-1",
            registry="r",
            source_url="https://example.org/x",
            confidence=level,
        )
        assert finding.confidence.value == level


# --- BackgroundReport: unverified filtered out at report assembly ----------


def test_unverified_findings_rejected_by_report():
    """The point of ``unverified`` is that it's a produce-then-filter state;
    once you assemble a BackgroundReport, none may remain."""
    entity = _org_entity()
    unverified = BackgroundFinding(
        id="bf-u",
        entity_id=entity.id,
        registry="openalex",
        source_url="https://api.openalex.org/authors?filter=display_name.search%3AJane%20Smith",
        confidence=BackgroundConfidence.unverified,
    )
    with pytest.raises(ValidationError):
        BackgroundReport(entities=[entity], findings=[unverified])


def test_verified_and_probable_findings_accepted():
    entity = _org_entity()
    report = BackgroundReport(
        entities=[entity],
        findings=[
            BackgroundFinding(
                id="bf-v",
                entity_id=entity.id,
                registry="propublica",
                source_url="https://projects.propublica.org/nonprofits/organizations/1",
                confidence=BackgroundConfidence.verified,
            ),
            BackgroundFinding(
                id="bf-p",
                entity_id=entity.id,
                registry="openalex",
                source_url="https://openalex.org/W1",
                confidence=BackgroundConfidence.probable,
            ),
        ],
    )
    assert len(report.findings) == 2


# --- BackgroundReport: referential integrity --------------------------------


def test_finding_entity_id_must_resolve():
    """A finding pointing at a nonexistent entity is a broken pointer — rejected."""
    with pytest.raises(ValidationError):
        BackgroundReport(
            entities=[_org_entity()],
            findings=[_propublica_finding(entity_id="e-ghost")],
        )


def test_not_found_entity_id_must_resolve():
    with pytest.raises(ValidationError):
        BackgroundReport(
            entities=[_org_entity()],
            not_found=[
                EntityNotFound(
                    entity_id="e-ghost",
                    registry="propublica",
                    query_url="https://projects.propublica.org/nonprofits/api/v2/search.json?q=Ghost",
                )
            ],
        )


def test_gap_entity_id_must_resolve_when_set():
    with pytest.raises(ValidationError):
        BackgroundReport(
            entities=[_org_entity()],
            gaps=[
                BackgroundGap(
                    entity_id="e-ghost",
                    registry="propublica",
                    reason="HTTP 503",
                )
            ],
        )


def test_gap_with_none_entity_id_is_whole_registry_gap():
    """A registry-wide failure (no key, network down) has entity_id=None."""
    report = BackgroundReport(
        entities=[_org_entity()],
        gaps=[BackgroundGap(registry="orcid", reason="ORCID API unreachable")],
    )
    assert report.gaps[0].entity_id is None


# --- EntityNotFound vs BackgroundGap vs absence -----------------------------


def test_not_found_distinct_from_gap():
    """A 'searched and empty' result is not the same as 'could not search'.

    The whole point of the split: a reviewer must be able to tell "this org
    isn't in ProPublica" from "ProPublica was down when we asked."
    """
    entity = _org_entity()
    report = BackgroundReport(
        entities=[entity],
        not_found=[
            EntityNotFound(
                entity_id=entity.id,
                registry="propublica",
                query_url="https://projects.propublica.org/nonprofits/api/v2/search.json?q=X",
            )
        ],
        gaps=[
            BackgroundGap(
                entity_id=entity.id,
                registry="openalex",
                reason="HTTP 503 from OpenAlex",
            )
        ],
    )
    assert len(report.not_found) == 1
    assert len(report.gaps) == 1
    # Same entity in both — different-registry outcomes about the same subject.
    assert report.not_found[0].entity_id == report.gaps[0].entity_id == entity.id


# --- Cross-client dedup: secondary_sources ---------------------------------


def test_finding_carries_secondary_sources_for_dedup():
    """OpenAlex + ORCID may both hit the same person — coalesce, don't duplicate."""
    entity = _person_entity()
    finding = BackgroundFinding(
        id="bf-dup",
        entity_id=entity.id,
        registry="openalex",
        source_url="https://openalex.org/A123",
        confidence=BackgroundConfidence.verified,
        secondary_sources=["https://orcid.org/0000-0001-2345-6789"],
    )
    BackgroundReport(entities=[entity], findings=[finding])
    assert finding.secondary_sources == ["https://orcid.org/0000-0001-2345-6789"]


# --- EvidenceReport integration --------------------------------------------


def test_evidence_report_background_optional_and_absent_by_default():
    report = EvidenceReport(document=FlattenedDoc(file="p.pdf", text="t"))
    assert report.background is None
    assert "background" not in report.to_report_dict()


def test_evidence_report_background_round_trips():
    entity = _org_entity()
    background = BackgroundReport(
        entities=[entity],
        findings=[_propublica_finding()],
        not_found=[
            EntityNotFound(
                entity_id=entity.id,
                registry="openalex",
                query_url="https://api.openalex.org/works?filter=x",
            )
        ],
        gaps=[BackgroundGap(registry="orcid", reason="ORCID API unreachable")],
    )
    report = EvidenceReport(
        document=FlattenedDoc(file="p.pdf", text="Institute for X submitted this."),
        background=background,
    )
    again = EvidenceReport.model_validate_json(report.model_dump_json())
    assert again == report
    assert again.background is not None
    assert again.background.findings[0].source_url.startswith("https://projects.propublica.org")


def test_background_report_extra_fields_rejected():
    """Unknown fields in the background block fail loudly, matching the rest of the model."""
    entity = _org_entity()
    with pytest.raises(ValidationError):
        BackgroundReport.model_validate(
            {
                "entities": [entity.model_dump()],
                "findings": [],
                "brief_style": "narrative",  # not a real field
            }
        )


def test_finding_extra_fields_rejected():
    with pytest.raises(ValidationError):
        BackgroundFinding.model_validate(
            {
                "id": "bf-x",
                "entity_id": "e-org-1",
                "registry": "propublica",
                "source_url": "https://example.org/x",
                "confidence": "verified",
                "is_probably_real": True,  # verdict-shaped typo
            }
        )


# --- brief_markdown is the open-web lane's slot ----------------------------


def test_brief_markdown_optional_and_free_form():
    """The open-web lane writes here; the structured lane leaves it None."""
    report = BackgroundReport()
    assert report.brief_markdown is None
    with_brief = BackgroundReport(brief_markdown="## Background\n\nSome sourced prose.")
    assert with_brief.brief_markdown is not None
    assert "Background" in with_brief.brief_markdown
