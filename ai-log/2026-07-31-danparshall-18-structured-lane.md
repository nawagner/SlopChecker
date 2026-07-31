# 2026-07-31 — #18 structured lane, Phases 0 and 1

**Session:** Claude (CLI, air machine), Dan (fable) as delegate. Started
14:38 UTC.

**Issue:** #18 — Auto-generated background report on submitting team and
topic. Split into two lanes by an earlier session (design convo on
`danparshall/18-background-report`). This session picks up **Plan A —
Pure-structured lookups** on a fresh branch off `origin/main`.

**Branch:** `danparshall/18-structured-lookups` (do NOT stack on
`danparshall/18-background-report` per the plan — that branch will hold
only the open-web lane).

## What landed

Phase 0 of the plan: shared shape on `models.py`, small independent PR.

- **`src/slopchecker/models.py`** — six new types plus two new StrEnums,
  and one optional field on `EvidenceReport`:
  - `EntityKind` (StrEnum): `org` | `person`.
  - `BackgroundConfidence` (StrEnum): `verified` | `probable` |
    `unverified`.
  - `Entity`: named entity extracted from the proposal. `affiliation`
    is the corroboration hook for common-name disambiguation.
  - `BackgroundFinding`: one source-linked registry hit.
    `source_url` required (structural), `entity_id` references an
    `Entity` in the same report.
  - `EntityNotFound`: explicit "we looked and it isn't there" — first
    class, distinct from a coverage gap and from silence. Records the
    query URL.
  - `BackgroundGap`: per-(entity, registry) failure. `entity_id=None`
    means the whole registry was unreachable.
  - `BackgroundReport`: aggregate. Model validator enforces referential
    integrity across findings/not_found/gaps and rejects
    `confidence="unverified"` findings.
  - `EvidenceReport.background: BackgroundReport | None = None`.
- **`tests/test_background_models.py`** — 19 new tests covering
  required fields, closed enum, referential integrity across all three
  child collections, `EntityNotFound` vs `BackgroundGap` vs absence,
  `EvidenceReport.background` optionality + round-trip, and `extra=forbid`
  on the two most collision-prone models.
- **`docs/DATA_MODEL.md`** — added the top-level row and a new section
  documenting `BackgroundReport` and its members.

## Design decisions and their reasoning

- **`unverified` kept in the enum, filtered at report assembly.** The
  plan describes `verified | probable | unverified` and says the
  unverified state never reaches a shipping report. Encoded as: the
  enum has three values so a lookup can produce and enumerate ambiguous
  matches, and `BackgroundReport` rejects any `unverified` finding at
  construction. Filtering happens; it just doesn't have to happen
  early.
- **Common-name disambiguation lives at the lookup site, not on the
  model.** Different registries have different fields that count as
  "corroboration" (OpenAlex last_known_institution, ORCID
  employment-summary, ProPublica's EIN uniqueness). The model can't
  enforce "verified requires affiliation" across all of them without
  becoming per-registry. Documented as a code-level invariant to be
  covered by client tests in later phases.
- **`EntityNotFound` and `BackgroundGap` are separate lists**, not a
  union type on findings. Cleaner enumerate/render semantics; matches
  the plan's "explicit NotFound" phrasing without complicating the
  finding shape.
- **Names carry the `Background`/`Entity` prefix** (`BackgroundGap`
  vs bare `Gap`, `EntityNotFound` vs bare `NotFound`) to leave room
  for other "gap" or "not found" senses in the future.

## Coordination filed

- **#18** — comment claiming Plan A on the fresh branch with the phase
  order.
- **#3** — comment with the proposed `models.py` addition (per
  CLAUDE.md's "change a shared model, comment first" rule). Posted
  before implementing, but the hackathon-pragmatic interpretation is
  to keep moving: types are additive-only, and if the shape needs to
  change based on feedback the PR is small.
- **#8** — not yet flagged; will do so before Phase 4 (registered check
  under `checks/`, which is Nick's package).

## Verification

- 19 new tests passing.
- Full suite: 450 passed, 9 deselected (integration; deliberately
  excluded from the default run per this repo's convention), 1 warning
  (pre-existing starlette/httpx compat).
- `ruff check` + `ruff format --check`: clean.
- `mypy src/slopchecker/models.py`: clean.
- D1 schema contract tests (`tests/test_d1_schema_contract.py`):
  8 passed. The new `background` field is optional and default-`None`,
  so `to_report_dict(exclude_none=True)` doesn't emit it and existing
  D1 storage paths are unaffected.

## Phase 1 — module skeleton + rules-based entity extraction

Bundled into the same PR as Phase 0 (same branch, same review cycle). Kept
in one PR because Phase 1 introduces no new coordination surface — no
`models.py` change, no `checks/` touch, no renderer — and reviewers can
still evaluate the two commits as separate logical units.

### What landed

- **`src/slopchecker/background/__init__.py`** — package + convenience
  export of `extract_entities`.
- **`src/slopchecker/background/structured/__init__.py`** — subpackage
  that will hold the ProPublica / OpenAlex / ORCID clients in Phase 2/3.
- **`src/slopchecker/background/structured/base.py`** — `RegistryLookup`
  Protocol every client will implement. Returns a mixed
  `list[BackgroundFinding | EntityNotFound | BackgroundGap]` so a single
  call can produce multiple outcomes (a hit plus ambiguous-candidate
  gaps).
- **`src/slopchecker/background/extract.py`** — rules-first
  `extract_entities(FlattenedDoc) -> list[Entity]`.
- **`tests/test_background_extract.py`** — 10 tests covering
  section-driven extraction (single PI, multi-personnel bullet list,
  affiliation attached to person), the negative cases (no PI section,
  blog post → empty), anchor discipline (every entity has an `Anchor`
  whose `quote` is a verbatim substring of `FlattenedDoc.text`; spans
  match), id uniqueness, determinism, plus one end-to-end smoke test
  against `harness/fixtures/proposal_climate.md`.

### Extraction rules

Section-driven, deliberately narrow. Guessing at names in body prose is
the exact failure mode that surfaces individual-level claims without
evidence, which #18 explicitly warns against.

1. Match Markdown ATX headings whose title is in a whitelist:
   `PI`, `PI/Institution`, `Principal Investigator(s)`, `Team`,
   `Personnel`, `Investigators`, `Co-Investigators`, `Submitted by`,
   `Applicant(s)`.
2. Within each matching section, walk non-empty lines (strip leading
   bullet markers). Split on commas.
3. If the first comma-part matches `_PERSON_TITLE_RE` (`Dr.`, `Prof.`,
   `Mrs.`, `Ms.`, `Mx.`, `Mr.`, `Professor` followed by a capital
   letter), treat it as a person name.
4. The last non-department comma-part is the institution; middle parts
   starting with `Department|School|College|Faculty|Institute of|...`
   are skipped (they're the person's unit, not their affiliation).
5. Emit one Person Entity with `affiliation` set to that institution,
   plus one Org Entity for the institution itself. De-dup by (kind,
   name).

Every entity gets an `Anchor` whose `quote` is the exact substring of
`FlattenedDoc.text` — same discipline as every other anchor in the
model.

### Design decisions and dead ends

- **Deliberately narrow person-title regex.** An earlier draft matched
  bare capitalized names, which fired on prose ("Recent NIH R01 awards
  cited Fenwick's work..."). Rolled back to require an explicit title
  prefix. Follow-up ticket for LLM-based extraction to cover byline
  patterns and prose-only PI mentions.
- **Department-marker filter to keep institutions clean.** Without it,
  `Dr. Alice Kimura, Department of Materials Science, Riverbend
  Institute of Technology` produced `affiliation="Department of
  Materials Science"`, which every registry lookup would then confuse
  for an unrelated org.
- **No section-structure API from `ingest/` yet.** The plan suggested
  using section headers already extracted by `ingest/`; those don't
  exist on `FlattenedDoc` (docstring: "Section structure is deferred
  until a loader needs it"). Walked the text directly with a regex,
  same shape as what a `sections` field would produce eventually.
- **PI/Institution section not present ≠ error.** A blog post or
  think-tank report has no PI section and produces an empty entity
  list. The runner in Phase 4 will convert `no entities` into the
  ledger row `skipped: no entities extracted` — a first-class outcome,
  not a silent success.

### Verification

- 10 new tests passing (all Phase 1).
- 19 Phase 0 tests still green.
- Full suite: 462 passed, 9 deselected, 1 warning.
- `ruff check` / `ruff format --check` / `mypy src/slopchecker/background/`:
  all clean.
- Nothing in `src/slopchecker/checks/` touched — Nick's package flag
  isn't needed until Phase 4.

## What's left (for later PRs on this branch)

Later phases per `01_structured_lane.md`:

- Phase 2: ProPublica Nonprofit Explorer client (cassette-tested).
- Phase 3: OpenAlex + ORCID clients + cross-client dedup.
- Phase 4: Runner + registered check in `checks/` (flag Nick on #8 first).
- Phase 5: Renderer coordination with Emerson/Dominique.
- Phase 6: PRIVACY.md rows, final polish.

Each of Phases 2–6 is its own small PR on the same branch.
