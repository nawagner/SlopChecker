# 2026-07-31 — Dan (fable) — #142 e2e hardening + pre-demo smoke

## Issues

#142 (filed this session, from a pre-demo coverage survey). Touches #126,
#15, #115, #114 context.

## What changed

- **Survey first** (the ask: "does EVERYTHING on the back end work e2e?").
  Findings, in the issue: the demo path (web upload) had zero automated
  coverage; CI has zero secrets so the llm/api tiers only ever exercise
  their skip paths; no full-roster ledger invariant; `-m integration`
  inherits dev-machine keys (paid calls + config drift vs CI); e2e never
  asserts citations or batch similarity.
- **`tests/test_integration_e2e.py`**: credential scrub (set to `""` — blank
  reads as absent and `load_dotenv(override=False)` can't resurrect it);
  full-roster + none-errored + skips-have-reasons invariant; keyless
  degrade assertions (skip rows name the missing key); #126 regression lock
  (rendered fabricated-citations PDF through the real CLI, citation checks
  must RUN, network checks `--skip`'d so required CI stays offline); planted
  near-dup batch pair asserting `similar_documents` fires (#14's two-pass
  CLI wiring). 9 → 13 integration tests.
- **`checks/tagging.py`** (Nick's module — flagged on #142/PR): the roster
  invariant's first run caught that `tagging` emits rows only under
  `doc_type_confidence`/`submitter_type_confidence`/`topic_tags`, never its
  registered id — the exact defect Nick flagged in the #15 review and nobody
  fixed. Additive summary row under `check="tagging"`; rollup ids unchanged;
  unit test.
- **`tests/test_live_llm.py` + ci.yml `live-llm` job**: real-key plumbing
  smoke (claims / claim_supported / pangram_document), plumbing-only
  assertions (ok or reasoned-skip, never errored; quote-anchor holds through
  a real model response). Skips cleanly keyless → job is inert until Nick
  sets repo secrets (`gh api .../actions/secrets` → 0 today). Advisory —
  ci.yml comment says why it must never join `mainsaver`.
- **`scripts/demo_smoke.py`**: the laptop button. Uploads the
  fabricated-citations PDF to live `/api/check`, audits the ledger
  (errored/demo-critical-skip = fail, expected coverage gaps = warn),
  compares deployed ledger vs local registry for deploy drift.

## Verified against production

~10s round trip, 15 ledger rows: claims runs real Anthropic on Railway
(10–13 claims — run-to-run variance also confirms the lens cache isn't on
server-side, #119 secret still unset), Pangram 1.0 on the fabricated doc,
3/9 planted DOIs correctly unresolved. The roster check caught real drift
on its first run: production's ledger has no `tagging` row (the bug above).
Pangram leg of `live_llm` verified with a real local key (1 passed).

## Dead ends / gotchas

- `citations_linked` on the rendered grant PDF returns `result=True` with
  detail "no in-text citations found" — reference *list* parses (post-#126)
  but in-text markers don't survive PDF rendering of this fixture. Vacuous
  pass shape; left alone (Nick's module), worth its own look.
- `recommendation` lives at `summary.recommendation` in report.json, not
  top-level.

## What's left

- Nick: set `ANTHROPIC_API_KEY` (low-spend-limit key) + `PANGRAM_API_KEY`
  as repo Actions secrets to arm the `live-llm` job.
- After merge + Railway redeploy: `uv run python scripts/demo_smoke.py`
  should go green without `--lenient`.
- In-process llm-tier chain test with a fake client (item C-prime) not done
  — `live_llm` + unit fakes bracket it; add if time allows.
