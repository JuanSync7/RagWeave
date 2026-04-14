# Platform Services Specification Summary

<!-- @summary
Concise digest of the Platform Services Specification (v1.3). Covers identity/auth,
tenancy, admission control, and data/caching requirements for the RAG platform
services layer. Companion to PLATFORM_SERVICES_SPEC.md.
@end-summary -->

---

## 1) Generic System Overview

### Purpose

The platform services layer establishes the foundational control plane that every inbound request must traverse before reaching domain-specific execution logic. Without this layer, a multi-tenant system cannot enforce cost and capacity governance, prevent abuse, or maintain isolation between customers. It exists because orchestration and retrieval capabilities alone are insufficient for production reliability — the system must also answer "who is asking, are they allowed, and is the system ready to serve them."

### How It Works

Every inbound request enters through an identity gate, where credentials are validated and the requesting principal is resolved to a tenant context. The gate makes an allow-or-deny decision based on credential validity, tenant mapping, and role permissions. Requests missing valid credentials or lacking a resolvable tenant are terminated immediately with a structured error response.

Admitted requests then pass through an admission control stage, which evaluates current system load signals — queue depth, worker saturation, and per-tenant quota consumption — against configured policy windows. Requests that exceed rate limits or push against quota ceilings are explicitly rejected with retry guidance rather than silently queued or timed out. When the system supports service-class differentiation, interactive and batch requests are evaluated against independent admission budgets so that bulk workloads cannot crowd out low-latency user traffic.

Requests that clear admission control are dispatched into the workflow execution layer with control tags attached. Those tags carry tenant, role, and policy attribution that downstream activities use to enforce data access boundaries and cache key scoping.

At the execution and data access stage, retrieval activities interact with a shared vector store (in production deployments) and a response cache. Cached results are keyed by tenant, project, and request fingerprint so that repeated queries receive low-latency responses from cache rather than full retrieval cycles. When the cache is unavailable, the system bypasses it transparently and completes the request through the direct execution path.

### Tunable Knobs

Operators can configure rate-limit thresholds (burst and sustained) and quota windows (minute, hour, and day granularity) per tenant and per principal. Admission control has configurable queue-depth thresholds and saturation signals that determine when shedding begins. Service-class assignment (interactive vs. batch) and the independent admission policies for each class are externally configurable. Cache time-to-live values are configurable per scope. All policy rules and timeout budgets are externalized so they can be updated on restart or controlled reload without code changes.

### Design Rationale

The layer is shaped by three constraints. First, tenant isolation must be enforced before expensive work is scheduled — late enforcement wastes capacity and makes blast-radius containment harder. Second, the system must shed load explicitly and predictably: silent timeouts under saturation are operationally worse than explicit rejections with retry semantics. Third, all behavioral thresholds must live in versioned external configuration rather than code constants so that tuning and incident response do not require deployments.

### Boundary Semantics

Entry point: an inbound API request arriving at the service boundary with authentication credentials and request metadata. Exit point: either a structured rejection response (with appropriate HTTP status and retry guidance) or an accepted request forwarded to workflow dispatch with principal, tenant, role, and policy tags attached. The layer does not retain per-request state beyond audit records and cache entries. Responsibility ends when the request enters the workflow execution engine.

---

## 2) Header

| Field | Value |
|---|---|
| **Companion spec** | `PLATFORM_SERVICES_SPEC.md` |
| **Spec version** | 1.3 |
| **Domain** | Platform Services — identity/auth, tenancy, admission control, data services, caching |
| **Status** | Implemented Baseline + OIDC + Admin |
| **See also** | `SERVER_API_SPEC.md`, `docs/operations/OPERATIONS_PLATFORM_SPEC.md`, `docs/retrieval/RETRIEVAL_QUERY_SPEC.md` |

---

## 3) Scope and Boundaries

**Entry point:** Inbound API request reaches the RAG service boundary.

**Exit point:** Request is accepted, rejected, or routed with auditable policy enforcement; data access proceeds through cache or persistence layers.

**In scope:**
- Identity and authentication (API keys and bearer tokens)
- Tenant resolution and isolation
- Role-based access control for platform and query scopes
- Rate limits, per-tenant and per-principal quotas, and quota windows
- Admission control based on queue depth and worker saturation
- Service-class differentiation (interactive vs. batch)
- Timeout and cancellation propagation
- Shared vector store deployment mode for production
- Response caching with tenant/project partitioning
- Data retention and backup policy definitions for operational stores

**Out of scope:**
- Observability, SLOs, and alerting (see `docs/operations/OPERATIONS_PLATFORM_SPEC.md`)
- Operations, DR, CI/CD, and delivery (see `docs/operations/OPERATIONS_PLATFORM_SPEC.md`)
- Prompt engineering and model quality tuning for answer generation
- Front-end product UX and presentation-layer behavior
- Embedding ingestion pipeline internals

---

## 4) Architecture / Pipeline Overview

```
Inbound Client Request
        |
        v
+-----------------------------+
| [1] IDENTITY GATE           |  AuthN, tenant resolution, RBAC
+-----------------------------+
        |
        v
+-----------------------------+
| [2] ADMISSION CONTROL       |  Rate limits, quotas, queue budget
+-----------------------------+       |-- reject (429/503)
        |                             |-- queue or pass
        v
+-----------------------------+
| [3] WORKFLOW DISPATCH       |  Routing with policy tags
+-----------------------------+
        |
        v
+-----------------------------+
| [4] EXECUTION + DATA ACCESS |  Retrieval + cache (bypass on failure)
+-----------------------------+
        |
        v
     Response
```

Stages 1–2 are pure control-plane; stage 4 is data-plane. Optional: project-level isolation (within a tenant) and service-class routing at stage 2.

---

## 5) Requirement Framework

- **ID convention:** `REQ-xxx` where the leading digit(s) identify the domain section.
- **Priority keywords:** MUST (absolute), SHOULD (recommended with justification if omitted), MAY (optional).
- **Structure per requirement:** description, rationale, acceptance criteria.
- **Traceability matrix:** included in the spec; 16 requirements total (12 MUST, 4 SHOULD, 0 MAY).

| Section | ID Range | Domain |
|---|---|---|
| 3 | REQ-1xx | Identity, Auth, and Tenancy |
| 4 | REQ-2xx | Rate Limits, Quotas, and Admission Control |
| 5 | REQ-3xx | Data Services and Caching |
| 6 | REQ-9xx | Non-Functional Requirements |

---

## 6) Functional Requirement Domains

**Identity, Auth, and Tenancy (REQ-100 to REQ-199)**
Covers mandatory authentication for all non-health endpoints, tenant resolution before dispatch, RBAC enforcement for platform and query scopes, and optional project-level isolation within a tenant.

**Rate Limits, Quotas, and Admission Control (REQ-200 to REQ-299)**
Covers per-tenant and per-principal rate limiting at the API boundary, multi-window quota enforcement (minute/hour/day), admission control based on saturation signals, deterministic timeout and cancellation semantics, and optional service-class differentiation with independent admission budgets.

**Data Services and Caching (REQ-300 to REQ-399)**
Covers production shared vector store deployment mode, response caching with configurable TTL, tenant/project-partitioned cache namespacing, and data retention and backup policy definitions for all operational stores.

---

## 7) Non-Functional and Security Themes

- **Control-plane latency:** The spec defines target p95 latency budgets for each stage so that governance overhead does not consume request time budgets.
- **Graceful degradation:** When the cache layer is unavailable, the system bypasses it and continues on the direct execution path; unhandled exceptions from single optional component failures are prohibited.
- **Configuration externalization:** All limits, policy rules, timeout budgets, and routing thresholds must be externalized to versioned configuration and must apply on restart or controlled reload.

---

## 8) Design Principles

| Principle | Description |
|---|---|
| **Isolation First** | Tenant and principal boundaries are enforced before expensive work is scheduled |
| **Fail Safe Under Load** | System sheds load explicitly and predictably rather than timing out silently |
| **Policy Over Hardcode** | Limits, thresholds, and access rules are externalized and versioned |

---

## 9) Key Decisions

- **API-boundary enforcement:** Rate limits and admission control are applied at the API edge before workflow dispatch — not inside the workflow or at the retrieval layer — so that capacity is not wasted on work that will be rejected.
- **Explicit rejection over silent queuing:** Requests that exceed limits receive structured error responses with retry guidance rather than being silently accumulated in an unbounded queue.
- **Cache bypass as a degradation path:** The cache is treated as an optional accelerator; its unavailability triggers bypass rather than service interruption.
- **Two-phase implementation:** The spec structures delivery in two phases: control-plane access and protection first, then stateful data services and caching. This sequencing ensures security and load protection land before shared infrastructure complexity is introduced.

---

## 10) Acceptance and Evaluation

The spec defines system-level acceptance criteria across three dimensions:

- **Unauthorized access prevention** — coverage of protected endpoints.
- **Load protection effectiveness** — bounded queue behavior under a stress multiplier profile.
- **Data service reliability** — cache bypass under cache-layer failure preserves service availability.

Each functional requirement includes its own acceptance criteria in the companion spec. The spec does not define an automated evaluation or feedback framework beyond these conformance tests.

---

## 11) External Dependencies

| Dependency | Type | Role |
|---|---|---|
| Workflow orchestrator | Required | Task queue backbone; queue governance depends on its availability |
| Shared vector store | Required (production mode) | Multi-replica production data access |
| Cache store | Optional (accelerator) | Response and artifact caching; bypass mode on failure |
| OIDC provider | Required (when bearer tokens used) | Issuer/audience/JWKS validation |

**Constraint:** The platform is assumed to run in containerized environments; host-only hardening assumptions are excluded.

---

## 12) Companion Documents

This summary is a digest of `PLATFORM_SERVICES_SPEC.md` (v1.3). It is not a replacement for the spec — individual requirement text, acceptance criteria thresholds, and the full traceability matrix live in the companion spec.

**Related specifications:**
- `SERVER_API_SPEC.md` — API server endpoint contracts
- `docs/operations/OPERATIONS_PLATFORM_SPEC.md` — Observability, SLOs, alerting, DR, CI/CD, and delivery
- `docs/retrieval/RETRIEVAL_QUERY_SPEC.md` — Retrieval pipeline behavior

The spec was split from `BACKEND_PLATFORM_SPEC.md` at v1.3; observability and operations requirements were moved to the operations spec at that point.

---

## 13) Sync Status

| Field | Value |
|---|---|
| **Spec version summarized** | 1.3 |
| **Summary written** | 2026-04-10 |
| **Aligned to** | `PLATFORM_SERVICES_SPEC.md` v1.3 |
| **Next update trigger** | Spec version bump or scope change |
