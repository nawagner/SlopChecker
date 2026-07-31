"""Source retrieval for #10, behind a small protocol.

Retrieval is the deliberately-stubbed half of #10: this PR ships the
``SourceFetcher`` protocol, a local-directory fetcher (tests, and manual
runs against pre-downloaded text), and a disk cache wrapper. Real network
fetchers (arXiv, PMC OA, DOAJ, plain-URL gray literature) are follow-up
work on #10 — they plug in behind the same protocol. Retrieval must stay
limited to openly available full text; no paywall circumvention.

Cached source text lives in the cache directory and is never redistributed:
reports only carry the matched window (see ``matching.QuoteMatch.window``).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Protocol, runtime_checkable

from slopchecker.pipeline.citations.models import ReferenceEntry


@runtime_checkable
class SourceFetcher(Protocol):
    """Fetch the full text for a reference, or None if unavailable."""

    def fetch(self, ref: ReferenceEntry) -> str | None: ...


def source_keys(ref: ReferenceEntry) -> list[str]:
    """Stable filesystem-safe keys for a reference, most specific first."""
    keys: list[str] = []
    if ref.arxiv_id:
        keys.append(f"arxiv-{ref.arxiv_id}")
    if ref.doi:
        keys.append("doi-" + re.sub(r"[^\w.-]+", "_", ref.doi))
    if ref.url:
        digest = hashlib.sha256(ref.url.encode()).hexdigest()[:16]
        keys.append(f"url-{digest}")
    keys.append("ref-" + re.sub(r"[^\w.-]+", "_", ref.key))
    return keys


class LocalFileFetcher:
    """Serve source text from a directory of ``<key>.txt`` files.

    The offline fetcher: tests use it exclusively, and a demo can use it
    with hand-downloaded open-access text. Missing file = source
    unavailable, by design.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def fetch(self, ref: ReferenceEntry) -> str | None:
        for key in source_keys(ref):
            path = self.root / f"{key}.txt"
            if path.is_file():
                return path.read_text()
        return None


class CachingFetcher:
    """Wrap a fetcher with a per-reference disk cache (#10: cache retrieved
    text; the report quotes only the matched window)."""

    def __init__(self, inner: SourceFetcher, cache_dir: Path | str):
        self.inner = inner
        self.cache_dir = Path(cache_dir)

    def fetch(self, ref: ReferenceEntry) -> str | None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{source_keys(ref)[0]}.txt"
        if path.is_file():
            return path.read_text()
        text = self.inner.fetch(ref)
        if text is not None:
            path.write_text(text)
        return text
