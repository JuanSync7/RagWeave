# Ingestion Orchestration Test Documentation

> **Document type:** Test documentation (Layer 6 — post-implementation)
> **Engineering guide:** `INGESTION_ORCHESTRATION_ENGINEERING_GUIDE.md`
> **Implementation reference:** `INGESTION_ORCHESTRATION_IMPLEMENTATION.md` v1.0.0
> **Last updated:** 2026-04-17

---

## 1. Test Strategy

The orchestration layer introduces two distinct concerns that require different testing approaches:

**Concern 1 — Pure logic (no Temporal dependency)**
`constants.py` contains deterministic routing helpers (`trigger_to_priority`, `trigger_to_queue`) and lookup tables. These are testable with plain `pytest` without any Temporal infrastructure.

**Concern 2 — Worker and workflow behavior (Temporal-coupled)**
`worker.py` and `workflows.py` integrate with the Temporal Python SDK. Testing these fully requires either a running Temporal server or the `temporalio` test environment. As of the current implementation, no dedicated Temporal unit tests exist in the test suite. The rationale and planned coverage are documented in Section 3 below.

**Concern 3 — Orchestrator integration (`impl.py`)**
`ingest_directory` and `ingest_file` in `src/ingest/impl.py` are the call sites where trigger types, queues, and priorities originate. These functions are tested in `tests/ingest/test_orchestrator.py` and `tests/ingest/test_two_phase_orchestrator.py` with unit-level mocking of `run_document_processing` and `run_embedding_pipeline`.

**Testing philosophy:**
- The Temporal layer is thin orchestration. Business logic (document processing, embedding) lives in activities, which are tested through the phase-level tests in `tests/ingest/`.
- Workflow behavior (fan-out, error aggregation, trigger propagation) is verified through integration testing with `temporalio`'s test environment when that infrastructure is available.
- `constants.py` routing helpers are fully unit-testable and should be covered first.

---

## 2. Test File Map

### 2.1 Existing test files relevant to orchestration

No dedicated test files exist under `tests/ingest/temporal/`. The directory does not exist as of this writing.

The following existing test files exercise the orchestrator layer (`src/ingest/impl.py`) which is the upstream call site for Temporal workflow submission:

| File | What it covers |
|------|---------------|
| `tests/ingest/test_orchestrator.py` | `ingest_directory` (new files, skip-unchanged, remove-deleted, partial failure, invalid config guard, empty dir); `ingest_file` result fields (log merging, metadata, empty errors); `verify_core_design` |
| `tests/ingest/test_two_phase_orchestrator.py` | `ingest_file` two-phase contract: `source_hash` returned, `clean_store` written, phase-1-error short-circuit |
| `tests/ingest/test_verify_core_design.py` | `verify_core_design` contradiction detection (chunk overlap, KG dependencies, docling config, VLM config) |
| `tests/ingest/conftest.py` | Shared `pytest` fixtures for the `tests/ingest/` package |

### 2.2 Missing test files (gap analysis)

The following test files do not yet exist. They represent the planned coverage for the orchestration subsystem:

| Planned file | What it should cover |
|--------------|---------------------|
| `tests/ingest/temporal/test_constants.py` | `trigger_to_priority`, `trigger_to_queue`, `QUEUE_USER`/`QUEUE_BACKGROUND` resolution, unknown trigger fallback |
| `tests/ingest/temporal/test_worker_slots.py` | `_resolve_slots` precedence (explicit > legacy > default), `_validate_slots` boundary conditions |
| `tests/ingest/temporal/test_worker_queues.py` | `_resolve_queues` dual-enable logic, `_validate_queues` rejection cases (empty, whitespace, >200 chars) |
| `tests/ingest/temporal/test_workflows.py` | `IngestDirectoryWorkflow` trigger propagation to children, error aggregation, happy-path fan-out (Temporal test env required) |

---

## 3. Coverage by FR

### FR-3553 — Legacy single-queue fallback

**Current coverage:** Indirect. `tests/ingest/test_orchestrator.py` exercises `ingest_directory` without Temporal infrastructure — the queue selection logic is not reachable from that level. Worker-level fallback logic in `_resolve_queues()` is untested by automated tests.

**Gap:** No test verifies that when `RAG_INGEST_USER_TASK_QUEUE` is unset the worker falls back to `TEMPORAL_TASK_QUEUE`.

**Planned:** `tests/ingest/temporal/test_worker_queues.py::test_legacy_fallback_when_both_unset`

---

### FR-3555–FR-3557 — Priority assignment per trigger type

**Current coverage:** None. The `trigger_to_priority` and `trigger_to_queue` functions have no automated test coverage.

**Gap:** Full gap.

**Planned:** `tests/ingest/temporal/test_constants.py` covering all three trigger values, the unknown-trigger fallback, and the `QUEUE_USER` / `QUEUE_BACKGROUND` default resolution from env vars.

---

### FR-3560–FR-3562 — Dual-worker architecture with slot isolation

**Current coverage:** None. Worker construction is not tested.

**Gap:** No test verifies that dual-queue mode spawns two `Worker` instances or that slot values are passed correctly to each worker.

**Planned:** `tests/ingest/temporal/test_worker_slots.py` using `unittest.mock.patch` on `temporalio.worker.Worker` and `temporalio.client.Client.connect`.

---

### FR-3565–FR-3566 — `trigger_type` in workflow args and backward compatibility

**Current coverage:** None. The `IngestDocumentArgs` and `IngestDirectoryArgs` dataclasses and their `trigger_type` defaults are not directly tested.

**Gap:** No test verifies that omitting `trigger_type` produces `"batch"` (backward-compat default) rather than raising.

**Planned:** `tests/ingest/temporal/test_workflows.py` — instantiation tests for args defaults without Temporal server dependency.

---

### FR-3556 AC-2 — Child workflows inherit parent `trigger_type`

**Current coverage:** None.

**Gap:** No test verifies that `IngestDirectoryWorkflow` passes its own `trigger_type` to each child `IngestDocumentWorkflow`.

**Planned:** `tests/ingest/temporal/test_workflows.py` — mock `workflow.start_child_workflow` and assert `trigger_type` propagation.

---

### FR-3570 — Queue name validation

**Current coverage:** None at the unit level. `_validate_queues()` has no automated test.

**Planned:** `tests/ingest/temporal/test_worker_queues.py` covering empty string, whitespace-only string, 201-character name, and valid name cases.

---

### FR-3571 — Slot allocation precedence

**Current coverage:** None.

**Planned:** `tests/ingest/temporal/test_worker_slots.py` with env-var monkeypatching for all three precedence levels (explicit slots > legacy total > hardcoded defaults).

---

### FR-3572 — Priority env var overrides

**Current coverage:** None. Priority constants read from env vars at import time; no test exercises this path.

**Gap:** No test verifies that setting `RAG_INGEST_PRIORITY_HIGH=5` is reflected in `PRIORITY_HIGH`.

**Planned:** `tests/ingest/temporal/test_constants.py` — importlib reload with monkeypatched env vars.

---

### FR-3575 — Structured log emission at workflow entry

**Current coverage:** None.

**Planned:** `tests/ingest/temporal/test_workflows.py` — assert that `workflow.logger.info` is called with expected `trigger_type`, `queue`, and `priority` fields using Temporal's test environment `mock_workflow_logger`.

---

### Orchestrator-level coverage (impl.py)

The following FR areas are covered by existing tests through `ingest_directory` and `ingest_file`:

| FR area | Covered by |
|---------|------------|
| Two-phase pipeline contract | `test_two_phase_orchestrator.py` |
| Idempotency / skip-unchanged | `test_orchestrator.py::TestIngestDirectorySkipUnchanged` |
| Partial failure handling | `test_orchestrator.py::TestIngestDirectoryPartialFailure` |
| Config validation guard | `test_orchestrator.py::TestIngestDirectoryInvalidConfig` |
| Removed source cleanup | `test_orchestrator.py::TestIngestDirectoryRemoveDeleted` |
| `verify_core_design` contracts | `test_verify_core_design.py`, `test_orchestrator.py::TestVerifyCoreDesign` |

---

## 4. Fixture Reference

### 4.1 Existing fixtures (`tests/ingest/test_orchestrator.py`)

These helpers are defined inline in the test module (not in `conftest.py`):

```python
def _make_runtime(tmp_path, **config_overrides) -> Runtime:
    """Build a minimal Runtime with all optional stages disabled."""

def _make_config(tmp_path, **overrides) -> IngestionConfig:
    """Build a minimal IngestionConfig with all optional stages disabled."""

def _mock_ingest_result(stored=3, errors=None, summary="Test summary",
                        keywords=None) -> IngestFileResult:
    """Return an IngestFileResult for use as mock return value."""

def _make_mock_ctx() -> MagicMock:
    """Return a MagicMock context manager for patching get_client."""

def _phase1_result(doc: Path, cleaned="clean text") -> dict:
    """Return a fake DocumentProcessingState dict for a file path."""

def _phase2_result(**overrides) -> dict:
    """Return a fake EmbeddingState dict with optional field overrides."""
```

### 4.2 Recommended fixtures for future temporal tests

When `tests/ingest/temporal/` is created, the following fixture patterns are recommended:

```python
import pytest
import os
import importlib

@pytest.fixture(autouse=True)
def clear_queue_env(monkeypatch):
    """Remove dual-queue env vars before each test to prevent cross-test pollution.
    constants.py resolves queue names at import time, so tests that need specific
    values should monkeypatch and reload the module.
    """
    monkeypatch.delenv("RAG_INGEST_USER_TASK_QUEUE", raising=False)
    monkeypatch.delenv("RAG_INGEST_BACKGROUND_TASK_QUEUE", raising=False)
    yield

@pytest.fixture
def dual_queue_env(monkeypatch):
    """Set both queue env vars to enable dual-queue mode."""
    monkeypatch.setenv("RAG_INGEST_USER_TASK_QUEUE", "ingest-user")
    monkeypatch.setenv("RAG_INGEST_BACKGROUND_TASK_QUEUE", "ingest-background")
    yield "ingest-user", "ingest-background"
```

Note: because `constants.py` resolves `QUEUE_USER` and `QUEUE_BACKGROUND` at import time (module-level `os.environ.get`), tests that exercise these values need to either reload the module or test `trigger_to_queue()` / `trigger_to_priority()` directly (which read from the module-level constants).

---

## 5. Running Tests

### 5.1 Run all orchestration-adjacent tests

```bash
pytest tests/ingest/test_orchestrator.py tests/ingest/test_two_phase_orchestrator.py \
       tests/ingest/test_verify_core_design.py -v
```

### 5.2 Run the full ingest test suite

```bash
pytest tests/ingest/ -v
```

### 5.3 Run with coverage for impl.py

```bash
pytest tests/ingest/test_orchestrator.py tests/ingest/test_two_phase_orchestrator.py \
       --cov=src.ingest.impl --cov-report=term-missing
```

### 5.4 Running future temporal tests (once created)

```bash
pytest tests/ingest/temporal/ -v
```

For workflow tests that require the Temporal test environment, ensure `temporalio` is installed and use the SDK's `WorkflowEnvironment`:

```python
from temporalio.testing import WorkflowEnvironment

@pytest.mark.asyncio
async def test_directory_workflow_propagates_trigger_type():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        ...
```

### 5.5 Markers

No custom pytest markers are defined for orchestration tests. The standard markers apply:

```bash
pytest tests/ingest/ -m "not slow"    # skip slow/integration tests if marked
pytest tests/ingest/ -k "orchestrator" # run only orchestrator-related tests
```
