# 2026-07-31 — etbrooking — last-minute: LLM topic classification + ranked Pangram passages

Session: Fable (same session as the rubrics work). No issue filed — direct
operator request under demo time pressure; this log + STATUS is the trail.
Touches #15 (topics) and #12 (Pangram) conceptually.

## What changed

- **`pipeline/checks_topics.py`** (new): `topic_classification`, tier=llm.
  Claude prompt classifies the document into the FIXED topic set from
  `checks.tagging.load_taxonomy()` — one source of truth with the
  deterministic tagger, so both lanes speak the same vocabulary and #20's
  batch summary can group on either. Contract in the prompt: primary + up
  to 2 secondary, each with confidence and a verbatim evidence quote;
  "other" is the only escape hatch. Enforcement in code: off-list topic →
  errored row (never a made-up tag in the report), quote not verbatim in
  doc.text → anchor dropped, topic kept. Missing ANTHROPIC_API_KEY →
  skipped gap. Reuses `lens_runtime`'s AnthropicClient + retry + strict
  JSON parse rather than duplicating transport code.
- **`pipeline/checks_detect.py`**: Pangram findings are now the top-5 most
  AI-like passages, ranked by `pangram_window_ai_score`, relabeled
  "Most AI-like passage #N" with score + original Pangram label in the
  note. The doc-level row keeps `fraction_ai` as its result (scores stay
  in their own lane) and its detail now lists the top passage scores and
  states any cap ("showing top 5 of 8"). Dan's `detect/pangram.py` is
  untouched — all in the mapping layer I own from #96.

## Why this shape

- Deterministic `tagging` stays registered: the no-LLM-fallback house rule
  ("checkers must be runnable by a dumb script with no LLM at all") — the
  LLM check upgrades coverage, doesn't replace the floor.
- Capping passages at 5 with the cut stated in the ledger keeps a
  heavily-AI document from wallpapering the report (the "no silent caps"
  rule: the drop is visible).

## Verified

584 passed (+12 new: 6 topics, 2 ranking, existing 4 detect), ruff
check + format clean. The one failure is the pre-existing
`test_harness_end_to_end_matches_expected_outcomes` miss that fails
identically on clean main (flagged on PR #145).

## Left

- Renderer surfaces `Finding.note` already; if the ranked labels crowd the
  margin on the demo doc, that's Dominique's #149 territory.
- `topic_classification` needs `ANTHROPIC_API_KEY` on Railway to run live
  (same env story as the claims lens, #115).
