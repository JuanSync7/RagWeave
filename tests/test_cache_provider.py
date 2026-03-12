from src.platform.cache.provider import InMemoryTTLCache


def test_in_memory_ttl_cache_roundtrip():
    cache = InMemoryTTLCache()
    cache.set("k", {"v": 1}, ttl_seconds=10)
    assert cache.get("k") == {"v": 1}

