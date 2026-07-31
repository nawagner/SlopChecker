"""Disk cache for network lookups (#8: "cache results so re-runs and batches
don't re-hammer the same endpoints").

Keyed on the identifier, not on the document: a DOI cited by forty proposals
in a batch is fetched once. Entries are plain JSON so a human can read (and
delete) them, and every read degrades to a miss — a corrupt or unreadable
cache slows a run down, it never fails one.

The escape hatch is ``slopcheck run --no-cache`` (``CheckContext.no_cache``),
with ``SLOPCHECK_CACHE_DIR`` overriding the location.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

# Seven days: DOI registration and canonical metadata are close to immutable
# on hackathon timescales, and a stale "resolves" is cheap to correct.
DEFAULT_TTL_S = 7 * 24 * 3600

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def default_cache_dir() -> Path:
    """``SLOPCHECK_CACHE_DIR`` if set, else ``~/.cache/slopchecker``."""
    override = os.environ.get("SLOPCHECK_CACHE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "slopchecker"


class NullCache:
    """The ``--no-cache`` cache: every read misses, every write is dropped."""

    def get(self, namespace: str, key: str) -> Any | None:
        return None

    def set(self, namespace: str, key: str, value: Any) -> None:
        return None


class DiskCache:
    """JSON-file cache under ``root/<namespace>/<slug>-<hash>.json``.

    The in-memory layer in front matters more than it looks: checks run in
    parallel threads within a tier and several of them ask about the same
    DOI, so without it one run re-fetches what it just fetched.
    """

    def __init__(self, root: Path | str | None = None, ttl_s: float = DEFAULT_TTL_S):
        self.root = Path(root) if root is not None else default_cache_dir()
        self.ttl_s = ttl_s
        self._mem: dict[tuple[str, str], Any] = {}
        self._lock = threading.Lock()

    def path_for(self, namespace: str, key: str) -> Path:
        """Readable slug plus a hash, so keys stay unique and filesystem-safe."""
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        slug = _SAFE.sub("_", key)[:60].strip("_") or "key"
        return self.root / _SAFE.sub("_", namespace) / f"{slug}-{digest}.json"

    def get(self, namespace: str, key: str) -> Any | None:
        with self._lock:
            if (namespace, key) in self._mem:
                return self._mem[(namespace, key)]
        path = self.path_for(namespace, key)
        try:
            entry = json.loads(path.read_text())
            if time.time() - float(entry["cached_at"]) > self.ttl_s:
                return None
            value = entry["value"]
        except (OSError, ValueError, KeyError, TypeError):
            return None  # unreadable, corrupt, or half-written: just a miss
        with self._lock:
            self._mem[(namespace, key)] = value
        return value

    def set(self, namespace: str, key: str, value: Any) -> None:
        with self._lock:
            self._mem[(namespace, key)] = value
        path = self.path_for(namespace, key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write-then-rename so a killed run can't leave a torn file that
            # every later run has to fail to parse.
            tmp = path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps({"cached_at": time.time(), "value": value}))
            tmp.replace(path)
        except OSError:
            return  # read-only or full disk: the run continues uncached


Cache = DiskCache | NullCache


def cache_for(no_cache: bool = False, cache_dir: Path | str | None = None) -> Cache:
    """The cache a check should use, given the run's flags."""
    return NullCache() if no_cache else DiskCache(cache_dir)
