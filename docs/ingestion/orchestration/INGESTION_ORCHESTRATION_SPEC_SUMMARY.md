# Ingestion Orchestration — Specification Summary

> **Document type:** Specification summary (Layer 2)
> **Upstream:** INGESTION_ORCHESTRATION_SPEC.md
> **Last updated:** 2026-04-15

---

## 1) System Overview

### Purpose

When an ingestion pipeline routes all workflows through a single task queue, three scheduling failure modes compound. Background maintenance work — garbage collection syncs, schema migrations, bulk re-hashing — fills the queue and blocks user-initiated ingestion. Within user-initiated work, a large batch submission forces a single urgent document to wait behind hundreds of batch items. And the scheduling system provides no mechanism to express that one workflow matters more than another. The orchestration layer resolves all three failure modes through a dual-mechanism approach that separates workloads by type and orders them by urgency within each type.

### Pipeline Flow

The orchestration layer sits above the two-phase ingestion pipeline (document processing followed by embedding), controlling when and where workflows execute without modifying what they do. Two named task queues replace the single legacy queue. All user-initiated workflows — single-document submissions and batch directory ingestions — are routed to a dedicated user queue. All system-initiated workflows — garbage collection, re-hashing, schema migrations, scheduled re-ingestion — are routed to a separate background queue. Each worker process polls both queues simultaneously, but with dedicated capacity slots for each: a configurable number of concurrent execution slots are reserved for user-facing work and a separate allocation for background work. This reservation ensures background work can never fully consume a worker's capacity.

Within the user queue, a per-workflow priority mechanism prevents batch submissions from starving single-document requests. Single-document ingestion receives the highest priority; batch child workflows receive medium priority. When a user submits a 500-document batch and then submits one more document, the single document is scheduled ahead of the remaining batch items even though they were enqueued first. Background workflows receive low priority for consistency, though they run on a separate queue.

Priority is always implicit — determined by the ingestion trigger type, not by user selection. The mapping is deterministic: a user submitting a single document wants to query it immediately, so it is urgent. A batch is important but tolerates ordering delays. Background work is non-urgent by definition. No user-facing control for priority exists because it would add complexity with no clear benefit.

### Tunable Knobs

Operators can configure both queue names for namespace isolation across environments, the number of concurrent execution slots allocated to each queue per worker, and the numeric priority values for each tier. All settings are available as environment variables with sensible defaults. A legacy single-queue fallback mode preserves backward compatibility during migration.

### Design Rationale

Two principles govern the design. Workload isolation through queue separation is the coarsest and most reliable scheduling boundary, ensuring interactive work is never blocked by a background backlog. Fine-grained ordering through per-workflow priority within the user queue solves the batch-starvation problem without requiring separate queues for every ingestion trigger type.

### Boundary Semantics

The orchestration layer's entry point is a workflow submission request arriving at the scheduling client — from a command-line interface, an API endpoint, or a background scheduler. Its exit point is a workflow dispatched to the correct task queue with the correct priority, picked up by a worker with available capacity, and executed through the existing two-phase pipeline. The layer controls scheduling and capacity allocation; it does not modify pipeline phase logic, activity timeouts, retry policies, or data contracts.

---

## 2) Scope and Boundaries

**Entry point:** Workflow submission request (CLI, API, or scheduler) arriving at the Temporal client.

**Exit point:** Workflow dispatched to correct task queue with correct priority, executed by a worker.

**In scope:** Temporal task queue topology, per-workflow priority assignment, worker slot allocation, priority assignment rules, queue name and slot configuration, backward compatibility with legacy single-queue mode.

**Out of scope:** Phase 1/Phase 2 pipeline logic, Temporal cluster operations, API-layer rate limiting, dynamic priority adjustment, user-facing priority selection, multi-tenant isolation, workflow preemption.

---

## 3) Dual Task Queue Topology (FR-3550–FR-3553)

Two named Temporal task queues replace the legacy single queue. The `ingest-user` queue (FR-3550) receives all user-initiated workflows — single-document and batch directory ingestion, including child workflows spawned by directory fan-out. The `ingest-background` queue (FR-3551) receives all system-initiated maintenance workflows (GC sync, rehash, schema migration, scheduled re-ingestion). Queue routing is determined at submission time by the caller, based on ingestion trigger type (FR-3552). Both queue names are configurable via environment variables.

Backward compatibility (FR-3553) is preserved: when neither new queue variable is set, the system falls back to the existing single-queue configuration, with a log warning advising migration. This enables zero-downtime transition from single-queue to dual-queue topology.

---

## 4) Intra-Queue Priority (FR-3555–FR-3557)

Every `IngestDocumentWorkflow` carries a priority value set at submission time (FR-3555). Priority is an integer (1=highest, 5=lowest) used by the scheduling system to order pending tasks within a queue. The `IngestDirectoryWorkflow` propagates medium priority to each child workflow (FR-3556), sourced from input args rather than hardcoded. Background workflows use low priority (FR-3557) for consistency.

Key decision: priority affects queue ordering only, not preemption. In-flight workflows are not interrupted by higher-priority submissions.

---

## 5) Worker Slot Allocation (FR-3560–FR-3562)

Each worker polls both queues simultaneously (FR-3560), maximising resource utilisation. Slot allocation between queues is configurable (FR-3561): default 3 user slots and 1 background slot, validated at startup (minimum 1 each, total minimum 2). Slot limits are hard reservations (FR-3562) — background work cannot overflow into user slots and vice versa, even when one queue's slots are idle. The recommended implementation uses two worker instances within the same process, each polling one queue with its own concurrency limit.

Key decision: capacity is reserved, not borrowed. This prevents a burst of background work from consuming all worker capacity and blocking user requests.

---

## 6) Priority Assignment Rules (FR-3565–FR-3567)

Priority is implicit and deterministic (FR-3565): single-document = priority 1 (high), batch children = priority 2 (medium), background = priority 3 (low). No CLI flag, API parameter, or UI control exists for setting priority. Assignment occurs at the workflow submission call site, not within the workflow definition (FR-3566) — workflows are agnostic to their own priority. Named constants (`PRIORITY_HIGH`, `PRIORITY_MEDIUM`, `PRIORITY_LOW`) are defined in a shared module (FR-3567) to eliminate magic numbers.

---

## 7) Configuration (FR-3570–FR-3572)

Queue names are configurable via `RAG_INGEST_USER_TASK_QUEUE` and `RAG_INGEST_BACKGROUND_TASK_QUEUE` with defaults `ingest-user` and `ingest-background` (FR-3570). Slot counts are configurable via `RAG_INGEST_USER_SLOTS` (default 3) and `RAG_INGEST_BACKGROUND_SLOTS` (default 1), with a legacy `RAG_INGEST_WORKER_CONCURRENCY` fallback that splits 75/25 (FR-3571). Priority numeric values are configurable with strict ordering validation (high < medium < low) (FR-3572).

---

## 8) Observability (FR-3575–FR-3576)

All workflow submission and task-pickup events include task queue, priority, workflow ID, and trigger type in structured log fields (FR-3575). Slot utilisation gauge metrics for each queue (FR-3576) are recommended but may be deferred to a follow-up iteration — initial implementation may use structured log lines at DEBUG level.

---

## 9) Non-Functional Requirements (NFR-3580–NFR-3582)

- **Priority scheduling latency (NFR-3580):** A high-priority workflow submitted while 50 medium-priority workflows are pending begins execution before any of the 50 that have not yet started.
- **Queue independence (NFR-3581):** Failures in one queue do not affect the other queue's operation. Workers do not crash due to failures isolated to one queue.
- **Zero-downtime migration (NFR-3582):** Transition from single-queue to dual-queue is achievable without ingestion downtime. New workers with dual-queue config can run alongside legacy workers.

---

## 10) Key Design Decisions

- **Dual-queue over single-queue with priorities alone:** Queue-level isolation is the coarsest and most reliable boundary. Priority ordering within a single queue cannot prevent background work from consuming all worker capacity.
- **Hard slot reservation, not borrowing:** Background slots remain reserved even when idle. This guarantees user-facing capacity is always available at the cost of slightly lower background throughput during low-load periods.
- **Implicit priority, no user-facing control:** Priority is an infrastructure concern. The mapping from trigger type to priority is deterministic and requires no user decision-making.
- **Priority at call site, not in workflow:** The workflow definition processes a document regardless of scheduling context. The caller (CLI, API, scheduler, parent workflow) knows the trigger context.
- **Legacy single-queue fallback:** Existing deployments continue functioning with the legacy queue until operators explicitly migrate. A log warning prompts migration without forcing it.
- **Two Temporal Workers in one process:** Hard slot isolation is achieved by running separate worker instances per queue, sharing prewarmed resources (embedding model, DB clients).

---

## 11) Requirement Summary

The spec covers **18 functional requirements** and **3 non-functional requirements**:

| ID Range | Domain | Count |
|----------|--------|-------|
| FR-3550–FR-3553 | Dual Task Queue Topology | 4 |
| FR-3555–FR-3557 | Intra-Queue Priority | 3 |
| FR-3560–FR-3562 | Worker Slot Allocation | 3 |
| FR-3565–FR-3567 | Priority Assignment Rules | 3 |
| FR-3570–FR-3572 | Configuration | 3 |
| FR-3575–FR-3576 | Observability | 2 |
| NFR-3580–NFR-3582 | Non-Functional Requirements | 3 |

Priority breakdown: 16 MUST (SHALL), 3 SHOULD.

---

## 12) Companion Documents

| Document | Purpose |
|----------|---------|
| INGESTION_ORCHESTRATION_SPEC.md | Authoritative requirements specification — source of truth |
| INGESTION_ORCHESTRATION_SPEC_SUMMARY.md (this document) | Stakeholder-ready digest |
| DOCUMENT_PROCESSING_SPEC.md | Phase 1 pipeline requirements |
| EMBEDDING_PIPELINE_SPEC.md | Phase 2 pipeline requirements |
| INGESTION_PLATFORM_SPEC.md | Cross-cutting platform requirements (error handling, idempotency, retry policies) |

---

## 13) Sync Status

- **Spec version aligned to:** INGESTION_ORCHESTRATION_SPEC.md v1.0.0
- **Last synced:** 2026-04-15
- **Sync method:** Manual review
