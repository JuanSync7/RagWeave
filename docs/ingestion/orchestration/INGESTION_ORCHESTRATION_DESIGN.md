> **Document type:** Design document (Layer 4)
> **Upstream:** INGESTION_ORCHESTRATION_SPEC.md
> **Last updated:** 2026-04-15

# Ingestion Orchestration — Design (v1.0.0)

| Field | Value |
|-------|-------|
| **Document** | Ingestion Orchestration Design Document |
| **Version** | 1.0.0 |
| **Status** | Active |
| **Spec Reference** | `INGESTION_ORCHESTRATION_SPEC.md` v1.0.0 (FR-3550–FR-3576, NFR-3580–NFR-3582) |
| **Companion Documents** | `INGESTION_ORCHESTRATION_SPEC.md`, `EMBEDDING_PIPELINE_DESIGN.md`, `DOCUMENT_PROCESSING_DESIGN.md`, `INGESTION_PLATFORM_SPEC.md` |
| **Created** | 2026-04-15 |
| **Last Updated** | 2026-04-15 |

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-04-15 | Initial design. Covers dual queue configuration, priority assignment, worker slot allocation, and legacy queue migration. |

> **Document Intent.** This design document translates the requirements defined in
> `INGESTION_ORCHESTRATION_SPEC.md` (FR-3550–FR-3576, NFR-3580–NFR-3582) into a task-oriented
> implementation plan. Each task maps to one or more specification requirements and includes
> subtasks, complexity estimates, dependencies, and testing strategies.
>
> The Ingestion Orchestration layer replaces the current single Temporal task queue
> (`rag-reliability`) with a dual-queue topology that separates user-initiated ingestion from
> background maintenance work, and adds per-workflow priority within the user queue to prevent
> batch submissions from starving single-document requests.

---

## 1. Overview

The current ingestion system routes all workflows through a single Temporal task queue
(`rag-reliability`) with no priority differentiation. This creates three problems:

1. Background work (GC sync, rehash, schema migration) blocks user-facing ingestion.
2. A 500-document batch submission blocks a subsequent single-document request.
3. No mechanism exists to express scheduling priority at any granularity.

The orchestration layer resolves these through two complementary mechanisms:

- **Dual task queues:** `ingest-user` for user-initiated work, `ingest-background` for
  system-initiated maintenance. Queue-level isolation ensures background work never blocks
  interactive requests.
- **Per-workflow priority:** Within the `ingest-user` queue, single-document workflows receive
  priority 1 (high) and batch child workflows receive priority 2 (medium). Temporal's native
  priority scheduling ensures the single document is dispatched ahead of pending batch items.

Workers poll both queues simultaneously with configurable slot allocation (default: 3 user
slots, 1 background slot), ensuring background work progresses without consuming user-facing
capacity.

---

## 2. Current State Analysis

### 2.1 Current Worker Configuration

The worker in `src/ingest/temporal/worker.py` creates a single `Worker` instance polling the
`TEMPORAL_TASK_QUEUE` (default: `rag-reliability`) with a configurable
`max_concurrent_activities` (default: 4, overridable via `RAG_INGEST_WORKER_CONCURRENCY`).

```python
# Current: single worker, single queue
worker = Worker(
    client,
    task_queue=task_queue,
    workflows=[IngestDirectoryWorkflow, IngestDocumentWorkflow],
    activities=[document_processing_activity, embedding_pipeline_activity],
    max_concurrent_activities=max_concurrent_activities,
)
```

The `main()` function reads `RAG_INGEST_TASK_QUEUE` and `RAG_INGEST_WORKER_CONCURRENCY` from
environment variables. No priority or multi-queue support exists.

### 2.2 Current Workflow Submission

In `src/ingest/temporal/workflows.py`, `IngestDirectoryWorkflow` spawns child workflows via
`start_child_workflow()` with no `priority` parameter and no explicit `task_queue` parameter
(children inherit the parent's queue). `IngestDocumentWorkflow` is a simple two-phase workflow
with no priority awareness.

### 2.3 Current Settings

`config/settings.py` exports `TEMPORAL_TASK_QUEUE` (default: `rag-reliability`) and
`TEMPORAL_TARGET_HOST`. No queue topology, slot allocation, or priority settings exist.

---

## 3. Task Decomposition

### 3.1 Dual Queue Configuration

**Description:** Add the dual-queue settings to `config/settings.py` and implement validation
logic. Define the two queue names, legacy fallback behavior, and startup validation.

**Requirements Covered:** FR-3550, FR-3551, FR-3552, FR-3553, FR-3570

**Dependencies:** None

**Complexity:** S

**Subtasks:**

1. **Settings additions.** Add to `config/settings.py`:
   - `TEMPORAL_USER_TASK_QUEUE = os.environ.get("RAG_INGEST_USER_TASK_QUEUE", "ingest-user")`
   - `TEMPORAL_BACKGROUND_TASK_QUEUE = os.environ.get("RAG_INGEST_BACKGROUND_TASK_QUEUE", "ingest-background")`
   Following the existing pattern for `TEMPORAL_TASK_QUEUE` (FR-3570).
2. **Legacy fallback.** When both `RAG_INGEST_USER_TASK_QUEUE` and `RAG_INGEST_BACKGROUND_TASK_QUEUE`
   are unset, fall back to `TEMPORAL_TASK_QUEUE` (default `rag-reliability`) for all workflows.
   This preserves single-queue behavior for existing deployments (FR-3553).
3. **Queue name validation.** At import time or worker startup, validate queue names: non-empty,
   no whitespace, max 200 characters. Fail fast with a clear error on invalid names (FR-3570 AC-3).
4. **Slot configuration additions.** Add to `config/settings.py`:
   - `INGEST_USER_SLOTS = int(os.environ.get("RAG_INGEST_USER_SLOTS", "3"))`
   - `INGEST_BACKGROUND_SLOTS = int(os.environ.get("RAG_INGEST_BACKGROUND_SLOTS", "1"))`
   - Legacy fallback: if `RAG_INGEST_WORKER_CONCURRENCY` is set and slot-specific variables are
     not, divide as 75% user / 25% background (minimum 1 each). If all three are set, slot-specific
     variables win and a log warning is emitted (FR-3571).
5. **Slot validation.** Each slot value must be >= 1 and the sum must be >= 2. Fail fast on
   violation (FR-3561 AC-4, AC-5).
6. **Priority value configuration.** Add configurable priority values with validation that
   high < medium < low (FR-3572).

**Testing Strategy:**

- Unit tests for legacy fallback: verify single-queue behavior when new env vars are unset.
- Unit tests for validation: invalid queue names, slot values of 0, priority ordering violation.
- Unit test for slot legacy fallback: verify 75/25 split calculation.

---

### 3.2 Priority Assignment Logic

**Description:** Define priority constants and implement the priority assignment at each
workflow submission call site. Priority is always implicit based on trigger type.

**Requirements Covered:** FR-3555, FR-3556, FR-3557, FR-3565, FR-3566, FR-3567

**Dependencies:** Task 3.1 (priority value configuration)

**Complexity:** S

**Subtasks:**

1. **Priority constants module.** Create or extend `src/ingest/temporal/constants.py` (or
   `src/ingest/common/types.py`) with named constants (FR-3567):
   ```python
   """Ingestion workflow priority levels.

   Priority is assigned implicitly based on the ingestion trigger type.
   Lower numeric values indicate higher scheduling priority.
   There is no user-facing mechanism to set priority directly (FR-3565).
   """
   PRIORITY_HIGH: int = 1    # Single-document, user-initiated
   PRIORITY_MEDIUM: int = 2  # Batch directory, user-initiated
   PRIORITY_LOW: int = 3     # Background (GC, rehash, migration)
   ```
   Use configurable values from `config/settings.py` if overridden (FR-3572).
2. **Workflow input extension.** Add `trigger_type: str` field to `IngestDocumentArgs` and
   `IngestDirectoryArgs` dataclasses in `src/ingest/temporal/workflows.py`. Valid values:
   `"single"`, `"batch"`, `"background"` (FR-3565).
3. **Submission call site: CLI `ingest` command.** Update the CLI handler to pass
   `priority=PRIORITY_HIGH` and `task_queue=TEMPORAL_USER_TASK_QUEUE` when submitting a
   single-document workflow. Pass `priority=PRIORITY_MEDIUM` and
   `task_queue=TEMPORAL_USER_TASK_QUEUE` for directory ingestion (FR-3566 AC-1).
4. **Submission call site: API `/ingest` endpoint.** Same as CLI: route to `ingest-user` with
   appropriate priority based on single vs. directory (FR-3552 AC-2, AC-3).
5. **Submission call site: background scheduler.** Update GC, rehash, and schema migration
   triggers to pass `priority=PRIORITY_LOW` and `task_queue=TEMPORAL_BACKGROUND_TASK_QUEUE`
   (FR-3557, FR-3566 AC-3).
6. **Child workflow priority propagation.** In `IngestDirectoryWorkflow.run()`, update
   `start_child_workflow()` calls to include `priority=PRIORITY_MEDIUM`. The priority value
   SHALL be sourced from workflow input, not hardcoded in the workflow class (FR-3556).
7. **No hardcoded priority in workflow classes.** Verify that `IngestDocumentWorkflow` and
   `IngestDirectoryWorkflow` contain no hardcoded priority values. Priority is set by the caller
   (FR-3566 AC-4).

**Testing Strategy:**

- Unit test: verify priority constants match configured values.
- Unit test: verify `IngestDirectoryWorkflow` propagates priority to child workflows.
- Integration test: submit a single-doc workflow with priority 1 and a batch child with
  priority 2, verify ordering in the task queue (NFR-3580).

---

### 3.3 Worker Slot Allocation

**Description:** Refactor the worker to poll both queues with hard slot isolation using two
`Worker` instances in the same process.

**Requirements Covered:** FR-3560, FR-3561, FR-3562, FR-3575, FR-3576, NFR-3581

**Dependencies:** Task 3.1 (configuration)

**Complexity:** M

**Subtasks:**

1. **Dual-worker architecture.** Refactor `run_worker()` in `src/ingest/temporal/worker.py` to
   create two `Worker` instances in the same process (FR-3560, implementation note 7.1 from
   spec):
   ```python
   user_worker = Worker(
       client,
       task_queue=TEMPORAL_USER_TASK_QUEUE,
       max_concurrent_activities=INGEST_USER_SLOTS,
       workflows=[IngestDirectoryWorkflow, IngestDocumentWorkflow],
       activities=[document_processing_activity, embedding_pipeline_activity],
   )
   bg_worker = Worker(
       client,
       task_queue=TEMPORAL_BACKGROUND_TASK_QUEUE,
       max_concurrent_activities=INGEST_BACKGROUND_SLOTS,
       workflows=[IngestDirectoryWorkflow, IngestDocumentWorkflow],
       activities=[document_processing_activity, embedding_pipeline_activity],
   )
   await asyncio.gather(user_worker.run(), bg_worker.run())
   ```
   Both workers share the same prewarmed resources (embedding model, DB clients). The
   `prewarm_worker_resources()` call runs once before both workers start.
2. **Slot enforcement.** Hard slot isolation is achieved by separate `Worker` instances, each
   with its own `max_concurrent_activities`. Background tasks cannot consume user slots and
   vice versa (FR-3562). No slot borrowing between queues.
3. **Legacy single-worker mode.** When running in legacy fallback (FR-3553), create a single
   `Worker` instance with the legacy queue name and `max_concurrent_activities` equal to the
   sum of user + background slots (or the legacy concurrency value).
4. **Startup logging.** Log both queue names, slot allocation, and mode (dual-queue or legacy)
   at INFO level (FR-3560 AC-3, FR-3575):
   ```
   worker started mode=dual-queue user_queue=ingest-user user_slots=3 bg_queue=ingest-background bg_slots=1
   ```
   In legacy mode, emit a warning advising migration (FR-3553 AC-3).
5. **Queue-aware structured logging.** Add `task_queue` and `priority` fields to workflow
   submission and task-pickup log entries (FR-3575). Use structured key-value logging, not
   string interpolation.
6. **Slot utilisation metrics (SHOULD).** Emit gauge metrics `ingest_worker_user_slots_active`
   and `ingest_worker_background_slots_active` via structured log lines at DEBUG level.
   Defer Prometheus endpoint integration to a follow-up iteration (FR-3576 AC-3).
7. **Update `main()`.** Update the `main()` entry point to read the new configuration variables
   and call the refactored `run_worker()`. Remove or deprecate `RAG_INGEST_TASK_QUEUE` in
   favor of the new queue-specific variables (but keep it as the legacy fallback).

**Testing Strategy:**

- Slot isolation test: submit concurrent tasks to both queues, verify that user-queue tasks
  cannot consume background slots and vice versa (FR-3562 AC-4).
- Legacy mode test: verify single-worker behavior when new env vars are unset.
- Queue independence test: verify that failures in one queue do not affect the other (NFR-3581).
- Startup log test: verify log output includes queue names and slot counts.

---

### 3.4 Legacy Queue Migration

**Description:** Implement the migration path from the single `rag-reliability` queue to the
dual-queue topology, ensuring zero-downtime transition.

**Requirements Covered:** FR-3553, NFR-3582

**Dependencies:** Tasks 3.1, 3.2, 3.3

**Complexity:** S

**Subtasks:**

1. **Phase 1: Deploy with legacy fallback.** Deploy new worker code with dual-queue support but
   no new environment variables set. Workers run in legacy mode, processing all workflows on
   `rag-reliability`. Verify existing workflows continue processing (NFR-3582 AC-1).
2. **Phase 2: Enable dual-queue workers.** Set `RAG_INGEST_USER_TASK_QUEUE` and
   `RAG_INGEST_BACKGROUND_TASK_QUEUE` environment variables. Restart workers. New workers poll
   both new queues. Old workers (if any remain) continue polling the legacy queue (NFR-3582 AC-2).
3. **Phase 3: Update submission call sites.** Deploy updated CLI, API, and scheduler code that
   routes workflows to the correct queue with the correct priority. New workflows go to the new
   queues; any remaining workflows on the legacy queue are drained by legacy-mode workers or
   new workers that also poll the legacy queue during transition.
4. **Phase 4: Drain and decommission.** Once the legacy queue is empty, remove legacy
   configuration. Workers no longer fall back to `rag-reliability`.
5. **Migration validation.** At each phase, verify:
   - No workflows are lost or stuck.
   - Worker logs confirm the expected queue polling configuration.
   - User-submitted workflows are routed to `ingest-user`.
   - Background workflows are routed to `ingest-background`.

**Testing Strategy:**

- Staged deployment test in a staging environment: walk through all four phases and verify
  no workflow loss.
- Verify that new workers with dual-queue config can coexist with old workers on the legacy
  queue during transition.

---

## 4. Temporal Configuration Details

### 4.1 Queue Topology

| Queue | Name (default) | Environment Variable | Purpose |
|-------|---------------|---------------------|---------|
| User | `ingest-user` | `RAG_INGEST_USER_TASK_QUEUE` | All user-initiated ingestion (single-doc, batch) |
| Background | `ingest-background` | `RAG_INGEST_BACKGROUND_TASK_QUEUE` | All system-initiated work (GC, rehash, migration) |
| Legacy | `rag-reliability` | `TEMPORAL_TASK_QUEUE` | Fallback when new queue vars are unset |

### 4.2 Priority Mapping

| Trigger Type | Queue | Priority | Constant |
|-------------|-------|----------|----------|
| Single-document (user) | `ingest-user` | 1 (high) | `PRIORITY_HIGH` |
| Batch directory (user) | `ingest-user` | 2 (medium) | `PRIORITY_MEDIUM` |
| Batch child workflow | `ingest-user` | 2 (medium) | `PRIORITY_MEDIUM` |
| GC sync | `ingest-background` | 3 (low) | `PRIORITY_LOW` |
| Rehash migration | `ingest-background` | 3 (low) | `PRIORITY_LOW` |
| Schema migration | `ingest-background` | 3 (low) | `PRIORITY_LOW` |
| Scheduled re-ingestion | `ingest-background` | 3 (low) | `PRIORITY_LOW` |

### 4.3 Worker Slot Defaults

| Setting | Environment Variable | Default | Constraint |
|---------|---------------------|---------|-----------|
| User slots | `RAG_INGEST_USER_SLOTS` | 3 | >= 1 |
| Background slots | `RAG_INGEST_BACKGROUND_SLOTS` | 1 | >= 1 |
| Legacy concurrency | `RAG_INGEST_WORKER_CONCURRENCY` | 4 | Fallback: 75/25 split |

### 4.4 Configuration Precedence

```
Slot-specific env vars (RAG_INGEST_USER_SLOTS, RAG_INGEST_BACKGROUND_SLOTS)
    ▼ (if unset, fall through)
Legacy env var (RAG_INGEST_WORKER_CONCURRENCY) → 75% user / 25% background
    ▼ (if unset, fall through)
Hardcoded defaults: user=3, background=1
```

---

## 5. Migration Path

### Phase 1: Code Deployment (No Config Change)

- Deploy new worker code. No new environment variables set.
- Workers detect legacy mode (FR-3553): single `rag-reliability` queue, combined slot count.
- Log warning: `"Running in legacy single-queue mode. Set RAG_INGEST_USER_TASK_QUEUE and RAG_INGEST_BACKGROUND_TASK_QUEUE to enable dual-queue topology."`.
- All existing workflows continue processing normally.

### Phase 2: Enable Dual-Queue Workers

- Set `RAG_INGEST_USER_TASK_QUEUE=ingest-user` and `RAG_INGEST_BACKGROUND_TASK_QUEUE=ingest-background`.
- Optionally set `RAG_INGEST_USER_SLOTS` and `RAG_INGEST_BACKGROUND_SLOTS`.
- Restart workers. New workers poll both new queues.
- Existing pending workflows on `rag-reliability` continue to be processed by any remaining
  legacy-mode workers or by temporarily running workers that poll all three queues.

### Phase 3: Update Submission Call Sites

- Deploy updated CLI, API, and scheduler code.
- New submissions route to the correct queue with priority.
- Verify via structured logs that `task_queue` and `priority` fields appear correctly.

### Phase 4: Decommission Legacy Queue

- Drain remaining workflows from `rag-reliability`.
- Remove legacy fallback configuration.
- Remove `RAG_INGEST_TASK_QUEUE` environment variable references from deployment manifests.

---

## Task Dependency Graph

```
Task 3.1: Dual Queue Configuration ─────────────────────────────────────┐
    │                                                                    │
    ├──► Task 3.2: Priority Assignment Logic ◄─── Task 3.1              │
    │                                                                    │
    ├──► Task 3.3: Worker Slot Allocation ◄─── Task 3.1                 │
    │                                                                    │
    └──► Task 3.4: Legacy Queue Migration ◄─── Tasks 3.1, 3.2, 3.3     │

Parallelisable:
  - Tasks 3.2 and 3.3 can proceed in parallel (both depend only on 3.1).

Critical path: 3.1 → 3.3 → 3.4
```

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|------|---------------------|
| 3.1 Dual Queue Configuration | FR-3550, FR-3551, FR-3552, FR-3553, FR-3570, FR-3571, FR-3572 |
| 3.2 Priority Assignment Logic | FR-3555, FR-3556, FR-3557, FR-3565, FR-3566, FR-3567 |
| 3.3 Worker Slot Allocation | FR-3560, FR-3561, FR-3562, FR-3575, FR-3576, NFR-3581 |
| 3.4 Legacy Queue Migration | FR-3553, NFR-3582 |
