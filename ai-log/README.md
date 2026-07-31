# ai-log

Work trail for AI-assisted sessions. See `CLAUDE.md` at the repo root.

- `YYYY-MM-DD-<handle>-<slug>.md` — session logs: issues worked, decisions,
  dead ends, what's left. Written by the session before its final commit.
- `transcripts/` — raw session transcripts (`.jsonl`), auto-uploaded by the
  project hook in `.claude/settings.json`. Scrubbed for obvious credential
  patterns; opt out with `SLOPCHECK_NO_TRANSCRIPT=1`.
