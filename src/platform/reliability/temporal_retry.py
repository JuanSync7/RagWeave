"""Temporal-backed retry provider.

This implementation keeps Temporal optional and fail-open. When a Temporal
client or worker is not available, execution falls back to direct invocation.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Dict, Optional, TypeVar

from config.settings import TEMPORAL_TARGET_HOST, TEMPORAL_TASK_QUEUE
from src.platform.reliability.contracts import RetryProvider
from src.platform.schemas.reliability import RetryPolicy

T = TypeVar("T")
logger = logging.getLogger("rag.reliability.temporal")

_OPERATION_REGISTRY: Dict[str, Callable[[], object]] = {}


@dataclass(frozen=True)
class TemporalPayload:
    operation_name: str
    idempotency_key: Optional[str]
    max_attempts: int
    initial_backoff_seconds: float
    max_backoff_seconds: float


def register_temporal_operation(name: str, fn: Callable[[], object]) -> None:
    """Register operation callbacks for Temporal worker activity execution."""
    _OPERATION_REGISTRY[name] = fn


class TemporalRetryProvider(RetryProvider):
    """Retry provider delegating operations to Temporal workflow execution."""

    def __init__(self):
        try:
            import temporalio  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "Temporal SDK not installed. Install `temporalio` to enable Temporal retries."
            ) from exc
        self.target_host = TEMPORAL_TARGET_HOST
        self.task_queue = TEMPORAL_TASK_QUEUE

    def execute(
        self,
        operation_name: str,
        fn: Callable[[], T],
        policy: Optional[RetryPolicy] = None,
        idempotency_key: Optional[str] = None,
    ) -> T:
        policy = policy or RetryPolicy()
        register_temporal_operation(operation_name, fn)

        payload = TemporalPayload(
            operation_name=operation_name,
            idempotency_key=idempotency_key,
            max_attempts=policy.max_attempts,
            initial_backoff_seconds=policy.initial_backoff_seconds,
            max_backoff_seconds=policy.max_backoff_seconds,
        )

        try:
            return asyncio.run(self._execute_via_temporal(payload))
        except Exception as exc:
            logger.warning("Temporal execution unavailable, falling back to local: %s", exc)
            return fn()

    async def _execute_via_temporal(self, payload: TemporalPayload) -> T:
        """Dispatch operation through Temporal workflow for durable retries."""
        from temporalio.client import Client

        client = await Client.connect(self.target_host)
        workflow_id = (
            f"rag-retry-{payload.operation_name}-"
            f"{payload.idempotency_key or 'no-idempotency-key'}"
        )
        result = await client.execute_workflow(
            "RetryWorkflow",
            payload.__dict__,
            id=workflow_id,
            task_queue=self.task_queue,
        )
        return result

