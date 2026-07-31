#!/usr/bin/env python3
"""UserPromptSubmit hook: keep the clone fresh without yanking work in flight.

Five people commit in parallel; a clone goes stale within minutes. This pulls
--rebase from origin/main on every turn, but ONLY when it's safe:
  - current branch is main
  - working tree is clean
  - no rebase/merge in progress
Any other state: silently skip. Best-effort, always exits 0.
"""

import subprocess
import sys
from pathlib import Path


def git(*args: str, timeout: int = 20) -> str:
    out = subprocess.run(
        ["git", *args], capture_output=True, text=True, timeout=timeout
    )
    return out.stdout.strip()


def main() -> None:
    if git("rev-parse", "--abbrev-ref", "HEAD") != "main":
        return
    if git("status", "--porcelain"):
        return  # local work in flight — never rebase under it
    gitdir = Path(git("rev-parse", "--git-dir") or ".git")
    if any((gitdir / n).exists() for n in ("rebase-merge", "rebase-apply", "MERGE_HEAD")):
        return
    git("pull", "--rebase", "--quiet", "origin", "main", timeout=45)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
