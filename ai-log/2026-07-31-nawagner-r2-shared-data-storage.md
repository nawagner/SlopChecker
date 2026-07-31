# R2 bucket for shared data storage

**Date:** 2026-07-31
**Issues:** no direct issue; touches #22 (fixtures) and #23 (data handling)
**Branch:** `claude/r2-bucket-doc-storage-a69579`

## What landed

- Cloudflare R2 bucket `slopchecker-docs`, private, in the Learning Journey
  AI account (`8888d6a3…`), region ENAM.
- Mirrored the team Drive folder `unimelb_data` into it under a `unimelb/`
  prefix: `unimelb_training.csv` (3.6 MB), `unimelb_test.csv` (919 KB),
  `unimelb_example.csv` (36 KB), `unimelb.zip` (462 KB). `.DS_Store` skipped.
- `docs/data-storage.md` — contents table, access procedure, boto3/rclone/
  wrangler snippets, conventions for adding data.
- `.env.example` gains `R2_*` vars; README links the doc.

## Decisions and why

**Bucket lives in the Learning Journey AI account.** Nick's call. It's the
only account whose token carries R2 scope — the second CF account
(`667e076b…`) has workers/KV/D1/pages but no R2. Consequence worth knowing:
that account also holds unrelated production buckets (`rubrics`,
`success-examples`, `webinar-assets`), which is exactly why the access doc
insists the shared token be **bucket-scoped**, not account-scoped.

**No R2 API token was minted in this session, deliberately.** This repo
commits session transcripts to `ai-log/transcripts/` and transcript upload
is now opted in on this machine. A secret access key generated in-session
would be written to a public repo, and CLAUDE.md says the scrubber is
best-effort, not a guarantee. Nick mints it in the dashboard instead.

**R2 is a weak fit for human doc sharing, and we should be honest about
that.** R2 has no per-user identity — it's one shared key pair, not
revocable per person, with no per-reader audit trail. Drive already does
per-user ACLs better. R2 earns its place here for *programmatic* access
(pipeline/CI pulling bulk data), not as a replacement for Drive as the
team's document surface. Worth revisiting if we start using it for
day-to-day docs.

## Dead ends / gotchas

- **`wrangler r2 object put` silently writes to a LOCAL simulated bucket
  unless you pass `--remote`.** First upload reported "Upload complete"
  with `Resource location: local` and nothing reached Cloudflare. Every
  R2 object command in wrangler 4.x needs `--remote`. This is a
  genuinely dangerous default — it succeeds loudly and does nothing.
- **`wrangler r2 bucket info` reports `object_count: 0` well after a
  successful upload.** R2's bucket metrics lag. Don't trust them for
  verification; read the objects back instead (we verified all four
  byte-for-byte against the source files).
- **`wrangler` needs `CLOUDFLARE_ACCOUNT_ID` set** in any non-interactive
  session, because this login has two accounts and can't prompt.
- `gws drive files list` takes a Drive `q` query via `--params`, not a
  `--folder` flag.

## Data-provenance note

The dataset matches the University of Melbourne grant-applications schema:
grant metadata plus repeating per-investigator blocks including
`Year.of.Birth`, `Country.of.Birth`, `Home.Language`, department/faculty
numbers, and prior grant success counts, for up to 15 investigators across
8,708 rows.

I paused on this before uploading, because CLAUDE.md is absolute that
fixtures are fabricated and no real applicant material enters the corpus,
and because #23 (data handling, p0, unresolved) explicitly asks that this
kind of call be deliberate rather than a side effect of implementation.
Nick confirmed the data is synthetic. Recording it here so the next person
doesn't have to re-derive the question from the column names.

## What's left

- Nick: mint the bucket-scoped R2 token, share out-of-band, tell the team.
- #23 should say where R2 sits in the retention story — what we keep in
  the bucket, for how long, and whether bucket contents are in scope for
  the "what leaves the machine" disclosure.
- `docs/` is Emerson/Dominique's per the ownership table. This adds a new
  technical file rather than editing narrative docs, but flagging it —
  move or restructure if it cuts across the docs plan.
