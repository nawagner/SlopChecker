"""Pure evaluator for the budget-feasibility lens output (#17).

Given a parsed ``LensOutput`` (extraction + pairings from the LLM), this
module joins against ``benchmarks_us.US_2026`` and emits ``Finding``
records the runner adds to the evidence report. No LLM calls, no I/O.

The lens does no arithmetic and no judgment; every derived number and
every flag lives here. The split is what makes US-only benchmark scope
inspectable (Python + version control) and cheap to widen.

Every ``personnel_underfunded`` finding carries the assumption used
(``assumed_bands_usd``, ``assumed_fringe_rate``, ``benchmark_source``,
``flagged_because``) in ``Finding.evidence`` so a reviewer sees the
reasoning and can override without re-running.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from slopchecker.models import Anchor, CheckResult, Finding
from slopchecker.pipeline.budget_feasibility.benchmarks_us import (
    US_2026,
    BenchmarkTable,
)

# Rule 6 in the design convo: `stated < expected_p20 / threshold`, default
# threshold=3.0. The flag fires when the stated amount is materially
# below the low end of the benchmark band — a p20 band is already
# defensible-low; only flagging at 3x below keeps the false-positive
# rate honest.
DEFAULT_SHORTFALL_THRESHOLD = 3.0

# Tolerance for `sum_of_lines_matches_stated_total` — line-item rounding
# happens; a $1 mismatch is noise, not a real discrepancy.
DEFAULT_SUM_TOLERANCE_USD = 1.0


# ---------------------------------------------------------------------------
# Lens-output dataclasses (mirrors the JSON schema locked in the design
# convo). The check.py orchestrator (Phase 3) will unmarshal validated
# JSON into these; the evaluator here takes them as given.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleAllocation:
    """One (role, count, fte_fraction) tuple inside a personnel line."""

    role: str
    count: int
    fte_fraction: float


@dataclass(frozen=True)
class PersonnelLine:
    """One personnel budget line — salary/wage/stipend/fringe spend."""

    id: str
    page: int
    quote: str
    amount_usd: float
    period_yrs: float | None
    fringe_rate: float | None
    indirect_rate: float | None
    roles_named: list[RoleAllocation] = field(default_factory=list)


@dataclass(frozen=True)
class NonPersonnelLine:
    """One non-personnel budget line (equipment, travel, indirect, ...)."""

    id: str
    page: int
    quote: str
    amount_usd: float
    category: str


@dataclass(frozen=True)
class ScopeCommitment:
    """One quantitative deliverable the proposal promises."""

    id: str
    page: int
    quote: str
    quantity: float
    unit: str
    timeframe_yrs: float | None


@dataclass(frozen=True)
class Pairing:
    """Many-to-many link from a scope commitment to a budget line."""

    scope_id: str
    budget_id: str


@dataclass(frozen=True)
class ProjectInfo:
    """Project-level totals the lens surfaces when the doc states them."""

    stated_total_usd: float | None = None
    duration_yrs: float | None = None


@dataclass(frozen=True)
class LensOutput:
    """Everything the budget-feasibility lens emits about one proposal."""

    project: ProjectInfo
    personnel_lines: list[PersonnelLine] = field(default_factory=list)
    non_personnel_lines: list[NonPersonnelLine] = field(default_factory=list)
    scope_commitments: list[ScopeCommitment] = field(default_factory=list)
    pairings: list[Pairing] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Evaluator internal shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShortfallEstimate:
    """Expected personnel cost under the p20 and p80 band assumptions,
    plus the shortfall factor (expected / stated) at each end."""

    expected_p20_usd: float
    expected_p80_usd: float
    shortfall_factor_p20: float
    shortfall_factor_p80: float


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def shortfall_factor(
    line: PersonnelLine,
    benchmarks: BenchmarkTable = US_2026,
) -> ShortfallEstimate:
    """Compute expected personnel cost at p20 and p80 for one line.

    Sums each role's ``count × fte_fraction × period_yrs × band`` at
    both percentiles, multiplies by ``(1 + fringe_rate)``, and returns
    the two totals plus their ratios against the line's stated amount.

    Roles whose band is ``None`` (currently only ``"other"``) contribute
    zero — the evaluator declines to reason about them rather than
    inventing a band. A line whose roles ALL bucket to ``None`` therefore
    gets ``expected_*_usd = 0`` and ``shortfall_factor_* = 0`` — the
    orchestrator uses that as the signal to suppress the
    ``personnel_underfunded`` finding.

    ``period_yrs`` defaults to 1.0 when the lens didn't extract a
    period (the majority of grant lines are the funded year); fringe
    defaults to ``benchmarks.fringe_rate_default`` when the line
    doesn't state its own.
    """
    period = line.period_yrs if line.period_yrs is not None else 1.0
    fringe = line.fringe_rate if line.fringe_rate is not None else benchmarks.fringe_rate_default
    multiplier = 1.0 + fringe

    p20_subtotal = 0.0
    p80_subtotal = 0.0
    for role_alloc in line.roles_named:
        band = benchmarks.salary_bands_usd.get(role_alloc.role)
        if band is None:
            continue
        person_years = role_alloc.count * role_alloc.fte_fraction * period
        p20_subtotal += person_years * band[0]
        p80_subtotal += person_years * band[1]

    expected_p20 = p20_subtotal * multiplier
    expected_p80 = p80_subtotal * multiplier
    factor_p20 = expected_p20 / line.amount_usd if line.amount_usd else 0.0
    factor_p80 = expected_p80 / line.amount_usd if line.amount_usd else 0.0
    return ShortfallEstimate(
        expected_p20_usd=expected_p20,
        expected_p80_usd=expected_p80,
        shortfall_factor_p20=factor_p20,
        shortfall_factor_p80=factor_p80,
    )


def _budget_amount_index(lens_out: LensOutput) -> dict[str, float]:
    """Map budget_id (PL* or NL*) → amount_usd for pairing lookups."""
    return {
        **{pl.id: pl.amount_usd for pl in lens_out.personnel_lines},
        **{nl.id: nl.amount_usd for nl in lens_out.non_personnel_lines},
    }


def pairing_ratios(lens_out: LensOutput) -> dict[str, float]:
    """USD-per-unit ratio for each scope commitment with at least one
    paired budget line and positive quantity.

    When multiple budget lines pair to one commitment (Meridian: SC1
    trainings paired to BOTH personnel and travel), the numerator is
    the sum of all paired amounts. Ratio is
    ``sum(paired_amounts) / quantity``.

    Scopes with no pairings or zero quantity are omitted.
    """
    amounts = _budget_amount_index(lens_out)
    paired_by_scope: dict[str, list[str]] = {}
    for pair in lens_out.pairings:
        paired_by_scope.setdefault(pair.scope_id, []).append(pair.budget_id)

    quantity_by_scope = {sc.id: sc.quantity for sc in lens_out.scope_commitments}

    ratios: dict[str, float] = {}
    for scope_id, budget_ids in paired_by_scope.items():
        quantity = quantity_by_scope.get(scope_id)
        if quantity is None or quantity <= 0:
            continue
        total = sum(amounts.get(bid, 0.0) for bid in budget_ids)
        ratios[scope_id] = total / quantity
    return ratios


def unpaired_scope_ids(lens_out: LensOutput) -> set[str]:
    """Scope commitment ids that appear in no pairing."""
    paired = {p.scope_id for p in lens_out.pairings}
    return {sc.id for sc in lens_out.scope_commitments} - paired


def unpaired_budget_ids(lens_out: LensOutput) -> set[str]:
    """Budget-line ids (PL* and NL*) that appear in no pairing."""
    paired = {p.budget_id for p in lens_out.pairings}
    all_budget = {pl.id for pl in lens_out.personnel_lines} | {
        nl.id for nl in lens_out.non_personnel_lines
    }
    return all_budget - paired


def sum_of_lines_matches_stated_total(
    lens_out: LensOutput,
    tolerance_usd: float = DEFAULT_SUM_TOLERANCE_USD,
) -> bool | None:
    """Whether ``sum(personnel + non_personnel amounts) ≈ stated_total_usd``.

    Returns ``None`` when the proposal did not state a total (no basis
    for comparison — the caller should not emit a finding). Returns a
    plain ``bool`` when it did.
    """
    stated = lens_out.project.stated_total_usd
    if stated is None:
        return None
    total = sum(pl.amount_usd for pl in lens_out.personnel_lines) + sum(
        nl.amount_usd for nl in lens_out.non_personnel_lines
    )
    return abs(total - stated) <= tolerance_usd


# ---------------------------------------------------------------------------
# Top-level orchestration — builds `Finding` records
# ---------------------------------------------------------------------------


def _bench_source_label(benchmarks: BenchmarkTable) -> str:
    if benchmarks is US_2026:
        return "US_2026 (BLS OEWS May 2024 + NIH NRSA FY 2024 + Chronicle 2024)"
    return "custom benchmark table"


def _bands_for_line(line: PersonnelLine, benchmarks: BenchmarkTable) -> dict[str, list[int]]:
    """The subset of the salary-bands table that actually applied to this
    line (roles referenced with a defined band) — printed in evidence so
    the reviewer sees exactly which numbers went into the shortfall math.
    """
    out: dict[str, list[int]] = {}
    for role_alloc in line.roles_named:
        band = benchmarks.salary_bands_usd.get(role_alloc.role)
        if band is None:
            continue
        out[role_alloc.role] = [band[0], band[1]]
    return out


def _personnel_underfunded_finding(
    line: PersonnelLine,
    estimate: ShortfallEstimate,
    threshold: float,
    fired: bool,
    benchmarks: BenchmarkTable,
) -> Finding:
    fringe_used = (
        line.fringe_rate if line.fringe_rate is not None else benchmarks.fringe_rate_default
    )
    evidence: dict[str, Any] = {
        "quote": line.quote,
        "quote_page": line.page,
        "amount_stated_usd": line.amount_usd,
        "amount_expected_p20_usd": estimate.expected_p20_usd,
        "amount_expected_p80_usd": estimate.expected_p80_usd,
        "shortfall_factor_p20": estimate.shortfall_factor_p20,
        "shortfall_factor_p80": estimate.shortfall_factor_p80,
        "shortfall_flag_threshold": threshold,
        "benchmark_source": _bench_source_label(benchmarks),
        "assumed_bands_usd": _bands_for_line(line, benchmarks),
        "assumed_fringe_rate": fringe_used,
        "flagged_because": "stated < expected_p20 / threshold",
    }
    return Finding(
        id=f"BF_personnel_underfunded_{line.id}",
        target=line.id,
        label="Personnel underfunded (vs US benchmark)",
        anchor=Anchor(page=line.page, quote=line.quote),
        checks=[CheckResult(name="personnel_underfunded", result=fired)],
        evidence=evidence,
    )


def _pairing_ratio_finding(
    scope: ScopeCommitment,
    ratio: float,
    budget_ids: list[str],
) -> Finding:
    return Finding(
        id=f"BF_pairing_ratio_{scope.id}",
        target=scope.id,
        label=f"Funding per {scope.unit}",
        anchor=Anchor(page=scope.page, quote=scope.quote),
        checks=[CheckResult(name="pairing_ratio_usd_per_unit", result=ratio)],
        evidence={
            "quote": scope.quote,
            "quote_page": scope.page,
            "quantity": scope.quantity,
            "unit": scope.unit,
            "paired_budget_ids": budget_ids,
        },
    )


def _unfunded_commitment_finding(scope: ScopeCommitment) -> Finding:
    return Finding(
        id=f"BF_unfunded_commitment_{scope.id}",
        target=scope.id,
        label="Quantitative commitment with no funding source",
        anchor=Anchor(page=scope.page, quote=scope.quote),
        checks=[
            CheckResult(name="unfunded_quantitative_commitment", result=True),
        ],
        evidence={
            "quote": scope.quote,
            "quote_page": scope.page,
            "quantity": scope.quantity,
            "unit": scope.unit,
        },
    )


def _unallocated_budget_finding(
    line: PersonnelLine | NonPersonnelLine,
) -> Finding:
    return Finding(
        id=f"BF_unallocated_budget_{line.id}",
        target=line.id,
        label="Budget line with no scope commitment",
        anchor=Anchor(page=line.page, quote=line.quote),
        checks=[CheckResult(name="unallocated_budget_line", result=True)],
        evidence={
            "quote": line.quote,
            "quote_page": line.page,
            "amount_usd": line.amount_usd,
        },
    )


def _sum_matches_finding(lens_out: LensOutput, matches: bool) -> Finding:
    stated = lens_out.project.stated_total_usd
    total = sum(pl.amount_usd for pl in lens_out.personnel_lines) + sum(
        nl.amount_usd for nl in lens_out.non_personnel_lines
    )
    return Finding(
        id="BF_sum_of_lines_matches_stated_total",
        target="project",
        label="Line items sum to stated total",
        checks=[CheckResult(name="sum_of_lines_matches_stated_total", result=matches)],
        evidence={
            "stated_total_usd": stated,
            "sum_of_line_items_usd": total,
            "delta_usd": total - stated if stated is not None else None,
        },
    )


def evaluate_lens_output(
    lens_out: LensOutput,
    benchmarks: BenchmarkTable = US_2026,
    shortfall_flag_threshold: float = DEFAULT_SHORTFALL_THRESHOLD,
) -> list[Finding]:
    """Emit derived findings from a parsed lens output.

    Emits, in order:

    1. Per personnel line with at least one evaluable role — a
       ``personnel_underfunded`` finding (true when the shortfall
       factor at p20 ≥ ``shortfall_flag_threshold``).
    2. Per scope commitment with paired budget lines and positive
       quantity — a ``pairing_ratio_usd_per_unit`` finding.
    3. Per unpaired scope commitment with positive quantity — an
       ``unfunded_quantitative_commitment`` finding.
    4. Per unpaired budget line — an ``unallocated_budget_line`` finding.
    5. When ``project.stated_total_usd`` is set — a
       ``sum_of_lines_matches_stated_total`` finding.

    See ``lenses/budget_feasibility.md`` for the input schema and the
    design convo for the rationale on each of these check names.
    """
    findings: list[Finding] = []

    # 1. Personnel underfunded
    for pl in lens_out.personnel_lines:
        if not pl.roles_named:
            continue
        estimate = shortfall_factor(pl, benchmarks=benchmarks)
        if estimate.expected_p20_usd <= 0:
            # No evaluable roles (all bucketed to "other" or unknown) — the
            # evaluator declines to reason about the line.
            continue
        fired = estimate.shortfall_factor_p20 >= shortfall_flag_threshold
        findings.append(
            _personnel_underfunded_finding(
                pl,
                estimate=estimate,
                threshold=shortfall_flag_threshold,
                fired=fired,
                benchmarks=benchmarks,
            )
        )

    # 2. Pairing ratios (per scope with pairings)
    ratios = pairing_ratios(lens_out)
    scope_by_id = {sc.id: sc for sc in lens_out.scope_commitments}
    paired_by_scope: dict[str, list[str]] = {}
    for pair in lens_out.pairings:
        paired_by_scope.setdefault(pair.scope_id, []).append(pair.budget_id)
    for scope_id, ratio in ratios.items():
        scope = scope_by_id.get(scope_id)
        if scope is None:
            continue
        findings.append(
            _pairing_ratio_finding(scope, ratio=ratio, budget_ids=paired_by_scope[scope_id])
        )

    # 3. Unfunded quantitative commitments (unpaired scopes, quantity > 0)
    unpaired_scopes = unpaired_scope_ids(lens_out)
    for sc in lens_out.scope_commitments:
        if sc.id not in unpaired_scopes:
            continue
        if sc.quantity is None or sc.quantity <= 0:
            continue
        findings.append(_unfunded_commitment_finding(sc))

    # 4. Unallocated budget lines
    unpaired_budgets = unpaired_budget_ids(lens_out)
    for pl in lens_out.personnel_lines:
        if pl.id in unpaired_budgets:
            findings.append(_unallocated_budget_finding(pl))
    for nl in lens_out.non_personnel_lines:
        if nl.id in unpaired_budgets:
            findings.append(_unallocated_budget_finding(nl))

    # 5. Sum-of-lines vs stated total (only when stated)
    matches = sum_of_lines_matches_stated_total(lens_out)
    if matches is not None:
        findings.append(_sum_matches_finding(lens_out, matches=matches))

    return findings
