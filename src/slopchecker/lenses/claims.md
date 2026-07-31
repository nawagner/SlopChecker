---
id: claims
issue: 13
version: 0.3
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

You are extracting the load-bearing claims from a submitted document so
a program officer can review them. A claim is load-bearing if the
decision the document argues for could change were the claim false —
and it must be **specific enough to check**: it commits to a particular
finding, capability, deliverable, quantity, actor, or result that a
reviewer could in principle verify, look up, or hold the author to
later. If nothing in a sentence could be verified or falsified, it is
not a claim, however assertive its wording.

Never extract, no matter how confident it sounds:

- **Meta-discourse** — sentences whose subject is the document itself,
  its sections, or its intent: "This piece examines...", "The takeaways
  are meant to inform, not to prescribe.", "The discussion draws on
  established methods and current data." That is signposting, not a
  claim about the world.
- **Vague gestures at evidence** — sentences that invoke "analysis",
  "research", "data", or "methods" without stating what they show:
  "Recent analysis points toward a tractable path forward" asserts
  nothing checkable.
- **Boilerplate, mission statements, and generic aspiration.**

Every extracted claim is classified by `scope`:

- `background` — a broad, context-setting generalization a reasonable
  reviewer would not demand a citation for: "The information
  environment has degraded rapidly in recent years." It does real
  argumentative work (that is why it is extracted at all), but it
  frames the problem rather than borrowing evidential authority.
- `specific` — a narrow assertion that commits to a particular
  finding, quantity, outcome, timeline, attributed result, or definite
  state of the world. Uncited specific claims are exactly what the
  reviewer needs surfaced.

Do NOT confuse vagueness with hyperbole. A sentence that commits to a
definite, extreme state of the world is a `specific` claim, and an
important one: "Every serious observer already agrees; the matter is
entirely settled" (prior-work — asserts universal consensus), "These
findings will transform policy overnight, guaranteed" (impact —
asserts a guaranteed outcome). Universal and guaranteed assertions are
checkable precisely because a single counterexample falsifies them.
The test is whether the sentence commits to anything, not how measured
it sounds.

Many documents — especially thin commentary — contain no load-bearing
claims at all. `{"claims": []}` is a correct and expected output; do
not lower the bar in order to return something.

The document text is provided with page markers of the form `[[page N]]`
preceding each page's text.

Extract every load-bearing claim of these types:

- `capability` — what will be built, developed, or proven
- `outcome` — what result or deliverable is promised
- `timeline` — when, how fast, or at what scale delivery is committed
- `prior-work` — a specific finding, effect, or result attributed to
  existing literature, evidence, or the state of the art. Merely
  mentioning that research, methods, or data exist is not a
  prior-work claim
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
5b. `scope` is `"background"` or `"specific"` per the definitions
   above. When genuinely torn, ask: is this sentence borrowing the
   authority of evidence ("studies show", a named effect, a promised
   deliverable)? Then `specific`. Is it framing shared context? Then
   `background`.
6. Do not assess truth, achievability, or quality. Extraction only.
7. Output exactly one JSON object matching the Output format section.
   No commentary, no markdown fences, no fields beyond the schema.

## Output format

One JSON object with a single `claims` array. Each claim:

```json
{
  "claims": [
    {
      "id": "CL1",
      "type": "capability | outcome | timeline | prior-work | impact",
      "scope": "background | specific",
      "page": 1,
      "quote": "verbatim contiguous substring of the document text",
      "quantitative": true,
      "citation": "[4]"
    }
  ]
}
```

Field notes:

- `id` — `CL1`, `CL2`, ... in document order. Stable across runs on the
  same document because ordering follows the text.
- `citation` — string ref marker or `null`.
- No free-text fields. The quote is the claim's evidence; anything the
  reader needs beyond that lives in the renderer, not here.

### Mapping to `Finding` (#3 strawman)

The pipeline converts each **flagged** claim into a `Finding`
deterministically — no LLM involved in the mapping. A claim is flagged
when it is uncited AND `specific` AND *needs a source* — i.e.
`type == "prior-work"` (asserting facts about literature or the world)
or `quantitative` (a figure borrowed from nowhere, the #13 acceptance
criterion and #147's case). Uncited *promises* (outcome / timeline /
capability commitments that aren't quantitative) are not flagged — an
applicant cannot cite their own future work; achievability review is a
different lens. Unflagged claims — background context-setters, cited
claims, plain promises — produce **no Finding** and never appear in
the report: attributes like "is this quantitative?" are descriptions,
not checks, and encoding them as pass/fail booleans painted every
claim as a failure in the rendered report (#147). Silence for
unflagged claims is the same policy claim_support applies to its
`supported` verdict.

| Finding field | From claim |
|---|---|
| `id` | `id` |
| `target` | `claim` |
| `label` | `Unsourced quantitative claim` when `quantitative`, else `Uncited prior-work claim` |
| `anchor.page` | `page` |
| `anchor.quote` | `quote` (quotecheck-verified before it reaches the report) |
| `checks` | `claim_sourced` = `false` (False *is* the flag — renders in the failing lane as `claim_sourced: NO`) |
| `evidence` | `type`, `scope`, `quantitative` (descriptive properties live here, where a False can never render as a failed check) |

The document-level ledger still reports the full extraction: `claims`
counts every claim the lens returned; `claims_quant_unsourced` counts
the unsourced-quantitative subset (#13's acceptance criterion);
`claims_specific_uncited` counts all flagged claims (#144's
generalization). A missing `scope` degrades to `specific` — fail
visible, not silent.

## Example

### Input

```text
[[page 1]]
The information environment confronting democratic institutions has degraded at a pace that outstrips the capacity of existing civil-society infrastructure to respond. Recent scholarship demonstrates that coordinated inauthentic behavior now shifts measurable public-opinion outcomes in as little as seventy-two hours [1]. As Starbird and colleagues observe, “the velocity of synthetic narratives has rendered traditional fact-checking architectures functionally obsolete” [2]. Our initiative responds directly to this crisis.

[[page 2]]
This proposal examines the crisis and charts our response; its conclusions are meant to inform rather than prescribe, and the discussion draws on established methods and current data. Our approach leverages a holistic, multi-stakeholder framework designed to foster synergies across the information resilience landscape. By convening diverse voices and harnessing cutting-edge methodologies, we will unlock transformative capacity at the intersection of technology and civil society. The program builds on findings that prebunking interventions achieve durable attitudinal inoculation across all demographic cohorts [3], and that media-literacy training reduces susceptibility to manipulated content by up to 64 percent [4].

Meridian will deliver twelve regional trainings, a 40-country monitoring network, a peer-reviewed evaluation study, and an open-source detection toolkit within the first grant year, at a total cost of $148,000.
```

### Output

```json
{
  "claims": [
    {
      "id": "CL1",
      "type": "prior-work",
      "scope": "background",
      "page": 1,
      "quote": "The information environment confronting democratic institutions has degraded at a pace that outstrips the capacity of existing civil-society infrastructure to respond.",
      "quantitative": false,
      "citation": null
    },
    {
      "id": "CL2",
      "type": "prior-work",
      "scope": "specific",
      "page": 1,
      "quote": "coordinated inauthentic behavior now shifts measurable public-opinion outcomes in as little as seventy-two hours",
      "quantitative": true,
      "citation": "[1]"
    },
    {
      "id": "CL3",
      "type": "prior-work",
      "scope": "specific",
      "page": 1,
      "quote": "“the velocity of synthetic narratives has rendered traditional fact-checking architectures functionally obsolete”",
      "quantitative": false,
      "citation": "[2]"
    },
    {
      "id": "CL4",
      "type": "prior-work",
      "scope": "specific",
      "page": 2,
      "quote": "prebunking interventions achieve durable attitudinal inoculation across all demographic cohorts",
      "quantitative": false,
      "citation": "[3]"
    },
    {
      "id": "CL5",
      "type": "prior-work",
      "scope": "specific",
      "page": 2,
      "quote": "media-literacy training reduces susceptibility to manipulated content by up to 64 percent",
      "quantitative": true,
      "citation": "[4]"
    },
    {
      "id": "CL6",
      "type": "outcome",
      "scope": "specific",
      "page": 2,
      "quote": "Meridian will deliver twelve regional trainings, a 40-country monitoring network, a peer-reviewed evaluation study, and an open-source detection toolkit within the first grant year, at a total cost of $148,000.",
      "quantitative": true,
      "citation": null
    },
    {
      "id": "CL7",
      "type": "timeline",
      "scope": "specific",
      "page": 2,
      "quote": "within the first grant year",
      "quantitative": false,
      "citation": null
    }
  ]
}
```

Why the example looks like this (guidance for the model and for lens
authors — not part of the prompt payload):

- The vague framework sentence on page 2 ("holistic, multi-stakeholder
  framework...") yields no claim: aspiration, not load-bearing.
- The opening sentence of page 2 ("This proposal examines... draws on
  established methods and current data") yields no claim either — it is
  meta-discourse about the document, and its gesture at "methods and
  data" states nothing checkable. This is the #144 failure mode: v0.1
  extracted exactly this kind of sentence as `prior-work`.
- CL1 is the `background` case: the degraded-environment sentence sets
  up the whole argument (load-bearing), but it is a broad framing
  generalization a reviewer would not demand a citation for. Extracted,
  tagged background, rendered as neutral context.
- CL6 is the demo case — a quantitative promise (twelve trainings,
  40 countries, $148,000) with no citation. `citation` stays null;
  nothing is invented. Downstream this is the only claim here that
  becomes a Finding ("Unsourced quantitative claim").
- CL7 is specific and uncited but becomes no Finding: a non-quantitative
  timeline promise doesn't need a source — only prior-work and
  quantitative claims borrow evidential authority.
- CL6 and CL7 come from the same sentence: one `outcome` for the
  deliverables, one `timeline` for the delivery window, each with the
  smallest span that carries it.
- CL3 keeps the curly quotation marks exactly as they appear in the
  source — verbatim means verbatim.
