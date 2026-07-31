# D1 report history + tracked schema migrations (#88)

Issue: #88 (filed this session). Touches #3 (binds to the shared model), #27
(Emerson's `worker/src/`), #20 and #14 (both unblocked by having somewhere to
query).

## What landed

A Cloudflare D1 database behind the Worker, with Drizzle Kit tracking schema
migrations in the repo.

- `worker/src/db/schema.ts` — the source of truth. Five tables mirroring
  `models.py`: `submissions`, `runs`, `findings`, `finding_checks`,
  `ledger_rows`.
- `worker/migrations/` — generated SQL, committed (including `meta/`).
- `worker/src/routes/runs.ts` — `POST /api/runs`, `GET /api/runs/:id`,
  `GET /api/runs?text_sha256=`.
- `tests/test_d1_schema_contract.py` — 8 guards on the required Python CI job.
- `worker/test/` — 35 tests in real workerd against real D1.
- `docs/d1-database.md`, plus a "where a report is stored" section in
  `docs/DATA_MODEL.md`.

## Decisions and why

**D1 sits behind the Worker binding; Python never touches it.** The Worker
binding needs no credential; the REST API needs an account-scoped token. #23
and #65 established that no credential is minted or pasted in a session here,
because transcripts land in a public directory and the scrubber is
best-effort. Keeping D1 Worker-only means the feature adds no new secret at
all — the only new config value is `database_id`, which is an identifier.

**Results are stored as a `(result_kind, result_num)` pair.** This is the one
non-obvious thing in the schema and it's worth the extra column. `models.py`
says a result is `bool | int | float`; SQLite stores booleans as 1 and 0. With
a bare `result REAL` column, a Pangram score of `1.0` becomes indistinguishable
from a passing `true` — and `EvidenceReport.counts()` keys off `r is True` /
`isinstance(r, bool)`, with the renderer's three lanes following it. A CHECK
constraint (`result_kind IN ('bool','number')`, plus `result_kind <> 'bool' OR
result_num IN (0,1)`) makes it a database guarantee rather than a convention.

Two values, not three (`int` vs `float`): that split is unrepresentable at the
JSON boundary in *both* directions — `JSON.parse("1.0")` and `JSON.parse("1")`
are the same value, and `JSON.stringify(1.0)` is `"1"`. A three-valued kind
would be a column we could neither fill correctly nor use. Consequence: a check
emitting `1.0` reads back as `1`. Still in the score lane, which is what's
load-bearing.

**D1 accepts exactly what `models.py` accepts, and enforces nothing it
doesn't.** Every CHECK mirrors a pydantic constraint. Concretely this means the
DB does *not* enforce unique finding ids within a run (the model doesn't) and
*does* allow a `reason` on an `ok` row (`CheckResult._status_consistent`
permits it). A database stricter than the model would be a second, competing
contract, and the failure would show up as reports that validate but won't
store.

**Counts stay derived** (#3) — computed from the ledger on read. There's a test
asserting no `passed`/`failed`/`scores` column exists.

**`document.text` never enters D1** — 30–80 KB per real document is R2's job
(#65). D1 keeps `text_sha256` + `text_length`; that pair is the seam, and
`text_location` in the read response is the (currently `null`) hook for wiring
R2 later without a migration.

**Migrations are applied to production manually, not on deploy.**
`preview_urls = true` means non-main branches deploy too, and with no
`preview_database_id` they bind the *same* database — auto-apply would let an
unmerged branch migrate production. D1 also has no `migrations rollback`.

## Dead ends and things that cost time

- **`drizzle-kit check` does not detect schema-vs-migration drift.** It
  validates migration files against each other only. I had a CI step relying on
  it, verified it against a deliberately drifted schema, and found it reports
  "Everything's fine". The CI step now regenerates and diffs, which does catch
  it. If you add a schema check anywhere, test that it actually fails.
- **`@cloudflare/vitest-pool-workers` 0.20 removed `defineWorkersConfig` and
  the `/config` subpath.** Most published examples are stale. The current API
  is a `cloudflareTest()` Vite plugin. Also: the package is ESM-only, so the
  config must be `vitest.config.mts` (or the package flipped to
  `"type": "module"`, which would affect wrangler and drizzle-kit), and
  `readD1Migrations` has to be awaited *inside* the async options factory —
  Vite bundles the config as CJS, where top-level await is a build error.
- **Don't put `CASE` in migration SQL.** wrangler's statement splitter opens a
  compound-statement guard on `CASE` and closes it only on `END` followed by
  whitespace or `;` — an aggregate ends `END)`, so the terminating semicolon is
  swallowed and the rest of the file merges into one statement. `SUM(<predicate>)`
  does the same job since SQLite comparisons yield 0/1. There's a test
  asserting no `CASE` appears in migrations.
- **A placeholder `database_id` is enough for everything except
  `--remote`.** wrangler hands the value to Miniflare as a plain SQLite
  filename without validating it. Local dev, the whole test suite, and CI run
  on `"local-dev-placeholder"`. Worth knowing before anyone blocks on
  provisioning.
- `@cloudflare/workers-types` was referenced in `worker/tsconfig.json` but had
  never been installed, so `tsc --noEmit` on `worker/` failed before any of
  this work. Now installed, along with `typescript` itself.

## One real bug, found by the independent tests

Idempotency didn't survive key reordering. The hash was
`sha256(JSON.stringify(report))`, and the code comment claimed that
re-stringifying made a reformatted retry hash identically. Half true:
`JSON.stringify` collapses whitespace but preserves each object's *insertion*
order, so the same report emitted with `document` and `schema_version` swapped
produced a different hash and a duplicate run row.

Pydantic serializes in field-definition order, so any single producer is
self-consistent and this would never fire in the happy path — which is exactly
why it survived my own review. It fires on "the same report arriving via a
different code path", which is the retry case idempotency exists to absorb.

Fixed with `canonicalJson()` in `codec.ts`: recursively key-sorted
serialization for the hash only. Arrays are deliberately **not** reordered —
`findings`, `ledger` and `checks` are ordered lists, so two reports differing
in array order are genuinely different reports. The regression test is in
`worker/test/invariants.test.ts`.

Worth noting how it was found: the agent wrote the test from the stated
contract, watched it fail against real behaviour, and encoded it as
`it.fails(...)` rather than quietly weakening the assertion to make the suite
green. That's the behaviour to keep.

## Verified, not assumed

- All 8 negative constraint cases reject with the correct constraint firing;
  the permissive cases (reason on an ok row, duplicate finding ids) are
  accepted.
- The fixture round-trips and the result **validates through pydantic** under
  `extra="forbid"`; counts match `EvidenceReport.counts()`.
- 120 findings / 240 checks / 40 ledger rows round-trip with order preserved,
  402 statements in one `db.batch()`.
- D1 enforces foreign keys — cascade deletes leave no orphans.
- Tests were written by three independent agents working from the *contract*
  rather than the implementation, each required to prove every test fails
  under a targeted mutation before accepting it. One found that dropping
  `ORDER BY` on findings does *not* go red (SQLite's table scan happens to
  preserve insertion order) and replaced it with a reversing mutation rather
  than keeping a weak test.

## Known property, not a bug

A report read back is **semantically** identical, not byte-identical.
`to_report_dict()` writes `status: "ok"` and `evidence: {}` explicitly; those
model defaults are normalized away on storage. `model_validate(a) ==
model_validate(b)` holds; raw dict equality does not. If you ever need a
content hash of a stored report, hash the model-normalized form.

## What's left

- Nick creates the database (`wrangler d1 create slopchecker`) and pastes
  `database_id` into `worker/wrangler.toml`, then `npm run db:migrate:remote`.
  Nothing else is blocked on this.
- The `worker` CI job is advisory until someone adds it to the `mainsaver`
  ruleset — same out-of-band step #43 took for `test`.
- Persisting what `POST /check` produces is deliberately out of scope; that's
  #27's call now that the storage endpoint exists.
