"""HTML loader (#4), stdlib-only.

Flattening model: block-level elements delimit blocks; blocks are joined
with a blank line. Intra-block whitespace is collapsed (that's what a
browser renders, and it's what a human quoting the page would copy).
Heading blocks (h1–h6) feed the section map. <script>/<style>/<head>
content never reaches the text; <title> becomes document metadata.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from slopchecker.ingest.types import IngestResult
from slopchecker.ingest.util import (
    build_sections,
    errored,
    find_references,
    normalize,
    sha256_file,
)
from slopchecker.models import FlattenedDoc

_BLOCK_TAGS = {
    "p",
    "div",
    "section",
    "article",
    "header",
    "footer",
    "main",
    "aside",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "dl",
    "dt",
    "dd",
    "table",
    "tr",
    "caption",
    "figure",
    "figcaption",
    "blockquote",
    "pre",
    "br",
    "hr",
}
_SKIP_TAGS = {"script", "style", "template"}
_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


class _Flattener(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self.headings: list[tuple[int, str, int]] = []  # (level, title, block_index)
        self.title: str | None = None
        self._buffer: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._heading_level: int | None = None

    def _flush(self, heading_level: int | None = None) -> None:
        block = " ".join("".join(self._buffer).split())
        self._buffer = []
        if not block:
            return
        if heading_level is not None:
            self.headings.append((heading_level, block, len(self.blocks)))
        self.blocks.append(block)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in _BLOCK_TAGS:
            self._flush(self._heading_level)
            self._heading_level = _HEADING_TAGS.get(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in _BLOCK_TAGS:
            self._flush(self._heading_level)
            self._heading_level = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title = ((self.title or "") + data).strip() or None
            return
        self._buffer.append(data)

    def close(self) -> None:
        super().close()
        self._flush(self._heading_level)


def load_html(path: Path) -> IngestResult:
    raw = normalize(path.read_text(encoding="utf-8", errors="replace"))
    parser = _Flattener()
    parser.feed(raw)
    parser.close()

    if not parser.blocks:
        return errored(f"{path.name}: no text content found in HTML — nothing to check.")

    text = "\n\n".join(parser.blocks)
    # Block index -> char offset of that block's start in the joined text.
    offsets: list[int] = []
    cursor = 0
    for block in parser.blocks:
        offsets.append(cursor)
        cursor += len(block) + 2  # the "\n\n" separator

    headings = [(level, title, offsets[i]) for level, title, i in parser.headings]
    sections = build_sections(text, headings)
    document = FlattenedDoc(
        file=path.name,
        text=text,
        sha256=sha256_file(path),
        media_type="text/html",
        title=parser.title,
    )
    return IngestResult(
        status="ok",
        document=document,
        sections=sections,
        references=find_references(text, sections),
    )
