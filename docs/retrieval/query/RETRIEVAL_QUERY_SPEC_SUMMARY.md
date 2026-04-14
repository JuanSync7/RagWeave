# Retrieval Query & Ranking — Specification Summary

**Companion spec:** `RETRIEVAL_QUERY_SPEC.md` v1.3
**Domain:** Retrieval Pipeline — Query Processing and Ranking
**Status:** Draft
**See also:** `RETRIEVAL_GENERATION_SPEC.md` (generation, post-generation guardrails, observability, NFRs)

---

## 1) Generic System Overview

### Purpose

This system handles the query-facing half of a retrieval-augmented generation pipeline. Its job is to transform an ambiguous or conversationally-anchored natural language question into a set of well-formed retrieval queries, enforce input safety, find the most relevant documents from a corpus, and surface a high-confidence ranked set of evidence chunks to downstream generation. Without this system, user queries would hit a document index in their raw, noisy form — producing irrelevant results, exposing the system to injection attacks, and providing no mechanism to maintain coherence across a multi-turn conversation.

### How It Works

A query enters the system as raw natural language. The first stage reformulates it into one or two precision-optimized search queries. When conversation memory is active, the reformulation stage draws on a sliding window of recent exchanges and a compacted summary of earlier turns to resolve pronouns, expand backward references ("the above", "tell me more"), and detect when a user is resetting context. Two query variants are produced in a single model call: one enriched with conversational context, one polished from the current turn only. A confidence score is also assigned — queries that remain too ambiguous after reformulation are returned to the user with a clarification request rather than sent downstream.

Before retrieval begins, a guardrail stage validates the reformulated query: length bounds are checked, search parameters are range-validated, metadata filters are sanitized, and the query is scanned against an updatable list of injection patterns. Each query is also classified by risk tier — high-stakes domains receive a higher-friction verification path later in the pipeline. When an external model provider is in use, personally identifiable information is detected and redacted from the query before it leaves the system boundary.

Retrieval combines two complementary search strategies — semantic similarity search over dense embeddings and keyword-based search over full document text — whose outputs are merged using a configurable fusion weight. An optional knowledge-graph expansion step appends related terms to the keyword query to improve recall for acronyms and cross-domain entities. Metadata filters (document source, domain, type, version) narrow the candidate set before scoring begins. Embedding computation for repeated queries is cached to avoid redundant work, and a connection pool to the document store is maintained across requests. Full-pipeline response caching is also available for identical repeat queries within a configurable time window.

The final stage reranks the retrieved candidates using a cross-encoder model that scores each query–document pair independently. Scores are normalized and compared against tiered thresholds. Documents that fall below the minimum threshold are excluded from the generation context. If no document clears the threshold, the system returns a no-match signal rather than passing empty or weak context to the generator.

### Tunable Knobs

**Reformulation behavior:** Operators can control how many reformulation attempts are made before falling back to a clarification request, and can adjust the confidence threshold that governs when a query is considered ready for retrieval.

**Conversation memory window:** The number of recent turns injected as context is configurable globally and can be overridden per request. Compaction of older turns into a rolling summary can be triggered manually or automatically. Per-request controls allow memory to be disabled or the window narrowed for individual queries.

**Retrieval fusion weight:** The balance between semantic and keyword search is a runtime parameter. Setting it to either extreme yields a pure-mode search; the middle range blends both signals. The knowledge-graph expansion toggle, expansion depth, and term limit are independently adjustable.

**Candidate set size and reranking cutoffs:** How many candidates enter the reranker and how many pass through to generation are both configurable. The score thresholds that define strong, moderate, weak, and no-match zones can be changed without code modification.

**Safety and validation:** Injection pattern lists and risk-classification keyword taxonomies live in external configuration files, allowing them to be updated at restart without redeployment. Query length bounds, parameter ranges, and PII detection scope are all configurable.

**Caching:** Both the embedding cache size and the full-response cache TTL are configurable. Caching can be disabled entirely.

### Design Rationale

The separation of reformulation from retrieval reflects a fundamental mismatch: users speak conversationally, but document indexes are built for precise terminology. A reformulation stage bridges this gap without requiring users to formulate expert-level queries. The dual-query output (memory-enriched vs. standalone) is a hedge against a failure mode where injecting prior context narrows the query incorrectly — producing two variants in one model call keeps latency constant while enabling a fallback path.

Hybrid search exists because neither semantic nor keyword retrieval is universally superior. Technical corpora contain exact identifiers — part numbers, standard abbreviations, specification codes — that semantic search frequently misses. BM25 captures these; vector search captures conceptual meaning. The fusion weight exposes this tradeoff to operators rather than hard-coding a single strategy.

Reranking as a second pass reflects the cost asymmetry between retrieval and cross-encoder scoring: fast first-pass retrieval casts a wide net, and expensive but precise reranking narrows it. The hard exclusion floor prevents the generator from receiving irrelevant context, which is the primary driver of hallucinated answers.

Risk classification before generation enables proportional handling: high-consequence domains can be routed to stricter verification without adding friction to routine queries.

### Boundary Semantics

**Entry point:** A natural language query submitted by a user, optionally accompanied by a conversation identifier, memory control flags, and metadata filters. If memory is active and no conversation identifier is provided, one is created and returned.

**Exit point:** A ranked set of scored, reranked document chunks ready for ingestion by the generation stage. The output also carries the query result schema (reformulated query, standalone query, memory suppression flag, backward-reference flag, confidence score) and the assigned risk level. No answer text is produced by this system.

**State maintained:** Conversation turns and rolling summaries are persisted in a dedicated store with TTL-based expiration. Embedding and response caches are held in memory. All other intermediate artifacts are transient per request.

**Handoff:** This system's output is consumed by the generation stage (covered in the companion spec). Document ingestion, embedding model training, and offline evaluation infrastructure are upstream or external concerns and are not managed here.

---

## 2) Document Header

| Field | Value |
|-------|-------|
| Companion spec | `RETRIEVAL_QUERY_SPEC.md` |
| Spec version | 1.3 |
| Status | Draft |
| Domain | Retrieval Pipeline — Query Processing and Ranking |
| Companion spec (generation half) | `RETRIEVAL_GENERATION_SPEC.md` |

This summary covers the **query processing, conversation memory, conversational query routing, pre-retrieval guardrail, retrieval, and reranking** sections of the companion spec (Sections 3–6, 3a, 3b). For generation, post-generation guardrails, observability, and NFRs, see `RETRIEVAL_GENERATION_SPEC.md`.

---

## 3) Scope and Boundaries

**Entry point:** User submits a natural language query.

**Exit point:** User receives a generated answer with source citations and confidence metadata.

Everything between these two points is in scope for the retrieval pipeline overall. This spec covers the query-to-reranking half specifically.

**In scope:**
- Query reformulation and confidence-based routing
- Conversation memory: persistent storage, sliding window, rolling summary, lifecycle operations, per-request controls
- Conversational query routing: dual-query reformulation, backward-reference detection, context-reset detection, memory-aware reformulation prompt
- Pre-retrieval guardrail: input validation, injection detection, risk classification, PII redaction (external LLM mode)
- Retrieval: vector search, BM25, hybrid fusion, optional knowledge-graph expansion, metadata filtering, embedding cache, connection pooling, response cache
- Reranking: cross-encoder rescoring, score normalization, threshold-based exclusion

**Out of scope:**
- Document generation (covered in `RETRIEVAL_GENERATION_SPEC.md`)
- Post-generation guardrails and confidence scoring (covered in `RETRIEVAL_GENERATION_SPEC.md`)
- Answer delivery formatting and risk-based display (covered in `RETRIEVAL_GENERATION_SPEC.md`)
- Observability and non-functional requirements (covered in `RETRIEVAL_GENERATION_SPEC.md`)
- Document ingestion pipeline
- Embedding pipeline (offline)
- Offline evaluation infrastructure

---

## 4) Architecture / Pipeline Overview

The spec defines an 8-stage pipeline. This spec covers stages 1–4 (plus the conversation memory subsystem that feeds stage 1 and is written by stage 8).

```
User Query (natural language input)
    │
    ▼
┌─────────────────────────────────────┐
│ [1] QUERY PROCESSING                │◄── Conversation Memory
│     Reformulate → processed_query   │    (sliding window + rolling summary)
│     + standalone_query              │
│     Backward-ref & reset detection  │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│ [2] PRE-RETRIEVAL GUARDRAIL         │
│     Input validation                │
│     Injection detection             │
│     Risk classification             │
│     PII redaction (external mode)   │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│ [3] RETRIEVAL                       │
│     Vector search + BM25 hybrid     │
│     Optional KG expansion           │
│     Metadata filtering              │
│     Embedding cache / conn pool     │
│     Response cache (optional)       │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│ [4] RERANKING                       │
│     Cross-encoder rescoring         │
│     Score normalization             │
│     Threshold-based exclusion       │
└───────────────┬─────────────────────┘
                │
                ▼
          → Generation stage
            (RETRIEVAL_GENERATION_SPEC.md)
```

**Conversation Memory** is a persistent subsystem that feeds stage 1 (context injection) and is updated after stage 8 (answer delivery). It is defined in Section 3a of the spec.

---

## 5) Requirement Framework

Requirements follow RFC 2119 priority language:

- **MUST** — Absolute requirement; system is non-conformant without it.
- **SHOULD** — Recommended; may be omitted with documented justification.
- **MAY** — Optional; included at implementor's discretion.

Each requirement carries:
- A unique numeric ID (REQ-xxx)
- A priority keyword
- A description of the required behavior
- A rationale explaining why the requirement exists
- Acceptance criteria specifying how conformance is verified

A traceability matrix at the end of the spec maps all 34 requirements to their section and pipeline stage.

**Requirement totals for this spec:** 34 total — 24 MUST, 9 SHOULD, 1 MAY.

---

## 6) Functional Requirement Domains

| Domain | ID Range / Family | Coverage |
|--------|------------------|----------|
| Query Processing | REQ-101 to REQ-104 | Reformulation, confidence routing, coreference resolution, iterative refinement |
| Conversation Memory | REQ-1001 to REQ-1008 | Persistent tenant-scoped storage, sliding window, rolling summary, lifecycle operations, per-request memory controls, response identity, TTL expiration |
| Conversational Query Routing | REQ-1101 to REQ-1109 | Dual-query reformulation, zero-overhead structured output, backward-reference detection, context-reset detection and memory suppression, memory-aware reformulation prompt, query result schema extensions |
| Pre-Retrieval Guardrail | REQ-201 to REQ-205 | Input validation, prompt injection detection (external config), risk classification (keyword taxonomy), PII redaction (external LLM mode), structured rejection responses |
| Retrieval | REQ-301 to REQ-308 | Vector search, BM25 keyword search, hybrid fusion with configurable weight, optional knowledge-graph expansion, metadata pre-filtering, embedding cache (LRU), connection pooling, full-response cache (TTL) |
| Reranking | REQ-401 to REQ-403 | Cross-encoder rescoring, top-K cutoff, tiered score thresholds with hard exclusion floor |

---

## 7) Non-Functional and Security Themes

The companion spec (`RETRIEVAL_GENERATION_SPEC.md`) is the authoritative location for NFR and security requirements. However, several quality-of-service and security concerns surface within this spec's rationale text and acceptance criteria:

**Performance and efficiency:**
- Embedding caching to eliminate redundant computation on repeated queries
- Connection pooling to amortize database connection setup cost
- Full-pipeline response caching to bypass all expensive stages for repeat queries
- Dual-query reformulation designed to produce both variants in a single model call (zero additional latency)

**Security and data governance:**
- Injection pattern detection using externalized, hot-updateable configuration
- PII redaction before queries leave the system boundary (conditional on external model use)
- Sanitized rejection responses that do not expose internal pattern details to callers
- Risk classification as a prerequisite for proportional downstream verification

**Reliability:**
- Fail-fast health checks on startup prevent the system from accepting queries when the document store is unreachable
- Hard reranker floor prevents generation on irrelevant context (hallucination prevention)
- Conversation memory TTL expiration prevents unbounded storage growth

---

## 8) Design Principles

The spec does not include an explicit Design Principles section. The following principles are distilled from requirement rationales throughout the spec:

- **Reformulation before retrieval** — User queries are transformed into retrieval-optimized form before hitting the index; raw queries are never sent directly to the document store.
- **Hybrid over monoidal search** — Neither semantic nor keyword retrieval is sufficient alone; both signals are combined with an operator-tunable weight.
- **Configurable over hardcoded** — Safety patterns, risk taxonomies, thresholds, and tuning parameters are externalized to configuration files; behavior changes without code changes.
- **Fail safe on weak evidence** — Documents that do not meet the relevance threshold are excluded; the system declines to generate rather than hallucinate from poor context.
- **Memory as an opt-in enrichment** — Conversation memory improves coherence but can be suppressed per-request; memory failures or resets do not break the base retrieval path.
- **Dual-query hedging** — A standalone query variant is always produced alongside the memory-enriched one, providing a fallback without additional model calls.
- **Proportional verification** — Risk classification before generation enables high-stakes queries to receive stricter handling without adding friction to routine queries.

---

## 9) Key Decisions

- **Split from monolithic spec:** This spec was split from a single retrieval specification (v1.2) to separate query processing concerns from generation concerns. The query-to-reranking stages are in this document; generation, post-generation, and NFRs are in the companion spec.
- **Dual-query output in one model call:** Rather than two separate reformulation calls, both the memory-enriched and standalone query variants are produced via structured output in a single call. This was chosen to keep query processing latency constant.
- **Externalized injection and risk patterns:** Injection detection patterns and risk taxonomy keywords are stored in external configuration files rather than code, enabling updates without redeployment.
- **Knowledge-graph expansion is optional (MAY):** KG expansion is independently toggleable and carries MAY priority — the pipeline is fully functional without it.
- **PII redaction is conditional:** PII redaction is only required when using an external model provider. Local deployments do not require it (data does not leave the system boundary).
- **Conversation memory is separately routable:** The `suppress_memory`, `has_backward_reference`, and `standalone_query` fields on the query result schema enable downstream components to route differently without re-invoking the query processor.

---

## 10) Acceptance and Evaluation

The spec defines acceptance criteria on every individual requirement. There is no dedicated system-level acceptance criteria section or evaluation framework in this spec.

**Acceptance criteria patterns observed across the spec:**
- Behavioral correctness: given a specific input, the system produces a specific observable output (e.g., a vague query routes to clarification; a low-scoring document is excluded from context).
- Configurability verification: changing a parameter produces a measurably different outcome without code changes.
- Isolation: tenant-scoped memory does not bleed across tenants; memory-disabled queries produce the same result as stateless queries.
- Performance proxies: latency reduction on cache hits is observable; the dual-query path makes exactly one model call.

For system-level acceptance criteria, confidence scoring targets, and evaluation framework, see `RETRIEVAL_GENERATION_SPEC.md`.

---

## 11) External Dependencies

| Dependency | Role | Notes |
|------------|------|-------|
| Language model (query processing) | Reformulates queries, produces dual-query output via structured response | Required for query processing stage |
| Embedding model | Encodes the query into a dense vector at query time | Must match the model used during document ingestion |
| Vector database | Stores and serves dense document embeddings; supports metadata pre-filtering | Required; health-checked on startup |
| BM25 / full-text search index | Serves keyword-based document retrieval | Required alongside vector search |
| Cross-encoder reranking model | Scores query–document pairs for fine-grained reranking | Required for reranking stage |
| Conversation memory store | Persistent, TTL-aware store for conversation turns and rolling summaries | Required when conversation memory is enabled; optional for stateless deployments |
| Knowledge graph | Provides entity relationships for query expansion | Optional (MAY); independently toggleable |
| Language model (PII detection) | Detects and redacts PII from queries | Required only when external model provider is in use |
| Injection pattern config file | Defines prompt injection detection patterns | Required; loaded at startup; updated without redeployment |
| Risk taxonomy config file | Defines keyword lists for HIGH/MEDIUM/LOW risk classification | Required; externalized to config |

---

## 12) Companion Documents

| Document | Relationship |
|----------|-------------|
| `RETRIEVAL_QUERY_SPEC.md` | **Source spec** — this summary is derived from it |
| `RETRIEVAL_GENERATION_SPEC.md` | Companion spec — covers generation, post-generation guardrails, observability, and NFRs |
| `RETRIEVAL_ENGINEERING_GUIDE.md` | Engineering guide — describes currently implemented runtime behavior |
| `RETRIEVAL_NEW_ENGINEER_ONBOARDING_CHECKLIST.md` | Onboarding reference |
| `src/retrieval/README.md` | Source-level directory context |

This summary is a digest of the companion spec. It is designed to be readable without opening the spec, but is not a replacement for it. For requirement-level detail, acceptance criteria values, and the traceability matrix, refer to `RETRIEVAL_QUERY_SPEC.md` directly.

---

## 13) Sync Status

| Field | Value |
|-------|-------|
| Spec version aligned to | 1.3 |
| Summary written | 2026-04-10 |
| Summary status | Current |

> This summary was written against spec version 1.3. If the companion spec is updated, re-run `/write-spec-summary` to refresh this document.
