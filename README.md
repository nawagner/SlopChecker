# SlopChecker

An open-source utility for funding orgs to screen incoming proposals for
AI-generation signals, citation integrity, solicitation compliance, and
tagging. It reports evidence for a human reviewer — it never auto-rejects
anything.

Built by a five-person team at [Hacking the Think Tank](https://hackingthethinktank.com/)
(2026-07-31). Live demo: **[slop-checker.com](https://slop-checker.com)**.

## Quickstart

```bash
git clone https://github.com/nawagner/SlopChecker.git
cd SlopChecker
pip install -e ".[dev,pdf,docx]"
cp .env.example .env          # optional — every key is optional, see below
slopcheck run harness/fixtures/proposal_climate.md --tier deterministic
```

That runs the checks that need no API keys and no network, and writes
`slopcheck-reports/proposal_climate.report.json` (+ `.html` if you add
`--format json,html`). Add `--tier all` once you've filled in `.env` to
also run the API/LLM-backed checks.

```bash
slopcheck --help          # commands: run, render, config, version
slopcheck run --help      # --tier, --only/--skip, --format, --dry-run, --batch
slopcheck config          # shows which API keys are set, without printing them
```

`slopcheck render report.json --pdf` turns a `report.json` into the
paginated PDF evidence report — the actual shipping artifact; HTML is the
design-fidelity preview.

## Demo document

To see the tool actually working — for a demo, or a first real look at the
output — run it on this one:

```bash
slopcheck run tests/fixtures/synthetic/files/grant_application__fabricated_citations.docx \
  --format json,html
```

Nine DOIs, all nine correctly formatted, three of which do not exist:
`citation_identifiers_valid` passes 9/9 while `all_dois_resolve` fails with
3 not found. "Looks perfect, isn't real" in one screen, quote-anchored, with
no spurious findings alongside it. `.docx` is named above only because it's
the format a funder is most likely to hand you; see the table below.

**Any of the four formats works** — `.docx`, `.html`, `.md` and `.pdf` all
produce the same citation result on this document:

| format | `citation_identifiers_valid` | `all_dois_resolve` |
|---|---|---|
| `.docx` | true — 9/9 well-formed | false — 3/9 resolved, 3 not found |
| `.html` | true — 9/9 well-formed | false — 3/9 resolved, 3 not found |
| `.md` | true — 9/9 well-formed | false — 3/9 resolved, 3 not found |
| `.pdf` | true — 9/9 well-formed | false — 3/9 resolved, 3 not found |

Format parity is recent and was hard-won: PDF was fixed by #126 and Markdown
by #123, and before those the citation tier was dark on the format funders
actually upload. If you see `skipped — no reference list found in the
document` on a document that plainly has one, that's a regression in
reference-region detection, not a property of the file.

Three of the six remaining DOIs are real but return 403, so they render as
gray coverage-gap chips rather than failures — worth knowing before it's on a
screen. `metadata_match` is a coverage gap on every identifier, and the
Pangram score only appears if `PANGRAM_API_KEY` is set.

The proposals in `harness/fixtures/` (`proposal_climate.md`,
`proposal_edu.md`) read much more like real submissions, but every DOI in
them is a fabricated `10.9999/fake-*`, so even in a format that parses they
resolve 0/3 — no real-vs-invented contrast to point at. Scenario selection
is tracked on #25.

## API keys

Every key in `.env.example` is optional. A check whose key is missing
reports `skipped: missing <VAR>` instead of crashing the run — see
`slopcheck config` to check what's set.

## Data handling

Submissions are often unpublished and contain applicant data. What leaves your
machine, to whom, and what is retained is documented in
[PRIVACY.md](PRIVACY.md). Short version: the only checks that send your document
off-machine are the ones you supply keys for (Pangram) or that fetch cited
sources over the network; the whole deterministic tier runs locally.

## How it works

```mermaid
flowchart LR
    A["Proposal<br/>PDF / DOCX / MD / HTML"] --> B["ingest/<br/>normalize to text"]
    B --> C["FlattenedDoc"]
    C --> D["pipeline runner<br/>--tier deterministic | api | llm | all"]
    D --> D1["checks/<br/>deterministic<br/>(DOI, metadata, tagging)"]
    D --> D2["detect/<br/>api<br/>(Pangram)"]
    D --> D3["lenses/<br/>llm<br/>(claim extraction, ...)"]
    D1 --> E["EvidenceReport<br/>report.json"]
    D2 --> E
    D3 --> E
    E --> F["render/"]
    F --> G["HTML report"]
    F --> H["PDF report<br/>(shipping artifact)"]
```

Every check result feeding into `report.json` is `true | false | number`
plus a `skipped`/`errored` status — never free text, never a verdict. See
[`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) for the full contract.

## How it's organized

| Path | What it is |
|---|---|
| `src/slopchecker/pipeline/` | check registry, tiered runner, citation extraction |
| `src/slopchecker/lenses/` | LLM prompt packs (markdown, see [`lenses/README.md`](src/slopchecker/lenses/README.md)) |
| `src/slopchecker/detect/` | AI-detection providers (Pangram) |
| `src/slopchecker/checks/` | deterministic checks: DOI resolution, metadata, tagging |
| `src/slopchecker/report/` | evidence report rendering: HTML + PDF |
| `src/slopchecker/ingest/` | PDF/DOCX/MD/HTML → normalized `FlattenedDoc` |
| `worker/` | Cloudflare Worker: proxy, landing page, D1 report store |
| `harness/` | planted-defect validation, recall scoring |
| `fixtures/`, `tests/fixtures/` | fabricated test documents — never real applicant material (#22). The case library is `tests/fixtures/synthetic/` (18 cases x 4 formats, planted defects, `files_index.csv` is the ground truth) |

`report.json` is the contract between checks and the renderer — see
[`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) for the schema, a worked
example, and how to run the tests. Shared bulk data (corpora, fixtures too
big for git) lives in Cloudflare R2 — see
[`docs/data-storage.md`](docs/data-storage.md) for what's there and how to
get access. R2 is a file drop, not a case library: it holds one proposal
(`fixtures/proposal_climate.pdf`), the funder rubrics, and the UniMelb
dataset — test documents live in `tests/fixtures/synthetic/`. Reports can
additionally be stored in Cloudflare D1 to make
results queryable across submissions — see
[`docs/d1-database.md`](docs/d1-database.md).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) to get set up, and
[`CLAUDE.md`](CLAUDE.md) for the full set of team conventions (module
ownership, git discipline, design decisions already made).

## Team

Nick Wagner, Dan Parshall, Emerson Brooking, Alex, Dominique Ramsawak —
see `CLAUDE.md` for GitHub handles.
