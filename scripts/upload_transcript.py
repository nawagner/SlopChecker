#!/usr/bin/env python3
"""Copy the current Claude Code session transcript into ai-log/transcripts/.

Wired up as a project hook in .claude/settings.json:
  Stop       -> copy transcript into the working tree
  SessionEnd -> copy + git add/commit/push (--push)

Best-effort by design: always exits 0 so a logging failure never blocks a
session. OPT-IN: does nothing unless enabled via SLOPCHECK_TRANSCRIPT=1 in
your environment, or a .slopcheck-transcript file (gitignored, content "1")
at the repo root — written by the session after asking you, see
transcript_prompt.py. Personal context injected by your own hooks/memory
would otherwise end up in a public repo.

The repo is public. Obvious credential patterns are scrubbed before the copy,
but scrubbing is best-effort — don't paste secrets into sessions here.
"""

import json
import os
import re
import subprocess
import sys
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
    re.compile(r"(?i)(api[_-]?key|secret|password|token)([\"'\\\s]*[:=][\"'\\\s]*)[A-Za-z0-9\-._]{16,}"),
]


def scrub(text: str) -> str:
    for pat in REDACTIONS:
        if pat.groups:
            text = pat.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", text)
        else:
            text = pat.sub("[REDACTED]", text)
    return text


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], capture_output=True, text=True, timeout=60
    )
    return out.stdout.strip()


def enabled(root: Path) -> bool:
    env = os.environ.get("SLOPCHECK_TRANSCRIPT")
    if env in ("0", "1"):
        return env == "1"
    pref = root / ".slopcheck-transcript"
    return pref.is_file() and pref.read_text().strip() == "1"


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
        git("add", rel)
        git("commit", "-m", f"transcript: {user} {session8}", "--", rel)
        git("pull", "--rebase", "origin", "main")
        git("push", "origin", "main")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # logging must never block a session
    sys.exit(0)
