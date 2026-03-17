# @summary
# Simple in-memory fixed-window rate limiter implementation.
# Exports: LimitResult, InMemoryRateLimiter
# Deps: dataclasses, threading, time
# @end-summary
"""In-memory fixed-window rate limiter."""

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

