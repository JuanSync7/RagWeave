# RAG Retrieval Performance and Validation Specification

**RAG Platform**
Version: 1.2 | Status: Implemented Baseline+OIDC+QuotaControls | Domain: Retrieval Performance

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-11 | AI Assistant | Initial draft focused on retrieval latency controls, evaluation harness, and load testing |
| 1.1 | 2026-03-11 | AI Assistant | Implemented baseline: fast-path flag, per-request iteration caps, stage budget tracking, pipeline budget metadata, and metrics export for stage latencies |
| 1.2 | 2026-03-11 | AI Assistant | Added tenant quota controls with admin APIs and OIDC-authenticated principal context for policy enforcement |

---

## 1. Scope & Definitions

### 1.1 Problem Statement

Retrieval latency is currently high for simple queries, and the platform lacks enforceable controls to prevent reformulation loops and stage-level budget overruns. Prompt/model changes can regress retrieval quality without a release gate, and there is no formal load test envelope to validate worker scaling behavior under concurrent users.

### 1.2 Scope

This specification defines requirements for the **retrieval performance and validation layer** of the RAG query path. The boundary is:

- **Entry point:** Query arrives at retrieval pipeline processing.
- **Exit point:** Retrieval stage completes with bounded latency and validated quality under defined load profiles.

Everything between these points is in scope, including retrieval fast-path controls, timeout budgeting, benchmark regression gates, and load test discipline.

### 1.2.1 Current Implementation Status (2026-03-11)

- Retrieval controls are policy-enforced with per-stage budget metadata and overall timeout controls.
- Tenant-level quota controls are now managed via admin APIs and enforced at API admission.
- OIDC-authenticated principal context is available for quota and tenancy enforcement.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **Fast Path** | A reduced-compute retrieval route that skips or limits expensive query refinement steps |
| **Stage Budget** | Maximum allowed latency per retrieval stage before fallback behavior is triggered |
| **Budget Overrun** | Stage execution exceeding configured latency budget |
| **Gold Set** | Curated query-answer/source dataset used for offline evaluation |
| **Regression Gate** | CI/CD criterion that blocks deployment on metric degradation |
| **Saturation Point** | Concurrency level where queue delay or error rate sharply increases |

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
| 3 | REQ-1xx | Retrieval Runtime Controls |
| 4 | REQ-2xx | Evaluation Harness and Regression |
| 5 | REQ-3xx | Load Testing and Capacity Validation |
| 6 | REQ-9xx | Non-Functional Requirements |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | Query processing uses LLM-assisted reformulation/evaluation | Fast-path and timeout controls must account for model response variance |
| A-2 | Stage timings are emitted for retrieval sub-steps | Budget and regression checks cannot be enforced without stage telemetry |
| A-3 | Temporal workers execute retrieval activities | Capacity testing must include queue behavior, not only isolated function latency |
| A-4 | A representative evaluation dataset can be maintained | Regression gate confidence degrades without stable benchmark coverage |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **Bounded Latency First** | Retrieval must fail predictably, not stall unpredictably |
| **Quality with Guardrails** | Performance optimizations must preserve relevance and grounding quality |
| **Measure Before Ship** | Prompt/model/config changes require benchmark evidence |
| **Scale with Evidence** | Worker replica decisions are based on load-test data, not assumptions |

### 1.8 Out of Scope

The following are explicitly **not covered** by this specification:

- Full generation model optimization strategy
- Front-end streaming UX details
- Ingestion pipeline document preprocessing quality

---

## 2. System Overview

### 2.1 Architecture Diagram

```
Query Entering Retrieval Pipeline
    │
    ▼
┌──────────────────────────────────────┐
│ [1] CLASSIFY + FAST-PATH DECISION    │
│     Route simple/high-confidence     │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [2] REFORMULATE / EVALUATE LOOP      │
│     Iterative refinement with caps   │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [3] RETRIEVAL EXECUTION              │
│     Search + rerank with stage caps  │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [4] BUDGET CHECK + FALLBACK          │
│     Timeout policy and route action  │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [5] EVALUATE + LOAD-TEST FEEDBACK    │
│     Benchmark gates and SLO evidence │
└──────────────────────────────────────┘
```

### 2.2 Data Flow Summary

| Stage | Input | Output |
|-------|-------|--------|
| Classify + Fast-Path Decision | Raw query + lightweight heuristics | Fast-path flag and iteration budget |
| Reformulate / Evaluate Loop | Query + iteration settings | Processed query, confidence score, route action |
| Retrieval Execution | Processed query + retrieval params | Ranked candidates and stage timings |
| Budget Check + Fallback | Stage timings + policy thresholds | Continue, degrade, or fail-fast decision |
| Evaluate + Load-Test Feedback | Offline and synthetic workloads | Regression report, capacity envelope, release decision |

---

## 3. Retrieval Runtime Controls

> **REQ-101** | Priority: MUST
> **Description:** The system MUST enforce a configurable maximum reformulation iteration count and MUST default to a bounded value suitable for interactive traffic.
> **Rationale:** Unbounded or excessive loops are a primary source of retrieval latency spikes.
> **Acceptance Criteria:** Configuration controls max iterations; attempts beyond limit do not execute and are logged with explicit cap reason.

> **REQ-102** | Priority: MUST
> **Description:** The system MUST support a fast-path mode that bypasses refinement for simple or high-confidence queries based on deterministic gating rules.
> **Rationale:** Many queries do not require full refinement; bypassing expensive LLM calls lowers p95 latency.
> **Acceptance Criteria:** Fast-path decision reason is recorded; eligible queries skip refinement and preserve acceptable retrieval quality.

> **REQ-103** | Priority: MUST
> **Description:** The system MUST implement stage-level timeout budgets for query reformulation, confidence evaluation, search, and reranking.
> **Rationale:** Stage budgets prevent one component from consuming the entire latency envelope.
> **Acceptance Criteria:** Over-budget stages are interrupted or short-circuited according to policy and reported in stage timings.

> **REQ-104** | Priority: MUST
> **Description:** The system MUST define fallback behavior for each budget overrun case, including graceful degradation path and user-safe response.
> **Rationale:** Timeout without fallback causes unpredictable failures and poor user trust.
> **Acceptance Criteria:** For each stage overrun category, integration tests verify deterministic fallback action and non-crashing behavior.

> **REQ-105** | Priority: SHOULD
> **Description:** The system SHOULD support typo normalization and lightweight lexical correction before refinement routing.
> **Rationale:** Obvious typo repair can avoid unnecessary iterative refinement cycles.
> **Acceptance Criteria:** Common typo suite shows corrected query forms and reduced refinement invocation rate.

> **REQ-106** | Priority: MUST
> **Description:** The system MUST emit structured stage timing telemetry for all retrieval sub-stages and aggregate totals by retrieval bucket.
> **Rationale:** Performance governance is impossible without stable timing instrumentation.
> **Acceptance Criteria:** Every query includes stage records with name, duration, bucket, and outcome status.

---

## 4. Evaluation Harness and Regression

> **REQ-201** | Priority: MUST
> **Description:** The system MUST maintain an offline gold evaluation set representing high-frequency and high-risk retrieval scenarios.
> **Rationale:** Real-world quality cannot be inferred from ad hoc manual checks.
> **Acceptance Criteria:** Dataset includes defined minimum coverage across query classes, with versioned snapshots and ownership.

> **REQ-202** | Priority: MUST
> **Description:** The system MUST compute benchmark metrics for retrieval quality and latency, including recall@k, nDCG@k, stage latency p95, and fallback rate.
> **Rationale:** Single-metric monitoring hides regressions that affect user outcomes.
> **Acceptance Criteria:** Benchmark job outputs all required metrics per run with baseline comparison.

> **REQ-203** | Priority: MUST
> **Description:** The system MUST enforce regression gates in CI/CD for prompt, model, and retrieval configuration changes.
> **Rationale:** Un-gated changes can silently degrade quality or latency in production.
> **Acceptance Criteria:** Release pipeline fails when configured degradation thresholds are breached.

> **REQ-204** | Priority: SHOULD
> **Description:** The system SHOULD include scenario-based benchmark slices for typo-heavy queries, short ambiguous queries, and domain-specific terminology.
> **Rationale:** Edge patterns often drive the worst latency and quality failures.
> **Acceptance Criteria:** Slice-level reports are generated and used in change review decisions.

> **REQ-205** | Priority: MUST
> **Description:** The system MUST track benchmark trend history and annotate runs with change metadata (model version, prompt hash, config version).
> **Rationale:** Root-cause analysis requires knowing exactly what changed between runs.
> **Acceptance Criteria:** Historical dashboard supports run-to-run diff by artifact versions.

---

## 5. Load Testing and Capacity Validation

> **REQ-301** | Priority: MUST
> **Description:** The system MUST define standardized load profiles for interactive and mixed workloads, including concurrency ramps and sustained windows.
> **Rationale:** Capacity claims are unreliable without repeatable workload definitions.
> **Acceptance Criteria:** Profiles are versioned, executable, and produce comparable results across environments.

> **REQ-302** | Priority: MUST
> **Description:** The system MUST measure worker scaling behavior on shared Temporal task queues, including queue delay, activity throughput, and saturation onset.
> **Rationale:** Horizontal scaling assumptions must be validated against queue dynamics.
> **Acceptance Criteria:** Replica-sweep test reports throughput curve and identifies knee point for each profile.

> **REQ-303** | Priority: MUST
> **Description:** The system MUST validate API timeout, cancellation, and retry behavior under load, including client-observed error semantics.
> **Rationale:** High-load failure behavior must remain predictable for callers.
> **Acceptance Criteria:** Load tests include cancel/timeout scenarios with expected status code and retry guidance outcomes.

> **REQ-304** | Priority: SHOULD
> **Description:** The system SHOULD run scheduled canary load tests in pre-production before major retrieval model or prompt revisions.
> **Rationale:** Canary testing catches scaling regressions before full rollout.
> **Acceptance Criteria:** Major retrieval changes include signed canary report before promotion.

> **REQ-305** | Priority: MUST
> **Description:** The system MUST publish a capacity envelope documenting supported concurrency, expected p95 latency, and headroom thresholds.
> **Rationale:** Operations and product commitments require explicit capacity boundaries.
> **Acceptance Criteria:** Capacity envelope is refreshed after significant platform or model changes and referenced in release notes.

---

## 6. Non-Functional Requirements

> **REQ-901** | Priority: SHOULD
> **Description:** The system SHOULD meet the following retrieval path targets under standard interactive load:
>
> | Component/Stage | Target |
> |-----------------|--------|
> | Fast-path decision | < 20ms p95 |
> | Reformulate/evaluate total | < 1200ms p95 |
> | Search + rerank total | < 800ms p95 |
> | Retrieval total | < 2000ms p95 |
> | **Retrieval timeout hard ceiling** | **<= 3000ms per request policy path** |
>
> **Rationale:** Interactive RAG performance requires bounded retrieval so generation can begin promptly.
> **Acceptance Criteria:** SLO tracking shows compliance or documented error-budget exceptions.

> **REQ-902** | Priority: MUST
> **Description:** The system MUST degrade gracefully when retrieval performance dependencies are impaired:
>
> | Component Unavailable | Degraded Behavior |
> |----------------------|-------------------|
> | Query refinement model | Skip to fast path with conservative retrieval parameters |
> | Reranker model | Return search-ranked candidates with confidence downgrade |
> | Benchmark backend | Continue serving traffic and mark release gates as non-passing for protected branches |
>
> The system MUST NOT crash or emit unhandled exceptions due to single-component degradation.
> **Rationale:** Retrieval path resilience is required to preserve service continuity during partial outages.
> **Acceptance Criteria:** Chaos tests demonstrate each degraded path and successful recovery.

> **REQ-903** | Priority: MUST
> **Description:** All retrieval latency controls, iteration caps, budget thresholds, benchmark gates, and load profiles MUST be configuration-driven and versioned.
> **Rationale:** Performance tuning is continuous and must not require code rewrites for each adjustment.
> **Acceptance Criteria:** Config-only changes can adjust control behavior and are traceable to release artifacts.

---

## 7. System-Level Acceptance Criteria

| Criterion | Threshold | Related Requirements |
|-----------|-----------|---------------------|
| Retrieval latency containment | p95 retrieval <= target on standard profile | REQ-101, REQ-102, REQ-103, REQ-901 |
| Timeout determinism | 100% timeout paths map to defined fallback outcomes | REQ-104, REQ-902 |
| Regression protection | 100% governed changes pass benchmark gates | REQ-201, REQ-202, REQ-203, REQ-205 |
| Scaling evidence | Capacity envelope updated after replica sweep | REQ-302, REQ-305 |
| Load failure semantics | Timeout/cancel behavior matches contract under stress | REQ-303 |

---

## 8. Requirements Traceability Matrix

| REQ ID | Section | Priority | Component/Stage |
|--------|---------|----------|----------------|
| REQ-101 | 3 | MUST | Retrieval Runtime Controls |
| REQ-102 | 3 | MUST | Retrieval Runtime Controls |
| REQ-103 | 3 | MUST | Retrieval Runtime Controls |
| REQ-104 | 3 | MUST | Retrieval Runtime Controls |
| REQ-105 | 3 | SHOULD | Retrieval Runtime Controls |
| REQ-106 | 3 | MUST | Retrieval Runtime Controls |
| REQ-201 | 4 | MUST | Evaluation Harness and Regression |
| REQ-202 | 4 | MUST | Evaluation Harness and Regression |
| REQ-203 | 4 | MUST | Evaluation Harness and Regression |
| REQ-204 | 4 | SHOULD | Evaluation Harness and Regression |
| REQ-205 | 4 | MUST | Evaluation Harness and Regression |
| REQ-301 | 5 | MUST | Load Testing and Capacity Validation |
| REQ-302 | 5 | MUST | Load Testing and Capacity Validation |
| REQ-303 | 5 | MUST | Load Testing and Capacity Validation |
| REQ-304 | 5 | SHOULD | Load Testing and Capacity Validation |
| REQ-305 | 5 | MUST | Load Testing and Capacity Validation |
| REQ-901 | 6 | SHOULD | Non-Functional |
| REQ-902 | 6 | MUST | Non-Functional |
| REQ-903 | 6 | MUST | Non-Functional |

**Total Requirements: 19**
- MUST: 15
- SHOULD: 4
- MAY: 0

---

## Appendix A. Implementation Phasing

### Phase 1 — Latency Guardrails (1-2 weeks)

**Objective:** Bound retrieval latency and establish deterministic fallback behavior.

| Scope | Requirements |
|-------|-------------|
| Iteration and fast-path controls | REQ-101, REQ-102, REQ-105 |
| Stage budgets and fallback matrix | REQ-103, REQ-104, REQ-106, REQ-903 |

**Success criteria:** Retrieval no longer exhibits uncontrolled long-tail stalls for common query classes.

### Phase 2 — Benchmark Governance (1-2 weeks)

**Objective:** Prevent quality/latency regressions in release flow.

| Scope | Requirements |
|-------|-------------|
| Gold set + metric suite | REQ-201, REQ-202, REQ-204 |
| CI/CD regression gates + trend tracking | REQ-203, REQ-205 |

**Success criteria:** Prompt/model changes cannot merge when benchmark thresholds are violated.

### Phase 3 — Capacity Validation (1-2 weeks)

**Objective:** Quantify worker scaling and publish operating envelope.

| Scope | Requirements |
|-------|-------------|
| Load profiles + queue scaling analysis | REQ-301, REQ-302 |
| Stress failure semantics + capacity docs | REQ-303, REQ-304, REQ-305, REQ-901, REQ-902 |

**Success criteria:** Team has an evidence-backed concurrency envelope and response strategy for saturation.
