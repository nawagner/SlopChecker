---
id: budget_feasibility
issue: 17
version: 0.1
output: json
---

# Budget-feasibility extraction lens

## Purpose

Extract the budget lines, the quantitative scope commitments, and the
pairings between them from a funding proposal so a downstream Python
evaluator can compare implied cost against US benchmarks and surface
underfunded lines, unfunded commitments, and unallocated spend.

Extraction and pairing only. This lens performs no arithmetic and
issues no judgment: it does not compute totals, ratios, shortfalls, or
feasibility verdicts. Bucketing free-text role titles into a closed
`role` enum is the only normalization the model does. Everything else
(salary benchmarks, shortfall factors, pairing ratios, unpaired
derivations, sum checks) is Python's job in
`pipeline/budget_feasibility/`.

## System prompt

You are extracting the budget lines, the quantitative scope
commitments, and the pairings between them from a funding proposal so
a program officer can review whether the money adds up to the
promises.

The document text is provided with page markers of the form
`[[page N]]` preceding each page's text.

Extract three kinds of items:

- `personnel_lines` — line items whose dollar amount is spent on
  people (salaries, wages, stipends, fringe). One entry per
  distinguishable line the proposal calls out (a single "total
  personnel" line is one entry; separate PI / postdoc / student lines
  are separate entries).
- `non_personnel_lines` — every other budget line item (equipment,
  travel, supplies, indirect / overhead / F&A, subcontracts, other).
- `scope_commitments` — deliverables the proposal promises in
  countable terms: number of trainings, number of countries covered,
  number of studies published, number of tools shipped. A commitment
  without a number (e.g. "we will foster engagement") is not a scope
  commitment and MUST be skipped — the evaluator downstream can only
  reason about quantifiable promises.

Then emit `pairings` linking scope commitments to the budget lines
that fund them. Pairings are many-to-many: one commitment may be paid
for by several lines (postdocs + travel funds the same training
series), and one budget line may cover several commitments (the same
postdocs cover trainings AND country monitoring).

Rules — all of them are hard constraints:

1. `quote` MUST be a verbatim, contiguous substring of the document
   text: no paraphrase, no ellipsis, no corrected typos, no smoothed
   punctuation, no rejoined line-broken words. Quotes are mechanically
   verified against the source; a quote that does not match
   character-for-character is discarded and the item is lost.
2. Prefer the shortest contiguous span that anchors the item — for a
   budget line, the span containing the dollar amount; for a scope
   commitment, the span containing the number and the unit.
3. `page` is the number from the nearest preceding `[[page N]]`
   marker.
4. `role` bucketizes each free-text personnel title into ONE of this
   closed enum, no other values: `pi | co_pi | senior_scientist |
   postdoc | grad_student | research_assistant | admin | technician |
   consultant | other`. Choose `other` when no bucket fits; do not
   invent new roles.
5. Do NO arithmetic. Do not sum line items, do not compute ratios,
   do not compare stated amounts to any benchmark, do not flag
   anything as high or low. Extract only what the document says.
6. Nullable fields the model must NOT invent when the document does
   not state them: `period_yrs`, `timeframe_yrs`, `fte_fraction`,
   `fringe_rate`, `indirect_rate`, `project.stated_total_usd`,
   `project.duration_yrs`. If the value is not on the page, emit
   `null`. Never guess a period from context; never back-out a fringe
   rate from arithmetic.
7. `pairings` are only emitted when the document's text plausibly
   supports the pair — the same sentence or the same paragraph names
   both the commitment and the funding source, or the budget line
   itself describes what it funds ("Travel: $18,000 for regional
   training delivery"). Do not speculate. Missed pairings are cheap
   for the evaluator to surface as unpaired; invented pairings
   silently hide unfunded commitments.
8. `unpaired_scope` and `unpaired_budget` are NOT model output — the
   evaluator derives them from the ids you emit. Do not include them.
9. Output exactly one JSON object matching the Output format section.
   No commentary, no markdown fences, no fields beyond the schema.

## Output format

One JSON object with `project`, `personnel_lines`, `non_personnel_lines`,
`scope_commitments`, and `pairings` fields:

```json
{
  "project": {
    "stated_total_usd": 148000,
    "duration_yrs": 1
  },
  "personnel_lines": [
    {
      "id": "PL1",
      "page": 2,
      "quote": "verbatim contiguous substring of the document text",
      "amount_usd": 40000,
      "period_yrs": 1,
      "fringe_rate": 0.28,
      "indirect_rate": null,
      "roles_named": [
        {"role": "pi", "count": 1, "fte_fraction": 0.25},
        {"role": "postdoc", "count": 2, "fte_fraction": 1.0}
      ]
    }
  ],
  "non_personnel_lines": [
    {
      "id": "NL1",
      "page": 2,
      "quote": "verbatim contiguous substring of the document text",
      "amount_usd": 12000,
      "category": "equipment"
    }
  ],
  "scope_commitments": [
    {
      "id": "SC1",
      "page": 1,
      "quote": "verbatim contiguous substring of the document text",
      "quantity": 12,
      "unit": "training",
      "timeframe_yrs": 1
    }
  ],
  "pairings": [
    {"scope_id": "SC1", "budget_id": "PL1"}
  ]
}
```

Field notes:

- `id` — `PL1`, `PL2`, ... for personnel lines, `NL1`, `NL2`, ... for
  non-personnel lines, `SC1`, `SC2`, ... for scope commitments, in
  document order. Stable across runs on the same document.
- `personnel_lines[].roles_named` — one entry per distinguishable
  role the line covers; `fte_fraction` is 0.25 for "25% effort", 1.0
  for "full time"; `count` is the number of people at that role and
  effort level. Empty list when the line does not name roles.
- `non_personnel_lines[].category` — one of `equipment | travel |
  supplies | indirect | subcontract | other`. `indirect` covers
  overhead, F&A, and NICRA-based indirects.
- `scope_commitments[].quantity` — integer or float count of the
  countable unit. A commitment with no explicit count is not a scope
  commitment and MUST be skipped (per rule from the System prompt).
- `scope_commitments[].unit` — free noun singular ("country",
  "training", "study", "toolkit"). No enum here — units follow the
  domain.
- `pairings[].scope_id` and `pairings[].budget_id` — cross-reference
  the ids above. `budget_id` may reference either a personnel or a
  non-personnel line.
- No free-text fields. `quote` is the item's evidence; anything the
  reader needs beyond that lives in the renderer or the evaluator,
  not here.

### Mapping to `Finding` (#3 strawman)

The pipeline runs the lens output through the evaluator in
`pipeline/budget_feasibility/evaluate.py`. The evaluator — not the
lens — emits `Finding` records with the benchmark assumption printed
in `evidence`:

| Finding.check | Source in lens output | Result type |
|---|---|---|
| `personnel_underfunded` | per personnel_line | `bool` — true when `amount_usd < expected_p20 / threshold` (default 3.0) |
| `pairing_ratio_usd_per_unit` | per scope-to-budget pairing | `float` — `sum(paired_amounts) / quantity` |
| `unfunded_quantitative_commitment` | per unpaired scope with `quantity > 0` | `bool` — always true when emitted |
| `unallocated_budget_line` | per unpaired budget line | `bool` — always true when emitted |
| `sum_of_lines_matches_stated_total` | project-level | `bool` — only emitted when `project.stated_total_usd` is not null |

Every `Finding.evidence` for a benchmark-derived check carries the
assumption used (`amount_expected_p20_usd`, `assumed_bands_usd`,
`assumed_fringe_rate`, `benchmark_source`, `flagged_because`) so the
reviewer can inspect the reasoning and override.

## Example

### Input

```text
[[page 1]]
The Meridian Institute proposes a coordinated response to the accelerating erosion of information integrity. Our program will deliver twelve regional trainings, a 40-country monitoring network, a peer-reviewed evaluation study, and an open-source detection toolkit within the first grant year, at a total cost of $148,000.

[[page 2]]
Personnel. Dr. Alina Vasquez (PI, 25% effort, 12 months) will oversee program design and stakeholder engagement. Two postdoctoral researchers (100% effort, 12 months each) will conduct the trainings and lead the country-monitoring rollout. Total personnel: $40,000, inclusive of a fringe benefits rate of 28%.

Equipment: $12,000 for laptop and secure-comms procurement.
Travel: $18,000 for regional training delivery across six US regions.
Indirect costs: $78,000, calculated at 55% of modified total direct costs per the Meridian NICRA agreement.
```

### Output

```json
{
  "project": {
    "stated_total_usd": 148000,
    "duration_yrs": 1
  },
  "personnel_lines": [
    {
      "id": "PL1",
      "page": 2,
      "quote": "Total personnel: $40,000, inclusive of a fringe benefits rate of 28%.",
      "amount_usd": 40000,
      "period_yrs": 1,
      "fringe_rate": 0.28,
      "indirect_rate": null,
      "roles_named": [
        {"role": "pi", "count": 1, "fte_fraction": 0.25},
        {"role": "postdoc", "count": 2, "fte_fraction": 1.0}
      ]
    }
  ],
  "non_personnel_lines": [
    {
      "id": "NL1",
      "page": 2,
      "quote": "Equipment: $12,000 for laptop and secure-comms procurement.",
      "amount_usd": 12000,
      "category": "equipment"
    },
    {
      "id": "NL2",
      "page": 2,
      "quote": "Travel: $18,000 for regional training delivery across six US regions.",
      "amount_usd": 18000,
      "category": "travel"
    },
    {
      "id": "NL3",
      "page": 2,
      "quote": "Indirect costs: $78,000, calculated at 55% of modified total direct costs per the Meridian NICRA agreement.",
      "amount_usd": 78000,
      "category": "indirect"
    }
  ],
  "scope_commitments": [
    {
      "id": "SC1",
      "page": 1,
      "quote": "twelve regional trainings",
      "quantity": 12,
      "unit": "training",
      "timeframe_yrs": 1
    },
    {
      "id": "SC2",
      "page": 1,
      "quote": "a 40-country monitoring network",
      "quantity": 40,
      "unit": "country",
      "timeframe_yrs": 1
    },
    {
      "id": "SC3",
      "page": 1,
      "quote": "a peer-reviewed evaluation study",
      "quantity": 1,
      "unit": "study",
      "timeframe_yrs": 1
    },
    {
      "id": "SC4",
      "page": 1,
      "quote": "an open-source detection toolkit",
      "quantity": 1,
      "unit": "toolkit",
      "timeframe_yrs": 1
    }
  ],
  "pairings": [
    {"scope_id": "SC1", "budget_id": "PL1"},
    {"scope_id": "SC1", "budget_id": "NL2"},
    {"scope_id": "SC2", "budget_id": "PL1"}
  ]
}
```

Why the example looks like this (guidance for the model and for lens
authors — not part of the prompt payload):

- The `roles_named` for PL1 comes from *two* earlier sentences ("Dr.
  Alina Vasquez (PI, 25% effort, 12 months)" and "Two postdoctoral
  researchers (100% effort, 12 months each)") rolled into the single
  "Total personnel: $40,000" line — the model must bucketize the
  free-text titles into the `role` enum without inventing a role
  name.
- `period_yrs: 1` for PL1 comes from "12 months" (converted to years,
  the only numeric normalization the model does). `duration_yrs: 1`
  for the project comes from "the first grant year".
- `indirect_rate` is `null` on PL1 because the text does not attach
  an indirect rate to the personnel line itself; the 55% NICRA rate
  is captured on NL3 via `category: "indirect"` instead. The
  evaluator looks in both places (per the design convo's decision).
- Only three pairings are emitted, even though the document has four
  scope commitments and four budget lines. SC3 (evaluation study) and
  SC4 (toolkit) have no explicit funding source in the text — the
  evaluator surfaces them as `unfunded_quantitative_commitment`.
  Equipment (NL1) and indirect (NL3) have no explicit deliverable
  attached — the evaluator surfaces them as `unallocated_budget_line`.
  Guessing pairings ("indirects fund overhead which funds everything")
  would silently hide the gap.
- SC1 (trainings) pairs to *both* PL1 (the postdocs "conduct the
  trainings") and NL2 (travel "for regional training delivery").
  Many-to-many pairings are the whole point.
- The planted defect the evaluator will catch: PL1's `$40,000` covers
  2.25 FTE-yr of personnel (0.25 PI + 2.0 postdocs). At the US p20
  bands ($95K PI, $52K postdoc) × 1.28 fringe, that is
  ~$163,840 expected — a shortfall factor of ~4.1 against p20, well
  above the 3.0 default threshold. `personnel_underfunded: true`
  fires on PL1, with the assumption printed in evidence.
