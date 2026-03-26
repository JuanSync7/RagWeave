# @summary
# Temporal worker entry point for the ingestion pipeline.
# Loads the embedding model and MinIO client once at startup, then registers
# workflows and activities with the Temporal task queue.
# Exports: main, run_worker
# Deps: temporalio, src.ingest.temporal.activities, src.ingest.temporal.workflows
# @end-summary
"""Ingestion pipeline Temporal worker.

Run with:
    python -m src.ingest.temporal.worker

One worker process per GPU. Scale by adding replicas — each replica loads
its own embedding model and handles the full pipeline end-to-end.
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from config.settings import TEMPORAL_TARGET_HOST, TEMPORAL_TASK_QUEUE
from src.ingest.temporal.activities import (
    document_processing_activity,
    embedding_pipeline_activity,
    prewarm_worker_resources,
)
from src.ingest.temporal.workflows import IngestDirectoryWorkflow, IngestDocumentWorkflow

logger = logging.getLogger("rag.ingest.temporal.worker")


async def run_worker(
    task_queue: str = TEMPORAL_TASK_QUEUE,
    max_concurrent_activities: int = 4,
) -> None:
    """Connect to Temporal, prewarm resources, and start the worker loop.

    Args:
        task_queue: Temporal task queue name to listen on.
        max_concurrent_activities: Max parallel activity executions per worker.
            Tune based on available VRAM — start at 2-4, increase until GPU
            utilisation plateaus or OOM errors appear.
    """
    logger.info("prewarming worker resources (loading embedding model)...")
    prewarm_worker_resources()
    logger.info("worker resources ready")

    client = await Client.connect(TEMPORAL_TARGET_HOST)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[IngestDirectoryWorkflow, IngestDocumentWorkflow],
        activities=[document_processing_activity, embedding_pipeline_activity],
        max_concurrent_activities=max_concurrent_activities,
    )
    logger.info(
        "worker started task_queue=%s max_concurrent_activities=%d",
        task_queue,
        max_concurrent_activities,
    )
    await worker.run()


def main() -> None:
    import os
    concurrency = int(os.environ.get("RAG_INGEST_WORKER_CONCURRENCY", "2"))
    queue = os.environ.get("RAG_INGEST_TASK_QUEUE", TEMPORAL_TASK_QUEUE)
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker(task_queue=queue, max_concurrent_activities=concurrency))


if __name__ == "__main__":
    main()
