# 2026-07-31 — #17 budget-feasibility Phase 3 (LLM orchestrator)

**Issue:** #17
**Branch:** `danparshall/17-budget-lens`
**Machine:** Dans-MacBook-Air (`(air)`)
**Session role:** picked up from an in-conversation handoff naming Phase 3 of
`docs/active/17-budget-lens/plans/20260731_budget_feasibility_lens_implementation.md`.

## Purpose

Phase 3 wires the `budget_feasibility` lens (extraction + pairing) to the
US-benchmark evaluator that Phase 2 landed. This session added the LLM
orchestrator + a fake-transport test suite so the check runs end-to-end
under `--tier llm` without any live LLM traffic in CI.

## What landed

**New files in `src/slopchecker/pipeline/budget_feasibility/`:**

- `llm.py` — mirror of `claim_support/llm.py`. Typed transport error
  hierarchy (`TransportError` base + `TransportAuthError`,
  `TransportClientError`, `TransportRateLimit`, `TransportServerError`,
  `TransportRefusal`), `Transport` protocol, and `AnthropicTransport`
  with a lazy `anthropic` SDK import so unit tests never require the SDK
  to be installed. `output_config.format` handles server-side JSON-
  schema validation, matching the pattern locked by #11.
- `prompts.py` — `LENS_OUTPUT_SCHEMA` (a strict JSON schema for the
  lens's Output-format block, `additionalProperties: false` throughout,
  nullable-typed for every field the lens is allowed to emit as `null`)
  and `build_budget_feasibility_prompt(lens, doc_text)`. The user
  message ships the lens's one-shot (its own `### Input` / `### Output`
  from `budget_feasibility.md`) so the model sees exactly the shape
  `test_lenses.py` already exercises.
- `check.py` — the orchestrator. `BudgetFeasibilityConfig`
  (`model`, `max_attempts=3`, `initial_backoff_seconds=0.5`,
  `shortfall_flag_threshold=3.0`) + `BudgetFeasibilityCheck.run`.
  `_call_with_retry` is inline per the #37 design comment; auth/client/
  refusal errors raise immediately, 429/5xx retry with exponential
  backoff. After the LLM call it (a) parses the payload into the
  evaluator's dataclasses (a malformed shape becomes an errored ledger
  row, never a stack trace), (b) runs `match_quote` on every `quote`
  field — items whose quote isn't verbatim-or-minor-variation in
  `doc.text` are dropped along with pairings that reference them, and
  (c) invokes `evaluate_lens_output(verified_out, benchmarks=US_2026,
  shortfall_flag_threshold=...)` to emit findings. Registered via
  `@register(id="budget_feasibility", tier="llm", est_cost_usd=0.03,
  needs_network=True)`.

**Changes to existing files:**

- `src/slopchecker/pipeline/budget_feasibility/__init__.py` — imports
  `check` for the `@register` side effect + re-exports the config /
  check class (mirrors `claim_support/__init__.py`).
- `src/slopchecker/pipeline/registry.py` — added
  `slopchecker.pipeline.budget_feasibility` to `CHECK_PACKAGES` so
  `discover()` picks up the registration.
- `tests/test_budget_feasibility.py` — new orchestrator-tests section
  (10 tests appended after the existing 24 evaluator tests): missing
  API key skips, Meridian end-to-end happy path, benchmark-assumption
  preservation in `Finding.evidence`, hallucinated-quote drops only
  the affected line, transient error retry, retry exhaustion,
  permanent auth error, malformed enum payload, missing required key
  payload, and registry discovery. Uses a `FakeTransport` mirroring
  the `claim_support` test's shape (records every call, asserts
  scripted role alignment, raises exception turns on demand). The
  Meridian payload is loaded from the lens's own `example_output`
  block so any drift in the lens markdown surfaces via
  `test_lenses.py` first (locked upstream), not here.

## Design decisions

- **Quote check uses `match_quote`, not raw `in`.** The lens markdown
  strictly requires verbatim substrings, so a raw `quote in doc.text`
  would satisfy the letter of the rule. But real PDF extraction
  introduces small whitespace jitter, and `claim_support` already sets
  the precedent that `found_verbatim` **or** `found_minor_variation`
  is the acceptable status. Consistency with the sibling LLM check
  won.
- **Payload parse errors go to an errored ledger row, not a stack
  trace.** `output_config.format` enforces the schema server-side but
  CLAUDE.md's "degrade to gaps, never crash" rule means the check
  must survive a fake transport (or a misconfigured provider) that
  bypasses that validation. `_parse_lens_output` runs client-side
  re-validation of the role/category enums so the evaluator never sees
  a shape it can't handle. Two new tests cover this.
- **Ledger surfaces quote drops via `detail`, not a second row.**
  `claim_support` handles per-citation gaps by aggregating them into
  the single ok row's `detail` string. Mirroring that here avoids
  inventing a new ledger-row shape and keeps the report's row count
  legible. The plan doc used the phrase "`lens_quote_unverified`
  coverage-gap row" — read that as "the ledger records the drop in
  some form the reviewer sees", implemented as detail text so the
  wire format matches the sibling check.
- **`role="lens"` is the diagnostic label.** The `Transport.role`
  argument is a per-call debug string, not a wire concept. Using
  `"lens"` here (vs `claim_support`'s `"judge"`/`"refuter"`) lets a
  future shared retry-ladder tell one caller from another. The
  `FakeTransport` asserts against this so a scripted response bound
  to the wrong role blows up loudly instead of silently mis-aligning.
- **`shortfall_flag_threshold` on the config.** Callers can tighten
  or loosen the flag without editing the evaluator; useful when the
  eval on real proposals lands. Default stays 3.0.
- **Existing `(fable)` git identity in the worktree config.** The
  worktree's `.git/config` had `user.name = Dan Parshall (fable)`
  even though this machine's `~/.gitconfig.local` is `(air)`. Prior
  branch commits (655ab67, 7291630, 7412749) all say `(air)`. I
  overrode this commit with `-c user.name="Dan Parshall (air)"` to
  match rather than editing repo config (CLAUDE.md rule: never
  update the git config).

## What didn't land (deferred)

- **Phase 4 — fixtures + manual smoke.** The plan's Meridian +
  reasonable-Meridian fixture pair. Small enough to fit in a follow-up
  commit; skipping keeps this PR reviewable in one sitting.
- **Phase 5 — PR + `harness/README.md` update.** Also next.
- **Live end-to-end test.** Tracked in #130 (deliberately out-of-scope
  for the lens PR).
- **Page-marker injection into the prompt user text.** Right now
  `build_budget_feasibility_prompt` sends `doc.text` as-is. When
  ingested docs don't include `[[page N]]` markers, the lens's page
  numbers won't be reliable. Follow-up: derive markers from
  `FlattenedDoc.page_offsets`. YAGNI for the mocked-transport tests
  (which use `lens.example_input` verbatim, page markers included).

## Verification

- `pytest tests/test_budget_feasibility.py -q` — 34 passed.
- `pytest tests/ -q` — 417 passed, 9 deselected.
- `ruff check` + `ruff format` on new + touched files — clean.
- `mypy` on `src/slopchecker/pipeline/budget_feasibility/` — clean
  (6 source files, no issues).
- RED verified before writing implementation: after the tests-only
  commit, `pytest tests/test_budget_feasibility.py` failed at import
  time on `ModuleNotFoundError: No module named
  'slopchecker.pipeline.budget_feasibility.check'`.

## Coordination note

`project.stated_total_usd` still overlaps with #109's arithmetic remit
(Nick). Field name is unchanged from Phase 2, so no new coordination is
needed at Phase 3, but the merge order still matters — flag stays open.
