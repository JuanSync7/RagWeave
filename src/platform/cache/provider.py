"""Cache provider with in-memory TTL backend and optional Redis."""

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
    def get(self, key: str) -> Any | None:
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        raise NotImplementedError


class InMemoryTTLCache(CacheProvider):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
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
        ttl = ttl_seconds if ttl_seconds is not None else CACHE_TTL_SECONDS
        expires_at = time.time() + max(1, int(ttl))
        with self._lock:
            self._store[key] = (expires_at, value)


class RedisCache(CacheProvider):
    def __init__(self, redis_url: str) -> None:
        import redis  # type: ignore

        self._client = redis.from_url(redis_url, decode_responses=True)

    def get(self, key: str) -> Any | None:
        raw = self._client.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else CACHE_TTL_SECONDS
        self._client.set(key, json.dumps(value), ex=max(1, int(ttl)))


class NoopCache(CacheProvider):
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        return None


_CACHE: CacheProvider | None = None


def get_cache() -> CacheProvider:
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

