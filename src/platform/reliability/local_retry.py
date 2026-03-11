"""Local retry implementation with exponential backoff."""

import logging
import time
from typing import Callable, Optional, TypeVar

from src.platform.reliability.contracts import RetryProvider
from src.platform.schemas.reliability import RetryPolicy

T = TypeVar("T")

logger = logging.getLogger("rag.reliability.local_retry")


class LocalRetryProvider(RetryProvider):
    """Retry provider for local execution."""

    def execute(
        self,
        operation_name: str,
        fn: Callable[[], T],
        policy: Optional[RetryPolicy] = None,
        idempotency_key: Optional[str] = None,
    ) -> T:
        policy = policy or RetryPolicy()
        backoff = policy.initial_backoff_seconds
        last_error: Optional[BaseException] = None

        for attempt in range(1, policy.max_attempts + 1):
            try:
                return fn()
            except policy.retryable_exceptions as exc:
                last_error = exc
                if attempt >= policy.max_attempts:
                    break
                logger.warning(
                    "Retrying operation=%s attempt=%d/%d idempotency_key=%s error=%s",
                    operation_name,
                    attempt,
                    policy.max_attempts,
                    idempotency_key,
                    exc,
                )
                time.sleep(backoff)
                backoff = min(backoff * policy.backoff_multiplier, policy.max_backoff_seconds)

        assert last_error is not None
        raise last_error

