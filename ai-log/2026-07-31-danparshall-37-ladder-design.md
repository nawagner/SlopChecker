# 2026-07-31 · #37 retry-ladder design conversation

**Session summary:** Brainstorm on #37 (retry ladder + cross-provider failover
with typed rung provenance). No code landed. Two shape decisions captured as a
comment on #37; ticket parked as post-MVP, blocked on landing #13 (or #11) as
forcing function.

## Issue(s)

- #37 — Retry ladder + cross-provider failover with typed rung provenance
  (authored by @danparshall, labeled `needs-design`).

## What changed

- New comment on #37:
  <https://github.com/nawagner/SlopChecker/issues/37#issuecomment-5145628698>
- This session log.
- STATUS.md entry.

No `src/` changes. No tests. No `models.py` change.

## Decisions

1. **#37 is post-MVP, not hackathon-critical.** The runner already degrades
   to gap rows on any exception (`pipeline/runner.py:_collect`); Pangram
   already has its own inline retry loop; the refusal problem the ladder is
   designed for cannot happen with a classifier and there's no chat-model
   check in the tree yet. Priority is a working end-to-end LLM check (#13
   or #11), not a shared ladder for calls that don't exist.

2. **Ladder home: check-invoked `LadderExecutor` (when built).** Check owns
   policy (which rungs, which reframe copy); executor owns mechanism (rung
   order, exception typing, provenance capture). Rejected runner-wrapped
   policy because "try a different prompt" is hard to hoist above the check
   that owns the prompt. Rung objects carry `(label, prompt_fn,
   provider=None)`; provider defaults to caller's client, cross-provider
   rungs override.

3. **Provenance shape: `Finding.evidence["rung"] = "<label>"`.** No
   `models.py` change, no schema version bump. Renderer reads
   `evidence.get('rung')`. Rejected first-class `Finding.rung` because
   ladder is one mechanism among many; doesn't earn a top-level field
   until it has multiple users.

4. **Block on #13 (or #11) first.** With two real callers in the tree,
   extracting a shared `Ladder` becomes a small mechanical refactor of the
   pattern Pangram already demonstrates. Designing against zero callers is
   speculation.

## Dead ends / paths not taken

- **Started brainstorming rung taxonomy and retry composition.** Pulled up
  short: without a concrete LLM call in the codebase, the rung shape is
  speculation. Better to let it emerge from #13's implementation and
  refactor once — the whole reason tls-review-shared's ladder works is
  that they discovered rungs empirically from real refusals.

- **Considered co-designing #37 with #13 or #11 as forcing function.**
  Rejected as too big a scope for a hackathon; better to build the LLM
  check with an inline loop first (following Pangram), then extract.

- **Considered first-class `Finding.rung` on `models.py`.** Rejected as
  schema-version-bump-for-one-user. `evidence` dict is the right home
  until ladder has multiple callers.

## What's left

- Someone builds #13 with an inline `_call_with_retry` (Pangram pattern),
  separates prompt assembly from the call, emits
  `evidence["provider"] / ["model"]`.
- After #13 (and ideally one more), extract shared `Ladder` per the
  decisions above.
- Cross-provider rung config-gated for hackathon (opt-out; single-provider
  is default).

## Notes for the next session on #37

- The comment posted on #37 is the design record; read it before opening
  a design PR. If shape decisions have to change, comment there so the
  ticket has one canonical thread.
- Nothing about this ticket is time-sensitive for hackathon. Do NOT let
  it distract from demo-path work.
