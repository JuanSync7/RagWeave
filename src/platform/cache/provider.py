# @summary
# Cache provider facade with in-memory TTL backend and optional Redis.
# Selects backend based on config and returns a process-wide singleton.
# Exports: CacheProvider, InMemoryTTLCache, RedisCache, NoopCache, get_cache
# Deps: config.settings, json, threading, time
# @end-summary
"""Cache provider facade with in-memory TTL backend and optional Redis.

This module centralizes caching behind a small interface so callers can use
`get_cache()` without caring whether caching is disabled, in-memory, or Redis.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from config.settings import (
    CACHE_ENABLED,
    CACHE_PROVIDER,
    CACHE_TTL_SECONDS,
    CACHE_REDIS_URL,
)


class CacheProvider:
    """Cache backend interface.

    Implementations should be safe for concurrent use.
    """

    def get(self, key: str) -> Any | None:
        """Get a cached value.

        Args:
            key: Cache key.

        Returns:
            The cached value, or None if the key is missing or expired.
        """
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Set a cached value.

        Args:
            key: Cache key.
            value: Value to store.
            ttl_seconds: Optional TTL override, in seconds.
        """
        raise NotImplementedError


class InMemoryTTLCache(CacheProvider):
    """Thread-safe in-process cache with per-key TTL.

    Values are stored as Python objects and expired lazily on read.
    """

    def __init__(self) -> None:
        """Initialize an empty in-memory cache."""
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        """Get a cached value.

        Args:
            key: Cache key.

        Returns:
            The cached value, or None if the key is missing or expired.
        """
        now = time.time()
        with self._lock:
            if key not in self._store:
                return None
            expires_at, value = self._store[key]
            if now >= expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Set a cached value.

        Args:
            key: Cache key.
            value: Value to store.
            ttl_seconds: Optional TTL override, in seconds.
        """
        ttl = ttl_seconds if ttl_seconds is not None else CACHE_TTL_SECONDS
        expires_at = time.time() + max(1, int(ttl))
        with self._lock:
            self._store[key] = (expires_at, value)


class RedisCache(CacheProvider):
    """Redis-backed cache using JSON serialization.

    Values are JSON-encoded on write and decoded on read.
    """

    def __init__(self, redis_url: str) -> None:
        """Create a Redis cache client.

        Args:
            redis_url: Redis connection URL.
        """
        import redis  # type: ignore

        self._client = redis.from_url(redis_url, decode_responses=True)

    def get(self, key: str) -> Any | None:
        """Get a cached value.

        Args:
            key: Cache key.

        Returns:
            The decoded JSON value, or None if the key is missing.
        """
        raw = self._client.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Set a cached value.

        Args:
            key: Cache key.
            value: Value to store. Must be JSON-serializable.
            ttl_seconds: Optional TTL override, in seconds.
        """
        ttl = ttl_seconds if ttl_seconds is not None else CACHE_TTL_SECONDS
        self._client.set(key, json.dumps(value), ex=max(1, int(ttl)))


class NoopCache(CacheProvider):
    """Cache implementation that never stores values."""

    def get(self, key: str) -> Any | None:
        """Get a cached value.

        Args:
            key: Cache key.

        Returns:
            Always None.
        """
        return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Set a cached value.

        Args:
            key: Cache key.
            value: Value to store.
            ttl_seconds: Optional TTL override, in seconds.
        """
        return None


_CACHE: CacheProvider | None = None


def get_cache() -> CacheProvider:
    """Return the process-wide cache provider.

    The provider is chosen from configuration on first call and then cached.

    Returns:
        The configured cache provider:

        - `NoopCache` if caching is disabled.
        - `RedisCache` if Redis is selected and initialization succeeds.
        - `InMemoryTTLCache` as a fallback or when explicitly selected.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    if not CACHE_ENABLED:
        _CACHE = NoopCache()
        return _CACHE

    provider = CACHE_PROVIDER.strip().lower()
    if provider == "redis":
        try:
            _CACHE = RedisCache(CACHE_REDIS_URL)
            return _CACHE
        except Exception:
            _CACHE = InMemoryTTLCache()
            return _CACHE

    _CACHE = InMemoryTTLCache()
    return _CACHE

