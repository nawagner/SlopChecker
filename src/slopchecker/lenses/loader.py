"""Thin loader for lens prompt packs.

A lens is a markdown file in this directory: YAML-ish frontmatter
(flat ``key: value`` lines between ``---`` fences), an H1 title, and
H2 sections. Required sections: "System prompt", "Output format",
"Example" (the example holding an ``### Input`` and an ``### Output``
H3, each with one fenced code block). See README.md in this directory
for the full format spec.

This module only parses markdown into a `Lens`. Prompt assembly, the
LLM client, retries, and caching are pipeline concerns (#37) — not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

LENS_DIR = Path(__file__).parent

REQUIRED_SECTIONS = ("system prompt", "output format", "example")

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_H1_RE = re.compile(r"^# (?P<title>.+)$", re.MULTILINE)
_H2_SPLIT_RE = re.compile(r"^## +(?P<heading>.+)$", re.MULTILINE)
_H3_SPLIT_RE = re.compile(r"^### +(?P<heading>.+)$", re.MULTILINE)
_FENCE_RE = re.compile(r"^```[^\n]*\n(?P<body>.*?)^```", re.DOTALL | re.MULTILINE)


class LensError(ValueError):
    """Base class for lens loading problems."""


class LensNotFoundError(LensError):
    """No lens markdown file with the requested name."""


class LensFormatError(LensError):
    """Lens file exists but does not follow the pack format."""


@dataclass(frozen=True)
class Lens:
    """A parsed lens prompt pack."""

    id: str
    title: str
    meta: dict[str, str]
    sections: dict[str, str]
    path: Path

    @property
    def system_prompt(self) -> str:
        return self.sections["system prompt"]

    @property
    def output_format(self) -> str:
        return self.sections["output format"]

    @property
    def example(self) -> str:
        return self.sections["example"]

    @property
    def example_input(self) -> str:
        return _fenced_block(_subsection(self.example, "input"), self.path, "Input")

    @property
    def example_output(self) -> str:
        return _fenced_block(_subsection(self.example, "output"), self.path, "Output")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "meta": dict(self.meta),
            "sections": dict(self.sections),
            "path": str(self.path),
        }


def list_lenses(directory: Path = LENS_DIR) -> list[str]:
    """Names of the lens packs available in `directory` (README excluded)."""
    return sorted(p.stem for p in directory.glob("*.md") if p.name != "README.md")


def load_lens(name: str, directory: Path = LENS_DIR) -> Lens:
    """Parse `<directory>/<name>.md` into a `Lens`.

    Raises `LensNotFoundError` if the file is missing and
    `LensFormatError` if it does not follow the pack format.
    """
    path = directory / f"{name}.md"
    if not path.is_file():
        raise LensNotFoundError(f"no lens {name!r} in {directory}")
    text = path.read_text(encoding="utf-8")

    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise LensFormatError(f"{path}: missing --- frontmatter block")
    meta = _parse_frontmatter(match.group(1), path)
    body = text[match.end() :]

    h1 = _H1_RE.search(body)
    if h1 is None:
        raise LensFormatError(f"{path}: missing # title")

    sections = _split_sections(body, _H2_SPLIT_RE)
    missing = [s for s in REQUIRED_SECTIONS if not sections.get(s, "").strip()]
    if missing:
        raise LensFormatError(f"{path}: missing required section(s): {', '.join(missing)}")

    lens = Lens(
        id=meta.get("id", path.stem),
        title=h1.group("title").strip(),
        meta=meta,
        sections=sections,
        path=path,
    )
    # Force example Input/Output parsing now so a malformed example fails
    # at load time, not at first use.
    lens.example_input, lens.example_output  # noqa: B018
    return lens


def _parse_frontmatter(block: str, path: Path) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise LensFormatError(f"{path}: bad frontmatter line: {line!r}")
        meta[key.strip()] = value.strip()
    return meta


def _split_sections(body: str, splitter: re.Pattern[str]) -> dict[str, str]:
    """Map lowercased heading -> raw markdown until the next same-level heading."""
    sections: dict[str, str] = {}
    matches = list(splitter.finditer(body))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[match.group("heading").strip().lower()] = body[match.end() : end].strip()
    return sections


def _subsection(section: str, heading: str) -> str:
    return _split_sections(section, _H3_SPLIT_RE).get(heading, "")


def _fenced_block(text: str, path: Path, label: str) -> str:
    match = _FENCE_RE.search(text)
    if match is None:
        raise LensFormatError(f"{path}: example {label} has no fenced code block")
    return match.group("body")
