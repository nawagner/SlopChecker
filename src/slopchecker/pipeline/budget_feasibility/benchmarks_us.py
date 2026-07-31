"""US-only salary and rate benchmarks for the budget-feasibility check (#17).

Numbers are wide 20th–80th-percentile bands drawn from public sources
(BLS OEWS May 2024, Chronicle of Higher Ed Faculty Salary Survey 2024,
NIH NRSA FY 2024 stipend scale). Widening a band later is cheap;
narrowing is not — err generous.

**Verify against source before shipping to any demo run.** These are
drafts locked in the #17 design conversation; a reviewer should be able
to trace every band back to the citation printed alongside it. If a
value here changes, the change is deliberate and gets a comment saying
why.

Only US-relevant roles are covered. Non-US cost structures (e.g. LMIC
program-officer salaries, EU consortium indirects) are OUT of scope
per the design convo — the evaluator refuses to reason about lines
whose roles don't bucket into this table's keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BenchmarkTable:
    """Wide-range US benchmarks for personnel and indirects.

    ``salary_bands_usd[role]`` is a ``(p20, p80)`` tuple in USD/FTE-year,
    or ``None`` for roles the table declines to evaluate (the ``other``
    escape valve). ``fringe_rate_default`` is used only when a personnel
    line does not state its own fringe rate inline. Indirect rate is
    NOT baked in here — proposals state their own NICRA rate; the
    evaluator captures the stated rate from the personnel line or from
    an indirect ``non_personnel_line``.
    """

    salary_bands_usd: dict[str, tuple[int, int] | None]
    grad_tuition_usd_per_year: tuple[int, int]
    fringe_rate_default: float
    citations: dict[str, str] = field(default_factory=dict)


US_2026 = BenchmarkTable(
    salary_bands_usd={
        # PI/faculty bands: R1 tenured/tenure-track full-time, wide range
        # covering assistant → full professor across disciplines.
        "pi": (95_000, 220_000),
        "co_pi": (85_000, 180_000),
        "senior_scientist": (95_000, 200_000),
        # Postdoc: NIH NRSA FY 2024 minimum ($52,704) rounded to $52,000;
        # upper end reflects industry-adjacent postdocs and non-NIH funders.
        "postdoc": (52_000, 82_000),
        # Grad student stipend only — tuition/fees tracked separately.
        "grad_student": (30_000, 45_000),
        "research_assistant": (45_000, 75_000),
        "admin": (48_000, 90_000),
        "technician": (42_000, 78_000),
        # Consultant per-FTE-year equivalent (per-day rates converted).
        "consultant": (100_000, 300_000),
        # "other" is the escape valve — the evaluator declines to reason
        # about roles it can't bucket. Contribution to expected cost is
        # zero, which drops the personnel_underfunded flag rather than
        # triggering it on a role we don't understand.
        "other": None,
    },
    grad_tuition_usd_per_year=(30_000, 60_000),
    fringe_rate_default=0.28,
    citations={
        "salary_bands": ("BLS OEWS May 2024 + Chronicle of Higher Ed Faculty Salary Survey 2024"),
        "postdoc": "NIH NRSA FY 2024 stipend scale + BLS SOC 19-3099",
        "grad_stipend": "Chronicle grad stipend survey 2024",
        "fringe": "NIH standard fringe assumption; institutional rates vary 25-35%",
    },
)
