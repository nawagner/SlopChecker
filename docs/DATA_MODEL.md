# DATA_MODEL.md — the report.json contract (#3)

`report.json` is the contract between checkers and the renderer. It is
defined once, as pydantic models, in `src/slopchecker/models.py`. This doc
is the human-readable mirror; if they disagree, the code wins — and please
open an issue comment on #3.

Naming: CLAUDE.md's names won over the issue-#3 strawman —
**`FlattenedDoc` / `Finding` / `EvidenceReport`** (aliases `Document` and
`Report` exist for code written against the issue text). The field layout
codifies the shape already shipped by the renderer (#35/#40); the reference
instance is `tests/fixtures/sample_report.json`, and
`EvidenceReport.to_report_dict()` emits exactly what
`report.html.render_report()` consumes.

Ground rules baked into the types:

- **Check results are `true | false | number` — never free text.** Strings
  are rejected at validation time, even `"true"`. Human framing lives in
  the renderer.
- **Findings are evidence, not verdicts.** No `is_ai_generated`-style
  fields. A detector score is a number in its own lane; the tool
  recommends `human_review`, it never auto-rejects.
- **A check that didn't run is first-class.** `status: skipped | errored`
  with a mandatory `reason` — never a silently missing result. This is how
  "degrade to gaps, never crash" shows up in the data.
- **Unknown fields are rejected** (`extra="forbid"`). A typo in a checker's
  output fails loudly instead of being silently dropped.

## Models

### `EvidenceReport` (alias `Report`) — the top level

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | `str` (default `"0.1"`) | Contract version; bump on breaking change |
| `document` | `FlattenedDoc` | The normalized document under review |
| `solicitation` | `str?` | Solicitation ID the proposal responds to |
| `run` | `RunInfo` | When/how long/which code/what cost |
| `findings` | `list[Finding]` | Quote-anchored evidence cards |
| `ledger` | `list[LedgerRow]` | Document-level all-checks table |
| `summary` | `Summary` | Recommendation (always advisory) |

Methods: `counts()` derives `passed/failed/scores/skipped/errored` tallies
from the ledger (never stored — Emerson's rule on #3). `to_report_dict()`
returns the JSON-ready dict the renderer takes.

### `FlattenedDoc` (alias `Document`)

| Field | Type | Meaning |
|---|---|---|
| `file` | `str` | Source filename |
| `text` | `str` | The single normalized text all anchors index into |
| `sha256` | `str?` | Hash of the source file |
| `pages` | `int?` | Page count |
| `page_offsets` | `list[int]?` | Char offset in `text` where each page starts (#4) |
| `media_type` | `str?` | Source type, e.g. `application/pdf` |
| `title`, `byline`, `submitter` | `str?` | Display metadata |

Section structure is deferred until a loader needs it.

### `Finding`

One quote-anchored piece of evidence. Rendered as an annotation card
beside the passage it refers to.

| Field | Type | Meaning |
|---|---|---|
| `id` | `str` | Short card ID (`C3`, `Q1`, `D1`) |
| `target` | `str?` | What it's about (`ref[3]`, `p2`) |
| `label` | `str?` | Card title; renderer falls back to `target`/`id` |
| `anchor` | `Anchor?` | Where in the document this points |
| `checks` | `list[CheckResult]` | The bool/number results |
| `verdict` | `Verdict?` | Closed enum for LLM claim-support judgments (#11) |
| `evidence` | `dict` | Raw supporting data — enough for a human to verify without re-running (resolved metadata, HTTP status, source excerpt, model + score details) |
| `note` | `str?` | One line max. Enforced. |

`Verdict` is `supported | overstated | unsupported | contradicted |
unverifiable`. `overstated` (source supports less than claimed) is
deliberately distinct from `unsupported` (no support) and `contradicted`
(source refutes); `unverifiable` (paywalled / not retrievable) never hides
inside `unsupported`.

### `Anchor` and `Span`

| Field | Type | Meaning |
|---|---|---|
| `Anchor.page` | `int?` (≥1) | Page the quote appears on |
| `Anchor.quote` | `str` | Verbatim excerpt from `document.text`; must be mechanically grounded (quotecheck) before it reaches the report |
| `Anchor.span` | `Span?` | Exact offsets, when the producer knows them |
| `Span.start`, `Span.end` | `int` (≥0) | Half-open char offsets `[start, end)` into `document.text`; `end ≥ start` enforced |

### `CheckResult` (inside `Finding.checks`)

| Field | Type | Meaning |
|---|---|---|
| `name` | `str` | Check name (`doi_resolves`, `pangram_span`) |
| `result` | `bool \| int \| float \| null` | The outcome. Strict — strings rejected |
| `status` | `"ok" \| "skipped" \| "errored"` | Whether the check actually ran |
| `reason` | `str?` | Required when status ≠ `ok` |

Consistency is enforced: `ok` requires a `result`; `skipped`/`errored`
require a `reason` and may not carry a `result`.

### `LedgerRow` (inside `EvidenceReport.ledger`)

Same status discipline as `CheckResult`.

| Field | Type | Meaning |
|---|---|---|
| `check` | `str` | Check name |
| `label` | `str?` | Human label for the table row |
| `result` | `bool \| int \| float \| null` | Outcome |
| `detail` | `str?` | Short context (`"3 / 4 — ref [3] not found"`) |
| `status` / `reason` | as above | First-class skipped/errored |

### `Check` — a check *definition*, not a result

Registry entry so the orchestrator can budget and gate.

| Field | Type | Meaning |
|---|---|---|
| `id` | `str` | Stable ID, matches `CheckResult.name` / `LedgerRow.check` |
| `name` | `str` | Human name |
| `tier` | `"deterministic" \| "api" \| "llm"` | The deterministic tier must run with no LLM at all |
| `est_cost_usd` | `float` (default 0) | Estimated cost per run |
| `needs_network` | `bool` (default false) | Skip offline |

### `RunInfo` and `Summary`

| Field | Type | Meaning |
|---|---|---|
| `RunInfo.date` | `str?` | Run date |
| `RunInfo.seconds` | `int \| float?` | Wall-clock duration |
| `RunInfo.version` | `str?` | slopchecker version that produced the report |
| `RunInfo.cost_usd` | `float?` | Actual spend |
| `Summary.recommendation` | `str` (default `"human_review"`) | Always advisory |

## Worked minimal example

A report with one finding (a citation whose DOI does not resolve), one
score row, and one check that could not run:

```json
{
  "schema_version": "0.1",
  "document": {
    "file": "proposal.pdf",
    "text": "Prebunking achieves durable inoculation [1].\n\n[1] Doe, J. (2025). doi:10.1/fabricated"
  },
  "run": { "date": "2026-07-31", "seconds": 12 },
  "findings": [
    {
      "id": "C1",
      "target": "ref[1]",
      "label": "Citation [1]",
      "anchor": { "page": 1, "quote": "Prebunking achieves durable inoculation" },
      "checks": [
        { "name": "doi_resolves", "result": false, "status": "ok" }
      ],
      "evidence": { "doi": "10.1/fabricated", "http_status": 404 },
      "note": "DOI does not resolve."
    }
  ],
  "ledger": [
    { "check": "all_dois_resolve", "label": "All DOIs resolve", "result": false, "detail": "0 / 1", "status": "ok" },
    { "check": "pangram_document", "label": "AI detection (Pangram)", "result": 0.96, "detail": "document score", "status": "ok" },
    { "check": "claim_support", "label": "Claims supported by sources", "status": "skipped", "reason": "ANTHROPIC_API_KEY not set" }
  ],
  "summary": { "recommendation": "human_review" }
}
```

Render it: `slopcheck render report.json` (add `--pdf` for the shipping
artifact). Producing one from models:

```python
from slopchecker.models import EvidenceReport, FlattenedDoc

report = EvidenceReport(document=FlattenedDoc(file="proposal.pdf", text="..."))
report_json = report.model_dump_json(exclude_none=True)      # to disk
report = EvidenceReport.model_validate_json(report_json)     # from disk
html_input = report.to_report_dict()                         # for report/html.py
```

## Running the tests

From the repo root (after `uv venv` + `uv pip install -e ".[dev]"`; add
`,web,pdf` extras to cover the web stub and PDF loaders):

```bash
uv run pytest                        # everything
uv run pytest tests/test_models.py   # just the data model
uv run pytest tests/test_models.py -k round_trip   # one shape of test
uv run ruff check .                  # lint (CI runs this too)
```

Which tests cover which modules:

| Test file | Covers |
|---|---|
| `tests/test_models.py` | `src/slopchecker/models.py` (this contract), incl. one wiring test through `report/html.py` |
| `tests/test_config.py` | `src/slopchecker/config.py` |
| `tests/test_web.py` | `src/slopchecker/web.py` |
| `tests/test_report_html.py` | `src/slopchecker/report/html.py` |
| `tests/test_report_pdf.py` | `src/slopchecker/report/pdf.py` (skips without a Chromium-family browser) |

House rule (CLAUDE.md): **agents run the tests they touched before opening
a PR.** If you change `models.py`, that means at minimum
`uv run pytest tests/test_models.py tests/test_report_html.py` — the
renderer consumes what these models emit. And changing a shared model =
comment on #3 first.
