# Server API and Service Layer — Implementation Guide

**AION Knowledge Management Platform**
Version: 1.0 | Status: Draft | Domain: Server API

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-13 | AI Assistant | Initial implementation guide reverse-engineered from implemented server layer |

> **Document intent:** This file is a phased implementation plan tied to `SERVER_API_SPEC.md`.
> For as-built behavior, refer to `server/README.md`.

This document provides a phased implementation plan and code appendix for the server API layer specified in `SERVER_API_SPEC.md`. Every task references the requirements it satisfies.

---

# Part A: Task-Oriented Overview

## Phase 1 — API Foundation and Process Separation

Establish the lightweight API server, request correlation, and bounded concurrency.

### Task 1.1: API Server Skeleton with Process Separation

**Description:** Build the HTTP server process that handles routing, middleware, and lifecycle management without importing ML model libraries.

**Requirements Covered:** REQ-101, REQ-104, REQ-903

**Dependencies:** None

**Complexity:** M

**Subtasks:**

1. Define the server application with CORS middleware and configurable allowed origins
2. Implement async lifecycle hooks for establishing and closing connections to the workflow engine
3. Ensure no ML model imports exist in the API process (embedding, reranking, generation libraries)
4. Externalize all server configuration (port, CORS origins, workflow engine address) to environment variables
5. Wire route modules using a router factory pattern for testable dependency injection

---

### Task 1.2: Request Correlation Middleware

**Description:** Implement middleware that assigns a unique request identifier to every inbound request and propagates it through the response.

**Requirements Covered:** REQ-102

**Dependencies:** Task 1.1

**Complexity:** S

**Subtasks:**

1. Generate a unique request ID for each request (e.g., `req-<hex>`)
2. If the client provides an `x-request-id` header, honor it
3. Store the request ID on the request state for downstream access
4. Include the request ID in the response `x-request-id` header

---

### Task 1.3: Bounded Concurrency and Overload Protection

**Description:** Implement API-tier admission control using a semaphore-based concurrency limiter with configurable queue timeout.

**Requirements Covered:** REQ-103, REQ-903

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**

1. Create a semaphore with configurable max in-flight permits
2. Implement an acquire function with configurable queue wait timeout
3. On timeout, return 503 with the standard error envelope and overload message
4. Implement a release function that decrements the in-flight counter
5. Emit metrics for in-flight count and overload rejection count
6. Externalize max permits and queue timeout to environment variables

---

## Phase 2 — Endpoint Contracts and Schemas

Define typed request/response models and wire the core endpoint surface.

### Task 2.1: Request and Response Schema Models

**Description:** Define typed schema models for all API endpoints covering query, health, admin, conversation, and console payloads.

**Requirements Covered:** REQ-201, REQ-202, REQ-203, REQ-207, REQ-208

**Dependencies:** None

**Complexity:** M

**Subtasks:**

1. Define `QueryRequest` with all documented fields, validation constraints, and strict mode
2. Define `QueryResponse` with chunks, confidence, timings, conversation ID, and budget metadata
3. Define `HealthResponse` with dependency status fields
4. Define admin schemas: `CreateApiKeyRequest/Response`, `QuotaUpdateRequest/Response`
5. Define conversation schemas: `ConversationCreateRequest`, `ConversationMetaResponse`, `ConversationHistoryResponse`, `ConversationCompactRequest`
6. Define console schemas: `ConsoleQueryRequest`, `ConsoleIngestionRequest`, `ConsoleCommandRequest`
7. Add a model validator for `stage_budget_overrides` to reject unknown stage names and out-of-range values

---

### Task 2.2: Core Route Handlers (Query, Health, Admin, System)

**Description:** Implement route handlers for the core API surface using the typed schemas and dependency injection.

**Requirements Covered:** REQ-201, REQ-204, REQ-205, REQ-206, REQ-208

**Dependencies:** Task 2.1, Task 1.1

**Complexity:** L

**Subtasks:**

1. Implement query route handler that validates input, enforces rate limits, acquires a request slot, dispatches to the workflow engine, and returns the structured response
2. Implement streaming query route handler (see Phase 3)
3. Implement health route handler that probes workflow engine connectivity and worker availability
4. Implement admin route handlers for API key lifecycle (list, create, revoke) and quota management (list, set, delete) with RBAC guards
5. Implement system route handler for root metadata and metrics export
6. Implement conversation route handlers for create, list, history, and compact operations
7. Wire all route handlers into the application using the router factory pattern

**Risks:** Route handler proliferation across files may cause import tangles; mitigate by keeping handlers thin and delegating to shared service functions.

**Testing Strategy:** Contract tests for each endpoint with valid/invalid payloads. Auth matrix tests for admin endpoints.

---

## Phase 3 — Error Handling and Streaming

Implement universal error envelopes and the SSE streaming protocol.

### Task 3.1: Universal Error Envelope Handlers

**Description:** Implement exception handlers that normalize all error types into the standard error envelope format.

**Requirements Covered:** REQ-301, REQ-302, REQ-303, REQ-304

**Dependencies:** Task 1.2

**Complexity:** M

**Subtasks:**

1. Define shared error envelope schema: `ApiErrorResponse` with `ok`, `error` (code, message, details), and `request_id`
2. Define console envelope schema: `ConsoleEnvelope` with `ok`, `request_id`, `data`, `error`
3. Implement HTTP exception handler that maps status codes to error codes
4. Implement request validation exception handler that extracts field-level errors into details
5. Implement catch-all exception handler that logs the full trace and returns a generic 500 envelope
6. Implement helper functions: `error_payload()`, `console_ok()`, `console_err()`

---

### Task 3.2: SSE Streaming Implementation

**Description:** Implement the streaming query endpoint that delivers generation tokens as Server-Sent Events with structured event types.

**Requirements Covered:** REQ-401, REQ-402, REQ-403, REQ-404

**Dependencies:** Task 2.2, Task 3.1

**Complexity:** L

**Subtasks:**

1. Implement the streaming endpoint that returns an SSE response
2. Submit the workflow, receive the retrieval result, and emit a retrieval completion event with chunks and stage timings
3. Stream generation tokens as individual SSE events with a type discriminator
4. Emit a final result event with the complete response metadata
5. Implement error event emission for mid-stream failures
6. Implement background observability emission for streaming requests to avoid blocking token delivery

**Risks:** SSE transport differences across HTTP clients and proxies may break streaming; mitigate with chunked transfer encoding and keep-alive events.

---

## Phase 4 — Workflow Dispatch and Worker Lifecycle

Implement the durable dispatch pattern and worker model preloading.

### Task 4.1: Workflow Dispatch Layer

**Description:** Implement the dispatch layer that submits query execution to the durable workflow engine with timeout policies and correlation IDs.

**Requirements Covered:** REQ-501, REQ-504

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**

1. Define the workflow submission function with configurable execution timeout and task queue timeout
2. Generate a unique workflow identifier per query for correlation
3. Include the full query payload, memory context, and budget controls in the workflow input
4. Handle workflow timeout by returning a structured timeout error to the client
5. Handle workflow failure by mapping the error to the standard error envelope

---

### Task 4.2: Worker Model Preloading and Lifecycle

**Description:** Implement the worker startup sequence that preloads ML models before accepting tasks, and the graceful shutdown sequence.

**Requirements Covered:** REQ-502, REQ-503

**Dependencies:** None

**Complexity:** M

**Subtasks:**

1. Implement `init_rag_chain()` that loads the retrieval pipeline singleton (embedding model, reranker, generator, vector DB connection) with timing logs
2. Implement `shutdown_rag_chain()` that releases model resources
3. Call init at worker startup before registering with the task queue
4. Call shutdown on worker process exit signal
5. Implement a health guard that rejects tasks if the chain is not initialized

---

### Task 4.3: Activity-Level Result Caching

**Description:** Implement result caching within the worker activity to bypass the retrieval pipeline for identical query payloads.

**Requirements Covered:** REQ-505

**Dependencies:** Task 4.2

**Complexity:** S

**Subtasks:**

1. Compute a deterministic cache key from all query parameters (query, filters, alpha, limits, memory context)
2. Check the cache before executing the retrieval pipeline
3. On cache miss, execute the pipeline and store the result with configurable TTL
4. Emit cache hit/miss metrics for observability

---

## Phase 5 — Tooling Adapter and Container Deployment

### Task 5.1: Tooling Protocol Adapter

**Description:** Implement an adapter that exposes RAG query and health endpoints through a structured tooling protocol for AI assistant integrations.

**Requirements Covered:** REQ-601, REQ-602

**Dependencies:** Task 2.2

**Complexity:** M

**Subtasks:**

1. Define tool descriptors for query (parameters: query text, source filter, heading filter, search limit) and health (no parameters)
2. Implement the adapter that receives tool invocations and forwards them to the standard API client
3. Map API responses to tool result format
4. Handle authentication passthrough from the tooling protocol to the API

---

### Task 5.2: Container Image and Deployment Profiles

**Description:** Build the container image specification for the API server and define deployment profiles for common configurations.

**Requirements Covered:** REQ-701, REQ-702, REQ-703, REQ-704

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**

1. Define the API container image with a minimal base (no ML runtime dependencies)
2. Install only HTTP server, workflow client, validation, metrics, and auth libraries
3. Create a non-root user and set as the container runtime user
4. Add a health check command that probes the `/health` endpoint
5. Define deployment profiles: `default` (infrastructure only), `app` (API), `workers` (model workers), `monitoring` (metrics + dashboards), `observability` (tracing)
6. Document worker scaling with replica count adjustment independent of API tier

---

## Task Dependency Graph

```
Phase 1 (API Foundation)
├── Task 1.1: API Server Skeleton ─────────────────────────────────┐
├── Task 1.2: Request Correlation Middleware ◄── Task 1.1 ─────────┤
└── Task 1.3: Bounded Concurrency ◄── Task 1.1 ───────────────────┤
                                                                    │
Phase 2 (Endpoint Contracts)                                       │
├── Task 2.1: Request/Response Schemas ────────────────────────────┤
└── Task 2.2: Core Route Handlers ◄── Task 2.1, Task 1.1 ─────────┼──┐ [CRITICAL]
                                                                    │  │
Phase 3 (Error Handling and Streaming)                             │  │
├── Task 3.1: Universal Error Envelopes ◄── Task 1.2 ──────────────┤  │
└── Task 3.2: SSE Streaming ◄── Task 2.2, Task 3.1 ────────────────┘  │ [CRITICAL]
                                                                        │
Phase 4 (Workflow and Workers)                                         │
├── Task 4.1: Workflow Dispatch Layer ◄── Task 1.1 ─────────────────────┤
├── Task 4.2: Worker Model Preloading ──────────────────────────────────┤
└── Task 4.3: Activity Result Caching ◄── Task 4.2 ────────────────────┤
                                                                        │
Phase 5 (Adapter and Deployment)                                       │
├── Task 5.1: Tooling Protocol Adapter ◄── Task 2.2 ───────────────────┤
└── Task 5.2: Container Image and Profiles ◄── Task 1.1 ───────────────┘

Critical path: Task 1.1 → Task 2.2 → Task 3.2 → Task 5.2
```

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|------|---------------------|
| 1.1 API Server Skeleton | REQ-101, REQ-104, REQ-903 |
| 1.2 Request Correlation Middleware | REQ-102 |
| 1.3 Bounded Concurrency | REQ-103, REQ-903 |
| 2.1 Request/Response Schemas | REQ-201, REQ-202, REQ-203, REQ-207, REQ-208 |
| 2.2 Core Route Handlers | REQ-201, REQ-204, REQ-205, REQ-206, REQ-208 |
| 3.1 Universal Error Envelopes | REQ-301, REQ-302, REQ-303, REQ-304 |
| 3.2 SSE Streaming | REQ-401, REQ-402, REQ-403, REQ-404 |
| 4.1 Workflow Dispatch Layer | REQ-501, REQ-504 |
| 4.2 Worker Model Preloading | REQ-502, REQ-503 |
| 4.3 Activity Result Caching | REQ-505 |
| 5.1 Tooling Protocol Adapter | REQ-601, REQ-602 |
| 5.2 Container Image and Profiles | REQ-701, REQ-702, REQ-703, REQ-704 |

---

# Part B: Code Appendix

## B.1: API Server Application and Lifecycle

This snippet shows the server application skeleton with middleware, lifecycle hooks, and router wiring.

**Tasks:** Task 1.1, Task 1.2, Task 1.3
**Requirements:** REQ-101, REQ-102, REQ-103, REQ-104

```python
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Callable

logger = logging.getLogger(__name__)

_workflow_client = None
_api_inflight_semaphore = None
_overload_queue_timeout_ms: int = 250

API_PORT = int(os.environ.get("RAG_API_PORT", "8000"))
MAX_INFLIGHT = int(os.environ.get("RAG_API_MAX_INFLIGHT_REQUESTS", "64"))
QUEUE_TIMEOUT_MS = int(os.environ.get("RAG_API_OVERLOAD_QUEUE_TIMEOUT_MS", "250"))


@asynccontextmanager
async def lifespan(app):
    global _workflow_client
    _workflow_client = await connect_to_workflow_engine()
    logger.info("API server ready — queries route through workers")
    try:
        yield
    finally:
        if _workflow_client is not None:
            await _workflow_client.close()
        logger.info("API server shutting down")


def create_app():
    """Build the HTTP application with middleware and routes."""
    app = create_http_app(title="RAG Query API", lifespan=lifespan)
    app.add_cors_middleware(allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def add_request_id(request, call_next):
        request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:12]}"
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    app.include_router(create_query_router(get_workflow_client=lambda: _workflow_client))
    app.include_router(create_admin_router())
    app.include_router(create_system_router())
    app.include_router(create_console_router())
    return app
```

**Key design decisions:**
- Lifecycle hooks manage the workflow engine connection; no ML imports in this process.
- Router factory functions accept dependencies as arguments for testability.
- Request ID middleware runs on every request before any route handler.

---

## B.2: Error Envelope and Exception Handlers

This snippet shows the universal error envelope and exception normalization handlers.

**Tasks:** Task 3.1
**Requirements:** REQ-301, REQ-302, REQ-303, REQ-304

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ApiErrorDetail:
    code: str
    message: str
    details: Optional[dict] = None


@dataclass
class ApiErrorResponse:
    ok: bool = False
    error: ApiErrorDetail = None
    request_id: Optional[str] = None


@dataclass
class ConsoleEnvelope:
    ok: bool
    request_id: Optional[str] = None
    data: Optional[dict] = None
    error: Optional[ApiErrorDetail] = None


def error_payload(request, *, code: str, message: str, details: dict = None) -> dict:
    return {
        "ok": False,
        "error": {"code": code, "message": message, "details": details},
        "request_id": getattr(request.state, "request_id", None),
    }


def http_exception_handler(request, exc):
    """Normalize HTTP exceptions to the error envelope."""
    detail = exc.detail
    message = detail if isinstance(detail, str) else str(detail.get("message", "Request failed"))
    return json_response(
        status_code=exc.status_code,
        content=error_payload(request, code=f"HTTP_{exc.status_code}", message=message),
    )


def validation_exception_handler(request, exc):
    """Normalize validation errors with field-level details."""
    return json_response(
        status_code=422,
        content=error_payload(
            request,
            code="REQUEST_VALIDATION_ERROR",
            message="Request validation failed",
            details={"errors": exc.errors()},
        ),
    )


def unhandled_exception_handler(request, exc):
    """Catch-all: log internally, return generic envelope."""
    logger.exception("Unhandled exception: %s", exc)
    return json_response(
        status_code=500,
        content=error_payload(request, code="INTERNAL_SERVER_ERROR", message="Internal server error"),
    )
```

**Key design decisions:**
- Three exception handlers cover all error paths: HTTP, validation, and catch-all.
- Error details never leak stack traces or internal paths.
- Console endpoints use a separate envelope with `data` field for success payloads.

---

## B.3: Bounded Concurrency Controller

This snippet shows the semaphore-based admission control for API overload protection.

**Tasks:** Task 1.3
**Requirements:** REQ-103

```python
import asyncio
from typing import Optional


class ConcurrencyController:
    """Bounded API concurrency with configurable queue wait."""

    def __init__(self, max_inflight: int, queue_timeout_ms: int):
        self._semaphore: Optional[asyncio.Semaphore] = (
            asyncio.Semaphore(max_inflight) if max_inflight > 0 else None
        )
        self._timeout_s = max(1, queue_timeout_ms) / 1000.0

    async def acquire(self, endpoint: str) -> bool:
        if self._semaphore is None:
            return False
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self._timeout_s)
        except asyncio.TimeoutError:
            raise OverloadError(f"Server overloaded at endpoint {endpoint}")
        return True

    def release(self, acquired: bool) -> None:
        if acquired and self._semaphore is not None:
            self._semaphore.release()
```

**Key design decisions:**
- Semaphore-based approach bounds in-flight requests without external dependencies.
- Queue timeout prevents slow-drip starvation under sustained overload.
- Disabled when max_inflight is 0, enabling unbounded mode for development.

---

## B.4: Worker Activity with Result Caching

This snippet shows the worker activity that executes RAG queries with activity-level result caching.

**Tasks:** Task 4.2, Task 4.3
**Requirements:** REQ-502, REQ-503, REQ-505

```python
import hashlib
import json
import logging
import time
from dataclasses import asdict
from typing import Optional

logger = logging.getLogger(__name__)

_rag_chain = None
_cache = None


def init_rag_chain() -> None:
    """Load retrieval pipeline singleton at worker startup."""
    global _rag_chain
    if _rag_chain is not None:
        return

    start = time.time()
    _rag_chain = build_rag_chain()
    logger.info("RAG chain ready in %.1fs", time.time() - start)


def shutdown_rag_chain() -> None:
    """Release pipeline resources for graceful shutdown."""
    global _rag_chain
    if _rag_chain is not None:
        _rag_chain.close()
    _rag_chain = None


def execute_rag_query(request: dict) -> dict:
    """Worker activity: run a query against preloaded models with caching."""
    if _rag_chain is None:
        raise RuntimeError("RAG chain not initialized")

    cache_key = _compute_cache_key(request)
    cached = _cache.get(cache_key) if _cache else None
    if isinstance(cached, dict):
        return cached

    start = time.perf_counter()
    response = _rag_chain.run(
        query=request["query"],
        alpha=request.get("alpha", 0.5),
        search_limit=request.get("search_limit", 10),
        rerank_top_k=request.get("rerank_top_k", 5),
        source_filter=request.get("source_filter"),
        heading_filter=request.get("heading_filter"),
        memory_context=request.get("memory_context"),
        memory_recent_turns=request.get("memory_recent_turns", []),
    )
    result = asdict(response)
    result["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)

    if _cache:
        _cache.set(cache_key, result)
    return result


def _compute_cache_key(request: dict) -> str:
    payload = json.dumps(request, sort_keys=True)
    return "rag:query:" + hashlib.sha256(payload.encode()).hexdigest()
```

**Key design decisions:**
- Singleton initialization at worker startup eliminates per-request model loading cost.
- Cache key includes all query parameters and memory context for correctness.
- Shutdown releases resources explicitly to avoid GPU memory leaks on container cycling.

---

## B.5: Container Specification

This snippet shows the container image definition for the lean API server.

**Tasks:** Task 5.2
**Requirements:** REQ-701, REQ-702

```dockerfile
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# API process: HTTP server, workflow client, validation, metrics, auth only.
# No ML model libraries (torch, transformers, sentence-transformers).
RUN pip install --upgrade pip && pip install \
    fastapi \
    "uvicorn[standard]" \
    "pydantic>=2.0" \
    prometheus-client \
    "pyjwt[crypto]" \
    redis

RUN groupadd --system app && useradd --system --gid app --create-home app

COPY --chown=app:app config /app/config
COPY --chown=app:app src /app/src
COPY --chown=app:app server /app/server

USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health >/dev/null || exit 1

CMD ["uvicorn", "server.api:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Key design decisions:**
- No ML runtime dependencies keeps the image lean and startup fast.
- Non-root user limits container escape blast radius.
- Built-in health check enables orchestrator readiness gating.
