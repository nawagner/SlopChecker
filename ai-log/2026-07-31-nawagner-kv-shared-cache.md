# 2026-07-31 — Nick (claude-code) — shared KV result cache (#119)

## Issue

#119, opened this session. Nick had already created the KV namespace
(`slopchecker_cache`, `80bde980a03a4a7e8dabda40e11a311f`) and wanted it used for
"Pangram score and other things you think of."

## What was actually broken

Reading before designing turned up the real motivation, which was sharper than
"add a cache":

- `pipeline/checks_detect.py:32` — *"A fresh `PangramDetector` is instantiated
  per call (no `cache_dir` — the server filesystem is ephemeral)."* Pangram was
  **entirely uncached in production**. Every run of the demo document was a
  fresh paid API call.
- `pipeline/checks_llm.py` — lens cache opt-in via `SLOPCHECK_LENS_CACHE_DIR`,
  off by default, and wiped on every Railway deploy anyway.
- `checks/cache.py` — solid, but `~/.cache/slopchecker` is per-machine.

So there were already four disk caches; the gap was that none of them survive
the hosted environment or reach past one laptop.

## Decisions (all confirmed with Nick before writing code)

**Access path — Worker proxy, not a Cloudflare token.** `wrangler.toml` already
records the rule from #23/#65: the Python side never talks to D1 because that
needs a CF API token, and no credential is minted or pasted in a session
(transcripts are public). That applies identically to KV's REST API. So the
Worker holds the binding and Python holds one narrow bearer token whose entire
blast radius is a cache.

**Scope — Pangram, lenses, DOI/URL.** Quotecheck's fetched source text was
explicitly excluded: third-party, sometimes paywalled full text has no business
in shared cloud storage.

**Privacy — derived values only.** Not enforceable in the cache module (it takes
arbitrary JSON), so it lives with the callers and is tested there.

**Consumers — Railway only.** Teammates keep the disk cache. Wider distribution
means the R2 key's "shown once, can't revoke one copy" problem, so a read-only
token is a follow-up, not this issue.

## The interesting part: two payload shapes, two mechanisms

Pangram and lens payloads look similar and are not.

**Pangram is already clean.** Its response carries `start_index`/`end_index` and
scores; `_windows_to_findings` re-slices the quote from `doc.text`. So it could
have been cached verbatim. It isn't — `project()` applies a field **whitelist**,
because Pangram can add a field to its response tomorrow and a blacklist would
silently forward a future `windows[].text`.

**Lens payloads are not clean.** They carry verbatim `quote` strings by
construction — that's the quote-anchoring contract. `_encode_payload` replaces
each `quote` with a `quote_span` `[start, end]`; `_decode_payload` re-slices from
`doc.text`. This is exact rather than best-effort because the cache key is the
hash of that same text: a hit means byte-identical input. A span outside the text
is dropped rather than decoded — a wrong quote would breach DATA_MODEL.md.

## Dead end worth recording: percent-encoding cache keys

First implementation percent-encoded the key into the URL path
(`quote(key, safe="")`) and hashed it only when it exceeded KV's 512-byte limit.
A test caught it: **httpx re-normalizes the URL and decodes `%2F` back to `/`.**

Two failures, not one. The path re-partitions across segments, *and* a key's
`?query` gets parsed off as a real query string — so `…/a/b?v=1` and
`…/a/b?v=2` collide on the same cache entry, silently returning the wrong
answer. Would have been invisible until a URL check misbehaved.

Fix: hash the remote key unconditionally. Three benefits — correctness, KV's key
limit stops mattering, and a privacy one that wasn't the goal: which DOIs a
proposal cites is itself information about the proposal, so the shared namespace
now holds opaque keys. Readability was the disk cache's stated virtue, and the
disk tier keeps it.

Regression test: `test_url_keys_do_not_leak_into_the_path`.

## Other judgment calls

- **1 MiB value cap is a privacy guard rail, not a perf one.** Derived-values
  payloads are small by construction, so a megabyte-plus value means text leaked
  in, and the write should fail loudly (413) rather than publish it.
- **Missing secret → 503, closed not open.** Callers treat any non-200 as a
  miss, so a deploy that forgets the secret is slow, never insecure.
- **`--no-cache` disables both tiers.** The flag means "re-fetch"; a shared hit
  would defeat it as thoroughly as a local one.
- **`WORKER_OWNED` restructured** so one list still gates every Worker-owned
  path. First pass put the `/api/cache` branch above the loop, which made the
  list look decorative when it's actually what takes a path away from FastAPI.

## Testing

- 33 new Python tests (`tests/test_shared_cache.py`), `httpx.MockTransport` as a
  fake Worker — no new test dependency, no network. Full suite 439 passed, ruff
  and format clean.
- 18 new Worker tests (`worker/test/cache.test.ts`) against real workerd and
  Miniflare's real KV. 91 passed, `tsc --noEmit` clean.
- `tests/test_web.py` fails to collect in this venv on a missing
  `python-multipart`. Pre-existing — confirmed by stashing the branch and
  re-running. Not touched.

## What's left

- **Nick must set the secret** (`wrangler secret put SLOPCHECK_CACHE_TOKEN`,
  then the same value plus `SLOPCHECK_CACHE_URL` in Railway). Generate it with
  `openssl rand -hex 32` — **do not paste it into a session**, transcripts here
  are public. Until then the code is inert and every run behaves as before.
- Read-only tokens for teammates' local CLIs (follow-up).
- Bulk purge for #108 — single-key `DELETE` exists; KV has no prefix-delete, so
  purge-everything needs `list` + batched delete.
