"""Solicitation compliance checks (#16): one YAML spec drives section
presence, narrative length, budget ceiling, and attachment-mention checks.
Deterministic tier, no LLM and no network.

Required-section and attachment names are alias-matched against whatever
headings/text the applicant actually wrote, not the RFP's exact wording — a
real applicant writes "Aims", not "Specific Aims". Matching is case-insensitive,
whole-word/phrase (same boundary regex as ``checks/tagging.py``'s
``_phrase_re``), never naive substring.

This pass only detects ATX (``#``) markdown headings, so the registered check
is scoped to ``media_type == "text/markdown"`` via ``applies_to`` — a PDF/DOCX
proposal reports "not applicable to this document" rather than a wrong
"everything is missing" result. PDF/DOCX heading detection is follow-up work.

Eligibility and priority-area fit (the issue's LLM-judgment tier) are out of
scope for this pass: no LLM client exists in the codebase yet (#37 is still
design-only) — see the #16 issue comment for the scoping call.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from slopchecker.models import Anchor, Finding, FlattenedDoc, LedgerRow, Span
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register

# --- spec model --------------------------------------------------------------


@dataclass(frozen=True)
class RequiredSection:
    name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class RequiredAttachment:
    name: str
    signals: tuple[str, ...]


@dataclass(frozen=True)
class NarrativeLimit:
    start_section: str | None
    end_section: str | None
    max_words: int | None
    max_pages: int | None


@dataclass(frozen=True)
class SolicitationSpec:
    id: str
    name: str
    required_sections: tuple[RequiredSection, ...]
    narrative: NarrativeLimit | None
    budget_ceiling_usd: float | None
    required_attachments: tuple[RequiredAttachment, ...]


def load_spec(path: str | os.PathLike[str]) -> SolicitationSpec:
    """Parse+validate a YAML spec file. A spec is a contract: a malformed or
    incomplete shape raises ValueError rather than silently dropping a field."""
    with Path(path).open("rb") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: spec must be a YAML mapping")
    for key in ("id", "name"):
        if not raw.get(key):
            raise ValueError(f"{path}: spec missing required key '{key}'")

    sections = tuple(
        RequiredSection(name=s["name"], aliases=tuple(s["aliases"]))
        for s in raw.get("required_sections", [])
    )

    narrative_raw = raw.get("narrative")
    narrative: NarrativeLimit | None = None
    if narrative_raw is not None:
        max_words = narrative_raw.get("max_words")
        max_pages = narrative_raw.get("max_pages")
        if max_words is None and max_pages is None:
            raise ValueError(f"{path}: narrative block must set max_words and/or max_pages")
        narrative = NarrativeLimit(
            start_section=narrative_raw.get("start_section"),
            end_section=narrative_raw.get("end_section"),
            max_words=max_words,
            max_pages=max_pages,
        )

    budget_ceiling = raw.get("budget", {}).get("ceiling_usd") if raw.get("budget") else None

    attachments = tuple(
        RequiredAttachment(name=a["name"], signals=tuple(a["signals"]))
        for a in raw.get("required_attachments", [])
    )

    return SolicitationSpec(
        id=raw["id"],
        name=raw["name"],
        required_sections=sections,
        narrative=narrative,
        budget_ceiling_usd=budget_ceiling,
        required_attachments=attachments,
    )


def resolve_spec(solicitation: str | None) -> SolicitationSpec | None:
    """Resolve CheckContext.solicitation into a spec, or None if unset/not
    found. Only a genuinely broken YAML file (found but malformed) raises;
    "no spec given" and "nothing there" are both just None."""
    if solicitation is None or not solicitation.strip():
        return None
    path = Path(solicitation)
    if not path.is_file() or path.suffix.lower() not in (".yaml", ".yml"):
        return None
    return load_spec(path)


# --- heading detection ---------------------------------------------------------

_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^(?:```|~~~)")


@dataclass(frozen=True)
class HeadingMatch:
    level: int
    title: str
    start: int


def find_headings(text: str) -> list[HeadingMatch]:
    headings: list[HeadingMatch] = []
    offset = 0
    in_fence = False
    for line in text.splitlines(keepends=True):
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            match = _ATX_HEADING.match(line.rstrip("\n"))
            if match:
                headings.append(
                    HeadingMatch(level=len(match.group(1)), title=match.group(2), start=offset)
                )
        offset += len(line)
    return headings


@lru_cache(maxsize=2048)
def _phrase_re(phrase: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", re.IGNORECASE)


def section_present(headings: list[HeadingMatch], section: RequiredSection) -> HeadingMatch | None:
    for heading in headings:
        if any(_phrase_re(alias).search(heading.title) for alias in section.aliases):
            return heading
    return None


def attachment_mentioned(text: str, attachment: RequiredAttachment) -> bool:
    return any(_phrase_re(signal).search(text) for signal in attachment.signals)


# --- narrative span / word count ----------------------------------------------


def _section_end(headings: list[HeadingMatch], heading: HeadingMatch, text_len: int) -> int:
    for other in headings:
        if other.start > heading.start and other.level <= heading.level:
            return other.start
    return text_len


def _section_by_name(spec: SolicitationSpec, name: str) -> RequiredSection:
    """The spec's own RequiredSection for `name`, so its full alias list is
    used to find the heading -- not the bare name, which an applicant's own
    heading wording (e.g. "Approach" for "Approach and Methods") won't match."""
    for section in spec.required_sections:
        if section.name == name:
            return section
    return RequiredSection(name=name, aliases=(name,))


def _narrative_span(
    doc: FlattenedDoc, headings: list[HeadingMatch], spec: SolicitationSpec, limit: NarrativeLimit
) -> tuple[int, int] | None:
    if limit.start_section is None or limit.end_section is None:
        return None
    start_heading = section_present(headings, _section_by_name(spec, limit.start_section))
    end_heading = section_present(headings, _section_by_name(spec, limit.end_section))
    if start_heading is None or end_heading is None:
        return None
    end = _section_end(headings, end_heading, len(doc.text))
    return start_heading.start, end


# --- budget total extraction ----------------------------------------------------

_BUDGET_TABLE_ROW = re.compile(
    r"\|\s*\*{0,2}total\*{0,2}\s*\|\s*\*{0,2}\$\s*([\d,]+(?:\.\d{2})?)\*{0,2}\s*\|",
    re.IGNORECASE,
)
_BUDGET_PHRASE = re.compile(
    r"\btotal\b[^\n$]{0,40}?\$\s*([\d,]+(?:\.\d{2})?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BudgetMatch:
    amount: float
    quote: str
    start: int
    end: int


def find_budget_total(text: str) -> BudgetMatch | None:
    matches = [*_BUDGET_TABLE_ROW.finditer(text), *_BUDGET_PHRASE.finditer(text)]
    if not matches:
        return None
    m = max(matches, key=lambda m: m.start())
    amount = float(m.group(1).replace(",", ""))
    return BudgetMatch(amount=amount, quote=m.group(0), start=m.start(), end=m.end())


# --- the registered check ------------------------------------------------------


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _missing_finding(id_prefix: str, label: str, key: str, name: str, spec_id: str) -> Finding:
    return Finding(
        id=f"{id_prefix}-{_slug(name)}",
        label=label,
        anchor=None,
        evidence={key: name, "spec_id": spec_id},
        note=f"required {label.lower()} not found: {name}",
    )


def _check_sections(doc: FlattenedDoc, headings: list[HeadingMatch], spec: SolicitationSpec):
    if not spec.required_sections:
        return None, []
    missing = [s.name for s in spec.required_sections if section_present(headings, s) is None]
    row = LedgerRow(
        check="compliance_sections",
        label="Required sections present",
        result=not missing,
        detail="all present" if not missing else f"missing: {', '.join(missing)}",
    )
    findings = [
        _missing_finding("compliance-section-missing", "Required section", "section", name, spec.id)
        for name in missing
    ]
    return row, findings


def _check_narrative_length(
    doc: FlattenedDoc, headings: list[HeadingMatch], spec: SolicitationSpec
):
    limit = spec.narrative
    if limit is None:
        return None
    span = _narrative_span(doc, headings, spec, limit)
    if span is None:
        return LedgerRow(
            check="compliance_narrative_length",
            label="Narrative length",
            status="skipped",
            reason=(
                f"could not locate '{limit.start_section}'..'{limit.end_section}' "
                "section boundaries in the document"
            ),
        )
    start, end = span
    narrative_text = doc.text[start:end]
    if limit.max_words is not None:
        count = len(narrative_text.split())
        return LedgerRow(
            check="compliance_narrative_length",
            label="Narrative length",
            result=count <= limit.max_words,
            detail=f"{count} words (limit {limit.max_words})",
        )
    if limit.max_pages is not None:
        if doc.pages is None:
            return LedgerRow(
                check="compliance_narrative_length",
                label="Narrative length",
                status="skipped",
                reason=(
                    "document has no page count (non-PDF source); configure "
                    "narrative.max_words to check text-based formats"
                ),
            )
        return LedgerRow(
            check="compliance_narrative_length",
            label="Narrative length",
            result=doc.pages <= limit.max_pages,
            detail=f"{doc.pages} pages (limit {limit.max_pages})",
        )
    return None


def _check_budget(doc: FlattenedDoc, spec: SolicitationSpec):
    ceiling = spec.budget_ceiling_usd
    if ceiling is None:
        return None, []
    match = find_budget_total(doc.text)
    if match is None:
        row = LedgerRow(
            check="compliance_budget",
            label="Budget within ceiling",
            status="skipped",
            reason="could not find a totalled dollar amount in the document text",
        )
        return row, []
    within = match.amount <= ceiling
    row = LedgerRow(
        check="compliance_budget",
        label="Budget within ceiling",
        result=within,
        detail=f"${match.amount:,.0f} vs ${ceiling:,.0f} ceiling",
    )
    findings = []
    if not within:
        findings.append(
            Finding(
                id="compliance-budget-over-ceiling",
                label="Budget",
                anchor=Anchor(quote=match.quote, span=Span(start=match.start, end=match.end)),
                evidence={
                    "total_usd": match.amount,
                    "ceiling_usd": ceiling,
                    "spec_id": spec.id,
                },
                note=f"budget total ${match.amount:,.0f} exceeds the ${ceiling:,.0f} ceiling",
            )
        )
    return row, findings


def _check_attachments(doc: FlattenedDoc, spec: SolicitationSpec):
    if not spec.required_attachments:
        return None, []
    missing = [a.name for a in spec.required_attachments if not attachment_mentioned(doc.text, a)]
    row = LedgerRow(
        check="compliance_attachments",
        label="Required attachments mentioned",
        result=not missing,
        detail="all mentioned" if not missing else f"missing: {', '.join(missing)}",
    )
    findings = [
        _missing_finding(
            "compliance-attachment-missing", "Required attachment", "attachment", name, spec.id
        )
        for name in missing
    ]
    return row, findings


@register(
    id="solicitation_compliance",
    name="Solicitation compliance",
    tier="deterministic",
    timeout_s=10.0,
    applies_to=lambda doc: doc.media_type == "text/markdown",
)
def solicitation_compliance(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    spec = resolve_spec(ctx.solicitation)
    if spec is None:
        given = ctx.solicitation
        reason = (
            "no solicitation spec given (--solicitation <path-to-yaml>)"
            if not given or not given.strip()
            else f"solicitation spec not found: {given!r}"
        )
        return CheckOutput(
            ledger=[
                LedgerRow(
                    check="compliance",
                    label="Solicitation compliance",
                    status="skipped",
                    reason=reason,
                )
            ]
        )
    return _evaluate(doc, spec)


def _evaluate(doc: FlattenedDoc, spec: SolicitationSpec) -> CheckOutput:
    headings = find_headings(doc.text)
    ledger: list[LedgerRow] = []
    findings: list[Finding] = []

    sections_row, sections_findings = _check_sections(doc, headings, spec)
    if sections_row is not None:
        ledger.append(sections_row)
        findings.extend(sections_findings)

    length_row = _check_narrative_length(doc, headings, spec)
    if length_row is not None:
        ledger.append(length_row)

    budget_row, budget_findings = _check_budget(doc, spec)
    if budget_row is not None:
        ledger.append(budget_row)
        findings.extend(budget_findings)

    attachments_row, attachments_findings = _check_attachments(doc, spec)
    if attachments_row is not None:
        ledger.append(attachments_row)
        findings.extend(attachments_findings)

    return CheckOutput(ledger=ledger, findings=findings)
