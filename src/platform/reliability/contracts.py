"""Reliability contracts used by the pipeline."""

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
        """Execute an operation with retry semantics."""

