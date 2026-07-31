# 2026-07-31 — etbrooking — #7/#12 registry wiring: citations + Pangram

Session: Fable via Claude Code (same session as web-layer and PDF-rendering
logs). Two sonnet subagents wrote the check modules against tight specs;
orchestrator did the registry edit, review, and the fallout fixes below.

- **Landed:** `pipeline/checks_citations.py` (`citations_linked`,
  deterministic — orphan in-text markers via `extract_citations`, findings
  passed through quote-anchored) and `pipeline/checks_detect.py`
  (`pangram_document`, api tier — wraps `PangramDetector`; detector's own
  skipped/errored ledger rows pass through). Registry `CHECK_PACKAGES` gains
  both modules. Quote-vs-source (#10) deliberately NOT registered — blocked
  on source retrieval (#8/#37).
- **#23 posture:** without `PANGRAM_API_KEY` in the environment the Pangram
  check emits a skipped gap row and no text leaves the process. The
  data-handling decision gates on setting the key in production, not on this
  code. Key is NOT set on Railway.
- **Fallout fixed (all pre-existing brittleness my registration exposed):**
  - `cli.py` wrote report.json with platform-default encoding; Windows
    cp1252 + a non-ASCII detail char = UnicodeDecodeError on render. Now
    explicit utf-8. (Also ASCII-ified my check's detail strings.)
  - `test_batch_ranks_by_concerns` asserted exact concern counts against the
    whole registry — now pinned with `--only flag_bad`.
  - `scratch_registry` fixture now calls `discover()` before copying, so a
    test's fake `pangram_document` can't collide with the real module's
    import-time `register()`.
  - The long-mysterious local-only `test_dry_run` failure: rich shrinks the
    dry-run table's id column on narrow consoles (legacy Windows is ~1 char
    narrower than CI) and ellipsizes/folds `pangram_document`. Fixed the
    product side (`overflow="fold"` — ids are the `--only`/`--skip`
    vocabulary, never drop chars) and pinned the test console to width 200.
- **Verified:** 182 passed, ruff clean. Live verification against the R2
  fixture PDF after merge + Railway auto-deploy.
- **Next (Emerson):** #20 batch summary view — claimed in-session.
