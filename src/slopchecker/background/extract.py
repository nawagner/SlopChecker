"""Rules-first entity extraction from a ``FlattenedDoc`` (#18, Phase 1).

Scope: cover the common proposal shape — a section headed
``PI`` / ``PI/Institution`` / ``Principal Investigator`` / ``Team`` /
``Personnel`` / ``Investigators`` / ``Co-Investigators`` / ``Submitted by`` /
``Applicant`` — and pull ``Dr. Name, Department, Institution``-shaped lines
into paired ``Entity`` records (one person with an affiliation, one org).
Nothing outside a matching section is inspected: guessing at names in body
prose is exactly the failure mode that surfaces individual-level claims
without evidence, which #18 explicitly warns against.

Output invariants (tested):

- Every ``Entity`` carries an ``Anchor`` whose ``quote`` is a verbatim
  substring of ``FlattenedDoc.text`` (same discipline as every other anchor
  in the model).
- Person entities carry the ``affiliation`` string when it's on the same
  comma-separated line — this is the corroboration hook the registry
  layer uses to disambiguate common names.
- Ids are unique per document and deterministic across runs.

LLM-based extraction (for proposals that don't follow the header
convention) is a follow-up ticket, not this module.
"""

from __future__ import annotations

import re

from slopchecker.models import Anchor, Entity, EntityKind, FlattenedDoc, Span

# Markdown headings that mark a section we're willing to extract from.
_PI_SECTION_TITLES = {
    "pi",
    "pi/institution",
    "principal investigator",
    "principal investigators",
    "team",
    "personnel",
    "investigators",
    "investigator",
    "co-investigators",
    "co-investigator",
    "coinvestigators",
    "submitted by",
    "applicant",
    "applicants",
}

# ``## Heading``, ``### Heading`` — Markdown ATX headings; content is
# whatever follows until the next heading (any level) or EOF.
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)

# A leading bullet marker on a personnel-list line — stripped before parsing.
_BULLET_RE = re.compile(r"^[\s]*[-*+•][\s]+")

# Person names start with a title we recognize. Deliberately narrow — a
# free-text guesser would over-fire on prose lines like "Findings from a
# recent NIH R01..." that live in proposals but aren't names.
_PERSON_TITLE_RE = re.compile(
    r"^(Dr\.?|Prof\.?|Professor|Mr\.?|Mrs\.?|Ms\.?|Mx\.?)\s+[A-Z]",
)

# A word that says "the following thing is a department, not a person or a
# top-level org." Used to skip department middle-of-line parts.
_DEPARTMENT_MARKERS = re.compile(
    r"^("
    r"Department|School|College|Faculty|"
    r"Institute of|Center for|Division of|"
    r"Lab(oratory)? for|Program in|Office of"
    r")\b",
    re.IGNORECASE,
)


def extract_entities(doc: FlattenedDoc) -> list[Entity]:
    """Extract people and orgs from proposal sections that name them.

    Returns a list — order is by first appearance in the document, ids
    are stable across runs on the same input.
    """
    text = doc.text
    seen_names: set[tuple[EntityKind, str]] = set()
    entities: list[Entity] = []

    for section_body_start, section_body_end in _pi_section_ranges(text):
        section_text = text[section_body_start:section_body_end]
        for line_start_offset, line in _entity_lines(section_text):
            line_start = section_body_start + line_start_offset
            person_name, person_span, org_name, org_span = _parse_person_org_line(line, line_start)
            if person_name is None:
                continue

            person_key = (EntityKind.person, person_name)
            if person_key not in seen_names:
                seen_names.add(person_key)
                entities.append(
                    Entity(
                        id=_entity_id(EntityKind.person, len(entities)),
                        kind=EntityKind.person,
                        name=person_name,
                        affiliation=org_name,
                        anchor=_anchor_from(text, person_span),
                    )
                )

            if org_name is not None:
                org_key = (EntityKind.org, org_name)
                if org_key not in seen_names:
                    seen_names.add(org_key)
                    entities.append(
                        Entity(
                            id=_entity_id(EntityKind.org, len(entities)),
                            kind=EntityKind.org,
                            name=org_name,
                            anchor=_anchor_from(text, org_span),
                        )
                    )

    return entities


# --- Section detection -----------------------------------------------------


def _pi_section_ranges(text: str) -> list[tuple[int, int]]:
    """(body_start, body_end) offsets for every section whose heading is in
    ``_PI_SECTION_TITLES``. Body is everything after the heading line up to
    (but not including) the next heading or EOF."""
    ranges: list[tuple[int, int]] = []
    headings = list(_HEADING_RE.finditer(text))
    for i, heading in enumerate(headings):
        title = heading.group(2).strip().lower().rstrip(":")
        if title not in _PI_SECTION_TITLES:
            continue
        body_start = heading.end() + 1  # skip past the heading's trailing newline
        body_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        ranges.append((body_start, body_end))
    return ranges


def _entity_lines(section_text: str) -> list[tuple[int, str]]:
    """Return (offset_in_section, cleaned_line) for each non-empty content line.

    ``offset_in_section`` points at the first character of the cleaned line
    in ``section_text`` — bullet markers and leading whitespace are stripped
    so anchors land on the name itself.
    """
    result: list[tuple[int, str]] = []
    offset = 0
    for raw_line in section_text.split("\n"):
        line_len = len(raw_line)
        if raw_line.strip():
            without_bullet = _BULLET_RE.sub("", raw_line)
            cleaned = without_bullet.strip()
            if cleaned:
                # Locate where ``cleaned`` starts inside ``raw_line`` — this
                # skips any leading whitespace and the bullet marker together.
                cleaned_start_in_line = raw_line.index(cleaned)
                result.append((offset + cleaned_start_in_line, cleaned))
        offset += line_len + 1  # +1 for the \n we split on
    return result


# --- Line parsing ----------------------------------------------------------


def _parse_person_org_line(
    line: str, line_start_in_text: int
) -> tuple[str | None, Span | None, str | None, Span | None]:
    """Try to split a comma-separated line into (person_name, org_name) with
    exact spans back in the source text. Returns Nones when the line doesn't
    look like a person entry."""
    parts_with_offsets = _split_commas_with_offsets(line, line_start_in_text)
    if not parts_with_offsets:
        return None, None, None, None

    person_text, person_start, person_end = parts_with_offsets[0]
    if not _PERSON_TITLE_RE.match(person_text):
        return None, None, None, None

    person_span = Span(start=person_start, end=person_end)

    # Institution is the last non-department comma-separated segment when
    # there are ≥ 2 parts. If every trailing segment is a department, no
    # institution is attached (the person is emitted alone).
    org_text: str | None = None
    org_span: Span | None = None
    for text_part, part_start, part_end in reversed(parts_with_offsets[1:]):
        if _DEPARTMENT_MARKERS.match(text_part):
            continue
        org_text = text_part
        org_span = Span(start=part_start, end=part_end)
        break

    return person_text, person_span, org_text, org_span


def _split_commas_with_offsets(line: str, line_start_in_text: int) -> list[tuple[str, int, int]]:
    """Split on commas, keeping each part's (start, end) offsets in the
    original source text. Preserves whitespace-stripped part text and the
    exact spans so downstream anchors don't drift."""
    parts: list[tuple[str, int, int]] = []
    cursor = 0
    for raw in line.split(","):
        raw_start = cursor
        raw_end = cursor + len(raw)
        # Trim leading/trailing whitespace within this comma-segment.
        stripped = raw.strip()
        if stripped:
            lstrip_amount = len(raw) - len(raw.lstrip())
            rstrip_amount = len(raw) - len(raw.rstrip())
            parts.append(
                (
                    stripped,
                    line_start_in_text + raw_start + lstrip_amount,
                    line_start_in_text + raw_end - rstrip_amount,
                )
            )
        cursor = raw_end + 1  # +1 for the comma we split on
    return parts


# --- Small helpers ---------------------------------------------------------


def _anchor_from(text: str, span: Span | None) -> Anchor | None:
    if span is None:
        return None
    return Anchor(quote=text[span.start : span.end], span=span)


def _entity_id(kind: EntityKind, ordinal: int) -> str:
    prefix = "p" if kind is EntityKind.person else "o"
    return f"e-{prefix}-{ordinal + 1}"
