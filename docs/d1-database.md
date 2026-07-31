# Report history (Cloudflare D1)

Evidence reports are files first — `report.json` on disk is still the contract
(`docs/DATA_MODEL.md`). D1 is where reports go when you want to ask questions
*across* documents: which DOIs failed to resolve last week, has this text been
submitted before, what did the ledger say the last three times we ran this
proposal.

This is the queryable index, not the archive. Bulk blobs stay in R2
(`docs/data-storage.md`); the two are complementary and meet at
`text_sha256`.

- **Database:** `slopchecker` (binding `DB`)
- **Schema source of truth:** `worker/src/db/schema.ts`
- **Migrations:** `worker/migrations/` (generated, committed)
- **Tooling:** Drizzle Kit generates, `wrangler d1 migrations apply` runs

## Why it lives behind the Worker

D1 is reachable two ways: a Worker binding, or the Cloudflare REST API. The
binding needs no credential; the REST API needs an account-scoped token.

The Python pipeline runs on Railway, so wiring it to D1 directly would mean
minting a Cloudflare API token and putting it somewhere. Sessions in this repo
commit their transcripts to a public directory and the credential scrubber is
best-effort (CLAUDE.md), which is why #23/#65 settled on *no credential is ever
minted or pasted in a session*. Keeping D1 strictly behind the Worker binding
means this whole feature adds **no new secret anywhere** — the only new config
value is `database_id`, which is an identifier, not a credential, and belongs in
committed `wrangler.toml` exactly as the R2 bucket name does.

Consequence worth knowing: `/api/runs*` is served by the Worker and never
reaches FastAPI. A route added to `web.py` under that prefix would be silently
unreachable. The reservation is the `WORKER_OWNED` list in `worker/src/index.ts`.

## Setup

The database is created out-of-band — from a logged-in shell or the dashboard —
and its id pasted into `worker/wrangler.toml`. From the repo root:

```bash
cd worker && npx wrangler d1 create slopchecker --location enam
```

`wrangler d1 create` "provides the binding and UUID that you will put in your
config file" — it prints a ready-made `[[d1_databases]]` block. Take only the
`database_id` line from it and paste that UUID over `local-dev-placeholder` in
`worker/wrangler.toml`; the rest of the block is already there.

`--location enam` is a hint, not a guarantee, and matches the R2 bucket's region
(`docs/data-storage.md`) so the two stores sit together. Drop it if you don't
care. Do **not** pass `--jurisdiction` unless there's a compliance reason — it
overrides the location hint and can't be changed later.

Then apply the migrations to the remote database:

```bash
cd worker && npm run db:migrate:remote
```

That prompts for confirmation and captures a backup before applying. Verify with:

```bash
cd worker && npx wrangler d1 migrations list DB --remote
```

### The placeholder does not survive a deploy

`database_id = "local-dev-placeholder"` is enough for **local dev, the test
suite, and GitHub Actions** — all of those hand the value to Miniflare as a
plain SQLite filename and never validate it.

It is **not** enough for `wrangler deploy`, which resolves the id against the
Cloudflare account. Cloudflare's Git integration runs a deploy on every branch
push, so a placeholder makes the Workers build fail, and on `main` that breaks
production Worker deploys.

`wrangler deploy --dry-run` will not catch this — dry-run never contacts the
API. If you are working on this without a real database, expect the Workers
build check to be red and don't merge on it.

## Local development

```bash
cd worker
npm install
npm run db:generate      # schema.ts -> migrations/NNNN_*.sql
npm run db:migrate:local # apply to .wrangler/state (Miniflare, no network)
npm run dev              # http://localhost:8787
npm test                 # real workerd + real D1
```

Post a report and read it back:

```bash
curl -sS -X POST http://localhost:8787/api/runs \
  -H 'content-type: application/json' \
  --data-binary @../tests/fixtures/sample_report.json
```

```bash
npx wrangler d1 execute DB --local --command "SELECT check_name, result_kind, result_num FROM ledger_rows ORDER BY ordinal"
```

## Changing the schema

Edit `worker/src/db/schema.ts`, then:

```bash
cd worker && npm run db:generate
```

Commit both the new `migrations/NNNN_*.sql` **and** `migrations/meta/` — the
meta directory is Drizzle's diff snapshot, and without it every subsequent
`generate` re-emits the entire schema. CI regenerates and fails if the result
differs from what's committed, so a schema edit without a regenerated migration
is caught rather than silently shipped.

Migrations are applied to production **manually**, not on deploy. Cloudflare's
Git integration auto-deploys `worker/` on merge to main, and it would be
technically clean to prepend the migration step — but `preview_urls = true`
means non-main branches also deploy, and with no `preview_database_id` they
bind the *same* database. Auto-apply would let an unmerged branch migrate
production. D1 also has no `migrations rollback`. So after merging a schema
change, someone runs `npm run db:migrate:remote`. Revisit if a preview database
is ever added.

## The schema, and the one thing to understand about it

Five tables mirroring `src/slopchecker/models.py`:

| Table | One row per |
|---|---|
| `submissions` | distinct document text (deduped on `text_sha256`) |
| `runs` | pipeline execution over a submission |
| `findings` | quote-anchored piece of evidence |
| `finding_checks` | `CheckResult` inside a finding |
| `ledger_rows` | `LedgerRow` in the document-level ledger |

Three rules are load-bearing:

**Results are stored as a (kind, number) pair.** `models.py` says a check result
is `bool | int | float`. SQLite stores booleans as 1 and 0, so a naive
`result REAL` column would make a Pangram score of `1.0` indistinguishable from
a passing `true` — and `EvidenceReport.counts()` and the renderer's three visual
lanes both key off exactly that distinction. So every result column is really
two: `result_kind` (`'bool'` or `'number'`, CHECK-constrained) and `result_num`.
A stored score can never read back as a pass.

The kind has two values rather than three (`int` vs `float`) because that
distinction is unrepresentable at the JSON boundary in *both* directions:
`JSON.parse("1.0")` and `JSON.parse("1")` produce the same value, and
`JSON.stringify(1.0)` is `"1"`. So a check emitting `1.0` reads back as `1`.
It stays in the score lane — which is the part that matters — but the literal
changes. If literal fidelity is ever needed, that's a serializer change, not a
schema change.

**Counts are never columns.** `passed/failed/scores/skipped/errored` are computed
from the ledger on read (`countsFor` in `worker/src/routes/runs.ts`), per the #3
decision that tallies are derived. A query can't drift from the ledger; a column
can. There is a test asserting no such column exists.

**`document.text` is never stored.** A real proposal's flattened text is 30–80 KB;
that's R2's job. D1 keeps `text_sha256` and `text_length`, and the `GET` response
returns the report with `document.text` omitted plus those two values in the
envelope. Because `FlattenedDoc.text` is required and the model forbids unknown
keys, a consumer splices it back:

```python
payload = response.json()
report = EvidenceReport.model_validate(
    {**payload["report"],
     "document": {**payload["report"]["document"], "text": original_text}}
)
```

`text_location` is `null` today. When the R2 bucket is bound in this same
`wrangler.toml`, it becomes the object URL — `text_sha256` is already the key,
so wiring it is additive and needs no migration.

### What "round-trips" means here, precisely

A report read back is **semantically** identical to the one stored, not
byte-identical. Model defaults are normalized away: `status: "ok"` and an empty
`evidence: {}` are omitted on the way out, because both are what `models.py`
would fill in anyway.

This matters because the two producers disagree on style. A report serialized by
the pipeline (`EvidenceReport.to_report_dict()`) writes those defaults out
explicitly; the hand-written fixture omits them. Both validate to the same
`EvidenceReport`, so the property worth asserting — and what the tests assert —
is:

```python
EvidenceReport.model_validate(stored) == EvidenceReport.model_validate(original)
```

not raw dict equality. If you need byte-stability for something like a content
hash, hash the model-normalized form (`to_report_dict()`), not the raw payload.

## API

| | |
|---|---|
| `POST /api/runs` | body is a `report.json`. `201` with `{run_id, submission_id, created, text_sha256, text_length, counts}` |
| `GET /api/runs/:id` | the stored report plus envelope. `404` if unknown |
| `GET /api/runs?text_sha256=&limit=` | run history, newest first |

Ingest is idempotent on the report's own hash: a retried POST returns `200` with
`created: false` and the original `run_id` rather than duplicating a run. The
same document text arriving with *different* metadata is a `409` naming the
divergent fields — a stored row should never contradict the report you read back.

A malformed report is a `400` naming the JSON path that failed
(`{"error": "...", "path": "ledger[0].result"}`). The database is not the
validator of record — pydantic is — but every CHECK constraint here mirrors a
`models.py` rule, and none is stricter. **A report that pydantic accepts must be
storable**, or D1 becomes a second, competing contract.

## Sharp edges

- **No `CASE` in migration SQL.** Wrangler's statement splitter opens a
  compound-statement guard on `CASE` and closes it only on `END` followed by
  whitespace or `;` — but an aggregate ends `END)`, so the terminating semicolon
  gets swallowed and the rest of the file merges into one statement. The failure
  is a syntax error far from the cause. `SUM(<predicate>)` does the same job,
  since SQLite comparisons already yield 0/1.
- **D1 caps bound parameters at 100 per query**, which is why writes are a
  `db.batch()` of single-row inserts rather than one multi-row `INSERT`. The
  batch is also atomic, which matters: a half-written report would still satisfy
  `extra="forbid"` on read and be quietly wrong.
- **Queries per Worker invocation** are capped (1000 paid / 50 free). A report
  with many findings costs roughly `2 + findings + checks + ledger` statements.
  Worth watching if a check starts emitting a finding per matched window.
- **`drizzle-kit check` does not detect schema-vs-migration drift** — it only
  validates the migration files against each other. The CI step that catches
  drift regenerates and diffs.
- **SQLite can't `ALTER` most things**, so Drizzle's answer for a column change
  is create-new/copy/drop wrapped in `PRAGMA foreign_keys`. D1 restricts
  `PRAGMA`. The initial migration is pure `CREATE TABLE` and unaffected; verify
  this on a throwaway column rename before you need it under time pressure.
