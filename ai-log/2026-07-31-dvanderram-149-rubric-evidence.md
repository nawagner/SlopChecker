# 2026-07-31 — Dominique — #149 render rubric evidence

Issue: #149 (report module). Refs #145 (data shape), #90 (rubric concept),
#19 (report), #74 (palette).

## What changed

`src/slopchecker/report/` only.

- `html.py`: two-quote evidence pair in the finding card, an opt-in evidence
  rendering table, `Checked against:` in the header facts, and a
  `CHECK_LABELS` entry for `rubric_budget_ceiling` (it was falling back to
  `rubric budget ceiling` from the underscore split).
- `assets/report.css`: `.ev` / `.ev-q` / `.ev-cap` / `.ev-src` / `.v-fact`,
  plus a print rule keeping a pair whole on one page.
- `tests/test_report_html.py`: six tests over a report shaped like a real
  `rubric_budget_ceiling` violation.
- `worker/public/demo-report.html`: regenerated via the renderer.

## Decisions and why

- **Stacked, not side by side.** The rail is 22rem. Two columns at ~10rem each
  re-wrap both quotes into ragged fragments, which is the opposite of "read
  the funder's own sentence".
- **The proposal side repeats `anchor.quote`.** It's already marked in the
  document body, so on screen this is a duplication. In print the rail lands
  *after* the document — without the repeat the card asserts a comparison
  whose other half is pages away. Print is the shipping artifact, so print
  wins.
- **The pair survives rail condensing; the kv table still doesn't.** The
  one-line summary can stand in for a kv table. It can't stand in for a
  quotation, and clamping a quote to two lines would misrepresent evidence.
  Cost: a condensed rail is a few rem taller per evidence-bearing finding.
  If a document ever produces many of them at once this may need revisiting —
  the placer handles the overlap, it just pushes the stack down.
- **`evidence` renders by opt-in, never as a dict dump** (the general rule the
  issue asked for). `_EV_QUOTES` maps an evidence key to a caption plus the
  key naming the document it was quoted from; `_EV_FIELDS` maps keys to a
  label and a formatter. Unregistered keys render nowhere in the card and stay
  visible in the embedded report.json, so nothing is hidden — it just isn't
  presented as if a reader needed it. Adding a check with evidence worth
  showing = adding a row.
- **The two numbers are colourless (`.v-fact`).** They're inputs to the check,
  not results. A `$90,000` tinted with `--no` in the same column as `NO` reads
  as a second failing check.
- **Header silent without a solicitation.** The skipped `rubric_budget_ceiling`
  ledger row already says "not checked against a solicitation"; saying it
  twice in two voices invites them to drift apart.
- **Borders, not background stripes, for the two rules.** Chrome drops
  backgrounds in a normal browser print unless `print-color-adjust: exact`;
  borders always print. So the blue/red distinction survives a funder hitting
  Cmd+P, not just our headless pipeline.

## Verified

- Light and forced-dark render of the real climate run (`--rubric`
  `aldergrove-community-climate-rfp.md`) — pair legible in both, `--soft`
  caption on `--panel` is the contrast pair already cleared in #74.
- Real PDF via `report/pdf.py`: pair intact on one page with the kv table
  restored beneath it.
- Negative case (`slopcheck run` with no `--rubric`): header omits
  `Checked against`, no `.ev` block, ledger row reads
  `SKIPPED — no rubric supplied (--rubric) — not checked against a solicitation`.
- `tests/test_report_html.py` 30 passed; full suite 549 passed with 7
  pre-existing `test_upload_transcript.py` failures that reproduce on clean
  `origin/main` (this laptop's git predates `git init -b`). `ruff check` and
  `ruff format --check` clean.

## Left open

- `worker/public/demo-report.html` renders from `tests/fixtures/sample_report.json`,
  which has no rubric finding — so the landing-page specimen picks up the CSS
  and the header line but not the two-quote moment. Making it show means
  either adding a `rubric_budget_ceiling` row + finding to that fixture (four
  `worker/test/*.ts` files and `test_models` import it; `docs/DATA_MODEL.md`
  calls it the canonical instance) or repointing the specimen at the climate
  run, which changes which document the landing page shows. Asked on #149
  instead of deciding it inside this PR.
- The skipped reason contains CLI jargon — `no rubric supplied (--rubric)` —
  in a report a funder reads. It lives in `pipeline/checks_rubric.py`
  (Emerson's), and rewriting checker reasons in the renderer would be exactly
  the prose synthesis the evidence layer forbids. Flagged on #149.

## Dead ends

- Hiding the pair when the rail condenses (the first implementation, mirroring
  `.kv`). Screenshotting the real climate run showed the result: 15 findings
  condense the rail, so the demo moment was invisible until clicked. Reversed.
- The in-app browser preview can't screenshot files outside the project
  folder; headless Chrome `--screenshot` against a scratchpad file works, and
  forced dark mode is easiest by rewriting `@media (prefers-color-scheme: dark)`
  to `@media all` in a throwaway copy.
