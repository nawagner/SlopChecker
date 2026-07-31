"""Planted-defect injection for the validation harness (#29).

Ported from pat-helper (`pat_helper/injector.py`): copy `fixtures_dir` -> a
mutated directory, apply defects, return a manifest with per-defect line
numbers so recall scoring can report where each defect landed.

Each defect: {id, file, original, mutated, ...}. The first occurrence of
`original` in `file` is replaced by `mutated`. Missing text is a hard error
— a silently unplanted defect would corrupt recall scoring by counting a
never-injected defect as a MISS.

`mutated == ""` is deletion. `pending_lens` defects are still injected (so
the report includes the line where the pending defect would live), just
matched differently by run.py.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def inject(
    fixtures_dir: Path,
    defects: list[dict[str, Any]],
    out_dir: Path,
) -> list[dict[str, Any]]:
    """Copy `fixtures_dir` into `out_dir` and apply every defect.

    Returns a manifest: one dict per defect with `id`, `file`, `line`,
    `original`, `mutated`, plus any pass-through fields (`match`,
    `pending_lens`, `check_expected`, `description`) so recall scoring
    doesn't need the original YAML.

    Order matters when two defects touch the same file: each defect finds
    the first occurrence of its `original` in the *already mutated* copy,
    so a defect that removes a line can't shadow a later defect on the same
    line, and two defects targeting the same substring can't be planted (the
    second raises).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in fixtures_dir.iterdir():
        if f.is_file():
            shutil.copy(f, out_dir / f.name)

    manifest: list[dict[str, Any]] = []
    for defect in defects:
        target = out_dir / defect["file"]
        if not target.exists():
            raise ValueError(
                f"defect {defect['id']!r}: file {defect['file']!r} not in fixtures dir"
            )
        text = target.read_text()
        pos = text.find(defect["original"])
        if pos == -1:
            raise ValueError(
                f"defect {defect['id']!r}: original text not found in {defect['file']!r}"
            )
        line = text.count("\n", 0, pos) + 1
        target.write_text(text[:pos] + defect["mutated"] + text[pos + len(defect["original"]) :])
        manifest.append(
            {
                "id": defect["id"],
                "file": defect["file"],
                "line": line,
                "original": defect["original"],
                "mutated": defect["mutated"],
                "match": defect.get("match", {"kind": "pending"}),
                "pending_lens": defect.get("pending_lens"),
                "check_expected": defect.get("check_expected"),
                "description": defect.get("description"),
            }
        )
    return manifest
