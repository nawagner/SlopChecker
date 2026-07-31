"""Tests for #17: budget-feasibility evaluator.

The lens (``lenses/budget_feasibility.md``) does pure extraction + pairing.
The evaluator here joins the lens output against ``benchmarks_us.py`` and
emits ``Finding`` records — this is where the actual feasibility judgment
lives. The two artifacts are split following the ``claim_support``
precedent so US-only benchmark scope stays inspectable and version-
controlled in Python, not baked into a prompt.

Two contracts under test:

1. Pure-function arithmetic — ``shortfall_factor``, ``pairing_ratios``,
   ``unpaired_scope_ids``, ``unpaired_budget_ids``,
   ``sum_of_lines_matches_stated_total``. Given a hand-crafted
   ``LensOutput``, the numbers come out as documented in the design
   convo and its planted-defect worked example.

2. End-to-end ``evaluate_lens_output`` on the Meridian planted-defect
   fixture emits the expected set of findings, with the benchmark
   assumption printed in every ``personnel_underfunded`` finding's
   ``evidence`` so a reviewer can override.

No LLM calls. No I/O. All fixtures are fabricated per CLAUDE.md.
"""

from __future__ import annotations

from math import isclose

import pytest

from slopchecker.pipeline.budget_feasibility.benchmarks_us import (
    US_2026,
    BenchmarkTable,
)
from slopchecker.pipeline.budget_feasibility.evaluate import (
    LensOutput,
    NonPersonnelLine,
    Pairing,
    PersonnelLine,
    ProjectInfo,
    RoleAllocation,
    ScopeCommitment,
    ShortfallEstimate,
    evaluate_lens_output,
    pairing_ratios,
    shortfall_factor,
    sum_of_lines_matches_stated_total,
    unpaired_budget_ids,
    unpaired_scope_ids,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _meridian_pl1() -> PersonnelLine:
    """The planted-defect personnel line from the design convo.

    PI at 25% effort for 1 year + two postdocs at 100% effort for 1 year,
    charged at $40,000 total inclusive of 28% fringe.
    """
    return PersonnelLine(
        id="PL1",
        page=2,
        quote="Total personnel: $40,000, inclusive of a fringe benefits rate of 28%.",
        amount_usd=40_000,
        period_yrs=1.0,
        fringe_rate=0.28,
        indirect_rate=None,
        roles_named=[
            RoleAllocation(role="pi", count=1, fte_fraction=0.25),
            RoleAllocation(role="postdoc", count=2, fte_fraction=1.0),
        ],
    )


def _meridian_lens_output() -> LensOutput:
    """The full Meridian few-shot as a LensOutput (schema from the design convo)."""
    return LensOutput(
        project=ProjectInfo(stated_total_usd=148_000, duration_yrs=1.0),
        personnel_lines=[_meridian_pl1()],
        non_personnel_lines=[
            NonPersonnelLine(
                id="NL1",
                page=2,
                quote="Equipment: $12,000 for laptop and secure-comms procurement.",
                amount_usd=12_000,
                category="equipment",
            ),
            NonPersonnelLine(
                id="NL2",
                page=2,
                quote="Travel: $18,000 for regional training delivery across six US regions.",
                amount_usd=18_000,
                category="travel",
            ),
            NonPersonnelLine(
                id="NL3",
                page=2,
                quote=(
                    "Indirect costs: $78,000, calculated at 55% of modified "
                    "total direct costs per the Meridian NICRA agreement."
                ),
                amount_usd=78_000,
                category="indirect",
            ),
        ],
        scope_commitments=[
            ScopeCommitment(
                id="SC1",
                page=1,
                quote="twelve regional trainings",
                quantity=12,
                unit="training",
                timeframe_yrs=1.0,
            ),
            ScopeCommitment(
                id="SC2",
                page=1,
                quote="a 40-country monitoring network",
                quantity=40,
                unit="country",
                timeframe_yrs=1.0,
            ),
            ScopeCommitment(
                id="SC3",
                page=1,
                quote="a peer-reviewed evaluation study",
                quantity=1,
                unit="study",
                timeframe_yrs=1.0,
            ),
            ScopeCommitment(
                id="SC4",
                page=1,
                quote="an open-source detection toolkit",
                quantity=1,
                unit="toolkit",
                timeframe_yrs=1.0,
            ),
        ],
        pairings=[
            Pairing(scope_id="SC1", budget_id="PL1"),
            Pairing(scope_id="SC1", budget_id="NL2"),
            Pairing(scope_id="SC2", budget_id="PL1"),
        ],
    )


# ---------------------------------------------------------------------------
# shortfall_factor
# ---------------------------------------------------------------------------


def test_shortfall_factor_meridian_planted_case():
    """The Meridian PL1 defect: 2.25 FTE-yr charged at $40K.

    Expected p20 = (0.25 × $95,000 PI + 2 × 1.0 × $52,000 postdoc) × 1.28 fringe
                 = (23,750 + 104,000) × 1.28
                 = 127,750 × 1.28
                 = $163,520.

    (The implementation plan quoted ~$163,840 — off by $320 versus its own
    arithmetic. Verified by hand; using the correct product here. Both
    numbers round to a shortfall factor of ~4.1, so the qualitative story
    the design convo tells is unchanged.)
    """
    estimate = shortfall_factor(_meridian_pl1(), benchmarks=US_2026)
    assert isinstance(estimate, ShortfallEstimate)
    assert isclose(estimate.expected_p20_usd, 163_520.0, abs_tol=0.01)
    assert isclose(estimate.shortfall_factor_p20, 163_520.0 / 40_000.0, abs_tol=1e-6)


def test_shortfall_factor_p80_uses_upper_band():
    """p80 uses the upper end of each role's band and the same fringe."""
    # PI p80 220_000; postdoc p80 82_000
    # expected_p80 = (0.25 × 220_000 + 2 × 82_000) × 1.28
    #              = (55_000 + 164_000) × 1.28
    #              = 219_000 × 1.28
    #              = 280_320
    estimate = shortfall_factor(_meridian_pl1(), benchmarks=US_2026)
    assert isclose(estimate.expected_p80_usd, 280_320.0, abs_tol=0.01)
    assert isclose(estimate.shortfall_factor_p80, 280_320.0 / 40_000.0, abs_tol=1e-6)


def test_shortfall_factor_skips_role_other_as_zero_contribution():
    """A role bucketed to 'other' has no band, so it contributes zero to
    expected cost. This is the escape valve for titles the enum can't
    represent — the check silently drops them rather than inventing a band.
    """
    line = PersonnelLine(
        id="PL_other",
        page=1,
        quote="Consultant: $200,000, one full-time consultant.",
        amount_usd=200_000,
        period_yrs=1.0,
        fringe_rate=None,  # use benchmark default
        indirect_rate=None,
        roles_named=[
            RoleAllocation(role="other", count=1, fte_fraction=1.0),
        ],
    )
    estimate = shortfall_factor(line, benchmarks=US_2026)
    assert estimate.expected_p20_usd == 0.0
    assert estimate.expected_p80_usd == 0.0


def test_shortfall_factor_uses_line_fringe_when_stated():
    """When the personnel line states its own fringe rate, that wins over
    the benchmark's default fringe. Uses PI-only for math clarity."""
    line = PersonnelLine(
        id="PL_alt",
        page=1,
        quote="PI at 100% effort, $200,000 total, fringe 50%.",
        amount_usd=200_000,
        period_yrs=1.0,
        fringe_rate=0.50,  # line-stated, higher than benchmark default of 0.28
        indirect_rate=None,
        roles_named=[RoleAllocation(role="pi", count=1, fte_fraction=1.0)],
    )
    # expected_p20 = 95_000 × (1 + 0.50) = 142_500
    estimate = shortfall_factor(line, benchmarks=US_2026)
    assert isclose(estimate.expected_p20_usd, 142_500.0, abs_tol=0.01)


# ---------------------------------------------------------------------------
# personnel_underfunded flag boundary (through evaluate_lens_output)
# ---------------------------------------------------------------------------


def _lens_out_with_single_pl(line: PersonnelLine) -> LensOutput:
    return LensOutput(
        project=ProjectInfo(stated_total_usd=None, duration_yrs=None),
        personnel_lines=[line],
        non_personnel_lines=[],
        scope_commitments=[],
        pairings=[],
    )


def _finding_by_check(findings, check_name, target=None):
    for f in findings:
        if any(cr.name == check_name for cr in f.checks):
            if target is None or f.target == target:
                return f
    return None


def test_personnel_underfunded_fires_exactly_at_threshold_boundary():
    """Threshold is 3.0 with a `>=` boundary (per the implementation plan):
    a shortfall factor of exactly 3.0 fires the flag.

    Construct a PI-only line whose expected_p20 / stated == 3.0 exactly.
    expected_p20 = 95_000 × 1.28 = 121_600, so stated = 121_600 / 3.0.
    """
    stated = 121_600.0 / 3.0
    line = PersonnelLine(
        id="PL_boundary",
        page=1,
        quote="PI at 100% effort for one year.",
        amount_usd=stated,
        period_yrs=1.0,
        fringe_rate=None,
        indirect_rate=None,
        roles_named=[RoleAllocation(role="pi", count=1, fte_fraction=1.0)],
    )
    findings = evaluate_lens_output(_lens_out_with_single_pl(line))
    underfunded = _finding_by_check(findings, "personnel_underfunded", target="PL_boundary")
    assert underfunded is not None
    result = next(cr.result for cr in underfunded.checks if cr.name == "personnel_underfunded")
    assert result is True


def test_personnel_underfunded_does_not_fire_below_threshold():
    """A shortfall factor of ~2.9 (below the 3.0 default) does not fire.

    stated = expected_p20 / 2.9 → factor is 2.9.
    """
    stated = 121_600.0 / 2.9
    line = PersonnelLine(
        id="PL_below",
        page=1,
        quote="PI at 100% effort for one year, tight but not implausible.",
        amount_usd=stated,
        period_yrs=1.0,
        fringe_rate=None,
        indirect_rate=None,
        roles_named=[RoleAllocation(role="pi", count=1, fte_fraction=1.0)],
    )
    findings = evaluate_lens_output(_lens_out_with_single_pl(line))
    underfunded = _finding_by_check(findings, "personnel_underfunded", target="PL_below")
    if underfunded is not None:
        result = next(cr.result for cr in underfunded.checks if cr.name == "personnel_underfunded")
        assert result is False


def test_personnel_underfunded_fires_meridian_planted_shortfall():
    """The Meridian planted defect: ~4.1x shortfall against p20 → fires."""
    findings = evaluate_lens_output(_lens_out_with_single_pl(_meridian_pl1()))
    underfunded = _finding_by_check(findings, "personnel_underfunded", target="PL1")
    assert underfunded is not None
    result = next(cr.result for cr in underfunded.checks if cr.name == "personnel_underfunded")
    assert result is True


def test_personnel_underfunded_skipped_when_roles_named_empty():
    """A personnel line that names no roles has no evaluable salary math,
    so no personnel_underfunded finding is emitted at all. (Per the plan:
    'A PersonnelLine with roles_named=[] emits no personnel_underfunded
    finding, only pairing_ratio_usd_per_unit.')"""
    line = PersonnelLine(
        id="PL_no_roles",
        page=1,
        quote="Personnel: $10,000.",
        amount_usd=10_000,
        period_yrs=1.0,
        fringe_rate=None,
        indirect_rate=None,
        roles_named=[],
    )
    findings = evaluate_lens_output(_lens_out_with_single_pl(line))
    assert _finding_by_check(findings, "personnel_underfunded", target="PL_no_roles") is None


def test_personnel_underfunded_evidence_carries_the_assumption():
    """Every personnel_underfunded finding must print the benchmark
    assumption in `evidence` so a reviewer can override without re-running.
    Fields: assumed_bands_usd, assumed_fringe_rate, benchmark_source,
    flagged_because, amount_stated_usd, amount_expected_p20_usd,
    amount_expected_p80_usd, shortfall_factor_p20."""
    findings = evaluate_lens_output(_lens_out_with_single_pl(_meridian_pl1()))
    underfunded = _finding_by_check(findings, "personnel_underfunded", target="PL1")
    assert underfunded is not None
    ev = underfunded.evidence
    assert ev["amount_stated_usd"] == 40_000
    assert isclose(ev["amount_expected_p20_usd"], 163_520.0, abs_tol=0.01)
    assert isclose(ev["amount_expected_p80_usd"], 280_320.0, abs_tol=0.01)
    assert isclose(ev["shortfall_factor_p20"], 163_520.0 / 40_000.0, abs_tol=1e-6)
    assert ev["shortfall_flag_threshold"] == 3.0
    assert "benchmark_source" in ev and ev["benchmark_source"]
    assert ev["assumed_bands_usd"]["pi"] == [95_000, 220_000]
    assert ev["assumed_bands_usd"]["postdoc"] == [52_000, 82_000]
    assert ev["assumed_fringe_rate"] == 0.28
    assert ev["flagged_because"] == "stated < expected_p20 / threshold"


# ---------------------------------------------------------------------------
# pairing_ratios
# ---------------------------------------------------------------------------


def test_pairing_ratio_single_budget_line():
    """SC1 (quantity=40, unit=country) paired to PL1 (amount_usd=$40,000):
    ratio = 40,000 / 40 = $1,000 per country."""
    lens_out = LensOutput(
        project=ProjectInfo(),
        personnel_lines=[
            PersonnelLine(
                id="PL1",
                page=1,
                quote="Personnel: $40,000.",
                amount_usd=40_000,
                period_yrs=1.0,
                fringe_rate=None,
                indirect_rate=None,
                roles_named=[],
            )
        ],
        non_personnel_lines=[],
        scope_commitments=[
            ScopeCommitment(
                id="SC1",
                page=1,
                quote="a 40-country network",
                quantity=40,
                unit="country",
                timeframe_yrs=None,
            )
        ],
        pairings=[Pairing(scope_id="SC1", budget_id="PL1")],
    )
    ratios = pairing_ratios(lens_out)
    assert ratios["SC1"] == pytest.approx(1_000.0)


def test_pairing_ratio_sums_multiple_paired_budget_lines():
    """When a single scope commitment is paired to multiple budget lines,
    the ratio is sum(paired_amounts) / quantity — the whole envelope
    funding the commitment divided by the quantity being delivered.

    Meridian: SC1 (12 trainings) paired to BOTH PL1 (personnel deliver
    them, $40K) AND NL2 (travel funds them, $18K). Ratio = 58,000 / 12
    ≈ $4,833.33 per training.
    """
    lens_out = LensOutput(
        project=ProjectInfo(),
        personnel_lines=[
            PersonnelLine(
                id="PL1",
                page=1,
                quote="Personnel: $40,000.",
                amount_usd=40_000,
                period_yrs=1.0,
                fringe_rate=None,
                indirect_rate=None,
                roles_named=[],
            )
        ],
        non_personnel_lines=[
            NonPersonnelLine(
                id="NL2",
                page=1,
                quote="Travel: $18,000.",
                amount_usd=18_000,
                category="travel",
            )
        ],
        scope_commitments=[
            ScopeCommitment(
                id="SC1",
                page=1,
                quote="twelve regional trainings",
                quantity=12,
                unit="training",
                timeframe_yrs=None,
            )
        ],
        pairings=[
            Pairing(scope_id="SC1", budget_id="PL1"),
            Pairing(scope_id="SC1", budget_id="NL2"),
        ],
    )
    ratios = pairing_ratios(lens_out)
    assert ratios["SC1"] == pytest.approx(58_000.0 / 12.0)


# ---------------------------------------------------------------------------
# unpaired_scope_ids / unpaired_budget_ids
# ---------------------------------------------------------------------------


def test_unpaired_scope_ids_meridian_returns_sc3_and_sc4():
    """SC1 and SC2 are paired to PL1/NL2; SC3 (evaluation study) and SC4
    (toolkit) are not paired to anything."""
    lens_out = _meridian_lens_output()
    assert unpaired_scope_ids(lens_out) == {"SC3", "SC4"}


def test_unpaired_budget_ids_meridian_returns_nl1_and_nl3():
    """PL1 and NL2 are paired; NL1 (equipment) and NL3 (indirect) are not
    paired to any scope commitment."""
    lens_out = _meridian_lens_output()
    assert unpaired_budget_ids(lens_out) == {"NL1", "NL3"}


def test_unfunded_quantitative_commitment_skipped_for_quantity_zero():
    """A scope commitment with quantity=0 is not a real quantitative
    commitment. Even if it's unpaired, no `unfunded_quantitative_commitment`
    finding is emitted for it (plan: 'quantity>0 gate')."""
    lens_out = LensOutput(
        project=ProjectInfo(),
        personnel_lines=[],
        non_personnel_lines=[],
        scope_commitments=[
            ScopeCommitment(
                id="SC0",
                page=1,
                quote="a placeholder commitment",
                quantity=0,
                unit="thing",
                timeframe_yrs=None,
            )
        ],
        pairings=[],
    )
    findings = evaluate_lens_output(lens_out)
    assert _finding_by_check(findings, "unfunded_quantitative_commitment", target="SC0") is None


def test_unfunded_quantitative_commitment_fires_for_unpaired_positive_quantity():
    """An unpaired scope commitment with a positive quantity emits
    `unfunded_quantitative_commitment: true`."""
    findings = evaluate_lens_output(_meridian_lens_output())
    sc3 = _finding_by_check(findings, "unfunded_quantitative_commitment", target="SC3")
    sc4 = _finding_by_check(findings, "unfunded_quantitative_commitment", target="SC4")
    assert sc3 is not None
    assert sc4 is not None
    for f in (sc3, sc4):
        result = next(cr.result for cr in f.checks if cr.name == "unfunded_quantitative_commitment")
        assert result is True


def test_unallocated_budget_line_fires_for_unpaired_lines():
    """Meridian NL1 (equipment) and NL3 (indirect) have no scope pairing;
    both emit `unallocated_budget_line: true`."""
    findings = evaluate_lens_output(_meridian_lens_output())
    nl1 = _finding_by_check(findings, "unallocated_budget_line", target="NL1")
    nl3 = _finding_by_check(findings, "unallocated_budget_line", target="NL3")
    assert nl1 is not None
    assert nl3 is not None


# ---------------------------------------------------------------------------
# sum_of_lines_matches_stated_total
# ---------------------------------------------------------------------------


def test_sum_of_lines_matches_stated_total_meridian_exact():
    """40k personnel + 12k equipment + 18k travel + 78k indirect = 148k,
    which equals the stated $148,000 total exactly."""
    assert sum_of_lines_matches_stated_total(_meridian_lens_output()) is True


def test_sum_of_lines_matches_within_one_dollar_tolerance():
    """A $1 rounding delta is tolerated as 'matches'."""
    lens_out = _meridian_lens_output()
    # Rebuild with stated_total off by exactly $1.
    lens_out = LensOutput(
        project=ProjectInfo(stated_total_usd=148_001, duration_yrs=1.0),
        personnel_lines=lens_out.personnel_lines,
        non_personnel_lines=lens_out.non_personnel_lines,
        scope_commitments=lens_out.scope_commitments,
        pairings=lens_out.pairings,
    )
    assert sum_of_lines_matches_stated_total(lens_out) is True


def test_sum_of_lines_does_not_match_when_delta_is_material():
    """A $1,000 mismatch is not within tolerance."""
    lens_out = _meridian_lens_output()
    lens_out = LensOutput(
        project=ProjectInfo(stated_total_usd=147_000, duration_yrs=1.0),
        personnel_lines=lens_out.personnel_lines,
        non_personnel_lines=lens_out.non_personnel_lines,
        scope_commitments=lens_out.scope_commitments,
        pairings=lens_out.pairings,
    )
    assert sum_of_lines_matches_stated_total(lens_out) is False


def test_sum_of_lines_check_not_emitted_when_stated_total_is_null():
    """When the proposal doesn't state a total, we don't invent one — the
    check simply is not emitted."""
    lens_out = _meridian_lens_output()
    lens_out = LensOutput(
        project=ProjectInfo(stated_total_usd=None, duration_yrs=1.0),
        personnel_lines=lens_out.personnel_lines,
        non_personnel_lines=lens_out.non_personnel_lines,
        scope_commitments=lens_out.scope_commitments,
        pairings=lens_out.pairings,
    )
    findings = evaluate_lens_output(lens_out)
    assert _finding_by_check(findings, "sum_of_lines_matches_stated_total") is None


# ---------------------------------------------------------------------------
# evaluate_lens_output end-to-end shape on Meridian
# ---------------------------------------------------------------------------


def test_evaluate_meridian_emits_expected_finding_shape():
    """Feed the full Meridian LensOutput and check the shape of the
    emitted evidence:

    - one personnel_underfunded finding (PL1, true)
    - two pairing_ratio_usd_per_unit findings (SC1, SC2) — one per
      *unique paired scope*, not one per Pairing row. Many-to-many
      pairings collapse into a single ratio per scope with the
      numerator summed across all budget lines paired to that scope.
      Meridian has 3 pairing rows but only 2 unique paired scopes.
    - two unfunded_quantitative_commitment findings (SC3, SC4)
    - two unallocated_budget_line findings (NL1, NL3)
    - one sum_of_lines_matches_stated_total finding (true)
    """
    findings = evaluate_lens_output(_meridian_lens_output())
    counts: dict[str, int] = {}
    for f in findings:
        for cr in f.checks:
            counts[cr.name] = counts.get(cr.name, 0) + 1
    assert counts.get("personnel_underfunded", 0) == 1
    assert counts.get("pairing_ratio_usd_per_unit", 0) == 2
    assert counts.get("unfunded_quantitative_commitment", 0) == 2
    assert counts.get("unallocated_budget_line", 0) == 2
    assert counts.get("sum_of_lines_matches_stated_total", 0) == 1


def test_evaluate_findings_all_carry_a_target():
    """Every finding points at a specific lens-output id (PL/NL/SC) or is
    the project-level sum check — no orphan findings."""
    findings = evaluate_lens_output(_meridian_lens_output())
    assert findings
    for f in findings:
        assert f.target is not None and f.target


def test_evaluate_respects_custom_shortfall_threshold():
    """Passing a stricter threshold (say 5.0) suppresses the Meridian
    planted underfunding because its shortfall factor is ~4.1 < 5.0."""
    findings = evaluate_lens_output(_meridian_lens_output(), shortfall_flag_threshold=5.0)
    underfunded = _finding_by_check(findings, "personnel_underfunded", target="PL1")
    if underfunded is not None:
        result = next(cr.result for cr in underfunded.checks if cr.name == "personnel_underfunded")
        assert result is False


def test_us_2026_bands_match_design_convo_lockdown():
    """The design convo locked specific salary bands; those bands are the
    contract with the reviewer (evidence field ``assumed_bands_usd``).
    Guard against a silent widening of the bands — if the numbers change,
    this test fails and the change is deliberate."""
    assert isinstance(US_2026, BenchmarkTable)
    assert US_2026.salary_bands_usd["pi"] == (95_000, 220_000)
    assert US_2026.salary_bands_usd["co_pi"] == (85_000, 180_000)
    assert US_2026.salary_bands_usd["senior_scientist"] == (95_000, 200_000)
    assert US_2026.salary_bands_usd["postdoc"] == (52_000, 82_000)
    assert US_2026.salary_bands_usd["grad_student"] == (30_000, 45_000)
    assert US_2026.salary_bands_usd["research_assistant"] == (45_000, 75_000)
    assert US_2026.salary_bands_usd["admin"] == (48_000, 90_000)
    assert US_2026.salary_bands_usd["technician"] == (42_000, 78_000)
    assert US_2026.salary_bands_usd["consultant"] == (100_000, 300_000)
    assert US_2026.salary_bands_usd["other"] is None
    assert US_2026.fringe_rate_default == 0.28
