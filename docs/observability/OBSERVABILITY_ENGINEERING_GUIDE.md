# Swappable Observability Subsystem — Engineering Guide

| Field | Value |
|---|---|
| **Document** | Post-Implementation Engineering Guide |
| **Version** | 1.0 |
| **Date** | 2026-03-27 |
| **Status** | Final |
| **Spec Reference** | `docs/observability/OBSERVABILITY_SPEC.md` |
| **Design Reference** | `docs/observability/OBSERVABILITY_DESIGN.md` |
| **Package Root** | `src/platform/observability/` |

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture Decisions](#2-architecture-decisions)
3. [Module Reference](#3-module-reference)
   - 3.1 [`backend.py` — Abstract Base Classes](#31-srcplatformobservabilitybackendpy--abstract-base-classes)
   - 3.2 [`schemas.py` — Record Dataclasses](#32-srcplatformobservabilityschemasspy--record-dataclasses)
   - 3.3 [`__init__.py` — Public API Facade](#33-srcplatformobservabilityinitpy--public-api-facade)
   - 3.4 [`noop/backend.py` — No-Op Backend](#34-srcplatformobservabilitynoop-backendpy--no-op-backend)
   - 3.5 [`langfuse/backend.py` — Langfuse v3 Backend](#35-srcplatformobservabilitylangfusebackendpy--langfuse-v3-backend)
4. [End-to-End Data Flow](#4-end-to-end-data-flow)
   - 4.1 [Happy Path — Langfuse Active](#41-happy-path--langfuse-active)
   - 4.2 [Langfuse-Down Fallback](#42-langfuse-down-fallback)
   - 4.3 [`@observe` Decorator Path](#43-observe-decorator-path)
5. [Configuration Reference](#5-configuration-reference)
6. [Integration Contracts](#6-integration-contracts)
7. [Operational Notes](#7-operational-notes)
8. [Known Limitations](#8-known-limitations)
9. [Extension Guide — Adding a New Backend](#9-extension-guide--adding-a-new-backend)
10. [Requirement Coverage Appendix](#10-requirement-coverage-appendix)

---

## 1. System Overview

The Swappable Observability Subsystem provides distributed tracing, LLM cost tracking, and span-level instrumentation for the RAG platform. It is designed so that:

- **Consumers** (retrieval, ingest) interact exclusively with one stable import: `from src.platform.observability import get_tracer, observe`.
- **The active backend** (no-op or Langfuse) is selected by an environment variable at process startup — no code change is required to switch providers.
- **All observability calls are fail-open**: a broken or unreachable backend never crashes the application it observes.

### 1.1 Package Layout

```
src/platform/observability/
├── __init__.py          # Public API facade (the ONLY import surface for consumers)
├── backend.py           # Abstract base classes: ObservabilityBackend, Span, Trace, Generation
├── schemas.py           # In-memory record dataclasses: SpanRecord, TraceRecord, GenerationRecord
├── providers.py         # Deprecated backward-compat shim (DeprecationWarning on import)
├── noop/
│   ├── __init__.py      # Re-export: NoopBackend
│   └── backend.py       # NoopBackend, NoopSpan, NoopTrace, NoopGeneration
└── langfuse/
    ├── __init__.py      # Re-export: LangfuseBackend
    └── backend.py       # LangfuseBackend, LangfuseSpan, LangfuseTrace, LangfuseGeneration
```

### 1.2 Architecture Diagram

```
  Call Sites (Application Layer)
  ┌─────────────────────────────────────────────────────────────────────┐
  │  src/retrieval/query/nodes/reranker.py                              │
  │  src/retrieval/generation/nodes/generator.py                        │
  │  src/retrieval/pipeline/rag_chain.py  ... (consumers)               │
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
  │   ├── Span (ABC)         — start / end / set_attribute              │
  │   ├── Trace (ABC)        — span() / generation() / context manager  │
  │   └── Generation (ABC)   — LLM call tracking                        │
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

### 1.3 Data Flow Summary

| Stage | Input | Output | Component |
|---|---|---|---|
| 1. Instrumentation | Call site invokes `@observe("name")` or `with tracer.trace("name")` | Request to open a trace or span | `__init__.py` |
| 2. Backend resolution | `OBSERVABILITY_PROVIDER` env var at process startup | Process-wide `ObservabilityBackend` singleton | `get_tracer()` in `__init__.py` |
| 3. Backend dispatch | `trace()` / `span()` / `generation()` call on singleton | Concrete `Span`, `Trace`, or `Generation` instance | `ObservabilityBackend` ABC |
| 4a. Langfuse recording | Span/trace/generation lifecycle events | Langfuse SDK calls | `LangfuseBackend` |
| 4b. Noop recording | Same events | (no output) | `NoopBackend` |
| 5. SDK transmission | Langfuse SDK payload | HTTP requests to Langfuse server | Langfuse SDK (confined to `langfuse/backend.py`) |
| 6. Persistent storage | Ingested records | Durable trace state | `langfuse-db` PostgreSQL 16 |
| 7. Developer inspection | Browser to `http://localhost:3000` | Rendered trace UI | Langfuse UI |

### 1.4 `providers.py` — Deprecated Shim

`src/platform/observability/providers.py` is a thin, module-level shim that emits a `DeprecationWarning` at import time and re-exports `get_tracer` from the public API. It exists solely to keep old import paths working during migration. It has no behavior of its own. New code must never import from it.

---

## 2. Architecture Decisions

### Decision: Provider Isolation via Subdirectory Packages

**Context:** The previous design placed `langfuse_tracer.py` and `noop_tracer.py` flat alongside the ABC contracts. Any refactor to the ABC surface required also editing the provider files, and any accidental import from `langfuse_tracer.py` in consumer code would couple them to the SDK.

**Options considered:**
1. **Flat layout** — all files at the same directory level. Simple, but leaks provider internals to consumers and makes adding a second backend ambiguous.
2. **Subdirectory per provider** — `noop/` and `langfuse/` are isolated packages; ABCs and public API live at the parent level. Each provider can be imported, linted, and tested independently.

**Choice:** Option 2 — subdirectory per provider.

**Rationale:** The guardrails package (`src/guardrails/`) established this pattern for the project. Provider isolation is the structural enforcement of the "provider-agnostic consumers" design principle (REQ-201). The alternative allows transitive SDK coupling through accidental imports.

**Consequences:**
- **Positive:** All Langfuse SDK imports are confined to exactly one file (`langfuse/backend.py`). Adding LangSmith or another provider adds one directory; nothing else changes.
- **Negative:** One additional level of indirection when tracing an SDK call for debugging.
- **Watch for:** Developers who add `from src.platform.observability.langfuse import ...` in consumer code — this breaks the isolation contract.

---

### Decision: Fail-Open Design for All SDK Calls

**Context:** The application must remain functional when Langfuse is unreachable, misconfigured, or raises an unexpected exception during span creation or attribute setting.

**Options considered:**
1. **Fail-fast** — propagate all SDK exceptions to callers. Simple to reason about, but observability failures cascade into application failures.
2. **Fail-open** — catch all exceptions inside SDK-calling methods; log a warning; return a noop object. Application is never affected by observability errors.
3. **Circuit breaker** — fail-open after N consecutive failures, with automatic reset. Adds significant complexity.

**Choice:** Option 2 — fail-open on all SDK calls except `flush()` and `shutdown()`.

**Rationale:** REQ-901 (design principle 1) mandates fail-open. The asymmetry at `flush()`/`shutdown()` is intentional: these are lifecycle operations where callers (shutdown hooks, test teardown) explicitly need to know whether data was durably flushed.

**Consequences:**
- **Positive:** Observability errors are never visible to the application user. The system silently degrades to noop behavior.
- **Negative:** SDK errors are only visible in the `rag.observability.langfuse` logger at WARNING level; they are not surfaced as metrics.
- **Watch for:** A misconfigured Langfuse backend that silently drops all traces — operators must check logs during setup.

---

### Decision: Thread-Safe Singleton via Double-Checked Locking

**Context:** `get_tracer()` is called by every instrumented function on every request. The backend must be initialized exactly once. A naive lock on every call would add measurable overhead to the hot path.

**Options considered:**
1. **Module-level initialization** — initialize `_backend` at import time. Simple, but forces early SDK import and makes testing harder (no way to reset the singleton).
2. **Locking every call** — acquire `_backend_lock` on each `get_tracer()` invocation. Correct, but unnecessary overhead after first initialization.
3. **Double-checked locking** — fast-path check with no lock (`if _backend is not None: return`), slow-path lock only on first call.

**Choice:** Option 3 — double-checked locking.

**Rationale:** The fast path (99.9%+ of calls) has no lock contention. The slow path (first call only) is safe under Python's GIL and explicit `threading.Lock`. This is the standard pattern for lazy singletons in Python.

**Consequences:**
- **Positive:** Zero lock overhead after first initialization. Singleton is created exactly once.
- **Negative:** Slightly more code than module-level initialization.
- **Watch for:** In tests that need to reset the singleton between test cases, the module-level `_backend` variable must be patched directly (e.g., `monkeypatch.setattr("src.platform.observability._backend", None)`).

---

### Decision: `@observe` Decorator with Configurable Capture

**Context:** The most common instrumentation pattern — wrap a function with a span — requires 5+ lines of boilerplate with a context manager. A decorator reduces this to one line.

**Options considered:**
1. **No decorator** — callers always write the `with get_tracer().span(...) as span:` pattern explicitly.
2. **Always-on capture** — `@observe` always captures inputs and outputs. Simple, but risks logging sensitive data or large objects by default.
3. **Opt-in capture** — `@observe(capture_input=True, capture_output=True)` flags default to `False`.

**Choice:** Option 3 — decorator factory with opt-in capture, truncated at 500 characters.

**Rationale:** `capture_input=False` by default avoids accidental PII logging (REQ-339). The 500-character truncation (`_MAX_CAPTURE_LEN = 500`) prevents runaway memory allocation on large document inputs.

**Consequences:**
- **Positive:** Most call sites become `@observe("component.operation")` — zero boilerplate. Input/output capture is available when needed.
- **Negative:** `capture_input=True` skips `self`/`cls` (first positional arg) but captures remaining args via `repr()`, which may not always be readable.
- **Watch for:** Functions with side effects in `__repr__` — `repr(args[1:])` will call those `__repr__` methods.

---

### Decision: Backward-Compatibility Strategy

**Context:** Existing call sites imported from `from src.platform.observability.providers import get_tracer` and called `backend.start_span(...)`. Both import paths and method names are incorrect after the redesign.

**Options considered:**
1. **Hard break** — remove old names immediately, fix all callers atomically. Clean, but requires one coordinated change across all consumer files.
2. **Shim + alias** — `providers.py` re-exports `get_tracer` with a `DeprecationWarning`; `start_span()` on the ABC delegates to `span()` with a `DeprecationWarning`.

**Choice:** Option 2 — shims with `DeprecationWarning`.

**Rationale:** Allows consumer migration to happen incrementally without blocking on a single coordinated commit. Warnings surface in tests and CI so the migration is tracked automatically.

**Consequences:**
- **Positive:** Zero import errors during migration. Warnings appear in test output, making migration progress visible.
- **Negative:** Deprecated symbols persist in the codebase until removed. Future maintainer must remember to complete the migration.
- **Watch for:** If `PYTHONWARNINGS=error` is set in CI, these `DeprecationWarning` emissions will become test failures — intentional, as they enforce migration completion.

---

## 3. Module Reference

### `src/platform/observability/backend.py` — Abstract Base Classes

**Purpose:**

This module defines the provider-agnostic contract layer for the entire observability subsystem. It contains four ABCs — `Span`, `Generation`, `Trace`, and `ObservabilityBackend` — along with a `Tracer` alias for backward compatibility. No third-party dependencies are imported; the file is importable in any Python environment, including test environments without the Langfuse SDK installed.

**How it works:**

1. `Span` is the base for any single timed operation. It declares two abstract methods (`set_attribute`, `end`) and provides concrete `__enter__`/`__exit__` implementations. `__enter__` returns `self`, enabling `with backend.span("name") as span:`. `__exit__` calls `self.end(status="error", error=exc_val)` when an exception occurred, or `self.end(status="ok")` otherwise, then returns `False` to never suppress exceptions.

2. `Generation` is a specialized variant of the tracing concept for LLM calls. It declares three abstract methods: `set_output`, `set_token_counts`, and `end`. Like `Span`, it provides concrete context manager protocol methods.

3. `Trace` is the root grouping object. It declares abstract `span()` and `generation()` factory methods for creating correlated child observations. Its `__exit__` returns `False` without calling any finalization method — it delegates lifecycle management to its children.

4. `ObservabilityBackend` is the top-level ABC that backends implement. It declares five abstract methods: `span`, `trace`, `generation`, `flush`, and `shutdown`. It also provides a concrete `start_span()` method that emits `DeprecationWarning` and delegates to `span()`.

5. The module-level `Tracer = ObservabilityBackend` alias provides a stable name for consumers that type-annotate with the old name.

```python
# Context manager protocol — defined once in the ABC, inherited by all backends
def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
    if exc_val is not None:
        self.end(status="error", error=exc_val)
    else:
        self.end(status="ok")
    return False  # Never suppress exceptions
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| `__enter__`/`__exit__` implemented in the ABC, not abstract | Require subclasses to implement context manager protocol | Protocol is identical for all implementations; shared once in the ABC eliminates duplication and prevents subtle bugs |
| `__exit__` returns `False` unconditionally | Return `True` on errors to suppress | Fail-open: observability must never hide application errors from callers |
| `Trace.__exit__` does nothing (no finalization call) | Call a `trace.end()` method | Child spans manage their own lifecycle; the trace grouping object does not need explicit finalization |
| `start_span()` as a concrete method on the ABC | Delete it immediately | Backward compatibility during migration; `DeprecationWarning` surfaces the debt in CI |

**Configuration:**

This module has no configuration parameters. All behavior is fixed by the ABC contract. Provider-specific configuration lives in the provider subdirectory.

**Error behavior:**

The ABCs themselves do not raise during method dispatch. Concrete implementations are contractually required (per `Span`, `Generation` docstrings) to catch and suppress all exceptions internally, with the exception of `flush()` and `shutdown()`, which propagate SDK exceptions to callers.

Attempting to instantiate any ABC directly raises `TypeError: Can't instantiate abstract class`.

---

### `src/platform/observability/schemas.py` — Record Dataclasses

**Purpose:**

Defines three `@dataclass` types — `SpanRecord`, `TraceRecord`, and `GenerationRecord` — that represent completed observation events as plain Python objects. These types have zero third-party dependencies and are safe to import in any test environment or storage adapter without pulling in the Langfuse SDK.

**Type definitions:**

```python
@dataclass
class SpanRecord:
    name: str                          # REQ-149
    trace_id: str                      # REQ-149
    parent_span_id: Optional[str]      # REQ-149
    attributes: dict = field(default_factory=dict)
    start_ts: float = field(default_factory=time)  # REQ-155
    end_ts: Optional[float] = None     # set by end()
    status: str = "ok"                 # REQ-117
    error_message: Optional[str] = None

@dataclass
class TraceRecord:
    name: str
    trace_id: str                      # must not be None — REQ-151
    metadata: dict = field(default_factory=dict)
    start_ts: float = field(default_factory=time)
    end_ts: Optional[float] = None
    status: str = "ok"

@dataclass
class GenerationRecord:
    name: str
    trace_id: str
    model: str
    input: str
    output: Optional[str] = None       # REQ-153 — optional; may not be set in error paths
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    start_ts: float = field(default_factory=time)
    end_ts: Optional[float] = None
    status: str = "ok"
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Separate file from `backend.py` | Co-locate schemas inside `backend.py` | Storage adapters and tests import schemas without needing the full ABC hierarchy; file separation enforces this at the import level |
| `output`, `prompt_tokens`, `completion_tokens` are `Optional` | Require all `GenerationRecord` fields | These fields may legitimately be absent in error paths or streaming scenarios where `set_output()`/`set_token_counts()` are never called |
| `start_ts` defaults to `time.time()` at construction | Accept timestamp from caller | Captures the true start time automatically; callers do not need to manage timestamps |

**How it works:**

These dataclasses are passive containers — they do not compute or validate on construction. When a backend implementation finalizes an observation (calls `end()`), it populates the relevant record type with the observed values. The `start_ts` field defaults to `time()` at instantiation time, so the clock starts when the record is created, not when `end()` is called. The `end_ts` field is `None` until `end()` populates it. Both the noop backend and future backends may use these types to capture in-memory records for testing assertions.

**Configuration:**

This module has no configurable parameters. Record field defaults (`start_ts` via `default_factory=time`, `status="ok"`) are fixed at definition time and are not overridable via environment variables.

**Error behavior:**

These dataclasses do not perform validation at construction time. No exceptions are raised on instantiation regardless of field values. Type errors from incorrect field types (e.g., passing a string for `prompt_tokens`) are Python `TypeError` raised by the Python runtime, not by this module.

---

### `src/platform/observability/__init__.py` — Public API Facade

**Purpose:**

This module is the sole import surface for all consumers of the observability subsystem. It owns the process-wide backend singleton, implements the thread-safe `get_tracer()` factory, and provides the `@observe` decorator. No other module within this package is part of the public API — all other files are implementation details.

**How it works:**

1. **Singleton initialization (double-checked locking):** Module-level variables `_backend: Optional[ObservabilityBackend] = None` and `_backend_lock = threading.Lock()` are defined at import time. `get_tracer()` checks `_backend` without a lock on the fast path. On the first call, it acquires `_backend_lock`, double-checks `_backend is None`, then calls `_init_backend()`.

2. **`_init_backend()` — backend selection:** Reads `OBSERVABILITY_PROVIDER` from `config.settings` (falling back to `os.environ` if the settings module is not importable). Normalizes the value to lowercase and routes:
   - Empty string or `"noop"` → `NoopBackend()` (imported from `noop.backend`)
   - `"langfuse"` → attempts `LangfuseBackend()` inside a `try/except`; on any exception, logs a warning and falls back to `NoopBackend()`
   - Any other value → raises `ValueError` with the unrecognized provider name

3. **`@observe` decorator factory:** Returns a decorator that calls `get_tracer().span(span_name)` as a context manager around the wrapped function. Input capture (`capture_input=True`) records `repr(args[1:])[:500]` as the `"input"` span attribute, skipping `self`/`cls`. Output capture (`capture_output=True`) records `repr(result)[:500]` as `"output"`. On exception, sets `"error"` attribute to `str(exc)` and re-raises.

```python
# @observe internals
def wrapper(*args, **kwargs):
    backend = get_tracer()
    with backend.span(span_name) as span:
        if capture_input and args:
            span.set_attribute("input", repr(args[1:])[:_MAX_CAPTURE_LEN])
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            span.set_attribute("error", str(exc))
            raise
        if capture_output:
            span.set_attribute("output", repr(result)[:_MAX_CAPTURE_LEN])
        return result
```

4. **Re-exports and `__all__`:** `Span`, `Trace`, `Generation`, and `ObservabilityBackend` are re-exported from `backend.py` for consumers that need type annotations. The `Tracer = ObservabilityBackend` alias is included for backward compatibility.

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Backend selection reads `config.settings` first, then `os.environ` | Exclusively use `os.environ` | `config.settings` is the canonical configuration layer for the project; `os.environ` fallback preserves testability without the settings module |
| `_init_backend()` catches all exceptions for `langfuse` provider, but raises `ValueError` for unknown providers | Treat all errors the same (always fall back) | Unknown provider names indicate a configuration mistake that should fail loudly; Langfuse connectivity errors should be silent |
| `observe` uses a factory pattern (`observe(...)` returns a decorator) | `observe` is a direct decorator | Factory allows named parameters (`name`, `capture_input`, `capture_output`) with clean call-site syntax |
| Input capture skips `args[0]` (self/cls) | Capture all positional args | Methods are the primary decoration target; `self` is never useful in a span attribute and would be confusingly verbose |

**Configuration:**

| Parameter | Type | Default | Effect |
|---|---|---|---|
| `OBSERVABILITY_PROVIDER` | `str` env var | `"noop"` | Selects active backend: `"noop"`, `"langfuse"`, or raises `ValueError` |
| `name` (on `@observe`) | `Optional[str]` | `func.__qualname__` | Span name recorded for this function invocation |
| `capture_input` (on `@observe`) | `bool` | `False` | If `True`, records positional args (excluding self) as `"input"` attribute |
| `capture_output` (on `@observe`) | `bool` | `False` | If `True`, records return value as `"output"` attribute |
| `_MAX_CAPTURE_LEN` | `int` (module constant) | `500` | Maximum character length for captured input/output values |

**Error behavior:**

- `get_tracer()` never raises. On any `langfuse` initialization error, it falls back to `NoopBackend` and logs a warning to `rag.observability`.
- `get_tracer()` raises `ValueError` for unrecognized `OBSERVABILITY_PROVIDER` values — this is intentional; it is a configuration error, not a runtime error.
- The `@observe` decorator never suppresses application exceptions. It records the exception as an `"error"` attribute, ends the span with `status="error"`, and re-raises.
- The singleton cannot be re-initialized after first `get_tracer()` call. Tests that need a fresh backend must patch `_backend` directly.

---

### `src/platform/observability/noop/backend.py` — No-Op Backend

**Purpose:**

Provides `NoopBackend`, `NoopSpan`, `NoopTrace`, and `NoopGeneration` — concrete implementations of the observability ABCs that perform no operations whatsoever. This is the default backend when `OBSERVABILITY_PROVIDER` is unset or set to `"noop"`. It is also the automatic fallback when the configured backend fails to initialize. Every method returns immediately with a correctly typed object and zero I/O, computation, or allocation beyond the object return itself.

**How it works:**

1. **`NoopSpan(Span)`:** `set_attribute()` and `end()` are both `return` statements. The context manager protocol is inherited from the `Span` ABC — `__enter__` returns `self`, `__exit__` calls `self.end()` and returns `False`.

2. **`NoopGeneration(Generation)`:** `set_output()`, `set_token_counts()`, and `end()` are all `return` statements. Accepts any argument without raising.

3. **`NoopTrace(Trace)`:** `span()` returns a fresh `NoopSpan()`. `generation()` returns a fresh `NoopGeneration()`. Neither method raises under any input.

4. **`NoopBackend(ObservabilityBackend)`:** `span()` returns `NoopSpan()`. `trace()` returns `NoopTrace()`. `generation()` returns `NoopGeneration()`. `flush()` and `shutdown()` are `return` statements.

```python
class NoopSpan(Span):
    def set_attribute(self, key: str, value: object) -> None:
        return  # zero-cost; accepts any input

    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        return  # zero-cost; accepts any input
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| All methods are bare `return` statements | Raise `NotImplementedError` in noop | The noop backend is the production code path for non-instrumented deployments; it must be completely side-effect free |
| `NoopTrace.span()` returns `NoopSpan()` (not `self`) | Return a singleton noop span | Returns a distinct object per call to match the expected semantics; the cost of a single object allocation per call is acceptable |
| `flush()` and `shutdown()` are no-ops | Have them log a debug message | The noop backend is explicitly zero-output; even debug logging would add overhead |
| Provider is in `noop/backend.py` (subdirectory) | Flat file `noop_backend.py` | Consistent with the provider isolation pattern; allows `noop/__init__.py` to control the exported surface |

**Configuration:**

The noop backend has no configuration. It is fully operational with zero environment variables.

| Parameter | Type | Default | Effect |
|---|---|---|---|
| `OBSERVABILITY_PROVIDER` | `str` env var | `"noop"` | Set to empty or `"noop"` to activate this backend |

**Error behavior:**

The noop backend never raises under any circumstances. All methods accept any input, including `None` values, negative integers, and empty strings. This is the strictest possible implementation of the fail-open contract.

---

### `src/platform/observability/langfuse/backend.py` — Langfuse v3 Backend

**Purpose:**

Implements the observability ABC contract against the Langfuse v3 SDK. All `import langfuse` statements in the entire codebase are confined exclusively to this file (REQ-201). This module provides `LangfuseBackend`, `LangfuseSpan`, `LangfuseTrace`, and `LangfuseGeneration`. All observation methods are fail-open — SDK exceptions are caught, logged at WARNING level to `rag.observability.langfuse`, and replaced with noop fallback objects. Only `flush()` and `shutdown()` propagate SDK exceptions to callers.

**How it works:**

1. **`LangfuseBackend.__init__()`:** Executes `from langfuse import get_client` and calls `get_client()` to obtain the SDK singleton. This is the ONLY point in the codebase where `langfuse` is imported. If `get_client()` raises (e.g., missing credentials, wrong API URL), the exception propagates up to `_init_backend()` in `__init__.py`, which catches it and falls back to `NoopBackend`.

2. **`LangfuseSpan`:** Wraps a Langfuse SDK observation object (`self._inner`). `set_attribute()` calls `self._inner.update(metadata={key: value})`. `end()` calls `self._inner.update(level="ERROR", status_message=str(error))` if an error is present, then `self._inner.end()`. Both calls are wrapped in `try/except Exception`.

3. **`LangfuseGeneration`:** Wraps a Langfuse SDK generation observation. `set_output()` calls `self._inner.update(output=output)`. `set_token_counts()` maps `prompt_tokens` to `usage.input` and `completion_tokens` to `usage.output` (Langfuse v3 API convention). Both are fail-open.

4. **`LangfuseTrace`:** Wraps a Langfuse SDK trace object (`self._trace`). Child spans/generations are created through the trace object for correct parent-child correlation: `self._trace.span(name=name, metadata=attributes or {})`. If the SDK call fails, returns `NoopSpan()` or `NoopGeneration()` instead.

5. **`LangfuseBackend.span()`:** When `parent` is a `LangfuseTrace` instance, creates the span through `parent._trace.span(...)` for proper trace correlation. Otherwise, creates a top-level observation via `self._client.start_observation(as_type="span", ...)`. Fail-open — returns `NoopSpan()` on any SDK exception.

6. **`LangfuseBackend.flush()`** and **`LangfuseBackend.shutdown()`:** Call `self._client.flush()` and `self._client.shutdown()` directly, without try/except. SDK exceptions propagate to callers.

```python
class LangfuseBackend(ObservabilityBackend):
    def __init__(self) -> None:
        from langfuse import get_client  # SDK import confined here (REQ-201)
        self._client = get_client()      # Raises on misconfiguration — caller handles

    def flush(self) -> None:
        self._client.flush()             # Propagates exceptions (REQ-249)

    def shutdown(self) -> None:
        self._client.shutdown()          # Propagates exceptions (REQ-251)
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| `from langfuse import get_client` inside `__init__()`, not at module level | Module-level import at the top of `langfuse/backend.py` | Confines the import to one code path; if Langfuse is not installed, importing `src.platform.observability` does not fail |
| `flush()` and `shutdown()` propagate exceptions, all other methods are fail-open | Fail-open everywhere, including flush/shutdown | Callers that invoke `flush()` (e.g., Temporal activity teardown) need to know if data was actually written; silent failure would cause data loss that goes undetected |
| Fall back to `NoopSpan()`/`NoopGeneration()` (not silently `None`) on SDK error | Return `None` and let caller handle it | Callers always receive a valid typed object; no null checks required; the noop objects have the correct interface |
| Token counts mapped to `usage={"input": ..., "output": ...}` | Use Langfuse v2 field names | This is the Langfuse v3 SDK convention; using v2 names would cause silent data loss in the UI |

**Configuration:**

All Langfuse SDK configuration is read from environment variables by the SDK itself. This backend accepts no constructor parameters.

| Parameter | Type | Default | Effect |
|---|---|---|---|
| `LANGFUSE_PUBLIC_KEY` | `str` env var | (required) | SDK authentication public key |
| `LANGFUSE_SECRET_KEY` | `str` env var | (required) | SDK authentication secret key |
| `LANGFUSE_HOST` | `str` env var | `https://cloud.langfuse.com` | Langfuse server URL (set to `http://localhost:3000` for local Docker) |
| `OBSERVABILITY_PROVIDER` | `str` env var | — | Must be `"langfuse"` to activate this backend |

**Error behavior:**

- **Initialization:** If `get_client()` raises for any reason, the exception propagates to `_init_backend()` in `__init__.py`, which catches it, logs a warning, and instantiates `NoopBackend` instead. The application never sees the error.
- **Span/Trace/Generation creation:** All exceptions from the Langfuse SDK are caught. A `WARNING` is logged to `rag.observability.langfuse`. The failing call returns a `NoopSpan()`, `NoopTrace()`, or `NoopGeneration()` as appropriate.
- **Attribute setting:** Exceptions from `self._inner.update(...)` are caught and logged. The attribute is silently discarded.
- **`flush()`/`shutdown()`:** SDK exceptions propagate directly to callers. Callers are responsible for handling `TimeoutError`, `ConnectionError`, or any other SDK exception.

---

## 4. End-to-End Data Flow

### 4.1 Happy Path — Langfuse Active

This scenario traces a RAG retrieval request from call site through to the Langfuse UI.

**Preconditions:** `OBSERVABILITY_PROVIDER=langfuse`, Langfuse SDK configured and server reachable.

**Step 1 — Process startup (first `get_tracer()` call):**

```
_backend is None
→ acquire _backend_lock
→ _init_backend() reads OBSERVABILITY_PROVIDER="langfuse"
→ from langfuse import get_client
→ _client = get_client()  # SDK singleton, reads LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
→ LangfuseBackend instance created
→ _backend = LangfuseBackend(...)
→ release _backend_lock
```

**Step 2 — Trace creation at pipeline entry point:**

```python
with get_tracer().trace("rag.request", metadata={"user_id": uid}) as t:
```

```
get_tracer() → returns _backend (LangfuseBackend) — fast path, no lock
LangfuseBackend.trace("rag.request", {"user_id": uid})
→ self._client.trace(name="rag.request", metadata={"user_id": uid})
→ Langfuse SDK creates trace object with trace_id = "abc-123"
→ LangfuseTrace(trace_obj) returned
→ t is a LangfuseTrace wrapping the SDK trace
```

**Step 3 — Child span creation (reranker):**

```python
with t.span("reranker.rerank", {"query": query}) as span:
    span.set_attribute("doc_count", 10)
    # ... reranking logic ...
```

```
LangfuseTrace.span("reranker.rerank", {"query": query})
→ self._trace.span(name="reranker.rerank", metadata={"query": query})
→ Langfuse SDK creates span observation, parent=trace_id "abc-123"
→ LangfuseSpan(inner_obs) returned

span.set_attribute("doc_count", 10)
→ LangfuseSpan.set_attribute("doc_count", 10)
→ self._inner.update(metadata={"doc_count": 10})
→ SDK buffers the update

# context manager exits normally
LangfuseSpan.__exit__(None, None, None)
→ self.end(status="ok")
→ self._inner.end()
→ SDK marks span as complete, buffers for transmission
```

**Step 4 — Flush on request completion:**

```
get_tracer().flush()
→ LangfuseBackend.flush()
→ self._client.flush()
→ SDK transmits all buffered observations to Langfuse HTTP API
→ Langfuse server ingests, stores in langfuse-db PostgreSQL
→ Trace visible at http://localhost:3000
```

**Object shapes at each stage:**

| Stage | Object | Type |
|---|---|---|
| After `trace()` | `t` | `LangfuseTrace` wrapping Langfuse SDK trace object |
| After `t.span()` | `span` | `LangfuseSpan` wrapping Langfuse SDK observation |
| After `span.set_attribute()` | (side effect) | SDK observation updated with metadata dict |
| After `span.end()` | (side effect) | SDK observation finalized and buffered |
| After `flush()` | (side effect) | HTTP POST to Langfuse API, observation persisted |

---

### 4.2 Langfuse-Down Fallback

This scenario shows the fail-open path when Langfuse is unreachable at startup.

**Preconditions:** `OBSERVABILITY_PROVIDER=langfuse`, but Langfuse server is unreachable.

**Step 1 — Process startup (first `get_tracer()` call):**

```
_init_backend() reads OBSERVABILITY_PROVIDER="langfuse"
→ try: LangfuseBackend()
→ from langfuse import get_client
→ get_client()  # SDK tries to connect / validate credentials
→ raises ConnectionError (or any Exception)
→ except Exception as exc:
    logger.warning("Failed to initialize langfuse backend (%s); falling back to noop.", exc)
→ from src.platform.observability.noop.backend import NoopBackend
→ _backend = NoopBackend()
```

**Step 2 — All subsequent calls are zero-cost no-ops:**

```python
with get_tracer().trace("rag.request") as t:     # Returns NoopTrace()
    with t.span("reranker.rerank") as span:       # Returns NoopSpan()
        span.set_attribute("doc_count", 10)        # return (no-op)
    # No data is transmitted. No errors are raised. Application runs normally.
```

**Step 3 — Mid-request Langfuse failure (already initialized):**

If Langfuse was reachable at startup but becomes unreachable during a request:

```
LangfuseSpan.set_attribute("key", value)
→ self._inner.update(metadata={"key": value})
→ raises ConnectionError from SDK
→ except Exception as exc:
    logger.warning("LangfuseSpan.set_attribute failed: %s", exc)
→ returns None (attribute silently discarded)
# Application continues normally
```

---

### 4.3 `@observe` Decorator Path

This scenario shows the decorator path for a simple function annotation.

**Setup:**

```python
from src.platform.observability import observe

@observe("reranker.rerank", capture_input=True, capture_output=False)
def rerank(self, query: str, documents: list) -> list:
    # ... reranking logic ...
    return ranked_docs
```

**At decoration time (import/class definition):**

```
observe("reranker.rerank", capture_input=True, capture_output=False)
→ returns decorator
decorator(rerank)
→ span_name = "reranker.rerank"
→ functools.wraps(rerank)(wrapper)
→ rerank is now wrapper, preserving __name__, __qualname__, __doc__
```

**At call time (`reranker.rerank(query="Paris", documents=[...])`)**:

```
wrapper(self, query, documents)
→ backend = get_tracer()        # fast path — no lock
→ backend.span("reranker.rerank")  # returns LangfuseSpan or NoopSpan
→ with backend.span("reranker.rerank") as span:
    # capture_input=True: args = (self, query, documents)
    span.set_attribute("input", repr((query, documents))[:500])
    try:
        result = rerank(self, query, documents)  # original function
    except Exception as exc:
        span.set_attribute("error", str(exc))
        raise  # always re-raises; @observe never suppresses
    # capture_output=False: skip
    return result
# context manager exits → span.end(status="ok")
```

**State at each point:**

| Point | State |
|---|---|
| Before `wrapper` entry | `_backend` already initialized (singleton) |
| `backend.span(...)` | New span object created, start timestamp set |
| `set_attribute("input", ...)` | Input repr recorded as span attribute (truncated to 500 chars) |
| Exception path | `"error"` attribute set, span ends with `status="error"`, exception re-raised |
| Normal exit | `capture_output=False`: no output attribute. Span ends with `status="ok"` |

---

## 5. Configuration Reference

### 5.1 Backend Selection

| Variable | Values | Default | Behavior |
|---|---|---|---|
| `OBSERVABILITY_PROVIDER` | `"noop"` | `"noop"` | Zero-cost no-op backend. Default when unset. |
| `OBSERVABILITY_PROVIDER` | `"langfuse"` | — | Langfuse v3 backend. Initializes SDK at first `get_tracer()` call. |
| `OBSERVABILITY_PROVIDER` | any other value | — | `ValueError` raised at first `get_tracer()` call. |

### 5.2 Langfuse SDK Configuration

These variables are read by the Langfuse SDK inside `LangfuseBackend.__init__()`. They are not read by any Python code in this package.

| Variable | Required | Default | Description |
|---|---|---|---|
| `LANGFUSE_PUBLIC_KEY` | Yes (langfuse provider) | — | API public key from Langfuse project settings |
| `LANGFUSE_SECRET_KEY` | Yes (langfuse provider) | — | API secret key from Langfuse project settings |
| `LANGFUSE_HOST` | No | `https://cloud.langfuse.com` | Langfuse server URL. Set to `http://localhost:3000` for local Docker. |

### 5.3 Docker Compose (Langfuse Services)

Langfuse services are in `docker-compose.yml` under `profiles: ["observability"]`. Start with:

```bash
docker compose --profile observability up -d
```

| Variable | Service | Description |
|---|---|---|
| `LANGFUSE_PORT` | `langfuse` | Host port for Langfuse UI (default `3000`) |
| `LANGFUSE_NEXTAUTH_SECRET` | `langfuse` | Random secret for NextAuth session signing |
| `LANGFUSE_SALT` | `langfuse` | Salt for password hashing |
| `LANGFUSE_ENCRYPTION_KEY` | `langfuse` | 32-char encryption key for sensitive data |
| `LANGFUSE_INIT_ORG_ID` | `langfuse` | Organization ID for initial setup |
| `LANGFUSE_INIT_PROJECT_ID` | `langfuse` | Project ID for initial setup |

### 5.4 `@observe` Decorator Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `Optional[str]` | `func.__qualname__` | Span name. Use convention `"component.operation"`. |
| `capture_input` | `bool` | `False` | Record positional args (excluding self/cls) as `"input"` attribute, truncated at 500 chars. |
| `capture_output` | `bool` | `False` | Record return value as `"output"` attribute, truncated at 500 chars. |

---

## 6. Integration Contracts

### 6.1 Consumer Import Contract

The only permitted import pattern for consumers is:

```python
from src.platform.observability import get_tracer, observe
```

Importing from any sub-module (e.g., `from src.platform.observability.langfuse import ...` or `from src.platform.observability.providers import ...`) is prohibited. The sub-module paths are implementation details subject to change without notice.

### 6.2 Type Annotation Contract

Consumers that need type annotations should use the types re-exported from the public API:

```python
from src.platform.observability import ObservabilityBackend, Span, Trace, Generation
```

The `Tracer` alias is available but deprecated — use `ObservabilityBackend`.

### 6.3 Span Usage Contract

Two usage patterns are supported and should be chosen as follows:

**Pattern A — Context manager (recommended for most cases):**

```python
with get_tracer().span("component.operation") as span:
    span.set_attribute("key", value)
    result = do_work()
# span.end() is called automatically
```

**Pattern B — `@observe` decorator (recommended for full-function tracing):**

```python
@observe("component.operation")
def my_function(self, arg):
    return do_work(arg)
```

**Pattern C — Trace grouping (recommended for pipeline entry points):**

```python
with get_tracer().trace("pipeline.request", metadata={"request_id": rid}) as trace:
    with trace.span("stage.one") as s1:
        s1.set_attribute("key", val)
    with trace.generation("llm.call", model="gpt-4o", input=prompt) as gen:
        result = call_llm(prompt)
        gen.set_output(result)
        gen.set_token_counts(100, 42)
```

### 6.4 Flush Contract

Callers responsible for process lifecycle (Temporal workers, test teardown) must call `flush()` before process exit to ensure buffered observations are transmitted:

```python
try:
    get_tracer().flush()
except Exception as exc:
    logger.error("Observability flush failed: %s", exc)
```

`flush()` propagates SDK exceptions. Callers must handle or log them.

### 6.5 Test Contract

Tests must not require a live Langfuse server. The recommended approach is:

```python
# Use noop backend in all tests (default when OBSERVABILITY_PROVIDER is unset)
# Or patch the singleton directly for backend-specific tests:
import src.platform.observability as obs_module

def test_something(monkeypatch):
    monkeypatch.setattr(obs_module, "_backend", None)  # reset singleton
    monkeypatch.setenv("OBSERVABILITY_PROVIDER", "noop")
    # test code here
```

---

## 7. Operational Notes

### 7.1 Starting Langfuse Locally

```bash
# Start Langfuse and its PostgreSQL dependency
docker compose --profile observability up -d

# Verify health
curl http://localhost:3000/api/public/health

# Access UI
open http://localhost:3000
```

### 7.2 Enabling Observability in the Application

```bash
# In your .env or shell:
OBSERVABILITY_PROVIDER=langfuse
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3000

# Restart the application process
```

### 7.3 Verifying the Active Backend

```python
from src.platform.observability import get_tracer
backend = get_tracer()
print(type(backend).__name__)  # "NoopBackend" or "LangfuseBackend"
```

### 7.4 Diagnosing Silent Fallback

If `get_tracer()` returns `NoopBackend` when `langfuse` was expected:

1. Check the `rag.observability` logger at WARNING level. The fallback always logs: `"Failed to initialize langfuse backend (...); falling back to noop."`
2. Verify `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST` are set correctly.
3. Verify the Langfuse Docker services are running: `docker compose ps`.
4. Check that the `langfuse` Python package is installed: `uv pip show langfuse`.

### 7.5 Flushing in Temporal Workers

Temporal activities are short-lived. Add flush to the activity teardown:

```python
from src.platform.observability import get_tracer

async def my_activity():
    try:
        result = do_work()
        return result
    finally:
        get_tracer().flush()
```

### 7.6 Log Reference

| Logger | Level | Message Pattern | Trigger |
|---|---|---|---|
| `rag.observability` | `WARNING` | `Failed to initialize langfuse backend (...); falling back to noop.` | Langfuse SDK raises during `LangfuseBackend.__init__()` |
| `rag.observability.langfuse` | `WARNING` | `LangfuseSpan.set_attribute failed: ...` | SDK raises during attribute update |
| `rag.observability.langfuse` | `WARNING` | `LangfuseSpan.end failed: ...` | SDK raises during span finalization |
| `rag.observability.langfuse` | `WARNING` | `LangfuseTrace.span failed: ...` | SDK raises during child span creation |
| `rag.observability.langfuse` | `WARNING` | `LangfuseBackend.span failed: ...` | SDK raises during top-level span creation |

---

## 8. Known Limitations

**1. No distributed context propagation.** The current implementation does not propagate trace context across process or service boundaries. Each process has its own singleton backend and its own trace IDs. Cross-service trace correlation requires manual trace ID passing.

**2. No automatic LLM call interception.** The `@observe` decorator and `generation()` factory require explicit instrumentation at each LLM call site. There is no automatic hook into LLM provider SDKs.

**3. Singleton cannot be swapped at runtime.** The backend is initialized once per process at the first `get_tracer()` call. Switching providers requires a process restart.

**4. Silent data loss on Langfuse failure.** When a span's `set_attribute()` or `end()` fails, the span data is silently discarded (logged at WARNING only). There is no retry, dead-letter queue, or metric for dropped observations.

**5. No PII redaction.** Captured input/output values (via `capture_input=True`/`capture_output=True`) are stored as-is. `repr()` is applied but may include sensitive data if the argument objects contain it.

**6. `capture_input` uses `repr()`.** Input capture calls `repr(args[1:])`, which may produce unreadable output for complex objects and will invoke arbitrary `__repr__` methods.

**7. No multi-tenant trace isolation.** All traces share the same Langfuse project. Per-user or per-tenant trace namespacing is not implemented.

**8. `flush()` and `shutdown()` are synchronous.** In async code paths, these calls block the event loop. Wrap them in `asyncio.get_event_loop().run_in_executor(None, get_tracer().flush)` if needed.

---

## 9. Extension Guide — Adding a New Backend

This guide shows how to add a LangSmith backend as a concrete example. The same steps apply for any other provider (OpenTelemetry, DataDog, etc.).

### Step 1 — Create the provider subdirectory

```bash
mkdir src/platform/observability/langsmith
touch src/platform/observability/langsmith/__init__.py
touch src/platform/observability/langsmith/backend.py
```

### Step 2 — Implement the backend in `langsmith/backend.py`

```python
# src/platform/observability/langsmith/backend.py
# @summary
# LangSmith backend implementation for the observability subsystem.
# Exports: LangSmithBackend
# Deps: langsmith (SDK — all imports confined here), src.platform.observability.backend
# @end-summary
"""LangSmith backend implementation.

All imports from the langsmith package are confined exclusively to this file.
"""
from __future__ import annotations
import logging
from typing import Optional

from src.platform.observability.backend import (
    Generation, ObservabilityBackend, Span, Trace,
)
from src.platform.observability.noop.backend import NoopSpan, NoopTrace, NoopGeneration

logger = logging.getLogger("rag.observability.langsmith")


class LangSmithSpan(Span):
    def __init__(self, inner_run) -> None:
        self._inner = inner_run

    def set_attribute(self, key: str, value: object) -> None:
        try:
            self._inner.update(extra={key: value})
        except Exception as exc:
            logger.warning("LangSmithSpan.set_attribute failed: %s", exc)

    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        try:
            self._inner.end(error=str(error) if error else None)
        except Exception as exc:
            logger.warning("LangSmithSpan.end failed: %s", exc)


# ... LangSmithGeneration, LangSmithTrace similarly ...


class LangSmithBackend(ObservabilityBackend):
    def __init__(self) -> None:
        from langsmith import Client  # SDK import confined here
        self._client = Client()

    def span(self, name: str, attributes=None, parent=None) -> Span:
        try:
            run = self._client.create_run(name=name, run_type="chain", inputs=attributes or {})
            return LangSmithSpan(run)
        except Exception as exc:
            logger.warning("LangSmithBackend.span failed: %s", exc)
            return NoopSpan()

    # ... trace(), generation(), flush(), shutdown() ...
```

### Step 3 — Export from `__init__.py` in the subdirectory

```python
# src/platform/observability/langsmith/__init__.py
from src.platform.observability.langsmith.backend import LangSmithBackend

__all__ = ["LangSmithBackend"]
```

### Step 4 — Register the provider in `__init__.py`

Open `src/platform/observability/__init__.py` and add a branch in `_init_backend()`:

```python
if provider == "langsmith":
    try:
        from src.platform.observability.langsmith.backend import LangSmithBackend
        return LangSmithBackend()
    except Exception as exc:
        logger.warning(
            "Failed to initialize langsmith backend (%s); falling back to noop.",
            exc,
        )
        from src.platform.observability.noop.backend import NoopBackend
        return NoopBackend()
```

### Step 5 — Update the ValueError message

Update the `ValueError` in `_init_backend()` to include the new provider name:

```python
raise ValueError(
    f"Unknown OBSERVABILITY_PROVIDER: {provider!r}. "
    "Valid values: 'noop', 'langfuse', 'langsmith'."
)
```

### Step 6 — Update configuration documentation

- Add `LANGSMITH_API_KEY` (and any other required variables) to `.env.example` with placeholder values.
- Update `docs/observability/OBSERVABILITY_ENGINEERING_GUIDE.md` Configuration Reference (Section 5).

### Step 7 — Write tests

Following the test contract (Section 6.5), add tests to `tests/platform/observability/langsmith/`:

- Unit tests that mock the LangSmith SDK client.
- Verify fail-open: inject exceptions into SDK methods, verify no propagation.
- Verify `flush()` and `shutdown()` propagate exceptions.
- Verify all concrete classes pass `isinstance(obj, <ABC>)` checks.

### Step 8 — Update `@summary` blocks

Add `@summary` / `@end-summary` comment blocks to `langsmith/backend.py` and `langsmith/__init__.py`, then run `context-agent update` to refresh the directory README.md chain.

---

## 10. Requirement Coverage Appendix

This appendix maps every requirement from `docs/observability/OBSERVABILITY_SPEC.md` to the module that implements it.

### REQ-1xx — Backend Abstraction

| REQ | Priority | Description (abbreviated) | Implemented in |
|---|---|---|---|
| REQ-101 | MUST | `ObservabilityBackend` is an ABC with 5 abstract methods | `backend.py` — `ObservabilityBackend` class |
| REQ-103 | MUST | `backend.span()` returns `Span` instance | `backend.py` — `ObservabilityBackend.span()` signature |
| REQ-105 | MUST | `backend.trace()` returns `Trace` instance | `backend.py` — `ObservabilityBackend.trace()` signature |
| REQ-107 | MUST | `backend.generation()` returns `Generation` instance | `backend.py` — `ObservabilityBackend.generation()` signature |
| REQ-109 | MUST | `flush()` is abstract; drains pending writes | `backend.py` — `ObservabilityBackend.flush()` |
| REQ-111 | MUST | `shutdown()` is abstract; subsequent calls do not raise | `backend.py` — `ObservabilityBackend.shutdown()` |
| REQ-113 | MUST | `Span` ABC with abstract `set_attribute`, `end` | `backend.py` — `Span` class |
| REQ-115 | MUST | `set_attribute` accepts any Python object | `backend.py` — `Span.set_attribute()` |
| REQ-117 | MUST | `Span.end()` accepts `status` and `error` | `backend.py` — `Span.end()` |
| REQ-119 | MUST | `Span.__enter__` returns `self` | `backend.py` — `Span.__enter__()` |
| REQ-121 | MUST | `Span.__exit__` calls `end()` correctly, returns `False` | `backend.py` — `Span.__exit__()` |
| REQ-123 | MUST | Exceptions in `set_attribute`/`end` caught internally | `noop/backend.py`, `langfuse/backend.py` |
| REQ-125 | MUST | `Trace` ABC with abstract `span`, `generation` | `backend.py` — `Trace` class |
| REQ-127 | MUST | `Trace.span()` child shares `trace_id` | `langfuse/backend.py` — `LangfuseTrace.span()` |
| REQ-129 | MUST | `Trace.generation()` child shares `trace_id` | `langfuse/backend.py` — `LangfuseTrace.generation()` |
| REQ-131 | MUST | `Trace.__enter__` returns `self` | `backend.py` — `Trace.__enter__()` |
| REQ-133 | MUST | `Trace.__exit__` returns `False` | `backend.py` — `Trace.__exit__()` |
| REQ-135 | MUST | Exceptions in `Trace.span()`/`Trace.generation()` caught | `langfuse/backend.py` — `LangfuseTrace.span()`, `.generation()` |
| REQ-137 | MUST | `Generation` ABC with abstract methods | `backend.py` — `Generation` class |
| REQ-139 | MUST | `Generation.set_output()` stores output | `langfuse/backend.py` — `LangfuseGeneration.set_output()` |
| REQ-141 | MUST | `Generation.set_token_counts()` stores counts | `langfuse/backend.py` — `LangfuseGeneration.set_token_counts()` |
| REQ-143 | MUST | `Generation.end()` follows same contract as `Span.end()` | `langfuse/backend.py`, `noop/backend.py` |
| REQ-145 | MUST | `Generation.__enter__` returns `self`, `__exit__` returns `False` | `backend.py` — `Generation.__enter__()`, `.__exit__()` |
| REQ-147 | MUST | Exceptions in `Generation` methods caught internally | `langfuse/backend.py` — all `LangfuseGeneration` methods |
| REQ-149 | MUST | `SpanRecord` dataclass with all required fields | `schemas.py` — `SpanRecord` |
| REQ-151 | MUST | `TraceRecord` dataclass with all required fields | `schemas.py` — `TraceRecord` |
| REQ-153 | MUST | `GenerationRecord` dataclass with optional output/token fields | `schemas.py` — `GenerationRecord` |
| REQ-155 | MUST | `start_ts`/`end_ts` use `time.time()` | `schemas.py` — `field(default_factory=time)` |
| REQ-157 | SHOULD | Schemas importable without any backend dependency | `schemas.py` — zero third-party imports |
| REQ-159 | MUST | `NoopBackend` is a concrete subclass of `ObservabilityBackend` | `noop/backend.py` — `NoopBackend` |
| REQ-161 | MUST | All `NoopBackend` methods return typed noop objects, never raise | `noop/backend.py` — all methods |
| REQ-163 | MUST | `NoopBackend.flush()` is a no-op | `noop/backend.py` — `NoopBackend.flush()` |
| REQ-165 | MUST | `NoopBackend.shutdown()` is a no-op | `noop/backend.py` — `NoopBackend.shutdown()` |
| REQ-167 | MUST | `start_span()` deprecated alias on `ObservabilityBackend` | `backend.py` — `ObservabilityBackend.start_span()` |
| REQ-169 | MUST | `start_span()` emits `DeprecationWarning` | `backend.py` — `ObservabilityBackend.start_span()` |
| REQ-171 | MUST | `start_span()` delegates to `span()` | `backend.py` — `ObservabilityBackend.start_span()` |

### REQ-2xx — Langfuse Backend

| REQ | Priority | Description (abbreviated) | Implemented in |
|---|---|---|---|
| REQ-201 | MUST | All langfuse SDK imports confined to `langfuse/backend.py` | `langfuse/backend.py` — `__init__()` deferred import |
| REQ-203 | MUST | `LangfuseBackend` is concrete subclass of `ObservabilityBackend` | `langfuse/backend.py` — `LangfuseBackend` |
| REQ-205 | MUST | `LangfuseBackend.__init__()` accepts no credential params | `langfuse/backend.py` — `LangfuseBackend.__init__()` |
| REQ-207 | MUST | `LangfuseBackend.__init__()` propagates SDK exceptions | `langfuse/backend.py` — no try/except in `__init__()` |
| REQ-209 | MUST | `LangfuseBackend.span()` is fail-open | `langfuse/backend.py` — `LangfuseBackend.span()` try/except |
| REQ-211 | MUST | `LangfuseBackend.span()` returns `LangfuseSpan` | `langfuse/backend.py` — `LangfuseBackend.span()` |
| REQ-213 | MUST | `LangfuseBackend.span()` returns `NoopSpan` on error | `langfuse/backend.py` — exception handler |
| REQ-215 | MUST | `LangfuseBackend.trace()` is fail-open | `langfuse/backend.py` — `LangfuseBackend.trace()` try/except |
| REQ-217 | MUST | `LangfuseBackend.trace()` returns `LangfuseTrace` | `langfuse/backend.py` — `LangfuseBackend.trace()` |
| REQ-219 | MUST | `LangfuseBackend.trace()` returns `NoopTrace` on error | `langfuse/backend.py` — exception handler |
| REQ-221 | MUST | `LangfuseBackend.generation()` is fail-open | `langfuse/backend.py` — `LangfuseBackend.generation()` |
| REQ-223 | MUST | `LangfuseSpan.set_attribute()` maps to SDK `update(metadata=...)` | `langfuse/backend.py` — `LangfuseSpan.set_attribute()` |
| REQ-225 | MUST | `LangfuseSpan.set_attribute()` is fail-open | `langfuse/backend.py` — try/except in `set_attribute()` |
| REQ-227 | MUST | `LangfuseSpan.end()` calls SDK `end()` | `langfuse/backend.py` — `LangfuseSpan.end()` |
| REQ-229 | MUST | `LangfuseSpan.end()` calls `update(level="ERROR")` on error | `langfuse/backend.py` — `LangfuseSpan.end()` |
| REQ-231 | MUST | `LangfuseSpan.end()` is fail-open | `langfuse/backend.py` — try/except in `end()` |
| REQ-233 | MUST | `LangfuseGeneration.set_output()` maps to SDK `update(output=...)` | `langfuse/backend.py` — `LangfuseGeneration.set_output()` |
| REQ-235 | MUST | `LangfuseGeneration.set_token_counts()` maps to `usage` dict | `langfuse/backend.py` — `LangfuseGeneration.set_token_counts()` |
| REQ-237 | MUST | `LangfuseTrace.span()` creates child via trace object | `langfuse/backend.py` — `LangfuseTrace.span()` |
| REQ-239 | MUST | `LangfuseTrace.span()` returns `NoopSpan` on error | `langfuse/backend.py` — exception handler |
| REQ-241 | MUST | `LangfuseTrace.generation()` creates child via trace object | `langfuse/backend.py` — `LangfuseTrace.generation()` |
| REQ-243 | MUST | `LangfuseTrace.generation()` returns `NoopGeneration` on error | `langfuse/backend.py` — exception handler |
| REQ-245 | MUST | `LangfuseBackend.span()` routes through trace when parent is `LangfuseTrace` | `langfuse/backend.py` — `isinstance(parent, LangfuseTrace)` check |
| REQ-247 | MUST | All Langfuse SDK exceptions logged at WARNING | `langfuse/backend.py` — `logger.warning(...)` in all except blocks |
| REQ-249 | MUST | `LangfuseBackend.flush()` propagates SDK exceptions | `langfuse/backend.py` — `LangfuseBackend.flush()` (no try/except) |
| REQ-251 | MUST | `LangfuseBackend.shutdown()` propagates SDK exceptions | `langfuse/backend.py` — `LangfuseBackend.shutdown()` (no try/except) |

### REQ-3xx — Public API and Decorators

| REQ | Priority | Description (abbreviated) | Implemented in |
|---|---|---|---|
| REQ-301 | MUST | `get_tracer()` is the only API to obtain the backend | `__init__.py` — `get_tracer()` |
| REQ-303 | MUST | `get_tracer()` returns the same instance on every call | `__init__.py` — singleton pattern |
| REQ-305 | MUST | Singleton initialized on first call (lazy) | `__init__.py` — `if _backend is not None: return _backend` |
| REQ-307 | MUST | Singleton initialization is thread-safe | `__init__.py` — `threading.Lock()` with double-checked locking |
| REQ-309 | MUST | `OBSERVABILITY_PROVIDER=noop` → `NoopBackend` | `__init__.py` — `_init_backend()` |
| REQ-311 | MUST | `OBSERVABILITY_PROVIDER=langfuse` → `LangfuseBackend` | `__init__.py` — `_init_backend()` |
| REQ-313 | MUST | Unknown `OBSERVABILITY_PROVIDER` → `ValueError` | `__init__.py` — `_init_backend()` raise |
| REQ-315 | MUST | Langfuse init failure → falls back to `NoopBackend`, logs warning | `__init__.py` — `_init_backend()` try/except |
| REQ-317 | MUST | `get_tracer()` never raises | `__init__.py` — fail-open init |
| REQ-319 | MUST | `observe()` decorator factory returns decorator | `__init__.py` — `observe()` |
| REQ-321 | MUST | `observe()` uses `functools.wraps` | `__init__.py` — `@functools.wraps(func)` |
| REQ-323 | MUST | `observe()` wraps function with `get_tracer().span()` | `__init__.py` — `with backend.span(span_name) as span:` |
| REQ-325 | MUST | `observe()` defaults `name` to `func.__qualname__` | `__init__.py` — `span_name = name if name is not None else func.__qualname__` |
| REQ-327 | MUST | `observe(capture_input=True)` records `repr(args[1:])` | `__init__.py` — `span.set_attribute("input", ...)` |
| REQ-329 | MUST | `observe()` captured values truncated at 500 chars | `__init__.py` — `[:_MAX_CAPTURE_LEN]` |
| REQ-331 | MUST | `observe()` records exception as `"error"` attribute | `__init__.py` — `span.set_attribute("error", str(exc))` |
| REQ-333 | MUST | `observe()` re-raises exceptions | `__init__.py` — `raise` |
| REQ-335 | MUST | `observe(capture_output=True)` records `repr(result)` | `__init__.py` — `span.set_attribute("output", ...)` |
| REQ-337 | MUST | `__all__` exports `get_tracer`, `observe`, `Tracer`, `Span`, `Trace`, `Generation` | `__init__.py` — `__all__ = [...]` |
| REQ-339 | MUST | `capture_input` and `capture_output` default to `False` | `__init__.py` — `observe(capture_input: bool = False, ...)` |
| REQ-341 | MUST | `providers.py` emits `DeprecationWarning` on import | `providers.py` — `warnings.warn(...)` at module level |

### REQ-4xx — Consumer Integration

| REQ | Priority | Description (abbreviated) | Implemented in |
|---|---|---|---|
| REQ-401 | MUST | All consumers import only from `src.platform.observability` | `retrieval/query/nodes/reranker.py`, `retrieval/generation/nodes/generator.py`, `retrieval/pipeline/rag_chain.py`, others |
| REQ-403 | MUST | No consumer imports from provider subdirectory | (structural enforcement — sub-modules are not in `__all__`) |
| REQ-405 | MUST | No consumer uses `start_span()` | Migrated call sites |
| REQ-407 | MUST | Retrieval reranker uses `get_tracer().span()` | `retrieval/query/nodes/reranker.py` |
| REQ-409 | MUST | Retrieval generator uses `generation()` | `retrieval/generation/nodes/generator.py` |
| REQ-411 | MUST | RAG chain uses `trace()` at entry point | `retrieval/pipeline/rag_chain.py` |
| REQ-413 | MUST | `@observe` decorator used where appropriate | Consumer files |
| REQ-415 | MUST | Module-level `_tracer_instance` globals removed | Migrated consumer files |
| REQ-421 | MUST | Backward-compat aliases (`Tracer`, `start_span`) preserved | `backend.py`, `__init__.py` |
| REQ-423 | MUST | `Tracer` alias emits `DeprecationWarning` on use | `backend.py` — `Tracer = ObservabilityBackend` (documented) |

### REQ-5xx — Infrastructure

| REQ | Priority | Description (abbreviated) | Implemented in |
|---|---|---|---|
| REQ-501 | MUST | `langfuse` Docker service defined with `profile: observability` | `docker-compose.yml` |
| REQ-503 | MUST | `langfuse-db` PostgreSQL service defined | `docker-compose.yml` |
| REQ-505 | MUST | `langfuse` depends on `langfuse-db` with `service_healthy` | `docker-compose.yml` |
| REQ-507 | MUST | `langfuse-db` has health check | `docker-compose.yml` |
| REQ-509 | MUST | `langfuse` UI accessible at `http://localhost:3000` | `docker-compose.yml` |
| REQ-511 | MUST | `langfuse-db-data` named volume defined | `docker-compose.yml` |
| REQ-513 | MUST | `.env.example` updated with Langfuse vars | `.env.example` |

### REQ-9xx — Non-Functional Requirements

| REQ | Priority | Description (abbreviated) | Implemented in |
|---|---|---|---|
| REQ-901 | MUST | Fail-open: backend errors never propagate to application | `langfuse/backend.py` — all try/except blocks |
| REQ-903 | MUST | `NoopBackend` has zero I/O and zero side effects | `noop/backend.py` — bare `return` statements |
| REQ-905 | MUST | Backend selection requires no code change | `__init__.py` — `_init_backend()` env-var routing |
| REQ-907 | MUST | Langfuse SDK imports never escape `langfuse/backend.py` | `langfuse/backend.py` — deferred import in `__init__()` |
| REQ-909 | MUST | `get_tracer()` is thread-safe | `__init__.py` — double-checked locking |
| REQ-911 | MUST | No consumer sees SDK types in type signatures | `backend.py` — ABC types only in public signatures |
| REQ-913 | SHOULD | `@observe` preserves function metadata | `__init__.py` — `functools.wraps` |
| REQ-915 | MUST | `flush()` / `shutdown()` propagate exceptions | `langfuse/backend.py`, `noop/backend.py` |
| REQ-917 | MUST | Langfuse SDK errors logged at WARNING | `langfuse/backend.py` — `logger.warning(...)` |
| REQ-919 | MUST | Stable public API — `__init__.py` is only import surface | `__init__.py` — `__all__` |
| REQ-921 | MUST | Noop backend requires no third-party dependencies | `noop/backend.py` — zero external imports |
| REQ-923 | MUST | Schema types require no third-party dependencies | `schemas.py` — zero external imports |
| REQ-925 | MUST | Tests must not require live Langfuse server | Test contract (Section 6.5) |
| REQ-927 | SHOULD | `DeprecationWarning` on use of deprecated symbols | `backend.py`, `providers.py`, `__init__.py` |
| REQ-929 | MUST | `capture_input=False` by default (avoid accidental PII logging) | `__init__.py` — `observe()` defaults |
| REQ-931 | MUST | Captured values truncated at 500 characters | `__init__.py` — `_MAX_CAPTURE_LEN = 500` |
| REQ-933 | MUST | Exceptions in decorated functions always re-raised | `__init__.py` — `observe()` wrapper `raise` |
| REQ-935 | MUST | No module-level SDK imports outside provider subdirectory | Verified across all modules |
| REQ-937 | MUST | Docker services follow profile opt-in pattern | `docker-compose.yml` — `profiles: [observability]` |
| REQ-939 | MUST | Langfuse service has a health check | `docker-compose.yml` |
| REQ-941 | MUST | `providers.py` emits `DeprecationWarning` at import time | `providers.py` — module-level `warnings.warn()` |
