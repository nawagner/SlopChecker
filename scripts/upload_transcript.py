#!/usr/bin/env python3
"""Copy the current Claude Code session transcript into ai-log/transcripts/.

Wired up as a project hook in .claude/settings.json:
  Stop       -> copy transcript into the working tree
  SessionEnd -> copy + push to the ai-log-uploads branch (--push)

Best-effort by design: always exits 0 so a logging failure never blocks a
session. OPT-IN: does nothing unless enabled via SLOPCHECK_TRANSCRIPT=1 in
your environment, or a .slopcheck-transcript file (gitignored, content "1")
at the repo root — written by the session after asking you, see
transcript_prompt.py. Personal context injected by your own hooks/memory
would otherwise end up in a public repo.

The repo is public. Obvious credential patterns are scrubbed before the copy,
but scrubbing is best-effort — don't paste secrets into sessions here.

Push design (fix for #30): the SessionEnd push targets a dedicated
``ai-log-uploads`` branch instead of the working checkout's branch. It is
built with git plumbing (``hash-object`` + ``read-tree`` + ``commit-tree``)
so the current worktree's HEAD, index, and working tree are never touched
— any session, on any branch (including protected ``main``), can push. On
persistent failure the script drops ``ai-log/UPLOAD_FAILED.txt`` with the
last error so the break is at least visible, since the hook otherwise
swallows stderr.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

REDACTIONS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]{20,}"),
    re.compile(
        r"(?i)(api[_-]?key|secret|password|token)([\"'\\\s]*[:=][\"'\\\s]*)[A-Za-z0-9\-._]{16,}"
    ),
]

UPLOAD_BRANCH = "ai-log-uploads"
PUSH_ATTEMPTS = 3
MARKER_RELPATH = "ai-log/UPLOAD_FAILED.txt"


def scrub(text: str) -> str:
    for pat in REDACTIONS:
        if pat.groups:
            text = pat.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", text)
        else:
            text = pat.sub("[REDACTED]", text)
    return text


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


def enabled(root: Path) -> bool:
    env = os.environ.get("SLOPCHECK_TRANSCRIPT")
    if env in ("0", "1"):
        return env == "1"
    pref = root / ".slopcheck-transcript"
    return pref.is_file() and pref.read_text().strip() == "1"


def push_to_ai_log_uploads(root: Path, dest: Path, rel_path: str, message: str) -> None:
    """Commit ``dest`` at ``rel_path`` on ``ai-log-uploads`` and push it.

    Uses git plumbing so the current HEAD, index, and working tree are
    untouched. Retries on push race (re-fetch + rebuild + push). On
    persistent failure writes ``ai-log/UPLOAD_FAILED.txt`` with the last
    error, since the hook wrapper swallows stderr.
    """
    marker = root / MARKER_RELPATH
    remote_ref = f"refs/remotes/origin/{UPLOAD_BRANCH}"

    # Hash the transcript into the object database. This does not touch
    # the working index — the file is only referenced by SHA from here on.
    blob = git("hash-object", "-w", str(dest))
    if not blob:
        _mark_failed(marker, "hash-object returned empty output")
        return

    push_result: subprocess.CompletedProcess[str] | None = None
    for _attempt in range(PUSH_ATTEMPTS):
        # Refresh our view of the remote branch. If the branch doesn't
        # yet exist on origin, fetch exits 0 without setting the ref — we
        # handle that below and start the branch from scratch.
        subprocess.run(
            ["git", "fetch", "origin", UPLOAD_BRANCH],
            capture_output=True,
            text=True,
            timeout=60,
        )
        remote_exists = (
            subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", remote_ref],
                capture_output=True,
                text=True,
            ).returncode
            == 0
        )

        # Build the new tree in a throwaway index so the real index the
        # user is editing is never touched.
        tmp_index_fd, tmp_index_path = tempfile.mkstemp(prefix="slopcheck-idx-")
        os.close(tmp_index_fd)
        # read-tree wants a valid or absent index file; mkstemp leaves a
        # zero-byte file that git treats as corrupt, so remove it first.
        Path(tmp_index_path).unlink(missing_ok=True)
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = tmp_index_path
        try:
            if remote_exists:
                subprocess.run(
                    ["git", "read-tree", remote_ref],
                    env=env,
                    check=True,
                    capture_output=True,
                )
            subprocess.run(
                [
                    "git",
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"100644,{blob},{rel_path}",
                ],
                env=env,
                check=True,
                capture_output=True,
            )
            new_tree = subprocess.run(
                ["git", "write-tree"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        finally:
            Path(tmp_index_path).unlink(missing_ok=True)

        commit_args = ["git", "commit-tree", new_tree, "-m", message]
        if remote_exists:
            commit_args += ["-p", remote_ref]
        new_commit = subprocess.run(
            commit_args, check=True, capture_output=True, text=True
        ).stdout.strip()

        push_result = subprocess.run(
            ["git", "push", "origin", f"{new_commit}:refs/heads/{UPLOAD_BRANCH}"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if push_result.returncode == 0:
            marker.unlink(missing_ok=True)
            return

    err = (push_result.stderr if push_result else "").strip() or "unknown push error"
    _mark_failed(marker, err)


def _mark_failed(marker: Path, err: str) -> None:
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            f"Transcript upload failed after {PUSH_ATTEMPTS} attempt(s).\nLast error:\n{err}\n"
        )
    except Exception:
        pass


def main() -> None:

    payload = json.load(sys.stdin)
    src = Path(payload.get("transcript_path", ""))
    if not src.is_file():
        return

    root = Path(git("rev-parse", "--show-toplevel") or ".")
    if not enabled(root):
        return
    dest_dir = root / "ai-log" / "transcripts"
    dest_dir.mkdir(parents=True, exist_ok=True)

    user = re.sub(r"[^A-Za-z0-9_\-]", "", git("config", "user.name") or "unknown") or "unknown"
    session8 = (payload.get("session_id") or "nosession")[:8]
    dest = dest_dir / f"{date.today().isoformat()}-{user}-{session8}.jsonl"

    dest.write_text(scrub(src.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")

    if "--push" in sys.argv:
        rel = dest.relative_to(root).as_posix()
        push_to_ai_log_uploads(
            root=root,
            dest=dest,
            rel_path=rel,
            message=f"transcript: {user} {session8}",
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # logging must never block a session
    sys.exit(0)
