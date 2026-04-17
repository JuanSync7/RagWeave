import time
from unittest.mock import patch

from src.platform.cache.provider import InMemoryTTLCache, NoopCache


def test_in_memory_ttl_cache_roundtrip():
    cache = InMemoryTTLCache()
    cache.set("k", {"v": 1}, ttl_seconds=10)
    assert cache.get("k") == {"v": 1}


def test_cache_miss_returns_none():
    cache = InMemoryTTLCache()
    assert cache.get("nonexistent_key") is None


def test_cache_set_then_get_returns_stored_value():
    cache = InMemoryTTLCache()
    cache.set("mykey", [1, 2, 3], ttl_seconds=60)
    assert cache.get("mykey") == [1, 2, 3]


def test_cache_ttl_expiry():
    """Value must not be returned after TTL has elapsed."""
    cache = InMemoryTTLCache()
    # Set a value with TTL=1 second
    cache.set("expiring", "soon", ttl_seconds=1)
    # Simulate time advancing past the TTL by patching time.time
    future_time = time.time() + 5.0
    with patch("src.platform.cache.provider.time") as mock_time:
        mock_time.time.return_value = future_time
        assert cache.get("expiring") is None


def test_cache_overwrite_key():
    """Setting the same key twice replaces the value."""
    cache = InMemoryTTLCache()
    cache.set("k", "first", ttl_seconds=60)
    cache.set("k", "second", ttl_seconds=60)
    assert cache.get("k") == "second"


def test_noop_cache_always_returns_none():
    cache = NoopCache()
    cache.set("k", "v", ttl_seconds=60)
    assert cache.get("k") is None
