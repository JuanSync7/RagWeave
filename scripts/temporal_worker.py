#!/usr/bin/env python3
"""Temporal worker for durable retry workflows."""

import asyncio
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.worker import Worker

from config.settings import TEMPORAL_TARGET_HOST, TEMPORAL_TASK_QUEUE
from src.platform.reliability.temporal_retry import _OPERATION_REGISTRY


@activity.defn
def execute_registered_operation(payload: dict) -> object:
    name = payload["operation_name"]
    if name not in _OPERATION_REGISTRY:
        raise ValueError(f"Operation not registered: {name}")
    return _OPERATION_REGISTRY[name]()


@workflow.defn(name="RetryWorkflow")
class RetryWorkflow:
    @workflow.run
    async def run(self, payload: dict) -> object:
        return await workflow.execute_activity(
            execute_registered_operation,
            payload,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=float(payload["initial_backoff_seconds"])),
                maximum_interval=timedelta(seconds=float(payload["max_backoff_seconds"])),
                maximum_attempts=int(payload["max_attempts"]),
            ),
        )


async def main() -> None:
    client = await Client.connect(TEMPORAL_TARGET_HOST)
    worker = Worker(
        client,
        task_queue=TEMPORAL_TASK_QUEUE,
        workflows=[RetryWorkflow],
        activities=[execute_registered_operation],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

