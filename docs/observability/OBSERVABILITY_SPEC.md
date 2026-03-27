# Swappable Observability Subsystem — Requirements Specification

| Field | Value |
|---|---|
| Version | 1.0 |
| Date | 2026-03-27 |
| Status | Draft |
| Authors | Autonomous Pipeline |

---

## 1. Scope & Definitions

### 1.1 Problem Statement

The current observability subsystem at `src/platform/observability/` provides a minimal span-and-tracer abstraction backed by Langfuse, but its structure imposes several maintenance and extensibility liabilities.

First, Langfuse-specific code lives flat alongside the abstract base classes — `langfuse_tracer.py` occupies the same directory level as `contracts.py` and `providers.py`. There is no provider-scoped subdirectory. As a result, swapping or adding a backend (e.g., LangSmith) would require modifying files that consumers of the public API should never need to touch.

Second, the developer ergonomics are poor. There is no context manager on `Span`, so consumers must write verbose `try/finally` blocks to guarantee `end()` is called. There is no `@observe` decorator for the common case of tracing a single function. There is no `Trace` grouping concept, so spans from a single pipeline run cannot be correlated in the Langfuse UI without manual session/trace ID plumbing.

Third, consumers import from an internal module (`from src.platform.observability.providers import get_tracer`) rather than the stable package root. Any internal restructuring becomes a consumer-visible breaking change.

Fourth, Langfuse has no Docker Compose service definition. Unlike Temporal, which can be started with a single profile flag, Langfuse must be launched manually outside the project's infrastructure tooling.

---

### 1.2 Scope Boundary

| Boundary | Definition |
|---|---|
| **Entry points** | Call sites in `src/ingest/` and `src/retrieval/` that import from `src.platform.observability`. |
| **Exit points** | Trace and span data visible in the Langfuse UI when the Langfuse backend is active; no output when the noop backend is active. |
| **System boundary** | `src/platform/observability/` (all provider logic and the public API facade) + the Docker Compose file (Langfuse service definition) + consumer call sites (instrumentation patterns). |
| **Out of process** | The Langfuse server itself (OSS, run via Docker). This spec covers how the project starts and connects to it, not how Langfuse works internally. |

---

### 1.3 Terminology

| Term | Definition |
|---|---|
| **ObservabilityBackend** | The abstract base class (ABC) defining the contract that every concrete provider must implement. Replaces the current `Tracer` ABC in `contracts.py`. |
| **Tracer** | A process-wide singleton that holds the active `ObservabilityBackend` instance. Call sites obtain it via the public API; they never instantiate backends directly. |
| **Span** | A single timed operation within a trace (e.g., `"reranker.rerank"`). Has a name, start time, end time, and an arbitrary dictionary of attributes. Must support use as a context manager. |
| **Trace** | A logical grouping of spans representing one request or pipeline run. Provides correlation across all spans emitted during that run. |
| **Generation** | A specialised span that additionally captures LLM-specific fields: prompt input, completion output, model name, and token counts. |
| **Provider** | A concrete implementation of `ObservabilityBackend` (e.g., `LangfuseBackend`, `NoopBackend`). All provider-specific code must be isolated inside a provider-scoped subdirectory. |
| **`@observe`** | A generic function decorator that wraps the decorated function with a span automatically. |
| **`flush()`** | A method on the backend that drains any pending buffered observations to the backend. Critical for short-lived workers (e.g., Temporal activities). |
| **Noop backend** | A `NoopBackend` implementation whose every method is a zero-cost no-op. |
| **`OBSERVABILITY_PROVIDER`** | The environment variable whose value selects the active backend at process startup. |
| **Profile-based opt-in** | A Docker Compose `--profile` flag pattern that starts an optional service only when the operator explicitly requests it. |
| **Stable public API** | The set of symbols exported from `src.platform.observability` (the package root `__init__.py`). |

---

### 1.4 Requirement Format & Priority Levels

Requirements in Sections 3–9 use the following blockquote format:

> **REQ-xxx** | Priority: MUST/SHOULD/MAY
>
> **Description:** A single, testable statement of what the system must do or be.
>
> **Rationale:** Why this requirement exists.
>
> **Acceptance Criteria:** A concrete, verifiable condition that confirms the requirement is satisfied.

Priority keywords follow RFC 2119:

| Keyword | Meaning |
|---|---|
| **MUST** | An absolute requirement. Non-conformant if not satisfied. |
| **SHOULD** | A strong recommendation. Deviation permitted only with documented reason. |
| **MAY** | An optional capability. |

---

### 1.5 ID Convention

| ID Range | Section | Subject |
|---|---|---|
| REQ-1xx | Section 3 | Backend Abstraction — `ObservabilityBackend` ABC, `Span`, `Trace`, `Generation` contracts |
| REQ-2xx | Section 4 | Langfuse Backend — `LangfuseBackend` implementation and subdirectory isolation |
| REQ-3xx | Section 5 | Public API & Decorators — `get_tracer()`, `@observe`, context-manager `Span`, stable imports |
| REQ-4xx | Section 6 | Consumer Integration — migration of existing call sites, backward-compatible aliases |
| REQ-5xx | Section 7 | Infrastructure — Docker Compose Langfuse service, profile-based opt-in, health check |
| REQ-9xx | Section 8 | Non-Functional Requirements — fail-open, zero-overhead noop, startup latency |

---

### 1.6 Assumptions & Constraints

- Python 3.10 or higher is required.
- The `langfuse` SDK (v3) is already declared as a dependency in `pyproject.toml`.
- The noop backend must be importable and functional with zero third-party dependencies.
- The refactor must not break any existing consumer import during the migration period.
- Docker Compose is the authoritative local infrastructure tool. The Langfuse service must follow the same profile opt-in pattern established for Temporal.
- Langfuse is assumed to be running at a configurable host/port. The backend must fail open if the Langfuse server is unreachable at startup or during operation.
- The `OBSERVABILITY_PROVIDER` environment variable is the sole configuration mechanism for backend selection.
- Tests must not require a live Langfuse server.
- The guardrails package (`src/guardrails/`) is the authoritative reference pattern for provider isolation.

---

### 1.7 Design Principles

**1. Fail-open** — Any error during backend initialization, span creation, attribute setting, or span completion must be caught and silently suppressed. Observability must never crash the application it observes.

**2. Provider-agnostic consumers** — No symbol from a provider-specific SDK may appear in any import statement outside of that provider's subdirectory. Consumers interact exclusively with the `ObservabilityBackend` ABC and the public API.

**3. Config-driven selection** — The active backend is chosen at process startup by reading `OBSERVABILITY_PROVIDER` from the environment, with no code change required to switch providers.

**4. Stable public API** — The package root `__init__.py` is the only import surface consumers are permitted to use. Internal module paths are implementation details.

**5. Zero-overhead noop** — When `OBSERVABILITY_PROVIDER` is unset or `"noop"`, the active backend is `NoopBackend`, whose every method returns immediately with no computation, no allocation beyond a trivial return value, and no I/O.

---

### 1.8 Out of Scope

#### Out of scope for this specification
- LangSmith backend implementation
- OpenTelemetry exporter / OTLP protocol
- Prometheus-to-Langfuse bridging
- Multi-tenant trace isolation (per-user trace namespacing)
- Automatic PII redaction from span attributes
- Distributed tracing across service boundaries (cross-process context propagation)

#### Out of scope for this project (acknowledged but not planned)
- Production-hardened Langfuse deployment (TLS, external PostgreSQL, backup)
- Custom UI or dashboard layer built on Langfuse data
- Automatic propagation of trace context into LLM API calls via Langfuse hooks

---

## 2. System Overview

### 2.1 Architecture Diagram

```
  Call Sites (Application Layer)
  ┌─────────────────────────────────────────────────────────────────────┐
  │  [src/retrieval/query/nodes/reranker.py]                            │
  │  [src/retrieval/generation/nodes/generator.py]                      │
  │  [src/ingest/support/docling.py]  ... (8 consumers total)           │
  │                                                                      │
  │   from src.platform.observability import observe, get_tracer        │
  │                                                                      │
  │   @observe("stage.name")           with get_tracer().trace() as t:  │
  │   def fn(): ...                        span = t.span(...)           │
  └──────────────────────────┬──────────────────────────────────────────┘
                             │
                             ▼
  Public API  [src/platform/observability/__init__.py]
  ┌─────────────────────────────────────────────────────────────────────┐
  │   get_tracer()  ·  observe()  ·  Tracer  ·  Span  ·  Trace         │
  │   Generation                                                         │
  │   get_tracer() returns process-wide ObservabilityBackend singleton  │
  └──────────────────────────┬──────────────────────────────────────────┘
                             │
                             ▼
  Abstractions  [src/platform/observability/backend.py]
  ┌─────────────────────────────────────────────────────────────────────┐
  │   ObservabilityBackend (ABC)                                        │
  │   ├── Span (ABC)         ─ start / end / set_attribute              │
  │   ├── Trace (ABC)        ─ span() / context manager                 │
  │   └── Generation (ABC)   ─ LLM call tracking                       │
  │   [src/platform/observability/schemas.py]                           │
  │   SpanRecord · TraceRecord · GenerationRecord  (dataclasses)        │
  └──────────┬───────────────────────────────────────┬──────────────────┘
             │ OBSERVABILITY_PROVIDER=langfuse        │ OBSERVABILITY_PROVIDER=noop
             ▼                                        ▼
  ┌─────────────────────────┐            ┌────────────────────────────┐
  │  LangfuseBackend        │            │  NoopBackend               │
  │  [.../langfuse/         │            │  [.../noop/backend.py]     │
  │     backend.py]         │            │  all methods are           │
  │  LangfuseSpan           │            │  silent no-ops             │
  │  LangfuseTrace          │            │  (no output)               │
  │  LangfuseGeneration     │            │                            │
  │  (all Langfuse SDK      │            └────────────────────────────┘
  │   imports confined here)│
  └────────────┬────────────┘
               │  Langfuse SDK calls
               ▼
  ╔═════════════════════════════════════════════════════════╗
  ║  Docker Layer  (profile: observability)                 ║
  ║  ┌──────────────────────────┐                          ║
  ║  │  langfuse                │  ◄── http://localhost:3000
  ║  │  langfuse/langfuse:3     │                          ║
  ║  └────────────┬─────────────┘                          ║
  ║               │ SQL                                     ║
  ║               ▼                                         ║
  ║  ┌──────────────────────────┐                          ║
  ║  │  langfuse-db             │                          ║
  ║  │  PostgreSQL 16           │                          ║
  ║  └──────────────────────────┘                          ║
  ╚═════════════════════════════════════════════════════════╝
```

---

### 2.2 Data Flow Summary

| Stage | Input | Output | Component |
|---|---|---|---|
| 1. Instrumentation | Call site invokes `@observe("name")` or `with tracer.trace("name")` | Request to open a trace or span | `src/platform/observability/__init__.py` |
| 2. Backend resolution | `OBSERVABILITY_PROVIDER` env var read at process startup | Process-wide `ObservabilityBackend` singleton | `get_tracer()` in `__init__.py` |
| 3. Backend dispatch | `trace()` / `span()` / `generation()` call on singleton | Concrete `Span`, `Trace`, or `Generation` instance | `ObservabilityBackend` ABC |
| 4a. Langfuse recording | Span/trace/generation lifecycle events | Langfuse SDK calls | `LangfuseBackend` (`langfuse/backend.py`) |
| 4b. Noop recording | Same events | (no output) | `NoopBackend` (`noop/backend.py`) |
| 5. SDK transmission | Langfuse SDK payload | HTTP requests to Langfuse server | Langfuse SDK (confined to `langfuse/`) |
| 6. Persistent storage | Ingested records | Durable trace state | `langfuse-db` PostgreSQL 16 |
| 7. Developer inspection | Browser request to `http://localhost:3000` | Rendered trace UI | Langfuse UI |

---

### 2.3 Component Summary

| Component | Location | Responsibility |
|---|---|---|
| Public API | `src/platform/observability/__init__.py` | Stable import surface; exports `get_tracer`, `observe`, `Tracer`, `Span`, `Trace`, `Generation` |
| `ObservabilityBackend` ABC | `src/platform/observability/backend.py` | Defines provider contract: `Span`, `Trace`, `Generation` ABCs |
| Record schemas | `src/platform/observability/schemas.py` | `SpanRecord`, `TraceRecord`, `GenerationRecord` dataclasses |
| `NoopBackend` | `src/platform/observability/noop/backend.py` | Silent no-op; default when `OBSERVABILITY_PROVIDER` is unset or `noop` |
| `LangfuseBackend` | `src/platform/observability/langfuse/backend.py` | Langfuse-specific implementation; all SDK imports confined here |
| `langfuse` Docker service | `docker-compose.yml` (profile: `observability`) | Runs `langfuse/langfuse:3`; UI + API on port 3000 |
| `langfuse-db` Docker service | `docker-compose.yml` (profile: `observability`) | Runs PostgreSQL 16; dedicated storage for Langfuse data |
| Call-site consumers | `src/retrieval/**` and `src/ingest/**` (8 files) | Import only from the public API |

---

## 3. Backend Abstraction

### 3.1 ObservabilityBackend ABC

> **REQ-101** | Priority: MUST
>
> **Description:** `ObservabilityBackend` must be defined as an abstract base class (ABC) in `src/platform/observability/backend.py`, exporting the methods `span`, `trace`, `generation`, `flush`, and `shutdown` as abstract methods.
>
> **Rationale:** A single canonical ABC ensures all backend implementations satisfy the same contract and can be substituted without changes to callers.
>
> **Acceptance Criteria:** Attempting to instantiate `ObservabilityBackend` directly raises `TypeError`. A concrete subclass that does not implement all five methods also raises `TypeError` on instantiation.

---

> **REQ-103** | Priority: MUST
>
> **Description:** `ObservabilityBackend.span(name: str, attributes: dict | None = None, parent: Span | None = None) -> Span` must return an object that is an instance of the `Span` ABC.
>
> **Rationale:** Callers must be able to rely on the returned object supporting `set_attribute`, `end`, and context manager protocol without inspecting its concrete type.
>
> **Acceptance Criteria:** For any conforming backend implementation, `isinstance(backend.span("x"), Span)` returns `True`. Passing `parent=None` and an existing `Span` instance both succeed without raising.

---

> **REQ-105** | Priority: MUST
>
> **Description:** `ObservabilityBackend.trace(name: str, metadata: dict | None = None) -> Trace` must return an object that is an instance of the `Trace` ABC.
>
> **Rationale:** Callers need a consistent Trace handle regardless of the active backend.
>
> **Acceptance Criteria:** For any conforming backend implementation, `isinstance(backend.trace("x"), Trace)` returns `True`. Omitting `metadata` is accepted without raising.

---

> **REQ-107** | Priority: MUST
>
> **Description:** `ObservabilityBackend.generation(name: str, model: str, input: str, metadata: dict | None = None) -> Generation` must return an object that is an instance of the `Generation` ABC.
>
> **Rationale:** LLM call tracking is a first-class concern; the ABC must enforce that all backends provide a conforming Generation handle.
>
> **Acceptance Criteria:** For any conforming backend, `isinstance(backend.generation("g", "gpt-4", "hello"), Generation)` returns `True`. Omitting any required positional parameter raises `TypeError`.

---

> **REQ-109** | Priority: MUST
>
> **Description:** `ObservabilityBackend.flush() -> None` must be declared as an abstract method. Concrete implementations must complete all pending writes before returning.
>
> **Rationale:** Tests and shutdown sequences need a synchronization point to ensure no observations are dropped before the process exits.
>
> **Acceptance Criteria:** After calling `flush()`, any record finalized before the `flush()` call is retrievable from the backend's storage or export target. `flush()` returns `None`.

---

> **REQ-111** | Priority: MUST
>
> **Description:** `ObservabilityBackend.shutdown() -> None` must be declared as an abstract method. After `shutdown()` is called, subsequent calls to `span`, `trace`, `generation`, and `flush` on the same instance must not raise an exception.
>
> **Rationale:** Process-exit hooks may call `shutdown()` before all application code has completed; callers must not crash because shutdown was invoked early.
>
> **Acceptance Criteria:** A backend instance that has had `shutdown()` called accepts subsequent calls to `span("x")`, `trace("x")`, `generation("g", "m", "i")`, and `flush()` without raising.

---

### 3.2 Span Contract

> **REQ-113** | Priority: MUST
>
> **Description:** `Span` must be defined as an ABC in `src/platform/observability/backend.py` with abstract methods `set_attribute`, `end`, `__enter__`, and `__exit__`.
>
> **Rationale:** Callers use spans directly and via `with` statements; both usage patterns must be guaranteed by the ABC.
>
> **Acceptance Criteria:** A concrete subclass of `Span` that omits any one of `set_attribute`, `end`, `__enter__`, or `__exit__` raises `TypeError` on instantiation.

---

> **REQ-115** | Priority: MUST
>
> **Description:** `Span.set_attribute(key: str, value: object) -> None` must accept any Python object as `value` and return `None`.
>
> **Rationale:** Attribute values are application-defined and may be strings, numbers, booleans, or structured objects.
>
> **Acceptance Criteria:** Calls with `value` set to `str`, `int`, `float`, `bool`, `list`, and `dict` all succeed without raising. Return value is `None` in each case.

---

> **REQ-117** | Priority: MUST
>
> **Description:** `Span.end(status: str = "ok", error: Exception | None = None) -> None` must accept `status` values `"ok"` and `"error"`, and must store the provided `error` (if any) for inclusion in the resulting `SpanRecord`.
>
> **Rationale:** Downstream consumers rely on status and error fields to filter and triage failures.
>
> **Acceptance Criteria:** Calling `span.end(status="ok")` results in a `SpanRecord` with `status="ok"` and `error_message=None`. Calling `span.end(status="error", error=ValueError("boom"))` results in a `SpanRecord` with `status="error"` and `error_message="boom"`.

---

> **REQ-119** | Priority: MUST
>
> **Description:** `Span.__enter__` must return the `Span` instance itself.
>
> **Rationale:** The `with backend.span("name") as s:` pattern requires the context variable to be the span object.
>
> **Acceptance Criteria:** `with backend.span("x") as s: assert s is not None` passes. The object bound to `s` exposes `set_attribute` and `end`.

---

> **REQ-121** | Priority: MUST
>
> **Description:** `Span.__exit__` must call `self.end(status="error", error=exc_val)` when `exc_val` is not `None`, and `self.end(status="ok")` otherwise. It must return `False` in both cases.
>
> **Rationale:** Returning `False` ensures exceptions propagate normally to the caller.
>
> **Acceptance Criteria:** A `Span` used in a `with` block that raises `RuntimeError("test")` produces a `SpanRecord` with `status="error"` and `error_message="test"`, and the `RuntimeError` is re-raised. A `with` block that completes normally produces a `SpanRecord` with `status="ok"`.

---

> **REQ-123** | Priority: MUST
>
> **Description:** Any exception raised inside `Span.set_attribute` or `Span.end` by a backend implementation must be caught internally and must not propagate to the caller.
>
> **Rationale:** Observability must never crash the application it observes (fail-open principle).
>
> **Acceptance Criteria:** A synthetic backend whose `set_attribute` raises `RuntimeError` internally: calling `span.set_attribute("k", "v")` from application code does not raise.

---

### 3.3 Trace Contract

> **REQ-125** | Priority: MUST
>
> **Description:** `Trace` must be defined as an ABC in `src/platform/observability/backend.py` with abstract methods `span`, `generation`, `__enter__`, and `__exit__`.
>
> **Rationale:** A Trace groups related spans and generations under a single identifier.
>
> **Acceptance Criteria:** A concrete subclass of `Trace` that omits any one of `span`, `generation`, `__enter__`, or `__exit__` raises `TypeError` on instantiation.

---

> **REQ-127** | Priority: MUST
>
> **Description:** `Trace.span(name: str, attributes: dict | None = None) -> Span` must return a `Span` instance whose underlying `SpanRecord` carries the same `trace_id` as the parent `Trace`.
>
> **Rationale:** All child spans must be correlated to their trace for correct grouping in backend storage and dashboards.
>
> **Acceptance Criteria:** Given `t = backend.trace("t1")` and `s = t.span("s1")`, the `SpanRecord` emitted by `s` has a `trace_id` equal to the `trace_id` of the `TraceRecord` emitted by `t`.

---

> **REQ-129** | Priority: MUST
>
> **Description:** `Trace.generation(name: str, model: str, input: str, metadata: dict | None = None) -> Generation` must return a `Generation` instance whose underlying `GenerationRecord` carries the same `trace_id` as the parent `Trace`.
>
> **Rationale:** LLM calls within a trace must be correlated to that trace for cost attribution and debugging.
>
> **Acceptance Criteria:** Given `t = backend.trace("t1")` and `g = t.generation("g1", "gpt-4o", "prompt")`, the `GenerationRecord` emitted by `g` has a `trace_id` equal to the `trace_id` of `t`.

---

> **REQ-131** | Priority: MUST
>
> **Description:** `Trace.__enter__` must return the `Trace` instance itself.
>
> **Rationale:** Enables the `with backend.trace("name") as t:` pattern.
>
> **Acceptance Criteria:** `with backend.trace("x") as t:` binds `t` to an object that exposes `span` and `generation` methods.

---

> **REQ-133** | Priority: MUST
>
> **Description:** `Trace.__exit__` must return `False` regardless of whether an exception occurred.
>
> **Rationale:** Same fail-open, non-swallowing contract as `Span.__exit__`.
>
> **Acceptance Criteria:** A `with backend.trace("x"):` block that raises `ValueError` re-raises that `ValueError` after the block exits.

---

> **REQ-135** | Priority: MUST
>
> **Description:** Any exception raised inside `Trace.span` or `Trace.generation` by a backend implementation must be caught internally and must not propagate to the caller.
>
> **Rationale:** Fail-open principle: trace grouping errors must not crash application code.
>
> **Acceptance Criteria:** A synthetic backend whose `Trace.span` raises `RuntimeError` internally: calling `trace.span("s")` from application code returns an object (a fallback no-op span) and does not raise.

---

### 3.4 Generation Contract

> **REQ-137** | Priority: MUST
>
> **Description:** `Generation` must be defined as an ABC in `src/platform/observability/backend.py` with abstract methods `set_output`, `set_token_counts`, `end`, `__enter__`, and `__exit__`.
>
> **Rationale:** LLM call tracking requires distinct fields not present on generic spans.
>
> **Acceptance Criteria:** A concrete subclass of `Generation` that omits any one abstract method raises `TypeError` on instantiation.

---

> **REQ-139** | Priority: MUST
>
> **Description:** `Generation.set_output(output: str) -> None` must store the provided string so it is included in the resulting `GenerationRecord.output` field.
>
> **Rationale:** The LLM completion text is the primary payload of a generation record.
>
> **Acceptance Criteria:** After `gen.set_output("Paris")` and `gen.end()`, the emitted `GenerationRecord` has `output="Paris"`. Calling `set_output` more than once overwrites; only the last call is reflected.

---

> **REQ-141** | Priority: MUST
>
> **Description:** `Generation.set_token_counts(prompt_tokens: int, completion_tokens: int) -> None` must store both values in `GenerationRecord.prompt_tokens` and `GenerationRecord.completion_tokens`.
>
> **Rationale:** Token counts are required for per-call cost attribution and quota enforcement.
>
> **Acceptance Criteria:** After `gen.set_token_counts(100, 42)` and `gen.end()`, the emitted `GenerationRecord` has `prompt_tokens=100` and `completion_tokens=42`. Passing non-integer values raises `TypeError`.

---

> **REQ-143** | Priority: MUST
>
> **Description:** `Generation.end(status: str = "ok", error: Exception | None = None) -> None` must finalize the `GenerationRecord`, following the same contract as `Span.end`.
>
> **Rationale:** Consistent end-call semantics across Span and Generation simplifies backend implementations and caller expectations.
>
> **Acceptance Criteria:** Calling `gen.end(status="error", error=TimeoutError("deadline"))` produces a `GenerationRecord` with `status="error"` and `error_message` containing `"deadline"`.

---

> **REQ-145** | Priority: MUST
>
> **Description:** `Generation.__enter__` must return the `Generation` instance itself, and `Generation.__exit__` must return `False`.
>
> **Rationale:** Enables `with backend.generation(...) as g:` usage and ensures exceptions propagate.
>
> **Acceptance Criteria:** `with backend.generation("g", "gpt-4o", "p") as g:` binds `g` to an object exposing `set_output`, `set_token_counts`, and `end`. A `with` block that raises `RuntimeError` re-raises it after exit.

---

> **REQ-147** | Priority: MUST
>
> **Description:** Any exception raised inside `Generation.set_output`, `Generation.set_token_counts`, or `Generation.end` by a backend implementation must be caught internally and must not propagate to the caller.
>
> **Rationale:** Fail-open principle: a broken observability backend must never interrupt an LLM call in progress.
>
> **Acceptance Criteria:** A synthetic backend whose `Generation.end` raises `RuntimeError` internally: calling `gen.end()` from application code does not raise.

---

### 3.5 Schema Types

> **REQ-149** | Priority: MUST
>
> **Description:** `SpanRecord` must be defined as a dataclass in `src/platform/observability/schemas.py` with fields: `name: str`, `trace_id: str`, `parent_span_id: str | None`, `attributes: dict`, `start_ts: float`, `end_ts: float`, `status: str`, `error_message: str | None`.
>
> **Rationale:** A typed, serializable record schema decouples the in-memory ABC contract from the storage/export format.
>
> **Acceptance Criteria:** `SpanRecord(name="s", trace_id="t", parent_span_id=None, attributes={}, start_ts=0.0, end_ts=1.0, status="ok", error_message=None)` constructs without error. Omitting any required field raises `TypeError`.

---

> **REQ-151** | Priority: MUST
>
> **Description:** `TraceRecord` must be defined as a dataclass in `src/platform/observability/schemas.py` with fields: `name: str`, `trace_id: str`, `metadata: dict`, `start_ts: float`, `end_ts: float`, `status: str`.
>
> **Rationale:** Trace-level metadata must be captured in a typed record distinct from span-level attributes.
>
> **Acceptance Criteria:** `TraceRecord(name="t", trace_id="abc", metadata={}, start_ts=0.0, end_ts=2.0, status="ok")` constructs without error. `trace_id` is a `str`, not `None`.

---

> **REQ-153** | Priority: MUST
>
> **Description:** `GenerationRecord` must be defined as a dataclass in `src/platform/observability/schemas.py` with fields: `name: str`, `trace_id: str`, `model: str`, `input: str`, `output: str | None`, `prompt_tokens: int | None`, `completion_tokens: int | None`, `start_ts: float`, `end_ts: float`, `status: str`.
>
> **Rationale:** `output` and token counts are optional because `set_output` and `set_token_counts` may not be called before `end` in all usage patterns.
>
> **Acceptance Criteria:** `GenerationRecord` constructs with `output=None`, `prompt_tokens=None`, `completion_tokens=None`. Also constructs with all fields populated.

---

> **REQ-155** | Priority: MUST
>
> **Description:** `start_ts` and `end_ts` fields in all three record types must be populated using `time.time()` at object creation (`start_ts`) and when `end()` is called (`end_ts`).
>
> **Rationale:** A consistent timestamp source enables correct duration calculations and cross-record ordering.
>
> **Acceptance Criteria:** For any record produced by a backend, `end_ts >= start_ts`. `end_ts` is set at the time `end()` is called, not at record construction time.

---

> **REQ-157** | Priority: SHOULD
>
> **Description:** All three schema dataclasses must be importable directly from `src/platform/observability/schemas.py` without importing from any backend implementation module.
>
> **Rationale:** Schema types are used by storage adapters and tests that should not take a dependency on backend implementation details.
>
> **Acceptance Criteria:** `from platform.observability.schemas import SpanRecord, TraceRecord, GenerationRecord` succeeds in a Python environment where no Langfuse dependency is installed.

---

### 3.6 NoopBackend

> **REQ-159** | Priority: MUST
>
> **Description:** `NoopBackend` must be defined in `src/platform/observability/noop/backend.py` and must be a concrete subclass of `ObservabilityBackend`.
>
> **Rationale:** `NoopBackend` is the default backend when no observability provider is configured.
>
> **Acceptance Criteria:** `isinstance(NoopBackend(), ObservabilityBackend)` is `True`. `NoopBackend()` constructs without raising.

---

> **REQ-161** | Priority: MUST
>
> **Description:** `NoopBackend.span`, `NoopBackend.trace`, and `NoopBackend.generation` must each return a dedicated no-op object (`NoopSpan`, `NoopTrace`, `NoopGeneration` respectively) satisfying the corresponding ABC `isinstance` check, without performing any I/O.
>
> **Rationale:** The noop backend must impose zero overhead.
>
> **Acceptance Criteria:** `isinstance(NoopBackend().span("x"), Span)` is `True`. `isinstance(NoopBackend().trace("x"), Trace)` is `True`. `isinstance(NoopBackend().generation("g", "m", "i"), Generation)` is `True`. None of these calls open a file, socket, or database connection.

---

> **REQ-163** | Priority: MUST
>
> **Description:** `NoopBackend.flush()` and `NoopBackend.shutdown()` must return `None` immediately without performing any I/O or blocking.
>
> **Rationale:** Tests and shutdown sequences calling `flush()` on a noop backend must complete instantly.
>
> **Acceptance Criteria:** Both calls return `None`. Execution time for each call is under 1ms.

---

> **REQ-165** | Priority: MUST
>
> **Description:** All methods on `NoopSpan`, `NoopTrace`, and `NoopGeneration` must return the correct type per the ABC contract and must not raise under any input.
>
> **Rationale:** No-op objects must be fully safe to use without guards, including with `None`, empty strings, and unexpected types as arguments.
>
> **Acceptance Criteria:** `NoopSpan().set_attribute(None, None)` does not raise. `NoopGeneration().set_token_counts(-1, -1)` does not raise. `NoopTrace().span(None)` does not raise and returns an instance of `Span`.

---

### 3.7 Config-Driven Selection

> **REQ-167** | Priority: MUST
>
> **Description:** The active `ObservabilityBackend` instance must be selected at application startup based on the `OBSERVABILITY_PROVIDER` environment variable. Valid values are `"noop"` and `"langfuse"`. Any other value must cause a startup error identifying the unrecognized value.
>
> **Rationale:** Explicit configuration-driven selection prevents silent fallback to the wrong backend.
>
> **Acceptance Criteria:** Setting `OBSERVABILITY_PROVIDER="noop"` results in a `NoopBackend`. Setting `"langfuse"` results in a `LangfuseBackend`. Setting `"datadog"` raises a `ValueError` containing `"datadog"` before any request is processed.

---

> **REQ-169** | Priority: MUST
>
> **Description:** The active `ObservabilityBackend` instance must be a singleton within a single process. All calls to the backend accessor within the same process lifetime must return the same object.
>
> **Rationale:** Multiple backend instances would result in duplicate observations and split flush queues.
>
> **Acceptance Criteria:** Calling `get_tracer()` twice returns objects where `call_1 is call_2` evaluates to `True`.

---

> **REQ-171** | Priority: MUST
>
> **Description:** If the configured backend fails to initialize, the system must catch the initialization error, log a warning containing the backend name and the exception message, and fall back to `NoopBackend`.
>
> **Rationale:** Fail-open principle applied to backend initialization.
>
> **Acceptance Criteria:** Given a `LangfuseBackend` whose `__init__` raises `RuntimeError("no api key")`: the application starts successfully, `get_tracer()` returns a `NoopBackend` instance, and a warning log entry contains both `"langfuse"` and `"no api key"`.

---

## 4. Langfuse Backend

### 4.1 Provider Isolation

> **REQ-201** | Priority: MUST
>
> **Description:** All imports from the `langfuse` package must appear exclusively in `src/platform/observability/langfuse/backend.py` and nowhere else in the codebase.
>
> **Rationale:** Confining SDK imports to a single file ensures the rest of the system remains free of provider-specific dependencies.
>
> **Acceptance Criteria:** A static import scan of all files under `src/platform/observability/` excluding `langfuse/backend.py` finds zero occurrences of `from langfuse` or `import langfuse`. The same scan applied to all consumer files also finds zero occurrences.

---

> **REQ-203** | Priority: MUST
>
> **Description:** `src/platform/observability/langfuse/__init__.py` must export exactly one public symbol: `LangfuseBackend`. It must NOT import or re-export `LangfuseSpan`, `LangfuseTrace`, `LangfuseGeneration`, or any Langfuse SDK symbol.
>
> **Rationale:** A minimal `__init__.py` surface prevents consumers from accidentally coupling to internal wrapper types.
>
> **Acceptance Criteria:** `from observability.langfuse import LangfuseBackend` succeeds. `from observability.langfuse import LangfuseSpan` raises `ImportError`.

---

### 4.2 LangfuseBackend Class

> **REQ-205** | Priority: MUST
>
> **Description:** `LangfuseBackend` must be a concrete subclass of `ObservabilityBackend` and must implement every abstract method declared by that ABC.
>
> **Rationale:** ABC compliance enforces the substitutability contract.
>
> **Acceptance Criteria:** `issubclass(LangfuseBackend, ObservabilityBackend)` returns `True`. `inspect.isabstract(LangfuseBackend)` returns `False`.

---

> **REQ-207** | Priority: MUST
>
> **Description:** `LangfuseBackend.__init__` must call `get_client()` exactly once and store the returned singleton. It must NOT catch exceptions raised by `get_client()`; those exceptions must propagate to the caller.
>
> **Rationale:** The factory layer is responsible for catching construction failures and falling back to the noop backend.
>
> **Acceptance Criteria:** When `get_client()` raises (via monkeypatching), `LangfuseBackend()` raises the same exception and does not return an instance.

---

> **REQ-209** | Priority: MUST
>
> **Description:** The observability factory must instantiate `LangfuseBackend` inside a `try/except` block and fall back to `NoopBackend` if any exception is raised during construction.
>
> **Rationale:** A misconfigured or unavailable Langfuse server must not prevent the application from starting.
>
> **Acceptance Criteria:** Given a monkeypatched `get_client()` that raises `Exception`, the factory returns a noop backend instance rather than raising.

---

> **REQ-211** | Priority: MUST
>
> **Description:** `LangfuseBackend.span(name, attributes, parent)` must return a `LangfuseSpan`. When `parent` is `None`, it must call `client.start_observation(as_type="span", ...)`. When `parent` is a `LangfuseTrace`, it must delegate to `trace_obj.span(...)`.
>
> **Rationale:** Correct parent-child linkage in Langfuse requires routing span creation through the trace object when a trace parent exists.
>
> **Acceptance Criteria:** Calling `backend.span("s", {}, parent=None)` invokes `client.start_observation` with `as_type="span"`. Calling `backend.span("s", {}, parent=trace_instance)` invokes `trace_obj.span(...)` instead.

---

> **REQ-213** | Priority: MUST
>
> **Description:** `LangfuseBackend.trace(name, metadata)` must call `client.trace(name=name, metadata=metadata)` and return a `LangfuseTrace` wrapping the result.
>
> **Rationale:** Exposing a `trace()` method allows callers to open a Langfuse trace root.
>
> **Acceptance Criteria:** Calling `backend.trace("t", {"k": "v"})` invokes `client.trace` with the correct keyword arguments. The return value is a `LangfuseTrace` instance.

---

> **REQ-215** | Priority: MUST
>
> **Description:** `LangfuseBackend.generation(name, model, input, metadata)` must call `client.start_observation(as_type="generation", ...)` and return a `LangfuseGeneration`.
>
> **Rationale:** Generations are a distinct Langfuse observation type that carries LLM-specific fields.
>
> **Acceptance Criteria:** Calling `backend.generation("g", "gpt-4", "prompt", {})` invokes `start_observation` with `as_type="generation"`. The return value is a `LangfuseGeneration` instance.

---

### 4.3 LangfuseSpan

> **REQ-217** | Priority: MUST
>
> **Description:** `LangfuseSpan.set_attribute(key, value)` must call `inner.update(metadata={key: value})` on the wrapped observation object.
>
> **Rationale:** Attribute updates must be forwarded to the Langfuse SDK so they appear in the trace UI.
>
> **Acceptance Criteria:** Calling `span.set_attribute("env", "prod")` results in exactly one call to `inner.update` with `metadata={"env": "prod"}`.

---

> **REQ-219** | Priority: MUST
>
> **Description:** `LangfuseSpan.set_attribute` must catch all exceptions raised by `inner.update` and log a warning. It must NOT re-raise.
>
> **Rationale:** Fail-open: a faulty Langfuse connection must not cause a downstream exception in business logic.
>
> **Acceptance Criteria:** When `inner.update` raises `RuntimeError`, calling `set_attribute` returns without raising and a warning is logged.

---

> **REQ-221** | Priority: MUST
>
> **Description:** `LangfuseSpan.end(status, error)` must call `inner.update(level="ERROR", status_message=str(error))` before calling `inner.end()` when `error` is not `None`. When `error` is `None`, it must call `inner.end()` without a preceding level update.
>
> **Rationale:** Setting the error level before ending ensures the trace UI correctly marks the span as failed.
>
> **Acceptance Criteria:** Calling `span.end(status="error", error=ValueError("oops"))` results in `inner.update(level="ERROR", status_message="oops")` called before `inner.end()`.

---

> **REQ-223** | Priority: MUST
>
> **Description:** `LangfuseSpan.end` must catch all exceptions raised by `inner.update` or `inner.end` and log a warning. It must NOT re-raise.
>
> **Rationale:** A span that cannot be closed must not propagate an exception into the calling code.
>
> **Acceptance Criteria:** When `inner.end` raises `ConnectionError`, calling `span.end(...)` returns without raising and a warning is logged.

---

> **REQ-225** | Priority: MUST
>
> **Description:** `LangfuseSpan` must implement the context manager protocol. `__enter__` must return `self`. `__exit__` must call `self.end(...)` and return `False`.
>
> **Rationale:** Returning `False` from `__exit__` ensures exceptions raised inside a `with` block are not suppressed.
>
> **Acceptance Criteria:** `with LangfuseSpan(...) as s:` binds `s` to the span instance. An exception inside the block propagates out after `end` is called.

---

### 4.4 LangfuseTrace

> **REQ-227** | Priority: MUST
>
> **Description:** `LangfuseTrace.span(name, attributes)` must call `trace_obj.span(name=name, metadata=attributes or {})` and return a `LangfuseSpan` wrapping the result.
>
> **Rationale:** Child spans must be created through the trace object to ensure Langfuse associates them with the correct trace root.
>
> **Acceptance Criteria:** Calling `trace.span("child", None)` passes `metadata={}` rather than `None`. The return value is a `LangfuseSpan` instance.

---

> **REQ-229** | Priority: MUST
>
> **Description:** `LangfuseTrace.generation(name, model, input, metadata)` must call `trace_obj.generation(...)` and return a `LangfuseGeneration`.
>
> **Rationale:** LLM calls under a trace must be recorded as generation observations for Langfuse cost analytics.
>
> **Acceptance Criteria:** The return value is a `LangfuseGeneration` instance. Arguments are forwarded correctly per mock assertion.

---

> **REQ-231** | Priority: MUST
>
> **Description:** Every method on `LangfuseTrace` must catch all exceptions and log a warning rather than propagating to the caller.
>
> **Rationale:** A trace object that encounters an SDK error must not interrupt pipeline execution.
>
> **Acceptance Criteria:** When `trace_obj.span` raises `Exception`, calling `trace.span(...)` does not raise and a warning is logged.

---

> **REQ-233** | Priority: MUST
>
> **Description:** `LangfuseTrace` must implement the context manager protocol. `__enter__` must return `self`. `__exit__` must return `False`.
>
> **Rationale:** Traces used as context managers must not suppress caller exceptions.
>
> **Acceptance Criteria:** An exception raised inside `with LangfuseTrace(...) as t:` propagates out unmodified.

---

### 4.5 LangfuseGeneration

> **REQ-235** | Priority: MUST
>
> **Description:** `LangfuseGeneration.set_output(output)` must call `inner.update(output=output)` on the wrapped observation.
>
> **Rationale:** LLM output must be recorded to enable Langfuse's input/output diff view and output-level evals.
>
> **Acceptance Criteria:** Calling `gen.set_output("response text")` results in exactly one call to `inner.update` with `output="response text"`.

---

> **REQ-237** | Priority: MUST
>
> **Description:** `LangfuseGeneration.set_token_counts(prompt_tokens, completion_tokens)` must call `inner.update(usage={"input": prompt_tokens, "output": completion_tokens})`.
>
> **Rationale:** The Langfuse SDK expects token counts under the `usage` key using `input` and `output` sub-keys.
>
> **Acceptance Criteria:** Calling `gen.set_token_counts(100, 50)` invokes `inner.update` with exactly `usage={"input": 100, "output": 50}`.

---

> **REQ-239** | Priority: MUST
>
> **Description:** `LangfuseGeneration.end(status, error)` must follow the same error-level update logic as `LangfuseSpan.end`.
>
> **Rationale:** Consistent error-marking behavior across all observation wrapper types ensures uniform trace UI rendering.
>
> **Acceptance Criteria:** Calling `gen.end(status="error", error=RuntimeError("fail"))` results in `inner.update(level="ERROR", status_message="fail")` called before `inner.end()`.

---

> **REQ-241** | Priority: MUST
>
> **Description:** Every method on `LangfuseGeneration` must catch all exceptions and log a warning rather than propagating to the caller.
>
> **Rationale:** Token count recording and output capture must never disrupt the LLM call.
>
> **Acceptance Criteria:** When `inner.update` raises for `set_output`, the call returns without raising and a warning is logged.

---

> **REQ-243** | Priority: MUST
>
> **Description:** `LangfuseGeneration` must implement the context manager protocol. `__enter__` must return `self`. `__exit__` must call `self.end(...)` and return `False`.
>
> **Rationale:** Consistent context manager semantics across all three wrapper types.
>
> **Acceptance Criteria:** An exception raised inside `with LangfuseGeneration(...) as g:` propagates out after `end` is called.

---

### 4.6 Connection and Configuration

> **REQ-245** | Priority: MUST
>
> **Description:** `LangfuseBackend` must NOT hardcode or default any value for `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, or `LANGFUSE_SECRET_KEY`. All three values must be read from environment variables by the Langfuse SDK when `get_client()` is called.
>
> **Rationale:** Hardcoded credentials create security vulnerabilities and prevent per-environment configuration.
>
> **Acceptance Criteria:** A static search of `langfuse/backend.py` finds no hardcoded URL, public key, or secret key literals.

---

> **REQ-247** | Priority: MUST
>
> **Description:** The `LangfuseBackend` constructor must NOT accept `host`, `public_key`, or `secret_key` as constructor parameters.
>
> **Rationale:** Accepting credentials as constructor arguments creates an alternative configuration path that bypasses environment-variable discipline.
>
> **Acceptance Criteria:** `inspect.signature(LangfuseBackend.__init__)` contains no parameters named `host`, `public_key`, or `secret_key`. Calling `LangfuseBackend(host="x")` raises `TypeError`.

---

### 4.7 Flush and Shutdown

> **REQ-249** | Priority: MUST
>
> **Description:** `LangfuseBackend.flush()` must call `self._client.flush()` synchronously and must propagate any exception raised by `client.flush()` to the caller.
>
> **Rationale:** `flush()` is called at shutdown checkpoints; callers must know whether buffered observations were successfully delivered.
>
> **Acceptance Criteria:** Calling `backend.flush()` invokes `client.flush()` exactly once. When `client.flush()` raises `TimeoutError`, `backend.flush()` re-raises the same `TimeoutError`.

---

> **REQ-251** | Priority: MUST
>
> **Description:** `LangfuseBackend.shutdown()` must call `self._client.shutdown()` and must propagate any exception raised by `client.shutdown()` to the caller.
>
> **Rationale:** Shutdown is a terminal lifecycle operation; errors must be surfaced.
>
> **Acceptance Criteria:** Calling `backend.shutdown()` invokes `client.shutdown()` exactly once. When `client.shutdown()` raises, the exception propagates unchanged.

---

## 5. Public API & Decorators

### 5.1 Import Surface Contract

> **REQ-301** | Priority: MUST
>
> **Description:** All public symbols of the observability subsystem must be importable from `src.platform.observability` directly. No consumer code shall import from any sub-module path as part of normal usage.
>
> **Rationale:** A stable, single-path import surface decouples consumers from internal module layout.
>
> **Acceptance Criteria:** A test imports each of `get_tracer`, `observe`, `Tracer`, `Span`, `Trace`, and `Generation` from `src.platform.observability` and all six imports succeed without error.

---

> **REQ-303** | Priority: MUST
>
> **Description:** All symbols not listed in `__all__` must be treated as internal. No guarantee of stability is provided for symbols imported from sub-module paths outside of the explicit backward-compatibility alias defined in REQ-331.
>
> **Rationale:** Explicitly marking the boundary between public and internal prevents accidental coupling to unstable internals.
>
> **Acceptance Criteria:** A static analysis check confirms that no symbol outside `__all__` is re-exported at the package level, and internal sub-modules are not transitively exposed through `__init__.py`.

---

### 5.2 `get_tracer()` Function

> **REQ-305** | Priority: MUST
>
> **Description:** `get_tracer()` must return the process-wide `ObservabilityBackend` singleton. Every call within a single process must return the same object instance.
>
> **Rationale:** A singleton backend ensures all instrumented callables route spans to one consistent destination.
>
> **Acceptance Criteria:** A test calls `get_tracer()` twice and asserts `result_a is result_b` evaluates to `True`.

---

> **REQ-307** | Priority: MUST
>
> **Description:** `get_tracer()` must declare its return type as `ObservabilityBackend`. It must NOT expose the concrete backend class through its return annotation.
>
> **Rationale:** Callers must program to the abstraction, not the implementation.
>
> **Acceptance Criteria:** Inspection of the function's `__annotations__` confirms the return type is `ObservabilityBackend`.

---

> **REQ-309** | Priority: MUST
>
> **Description:** `get_tracer()` must be importable and callable in a Python environment where the `langfuse` package is not installed. When `langfuse` is absent, `get_tracer()` must return the noop backend without raising `ImportError`.
>
> **Rationale:** Optional observability must not be a hard dependency.
>
> **Acceptance Criteria:** In a virtual environment with `langfuse` uninstalled, calling `get_tracer()` returns an `ObservabilityBackend` instance without exception.

---

> **REQ-311** | Priority: MUST
>
> **Description:** `get_tracer()` must be safe to call concurrently from multiple threads. The singleton initialization must NOT produce two distinct backend instances when two threads call `get_tracer()` simultaneously for the first time.
>
> **Rationale:** Application servers and async workers initialize concurrently.
>
> **Acceptance Criteria:** A test launches 50 threads that each call `get_tracer()` simultaneously and asserts that all 50 returned objects are the same instance (`len({id(r) for r in results}) == 1`).

---

### 5.3 `@observe` Decorator

> **REQ-313** | Priority: MUST
>
> **Description:** `observe` must be a decorator factory with the signature `observe(name: str | None = None, capture_input: bool = False, capture_output: bool = False)`. It must be applicable to plain functions, instance methods, and class methods.
>
> **Rationale:** A uniform decorator removes the need for per-callsite boilerplate and ensures consistent span creation.
>
> **Acceptance Criteria:** A test applies `@observe()` to a plain function, an instance method, and a `@classmethod`. All three calls complete without error and produce one span each.

---

> **REQ-315** | Priority: MUST
>
> **Description:** `observe` must use `functools.wraps` on the inner wrapper function. The decorated callable's `__name__`, `__qualname__`, and `__doc__` must equal those of the original function.
>
> **Rationale:** Preserving callable metadata is required for introspection, logging, and test discovery.
>
> **Acceptance Criteria:** After applying `@observe("x")` to function `foo` with docstring `"doc"`, assert `foo.__name__ == "foo"`, `foo.__qualname__` ends with `"foo"`, and `foo.__doc__ == "doc"`.

---

> **REQ-317** | Priority: MUST
>
> **Description:** When `name` is not provided to `observe`, the span name must default to the decorated function's `__qualname__`.
>
> **Rationale:** Automatic naming from `__qualname__` produces meaningful span identifiers without requiring the caller to supply a name.
>
> **Acceptance Criteria:** `@observe()` applied to `Bar.baz` produces a span with `name == "Bar.baz"`.

---

> **REQ-319** | Priority: MUST
>
> **Description:** `capture_input` must default to `False`. When `capture_input=False`, the decorator must NOT attach any input-derived attribute to the span.
>
> **Rationale:** Input capture is off by default to prevent accidental logging of PII.
>
> **Acceptance Criteria:** A span produced by a function decorated with default settings has no attribute keyed `"input"`.

---

> **REQ-321** | Priority: MUST
>
> **Description:** `capture_output` must default to `False`. When `capture_output=False`, the decorator must NOT attach any output-derived attribute to the span.
>
> **Rationale:** Output capture is off by default for the same PII risk reason as input capture.
>
> **Acceptance Criteria:** A span produced by a function decorated with default settings has no attribute keyed `"output"`.

---

> **REQ-323** | Priority: MUST
>
> **Description:** When `capture_input=True`, the decorator must set a span attribute `"input"` whose value is `repr()` of the positional arguments excluding the first positional argument, truncated to 500 characters.
>
> **Rationale:** Skipping the first positional argument avoids capturing `self` or `cls` objects.
>
> **Acceptance Criteria:** The span's `"input"` attribute equals `repr(args[1:])[:500]` and has length at most 500.

---

> **REQ-325** | Priority: MUST
>
> **Description:** When `capture_output=True`, the decorator must set a span attribute `"output"` whose value is `repr()` of the return value, truncated to 500 characters.
>
> **Rationale:** Truncation prevents unbounded span payloads from overwhelming the observability backend.
>
> **Acceptance Criteria:** The span's `"output"` attribute equals `repr(return_value)[:500]` and has length at most 500.

---

> **REQ-327** | Priority: MUST
>
> **Description:** When the decorated function raises an exception, the decorator must set a span attribute `"error"` to `str(exception)` and then re-raise the original exception unchanged.
>
> **Rationale:** Callers depend on exception propagation for control flow. Span recording must be a side effect only.
>
> **Acceptance Criteria:** `@observe()` applied to a function that raises `ValueError("boom")`: the `ValueError` propagates and the span has attribute `"error" == "boom"`.

---

> **REQ-329** | Priority: MUST
>
> **Description:** When the active backend is the noop backend, `@observe` must add no measurable overhead. Specifically, it must NOT perform serialization, I/O, or memory allocation beyond the span context manager's own noop implementation.
>
> **Rationale:** Instrumentation in hot paths must be zero-cost when observability is disabled.
>
> **Acceptance Criteria:** p99 overhead of `@observe` with `NoopBackend` does not exceed 1ms over 1,000 calls compared to the undecorated baseline.

---

### 5.4 Backward Compatibility Aliases

> **REQ-331** | Priority: MUST
>
> **Description:** The import path `from src.platform.observability.providers import get_tracer` must continue to resolve to the same function as `from src.platform.observability import get_tracer` during the migration period.
>
> **Rationale:** Existing consumers reference the internal `providers` path and cannot all be migrated atomically.
>
> **Acceptance Criteria:** A test imports `get_tracer` from both paths and asserts both names resolve to the same callable object.

---

> **REQ-333** | Priority: MUST
>
> **Description:** `src.platform.observability` must export `Tracer` as an alias for `ObservabilityBackend`. Code referencing `Tracer` as a type annotation or `isinstance` target must continue to function.
>
> **Rationale:** `Tracer` was the original name in `contracts.py`. External references must not break.
>
> **Acceptance Criteria:** A test imports `Tracer` from `src.platform.observability` and asserts `Tracer is ObservabilityBackend` evaluates to `True`.

---

> **REQ-335** | Priority: SHOULD
>
> **Description:** The `providers.py` compatibility shim should emit a `DeprecationWarning` when `get_tracer` is imported from `src.platform.observability.providers`.
>
> **Rationale:** A deprecation warning gives teams a visible signal to migrate their imports.
>
> **Acceptance Criteria:** Importing `get_tracer` from `src.platform.observability.providers` inside `warnings.catch_warnings(record=True)` records exactly one `DeprecationWarning` referencing the old import path.

---

> **REQ-337** | Priority: SHOULD
>
> **Description:** The `Tracer` alias should emit a `DeprecationWarning` when accessed, informing callers to use `ObservabilityBackend` instead.
>
> **Rationale:** Aliased names signal intent to converge on a single canonical name.
>
> **Acceptance Criteria:** Accessing `Tracer` from `src.platform.observability` inside `warnings.catch_warnings(record=True)` records a `DeprecationWarning` referencing `ObservabilityBackend`.

---

### 5.5 Module `__all__` and Re-exports

> **REQ-339** | Priority: MUST
>
> **Description:** `src/platform/observability/__init__.py` must define `__all__` as exactly `["get_tracer", "observe", "Tracer", "Span", "Trace", "Generation"]`.
>
> **Rationale:** An explicit `__all__` is the authoritative declaration of the public API surface.
>
> **Acceptance Criteria:** `observability.__all__ == ["get_tracer", "observe", "Tracer", "Span", "Trace", "Generation"]` with exactly that ordering.

---

> **REQ-341** | Priority: MUST
>
> **Description:** `Span`, `Trace`, and `Generation` must be re-exported from `src.platform.observability.__init__` by importing them from `backend.py`. They must NOT be defined directly in `__init__.py`.
>
> **Rationale:** Type definitions belong in the module that owns the abstraction. Re-exporting provides the stable import path without duplicating the definition.
>
> **Acceptance Criteria:** For each of `Span`, `Trace`, `Generation` imported from `src.platform.observability`, the symbol's `__module__` attribute resolves to `src.platform.observability.backend`.

---

## 6. Consumer Integration

### 6.1 Import Path Requirements

> **REQ-401** | Priority: MUST
>
> **Description:** All consumer modules that use observability instrumentation must import from the public package root `src.platform.observability` and not from any submodule path beneath it.
>
> **Rationale:** Submodule paths are internal implementation details that change when the backend provider is swapped.
>
> **Acceptance Criteria:** A grep for `from src.platform.observability.` (trailing dot) across all non-observability source files returns zero matches after migration is complete.

---

> **REQ-403** | Priority: MUST
>
> **Description:** The public package root must export `get_tracer` and `observe` as top-level names so that both resolve without error.
>
> **Rationale:** Consumers depend on a stable, minimal symbol set at the package root.
>
> **Acceptance Criteria:** `python -c "from src.platform.observability import get_tracer, observe"` exits with code 0.

---

> **REQ-405** | Priority: MUST
>
> **Description:** No consumer module may contain a direct import from `langfuse`, `opentelemetry`, or any other third-party observability library.
>
> **Rationale:** Direct third-party imports in consumer code create hard provider coupling.
>
> **Acceptance Criteria:** A grep for `import langfuse` and `import opentelemetry` across all files outside `src/platform/observability/` returns zero matches.

---

### 6.2 Decorator Usage Pattern

> **REQ-407** | Priority: SHOULD
>
> **Description:** When a function or method requires tracing of its full execution duration and does not need to attach dynamic span attributes computed from the return value, it should be instrumented using `@observe("span.name")` rather than a manual context manager.
>
> **Rationale:** The decorator pattern reduces boilerplate and eliminates the try/finally span-end pattern.
>
> **Acceptance Criteria:** At least one function in each of the eight enumerated consumer files uses `@observe` rather than a manual span.

---

> **REQ-409** | Priority: MUST
>
> **Description:** The `@observe` decorator must automatically end the span with status `"ok"` when the decorated function returns normally, and with status `"error"` when it raises an exception, without requiring any try/finally block in the consumer code.
>
> **Rationale:** Forcing consumers to manage span lifecycle in try/finally blocks is the primary source of instrumentation bugs in the current codebase.
>
> **Acceptance Criteria:** Given a function decorated with `@observe("test.op")`, when that function raises an unhandled exception, the backend records a span named `"test.op"` with status `"error"` and the exception propagates to the caller unchanged.

---

> **REQ-411** | Priority: MUST
>
> **Description:** The `@observe` decorator must accept a single positional string argument that becomes the span name, and must NOT require any other mandatory arguments.
>
> **Rationale:** Mandatory arguments beyond the span name add friction.
>
> **Acceptance Criteria:** Applying `@observe("some.name")` to a zero-argument function and calling it raises no `TypeError` related to decorator arguments.

---

### 6.3 Context Manager Usage Pattern

> **REQ-413** | Priority: MUST
>
> **Description:** `get_tracer().span(name, attributes)` must be usable as a context manager, and the span must be ended automatically when the `with` block exits regardless of exit mode.
>
> **Rationale:** The context manager pattern is required for cases where span attributes depend on values computed inside the span's body.
>
> **Acceptance Criteria:** A span created via the `with` form is recorded as ended in the backend after the `with` block exits, both in the normal-exit and exception-exit cases, without any explicit `span.end()` call.

---

> **REQ-415** | Priority: MUST
>
> **Description:** Within a `with get_tracer().span(...) as span:` block, the consumer must be able to call `span.set_attribute(key, value)` to attach attributes discovered during execution, and those attributes must appear on the recorded span.
>
> **Rationale:** Dynamic attributes are only available after computation begins and cannot be passed at span creation time.
>
> **Acceptance Criteria:** A span created with `{"input_count": 3}` then updated via `span.set_attribute("output_count", 1)` is recorded with both attributes present.

---

> **REQ-417** | Priority: MUST
>
> **Description:** `get_tracer().trace(name, attributes)` must be usable as a context manager that groups multiple child spans and generations under one logical trace root.
>
> **Rationale:** Pipeline-level operations span multiple retrieval and generation steps that logically belong to one user-visible trace entry.
>
> **Acceptance Criteria:** When a consumer opens a `with get_tracer().trace("rag.request") as trace:` block and creates two child spans via `trace.span(...)`, the backend records all three entries linked under the same trace identifier.

---

> **REQ-419** | Priority: SHOULD
>
> **Description:** A `trace` context manager object should expose a `generation(name, model, input)` method that creates a child entry typed as a generation event, distinct from a plain span.
>
> **Rationale:** Observability backends treat LLM generation events as first-class objects with model name, input prompt, and output fields.
>
> **Acceptance Criteria:** Calling `trace.generation("generator", model="gpt-4o", input="hello")` followed by `.set_output("world")` and `.end()` results in a backend entry tagged as generation type carrying all three fields.

---

### 6.4 Attribute Key Conventions

> **REQ-421** | Priority: MUST
>
> **Description:** All attribute keys passed by consumers must use snake_case strings composed only of lowercase letters, digits, and underscores.
>
> **Rationale:** A consistent key format prevents duplicate keys under different conventions and ensures attributes are interpretable by any backend.
>
> **Acceptance Criteria:** A linter rule or test asserts no attribute key in any consumer call site contains uppercase letters, hyphens, or dots.

---

> **REQ-423** | Priority: MUST
>
> **Description:** Consumer attribute keys must NOT include any provider-specific prefix or suffix, including `langfuse_`, `otel_`, `dd_`, or `nr_`.
>
> **Rationale:** Provider-specific keys leak the backend identity into consumer code.
>
> **Acceptance Criteria:** A grep for attribute key strings matching those prefixes across all non-observability source files returns zero matches.

---

> **REQ-425** | Priority: SHOULD
>
> **Description:** Consumer code should use canonical attribute key constants from a shared keys module (or exported from `src.platform.observability`) rather than raw string literals for keys that appear in more than one consumer file.
>
> **Rationale:** Repeated raw string literals for the same semantic concept diverge over time.
>
> **Acceptance Criteria:** Any attribute key string appearing in two or more of the eight consumer files is represented as a constant and all consumer sites reference that constant.

---

> **REQ-427** | Priority: MUST
>
> **Description:** Attribute values passed by consumers must be one of: `str`, `int`, `float`, or `bool`. Consumers must NOT pass `None`, complex objects, lists, or dicts as attribute values.
>
> **Rationale:** Non-scalar attribute values have undefined serialization behavior across backends.
>
> **Acceptance Criteria:** The observability public API raises `TypeError` or silently coerces when a consumer passes a non-scalar attribute value, and this behavior is documented and covered by a test.

---

### 6.5 Migration from Old Pattern

> **REQ-429** | Priority: MUST
>
> **Description:** All eight consumer files must change their observability import from `from src.platform.observability.providers import get_tracer` to `from src.platform.observability import get_tracer` (or `observe`).
>
> **Rationale:** The `.providers` submodule is an internal path that will not remain stable.
>
> **Acceptance Criteria:** After migration, `grep -r "from src.platform.observability.providers"` across the entire repository returns zero matches.

---

> **REQ-431** | Priority: MUST
>
> **Description:** All consumer call sites that currently call `tracer.start_span(name, attributes)` must be migrated to either `get_tracer().span(name, attributes)` as a context manager or `@observe(name)` as a decorator.
>
> **Rationale:** `start_span` is the old method name bound to the internal provider interface.
>
> **Acceptance Criteria:** A grep for `.start_span(` across all non-observability source files returns zero matches after migration.

---

> **REQ-433** | Priority: SHOULD
>
> **Description:** During the migration period, the observability backend ABC should expose `start_span(name, attributes, parent)` as an alias that forwards to `span(name, attributes, parent)`.
>
> **Rationale:** The eight consumer files cannot all be migrated atomically. The alias prevents a partial migration from breaking the running system.
>
> **Acceptance Criteria:** Calling `get_tracer().start_span("test", {})` on the active backend produces a valid span object and does not raise `AttributeError`.

---

> **REQ-435** | Priority: MUST
>
> **Description:** All consumer files that used a module-level lazy-initialized `_tracer_instance` variable must remove that pattern and call `get_tracer()` at the point of use or assign it once in `__init__` via `self.tracer = get_tracer()`.
>
> **Rationale:** Module-level lazy init with a global variable creates hidden mutable state that complicates backend swaps and test isolation.
>
> **Acceptance Criteria:** A grep for `_tracer_instance` across all non-observability source files returns zero matches after migration.

---

### 6.6 Prohibited Patterns

> **REQ-437** | Priority: MUST
>
> **Description:** Consumer code must NOT call `span.end()` explicitly when the span was acquired via a `with` context manager. The context manager protocol owns the span lifecycle.
>
> **Rationale:** An explicit `span.end()` inside a `with` block will double-end the span, producing malformed traces.
>
> **Acceptance Criteria:** A test that enters a `with get_tracer().span(...)` block, calls `span.end()` explicitly, and then exits the block results in exactly one `end` event recorded, not two.

---

> **REQ-439** | Priority: MUST
>
> **Description:** Consumer code must NOT catch exceptions from within a `with span:` or `@observe` block solely to record an error status and then re-raise, as the decorator and context manager both handle error status automatically.
>
> **Rationale:** The current codebase has explicit `except` clauses that set `_span_status = "error"` before re-raising. This pattern becomes incorrect after migration.
>
> **Acceptance Criteria:** After migration, no consumer file contains a bare `except` block whose sole purpose is to set a span status variable followed by a `raise`, as verified by static analysis.

---

> **REQ-441** | Priority: MUST
>
> **Description:** Consumer code must NOT import, instantiate, or reference any concrete backend class (`LangfuseBackend`, `NoopBackend`) by name.
>
> **Rationale:** Direct reference to concrete backend classes re-creates provider coupling.
>
> **Acceptance Criteria:** A grep for `LangfuseBackend` and `NoopBackend` across all files outside `src/platform/observability/` returns zero matches.

---

## 7. Infrastructure

### 7.1 Langfuse Docker Service

> **REQ-501** | Priority: MUST
>
> **Description:** The `docker-compose.yml` file must define a service named `langfuse` using the image `langfuse/langfuse:3`.
>
> **Rationale:** A versioned image pinned to the v3 major line ensures reproducible deployments and aligns with the Langfuse v3 API surface.
>
> **Acceptance Criteria:** Running `docker compose config` produces a service entry with `image: langfuse/langfuse:3` and service key `langfuse`.

---

> **REQ-503** | Priority: MUST
>
> **Description:** The `langfuse` service must expose container port 3000 to host port `${LANGFUSE_PORT:-3000}`.
>
> **Rationale:** The Langfuse web UI and API must be reachable from the host at a configurable port, following the same UI-exposure pattern used by `temporal-ui`.
>
> **Acceptance Criteria:** After `docker compose --profile observability up -d`, `curl http://localhost:3000/api/public/health` returns `200`. Setting `LANGFUSE_PORT=3001` and repeating returns `200` on port 3001.

---

> **REQ-505** | Priority: MUST
>
> **Description:** The `langfuse` service must declare `depends_on: langfuse-db` with condition `service_healthy`.
>
> **Rationale:** Langfuse performs schema migrations on startup; if the database is not ready, the process exits with an error.
>
> **Acceptance Criteria:** `docker compose config` shows `langfuse` with `depends_on.langfuse-db.condition: service_healthy`. Starting the stack results in `langfuse-db` reaching healthy status before `langfuse` starts.

---

### 7.2 Langfuse Database

> **REQ-507** | Priority: MUST
>
> **Description:** The `docker-compose.yml` file must define a service named `langfuse-db` using the image `postgres:16-alpine` with container name `rag-langfuse-db`.
>
> **Rationale:** A dedicated PostgreSQL instance prevents schema conflicts with `rag-postgres` and `temporal-db`.
>
> **Acceptance Criteria:** `docker compose config` shows service key `langfuse-db` with `image: postgres:16-alpine` and `container_name: rag-langfuse-db`.

---

> **REQ-509** | Priority: MUST
>
> **Description:** The `langfuse-db` service must set environment variables `POSTGRES_USER=langfuse`, `POSTGRES_PASSWORD=langfuse`, and `POSTGRES_DB=langfuse`.
>
> **Rationale:** These values must match the `DATABASE_URL` passed to the `langfuse` service.
>
> **Acceptance Criteria:** `docker compose --profile observability run --rm langfuse-db psql -U langfuse -d langfuse -c '\l'` exits with code 0 and lists the `langfuse` database.

---

### 7.3 Profile-Based Opt-In

> **REQ-511** | Priority: MUST
>
> **Description:** Both the `langfuse` and `langfuse-db` services must be assigned `profiles: [observability]`.
>
> **Rationale:** Observability infrastructure is opt-in, consistent with the existing `monitoring` profile pattern.
>
> **Acceptance Criteria:** `docker compose up -d` (no profile) starts zero containers for these services. `docker compose --profile observability up -d` starts both.

---

> **REQ-513** | Priority: MUST
>
> **Description:** The `langfuse` and `langfuse-db` services must not be included in the `monitoring` profile and must not depend on any service assigned only to the `monitoring` profile.
>
> **Rationale:** The observability and monitoring profiles must be independently startable.
>
> **Acceptance Criteria:** `docker compose --profile observability up -d` starts successfully without `--profile monitoring`. `docker compose --profile monitoring up -d` starts successfully without activating `langfuse` or `langfuse-db`.

---

### 7.4 Health Checks

> **REQ-515** | Priority: MUST
>
> **Description:** The `langfuse` service must define a health check that performs an HTTP GET to `http://localhost:3000/api/public/health` and expects an HTTP 200 response.
>
> **Rationale:** A health check confirms both the web server and database connectivity are operational.
>
> **Acceptance Criteria:** After startup, `docker inspect rag-langfuse` shows `Health.Status` as `healthy` within the configured `start_period`.

---

> **REQ-517** | Priority: MUST
>
> **Description:** The `langfuse-db` service must define a health check using `pg_isready -U langfuse`.
>
> **Rationale:** `pg_isready` confirms the PostgreSQL process is accepting connections for the specified user.
>
> **Acceptance Criteria:** After startup, `docker inspect rag-langfuse-db` shows `Health.Status` as `healthy`. The `langfuse` container does not start until this condition is met.

---

> **REQ-519** | Priority: SHOULD
>
> **Description:** The health check for `langfuse-db` must specify `interval`, `timeout`, `retries`, and `start_period` values in `docker-compose.yml`.
>
> **Rationale:** Explicit health check timing parameters prevent premature unhealthy transitions during slow container initialization.
>
> **Acceptance Criteria:** `docker compose config` shows all four timing fields present under the `langfuse-db` health check definition.

---

### 7.5 Volume Management

> **REQ-521** | Priority: MUST
>
> **Description:** The `langfuse-db` service must mount a named volume `langfuse-db-data` to the PostgreSQL data directory.
>
> **Rationale:** A named volume ensures Langfuse trace data persists across container restarts.
>
> **Acceptance Criteria:** `docker compose config` shows `langfuse-db-data` mounted in `langfuse-db`. After stopping and restarting `langfuse-db`, previously written data remains accessible.

---

> **REQ-523** | Priority: MUST
>
> **Description:** The named volume `langfuse-db-data` must be declared in the top-level `volumes` block of `docker-compose.yml`.
>
> **Rationale:** Explicit volume declaration makes the volume lifecycle visible and manageable.
>
> **Acceptance Criteria:** `docker compose config` lists `langfuse-db-data` as a key in the top-level `volumes` map.

---

### 7.6 Environment Variables

> **REQ-525** | Priority: MUST
>
> **Description:** The `.env.example` file must contain an entry `LANGFUSE_NEXTAUTH_SECRET=replace_me_min32chars`.
>
> **Rationale:** `NEXTAUTH_SECRET` is required by Langfuse for session signing; omitting it causes the server to refuse to start.
>
> **Acceptance Criteria:** `grep LANGFUSE_NEXTAUTH_SECRET .env.example` returns a line with a non-empty placeholder value.

---

> **REQ-527** | Priority: MUST
>
> **Description:** The `.env.example` file must contain an entry `LANGFUSE_SALT=replace_me_min32chars`.
>
> **Rationale:** The `SALT` variable is required for password hashing in Langfuse.
>
> **Acceptance Criteria:** `grep LANGFUSE_SALT .env.example` returns a line with a non-empty placeholder value.

---

> **REQ-529** | Priority: MUST
>
> **Description:** The `.env.example` file must contain an entry `LANGFUSE_ENCRYPTION_KEY=replace_me_exactly_64_hex_chars`.
>
> **Rationale:** Langfuse v3 requires a 256-bit (64 hex character) encryption key for encrypting integration secrets at rest.
>
> **Acceptance Criteria:** `grep LANGFUSE_ENCRYPTION_KEY .env.example` returns a line with a placeholder communicating the 64-character hex constraint.

---

> **REQ-531** | Priority: MUST
>
> **Description:** The `.env.example` file must contain entries for `LANGFUSE_PORT`, `LANGFUSE_INIT_ORG_ID`, `LANGFUSE_INIT_PROJECT_ID`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY`, each with a non-empty placeholder value.
>
> **Rationale:** These variables configure bootstrap seeding of the initial organization and project, the host port binding, and the API key pair used by application services.
>
> **Acceptance Criteria:** `grep -c 'LANGFUSE_PORT\|LANGFUSE_INIT_ORG_ID\|LANGFUSE_INIT_PROJECT_ID\|LANGFUSE_PUBLIC_KEY\|LANGFUSE_SECRET_KEY' .env.example` returns `5`.

---

### 7.7 Application Service Passthrough

> **REQ-533** | Priority: MUST
>
> **Description:** The `rag-api` service definition must pass `RAG_OBSERVABILITY_PROVIDER=${RAG_OBSERVABILITY_PROVIDER:-noop}` to the container environment.
>
> **Rationale:** The observability provider is selected at runtime via this variable.
>
> **Acceptance Criteria:** `docker compose config` shows `RAG_OBSERVABILITY_PROVIDER` in the `rag-api` environment block.

---

> **REQ-535** | Priority: MUST
>
> **Description:** The `rag-worker` service definition must pass `RAG_OBSERVABILITY_PROVIDER=${RAG_OBSERVABILITY_PROVIDER:-noop}` to the container environment.
>
> **Rationale:** The Temporal worker executes pipeline activities that emit traces; it must receive the same provider selection as `rag-api`.
>
> **Acceptance Criteria:** `docker compose config` shows `RAG_OBSERVABILITY_PROVIDER` in the `rag-worker` environment block with the same default value (`noop`).

---

> **REQ-537** | Priority: MUST
>
> **Description:** The `rag-api` and `rag-worker` services must each pass `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY` to the container environment.
>
> **Rationale:** These three variables constitute the minimum connection credential set for the Langfuse SDK.
>
> **Acceptance Criteria:** `docker compose config` shows all three variables present in both the `rag-api` and `rag-worker` environment blocks.

---

> **REQ-539** | Priority: MUST
>
> **Description:** The environment variable blocks of `rag-api` and `rag-worker` must not be modified to remove or rename any of the four Langfuse-related variables already present.
>
> **Rationale:** These variables form the stable passthrough contract between the Docker Compose layer and the application observability adapter.
>
> **Acceptance Criteria:** A diff of the `rag-api` and `rag-worker` environment blocks shows no deletions of `RAG_OBSERVABILITY_PROVIDER`, `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, or `LANGFUSE_SECRET_KEY`.

---

> **REQ-541** | Priority: SHOULD
>
> **Description:** The `docker-compose.yml` file should include an inline comment on the `langfuse` and `langfuse-db` service entries stating that they belong to the `observability` profile.
>
> **Rationale:** Operators unfamiliar with Docker Compose profiles may not discover these services are opt-in.
>
> **Acceptance Criteria:** The raw `docker-compose.yml` contains a comment beginning with `# observability profile` adjacent to both the `langfuse` and `langfuse-db` service entries.

---

## 8. Non-Functional Requirements

### 8.1 Performance

> **REQ-901** | Priority: MUST
>
> **Description:** The `NoopBackend` implementation must introduce zero measurable overhead — a mean call latency increase of less than 0.05ms compared to the unwrapped baseline, measured over 10,000 iterations.
>
> **Rationale:** When observability is disabled, the subsystem must not degrade pipeline throughput.
>
> **Acceptance Criteria:** A microbenchmark wrapping a no-op function with `@observe` using `NoopBackend` produces a mean call latency increase of less than 0.05ms over 10,000 iterations in a single-threaded Python process.

---

> **REQ-903** | Priority: MUST
>
> **Description:** The `@observe` decorator must not add more than 1ms of synchronous latency to any decorated function when using `NoopBackend`.
>
> **Rationale:** The decorator wraps hot-path nodes. Synchronous overhead above 1ms compounds across pipeline stages.
>
> **Acceptance Criteria:** Timing measurements of 1,000 consecutive calls to a decorated no-op function show p99 overhead ≤ 1ms over the undecorated equivalent.

---

> **REQ-905** | Priority: MUST
>
> **Description:** The `LangfuseBackend` must dispatch trace data to the Langfuse service exclusively via asynchronous, non-blocking calls on the instrumented thread.
>
> **Rationale:** Synchronous network I/O on the hot path would couple pipeline latency directly to Langfuse service availability.
>
> **Acceptance Criteria:** A test instrumenting a function with `LangfuseBackend` pointing at a non-responsive host completes the decorated call within 50ms, with no blocking network call on the calling thread.

---

> **REQ-907** | Priority: MUST
>
> **Description:** Span creation and span-end operations on the hot path must each complete in less than 0.5ms of CPU time when using `LangfuseBackend` in normal operation.
>
> **Rationale:** Cumulative CPU time across a multi-node pipeline must remain negligible relative to node business logic.
>
> **Acceptance Criteria:** A profiled integration test shows that `span()` and `end()` each consume less than 0.5ms CPU time per call averaged over 500 calls.

---

### 8.2 Reliability & Resilience

> **REQ-909** | Priority: MUST
>
> **Description:** Any exception raised by a backend during span creation, span ending, or flushing must be caught internally and must not propagate to the calling pipeline node.
>
> **Rationale:** Observability failures must never interrupt pipeline execution.
>
> **Acceptance Criteria:** A test that injects `RuntimeError` into `start_span()`, `end_span()`, and `flush()` of a backend mock verifies the decorated pipeline function completes successfully in all three cases.

---

> **REQ-911** | Priority: MUST
>
> **Description:** `flush()` must complete within 10 seconds when called at Temporal activity completion, regardless of the number of buffered spans.
>
> **Rationale:** Temporal activities have completion deadlines. An unbounded `flush()` call stalls activity heartbeat.
>
> **Acceptance Criteria:** A test that buffers 1,000 spans in `LangfuseBackend` and then calls `flush()` against a mock server with 100ms simulated network latency returns within 10 seconds.

---

> **REQ-913** | Priority: MUST
>
> **Description:** The backend singleton must support concurrent access from multiple threads without data corruption or deadlock.
>
> **Rationale:** Temporal workers execute activities concurrently in a thread pool.
>
> **Acceptance Criteria:** A stress test spawning 50 threads each calling `span()` and `end()` 100 times concurrently on a shared backend completes without exception, without deadlock within 30 seconds, and without dropping any spans.

---

> **REQ-915** | Priority: MUST
>
> **Description:** When the Langfuse service is unreachable, the `LangfuseBackend` must continue accepting new spans without raising an exception or blocking the caller.
>
> **Rationale:** Transient network partitions must not degrade pipeline availability.
>
> **Acceptance Criteria:** A test configuring `LangfuseBackend` with an unreachable host and calling `span()` / `end()` 100 times completes all 100 calls without exception and within 5 seconds total.

---

> **REQ-917** | Priority: SHOULD
>
> **Description:** `flush()` should log a warning-level message when it does not complete within 5 seconds.
>
> **Rationale:** Silent slow flushes at activity boundaries are difficult to diagnose.
>
> **Acceptance Criteria:** A test that mocks `flush()` to sleep 6 seconds captures at least one `WARNING`-level log entry containing the string `"flush"`.

---

### 8.3 Maintainability & Extensibility

> **REQ-919** | Priority: MUST
>
> **Description:** Adding a new observability provider must require creating exactly one new subdirectory under `observability/` and adding exactly one entry in the factory function, with no modifications to any consumer module, the `ObservabilityBackend` ABC, shared schemas, or `docker-compose` files.
>
> **Rationale:** This constraint enforces the open/closed principle.
>
> **Acceptance Criteria:** Adding a stub `LangSmithBackend` requires changes to no more than two files: the new provider module and the factory function.

---

> **REQ-921** | Priority: MUST
>
> **Description:** The factory function must select the backend implementation based solely on a single environment variable, with no code change required to switch providers.
>
> **Rationale:** Operators must be able to switch observability providers via deployment configuration.
>
> **Acceptance Criteria:** A parameterized test verifies that setting the provider env var to `"noop"`, `"langfuse"`, and an unrecognized value causes the factory to return `NoopBackend`, `LangfuseBackend`, and raise `ValueError` respectively, with no source file modification between cases.

---

> **REQ-923** | Priority: MUST
>
> **Description:** Every public class and public function in the observability subsystem must have a docstring and an `@summary` block in its module header.
>
> **Rationale:** Consistent documentation enables new contributors to understand provider contracts without reading implementation internals.
>
> **Acceptance Criteria:** A `pydocstyle` check against all modules under `observability/` reports zero missing-docstring violations. Every module file contains a non-empty `# @summary` block.

---

> **REQ-925** | Priority: SHOULD
>
> **Description:** The migration from the old provider import pattern to the new factory-based pattern must be completable one file at a time, with both patterns operational simultaneously during the migration window.
>
> **Rationale:** A big-bang migration across all consumers in a single commit introduces high review and rollback risk.
>
> **Acceptance Criteria:** A test environment with one consumer using the old import path and one using the new factory path passes all integration tests simultaneously.

---

> **REQ-927** | Priority: SHOULD
>
> **Description:** The total line count of code required to implement a new backend provider must not exceed 150 lines, excluding tests and docstrings.
>
> **Rationale:** An oversized provider scaffold indicates shared abstractions are inadequate.
>
> **Acceptance Criteria:** The `LangfuseBackend` implementation file (excluding tests and docstrings) contains 150 lines or fewer.

---

### 8.4 Security

> **REQ-929** | Priority: MUST
>
> **Description:** The values of `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` must never appear in any log output produced by the observability subsystem at any log level.
>
> **Rationale:** Credentials written to logs are trivially exfiltrated from log aggregation services and CI output.
>
> **Acceptance Criteria:** A test initializes `LangfuseBackend` with known sentinel credential values, triggers all log-emitting code paths, captures all log records at DEBUG level and above, and asserts neither sentinel value appears in any captured log record.

---

> **REQ-931** | Priority: MUST
>
> **Description:** No observability credential must be hardcoded as a literal value in any source file in the repository.
>
> **Rationale:** Hardcoded credentials in source code are exposed in version control history and cannot be rotated without a code change.
>
> **Acceptance Criteria:** A CI step running `detect-secrets` against all files under `observability/` reports zero detected secrets.

---

> **REQ-933** | Priority: MUST
>
> **Description:** Span attributes must not include raw user input or raw model output by default. The `capture_input` and `capture_output` flags must default to `False`.
>
> **Rationale:** User queries and model responses may contain PII. Opt-in capture prevents accidental PII transmission in the default deployment posture.
>
> **Acceptance Criteria:** A unit test instantiating the backend configuration without setting `capture_input` or `capture_output` asserts both fields evaluate to `False`. An integration test verifies span payloads contain no `input` or `output` attributes when defaults are in effect.

---

> **REQ-935** | Priority: SHOULD
>
> **Description:** When `capture_input` or `capture_output` is explicitly set to `True`, the observability subsystem should emit a single `WARNING`-level log entry at startup naming the enabled flag.
>
> **Rationale:** Explicit opt-in for PII-bearing span attributes should be auditable in startup logs.
>
> **Acceptance Criteria:** Initializing the backend with `capture_input=True` captures exactly one `WARNING`-level log entry containing the string `"capture_input"` during initialization.

---

### 8.5 Deployment

> **REQ-937** | Priority: MUST
>
> **Description:** The Langfuse service started via the Docker Compose observability profile must reach a healthy state within 60 seconds on a developer machine meeting the project's minimum hardware specification.
>
> **Rationale:** A startup time exceeding 60 seconds disrupts local development iteration cycles.
>
> **Acceptance Criteria:** A timed smoke test polls the Langfuse health endpoint at 5-second intervals and receives HTTP 200 within 60 seconds of `docker compose --profile observability up -d` completing.

---

> **REQ-939** | Priority: MUST
>
> **Description:** The observability provider must be selectable by setting a single environment variable, with no modification to any source file, Dockerfile, or Compose file required.
>
> **Rationale:** Provider selection via environment variable is the standard twelve-factor app configuration pattern.
>
> **Acceptance Criteria:** A test matrix verifies the pipeline initializes with `NoopBackend` when the provider env var is unset, and with `LangfuseBackend` when set to `"langfuse"`, without modifying any file between test runs.

---

> **REQ-941** | Priority: MUST
>
> **Description:** The old observability import path must remain importable and functionally equivalent to the new factory-based path for a minimum of one release after the migration is introduced.
>
> **Rationale:** Consumers of the old import path that are not yet migrated must not break at import time.
>
> **Acceptance Criteria:** A regression test imports the backend class from the old path and asserts the returned object is an instance of the same class returned by the new factory path. This test must remain and pass for at least one tagged release after the migration commit.

---

## 9. Requirements Traceability Matrix

| ID | Section | Priority | Summary |
|----|---------|----------|---------|
| REQ-101 | 3: Backend Abstraction | MUST | ObservabilityBackend ABC with 5 abstract methods in backend.py |
| REQ-103 | 3: Backend Abstraction | MUST | span() returns Span ABC instance |
| REQ-105 | 3: Backend Abstraction | MUST | trace() returns Trace ABC instance |
| REQ-107 | 3: Backend Abstraction | MUST | generation() returns Generation ABC instance |
| REQ-109 | 3: Backend Abstraction | MUST | flush() completes all pending writes before returning |
| REQ-111 | 3: Backend Abstraction | MUST | shutdown() abstract; post-shutdown calls never raise |
| REQ-113 | 3: Backend Abstraction | MUST | Span ABC with 4 abstract methods |
| REQ-115 | 3: Backend Abstraction | MUST | set_attribute accepts any Python object, returns None |
| REQ-117 | 3: Backend Abstraction | MUST | end() stores status and error in SpanRecord |
| REQ-119 | 3: Backend Abstraction | MUST | Span.__enter__ returns self |
| REQ-121 | 3: Backend Abstraction | MUST | Span.__exit__ calls end with appropriate status, returns False |
| REQ-123 | 3: Backend Abstraction | MUST | Span method exceptions caught internally, never propagate |
| REQ-125 | 3: Backend Abstraction | MUST | Trace ABC with 4 abstract methods |
| REQ-127 | 3: Backend Abstraction | MUST | Trace.span() child shares trace_id with parent Trace |
| REQ-129 | 3: Backend Abstraction | MUST | Trace.generation() child shares trace_id with parent Trace |
| REQ-131 | 3: Backend Abstraction | MUST | Trace.__enter__ returns self |
| REQ-133 | 3: Backend Abstraction | MUST | Trace.__exit__ returns False |
| REQ-135 | 3: Backend Abstraction | MUST | Trace method exceptions caught internally |
| REQ-137 | 3: Backend Abstraction | MUST | Generation ABC with 5 abstract methods |
| REQ-139 | 3: Backend Abstraction | MUST | set_output stores string in GenerationRecord.output |
| REQ-141 | 3: Backend Abstraction | MUST | set_token_counts stores both ints; non-int raises TypeError |
| REQ-143 | 3: Backend Abstraction | MUST | Generation.end() follows same contract as Span.end() |
| REQ-145 | 3: Backend Abstraction | MUST | Generation context manager: __enter__ returns self, __exit__ returns False |
| REQ-147 | 3: Backend Abstraction | MUST | Generation method exceptions caught internally |
| REQ-149 | 3: Backend Abstraction | MUST | SpanRecord dataclass with 8 typed fields |
| REQ-151 | 3: Backend Abstraction | MUST | TraceRecord dataclass with 6 typed fields |
| REQ-153 | 3: Backend Abstraction | MUST | GenerationRecord dataclass; output/token fields optional |
| REQ-155 | 3: Backend Abstraction | MUST | start_ts/end_ts use time.time(); end_ts >= start_ts |
| REQ-157 | 3: Backend Abstraction | SHOULD | Schema types importable without langfuse installed |
| REQ-159 | 3: Backend Abstraction | MUST | NoopBackend is concrete subclass of ObservabilityBackend |
| REQ-161 | 3: Backend Abstraction | MUST | NoopBackend returns typed no-op objects; zero I/O |
| REQ-163 | 3: Backend Abstraction | MUST | NoopBackend.flush()/shutdown() return None immediately, <1ms |
| REQ-165 | 3: Backend Abstraction | MUST | All Noop objects return correct types, never raise |
| REQ-167 | 3: Backend Abstraction | MUST | Config value selects backend; unknown value raises ValueError |
| REQ-169 | 3: Backend Abstraction | MUST | Backend is a process-wide singleton |
| REQ-171 | 3: Backend Abstraction | MUST | Failed backend init logs warning and falls back to NoopBackend |
| REQ-201 | 4: Langfuse Backend | MUST | All langfuse SDK imports confined to langfuse/backend.py |
| REQ-203 | 4: Langfuse Backend | MUST | langfuse/__init__.py exports only LangfuseBackend |
| REQ-205 | 4: Langfuse Backend | MUST | LangfuseBackend is concrete subclass of ObservabilityBackend |
| REQ-207 | 4: Langfuse Backend | MUST | LangfuseBackend.__init__ calls get_client() once; exceptions propagate |
| REQ-209 | 4: Langfuse Backend | MUST | Factory catches LangfuseBackend init failure, falls back to NoopBackend |
| REQ-211 | 4: Langfuse Backend | MUST | LangfuseBackend.span routes through trace object when parent provided |
| REQ-213 | 4: Langfuse Backend | MUST | LangfuseBackend.trace calls client.trace() and returns LangfuseTrace |
| REQ-215 | 4: Langfuse Backend | MUST | LangfuseBackend.generation uses as_type="generation" |
| REQ-217 | 4: Langfuse Backend | MUST | LangfuseSpan.set_attribute calls inner.update(metadata={key: value}) |
| REQ-219 | 4: Langfuse Backend | MUST | LangfuseSpan.set_attribute catches all exceptions, logs warning |
| REQ-221 | 4: Langfuse Backend | MUST | LangfuseSpan.end sets ERROR level before inner.end() when error given |
| REQ-223 | 4: Langfuse Backend | MUST | LangfuseSpan.end catches all inner exceptions, logs warning |
| REQ-225 | 4: Langfuse Backend | MUST | LangfuseSpan context manager: __enter__ returns self, __exit__ returns False |
| REQ-227 | 4: Langfuse Backend | MUST | LangfuseTrace.span creates child via trace_obj.span(), returns LangfuseSpan |
| REQ-229 | 4: Langfuse Backend | MUST | LangfuseTrace.generation creates child, returns LangfuseGeneration |
| REQ-231 | 4: Langfuse Backend | MUST | LangfuseTrace methods catch all exceptions, log warning |
| REQ-233 | 4: Langfuse Backend | MUST | LangfuseTrace context manager: __enter__ returns self, __exit__ returns False |
| REQ-235 | 4: Langfuse Backend | MUST | LangfuseGeneration.set_output calls inner.update(output=output) |
| REQ-237 | 4: Langfuse Backend | MUST | set_token_counts calls inner.update(usage={"input": n, "output": m}) |
| REQ-239 | 4: Langfuse Backend | MUST | LangfuseGeneration.end follows same error-level logic as LangfuseSpan.end |
| REQ-241 | 4: Langfuse Backend | MUST | LangfuseGeneration methods catch all exceptions, log warning |
| REQ-243 | 4: Langfuse Backend | MUST | LangfuseGeneration context manager |
| REQ-245 | 4: Langfuse Backend | MUST | No hardcoded credentials; all from env via SDK |
| REQ-247 | 4: Langfuse Backend | MUST | LangfuseBackend accepts no host/public_key/secret_key params |
| REQ-249 | 4: Langfuse Backend | MUST | LangfuseBackend.flush() calls client.flush(); propagates exceptions |
| REQ-251 | 4: Langfuse Backend | MUST | LangfuseBackend.shutdown() calls client.shutdown(); propagates exceptions |
| REQ-301 | 5: Public API | MUST | All 6 public symbols importable from package root |
| REQ-303 | 5: Public API | MUST | Symbols outside __all__ treated as internal |
| REQ-305 | 5: Public API | MUST | get_tracer() returns same singleton every call |
| REQ-307 | 5: Public API | MUST | get_tracer() return type annotation is ObservabilityBackend |
| REQ-309 | 5: Public API | MUST | get_tracer() works without langfuse installed |
| REQ-311 | 5: Public API | MUST | get_tracer() is thread-safe |
| REQ-313 | 5: Public API | MUST | observe() decorator factory with 3 params |
| REQ-315 | 5: Public API | MUST | observe uses functools.wraps |
| REQ-317 | 5: Public API | MUST | observe defaults span name to func.__qualname__ |
| REQ-319 | 5: Public API | MUST | capture_input defaults to False |
| REQ-321 | 5: Public API | MUST | capture_output defaults to False |
| REQ-323 | 5: Public API | MUST | capture_input=True sets "input" attr to repr(args[1:])[:500] |
| REQ-325 | 5: Public API | MUST | capture_output=True sets "output" attr to repr(return_value)[:500] |
| REQ-327 | 5: Public API | MUST | On exception: sets "error" attribute, re-raises unchanged |
| REQ-329 | 5: Public API | MUST | @observe with NoopBackend adds ≤1ms overhead |
| REQ-331 | 5: Public API | MUST | Old import path providers.get_tracer still resolves |
| REQ-333 | 5: Public API | MUST | Tracer alias exported; Tracer is ObservabilityBackend |
| REQ-335 | 5: Public API | SHOULD | providers.get_tracer import emits DeprecationWarning |
| REQ-337 | 5: Public API | SHOULD | Tracer alias access emits DeprecationWarning |
| REQ-339 | 5: Public API | MUST | __all__ = ["get_tracer", "observe", "Tracer", "Span", "Trace", "Generation"] |
| REQ-341 | 5: Public API | MUST | Span/Trace/Generation re-exported from backend.py |
| REQ-401 | 6: Consumer Integration | MUST | All consumers import from package root only |
| REQ-403 | 6: Consumer Integration | MUST | get_tracer and observe importable from package root |
| REQ-405 | 6: Consumer Integration | MUST | No consumer imports langfuse or opentelemetry directly |
| REQ-407 | 6: Consumer Integration | SHOULD | Simple tracing uses @observe decorator |
| REQ-409 | 6: Consumer Integration | MUST | @observe auto-ends span; no try/finally in consumer |
| REQ-411 | 6: Consumer Integration | MUST | @observe accepts single positional string; no other mandatory args |
| REQ-413 | 6: Consumer Integration | MUST | span() usable as context manager; auto-ended on block exit |
| REQ-415 | 6: Consumer Integration | MUST | span.set_attribute() inside with block adds attributes |
| REQ-417 | 6: Consumer Integration | MUST | trace() groups child spans under one logical trace root |
| REQ-419 | 6: Consumer Integration | SHOULD | trace object exposes generation() for LLM call tracking |
| REQ-421 | 6: Consumer Integration | MUST | Attribute keys must be snake_case |
| REQ-423 | 6: Consumer Integration | MUST | Attribute keys must not contain provider-specific prefixes |
| REQ-425 | 6: Consumer Integration | SHOULD | Repeated attribute keys defined as shared constants |
| REQ-427 | 6: Consumer Integration | MUST | Attribute values must be str, int, float, or bool |
| REQ-429 | 6: Consumer Integration | MUST | All 8 consumer files migrate to package-root import |
| REQ-431 | 6: Consumer Integration | MUST | All start_span() calls migrated to span() or @observe |
| REQ-433 | 6: Consumer Integration | SHOULD | start_span alias available during migration period |
| REQ-435 | 6: Consumer Integration | MUST | Module-level _tracer_instance pattern removed |
| REQ-437 | 6: Consumer Integration | MUST | No explicit span.end() inside a with-block |
| REQ-439 | 6: Consumer Integration | MUST | No bare except solely to set span status before re-raise |
| REQ-441 | 6: Consumer Integration | MUST | No consumer imports concrete backend class names |
| REQ-501 | 7: Infrastructure | MUST | docker-compose.yml defines "langfuse" service using langfuse/langfuse:3 |
| REQ-503 | 7: Infrastructure | MUST | langfuse service exposes port ${LANGFUSE_PORT:-3000} |
| REQ-505 | 7: Infrastructure | MUST | langfuse depends_on langfuse-db with service_healthy |
| REQ-507 | 7: Infrastructure | MUST | langfuse-db: postgres:16-alpine, container name rag-langfuse-db |
| REQ-509 | 7: Infrastructure | MUST | langfuse-db sets POSTGRES_USER/PASSWORD/DB all to "langfuse" |
| REQ-511 | 7: Infrastructure | MUST | Both services assigned profiles: [observability] |
| REQ-513 | 7: Infrastructure | MUST | langfuse and langfuse-db do not belong to monitoring profile |
| REQ-515 | 7: Infrastructure | MUST | langfuse health check: GET /api/public/health → 200 |
| REQ-517 | 7: Infrastructure | MUST | langfuse-db health check: pg_isready -U langfuse |
| REQ-519 | 7: Infrastructure | SHOULD | langfuse-db health check specifies all 4 timing fields |
| REQ-521 | 7: Infrastructure | MUST | langfuse-db mounts named volume langfuse-db-data |
| REQ-523 | 7: Infrastructure | MUST | langfuse-db-data declared in top-level volumes block |
| REQ-525 | 7: Infrastructure | MUST | .env.example contains LANGFUSE_NEXTAUTH_SECRET placeholder |
| REQ-527 | 7: Infrastructure | MUST | .env.example contains LANGFUSE_SALT placeholder |
| REQ-529 | 7: Infrastructure | MUST | .env.example contains LANGFUSE_ENCRYPTION_KEY placeholder |
| REQ-531 | 7: Infrastructure | MUST | .env.example contains 5 remaining Langfuse vars |
| REQ-533 | 7: Infrastructure | MUST | rag-api passes RAG_OBSERVABILITY_PROVIDER |
| REQ-535 | 7: Infrastructure | MUST | rag-worker passes RAG_OBSERVABILITY_PROVIDER |
| REQ-537 | 7: Infrastructure | MUST | Both services pass LANGFUSE_HOST, PUBLIC_KEY, SECRET_KEY |
| REQ-539 | 7: Infrastructure | MUST | rag-api/rag-worker env blocks preserve 4 Langfuse variables |
| REQ-541 | 7: Infrastructure | SHOULD | docker-compose.yml has inline comment for observability profile |
| REQ-901 | 8: Non-Functional | MUST | NoopBackend <0.05ms mean latency over 10,000 iterations |
| REQ-903 | 8: Non-Functional | MUST | @observe with NoopBackend ≤1ms p99 overhead per 1,000 calls |
| REQ-905 | 8: Non-Functional | MUST | LangfuseBackend dispatches data via async non-blocking calls only |
| REQ-907 | 8: Non-Functional | MUST | span creation and end each <0.5ms CPU time |
| REQ-909 | 8: Non-Functional | MUST | Backend exceptions caught; pipeline function completes normally |
| REQ-911 | 8: Non-Functional | MUST | flush() completes within 10 seconds with 1,000 buffered spans |
| REQ-913 | 8: Non-Functional | MUST | Backend singleton supports 50-thread concurrent access |
| REQ-915 | 8: Non-Functional | MUST | LangfuseBackend accepts spans without blocking when unreachable |
| REQ-917 | 8: Non-Functional | SHOULD | flush() logs WARNING when it takes >5 seconds |
| REQ-919 | 8: Non-Functional | MUST | New provider requires 1 subdirectory + 1 factory entry only |
| REQ-921 | 8: Non-Functional | MUST | Factory selects backend by env var alone |
| REQ-923 | 8: Non-Functional | MUST | All public classes/functions have docstrings + @summary blocks |
| REQ-925 | 8: Non-Functional | SHOULD | Migration completable one file at a time |
| REQ-927 | 8: Non-Functional | SHOULD | New provider implementation ≤150 lines |
| REQ-929 | 8: Non-Functional | MUST | LANGFUSE credentials never appear in log output |
| REQ-931 | 8: Non-Functional | MUST | No observability credential hardcoded in any source file |
| REQ-933 | 8: Non-Functional | MUST | capture_input and capture_output default to False |
| REQ-935 | 8: Non-Functional | SHOULD | capture_input/output=True emits WARNING at startup |
| REQ-937 | 8: Non-Functional | MUST | Langfuse Docker service healthy within 60 seconds |
| REQ-939 | 8: Non-Functional | MUST | Provider selection by single env var; no source change required |
| REQ-941 | 8: Non-Functional | MUST | Old import path remains functional for minimum one release |

**Tally:** 119 MUST · 18 SHOULD · 0 MAY · **Total: 137 requirements**

---

## Appendix A: Glossary

See Section 1.3 Terminology.

## Appendix B: Document References

| Document | Location | Purpose |
|---|---|---|
| Brainstorm Sketch | `docs/superpowers/specs/2026-03-27-observability-langfuse-sketch.md` | Approach selection and scope |
| Guardrails Reference | `src/guardrails/` | Reference pattern for provider isolation |
| Current Observability | `src/platform/observability/` | Existing implementation to be refactored |
| Docker Compose | `docker-compose.yml` | Infrastructure to be extended |

## Appendix C: Open Questions

| # | Question | Impact |
|---|---|---|
| 1 | Should `LangfuseBackend.flush()` enforce a hard timeout internally, or leave timeout responsibility to the caller? | REQ-911 assumes caller manages timeout |
| 2 | Should the `@observe` decorator support async functions (`async def`) in addition to sync functions? | If Temporal activities become async, this will be needed |
| 3 | Should attribute value coercion (non-scalar → str) be done silently or via TypeError? REQ-427 leaves this open. | Affects consumer ergonomics |
