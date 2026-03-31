# Swappable Observability Subsystem — Test Docs

> **For write-module-tests agents:** This document is your source of truth.
> Read ONLY your assigned module section. Do not read source files, implementation code,
> or other modules' test specs.

**Engineering guide:** `docs/observability/OBSERVABILITY_ENGINEERING_GUIDE.md`
**Phase 0 contracts:** `docs/observability/OBSERVABILITY_IMPLEMENTATION_DOCS.md`
**Spec:** `docs/observability/OBSERVABILITY_SPEC.md`
**Produced by:** write-test-docs

---

## Table of Contents

1. [Mock / Stub Interface Specifications](#1-mock--stub-interface-specifications)
2. [Module Test Specs](#2-module-test-specs)
   - 2.1 [`backend.py` — Abstract Base Classes](#21-srcplatformobservabilitybackendpy--abstract-base-classes)
   - 2.2 [`schemas.py` — Record Dataclasses](#22-srcplatformobservabilityschemasspy--record-dataclasses)
   - 2.3 [`__init__.py` — Public API Facade](#23-srcplatformobservabilityinitpy--public-api-facade)
   - 2.4 [`noop/backend.py` — NoopBackend](#24-srcplatformobservabilitynoopbackendpy--noopbackend)
   - 2.5 [`langfuse/backend.py` — LangfuseBackend](#25-srcplatformobservabilitylangfusebackendpy--langfusebackend)
   - 2.6 [`providers.py` — Deprecated Shim](#26-srcplatformobservabilityproviderspymdash-deprecated-shim)
3. [Integration Test Specs](#3-integration-test-specs)
   - 3.1 [Happy path: `get_tracer()` with `OBSERVABILITY_PROVIDER=noop`](#31-happy-path-get_tracer-with-observability_providernoop)
   - 3.2 [Langfuse fallback: `LangfuseBackend.__init__` failure](#32-langfuse-fallback-langfusebackend__init__-failure)
   - 3.3 [`@observe` error path: exception in decorated function](#33-observe-error-path-exception-in-decorated-function)
4. [FR Traceability Matrix](#4-fr-traceability-matrix)

---

## 1. Mock / Stub Interface Specifications

### Mock: Langfuse SDK client (`langfuse.get_client()`)

| Field | Value |
|---|---|
| **What it replaces** | `langfuse.get_client()` — the Langfuse v3 SDK singleton call inside `LangfuseBackend.__init__()` |
| **Function signature** | `get_client() -> LangfuseClient` |
| **Happy path return** | A `MagicMock` object exposing `.trace()`, `.span()`, `.generation()`, `.start_observation()`, `.flush()`, `.shutdown()` |
| **Error path return** | Raises any `Exception` (e.g., `ConnectionError("no server")`, `RuntimeError("missing key")`) |
| **Used by modules** | `langfuse/backend.py` tests exclusively |

**Child observation mock pattern:**

```python
mock_inner = MagicMock()
mock_inner.update = MagicMock()
mock_inner.end = MagicMock()

mock_client = MagicMock()
mock_client.trace.return_value = mock_inner
mock_client.start_observation.return_value = mock_inner
```

**Mock reset requirement:** LangfuseBackend tests must patch `langfuse.get_client` at the import-time location:
`src.platform.observability.langfuse.backend.get_client` (after the deferred import fires).
Alternatively, monkeypatch the import itself using `unittest.mock.patch`.

---

### Mock: `config.settings.OBSERVABILITY_PROVIDER`

| Field | Value |
|---|---|
| **What it replaces** | `config.settings.OBSERVABILITY_PROVIDER` — the settings object read by `_init_backend()` |
| **Function signature** | Attribute access: `settings.OBSERVABILITY_PROVIDER -> str` |
| **Happy path return** | `"noop"`, `"langfuse"`, or `""` (empty string) |
| **Error path return** | `AttributeError` (settings module not importable) — triggers `os.environ` fallback |
| **Used by modules** | `__init__.py` tests |

**Patch pattern:**

```python
monkeypatch.setattr("src.platform.observability.config.settings.OBSERVABILITY_PROVIDER", "noop")
# Or, for AttributeError fallback path:
monkeypatch.delattr("src.platform.observability.config.settings", "OBSERVABILITY_PROVIDER", raising=False)
```

---

### Mock: `os.environ["OBSERVABILITY_PROVIDER"]`

| Field | Value |
|---|---|
| **What it replaces** | Environment variable read as fallback by `_init_backend()` when `config.settings` is not importable |
| **Function signature** | `os.environ.get("OBSERVABILITY_PROVIDER", "") -> str` |
| **Happy path return** | `"noop"` or `"langfuse"` |
| **Error path return** | `""` (empty string) — results in `NoopBackend` |
| **Used by modules** | `__init__.py` factory tests |

**Patch pattern:**

```python
monkeypatch.setenv("OBSERVABILITY_PROVIDER", "noop")
monkeypatch.delenv("OBSERVABILITY_PROVIDER", raising=False)
```

---

### Singleton reset pattern (required for all `__init__.py` tests)

Because `get_tracer()` uses module-level `_backend` state, every test that exercises factory logic must reset the singleton:

```python
import src.platform.observability as obs_module

def test_something(monkeypatch):
    monkeypatch.setattr(obs_module, "_backend", None)
    # ... set env vars ... then call get_tracer()
```

---

## 2. Module Test Specs

---

### 2.1 `src/platform/observability/backend.py` — Abstract Base Classes

**Module purpose:** Defines `Span`, `Generation`, `Trace`, and `ObservabilityBackend` ABCs that form the provider-agnostic contract layer — no third-party imports, importable in any environment.

**In scope:**
- ABC instantiation raises `TypeError` (Python enforcement)
- `Span.__enter__` / `__exit__` concrete implementations
- `Generation.__enter__` / `__exit__` concrete implementations
- `Trace.__enter__` / `__exit__` concrete implementations
- `ObservabilityBackend.start_span()` deprecated alias behavior (emits `DeprecationWarning`, delegates to `span()`)
- `Tracer = ObservabilityBackend` alias

**Out of scope:**
- Concrete method behavior (tested in `noop/backend.py` and `langfuse/backend.py` specs)
- Record field population (tested in `schemas.py` spec)
- Singleton and factory behavior (tested in `__init__.py` spec)

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| `Span.__enter__` returns self | A minimal concrete `Span` subclass; call `__enter__()` | Returns the span instance itself |
| `Span.__exit__` normal exit | Call `__exit__(None, None, None)` | Calls `end(status="ok")`; returns `False` |
| `Span.__exit__` exception exit | Call `__exit__(type, ValueError("boom"), tb)` | Calls `end(status="error", error=ValueError("boom"))`; returns `False` |
| `Generation.__enter__` returns self | Minimal `Generation` subclass; call `__enter__()` | Returns the generation instance itself |
| `Generation.__exit__` normal exit | Call `__exit__(None, None, None)` | Calls `end(status="ok")`; returns `False` |
| `Generation.__exit__` exception exit | Call `__exit__(type, RuntimeError("x"), tb)` | Calls `end(status="error", error=RuntimeError("x"))`; returns `False` |
| `Trace.__enter__` returns self | Minimal `Trace` subclass; call `__enter__()` | Returns the trace instance itself |
| `Trace.__exit__` any exit | Call `__exit__(None, None, None)` or with exception | Returns `False` in both cases |
| `start_span()` delegates to `span()` | Call `backend.start_span("op", {})` | `span("op", {})` is called; returns same result |
| `Tracer` alias | `from backend import Tracer` | `Tracer is ObservabilityBackend` is `True` |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| `TypeError` | Instantiate `ObservabilityBackend()` directly | Raises `TypeError: Can't instantiate abstract class` |
| `TypeError` | Instantiate `Span()` directly | Raises `TypeError: Can't instantiate abstract class` |
| `TypeError` | Instantiate `Trace()` directly | Raises `TypeError: Can't instantiate abstract class` |
| `TypeError` | Instantiate `Generation()` directly | Raises `TypeError: Can't instantiate abstract class` |
| `TypeError` | Subclass missing one abstract method | Raises `TypeError` on instantiation |
| `DeprecationWarning` | Call `backend.start_span("op", {})` | Exactly one `DeprecationWarning` emitted referencing `start_span` |

#### Boundary conditions

- A concrete `Span` subclass implementing all five required methods instantiates without error (REQ-113).
- `__exit__` returns `False` (not `None`, not `True`) in every code path — validated by `assert result is False` (REQ-121, REQ-133, REQ-145).
- `start_span()` with `parent=None` and `parent=<span_instance>` both succeed without raising (REQ-103).
- The `DeprecationWarning` from `start_span()` must be catchable via `warnings.catch_warnings(record=True)` (REQ-433).

#### Integration points

- `backend.py` has zero third-party dependencies; importable without `langfuse` installed.
- `noop/backend.py` and `langfuse/backend.py` both subclass these ABCs.
- `__init__.py` re-exports `Span`, `Trace`, `Generation`, `ObservabilityBackend` from this module.

#### Known test gaps

- The `Tracer` alias DeprecationWarning (REQ-337) is spec'd as SHOULD; if not emitted by implementation, that is a spec deviation but the test cannot force it.
- Performance assertions for `start_span()` overhead are out of scope for unit tests (no timing SLA on the deprecated path).

#### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files (`src/`), other modules' test specs, or the engineering guide directly.

---

### 2.2 `src/platform/observability/schemas.py` — Record Dataclasses

**Module purpose:** Defines `SpanRecord`, `TraceRecord`, and `GenerationRecord` as plain `@dataclass` types with zero third-party dependencies — passive containers for completed observation events.

**In scope:**
- Field presence and types for all three dataclasses
- Default field values (`start_ts` auto-set, `attributes`/`metadata` default to `{}`)
- Optional fields (`output`, `prompt_tokens`, `completion_tokens`, `end_ts`, `error_message`)
- Timestamp ordering invariant (`end_ts >= start_ts`)
- Importability without Langfuse SDK installed

**Out of scope:**
- Mutation by backend implementations (tested in backend specs)
- Serialization / deserialization (not part of this module's contract)
- Field validation at construction time (not performed — Python runtime only)

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| `SpanRecord` full construction | All required fields | Instance created; `status=="ok"`, `error_message is None` |
| `TraceRecord` minimal construction | `name`, `trace_id`, `metadata={}`, `start_ts`, `end_ts`, `status` | `trace_id` is non-None string |
| `GenerationRecord` with optional `None` fields | `output=None`, `prompt_tokens=None`, `completion_tokens=None` | Constructs without error |
| `GenerationRecord` with all fields | All fields including token counts and output | All fields present and accessible |
| `start_ts` auto-population | Construct `SpanRecord` without explicit `start_ts` | `start_ts` is a `float` close to `time.time()` |
| `attributes` default | Construct `SpanRecord` without `attributes` | `attributes == {}` |
| Import without Langfuse | Import `SpanRecord, TraceRecord, GenerationRecord` in env with no Langfuse | No `ImportError` raised |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| `TypeError` (Python runtime) | Omit required positional field (`name`, `trace_id`) | Python raises `TypeError` on construction |
| `TypeError` (Python runtime) | Pass `None` for `trace_id` | No validation — Python accepts it (dataclass does not validate types) |

#### Boundary conditions

- `end_ts >= start_ts` must hold for all properly constructed records (REQ-155).
- `start_ts` is populated at construction via `default_factory=time.time`, not at `end()` call time — test: construct a `SpanRecord`, wait briefly, then assert `start_ts` reflects construction time, not current time (REQ-155).
- `SpanRecord.trace_id` is a `str`, not `None` (REQ-151 pattern: `trace_id` must not be None when set by a backend).
- All three types importable as `from src.platform.observability.schemas import SpanRecord, TraceRecord, GenerationRecord` (REQ-157).

#### Integration points

- `schemas.py` has no imports from `backend.py`, `noop/`, or `langfuse/`.
- `noop/backend.py` and `langfuse/backend.py` may use these types to capture in-memory records for testing assertions.
- `__init__.py` does NOT re-export schema types (they are internal; consumers use ABCs).

#### Known test gaps

- No runtime type validation: passing `prompt_tokens="not_an_int"` does not raise at construction — only Python static analysis catches this. A mypy/pyright check, not a pytest test, is the right tool.
- `end_ts` is `None` until `end()` populates it. The ordering invariant `end_ts >= start_ts` can only be verified after a backend calls `end()`, so the pure dataclass unit test can only assert that `end_ts=None` at construction and that a backend-produced record satisfies the invariant.

#### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files (`src/`), other modules' test specs, or the engineering guide directly.

---

### 2.3 `src/platform/observability/__init__.py` — Public API Facade

**Module purpose:** Owns the process-wide `ObservabilityBackend` singleton, implements thread-safe `get_tracer()` via double-checked locking, provides the `@observe` decorator factory, and is the sole import surface for consumers.

**In scope:**
- `get_tracer()` singleton semantics (same instance on every call)
- `get_tracer()` thread safety (50-thread concurrent initialization)
- `_init_backend()` routing: `"noop"` → `NoopBackend`, `"langfuse"` → `LangfuseBackend`, unknown → `ValueError`
- `_init_backend()` fallback: `LangfuseBackend.__init__` failure → `NoopBackend` + warning log
- `@observe` decorator: span name defaulting, `functools.wraps`, input/output capture, error recording, re-raise
- `__all__` contract: exactly `["get_tracer", "observe", "Tracer", "Span", "Trace", "Generation"]`
- `Span`, `Trace`, `Generation` re-exported from `backend.py` (module attribute `__module__` check)
- `Tracer` alias: `Tracer is ObservabilityBackend`
- `_MAX_CAPTURE_LEN = 500` truncation

**Out of scope:**
- Internal behavior of `NoopBackend` or `LangfuseBackend` (tested in their own specs)
- Docker Compose or environment configuration (infrastructure spec)
- Deprecated `providers.py` shim (tested in `providers.py` spec)

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| `get_tracer()` returns singleton | Call `get_tracer()` twice after singleton reset | Both calls return the same object (`result_a is result_b`) |
| Provider `"noop"` → `NoopBackend` | `OBSERVABILITY_PROVIDER="noop"` | `type(get_tracer()).__name__ == "NoopBackend"` |
| Provider unset → `NoopBackend` | `OBSERVABILITY_PROVIDER` unset | Returns `NoopBackend` |
| Provider `"langfuse"` → `LangfuseBackend` | `OBSERVABILITY_PROVIDER="langfuse"`, mocked `get_client()` | Returns `LangfuseBackend` instance |
| `@observe` default name | `@observe()` on `Foo.bar` | Span created with name `"Foo.bar"` (`__qualname__`) |
| `@observe` explicit name | `@observe("my.op")` | Span created with name `"my.op"` |
| `@observe` `functools.wraps` | Apply to `def foo(): "doc"` | `foo.__name__=="foo"`, `foo.__doc__=="doc"` |
| `@observe` normal exit | Function returns `"result"` | Span `end(status="ok")` called; function return value preserved |
| `@observe(capture_input=True)` | Call `f(self, "arg1")` | Span has attribute `"input"` == `repr(("arg1",))[:500]` |
| `@observe(capture_output=True)` | Function returns `"hello"` | Span has attribute `"output"` == `repr("hello")[:500]` |
| Input truncation | `capture_input=True`, args repr > 500 chars | `"input"` attribute length == 500 |
| Output truncation | `capture_output=True`, return repr > 500 chars | `"output"` attribute length == 500 |
| `__all__` contents | Import `observability.__all__` | Exactly `["get_tracer", "observe", "Tracer", "Span", "Trace", "Generation"]` |
| `Tracer` alias | `from observability import Tracer, ObservabilityBackend` | `Tracer is ObservabilityBackend` |
| ABC re-export `__module__` | `Span.__module__` | `"src.platform.observability.backend"` (not `__init__`) |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| `ValueError` | `OBSERVABILITY_PROVIDER="datadog"` | `get_tracer()` raises `ValueError` containing `"datadog"` |
| `NoopBackend` fallback + warning | `OBSERVABILITY_PROVIDER="langfuse"`, `get_client()` raises `RuntimeError("no key")` | `get_tracer()` returns `NoopBackend`; warning log contains `"langfuse"` and `"no key"` |
| Exception re-raised by `@observe` | Decorated function raises `ValueError("boom")` | `ValueError` propagates; span has attribute `"error" == "boom"`; span ends with `status="error"` |
| No `"input"` attribute by default | `@observe()` (no capture flags) | Span has no attribute keyed `"input"` |
| No `"output"` attribute by default | `@observe()` (no capture flags) | Span has no attribute keyed `"output"` |

#### Boundary conditions

- Thread safety: 50 threads call `get_tracer()` simultaneously; exactly one backend object created — `len({id(r) for r in results}) == 1` (REQ-311).
- `capture_input=True` skips `args[0]` (i.e., `self`): call `f(self_obj, "a", "b")`, assert `"input"` is `repr(("a", "b"))[:500]`, not `repr((self_obj, "a", "b"))[:500]` (REQ-323).
- `@observe` with no arguments: `@observe()` — no positional string arg required (REQ-411).
- `@observe` on a classmethod and a plain function: both succeed without `TypeError` (REQ-313).
- `get_tracer()` return type annotation is `ObservabilityBackend`, not a concrete class (REQ-307) — verify `get_tracer.__annotations__["return"] is ObservabilityBackend`.
- After `LangfuseBackend` fallback, `get_tracer()` returns `NoopBackend` — verify `isinstance(get_tracer(), NoopBackend)` (REQ-171).
- Singleton reset between tests: `monkeypatch.setattr(obs_module, "_backend", None)` required for each factory test.

#### Integration points

- Calls `_init_backend()` internally on first `get_tracer()` call.
- Imports `NoopBackend` from `noop.backend` and `LangfuseBackend` from `langfuse.backend` inside `_init_backend()`.
- Reads `config.settings.OBSERVABILITY_PROVIDER` first, falls back to `os.environ["OBSERVABILITY_PROVIDER"]`.
- `@observe` calls `get_tracer().span(span_name)` as a context manager.

#### Known test gaps

- Performance SLA for `@observe` overhead (REQ-329, REQ-901, REQ-903) requires microbenchmark — not a standard pytest test; these should be in a dedicated benchmark suite.
- The `_MAX_CAPTURE_LEN` constant is an implementation detail; tests verify observed behavior (attribute length ≤ 500) rather than the constant value directly.
- `config.settings` fallback to `os.environ` is testable by patching, but the exact settings module import path must match the actual implementation's import.
- Thread-safety test is inherently non-deterministic; run with a sufficient thread count (≥ 50) and repeat count to minimize false-pass probability.

#### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files (`src/`), other modules' test specs, or the engineering guide directly.

---

### 2.4 `src/platform/observability/noop/backend.py` — NoopBackend

**Module purpose:** Provides `NoopBackend`, `NoopSpan`, `NoopTrace`, and `NoopGeneration` — concrete implementations that perform no operations, emit no output, and never raise under any input.

**In scope:**
- All four classes are concrete (no abstract method errors on instantiation)
- `isinstance` checks against ABCs: `NoopBackend` → `ObservabilityBackend`, `NoopSpan` → `Span`, `NoopTrace` → `Trace`, `NoopGeneration` → `Generation`
- All methods return `None` or a typed noop object; never raise
- `NoopBackend.span()` returns `NoopSpan`; `trace()` returns `NoopTrace`; `generation()` returns `NoopGeneration`
- `NoopTrace.span()` returns `NoopSpan`; `NoopTrace.generation()` returns `NoopGeneration`
- `flush()` and `shutdown()` return `None` immediately
- Context manager protocol: `__enter__` returns self; `__exit__` calls `end()`, returns `False`
- Zero imports from `langfuse` or any third-party SDK

**Out of scope:**
- Record population (noop backend does not produce `SpanRecord` etc. — tested in `schemas.py` and integration specs)
- Factory/singleton initialization (tested in `__init__.py` spec)

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| `NoopBackend()` instantiation | No args | Instance created; `isinstance(nb, ObservabilityBackend)` is `True` |
| `NoopBackend.span()` | `name="test.op"`, `attributes=None` | Returns `NoopSpan` instance; `isinstance(result, Span)` is `True` |
| `NoopBackend.trace()` | `name="trace1"`, `metadata=None` | Returns `NoopTrace` instance; `isinstance(result, Trace)` is `True` |
| `NoopBackend.generation()` | `name="g"`, `model="gpt-4"`, `input="hi"` | Returns `NoopGeneration` instance; `isinstance(result, Generation)` is `True` |
| `NoopBackend.flush()` | No args | Returns `None`; no error raised |
| `NoopBackend.shutdown()` | No args | Returns `None`; no error raised |
| `NoopSpan.set_attribute()` | `key="k"`, `value="v"` | Returns `None`; no error |
| `NoopSpan.end()` | `status="ok"`, `error=None` | Returns `None`; no error |
| `NoopGeneration.set_output()` | `"result text"` | Returns `None`; no error |
| `NoopGeneration.set_token_counts()` | `100, 42` | Returns `None`; no error |
| `NoopGeneration.end()` | `status="error"`, `error=RuntimeError("x")` | Returns `None`; no error |
| `NoopTrace.span()` | `name="child"` | Returns `NoopSpan`; `isinstance(result, Span)` is `True` |
| `NoopTrace.generation()` | `name="g"`, `model="m"`, `input="i"` | Returns `NoopGeneration`; `isinstance(result, Generation)` is `True` |
| Context manager `NoopSpan` | `with NoopBackend().span("x") as s:` | `s is not None`; no error; `__exit__` returns `False` |
| Context manager `NoopTrace` | `with NoopBackend().trace("t") as t:` | `t is not None`; no error; `__exit__` returns `False` |
| Context manager `NoopGeneration` | `with NoopBackend().generation("g","m","i") as g:` | `g is not None`; no error; `__exit__` returns `False` |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| (No errors — noop never raises) | `NoopSpan.set_attribute(None, None)` | Returns `None`; no exception |
| (No errors — noop never raises) | `NoopGeneration.set_token_counts(-1, -1)` | Returns `None`; no exception |
| (No errors — noop never raises) | `NoopTrace.span(None)` | Returns a `Span` instance (or no-op); no exception |
| (No errors — noop never raises) | `NoopSpan.end(status="bogus", error=object())` | Returns `None`; no exception |
| (No errors — noop never raises) | `NoopBackend.span(None)` | Returns `NoopSpan`; no exception |

#### Boundary conditions

- Each call to `NoopTrace.span()` returns a new `NoopSpan` instance (not a shared singleton) — verify via `s1 is not s2` (EG Section 3.4).
- `flush()` and `shutdown()` execution time is under 1ms (REQ-163) — assert with `time.perf_counter()` around the call.
- `NoopBackend` has zero third-party imports — verifiable by inspecting `sys.modules` before and after import, or by importing in a stripped environment (REQ-921).
- After `shutdown()` is called, subsequent calls to `span()`, `trace()`, `generation()`, and `flush()` on the same instance must not raise (REQ-111).

#### Integration points

- Subclasses `ObservabilityBackend` from `backend.py`.
- `NoopSpan`, `NoopTrace`, `NoopGeneration` subclass `Span`, `Trace`, `Generation` from `backend.py`.
- Used as fallback by `__init__.py` when `LangfuseBackend.__init__` fails.
- `langfuse/backend.py` returns `NoopSpan()`, `NoopTrace()`, `NoopGeneration()` on SDK failures (imports from this module).

#### Known test gaps

- Microbenchmark (mean call latency < 0.05ms over 10,000 iterations) is a performance test, not a unit test — excluded from standard pytest suite; requires a separate benchmark target (REQ-901).
- Verifying "zero allocation beyond object return" requires a profiling tool (e.g., `tracemalloc`), not a standard assertion — marked as a known gap.
- `NoopTrace.span(None)` behavior (passing `None` as name) is not explicitly contracted — test should assert no exception is raised and a `Span` instance is returned, without asserting the span's name value.

#### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files (`src/`), other modules' test specs, or the engineering guide directly.

---

### 2.5 `src/platform/observability/langfuse/backend.py` — LangfuseBackend

**Module purpose:** Implements the `ObservabilityBackend` ABC against the Langfuse v3 SDK. All `import langfuse` statements in the codebase are confined exclusively to this file. All observation methods are fail-open (exceptions caught, logged at WARNING). Only `flush()` and `shutdown()` propagate SDK exceptions.

**In scope:**
- `LangfuseBackend.__init__()` calls `get_client()` once; exceptions propagate (caller catches and falls back)
- `LangfuseBackend.span()`: routes through `trace_obj.span()` when `parent` is `LangfuseTrace`; else `client.start_observation(as_type="span", ...)`; fail-open → `NoopSpan` on error
- `LangfuseBackend.trace()`: calls `client.trace(name=name, metadata=metadata)`; returns `LangfuseTrace`; fail-open → `NoopTrace` on error
- `LangfuseBackend.generation()`: calls `client.start_observation(as_type="generation", ...)`; returns `LangfuseGeneration`; fail-open → `NoopGeneration` on error
- `LangfuseSpan.set_attribute()`: calls `inner.update(metadata={key: value})`; fail-open
- `LangfuseSpan.end()`: calls `inner.update(level="ERROR", status_message=str(error))` then `inner.end()` on error; `inner.end()` only on success; fail-open
- `LangfuseGeneration.set_output()`: calls `inner.update(output=output)`; fail-open
- `LangfuseGeneration.set_token_counts()`: calls `inner.update(usage={"input": prompt_tokens, "output": completion_tokens})`; fail-open
- `LangfuseGeneration.end()`: same error-level update logic as `LangfuseSpan.end()`; fail-open
- `LangfuseTrace.span()`: calls `trace_obj.span(name=name, metadata=attributes or {})`; fail-open → `NoopSpan`
- `LangfuseTrace.generation()`: calls `trace_obj.generation(...)`; fail-open → `NoopGeneration`
- `LangfuseBackend.flush()`: calls `client.flush()` with no try/except — propagates exceptions
- `LangfuseBackend.shutdown()`: calls `client.shutdown()` with no try/except — propagates exceptions
- `langfuse/__init__.py` exports only `LangfuseBackend`; `LangfuseSpan` is not importable from `langfuse/`
- WARNING log emitted on every caught SDK exception
- No hardcoded credentials

**Out of scope:**
- Singleton factory (tested in `__init__.py` spec)
- ABC contract enforcement (tested in `backend.py` spec)
- NoopBackend behavior (tested in `noop/backend.py` spec)

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| `LangfuseBackend()` init | Mocked `get_client()` returns `mock_client` | `backend._client is mock_client` |
| `backend.trace()` | `name="rag.req"`, `metadata={"k":"v"}` | `mock_client.trace` called with `name="rag.req"`, `metadata={"k":"v"}`; returns `LangfuseTrace` |
| `backend.span()` no parent | `name="s"`, `attributes={}`, `parent=None` | `mock_client.start_observation(as_type="span", ...)` called; returns `LangfuseSpan` |
| `backend.span()` with parent trace | `parent=langfuse_trace_instance` | `trace_obj.span(...)` called (not `client.start_observation`); returns `LangfuseSpan` |
| `backend.generation()` | `name="g"`, `model="gpt-4"`, `input="hi"` | `mock_client.start_observation(as_type="generation", ...)` called; returns `LangfuseGeneration` |
| `LangfuseSpan.set_attribute()` | `key="env"`, `value="prod"` | `mock_inner.update(metadata={"env": "prod"})` called exactly once |
| `LangfuseSpan.end()` success | `status="ok"`, `error=None` | `mock_inner.end()` called; `mock_inner.update` NOT called with `level="ERROR"` |
| `LangfuseSpan.end()` error | `status="error"`, `error=ValueError("oops")` | `mock_inner.update(level="ERROR", status_message="oops")` called before `mock_inner.end()` |
| `LangfuseGeneration.set_output()` | `"response text"` | `mock_inner.update(output="response text")` called exactly once |
| `LangfuseGeneration.set_token_counts()` | `100, 50` | `mock_inner.update(usage={"input": 100, "output": 50})` called exactly once |
| `LangfuseGeneration.end()` error | `error=RuntimeError("fail")` | `mock_inner.update(level="ERROR", status_message="fail")` called before `mock_inner.end()` |
| `LangfuseTrace.span()` | `name="child"`, `attributes=None` | `trace_obj.span(name="child", metadata={})` called (None → `{}`); returns `LangfuseSpan` |
| `LangfuseTrace.generation()` | Valid args | `trace_obj.generation(...)` called; returns `LangfuseGeneration` |
| `backend.flush()` | No args | `mock_client.flush()` called exactly once; returns `None` |
| `backend.shutdown()` | No args | `mock_client.shutdown()` called exactly once; returns `None` |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| SDK exception on `get_client()` | `get_client()` raises `RuntimeError("no key")` | `LangfuseBackend.__init__()` re-raises `RuntimeError`; no instance returned |
| `LangfuseSpan.set_attribute` fail-open | `mock_inner.update` raises `ConnectionError` | Returns `None`; no exception propagated; WARNING logged |
| `LangfuseSpan.end` fail-open | `mock_inner.end` raises `TimeoutError` | Returns `None`; no exception propagated; WARNING logged |
| `LangfuseGeneration.set_output` fail-open | `mock_inner.update` raises `Exception` | Returns `None`; no exception propagated; WARNING logged |
| `LangfuseGeneration.set_token_counts` fail-open | `mock_inner.update` raises `Exception` | Returns `None`; no exception propagated; WARNING logged |
| `LangfuseGeneration.end` fail-open | `mock_inner.end` raises `Exception` | Returns `None`; no exception propagated; WARNING logged |
| `LangfuseTrace.span` fail-open | `trace_obj.span` raises `Exception` | Returns `NoopSpan()`; no exception propagated; WARNING logged |
| `LangfuseTrace.generation` fail-open | `trace_obj.generation` raises `Exception` | Returns `NoopGeneration()`; no exception propagated; WARNING logged |
| `LangfuseBackend.span` fail-open | `client.start_observation` raises `Exception` | Returns `NoopSpan()`; no exception propagated; WARNING logged |
| `LangfuseBackend.trace` fail-open | `client.trace` raises `Exception` | Returns `NoopTrace()`; no exception propagated; WARNING logged |
| `LangfuseBackend.flush` propagates | `client.flush()` raises `TimeoutError` | `TimeoutError` propagates to caller; NOT caught |
| `LangfuseBackend.shutdown` propagates | `client.shutdown()` raises `RuntimeError` | `RuntimeError` propagates to caller; NOT caught |

#### Boundary conditions

- `langfuse/__init__.py` exports only `LangfuseBackend` — `from src.platform.observability.langfuse import LangfuseSpan` must raise `ImportError` (REQ-203).
- `LangfuseBackend.__init__` accepts no `host`, `public_key`, or `secret_key` constructor parameters — `LangfuseBackend(host="x")` raises `TypeError` (REQ-247).
- `issubclass(LangfuseBackend, ObservabilityBackend)` returns `True`; `inspect.isabstract(LangfuseBackend)` returns `False` (REQ-205).
- `LangfuseTrace.span(name, attributes=None)` must pass `metadata={}` (not `metadata=None`) to `trace_obj.span()` when `attributes` is `None` (REQ-227).
- WARNING logs are emitted to `rag.observability.langfuse` logger — validate with `caplog.set_level(logging.WARNING, logger="rag.observability.langfuse")` (EG Section 7.6).
- Credential values never appear in log output — sentinel credentials test (REQ-929 security).

#### Integration points

- Imports `ObservabilityBackend`, `Span`, `Trace`, `Generation` from `backend.py`.
- Imports `NoopSpan`, `NoopTrace`, `NoopGeneration` from `noop.backend` (for fallback returns).
- `langfuse.get_client` is imported inside `__init__()` — deferred import, not at module level.
- Called by `_init_backend()` in `__init__.py` when `OBSERVABILITY_PROVIDER="langfuse"`.

#### Known test gaps

- Langfuse SDK token count field names (`usage.input` / `usage.output` vs. v2 names) can only be verified against a real Langfuse server or a detailed SDK mock — unit tests verify only that `inner.update(usage={"input": ..., "output": ...})` is called with the correct dict structure.
- Non-blocking async dispatch (REQ-905): verifying that `span()` / `end()` do not block the calling thread on a non-responsive host requires a mock server with configurable latency — this is a functional/integration test, not a unit test.
- `flush()` 10-second deadline under load (REQ-911): requires a mock server with simulated latency — excluded from standard unit tests.
- Context manager protocol (`__enter__` / `__exit__`) for `LangfuseSpan`, `LangfuseTrace`, `LangfuseGeneration` is inherited from the `Span`/`Trace`/`Generation` ABCs in `backend.py`. If the ABC implementation is correct (tested in `backend.py` spec), no additional unit test is required here, but a smoke test is recommended.

#### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files (`src/`), other modules' test specs, or the engineering guide directly.

---

### 2.6 `src/platform/observability/providers.py` — Deprecated Shim

**Module purpose:** Thin module-level shim that emits a `DeprecationWarning` at import time and re-exports `get_tracer` from the public API. No behavior of its own.

**In scope:**
- `DeprecationWarning` emitted at module import time
- `get_tracer` imported from `providers` resolves to the same object as `get_tracer` from `src.platform.observability`

**Out of scope:**
- All other behaviors (delegated entirely to `__init__.py`)

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| `get_tracer` accessible from `providers` | `from observability.providers import get_tracer` | Import succeeds; `get_tracer` is callable |
| Same `get_tracer` object | Import from both paths | `providers.get_tracer is observability.get_tracer` is `True` |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| `DeprecationWarning` emitted | `import src.platform.observability.providers` inside `warnings.catch_warnings(record=True)` | Exactly one `DeprecationWarning` captured; message references the old import path |

#### Boundary conditions

- The `DeprecationWarning` must be catchable — use `warnings.catch_warnings(record=True)` with `warnings.simplefilter("always")` (REQ-335).
- If `PYTHONWARNINGS=error` is set, the `DeprecationWarning` becomes a `DeprecationError` — this is intentional and documented behavior.

#### Integration points

- Re-exports from `src.platform.observability.__init__`.
- No other modules depend on `providers.py` after migration.

#### Known test gaps

- Whether `providers.py` emits the warning on _every_ import vs. only the first depends on Python's warning filter state. Tests must use `warnings.catch_warnings(record=True)` with `simplefilter("always")` to bypass the default "once per location" filter.
- `REQ-337` (Tracer alias emits DeprecationWarning) is SHOULD-priority and may not be implemented — if not implemented, the test should be marked `xfail`.

#### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files (`src/`), other modules' test specs, or the engineering guide directly.

---

## 3. Integration Test Specs

Integration tests exercise cross-module data flows. They use the noop backend by default and mock the Langfuse SDK for Langfuse-path tests. No live Langfuse server is required.

**Test location:** `tests/platform/observability/test_integration.py`

**Shared setup:**

```python
import src.platform.observability as obs_module

@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    monkeypatch.setattr(obs_module, "_backend", None)
    yield
    monkeypatch.setattr(obs_module, "_backend", None)
```

---

### 3.1 Happy path: `get_tracer()` with `OBSERVABILITY_PROVIDER=noop`

**Scenario:** Consumer calls `get_tracer()` with noop provider → creates spans and traces → all calls succeed silently → noop path verified.

**Preconditions:** `OBSERVABILITY_PROVIDER` unset or `"noop"`.

**Steps and assertions:**

| Step | Action | Expected |
|---|---|---|
| 1 | `monkeypatch.setenv("OBSERVABILITY_PROVIDER", "noop")` + reset singleton | — |
| 2 | `backend = get_tracer()` | `isinstance(backend, ObservabilityBackend)` is `True`; `type(backend).__name__ == "NoopBackend"` |
| 3 | `span = backend.span("test.op", {"k": "v"})` | `isinstance(span, Span)` is `True` |
| 4 | `span.set_attribute("x", 1)` | No exception; returns `None` |
| 5 | `span.end(status="ok")` | No exception; returns `None` |
| 6 | `with backend.trace("t") as trace:` | `trace` is not `None` |
| 7 | `child = trace.span("child.op")` | `isinstance(child, Span)` is `True` |
| 8 | `child.set_attribute("y", 2)` | No exception |
| 9 | Exit `with` block normally | No exception; `trace.__exit__` returned `False` |
| 10 | `backend.flush()` | No exception; returns `None` |
| 11 | `backend.shutdown()` | No exception; returns `None` |
| 12 | `get_tracer()` called again | Same object as step 2 (`result_a is result_b`) |

**Verification focus:** Full noop pipeline from `get_tracer()` through span lifecycle — no errors, correct types throughout.

---

### 3.2 Langfuse fallback: `LangfuseBackend.__init__` failure

**Scenario:** `OBSERVABILITY_PROVIDER=langfuse` but `get_client()` raises — factory catches the error, falls back to `NoopBackend`, logs a warning.

**Preconditions:** `OBSERVABILITY_PROVIDER="langfuse"`. `get_client` is monkeypatched to raise `RuntimeError("no api key")`.

**Steps and assertions:**

| Step | Action | Expected |
|---|---|---|
| 1 | `monkeypatch.setenv("OBSERVABILITY_PROVIDER", "langfuse")` + reset singleton | — |
| 2 | Patch `langfuse.get_client` to raise `RuntimeError("no api key")` | — |
| 3 | `backend = get_tracer()` with `caplog` capturing `rag.observability` at WARNING | No exception raised from `get_tracer()` |
| 4 | Assert `type(backend).__name__ == "NoopBackend"` | `NoopBackend` was used as fallback |
| 5 | Assert warning log contains `"langfuse"` | Backend name in log |
| 6 | Assert warning log contains `"no api key"` | Exception message in log |
| 7 | `span = backend.span("test")` | `isinstance(span, Span)` is `True`; no error |
| 8 | `backend.flush()` | No exception |

**Verification focus:** Full fallback chain — `LangfuseBackend` construction failure → `NoopBackend` instantiated → warning logged → subsequent calls work normally.

---

### 3.3 `@observe` error path: exception in decorated function

**Scenario:** Function decorated with `@observe` raises an exception → span records error attribute → exception re-raised → span ends with `status="error"`.

**Preconditions:** Backend is `NoopBackend` (default). Use a `SpySpan` test double that records calls to `set_attribute` and `end`.

**Implementation note:** Since `NoopBackend` does not expose `set_attribute` call records, this integration test requires a test-double backend that captures span method calls. Implement a minimal `SpyBackend` / `SpySpan`:

```python
class SpySpan:
    def __init__(self):
        self.attributes = {}
        self.end_calls = []
    def set_attribute(self, key, value):
        self.attributes[key] = value
    def end(self, status="ok", error=None):
        self.end_calls.append({"status": status, "error": error})
    def __enter__(self): return self
    def __exit__(self, et, ev, tb):
        if ev is not None:
            self.end(status="error", error=ev)
        else:
            self.end(status="ok")
        return False

class SpyBackend(ObservabilityBackend):
    def __init__(self):
        self.spans = []
    def span(self, name, attributes=None, parent=None):
        s = SpySpan()
        self.spans.append(s)
        return s
    def trace(self, name, metadata=None): ...
    def generation(self, name, model, input, metadata=None): ...
    def flush(self): pass
    def shutdown(self): pass
```

**Steps and assertions:**

| Step | Action | Expected |
|---|---|---|
| 1 | Reset singleton; inject `SpyBackend` as `obs_module._backend` | — |
| 2 | Define `@observe("test.op") def boom(): raise ValueError("kaboom")` | — |
| 3 | Call `boom()` inside `pytest.raises(ValueError)` | `ValueError("kaboom")` propagates to caller |
| 4 | `spy = obs_module._backend.spans[0]` | Span was created |
| 5 | `assert spy.attributes.get("error") == "kaboom"` | Error string recorded on span |
| 6 | `assert spy.end_calls[0]["status"] == "error"` | Span ended with error status |
| 7 | `assert spy.end_calls[0]["error"] is ...` | The original `ValueError` instance passed to `end()` |

**Verification focus:** End-to-end `@observe` error path — span created → `"error"` attribute set → `end(status="error")` called → exception re-raised unchanged.

---

## 4. FR Traceability Matrix

> Every REQ-xxx from the spec appears in this table. FRs covered by a module unit test, integration test, or both are noted. FRs requiring live infrastructure or benchmarking are marked as "not covered — known gap".

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| REQ-101 | MUST | `ObservabilityBackend` ABC; direct instantiation raises `TypeError` | `backend.py` unit | — |
| REQ-103 | MUST | `backend.span()` returns `Span` instance | `backend.py` unit (ABC contract) | Integration 3.1 |
| REQ-105 | MUST | `backend.trace()` returns `Trace` instance | `backend.py` unit | Integration 3.1 |
| REQ-107 | MUST | `backend.generation()` returns `Generation` instance | `noop/backend.py` unit | — |
| REQ-109 | MUST | `flush()` abstract; drains pending writes | `noop/backend.py` unit (returns None); `langfuse/backend.py` mock | Integration 3.1, 3.2 |
| REQ-111 | MUST | `shutdown()` abstract; post-shutdown calls don't raise | `noop/backend.py` unit | — |
| REQ-113 | MUST | `Span` ABC; missing abstract method raises `TypeError` | `backend.py` unit | — |
| REQ-115 | MUST | `set_attribute` accepts any Python object, returns None | `noop/backend.py` unit; `langfuse/backend.py` mock | — |
| REQ-117 | MUST | `end()` stores `status` and `error` in `SpanRecord` | `schemas.py` + `langfuse/backend.py` mock | Integration 3.3 |
| REQ-119 | MUST | `Span.__enter__` returns self | `backend.py` unit | Integration 3.1 |
| REQ-121 | MUST | `Span.__exit__` calls `end()` correctly, returns `False` | `backend.py` unit | Integration 3.3 |
| REQ-123 | MUST | `set_attribute` / `end` exceptions caught internally | `langfuse/backend.py` mock | — |
| REQ-125 | MUST | `Trace` ABC; missing method raises `TypeError` | `backend.py` unit | — |
| REQ-127 | MUST | `Trace.span()` child shares `trace_id` | `langfuse/backend.py` mock (SDK call verification) | not covered — known gap (requires record inspection via live or captured output) |
| REQ-129 | MUST | `Trace.generation()` child shares `trace_id` | `langfuse/backend.py` mock | not covered — known gap |
| REQ-131 | MUST | `Trace.__enter__` returns self | `backend.py` unit | Integration 3.1 |
| REQ-133 | MUST | `Trace.__exit__` returns `False` | `backend.py` unit | — |
| REQ-135 | MUST | `Trace.span()` / `.generation()` exceptions caught internally | `langfuse/backend.py` mock | — |
| REQ-137 | MUST | `Generation` ABC; missing method raises `TypeError` | `backend.py` unit | — |
| REQ-139 | MUST | `Generation.set_output()` stores output | `langfuse/backend.py` mock | — |
| REQ-141 | MUST | `Generation.set_token_counts()` stores both values | `langfuse/backend.py` mock | — |
| REQ-143 | MUST | `Generation.end()` same contract as `Span.end()` | `langfuse/backend.py` mock | — |
| REQ-145 | MUST | `Generation.__enter__` returns self; `__exit__` returns `False` | `backend.py` unit | — |
| REQ-147 | MUST | `Generation` method exceptions caught internally | `langfuse/backend.py` mock | — |
| REQ-149 | MUST | `SpanRecord` dataclass fields | `schemas.py` unit | — |
| REQ-151 | MUST | `TraceRecord` dataclass fields | `schemas.py` unit | — |
| REQ-153 | MUST | `GenerationRecord` dataclass with optional fields | `schemas.py` unit | — |
| REQ-155 | MUST | `start_ts` / `end_ts` from `time.time()` | `schemas.py` unit | — |
| REQ-157 | SHOULD | Schemas importable without Langfuse SDK | `schemas.py` unit | — |
| REQ-159 | MUST | `NoopBackend` is concrete `ObservabilityBackend` subclass | `noop/backend.py` unit | Integration 3.1 |
| REQ-161 | MUST | `NoopBackend` methods return typed noop objects, never raise | `noop/backend.py` unit | Integration 3.1 |
| REQ-163 | MUST | `NoopBackend.flush()` is a no-op; returns None | `noop/backend.py` unit | Integration 3.1 |
| REQ-165 | MUST | All `NoopXxx` methods don't raise under any input | `noop/backend.py` unit | — |
| REQ-167 | MUST | `OBSERVABILITY_PROVIDER` selects backend at startup | `__init__.py` unit | Integration 3.1, 3.2 |
| REQ-169 | MUST | Singleton: all calls return same object | `__init__.py` unit | Integration 3.1 |
| REQ-171 | MUST | Init failure → `NoopBackend` fallback + warning | `__init__.py` unit | Integration 3.2 |
| REQ-201 | MUST | All `langfuse` imports confined to `langfuse/backend.py` | `langfuse/backend.py` unit (import isolation check) | not covered — known gap (static scan, not pytest) |
| REQ-203 | MUST | `langfuse/__init__.py` exports only `LangfuseBackend` | `langfuse/backend.py` unit | — |
| REQ-205 | MUST | `LangfuseBackend` is concrete `ObservabilityBackend` subclass | `langfuse/backend.py` unit | Integration 3.2 |
| REQ-207 | MUST | `LangfuseBackend.__init__` propagates `get_client()` exceptions | `langfuse/backend.py` unit | Integration 3.2 |
| REQ-209 | MUST | Factory catches `LangfuseBackend` init failure → `NoopBackend` | `__init__.py` unit | Integration 3.2 |
| REQ-211 | MUST | `LangfuseBackend.span()` routes through trace object when parent is `LangfuseTrace` | `langfuse/backend.py` mock | — |
| REQ-213 | MUST | `LangfuseBackend.trace()` calls `client.trace(name=, metadata=)` | `langfuse/backend.py` mock | — |
| REQ-215 | MUST | `LangfuseBackend.generation()` calls `start_observation(as_type="generation")` | `langfuse/backend.py` mock | — |
| REQ-217 | MUST | `LangfuseSpan.set_attribute()` calls `inner.update(metadata={key: value})` | `langfuse/backend.py` mock | — |
| REQ-219 | MUST | `LangfuseSpan.set_attribute()` fail-open with WARNING | `langfuse/backend.py` mock | — |
| REQ-221 | MUST | `LangfuseSpan.end()` calls `inner.update(level="ERROR")` before `inner.end()` on error | `langfuse/backend.py` mock | Integration 3.3 |
| REQ-223 | MUST | `LangfuseSpan.end()` fail-open with WARNING | `langfuse/backend.py` mock | — |
| REQ-225 | MUST | `LangfuseSpan` context manager: `__enter__` returns self, `__exit__` returns False | `langfuse/backend.py` mock | — |
| REQ-227 | MUST | `LangfuseTrace.span()` creates child via `trace_obj.span()`, None attrs → `{}` | `langfuse/backend.py` mock | — |
| REQ-229 | MUST | `LangfuseTrace.generation()` creates child via `trace_obj.generation()` | `langfuse/backend.py` mock | — |
| REQ-231 | MUST | `LangfuseTrace` methods fail-open with WARNING | `langfuse/backend.py` mock | — |
| REQ-233 | MUST | `LangfuseTrace` context manager: returns self, exit returns False | `langfuse/backend.py` mock | — |
| REQ-235 | MUST | `LangfuseGeneration.set_output()` calls `inner.update(output=...)` | `langfuse/backend.py` mock | — |
| REQ-237 | MUST | `LangfuseGeneration.set_token_counts()` calls `inner.update(usage={"input":..., "output":...})` | `langfuse/backend.py` mock | — |
| REQ-239 | MUST | `LangfuseGeneration.end()` same error-level logic as `LangfuseSpan.end()` | `langfuse/backend.py` mock | — |
| REQ-241 | MUST | `LangfuseGeneration` methods fail-open with WARNING | `langfuse/backend.py` mock | — |
| REQ-243 | MUST | `LangfuseGeneration` context manager protocol | `langfuse/backend.py` mock | — |
| REQ-245 | MUST | No hardcoded credentials in `langfuse/backend.py` | `langfuse/backend.py` unit (static/credential sentinel) | — |
| REQ-247 | MUST | `LangfuseBackend.__init__` accepts no credential params | `langfuse/backend.py` unit | — |
| REQ-249 | MUST | `flush()` propagates SDK exceptions | `langfuse/backend.py` mock | — |
| REQ-251 | MUST | `shutdown()` propagates SDK exceptions | `langfuse/backend.py` mock | — |
| REQ-301 | MUST | All public symbols importable from `src.platform.observability` | `__init__.py` unit | — |
| REQ-303 | MUST | `__all__` is the authoritative public API surface | `__init__.py` unit | — |
| REQ-305 | MUST | `get_tracer()` returns same instance on every call | `__init__.py` unit | Integration 3.1 |
| REQ-307 | MUST | `get_tracer()` return annotation is `ObservabilityBackend` | `__init__.py` unit | — |
| REQ-309 | MUST | `get_tracer()` callable without `langfuse` installed | `__init__.py` unit (stripped env) | not covered — known gap (environment setup required) |
| REQ-311 | MUST | `get_tracer()` thread-safe (50-thread test) | `__init__.py` unit | — |
| REQ-313 | MUST | `@observe` applies to plain functions, methods, classmethods | `__init__.py` unit | — |
| REQ-315 | MUST | `@observe` uses `functools.wraps` | `__init__.py` unit | — |
| REQ-317 | MUST | `@observe` default span name = `func.__qualname__` | `__init__.py` unit | — |
| REQ-319 | MUST | `capture_input` defaults to `False` | `__init__.py` unit | — |
| REQ-321 | MUST | `capture_output` defaults to `False` | `__init__.py` unit | — |
| REQ-323 | MUST | `capture_input=True` → `repr(args[1:])[:500]` as `"input"` | `__init__.py` unit | Integration 3.3 |
| REQ-325 | MUST | `capture_output=True` → `repr(result)[:500]` as `"output"` | `__init__.py` unit | — |
| REQ-327 | MUST | Exception → `"error"` attribute + re-raise | `__init__.py` unit | Integration 3.3 |
| REQ-329 | MUST | `@observe` with NoopBackend: p99 overhead ≤ 1ms over 1,000 calls | not covered — known gap (benchmark suite required) | — |
| REQ-331 | MUST | `providers.get_tracer` same callable as `observability.get_tracer` | `providers.py` unit | — |
| REQ-333 | MUST | `Tracer is ObservabilityBackend` | `__init__.py` unit | — |
| REQ-335 | SHOULD | `providers` import emits `DeprecationWarning` | `providers.py` unit | — |
| REQ-337 | SHOULD | `Tracer` alias emits `DeprecationWarning` on access | `__init__.py` unit (marked `xfail` if not implemented) | — |
| REQ-339 | MUST | `__all__ == ["get_tracer", "observe", "Tracer", "Span", "Trace", "Generation"]` | `__init__.py` unit | — |
| REQ-341 | MUST | `Span`, `Trace`, `Generation` `__module__` is `backend.py` | `__init__.py` unit | — |
| REQ-401 | MUST | Consumers import from `src.platform.observability` only | not covered — known gap (static grep, not pytest) | — |
| REQ-403 | MUST | Public package root exports `get_tracer` and `observe` | `__init__.py` unit | — |
| REQ-405 | MUST | No consumer imports `langfuse` directly | not covered — known gap (static grep) | — |
| REQ-407 | SHOULD | Decorator used in consumer files | not covered — known gap (code review / static analysis) | — |
| REQ-409 | MUST | `@observe` ends span automatically on success and exception | `__init__.py` unit | Integration 3.3 |
| REQ-411 | MUST | `@observe` accepts single positional string; no other mandatory args | `__init__.py` unit | — |
| REQ-413 | MUST | Context manager span ended automatically in both exit modes | `backend.py` unit; `noop/backend.py` unit | Integration 3.1 |
| REQ-415 | MUST | `span.set_attribute()` inside `with` block records attribute | `noop/backend.py` unit; `langfuse/backend.py` mock | Integration 3.1 |
| REQ-417 | MUST | `trace()` usable as context manager grouping multiple spans | `noop/backend.py` unit | Integration 3.1 |
| REQ-419 | SHOULD | `trace.generation()` creates child generation entry | `langfuse/backend.py` mock | — |
| REQ-421 | MUST | Attribute keys must be snake_case | not covered — known gap (linter / static analysis) | — |
| REQ-423 | MUST | No provider-specific attribute key prefixes | not covered — known gap (static grep) | — |
| REQ-425 | SHOULD | Shared attribute keys as constants | not covered — known gap (code review) | — |
| REQ-427 | MUST | Attribute values must be scalar types | not covered — known gap (documentation + linter; no runtime enforcement in noop path) | — |
| REQ-429 | MUST | Consumer imports migrated from `.providers` | not covered — known gap (static grep) | — |
| REQ-431 | MUST | Consumer call sites migrated from `.start_span()` | not covered — known gap (static grep) | — |
| REQ-433 | SHOULD | `start_span()` alias active during migration | `backend.py` unit | — |
| REQ-435 | MUST | Module-level `_tracer_instance` globals removed | not covered — known gap (static grep) | — |
| REQ-437 | MUST | Double-end span via context manager + explicit `end()` → exactly one end event | `noop/backend.py` unit (with spy) | — |
| REQ-439 | MUST | No consumer `except` block solely for span status | not covered — known gap (static analysis) | — |
| REQ-441 | MUST | No consumer references `LangfuseBackend` / `NoopBackend` by name | not covered — known gap (static grep) | — |
| REQ-501 | MUST | `langfuse` Docker service with `image: langfuse/langfuse:3` | not covered — known gap (docker-compose config inspection, not pytest) | — |
| REQ-503 | MUST | Port `${LANGFUSE_PORT:-3000}` exposed | not covered — known gap | — |
| REQ-505 | MUST | `langfuse` depends_on `langfuse-db` with `service_healthy` | not covered — known gap | — |
| REQ-507 | MUST | `langfuse-db` service with `postgres:16-alpine` | not covered — known gap | — |
| REQ-509 | MUST | `langfuse-db` env vars: `POSTGRES_USER/PASSWORD/DB=langfuse` | not covered — known gap | — |
| REQ-511 | MUST | Both services in `profiles: [observability]` | not covered — known gap | — |
| REQ-513 | MUST | `observability` profile independent from `monitoring` profile | not covered — known gap | — |
| REQ-515 | MUST | `langfuse` health check: HTTP GET `/api/public/health` → 200 | not covered — known gap (requires running Docker) | — |
| REQ-517 | MUST | `langfuse-db` health check: `pg_isready -U langfuse` | not covered — known gap | — |
| REQ-519 | SHOULD | `langfuse-db` health check timing params | not covered — known gap | — |
| REQ-521 | MUST | `langfuse-db` mounts `langfuse-db-data` named volume | not covered — known gap | — |
| REQ-523 | MUST | `langfuse-db-data` declared in top-level `volumes` | not covered — known gap | — |
| REQ-525 | MUST | `.env.example` has `LANGFUSE_NEXTAUTH_SECRET` | not covered — known gap (file grep, not pytest) | — |
| REQ-527 | MUST | `.env.example` has `LANGFUSE_SALT` | not covered — known gap | — |
| REQ-529 | MUST | `.env.example` has `LANGFUSE_ENCRYPTION_KEY` | not covered — known gap | — |
| REQ-531 | MUST | `.env.example` has `LANGFUSE_PORT`, `LANGFUSE_INIT_ORG_ID`, etc. | not covered — known gap | — |
| REQ-533 | MUST | `rag-api` passes `RAG_OBSERVABILITY_PROVIDER` | not covered — known gap | — |
| REQ-535 | MUST | `rag-worker` passes `RAG_OBSERVABILITY_PROVIDER` | not covered — known gap | — |
| REQ-537 | MUST | Both services pass `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | not covered — known gap | — |
| REQ-539 | MUST | Env var blocks not modified to remove Langfuse keys | not covered — known gap | — |
| REQ-541 | SHOULD | Inline comments on Langfuse service entries | not covered — known gap | — |
| REQ-901 | MUST | NoopBackend mean latency < 0.05ms over 10,000 iterations | not covered — known gap (benchmark suite) | — |
| REQ-903 | MUST | `@observe` p99 overhead ≤ 1ms (1,000 calls) | not covered — known gap (benchmark suite) | — |
| REQ-905 | MUST | Langfuse dispatches non-blocking | not covered — known gap (requires mock server with latency) | — |
| REQ-907 | MUST | `span()` / `end()` < 0.5ms CPU per call | not covered — known gap (profiling benchmark) | — |
| REQ-909 | MUST | Backend exceptions never propagate to pipeline | `langfuse/backend.py` mock; `__init__.py` unit | Integration 3.2, 3.3 |
| REQ-911 | MUST | `flush()` completes within 10s under load | not covered — known gap (mock server with latency) | — |
| REQ-913 | MUST | Backend singleton concurrent access: no corruption/deadlock | `__init__.py` unit (50-thread test) | — |
| REQ-915 | MUST | Unreachable host: 100 span calls without exception | not covered — known gap (requires network mock) | — |
| REQ-917 | SHOULD | `flush()` logs WARNING when > 5s | not covered — known gap (time mock + slow server) | — |
| REQ-919 | MUST | New backend: one directory + one factory entry, no other changes | not covered — known gap (architectural review) | — |
| REQ-921 | MUST | Factory parameterized: `noop` / `langfuse` / unknown → correct routing | `__init__.py` unit | — |
| REQ-923 | MUST | All public classes/functions have docstrings + `@summary` | not covered — known gap (`pydocstyle` lint check) | — |
| REQ-925 | SHOULD | Migration completable one file at a time | not covered — known gap (manual migration test) | — |
| REQ-927 | SHOULD | New backend ≤ 150 lines | not covered — known gap (line count review) | — |
| REQ-929 | MUST | Credentials never appear in log output | `langfuse/backend.py` unit (sentinel credential test) | — |
| REQ-931 | MUST | No hardcoded credentials in source | not covered — known gap (`detect-secrets` CI step) | — |
| REQ-933 | MUST | `capture_input` / `capture_output` default `False`; default spans have no PII attributes | `__init__.py` unit | — |
| REQ-935 | SHOULD | `capture_input=True` logs WARNING at startup | not covered — known gap (not implemented by default) | — |
| REQ-937 | MUST | Langfuse service healthy within 60s | not covered — known gap (requires running Docker) | — |
| REQ-939 | MUST | Provider selectable via single env var without file changes | `__init__.py` unit | Integration 3.1, 3.2 |
| REQ-941 | MUST | Old import path functionally equivalent for ≥ 1 release | `providers.py` unit | — |
