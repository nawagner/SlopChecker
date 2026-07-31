"""Caches for expensive results (#8: "cache results so re-runs and batches
don't re-hammer the same endpoints"; #119: share them across the team).

Two tiers, one interface (``Cache``):

- ``DiskCache`` — per-machine JSON files. Fast, private, ephemeral on Railway.
- ``HTTPCache`` — the shared Cloudflare KV namespace, reached through the
  Worker's ``/api/cache`` endpoint rather than a Cloudflare API token, for the
  reason ``worker/wrangler.toml`` records: no credential is minted or pasted in
  a session (#23/#65).

``TieredCache`` stacks them (disk as L1, KV as L2, write-through) so a warm
local run never pays a network round trip and a cold one still hits whatever a
teammate's run already computed.

Keyed on the identifier, not on the document: a DOI cited by forty proposals
in a batch is fetched once — now once per *team* rather than once per laptop.
Entries are plain JSON so a human can read (and delete) them, and every read
degrades to a miss — a corrupt, unreachable, or unauthorized cache slows a run
down, it never fails one.

The escape hatch is ``slopcheck run --no-cache`` (``CheckContext.no_cache``),
with ``SLOPCHECK_CACHE_DIR`` overriding the disk location and
``SLOPCHECK_CACHE_URL`` / ``SLOPCHECK_CACHE_TOKEN`` enabling the shared tier.

**Nothing that is document text may enter the shared tier.** Callers project
their payloads down to derived values first — see ``detect/pangram.py`` and
``pipeline/lens_runtime.py``. This module can't enforce that (it takes
arbitrary JSON), so the rule lives with the callers and is tested there.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx

from slopchecker import config as _config

# Seven days: DOI registration and canonical metadata are close to immutable
# on hackathon timescales, and a stale "resolves" is cheap to correct.
DEFAULT_TTL_S = 7 * 24 * 3600

# Content-hash-keyed entries (Pangram, lenses) are immutable by construction —
# the key *is* the hash of the input — so they only expire to keep the shared
# namespace from growing without bound.
CONTENT_HASH_TTL_S = 30 * 24 * 3600

# A cache is an optimization. If the shared tier can't answer in about the time
# a Worker round trip should take, a miss is cheaper than waiting.
DEFAULT_HTTP_TIMEOUT_S = 3.0

# KV's ceiling for the whole `namespace:key` string. `_remote_key` hashes every
# key to 64 hex chars, so this is a bound we stay well under by construction
# rather than something to check per call — kept named so the Worker-side limit
# is discoverable from here.
MAX_REMOTE_KEY_BYTES = 512

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


@runtime_checkable
class Cache(Protocol):
    """What a check needs from a cache: two methods, neither of which raises."""

    def get(self, namespace: str, key: str) -> Any | None: ...

    def set(self, namespace: str, key: str, value: Any) -> None: ...


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


def _remote_key(key: str) -> str:
    """The key as the Worker sees it: always a hash, never the raw key.

    Three reasons it is unconditional rather than "hash only when too long":

    1. **Correctness.** Keys are URLs and DOIs, and a URL does not survive a
       round trip through a URL path. httpx re-normalizes percent-encoding, so
       ``%2F`` decodes back to ``/`` and re-partitions the path — and a key's
       ``?query`` would be parsed off as an actual query string and lost, so
       two URLs differing only in their query would collide.
    2. **Privacy.** Which DOIs a proposal cites is itself information about the
       proposal. Hashing means the shared namespace holds derived values under
       opaque keys, consistent with the #119 rule for the values themselves.
    3. **KV's 512-byte key limit** stops being something to think about.

    Readability was the stated reason for the disk cache's readable slugs, and
    the disk tier keeps it — that is where a human greps and deletes.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class HTTPCache:
    """The shared KV tier, reached through the Worker's ``/api/cache``.

    Every failure — unreachable host, 401, 404, timeout, malformed body — is a
    miss, and every write failure is dropped silently. That is the whole
    contract: a shared cache that can fail a run is worse than no shared cache.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        ttl_s: float = DEFAULT_TTL_S,
        timeout_s: float = DEFAULT_HTTP_TIMEOUT_S,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ttl_s = ttl_s
        # One pooled client: checks run in parallel threads and httpx.Client is
        # thread-safe, so a per-call client would just re-handshake TLS.
        self._client = client or httpx.Client(
            timeout=timeout_s,
            headers={"authorization": f"Bearer {token}"},
        )

    def _url(self, namespace: str, key: str) -> str:
        # The hashed key is hex, so it needs no escaping; the namespace is
        # quoted anyway since it's the one segment a caller picks freely.
        ns = urllib.parse.quote(namespace, safe="")
        return f"{self.base_url}/api/cache/{ns}/{_remote_key(key)}"

    def get(self, namespace: str, key: str) -> Any | None:
        try:
            response = self._client.get(self._url(namespace, key))
            if response.status_code != 200:
                return None
            return response.json()
        except (httpx.HTTPError, ValueError):
            return None

    def set(self, namespace: str, key: str, value: Any) -> None:
        try:
            self._client.put(
                self._url(namespace, key),
                content=json.dumps(value),
                params={"ttl": int(self.ttl_s)},
                headers={"content-type": "application/json"},
            )
        except (httpx.HTTPError, TypeError, ValueError):
            return  # unreachable, unauthorized, or unserializable: run continues

    def close(self) -> None:
        self._client.close()


class TieredCache:
    """``local`` in front of ``remote``: read through, write to both.

    A remote hit backfills local, so the second document in a batch that cites
    the same DOI pays no network cost at all.
    """

    def __init__(self, local: Cache, remote: Cache) -> None:
        self.local = local
        self.remote = remote

    def get(self, namespace: str, key: str) -> Any | None:
        value = self.local.get(namespace, key)
        if value is not None:
            return value
        value = self.remote.get(namespace, key)
        if value is not None:
            self.local.set(namespace, key, value)
        return value

    def set(self, namespace: str, key: str, value: Any) -> None:
        self.local.set(namespace, key, value)
        self.remote.set(namespace, key, value)


def remote_cache(ttl_s: float = DEFAULT_TTL_S) -> HTTPCache | None:
    """The shared tier if it's configured, else None.

    Both env vars are required: a URL without a token would 401 on every call,
    which works (every call is a miss) but spends a round trip to learn nothing.
    """
    base_url = _config.get("SLOPCHECK_CACHE_URL")
    token = _config.get("SLOPCHECK_CACHE_TOKEN")
    if not base_url or not token:
        return None
    return HTTPCache(base_url, token, ttl_s=ttl_s)


def cache_for(
    no_cache: bool = False,
    cache_dir: Path | str | None = None,
    ttl_s: float = DEFAULT_TTL_S,
) -> Cache:
    """The cache a check should use, given the run's flags.

    ``--no-cache`` disables both tiers, not just the local one — the flag means
    "re-fetch", and a shared hit would defeat that as thoroughly as a local one.
    """
    if no_cache:
        return NullCache()
    local = DiskCache(cache_dir, ttl_s=ttl_s)
    remote = remote_cache(ttl_s=ttl_s)
    return TieredCache(local, remote) if remote is not None else local
