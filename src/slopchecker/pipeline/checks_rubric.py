"""Rubric-dependent checks (#90): the submission against the funder's own rules.

First of the family: budget ceiling. Deterministic tier — conservative
pattern-matching over the rubric text and the proposal's budget table, and
every way the extraction can fall short degrades to a skipped gap row with
the reason, never a guess. No rubric on the context is itself a gap
("not checked against a solicitation"), which keeps the coverage story
honest when the caller didn't supply one.
"""

from __future__ import annotations

import re

from slopchecker.models import Anchor, CheckResult, Finding, FlattenedDoc, LedgerRow, Span
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register

_AMOUNT = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")

# Phrases that mark an amount as the award ceiling. Two tiers: "strong"
# wordings are unambiguous caps; "weak" ones ("up to") also appear in
# non-cap contexts, so they only count when no strong line exists.
_STRONG_CAP = re.compile(
    r"(?:may|must|shall|will)?\s*not\s+exceed|no\s+more\s+than|maximum\s+award"
    r"|award\s+ceiling|ceiling|not\s+to\s+exceed|requesting\s+more\s+than",
    re.IGNORECASE,
)
_WEAK_CAP = re.compile(r"up\s+to|maximum", re.IGNORECASE)

_TOTAL_LINE = re.compile(r"total", re.IGNORECASE)


def _to_number(amount: str) -> float:
    return float(amount.replace(",", ""))


def _find_ceiling(text: str) -> tuple[float, str] | None:
    """The award ceiling stated in rubric text, with the line that states it.

    Returns None when no cap wording is found or when cap lines name more
    than one distinct amount (ambiguous — a gap, not a coin flip).
    """
    strong: list[tuple[float, str]] = []
    weak: list[tuple[float, str]] = []
    for line in text.splitlines():
        amounts = _AMOUNT.findall(line)
        if not amounts:
            continue
        if _STRONG_CAP.search(line):
            strong.extend((_to_number(a), line.strip()) for a in amounts)
        elif _WEAK_CAP.search(line):
            weak.extend((_to_number(a), line.strip()) for a in amounts)
    for candidates in (strong, weak):
        values = {v for v, _ in candidates}
        if len(values) == 1:
            return candidates[0]
    return None


def _find_budget_total(doc: FlattenedDoc) -> tuple[float, Span] | None:
    """The proposal's stated budget total, with exact offsets into doc.text.

    Scans lines containing "total" for dollar amounts and takes the largest
    (a grand total is never smaller than its line items). The span covers
    the matched amount so the finding's quote is verbatim by construction.
    """
    best: tuple[float, Span] | None = None
    offset = 0
    for line in doc.text.splitlines(keepends=True):
        if _TOTAL_LINE.search(line) and _AMOUNT.search(line):
            value = max(_to_number(a) for a in _AMOUNT.findall(line))
            if best is None or value > best[0]:
                # Span the whole line (newline excluded): the quote must
                # string-match uniquely in the renderer, and a bare "$90,000"
                # can appear more than once.
                stripped = line.rstrip("\r\n")
                span = Span(start=offset, end=offset + len(stripped))
                best = (value, span)
        offset += len(line)
    return best


def _gap(reason: str) -> CheckOutput:
    return CheckOutput(
        ledger=[
            LedgerRow(
                check="rubric_budget_ceiling",
                label="Budget within rubric ceiling",
                status="skipped",
                reason=reason,
            )
        ]
    )


@register(
    id="rubric_budget_ceiling",
    name="Budget within rubric ceiling",
    tier="deterministic",
)
def rubric_budget_ceiling(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    if ctx.rubric is None:
        return _gap("no rubric supplied (--rubric) — not checked against a solicitation")

    ceiling = _find_ceiling(ctx.rubric.text)
    if ceiling is None:
        return _gap(f"no unambiguous award ceiling found in rubric '{ctx.rubric.file}'")

    total = _find_budget_total(doc)
    if total is None:
        return _gap("no budget total found in the proposal")

    ceiling_value, ceiling_line = ceiling
    total_value, span = total
    within = total_value <= ceiling_value
    detail = (
        f"budget total ${total_value:,.0f} vs ceiling ${ceiling_value:,.0f}"
        f" ({ctx.rubric.file})"
    )

    findings: list[Finding] = []
    if not within:
        findings.append(
            Finding(
                id="rubric-budget-ceiling-exceeded",
                label="Budget exceeds rubric ceiling",
                anchor=Anchor(quote=doc.text[span.start : span.end], span=span),
                checks=[CheckResult(name="rubric_budget_ceiling", result=False)],
                evidence={
                    "rubric_file": ctx.rubric.file,
                    "rubric_quote": ceiling_line,
                    "ceiling_usd": ceiling_value,
                    "budget_total_usd": total_value,
                },
            )
        )

    return CheckOutput(
        ledger=[
            LedgerRow(
                check="rubric_budget_ceiling",
                label="Budget within rubric ceiling",
                result=within,
                detail=detail,
            )
        ],
        findings=findings,
    )
