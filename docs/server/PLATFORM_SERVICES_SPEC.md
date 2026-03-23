# Platform Services Specification

**AION Knowledge Management Platform**
Version: 1.3 | Status: Implemented Baseline+OIDC+Admin | Domain: Platform Services

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-11 | AI Assistant | Initial draft covering auth, quotas, reliability, security, and operations gaps |
| 1.1 | 2026-03-11 | AI Assistant | Implemented baseline: auth+tenancy context, RBAC guard, API rate limit, Redis/in-memory cache, Prometheus metrics endpoint |
| 1.2 | 2026-03-11 | AI Assistant | Added OIDC provider validation (issuer/audience/JWKS), persistent API-key lifecycle endpoints, and tenant quota admin APIs |
| 1.3 | 2026-03-17 | AI Assistant | Split from BACKEND_PLATFORM_SPEC.md. Observability/SLO/alerting and operations/DR/delivery requirements moved to `OPERATIONS_PLATFORM_SPEC.md` in `docs/operations/`. This spec now covers platform services only: identity, admission control, and data services. |

> **Document intent:** This is a normative requirements/specification document for the platform services layer (auth, tenancy, rate limits, caching).
> For observability, alerting, DR, CI/CD, and deployment operations, see `docs/operations/OPERATIONS_PLATFORM_SPEC.md`.
> For API server endpoint contracts, see `SERVER_API_SPEC.md`.
> For retrieval pipeline behavior, see `docs/retrieval/RETRIEVAL_QUERY_SPEC.md`.

---

## 1. Scope & Definitions

### 1.1 Problem Statement

The current platform has a strong orchestration and observability foundation (Temporal, Langfuse, container log visibility), but it still lacks key production controls needed for multi-tenant reliability and security. Without these controls, one noisy client can saturate worker capacity, and incidents are harder to contain.

### 1.2 Scope

This specification defines requirements for the **platform services layer** of the RAG system. The boundary is:

- **Entry point:** Inbound API request reaches the RAG service boundary.
- **Exit point:** Request is accepted/rejected/routed with auditable policy enforcement and data access through cache or persistence layers.

In scope: identity/auth, tenancy, rate control, admission control, data services, and caching.

### 1.2.1 Current Implementation Status (2026-03-11)

- OIDC bearer token validation is implemented with issuer, audience, and JWKS signature verification.
- Admin lifecycle endpoints are implemented for API keys and tenant quotas.
- API key and quota policies are persisted in runtime JSON stores under `.runtime/security/`.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **Tenant** | A logical customer/project boundary with isolated quotas, policies, and data visibility |
| **RBAC** | Role-based access control determining which principals can perform which actions |
| **Admission Control** | Policy gate that accepts, delays, or rejects requests based on system load and limits |
| **Backpressure** | Controlled reduction of accepted request volume when downstream capacity is constrained |

### 1.4 Requirement Priority Levels

This document uses RFC 2119 language:

- **MUST** — Absolute requirement. The system is non-conformant without it.
- **SHOULD** — Recommended. May be omitted only with documented justification.
- **MAY** — Optional. Included at the implementor's discretion.

### 1.5 Requirement Format

Each requirement follows this structure:

> **REQ-xxx** | Priority: MUST/SHOULD/MAY
> **Description:** What the system shall do.
> **Rationale:** Why this requirement exists.
> **Acceptance Criteria:** How to verify conformance.

Requirements are grouped by section with the following ID ranges:

| Section | ID Range | Component |
|---------|----------|-----------|
| 3 | REQ-1xx | Identity, Auth, and Tenancy |
| 4 | REQ-2xx | Rate Limits, Quotas, and Admission Control |
| 5 | REQ-3xx | Data Services and Caching |
| 6 | REQ-9xx | Non-Functional Requirements |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | Temporal remains the workflow orchestrator and task queue backbone | Queue governance requirements need redesign |
| A-2 | API traffic includes machine clients and interactive clients | Single policy model may not fit all request patterns |
| A-3 | Platform runs in containerized environments | Host-only assumptions cannot be used for production hardening |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **Isolation First** | Tenant and principal boundaries are enforced before expensive work is scheduled |
| **Fail Safe Under Load** | System sheds load explicitly and predictably rather than timing out silently |
| **Policy Over Hardcode** | Limits, thresholds, and access rules are externalized and versioned |

### 1.8 Out of Scope

The following are explicitly **not covered** by this specification:

- Observability, SLOs, and alerting (see `docs/operations/OPERATIONS_PLATFORM_SPEC.md`)
- Operations, DR, CI/CD, and delivery (see `docs/operations/OPERATIONS_PLATFORM_SPEC.md`)
- Prompt engineering and model quality tuning for answer generation
- Front-end product UX and presentation-layer behavior
- Embedding ingestion pipeline internals

---

## 2. System Overview

### 2.1 Architecture Diagram

```
Inbound Client Request
    |
    v
+--------------------------------------+
| [1] IDENTITY GATE                    |
|     AuthN, AuthZ, tenant resolution  |
+--------------------------------------+
               |
               v
+--------------------------------------+
| [2] ADMISSION CONTROL                |
|     Rate limit, quotas, queue budget |
+--------------------------------------+
               |
               v
+--------------------------------------+
| [3] WORKFLOW DISPATCH                |
|     Temporal routing + policy tags   |
+--------------------------------------+
               |
               v
+--------------------------------------+
| [4] EXECUTION + DATA ACCESS          |
|     Retrieval services + cache       |
+--------------------------------------+
```

### 2.2 Data Flow Summary

| Stage | Input | Output |
|-------|-------|--------|
| Identity Gate | Auth credentials + request metadata | Principal, tenant, role claims, allow/deny decision |
| Admission Control | Principal/tenant policy + current load signals | Accept, reject (429/503), or queue routing decision |
| Workflow Dispatch | Accepted request + control tags | Temporal workflow execution and correlation IDs |
| Execution + Data Access | Workflow activity calls | Retrieved/generated payload with cache and policy attribution |

---

## 3. Identity, Auth, and Tenancy

> **REQ-101** | Priority: MUST
> **Description:** The system MUST require API authentication for all non-health endpoints and MUST support either API keys or JWT bearer tokens.
> **Rationale:** Unauthenticated access allows abuse and prevents principal attribution for policy enforcement.
> **Acceptance Criteria:** Requests without valid credentials to protected endpoints return 401. Valid credentials return principal identity context to downstream handlers.

> **REQ-102** | Priority: MUST
> **Description:** The system MUST resolve every authenticated request to a tenant identifier before request dispatch.
> **Rationale:** Tenant resolution is required to apply isolated limits, policy controls, and data access boundaries.
> **Acceptance Criteria:** Request context includes a non-empty tenant ID; missing tenant mapping returns 403 with a user-safe message.

> **REQ-103** | Priority: MUST
> **Description:** The system MUST implement RBAC for platform operations and query execution scopes.
> **Rationale:** Different principals require different permissions (read/query/admin), and unrestricted privileges increase blast radius.
> **Acceptance Criteria:** Role-policy tests prove denied operations for insufficient roles and allowed operations for valid roles.

> **REQ-104** | Priority: SHOULD
> **Description:** The system SHOULD support project-level isolation within a tenant, including project-scoped quotas and metadata filters.
> **Rationale:** Multi-project tenants require internal isolation to avoid noisy-neighbor issues inside one tenant.
> **Acceptance Criteria:** Two projects under one tenant can have distinct limits and cannot access each other's restricted scope.

---

## 4. Rate Limits, Quotas, and Admission Control

> **REQ-201** | Priority: MUST
> **Description:** The system MUST enforce per-tenant and per-principal rate limits at the API boundary.
> **Rationale:** API-side enforcement prevents expensive downstream work from being scheduled when a client exceeds agreed usage.
> **Acceptance Criteria:** Burst and sustained threshold tests produce deterministic 429 responses and structured retry hints.

> **REQ-202** | Priority: MUST
> **Description:** The system MUST enforce token, request, and concurrency quotas over configurable windows (minute/hour/day).
> **Rationale:** Quotas provide predictable cost and capacity governance across tenants.
> **Acceptance Criteria:** Requests exceeding configured windows are denied until reset; quota counters are auditable.

> **REQ-203** | Priority: MUST
> **Description:** The system MUST implement admission control based on queue depth and worker saturation signals.
> **Rationale:** Backpressure avoids cascading latency collapse when workers are saturated.
> **Acceptance Criteria:** Under induced saturation, requests are rejected or delayed according to policy before p95 latency enters runaway growth.

> **REQ-204** | Priority: MUST
> **Description:** The system MUST expose explicit timeout and cancellation behavior at API level and propagate cancellation to workflow execution where supported.
> **Rationale:** Clients need deterministic behavior under long-running operations; orphaned executions waste capacity.
> **Acceptance Criteria:** Client timeout/cancel integration tests verify terminated or detached execution semantics as configured.

> **REQ-205** | Priority: SHOULD
> **Description:** The system SHOULD support differentiated service classes (interactive vs batch) with independent admission policies.
> **Rationale:** Mixed workloads otherwise contend for the same budget and degrade interactive user experience.
> **Acceptance Criteria:** Interactive class maintains target latency under simultaneous batch load.

---

## 5. Data Services and Caching

> **REQ-301** | Priority: MUST
> **Description:** The system MUST support a production-grade shared vector database deployment mode in addition to embedded/local mode.
> **Rationale:** Embedded local stores are suitable for development but do not satisfy multi-replica production consistency needs.
> **Acceptance Criteria:** Deployment profiles include shared database mode with documented connection, health, and failover behavior.

> **REQ-302** | Priority: MUST
> **Description:** The system MUST implement a Redis-backed cache for repeated query responses and intermediate retrieval artifacts with configurable TTL.
> **Rationale:** Cache hits reduce worker load and improve latency for repeated access patterns.
> **Acceptance Criteria:** Repeat-query benchmark shows measurable p50 and p95 latency improvement with correctness-preserving cache keys.

> **REQ-303** | Priority: SHOULD
> **Description:** The system SHOULD support cache partitioning by tenant and project.
> **Rationale:** Shared cache without partitioning can cause cross-tenant key collision risk and noisy-neighbor eviction.
> **Acceptance Criteria:** Cache key namespace includes tenant and project dimensions, and eviction metrics are attributable by scope.

> **REQ-304** | Priority: MUST
> **Description:** The system MUST define data retention and backup policies for operational stores (workflow DB, observability DBs, object store, vector store).
> **Rationale:** Recovery posture is incomplete without explicit retention and backup verification.
> **Acceptance Criteria:** Backup jobs run on schedule, restore drills validate target RPO/RTO objectives, and audit logs record outcomes.

---

## 6. Non-Functional Requirements

> **REQ-901** | Priority: SHOULD
> **Description:** The system SHOULD meet the following platform SLOs under declared standard load:
>
> | Component/Stage | Target |
> |-----------------|--------|
> | Auth + policy enforcement | < 50ms p95 |
> | Admission control decision | < 25ms p95 |
> | Queue wait for interactive class | < 500ms p95 |
> | **End-to-end interactive request** | **< 3s p95 (excluding generation stream duration)** |
>
> **Rationale:** Predictable control-plane overhead is required so latency budgets are consumed by model work, not governance plumbing.
> **Acceptance Criteria:** SLO reports show compliance for 30-day windows or documented error-budget burn.

> **REQ-902** | Priority: MUST
> **Description:** The system MUST degrade gracefully when optional platform components are unavailable:
>
> | Component Unavailable | Degraded Behavior |
> |----------------------|-------------------|
> | Cache layer | Bypass cache and continue with direct execution path |
>
> The system MUST NOT crash or return unhandled exceptions for single optional component failures.
> **Rationale:** Control plane reliability must survive cache disruptions.
> **Acceptance Criteria:** Failure-injection tests validate each degraded mode and recovery transition.

> **REQ-903** | Priority: MUST
> **Description:** All platform limits, policy rules, timeout budgets, and routing thresholds MUST be externalized to versioned configuration.
> **Rationale:** Hardcoded limits prevent safe iterative tuning and slow incident response.
> **Acceptance Criteria:** Config changes apply on restart or controlled reload, are auditable, and have documented defaults.

---

## 7. System-Level Acceptance Criteria

| Criterion | Threshold | Related Requirements |
|-----------|-----------|---------------------|
| Unauthorized access prevention | 100% protected endpoint coverage | REQ-101, REQ-103 |
| Load protection effectiveness | No unbounded queue growth under 2x stress profile | REQ-201, REQ-202, REQ-203 |
| Data service reliability | Cache bypass under Redis failure preserves service | REQ-302, REQ-902 |

---

## 8. Requirements Traceability Matrix

| REQ ID | Section | Priority | Component/Stage |
|--------|---------|----------|----------------|
| REQ-101 | 3 | MUST | Identity, Auth, and Tenancy |
| REQ-102 | 3 | MUST | Identity, Auth, and Tenancy |
| REQ-103 | 3 | MUST | Identity, Auth, and Tenancy |
| REQ-104 | 3 | SHOULD | Identity, Auth, and Tenancy |
| REQ-201 | 4 | MUST | Rate Limits, Quotas, and Admission Control |
| REQ-202 | 4 | MUST | Rate Limits, Quotas, and Admission Control |
| REQ-203 | 4 | MUST | Rate Limits, Quotas, and Admission Control |
| REQ-204 | 4 | MUST | Rate Limits, Quotas, and Admission Control |
| REQ-205 | 4 | SHOULD | Rate Limits, Quotas, and Admission Control |
| REQ-301 | 5 | MUST | Data Services and Caching |
| REQ-302 | 5 | MUST | Data Services and Caching |
| REQ-303 | 5 | SHOULD | Data Services and Caching |
| REQ-304 | 5 | MUST | Data Services and Caching |
| REQ-901 | 6 | SHOULD | Non-Functional |
| REQ-902 | 6 | MUST | Non-Functional |
| REQ-903 | 6 | MUST | Non-Functional |

**Total Requirements: 16**
- MUST: 12
- SHOULD: 4
- MAY: 0

---

## Appendix A. Implementation Phasing

### Phase 1 — Access and Protection Baseline (2-3 weeks)

**Objective:** Establish secure request boundaries and overload protection.

| Scope | Requirements |
|-------|-------------|
| Auth + tenancy + RBAC | REQ-101, REQ-102, REQ-103 |
| Rate limits + admission control | REQ-201, REQ-202, REQ-203, REQ-204 |
| Config externalization baseline | REQ-903 |

**Success criteria:** Protected endpoints enforce auth/tenant policies and reject abusive traffic deterministically.

### Phase 2 — Shared Data and Operational Guardrails (2-4 weeks)

**Objective:** Make stateful components and caching production-ready.

| Scope | Requirements |
|-------|-------------|
| Shared vector DB mode + caching | REQ-301, REQ-302, REQ-303 |
| Backup and retention policies | REQ-304 |

**Success criteria:** Repeat-query latency improves and restore procedures are validated.
