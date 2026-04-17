# Swappable Observability Subsystem — Specification Summary

## 1) Generic System Overview

### Purpose

The observability subsystem gives the platform a structured, low-overhead way to record what happens inside pipeline execution — which stages ran, how long they took, what went wrong, and what models were called. Without it, diagnosing latency regressions, tracing failures across pipeline stages, and attributing LLM cost to specific requests requires parsing logs manually or guessing. The subsystem also enforces a clean separation between the platform's instrumentation vocabulary and any particular backend vendor, so that switching observability providers requires a configuration change rather than a code rewrite.

### How It Works

When application code invokes a traced function — either via a function decorator or a manual context manager — the observability layer intercepts the call and opens a span record. A span captures a name, a start timestamp, a set of key-value attributes, and eventually an end timestamp and status. Spans can be grouped under a trace, which is a named logical unit representing one end-to-end pipeline request. Within a trace, individual LLM calls can be recorded as a distinct observation type that carries additional fields: the model identifier, the prompt input, and the completion output with token counts.

All instrumentation calls route through a process-wide singleton — a single backend instance that is selected at startup based on environment configuration and held for the lifetime of the process. The singleton pattern means all pipeline stages share one consistent destination and one flush queue. The backend selection factory reads the provider identifier from the environment, validates it, and instantiates the matching backend. If instantiation fails, the factory logs a warning and falls back to the no-operation backend silently.

Two backends are specified: a no-operation backend that satisfies the full interface contract with zero computation and no I/O, and an integration backend that forwards observations to a persistent trace-storage service via its SDK. The integration backend operates asynchronously — it buffers observations and dispatches them off the hot path, so a slow or unreachable trace server does not block pipeline execution. At shutdown or at defined activity boundaries, callers invoke a flush operation that drains buffered observations synchronously.

The trace storage service runs as an optional container alongside the application. It is not started by default and must be explicitly requested via a profile flag in the container orchestration layer.

### Tunable Knobs

**Provider selection** — Operators choose which backend is active at startup. Changing the provider requires only updating an environment variable; no source files are modified. When the variable is absent, the no-operation backend is used automatically.

**Input and output capture** — Each instrumented function can optionally record the input arguments and return value as span attributes. Both are disabled by default to avoid capturing sensitive user data or model outputs unintentionally. When enabled, values are truncated to a fixed character limit before being recorded.

**Trace server host and port** — The address at which the trace storage service listens is externally configurable, allowing it to be pointed at a local development instance or a shared team environment without code changes.

**Port binding** — The container port exposed by the trace service on the host is configurable, enabling it to coexist with other services on restricted developer machines.

### Design Rationale

The subsystem was designed around two hard constraints: observability must never crash the application it observes, and changing observability providers must require zero application code changes. These constraints drove the abstract base class model — all backend implementations satisfy the same interface, and all consumer code programs to that interface exclusively. Provider-specific SDK imports are confined to a single subdirectory, making each provider a self-contained unit that can be added or removed without touching shared modules.

The singleton pattern was chosen over per-call backend construction to avoid multiple flush queues and duplicate observations. Thread-safe initialization was specified explicitly because the platform runs concurrent workers that initialize simultaneously.

The decorator-based instrumentation path exists because the prior approach required verbose try/finally blocks around every instrumented call, which was a consistent source of instrumentation bugs — spans were silently left open when exception paths were incorrectly handled. The decorator centralizes that lifecycle management.

### Boundary Semantics

Entry point: any call site in the ingestion or retrieval layers that imports from the public observability package root and invokes a decorator or context manager. Exit point: trace and span data visible in the trace storage UI when the integration backend is active; no output when the no-operation backend is active. The subsystem does not modify the data flowing through the pipeline — it only observes and records it. Responsibility for interpreting, querying, and acting on trace data belongs to the trace storage service, which is outside this spec's boundary.

---

## 2) Header

| Field | Value |
|---|---|
| **Companion spec** | `OBSERVABILITY_SPEC.md` |
| **Spec version** | 1.0 (Draft, 2026-03-27) |
| **Summary purpose** | Digest of scope, architecture, requirement structure, and key decisions for technical stakeholders |
| **See also** | `OBSERVABILITY_DESIGN.md`, `OBSERVABILITY_IMPLEMENTATION_DOCS.md`, `OBSERVABILITY_ENGINEERING_GUIDE.md`, `OBSERVABILITY_TEST_DOCS.md` |

---

## 3) Scope and Boundaries

**Entry points**
- Call sites in the ingestion and retrieval layers that import from the public observability package root

**Exit points**
- Trace and span records visible in the trace storage UI when the integration backend is active
- No output when the no-operation backend is active

**System boundary**
- The observability package under the platform layer (all provider logic and the public API facade)
- The container orchestration file (trace storage service and its database)
- Consumer call sites (instrumentation patterns and import discipline)

**Out of process**
- The trace storage server itself (OSS, run via container); the spec covers how the project starts and connects to it, not how it operates internally

**Out of scope for this specification**
- Alternative backend integrations beyond the two specified providers
- Standard telemetry protocol exporters
- Multi-tenant trace isolation (per-user trace namespacing)
- Automatic PII redaction from span attributes
- Distributed tracing across service boundaries (cross-process context propagation)

**Out of scope for this project (acknowledged, not planned)**
- Production-hardened trace service deployment (TLS, external database, backup)
- Custom UI or dashboard layer built on trace data
- Automatic propagation of trace context into LLM API calls via backend hooks

---

## 4) Architecture / Pipeline Overview

```
  Call Sites (Ingest + Retrieval layers)
  ┌──────────────────────────────────────────────────┐
  │  @observe("stage.name")                          │
  │  with get_tracer().trace("name") as t: ...       │
  │  with get_tracer().span("name") as s: ...        │
  └────────────────────┬─────────────────────────────┘
                       │
                       ▼
  Public API Facade  [package root __init__.py]
  ┌──────────────────────────────────────────────────┐
  │  get_tracer()  observe()  Span  Trace  Generation│
  │  → returns process-wide backend singleton        │
  └────────────────────┬─────────────────────────────┘
                       │
                       ▼
  Abstract Backend Contract  [backend.py]
  ┌──────────────────────────────────────────────────┐
  │  ObservabilityBackend (ABC)                      │
  │  ├── Span (ABC)        set_attribute / end / ctx │
  │  ├── Trace (ABC)       span() / generation() / ctx│
  │  └── Generation (ABC)  set_output / set_tokens   │
  │  [schemas.py] SpanRecord / TraceRecord /         │
  │               GenerationRecord (dataclasses)      │
  └──────┬───────────────────────────┬───────────────┘
         │ provider=integration      │ provider=noop / unset
         ▼                           ▼
  ┌────────────────────┐   ┌────────────────────────┐
  │  Integration       │   │  NoopBackend           │
  │  Backend           │   │  all methods: no-ops   │
  │  (provider-scoped  │   │  zero I/O, zero alloc  │
  │   subdirectory)    │   └────────────────────────┘
  │  async buffering   │
  └────────┬───────────┘
           │ SDK calls (async, non-blocking)
           ▼
  ╔══════════════════════════════════════════╗
  ║  Container Layer  (profile: observability)║
  ║  ┌──────────────┐  depends_on (healthy)  ║
  ║  │ trace server │ ──────────────────────►║
  ║  └──────┬───────┘                        ║
  ║         │ SQL                            ║
  ║         ▼                               ║
  ║  ┌──────────────┐                       ║
  ║  │  trace DB    │  named volume          ║
  ║  └──────────────┘  (data persisted)     ║
  ╚══════════════════════════════════════════╝
```

**Data flow summary:**

| Stage | Input | Output |
|---|---|---|
| 1. Instrumentation | `@observe` / context manager call | Request to open a trace or span |
| 2. Backend resolution | Provider env var at process startup | Process-wide backend singleton |
| 3. Backend dispatch | `trace()` / `span()` / `generation()` call | Concrete Span, Trace, or Generation instance |
| 4a. Integration recording | Span/trace/generation lifecycle events | SDK calls (async, non-blocking) |
| 4b. Noop recording | Same events | (no output) |
| 5. Transmission | SDK payload | HTTP to trace service |
| 6. Persistent storage | Ingested records | Durable trace state |
| 7. Developer inspection | Browser request to service UI | Rendered trace timeline |

---

## 5) Requirement Framework

**ID convention:** `REQ-` prefix, numeric suffix. Priority uses RFC 2119 keywords: **MUST** (absolute), **SHOULD** (strong recommendation, deviation requires documented reason), **MAY** (optional).

**Format per requirement:** blockquote with `Description`, `Rationale`, and `Acceptance Criteria` fields. Every requirement is individually testable.

**ID ranges:**

| ID Range | Domain |
|---|---|
| REQ-1xx | Backend Abstraction |
| REQ-2xx | Integration Backend |
| REQ-3xx | Public API & Decorators |
| REQ-4xx | Consumer Integration |
| REQ-5xx | Infrastructure |
| REQ-9xx | Non-Functional Requirements |

A traceability matrix in Section 9 of the spec cross-references every requirement ID to its section, priority, and one-line summary.

---

## 6) Functional Requirement Domains

**Backend Abstraction (REQ-100 to REQ-199)**
Defines the abstract base classes for the backend, span, trace, and generation contracts; the typed dataclass schemas; the no-operation backend implementation; and the config-driven singleton factory including fail-open fallback behavior.

**Integration Backend (REQ-200 to REQ-299)**
Covers provider isolation (SDK imports confined to one subdirectory), the concrete backend implementation and its wrapper types for spans, traces, and generations, error-suppression at every SDK call boundary, credential-only-via-environment discipline, and flush/shutdown lifecycle propagation.

**Public API & Decorators (REQ-300 to REQ-399)**
Specifies the stable package root import surface, the singleton accessor function and its thread-safety requirements, the function decorator (name defaulting, input/output capture toggles, error recording, metadata preservation), backward-compatible aliases for both the legacy import path and the legacy type name, and the explicit `__all__` declaration.

**Consumer Integration (REQ-400 to REQ-499)**
Governs how pipeline call sites use the subsystem: import path discipline, decorator vs. context manager selection, attribute key naming conventions, scalar-only attribute value types, migration steps from the legacy pattern (import path, method name, module-level singleton variable), and prohibited patterns (double-ending spans, redundant error-catch blocks, direct concrete backend references).

**Infrastructure (REQ-500 to REQ-599)**
Defines the container service definitions for the trace server and its database: image versions, port bindings, profile-based opt-in, dependency ordering with health checks, named volume persistence, required environment variable entries in the example config file, and provider env var passthrough to the application services.

---

## 7) Non-Functional and Security Themes

**Performance**
- No-operation backend overhead is bounded to sub-millisecond per call
- Decorator overhead with no-operation backend bounded at p99 under 1ms per call
- Integration backend dispatches asynchronously; no blocking I/O on the instrumented thread
- Per-span CPU time on the hot path bounded at sub-millisecond averages

**Reliability and Resilience**
- All backend errors during span creation, end, and flush are caught internally and never propagate to callers
- Flush operation has a defined time bound for use at worker activity boundaries
- Backend singleton is safe for concurrent access from a thread pool without data corruption or deadlock
- Unreachable trace service does not cause span creation to block or raise

**Maintainability and Extensibility**
- Adding a new provider requires changes to exactly two files; no consumer or ABC modifications are needed
- Backend selection is config-only; no source changes required to switch providers
- All public classes and functions require docstrings; all modules require summary blocks
- Migration from legacy import pattern is completable file-by-file; both patterns must operate simultaneously during migration

**Security**
- Credentials must never appear in log output at any log level
- No credentials may be hardcoded as source literals; static scanning is a defined acceptance criterion
- Input and output capture default to off; enabling either emits a startup warning to make opt-in auditable

**Deployment**
- Trace service must reach healthy state within 60 seconds on developer hardware
- Provider selection requires only an environment variable; no file modifications needed between environments
- Legacy import path must remain functional for at least one release after migration is introduced

---

## 8) Design Principles

**Fail-open** — Any error in the observability layer is caught and silently suppressed; observability must never crash the application it observes.

**Provider-agnostic consumers** — No provider-SDK symbol may appear in any import statement outside the provider's subdirectory; consumers interact only with the abstract interface and public API.

**Config-driven selection** — The active backend is chosen at startup by reading a single environment variable; switching providers requires no code change.

**Stable public API** — The package root is the only permitted import surface; internal module paths are implementation details.

**Zero-overhead noop** — When observability is unconfigured or explicitly disabled, the active backend performs no computation, no allocation beyond a trivial return value, and no I/O.

---

## 9) Key Decisions

**Abstract base class as the backend contract** — Defines substitutability by enforcement rather than convention. Any implementation that satisfies the ABC can be selected at runtime without consumer changes.

**Process-wide singleton** — One backend instance per process prevents split flush queues, duplicate observations, and inconsistent provider state across concurrent workers.

**Fail-open fallback on backend init failure** — If the configured backend cannot initialize, the factory falls back to the no-operation backend with a warning rather than crashing. This keeps the application alive even when the trace service is misconfigured.

**Decorator as the primary instrumentation surface** — Eliminates the try/finally span-lifecycle pattern that was the primary source of instrumentation bugs in the prior implementation.

**Provider subdirectory isolation** — All provider-specific SDK imports are confined to a single subdirectory. Consumers and shared modules have no dependency on any particular provider. Adding a provider means creating one new directory; removing one means deleting it.

**Backward-compatible aliases for the migration period** — The legacy import path and the legacy type name are preserved as aliases that emit deprecation warnings, allowing incremental migration without a big-bang cutover.

**Profile-based opt-in for infrastructure** — The trace service and its database are not started unless explicitly requested via a Docker Compose profile flag, consistent with the existing pattern for other optional infrastructure services.

---

## 10) Acceptance and Evaluation

The spec defines acceptance criteria for every individual requirement in blockquote format. Acceptance is verified through:

- **Unit tests** covering ABC contract conformance, singleton behavior, decorator semantics, and noop correctness
- **Integration tests** covering the full backend lifecycle against a mock trace service
- **Static analysis checks** for import discipline (no provider symbols in consumer code, no credentials in source)
- **Concurrency stress tests** verifying thread-safe singleton initialization and concurrent span creation
- **Microbenchmarks** validating overhead bounds for both the no-operation and integration backends
- **Container smoke tests** polling the trace service health endpoint after startup

Tests must not require a live trace service. The spec explicitly requires that the no-operation backend be importable and testable with zero third-party dependencies installed.

---

## 11) External Dependencies

**Required**
- Provider SDK (v3) — declared as a project dependency; used exclusively within the integration backend's subdirectory
- Container orchestration tooling — used to start the optional trace service via profile flag

**Optional (operator-activated)**
- Trace storage service — OSS, run via container; the application backend falls back to no-operation if the service is unavailable
- Trace database — dedicated PostgreSQL instance; separate from the application database to prevent schema conflicts

**Downstream contract**
- The `rag-api` and `rag-worker` services receive the provider selection variable and the trace service credentials through their container environment blocks; this passthrough is a stable contract that must not be silently removed

---

## 12) Companion Documents

This summary is a digest of `OBSERVABILITY_SPEC.md` (the authoritative requirements document). It omits individual requirement IDs, threshold values, and traceability matrix detail — read the spec for those.

| Document | Purpose |
|---|---|
| `OBSERVABILITY_SPEC.md` | Authoritative requirements, acceptance criteria, traceability matrix |
| `OBSERVABILITY_DESIGN.md` | Technical design: task decomposition and code contracts |
| `OBSERVABILITY_IMPLEMENTATION_DOCS.md` | Implementation source of truth before code was written |
| `OBSERVABILITY_ENGINEERING_GUIDE.md` | Post-implementation guide: what was built and how components work |
| `OBSERVABILITY_TEST_DOCS.md` | Test planning: what to test for each module |

---

## 13) Sync Status

| Field | Value |
|---|---|
| **Spec version summarized** | 1.0 |
| **Summary written** | 2026-04-10 |
| **Status** | In sync with OBSERVABILITY_SPEC.md v1.0 |
