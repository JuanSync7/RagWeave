# @summary
# Reliability contracts defining retry provider interface.
# Exports: RetryProvider
# Deps: abc, src.platform.schemas.reliability
# @end-summary
"""Reliability contracts used by the pipeline.

Defines the minimal interface for executing operations with retry semantics.
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional, TypeVar

from src.platform.schemas.reliability import RetryPolicy

T = TypeVar("T")


class RetryProvider(ABC):
    """Abstract retry provider interface."""

    @abstractmethod
    def execute(
        self,
        operation_name: str,
        fn: Callable[[], T],
        policy: Optional[RetryPolicy] = None,
        idempotency_key: Optional[str] = None,
    ) -> T:
        """Execute an operation with retry semantics.

        Args:
            operation_name: Human-readable operation name for logging/metrics.
            fn: Callable to execute.
            policy: Optional retry policy override.
            idempotency_key: Optional idempotency key for logging/correlation.

        Returns:
            The return value of `fn`.
        """

