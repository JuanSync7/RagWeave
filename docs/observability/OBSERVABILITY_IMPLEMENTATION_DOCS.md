# Swappable Observability Subsystem — Implementation Docs

| Field | Value |
|---|---|
| System | Swappable Observability Subsystem |
| Spec | `docs/observability/OBSERVABILITY_SPEC.md` |
| Design doc | `docs/observability/OBSERVABILITY_DESIGN.md` |
| Output | `docs/observability/OBSERVABILITY_IMPLEMENTATION_DOCS.md` |
| Date | 2026-03-27 |
| Produced by | Claude Code (claude-sonnet-4-6) |

---

## Table of Contents

1. [Phase 0: Contract Definitions](#phase-0-contract-definitions)
2. [Task 1: Backend ABC and Schema Types](#task-1-backend-abc-and-schema-types)
3. [Task 2: NoopBackend Package](#task-2-noopbackend-package)
4. [Task 3: LangfuseBackend Package](#task-3-langfusebackend-package)
5. [Task 4: Public API Facade, Singleton Factory, and @observe Decorator](#task-4-public-api-facade-singleton-factory-and-observe-decorator)
6. [Task 5: Migrate Retrieval Consumers](#task-5-migrate-retrieval-consumers)
7. [Task 6: Migrate Ingest Consumers](#task-6-migrate-ingest-consumers)
8. [Task 7: Docker Compose Langfuse Services and .env.example](#task-7-docker-compose-langfuse-services-and-envexample)
9. [Module Boundary Map](#module-boundary-map)
10. [Dependency Graph](#dependency-graph)
11. [Task-to-FR Traceability Table](#task-to-fr-traceability-table)

---

## Phase 0: Contract Definitions

This section defines the exact code contracts used across all tasks. Every task section inlines the contracts it needs — agents do not need to consult this section directly, but it is the canonical source of truth for all contracts.

### Error Taxonomy

| Exception | Raised By | When | Propagates? |
|---|---|---|---|
| `ValueError` | `_init_backend()` | Unknown `OBSERVABILITY_PROVIDER` value | Yes — startup error |
| Any SDK exception | `LangfuseBackend.__init__` | `get_client()` fails (no keys, network) | Yes — factory catches and falls back |
| Any SDK exception | `LangfuseBackend.flush()`, `LangfuseBackend.shutdown()` | SDK flush/shutdown fails | Yes — callers must handle |
| Any exception | All other `LangfuseSpan`, `LangfuseTrace`, `LangfuseGeneration` methods | SDK call fails | No — caught, logged as warning, returns silently |
| `TypeError` | `ObservabilityBackend`, `Span`, `Trace`, `Generation` (ABCs) | Instantiated directly or subclass missing abstract method | Yes — Python ABC enforcement |

### Integration Contracts

```
Consumer call site
    → get_tracer() [__init__.py]
        → _backend singleton (ObservabilityBackend)
            → backend.span() / backend.trace() / backend.generation()
                → LangfuseSpan / LangfuseTrace / LangfuseGeneration  OR  NoopSpan / NoopTrace / NoopGeneration
                    → (Langfuse path) Langfuse SDK → HTTP → Langfuse Docker service
                    → (Noop path) immediate return, no I/O

Error propagation:
  LangfuseSpan/Trace/Generation methods → catch all → log warning → return None (fail-open)
  LangfuseBackend.flush() / .shutdown() → propagate SDK exceptions to caller
  _init_backend() ValueError → propagates to first get_tracer() caller
  LangfuseBackend.__init__ exception → caught by _init_backend() → NoopBackend fallback + warning log
```

### B.1 CONTRACT: backend.py — ObservabilityBackend ABC and Sub-types

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

    def start_span(
        self,
        name: str,
        attributes: Optional[dict] = None,
        parent: Optional["Span"] = None,
    ) -> "Span":
        """Deprecated alias for span(). Use span() instead."""
        import warnings
        warnings.warn(
            "start_span() is deprecated; use span() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.span(name, attributes, parent)


# Backward-compatible alias — deprecated, use ObservabilityBackend
Tracer = ObservabilityBackend
```

### B.2 CONTRACT: schemas.py — Record Dataclasses

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

### B.3 CONTRACT: noop/backend.py — NoopBackend

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

### B.4 CONTRACT: __init__.py — Public API Stubs

```python
# src/platform/observability/__init__.py  (stubs — implement using double-checked locking)
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
    raise NotImplementedError("Task 4")  # Task 3.1


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
    raise NotImplementedError("Task 4")  # Task 3.1


def _init_backend() -> ObservabilityBackend:
    """Initialize and return the backend based on OBSERVABILITY_PROVIDER.

    Called once at first get_tracer() invocation. Not intended for direct use.

    Returns:
        The initialized ObservabilityBackend.

    Notes:
        Falls back to NoopBackend on any initialization error, logging a warning.
        Raises ValueError for unknown OBSERVABILITY_PROVIDER values.
    """
    raise NotImplementedError("Task 4")  # Task 3.1


# Deprecated alias — use ObservabilityBackend
Tracer = ObservabilityBackend  # Simple alias; DeprecationWarning via providers.py shim

__all__ = ["get_tracer", "observe", "Tracer", "Span", "Trace", "Generation"]
```

---

## Task 1: Backend ABC and Schema Types

### Agent Isolation Contract

You have access to:
- The Phase 0 contracts inlined below (B.1 and B.2) — implement them exactly as written
- `src/platform/observability/` directory — you are creating two new files here
- `src/platform/observability/contracts.py` — read it before deleting to verify no content is lost
- `src/platform/schemas/observability.py` — read it before modifying to add re-exports

You do NOT have access to any other task's context. Do not import from `noop/`, `langfuse/`, or `__init__.py`.

### Design Task Reference

Task 1.1

### Target Files

| File | Action |
|---|---|
| `src/platform/observability/backend.py` | CREATE |
| `src/platform/observability/schemas.py` | CREATE |
| `src/platform/observability/contracts.py` | DELETE |
| `src/platform/schemas/observability.py` | MODIFY — add re-exports for backward compat |

### Requirements Covered

REQ-101, REQ-103, REQ-105, REQ-107, REQ-109, REQ-111, REQ-113, REQ-115, REQ-117, REQ-119, REQ-121, REQ-123, REQ-125, REQ-127, REQ-129, REQ-131, REQ-133, REQ-135, REQ-137, REQ-139, REQ-141, REQ-143, REQ-145, REQ-147, REQ-149, REQ-151, REQ-153, REQ-155, REQ-157

### Dependencies

None. This task has no upstream dependencies and can be started immediately.

### Implementation Steps

**Step 1 — Read existing files before making changes (REQ-101)**

Read `src/platform/observability/contracts.py` fully. Identify any content that is not reproduced in the B.1 or B.2 contracts below. If there is unique content, preserve it by incorporating it into the new files. If the file is empty or only contains content superseded by the new contracts, proceed to deletion.

Read `src/platform/schemas/observability.py` fully to understand what it currently exports and what re-exports need to be added.

**Step 2 — Create `src/platform/observability/backend.py` (REQ-103, REQ-105, REQ-107, REQ-109, REQ-111, REQ-113, REQ-115, REQ-117, REQ-119, REQ-121, REQ-123, REQ-125, REQ-127, REQ-129, REQ-131, REQ-133, REQ-135, REQ-137, REQ-139, REQ-141, REQ-143, REQ-145, REQ-147, REQ-157)**

Create the file with the exact content from contract B.1 below. Do not alter any docstring, method signature, or type annotation. Include the `@summary` block at the top of the file per project conventions.

The file must define:
- `Span` ABC with `set_attribute`, `end`, `__enter__`, `__exit__` (REQ-103, REQ-105, REQ-107, REQ-109)
- `Generation` ABC with `set_output`, `set_token_counts`, `end`, `__enter__`, `__exit__` (REQ-111, REQ-113, REQ-115, REQ-117, REQ-119)
- `Trace` ABC with `span`, `generation`, `__enter__`, `__exit__` (REQ-121, REQ-123, REQ-125, REQ-127)
- `ObservabilityBackend` ABC with `span`, `trace`, `generation`, `flush`, `shutdown` (REQ-129, REQ-131, REQ-133, REQ-135, REQ-137, REQ-139, REQ-141, REQ-143, REQ-145, REQ-147)
- `start_span` concrete method on `ObservabilityBackend` as a deprecated alias for `span` (REQ-433)
- `Tracer = ObservabilityBackend` backward-compat alias (REQ-157)

Contract B.1 (implement exactly):

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

    def start_span(
        self,
        name: str,
        attributes: Optional[dict] = None,
        parent: Optional["Span"] = None,
    ) -> "Span":
        """Deprecated alias for span(). Use span() instead."""
        import warnings
        warnings.warn(
            "start_span() is deprecated; use span() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.span(name, attributes, parent)


# Backward-compatible alias — deprecated, use ObservabilityBackend
Tracer = ObservabilityBackend
```

**Step 3 — Create `src/platform/observability/schemas.py` (REQ-149, REQ-151, REQ-153, REQ-155)**

Create the file with the exact content from contract B.2 below. Include the `@summary` block at the top per project conventions.

The file must define:
- `SpanRecord` dataclass (REQ-149, REQ-155)
- `TraceRecord` dataclass (REQ-151, REQ-155)
- `GenerationRecord` dataclass (REQ-153, REQ-155)

Contract B.2 (implement exactly):

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

**Step 4 — Delete `src/platform/observability/contracts.py` (REQ-157)**

After confirming in Step 1 that no content from `contracts.py` is lost, delete the file. If the project has an `__init__.py` or other files that import from `contracts.py`, update those imports to point to `backend.py` or `schemas.py` as appropriate.

**Step 5 — Modify `src/platform/schemas/observability.py` (REQ-157)**

Add re-exports for backward compatibility. Any code that previously imported from `src/platform/schemas/observability.py` must continue to work. Append re-export lines such as:

```python
# Backward-compat re-exports — these types have moved to src.platform.observability.backend
# and src.platform.observability.schemas
from src.platform.observability.backend import (  # noqa: F401
    Generation,
    ObservabilityBackend,
    Span,
    Trace,
    Tracer,
)
from src.platform.observability.schemas import (  # noqa: F401
    GenerationRecord,
    SpanRecord,
    TraceRecord,
)
```

**Step 6 — Add `@summary` block to each new file**

Per project conventions, add a `@summary` / `@end-summary` block at the top of `backend.py` and `schemas.py` describing their exports and dependencies.

### Testing Guidance

- Instantiate `Span`, `Generation`, `Trace`, `ObservabilityBackend` directly and assert `TypeError` is raised (ABC enforcement).
- Verify `Tracer` is `ObservabilityBackend` (identity check).
- Verify `SpanRecord`, `TraceRecord`, `GenerationRecord` can be instantiated with required fields and that optional fields default correctly.
- Verify `start_ts` defaults to a positive float (recent epoch time).
- Verify `end_ts` defaults to `None`.
- Verify `start_span()` on a concrete subclass emits `DeprecationWarning` and delegates to `span()`.

---

## Task 2: NoopBackend Package

### Agent Isolation Contract

You have access to:
- `src/platform/observability/backend.py` — already created by Task 1 (read it to confirm the ABC signatures)
- Phase 0 contract B.3 inlined below — implement it exactly
- `src/platform/observability/noop_tracer.py` — read it before deleting to confirm no content is lost

You do NOT have access to any other task's context. Do not import from `langfuse/` or `__init__.py`.

### Design Task Reference

Task 1.2

### Target Files

| File | Action |
|---|---|
| `src/platform/observability/noop/__init__.py` | CREATE |
| `src/platform/observability/noop/backend.py` | CREATE |
| `src/platform/observability/noop_tracer.py` | DELETE |

### Requirements Covered

REQ-159, REQ-161, REQ-163, REQ-165

### Dependencies

Task 1 must be complete. `src/platform/observability/backend.py` must exist before this task begins.

### Implementation Steps

**Step 1 — Read existing file before changes**

Read `src/platform/observability/noop_tracer.py` fully. Confirm its content is fully reproduced by the new `noop/backend.py` below. If there is any logic not covered (e.g., a custom `__init__` for `NoopBackend`), preserve it by incorporating into the new file.

**Step 2 — Create the `noop/` package directory**

Create `src/platform/observability/noop/` as a Python package by creating `noop/__init__.py`.

**Step 3 — Create `src/platform/observability/noop/__init__.py` (REQ-159)**

This file is the public export surface for the noop package. Export only `NoopBackend`. Do not re-export `NoopSpan`, `NoopTrace`, `NoopGeneration` — they are implementation details.

```python
# src/platform/observability/noop/__init__.py
# @summary
# Public exports for the noop observability backend package.
# Exports: NoopBackend
# Deps: noop.backend
# @end-summary
"""Noop observability backend package.

Exports the NoopBackend for use by the factory in src.platform.observability.
"""
from src.platform.observability.noop.backend import NoopBackend  # noqa: F401

__all__ = ["NoopBackend"]
```

**Step 4 — Create `src/platform/observability/noop/backend.py` (REQ-159, REQ-161, REQ-163, REQ-165)**

Create the file with the exact content from contract B.3 below. Include the `@summary` block at the top. Every method must satisfy the fail-open contract: no exceptions ever propagate out of any Noop class method.

Contract B.3 (implement exactly):

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

**Step 5 — Delete `src/platform/observability/noop_tracer.py` (REQ-159)**

After confirming no content is lost, delete the file. Search the codebase for any imports of `noop_tracer` and update them to `from src.platform.observability.noop import NoopBackend` or `from src.platform.observability.noop.backend import NoopBackend`.

**Step 6 — Add `@summary` blocks**

Add `@summary` / `@end-summary` to `noop/backend.py` describing its exports (`NoopSpan`, `NoopGeneration`, `NoopTrace`, `NoopBackend`) and its dependency on `src.platform.observability.backend`.

### Testing Guidance

- Instantiate `NoopBackend()` and verify it is an instance of `ObservabilityBackend`.
- Call `NoopBackend().span("x")` — assert return is a `NoopSpan` instance and is a `Span` instance.
- Call `NoopBackend().trace("x")` — assert return is a `NoopTrace` instance and is a `Trace` instance.
- Call `NoopBackend().generation("x", "model", "input")` — assert return is a `NoopGeneration` instance.
- Use all Noop classes with arbitrary values (`None`, empty strings, negative ints) and assert no exceptions are raised.
- Use `NoopSpan` as a context manager; verify `__exit__` calls `end()` correctly (inherits from ABC).
- Call `NoopBackend().flush()` and `NoopBackend().shutdown()` — assert no exceptions raised.

---

## Task 3: LangfuseBackend Package

### Agent Isolation Contract

You have access to:
- `src/platform/observability/backend.py` — already created by Task 1 (read it to confirm ABC signatures)
- `src/platform/observability/noop/backend.py` — already created by Task 2 (needed for fail-open fallbacks)
- `src/platform/observability/langfuse_tracer.py` — read it before deleting to confirm no content is lost
- The implementation constraints and routing logic specified in this section

You do NOT have access to any other task's context. Do not import from `__init__.py` or the public facade. All `from langfuse import ...` statements must appear ONLY in `langfuse/backend.py`.

### Design Task Reference

Task 2.1

### Target Files

| File | Action |
|---|---|
| `src/platform/observability/langfuse/__init__.py` | CREATE |
| `src/platform/observability/langfuse/backend.py` | CREATE |
| `src/platform/observability/langfuse_tracer.py` | DELETE |

### Requirements Covered

REQ-201, REQ-203, REQ-205, REQ-207, REQ-209, REQ-211, REQ-213, REQ-215, REQ-217, REQ-219, REQ-221, REQ-223, REQ-225, REQ-227, REQ-229, REQ-231, REQ-233, REQ-235, REQ-237, REQ-239, REQ-241, REQ-243, REQ-245, REQ-247, REQ-249, REQ-251

### Dependencies

Task 1 must be complete. `src/platform/observability/backend.py` must exist.
Task 2 must be complete. `src/platform/observability/noop/backend.py` must exist (for fail-open fallbacks).

### Implementation Steps

**Step 1 — Read existing file before changes**

Read `src/platform/observability/langfuse_tracer.py` fully. Note any business logic (e.g., credential loading, custom retry logic, SDK version pinning) that is not covered by the rules below. Preserve such logic by incorporating it into `langfuse/backend.py`.

**Step 2 — Create `src/platform/observability/langfuse/__init__.py` (REQ-203)**

This file exports ONLY `LangfuseBackend`. Do not export `LangfuseSpan`, `LangfuseTrace`, or `LangfuseGeneration` — they are implementation details.

```python
# src/platform/observability/langfuse/__init__.py
# @summary
# Public exports for the Langfuse observability backend package.
# Exports: LangfuseBackend
# Deps: langfuse.backend
# @end-summary
"""Langfuse observability backend package.

Exports LangfuseBackend for use by the factory in src.platform.observability.
"""
from src.platform.observability.langfuse.backend import LangfuseBackend  # noqa: F401

__all__ = ["LangfuseBackend"]
```

**Step 3 — Create `src/platform/observability/langfuse/backend.py` (REQ-201 through REQ-251)**

Create the file with the structure described below. Include the `@summary` block at the top. ALL `from langfuse import ...` statements must live in this file only (REQ-201).

The file structure is:

```python
# src/platform/observability/langfuse/backend.py
# @summary
# Langfuse-backed implementations of Span, Generation, Trace, and ObservabilityBackend.
# Exports: LangfuseBackend (LangfuseSpan, LangfuseTrace, LangfuseGeneration are internal)
# Deps: langfuse, src.platform.observability.backend, src.platform.observability.noop.backend
# @end-summary
from __future__ import annotations

import logging
from typing import Optional

from langfuse import Langfuse                 # REQ-201 — only file allowed to import langfuse
from langfuse.client import StatefulClient    # adjust to actual Langfuse SDK import path

from src.platform.observability.backend import (
    Generation,
    ObservabilityBackend,
    Span,
    Trace,
)
from src.platform.observability.noop.backend import (
    NoopGeneration,
    NoopSpan,
    NoopTrace,
)

logger = logging.getLogger("rag.observability.langfuse")
```

**Step 3a — Implement `LangfuseSpan` (REQ-217, REQ-219, REQ-221, REQ-223, REQ-225)**

Rules:
- Constructor accepts one argument: `inner` (the Langfuse SDK span/observation object).
- `set_attribute(key, value)` — calls `inner.update(metadata={key: value})`. Wraps entire call in `try/except Exception` and logs a warning on failure. Returns `None`. Never raises. (REQ-217, REQ-219)
- `end(status, error)` — if `error` is not None, calls `inner.update(level="ERROR", status_message=str(error))` first, then calls `inner.end()`. The entire block is wrapped in `try/except Exception` and logs a warning on failure. Returns `None`. Never raises. (REQ-221, REQ-223)
- `__enter__` and `__exit__` are inherited from the `Span` ABC — do not override them. (REQ-225)

```python
class LangfuseSpan(Span):
    """Langfuse-backed span wrapping a Langfuse SDK observation."""

    def __init__(self, inner: StatefulClient) -> None:
        self._inner = inner

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
```

**Step 3b — Implement `LangfuseGeneration` (REQ-235, REQ-237, REQ-239, REQ-241, REQ-243)**

Rules:
- Constructor accepts one argument: `inner` (the Langfuse SDK generation object).
- `set_output(output)` — calls `inner.update(output=output)`. Catch all exceptions, log warning. Never raises. (REQ-235, REQ-241)
- `set_token_counts(prompt_tokens, completion_tokens)` — calls `inner.update(usage={"input": prompt_tokens, "output": completion_tokens})`. Catch all exceptions, log warning. Never raises. (REQ-237, REQ-241)
- `end(status, error)` — same pattern as `LangfuseSpan.end`. Catch all exceptions, log warning. Never raises. (REQ-239, REQ-241)
- `__enter__` and `__exit__` are inherited from the `Generation` ABC. (REQ-243)

```python
class LangfuseGeneration(Generation):
    """Langfuse-backed generation wrapping a Langfuse SDK generation object."""

    def __init__(self, inner: StatefulClient) -> None:
        self._inner = inner

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
```

**Step 3c — Implement `LangfuseTrace` (REQ-227, REQ-229, REQ-231, REQ-233)**

Rules:
- Constructor accepts one argument: `trace_obj` (the Langfuse SDK trace object). Store as `self._trace`.
- `span(name, attributes)` — calls `self._trace.span(name=name, metadata=attributes or {})`, wraps result in `LangfuseSpan`, returns it. Wraps entire call in `try/except Exception`. On failure: log warning, return `NoopSpan()`. Never raises. (REQ-227, REQ-231)
- `generation(name, model, input, metadata)` — calls `self._trace.generation(name=name, model=model, input=input, metadata=metadata or {})`, wraps result in `LangfuseGeneration`, returns it. Wraps in `try/except Exception`. On failure: log warning, return `NoopGeneration()`. Never raises. (REQ-229, REQ-231)
- `__enter__` and `__exit__` are inherited from the `Trace` ABC. (REQ-233)

```python
class LangfuseTrace(Trace):
    """Langfuse-backed trace grouping spans and generations under a shared trace_id."""

    def __init__(self, trace_obj) -> None:
        self._trace = trace_obj

    def span(self, name: str, attributes: Optional[dict] = None) -> Span:
        try:
            obs = self._trace.span(name=name, metadata=attributes or {})
            return LangfuseSpan(obs)
        except Exception as exc:
            logger.warning("LangfuseTrace.span failed: %s", exc)
            return NoopSpan()

    def generation(
        self,
        name: str,
        model: str,
        input: str,
        metadata: Optional[dict] = None,
    ) -> Generation:
        try:
            obs = self._trace.generation(
                name=name, model=model, input=input, metadata=metadata or {}
            )
            return LangfuseGeneration(obs)
        except Exception as exc:
            logger.warning("LangfuseTrace.generation failed: %s", exc)
            return NoopGeneration()
```

**Step 3d — Implement `LangfuseBackend` (REQ-205, REQ-207, REQ-209, REQ-211, REQ-213, REQ-215, REQ-245, REQ-247, REQ-249, REQ-251)**

Rules:
- Constructor `__init__(self)` — takes NO `host`, `public_key`, `secret_key` parameters (REQ-247). Calls `self._client = Langfuse()` (SDK reads credentials from environment). Does NOT catch exceptions — exceptions propagate to the factory in Task 4 which handles the fallback (REQ-207).
- `span(name, attributes, parent)` — routing logic (REQ-211): if `parent` is a `LangfuseTrace`, use `parent._trace.span(...)` to nest the span; otherwise use `self._client.start_observation(as_type="span", ...)`. Wrap result in `LangfuseSpan`. Wrap entire logic in `try/except Exception`. On failure: log warning, return `NoopSpan()`.
- `trace(name, metadata)` — calls `self._client.trace(name=name, metadata=metadata or {})`, wraps result in `LangfuseTrace`. Wrap in `try/except Exception`. On failure: log warning, return `NoopTrace()`. (REQ-213)
- `generation(name, model, input, metadata)` — calls `self._client.start_observation(as_type="generation", name=name, model=model, input=input, metadata=metadata or {})`, wraps result in `LangfuseGeneration`. Wrap in `try/except Exception`. On failure: log warning, return `NoopGeneration()`. (REQ-215)
- `flush()` — calls `self._client.flush()`. PROPAGATES exceptions — do not catch. (REQ-249)
- `shutdown()` — calls `self._client.shutdown()`. PROPAGATES exceptions — do not catch. (REQ-251)

```python
class LangfuseBackend(ObservabilityBackend):
    """Langfuse-backed observability backend.

    Reads credentials from environment variables (LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY, LANGFUSE_HOST). Constructor exceptions propagate
    to the factory (_init_backend) which handles fallback to NoopBackend.
    """

    def __init__(self) -> None:
        # REQ-247: no constructor parameters for credentials — read from env
        # REQ-207: do not catch — factory handles fallback
        self._client = Langfuse()

    def span(
        self,
        name: str,
        attributes: Optional[dict] = None,
        parent: Optional[Span] = None,
    ) -> Span:
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
            return NoopTrace()

    def generation(
        self,
        name: str,
        model: str,
        input: str,
        metadata: Optional[dict] = None,
    ) -> Generation:
        try:
            obs = self._client.start_observation(
                as_type="generation",
                name=name,
                model=model,
                input=input,
                metadata=metadata or {},
            )
            return LangfuseGeneration(obs)
        except Exception as exc:
            logger.warning("LangfuseBackend.generation failed: %s", exc)
            return NoopGeneration()

    def flush(self) -> None:
        # REQ-249: propagate exceptions
        self._client.flush()

    def shutdown(self) -> None:
        # REQ-251: propagate exceptions
        self._client.shutdown()
```

**Step 4 — Delete `src/platform/observability/langfuse_tracer.py` (REQ-201)**

After confirming no content is lost, delete the file. Search the codebase for any imports of `langfuse_tracer` and update them to `from src.platform.observability.langfuse import LangfuseBackend`.

**Step 5 — Verify Langfuse SDK import path**

The exact import path for `StatefulClient` may differ between Langfuse SDK versions. Check the installed version:
- For `langfuse >= 2.x`: use `from langfuse.client import StatefulClient` or the appropriate typed object
- Adjust the `inner` type annotation to match the actual SDK type for the span/generation object returned by `trace.span(...)` and `client.start_observation(...)`

If the SDK does not expose a meaningful type for these objects, use `Any` from `typing`.

### Testing Guidance

- Instantiate `LangfuseBackend()` with no env vars set — confirm the constructor raises an exception (no keys).
- Mock the `Langfuse` client: inject a mock that raises on `trace()`. Call `LangfuseBackend().trace(...)` and confirm it returns a `NoopTrace` instance and logs a warning.
- Mock the `Langfuse` client: inject a mock `trace_obj` that raises on `span()`. Call `LangfuseTrace(mock).span(...)` and confirm it returns a `NoopSpan` instance.
- Call `LangfuseSpan(mock).set_attribute("k", "v")` where mock raises — confirm no exception propagates.
- Call `LangfuseSpan(mock).end(error=ValueError("x"))` — confirm `mock.update` was called with `level="ERROR"` and `status_message="x"`.
- Call `LangfuseGeneration(mock).set_token_counts(10, 20)` — confirm `mock.update` was called with `usage={"input": 10, "output": 20}`.
- Verify `LangfuseBackend().flush()` propagates SDK exceptions.
- Verify `LangfuseBackend().shutdown()` propagates SDK exceptions.
- Verify `langfuse/__init__.py` does NOT export `LangfuseSpan`, `LangfuseTrace`, `LangfuseGeneration`.

---

## Task 4: Public API Facade, Singleton Factory, and @observe Decorator

### Agent Isolation Contract

You have access to:
- `src/platform/observability/backend.py` — Task 1 output (read to confirm ABC and alias exports)
- `src/platform/observability/noop/backend.py` — Task 2 output (used inside `_init_backend`)
- `src/platform/observability/langfuse/backend.py` — Task 3 output (used inside `_init_backend`)
- `src/platform/observability/__init__.py` — the stub file (rewrite it from stubs to full implementation)
- `src/platform/observability/providers.py` — read it before modifying; convert to backward-compat shim
- `config/settings.py` — read to confirm the import path for `OBSERVABILITY_PROVIDER`

The Phase 0 contract B.4 is the stub that defines the public API shape. Implement it fully.

### Design Task Reference

Task 3.1

### Target Files

| File | Action |
|---|---|
| `src/platform/observability/__init__.py` | MODIFY — rewrite from stubs to full implementation |
| `src/platform/observability/providers.py` | MODIFY — convert to backward-compat shim |

### Requirements Covered

REQ-167, REQ-169, REQ-171, REQ-301, REQ-303, REQ-305, REQ-307, REQ-309, REQ-311, REQ-313, REQ-315, REQ-317, REQ-319, REQ-321, REQ-323, REQ-325, REQ-327, REQ-329, REQ-331, REQ-333, REQ-335, REQ-337, REQ-339, REQ-341

### Dependencies

Task 1, Task 2, and Task 3 must all be complete.

### Implementation Steps

**Step 1 — Read existing files before changes**

Read `src/platform/observability/__init__.py` to understand the current stub structure. Read `src/platform/observability/providers.py` to understand what it currently exports and who imports from it. Read `config/settings.py` to confirm the exact attribute name for `OBSERVABILITY_PROVIDER`.

**Step 2 — Implement `src/platform/observability/__init__.py` (REQ-301 through REQ-341)**

Replace the stub implementations with the full implementations below. Preserve all imports from contract B.4. The file must:

- Use thread-safe double-checked locking for the singleton (REQ-303, REQ-305)
- Export `get_tracer`, `observe`, `Tracer`, `Span`, `Trace`, `Generation` in `__all__` (REQ-339)
- Define `Tracer = ObservabilityBackend` as a backward-compat alias (REQ-333)

Full implementation:

```python
# src/platform/observability/__init__.py
# @summary
# Public API facade for the observability subsystem.
# Exports: get_tracer, observe, Tracer, Span, Trace, Generation
# Deps: observability.backend, observability.noop.backend, observability.langfuse.backend, config.settings
# @end-summary
"""Observability public API.

Single import surface for all observability consumers. Provides:
  - get_tracer(): process-wide backend singleton (thread-safe, lazy-init)
  - observe(): decorator factory for span-wrapping functions
  - Span, Trace, Generation: ABC types for type annotations
  - Tracer: deprecated alias for ObservabilityBackend
"""
from __future__ import annotations

import functools
import threading
from typing import Callable, Optional, TypeVar

from src.platform.observability.backend import (
    Generation,
    ObservabilityBackend,
    Span,
    Trace,
)

F = TypeVar("F", bound=Callable)

# Internal singleton state — do not access directly outside this module
_backend: Optional[ObservabilityBackend] = None
_backend_lock = threading.Lock()

_MAX_CAPTURE_LEN = 500


def get_tracer() -> ObservabilityBackend:
    """Return the process-wide ObservabilityBackend singleton.

    Initializes the backend on first call using OBSERVABILITY_PROVIDER.
    Subsequent calls return the same instance without acquiring the lock.
    Thread-safe via double-checked locking.

    Returns:
        The active ObservabilityBackend. Never raises — falls back to NoopBackend.
    """
    global _backend
    if _backend is not None:
        return _backend
    with _backend_lock:
        if _backend is None:
            _backend = _init_backend()
    return _backend


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
    def decorator(func: F) -> F:
        span_name = name if name is not None else func.__qualname__

        @functools.wraps(func)
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
        return wrapper  # type: ignore[return-value]
    return decorator


def _init_backend() -> ObservabilityBackend:
    """Initialize and return the backend based on OBSERVABILITY_PROVIDER.

    Called once at first get_tracer() invocation. Not intended for direct use.
    Falls back to NoopBackend on any initialization error, logging a warning.

    Returns:
        The initialized ObservabilityBackend.

    Raises:
        ValueError: If OBSERVABILITY_PROVIDER is set to an unknown value.
    """
    import logging
    from config.settings import OBSERVABILITY_PROVIDER

    logger = logging.getLogger("rag.observability")

    provider = (OBSERVABILITY_PROVIDER or "").strip().lower()

    if not provider or provider == "noop":
        from src.platform.observability.noop.backend import NoopBackend
        return NoopBackend()

    if provider == "langfuse":
        try:
            from src.platform.observability.langfuse.backend import LangfuseBackend
            return LangfuseBackend()
        except Exception as exc:
            logger.warning(
                "Failed to initialize langfuse backend (%s); falling back to noop.", exc
            )
            from src.platform.observability.noop.backend import NoopBackend
            return NoopBackend()

    raise ValueError(
        f"Unknown OBSERVABILITY_PROVIDER: {provider!r}. Valid values: 'noop', 'langfuse'."
    )


# Backward-compatible alias — deprecated, use ObservabilityBackend
Tracer = ObservabilityBackend

__all__ = ["get_tracer", "observe", "Tracer", "Span", "Trace", "Generation"]
```

**Step 3 — Confirm `config/settings.py` import (REQ-307)**

Open `config/settings.py` and confirm the exact attribute name for the observability provider setting. If it is not named `OBSERVABILITY_PROVIDER`, update the `_init_backend()` import accordingly. Do not rename the setting in `config/settings.py` — only adjust the import in `_init_backend()`.

If `OBSERVABILITY_PROVIDER` does not exist in `config/settings.py`, add it with a default value of `""` (empty string, which results in NoopBackend):

```python
OBSERVABILITY_PROVIDER: str = os.getenv("OBSERVABILITY_PROVIDER", "")
```

**Step 4 — Implement `src/platform/observability/providers.py` backward-compat shim (REQ-335)**

Read the current `providers.py` content. Replace its body with the shim below. The shim emits a `DeprecationWarning` and re-exports `get_tracer` so existing imports continue to work.

```python
# src/platform/observability/providers.py
"""Deprecated: import from src.platform.observability instead.

This module is a backward-compatibility shim. All new code should import
directly from src.platform.observability:

    from src.platform.observability import get_tracer
"""
import warnings

warnings.warn(
    "Importing from src.platform.observability.providers is deprecated. "
    "Use 'from src.platform.observability import get_tracer' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from src.platform.observability import get_tracer  # noqa: F401, E402
```

**Step 5 — Reset singleton in tests (REQ-303)**

The `_backend` singleton is a module-level global. Tests that need to test different providers must reset it between test runs. Add a helper reset function (not exported in `__all__`) for use in tests:

```python
def _reset_backend_for_testing() -> None:
    """Reset the singleton backend. For use in tests only — not for production code."""
    global _backend
    with _backend_lock:
        _backend = None
```

### Testing Guidance

- Call `get_tracer()` twice in the same process — confirm the same object is returned both times.
- Set `OBSERVABILITY_PROVIDER = ""` — confirm `get_tracer()` returns a `NoopBackend` instance.
- Set `OBSERVABILITY_PROVIDER = "noop"` — confirm `get_tracer()` returns a `NoopBackend` instance.
- Set `OBSERVABILITY_PROVIDER = "langfuse"` with invalid credentials — confirm `get_tracer()` returns a `NoopBackend` instance and emits a warning log.
- Set `OBSERVABILITY_PROVIDER = "unknown_value"` — confirm `get_tracer()` raises `ValueError`.
- Apply `@observe("test.func")` to a function — confirm it calls `get_tracer().span(...)` once per invocation.
- Apply `@observe(capture_input=True)` to a method `def f(self, a, b)` — confirm `span.set_attribute("input", ...)` is called with `args[1:]` (excludes `self`).
- Apply `@observe(capture_output=True)` to a function — confirm `span.set_attribute("output", ...)` is called with the truncated return value.
- Apply `@observe` to a function that raises — confirm the exception propagates and `set_attribute("error", ...)` was called.
- Verify `from src.platform.observability.providers import get_tracer` emits a `DeprecationWarning`.
- Verify `__all__` contains exactly `["get_tracer", "observe", "Tracer", "Span", "Trace", "Generation"]`.
- Verify concurrent calls to `get_tracer()` from multiple threads all return the same instance.

---

## Task 5: Migrate Retrieval Consumers

### Agent Isolation Contract

You have access to:
- `src/platform/observability/__init__.py` — Task 4 output (to understand the public API you are migrating to)
- The five files listed under Target Files — read each fully before modifying
- Only the observability-related changes specified below — do NOT change business logic

You do NOT have access to any other task's context. Apply only the migration changes listed. Do not refactor, rename, or restructure non-observability code.

### Design Task Reference

Task 4.1

### Target Files

| File | Action |
|---|---|
| `src/retrieval/query/nodes/reranker.py` | MODIFY |
| `src/retrieval/generation/nodes/generator.py` | MODIFY |
| `src/retrieval/query/nodes/query_processor.py` | MODIFY |
| `src/retrieval/pipeline/rag_chain.py` | MODIFY |
| `src/retrieval/generation/nodes/output_sanitizer.py` | MODIFY |

### Requirements Covered

REQ-401, REQ-403, REQ-405, REQ-407, REQ-409, REQ-411, REQ-413, REQ-415, REQ-417, REQ-421, REQ-423, REQ-427, REQ-429, REQ-431, REQ-435, REQ-437, REQ-439, REQ-441

### Dependencies

Task 4 must be complete. `src/platform/observability/__init__.py` must expose `get_tracer` and `observe`.

### Implementation Steps

**Step 1 — Read all five target files before making any changes**

Read each file fully. Note:
- Which observability import style is currently used (old providers path, direct langfuse, or already using the new path)
- Whether any file uses `_tracer_instance` module-level globals
- Whether any file uses `tracer.start_span(...)` with try-finally patterns
- Whether any file uses `from langfuse import ...` directly
- Which observability patterns (direct span, context manager, decorator) best fit each file's usage

Do not modify any file until you have read all five.

**Step 2 — Apply migration rule: update import line (REQ-401, REQ-429)**

For every file that currently imports from observability, change the import to:

```python
from src.platform.observability import get_tracer, observe
```

If the file already uses this exact import, skip it.

Remove any lines importing `from langfuse import ...` directly in consumer files (REQ-405). The Langfuse SDK must only be imported inside `langfuse/backend.py`.

**Step 3 — Remove `_tracer_instance` module-level globals (REQ-435)**

If a file contains:

```python
_tracer_instance = None

def _get_tracer():
    global _tracer_instance
    if _tracer_instance is None:
        _tracer_instance = ...
    return _tracer_instance
```

Delete the global and the lazy-init function. Replace every call to `_get_tracer()` or `_tracer_instance` with `get_tracer()` directly at the call site.

**Step 4 — Replace span usage patterns (REQ-431, REQ-437, REQ-439)**

Apply the following replacement rules based on usage patterns found in Step 1:

**Pattern A: Old try-finally with `start_span`**

Replace this:
```python
span = tracer.start_span("some.operation")
try:
    # ... logic ...
    span.end(status="ok")
except Exception as e:
    span.end(status="error", error=e)
    raise
```

With this (context manager — REQ-431):
```python
with get_tracer().span("some.operation") as span:
    # ... logic ...
```

Do NOT call `span.end()` explicitly inside the `with` block (REQ-437). Do NOT add bare `except` blocks that set status and re-raise (REQ-439) — the ABC `__exit__` handles this automatically.

**Pattern B: Function needs no dynamic attribute updates**

If a function is entirely wrapped in a single span and needs no mid-function attribute updates, apply the decorator:

```python
@observe("component.operation")
def my_function(self, ...):
    ...
```

**Pattern C: Function sets attributes from computed values mid-execution**

Use the context manager and call `span.set_attribute(key, value)` inside the block:

```python
with get_tracer().span("component.operation", {"initial_attr": value}) as span:
    result = compute()
    span.set_attribute("result_count", len(result))
```

**Step 5 — Apply attribute key rules (REQ-421, REQ-423, REQ-427)**

For every `set_attribute(key, value)` call:
- Keys must be `snake_case` — no hyphens, no dots in keys (dots are allowed in span names, not attribute keys).
- No provider-prefix keys: remove any `langfuse_`, `otel_`, or similar prefixes.
- Values must be `str`, `int`, `float`, or `bool`. If a value is a list or dict, use `len(value)` for count or `str(value)` for serialization.

**Step 6 — File-specific migration notes**

**`reranker.py` (REQ-407):**

Read the file and find the reranking method (likely `rerank` or similar). Replace the old span pattern with:

```python
with get_tracer().span("reranker.rerank", {"doc_count": len(documents)}) as span:
    # existing reranking logic here
    span.set_attribute("result_count", len(result))
    return result
```

The `with` block's `__exit__` automatically marks the span as error if an exception is raised.

**`generator.py` (REQ-409):**

Read the file and find the generation method. This method likely has dynamic values (model name, token counts). Use context manager with dynamic `set_attribute` calls. Example pattern:

```python
with get_tracer().span("generator.generate") as span:
    span.set_attribute("model", model_name)
    result = llm.invoke(prompt)
    span.set_attribute("output_length", len(result.content))
    return result
```

**`query_processor.py` (REQ-411):**

Read the file. Remove any module-level `_tracer_instance`. Find span usage and replace with `get_tracer()` at the call site using context manager.

**`rag_chain.py` (REQ-413):**

Read the file. This is the pipeline entry point. The trace root should be created here to group all child spans:

```python
with get_tracer().trace("rag.request", {"query_length": len(query)}) as trace:
    # child spans are created inside pipeline nodes
    result = pipeline.run(query)
    return result
```

If the pipeline nodes create their own spans via `get_tracer().span(...)`, they will operate independently (not nested under this trace unless the backend supports context propagation). The trace call here records the overall request boundary.

**`output_sanitizer.py` (REQ-415):**

Read the file. Apply import change and span pattern replacement per the general rules.

### Testing Guidance

- After migration, import each file and confirm no `ImportError` is raised.
- For each file, confirm `from langfuse import` no longer appears.
- For each file, confirm `_tracer_instance` no longer appears.
- For each file, confirm no `start_span(` call remains.
- For each file, confirm no explicit `span.end()` call appears inside a `with` block.
- Run the existing retrieval pipeline tests and confirm they pass (tests should not depend on observability internals).
- Mock `get_tracer()` to return a `NoopBackend` and run one full pipeline pass — confirm no exceptions and correct output.

---

## Task 6: Migrate Ingest Consumers

### Agent Isolation Contract

You have access to:
- `src/platform/observability/__init__.py` — Task 4 output (to understand the public API)
- The three files listed under Target Files — read each fully before modifying
- Only the observability-related changes specified below — do NOT change business logic, pipeline structure, or non-observability imports

If a file does not currently import from `src.platform.observability` at all, skip it. If a file uses `_tracer_instance`, remove and replace with `get_tracer()` at use site.

### Design Task Reference

Task 4.2

### Target Files

| File | Action |
|---|---|
| `src/ingest/support/docling.py` | MODIFY |
| `src/ingest/doc_processing/nodes/multimodal_processing.py` | MODIFY |
| `src/ingest/common/shared.py` | MODIFY |

### Requirements Covered

REQ-401, REQ-403, REQ-405, REQ-429, REQ-431, REQ-435, REQ-437, REQ-439

### Dependencies

Task 4 must be complete. `src/platform/observability/__init__.py` must expose `get_tracer` and `observe`.

### Implementation Steps

**Step 1 — Read all three target files before making any changes**

Read each file fully. For each file, note:
- Whether it currently imports from observability (if not, skip the file entirely)
- The current import path (old providers path, direct langfuse, or already correct)
- Whether it uses `_tracer_instance` module-level globals
- Whether it uses `start_span(...)` with try-finally patterns
- Whether it uses `from langfuse import ...` directly

**Step 2 — Apply migration rule: update import line (REQ-401, REQ-429)**

For every file that currently imports from observability (determined in Step 1), change the import to:

```python
from src.platform.observability import get_tracer, observe
```

Remove any `from langfuse import ...` lines in consumer files (REQ-405).

**Step 3 — Remove `_tracer_instance` module-level globals (REQ-435)**

Same rules as Task 5 Step 3. Delete any `_tracer_instance` globals and lazy-init functions. Replace call sites with `get_tracer()`.

**Step 4 — Replace span usage patterns (REQ-431, REQ-437, REQ-439)**

Same rules as Task 5 Step 4:
- Replace `start_span(...)` / try-finally with `with get_tracer().span(...) as span:`
- Do NOT call `span.end()` inside the `with` block
- Do NOT add bare `except` blocks that set status and re-raise

**Step 5 — File-specific migration notes**

**`src/ingest/support/docling.py`:**

Read the file. This is a support library for document parsing via Docling. Identify any span patterns around document loading or conversion calls. Replace with context manager pattern:

```python
with get_tracer().span("docling.convert", {"file_path": str(file_path)}) as span:
    result = converter.convert(file_path)
    span.set_attribute("page_count", len(result.pages) if hasattr(result, "pages") else 0)
    return result
```

**`src/ingest/doc_processing/nodes/multimodal_processing.py`:**

Read the file. This is a pipeline node for multimodal document processing. Identify the main processing method. Replace span patterns per the general rules. Example:

```python
with get_tracer().span("multimodal_processing.process") as span:
    span.set_attribute("doc_type", doc_type)
    result = self._process(document)
    return result
```

**`src/ingest/common/shared.py`:**

Read the file. This is a shared utilities module. It may contain helper functions used by multiple pipeline nodes. Identify observability-instrumented helpers and apply the migration rules. Be careful not to change non-observability helpers.

**Step 6 — Verify no regressions**

After modifying each file, verify that:
- All non-observability imports remain unchanged
- All business logic remains unchanged
- No new imports were added except the observability import update

### Testing Guidance

- After migration, import each file and confirm no `ImportError`.
- Confirm `from langfuse import` no longer appears in any of the three files.
- Confirm `_tracer_instance` no longer appears.
- Confirm no explicit `span.end()` inside a `with` block.
- Run existing ingest pipeline tests and confirm they pass.
- Mock `get_tracer()` to return a `NoopBackend` and run one document through the ingest pipeline — confirm no exceptions and correct output.

---

## Task 7: Docker Compose Langfuse Services and .env.example

### Agent Isolation Contract

You have access to:
- `docker-compose.yml` — read it fully before modifying
- `.env.example` — read it fully before modifying
- The exact YAML and env var values specified in this section — add them verbatim

Do NOT modify any existing service, network, or volume in `docker-compose.yml`. Add only what is listed. Do NOT modify any existing variable in `.env.example`. Add only what is listed.

This task is independent of all Python tasks and can be executed in parallel with Task 1.

### Design Task Reference

Task 5.1

### Target Files

| File | Action |
|---|---|
| `docker-compose.yml` | MODIFY — add two services and one volume |
| `.env.example` | MODIFY — add Langfuse variable placeholders |

### Requirements Covered

REQ-501, REQ-503, REQ-505, REQ-507, REQ-509, REQ-511, REQ-513, REQ-515, REQ-517, REQ-519, REQ-521, REQ-523, REQ-525, REQ-527, REQ-529, REQ-531, REQ-533, REQ-535, REQ-537, REQ-539, REQ-541

### Dependencies

None. This task is independent of all Python tasks.

### Implementation Steps

**Step 1 — Read `docker-compose.yml` fully**

Read the entire file. Note:
- The indentation style (2 spaces or 4 spaces)
- Whether a top-level `volumes:` block already exists
- The last existing service name (to add the new services after it)
- Any existing network definitions to be aware of

**Step 2 — Add Langfuse services under `services:` (REQ-501, REQ-503, REQ-505, REQ-507, REQ-509, REQ-511)**

Add the following two service definitions after the last existing service in the `services:` block. Both services must have `profiles: [observability]` — this ensures they are NOT started by `docker compose up -d` and are only started when `--profile observability` is passed (REQ-511).

```yaml
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
```

**Step 3 — Add volume under top-level `volumes:` block (REQ-513)**

Find the top-level `volumes:` block. If it exists, add the following entry to it:

```yaml
  langfuse-db-data:
```

If no top-level `volumes:` block exists, create one at the end of the file:

```yaml
volumes:
  langfuse-db-data:
```

**Step 4 — Read `.env.example` fully**

Read the entire file. Note:
- Whether a section separator comment style is used (e.g., `# ---`, `# Section Name`)
- Where to add the new section (append at the end or after a relevant existing section)

**Step 5 — Add Langfuse variables to `.env.example` (REQ-515 through REQ-541)**

Append the following block to `.env.example`. Match the existing comment style. The values shown are placeholders — operators must replace them with real values.

```
# Observability — Langfuse (optional, requires --profile observability)
LANGFUSE_PORT=3000
LANGFUSE_NEXTAUTH_SECRET=change-me-to-a-secure-random-string
LANGFUSE_SALT=change-me-to-another-secure-random-string
LANGFUSE_ENCRYPTION_KEY=change-me-to-a-32-byte-hex-string-0000000000000000
LANGFUSE_INIT_ORG_ID=my-org
LANGFUSE_INIT_PROJECT_ID=my-project
LANGFUSE_PUBLIC_KEY=lf-pk-change-me
LANGFUSE_SECRET_KEY=lf-sk-change-me
```

Also add the `OBSERVABILITY_PROVIDER` application variable in the appropriate application config section (if one exists) or at the end:

```
# Application observability provider selection (noop | langfuse)
OBSERVABILITY_PROVIDER=noop
```

**Step 6 — Verify profile isolation (REQ-511)**

After saving `docker-compose.yml`, mentally verify (or run if possible):
- `docker compose config --profiles` should list `observability` as an available profile.
- `docker compose up -d` (no profile) must NOT start `langfuse-db` or `langfuse`.
- `docker compose --profile observability up -d` starts both services.
- `langfuse` waits for `langfuse-db` to be healthy before starting (`depends_on: condition: service_healthy`).

### Testing Guidance

- Run `docker compose config` — confirm no YAML syntax errors.
- Confirm `langfuse-db` and `langfuse` both appear in `docker compose config --services` output.
- Run `docker compose up -d` without a profile and confirm neither service starts.
- Run `docker compose --profile observability up -d` and confirm both services start.
- After startup, access `http://localhost:3000/api/public/health` and confirm it returns HTTP 200.
- Confirm the `langfuse-db-data` volume is created by `docker volume ls`.
- Stop services and confirm volumes persist (REQ-513).

---

## Module Boundary Map

```
Task 1 (Backend ABC + Schemas)
  CREATE  src/platform/observability/backend.py
  CREATE  src/platform/observability/schemas.py
  DELETE  src/platform/observability/contracts.py
  MODIFY  src/platform/schemas/observability.py

Task 2 (NoopBackend Package)
  CREATE  src/platform/observability/noop/__init__.py
  CREATE  src/platform/observability/noop/backend.py
  DELETE  src/platform/observability/noop_tracer.py

Task 3 (LangfuseBackend Package)
  CREATE  src/platform/observability/langfuse/__init__.py
  CREATE  src/platform/observability/langfuse/backend.py
  DELETE  src/platform/observability/langfuse_tracer.py

Task 4 (Public API Facade)
  MODIFY  src/platform/observability/__init__.py
  MODIFY  src/platform/observability/providers.py
  MODIFY  src/platform/observability/backend.py  (add start_span alias)

Task 5 (Migrate Retrieval Consumers)
  MODIFY  src/retrieval/query/nodes/reranker.py
  MODIFY  src/retrieval/generation/nodes/generator.py
  MODIFY  src/retrieval/query/nodes/query_processor.py
  MODIFY  src/retrieval/pipeline/rag_chain.py
  MODIFY  src/retrieval/generation/nodes/output_sanitizer.py

Task 6 (Migrate Ingest Consumers)
  MODIFY  src/ingest/support/docling.py
  MODIFY  src/ingest/doc_processing/nodes/multimodal_processing.py
  MODIFY  src/ingest/common/shared.py

Task 7 (Docker + .env)
  MODIFY  docker-compose.yml
  MODIFY  .env.example
```

---

## Dependency Graph

```
Task 1: Backend ABC + Schemas   [no deps]
Task 7: Docker + .env           [no deps — runs in parallel with Task 1]
         │
         ▼
Task 2: NoopBackend Package     [depends on Task 1]
Task 3: LangfuseBackend Package [depends on Task 1]   [CRITICAL PATH]
         │                 │
         └────────┬────────┘
                  ▼
Task 4: Public API Facade       [depends on Task 1, 2, 3]   [CRITICAL PATH]
                  │
         ┌────────┴────────┐
         ▼                 ▼
Task 5: Retrieval Migration  Task 6: Ingest Migration
[depends on Task 4]          [depends on Task 4]

[CRITICAL PATH]: Task 1 → Task 3 → Task 4 → Task 5

Parallelism opportunities:
  - Task 1 and Task 7 can run simultaneously
  - Task 2 and Task 3 can run simultaneously (both depend only on Task 1)
  - Task 5 and Task 6 can run simultaneously (both depend only on Task 4)
```

---

## Task-to-FR Traceability Table

| Task | Design Task | Requirements Covered |
|---|---|---|
| Task 1 | Task 1.1 | REQ-101, 103, 105, 107, 109, 111, 113, 115, 117, 119, 121, 123, 125, 127, 129, 131, 133, 135, 137, 139, 141, 143, 145, 147, 149, 151, 153, 155, 157 |
| Task 2 | Task 1.2 | REQ-159, 161, 163, 165; NFR: REQ-901, 903 |
| Task 3 | Task 2.1 | REQ-201, 203, 205, 207, 209, 211, 213, 215, 217, 219, 221, 223, 225, 227, 229, 231, 233, 235, 237, 239, 241, 243, 245, 247, 249, 251; NFR: REQ-905, 907, 911, 915, 917 |
| Task 4 | Task 3.1 | REQ-167, 169, 171, 301, 303, 305, 307, 309, 311, 313, 315, 317, 319, 321, 323, 325, 327, 329, 331, 333, 335, 337, 339, 341; NFR: REQ-901, 903, 905, 909, 913, 919, 921, 923, 925, 927, 929, 931, 933, 935, 939, 941 |
| Task 5 | Task 4.1 | REQ-401, 403, 405, 407, 409, 411, 413, 415, 417, 421, 423, 427, 429, 431, 435, 437, 439, 441 |
| Task 6 | Task 4.2 | REQ-401, 403, 405, 429, 431, 435, 437, 439 |
| Task 7 | Task 5.1 | REQ-501, 503, 505, 507, 509, 511, 513, 515, 517, 519, 521, 523, 525, 527, 529, 531, 533, 535, 537, 539, 541; NFR: REQ-937, 939 |
