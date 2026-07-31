# 2026-07-31 · #12 Pangram integration

**Branch:** `danparshall/12-pangram` (worktree `.worktrees/dan-12-pangram`).
**Issue:** #12 — Pangram integration for AI-generated text detection.
**Session:** Claude (Sonnet, air laptop), TDD.

## What landed

- `src/slopchecker/detect/pangram.py` — the whole detector, ~300 lines
  including transport error taxonomy, retry loop, cache, and response →
  model mapping.
- `src/slopchecker/detect/__init__.py` — re-exports `Detector`,
  `DetectorResult`, `PangramConfig`, `PangramDetector`.
- `tests/test_detect_pangram.py` — 10 tests, all injected against a
  `FakeTransport` (mocking at the HTTP boundary, not at logic seams).
- CLAUDE.md ownership table: added `src/slopchecker/detect/` → Dan.
- STATUS.md log line.

## Design decisions (and why)

- **`Detector` is a `runtime_checkable` `Protocol`, not an ABC.** Small
  surface (`name`, `check`, `estimate_cost`), structural typing so the
  Pangram class doesn't inherit from anything — matches the codebase's
  taste (see how `Lens` is a plain frozen dataclass). Second detector
  slots in without touching the base.
- **We do NOT chunk the document ourselves.** Pangram v3's `/task`
  endpoint accepts arbitrary-length text and returns per-window scores
  with `start_index`/`end_index` character offsets against the original
  string. The issue's language ("chunk to the API's expected
  granularity") predates that — we pass `doc.text` through and map
  each returned window to a `Span`. Simpler and avoids offset drift.
- **Quotes are `doc.text[start:end]`, not `window["text"]`.** Same
  result on the happy path, but slicing the source string guarantees
  the quote-anchoring contract (DATA_MODEL.md) even if Pangram ever
  applies Unicode normalization or whitespace collapse to the returned
  window text.
- **Retry taxonomy:** 401/402 → `TransportAuthError` → surfaced
  immediately (retrying an invalid key is user-hostile — waste their
  time waiting for a permanent failure). 400/413/415/422 →
  `TransportClientError` → same. 429 → `TransportRateLimit` → retry.
  5xx → `TransportServerError` → retry. All retries have the same
  ceiling (`max_attempts`) and exponential backoff
  (`initial_backoff_seconds * 2^attempt`).
- **Local retry loop, not shared infra.** Nick's #37 tracks a
  cross-provider retry ladder with typed rung provenance; when it
  lands, `_call_with_retry` here gets replaced with a call into the
  shared machinery. Kept the local version dead-simple to make that
  swap easy.
- **Cache is opt-in via `PangramConfig.cache_dir`.** Off by default so
  a naive run doesn't clutter disk; on for anyone iterating on a fixed
  doc set (the harness, #29). Cache key is
  `sha256(model || "\0" || text)` so a model change invalidates.
- **`ai_label_names` is configurable.** Default surfaces `AI-Generated`
  and `AI-Assisted`; human windows contribute to the doc-level
  `fraction_ai` but don't become evidence cards. If the demo wants to
  show only high-confidence AI passages, tighten this in
  `PangramConfig`.
- **Cost model:** `ceil(word_count / 1000) * unit_price_usd`, min 1
  unit — matches Pangram's bulk billing shape. `unit_price_usd`
  defaults to 0 (I don't know the actual per-unit price); flip when we
  do. `estimate_cost(doc)` never hits the API, satisfying #12's
  "visible in `--dry-run`" criterion — the actual `--dry-run` flag
  wires in #6.

## Skipped / errored are first-class ledger rows

`_skipped(reason)` returns a `LedgerRow(status="skipped", reason=...)`
so the report still shows `AI detection (Pangram): SKIPPED — missing
PANGRAM_API_KEY`. Same for `errored`. "Degrade to gaps, never crash" is
the whole point — a run with no key produces a partial report that
explicitly names what it couldn't check.

## Dead ends / things I didn't do

- **No unit tests for `HTTPTransport`.** The pure logic
  (windows→findings, retry, cache, cost, skipped/errored) is
  thoroughly tested against `FakeTransport`; `HTTPTransport` is
  thin glue that maps status codes to typed exceptions and does a
  submit/poll loop. First real integration test with an actual key
  will exercise it. Adding httpx-level unit tests would double the
  test count for little marginal signal.
- **No `--dry-run` CLI wiring.** That's #6's job; I built the
  `estimate_cost()` surface it needs.
- **No wire-in to a pipeline runner.** #5's runner would need to know
  how to call detectors alongside checks; leaving that composition to
  #5 rather than pre-empting the design.
- **No integration smoke test with the real API.** Would want to run
  once with a fabricated doc + real key before we consider #12 fully
  demo-ready. Not part of the PR; noted here.

## Open flags / coordinate with

- **#23 (data handling policy)** — the tool now has code that will
  POST proposal text to `text.external-api.pangram.com`. Per the
  issue's own note ("whether the Pangram terms permit sending
  third-party submission text"), that policy conversation should
  finish before we run this on any real applicant material. Fine for
  fabricated fixtures / demo.
- **#37 (retry ladder)** — planned swap point in
  `PangramDetector._call_with_retry`.
- **Pangram model deprecation** — API requires explicit model
  selection after 2026-09-30. Default is already `pangram-4`;
  parameterized in `PangramConfig` so we can bump it without a
  release.

## Tests

`uv run pytest` → 60 passed (10 new), 2 skipped (PDF tests, expected).
`uv run ruff check src/slopchecker/detect tests/test_detect_pangram.py`
→ all checks passed.
`uv run mypy src/slopchecker/detect` → no issues.
