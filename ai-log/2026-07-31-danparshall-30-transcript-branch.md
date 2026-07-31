# 2026-07-31 — #30 transcript-upload lands on ai-log-uploads

**Issue:** #30 — SessionEnd's `upload_transcript.py --push` targeted the
session's current branch (usually `main`), which the `mainsaver` ruleset
protects, so every push was silently rejected. The script is best-effort
(always exits 0, `2>/dev/null` in `settings.json`), so the break was
invisible: transcripts stopped reaching the repo without any error trail.

## What landed

- `scripts/upload_transcript.py` — replaced the `git add` / `commit` /
  `pull --rebase main` / `push main` chain with a `push_to_ai_log_uploads`
  helper that:
  1. Hashes the transcript into the object DB (`git hash-object -w`).
  2. Fetches `origin ai-log-uploads` (idempotent — silently no-ops if the
     branch doesn't yet exist).
  3. Builds the new tree in a **throwaway index** (`GIT_INDEX_FILE=$tmp`)
     seeded with the existing branch's tree (or empty) plus the new blob.
  4. `commit-tree` with `origin/ai-log-uploads` as parent (or no parent
     if the branch is being created).
  5. Pushes the new commit to `refs/heads/ai-log-uploads` on origin.
  6. Retries up to 3× on push race (re-fetch + rebuild).
  7. On persistent failure writes `ai-log/UPLOAD_FAILED.txt` with the
     last stderr, so future breaks are visible in the working tree
     without needing to un-swallow stderr.
  8. A successful push clears any stale marker.

- `tests/test_upload_transcript.py` — new, 7 tests over a bare-repo
  fixture: create branch, append to existing, don't move HEAD/index/wd,
  don't touch `main`, marker on failure, clear marker on success, Stop
  copy still works. All 7 written RED-first (6 failed under old script,
  the Stop-copy test passed unchanged).

- `CLAUDE.md` — "Transcript upload" section: the "Known broken under
  protected main (tracked on #30)" bullet is gone. Added a note about
  the new `ai-log/UPLOAD_FAILED.txt` marker.

## Design decisions

- **Plumbing, not `git worktree` for uploads.** Considered spinning up a
  hidden `ai-log-uploads` worktree per-push, but that's slow, disk-heavy,
  and races between concurrent sessions. `hash-object`/`read-tree`/
  `commit-tree` never touches HEAD, index, or the working tree — so
  every session on every branch (feature branches, other worktrees,
  detached HEADs) can push without interfering with the user's edits.
- **Kept the `2>/dev/null` in `settings.json`** — that's fix #3 on the
  issue, and it affects everyone's session UX. The marker file gets us
  the visibility win without that scope. If someone wants to remove it
  in a follow-up, the marker still catches everything either way.
- **Retry count = 3** — a race lasts one round-trip; 3 attempts covers
  even a burst of concurrent sessions ending at the same second.
- **Local `ai-log/transcripts/` files stay untracked on your branch.**
  They only land on `ai-log-uploads` remotely. If you accidentally
  `git add .`, they'd still get staged — same risk as before, no worse.
  A follow-up could gitignore them on non-`ai-log-uploads` branches,
  but that's separate scope.

## Not done

- Fix #2 in the isolated form ("marker file") is subsumed by the marker
  logic here — it's live.
- Fix #3 ("drop `2>/dev/null` from `settings.json`") — deliberately
  skipped. Touches everyone's hook UX; belongs in its own PR after
  people notice the marker isn't enough.
- The `ai-log-uploads` branch is created on the first real SessionEnd
  after merge — no manual bootstrap needed.

## Verification

- 431 tests pass (was 424 baseline + 7 new). `pytest -m 'not integration'
  --ignore=tests/test_web.py` — `test_web.py` errors on a pre-existing
  `httpx`/`starlette` mismatch unrelated to this PR.
- `ruff check` clean on both changed files.
- Fake-remote fixture is a bare `git init --bare` + `git clone`, so the
  push semantics are identical to what GitHub sees.
