# Contributing

This is a hackathon project (five people, one week) — the process below
is meant to reduce collisions, not gatekeep. Full team conventions,
module ownership, and design decisions already made live in
[`CLAUDE.md`](CLAUDE.md); this file is the shorter "how do I get set up
and land my first change" version. If the two ever disagree, `CLAUDE.md`
wins.

## Setup

```bash
pip install -e ".[dev,pdf,docx]"    # add ,llm ,web ,harness as needed
cp .env.example .env                # optional — see README's "API keys"
ruff check .
pytest
```

## Pick up work

1. **Start from an open issue** — the issue tree (#2–#25, plus later
   ones) is the work plan. Check `CLAUDE.md`'s module ownership table
   first if the issue touches someone else's module.
2. **Comment on the issue when you start** ("Claiming — ...") so two
   people don't collide, and comment again when you finish with what
   landed and the PR link.
3. **One branch per unit of work:** `<handle>/<issue#>-<slug>`, e.g.
   `nick/8-doi-resolution`.
4. **Reference the issue number** in commits and the PR title (`#19`).

## Before opening a PR

- Run the tests you touched, at minimum. `pytest -m integration` runs the
  slower full-CLI-chain suite separately (skipped by default).
- `ruff check .`
- Rebase on `main`: `git pull --rebase origin main`, resolve conflicts,
  force-push your branch (never `main` — direct pushes to `main` are
  rejected; branch force-push is fine).
- Append a line to `STATUS.md`'s `## Log` (newest on top) and, for any
  substantive AI session, add `ai-log/YYYY-MM-DD-<handle>-<slug>.md`
  covering what changed, decisions made and why, and dead ends hit.

## Merging

Small PRs merge fast; big ones rot. Review is welcome but not required —
if no one bites within a few minutes, merge your own PR. Squash-merge,
delete the branch.

## Ground rules worth repeating here

- **Check results are `true | false | number`, never free text** — see
  `docs/DATA_MODEL.md`. A checker that can't express its finding as a
  bool or a score is doing too much.
  Scores are evidence, never verdicts — the tool recommends
  `human_review`, it never auto-rejects.
- **Every finding is quote-anchored** — mechanically grounded in the
  source text before it reaches the report.
- **Degrade to gaps, never crash.** Missing API key, paywalled source, no
  text layer: record it as a coverage gap and continue.
- **Fixtures are fabricated, always.** No real applicant material in the
  test corpus, ever (#22).
- **Changing a shared model** (`src/slopchecker/models.py`) — comment on
  #3 first; everything downstream breaks silently otherwise.

## Attribution

Commits should carry a real, attributable identity — not a generic bot
identity — so `git log` and GitHub both show who produced the change:
`git config user.name "Name (surface)"` (e.g. `"Nick (claude-code)"`) with
your real email. AI-authored or co-authored commits also carry a
`Co-Authored-By:` trailer naming the model. See `CLAUDE.md` for the full
rationale, including the session-transcript logging setup.
