"""Tests for scripts/upload_transcript.py — SessionEnd hook push behavior.

Regression coverage for #30: pushes must land on `ai-log-uploads` without
touching the current worktree's HEAD/index/working tree, so protected `main`
never blocks them. The script is best-effort (always exits 0), so silent
breakage was invisible in production — these tests are the alarm.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "upload_transcript.py"


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _make_fake_setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a fake bare 'origin' remote, a local clone, and a transcript file.

    Returns (bare_remote_path, local_repo_path, transcript_source_path).
    """
    remote = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
    )

    local = tmp_path / "local"
    subprocess.run(
        ["git", "clone", str(remote), str(local)],
        check=True,
        capture_output=True,
    )
    _git(local, "config", "user.email", "test@example.com")
    _git(local, "config", "user.name", "Tester")

    # Seed with an initial commit so main exists on remote.
    (local / "README.md").write_text("seed\n")
    _git(local, "add", "README.md")
    _git(local, "commit", "-m", "seed")
    _git(local, "push", "origin", "main")

    # Opt in to transcript upload for this fake repo.
    (local / ".slopcheck-transcript").write_text("1\n")

    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type":"user","content":"hello"}\n')

    return remote, local, transcript


def _run_script(
    local: Path, transcript: Path, session_id: str = "abcdef012345", push: bool = True
) -> subprocess.CompletedProcess[str]:
    payload = json.dumps(
        {"transcript_path": str(transcript), "session_id": session_id}
    )
    args = [sys.executable, str(SCRIPT)]
    if push:
        args.append("--push")
    # Isolate from any ambient SLOPCHECK_TRANSCRIPT the developer's shell has set.
    env = {k: v for k, v in os.environ.items() if k != "SLOPCHECK_TRANSCRIPT"}
    return subprocess.run(
        args,
        cwd=local,
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def test_stop_copy_still_works_without_push(tmp_path: Path) -> None:
    """No --push flag should still copy the transcript locally (Stop-hook path)."""
    _remote, local, transcript = _make_fake_setup(tmp_path)

    result = _run_script(local, transcript, push=False)
    assert result.returncode == 0, result.stderr

    dest_dir = local / "ai-log" / "transcripts"
    assert dest_dir.is_dir()
    files = sorted(dest_dir.glob("*.jsonl"))
    assert len(files) == 1
    assert files[0].read_text() == '{"type":"user","content":"hello"}\n'


def test_pushes_to_ai_log_uploads_branch_when_branch_doesnt_exist(
    tmp_path: Path,
) -> None:
    """Fresh remote — no ai-log-uploads branch yet. Script must create it."""
    remote, local, transcript = _make_fake_setup(tmp_path)

    result = _run_script(local, transcript, push=True)
    assert result.returncode == 0, result.stderr

    branches = _git(remote, "branch", "--list")
    assert "ai-log-uploads" in branches, f"branch missing on remote: {branches!r}"

    files = _git(remote, "ls-tree", "-r", "--name-only", "ai-log-uploads").splitlines()
    assert any(
        f.startswith("ai-log/transcripts/") and f.endswith(".jsonl") for f in files
    ), f"transcript not found in tree: {files}"


def test_pushes_appended_when_branch_already_exists(tmp_path: Path) -> None:
    """Second push should preserve prior transcripts on ai-log-uploads."""
    remote, local, transcript = _make_fake_setup(tmp_path)

    _run_script(local, transcript, session_id="aaaaaaaa11111111", push=True)

    transcript2 = tmp_path / "session2.jsonl"
    transcript2.write_text('{"type":"user","content":"world"}\n')
    result = _run_script(local, transcript2, session_id="bbbbbbbb22222222", push=True)
    assert result.returncode == 0, result.stderr

    files = _git(remote, "ls-tree", "-r", "--name-only", "ai-log-uploads").splitlines()
    transcripts = [f for f in files if f.startswith("ai-log/transcripts/")]
    assert len(transcripts) >= 2, f"expected two transcripts, got {transcripts}"


def test_does_not_modify_current_head_index_or_working_tree(tmp_path: Path) -> None:
    """Push must not commit to the current branch or leave staged changes."""
    _remote, local, transcript = _make_fake_setup(tmp_path)

    head_before = _git(local, "rev-parse", "HEAD")
    branch_before = _git(local, "branch", "--show-current")

    result = _run_script(local, transcript, push=True)
    assert result.returncode == 0, result.stderr

    head_after = _git(local, "rev-parse", "HEAD")
    branch_after = _git(local, "branch", "--show-current")

    assert head_before == head_after, "current branch HEAD moved"
    assert branch_before == branch_after, "current branch changed"

    staged = _git(local, "diff", "--cached", "--name-only")
    assert staged == "", f"unexpected staged files: {staged!r}"


def test_does_not_push_to_main(tmp_path: Path) -> None:
    """#30: the push must NOT target main (protected in production)."""
    remote, local, transcript = _make_fake_setup(tmp_path)

    main_before = _git(remote, "rev-parse", "main")
    result = _run_script(local, transcript, push=True)
    assert result.returncode == 0, result.stderr
    main_after = _git(remote, "rev-parse", "main")

    assert main_before == main_after, "push landed on main (regression of #30)"


def test_writes_marker_on_persistent_push_failure(tmp_path: Path) -> None:
    """If push keeps failing, drop ai-log/UPLOAD_FAILED.txt so the break is visible."""
    _remote, local, transcript = _make_fake_setup(tmp_path)

    _git(local, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))

    result = _run_script(local, transcript, push=True)
    assert result.returncode == 0, "script must always exit 0 (best-effort contract)"

    marker = local / "ai-log" / "UPLOAD_FAILED.txt"
    assert marker.is_file(), "UPLOAD_FAILED.txt not created after failed push"
    assert marker.read_text().strip(), "marker file is empty — needs the error details"


def test_success_clears_stale_marker(tmp_path: Path) -> None:
    """A successful push should remove a pre-existing UPLOAD_FAILED.txt."""
    _remote, local, transcript = _make_fake_setup(tmp_path)

    marker = local / "ai-log" / "UPLOAD_FAILED.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("stale failure from earlier session\n")

    result = _run_script(local, transcript, push=True)
    assert result.returncode == 0, result.stderr

    assert not marker.is_file(), "stale marker not cleared after successful push"
