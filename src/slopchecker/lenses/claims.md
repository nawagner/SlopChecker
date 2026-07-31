---
id: claims
issue: 13
version: 0.2
output: json
---

# Claims-extraction lens

## Purpose

Pull the load-bearing claims out of a proposal once, so downstream
features (cross-proposal similarity, the achievability read, the
claim-support citation check — see #13) reuse them instead of re-running
their own LLM passes. Extraction only: this lens never judges whether a
claim is true, achievable, or well-supported. Scoring belongs to other
lenses with domain context.

## System prompt

You are extracting the load-bearing claims from a funding proposal so a
program officer can review them. A claim is load-bearing if the funding
decision could change were it false. Ignore boilerplate, mission
statements, and generic aspiration.

The document text is provided with page markers of the form `[[page N]]`
preceding each page's text.

Extract every load-bearing claim of these types:

- `capability` — what will be built, developed, or proven
- `outcome` — what result or deliverable is promised
- `timeline` — when, how fast, or at what scale delivery is committed
- `prior-work` — what is asserted about existing literature, evidence,
  or the state of the art
- `impact` — what effect on the world or field is claimed, including the
  team's track record

Rules — all of them are hard constraints:

1. `quote` MUST be a verbatim, contiguous substring of the document
   text: no paraphrase, no ellipsis, no corrected typos, no smoothed
   punctuation. Quotes are mechanically verified against the source;
   a quote that does not match character-for-character is discarded
   and its claim is lost.
2. Prefer the shortest contiguous span that still carries the claim.
   One sentence may yield several claims of different types; each gets
   its own entry with its own span.
3. `page` is the number from the nearest preceding `[[page N]]` marker.
4. `quantitative` is true only when the claim commits to a specific
   number, percentage, multiplier, count, dollar amount, or timeframe
   expressed as a figure. Vague magnitude ("significant", "at scale")
   is false.
5. `citation` is the reference marker attached to the claim in the text
   (e.g. `[4]`), or null when the text attaches none. Never infer or
   invent a citation; if the sentence has no marker, the value is null.
6. `needs_source` is true only when the claim asserts something about
   the world outside the proposal — prior findings, statistics, the
   state of the art, third-party facts — that a careful reviewer would
   expect a citation for. The applicant's own commitments (their
   budget, deliverables, timeline, team, plans) are theirs to make:
   `needs_source` is false however many numbers they contain.
7. Do not assess truth, achievability, or quality. Extraction only.
8. Output exactly one JSON object matching the Output format section.
   No commentary, no markdown fences, no fields beyond the schema.

## Output format

One JSON object with a single `claims` array. Each claim:

```json
{
  "claims": [
    {
      "id": "CL1",
      "type": "capability | outcome | timeline | prior-work | impact",
      "page": 1,
      "quote": "verbatim contiguous substring of the document text",
      "quantitative": true,
      "citation": "[4]",
      "needs_source": true
    }
  ]
}
```

Field notes:

- `id` — `CL1`, `CL2`, ... in document order. Stable across runs on the
  same document because ordering follows the text.
- `citation` — string ref marker or `null`.
- `needs_source` — the lens's judgment call (rule 6). This moved INTO
  the LLM on 2026-07-31: the mechanical `quantitative && uncited` flag
  misfired constantly on budget lines and deliverable counts — an
  applicant's own $429,401 total is not a claim about the world that
  needs a footnote.
- No free-text fields. The quote is the claim's evidence; anything the
  reader needs beyond that lives in the renderer, not here.

### Mapping to `Finding` (#3 strawman)

The pipeline converts each **flagged** claim into a `Finding`
deterministically — no LLM involved in the mapping. A claim is flagged
when `quantitative && needs_source && citation == null` (an empirical
number with no source — the case #13's acceptance criterion is about).
A missing `needs_source` defaults to false: a misfire in this lane
costs more credibility than a miss. Unflagged claims produce **no
Finding** and never appear in the report: attributes like "is this
quantitative?" are descriptions, not checks, and encoding them as
pass/fail booleans painted every claim as a failure in the rendered
report. Silence for unflagged claims is the same policy claim_support
applies to its `supported` verdict.

| Finding field | From claim |
|---|---|
| `id` | `id` |
| `target` | `claim` |
| `label` | `Unsourced quantitative claim` |
| `anchor.page` | `page` |
| `anchor.quote` | `quote` (quotecheck-verified before it reaches the report) |
| `checks` | `quant_claim_sourced` = `false` (False *is* the flag — renders in the failing lane as `quant_claim_sourced: NO`) |

The document-level ledger still reports the full extraction: `claims`
counts every claim the lens returned; `claims_quant_unsourced` counts
the flagged subset.

## Example

### Input

```text
[[page 1]]
The information environment confronting democratic institutions has degraded at a pace that outstrips the capacity of existing civil-society infrastructure to respond. Recent scholarship demonstrates that coordinated inauthentic behavior now shifts measurable public-opinion outcomes in as little as seventy-two hours [1]. As Starbird and colleagues observe, “the velocity of synthetic narratives has rendered traditional fact-checking architectures functionally obsolete” [2]. Our initiative responds directly to this crisis.

[[page 2]]
Our approach leverages a holistic, multi-stakeholder framework designed to foster synergies across the information resilience landscape. By convening diverse voices and harnessing cutting-edge methodologies, we will unlock transformative capacity at the intersection of technology and civil society. The program builds on findings that prebunking interventions achieve durable attitudinal inoculation across all demographic cohorts [3], and that media-literacy training reduces susceptibility to manipulated content by up to 64 percent [4]. Independent assessments find that 78 percent of local newsrooms lack any dedicated verification staff.

Meridian will deliver twelve regional trainings, a 40-country monitoring network, a peer-reviewed evaluation study, and an open-source detection toolkit within the first grant year, at a total cost of $148,000.
```

### Output

```json
{
  "claims": [
    {
      "id": "CL1",
      "type": "prior-work",
      "page": 1,
      "quote": "coordinated inauthentic behavior now shifts measurable public-opinion outcomes in as little as seventy-two hours",
      "quantitative": true,
      "citation": "[1]",
      "needs_source": true
    },
    {
      "id": "CL2",
      "type": "prior-work",
      "page": 1,
      "quote": "“the velocity of synthetic narratives has rendered traditional fact-checking architectures functionally obsolete”",
      "quantitative": false,
      "citation": "[2]",
      "needs_source": true
    },
    {
      "id": "CL3",
      "type": "prior-work",
      "page": 2,
      "quote": "prebunking interventions achieve durable attitudinal inoculation across all demographic cohorts",
      "quantitative": false,
      "citation": "[3]",
      "needs_source": true
    },
    {
      "id": "CL4",
      "type": "prior-work",
      "page": 2,
      "quote": "media-literacy training reduces susceptibility to manipulated content by up to 64 percent",
      "quantitative": true,
      "citation": "[4]",
      "needs_source": true
    },
    {
      "id": "CL5",
      "type": "prior-work",
      "page": 2,
      "quote": "Independent assessments find that 78 percent of local newsrooms lack any dedicated verification staff.",
      "quantitative": true,
      "citation": null,
      "needs_source": true
    },
    {
      "id": "CL6",
      "type": "outcome",
      "page": 2,
      "quote": "Meridian will deliver twelve regional trainings, a 40-country monitoring network, a peer-reviewed evaluation study, and an open-source detection toolkit within the first grant year, at a total cost of $148,000.",
      "quantitative": true,
      "citation": null,
      "needs_source": false
    },
    {
      "id": "CL7",
      "type": "timeline",
      "page": 2,
      "quote": "within the first grant year",
      "quantitative": false,
      "citation": null,
      "needs_source": false
    }
  ]
}
```

Why the example looks like this (guidance for the model and for lens
authors — not part of the prompt payload):

- The vague framework sentence on page 2 ("holistic, multi-stakeholder
  framework...") yields no claim: aspiration, not load-bearing.
- CL5 is the demo case — an empirical statistic ("78 percent of local
  newsrooms") with no citation and `needs_source: true`. Downstream it
  is the only claim here that becomes a Finding ("Unsourced
  quantitative claim").
- CL6 shows the judgment that moved into the lens: a quantitative
  promise (twelve trainings, 40 countries, $148,000) with no citation —
  but it is the applicant's own commitment, so `needs_source` is false
  and it is NOT flagged. This exact line was the flag's worst misfire.
- CL6 and CL7 come from the same sentence: one `outcome` for the
  deliverables, one `timeline` for the delivery window, each with the
  smallest span that carries it.
- CL2 keeps the curly quotation marks exactly as they appear in the
  source — verbatim means verbatim.
