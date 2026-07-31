# 2026-07-31 — #144 claims lens sensitivity tuning

Session: Dan + Fable (CLI). Branch `danparshall/144-claims-lens`.

## Issue

#144 (filed this session): the claims lens tagged pure meta-discourse in a
filler blog post as `prior-work` claims on the live site — "The takeaways
are meant to inform, not to prescribe. ... The discussion draws on
established population methods and current data." rendered as red failed
checks.

## What landed

1. **Lens cache key includes the prompt payload** (`lens_runtime._cache_key`).
   Was `(model, lens.id, doc.text)` — a tuned prompt kept serving pre-tune
   payloads from disk/KV caches until TTL. Found before tuning, luckily.
2. **Claims lens v0.3** (`lenses/claims.md`): specificity gate ("commits to
   something checkable"), hard exclusions for meta-discourse and vague
   gestures at evidence, `{"claims": []}` legitimized, and — Dan's design —
   a `scope: background | specific` field: background = context-setting
   generalization no reviewer would demand a citation for; specific =
   narrow assertion borrowing evidential authority. Hyperbole is
   explicitly `specific` (universal/guaranteed assertions are falsifiable).
3. **Scope-aware mapping** (`checks_llm.py`) — **raced Emerson's #147.**
   We independently found the same problem (every claim rendering as a red
   card; `quant_unsourced=true`, the #13 red flag, rendering as a *green
   YES* chip). His fix (flagged-claims-only, single `quant_claim_sourced:
   NO` check, silence otherwise) merged to main mid-session; his design
   comment went to #13 while ours went to #144, so neither session saw the
   other until rebase. Reconciled as a synthesis (Dan's call): #147's
   silence policy + False-is-the-flag polarity, flag generalized to
   `uncited && specific && needs-a-source` (prior-work or quantitative).
   Uncited non-quant promises (outcome/timeline/capability) stay silent —
   you can't cite your own future work. Labels "Unsourced quantitative
   claim" / "Uncited prior-work claim"; check renamed `claim_sourced`.
   Background claims produce no Finding at all (ledger-only). New ledger
   count `claims_specific_uncited` beside `claims_quant_unsourced`.
4. **Whitespace-tolerant quote anchoring + visible drops**
   (`lens_runtime._quote_anchor`): eval sweeps showed whole runs returning
   `ok` with 0 claims on hard-wrapped fixtures — model rewraps a sentence
   with spaces, byte-exact substring check fails, every claim silently
   drops (observed `15/0/15`, `21/22/0` across repeats, incl. missed
   planted defects). Quotes now rescue via `\s+`-flexible match rewritten
   to the matched source bytes (verbatim contract holds); residual drops
   are counted (`unanchored_claims`) and surface as a skipped
   `claims_unanchored` gap row.

## Eval (lens-eval/)

Checkpointed, resume-safe before/after harness: 18 synthetic corpus `.md`
docs + the PDF rendition of the screenshot doc + both `pending_lens:claims`
harness defects injected (65%-no-citation, misattributed-[1]), triple runs
on variance-critical docs, `claude-opus-5`, no cache. Results in
`lens-eval/results.jsonl` (append-only, conditions per row).

Key numbers (round 2, v0.1 → v0.3, pre-anchoring-fix): filler blog/think-tank
docs 2–5 claims → 0–3 (meta-discourse gone; planted overclaims retained);
grant apps roughly halve; screenshot-repro PDF 0/1/0 → 0/0/0; both planted
defects still caught in runs unaffected by the anchor-drop bug. Round 3
(post-fix, r2 labels) numbers in results.jsonl — see PR for the final table.

## Dead ends / traps

- **First eval recorder whitelisted claim fields and silently dropped
  `scope`** — cost a re-run. In a session about silent data loss.
- **Eval baseline extracted from `HEAD` went stale when the tuning commits
  landed** — round-3 rows labeled `v0.1r2` actually ran the v0.3 lens.
  Caught via the per-row `lens_sha` (record conditions with results — it
  works). Baseline now pinned to `merge-base(HEAD, origin/main)`; rows
  kept and documented in lens-eval/README.md, usable as extra v0.3
  replicates.
- BSD sed doesn't do `\b`; Edit tool instead.
- `blog_post__ai_clean.md` extracts clean (0/0/0) on v0.1 locally — the
  live failure only reproduces on the **PDF** rendition (line-broken text,
  no headings). Format matters; eval PDFs, not just markdown.
- v0.1 run-to-run variance is severe (`21/22/0` on the same doc) — the
  0-run was mass anchor-drop, not model mood. Relevant to #107.

## Open / handed off

- @etbrooking: sanity-check the flag generalization (#13/#144) — his #147
  quant-only flag became `prior-work || quantitative`; renderer untouched.
- Two-sessions-one-file lesson: his design comment went to #13, ours to
  #144, and the first cross-visibility was a rebase conflict. Worth a
  glance at open PR titles before starting on a shared module, even for
  its owner.
- #107 (stability eval) can grow from `lens-eval/run_eval.py`.
- Other lenses (Dan said "lenses", plural) not yet touched — this session
  built the pattern: tune prompt → eval before/after → check planted-defect
  recall.
