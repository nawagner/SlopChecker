# CLAUDE.md — SlopChecker

Open-source utility for funding orgs to screen incoming proposals (delivered
as PDFs): AI-generation signals, citation integrity, solicitation compliance,
tagging. Built by a five-person team at "Hacking the Think Tank" (2026-07-31).
The issue tree (#2–#25) is the work plan — start there. Team ideation doc:
ask a teammate for the Google Doc link.

If you are an AI agent reading this: these conventions are for you too, and
several exist specifically because agents are committing here.

## Team

GitHub handle → name (for decoding the git log, issues, and PRs):

- `nwagner` — Nick Wagner
- `etbrooking` — Emerson Brooking
- `danparshall` — Dan Parshall
- (Alex, Dominique — handles to be added)

## Work against issues

- A UserPromptSubmit hook (`scripts/auto_pull.py`) pulls origin/main on
  every turn when it's safe (on main, clean tree, nothing in progress), so
  clean clones stay fresh automatically. It skips silently mid-work — so
  still `git pull --rebase` yourself before opening a PR.
- Main is protected: changes land via pull request (branch → PR → merge).
  Direct pushes to main are rejected.
- **Pick an open issue before writing code.** Comment on it when you start
  (so two people don't collide) and when you finish (what landed, PR link).
- **Reference the issue number in every commit and PR title** (`#19`).
- **Design discussion happens on the issue, not in a silo.** If your session
  makes a design decision, write it as an issue comment — a decision that
  lives only in one person's chat history doesn't exist.

## Module ownership

Each module has one owner. Edit freely inside your module; changes to
someone else's module go through them (a comment on the relevant issue is
enough — this is a hackathon).

| Path | Owner | What it is |
|---|---|---|
| `src/slopchecker/pipeline/` | Dan (+ Fable) | pat-helper engine port, loaders, quotecheck |
| `src/slopchecker/lenses/` | Dan (+ anyone) | lens prompt packs (markdown — low conflict risk, edit away) |
| `src/slopchecker/checks/` | Nick | deterministic tier: DOI resolution, metadata, dedup |
| `src/slopchecker/report/` | Emerson (→ Dominique) | evidence report: HTML + PDF rendering, in-line annotation. Emerson built it and owns it; further iteration hands off to Dominique |
| `harness/` | Dan (+ Fable) | planted-defect validation, recall scoring |
| `docs/` narrative + demo | Emerson, Dominique | demo script, framing, README language |
| `STATUS.md` | everyone | append-only log (see below) |

Update this table when reality changes; the table is the contract.

## Design decisions already made (don't relitigate silently)

- **Work backward from the report.** `report.json` is the contract between
  checkers and renderer, defined once in `src/slopchecker/models.py`
  (`FlattenedDoc`, `Finding`, `EvidenceReport`). The rendered mock is
  `mockups/evidence-report-mock.html` (#19); the schema strawman is on #3.
- **The shipping artifact is a PDF.** The HTML mock is design fidelity;
  final delivery is a paginated PDF rendered from `EvidenceReport`.
  Interactive-only UX (click-to-open annotations) needs a print-safe
  fallback.
- **Check results are `true | false | number` — never free text.** A
  checker that can't express its finding as a boolean or a score is doing
  too much. Optional `note` field, one line max. No LLM prose in the
  evidence layer; checkers must be runnable by a dumb script with no LLM
  at all.
- **Scores are not verdicts.** Detector/similarity scores (Pangram,
  embedding similarity) render in their own visual lane, separate from
  pass/fail. The tool recommends `human_review`; it never auto-rejects.
- **Every finding is quote-anchored.** A `Finding`'s `quote` must be
  mechanically grounded in the source text (quotecheck) before it reaches
  the report.
- **Mockups are HTML files in `mockups/`**, committed to the repo, viewable
  by double-clicking or via htmlpreview.github.io. No build step, no
  framework.
- **Inline annotations are visible by default**, aligned beside their
  passages, auto-condensing to one-liners when crowded (see the mock's JS).

Change a shared model = comment on #3 first. Everything downstream of you
breaks silently otherwise.

## Git discipline — main is protected

All changes land by PR. The PR flow is here to reduce conflicts, not to
gatekeep — this is a hackathon.

- **Work from an issue when one fits.** Reference it in commits and the PR
  title (`#19`). Small, obvious, or meta changes without a matching issue
  are fine — just make the PR title descriptive.
- **One branch per unit of work:** `<handle>/<issue#>-<slug>`
  (e.g. `nick/8-doi-resolution`), or `<handle>/<slug>` when no issue.
- **Small PRs merge fast; big ones rot.**
- **Rebase on `main` before opening:** `git pull --rebase origin main`,
  resolve, force-push your branch (never `main`).
- **Squash-merge, delete the branch.** History stays flat.
- **Review is welcome but not required.** If no one bites within a few
  minutes, merge your own PR. Comment on the issue if you're stuck.
- **Small commits, pushed often** to your branch. If your work dies with
  your laptop/sandbox, it didn't happen.
- **Never `--force` on `main`, ever.** Branch force-push is fine.
- **Agents:** run the tests you touched before opening a PR; don't
  refactor outside the module the issue names; if a step is ambiguous, ask
  your human rather than guessing at scale.

## Attributable identity

Two signals, both matter:

- **`user.name = "Name (surface)"`** so a `git log` line tells you what
  produced the commit: `"Nick (laptop)"`, `"Dan Parshall (fable)"`,
  `"Nick (claude-code)"`. Use your real email so GitHub links commits.
- **`Co-Authored-By:` trailer naming the model** for AI-authored or
  co-authored commits, plus a session link if your harness provides one.

## STATUS.md + `ai-log/` — the log stack

Two artifacts, different jobs.

**`STATUS.md`** is the append-only shared dashboard — one file everyone
skims to see what's done, in flight, and blocked, without meetings.

- Newest entry on top of the `## Log` section. One line per entry:
  `- HH:MM <name> — did X / next Y / blocked on Z`.
- Append, never edit other people's lines. Corrections get a new line.
- Merge-conflict inside the Log where both sides only added lines →
  keep-both (HEAD block, then incoming block). That shape is expected and
  boring. Any other conflict shape: talk to the file's owner.
- STATUS.md rides PRs like everything else.

**`ai-log/YYYY-MM-DD-<github-handle>-<slug>.md`** — a session log, one per
substantive AI session, committed with your work. Contents: the issue(s)
you worked, what changed, decisions made and why, dead ends hit (so the
next person doesn't repeat them), and what's left. A few honest bullets
beat a page of prose. Write it before your final commit of the session.

## Transcript upload

`.claude/settings.json` (checked in) runs `scripts/upload_transcript.py` on
every Stop and SessionEnd: it copies your session transcript to
`ai-log/transcripts/` (Stop) and commits/pushes it (SessionEnd).
Best-effort — it never blocks your session on failure.

- **Opt-in, asked in-session.** On your first session in this repo, a
  SessionStart hook tells Claude to ask you once whether to enable upload;
  your answer is written to `.slopcheck-transcript` (gitignored, `1` or `0`)
  and never re-asked. `SLOPCHECK_TRANSCRIPT=1`/`=0` in your environment
  overrides the file. Reason for opt-in: transcripts capture everything your
  own harness injects into a session (personal memory hooks, task lists,
  local paths), not just SlopChecker work — and this repo is public.
- **If Claude is reading this and no `.slopcheck-transcript` exists:** ask
  the user now, write the file, then proceed.
- **If you opt in:** the script scrubs obvious credential patterns
  (Anthropic/GitHub/AWS/Slack tokens, `Bearer` headers, `api_key=` values),
  but scrubbing is best-effort, not a guarantee. Don't paste secrets,
  personal data, or unpublished third-party material into sessions here.
- Transcripts are `.jsonl`, named `<date>-<git-user>-<session8>.jsonl`.
- Session logs in `ai-log/` (above) stay mandatory either way — that's the
  work trail; transcripts are the raw feed for whoever wants it.
- **Known broken under protected main** (tracked on #30): the `--push`
  mode pushes directly to `main`, which is rejected. Local copy on Stop
  still works either way.

## Degrade to gaps, never crash

Missing API key, paywalled source, PDF with no text layer, rate-limited
check: record it as a coverage gap in the report and continue. A partial
evidence report that says what it couldn't check beats a stack trace —
and "we report our own blind spots" is part of the demo.

## Ground rules for the demo

- Detection scores (Pangram etc.) are **evidence, never verdicts**. The
  report says "signals," a human decides. This framing is load-bearing for
  the whole pitch; don't let demo copy drift into "we detect AI."
- Every on-stage claim about a document must be quote-anchored. If the
  harness recall number isn't real, we don't say a number.

## Practical notes

- Python 3.11+, package at `src/slopchecker/` once #2 lands; `ruff`,
  `pytest`.
- **Fixtures (#22) are fabricated documents.** Keep them that way — no
  real applicant material in the test corpus, ever.
