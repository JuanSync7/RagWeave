"""Temporal-backed retry provider.

This implementation keeps Temporal optional and fail-open. When a Temporal
client or worker is not available, execution falls back to direct invocation.
"""
from __future__ import annotations


import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Optional, TypeVar

from config.settings import TEMPORAL_TARGET_HOST, TEMPORAL_TASK_QUEUE
from src.platform.reliability.contracts import RetryProvider
from src.platform.schemas import RetryPolicy

T = TypeVar("T")
logger = logging.getLogger("rag.reliability.temporal")

_OPERATION_REGISTRY: dict[str, Callable[[], object]] = {}


@dataclass(frozen=True)
class TemporalPayload:
    """Wire payload for Temporal retry workflow execution."""

    operation_name: str
    idempotency_key: Optional[str]
    max_attempts: int
    initial_backoff_seconds: float
    max_backoff_seconds: float


def register_temporal_operation(name: str, fn: Callable[[], object]) -> None:
    """Register an operation callback for Temporal worker activity execution.

    Args:
        name: Operation name used to look up the callback.
        fn: Callback invoked by the worker to perform the operation.
    """
    _OPERATION_REGISTRY[name] = fn


class TemporalRetryProvider(RetryProvider):
    """Retry provider delegating operations to Temporal workflow execution."""

    def __init__(self):
        """Create a Temporal-backed retry provider.

        Raises:
            ImportError: If the Temporal SDK is not installed.
        """
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
        """Execute an operation via Temporal if available, otherwise locally.

        Args:
            operation_name: Operation name for registry and workflow id.
            fn: Callable to execute.
            policy: Optional retry policy override.
            idempotency_key: Optional idempotency key for workflow id.

        Returns:
            The return value of `fn`.
        """
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
            # Detect whether we are already inside a running event loop (e.g.
            # called from a FastAPI async handler).  asyncio.run() raises
            # RuntimeError in that situation, which would silently bypass
            # Temporal.  Instead, delegate to a background thread that owns its
            # own event loop.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, self._execute_via_temporal(payload))
                    return future.result()
            else:
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
        try:
            result = await client.execute_workflow(
                "RetryWorkflow",
                payload.__dict__,
                id=workflow_id,
                task_queue=self.task_queue,
            )
        finally:
            await client.close()
        return result

