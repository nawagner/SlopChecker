#!/usr/bin/env python3
"""SessionStart hook: surface the transcript-upload consent question.

If no preference is recorded (env SLOPCHECK_TRANSCRIPT or .slopcheck-transcript
file), emit context instructing the session's Claude to ask the user once and
write the answer. Silent otherwise. Always exits 0.
"""

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if os.environ.get("SLOPCHECK_TRANSCRIPT") in ("0", "1"):
        return
    try:
        root = Path(
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=30,
            ).stdout.strip()
            or "."
        )
    except Exception:
        root = Path(".")
    pref = root / ".slopcheck-transcript"
    if pref.is_file() and pref.read_text().strip() in ("0", "1"):
        return
    print(
        "SlopChecker transcript upload: no preference recorded for this "
        "machine. Before starting substantive work, ask the user ONE question: "
        "\"Upload this repo's session transcripts to the public ai-log/ "
        "directory? (They're scrubbed for credential patterns, but will "
        "include anything your personal hooks inject into sessions.)\" "
        "Then write their answer to .slopcheck-transcript at the repo root: "
        "the single character 1 (yes) or 0 (no). The file is gitignored. "
        "Do not re-ask once it exists."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
