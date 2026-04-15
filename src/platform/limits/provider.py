# @summary
# Fixed-window rate limiter implementations (in-memory and Redis-backed).
# Exports: LimitResult, InMemoryRateLimiter, RedisRateLimiter
# Deps: dataclasses, threading, time, redis (optional)
# @end-summary
"""Fixed-window rate limiter implementations.

Provides an in-memory backend for single-process deployments and a
Redis-backed backend for cross-process / multi-container consistency.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class LimitResult:
    """Result of a rate-limit check."""

    allowed: bool
    remaining: int
    retry_after_seconds: int


class InMemoryRateLimiter:
    """Thread-safe fixed-window limiter keyed by arbitrary string."""

    def __init__(self, limit: int, window_seconds: int):
        """Create a rate limiter.

        Args:
            limit: Maximum allowed events per window.
            window_seconds: Window size in seconds.
        """
        self._limit = max(1, limit)
        self._window = max(1, window_seconds)
        self._lock = threading.Lock()
        self._state: dict[str, tuple[int, float]] = {}

    def check(
        self,
        key: str,
        *,
        limit: int | None = None,
        window_seconds: int | None = None,
    ) -> LimitResult:
        """Check and consume one unit against the rate limit.

        Args:
            key: Identifier to rate limit (tenant/project/user/etc.).
            limit: Optional limit override for this check.
            window_seconds: Optional window override for this check.

        Returns:
            A `LimitResult` describing whether the request is allowed and when
            the window resets.
        """
        effective_limit = max(1, int(limit if limit is not None else self._limit))
        effective_window = max(1, int(window_seconds if window_seconds is not None else self._window))
        now = time.time()
        with self._lock:
            count, reset_at = self._state.get(key, (0, now + effective_window))
            if now >= reset_at:
                count = 0
                reset_at = now + effective_window

            if count >= effective_limit:
                retry_after = int(max(1, reset_at - now))
                return LimitResult(False, 0, retry_after)

            count += 1
            self._state[key] = (count, reset_at)
            remaining = max(0, effective_limit - count)
            return LimitResult(True, remaining, int(max(0, reset_at - now)))


class RedisRateLimiter:
    """Fixed-window rate limiter backed by Redis for cross-process consistency.

    Uses Redis INCR + EXPIRE to maintain a shared counter across multiple
    API workers or containers. Each key represents one rate-limit window;
    the TTL on the key controls window expiry.

    Args:
        redis_url: Redis connection URL (e.g. ``redis://localhost:6379/0``).
        limit: Default maximum allowed events per window.
        window_seconds: Default window size in seconds.
        prefix: Key prefix to namespace rate-limit keys in Redis.
    """

    def __init__(
        self,
        redis_url: str,
        limit: int,
        window_seconds: int,
        prefix: str = "rag:ratelimit:",
    ) -> None:
        import redis as _redis  # type: ignore

        self._client = _redis.from_url(redis_url, decode_responses=True)
        self._limit = max(1, limit)
        self._window = max(1, window_seconds)
        self._prefix = prefix

    def check(
        self,
        key: str,
        *,
        limit: int | None = None,
        window_seconds: int | None = None,
    ) -> LimitResult:
        """Check and consume one unit against the rate limit.

        Atomically increments the counter in Redis and sets the TTL on the
        first request of each window.

        Args:
            key: Identifier to rate limit (tenant/project/user/etc.).
            limit: Optional limit override for this check.
            window_seconds: Optional window override for this check.

        Returns:
            A ``LimitResult`` describing whether the request is allowed.
        """
        effective_limit = max(1, int(limit if limit is not None else self._limit))
        effective_window = max(1, int(window_seconds if window_seconds is not None else self._window))
        redis_key = f"{self._prefix}{key}"

        pipe = self._client.pipeline(transaction=True)
        pipe.incr(redis_key)
        pipe.ttl(redis_key)
        results = pipe.execute()

        current_count: int = results[0]  # INCR returns the new count
        ttl: int = results[1]  # TTL: -1 = no expiry, -2 = key gone

        # Set expiry on the first increment of a new window.
        if ttl == -1:
            self._client.expire(redis_key, effective_window)
            ttl = effective_window

        if current_count > effective_limit:
            return LimitResult(
                allowed=False,
                remaining=0,
                retry_after_seconds=max(1, ttl),
            )
        return LimitResult(
            allowed=True,
            remaining=max(0, effective_limit - current_count),
            retry_after_seconds=0,
        )

