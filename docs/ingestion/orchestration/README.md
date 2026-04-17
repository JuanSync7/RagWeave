<!-- @summary
Ingestion orchestration documentation: priority queues, Temporal queue routing, worker slot allocation.
@end-summary -->

# docs/ingestion/orchestration

## Overview

This directory contains the specification and supporting documentation for the **Ingestion Orchestration** layer --- the Temporal-based queue topology, per-workflow priority scheme, and worker slot allocation that govern how ingestion workloads are scheduled, prioritised, and executed within the AION RAG Document Embedding Pipeline.

The orchestration layer addresses Gap 13 (Priority Queue for Ingestion) from the ingestion hardening initiative. It introduces a dual-queue architecture (`ingest-user` and `ingest-background`) with per-workflow priority within the user queue, ensuring that single-document submissions are never starved by batch or background workloads.

## Files

| File | Purpose |
| --- | --- |
| `INGESTION_ORCHESTRATION_SPEC.md` | Authoritative L3 requirements specification. Defines dual task queue topology, intra-queue priority, worker slot allocation, priority assignment rules, configuration schema, and observability requirements. FR-3550 through FR-3576, NFR-3580 through NFR-3582. |
| `INGESTION_ORCHESTRATION_SPEC_SUMMARY.md` | Concise summary of the specification for quick reference. |
| `INGESTION_ORCHESTRATION_DESIGN.md` | Design document (task decomposition, interfaces, queue topology contracts) |
| `INGESTION_ORCHESTRATION_IMPLEMENTATION.md` | Implementation guide (code-level, module-by-module) |

## Related Documents

| Document | Location | Relationship |
| --- | --- | --- |
| Ingestion Platform Spec | `docs/ingestion/INGESTION_PLATFORM_SPEC.md` | Cross-cutting platform requirements (error handling, re-ingestion, idempotency) that apply to all queues |
| Document Processing Spec | `docs/ingestion/document_processing/DOCUMENT_PROCESSING_SPEC.md` | Phase 1 pipeline requirements; activities executed by workers polling both queues |
| Embedding Pipeline Spec | `docs/ingestion/embedding/EMBEDDING_PIPELINE_SPEC.md` | Phase 2 pipeline requirements; activities executed by workers polling both queues |
| Current Temporal Workflows | `src/ingest/temporal/workflows.py` | Existing workflow definitions modified by this spec |
| Current Worker Config | `src/ingest/temporal/worker.py` | Existing worker entry point modified by this spec |
