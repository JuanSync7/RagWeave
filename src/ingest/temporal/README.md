<!-- @summary
Temporal execution subsystem for distributed parallel ingestion — wraps doc_processing and embedding phases as Temporal activities with workflow orchestration and a GPU worker entry point.
@end-summary -->

# ingest/temporal

## Overview

Temporal execution layer for the ingestion pipeline. Wraps Phase 1 (`doc_processing`) and Phase 2 (`embedding`) as Temporal activities so documents can be processed in parallel across multiple GPU workers.

This directory does **not** reimplement ingestion logic — it calls `run_document_processing()` and `run_embedding_pipeline()` from their respective subpackages. Temporal provides the task queue, retry policy, and worker scaling on top.

## Files

| File | Purpose |
| --- | --- |
| `activities.py` | `@activity.defn` wrappers for Phase 1 and Phase 2; module-level embedder and MinIO client singletons loaded once per worker process |
| `workflows.py` | `IngestDocumentWorkflow` (Phase 1 → Phase 2 chain) and `IngestDirectoryWorkflow` (fan-out to N document children) |
| `worker.py` | Worker entry point — prewarmes resources, connects to Temporal, starts the worker loop |

## Worker Scaling

One worker process per GPU. Each replica loads its own embedding model. Scale replicas up/down based on Temporal task queue depth (KEDA `targetQueueSize`).

```
RAG_INGEST_WORKER_CONCURRENCY   max parallel activities per worker (default 2)
RAG_INGEST_TASK_QUEUE           Temporal task queue name override
TEMPORAL_TARGET_HOST            Temporal server address
```

Run a worker:

```bash
python -m src.ingest.temporal.worker
```

## Workflow Design

- **`IngestDocumentWorkflow`** — Workflow ID = `source_key` (idempotent re-submission). Chains `document_processing_activity` → `embedding_pipeline_activity`. Each phase has its own `RetryPolicy(maximum_attempts=3)` so a Phase 2 failure does not re-run Phase 1.
- **`IngestDirectoryWorkflow`** — Fans out to N `IngestDocumentWorkflow` child workflows concurrently. Collects and summarises results.
- **CleanDocumentStore** — The durable Phase 1→2 boundary. Phase 1 writes clean text there; Phase 2 reads from it. No large data passes through Temporal serialization.
