# Swappable Observability Subsystem — Design Document

| Field | Value |
|---|---|
| **Document** | Observability Subsystem Design Document |
| **Version** | 0.1 |
| **Status** | Draft |
| **Spec Reference** | `docs/observability/OBSERVABILITY_SPEC.md` (REQ-101 through REQ-941) |
| **Output Path** | `docs/observability/OBSERVABILITY_DESIGN.md` |
| **Produced by** | write-design-docs |
| **Task Decomposition Status** | [x] Approved |

> **Document Intent.** This document provides the technical design with task decomposition
> and contract-grade code appendix for the Observability Subsystem specified in
> `docs/observability/OBSERVABILITY_SPEC.md`. Every task references the requirements
> it satisfies. Part B contract entries are consumed verbatim by the companion
> implementation docs.

---

# Part A: Task-Oriented Overview

## Phase 1 — Foundation: ABC Contracts and Schema Types

### Task 1.1: Backend ABC and Schema Types

**Description:** Create the two new files that form the contract layer of the observability subsystem: `backend.py` (all ABCs: `ObservabilityBackend`, `Span`, `Trace`, `Generation`) and `schemas.py` (all record dataclasses: `SpanRecord`, `TraceRecord`, `GenerationRecord`). This replaces the existing `contracts.py` which has only the minimal `Tracer`/`Span` pair. Both files must have zero third-party dependencies so they are importable in any environment.

**Requirements Covered:** REQ-101, REQ-103, REQ-105, REQ-107, REQ-109, REQ-111, REQ-113, REQ-115, REQ-117, REQ-119, REQ-121, REQ-123, REQ-125, REQ-127, REQ-129, REQ-131, REQ-133, REQ-135, REQ-137, REQ-139, REQ-141, REQ-143, REQ-145, REQ-147, REQ-149, REQ-151, REQ-153, REQ-155, REQ-157

**Dependencies:** None

**Complexity:** M

**Subtasks:**
1. Create `src/platform/observability/backend.py` — define `Span`, `Trace`, `Generation`, and `ObservabilityBackend` ABCs with all abstract methods, context-manager protocol (`__enter__`/`__exit__`), and complete docstrings.
2. Create `src/platform/observability/schemas.py` — define `SpanRecord`, `TraceRecord`, and `GenerationRecord` as `@dataclass` classes with all typed fields; timestamps default to `time.time()`.
3. Delete `src/platform/observability/contracts.py` (replaced by `backend.py`).
4. Update `src/platform/schemas/observability.py` to re-export from the new canonical location for backward compatibility (any existing import of `SpanRecord` or `Attributes` from the old path must still work).
5. Write `@summary` block and module docstring for both new files.

**Risks:** Removing `contracts.py` while consumers still import from it. Mitigation: the `providers.py` compat shim (Task 3.1) and `__init__.py` re-exports keep the public surface stable; internal callers (noop, langfuse) will be written fresh and never import `contracts.py`.

**Testing Strategy:** Unit tests verify each ABC raises `TypeError` on incomplete subclasses, context manager protocol returns `self` on `__enter__` and `False` on `__exit__`, and all record dataclasses construct without error with required fields.

---

### Task 1.2: NoopBackend Package

**Description:** Create the `src/platform/observability/noop/` subdirectory with `NoopBackend`, `NoopSpan`, `NoopTrace`, and `NoopGeneration` — all methods are zero-cost no-ops that return the correct typed objects and never raise under any input. This replaces the existing `noop_tracer.py`.

**Requirements Covered:** REQ-159, REQ-161, REQ-163, REQ-165

**Dependencies:** Task 1.1

**Complexity:** S

**Subtasks:**
1. Create directory `src/platform/observability/noop/` with `__init__.py` exporting `NoopBackend`.
2. Create `src/platform/observability/noop/backend.py` implementing `NoopSpan` (subclass of `Span`), `NoopTrace` (subclass of `Trace`), `NoopGeneration` (subclass of `Generation`), and `NoopBackend` (subclass of `ObservabilityBackend`).
3. Ensure all methods on `NoopSpan`, `NoopTrace`, `NoopGeneration` accept any input without raising (including `None`, negative ints, empty strings).
4. Ensure `NoopBackend.flush()` and `NoopBackend.shutdown()` return `None` without I/O.
5. Write `@summary` block and module docstring.

---

## Phase 2 — Langfuse Backend

### Task 2.1: LangfuseBackend Package

**Description:** Create the `src/platform/observability/langfuse/` subdirectory containing all Langfuse-specific code — `LangfuseBackend`, `LangfuseSpan`, `LangfuseTrace`, and `LangfuseGeneration`. All Langfuse SDK imports (`from langfuse import ...`) are confined exclusively to `langfuse/backend.py`. This replaces the existing `langfuse_tracer.py` and extends it with `Trace` and `Generation` concepts.

**Requirements Covered:** REQ-201, REQ-203, REQ-205, REQ-207, REQ-209, REQ-211, REQ-213, REQ-215, REQ-217, REQ-219, REQ-221, REQ-223, REQ-225, REQ-227, REQ-229, REQ-231, REQ-233, REQ-235, REQ-237, REQ-239, REQ-241, REQ-243, REQ-245, REQ-247, REQ-249, REQ-251

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**
1. Create directory `src/platform/observability/langfuse/` with `__init__.py` exporting only `LangfuseBackend`.
2. Create `src/platform/observability/langfuse/backend.py` and implement `LangfuseSpan` (wraps Langfuse SDK observation, fail-open `set_attribute` and `end`).
3. Implement `LangfuseTrace` (wraps Langfuse SDK trace, creates child spans/generations via `trace_obj.span()`/`trace_obj.generation()`).
4. Implement `LangfuseGeneration` (wraps Langfuse SDK generation observation, adds `set_output` and `set_token_counts`).
5. Implement `LangfuseBackend` (calls `get_client()` in `__init__` and propagates exceptions; no credential parameters).
6. Implement `LangfuseBackend.flush()` and `LangfuseBackend.shutdown()` to propagate SDK exceptions.
7. Write `@summary` block and module docstring.

**Risks:** Langfuse SDK v3 API surface (`get_client()`, `start_observation`, `client.trace()`) may differ from v2 if mixed. Mitigation: read the installed SDK version at test time; the existing `langfuse_tracer.py` uses `get_client()` confirming v3 is already in use.

**Testing Strategy:** Mock the Langfuse SDK client to verify SDK method calls and argument forwarding. Test fail-open: inject exceptions into `inner.update`/`inner.end` and verify no propagation. Test `flush()` and `shutdown()` exception propagation.

---

## Phase 3 — Public API

### Task 3.1: Public API Facade, Singleton Factory, and @observe Decorator

**Description:** Rewrite `src/platform/observability/__init__.py` as the stable public API: exports `get_tracer`, `observe`, `Tracer` (alias), `Span`, `Trace`, `Generation`; owns the thread-safe backend singleton; implements `get_tracer()` with fail-open backend init; implements the `@observe` decorator with `functools.wraps`, configurable input/output capture, and automatic span lifecycle. Update `providers.py` to become a backward-compat shim emitting `DeprecationWarning`.

**Requirements Covered:** REQ-167, REQ-169, REQ-171, REQ-301, REQ-303, REQ-305, REQ-307, REQ-309, REQ-311, REQ-313, REQ-315, REQ-317, REQ-319, REQ-321, REQ-323, REQ-325, REQ-327, REQ-329, REQ-331, REQ-333, REQ-335, REQ-337, REQ-339, REQ-341

**Dependencies:** Task 1.1, Task 1.2, Task 2.1

**Complexity:** M

**Subtasks:**
1. Implement thread-safe singleton in `__init__.py` using a module-level lock and `_backend: ObservabilityBackend | None` variable.
2. Implement `_init_backend()` private function: reads `OBSERVABILITY_PROVIDER`, tries to instantiate configured backend, falls back to `NoopBackend` on any exception and logs a warning.
3. Implement `get_tracer() -> ObservabilityBackend` as the public accessor returning the singleton.
4. Implement `observe(name, capture_input, capture_output)` decorator factory using `functools.wraps`; all defaults `False`; truncate captured values to 500 chars.
5. Define `__all__` and re-export `Span`, `Trace`, `Generation` from `backend.py`; export `Tracer` as `ObservabilityBackend` alias with `DeprecationWarning` on access.
6. Update `providers.py` to re-export `get_tracer` from `__init__` with a `DeprecationWarning` import-time warning (using `warnings.warn`).
7. Delete `src/platform/observability/langfuse_tracer.py` and `src/platform/observability/noop_tracer.py` (replaced by subdirectory packages).

**Risks:** Thread safety of singleton initialization. Mitigation: use `threading.Lock` with double-checked locking (see B.5 Pattern).

---

## Phase 4 — Consumer Migration

### Task 4.1: Migrate Retrieval Consumers

**Description:** Update all 5 retrieval files that currently import from `src.platform.observability.providers` to use the new public API. Replace all `start_span()`/try-finally patterns with either `@observe` decorators (for simple full-function tracing) or `with get_tracer().span()` context managers (where dynamic attributes are set mid-function). Remove all `_tracer_instance` module-level globals.

**Requirements Covered:** REQ-401, REQ-403, REQ-405, REQ-407, REQ-409, REQ-411, REQ-413, REQ-415, REQ-417, REQ-421, REQ-423, REQ-427, REQ-429, REQ-431, REQ-435, REQ-437, REQ-439, REQ-441

**Dependencies:** Task 3.1

**Complexity:** M

**Subtasks:**
1. Migrate `src/retrieval/query/nodes/reranker.py`: change import to `from src.platform.observability import get_tracer`; replace `self.tracer.start_span(...)`/try-finally with `with get_tracer().span("reranker.rerank", {...}) as span:`.
2. Migrate `src/retrieval/generation/nodes/generator.py`: replace old pattern; use context manager with dynamic attribute population from generation results.
3. Migrate `src/retrieval/query/nodes/query_processor.py`: remove module-level `_tracer_instance`; replace with `get_tracer()` call at use site.
4. Migrate `src/retrieval/pipeline/rag_chain.py`: replace import; use `with get_tracer().trace("rag.request") as trace:` at the pipeline entry point to group child spans.
5. Migrate `src/retrieval/generation/nodes/output_sanitizer.py`: replace import and span pattern.

**Testing Strategy:** Run existing retrieval tests. Verify no `AttributeError: 'NoopTracer' has no attribute 'start_span'` (or equivalent) after migration.

---

### Task 4.2: Migrate Ingest Consumers

**Description:** Update the 3 ingest files that use the old observability pattern to use the new public API. Same migration pattern as Task 4.1.

**Requirements Covered:** REQ-401, REQ-403, REQ-405, REQ-429, REQ-431, REQ-435, REQ-437, REQ-439

**Dependencies:** Task 3.1

**Complexity:** S

**Subtasks:**
1. Migrate `src/ingest/support/docling.py`: change import to `from src.platform.observability import get_tracer`; update span creation pattern.
2. Migrate `src/ingest/doc_processing/nodes/multimodal_processing.py`: replace import and span pattern.
3. Migrate `src/ingest/common/shared.py`: replace import and any span creation patterns.

---

## Phase 5 — Infrastructure

### Task 5.1: Docker Compose Langfuse Services and .env.example

**Description:** Add two new services to `docker-compose.yml` — `langfuse-db` (PostgreSQL 16) and `langfuse` (langfuse/langfuse:3) — both under the `observability` profile. Add health checks, named volume, and `depends_on` with `service_healthy` condition. Update `.env.example` with all required Langfuse environment variable placeholders.

**Requirements Covered:** REQ-501, REQ-503, REQ-505, REQ-507, REQ-509, REQ-511, REQ-513, REQ-515, REQ-517, REQ-519, REQ-521, REQ-523, REQ-525, REQ-527, REQ-529, REQ-531, REQ-533, REQ-535, REQ-537, REQ-539, REQ-541

**Dependencies:** None (independent of Python code changes)

**Complexity:** S

**Subtasks:**
1. Add `langfuse-db` service to `docker-compose.yml` with `postgres:16-alpine`, container name `rag-langfuse-db`, `POSTGRES_USER/PASSWORD/DB=langfuse`, health check `pg_isready -U langfuse` with `interval: 10s / timeout: 5s / retries: 5 / start_period: 10s`, volume `langfuse-db-data`, profile `observability`.
2. Add `langfuse` service with `langfuse/langfuse:3`, port `${LANGFUSE_PORT:-3000}:3000`, all required env vars, `depends_on: langfuse-db: condition: service_healthy`, health check `curl -f http://localhost:3000/api/public/health`, profile `observability`.
3. Add `langfuse-db-data` to the top-level `volumes:` block.
4. Update `.env.example` with `LANGFUSE_PORT`, `LANGFUSE_NEXTAUTH_SECRET`, `LANGFUSE_SALT`, `LANGFUSE_ENCRYPTION_KEY`, `LANGFUSE_INIT_ORG_ID`, `LANGFUSE_INIT_PROJECT_ID`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` entries with placeholder values.
5. Verify `rag-api` and `rag-worker` service env blocks already contain the 4 Langfuse passthrough variables (no change required; document if already correct).

---

## Task Dependency Graph

```
Phase 1 (Foundation)           Phase 2           Phase 3         Phase 4          Phase 5
┌─────────────────┐
│  Task 1.1       │ [CRITICAL]
│  Backend ABC    │──────────────────────────────────────────────┐
│  + Schemas      │──────────────┐                               │
└─────────────────┘              │                               │
         │                       │                               │
         ▼                       ▼                               │
┌─────────────────┐    ┌──────────────────┐                      │
│  Task 1.2       │    │  Task 2.1        │ [CRITICAL]           │
│  NoopBackend    │    │  LangfuseBackend │                      │
│  Package        │    │  Package         │                      │
└─────────────────┘    └──────────────────┘                      │
         │                       │                               │
         └───────────┬───────────┘                               │
                     ▼                                           │
          ┌──────────────────────┐                               │
          │  Task 3.1 [CRITICAL] │◄──────────────────────────────┘
          │  Public API Facade   │
          │  + @observe          │
          └──────────────────────┘
                     │
            ┌────────┴────────┐
            ▼                 ▼
  ┌──────────────────┐  ┌──────────────────┐
  │  Task 4.1        │  │  Task 4.2        │
  │  Retrieval       │  │  Ingest          │
  │  Migration       │  │  Migration       │
  └──────────────────┘  └──────────────────┘

┌───────────────────────────────────────────┐
│  Task 5.1 (independent — runs in parallel │
│  with any phase)                          │
│  Docker Compose + .env.example            │
└───────────────────────────────────────────┘

[CRITICAL] path: Task 1.1 → Task 2.1 → Task 3.1 → Task 4.1
```

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|---|---|
| Task 1.1 | REQ-101, 103, 105, 107, 109, 111, 113, 115, 117, 119, 121, 123, 125, 127, 129, 131, 133, 135, 137, 139, 141, 143, 145, 147, 149, 151, 153, 155, 157 |
| Task 1.2 | REQ-159, 161, 163, 165 |
| Task 2.1 | REQ-201, 203, 205, 207, 209, 211, 213, 215, 217, 219, 221, 223, 225, 227, 229, 231, 233, 235, 237, 239, 241, 243, 245, 247, 249, 251 |
| Task 3.1 | REQ-167, 169, 171, 301, 303, 305, 307, 309, 311, 313, 315, 317, 319, 321, 323, 325, 327, 329, 331, 333, 335, 337, 339, 341 |
| Task 4.1 | REQ-401, 403, 405, 407, 409, 411, 413, 415, 417, 421, 423, 427, 429, 431, 435, 437, 439, 441 |
| Task 4.2 | REQ-401, 403, 405, 429, 431, 435, 437, 439 |
| Task 5.1 | REQ-501, 503, 505, 507, 509, 511, 513, 515, 517, 519, 521, 523, 525, 527, 529, 531, 533, 535, 537, 539, 541 |
| Task 3.1 (NFR) | REQ-901, 903, 905, 909, 913, 919, 921, 923, 925, 927, 929, 931, 933, 935, 939, 941 |
| Task 2.1 (NFR) | REQ-905, 907, 911, 915, 917 |
| Task 1.2 (NFR) | REQ-901, 903 |
| Task 5.1 (NFR) | REQ-937, 939 |

---

# Part B: Code Appendix

## B.1: ObservabilityBackend ABC and Sub-types — Contract

Defines the complete abstract interface for all observability backends. Consumed by Task 1.1 (to write), Task 1.2 (NoopBackend), Task 2.1 (LangfuseBackend), and Task 3.1 (factory return type).

**Tasks:** Task 1.1, Task 1.2, Task 2.1, Task 3.1
**Requirements:** REQ-101 through REQ-147
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
# src/platform/observability/backend.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class Span(ABC):
    """Abstract tracing span for a single timed operation.

    Supports both direct lifecycle management and use as a context manager.
    All concrete implementations must be fail-open: exceptions raised inside
    set_attribute or end must be caught internally and never propagated.
    """

    @abstractmethod
    def set_attribute(self, key: str, value: object) -> None:
        """Set a key-value attribute on this span.

        Args:
            key: Attribute name. Must be a snake_case string.
            value: Attribute value. Any Python object accepted.

        Returns:
            None. Never raises — fail-open contract.
        """

    @abstractmethod
    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        """Finalize this span.

        Args:
            status: "ok" for successful completion, "error" for failures.
            error: The exception that caused the failure, if any.

        Returns:
            None. Never raises — fail-open contract.
        """

    def __enter__(self) -> "Span":
        """Return self to enable use as a context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """End the span on context manager exit. Returns False (never suppresses exceptions)."""
        if exc_val is not None:
            self.end(status="error", error=exc_val)
        else:
            self.end(status="ok")
        return False


class Generation(ABC):
    """Abstract tracing generation for a single LLM call.

    A Generation is a specialised Span that additionally captures LLM-specific
    fields: prompt input, completion output, model name, and token counts.
    """

    @abstractmethod
    def set_output(self, output: str) -> None:
        """Record the LLM completion output.

        Args:
            output: The model completion text. Overwrites any previous value.

        Returns:
            None. Never raises — fail-open contract.
        """

    @abstractmethod
    def set_token_counts(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Record token usage for this generation.

        Args:
            prompt_tokens: Number of tokens in the input prompt.
            completion_tokens: Number of tokens in the model completion.

        Returns:
            None. Never raises — fail-open contract.
        """

    @abstractmethod
    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        """Finalize this generation record.

        Args:
            status: "ok" for successful completion, "error" for failures.
            error: The exception that caused the failure, if any.

        Returns:
            None. Never raises — fail-open contract.
        """

    def __enter__(self) -> "Generation":
        """Return self to enable use as a context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """End the generation on context manager exit. Returns False."""
        if exc_val is not None:
            self.end(status="error", error=exc_val)
        else:
            self.end(status="ok")
        return False


class Trace(ABC):
    """Abstract trace root — a logical grouping of spans and generations.

    A Trace represents one request or pipeline run. All child spans and
    generations created through this object share the same trace_id.
    """

    @abstractmethod
    def span(self, name: str, attributes: Optional[dict] = None) -> Span:
        """Create a child span under this trace.

        Args:
            name: Span name. Convention: "component.operation".
            attributes: Optional initial attributes. Defaults to empty dict.

        Returns:
            A Span instance correlated to this trace. Never raises — fail-open contract.
        """

    @abstractmethod
    def generation(
        self,
        name: str,
        model: str,
        input: str,
        metadata: Optional[dict] = None,
    ) -> Generation:
        """Create a child generation (LLM call) under this trace.

        Args:
            name: Generation name.
            model: Model identifier (e.g., "gpt-4o", "claude-3-5-sonnet").
            input: The prompt text sent to the model.
            metadata: Optional additional metadata.

        Returns:
            A Generation instance correlated to this trace. Never raises — fail-open.
        """

    def __enter__(self) -> "Trace":
        """Return self to enable use as a context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit the trace context. Returns False (never suppresses exceptions)."""
        return False


class ObservabilityBackend(ABC):
    """Abstract base class for all observability backend providers.

    Implementations must be substitutable without changes to consumers.
    The active backend is a process-wide singleton accessed via get_tracer().
    """

    @abstractmethod
    def span(
        self,
        name: str,
        attributes: Optional[dict] = None,
        parent: Optional[Span] = None,
    ) -> Span:
        """Start and return a new span.

        Args:
            name: Span name. Convention: "component.operation".
            attributes: Optional initial attributes dict.
            parent: Optional parent span for nesting.

        Returns:
            A Span instance. Never raises — fail-open contract.
        """

    @abstractmethod
    def trace(self, name: str, metadata: Optional[dict] = None) -> Trace:
        """Start and return a new trace root.

        Args:
            name: Trace name. Convention: "pipeline.operation".
            metadata: Optional metadata dict attached to the trace root.

        Returns:
            A Trace instance. Never raises — fail-open contract.
        """

    @abstractmethod
    def generation(
        self,
        name: str,
        model: str,
        input: str,
        metadata: Optional[dict] = None,
    ) -> Generation:
        """Start and return a new generation (LLM call tracking).

        Args:
            name: Generation name.
            model: Model identifier.
            input: The prompt text sent to the model.
            metadata: Optional additional metadata.

        Returns:
            A Generation instance. Never raises — fail-open contract.
        """

    @abstractmethod
    def flush(self) -> None:
        """Drain all pending buffered observations to the backend.

        Blocks until all buffered data is flushed. Propagates exceptions
        from the underlying SDK (callers must handle timeout/network errors).

        Returns:
            None.

        Raises:
            Any exception raised by the underlying SDK flush operation.
        """

    @abstractmethod
    def shutdown(self) -> None:
        """Gracefully shut down the backend client.

        Called on process exit. Propagates exceptions from the underlying SDK.

        Returns:
            None.

        Raises:
            Any exception raised by the underlying SDK shutdown operation.
        """


# Backward-compatible alias — deprecated, use ObservabilityBackend
Tracer = ObservabilityBackend
```

**Key design decisions:**
- `Span.__enter__`/`__exit__` and `Trace.__enter__`/`__exit__` are implemented in the ABC as concrete methods, not abstract — all backends get context manager support for free without duplicating the logic.
- `Generation.__enter__`/`__exit__` follows the same pattern.
- `flush()` and `shutdown()` deliberately propagate exceptions (unlike `set_attribute`/`end`) because these are called at controlled lifecycle points where the caller needs to know if data was lost.
- `Tracer = ObservabilityBackend` alias is in `backend.py` for use by the `__init__.py` DeprecationWarning wrapper.

---

## B.2: Schema Dataclasses — Contract

Defines the canonical record types for in-memory span/trace/generation data. These are provider-agnostic and importable without any third-party SDK installed.

**Tasks:** Task 1.1
**Requirements:** REQ-149, REQ-151, REQ-153, REQ-155, REQ-157
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
# src/platform/observability/schemas.py
from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Optional


@dataclass
class SpanRecord:
    """In-memory record for a completed span observation.

    Produced when Span.end() is called. Used for testing assertions
    and noop backend record capture.
    """

    name: str                                      # REQ-149
    trace_id: str                                  # REQ-149
    parent_span_id: Optional[str]                  # REQ-149
    attributes: dict = field(default_factory=dict) # REQ-149
    start_ts: float = field(default_factory=time)  # REQ-155
    end_ts: Optional[float] = None                 # REQ-155 — set by end()
    status: str = "ok"                             # REQ-117, REQ-149
    error_message: Optional[str] = None            # REQ-117, REQ-149


@dataclass
class TraceRecord:
    """In-memory record for a completed trace root.

    Produced when a Trace context manager exits or is manually closed.
    """

    name: str                                      # REQ-151
    trace_id: str                                  # REQ-151 — must not be None
    metadata: dict = field(default_factory=dict)   # REQ-151
    start_ts: float = field(default_factory=time)  # REQ-155
    end_ts: Optional[float] = None                 # REQ-155 — set by end()
    status: str = "ok"                             # REQ-151


@dataclass
class GenerationRecord:
    """In-memory record for a completed LLM generation observation.

    output, prompt_tokens, completion_tokens are optional because
    set_output() and set_token_counts() may not be called before end()
    in error paths or streaming scenarios.
    """

    name: str                                       # REQ-153
    trace_id: str                                   # REQ-153
    model: str                                      # REQ-153
    input: str                                      # REQ-153
    output: Optional[str] = None                    # REQ-153
    prompt_tokens: Optional[int] = None             # REQ-153
    completion_tokens: Optional[int] = None         # REQ-153
    start_ts: float = field(default_factory=time)   # REQ-155
    end_ts: Optional[float] = None                  # REQ-155
    status: str = "ok"                              # REQ-153
```

**Key design decisions:**
- `start_ts` uses `default_factory=time` so it is set at construction time, not at class definition time.
- `end_ts` defaults to `None` and is set by `end()` — this separates construction from finalization.
- All three record types use `@dataclass` (not `TypedDict`) for field-level defaults and `default_factory` support.

---

## B.3: NoopBackend Contract

Defines the complete no-op implementation. All methods return appropriate typed objects immediately with zero side effects.

**Tasks:** Task 1.2
**Requirements:** REQ-159, REQ-161, REQ-163, REQ-165
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
# src/platform/observability/noop/backend.py
from __future__ import annotations

from typing import Optional

from src.platform.observability.backend import (
    Generation,
    ObservabilityBackend,
    Span,
    Trace,
)


class NoopSpan(Span):
    """Span implementation that does nothing."""

    def set_attribute(self, key: str, value: object) -> None:
        """Set attribute (no-op). Accepts any input, never raises."""
        return

    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        """End span (no-op). Accepts any input, never raises."""
        return


class NoopGeneration(Generation):
    """Generation implementation that does nothing."""

    def set_output(self, output: str) -> None:
        """Record output (no-op). Accepts any input, never raises."""
        return

    def set_token_counts(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Record token counts (no-op). Accepts any input, never raises."""
        return

    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        """End generation (no-op). Accepts any input, never raises."""
        return


class NoopTrace(Trace):
    """Trace implementation that returns no-op children."""

    def span(self, name: str, attributes: Optional[dict] = None) -> Span:
        """Return a NoopSpan. Accepts any input, never raises."""
        return NoopSpan()

    def generation(
        self,
        name: str,
        model: str,
        input: str,
        metadata: Optional[dict] = None,
    ) -> Generation:
        """Return a NoopGeneration. Accepts any input, never raises."""
        return NoopGeneration()


class NoopBackend(ObservabilityBackend):
    """Observability backend that performs no operations.

    Active when OBSERVABILITY_PROVIDER is unset or set to "noop".
    Also used as the fallback when the configured backend fails to initialize.
    All methods return typed no-op objects immediately with zero I/O.
    """

    def span(
        self,
        name: str,
        attributes: Optional[dict] = None,
        parent: Optional[Span] = None,
    ) -> Span:
        """Return a NoopSpan immediately."""
        return NoopSpan()

    def trace(self, name: str, metadata: Optional[dict] = None) -> Trace:
        """Return a NoopTrace immediately."""
        return NoopTrace()

    def generation(
        self,
        name: str,
        model: str,
        input: str,
        metadata: Optional[dict] = None,
    ) -> Generation:
        """Return a NoopGeneration immediately."""
        return NoopGeneration()

    def flush(self) -> None:
        """Flush (no-op). Returns immediately."""
        return

    def shutdown(self) -> None:
        """Shutdown (no-op). Returns immediately."""
        return
```

**Key design decisions:**
- The ABC `__enter__`/`__exit__` concrete methods on `Span`, `Trace`, and `Generation` are inherited — no need to re-implement in noop subclasses.
- `NoopTrace.span` and `NoopTrace.generation` accept `None` as `name` (and any other nonsense) without raising — the no-op contract is total.

---

## B.4: Public API Stubs — Contract

The public API surface of the observability package. `get_tracer` and `observe` are the primary consumer-facing symbols.

**Tasks:** Task 3.1
**Requirements:** REQ-167, REQ-169, REQ-171, REQ-305, REQ-307, REQ-309, REQ-311, REQ-313, REQ-339
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
# src/platform/observability/__init__.py  (stubs only — see B.5 for singleton pattern)
from __future__ import annotations

import functools
import threading
import warnings
from typing import Callable, Optional, TypeVar

from src.platform.observability.backend import (
    Generation,
    ObservabilityBackend,
    Span,
    Trace,
)

F = TypeVar("F", bound=Callable)

# Internal singleton state — do not access directly
_backend: Optional[ObservabilityBackend] = None
_backend_lock = threading.Lock()


def get_tracer() -> ObservabilityBackend:
    """Return the process-wide ObservabilityBackend singleton.

    Initializes the backend on first call using OBSERVABILITY_PROVIDER.
    Subsequent calls return the same instance. Thread-safe.

    Returns:
        The active ObservabilityBackend. Never raises — falls back to NoopBackend.
    """
    raise NotImplementedError("Task 3.1")


def observe(
    name: Optional[str] = None,
    capture_input: bool = False,
    capture_output: bool = False,
) -> Callable[[F], F]:
    """Decorator factory that wraps a function with an observability span.

    Usage:
        @observe("reranker.rerank")
        def rerank(self, query, documents): ...

        @observe(capture_output=True)
        def generate(self, prompt): ...

    Args:
        name: Span name. Defaults to func.__qualname__ if not provided.
        capture_input: If True, records positional args (excluding self/cls)
            as "input" attribute, truncated to 500 chars. Defaults to False.
        capture_output: If True, records return value as "output" attribute,
            truncated to 500 chars. Defaults to False.

    Returns:
        A decorator that preserves __name__, __qualname__, __doc__ via functools.wraps.
        The wrapped function raises exceptions normally (no suppression).
    """
    raise NotImplementedError("Task 3.1")


def _init_backend() -> ObservabilityBackend:
    """Initialize and return the backend based on OBSERVABILITY_PROVIDER.

    Called once at first get_tracer() invocation. Not intended for direct use.

    Returns:
        The initialized ObservabilityBackend.

    Notes:
        Falls back to NoopBackend on any initialization error, logging a warning.
    """
    raise NotImplementedError("Task 3.1")


# Deprecated alias — use ObservabilityBackend
def _tracer_alias_getter():
    warnings.warn(
        "Importing 'Tracer' from src.platform.observability is deprecated. "
        "Use 'ObservabilityBackend' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return ObservabilityBackend


Tracer = ObservabilityBackend  # Simple alias; DeprecationWarning via providers.py shim

__all__ = ["get_tracer", "observe", "Tracer", "Span", "Trace", "Generation"]
```

**Key design decisions:**
- `_backend` and `_backend_lock` are module-level so they survive import caching and are shared across all callers.
- `observe` returns a generic `Callable[[F], F]` to preserve type inference for callers using the decorator.
- `Tracer` alias is kept simple; the DeprecationWarning path is through `providers.py` import for consumers still using the old path.

---

## B.5: Thread-Safe Singleton Factory — Pattern

Illustrates the double-checked locking pattern for thread-safe lazy initialization of the backend singleton.

**Tasks:** Task 3.1
**Requirements:** REQ-167, REQ-169, REQ-171, REQ-309, REQ-311
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
"""
Thread-safe singleton initialization for the ObservabilityBackend.

Uses double-checked locking to minimize lock contention on the hot path
(get_tracer() is called on every instrumented request).
"""

import logging
import threading
from typing import Optional

from src.platform.observability.backend import ObservabilityBackend
from src.platform.observability.noop.backend import NoopBackend

logger = logging.getLogger("rag.observability")

_backend: Optional[ObservabilityBackend] = None
_backend_lock = threading.Lock()


def get_tracer() -> ObservabilityBackend:
    """Return the process-wide singleton. Thread-safe via double-checked locking."""
    global _backend
    # Fast path: singleton already initialized (no lock needed)
    if _backend is not None:
        return _backend
    # Slow path: first call — acquire lock and initialize
    with _backend_lock:
        if _backend is None:  # Double-check under lock
            _backend = _init_backend()
    return _backend


def _init_backend() -> ObservabilityBackend:
    """Initialize the backend from OBSERVABILITY_PROVIDER. Called once."""
    from config.settings import OBSERVABILITY_PROVIDER  # lazy import

    provider = OBSERVABILITY_PROVIDER.strip().lower()

    if provider == "noop" or not provider:
        return NoopBackend()

    if provider == "langfuse":
        try:
            from src.platform.observability.langfuse.backend import LangfuseBackend
            return LangfuseBackend()
        except Exception as exc:
            logger.warning(
                "Failed to initialize langfuse backend (%s); falling back to noop.",
                exc,
            )
            return NoopBackend()

    raise ValueError(
        f"Unknown OBSERVABILITY_PROVIDER: {provider!r}. "
        "Valid values: 'noop', 'langfuse'."
    )
```

**Key design decisions:**
- Double-checked locking: the `if _backend is not None` check outside the lock is the fast path; under the lock, the second check prevents double-initialization if two threads both passed the first check.
- Unknown provider raises `ValueError` before returning, not after — this causes a startup error at first `get_tracer()` call (REQ-167).
- `OBSERVABILITY_PROVIDER` is imported lazily inside `_init_backend()` to avoid circular imports during module load.

---

## B.6: @observe Decorator — Pattern

Illustrates the decorator factory implementation including `functools.wraps`, configurable capture, truncation, and error attribute recording.

**Tasks:** Task 3.1
**Requirements:** REQ-313, REQ-315, REQ-317, REQ-319, REQ-321, REQ-323, REQ-325, REQ-327, REQ-329
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
"""
Generic @observe decorator for wrapping functions with observability spans.
Works with any configured backend (Langfuse, noop, or future providers).
"""

import functools
from typing import Callable, Optional, TypeVar

F = TypeVar("F", bound=Callable)

_MAX_CAPTURE_LEN = 500


def observe(
    name: Optional[str] = None,
    capture_input: bool = False,
    capture_output: bool = False,
) -> Callable[[F], F]:
    """Decorator factory for automatic span instrumentation."""

    def decorator(func: F) -> F:
        span_name = name if name is not None else func.__qualname__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            backend = get_tracer()  # always fetches singleton
            with backend.span(span_name) as span:
                # Input capture: skip first positional arg (self/cls)
                if capture_input and args:
                    captured = repr(args[1:])[:_MAX_CAPTURE_LEN]
                    span.set_attribute("input", captured)
                try:
                    result = func(*args, **kwargs)
                except Exception as exc:
                    span.set_attribute("error", str(exc))
                    raise
                # Output capture on successful return
                if capture_output:
                    captured = repr(result)[:_MAX_CAPTURE_LEN]
                    span.set_attribute("output", captured)
                return result
        return wrapper  # type: ignore[return-value]

    return decorator
```

**Key design decisions:**
- `get_tracer()` is called inside `wrapper`, not in `decorator`. This means `@observe` can be applied before the backend singleton is initialized (e.g., at module import time) without forcing early initialization.
- `with backend.span(span_name) as span:` — the context manager handles `end(status="error")` automatically on exception; the `except` block only adds the `"error"` attribute before re-raising, it does NOT call `span.end()` (that would double-end).
- `repr(args[1:])[:_MAX_CAPTURE_LEN]` skips `args[0]` (self/cls) for methods; for plain functions this is harmless (first arg is still captured).

---

## B.7: LangfuseBackend Implementation — Pattern

Illustrates the structure of `LangfuseBackend` and its wrapper classes, showing the SDK call patterns and fail-open exception handling.

**Tasks:** Task 2.1
**Requirements:** REQ-201, REQ-205, REQ-207, REQ-211, REQ-213, REQ-215, REQ-217, REQ-221, REQ-227, REQ-235, REQ-237, REQ-249, REQ-251
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
"""
Langfuse v3 backend implementation.
All imports from `langfuse` are confined to this file.
"""

import logging
from typing import Optional

from src.platform.observability.backend import (
    Generation,
    ObservabilityBackend,
    Span,
    Trace,
)
from src.platform.observability.noop.backend import NoopSpan, NoopGeneration

logger = logging.getLogger("rag.observability.langfuse")


class LangfuseSpan(Span):
    def __init__(self, inner_obs):
        self._inner = inner_obs

    def set_attribute(self, key: str, value: object) -> None:
        try:
            self._inner.update(metadata={key: value})
        except Exception as exc:
            logger.warning("LangfuseSpan.set_attribute failed: %s", exc)

    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        try:
            if error is not None:
                self._inner.update(level="ERROR", status_message=str(error))
            self._inner.end()
        except Exception as exc:
            logger.warning("LangfuseSpan.end failed: %s", exc)


class LangfuseGeneration(Generation):
    def __init__(self, inner_obs):
        self._inner = inner_obs

    def set_output(self, output: str) -> None:
        try:
            self._inner.update(output=output)
        except Exception as exc:
            logger.warning("LangfuseGeneration.set_output failed: %s", exc)

    def set_token_counts(self, prompt_tokens: int, completion_tokens: int) -> None:
        try:
            self._inner.update(usage={"input": prompt_tokens, "output": completion_tokens})
        except Exception as exc:
            logger.warning("LangfuseGeneration.set_token_counts failed: %s", exc)

    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        try:
            if error is not None:
                self._inner.update(level="ERROR", status_message=str(error))
            self._inner.end()
        except Exception as exc:
            logger.warning("LangfuseGeneration.end failed: %s", exc)


class LangfuseTrace(Trace):
    def __init__(self, trace_obj):
        self._trace = trace_obj

    def span(self, name: str, attributes: Optional[dict] = None) -> Span:
        try:
            obs = self._trace.span(name=name, metadata=attributes or {})
            return LangfuseSpan(obs)
        except Exception as exc:
            logger.warning("LangfuseTrace.span failed: %s", exc)
            return NoopSpan()

    def generation(self, name: str, model: str, input: str,
                   metadata: Optional[dict] = None) -> Generation:
        try:
            obs = self._trace.generation(
                name=name, model=model, input=input, metadata=metadata or {}
            )
            return LangfuseGeneration(obs)
        except Exception as exc:
            logger.warning("LangfuseTrace.generation failed: %s", exc)
            return NoopGeneration()


class LangfuseBackend(ObservabilityBackend):
    def __init__(self):
        from langfuse import get_client  # SDK import confined here
        self._client = get_client()  # Raises on misconfiguration — caller handles

    def span(self, name: str, attributes: Optional[dict] = None,
             parent: Optional[Span] = None) -> Span:
        try:
            if isinstance(parent, LangfuseTrace):
                obs = parent._trace.span(name=name, metadata=attributes or {})
            else:
                obs = self._client.start_observation(
                    as_type="span", name=name, metadata=attributes or {}
                )
            return LangfuseSpan(obs)
        except Exception as exc:
            logger.warning("LangfuseBackend.span failed: %s", exc)
            return NoopSpan()

    def trace(self, name: str, metadata: Optional[dict] = None) -> Trace:
        try:
            t = self._client.trace(name=name, metadata=metadata or {})
            return LangfuseTrace(t)
        except Exception as exc:
            logger.warning("LangfuseBackend.trace failed: %s", exc)
            from src.platform.observability.noop.backend import NoopTrace
            return NoopTrace()

    def generation(self, name: str, model: str, input: str,
                   metadata: Optional[dict] = None) -> Generation:
        try:
            obs = self._client.start_observation(
                as_type="generation", name=name, model=model,
                input=input, metadata=metadata or {}
            )
            return LangfuseGeneration(obs)
        except Exception as exc:
            logger.warning("LangfuseBackend.generation failed: %s", exc)
            return NoopGeneration()

    def flush(self) -> None:
        self._client.flush()  # Propagates exceptions (REQ-249)

    def shutdown(self) -> None:
        self._client.shutdown()  # Propagates exceptions (REQ-251)
```

**Key design decisions:**
- `LangfuseTrace.span` and `LangfuseTrace.generation` fall back to noop objects (not `None`) on SDK errors — callers always get a valid object they can call methods on.
- `flush()` and `shutdown()` intentionally do NOT catch exceptions, unlike all other methods. This is a deliberate asymmetry per REQ-249/251: these are called at lifecycle checkpoints where failure must be visible.
- `LangfuseBackend.span` inspects `isinstance(parent, LangfuseTrace)` to determine whether to route through the trace object — this keeps trace-child correlation correct in Langfuse's data model.

---

## B.8: Docker Compose Langfuse Service — Pattern

Illustrates the two service definitions and volume declaration to be added to `docker-compose.yml`.

**Tasks:** Task 5.1
**Requirements:** REQ-501 through REQ-541
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```yaml
# Illustrative pattern — not the final implementation
# Add to docker-compose.yml

  # ── Observability profile ────────────────────────────────────────────
  # Start with: docker compose --profile observability up -d
  # UI available at http://localhost:${LANGFUSE_PORT:-3000}

  langfuse-db:
    image: postgres:16-alpine
    container_name: rag-langfuse-db
    profiles: [observability]
    environment:
      POSTGRES_USER: langfuse
      POSTGRES_PASSWORD: langfuse
      POSTGRES_DB: langfuse
    volumes:
      - langfuse-db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U langfuse"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    restart: unless-stopped

  langfuse:
    image: langfuse/langfuse:3
    container_name: rag-langfuse
    profiles: [observability]
    depends_on:
      langfuse-db:
        condition: service_healthy
    ports:
      - "${LANGFUSE_PORT:-3000}:3000"
    environment:
      DATABASE_URL: postgresql://langfuse:langfuse@langfuse-db:5432/langfuse
      NEXTAUTH_URL: http://localhost:${LANGFUSE_PORT:-3000}
      NEXTAUTH_SECRET: ${LANGFUSE_NEXTAUTH_SECRET}
      SALT: ${LANGFUSE_SALT}
      ENCRYPTION_KEY: ${LANGFUSE_ENCRYPTION_KEY}
      LANGFUSE_INIT_ORG_ID: ${LANGFUSE_INIT_ORG_ID:-my-org}
      LANGFUSE_INIT_PROJECT_ID: ${LANGFUSE_INIT_PROJECT_ID:-my-project}
      LANGFUSE_INIT_PROJECT_PUBLIC_KEY: ${LANGFUSE_PUBLIC_KEY:-}
      LANGFUSE_INIT_PROJECT_SECRET_KEY: ${LANGFUSE_SECRET_KEY:-}
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:3000/api/public/health || exit 1"]
      interval: 15s
      timeout: 10s
      retries: 5
      start_period: 30s
    restart: unless-stopped

# Add to top-level volumes block:
# volumes:
#   langfuse-db-data:
```

**Key design decisions:**
- `langfuse-db` uses `POSTGRES_USER/PASSWORD=langfuse` (matching the `DATABASE_URL`) rather than a separate secret, consistent with the existing `temporal-db` pattern.
- `start_period: 30s` on the `langfuse` service gives Langfuse time to run its database migrations before health checks start counting retries — Langfuse v3 migrations can take 10-20 seconds on first boot.
- `LANGFUSE_INIT_*` variables seed the initial organization, project, and API keys on first boot so the application services can connect immediately without manual UI setup.
