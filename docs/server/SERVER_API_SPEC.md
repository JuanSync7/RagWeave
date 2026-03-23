# Server API and Service Layer Specification

**AION Knowledge Management Platform**
Version: 1.0 | Status: Implemented Baseline | Domain: Server API

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-13 | AI Assistant | Initial specification reverse-engineered from implemented server layer |

> **Document intent:** This is a normative requirements/specification document for the HTTP API server and service layer.
> For retrieval pipeline behavior, see `RETRIEVAL_QUERY_SPEC.md` / `RETRIEVAL_GENERATION_SPEC.md`. For platform-level auth/quotas/observability, see `PLATFORM_SERVICES_SPEC.md`.
> For as-built runtime behavior, refer to `server/README.md` and `src/retrieval/README.md`.

---

## 1. Scope & Definitions

### 1.1 Problem Statement

The RAG system requires a well-defined HTTP API surface that separates the lightweight request-handling process from the heavyweight model-loading worker process. Without a formal API contract, clients cannot rely on stable request/response schemas, error semantics, or streaming behavior across releases.

### 1.2 Scope

This specification defines requirements for the **server API and service layer** of the RAG system. The boundary is:

- **Entry point:** HTTP request arrives at the API server.
- **Exit point:** HTTP response (or streaming event sequence) is returned to the client with structured payloads.

Everything between these points is in scope, including endpoint contracts, request/response schemas, error envelopes, streaming protocol, workflow dispatch, worker lifecycle, and tooling adapter surfaces.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **API Server** | The lightweight HTTP process that accepts requests, enforces policies, and dispatches work to backend workers. No ML models are loaded in this process. |
| **Worker** | A backend process that preloads ML models (embedding, reranking, generation) and executes retrieval activities. Workers receive work from a durable task queue. |
| **Workflow** | A durable execution unit that orchestrates one or more worker activities with retry semantics and timeout policies |
| **Error Envelope** | A standardized JSON response structure used for all non-2xx responses, including error code, message, details, and request ID |
| **Console Envelope** | A standardized JSON response structure used for web console endpoints, wrapping success data or error payloads with a request ID |
| **SSE** | Server-Sent Events — the streaming protocol used for real-time token delivery during answer generation |
| **MCP Adapter** | A tooling protocol adapter that exposes the RAG API as structured tool calls for AI assistant integrations |
| **Request Slot** | A bounded concurrency permit that limits the number of in-flight requests to prevent overload |

### 1.4 Requirement Priority Levels

This document uses RFC 2119 language:

- **MUST** — Absolute requirement. The system is non-conformant without it.
- **SHOULD** — Recommended. May be omitted only with documented justification.
- **MAY** — Optional. Included at the implementor's discretion.

### 1.5 Requirement Format

> **REQ-xxx** | Priority: MUST/SHOULD/MAY
> **Description:** What the system shall do.
> **Rationale:** Why this requirement exists.
> **Acceptance Criteria:** How to verify conformance.

Requirements are grouped by section with the following ID ranges:

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

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | The API server is a stateless HTTP process; all durable state lives in external stores | Horizontal scaling of the API tier breaks if in-process state is introduced |
| A-2 | Workers preload ML models at startup and keep them in memory for the worker lifetime | Per-request model loading would violate latency SLOs |
| A-3 | A durable workflow engine manages task dispatch, retry, and timeout policies | Without durable dispatch, transient failures require client-side retry logic |
| A-4 | API and workers run in separate containers with independent scaling profiles | Co-locating API and models in one process prevents independent scaling |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **Thin API, Heavy Worker** | The API process handles HTTP, policy, and dispatch only; all ML inference runs in workers |
| **Envelope Consistency** | Every response (success and error) follows a predictable schema; clients never encounter raw exceptions |
| **Streaming First** | Generation endpoints default to streaming; non-streaming is an opt-in mode |
| **Correlation Everywhere** | Every request carries a unique ID that propagates through dispatch, execution, and response |

### 1.8 Out of Scope

- Retrieval pipeline behavior (see `RETRIEVAL_QUERY_SPEC.md` / `RETRIEVAL_GENERATION_SPEC.md`)
- Auth, quotas, and admission control policies (see `PLATFORM_SERVICES_SPEC.md`)
- Ingestion pipeline behavior (see `INGESTION_PIPELINE_SPEC.md`)
- Web console UI behavior (see `WEB_CONSOLE_SPEC.md`)
- CLI client behavior (see `CLI_SPEC.md`)

---

## 2. System Overview

### 2.1 Architecture Diagram

```
Client (CLI / Browser / API Integration / AI Assistant)
    │
    ▼
┌──────────────────────────────────────┐
│ [1] API SERVER (stateless)           │
│     HTTP routing, policy enforcement │
│     Request correlation, streaming   │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [2] WORKFLOW DISPATCH                │
│     Durable task submission          │
│     Timeout and retry policy         │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [3] WORKER (model-loaded)            │
│     Preloaded embedding, reranker,   │
│     generator models; executes       │
│     retrieval activities             │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [4] RESPONSE / STREAM                │
│     Structured JSON or SSE stream    │
│     with error envelope guarantee    │
└──────────────────────────────────────┘
```

### 2.2 Data Flow Summary

| Stage | Input | Output |
|-------|-------|--------|
| API Server | HTTP request with auth credentials | Validated request with principal context and request ID |
| Workflow Dispatch | Validated request payload | Durable workflow execution ID |
| Worker Execution | Workflow activity with query parameters | RAG pipeline result (chunks, scores, generated answer) |
| Response / Stream | Pipeline result or generation tokens | Structured JSON response or SSE event stream |

---

## 3. API Architecture and Process Separation

> **REQ-101** | Priority: MUST
> **Description:** The system MUST separate the API server process from the model-loading worker process. The API server MUST NOT load ML models (embedding, reranking, or generation models) into its own process memory.
> **Rationale:** ML models consume significant GPU/CPU memory. Loading them in the API process would prevent independent scaling and cause the API server to compete with inference for memory and compute.
> **Acceptance Criteria:** The API server starts and serves requests without importing ML model libraries. Worker processes load models at startup and keep them in memory. The API and worker can be scaled independently.

> **REQ-102** | Priority: MUST
> **Description:** The system MUST attach a unique request identifier to every inbound HTTP request. The identifier MUST propagate through workflow dispatch, worker execution, and the final response. If the client provides a request ID header, it MUST be honored.
> **Rationale:** Without end-to-end correlation, debugging failures across API → dispatch → worker requires manual timestamp correlation, which is error-prone and slow.
> **Acceptance Criteria:** Every response includes a request ID header. The same ID appears in API logs, workflow execution records, and observability traces. A client-provided ID is echoed back unchanged.

> **REQ-103** | Priority: MUST
> **Description:** The system MUST implement bounded concurrency control at the API tier using a configurable maximum in-flight request count. When the limit is reached, new requests MUST wait for a configurable queue timeout before being rejected with a structured overload response.
> **Rationale:** Unbounded request acceptance under load causes cascading latency degradation and memory exhaustion. Bounded admission with fast rejection keeps the system predictable.
> **Acceptance Criteria:** Under sustained load exceeding the configured limit, excess requests receive a 503 response within the configured queue timeout. The in-flight count is observable via metrics.

> **REQ-104** | Priority: MUST
> **Description:** The API server MUST support CORS (Cross-Origin Resource Sharing) middleware with configurable allowed origins, methods, and headers.
> **Rationale:** Browser-based clients (web console, external integrations) require CORS headers to make cross-origin requests to the API.
> **Acceptance Criteria:** Browser requests from allowed origins receive appropriate CORS headers. Preflight OPTIONS requests are handled correctly.

---

## 4. Endpoint Contracts and Schemas

> **REQ-201** | Priority: MUST
> **Description:** The system MUST expose a query endpoint that accepts a structured query payload and returns a structured response with processed query, confidence, action, retrieved chunks, generated answer, stage timings, and conversation identifier.
> **Rationale:** The query endpoint is the primary user-facing surface. A well-defined schema enables client-side validation, typed SDKs, and schema evolution.
> **Acceptance Criteria:** The query endpoint accepts all documented fields with validation constraints (min/max lengths, valid ranges). Missing required fields return a 422 validation error. Optional fields default to documented values.

> **REQ-202** | Priority: MUST
> **Description:** The query request schema MUST support the following parameters at minimum:
>
> - `query` (required, string, bounded length)
> - `source_filter`, `heading_filter` (optional, string)
> - `alpha` (optional, float 0.0–1.0, default 0.5)
> - `search_limit` (optional, integer 1–100, default 10)
> - `rerank_top_k` (optional, integer 1–50, default 5)
> - `conversation_id` (optional, string)
> - `memory_enabled` (optional, boolean, default true)
> - `fast_path` (optional, boolean)
> - `overall_timeout_ms` (optional, integer)
> - `stage_budget_overrides` (optional, map of stage name to millisecond budget)
>
> **Rationale:** Comprehensive query controls enable clients to tune retrieval behavior per request without server-side configuration changes.
> **Acceptance Criteria:** Each parameter is validated against its documented constraints. Invalid values return descriptive validation errors. Unknown fields are rejected (strict schema).

> **REQ-203** | Priority: MUST
> **Description:** The query response schema MUST include: original query, processed query, query confidence, action taken, list of chunk results (text, score, metadata), optional generated answer, optional conversation identifier, latency metadata, and stage timing breakdown.
> **Rationale:** Comprehensive response fields enable clients to display rich results including provenance, confidence, and performance diagnostics.
> **Acceptance Criteria:** All documented fields are present in responses. Chunk results include text, score, and metadata. Stage timings include per-stage name, duration, and bucket.

> **REQ-204** | Priority: MUST
> **Description:** The system MUST expose a health endpoint that returns service readiness, including connectivity to the workflow engine and worker availability.
> **Rationale:** Load balancers, container orchestrators, and monitoring systems require a health endpoint to route traffic and trigger alerts.
> **Acceptance Criteria:** The health endpoint returns 200 with structured status when all dependencies are available. The response includes individual dependency status fields.

> **REQ-205** | Priority: MUST
> **Description:** The system MUST expose admin endpoints for API key lifecycle management (list, create, revoke) and tenant quota management (list, set, delete), gated by role-based access control.
> **Rationale:** Operator self-service for credential and quota management reduces operational overhead and enables multi-tenant governance.
> **Acceptance Criteria:** Admin endpoints require admin role. Non-admin requests receive 403. Key creation returns the key value once (not retrievable later). Quota changes take effect immediately.

> **REQ-206** | Priority: MUST
> **Description:** The system MUST expose a metrics endpoint that returns platform telemetry in a standard metrics exposition format.
> **Rationale:** Monitoring systems need a scrape endpoint to collect latency, throughput, error rate, and admission control metrics.
> **Acceptance Criteria:** The metrics endpoint returns all documented platform metrics in a parseable format. Metrics include labels for endpoint, method, and status.

> **REQ-207** | Priority: MUST
> **Description:** The system MUST expose conversation lifecycle endpoints: create conversation, list conversations for a principal, retrieve conversation history, and trigger conversation compaction.
> **Rationale:** Multi-turn memory requires explicit lifecycle management so clients can start, resume, inspect, and maintain conversations.
> **Acceptance Criteria:** All four operations are available as distinct endpoints. Conversation creation returns a stable identifier. History returns ordered turns. Compaction triggers rolling summary generation.

> **REQ-208** | Priority: SHOULD
> **Description:** The system SHOULD expose a root metadata endpoint that returns service name, documentation URL, health URL, and query endpoint URL.
> **Rationale:** A self-describing root endpoint enables API discovery and client bootstrapping.
> **Acceptance Criteria:** The root endpoint returns a JSON object with service metadata links.

---

## 5. Error Handling and Envelopes

> **REQ-301** | Priority: MUST
> **Description:** The system MUST return a structured error envelope for all non-2xx responses. The envelope MUST include: `ok` (boolean, always false), `error` object with `code` (string), `message` (string), and optional `details` (object), and `request_id` (string).
> **Rationale:** Inconsistent error formats force clients to implement per-endpoint error parsing. A universal envelope enables a single error handler.
> **Acceptance Criteria:** Every non-2xx response from any endpoint conforms to the error envelope schema. No endpoint returns raw exception text or stack traces.

> **REQ-302** | Priority: MUST
> **Description:** The system MUST normalize HTTP exceptions, request validation errors, and unhandled exceptions into the standard error envelope. Unhandled exceptions MUST NOT leak stack traces, internal paths, or system prompt content to the client.
> **Rationale:** Information leakage in error responses reveals internal architecture to attackers. Normalized errors are safe and debuggable via the correlated request ID.
> **Acceptance Criteria:** A deliberately triggered unhandled exception returns a 500 response with the error envelope and a generic message. The server-side log contains the full stack trace correlated by request ID.

> **REQ-303** | Priority: MUST
> **Description:** Request validation errors MUST return a 422 response with the error envelope. The `details` field MUST include structured validation error information (field name, constraint violated, provided value).
> **Rationale:** Clients need specific field-level error information to display meaningful validation messages.
> **Acceptance Criteria:** Submitting a query with `alpha=2.0` returns 422 with details indicating the alpha field violated the 0.0–1.0 range constraint.

> **REQ-304** | Priority: MUST
> **Description:** The console-facing endpoints MUST use a dedicated console envelope that wraps success data or error payloads with `ok`, `request_id`, `data` (on success), and `error` (on failure).
> **Rationale:** Console endpoints may return different payload shapes than the core API. A dedicated envelope provides consistency across all console actions.
> **Acceptance Criteria:** All console endpoints return the console envelope format. Success responses have `ok: true` with data. Error responses have `ok: false` with error details.

---

## 6. Streaming Protocol

> **REQ-401** | Priority: MUST
> **Description:** The system MUST support server-sent events (SSE) streaming for query endpoints. Streaming MUST deliver generation tokens incrementally as they are produced, enabling real-time answer display in clients.
> **Rationale:** Generation latency can be several seconds. Without streaming, users see no output until the full answer is complete, which degrades perceived responsiveness.
> **Acceptance Criteria:** A streaming query request receives an SSE event stream. Each token event contains the incremental text chunk. The final event contains the complete response metadata (chunks, timings, confidence).

> **REQ-402** | Priority: MUST
> **Description:** The streaming endpoint MUST emit structured events with distinct event types: retrieval stage completion, generation token, and final result. Each event MUST include a type discriminator.
> **Rationale:** Clients need to distinguish retrieval progress from generation tokens from the final result to render appropriate UI states.
> **Acceptance Criteria:** The stream begins with a retrieval completion event (chunks and timings), followed by token events, and ends with a final result event containing the complete response.

> **REQ-403** | Priority: MUST
> **Description:** Streaming errors MUST be delivered as structured SSE error events (not HTTP status codes, which are already sent as 200 for SSE). The error event MUST include the error code, message, and request ID.
> **Rationale:** Once SSE streaming begins, the HTTP status code is already 200. Errors during generation must be communicated within the event stream.
> **Acceptance Criteria:** A generation failure mid-stream produces an error event with structured error information. The client can detect the error event and display an appropriate message.

> **REQ-404** | Priority: SHOULD
> **Description:** The system SHOULD emit observability data (traces, metrics) for streaming requests asynchronously in the background to avoid adding latency to the stream.
> **Rationale:** Synchronous observability writes during streaming would delay token delivery. Background emission preserves streaming latency while maintaining full observability.
> **Acceptance Criteria:** Streaming request traces and metrics are available in the observability backend. Token delivery latency is not measurably affected by observability emission.

---

## 7. Workflow Dispatch and Worker Lifecycle

> **REQ-501** | Priority: MUST
> **Description:** The API server MUST dispatch query execution to backend workers through a durable workflow engine. The dispatch MUST include a unique workflow identifier, timeout policy, and the full query payload.
> **Rationale:** Durable dispatch provides automatic retry on transient failures, timeout enforcement, and execution tracking without building custom reliability infrastructure.
> **Acceptance Criteria:** A query dispatched through the workflow engine survives a transient worker restart (the workflow retries on a healthy worker). The workflow identifier is included in the query response.

> **REQ-502** | Priority: MUST
> **Description:** Workers MUST preload all ML models (embedding, reranking, and generation) at startup before accepting work from the task queue. The initialization MUST be logged with timing information.
> **Rationale:** Per-request model loading would violate latency SLOs. Startup preloading amortizes the cost across all requests. Timing logs enable capacity planning.
> **Acceptance Criteria:** A worker that has not completed model initialization does not accept tasks. Model initialization timing is logged. The first query after startup executes with model-in-memory latency (no cold start).

> **REQ-503** | Priority: MUST
> **Description:** Workers MUST support graceful shutdown that releases model resources and drains in-flight activities before process exit.
> **Rationale:** Ungraceful shutdown leaks GPU memory and may leave workflows in an incomplete state requiring manual intervention.
> **Acceptance Criteria:** A shutdown signal causes the worker to stop accepting new tasks, complete in-flight activities (within a timeout), release model resources, and exit cleanly.

> **REQ-504** | Priority: MUST
> **Description:** The workflow dispatch MUST support configurable execution timeout and task queue timeout policies. The API server MUST return a structured timeout error to the client when the workflow exceeds its timeout.
> **Rationale:** Without timeout policies, hung workers or slow models can block the client indefinitely. Configurable timeouts enable SLO enforcement.
> **Acceptance Criteria:** A query that exceeds the configured workflow timeout returns a 504 or structured timeout error. The timeout duration is configurable without code changes.

> **REQ-505** | Priority: SHOULD
> **Description:** The system SHOULD support activity-level result caching within the worker. Identical query payloads (same parameters, filters, and memory context) SHOULD return cached results without re-executing the retrieval pipeline.
> **Rationale:** Many RAG workloads involve repeated or near-identical queries. Activity-level caching eliminates redundant model inference for exact matches.
> **Acceptance Criteria:** A second identical query within the cache TTL returns the cached result with measurably lower latency. Cache keys include all query parameters and memory context.

---

## 8. Tooling Adapter Surface

> **REQ-601** | Priority: SHOULD
> **Description:** The system SHOULD expose the RAG query and health endpoints through a structured tooling protocol adapter (e.g., MCP) that enables AI assistants and IDE integrations to invoke RAG queries as tool calls.
> **Rationale:** AI assistants and developer tools benefit from structured tool invocation rather than raw HTTP calls. A tooling adapter broadens the integration surface.
> **Acceptance Criteria:** An AI assistant can invoke a query through the tooling adapter and receive a structured result. The adapter forwards to the standard API endpoints and returns the same schema.

> **REQ-602** | Priority: SHOULD
> **Description:** The tooling adapter MUST support at minimum: a query tool (accepting query text and optional filters) and a health tool (returning service status).
> **Rationale:** Query and health are the minimum viable tool surface for assistant integrations.
> **Acceptance Criteria:** Both tools are discoverable through the tooling protocol. Each tool has a documented schema describing its parameters and return type.

---

## 9. Container Deployment

> **REQ-701** | Priority: MUST
> **Description:** The API server MUST be deployable as a standalone container image that includes the HTTP server, route handlers, and dispatch logic but does NOT include ML model weights or heavy ML runtime dependencies.
> **Rationale:** A lean API container starts fast, scales horizontally, and does not waste memory on unused model artifacts.
> **Acceptance Criteria:** The API container image is significantly smaller than the worker image. The API container starts and passes health checks within 30 seconds.

> **REQ-702** | Priority: MUST
> **Description:** The container image MUST run as a non-root user and MUST include a health check command that validates API readiness.
> **Rationale:** Running as root increases the blast radius of container escape vulnerabilities. Built-in health checks enable orchestrator readiness gating.
> **Acceptance Criteria:** The container process runs as a non-root UID. The health check command is defined in the container specification. The orchestrator uses the health check to gate traffic routing.

> **REQ-703** | Priority: MUST
> **Description:** The deployment MUST support independent horizontal scaling of API server instances and worker instances. Worker scaling MUST be adjustable at runtime without restarting the API tier.
> **Rationale:** API and worker tiers have different resource profiles (API is CPU/network-bound, workers are GPU/memory-bound). Independent scaling enables cost-efficient resource allocation.
> **Acceptance Criteria:** Increasing worker replicas from 1 to 3 does not require API restart. The API load-balances across available workers through the workflow engine's task queue.

> **REQ-704** | Priority: SHOULD
> **Description:** The deployment SHOULD provide named profiles for common deployment configurations (infrastructure only, full application, application with monitoring, full stack including observability).
> **Rationale:** Different environments need different service subsets. Named profiles reduce deployment errors and simplify onboarding.
> **Acceptance Criteria:** Each named profile starts the documented set of services. Profiles can be combined. The default profile starts only infrastructure dependencies.

---

## 10. Non-Functional Requirements

> **REQ-901** | Priority: SHOULD
> **Description:** The API server SHOULD meet the following latency targets for request processing overhead (excluding worker execution time):
>
> | Component | Target |
> |-----------|--------|
> | Request parsing + validation | < 10ms p95 |
> | Auth + policy enforcement | < 50ms p95 |
> | Workflow dispatch | < 100ms p95 |
> | Response serialization | < 10ms p95 |
> | **Total API overhead** | **< 200ms p95** |
>
> **Rationale:** API overhead adds to end-to-end latency. Keeping it bounded ensures that latency budgets are consumed by retrieval and generation, not HTTP plumbing.
> **Acceptance Criteria:** API overhead is measurable via stage timing metadata. P95 overhead stays within target under standard load.

> **REQ-902** | Priority: MUST
> **Description:** The API server MUST start and serve health check requests within 30 seconds of container launch. The system MUST degrade gracefully when the workflow engine is temporarily unavailable:
>
> | Component Unavailable | Degraded Behavior |
> |----------------------|-------------------|
> | Workflow engine | Health endpoint reports degraded status; query endpoints return 503 with retry guidance |
> | Worker pool (zero workers) | Health endpoint reports no workers; query endpoints return 503 |
> | Metrics backend | Continue serving traffic; metrics are lost but functionality is preserved |
>
> **Rationale:** Transient infrastructure failures should not crash the API process. Graceful degradation with informative error responses enables client-side retry.
> **Acceptance Criteria:** The API server starts and serves `/health` within 30 seconds. Each degraded mode produces the documented behavior. The API process does not crash on any single dependency failure.

> **REQ-903** | Priority: MUST
> **Description:** All API server configuration (port, concurrency limits, queue timeouts, CORS origins, workflow engine address, deployment profiles) MUST be externalized to environment variables or configuration files. Changes MUST take effect on restart without code changes.
> **Rationale:** Hardcoded values prevent safe tuning and complicate environment-specific deployment.
> **Acceptance Criteria:** Every configurable parameter is documented with its environment variable name and default value. Changing a value requires only a configuration change and restart.

---

## 11. System-Level Acceptance Criteria

| Criterion | Threshold | Related Requirements |
|-----------|-----------|---------------------|
| Process separation verified | API process has no ML model imports | REQ-101 |
| Request correlation coverage | 100% of responses include request ID | REQ-102, REQ-301 |
| Error envelope compliance | 100% of non-2xx responses use the error envelope | REQ-301, REQ-302, REQ-303 |
| Streaming reliability | Token stream completes or delivers structured error event | REQ-401, REQ-402, REQ-403 |
| Worker lifecycle correctness | Graceful startup (preload) and shutdown (drain) verified | REQ-502, REQ-503 |
| Container security baseline | Non-root user, health check, lean image | REQ-701, REQ-702 |

---

## 12. Requirements Traceability Matrix

| REQ ID | Section | Priority | Component |
|--------|---------|----------|-----------|
| REQ-101 | 3 | MUST | API Architecture |
| REQ-102 | 3 | MUST | API Architecture |
| REQ-103 | 3 | MUST | API Architecture |
| REQ-104 | 3 | MUST | API Architecture |
| REQ-201 | 4 | MUST | Endpoint Contracts |
| REQ-202 | 4 | MUST | Endpoint Contracts |
| REQ-203 | 4 | MUST | Endpoint Contracts |
| REQ-204 | 4 | MUST | Endpoint Contracts |
| REQ-205 | 4 | MUST | Endpoint Contracts |
| REQ-206 | 4 | MUST | Endpoint Contracts |
| REQ-207 | 4 | MUST | Endpoint Contracts |
| REQ-208 | 4 | SHOULD | Endpoint Contracts |
| REQ-301 | 5 | MUST | Error Handling |
| REQ-302 | 5 | MUST | Error Handling |
| REQ-303 | 5 | MUST | Error Handling |
| REQ-304 | 5 | MUST | Error Handling |
| REQ-401 | 6 | MUST | Streaming |
| REQ-402 | 6 | MUST | Streaming |
| REQ-403 | 6 | MUST | Streaming |
| REQ-404 | 6 | SHOULD | Streaming |
| REQ-501 | 7 | MUST | Workflow Dispatch |
| REQ-502 | 7 | MUST | Workflow Dispatch |
| REQ-503 | 7 | MUST | Workflow Dispatch |
| REQ-504 | 7 | MUST | Workflow Dispatch |
| REQ-505 | 7 | SHOULD | Workflow Dispatch |
| REQ-601 | 8 | SHOULD | Tooling Adapter |
| REQ-602 | 8 | SHOULD | Tooling Adapter |
| REQ-701 | 9 | MUST | Container Deployment |
| REQ-702 | 9 | MUST | Container Deployment |
| REQ-703 | 9 | MUST | Container Deployment |
| REQ-704 | 9 | SHOULD | Container Deployment |
| REQ-901 | 10 | SHOULD | Non-Functional |
| REQ-902 | 10 | MUST | Non-Functional |
| REQ-903 | 10 | MUST | Non-Functional |

**Total Requirements: 34**

- MUST: 26
- SHOULD: 8
- MAY: 0
