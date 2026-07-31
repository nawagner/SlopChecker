# SlopChecker — conventions for Claude (and other AI) sessions

Open-source utility for funding orgs to screen incoming proposals: AI-generation
signals, citation integrity, solicitation compliance, tagging. Built by a
five-person team at the "Hacking the Think Tank" hackathon (2026-07-31).
Team ideation doc: ask a teammate for the Google Doc link. The issue tree
(#2–#25) is the work plan — start there.

## Work against issues

- Pick an open issue before writing code. Comment on it when you start (so two
  people don't collide) and when you finish (what landed, commit SHA).
- Reference the issue number in every commit message (`#19`).
- Design discussion happens on the issue, not in a silo. If your session makes
  a design decision, write it as an issue comment — a decision that lives only
  in one person's chat history doesn't exist.

## Design decisions already made (don't relitigate silently)

- **Work backward from the report.** `report.json` is the contract between
  checkers and renderer. The rendered mock is `mockups/evidence-report-mock.html`
  (#19); the schema strawman is on #3.
- **Check results are `true | false | number` — never free text.** A checker
  that can't express its finding as a boolean or a score is doing too much.
  Optional `note` field, one line max. No LLM prose in the evidence layer;
  checkers must be runnable by a dumb script with no LLM at all.
- **Scores are not verdicts.** Detector/similarity scores (Pangram, embedding
  similarity) render in their own visual lane, separate from pass/fail. The
  tool recommends `human_review`; it never auto-rejects.
- **Mockups are HTML files in `mockups/`**, committed to the repo, viewable by
  double-clicking or via htmlpreview.github.io. No build step, no framework.
- **Inline annotations are visible by default**, aligned beside their passages,
  auto-condensing to one-liners when crowded (see the mock's JS).

## Show your work (mandatory)

Every substantive AI session leaves two artifacts:

1. **A session log**, committed with your work:
   `ai-log/YYYY-MM-DD-<github-handle>-<slug>.md` containing: the issue(s) you
   worked, what changed, decisions made and why, dead ends hit (so the next
   person doesn't repeat them), and what's left. A few honest bullets beat a
   page of prose. Write it before your final commit of the session.
2. **Commit attribution.** AI-authored or co-authored commits carry a
   `Co-Authored-By:` trailer naming the model, and a session link if your
   harness provides one.

## Transcript upload (Nick's real-time ask)

`.claude/settings.json` (checked in) runs `scripts/upload_transcript.py` on
every Stop and SessionEnd: it copies your session transcript to
`ai-log/transcripts/` (Stop) and commits/pushes it (SessionEnd). Best-effort —
it never blocks your session on failure.

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

## Practical notes

- Python 3.11+, package at `src/slopchecker/` once #2 lands; `ruff`, `pytest`.
- Don't push directly to files someone else's issue owns without a heads-up
  comment. Mockups and `ai-log/` are append-friendly; core models (#3) get
  discussed first.
- Fixtures (#22) are fabricated documents. Keep them that way — no real
  applicant material in the test corpus, ever.
