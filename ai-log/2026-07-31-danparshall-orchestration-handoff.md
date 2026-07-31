# 2026-07-31 — Dan (+ Fable) orchestration session: handoff

Session ran ~15:45–16:50 UTC (11:45–12:50 EDT). One orchestrating agent +
five parallel lane agents. This file is the handoff for whoever (human or
agent) picks up next.

## What landed on main this session (12 PRs)

| PR | Issue | What |
|---|---|---|
| #41+#44 | — | CLAUDE.md team handle map (+ typo fix: Nick is `nawagner`) |
| #45 | #3 | `models.py` + `docs/DATA_MODEL.md` — THE contract; read the doc first |
| #46 | #13 | lens format + loader + claims-extraction prompt pack |
| #49 | #19 | CI fix (see gotcha 1) |
| #55 | #4 | `ingest()`: PDF/DOCX/MD/HTML/TXT → FlattenedDoc + sections + ref-region |
| #53 | #5 | check registry (`@register`, one file per check) + tiered runner |
| #63 | #6 | `slopcheck run` CLI (re-land — see gotcha 2) |
| #59 | #7,#10 | citation extraction (APA/Chicago/IEEE) + quote-match engine |
| #52/#62 + this | — | STATUS/housekeeping |

Suite: 126 passed / 12 skipped, ~0.6 s locally, ~30 s in CI. The 12 skips
are optional-dep guards (pymupdf/docx/browser), not failures.

## In flight elsewhere — do not collide

- **#12 Pangram** — another Dan session, in flight now.
- **#22 fixtures** — Alex (`990991A`), draft PRs #48/#54, force-pushes often.
- **R2 doc storage** — Nick's Claude, branch `claude/r2-bucket-doc-storage-*`.
- **#25 demo scenario, #20, #30** — Emerson's queue.
- Worktrees `dan-3-models`, `dan-13-claims`, `dan-4-ingest`, `dan-5-runner`,
  `dan-7-citations` under `.worktrees/` are DONE lanes, kept for reference;
  don't reuse or delete without Dan's say-so.

## Best next work (in rough priority order)

1. **#29 harness** — planted-defect fixtures + measured recall. Demo ground
   rule: no real recall number, no number on stage. Everything it needs is
   now on main. Dan has pat-helper context; ask before designing from scratch.
2. **#58 CLI↔ingest wiring** — small, unblocked, spec'd in the issue; makes
   `slopcheck run proposal.pdf` real end-to-end.
3. **Registry wiring of quote/citation checks** — noted on #7/#10; the checks
   exist as functions, not yet as `@register` entries.
4. **#15 / #23 / #24** — each has a scoping comment (2026-07-31) mapping the
   issue body onto what now exists. #15's trap: lenses aren't runnable until
   #37 (no LLM client) — ship prompt pack + deterministic check only.
5. **#16 compliance** — viable via `IngestResult.find_section()`.

## Gotchas learned the hard way

1. **PDF/CI**: `find_browser()` must prefer real `google-chrome` over snap
   `chromium` (snap confinement rejects /tmp user-data-dir → 60 s hang). Fixed
   in #49 — don't reorder it back. Crashpad flags are load-bearing too.
2. **Stacked PRs**: #56 "merged" but never reached main — base branch wasn't
   deleted so GitHub didn't retarget, and the squash landed on the stack.
   Rules adopted: ALWAYS `gh pr merge --squash --delete-branch`, and verify
   "landed" claims against `origin/main` content (`git show origin/main:path`),
   never against PR state or STATUS.md.
3. **CI required check is live** (`test` via ruleset `mainsaver`): red PRs
   can't merge. Run `ruff format src tests` before pushing — two lane PRs went
   red on format-only diffs.
4. **Tests must be fast + offline.** Dan's explicit requirement. Fabricated
   fixtures only (repo rule), generate binary fixtures in-test, mock network.
5. **STATUS.md**: append-only, corrections are new lines, keep-both on
   both-added conflicts. Main moves every few minutes — pull immediately
   before appending.
6. Alex's handle is *probably* `990991A` but unconfirmed — don't write it
   into the CLAUDE.md map without Dan's confirmation.

## Contract cheat-sheet (for anything new)

- Types: `slopchecker.models` — `FlattenedDoc`, `Finding` (quote-anchored
  `Anchor`), `CheckResult`/`LedgerRow` (status ok|skipped|errored + mandatory
  reason), `EvidenceReport.to_report_dict()` feeds the renderer.
- Results are strictly `bool|int|float`. Findings are evidence, not verdicts.
  `source_unavailable` ≠ `not_found`, skipped ≠ failed — everywhere.
- New check: one file + `@register(...)` returning `CheckOutput`. New lens:
  markdown per `lenses/README.md`; `tests/test_lenses.py` auto-validates it.
- Shared-model changes: comment on #3 first, even though it's closed.
