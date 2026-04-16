> **Document type:** Authoritative requirements specification (Layer 3)
> **Downstream:** INGESTION_ORCHESTRATION_SPEC_SUMMARY.md
> **Last updated:** 2026-04-15

# Ingestion Orchestration --- Specification (v1.0.0)

## Document Information

> **Document intent:** This is a formal specification for the **Ingestion Orchestration** layer --- the Temporal-based queue topology, per-workflow priority scheme, and worker slot allocation that govern how ingestion workloads are scheduled, prioritised, and executed. This specification defines the dual-queue architecture that separates user-initiated ingestion from background maintenance work, and the intra-queue priority mechanism that prevents large batch submissions from starving single-document requests.
> For Phase 1 functional requirements (document processing), see `DOCUMENT_PROCESSING_SPEC.md`.
> For Phase 2 functional requirements (embedding pipeline), see `EMBEDDING_PIPELINE_SPEC.md`.
> For cross-cutting platform requirements (re-ingestion, config, error handling, data model, NFR), see `INGESTION_PLATFORM_SPEC.md`.

| Field | Value |
|-------|-------|
| System | AION RAG Document Embedding Pipeline |
| Document Type | Pipeline Specification --- Orchestration Layer |
| Companion Documents | DOCUMENT_PROCESSING_SPEC.md (Phase 1 Functional Requirements), EMBEDDING_PIPELINE_SPEC.md (Phase 2 Functional Requirements), INGESTION_PLATFORM_SPEC.md (Platform/Cross-Cutting Requirements), INGESTION_ORCHESTRATION_SPEC_SUMMARY.md (This Spec Summary) |
| Version | 1.0.0 |
| Status | Draft |
| Supersedes | N/A (new specification) |

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-04-15 | AI Assistant | Initial specification. Defines dual Temporal task queue topology, intra-queue workflow priority, worker slot allocation, and priority assignment rules. FR-3550 through FR-3599. |

---

## 1. Purpose and Scope

### 1.1 Problem Statement

The current ingestion pipeline routes all workflows --- user-initiated single-document ingestion, large batch directory ingestion, background sync operations, rehash migrations, and schema migrations --- through a single Temporal task queue (`rag-reliability`). This design has three compounding failure modes:

1. **Background starvation of interactive work.** A scheduled GC sync or schema migration that enqueues hundreds of re-processing workflows will fill the task queue. A user who then submits a single document for immediate use must wait behind the entire background backlog, even though the background work is non-urgent.

2. **Batch starvation of single-document work.** Even within user-initiated work, a user who submits a 500-document directory ingestion and then immediately submits one more document will see the single document queued behind 499 batch items. The single document is almost certainly more urgent --- the user wants to query it now --- but the system treats it identically to the batch items.

3. **No differentiation mechanism.** Temporal task queues are FIFO by default. Without either multiple queues or per-workflow priority, the system cannot express "this workflow matters more than that one" at any granularity.

This specification defines the orchestration layer that resolves all three failure modes through a dual-mechanism approach: separate task queues for workload isolation, combined with per-workflow priority within the user-facing queue for fine-grained scheduling.

### 1.2 Scope

The Ingestion Orchestration layer SHALL define the Temporal queue topology, workflow priority assignment, and worker slot allocation that control how ingestion workflows are scheduled and executed.

**Entry point:** A workflow submission request (single document, batch directory, or background operation) arriving at the Temporal client.

**Exit point:** The workflow is dispatched to the correct task queue with the correct priority, picked up by a worker with available capacity, and executed through the existing two-phase pipeline (Phase 1: Document Processing, Phase 2: Embedding Pipeline).

**In scope:**

- Temporal task queue topology (queue names, routing rules)
- Per-workflow priority assignment within queues
- Worker configuration for multi-queue consumption with slot allocation
- Priority assignment rules mapping ingestion trigger types to priority levels
- Configuration schema for queue names, slot ratios, and priority values
- Interaction with existing `IngestDocumentWorkflow` and `IngestDirectoryWorkflow`

**Out of scope:**

- Modifications to the Phase 1 or Phase 2 pipeline logic (see `DOCUMENT_PROCESSING_SPEC.md`, `EMBEDDING_PIPELINE_SPEC.md`)
- Temporal cluster deployment, scaling, or operational procedures
- Rate limiting or throttling at the API/CLI layer (upstream concern)
- Cost-based scheduling or dynamic priority adjustment based on system load
- User-facing priority selection (priority is always implicit; see Section 3.4)
- Multi-tenant queue isolation (single-tenant deployment assumed)
- Workflow cancellation or preemption of in-flight activities (Temporal does not support activity preemption; priority affects queue ordering only)

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| Task Queue | A named Temporal queue that workers poll for workflow and activity tasks. Workers subscribe to one or more task queues. |
| Workflow Priority | A numeric value attached to a workflow at submission time via `start_workflow()`. Lower numeric values indicate higher scheduling priority. Temporal uses this value to order pending tasks within a single task queue. |
| User Queue | The `ingest-user` task queue, serving all user-initiated ingestion workflows (single-document and batch). |
| Background Queue | The `ingest-background` task queue, serving all system-initiated maintenance workflows (GC sync, rehash, schema migration). |
| Slot Allocation | The configuration of how many concurrent activity execution slots a worker dedicates to each task queue it polls. |
| Single-Document Ingestion | An `IngestDocumentWorkflow` triggered directly by a user action (CLI command, API call, or UI upload) for one specific document. |
| Batch Ingestion | An `IngestDirectoryWorkflow` that fans out to N child `IngestDocumentWorkflow` instances for a directory of documents. |
| Background Ingestion | Any workflow triggered by a system-initiated process: GC sync, rehash migration, schema version migration, or scheduled re-ingestion. |
| Fan-Out | The pattern where `IngestDirectoryWorkflow` spawns one child `IngestDocumentWorkflow` per source file. Each child is an independent workflow with its own priority. |

---

## 2. Architecture Overview

### 2.1 Queue Topology

The orchestration layer introduces two named Temporal task queues replacing the current single `rag-reliability` queue:

```
                        +---------------------------+
                        |   Workflow Submission      |
                        |   (CLI / API / Scheduler)  |
                        +---------------------------+
                                    |
                     +--------------+--------------+
                     |                             |
              User-initiated                System-initiated
              (single-doc, batch)           (GC, rehash, migration)
                     |                             |
                     v                             v
        +------------------------+    +---------------------------+
        |   ingest-user          |    |   ingest-background       |
        |   Task Queue           |    |   Task Queue              |
        |                        |    |                           |
        |  Priority ordering:    |    |  FIFO ordering            |
        |  1 = High (single-doc) |    |  (all background work     |
        |  2 = Medium (batch)    |    |   is equal priority)      |
        +------------------------+    +---------------------------+
                     |                             |
                     +----------+    +-------------+
                                |    |
                                v    v
                    +---------------------------+
                    |   Ingestion Worker         |
                    |                            |
                    |   Polls BOTH queues:       |
                    |   - N slots for user queue  |
                    |   - M slots for bg queue    |
                    +---------------------------+
                                |
                    +-----------+-----------+
                    |                       |
                    v                       v
            Phase 1: Document       Phase 2: Embedding
            Processing Activity     Pipeline Activity
```

### 2.2 Worker Slot Allocation

Each worker process is configured with a total number of concurrent activity slots and a ratio that determines how those slots are divided between the two queues:

```
    Worker (max_concurrent_activities = 4)
    +-----------------------------------------+
    |  User Queue Slots: 3                     |
    |  [slot 1] [slot 2] [slot 3]             |
    |                                          |
    |  Background Queue Slots: 1               |
    |  [slot 4]                                |
    +-----------------------------------------+
```

The slot allocation ensures that background work can never fully consume a worker's capacity. Even under heavy background load, user-facing slots remain available for interactive work.

### 2.3 Priority Within the User Queue

Within the `ingest-user` queue, workflows are ordered by Temporal's native priority mechanism:

```
    ingest-user Task Queue
    +-----------------------------------------------+
    |  Priority 1 (High): Single-document workflows  |
    |  [doc-X] [doc-Y]                               |
    |                                                 |
    |  Priority 2 (Medium): Batch child workflows     |
    |  [batch-doc-1] [batch-doc-2] ... [batch-doc-N]  |
    +-----------------------------------------------+
         ^
         |  Worker picks highest-priority pending task
```

When a user submits a 500-document batch and then submits a single document, the single document (priority 1) is scheduled ahead of the remaining batch items (priority 2), even though the batch items were enqueued first.

---

## 3. Functional Requirements

### 3.1 Dual Task Queue Topology

> **FR-3550: User Task Queue**
> The system SHALL provide a dedicated Temporal task queue named `ingest-user` (configurable) for all user-initiated ingestion workflows.
> **Rationale:** Isolating user-initiated work from background maintenance ensures that interactive ingestion requests are never blocked behind a backlog of system-initiated operations. Queue-level isolation is the coarsest and most reliable scheduling boundary Temporal provides.
> **Acceptance Criteria:**
> 1. All `IngestDocumentWorkflow` instances triggered by user action (CLI, API, UI) SHALL be submitted to the `ingest-user` task queue.
> 2. All `IngestDirectoryWorkflow` instances triggered by user action SHALL be submitted to the `ingest-user` task queue.
> 3. Child workflows spawned by `IngestDirectoryWorkflow` SHALL inherit the parent's task queue (`ingest-user`).
> 4. The queue name SHALL be configurable via the `RAG_INGEST_USER_TASK_QUEUE` environment variable, defaulting to `ingest-user`.

> **FR-3551: Background Task Queue**
> The system SHALL provide a dedicated Temporal task queue named `ingest-background` (configurable) for all system-initiated maintenance workflows.
> **Rationale:** Background operations (GC sync, rehash, schema migration) are non-urgent and should not compete with user-facing work for queue position. A separate queue allows workers to drain background work only when user-facing capacity is available.
> **Acceptance Criteria:**
> 1. All workflows triggered by GC/sync operations SHALL be submitted to the `ingest-background` task queue.
> 2. All workflows triggered by rehash or schema migration jobs SHALL be submitted to the `ingest-background` task queue.
> 3. All workflows triggered by scheduled re-ingestion (cron-based) SHALL be submitted to the `ingest-background` task queue.
> 4. The queue name SHALL be configurable via the `RAG_INGEST_BACKGROUND_TASK_QUEUE` environment variable, defaulting to `ingest-background`.

> **FR-3552: Queue Routing at Submission**
> The workflow submission layer SHALL determine the target task queue based on the ingestion trigger type and route the `start_workflow()` call to the correct queue.
> **Rationale:** Queue routing must happen at submission time, not at worker poll time. The caller (CLI, API handler, scheduler) knows whether the operation is user-initiated or background-initiated and must encode that knowledge into the queue selection.
> **Acceptance Criteria:**
> 1. The `ingest_file()` and `ingest_directory()` public API functions SHALL accept a `queue` parameter (or derive it from context) that determines the target task queue.
> 2. The CLI `ingest` command SHALL route to `ingest-user` by default.
> 3. The API `/ingest` endpoint SHALL route to `ingest-user` by default.
> 4. Background scheduler and GC trigger paths SHALL route to `ingest-background`.
> 5. If an invalid or unrecognised queue name is provided, the system SHALL reject the submission with a clear error message rather than silently defaulting.

> **FR-3553: Backward Compatibility with Legacy Queue**
> The system SHALL support a transitional mode where the legacy single-queue configuration (`rag-reliability`) continues to function.
> **Rationale:** Existing deployments use the `rag-reliability` queue. A hard cutover with no transition path risks breaking running workers during upgrade. The legacy queue must remain functional until operators explicitly migrate.
> **Acceptance Criteria:**
> 1. If `RAG_INGEST_USER_TASK_QUEUE` and `RAG_INGEST_BACKGROUND_TASK_QUEUE` are both unset, the system SHALL fall back to the existing `TEMPORAL_TASK_QUEUE` setting (default `rag-reliability`) for all workflows, preserving current single-queue behavior.
> 2. Workers configured with only the legacy queue name SHALL continue to process all workflow types without error.
> 3. A log warning SHALL be emitted at worker startup when running in legacy single-queue mode, advising migration to the dual-queue topology.

### 3.2 Intra-Queue Priority (Per-Workflow Priority)

> **FR-3555: Priority Field on Workflow Submission**
> The system SHALL set the Temporal workflow priority field on every `IngestDocumentWorkflow` submission via the `start_workflow()` `priority` parameter.
> **Rationale:** Temporal supports native per-workflow priority that determines task ordering within a single queue. This is the mechanism that prevents a single document from waiting behind 499 batch items within the `ingest-user` queue. Without it, the user queue is still FIFO and the batch-starvation problem (Section 1.1, failure mode 2) remains unsolved.
> **Acceptance Criteria:**
> 1. Every `IngestDocumentWorkflow` started via `start_workflow()` SHALL include a `priority` value.
> 2. Temporal SHALL use the priority value to order pending tasks within the target queue such that lower numeric values are scheduled first.
> 3. The priority value SHALL be an integer in the range 1--5, where 1 is highest priority and 5 is lowest.
> 4. Workflows already executing SHALL NOT be affected by the priority of newly submitted workflows (priority affects queue ordering, not preemption).

> **FR-3556: Priority Propagation to Child Workflows**
> The `IngestDirectoryWorkflow` SHALL propagate the appropriate priority value to each child `IngestDocumentWorkflow` it spawns via `start_child_workflow()`.
> **Rationale:** When a directory workflow fans out to N children, each child becomes an independent workflow in the task queue. Without explicit priority propagation, child workflows would receive a default priority and could interleave unpredictably with single-document workflows.
> **Acceptance Criteria:**
> 1. `IngestDirectoryWorkflow.run()` SHALL set the `priority` parameter on every `start_child_workflow()` call.
> 2. The priority value assigned to batch children SHALL be the medium priority level (2) as defined in FR-3560.
> 3. The priority value SHALL be sourced from the workflow input args, not hardcoded in the workflow definition, to allow future configurability.

> **FR-3557: Priority on Background Workflows**
> Background workflows submitted to the `ingest-background` queue SHALL use the low priority level (3).
> **Rationale:** Although background workflows run on a separate queue and will not directly compete with user-facing work, assigning an explicit priority maintains consistency and prepares for future scenarios where a single worker might temporarily drain both queues through a shared priority namespace.
> **Acceptance Criteria:**
> 1. All workflows submitted to `ingest-background` SHALL have priority set to 3 (low).
> 2. Within the background queue, all workflows SHALL be treated as equal priority (FIFO within the same priority level).

### 3.3 Worker Slot Allocation

> **FR-3560: Multi-Queue Worker Polling**
> Each ingestion worker process SHALL poll both the `ingest-user` and `ingest-background` task queues simultaneously.
> **Rationale:** Running separate worker processes per queue wastes resources --- a dedicated background worker sits idle when no background work exists, while user-facing workers may be overloaded. A single worker polling both queues maximises resource utilisation while still allowing slot-based capacity reservation.
> **Acceptance Criteria:**
> 1. The worker process SHALL register with both the user and background task queues.
> 2. The worker SHALL accept tasks from either queue when capacity is available.
> 3. Worker startup logs SHALL report both queue names and the slot allocation.

> **FR-3561: Configurable Slot Ratio**
> The worker SHALL support configurable slot allocation between the user and background queues, expressed as a ratio or explicit slot count.
> **Rationale:** Different deployment environments have different workload profiles. A development environment may allocate slots equally, while a production environment under heavy user load may dedicate 75% or more of slots to the user queue. The ratio must be tunable without code changes.
> **Acceptance Criteria:**
> 1. The worker SHALL accept configuration for user-queue slots via `RAG_INGEST_USER_SLOTS` (integer, default 3).
> 2. The worker SHALL accept configuration for background-queue slots via `RAG_INGEST_BACKGROUND_SLOTS` (integer, default 1).
> 3. The total concurrent activities SHALL equal the sum of user and background slots (e.g., 3 + 1 = 4).
> 4. Both slot values SHALL be validated at startup: each MUST be >= 1 and the sum MUST be >= 2.
> 5. If validation fails, the worker SHALL refuse to start and log a clear error message.

> **FR-3562: Slot Enforcement**
> The worker SHALL enforce slot limits such that background work cannot consume user-queue capacity and vice versa.
> **Rationale:** Without enforcement, a burst of background work could consume all worker slots, leaving none for user-facing requests. The slot allocation is a capacity reservation, not a suggestion. The implementation MAY use separate Temporal Worker instances within the same process (one per queue) to achieve hard slot isolation.
> **Acceptance Criteria:**
> 1. When all user-queue slots are occupied, additional user-queue tasks SHALL wait in the queue rather than consuming background slots.
> 2. When all background-queue slots are occupied, additional background tasks SHALL wait in the queue rather than consuming user slots.
> 3. When user-queue slots are idle and background tasks are pending, the background tasks SHALL NOT overflow into user slots (capacity is reserved, not borrowed).
> 4. The implementation SHALL be validated by a test that submits concurrent tasks to both queues and verifies slot isolation.

### 3.4 Priority Assignment Rules

> **FR-3565: Implicit Priority Assignment**
> The system SHALL assign workflow priority implicitly based on the ingestion trigger type. There SHALL be no user-facing mechanism to set priority directly.
> **Rationale:** Priority is an infrastructure concern, not a user decision. The mapping from trigger type to priority is deterministic: a single-document submission is always urgent (the user wants to query it now), a batch submission is important but can tolerate ordering delays, and background work is non-urgent by definition. Exposing priority to users would add complexity with no clear benefit --- a user who thinks their work is urgent will submit a single document anyway.
> **Acceptance Criteria:**
> 1. Single-document ingestion (user submits one file via CLI, API, or UI) SHALL be assigned priority 1 (high).
> 2. Batch ingestion (user submits a directory or multi-file set) SHALL assign priority 2 (medium) to each child `IngestDocumentWorkflow`.
> 3. Background ingestion (GC sync, rehash, schema migration, scheduled re-ingestion) SHALL be assigned priority 3 (low).
> 4. The `IngestDirectoryWorkflow` parent workflow itself SHALL be assigned priority 2 (medium).
> 5. No CLI flag, API parameter, or UI control SHALL exist for setting ingestion priority.

> **FR-3566: Priority Assignment Location**
> Priority assignment SHALL occur at the workflow submission call site, not within the workflow definition.
> **Rationale:** The workflow definition (`IngestDocumentWorkflow`) should be agnostic to its own priority --- it processes a document regardless of how it was scheduled. The caller (CLI handler, API handler, scheduler, or parent workflow) knows the trigger context and is the correct place to determine priority.
> **Acceptance Criteria:**
> 1. The `start_workflow()` call for single-document ingestion SHALL include `priority=1`.
> 2. The `start_child_workflow()` call within `IngestDirectoryWorkflow` SHALL include `priority=2`.
> 3. The `start_workflow()` call from background schedulers SHALL include `priority=3`.
> 4. The `IngestDocumentWorkflow` and `IngestDirectoryWorkflow` classes SHALL NOT contain hardcoded priority values.

> **FR-3567: Priority Value Constants**
> The system SHALL define named constants for all priority levels in a shared module accessible to all submission call sites.
> **Rationale:** Magic numbers scattered across call sites are error-prone and hard to audit. Named constants provide a single source of truth and make priority semantics self-documenting.
> **Acceptance Criteria:**
> 1. A module (e.g., `src.ingest.common.types` or `src.ingest.temporal.constants`) SHALL export: `PRIORITY_HIGH = 1`, `PRIORITY_MEDIUM = 2`, `PRIORITY_LOW = 3`.
> 2. All workflow submission call sites SHALL reference these constants, not literal integers.
> 3. The constants module SHALL include a docstring explaining the priority semantics and the rationale for implicit-only assignment.

### 3.5 Configuration

> **FR-3570: Queue Name Configuration**
> All task queue names SHALL be configurable via environment variables with sensible defaults.
> **Rationale:** Queue names are deployment-specific. Operators must be able to customise them for namespace isolation, multi-environment deployments, or naming conventions without modifying code.
> **Acceptance Criteria:**
> 1. `RAG_INGEST_USER_TASK_QUEUE` SHALL configure the user queue name (default: `ingest-user`).
> 2. `RAG_INGEST_BACKGROUND_TASK_QUEUE` SHALL configure the background queue name (default: `ingest-background`).
> 3. Queue names SHALL be validated at startup: non-empty strings, no whitespace, max 200 characters.
> 4. Configuration SHALL be read from `config/settings.py` following the existing pattern for `TEMPORAL_TASK_QUEUE`.

> **FR-3571: Slot Allocation Configuration**
> Worker slot allocation SHALL be configurable via environment variables.
> **Rationale:** Slot allocation is a capacity planning decision that varies by deployment. Development environments may use 2+2, production may use 6+2, GPU-constrained environments may use 2+1. This must be tunable without rebuilding.
> **Acceptance Criteria:**
> 1. `RAG_INGEST_USER_SLOTS` SHALL configure user-queue slot count (integer, default: 3).
> 2. `RAG_INGEST_BACKGROUND_SLOTS` SHALL configure background-queue slot count (integer, default: 1).
> 3. `RAG_INGEST_WORKER_CONCURRENCY` SHALL remain supported as a legacy fallback: if set and the slot-specific variables are unset, the total concurrency SHALL be divided as 75% user / 25% background (rounded, minimum 1 each).
> 4. If all three variables are set, the slot-specific variables SHALL take precedence and `RAG_INGEST_WORKER_CONCURRENCY` SHALL be ignored with a log warning.

> **FR-3572: Priority Value Configuration**
> Priority numeric values SHOULD be configurable but SHALL default to the values defined in FR-3567.
> **Rationale:** The default priority values (1, 2, 3) are expected to be sufficient for all foreseeable use cases. However, if Temporal's priority range semantics change or an operator needs to interleave with other systems' priorities, override capability prevents a code change.
> **Acceptance Criteria:**
> 1. `RAG_INGEST_PRIORITY_HIGH` SHALL configure the high priority value (integer, default: 1).
> 2. `RAG_INGEST_PRIORITY_MEDIUM` SHALL configure the medium priority value (integer, default: 2).
> 3. `RAG_INGEST_PRIORITY_LOW` SHALL configure the low priority value (integer, default: 3).
> 4. Validation SHALL enforce: high < medium < low (strict ordering). If violated, the worker SHALL refuse to start.

### 3.6 Observability

> **FR-3575: Queue-Aware Logging**
> All workflow submission and worker task-pickup events SHALL include the task queue name and priority level in structured log fields.
> **Rationale:** Operators diagnosing scheduling delays need to know which queue a workflow was submitted to and what priority it received. Without this, the dual-queue topology is opaque in logs.
> **Acceptance Criteria:**
> 1. Workflow submission log entries SHALL include fields: `task_queue`, `priority`, `workflow_id`, `trigger_type` (single/batch/background).
> 2. Worker task-pickup log entries SHALL include the queue from which the task was dequeued.
> 3. Log entries SHALL use structured logging (key-value pairs), not unstructured string interpolation.

> **FR-3576: Slot Utilisation Metrics**
> The worker SHOULD expose slot utilisation metrics for each queue.
> **Rationale:** Capacity planning requires visibility into how often user vs. background slots are saturated. If user slots are consistently full while background slots are idle, the operator should adjust the ratio.
> **Acceptance Criteria:**
> 1. The worker SHOULD emit gauge metrics: `ingest_worker_user_slots_active`, `ingest_worker_background_slots_active`.
> 2. Metrics SHOULD be available via the existing metrics export mechanism (Prometheus endpoint or structured log lines).
> 3. This requirement is SHOULD-level; initial implementation MAY defer metrics to a follow-up iteration and satisfy this FR with structured log lines at DEBUG level.

---

## 4. Non-Functional Requirements

### 4.1 Performance

> **NFR-3580: Priority Scheduling Latency**
> A high-priority single-document workflow submitted to the `ingest-user` queue while medium-priority batch workflows are pending SHALL be scheduled for execution within the Temporal server's next scheduling cycle (typically < 1 second) rather than waiting behind all pending batch workflows.
> **Acceptance Criteria:**
> 1. In a test scenario with 50 pending medium-priority workflows and 1 subsequently submitted high-priority workflow, the high-priority workflow SHALL begin execution before any of the 50 pending workflows that have not yet started.

### 4.2 Reliability

> **NFR-3581: Queue Independence**
> A failure in one task queue (e.g., all background workflows failing) SHALL NOT affect the other queue's operation.
> **Acceptance Criteria:**
> 1. If all workflows in `ingest-background` fail with errors, workflows in `ingest-user` SHALL continue to be scheduled and executed normally.
> 2. Worker processes SHALL NOT crash or enter a degraded state due to failures isolated to one queue.

### 4.3 Backward Compatibility

> **NFR-3582: Zero-Downtime Migration**
> The transition from single-queue to dual-queue topology SHALL be achievable without ingestion downtime.
> **Acceptance Criteria:**
> 1. Workers running the new code with legacy single-queue configuration (FR-3553) SHALL process all existing pending workflows.
> 2. New workers with dual-queue configuration MAY be started alongside legacy workers during migration.
> 3. No workflow data or queue state SHALL be lost during the transition.

---

## 5. Data Contracts

### 5.1 Workflow Input Extensions

The following fields SHALL be added to the existing workflow input dataclasses:

```python
@dataclass
class IngestDocumentArgs:
    source: SourceArgs
    config: dict
    trigger_type: str  # "single" | "batch" | "background"
    # priority is NOT part of the workflow args --- it is set on the
    # start_workflow() call, not passed to the workflow definition.
```

```python
@dataclass
class IngestDirectoryArgs:
    sources: list
    config: dict
    trigger_type: str  # "batch" | "background"
```

### 5.2 Priority Constants

```python
# src/ingest/temporal/constants.py (or src/ingest/common/types.py)

PRIORITY_HIGH: int = 1    # Single-document, user-initiated
PRIORITY_MEDIUM: int = 2  # Batch directory, user-initiated
PRIORITY_LOW: int = 3     # Background (GC, rehash, migration)
```

### 5.3 Configuration Schema

```python
# config/settings.py additions

# --- Temporal Queue Topology ---
TEMPORAL_USER_TASK_QUEUE = os.environ.get(
    "RAG_INGEST_USER_TASK_QUEUE", "ingest-user"
)
TEMPORAL_BACKGROUND_TASK_QUEUE = os.environ.get(
    "RAG_INGEST_BACKGROUND_TASK_QUEUE", "ingest-background"
)

# --- Worker Slot Allocation ---
INGEST_USER_SLOTS = int(os.environ.get("RAG_INGEST_USER_SLOTS", "3"))
INGEST_BACKGROUND_SLOTS = int(os.environ.get("RAG_INGEST_BACKGROUND_SLOTS", "1"))

# --- Priority Values ---
INGEST_PRIORITY_HIGH = int(os.environ.get("RAG_INGEST_PRIORITY_HIGH", "1"))
INGEST_PRIORITY_MEDIUM = int(os.environ.get("RAG_INGEST_PRIORITY_MEDIUM", "2"))
INGEST_PRIORITY_LOW = int(os.environ.get("RAG_INGEST_PRIORITY_LOW", "3"))
```

---

## 6. Interaction with Companion Specifications

### 6.1 INGESTION_PLATFORM_SPEC.md

The platform spec defines cross-cutting concerns (error handling, re-ingestion, idempotency) that apply to all workflows regardless of queue or priority. The orchestration layer does not modify these behaviors --- it controls _when_ and _where_ workflows execute, not _what_ they do.

- **Idempotency:** Workflow ID = `source_key` remains unchanged. Re-submission of the same document to a different queue is safe because Temporal deduplicates by workflow ID.
- **Re-ingestion:** A re-ingestion triggered by the user routes to `ingest-user`; a re-ingestion triggered by schema migration routes to `ingest-background`.
- **Error handling:** Retry policies defined in `IngestDocumentWorkflow` are queue-agnostic and apply identically regardless of which queue the workflow runs on.

### 6.2 DOCUMENT_PROCESSING_SPEC.md / EMBEDDING_PIPELINE_SPEC.md

The Phase 1 and Phase 2 pipeline specifications define the activity logic. The orchestration layer interacts with them only at the workflow-to-activity boundary:

- Activities are registered on workers that poll both queues; the same activity implementations serve both queues.
- Activity timeouts, retry policies, and scheduling parameters remain as defined in the pipeline specs.
- No changes to activity input/output contracts are required by this specification.

### 6.3 Future: GC/Sync Specification

When the GC/sync specification (Gap 2) is authored, it SHALL reference this spec for the background queue routing contract. GC workflows MUST be submitted to `ingest-background` with priority 3.

---

## 7. Implementation Notes

> These notes are informational guidance for implementers. They are not normative requirements.

### 7.1 Temporal Worker Architecture for Slot Isolation

Temporal's Python SDK `Worker` class accepts a single `task_queue` parameter. To achieve hard slot isolation (FR-3562), the recommended approach is to run two `Worker` instances within the same process, each polling a different queue with its own `max_concurrent_activities` setting:

```python
# Pseudocode — not normative
user_worker = Worker(
    client, task_queue="ingest-user",
    max_concurrent_activities=user_slots,
    workflows=[...], activities=[...]
)
bg_worker = Worker(
    client, task_queue="ingest-background",
    max_concurrent_activities=bg_slots,
    workflows=[...], activities=[...]
)
# Run both concurrently in the same process
await asyncio.gather(user_worker.run(), bg_worker.run())
```

Both workers share the same prewarmed resources (embedding model, DB clients).

### 7.2 Temporal Priority API

As of Temporal Python SDK v1.x, workflow priority is set via the `priority` parameter on `start_workflow()` and `start_child_workflow()`. The value is a `temporalio.common.Priority` object or integer. Consult the SDK documentation for the exact API surface at implementation time.

### 7.3 Migration Path

1. Deploy new worker code with dual-queue support but legacy fallback (FR-3553).
2. Verify all existing workflows continue processing on the legacy queue.
3. Update environment variables to enable dual-queue topology.
4. Restart workers; new workers poll both queues.
5. Update submission call sites (CLI, API) to route to the correct queue.
6. Drain legacy queue; remove legacy configuration.

---

## Appendix A: FR Traceability Matrix

| FR ID | Title | Section |
|-------|-------|---------|
| FR-3550 | User Task Queue | 3.1 |
| FR-3551 | Background Task Queue | 3.1 |
| FR-3552 | Queue Routing at Submission | 3.1 |
| FR-3553 | Backward Compatibility with Legacy Queue | 3.1 |
| FR-3555 | Priority Field on Workflow Submission | 3.2 |
| FR-3556 | Priority Propagation to Child Workflows | 3.2 |
| FR-3557 | Priority on Background Workflows | 3.2 |
| FR-3560 | Multi-Queue Worker Polling | 3.3 |
| FR-3561 | Configurable Slot Ratio | 3.3 |
| FR-3562 | Slot Enforcement | 3.3 |
| FR-3565 | Implicit Priority Assignment | 3.4 |
| FR-3566 | Priority Assignment Location | 3.4 |
| FR-3567 | Priority Value Constants | 3.4 |
| FR-3570 | Queue Name Configuration | 3.5 |
| FR-3571 | Slot Allocation Configuration | 3.5 |
| FR-3572 | Priority Value Configuration | 3.5 |
| FR-3575 | Queue-Aware Logging | 3.6 |
| FR-3576 | Slot Utilisation Metrics | 3.6 |
| NFR-3580 | Priority Scheduling Latency | 4.1 |
| NFR-3581 | Queue Independence | 4.2 |
| NFR-3582 | Zero-Downtime Migration | 4.3 |
