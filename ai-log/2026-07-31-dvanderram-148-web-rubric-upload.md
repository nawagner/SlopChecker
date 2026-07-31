# 2026-07-31 — Dominique — #148 web rubric upload

Issue: #148 (backend `web.py` handed to me explicitly, frontend in my #74 lane).
Refs #90 (architecture), #145 (pipeline slice), #149 (the rendering this makes
reachable from the web), #27 (web infra).

## What changed

- `src/slopchecker/web.py`: `POST /check` gains an optional `rubric` multipart
  field. Read/validate/ingest is now one helper used by both fields, so the
  rubric gets the same 413/422 contract as the proposal. `ctx.rubric` is set
  the way `cli.py` sets it, and `report.solicitation` is stamped from the
  rubric's (flattened) filename.
- `worker/public/index.html`: an "Attach your solicitation — optional" row
  inside the existing upload form, its own hidden file input, the no-rubric
  coverage-gap copy stated up front, and `rubric` appended to the existing
  `FormData` only when a file is chosen. Error copy distinguishes the two
  files.
- `src/slopchecker/pipeline/checks_rubric.py`: gap reason no longer names a CLI
  flag (see below).
- `src/slopchecker/report/html.py`: one-character fix from #149 — the space
  between an evidence caption and its source filename.
- Tests: 7 new in `tests/test_web.py`; 3 updated for the reason string.

## Decisions and why

- **One upload, not two steps.** The rubric row lives inside the same `<form>`
  as the proposal, under a rule. A separate box would imply a separate action
  and a separate result.
- **The no-rubric state says what it costs, before you run.** "Nothing
  attached — compliance is reported as unchecked, not passed." The gap row in
  the report is honest but arrives too late to change what you uploaded.
- **Errors name the field, but only the secondary one.** The API prefixes the
  rubric's failures with `rubric: ` and leaves the proposal's messages exactly
  as they were — the proposal is the subject of the request, so naming it adds
  nothing. The page turns the prefix into "Couldn't read your solicitation: …"
  rather than printing a field name at a funder.
- **Drag-and-drop still means "the proposal."** With two inputs a drop is
  ambiguous; guessing wrong would silently check the RFP as if it were the
  submission.
- **CLI parity over local tidiness.** `ctx.solicitation` stays `None` when only
  a rubric is supplied, matching `cli.py` (which fills it only from an explicit
  `--solicitation`). The stamp lives on `report.solicitation`. Two surfaces
  that disagree about what checks see would be a bug nobody finds until a
  rubric-dependent check reads `ctx.solicitation`.
- **`build_context([doc])` rather than a bare `CheckContext()`.** It's the
  documented constructor and populates `batch`; the similarity check still
  reports its own gap at batch size 1.

## Copy change outside my module (flagged)

`checks_rubric.py` returned `no rubric supplied (--rubric) — not checked
against a solicitation`. That row is now read by funders on the website, where
`--rubric` names nothing they can see. Changed to `no solicitation or rubric
supplied — compliance not checked`, which is true on both surfaces. `pipeline/`
is Emerson's; noted on #148 and #149, and trivially revertable — three tests
assert the string and one now asserts the flag is *absent*.

## Verified

Real browser against a local uvicorn + static server (scratchpad script mounting
`worker/public` and proxying `/api`, mirroring the Worker), driving the actual
form JS rather than TestClient:

- Both files → report with the two-quote pair, `Checked against:
  aldergrove-community-climate-rfp.md`, `rubric_budget_ceiling` NO.
- Proposal only → 200, skipped compliance row, no solicitation stamp.
- `.exe` rubric → 422 shown as "Couldn't read your solicitation: unsupported
  format '.exe' — supported: …", Run re-enabled.
- Dark mode and 375px: no horizontal overflow, controls stack, ghost button
  legible on the dark panel.
- `tests/test_web.py` 13 passed; full suite 581 passed with the same 7
  pre-existing `test_upload_transcript.py` failures (this laptop's git predates
  `git init -b`; identical on clean `main`). `ruff` clean.

## Left open

- The issue's last acceptance box — "verified once on slop-checker.com" — needs
  the Railway + Worker deploy, which I can't do from here. The Worker itself
  needs no change: `/api/*` is proxied as `fetch(new Request(upstream,
  request))`, so multipart with two parts passes through untouched.
- Still the #149 leftover: `demo-report.html` renders from
  `tests/fixtures/sample_report.json` and so has no rubric finding to show.

## Dead ends

- Setting `ctx.solicitation` from the rubric filename felt tidier and was
  wrong — see CLI parity above.
- The in-app preview can't screenshot `file://` paths outside the project, and
  the upload flow needs a live API anyway; the local proxy script was the
  cheaper route than pointing the page at Railway.
