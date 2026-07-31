# 2026-07-31 — Dan (fable) — #11 claim-support LLM check

Landing the MVP for [#11: Citation check — does the reference actually
support the claim it's cited for?](https://github.com/nawagner/SlopChecker/issues/11)

Branch: `danparshall/11-claim-support` (worktree at
`.worktrees/dan-11-claim-support`).

## What landed

New subpackage `src/slopchecker/pipeline/claim_support/`:

- `check.py` — `@register`d check `claim_supported` under `tier="llm"`,
  off by default via tier gating. Iterates citations from
  `extract_citations`, fetches source via `SourceFetcher`, runs
  judge → quotecheck → refuter, emits `Finding`s only for
  overstated/unsupported/contradicted verdicts that survive the refuter.
- `llm.py` — `Transport` protocol, `AnthropicTransport` (uses
  `output_config.format` for structured output + `thinking:
  {type: "adaptive"}` per the claude-api skill), typed transport
  exceptions matching `detect/pangram.py`'s pattern.
- `prompts.py` — `judge_prompt()` and `refuter_prompt()` as separate
  assembly functions per the #37 design comment; closed JSON schemas
  matching `models.Verdict`.
- `__init__.py` — imports `check` to trigger `@register`; exports
  `ClaimSupportCheck` / `ClaimSupportConfig` for tests.

One-line change to `src/slopchecker/pipeline/registry.py`: added the
new subpackage to `CHECK_PACKAGES` so `discover()` picks it up.

Tests: 20 in `tests/test_claim_support.py`. All 196 in the suite pass,
ruff + mypy clean.

## Design decisions & why

**Adversarial verify shape ported from pat-helper** (via #37's design
comment). Judge model returns a `Verdict` enum + supporting passage +
confidence; refuter model tries to refute. Currently both use
`claude-opus-5` — the second-provider refuter is deferred until a second
provider lands in `config.py` (also blocks #37's shared Ladder).

**Two invariants baked into the design and each covered by a test:**

1. Every emitted `Finding` carries a passage the LLM claimed *and*
   mechanically verified via `match_quote` against the retrieved source
   text. No passage or unmatched passage → no finding.
2. Bias hard toward silence — `supported`, `unverifiable`, refuter's
   `refuted`, confidence below 0.6, or no passage all produce no
   finding. Only concern verdicts (`overstated`/`unsupported`/
   `contradicted`) surviving the refuter reach the report.

**Cost ceiling per acceptance criterion 3:** `max_citations_per_doc=20`
+ `max_source_chars=30_000`. Worst-case LLM calls per doc = `2N`
(one judge per citation, one refuter per concern that carries a
verified passage).

**Anchor.quote is the claim from the proposal, not the source passage.**
Caught in self-review: `Anchor.quote` is contractually the excerpt from
`FlattenedDoc.text` (the proposal), because the renderer locates it via
`text.find(quote)` in `report/html.py:79`. The LLM's source passage
lives in `evidence["source_passage"]` instead. My first test
coincidentally passed because the phrase existed in both proposal and
source — added a regression test using a source-only phrase.

**Schema-slip resilience.** `output_config.format` enforces the schema
server-side, but "degrade to gaps, never crash" means we don't rely on
that. Bad payload → `TransportClientError(422)` → errored ledger row,
not a stack trace.

**`TransportRefusal` is per-citation, not per-doc.** A policy refusal
on one claim shouldn't abort the whole check. Recorded as a per-citation
gap in the ledger detail.

**LLM plumbing is private to this subpackage** per the #37 design
comment. No files shared with the parallel #13 lens-executor session
(registry.py is the one exception, and the edit is a single new tuple
entry that git will merge fine with a similar edit from #13).

## Dead ends

- Initially anchored to `judge.passage` (source text). Renderer
  contract required `Anchor.quote` from `FlattenedDoc.text`. Self-code-review
  agent caught it; test coincidentally masked it. Fixed and added a
  regression test with a source-only phrase.
- Considered adding `docs/active/<branch>/` per the Nori workflow —
  reversed course. This is a hackathon repo with its own conventions
  (`STATUS.md` + `ai-log/`); the research-profile doc tree would be
  noise for teammates and duplicate what STATUS + ai-log already cover.

## What's left / follow-up tickets to file

1. **20-pair confusion-matrix eval** (acceptance criterion 2, deferred).
   Needs a hand-built corpus of known good/bad claim/source pairs, then
   record recall/precision. Blocked on nothing; will file as follow-up.
2. **Cross-provider refuter.** Currently both roles are Anthropic. Needs
   a second provider in `config.py` — waiting on #37.
3. **Wire real source fetchers.** The `SourceFetcher` protocol is
   pluggable but only `LocalFileFetcher` exists. Real network fetchers
   (arXiv, PMC OA, DOAJ) are follow-up work on #10.
4. **`CheckOutput.cost_usd` is not populated.** The Anthropic SDK doesn't
   surface unit price in `response.usage`; need to compute from token
   counts + a per-model rate. Non-blocking for MVP.
5. **Window-centered source truncation.** Current MVP head-truncates
   the source at `max_source_chars`. A follow-up could locate the
   citation's likely relevant span (e.g. `match_quote` on the claim text)
   and center the window there.

## Files touched

```
A  src/slopchecker/pipeline/claim_support/__init__.py
A  src/slopchecker/pipeline/claim_support/check.py
A  src/slopchecker/pipeline/claim_support/llm.py
A  src/slopchecker/pipeline/claim_support/prompts.py
M  src/slopchecker/pipeline/registry.py  (one line: added claim_support to CHECK_PACKAGES)
A  tests/test_claim_support.py
A  ai-log/2026-07-31-danparshall-11-claim-support.md
```
