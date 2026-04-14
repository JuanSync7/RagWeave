# @summary
# Temporal workflow definitions for per-document and per-directory ingestion.
# Exports: IngestDocumentWorkflow, IngestDirectoryWorkflow
# Deps: temporalio, src.ingest.temporal.activities, config.settings
# @end-summary
"""Temporal workflows for the two-phase ingestion pipeline.

IngestDocumentWorkflow   — one per document, chains Phase 1 → Phase 2.
IngestDirectoryWorkflow  — fans out to N IngestDocumentWorkflow children.

Workflow ID = source_key so re-submitting the same document is idempotent.
"""

from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from config.settings import (
        RAG_INGEST_TEMPORAL_DOC_TIMEOUT_MIN,
        RAG_INGEST_TEMPORAL_EMB_TIMEOUT_MIN,
        RAG_INGEST_TEMPORAL_RETRY_INTERVAL_S,
        RAG_INGEST_TEMPORAL_RETRY_MAX,
    )
    from src.ingest.temporal.activities import (
        ActivityArgs,
        DocProcessingResult,
        EmbeddingResult,
        SourceArgs,
        document_processing_activity,
        embedding_pipeline_activity,
    )


# ---------------------------------------------------------------------------
# Workflow input / output contracts
# ---------------------------------------------------------------------------

@dataclass
class IngestDocumentArgs:
    source: SourceArgs
    config: dict  # IngestionConfig serialised via dataclasses.asdict()


@dataclass
class IngestDocumentResult:
    source_key: str
    errors: list
    stored_count: int
    processing_log: list


@dataclass
class IngestDirectoryArgs:
    sources: list           # list[SourceArgs]
    config: dict


@dataclass
class IngestDirectoryResult:
    processed: int
    failed: int
    stored_chunks: int
    errors: list


# ---------------------------------------------------------------------------
# Per-document workflow
# ---------------------------------------------------------------------------

_DOC_PROCESSING_TIMEOUT = timedelta(minutes=RAG_INGEST_TEMPORAL_DOC_TIMEOUT_MIN)
_EMBEDDING_TIMEOUT = timedelta(minutes=RAG_INGEST_TEMPORAL_EMB_TIMEOUT_MIN)
_RETRY_POLICY = RetryPolicy(
    maximum_attempts=RAG_INGEST_TEMPORAL_RETRY_MAX,
    initial_interval=timedelta(seconds=RAG_INGEST_TEMPORAL_RETRY_INTERVAL_S),
)


@workflow.defn
class IngestDocumentWorkflow:
    """Two-phase ingestion for a single document.

    Phase 1 (document_processing_activity) runs first and saves output to
    CleanDocumentStore. If it succeeds, Phase 2 (embedding_pipeline_activity)
    reads from there — no large data is passed through Temporal.

    Either phase can be retried independently without re-running the other.
    """

    @workflow.run
    async def run(self, args: IngestDocumentArgs) -> IngestDocumentResult:
        activity_args = ActivityArgs(source=args.source, config=args.config)

        # ── Phase 1 ──────────────────────────────────────────────────────
        phase1: DocProcessingResult = await workflow.execute_activity(
            document_processing_activity,
            activity_args,
            schedule_to_close_timeout=_DOC_PROCESSING_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )
        if phase1.errors:
            return IngestDocumentResult(
                source_key=args.source.source_key,
                errors=phase1.errors,
                stored_count=0,
                processing_log=phase1.processing_log,
            )

        # ── Phase 2 ──────────────────────────────────────────────────────
        phase2: EmbeddingResult = await workflow.execute_activity(
            embedding_pipeline_activity,
            activity_args,
            schedule_to_close_timeout=_EMBEDDING_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )
        return IngestDocumentResult(
            source_key=args.source.source_key,
            errors=phase2.errors,
            stored_count=phase2.stored_count,
            processing_log=phase1.processing_log + phase2.processing_log,
        )


# ---------------------------------------------------------------------------
# Directory-level workflow (fan-out)
# ---------------------------------------------------------------------------

@workflow.defn
class IngestDirectoryWorkflow:
    """Submit one IngestDocumentWorkflow child per discovered source file.

    All children run concurrently up to Temporal's concurrency limits.
    Results are collected and summarised.
    """

    @workflow.run
    async def run(self, args: IngestDirectoryArgs) -> IngestDirectoryResult:
        child_handles = []
        for source_dict in args.sources:
            source = SourceArgs(**source_dict) if isinstance(source_dict, dict) else source_dict
            handle = await workflow.start_child_workflow(
                IngestDocumentWorkflow,
                IngestDocumentArgs(source=source, config=args.config),
                id=f"ingest-doc-{source.source_key}",
                retry_policy=RetryPolicy(maximum_attempts=1),  # retries handled inside child
            )
            child_handles.append(handle)

        results = await asyncio.gather(*child_handles, return_exceptions=True)

        processed = failed = stored_chunks = 0
        errors: list = []
        for r in results:
            if isinstance(r, Exception):
                failed += 1
                errors.append(str(r))
            elif r.errors:
                failed += 1
                errors.extend(r.errors)
            else:
                processed += 1
                stored_chunks += r.stored_count

        return IngestDirectoryResult(
            processed=processed,
            failed=failed,
            stored_chunks=stored_chunks,
            errors=errors,
        )
