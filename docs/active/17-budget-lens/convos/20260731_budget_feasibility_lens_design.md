# 2026-07-31 — Budget-feasibility lens design

Participants: Dan (air) + fable (claude-sonnet).

## Session goal

Design the LLM lens for #17 (budget & achievability). Split the issue's arithmetic half out to its own ticket so the lens can be scoped cleanly.

## Framing decisions

- **Split #17 into two work items.** Arithmetic (line items sum, indirect rate, totals-match-narrative) is deterministic and belongs in `checks/` (Nick's module) — filed as #109. Feasibility is LLM-driven and belongs in `lenses/` (Dan's module) — stays on #17, this branch.
- **Lens posture: pure extraction + pairing, no verdict in the lens itself.** Lenses in this repo are declared "evidence, not verdicts" per `lenses/README.md`; the `claims` lens is precedent (extraction only). Judgment stays deterministic.
- **Bounded scope: US-only for v1.** Directly counters #17's failure-mode note about flagging unfamiliar-but-legitimate cost structures — we're not evaluating non-US structures because we're not looking at them. Other jurisdictions get their own benchmarks module later.
- **Two-artifact structure, matching `claim_support` precedent:**
  - `lenses/budget_feasibility.md` — LLM prompt pack (extracts + pairs + emits structured budget/scope objects)
  - `pipeline/budget_feasibility/` — Python that runs the lens, joins against `benchmarks_us.py`, computes shortfall factors, emits `Findings` with the bench assumption in `evidence`
- **Benchmark posture: wide, defensible ranges.** 20th–80th percentile from published surveys (BLS OEWS, Chronicle salary survey, NIH stipend scale). Trades some sensitivity for confidence in every flag. Cited in the module.

## Lens output schema (locked)

```json
{
  "project": {"stated_total_usd": 148000, "duration_yrs": 1},
  "personnel_lines": [
    {
      "id": "PL1",
      "page": 5,
      "quote": "verbatim contiguous substring from the doc",
      "amount_usd": 40000,
      "period_yrs": 3,
      "fringe_rate": 0.28,     // nullable — only when stated
      "indirect_rate": null,   // nullable — only when stated
      "roles_named": [
        {"role": "pi", "count": 1, "fte_fraction": 0.25},
        {"role": "postdoc", "count": 2, "fte_fraction": 1.0}
      ]
    }
  ],
  "non_personnel_lines": [
    {
      "id": "NL1",
      "page": 5,
      "quote": "Equipment: $12,000",
      "amount_usd": 12000,
      "category": "equipment | travel | supplies | indirect | subcontract | other"
    }
  ],
  "scope_commitments": [
    {
      "id": "SC1",
      "page": 2,
      "quote": "40-country monitoring network within year one",
      "quantity": 40,
      "unit": "country",
      "timeframe_yrs": 1
    }
  ],
  "pairings": [
    {"scope_id": "SC1", "budget_id": "PL1"}
  ]
}
```

### Schema rules (locked)

- **No free-text fields anywhere.** Every field is quote (verbatim), enum, number, or bool. Matches `claims.md` rule #7.
- **`role` enum, closed:** `pi | co_pi | senior_scientist | postdoc | grad_student | research_assistant | admin | technician | consultant | other`. Model bucketizes free-text titles into this list. Enum is what `benchmarks_us.py` keys against.
- **Model does no arithmetic.** No `raw_ratio` in the schema — Python evaluator computes `amount_usd / quantity` and everything else. Model extracts only what the doc says.
- **`unpaired_scope` / `unpaired_budget` are Python-derived,** not model-emitted. Computed as `all_ids - paired_ids`.
- **`pairings` are many-to-many.** A scope can pair to several budget lines (deliverables = personnel + travel); a budget line can pair to several scope items (same postdocs do trainings AND monitoring).
- **Nullable fields the model must NOT invent:** `period_yrs`, `timeframe_yrs`, `fte_fraction`, `fringe_rate`, `indirect_rate`, `project.stated_total_usd`, `project.duration_yrs`. Rule mirrors the `claims` lens's `citation: null` discipline.
- **`pairing_basis` deliberately dropped.** MVP — if the pair is wrong, quotes make it inspectable; the model doesn't need to explain itself.

### Meta-design decisions (unchanged from framing)

- Fringe rate captured per personnel line when stated inline; indirect rate captured when stated inline OR as its own `non_personnel_lines` entry with `category: "indirect"`. The evaluator can look in both places.
- Project-level `stated_total_usd` overlaps with #109's arithmetic territory (line-items-sum-to-stated-total). Shared via `report.json` — coordinate on the field name with Nick before either merges.

## Few-shot pack (locked)

**Fabricated proposal** (Meridian variant, continuity with `claims.md`):

```text
[[page 1]]
The Meridian Institute proposes a coordinated response to the accelerating erosion of information integrity. Our program will deliver twelve regional trainings, a 40-country monitoring network, a peer-reviewed evaluation study, and an open-source detection toolkit within the first grant year, at a total cost of $148,000.

[[page 2]]
Personnel. Dr. Alina Vasquez (PI, 25% effort, 12 months) will oversee program design and stakeholder engagement. Two postdoctoral researchers (100% effort, 12 months each) will conduct the trainings and lead the country-monitoring rollout. Total personnel: $40,000, inclusive of a fringe benefits rate of 28%.

Equipment: $12,000 for laptop and secure-comms procurement.
Travel: $18,000 for regional training delivery across six US regions.
Indirect costs: $78,000, calculated at 55% of modified total direct costs per the Meridian NICRA agreement.
```

**Expected output** — see the JSON block in the design conversation for the full artifact. Highlights the model must reproduce:

- SC1 (trainings) pairs to BOTH PL1 (personnel deliver them) and NL2 (travel funds them).
- PL1 pairs to BOTH SC1 (trainings) and SC2 (country network) — same postdocs cover both.
- `fringe_rate: 0.28` on PL1 (stated inline), `indirect_rate: null` on PL1 (indirects live as NL3).
- SC3 (evaluation study) and SC4 (toolkit) have no pairing — surface as unpaired scope downstream.

**Planted feasibility signal:** $40K personnel for 2 FTE-yr postdoc equivalents = ~$20K/postdoc-year. US postdoc band is $52K–82K per BLS. Evaluator flags shortfall factor ≥3 → `personnel_underfunded: true` on PL1.

## Python evaluator interface (locked)

Module layout follows `pipeline/claim_support/` precedent:

```
src/slopchecker/pipeline/budget_feasibility/
├── __init__.py       # public API: registered check + Finding emit
├── check.py          # orchestrator — invokes the lens, joins with benchmarks, emits Findings
├── llm.py            # thin wrapper around the LLM call, JSON-schema retry logic
├── benchmarks_us.py  # {role: (p20, p80)} + fringe/indirect assumptions + citations
└── evaluate.py       # pure functions: shortfall_factor(), pairing_ratios(), etc.
```

### Evaluator signature

```python
def evaluate_lens_output(
    lens_out: LensOutput,
    benchmarks: BenchmarkTable = US_2026,
    shortfall_flag_threshold: float = 3.0,
) -> list[Finding]:
    """Compute derived findings from a parsed lens output.

    Emits Findings for:
      - Each personnel_line: personnel_expected_cost_p20, _p80, shortfall_factor,
        and personnel_underfunded (bool) if shortfall_factor >= threshold.
      - Each pairing: pairing_ratio_usd_per_unit (float, no threshold).
      - Each unpaired scope with quantity > 0: unfunded_quantitative_commitment (bool true).
      - Each unpaired budget line: unallocated_budget_line (bool true).
      - Project-level: sum_of_lines_matches_stated_total (bool, only when project.stated_total_usd is not null).
    """
```

### `benchmarks_us.py` shape (wide 20th–80th percentile)

```python
US_2026 = BenchmarkTable(
    salary_bands_usd={
        "pi":                 (95_000, 220_000),    # Chronicle 2024 R1 tenured/tenure-track full-time
        "co_pi":              (85_000, 180_000),
        "senior_scientist":   (95_000, 200_000),
        "postdoc":            (52_000, 82_000),     # NIH NRSA + BLS
        "grad_student":       (30_000, 45_000),     # + tuition tracked separately
        "research_assistant": (45_000, 75_000),
        "admin":              (48_000, 90_000),
        "technician":         (42_000, 78_000),
        "consultant":         (100_000, 300_000),   # per-day converted to FTE-equivalent
        "other":              None,                  # no evaluation for this bucket
    },
    grad_tuition_usd_per_year=(30_000, 60_000),
    fringe_rate_default=0.28,
    citations={
        "salary_bands": "BLS OEWS May 2024 + Chronicle of Higher Ed Faculty Salary Survey 2024",
        "postdoc":      "NIH NRSA FY 2024 stipend scale + BLS SOC 19-3099",
        "grad_stipend": "Chronicle grad stipend survey 2024",
    },
)
```

### Every Finding carries the assumption used in `evidence`

```json
{
  "check": "personnel_underfunded",
  "target": "PL1",
  "result": true,
  "evidence": {
    "quote": "...verbatim personnel-line quote...",
    "quote_page": 2,
    "amount_stated_usd": 40000,
    "amount_expected_p20_usd": 156000,
    "amount_expected_p80_usd": 246000,
    "shortfall_factor_p20": 3.9,
    "shortfall_flag_threshold": 3.0,
    "benchmark_source": "US_2026 (BLS OEWS May 2024 + NIH NRSA FY 2024)",
    "assumed_bands_usd": {"pi": [95000, 220000], "postdoc": [52000, 82000]},
    "assumed_fringe_rate": 0.28,
    "flagged_because": "stated < expected_p20 / threshold"
  }
}
```

### Flag rule rationale

`personnel_underfunded := stated < expected_p20 / threshold` (not `stated < expected_p20`). The 20th-percentile lower band is *already* a defensible low-cost assumption. Only flagging when the stated $ is materially below even p20 (default 3x below) keeps false-positive rate honest — the flag fires when money makes no plausible sense against US benchmarks, not when it's merely tight.

## Open questions for follow-on work

- Threshold constants for the evaluator: shortfall factor cutoff (3x? 2x?), unpaired-scope severity, ratio-anomaly cutoffs
- `benchmarks_us.py` citation sources: BLS OEWS 2024 + Chronicle salary survey + NIH stipend scale — pick canonical
- Test fixtures: at minimum one hand-crafted underfunded proposal + one clean control proposal; use `harness/` for scoring
- Nick coordination on `project.stated_total_usd` field name (#109 overlap)

## Session status

- Design locked (schema + few-shot). Docs saved. Ready to draft the lens `.md` and sketch the evaluator interface.
