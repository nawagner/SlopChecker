# 2026-07-31 — etbrooking (Claude Fable 5) — report mock + AI conventions

**Issues worked:** #19, #3 (comments), plus repo conventions (no issue).

## What changed

- `mockups/evidence-report-mock.html` — evidence report mock, built working
  backward from the output (a16e48b, adbaa47). Genius-style inline annotations,
  visible by default, aligned beside their passages, auto-condensing to
  one-liners when the stack overflows the column. All check results render as
  YES/NO or bare scores; `report.json` stub at the bottom is the implied schema.
- Commented the `Finding` schema strawman on #3: `result: bool | float` only,
  `anchor` = page + quote span.
- `CLAUDE.md`, `.claude/settings.json`, `scripts/upload_transcript.py`,
  `ai-log/` — team conventions for AI sessions + transcript auto-upload hook
  (Nick's real-time ask). Scrubs obvious credential patterns; opt out with
  `SLOPCHECK_NO_TRANSCRIPT=1`.

## Decisions

- Checks emit no prose (bool/float + optional one-line note) so checkers can be
  dumb scripts; human framing lives in the renderer.
- Scores (Pangram, similarity) get a separate visual lane from pass/fail —
  the report never presents a detector score as a verdict.
- Click-only annotation interaction (no hover) — survives touch and projectors.
- Transcript upload is on by default but documented as best-effort scrubbing on
  a public repo; team should decide consciously whether to keep it on.

## Dead ends

- `gh` CLI isn't on PATH in Git Bash on my machine; plain `git` + stored
  credentials works fine for pushing.
- GitHub won't render committed HTML — use
  `https://htmlpreview.github.io/?<blob-url>` for sharable previews.
- IFP's internal slop-screening tool: searched, not public, no repo or writeup.
  Whoever has the IFP contact should just ask them for their heuristics list.

## Left to do

- Turn the mock into the real `report.json → HTML` renderer once #3's models
  land (closes #19).
- Batch summary view (#20) can reuse the mock's ledger table styling.
