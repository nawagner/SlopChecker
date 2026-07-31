# 2026-07-31 — `danparshall/13-lens-runtime` — #13 runtime half

## Issue

**#13 — lens runtime.** PR #46 (a prior session) landed the claims lens as a
prompt pack. This branch ships the execution half: a lens executor that runs
the pack against a real LLM, parses the strict-JSON output, mechanically
quote-anchors each emitted claim, and caches per document hash.

## What changed

- **`src/slopchecker/pipeline/lens_runtime.py` (new)** — the executor.
  - Typed transport exception hierarchy (`TransportAuthError` /
    `TransportClientError` / `TransportRateLimit` / `TransportServerError`),
    parallel to `detect/pangram.py`.
  - `LLMClient` protocol at the boundary; `AnthropicClient` wraps
    `anthropic.Anthropic()` and maps SDK exceptions to the typed transport
    types so the retry loop can dispatch by class.
  - `_call_with_retry` — retries only 429 / 5xx (transient), surfaces
    401/402/4xx immediately.
  - `assemble_messages(lens, doc)` deliberately separate from the call site
    so a future "reframed" prompt is a sibling function, not an edit — locks
    in one of the two shape decisions from #37's 2026-07-31 design comment.
  - `_parse_json_strict` tolerates markdown code fences (matches the
    pat-helper pattern; pat_helper is a separate repo, not a dep).
  - `_quote_anchor` drops claims whose `quote` isn't a verbatim substring
    of `doc.text`. No fuzzy matching — the mandate is verbatim.
  - Content-hash cache keyed on `(model, lens.id, doc.text)` so a model
    change or a different lens invalidates.
  - Missing `ANTHROPIC_API_KEY` → `status="skipped"` with the env-var name
    in the reason (degrade-to-gaps).
  - `LensRunResult.provider` / `.model` always populated so the registered
    check can drop them into `Finding.evidence` — locks in the second #37
    shape decision (adding `"rung": "plain"` later is a one-line change
    with no schema-version bump).

- **`src/slopchecker/pipeline/checks_llm.py` (new)** — registers the `claims`
  check. Loads `lenses/claims.md`, calls `run_lens`, maps each surviving
  claim → `Finding` per the mapping table in `lenses/claims.md`, emits
  doc-level ledger rows: `claims` (did it run + finding count) and
  `claims_quant_unsourced` (the report-summary number named in #13's
  acceptance criteria). Cache opt-in via `SLOPCHECK_LENS_CACHE_DIR` — off
  by default so a fresh checkout has no filesystem side effects.

- **`src/slopchecker/pipeline/registry.py`** — added `slopchecker.pipeline.checks_llm`
  to `CHECK_PACKAGES` so `discover()` picks up the new check.

- **`tests/test_lens_runtime.py` (new)** — 21 tests covering prompt
  assembly (page markers, presence checks), retry policy per exception
  class, credential-missing skip path, cache hit/miss, cache-key
  invalidation on model change and on lens change, cache-does-not-write
  on error, JSON parse tolerance, quote-anchor drop, provenance in result.

- **`tests/test_check_claims.py` (new)** — 8 tests covering the
  claim→Finding mapping table, derived-bool checks per claim, doc-level
  quant_unsourced count, ok/skipped/errored ledger rows under the
  registered id, discoverability, and missing-page fallback.

Baseline test count 176 → 205 (+29).

## Design decisions worth surfacing

- **Runtime is sync, not async.** Matches `pipeline/runner.py`. Pat-helper's
  original is async; not adopting that here because SlopChecker's runner uses
  a `ThreadPoolExecutor` and expects checks to be sync callables.
- **Provider/model in `Finding.evidence`, not first-class fields.** Same
  reasoning captured on #37 — `evidence` is `dict[str, Any]`, so adding
  `rung` later needs no schema-version bump.
- **Runtime handles `MissingCredential` locally.** `runner.py` also catches
  it uniformly, but `run_lens` is a library function callable outside the
  pipeline; keeping the skipped return keeps the `LensRunResult` contract
  clean for other consumers.
- **Ledger-id convention held on every path.** After the /simplify pass,
  the success path now also emits a `check="claims"` row (in addition to
  the `claims_quant_unsourced` metric row) so `registry.py:96`'s "id must
  match `LedgerRow.check`" invariant holds on ok/skipped/errored equally.
- **Cache scope kept narrow.** `lens.id` is part of the cache key so a
  future lens using the same runtime doesn't collide.

## Deferred to a separate evaluation ticket (NOT in this PR)

The 2026-07-31 note on #13 (from the session that landed the prompt pack)
listed three items still open. Two are eval work, filed for a separate
ticket:

- **Run-to-run stability diffing.** Needs a scoring harness of its own.
- **5-real-proposal manual review.** Needs a dataset + labeler.

The third — per-doc-hash caching — landed as part of this PR.

## Dead ends / gotchas the next person shouldn't repeat

- **`sdk_client` param on `AnthropicClient.__init__` was YAGNI.** First
  draft accepted an injectable SDK client. Tests inject at the `LLMClient`
  boundary (via `run_lens(client=FakeClient())`), not at the SDK boundary.
  The /simplify pass dropped it.
- **`quant_unsourced` count was computed via a nested loop over
  `findings × checks` in the first draft.** The same number is directly
  computable from `payload["claims"]` — one loop, no name-matching on
  emitted CheckResults. Simpler and less fragile.
- **The mapping table in `lenses/claims.md` is the contract, not `_map_claim_to_finding`.**
  If the mapping needs to change, update the table first and the code
  second — the table is what a report reader will consult.
- **CI mypy has 4 pre-existing errors** (`config.py`, `runner.py`,
  `web.py`) unrelated to this PR. CI runs mypy `continue-on-error: true`
  so nothing blocks; not in scope here.

## What's left

- Open PR, add PR link as an issue comment on #13.
- Long-tail: file the separate eval ticket (stability diff + 5-proposal
  manual review) so #13 can close cleanly.

## Related

- **#37** — the retry-ladder-and-provenance design conversation this PR's
  shape decisions were locked against. Its own runtime work is now
  unblocked by this PR (one real caller in the tree with the right
  typed-exception + evidence shape).
- **#11** — parallel session in `pipeline/` building the claim-support
  verifier. Different lens output shape (findings + verdict), different
  Finding mapping; no file overlap with this PR.
- **PR #46** — the prompt-pack half of #13.
