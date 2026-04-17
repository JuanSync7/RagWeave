## 1) Generic System Overview

### Purpose

The guardrail integration layer provides a coordinated safety and intent-management subsystem around a retrieval-augmented generation pipeline. Without it, the pipeline processes every user query identically — routing greetings through expensive retrieval stages, passing adversarial injection attempts to the language model, and returning generated answers that may contain hallucinated facts, leaked sensitive data, or harmful content. This subsystem addresses all five failure modes in a single, cohesive layer: it classifies intent, detects adversarial queries, sanitizes sensitive data, and verifies the trustworthiness of generated output before it reaches the user.

### How It Works

The system operates in two execution phases relative to the generation boundary.

Before generation, four input rails run concurrently alongside existing query processing. An intent classifier assigns the query a canonical purpose label (search, greeting, farewell, administrative, or off-topic). Non-search intents are diverted to lightweight canned-response handlers and never enter the retrieval stages. For queries that reach retrieval, an injection and jailbreak detector applies semantic analysis as a defense-in-depth layer alongside any pre-existing pattern-based detection. A PII detector scans the query for personally identifiable information and replaces detected values with typed placeholders before the query flows downstream. A toxicity filter screens for harmful content categories and blocks offending queries with a policy-defined response. All four input rails feed into a merge gate that applies a fixed priority order — security rejections take precedence over intent routing, and PII redaction is non-blocking, modifying the query without altering its flow.

After generation, three output rails run sequentially. A faithfulness checker compares every claim in the generated answer against the exact set of retrieved context chunks used for generation, producing a grounding score. Answers that fall below a configurable threshold are either rejected or flagged with a warning, depending on operator configuration. A second PII detector inspects the generated answer itself, since source documents may contain sensitive data that the language model echoes. A toxicity filter applies a final content screen before the answer exits the pipeline.

The runtime is initialized once at worker startup and shared across all queries. A master toggle can disable the entire subsystem instantly, reverting pipeline behavior to its pre-integration baseline.

### Tunable Knobs

Operators can configure each rail independently. Intent classification exposes a confidence threshold below which the classifier falls back to search rather than diverting the query. Injection detection supports sensitivity tiers — strict, balanced, or permissive — allowing operators to trade false-positive rate against detection coverage. PII detection can be toggled separately for input and output, and the set of recognized PII categories is configurable. Toxicity detection exposes a numeric threshold controlling where the boundary between borderline and blocked content is drawn. Faithfulness checking exposes both the score threshold and the action taken on failure (reject versus flag). A master toggle controls the entire subsystem. All individual rails are also independently toggleable. Default values for all parameters are set to conservative, protective behavior.

### Design Rationale

Multiple independent safety layers are deliberately overlapping — if one layer fails or is bypassed, others remain active. This defense-in-depth principle means no single rail is a chokepoint. Input rails execute concurrently with query processing because serial execution would approximately double the per-query latency cost. Output rails execute sequentially because each depends on the output of the previous stage. The merge gate uses a fixed priority order — security verdicts before intent routing before query modification — so that safety outcomes are deterministic and auditable regardless of which combination of rails fires. Fail-safe behavior under error conditions (LLM unavailability, rail timeouts, runtime crashes) keeps the pipeline operational at reduced protection rather than causing total failure. Configuration is fully externalized so that safety policy changes require no code deployment.

### Boundary Semantics

The system's entry point is the raw user query arriving from the API layer, before any processing begins. Input rails and query processing start simultaneously. The merge gate collects both streams and produces a single routing decision. If the decision is search, the query (possibly with PII redacted) proceeds through retrieval and generation. After generation, the generated answer and the retrieved context chunks pass into the output rail sequence. The system's exit point is a verified, possibly modified answer enriched with a structured metadata field recording which rails executed, their verdicts, and their timing. The system neither stores state between queries nor modifies any persistence layer — it is a stateless processing wrapper around the pipeline.

---

## 2) Document Header

| Field | Value |
|-------|-------|
| **Companion Spec** | `NEMO_GUARDRAILS_SPEC.md` |
| **Version** | 1.0 (Draft) |
| **Domain** | Retrieval Pipeline — Safety & Intent Management |
| **Purpose** | Normative requirements for integrating a declarative rail framework into the RAG retrieval pipeline |
| **See Also** | `RETRIEVAL_QUERY_SPEC.md`, `PLATFORM_SERVICES_SPEC.md`, `NEMO_GUARDRAILS_IMPLEMENTATION.md` |

---

## 3) Scope and Boundaries

### Entry Point

A raw user query arrives at the guardrail layer before query processing begins (input rails) or after generation completes (output rails).

### Exit Point

For input rails: a verdict (`pass` / `reject` / `modify`) plus an intent label and any PII redactions applied to the query. For output rails: a verified or redacted answer with a structured guardrails metadata record.

### In Scope

- Canonical intent classification and non-search intent routing
- Injection and jailbreak detection as a defense-in-depth layer alongside existing pattern-based detection
- Input PII detection and type-tagged redaction
- Input toxicity filtering
- Output faithfulness and hallucination detection
- Output PII detection and redaction
- Output toxicity filtering
- Rail orchestration, merge gate logic, and runtime lifecycle management
- Structured logging, tracing, and metrics for all rail executions
- Full configuration externalization for all rails and thresholds
- Graceful degradation under LLM unavailability, rail timeouts, and runtime failure

### Out of Scope — This Spec

- Retrieval pipeline stages (query processing, knowledge graph expansion, hybrid search, reranking, generation) — covered by the parent retrieval specification
- Ingestion pipeline safety — covered by embedding pipeline specifications
- Authentication, authorization, and rate limiting — covered by the platform services specification

### Out of Scope — This Project

- Training custom detection models
- Real-time PII detection model fine-tuning
- Multi-language toxicity detection (English-only in Phase 1)

---

## 4) Architecture / Pipeline Overview

```
User Query (raw)
    │
    ├────────────────────────────────────┐
    │                                   │
    ▼                                   ▼
Existing Query Processing          Input Rails (parallel)
  Sanitize → Reformulate              [A] Intent Classifier
  → Evaluate → Route                  [B] Injection/Jailbreak Rail
                                      [C] PII Detection & Redaction
                                      [D] Toxicity Filter
    │                                   │
    └──────────────┬────────────────────┘
                   ▼
            Rail Merge Gate
         (inject > toxicity > intent > PII)
                   │
                   ▼  (if intent = search)
         Retrieval Stages 2–5
           KG Expand → Embed → Search → Rerank
                   │
                   ▼
              Generation
                   │
                   ▼
         Output Rails (sequential)
           [E] Faithfulness / Hallucination Check
           [F] Output PII Detection & Redaction
           [G] Output Toxicity Filter
                   │
                   ▼
         Final Response
           (RAGResponse + guardrails metadata)
```

**Data flow summary:**

| Stage | Input | Output |
|-------|-------|--------|
| Input Rails (parallel) | Raw user query | Intent label, injection verdict, PII redactions, toxicity verdict |
| Rail Merge Gate | Query result + input rail results | Single routing decision |
| Output Rails (sequential) | Generated answer + retrieved context | Faithfulness score, redacted answer, final verdicts |

---

## 5) Requirement Framework

- **Priority keywords:** RFC 2119 — MUST (absolute), SHOULD (recommended), MAY (optional)
- **Requirement format:** Each requirement includes a description, rationale, and acceptance criteria
- **ID convention:** `REQ-{section-prefix}{nn}` — three-digit IDs grouped by rail category
- **Total requirements:** 42 (30 MUST, 10 SHOULD, 2 MAY)
- **Traceability matrix:** Appendix of the companion spec maps every REQ-ID to its section, priority, and component

---

## 6) Functional Requirement Domains

| Domain | ID Range | Coverage |
|--------|----------|----------|
| **Input Rail — Canonical Intent Classification** | REQ-1xx | Intent taxonomy definition, Colang flow definitions, routing logic, confidence-based fallback, runtime extensibility |
| **Input Rail — Injection & Jailbreak Detection** | REQ-2xx | Semantic injection detection, rejection messaging, audit logging, configurable sensitivity |
| **Input Rail — PII Detection & Redaction** | REQ-3xx | Minimum PII categories (email, phone, government ID), extended categories, type-tagged redaction, rail toggle, detection logging |
| **Input Rail — Toxicity Filtering** | REQ-4xx | Toxicity category coverage, rejection messaging, configurable thresholds, rail toggle |
| **Output Rail — Faithfulness & Hallucination Detection** | REQ-5xx | Per-answer faithfulness scoring, configurable threshold and action (reject vs. flag), claim-level scoring, context-binding guarantee, entity hallucination detection |
| **Output Rail — Output PII & Toxicity Filtering** | REQ-6xx | Output PII detection and redaction, output toxicity detection and replacement, independent toggle from input rails |
| **Rail Orchestration & Runtime** | REQ-7xx | Runtime lifecycle (single initialization), parallel input rail execution, sequential output rail execution, configuration directory structure, per-rail toggles, master toggle, merge gate priority logic, guardrails metadata in response |

---

## 7) Non-Functional and Security Themes

**Performance:**
- Input rails (all, parallel) must complete within a target latency window at P95
- Output faithfulness check has a higher latency allowance than the input rail set
- Output PII and toxicity filtering must complete within a tight window
- Total rail overhead must fit within the overall pipeline timeout budget

**Resilience:**
- LLM unavailability triggers graceful fallback to deterministic alternatives for LLM-dependent rails
- Colang parse errors at startup produce clear, actionable failure messages
- Rail execution timeouts result in a pass-with-warning rather than pipeline failure
- Runtime crashes auto-disable the NeMo subsystem and revert to baseline pipeline behavior

**Observability:**
- Structured log entries per rail execution (rail name, verdict, timing, query ID, tenant ID)
- OpenTelemetry-compatible spans per rail, nested under the pipeline root span
- Prometheus metrics for rail execution counts, latency histograms, and rejection counts by rail and reason

**Configuration integrity:**
- Every threshold, toggle, and pattern must be externalized — nothing hardcoded
- Master toggle must produce zero side effects when set to disabled
- Per-rail environment variable naming follows a documented convention

**Testability:**
- Unit and integration test coverage target for the guardrails module
- Each graceful degradation scenario must have a corresponding test

---

## 8) Design Principles

| Principle | Description |
|-----------|-------------|
| **Defense in Depth** | Multiple independent safety layers provide overlapping coverage; no single rail is exclusively relied upon |
| **Fail-Safe over Fail-Fast** | Rail errors default to a safe action rather than crashing the pipeline |
| **Parallel by Default** | Input rails run concurrently with query processing to minimize latency impact |
| **Configurable Strictness** | Every rail is individually toggleable and tunable; production and development can apply different policies |
| **Observability First** | Every rail execution emits structured logs and telemetry spans for auditing and tuning |

---

## 9) Key Decisions

- **Parallel input rail execution** — Input rails run concurrently with query processing to avoid doubling stage latency. The merge gate synchronizes both streams before routing.
- **Sequential output rail execution** — Output rails run in a fixed order (faithfulness → PII → toxicity) to avoid wasted work: an answer rejected by faithfulness is not unnecessarily redacted.
- **Merge gate priority order** — Injection rejection overrides all; toxicity rejection overrides intent routing; PII redaction is non-blocking.
- **Single-initialization runtime** — The guardrail runtime initializes once at worker startup and is reused across queries to avoid per-query startup overhead.
- **Master kill switch** — A single environment variable disables the entire subsystem with zero side effects, enabling rapid rollback.
- **Defense-in-depth for injection** — The existing pattern-based injection detection is retained as a fast pre-filter alongside the new semantic detection layer.
- **Context binding for faithfulness** — The faithfulness checker must use the exact same retrieved context chunks that were provided to the generator — re-retrieval is prohibited.

---

## 10) Acceptance and Evaluation

The spec defines six system-level acceptance criteria:

- All input rails complete within the query processing latency budget at P95
- Injection detection achieves a defined minimum detection rate against a standard injection pattern set
- PII redaction produces zero PII value leakage in pipeline logs
- Faithfulness checking achieves a defined minimum recall on fabricated claims in a synthetic test set
- The master toggle disables all subsystem behavior with no observable side effects
- The pipeline remains operational under NeMo runtime unavailability

The spec does not define an evaluation or feedback loop framework beyond test coverage targets and Prometheus alerting. Threshold values for all criteria are specified in the companion spec.

---

## 11) External Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| Declarative rail framework SDK | Required | Must be installed and meet a minimum version; drives rail execution and flow loading |
| Local LLM inference endpoint | Required (for LLM rails) | Used for intent classification and faithfulness checking; falls back to deterministic alternatives when unavailable |
| OpenTelemetry-compatible tracing provider | Required (for observability) | Receives rail execution spans |
| Prometheus metrics endpoint | Required (for observability) | Receives rail execution counters and latency histograms |
| Existing pattern-based injection detection | Retained | Continues as a fast pre-filter; NeMo injection rail adds a second layer |

---

## 12) Companion Documents

This summary is a Layer 2 digest of the companion spec (`NEMO_GUARDRAILS_SPEC.md`). It captures intent, scope, requirement structure, and key decisions. For individual requirement text, acceptance criteria values, the traceability matrix, the glossary, and open questions, refer to the companion spec directly.

| Document | Relationship |
|----------|-------------|
| `NEMO_GUARDRAILS_SPEC.md` | Companion spec — normative source of truth for all requirements |
| `NEMO_GUARDRAILS_IMPLEMENTATION.md` | Implementation guide for this integration |
| `RETRIEVAL_QUERY_SPEC.md` | Parent retrieval pipeline specification — this integration extends it |
| `RETRIEVAL_ENGINEERING_GUIDE.md` | As-built retrieval documentation describing current runtime behavior |
| `PLATFORM_SERVICES_SPEC.md` | Platform specification covering auth, rate limiting, and other platform concerns |

---

## 13) Sync Status

| Field | Value |
|-------|-------|
| **Spec version aligned to** | 1.0 |
| **Spec date** | 2026-03-14 |
| **Summary written** | 2026-04-10 |
| **Sections covered** | All 10 requirement sections + 4 appendices |
| **Requirements counted** | 42 (30 MUST / 10 SHOULD / 2 MAY) |
