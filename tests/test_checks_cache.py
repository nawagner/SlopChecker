"""Disk cache for network lookups (#8), offline.

The acceptance criterion is "disk cache keyed on the identifier, with a
--no-cache escape hatch". The other half of these tests is the failure
behavior: a cache that can't be read or written must slow a run down, never
fail one.
"""

from __future__ import annotations

import json
import time

import pytest

from slopchecker.checks.cache import DiskCache, NullCache, cache_for, default_cache_dir


def test_roundtrip(tmp_path) -> None:
    cache = DiskCache(tmp_path)
    cache.set("resolve", "doi:10.1038/nature12373", {"outcome": "resolves", "http_status": 200})
    assert cache.get("resolve", "doi:10.1038/nature12373") == {
        "outcome": "resolves",
        "http_status": 200,
    }


def test_miss_returns_none(tmp_path) -> None:
    assert DiskCache(tmp_path).get("resolve", "doi:nope") is None


def test_survives_a_new_cache_object(tmp_path) -> None:
    """Batches and re-runs are the point: the second run must not re-fetch."""
    DiskCache(tmp_path).set("resolve", "doi:x", {"outcome": "not_found"})
    assert DiskCache(tmp_path).get("resolve", "doi:x") == {"outcome": "not_found"}


def test_keyed_on_the_identifier_not_the_document(tmp_path) -> None:
    cache = DiskCache(tmp_path)
    cache.set("resolve", "doi:a", {"outcome": "resolves"})
    cache.set("resolve", "doi:b", {"outcome": "not_found"})
    assert cache.get("resolve", "doi:a") != cache.get("resolve", "doi:b")


def test_namespaces_do_not_collide(tmp_path) -> None:
    cache = DiskCache(tmp_path)
    cache.set("resolve", "k", {"v": 1})
    cache.set("metadata", "k", {"v": 2})
    assert cache.get("resolve", "k") == {"v": 1}
    assert cache.get("metadata", "k") == {"v": 2}


def test_entries_expire(tmp_path) -> None:
    cache = DiskCache(tmp_path, ttl_s=0.01)
    cache.set("resolve", "doi:x", {"outcome": "resolves"})
    time.sleep(0.05)
    # Bypass the in-memory layer the way a later run would.
    assert DiskCache(tmp_path, ttl_s=0.01).get("resolve", "doi:x") is None


def test_corrupt_entry_is_a_miss_not_a_crash(tmp_path) -> None:
    cache = DiskCache(tmp_path)
    path = cache.path_for("resolve", "doi:x")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not json")
    assert cache.get("resolve", "doi:x") is None


def test_entry_missing_its_timestamp_is_a_miss(tmp_path) -> None:
    cache = DiskCache(tmp_path)
    path = cache.path_for("resolve", "doi:x")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"value": {"outcome": "resolves"}}))
    assert cache.get("resolve", "doi:x") is None


def test_unwritable_cache_does_not_raise(tmp_path) -> None:
    """A read-only or full disk must not take the run down."""
    target = tmp_path / "not-a-dir"
    target.write_text("i am a file")
    cache = DiskCache(target)
    cache.set("resolve", "doi:x", {"outcome": "resolves"})  # must not raise
    assert cache.get("resolve", "doi:x") == {"outcome": "resolves"}  # memory layer still serves


def test_null_cache_never_stores() -> None:
    cache = NullCache()
    cache.set("resolve", "doi:x", {"outcome": "resolves"})
    assert cache.get("resolve", "doi:x") is None


def test_no_cache_flag_selects_the_null_cache(tmp_path) -> None:
    assert isinstance(cache_for(no_cache=True), NullCache)
    assert isinstance(cache_for(no_cache=False, cache_dir=tmp_path), DiskCache)


def test_cache_dir_override(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLOPCHECK_CACHE_DIR", str(tmp_path / "elsewhere"))
    assert default_cache_dir() == tmp_path / "elsewhere"
    monkeypatch.delenv("SLOPCHECK_CACHE_DIR")
    assert default_cache_dir().name == "slopchecker"


def test_long_and_unsafe_keys_stay_distinct(tmp_path) -> None:
    """URLs are keys: slashes, queries, and 300-character paths included."""
    cache = DiskCache(tmp_path)
    a = "url:https://example.org/" + "x" * 300 + "?a=1"
    b = "url:https://example.org/" + "x" * 300 + "?a=2"
    cache.set("resolve", a, {"outcome": "resolves"})
    cache.set("resolve", b, {"outcome": "not_found"})
    assert DiskCache(tmp_path).get("resolve", a) == {"outcome": "resolves"}
    assert DiskCache(tmp_path).get("resolve", b) == {"outcome": "not_found"}
