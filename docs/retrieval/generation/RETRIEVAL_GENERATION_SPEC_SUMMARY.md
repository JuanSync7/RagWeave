# Retrieval Pipeline — Generation and Safety Spec Summary

## 1) Generic System Overview

### Purpose

Once relevant documents have been retrieved and ranked, a secondary system must transform those document chunks into a coherent, trustworthy answer — and verify that the answer meets safety and quality standards before it reaches the user. This system covers the downstream half of the retrieval pipeline: context preparation, answer generation, post-generation safety enforcement, and operational observability. Without this layer, retrieved documents would surface as raw chunks rather than synthesized answers, hallucinated content would go undetected, and there would be no mechanism to block low-confidence or data-handling-unsafe responses from reaching users.

### How It Works

The pipeline begins after document retrieval and reranking are complete. In the context preparation stage, each retrieved chunk is wrapped with structured metadata — source identity, version, date, domain, and section — to form a deterministic, injection-ready context block. The stage also checks whether multiple retrieved documents reference the same source at conflicting versions; if a conflict is detected, it is flagged and surfaced explicitly to both the generator and the user.

The generation stage constructs a prompt from the prepared context and a fixed anti-hallucination instruction set, then invokes the language model. The generator is instructed to answer only from the provided documents, cite every factual claim, declare when information is insufficient, and self-report its confidence level. If the primary retrieval was weak and the query carries conversation history signals, the system may instead route through a memory-aware path: it either retries retrieval using a standalone query free of conversation context, or — when the query is explicitly backward-referencing prior turns and all retrieval fails — generates from conversation memory alone rather than from documents.

After generation, a multi-signal post-generation guardrail evaluates the answer before it is released. It computes a composite confidence score from three independent signals: retrieval quality, the model's self-reported confidence, and citation coverage. It also scans the output for personal information and redacts any detected items, and strips internal artifacts such as system prompt fragments or formatting markers. Based on the composite score and the risk level of the original query, the guardrail routes the answer: high-confidence answers are returned directly (with a verification notice for high-risk queries), moderate-confidence answers trigger a single broadened re-retrieval attempt, and low-confidence answers are blocked entirely. Blocked and flagged answers are excluded from conversation memory to prevent error echo in future turns.

Throughout every query, the pipeline records a structured trace covering all stages, their inputs, outputs, latencies, and decision points.

### Tunable Knobs

Operators can configure the composite confidence weights — adjusting how much the retrieval signal, the model's self-assessment, and citation coverage each contribute to the final score. The thresholds that divide "high", "moderate", and "low" confidence zones are independently configurable, as are the routing actions tied to each zone. Risk classification taxonomy (which query domains are treated as high-risk) is externalized and editable without code changes. Retry behavior for external service calls — including attempt count and backoff intervals — is configurable. PII detection patterns and output sanitization patterns can be extended via configuration. Latency budgets per stage are also configurable, enabling operators to tune performance targets for their deployment environment.

### Design Rationale

Separating context preparation from generation enforces a clean contract: the generator always receives a normalized, metadata-complete input regardless of the diversity of source documents. This makes the generation stage independently testable and the citation verification deterministic. The multi-signal confidence approach was chosen because no single signal is reliable in isolation — retrieval scores measure search quality but not generation quality, model self-reports are informative but biased toward overconfidence, and citation coverage is structural but cannot detect fluent paraphrasing that drifts from source material. Combining all three produces a more robust guard than any one alone. The one-retry re-retrieval pattern limits cost: most queries either need no retry or benefit from a single broader pass; unlimited retries would degrade latency without proportional quality gain. Memory-aware routing was added to handle conversational query patterns that break under a pure retrieval-first approach — backward-reference queries have no document answer by design, and forcing them through retrieval produces systematic failures.

### Boundary Semantics

Entry point: this system receives the output of the retrieval and reranking stages — a ranked list of document chunks plus query metadata including risk level, memory context, and retrieval quality signal. Exit point: it produces a structured response containing the generated answer (or a block message), a composite confidence score, citation metadata, any verification warnings, PII redaction records, and a generation source indicator. Conversation memory storage is the caller's responsibility; this system only signals whether a response is eligible for storage. The trace record is emitted as a side effect and consumed by the observability layer.

---

## 2) Header

| Field | Value |
|-------|-------|
| Companion spec | `RETRIEVAL_GENERATION_SPEC.md` |
| Version | 1.3 |
| Status | Draft |
| Domain | Retrieval Pipeline — Generation and Safety |
| Platform | AION Knowledge Management Platform |
| See also | `RETRIEVAL_QUERY_SPEC.md` (query processing, retrieval, reranking, conversation memory) |
| See also | `docs/performance/RAG_RETRIEVAL_PERFORMANCE_SPEC.md` (performance budgets, load testing) |

**Purpose of this summary:** Provide a concise, navigable digest of the generation and safety specification. Read the companion spec for full requirement text, acceptance criteria, and traceability.

---

## 3) Scope and Boundaries

**Entry point:** Ranked document chunks from the retrieval and reranking stages, plus query metadata (risk level, retrieval quality signal, memory context, backward-reference flag, suppress-memory flag).

**Exit point:** Structured response with generated answer or block message, composite confidence score, citation data, verification warnings, PII redaction log, generation source field, and query trace.

**In scope:**
- Document formatting and metadata injection for LLM context
- Version conflict detection across retrieved documents
- Anti-hallucination prompt construction and source citation enforcement
- Language model invocation with retry and backoff
- Memory-aware retrieval fallback and memory-generation routing
- Composite confidence scoring (retrieval signal + model self-report + citation coverage)
- Citation coverage verification and hallucination flagging
- PII detection and redaction from generated answers
- Output sanitization (system prompt leak removal, internal artifact stripping)
- Risk-level-aware confidence routing (pass, re-retrieve, flag, block)
- Conversation memory write eligibility gating for blocked/flagged responses
- End-to-end query tracing and per-stage metric capture
- Alerting threshold definitions for operational health
- Graceful degradation when optional components are unavailable
- Externalized configuration for all thresholds, weights, and patterns

**Out of scope** (covered in `RETRIEVAL_QUERY_SPEC.md`):
- Query classification, reformulation, and confidence scoring
- Pre-retrieval guardrail (injection detection, PII in queries, risk classification)
- Vector and keyword retrieval execution
- Reranking and score normalization
- Conversation memory management (storage, rolling summary, turn appending)
- Knowledge graph query expansion

**Out of scope** (covered in `RAG_RETRIEVAL_PERFORMANCE_SPEC.md`):
- Fast-path routing and per-stage timeout enforcement
- Load testing and capacity validation
- Evaluation harness configuration

---

## 4) Architecture / Pipeline Overview

This spec covers stages 7–11 of the end-to-end retrieval pipeline. Stages 1–6 are specified in `RETRIEVAL_QUERY_SPEC.md`.

```
[Reranked chunks + query metadata]  ←  from RETRIEVAL_QUERY_SPEC
         │
         ▼
┌─────────────────────────────┐
│  Stage 7: Document Formatting│  metadata injection, version conflict detection
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Stage 8: Generation         │  anti-hallucination prompt, citation enforcement,
│                              │  LLM call with retry/backoff
│  ┌────────────────────────┐  │
│  │ Stage 8a: Memory-Aware │  │  fallback retrieval, memory-generation path,
│  │ Generation Routing     │  │  suppress-memory enforcement, source tracking
│  └────────────────────────┘  │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Stage 9: Post-Gen Guardrail │  composite confidence, citation coverage,
│                              │  PII redaction, output sanitization,
│                              │  confidence routing (pass/re-retrieve/flag/block)
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Stage 10: Observability     │  end-to-end trace, per-stage metrics, alerting
└─────────────┬───────────────┘
              │
              ▼
     [RAGResponse to caller]
     (+ memory write eligibility signal)
```

**Confidence routing decision:**

```
composite score > 0.70  →  PASS  (+ verification warning if HIGH risk)
0.50 – 0.70             →  RE-RETRIEVE (one retry, then PASS or BLOCK)
< 0.50                  →  BLOCK  ("Insufficient documentation found")
BLOCK or FLAG           →  excluded from conversation memory storage
```

---

## 5) Requirement Framework

**ID convention:** `REQ-NNN` where the hundreds digit indicates pipeline stage.

| Range | Stage |
|-------|-------|
| REQ-501 – REQ-503 | Document Formatting |
| REQ-601 – REQ-605 | Generation |
| REQ-701 – REQ-706 | Post-Generation Guardrail |
| REQ-801 – REQ-803 | Observability |
| REQ-901 – REQ-903 | Non-Functional |
| REQ-1201 – REQ-1209 | Memory-Aware Generation Routing |

**Priority keywords:** MUST (normative), SHOULD (strong recommendation), MAY (optional).

**This spec (generation and safety scope):** 26 requirements — MUST: 20, SHOULD: 5, MAY: 0.

Each requirement includes:
- A description of the normative behavior
- A rationale explaining why the requirement exists
- Acceptance criteria for verifying the requirement

A full traceability matrix is in the companion spec.

---

## 6) Functional Requirement Domains

**Document Formatting (REQ-501 – REQ-503)**
Covers structured metadata injection into LLM context (source, version, date, domain, section), deterministic context string construction, and version conflict detection with explicit flagging and user-visible surfacing.

**Generation (REQ-601 – REQ-605)**
Covers anti-hallucination system prompt requirements (answer-from-documents-only, citation format, confidence self-report, insufficiency declaration), safe template variable handling for documents containing code or structured content, citation format enforcement, self-reported confidence extraction with bias correction, and retry-with-backoff for external language model calls.

**Memory-Aware Generation Routing (REQ-1201 – REQ-1209)**
Covers fallback retrieval using standalone query when primary retrieval is weak, memory-generation path for backward-reference queries when all retrieval fails, priority of retrieval-plus-memory over memory-only when retrieval succeeds, suppress-memory enforcement (context reset), exclusion of blocked/flagged responses from conversation memory storage, and generation source tracking in the response envelope.

**Post-Generation Guardrail (REQ-701 – REQ-706)**
Covers composite confidence score computation from three weighted signals (retrieval quality, model self-report, citation coverage), citation coverage verification and hallucination flagging, PII detection and typed-placeholder redaction, output sanitization (system prompt fragments, internal markers), enhanced numerical-value filtering for high-risk queries, and confidence-routing logic (pass, single re-retrieve, flag, block).

**Observability (REQ-801 – REQ-803)**
Covers end-to-end trace with unique trace ID per query, per-stage structured metric capture across all pipeline stages, and configurable alerting thresholds for composite confidence, latency, PII rate, and re-retrieval rate.

---

## 7) Non-Functional and Security Themes

**Performance**
- Per-stage latency targets are defined for all stages from query processing through post-generation guardrail
- End-to-end target is defined; per-stage budgets are proportional to computational complexity
- P95 latency is tracked alongside median

**Reliability and Graceful Degradation**
- The pipeline must not crash when any single optional component is unavailable
- Defined degraded behaviors for unavailability of: language model (generation and query processing paths), knowledge graph, embedding cache, query result cache
- Each degradation scenario is explicitly enumerated and testable

**Configuration Externalization**
- All thresholds, weights, patterns, and parameters must reside in configuration files
- Changes take effect on restart without code changes
- Missing values fall back to documented defaults

**Security and Data Handling**
- PII redaction before any answer reaches the user (regex and named-entity recognition coverage)
- Output sanitization to prevent system prompt leakage
- Audit logging of all redactions
- Blocked and flagged responses excluded from persistent conversation memory to prevent error accumulation

---

## 8) Design Principles

The following principles are evident from the rationale blocks throughout the spec:

- **Grounding over fluency** — answers must be traceable to retrieved documents; the system prefers acknowledging insufficient information over generating plausible-sounding content.
- **Defense in depth** — no single safety signal is sufficient; composite scoring, citation verification, and PII detection all run independently.
- **Retrieval primacy** — when retrieval succeeds at any quality level, the retrieval-based path is always preferred over memory-only generation.
- **Single retry discipline** — re-retrieval is attempted at most once; unlimited retries are excluded to contain latency and cost.
- **Fail visible** — version conflicts, low confidence, and PII detections are surfaced explicitly to users and operators rather than silently handled.
- **Configuration over code** — no threshold, weight, or pattern is hardcoded; all are externalized and documented.
- **Memory hygiene** — unreliable responses (blocked, flagged) are excluded from conversation memory to prevent error propagation across turns.

---

## 9) Key Decisions

**Three-signal composite confidence:** Retrieval quality, model self-report, and citation coverage are combined with configurable weights rather than relying on any single signal. Rationale: each signal captures a different failure mode; combination is more robust.

**One-retry re-retrieval:** When composite confidence falls in the mid-range, the system re-retrieves once with broader parameters. A second retry is not attempted. Rationale: diminishing returns after one broadening pass; latency cost of additional retries outweighs expected quality gain.

**Memory-generation path with confidence routing still applied:** When the system generates from conversation memory rather than documents, confidence routing (including blocking) is not bypassed. Rationale: low-quality memory answers are still harmful; the safety net applies regardless of generation source.

**Backward-reference detection triggers memory-generation only on retrieval failure:** If retrieval succeeds (strong or moderate), documents plus memory are used together even for backward-reference queries. Memory-only generation is a fallback, not a preference. Rationale: documents produce higher-quality answers than memory when available.

**Suppressed memory excludes conversation context from both retrieval and generation:** When a context reset is detected, the standalone query is used for retrieval and memory is excluded from the prompt entirely. Rationale: user intent to reset context must be respected end-to-end.

**Blocked/flagged responses excluded from memory storage:** Only user turns are always stored. Rationale: storing error messages in memory causes subsequent queries to reproduce the error via context injection.

**Generation source field in response envelope:** The response always indicates which path (retrieval, memory, or retrieval+memory) produced the answer. Rationale: downstream consumers need this signal for display, debugging, and future differentiated confidence thresholds.

---

## 10) Acceptance, Evaluation, and Feedback

Each requirement in the companion spec includes acceptance criteria. The spec defines measurable correctness for:

- Metadata completeness and format consistency for context chunks
- Version conflict detection and surfacing
- Citation presence and traceability in generated answers
- Composite confidence computation and per-signal logging
- Citation coverage measurement and threshold-triggered flagging
- PII detection coverage across defined categories and redaction output format
- Output sanitization correctness (no system prompt substrings, no internal markers)
- Confidence routing correctness across all score-range/risk-level combinations
- Memory path correctness: fallback retrieval triggering conditions, memory-generation triggering conditions, and suppression behavior
- Memory write eligibility gating for blocked and flagged responses
- Per-stage metric capture completeness
- Degraded-mode behavior for each enumerated component failure

The spec does not define an evaluation harness or automated regression suite — those are delegated to the performance spec and test infrastructure.

---

## 11) External Dependencies

**Required (pipeline cannot function without):**
- Language model API for generation (with retry/backoff logic required)

**Optional (pipeline degrades gracefully without):**
- Knowledge graph expansion (retrieval falls back to base query)
- Embedding cache (embeddings are recomputed on cache miss)
- Query result cache (full pipeline recomputes on cache miss)

**Downstream contracts:**
- Caller is responsible for conversation memory storage; this system provides the write-eligibility signal
- Observability layer consumes the structured trace and per-stage metrics emitted by this system
- Display layer is expected to render both the `generated_answer` field and the `verification_warning` field (the spec also appends warnings inline to `generated_answer` for display-layer compatibility)

---

## 12) Companion Documents

| Document | Relationship |
|----------|-------------|
| `RETRIEVAL_QUERY_SPEC.md` | Companion spec covering stages 1–6: query processing, pre-retrieval guardrail, retrieval, reranking, and conversation memory. REQ-1xx through REQ-4xx and REQ-10xx live there. |
| `docs/performance/RAG_RETRIEVAL_PERFORMANCE_SPEC.md` | Performance spec covering fast-path routing, per-stage timeout budgets, evaluation harness, load testing, and capacity validation. |
| `RETRIEVAL_GENERATION_DESIGN.md` | Design document with task decomposition and code contracts for this subsystem. |
| `RETRIEVAL_GENERATION_IMPLEMENTATION.md` | Implementation source-of-truth for this subsystem. |
| `RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` | Engineering guide documenting what was built, key decisions, and component behavior. |
| `RETRIEVAL_GENERATION_MODULE_TESTS.md` | Test planning document defining what to test per module. |

This summary covers the generation and safety scope only (stages 7–11 plus memory-aware routing). It is not a replacement for the companion spec — it is a navigational digest.

---

## 13) Sync Status

| Field | Value |
|-------|-------|
| Spec version | 1.3 |
| Spec last changed | 2026-03-27 |
| Summary written | 2026-04-10 |
| Aligned to | `RETRIEVAL_GENERATION_SPEC.md` v1.3 |
