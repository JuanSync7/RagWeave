# Ingestion Orchestration Engineering Guide

> **Document type:** Engineering guide (Layer 6 — post-implementation)
> **Implementation reference:** `INGESTION_ORCHESTRATION_IMPLEMENTATION.md` v1.0.0
> **Spec reference:** `INGESTION_ORCHESTRATION_SPEC.md` (FR-3550–FR-3576)
> **Last updated:** 2026-04-17

---

## 1. Overview

The Ingestion Orchestration layer solves a concrete starvation problem with the original single Temporal task queue (`rag-reliability`): background maintenance work (GC, schema migration, re-hashing) could block interactive single-document uploads, and no mechanism existed to express scheduling priority within the queue.

**Solution implemented:**

1. **Dual task queues** — `ingest-user` handles user-triggered ingestion; `ingest-background` handles system-initiated maintenance. Each queue is polled by its own `Worker` instance with an independent concurrency slot budget.
2. **Trigger-type routing** — every workflow submission carries a `trigger_type` string (`"single"`, `"batch"`, or `"background"`). This string determines which queue and which numeric priority is assigned at the submission call site.
3. **Priority propagation** — `IngestDirectoryWorkflow` propagates its own `trigger_type` to every child `IngestDocumentWorkflow`, so batch children inherit medium priority and background directory scans inherit low priority.

**Functional requirements covered:**

| FR | Description |
|----|-------------|
| FR-3550–FR-3552 | Dual queue topology (user queue, background queue, legacy fallback) |
| FR-3553 | Legacy single-queue fallback when dual-queue env vars are unset |
| FR-3555–FR-3557 | Priority assignment per trigger type |
| FR-3560–FR-3562 | Dual-worker architecture with hard slot isolation |
| FR-3565–FR-3567 | Trigger-type string constants and routing helpers |
| FR-3570–FR-3572 | Queue name validation, slot allocation, priority env var overrides |
| FR-3575 | Structured log emission at workflow entry |

---

## 2. Module Layout

```
src/ingest/temporal/
├── constants.py      Priority constants + trigger-type routing helpers
├── worker.py         Dual-worker entry point (run_worker, main)
├── workflows.py      IngestDocumentWorkflow, IngestDirectoryWorkflow
└── activities.py     document_processing_activity, embedding_pipeline_activity

config/
└── settings.py       RAG_INGEST_* env vars (queue names, slots, priorities)

src/ingest/common/
└── types.py          IngestionConfig (queue-adjacent config fields)

src/ingest/
└── impl.py           ingest_directory / ingest_file (upstream orchestrator)
```

### What each module exports

| Module | Key exports |
|--------|-------------|
| `constants.py` | `PRIORITY_HIGH`, `PRIORITY_MEDIUM`, `PRIORITY_LOW`, `TRIGGER_SINGLE`, `TRIGGER_BATCH`, `TRIGGER_BACKGROUND`, `QUEUE_USER`, `QUEUE_BACKGROUND`, `trigger_to_priority()`, `trigger_to_queue()` |
| `worker.py` | `run_worker()`, `main()` |
| `workflows.py` | `IngestDocumentWorkflow`, `IngestDirectoryWorkflow`, `IngestDocumentArgs`, `IngestDocumentResult`, `IngestDirectoryArgs`, `IngestDirectoryResult` |

---

## 3. Key Abstractions

### 3.1 Priority and routing constants (`constants.py`)

```python
PRIORITY_HIGH: int   # default 1 — single-document, user-initiated
PRIORITY_MEDIUM: int # default 2 — batch directory workflows
PRIORITY_LOW: int    # default 3 — background system-initiated

TRIGGER_SINGLE: str     = "single"
TRIGGER_BATCH: str      = "batch"
TRIGGER_BACKGROUND: str = "background"

QUEUE_USER: str        # resolved from RAG_INGEST_USER_TASK_QUEUE or legacy fallback
QUEUE_BACKGROUND: str  # resolved from RAG_INGEST_BACKGROUND_TASK_QUEUE or legacy fallback

def trigger_to_priority(trigger_type: str) -> int:
    """Returns numeric priority for trigger_type. Unknown triggers fall back to PRIORITY_LOW."""

def trigger_to_queue(trigger_type: str) -> str:
    """Returns queue name string for trigger_type. Unknown triggers fall back to QUEUE_BACKGROUND."""
```

The fallback contract is intentional and security-oriented: unknown callers receive the lowest scheduling priority and are never accidentally placed on the user queue.

### 3.2 Workflow argument dataclasses (`workflows.py`)

```python
@dataclass
class IngestDocumentArgs:
    source: SourceArgs
    config: dict              # IngestionConfig serialised via dataclasses.asdict()
    trigger_type: str = TRIGGER_BATCH   # backward-compat default (FR-3565)

@dataclass
class IngestDocumentResult:
    source_key: str
    errors: list
    stored_count: int
    processing_log: list

@dataclass
class IngestDirectoryArgs:
    sources: list             # list[SourceArgs | dict]
    config: dict
    trigger_type: str = TRIGGER_BATCH   # backward-compat default

@dataclass
class IngestDirectoryResult:
    processed: int
    failed: int
    stored_chunks: int
    errors: list
```

The `trigger_type` field defaults to `"batch"` in both args classes so callers that pre-date dual-queue routing continue to work without code changes — they are treated as medium-priority batch items on the user queue.

### 3.3 Worker slot resolution (`worker.py`)

```python
def _resolve_slots() -> tuple[int, int]:
    """Returns (user_slots, bg_slots).

    Precedence:
      1. RAG_INGEST_USER_SLOTS / RAG_INGEST_BACKGROUND_SLOTS (explicit)
      2. RAG_INGEST_WORKER_CONCURRENCY (legacy — 75% user / 25% background, min 1 each)
      3. Hardcoded defaults: user=3, background=1
    """

def _resolve_queues() -> tuple[bool, str, str]:
    """Returns (dual_enabled, user_queue, background_queue).
    dual_enabled is True only when both RAG_INGEST_USER_TASK_QUEUE and
    RAG_INGEST_BACKGROUND_TASK_QUEUE are non-empty.
    """
```

### 3.4 Worker startup (`worker.py`)

```python
async def run_worker() -> None:
    """Connect to Temporal, prewarm resources, and start worker(s).

    Dual-queue mode: two Worker instances in the same process, each polling
    its own queue with an independent max_concurrent_activities limit.

    Legacy mode: one Worker on TEMPORAL_TASK_QUEUE with (user_slots + bg_slots)
    total concurrency. Emits a WARNING log so operators know dual-queue is inactive.
    """

def main() -> None:
    """Entry point for the ingestion worker process."""
```

---

## 4. Queue Architecture

### 4.1 Dual-queue topology

```
Temporal Server
├── ingest-user        ← user-initiated work
│   ├── single-document uploads  (priority 1)
│   └── batch directory jobs     (priority 2)
└── ingest-background  ← system maintenance
    └── GC / rehash / migration  (priority 3)
```

In dual-queue mode, `worker.py` creates two `Worker` instances in a single process:

```python
user_worker = Worker(
    client,
    task_queue=user_queue,
    max_concurrent_activities=user_slots,   # default 3
    workflows=_WORKFLOWS,
    activities=_ACTIVITIES,
)
bg_worker = Worker(
    client,
    task_queue=bg_queue,
    max_concurrent_activities=bg_slots,     # default 1
    workflows=_WORKFLOWS,
    activities=_ACTIVITIES,
)
await asyncio.gather(user_worker.run(), bg_worker.run())
```

Hard slot isolation is structural: each `Worker` has its own `max_concurrent_activities` limit. Background tasks can never consume user-queue activity slots because they are polled by separate worker instances.

### 4.2 Slot defaults

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_INGEST_USER_SLOTS` | 3 | Max concurrent activities on the user worker |
| `RAG_INGEST_BACKGROUND_SLOTS` | 1 | Max concurrent activities on the background worker |
| `RAG_INGEST_WORKER_CONCURRENCY` | 4 | Legacy total; split 75% user / 25% background when slot-specific vars are unset |

### 4.3 Legacy fallback (single-queue mode)

When either `RAG_INGEST_USER_TASK_QUEUE` or `RAG_INGEST_BACKGROUND_TASK_QUEUE` is unset, the worker falls back to a single `Worker` on `TEMPORAL_TASK_QUEUE` (defaults to `"rag-reliability"`) with `(user_slots + bg_slots)` total activity concurrency. A `WARNING`-level log entry is emitted at startup:

```
Running in legacy single-queue mode. Set RAG_INGEST_USER_TASK_QUEUE and
RAG_INGEST_BACKGROUND_TASK_QUEUE to enable dual-queue topology.
```

---

## 5. Priority Routing

### 5.1 Trigger-type to queue and priority mapping

```
TRIGGER_SINGLE      → QUEUE_USER       / PRIORITY_HIGH   (default 1)
TRIGGER_BATCH       → QUEUE_USER       / PRIORITY_MEDIUM (default 2)
TRIGGER_BACKGROUND  → QUEUE_BACKGROUND / PRIORITY_LOW    (default 3)
```

Lower numeric values indicate higher scheduling priority. There is no user-facing mechanism to set priority directly — it is derived exclusively from `trigger_type`.

### 5.2 Priority assignment at call sites

Submission call sites (CLI, API, background scheduler) resolve the target queue and priority before submitting:

```python
from src.ingest.temporal.constants import trigger_to_queue, trigger_to_priority

task_queue = trigger_to_queue(trigger_type)
priority   = trigger_to_priority(trigger_type)

await client.start_workflow(
    IngestDocumentWorkflow.run,
    IngestDocumentArgs(source=source, config=config_dict, trigger_type=trigger_type),
    id=f"ingest-doc-{source_key}",
    task_queue=task_queue,
    priority=priority,
)
```

### 5.3 Child workflow priority propagation

`IngestDirectoryWorkflow` propagates `trigger_type` to each child workflow. Children run on the parent's inherited task queue:

```python
handle = await workflow.start_child_workflow(
    IngestDocumentWorkflow,
    IngestDocumentArgs(
        source=source,
        config=args.config,
        trigger_type=args.trigger_type,   # propagate trigger (FR-3556 AC-2)
    ),
    id=f"ingest-doc-{source.source_key}",
    task_queue=workflow.info().task_queue,  # inherit parent queue
    retry_policy=RetryPolicy(maximum_attempts=1),
)
```

Retries for individual documents are handled inside the child workflow, not the directory-level workflow.

### 5.4 Structured logging at workflow entry

Both workflow types emit a structured log entry at the start of `run()` (FR-3575):

```python
workflow.logger.info(
    "workflow entry source_key=%s trigger_type=%s queue=%s priority=%d",
    args.source.source_key,
    args.trigger_type,
    _queue,
    _priority,
)
```

The queue and priority values logged are derived from `trigger_to_queue()` / `trigger_to_priority()` applied to `args.trigger_type`. These are informational only — routing decisions were already made at the submission call site.

---

## 6. Worker Startup

### 6.1 Starting the workers

```bash
python -m src.ingest.temporal.worker
```

Or via the `main()` entry point, which configures `logging.basicConfig(level=INFO)` and calls `asyncio.run(run_worker())`.

### 6.2 Dual-queue startup sequence

`run_worker()` executes the following steps in order:

1. `_resolve_queues()` — determine if dual-queue mode is active and read queue names
2. `_resolve_slots()` — compute user and background slot counts
3. `_validate_slots(user_slots, bg_slots)` — fail fast if slots < 1 or total < 2
4. If dual mode: `_validate_queues(user_queue, bg_queue)` — fail fast on invalid names
5. `prewarm_worker_resources()` — load embedding model into memory
6. `await Client.connect(TEMPORAL_TARGET_HOST)` — connect to Temporal
7. Create `Worker` instances and `await asyncio.gather(user_worker.run(), bg_worker.run())`

### 6.3 Startup validation checks

`_validate_queues()` enforces (FR-3570 AC-3):
- Queue name must be a non-empty string
- Queue name must not exceed 200 characters
- Queue name must not contain whitespace

`_validate_slots()` enforces (FR-3561 AC-4, AC-5):
- `user_slots >= 1`
- `bg_slots >= 1`
- `user_slots + bg_slots >= 2`

Both validations raise `ValueError` with a descriptive message on failure.

### 6.4 Startup log summary

On successful dual-queue startup, the worker logs:

```
worker started mode=dual-queue user_queue=<name> user_slots=<n>
                               bg_queue=<name>   bg_slots=<n>
```

---

## 7. Configuration

All orchestration env vars are declared in `config/settings.py` (lines 543–577) and re-resolved locally in `constants.py` and `worker.py` so those modules remain self-contained.

### 7.1 Queue names

| Env var | Default | Description |
|---------|---------|-------------|
| `RAG_INGEST_USER_TASK_QUEUE` | `""` (legacy fallback) | Task queue for user-initiated ingestion. Typical prod value: `"ingest-user"` |
| `RAG_INGEST_BACKGROUND_TASK_QUEUE` | `""` (legacy fallback) | Task queue for background/batch ingestion. Typical prod value: `"ingest-background"` |
| `RAG_TEMPORAL_TASK_QUEUE` | `"rag-reliability"` | Legacy single queue name; used as fallback in both modules |
| `RAG_TEMPORAL_TARGET_HOST` | `"localhost:7233"` | Temporal server address |

Dual-queue mode activates only when **both** `RAG_INGEST_USER_TASK_QUEUE` and `RAG_INGEST_BACKGROUND_TASK_QUEUE` are non-empty.

### 7.2 Slot allocation

| Env var | Default | Description |
|---------|---------|-------------|
| `RAG_INGEST_USER_SLOTS` | `3` | Max concurrent activities for user-queue worker |
| `RAG_INGEST_BACKGROUND_SLOTS` | `1` | Max concurrent activities for background-queue worker |
| `RAG_INGEST_WORKER_CONCURRENCY` | `4` | Legacy total concurrency; split 75% / 25% when slot-specific vars are unset |

When `RAG_INGEST_USER_SLOTS` or `RAG_INGEST_BACKGROUND_SLOTS` are set alongside `RAG_INGEST_WORKER_CONCURRENCY`, the slot-specific variables take precedence and a warning is logged.

### 7.3 Priority levels

| Env var | Default | Maps to |
|---------|---------|---------|
| `RAG_INGEST_PRIORITY_HIGH` | `1` | `TRIGGER_SINGLE` (single-document uploads) |
| `RAG_INGEST_PRIORITY_MEDIUM` | `2` | `TRIGGER_BATCH` (directory fan-out) |
| `RAG_INGEST_PRIORITY_LOW` | `3` | `TRIGGER_BACKGROUND` (GC, migration, rehash) |

Lower values = higher scheduling precedence. The constraint `HIGH < MEDIUM < LOW` must hold; `validate_orchestration_config()` (documented in the implementation guide) enforces this ordering.

### 7.4 Minimal production `.env` for dual-queue mode

```bash
RAG_INGEST_USER_TASK_QUEUE=ingest-user
RAG_INGEST_BACKGROUND_TASK_QUEUE=ingest-background
RAG_INGEST_USER_SLOTS=4
RAG_INGEST_BACKGROUND_SLOTS=1
RAG_TEMPORAL_TARGET_HOST=temporal-server:7233
```

---

## 8. Troubleshooting

### Worker starts in legacy mode unexpectedly

**Symptom:** Log line `Running in legacy single-queue mode` appears at startup.

**Cause:** At least one of `RAG_INGEST_USER_TASK_QUEUE` / `RAG_INGEST_BACKGROUND_TASK_QUEUE` is empty or unset. Both must be non-empty for dual-queue mode to activate.

**Fix:** Set both variables to non-empty, whitespace-free strings.

---

### `ValueError: TEMPORAL_USER_TASK_QUEUE must be a non-empty string`

**Cause:** `_validate_queues()` ran but one queue name was empty. This only fires in dual-queue mode; if both vars are unset the worker falls back to legacy mode instead.

**Possible cause:** `RAG_INGEST_USER_TASK_QUEUE` was set to an empty string or whitespace explicitly (e.g., `RAG_INGEST_USER_TASK_QUEUE=" "`).

**Fix:** Ensure both queue name variables contain valid, non-whitespace strings or unset them both to revert to legacy mode.

---

### `ValueError: RAG_INGEST_USER_SLOTS must be >= 1`

**Cause:** `RAG_INGEST_USER_SLOTS` or `RAG_INGEST_BACKGROUND_SLOTS` was set to `0` or a negative integer.

**Fix:** Set both slot variables to integers >= 1.

---

### Background tasks running on user queue (or vice versa)

**Symptom:** Structured logs show `queue=ingest-user` for a `trigger_type=background` workflow, or the reverse.

**Cause:** The submission call site is not using `trigger_to_queue()` to resolve the target queue, or is hardcoding the queue name.

**Fix:** Ensure all submission call sites call `trigger_to_queue(trigger_type)` and `trigger_to_priority(trigger_type)` from `src.ingest.temporal.constants` to resolve the queue and priority.

---

### `RAG_INGEST_WORKER_CONCURRENCY` ignored at startup

**Symptom:** Log warning `RAG_INGEST_WORKER_CONCURRENCY is set alongside slot-specific variables; ignoring legacy concurrency value.`

**Cause:** Both `RAG_INGEST_WORKER_CONCURRENCY` and one or both of the slot-specific variables (`RAG_INGEST_USER_SLOTS`, `RAG_INGEST_BACKGROUND_SLOTS`) are set. The slot-specific variables take precedence.

**Fix:** Remove `RAG_INGEST_WORKER_CONCURRENCY` from the environment once you have set the explicit slot variables.

---

### Child workflows on wrong queue after directory fan-out

**Symptom:** Child `IngestDocumentWorkflow` runs on a different queue than the parent `IngestDirectoryWorkflow`.

**Cause:** `IngestDirectoryWorkflow` uses `task_queue=workflow.info().task_queue` so children inherit the parent's queue. If the parent was submitted to the wrong queue, children follow.

**Fix:** Verify that `IngestDirectoryWorkflow` is submitted to the correct queue at the call site using `trigger_to_queue(trigger_type)`.

---

### Embedding model reload on every worker replica

**Symptom:** Worker startup is slow; embedding model is loaded once per replica but not shared across workers in the same process.

**Expected behaviour:** `prewarm_worker_resources()` is called once before both `Worker` instances are created. Both workers share the prewarmed resources. Each new process replica loads independently — this is by design.

---

### Workflow `trigger_type` logs `queue=ingest-background` but priority shows `1`

**Symptom:** Inconsistent queue/priority in structured logs.

**Cause:** The log inside the workflow body is derived from the `trigger_type` field of `args` using `trigger_to_queue()` / `trigger_to_priority()`. It reflects what the call site *should* have done, not what it *actually* did. Queue routing is determined at submission time by the Temporal client, not inside the workflow.

**Fix:** Cross-reference the Temporal UI to confirm the actual task queue the workflow ran on. If the log and the actual queue differ, the submission call site passed a mismatched `trigger_type`.
