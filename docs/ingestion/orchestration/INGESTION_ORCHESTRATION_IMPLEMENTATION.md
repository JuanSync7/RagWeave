> **Document type:** Implementation document (Layer 5)
> **Upstream:** INGESTION_ORCHESTRATION_DESIGN.md
> **Last updated:** 2026-04-15

# Ingestion Orchestration — Implementation Guide (v1.0.0)

| Field | Value |
|-------|-------|
| **Document** | Ingestion Orchestration Implementation Guide |
| **Version** | 1.0.0 |
| **Status** | Active |
| **Design Reference** | `INGESTION_ORCHESTRATION_DESIGN.md` v1.0.0 (Tasks 3.1–3.4) |
| **Spec Reference** | `INGESTION_ORCHESTRATION_SPEC.md` v1.0.0 (FR-3550–FR-3576, NFR-3580–NFR-3582) |
| **Companion Documents** | `INGESTION_ORCHESTRATION_SPEC.md`, `INGESTION_ORCHESTRATION_DESIGN.md`, `EMBEDDING_PIPELINE_IMPLEMENTATION.md`, `DOCUMENT_PROCESSING_IMPLEMENTATION.md` |
| **Created** | 2026-04-15 |
| **Last Updated** | 2026-04-15 |

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-04-15 | Initial implementation guide. Covers dual queue configuration, priority assignment, worker slot allocation, and legacy queue migration runbook. |

---

## 1. Implementation Overview

This document is the implementation source-of-truth for the Ingestion Orchestration layer. It translates the task decomposition in `INGESTION_ORCHESTRATION_DESIGN.md` into concrete configuration changes, code modifications, and migration procedures.

**Problem solved:** The current single Temporal task queue (`rag-reliability`) causes three failure modes: background work blocks interactive ingestion, batch submissions starve single-document requests, and no mechanism exists to express scheduling priority.

**Solution:** Two complementary mechanisms:

1. **Dual task queues:** `ingest-user` for user-initiated work, `ingest-background` for system-initiated maintenance.
2. **Per-workflow priority:** Within `ingest-user`, single-document workflows get priority 1 (high) and batch children get priority 2 (medium). Temporal's native priority scheduling dispatches single documents ahead of pending batch items.

**Files modified:**

| File | Change |
|------|--------|
| `config/settings.py` | Add dual-queue, slot allocation, and priority env vars |
| `src/ingest/temporal/constants.py` | New file: priority constants |
| `src/ingest/temporal/worker.py` | Dual-worker architecture with slot isolation |
| `src/ingest/temporal/workflows.py` | Add `trigger_type` to workflow args |
| CLI / API submission call sites | Route to correct queue with correct priority |

---

## 2. Queue Configuration

**Design task:** 3.1
**Requirements:** FR-3550, FR-3551, FR-3552, FR-3553, FR-3570, FR-3571, FR-3572

### 2.1 Settings Additions

```python
# config/settings.py — additions

import os
import logging

logger = logging.getLogger("rag.config")

# --- Temporal Queue Topology (FR-3570) ---
TEMPORAL_USER_TASK_QUEUE = os.environ.get(
    "RAG_INGEST_USER_TASK_QUEUE", ""
)
TEMPORAL_BACKGROUND_TASK_QUEUE = os.environ.get(
    "RAG_INGEST_BACKGROUND_TASK_QUEUE", ""
)

# --- Legacy Fallback (FR-3553) ---
# When both new queue vars are unset, fall back to the existing single queue.
_DUAL_QUEUE_ENABLED = bool(TEMPORAL_USER_TASK_QUEUE and TEMPORAL_BACKGROUND_TASK_QUEUE)

if not _DUAL_QUEUE_ENABLED:
    # Legacy mode: single queue for everything
    TEMPORAL_USER_TASK_QUEUE = TEMPORAL_TASK_QUEUE
    TEMPORAL_BACKGROUND_TASK_QUEUE = TEMPORAL_TASK_QUEUE
else:
    # Defaults for dual-queue mode
    if not TEMPORAL_USER_TASK_QUEUE:
        TEMPORAL_USER_TASK_QUEUE = "ingest-user"
    if not TEMPORAL_BACKGROUND_TASK_QUEUE:
        TEMPORAL_BACKGROUND_TASK_QUEUE = "ingest-background"

# --- Worker Slot Allocation (FR-3571) ---
_LEGACY_CONCURRENCY = os.environ.get("RAG_INGEST_WORKER_CONCURRENCY")
_USER_SLOTS_RAW = os.environ.get("RAG_INGEST_USER_SLOTS")
_BG_SLOTS_RAW = os.environ.get("RAG_INGEST_BACKGROUND_SLOTS")

if _USER_SLOTS_RAW or _BG_SLOTS_RAW:
    # Slot-specific variables take precedence
    INGEST_USER_SLOTS = int(_USER_SLOTS_RAW) if _USER_SLOTS_RAW else 3
    INGEST_BACKGROUND_SLOTS = int(_BG_SLOTS_RAW) if _BG_SLOTS_RAW else 1
    if _LEGACY_CONCURRENCY:
        logger.warning(
            "RAG_INGEST_WORKER_CONCURRENCY is set alongside slot-specific "
            "variables; ignoring legacy concurrency value"
        )
elif _LEGACY_CONCURRENCY:
    # Legacy fallback: 75% user / 25% background (minimum 1 each)
    total = int(_LEGACY_CONCURRENCY)
    INGEST_BACKGROUND_SLOTS = max(1, total // 4)
    INGEST_USER_SLOTS = max(1, total - INGEST_BACKGROUND_SLOTS)
else:
    # Hardcoded defaults
    INGEST_USER_SLOTS = 3
    INGEST_BACKGROUND_SLOTS = 1

# --- Priority Values (FR-3572) ---
INGEST_PRIORITY_HIGH = int(os.environ.get("RAG_INGEST_PRIORITY_HIGH", "1"))
INGEST_PRIORITY_MEDIUM = int(os.environ.get("RAG_INGEST_PRIORITY_MEDIUM", "2"))
INGEST_PRIORITY_LOW = int(os.environ.get("RAG_INGEST_PRIORITY_LOW", "3"))
```

### 2.2 Validation Logic

```python
# config/settings.py — validation (called at import time or worker startup)

def validate_orchestration_config() -> None:
    """Validate queue topology, slot allocation, and priority configuration.

    Raises ValueError on invalid configuration. Called at worker startup
    to fail fast (FR-3561 AC-5, FR-3570 AC-3, FR-3572 AC-4).
    """
    # Queue name validation (FR-3570 AC-3)
    for name, value in [
        ("TEMPORAL_USER_TASK_QUEUE", TEMPORAL_USER_TASK_QUEUE),
        ("TEMPORAL_BACKGROUND_TASK_QUEUE", TEMPORAL_BACKGROUND_TASK_QUEUE),
    ]:
        if not value or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
        if len(value) > 200:
            raise ValueError(f"{name} exceeds maximum length of 200 characters")
        if any(c.isspace() for c in value):
            raise ValueError(f"{name} must not contain whitespace: {value!r}")

    # Slot validation (FR-3561 AC-4, AC-5)
    if INGEST_USER_SLOTS < 1:
        raise ValueError(
            f"RAG_INGEST_USER_SLOTS must be >= 1, got {INGEST_USER_SLOTS}"
        )
    if INGEST_BACKGROUND_SLOTS < 1:
        raise ValueError(
            f"RAG_INGEST_BACKGROUND_SLOTS must be >= 1, got {INGEST_BACKGROUND_SLOTS}"
        )
    if INGEST_USER_SLOTS + INGEST_BACKGROUND_SLOTS < 2:
        raise ValueError(
            "Total slot count (user + background) must be >= 2"
        )

    # Priority ordering validation (FR-3572 AC-4)
    if not (INGEST_PRIORITY_HIGH < INGEST_PRIORITY_MEDIUM < INGEST_PRIORITY_LOW):
        raise ValueError(
            f"Priority ordering violated: high ({INGEST_PRIORITY_HIGH}) "
            f"must be < medium ({INGEST_PRIORITY_MEDIUM}) "
            f"must be < low ({INGEST_PRIORITY_LOW})"
        )
```

---

## 3. Priority Assignment Implementation

**Design task:** 3.2
**Requirements:** FR-3555, FR-3556, FR-3557, FR-3565, FR-3566, FR-3567

### 3.1 Priority Constants Module

```python
# src/ingest/temporal/constants.py (NEW FILE)

"""Ingestion workflow priority levels.

Priority is assigned implicitly based on the ingestion trigger type.
Lower numeric values indicate higher scheduling priority. There is no
user-facing mechanism to set priority directly (FR-3565).

The values below are defaults; they can be overridden via environment
variables RAG_INGEST_PRIORITY_HIGH, RAG_INGEST_PRIORITY_MEDIUM, and
RAG_INGEST_PRIORITY_LOW (FR-3572).
"""

from config.settings import (
    INGEST_PRIORITY_HIGH,
    INGEST_PRIORITY_MEDIUM,
    INGEST_PRIORITY_LOW,
)

PRIORITY_HIGH: int = INGEST_PRIORITY_HIGH    # Single-document, user-initiated
PRIORITY_MEDIUM: int = INGEST_PRIORITY_MEDIUM  # Batch directory, user-initiated
PRIORITY_LOW: int = INGEST_PRIORITY_LOW      # Background (GC, rehash, migration)
```

### 3.2 Workflow Input Extension

```python
# src/ingest/temporal/workflows.py — updated dataclasses

@dataclass
class IngestDocumentArgs:
    source: SourceArgs
    config: dict
    trigger_type: str = "single"  # "single" | "batch" | "background"


@dataclass
class IngestDirectoryArgs:
    sources: list
    config: dict
    trigger_type: str = "batch"   # "batch" | "background"
```

### 3.3 Submission Call Site: CLI

```python
# In CLI ingest command handler

from config.settings import TEMPORAL_USER_TASK_QUEUE
from src.ingest.temporal.constants import PRIORITY_HIGH, PRIORITY_MEDIUM

# Single-document ingestion (FR-3565 AC-1, FR-3566 AC-1)
await client.start_workflow(
    IngestDocumentWorkflow.run,
    IngestDocumentArgs(source=source, config=config_dict, trigger_type="single"),
    id=f"ingest-doc-{source_key}",
    task_queue=TEMPORAL_USER_TASK_QUEUE,
    priority=PRIORITY_HIGH,
)

# Directory ingestion (FR-3565 AC-4)
await client.start_workflow(
    IngestDirectoryWorkflow.run,
    IngestDirectoryArgs(sources=sources, config=config_dict, trigger_type="batch"),
    id=f"ingest-dir-{dir_key}",
    task_queue=TEMPORAL_USER_TASK_QUEUE,
    priority=PRIORITY_MEDIUM,
)
```

### 3.4 Submission Call Site: Background Scheduler

```python
# In GC/sync/rehash/migration triggers

from config.settings import TEMPORAL_BACKGROUND_TASK_QUEUE
from src.ingest.temporal.constants import PRIORITY_LOW

# Background ingestion (FR-3557, FR-3566 AC-3)
await client.start_workflow(
    IngestDocumentWorkflow.run,
    IngestDocumentArgs(source=source, config=config_dict, trigger_type="background"),
    id=f"ingest-doc-{source_key}",
    task_queue=TEMPORAL_BACKGROUND_TASK_QUEUE,
    priority=PRIORITY_LOW,
)
```

### 3.5 Child Workflow Priority Propagation

```python
# In src/ingest/temporal/workflows.py — IngestDirectoryWorkflow.run()

from src.ingest.temporal.constants import PRIORITY_MEDIUM

@workflow.defn
class IngestDirectoryWorkflow:
    @workflow.run
    async def run(self, args: IngestDirectoryArgs) -> IngestDirectoryResult:
        child_handles = []
        for source_dict in args.sources:
            source = SourceArgs(**source_dict) if isinstance(source_dict, dict) else source_dict
            handle = await workflow.start_child_workflow(
                IngestDocumentWorkflow,
                IngestDocumentArgs(
                    source=source,
                    config=args.config,
                    trigger_type="batch",  # Children are batch items
                ),
                id=f"ingest-doc-{source.source_key}",
                task_queue=workflow.info().task_queue,  # Inherit parent queue
                priority=PRIORITY_MEDIUM,  # FR-3556 AC-2
                retry_policy=RetryPolicy(maximum_attempts=1),
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
```

### 3.6 Queue-Aware Structured Logging

```python
# At workflow submission call sites (FR-3575)

logger.info(
    "workflow submitted",
    extra={
        "task_queue": task_queue,
        "priority": priority,
        "workflow_id": workflow_id,
        "trigger_type": trigger_type,
    },
)
```

---

## 4. Worker Slot Allocation

**Design task:** 3.3
**Requirements:** FR-3560, FR-3561, FR-3562, FR-3575, FR-3576, NFR-3581

### 4.1 Dual-Worker Architecture

```python
# src/ingest/temporal/worker.py — full refactored implementation

from __future__ import annotations

import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from config.settings import (
    TEMPORAL_TARGET_HOST,
    TEMPORAL_TASK_QUEUE,
    TEMPORAL_USER_TASK_QUEUE,
    TEMPORAL_BACKGROUND_TASK_QUEUE,
    INGEST_USER_SLOTS,
    INGEST_BACKGROUND_SLOTS,
    _DUAL_QUEUE_ENABLED,
    validate_orchestration_config,
)
from src.ingest.temporal.activities import (
    document_processing_activity,
    embedding_pipeline_activity,
    prewarm_worker_resources,
)
from src.ingest.temporal.workflows import IngestDirectoryWorkflow, IngestDocumentWorkflow

logger = logging.getLogger("rag.ingest.temporal.worker")

_WORKFLOWS = [IngestDirectoryWorkflow, IngestDocumentWorkflow]
_ACTIVITIES = [document_processing_activity, embedding_pipeline_activity]


async def run_worker() -> None:
    """Connect to Temporal, prewarm resources, and start worker(s).

    In dual-queue mode (FR-3560): creates two Worker instances in the same
    process, each polling a different queue with its own slot limit.
    Hard slot isolation is achieved by separate Worker instances (FR-3562).

    In legacy mode (FR-3553): creates a single Worker on the legacy queue.
    """
    validate_orchestration_config()

    logger.info("prewarming worker resources (loading embedding model)...")
    prewarm_worker_resources()
    logger.info("worker resources ready")

    client = await Client.connect(TEMPORAL_TARGET_HOST)

    if _DUAL_QUEUE_ENABLED:
        # --- Dual-queue mode ---
        user_worker = Worker(
            client,
            task_queue=TEMPORAL_USER_TASK_QUEUE,
            max_concurrent_activities=INGEST_USER_SLOTS,
            workflows=_WORKFLOWS,
            activities=_ACTIVITIES,
        )
        bg_worker = Worker(
            client,
            task_queue=TEMPORAL_BACKGROUND_TASK_QUEUE,
            max_concurrent_activities=INGEST_BACKGROUND_SLOTS,
            workflows=_WORKFLOWS,
            activities=_ACTIVITIES,
        )
        logger.info(
            "worker started mode=dual-queue "
            "user_queue=%s user_slots=%d "
            "bg_queue=%s bg_slots=%d",
            TEMPORAL_USER_TASK_QUEUE,
            INGEST_USER_SLOTS,
            TEMPORAL_BACKGROUND_TASK_QUEUE,
            INGEST_BACKGROUND_SLOTS,
        )
        # Both workers run concurrently, sharing prewarmed resources
        await asyncio.gather(user_worker.run(), bg_worker.run())

    else:
        # --- Legacy single-queue mode (FR-3553) ---
        total_slots = INGEST_USER_SLOTS + INGEST_BACKGROUND_SLOTS
        worker = Worker(
            client,
            task_queue=TEMPORAL_TASK_QUEUE,
            max_concurrent_activities=total_slots,
            workflows=_WORKFLOWS,
            activities=_ACTIVITIES,
        )
        logger.warning(
            "Running in legacy single-queue mode. "
            "Set RAG_INGEST_USER_TASK_QUEUE and RAG_INGEST_BACKGROUND_TASK_QUEUE "
            "to enable dual-queue topology. "
            "task_queue=%s max_concurrent_activities=%d",
            TEMPORAL_TASK_QUEUE,
            total_slots,
        )
        await worker.run()


def main() -> None:
    """Entry point for the ingestion worker process."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
```

### 4.2 Slot Enforcement

Hard slot isolation is achieved structurally: each `Worker` instance has its own `max_concurrent_activities` limit. Because the two workers are separate objects polling separate queues, background tasks cannot consume user slots and vice versa (FR-3562).

Key invariants:
- When all user-queue slots are occupied, additional user tasks wait in the queue.
- When all background-queue slots are occupied, additional background tasks wait.
- Background tasks never overflow into user slots (capacity is reserved, not borrowed).

### 4.3 Slot Utilisation Logging

```python
# Deferred to follow-up: Prometheus gauge metrics (FR-3576 AC-3).
# For v1, emit structured log lines at DEBUG level:

logger.debug(
    "slot_utilisation",
    extra={
        "ingest_worker_user_slots_active": user_active_count,
        "ingest_worker_background_slots_active": bg_active_count,
    },
)
```

---

## 5. Configuration Reference

### 5.1 Queue Topology

| Setting | Env Variable | Default | Constraint | FR |
|---------|-------------|---------|-----------|-----|
| User queue name | `RAG_INGEST_USER_TASK_QUEUE` | `ingest-user` | Non-empty, no whitespace, max 200 chars | FR-3550, FR-3570 |
| Background queue name | `RAG_INGEST_BACKGROUND_TASK_QUEUE` | `ingest-background` | Non-empty, no whitespace, max 200 chars | FR-3551, FR-3570 |
| Legacy queue name | `TEMPORAL_TASK_QUEUE` | `rag-reliability` | Fallback when new vars unset | FR-3553 |

### 5.2 Worker Slot Allocation

| Setting | Env Variable | Default | Constraint | FR |
|---------|-------------|---------|-----------|-----|
| User queue slots | `RAG_INGEST_USER_SLOTS` | `3` | >= 1 | FR-3561 |
| Background queue slots | `RAG_INGEST_BACKGROUND_SLOTS` | `1` | >= 1 | FR-3561 |
| Legacy concurrency | `RAG_INGEST_WORKER_CONCURRENCY` | `4` | Fallback: 75/25 split | FR-3571 |

**Precedence:**

```
Slot-specific env vars (RAG_INGEST_USER_SLOTS, RAG_INGEST_BACKGROUND_SLOTS)
    | (if unset, fall through)
    v
Legacy env var (RAG_INGEST_WORKER_CONCURRENCY) -> 75% user / 25% background
    | (if unset, fall through)
    v
Hardcoded defaults: user=3, background=1
```

### 5.3 Priority Values

| Setting | Env Variable | Default | Constraint | FR |
|---------|-------------|---------|-----------|-----|
| High priority | `RAG_INGEST_PRIORITY_HIGH` | `1` | Must be < medium | FR-3567, FR-3572 |
| Medium priority | `RAG_INGEST_PRIORITY_MEDIUM` | `2` | Must be > high, < low | FR-3567, FR-3572 |
| Low priority | `RAG_INGEST_PRIORITY_LOW` | `3` | Must be > medium | FR-3567, FR-3572 |

### 5.4 Priority Mapping

| Trigger Type | Queue | Priority | Constant |
|-------------|-------|----------|----------|
| Single-document (user) | `ingest-user` | 1 (high) | `PRIORITY_HIGH` |
| Batch directory parent (user) | `ingest-user` | 2 (medium) | `PRIORITY_MEDIUM` |
| Batch child workflow | `ingest-user` | 2 (medium) | `PRIORITY_MEDIUM` |
| GC sync | `ingest-background` | 3 (low) | `PRIORITY_LOW` |
| Rehash migration | `ingest-background` | 3 (low) | `PRIORITY_LOW` |
| Schema migration | `ingest-background` | 3 (low) | `PRIORITY_LOW` |
| Scheduled re-ingestion | `ingest-background` | 3 (low) | `PRIORITY_LOW` |

---

## 6. Migration Runbook

### Phase 1: Deploy New Code (No Config Change)

**Goal:** Deploy workers with dual-queue support but legacy fallback active.

1. Merge the updated `worker.py`, `settings.py`, and `constants.py`.
2. Deploy to all worker replicas. **Do not set** `RAG_INGEST_USER_TASK_QUEUE` or `RAG_INGEST_BACKGROUND_TASK_QUEUE`.
3. Workers detect legacy mode automatically (FR-3553).
4. **Verify:**
   - Worker logs show: `"Running in legacy single-queue mode..."`.
   - All existing pending workflows on `rag-reliability` continue processing.
   - No errors in worker or workflow logs.

### Phase 2: Enable Dual-Queue Workers

**Goal:** Workers poll both new queues with slot isolation.

1. Set environment variables:
   ```bash
   RAG_INGEST_USER_TASK_QUEUE=ingest-user
   RAG_INGEST_BACKGROUND_TASK_QUEUE=ingest-background
   # Optional: tune slot allocation
   RAG_INGEST_USER_SLOTS=3
   RAG_INGEST_BACKGROUND_SLOTS=1
   ```
2. Rolling restart of worker replicas.
3. **Verify:**
   - Worker logs show: `"worker started mode=dual-queue user_queue=ingest-user user_slots=3 bg_queue=ingest-background bg_slots=1"`.
   - During transition, keep at least one legacy-mode worker running to drain `rag-reliability`.

### Phase 3: Update Submission Call Sites

**Goal:** New workflow submissions route to the correct queue with correct priority.

1. Deploy updated CLI, API, and scheduler code with queue routing and priority assignment.
2. **Verify:**
   - `task_queue` and `priority` fields appear in workflow submission log entries.
   - Single-document ingestion goes to `ingest-user` with priority 1.
   - Batch ingestion goes to `ingest-user` with priority 2.
   - Background operations go to `ingest-background` with priority 3.

### Phase 4: Decommission Legacy Queue

**Goal:** Remove the legacy `rag-reliability` queue.

1. Wait for all workflows on `rag-reliability` to complete (check Temporal UI or `tctl`).
2. Remove `RAG_INGEST_TASK_QUEUE` from deployment manifests.
3. Remove `RAG_INGEST_WORKER_CONCURRENCY` if no longer needed.
4. **Verify:**
   - No workflows pending on `rag-reliability`.
   - All workers running in dual-queue mode.

### Rollback Procedure

If issues arise at any phase:

1. **Phase 1 rollback:** Revert code deployment. No config changes were made.
2. **Phase 2 rollback:** Unset `RAG_INGEST_USER_TASK_QUEUE` and `RAG_INGEST_BACKGROUND_TASK_QUEUE`. Restart workers. They return to legacy mode.
3. **Phase 3 rollback:** Revert CLI/API/scheduler code. Workflows resume going to the legacy queue (if workers still poll it).
4. **Phase 4 rollback:** Re-add `RAG_INGEST_TASK_QUEUE` to deployment manifests and restart workers in legacy mode.

---

## Task-to-Requirement Mapping

| Section | Design Task | Requirements Covered |
|---------|-------------|---------------------|
| 2. Queue Configuration | 3.1 | FR-3550, FR-3551, FR-3552, FR-3553, FR-3570, FR-3571, FR-3572 |
| 3. Priority Assignment | 3.2 | FR-3555, FR-3556, FR-3557, FR-3565, FR-3566, FR-3567 |
| 4. Worker Slot Allocation | 3.3 | FR-3560, FR-3561, FR-3562, FR-3575, FR-3576, NFR-3581 |
| 6. Migration Runbook | 3.4 | FR-3553, NFR-3582 |

---

## Companion Documents

| Document | Role |
|----------|------|
| `INGESTION_ORCHESTRATION_SPEC.md` | Authoritative requirements (FR-3550–FR-3576, NFR-3580–NFR-3582) |
| `INGESTION_ORCHESTRATION_DESIGN.md` | Task decomposition and dependency graph |
| `INGESTION_ORCHESTRATION_IMPLEMENTATION.md` (this document) | Implementation guide and migration runbook |
| `EMBEDDING_PIPELINE_IMPLEMENTATION.md` | Embedding pipeline implementation |
| `DOCUMENT_PROCESSING_IMPLEMENTATION.md` | Document processing implementation |
