# Structured background lookups — Implementation Plan

**Goal:** For a submitted proposal, look up the applicant organization and
named personnel in a fixed set of public registries (ProPublica Nonprofit
Explorer, OpenAlex, ORCID) and produce a structured, source-linked
`BackgroundReport` — no LLM required.

**Originating conversation:** [docs/active/18-background-report/convos/20260731_split_structured_vs_openweb.md](../convos/20260731_split_structured_vs_openweb.md)

**Context:** [#18](https://github.com/nawagner/SlopChecker/issues/18)
bundles structured lookups with an optional open-web pass. The structured
half is deterministic-tier work: typed API wrappers, mechanical entity
matching, explicit "not found" as a first-class outcome. Doing it as
plain code (not through an agent) preserves auditability — every finding
traces to a specific API call — and lets us enforce common-name
disambiguation as a code-level invariant rather than a system-prompt
promise.

**Confidence:** High for the module skeleton, contract, and ProPublica /
OpenAlex clients (those APIs are stable and well-documented). Moderate on
entity extraction from arbitrary proposal prose — rules-first with an
LLM fallback should get us far enough for the demo.

**Architecture:** New `src/slopchecker/background/structured/` subpackage.
Each source is a small client behind a common `RegistryLookup` Protocol
so they can be tested and skipped independently. Entity extraction from
`FlattenedDoc` is its own module; the runner calls extraction once and
fans each entity out to each lookup. Findings and coverage gaps go into
a `BackgroundReport` object living on `models.py`. Registered as a
deterministic-tier check so it appears in `slopcheck run` when the
relevant checks aren't skipped.

**Branch:** create a fresh branch, e.g. `<handle>/18-structured-lookups`,
off the current `origin/main`. Do **not** stack on
`danparshall/18-background-report` — that branch will hold only the
open-web lane. The plan doc referenced above lives there; the fresh
branch can read it via the GitHub URL rather than needing to rebase.

**Tech Stack:** Python 3.11+, `httpx` (already a transitive dep via
`fastapi`/existing checks; confirm before adding), `pydantic` for the
shape (already used across `models.py`), `pytest` with `pytest-recording`
or `vcrpy` for cassette-based integration tests. **No** LLM dependency
required for MVP (see "What could change" on entity extraction).

---

## Testing plan

The whole module must be exercisable without a network connection so CI
stays fast and offline-safe. Two layers:

- **Cassette-based integration tests** per client (`test_propublica.py`,
  `test_openalex.py`, `test_orcid.py`). Recorded once with real API
  responses, replayed on every CI run. Each cassette lives in
  `tests/cassettes/background/`.
- **Unit tests** on the module surface — entity extraction, `NotFound`
  vs "did not check" distinction, common-name disambiguation,
  `BackgroundReport` aggregation, degrade-to-gaps behavior when a client
  raises.

Behavior to cover (not exhaustive — the implementer should add more as
they build):

- Given a proposal that names "Institute for X" as the applicant org,
  the module returns a `BackgroundFinding` with `source_url` pointing
  at the specific ProPublica record and `confidence="verified"` when
  ProPublica returns a single hit.
- Given "Jane Smith, Harvard" cited in the proposal, and OpenAlex
  returning two authors named Jane Smith (one at Harvard, one at
  Oxford), the module attaches only the Harvard record to the finding
  and produces a `Gap` (not an unverified finding) for the Oxford
  match.
- Given a nonexistent org, the module emits a `NotFound` finding, not
  silence. The test asserts on `NotFound`, not on absence of a finding.
- Given a network error on ProPublica (503, timeout), the module emits
  a coverage gap and continues; the OpenAlex lookup still runs.
- Given `--tier deterministic` and no keys required, the check runs.
  Given no network at all, the check emits gaps for every registry and
  the run does not error.
- Given an entity extraction that returns zero entities from a proposal
  (e.g. a blog post), the check ledger row is `skipped: no entities
  extracted`, distinct from "checked and found nothing."

NOTE: I will write *all* tests before I add any implementation behavior.

---

## Steps

### Phase 0 — Shared shape (do first, coordinate on #3)

- [ ] Read `src/slopchecker/models.py` and `docs/DATA_MODEL.md` end to
      end. Understand `FlattenedDoc`, `Finding`, `LedgerRow`,
      `EvidenceReport`.
- [ ] Draft the `BackgroundReport` / `BackgroundFinding` / `Entity` /
      `Gap` types as an addition to `models.py`. Types only, no logic.
- [ ] Post the draft as a comment on [#3](https://github.com/nawagner/SlopChecker/issues/3)
      before adding it, per CLAUDE.md's "change a shared model, comment
      on #3 first" rule. Wait for a thumbs-up (or an hour of no
      objection) before proceeding.
- [ ] Write pytest for the new types (round-trip JSON via pydantic;
      `confidence` must be one of the three literals; `source_url`
      required on every `BackgroundFinding`).
- [ ] Land the types + tests as their own PR, small and mergeable
      independently of the rest. This unblocks the open-web lane too.

### Phase 1 — Module skeleton and entity extraction

- [ ] Create `src/slopchecker/background/__init__.py` and
      `src/slopchecker/background/structured/__init__.py`.
- [ ] Define `class RegistryLookup(Protocol)` in
      `background/structured/base.py` — one method `lookup(entity: Entity)
      -> list[BackgroundFinding | NotFound | Gap]`. Every client
      implements this.
- [ ] Write failing tests for `extract_entities(doc: FlattenedDoc) ->
      list[Entity]` — one test per rule (org name near "submitted by" /
      "applicant" header; PI listed in a "Personnel" or "Team" section;
      email domain corroborates org). Cover a proposal fixture from
      `tests/fixtures/synthetic/`.
- [ ] Implement `extract_entities` as a rules-based first pass. Use
      section headers already extracted by `ingest/` where possible.
      LLM fallback is a follow-up ticket, not this PR.
- [ ] Run the tests; confirm green.

### Phase 2 — ProPublica Nonprofit Explorer client

- [ ] Read the ProPublica Nonprofits API docs
      (<https://projects.propublica.org/nonprofits/api>). No auth
      required. Note the search endpoint, the org detail endpoint, the
      filings endpoint.
- [ ] Write failing tests using recorded cassettes: happy-path org
      lookup, ambiguous-name lookup, no-such-org.
- [ ] Implement `background/structured/propublica.py` — `class
      ProPublicaLookup` conforming to `RegistryLookup`. Emits
      `BackgroundFinding(source_url="https://projects.propublica.org/nonprofits/organizations/<EIN>",
      ...)` on hit, `NotFound` on empty search, `Gap` on HTTP error.
- [ ] Confirm the `confidence` value is set correctly: `verified` only
      when a single hit matches, `probable` when name and one
      corroborating field match, otherwise emit multiple `Gap`s (never a
      silent single-match commit).
- [ ] Register nothing in the pipeline yet; the client is tested in
      isolation this phase.

### Phase 3 — OpenAlex + ORCID clients

- [ ] Read OpenAlex API docs (<https://docs.openalex.org>). Note the
      `authors` endpoint and its affiliation filter.
- [ ] Write failing tests: named author + affiliation match returns one
      finding; named author + affiliation mismatch returns a Gap for
      each ambiguous match, not a silent commit; common-name
      disambiguation ("Jane Smith" with no affiliation → Gap for each
      candidate).
- [ ] Implement `background/structured/openalex.py`.
- [ ] Repeat for `background/structured/orcid.py` (ORCID Public API,
      no auth required; <https://info.orcid.org/documentation/api-tutorials/api-tutorial-searching-the-orcid-registry>).
      Same affiliation-corroboration rule.
- [ ] Cross-client dedup: if OpenAlex and ORCID both attach to the same
      person, coalesce into one `BackgroundFinding` with both source
      URLs in a `secondary_sources` field. Test this.

### Phase 4 — Runner and registered check

- [ ] Write failing test for the top-level runner
      `run_structured_background(doc: FlattenedDoc, clients:
      list[RegistryLookup]) -> BackgroundReport`. Verify: every
      extracted entity is asked of every client; failures degrade to
      gaps; the aggregate report has the expected shape.
- [ ] Implement the runner.
- [ ] Write failing test for a registered check
      `structured_background_report` in
      `src/slopchecker/checks/background.py` (Nick's package — flag on
      [#8](https://github.com/nawagner/SlopChecker/issues/8) or the
      relevant follow-up before committing there, per CLAUDE.md module
      ownership).
- [ ] Implement the check. It emits ledger rows (one per client per
      entity: `bool` for "hit / not-found", `int` for "n candidates")
      plus the full `BackgroundReport` on `EvidenceReport.background`
      (new optional field on the model, added in Phase 0).
- [ ] End-to-end: `slopcheck run tests/fixtures/synthetic/files/proposal_climate.md`
      returns a report with the background block populated (against
      real APIs during development; against cassettes in CI).

### Phase 5 — Renderer and demo

- [ ] Check with Emerson/Dominique (renderer owners) before touching
      `report/` — the mock at `mockups/evidence-report-mock.html`
      predates this feature. Options: add a "Background" section to
      the HTML report; ship the JSON only and let the renderer catch
      up on a follow-up ticket.
- [ ] If adding the section: one card per entity, showing each finding
      with a clickable `source_url`, and explicit "Not found in
      <registry>" rows for `NotFound` results (visible-by-default per
      #19's principle).
- [ ] Confirm the report carries an "unverified machine-generated
      research — reviewer must check every source link" banner when
      any background finding is present.

### Phase 6 — Ship

- [ ] Run the full test suite. All green.
- [ ] `ruff check` and `ruff format --check` clean.
- [ ] `mypy` clean on the new module (existing convention in this
      repo).
- [ ] Update `PRIVACY.md`: add rows for ProPublica, OpenAlex, ORCID in
      the "What each check sends" table. All three are "cited
      identifiers / entity names" — never the submission body.
- [ ] Write the `ai-log/<date>-<handle>-18-structured-lookups.md`
      session log per CLAUDE.md.
- [ ] Rebase on origin/main, open PR titled
      `#18 Structured background lookups (ProPublica, OpenAlex, ORCID)`.
      Reference this plan doc in the PR body. Post a comment on #18
      that structured lane is up for review.
- [ ] Do not close #18 — the open-web lane is a separate PR.

---

**Testing Details** Cassette-based integration tests per client (so CI
runs offline) plus unit tests for entity extraction, common-name
disambiguation, degrade-to-gaps, and the runner. Every test asserts on
observable behavior — `NotFound` emitted vs suppressed, correct
`source_url`, correct `confidence` — never on internal implementation
details or on mock call signatures. The one hard test: an ambiguous
common-name lookup must produce `Gap`s not a `BackgroundFinding`,
because that's the invariant that keeps us from libel.

**Implementation Details**

- New subpackage: `src/slopchecker/background/structured/`.
- Shared shape added to `src/slopchecker/models.py` in Phase 0, posted
  as a comment on #3 before merging.
- Registered check under `src/slopchecker/checks/` (Nick's module —
  flag first).
- `httpx` for HTTP, `pytest-recording` or `vcrpy` for cassettes.
- No LLM required for MVP; entity extraction is rules-first.
- Degrade to gaps on every HTTP error; never let a lookup failure abort
  the run.
- `NotFound` is a first-class type distinct from `Gap` distinct from
  absence-of-finding.
- Every `BackgroundFinding` requires a `source_url`; enforced by the
  pydantic model.
- Common-name disambiguation is a code-level invariant: no
  `BackgroundFinding` with `confidence="verified"` unless
  `entity.affiliation` corroborated.
- Cross-client dedup coalesces OpenAlex + ORCID into a single finding
  with `secondary_sources` populated.

**What could change**

- **Entity extraction quality.** Rules-first may be too brittle on real
  proposals (as opposed to synthetic fixtures). If the demo shows this
  failing, an LLM-based extractor (single call to `AnthropicClient`,
  reusing `pipeline/lens_runtime.py` machinery) is the natural
  follow-up — file it as a new ticket rather than growing this PR.
- **API stability.** ProPublica Nonprofits API is stable but slow; if
  demo latency is a problem, add a per-org cache under `PRIVACY.md`'s
  30-day retention rule.
- **Rate limits.** OpenAlex asks for a mailto in the User-Agent; ORCID
  is lenient. Add the mailto from `CROSSREF_MAILTO` (already exists in
  `.env.example`) rather than a new key.
- **The shared shape** could grow columns as Candid ([#21](https://github.com/nawagner/SlopChecker/issues/21))
  lands. Keep the pydantic model open to extension (optional fields
  with sensible defaults).

**Questions**

- Does the entity-extraction rules pass need to handle multi-org
  proposals (e.g. subcontractors)? Recommend yes for `Entity`
  extraction, no for cross-org affiliation checks in this PR — file
  a follow-up.
- Should `PANGRAM_API_KEY` be checked against personnel names for
  "have they written AI-generated papers before"? **No** — that's
  scope creep, and it's exactly the kind of individual-level claim
  the ticket warns against.
- Is there a rate-limit story we owe #23? Probably yes — add a
  simple in-process rate limiter (`asyncio.Semaphore` or equivalent)
  and note it in `PRIVACY.md` alongside the retention rules.

---
