# Server API and Service Layer — Specification Summary

**Companion spec:** `SERVER_API_SPEC.md` | Version: 1.0
**Domain:** Server API | **Status:** Implemented Baseline
**Purpose:** Concise digest of the companion specification — intent, scope, structure, and key decisions without duplicating requirement-level detail.
**See also:** `RETRIEVAL_QUERY_SPEC.md`, `RETRIEVAL_GENERATION_SPEC.md`, `PLATFORM_SERVICES_SPEC.md`

---

## 1) Generic System Overview

### Purpose

This system defines the HTTP API surface and service coordination layer for a retrieval-augmented generation platform. It exists to provide clients — human users, browser applications, and AI assistant integrations — with a stable, well-typed interface into the platform's query capabilities. Without a formal API contract with predictable request and response shapes, error semantics, and streaming behavior, clients cannot be built reliably and the system cannot be operated safely at scale.

### How It Works

A request enters the system at the HTTP boundary, where it is validated against a typed schema and assigned a unique correlation identifier. The API tier is intentionally lightweight: it enforces admission control (rejecting or queuing requests beyond a configured concurrency limit), attaches policy context, and hands work off immediately through a durable task dispatch mechanism. No inference or model computation occurs in this process.

Dispatched work is received by a backend execution tier — a separate process that has preloaded all necessary inference models at startup and holds them resident in memory. This tier executes the full retrieval-and-generation pipeline and returns a result. For query endpoints, results flow back either as a single structured response or as an incremental event stream that delivers generation tokens in real time as they are produced, followed by a final event containing full metadata (retrieved chunks, stage timings, confidence).

Errors anywhere in the pipeline are normalized into a uniform envelope structure before reaching the client. During streaming, errors that occur after the response has begun are delivered as structured error events within the stream — not as HTTP status codes, which have already been sent.

The system also exposes adjacent surfaces: conversation lifecycle management for multi-turn interactions, admin endpoints for credential and quota governance, a metrics exposition endpoint for platform telemetry, and an optional tooling adapter surface that lets AI assistants invoke query and health operations as structured tool calls.

### Tunable Knobs

Operators can configure the maximum number of in-flight requests the API tier will hold before queuing or rejecting, and how long a queued request will wait before being declined. The workflow dispatch layer has configurable execution timeout policies that determine when a hung or slow execution is abandoned and the client receives a timeout response. Workers can optionally cache results for repeated identical query payloads, with a configurable cache lifetime. Cross-origin access rules (which origins, methods, and headers are permitted) are configurable without code changes. All configuration surfaces are externalized and take effect on restart.

### Design Rationale

The most consequential architectural decision is the strict separation of the API process from the model-execution process. Inference models are memory-heavy and require specialized hardware. Merging them with the HTTP-handling process would prevent independent scaling, create memory contention, and force slow container startup. By keeping the API tier lightweight and stateless, it can scale horizontally on commodity resources while the execution tier scales independently based on GPU or compute availability.

Durable workflow dispatch was chosen over direct RPC for reliability: transient worker failures do not require client-side retry logic, because the workflow layer retries on the client's behalf. This makes the API surface appear reliable even when the execution tier is briefly unavailable.

Uniform error and response envelopes were chosen to enable a single error-handling path in clients and to prevent information leakage — no stack traces, internal paths, or system prompt content should ever reach the client.

### Boundary Semantics

Entry point: an HTTP request arriving at the API server, carrying a query payload and authentication credentials. Exit point: an HTTP response (or SSE event sequence) returned to the client with a structured payload and a correlation identifier. The API tier is responsible for validation, admission control, correlation, dispatch, and response serialization. Retrieval pipeline logic, model inference, and conversation memory are out of scope for this system — they are handled downstream by the execution tier and are covered by separate specifications.

---

## 2) Header

| Field | Value |
|-------|-------|
| Companion spec | `SERVER_API_SPEC.md` |
| Spec version | 1.0 |
| Spec status | Implemented Baseline |
| Summary last synced | 2026-04-10 |
| Domain | Server API |

---

## 3) Scope and Boundaries

**Entry point:** HTTP request arrives at the API server.
**Exit point:** HTTP response (or SSE event sequence) is returned to the client with a structured payload.

**In scope:**
- Endpoint contracts and request/response schemas
- Error envelopes (standard and console variants)
- Streaming protocol (SSE event types and error delivery)
- Workflow dispatch and timeout policies
- Worker lifecycle (startup preload, graceful shutdown)
- Admission control and request correlation
- Admin endpoints (key and quota management)
- Conversation lifecycle endpoints
- Metrics exposition endpoint
- Tooling adapter surface (optional)
- Container deployment requirements
- Non-functional requirements (latency, availability, configuration)

**Out of scope:**
- Retrieval pipeline behavior (see `RETRIEVAL_QUERY_SPEC.md` / `RETRIEVAL_GENERATION_SPEC.md`)
- Auth, quotas, and admission control policies (see `PLATFORM_SERVICES_SPEC.md`)
- Ingestion pipeline behavior (see `INGESTION_PIPELINE_SPEC.md`)
- Web console UI behavior (see `WEB_CONSOLE_SPEC.md`)
- CLI client behavior (see `CLI_SPEC.md`)

---

## 4) Architecture / Pipeline Overview

```
Client (CLI / Browser / API Integration / AI Assistant)
    |
    v
[1] API SERVER (stateless)
    HTTP routing, admission control, correlation, CORS
    |
    v
[2] WORKFLOW DISPATCH
    Durable task submission, timeout and retry policy
    |
    v
[3] WORKER (model-loaded)
    Preloaded models; executes retrieval and generation
    |
    v
[4] RESPONSE / STREAM
    Structured JSON response or SSE event stream
    with error envelope guarantee
```

**Data flow summary:**

| Stage | Input | Output |
|-------|-------|--------|
| API Server | HTTP request with credentials | Validated request + request ID |
| Workflow Dispatch | Validated payload | Durable workflow execution ID |
| Worker Execution | Workflow activity + query parameters | RAG pipeline result |
| Response / Stream | Pipeline result or generation tokens | JSON response or SSE event stream |

---

## 5) Requirement Framework

**ID convention:** `REQ-xxx` (numeric, no prefix family separation)

**Priority keywords:** RFC 2119 — MUST (absolute), SHOULD (recommended), MAY (optional)

**Requirement format:** Each requirement includes description, rationale, and acceptance criteria.

**ID ranges by section:**

| Section | ID Range | Component |
|---------|----------|-----------|
| 3 | REQ-1xx | API Architecture and Process Separation |
| 4 | REQ-2xx | Endpoint Contracts and Schemas |
| 5 | REQ-3xx | Error Handling and Envelopes |
| 6 | REQ-4xx | Streaming Protocol |
| 7 | REQ-5xx | Workflow Dispatch and Worker Lifecycle |
| 8 | REQ-6xx | Tooling Adapter Surface |
| 9 | REQ-7xx | Container Deployment |
| 10 | REQ-9xx | Non-Functional Requirements |

**Totals:** 34 requirements — 26 MUST, 8 SHOULD, 0 MAY.

---

## 6) Functional Requirement Domains

**REQ-1xx — API Architecture and Process Separation**
Covers strict separation of API and worker processes, end-to-end request correlation, bounded concurrency admission control, and CORS middleware configuration.

**REQ-2xx — Endpoint Contracts and Schemas**
Covers the query endpoint (request schema with all tunable parameters, response schema with chunks and timings), health endpoint, admin endpoints (key and quota lifecycle), metrics endpoint, conversation lifecycle endpoints, and an optional root discovery endpoint.

**REQ-3xx — Error Handling and Envelopes**
Covers the universal error envelope for all non-2xx responses, normalization of HTTP exceptions and unhandled errors (with no information leakage), field-level validation error detail in 422 responses, and the dedicated console envelope for web-facing endpoints.

**REQ-4xx — Streaming Protocol**
Covers SSE streaming for query endpoints, structured event types (retrieval completion, generation token, final result), in-stream error events for mid-stream failures, and asynchronous observability emission to avoid stream latency impact.

**REQ-5xx — Workflow Dispatch and Worker Lifecycle**
Covers durable dispatch through a workflow engine, model preloading at worker startup, graceful shutdown with drain, configurable execution and queue timeout policies, and optional activity-level result caching.

**REQ-6xx — Tooling Adapter Surface**
Covers an optional structured tooling protocol adapter exposing query and health as discoverable tool calls for AI assistant and IDE integrations.

**REQ-7xx — Container Deployment**
Covers lean API container image (no model weights), non-root process execution with built-in health checks, independent horizontal scaling of API and worker tiers, and named deployment profiles for common environment configurations.

**REQ-9xx — Non-Functional Requirements**
Covers API processing overhead targets (latency budget for validation, auth, dispatch, and serialization), startup readiness within 30 seconds, graceful degradation behavior for each dependency failure mode, and full externalization of all configuration.

---

## 7) Non-Functional and Security Themes

**Latency:** The spec defines API-tier processing overhead targets (request parsing, auth enforcement, workflow dispatch, response serialization) to ensure latency budget is consumed by retrieval and generation, not HTTP plumbing.

**Availability and graceful degradation:** Defined degraded behavior for each dependency failure mode — workflow engine unavailable, worker pool empty, and metrics backend unavailable — ensures the API process remains alive and informative rather than crashing.

**Startup readiness:** The API server must be ready to serve health checks within a defined window after container launch.

**Information security:** Error normalization must prevent leakage of stack traces, internal paths, and system prompt content. Container images must run as non-root users.

**Configuration externalization:** All behavioral parameters must be settable via environment variables or configuration files, with no hardcoded values requiring code changes.

---

## 8) Design Principles

| Principle | Description |
|-----------|-------------|
| **Thin API, Heavy Worker** | The API process handles HTTP, policy, and dispatch only; all ML inference runs in workers |
| **Envelope Consistency** | Every response (success and error) follows a predictable schema; clients never encounter raw exceptions |
| **Streaming First** | Generation endpoints default to streaming; non-streaming is an opt-in mode |
| **Correlation Everywhere** | Every request carries a unique ID that propagates through dispatch, execution, and response |

---

## 9) Key Decisions

- **Process separation is absolute:** The API server must not import or load ML model libraries. This enables independent scaling, prevents memory contention, and keeps the API container lean.
- **Durable workflow dispatch over direct RPC:** Transient worker failures are absorbed by the workflow layer rather than surfaced to clients, eliminating the need for client-side retry logic.
- **Universal error envelopes:** Every non-2xx response and every in-stream error follows a single schema, making a single client-side error handler sufficient for all endpoints.
- **SSE streaming as the default:** Generation is streaming-first; non-streaming is an opt-in mode. This reflects a design assumption that generation latency warrants real-time delivery.
- **Stateless API tier:** All durable state lives in external stores. This is a foundational assumption enabling horizontal scaling of the API tier without coordination overhead.
- **Tooling adapter as optional surface:** AI assistant and IDE integrations are addressed through an optional adapter rather than bespoke endpoints, keeping the core API surface clean.

---

## 10) Acceptance and Evaluation

The spec defines a system-level acceptance criteria table covering six dimensions:

- **Process separation** — verified by confirming no ML model imports in the API process
- **Request correlation coverage** — 100% of responses must include a request ID
- **Error envelope compliance** — 100% of non-2xx responses must use the standard envelope
- **Streaming reliability** — token stream must complete or deliver a structured error event
- **Worker lifecycle correctness** — graceful startup (preload) and shutdown (drain) verified
- **Container security baseline** — non-root user, health check, and lean image confirmed

Specific thresholds are defined in the companion spec. The spec does not include an evaluation or feedback framework beyond these acceptance criteria.

---

## 11) External Dependencies

| Dependency | Role | Requirement |
|------------|------|-------------|
| Durable workflow engine | Task dispatch, retry, and timeout orchestration | Required — query execution depends on it |
| Task queue | Work distribution between API and workers | Required — implicit in workflow dispatch |
| ML model weights and inference runtime | Model preloading in worker processes | Required for workers; must not be present in API container |
| Metrics backend | Telemetry collection | Optional — API continues serving if unavailable |
| External stores (state, conversation memory) | Durable state outside the stateless API process | Required — in-process state breaks horizontal scaling |

---

## 12) Companion Documents

This summary is a **Layer 2 — Spec Summary** document. It provides intent, scope, and structural overview without duplicating requirement-level detail.

| Document | Role |
|----------|------|
| `SERVER_API_SPEC.md` | Layer 3 — Authoritative Spec (normative; read for individual requirements, acceptance criteria, and traceability) |
| `RETRIEVAL_QUERY_SPEC.md` | Covers retrieval pipeline query behavior (out of scope here) |
| `RETRIEVAL_GENERATION_SPEC.md` | Covers generation pipeline behavior (out of scope here) |
| `PLATFORM_SERVICES_SPEC.md` | Covers auth, quotas, and admission control policies (out of scope here) |
| `INGESTION_PIPELINE_SPEC.md` | Covers ingestion pipeline behavior (out of scope here) |
| `WEB_CONSOLE_SPEC.md` | Covers web console UI behavior (out of scope here) |
| `CLI_SPEC.md` | Covers CLI client behavior (out of scope here) |
| `server/README.md` | As-built runtime behavior reference |

The spec also includes a requirements traceability matrix (Section 12) and a glossary of terms (Section 1.3) — both are in the companion spec and not reproduced here.

---

## 13) Sync Status

| Field | Value |
|-------|-------|
| Spec version summarized | 1.0 |
| Spec date | 2026-03-13 |
| Summary written | 2026-04-10 |
| Alignment status | In sync |
