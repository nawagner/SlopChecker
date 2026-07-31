# Shared result cache (Cloudflare KV)

Expensive, deterministic results — Pangram detection scores, LLM lens payloads,
DOI/URL resolutions — are cached in a Cloudflare KV namespace shared across
runs, instead of being recomputed every time.

The problem it solves is specific. Before this, `checks_detect.py` carried the
comment *"no `cache_dir` — the server filesystem is ephemeral"*: **Pangram was
entirely uncached in production**, so every run of the same document was a fresh
paid API call. The lens cache was opt-in and equally ephemeral on Railway, and
`~/.cache/slopchecker` is per-machine, so a DOI cited by forty proposals was
fetched once per laptop rather than once per team.

- **Namespace:** `slopchecker_cache` (`80bde980a03a4a7e8dabda40e11a311f`)
- **Binding:** `CACHE` (see `[[kv_namespaces]]` in `worker/wrangler.toml`)
- **Endpoint:** `/api/cache` (`worker/src/routes/cache.ts`)
- **Client:** `HTTPCache` in `src/slopchecker/checks/cache.py`

The namespace ID is an identifier, not a credential — same class as
`database_id` and the R2 bucket name, and Cloudflare expects it in committed
config. The bearer token that gates the endpoint is a Worker secret.

## Why it goes through the Worker

Same reason D1 does (`docs/d1-database.md`): KV is reachable via a Worker
binding, which needs no credential, or via the REST API, which needs a
Cloudflare account token. The Python pipeline runs on Railway, so talking to KV
directly would mean minting a Cloudflare token and putting it in an environment
that AI sessions touch — and this repo commits transcripts publicly (#23/#65).

So the Worker holds the binding, and Python holds one narrow bearer token that
can do exactly three things: read, write, and delete cache entries. If it leaks,
the blast radius is a cache.

```
Railway (Python)  --Bearer-->  Worker /api/cache  --binding-->  KV
```

## What it stores

| Namespace | Key (hashed) | Value | TTL |
|---|---|---|---|
| `pangram` | sha256(model, doc.text) | `fraction_ai`, `headline`, per-window label/offsets/scores | 30 days |
| `lens` | sha256(model, lens.id, doc.text) | Claim records with `quote_span` offsets | 30 days |
| `doi`, `url` | the identifier | Resolution outcome and canonical metadata | 7 days |

Content-hash keys are immutable by construction — the key *is* the hash of the
input — so their TTL only exists to stop the namespace growing without bound.
The 7-day identifier TTL is unchanged from the disk cache: a stale "resolves" is
cheap to correct.

## KV vs D1 vs R2 — which store, and why

Three stores, three jobs. The rule of thumb is **how bad is it if this
disappears**:

| Store | Holds | If it vanishes |
|---|---|---|
| **KV** (`slopchecker_cache`) | Derived results, content-hash keyed | Nothing is lost — the next run recomputes. Entries expire on their own. |
| **D1** (`slopchecker`) | Evidence reports: submissions, runs, findings, ledger rows | Report history is gone. Durable, migration-tracked, queryable across documents. |
| **R2** (`slopchecker-docs`) | Bulk blobs: corpora, fixtures, rendered PDFs | Re-upload from the repo or Drive. |

So nothing should live *only* in KV. In practice nothing does: every Pangram
score, lens claim, and DOI resolution that reaches a report is already persisted
in D1 by `POST /api/runs`. KV is a fast path in front of recomputation, not a
record.

**Follow-up worth having:** `GET /api/runs?text_sha256=` already returns prior
runs for a document, so a KV miss could fall back to D1 — recovering a Pangram
score computed months ago even after the KV entry expired. It isn't wired up
because the cache key includes the model and D1 doesn't index by it, so it needs
a deliberate "which prior result is still valid" rule rather than a lookup.
Tracked on #119 rather than guessed at here.

## The privacy rule: derived values only

**No document text may enter KV.** Reports are quote-anchored, so it would be
easy to cache the finished object and ship applicant prose to shared cloud
storage by accident. Two mechanisms prevent it, one per payload shape:

**Pangram** — `detect/pangram.py:project()` applies a field **whitelist**, not a
blacklist. Pangram's response happens to carry only offsets and scores today,
but they can add a field tomorrow; anything unlisted is dropped rather than
forwarded. Quotes are re-sliced from `doc.text` by `_windows_to_findings`, and
the cache key is the hash of that same text, so a hit guarantees the offsets
still line up.

**Lenses** — lens payloads *do* carry verbatim quotes, so
`lens_runtime._encode_payload` replaces each `quote` with a `quote_span`
`[start, end]` on the way in, and `_decode_payload` re-slices it from `doc.text`
on the way out. Exact, not approximate, for the same content-hash reason. A span
that falls outside the text is dropped rather than decoded — a wrong quote would
breach the anchoring contract in `docs/DATA_MODEL.md`.

Two further properties fall out of the design:

- **Keys are hashed too.** Which DOIs a proposal cites is itself information
  about the proposal, so the shared namespace holds opaque keys. (This also
  fixes a real bug: httpx re-normalizes `%2F` back to `/`, so a percent-encoded
  URL key would re-partition the request path and lose its query string.)
- **The 1 MiB value cap is a privacy guard rail**, not a performance one.
  Derived-values-only payloads are small by construction, so a megabyte-plus
  value means text leaked into one, and the write fails loudly.

Deliberately **not** cached: the source text quotecheck fetches
(`pipeline/quotes/fetch.py`). That would put third-party, sometimes paywalled
full text into shared cloud storage.

## Failure behavior

Every failure of the shared tier is a **cache miss**, never a run failure —
unreachable host, 401, 404, timeout, malformed body, unserializable value. A
shared cache that can fail a run is worse than no shared cache. The Worker
refuses rather than opens when its secret is missing (503), because callers
treat any non-200 as a miss: a deploy that forgets the secret is slow, not
insecure.

`TieredCache` stacks disk (L1) in front of KV (L2) with write-through, so a warm
local run never pays a round trip and a remote hit backfills local. The disk tier
keeps human-readable filenames — that is where you grep and delete.

## Setup

The token is a shared secret; **do not paste it into an AI session** (this repo
commits transcripts publicly). Generate it locally:

```bash
openssl rand -hex 32
```

Set it on the Worker:

```bash
cd worker && npx wrangler secret put SLOPCHECK_CACHE_TOKEN
```

Then set both variables on the Railway service (dashboard → Variables):

```
SLOPCHECK_CACHE_URL=https://slop-checker.com
SLOPCHECK_CACHE_TOKEN=<the same value>
```

Nothing else needs to change: with the variables unset, `remote_cache()` returns
`None` and every run behaves exactly as it did before.

### Local development

```bash
cd worker && npm run dev
```

Miniflare provisions a local KV namespace from the `[[kv_namespaces]]` block, so
`wrangler dev` and the test suite both get one without touching production. Point
Python at it with `SLOPCHECK_CACHE_URL=http://localhost:8787`.

### Verifying

```bash
curl -H "authorization: Bearer $SLOPCHECK_CACHE_TOKEN" https://slop-checker.com/api/cache/pangram/abc
```

`404` means the endpoint is live and the token is good. `401` means the token is
wrong; `503` means the binding or the secret is missing.

## Not done yet

- **Read-only tokens for teammates.** Today only Railway holds a token; local
  CLI runs use the disk cache. Sharing it more widely means the same "shown
  once, can't revoke one copy" problem the R2 key has
  (`docs/data-storage.md`) — a scoped read-only token is the fix, tracked as a
  follow-up rather than done here.
- **Bulk purge.** `DELETE /api/cache/:ns/:key` exists and is idempotent, but
  #108 wants a purge-everything command as a data-handling control. KV has no
  prefix-delete, so that needs a `list` + batched delete.
