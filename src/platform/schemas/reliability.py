"""Typed schemas for reliability and retry behavior.

These dataclasses define retry policies and operation metadata shared across
retry provider implementations.
"""
from __future__ import annotations


from dataclasses import dataclass
from typing import Callable, Optional, Type


@dataclass(frozen=True)
class RetryPolicy:
    """Retry policy for external service operations."""

    max_attempts: int = 3
    initial_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 5.0
    backoff_multiplier: float = 2.0
    retryable_exceptions: tuple[Type[BaseException], ...] = (Exception,)


@dataclass(frozen=True)
class RetryOperation:
    """Operation metadata used by retry providers."""

    operation_name: str
    idempotency_key: Optional[str]
    timeout_seconds: Optional[float] = None
    policy: Optional[RetryPolicy] = None


RetryCallable = Callable[[], object]
