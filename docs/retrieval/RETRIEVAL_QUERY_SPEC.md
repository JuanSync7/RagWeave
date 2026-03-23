# Retrieval Pipeline — Query and Ranking Specification

**AION Knowledge Management Platform**
Version: 1.2 | Status: Draft | Domain: Retrieval Pipeline — Query Processing

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-11 | AI Assistant | Initial draft — 8-stage pipeline with 39 requirements |
| 1.1 | 2026-03-13 | AI Assistant | Added conversation memory section (REQ-1001–1008), performance budget cross-reference |
| 1.2 | 2026-03-17 | AI Assistant | Split from monolithic RETRIEVAL_SPEC.md. This file covers query processing, conversation memory, pre-retrieval guardrails, retrieval, and reranking (sections 1-6, REQ-101 through REQ-403 + REQ-1001 through REQ-1008). For generation, post-gen guardrails, and observability, see RETRIEVAL_GENERATION_SPEC.md. |

> **Document intent:** This is a normative requirements/specification document for the **query processing and retrieval** stages of the pipeline.
> For generation, document formatting, and post-generation guardrails, see `RETRIEVAL_GENERATION_SPEC.md`.
> For currently implemented runtime behavior, refer to `RETRIEVAL_ENGINEERING_GUIDE.md`, `RETRIEVAL_NEW_ENGINEER_ONBOARDING_CHECKLIST.md`, and `src/retrieval/README.md`.

---

## 1. Scope & Definitions

### 1.1 Scope

This specification defines the requirements for the **retrieval pipeline** of the AION RAG system. The pipeline boundary is:

- **Entry point:** User submits a natural language query
- **Exit point:** User receives a generated answer with source citations and confidence metadata

Everything between these two points is in scope. Document ingestion, embedding pipeline, and offline evaluation infrastructure are explicitly **out of scope**.

### 1.2 Terminology

| Term | Definition |
|------|-----------|
| **Hybrid Search** | A retrieval strategy combining dense vector similarity search (semantic) with BM25 keyword search (lexical) using a configurable fusion weight |
| **Reranking** | A second-pass scoring step using a cross-encoder model to re-score each (query, document) pair for fine-grained relevance |
| **Guardrail** | A validation checkpoint in the pipeline that inspects inputs or outputs and may reject, redact, or flag content before it proceeds |
| **Confidence Score** | A composite numerical score (0.0–1.0) derived from multiple independent signals indicating the reliability of the generated answer |
| **PII** | Personally Identifiable Information — names, email addresses, phone numbers, employee IDs, physical addresses, and other data that can identify an individual |
| **Risk Level** | A classification (HIGH, MEDIUM, LOW) assigned to a query based on the potential consequences of an incorrect answer |
| **Coreference Resolution** | The process of resolving pronouns and references ("it", "that", "the previous one") against prior conversation context |
| **Knowledge Graph (KG)** | A directed graph of domain entities and their relationships, used optionally to expand queries with related terms |
| **Fusion** | The method by which BM25 and vector search scores are combined into a single ranked list |
| **Conversation Memory** | Persistent, tenant-scoped storage of multi-turn conversation turns and rolling summaries used to provide conversational context across queries |
| **Sliding Window** | A context strategy that injects the N most recent conversation turns as context into query processing |
| **Rolling Summary** | A compacted summary of older conversation turns that is maintained to provide long-range context without unbounded growth |
| **Conversation Compaction** | The process of summarizing accumulated conversation turns into a condensed rolling summary, triggered manually or by turn-count thresholds |

### 1.3 Requirement Priority Levels

This document uses RFC 2119 language:

- **MUST** — Absolute requirement. The system is non-conformant without it.
- **SHOULD** — Recommended. May be omitted only with documented justification.
- **MAY** — Optional. Included at the implementor's discretion.

### 1.4 Requirement Format

Each requirement follows this structure:

> **REQ-xxx** | Priority: MUST/SHOULD/MAY
> **Description:** What the system shall do.
> **Rationale:** Why this requirement exists.
> **Acceptance Criteria:** How to verify conformance.

---

## 2. Pipeline Overview

### 2.1 Pipeline Stages

```text
User Query (natural language input)
    │
    ▼
┌──────────────────────────────────────┐
│ [1] QUERY PROCESSING                 │◄─── Conversation Memory
│     Reformulate, score confidence,   │     (sliding window + rolling
│     resolve multi-turn references    │      summary context injection)
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [2] PRE-RETRIEVAL GUARDRAIL          │
│     Input validation, injection      │
│     detection, risk classification,  │
│     PII filtering (external LLM)     │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [3] RETRIEVAL                        │
│     Vector search + BM25 hybrid      │
│     Optional KG expansion            │
│     Metadata filtering               │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [4] RERANKING                        │
│     Cross-encoder rescoring          │
│     Score normalization & thresholds │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [5] DOCUMENT FORMATTING              │
│     Structured metadata attachment   │
│     Version conflict detection       │
│     Context preparation for LLM      │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [6] GENERATION                       │
│     Anti-hallucination prompt        │
│     Source citation                  │
│     LLM confidence self-report       │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [7] POST-GENERATION GUARDRAIL        │
│     3-signal confidence scoring      │
│     Hallucination detection          │
│     PII filtering, output sanitize   │
│     Confidence routing               │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [8] ANSWER DELIVERY                  │───► Conversation Memory
│     Return answer with sources,      │     (persist turn, update
│     confidence, risk-based display   │      rolling summary)
└──────────────────────────────────────┘
```

### 2.2 Data Flow Summary

| Stage | Input | Output |
|-------|-------|--------|
| Query Processing | Raw user query, conversation memory context | Processed query, confidence, action (search/ask_user) |
| Pre-Retrieval Guardrail | Processed query, risk taxonomy, PII patterns | Validated query, risk level, or rejection |
| Retrieval | Validated query, query embedding, filters | Ranked candidate documents (top-N) |
| Reranking | Query, candidate documents | Re-scored documents (top-K), relevance scores |
| Document Formatting | Re-scored documents, metadata | Formatted context string, version conflict flags |
| Generation | Formatted context, query, system prompt | Generated answer with citations, LLM confidence |
| Post-Generation Guardrail | Answer, retrieved docs, scores, risk level | Validated answer or re-retrieval trigger or escalation |
| Answer Delivery | Validated answer, sources, confidence, risk | Final response to user; turn persisted to conversation memory |

---

## 3. Query Processing

> **REQ-101** | Priority: MUST
> **Description:** The system MUST reformulate user queries into precise retrieval queries using an LLM. The reformulation MUST add domain context, remove ambiguity, and generate up to 2 alternative phrasings for ambiguous queries.
> **Rationale:** Vague queries produce poor retrieval. A query like "what's the timing thing for USB" must be transformed into "USB controller timing constraints specification" before hitting the vector database.
> **Acceptance Criteria:** Given a vague query, the system produces a primary reformulated query and at least one alternative phrasing. Reformulated queries retrieve more relevant documents than the original query in A/B evaluation.

> **REQ-102** | Priority: MUST
> **Description:** The system MUST score each query for confidence (0.0–1.0) and route based on a configurable threshold. Queries above the threshold proceed to search. Queries below the threshold MUST be returned to the user with a clarification request.
> **Rationale:** Sending low-quality queries to retrieval wastes compute and returns poor results. It is better to ask the user for clarification.
> **Acceptance Criteria:** Queries like "asdf jkl" are routed to ask_user. Queries like "what is the supply voltage for USB power domain" are routed to search. The confidence threshold is configurable without code changes.

> **REQ-103** | Priority: SHOULD
> **Description:** The system SHOULD maintain conversation history (last N turns) and resolve coreferences in follow-up queries. Pronouns and references ("it", "that", "the previous one", "tell me more") SHOULD be resolved against recent conversation context before reformulation.
> **Rationale:** Without multi-turn context, users cannot have natural follow-up conversations. Every query is treated as independent, which limits usability in interactive deployments.
> **Acceptance Criteria:** After answering "What is the USB power domain voltage?", a follow-up query "What about the clock frequency?" is resolved to "What is the USB controller clock frequency?" using conversation context.

> **REQ-104** | Priority: MUST
> **Description:** The system MUST implement an iterative refinement loop for query processing. If the confidence score is below the threshold after reformulation, the system MUST retry reformulation up to a configurable maximum number of iterations before routing to ask_user.
> **Rationale:** A single reformulation attempt may not be sufficient for highly ambiguous queries. Iterative refinement gives the system multiple chances to improve query quality.
> **Acceptance Criteria:** The system attempts up to N reformulations (configurable, default 3) before giving up. Each iteration produces a measurably different query. The loop terminates early if confidence exceeds the threshold.

---

## 3a. Conversation Memory

> **REQ-1001** | Priority: MUST
> **Description:** The system MUST support persistent, tenant-scoped conversation memory. Each conversation MUST be isolated by tenant and principal identity. Conversations MUST persist across requests so that users can resume multi-turn interactions after disconnection.
> **Rationale:** Stateless query processing forces users to repeat context in every query. Persistent memory enables natural multi-turn interactions and eliminates redundant clarification, which is critical for complex engineering investigations that span multiple questions.
> **Acceptance Criteria:** A user can submit a query with a conversation identifier, disconnect, reconnect later, and submit a follow-up query that correctly resolves references to the earlier turn. Two different tenants using the same conversation identifier do not share state.

> **REQ-1002** | Priority: MUST
> **Description:** The system MUST implement a sliding window context strategy that injects the N most recent conversation turns into query processing. The window size (N) MUST be configurable globally and overridable per request.
> **Rationale:** Injecting the full conversation history into every query would exceed LLM context limits and degrade relevance. A bounded sliding window provides recent context while keeping token usage predictable.
> **Acceptance Criteria:** With a window size of 5, the 6th turn drops the oldest turn from the injected context. Changing the window size per request produces a different context window. The default window size is configurable without code changes.

> **REQ-1003** | Priority: SHOULD
> **Description:** The system SHOULD maintain a rolling summary of conversation turns that fall outside the sliding window. The summary SHOULD be compacted (condensed) periodically or on demand to prevent unbounded growth while preserving long-range conversational context.
> **Rationale:** Without a summary, older conversation context is completely lost when it exits the sliding window. A rolling summary preserves the essential themes and entities from earlier turns, enabling the system to maintain coherence across long conversations.
> **Acceptance Criteria:** After 20 turns with a window of 5, the system injects both the rolling summary (covering turns 1–15) and the 5 most recent turns. Compaction reduces summary size without losing key entities and topics.

> **REQ-1004** | Priority: MUST
> **Description:** The system MUST provide lifecycle operations for conversation management: create a new conversation, list conversations for a tenant/principal, retrieve conversation history, and trigger manual compaction.
> **Rationale:** Users and operators need to manage conversations explicitly — starting fresh investigations, reviewing past interactions, and controlling memory growth.
> **Acceptance Criteria:** All four lifecycle operations (create, list, history, compact) are available through the API. Creating a conversation returns a stable identifier. Listing conversations returns metadata (title, message count, timestamps). History returns the ordered turns for a conversation.

> **REQ-1005** | Priority: MUST
> **Description:** The system MUST support per-request memory controls: enabling or disabling memory injection, overriding the turn window size, and forcing immediate compaction after a turn.
> **Rationale:** Different query types benefit from different memory strategies. Exploratory queries benefit from full context; one-off lookups should not be polluted by prior conversation state. Operators may need to trigger compaction to control resource usage.
> **Acceptance Criteria:** A query with memory disabled produces the same result as a stateless query. A query with `memory_turn_window=2` injects only the 2 most recent turns regardless of the global default. A query with forced compaction triggers summary compaction before the response is returned.

> **REQ-1006** | Priority: MUST
> **Description:** The system MUST return the conversation identifier in every query response when memory is active, enabling clients to maintain conversation continuity without server-side session state.
> **Rationale:** Stateless clients (CLI, web console, API integrations) need the conversation identifier in responses to pass it back on subsequent requests.
> **Acceptance Criteria:** When a query is submitted without a conversation identifier and memory is enabled, the system creates a new conversation and returns its identifier in the response. When a query includes a conversation identifier, the same identifier is returned.

> **REQ-1007** | Priority: SHOULD
> **Description:** The system SHOULD use a dedicated persistent data store for conversation memory that supports TTL-based expiration. Conversations without activity beyond a configurable TTL SHOULD be automatically expired.
> **Rationale:** Conversation state grows over time. Without automatic expiration, inactive conversations accumulate and consume storage. A dedicated store with TTL support prevents unbounded growth without manual cleanup.
> **Acceptance Criteria:** A conversation with no activity for longer than the configured TTL is no longer retrievable. The TTL is configurable. Active conversations (with recent queries) are not affected by TTL expiration.

> **REQ-1008** | Priority: SHOULD
> **Description:** The system SHOULD inject conversation memory context into the query processing stage (Section 3) so that coreference resolution and query reformulation benefit from prior turns and the rolling summary.
> **Rationale:** Conversation memory is only valuable if it influences query processing. Injecting memory context before reformulation enables the system to resolve "it", "that", and "tell me more" against prior conversation state.
> **Acceptance Criteria:** A follow-up query "What about the clock frequency?" after a prior turn about "USB power domain voltage" is reformulated to include "USB controller" context from memory. The memory context appears in the query processing input, not just the generation prompt.

---

## 4. Pre-Retrieval Guardrail

> **REQ-201** | Priority: MUST
> **Description:** The system MUST validate all query inputs before retrieval. Validation MUST include:
>
> - Query length within configurable bounds (min and max characters)
> - Search parameters (`alpha`, `search_limit`, `rerank_top_k`) within valid ranges
> - Metadata filter values (`source_filter`, `heading_filter`) sanitized against injection
> **Rationale:** Unvalidated inputs passed directly to the vector database or LLM can cause errors, unexpected behavior, or security vulnerabilities.
> **Acceptance Criteria:** Out-of-range parameters are rejected with descriptive error messages. Filter values containing Weaviate query language injection are sanitized or rejected. Empty queries are rejected.

> **REQ-202** | Priority: MUST
> **Description:** The system MUST detect and reject prompt injection attempts. Injection patterns MUST be defined in an external configuration file (not hardcoded) so they can be updated without code changes.
> **Rationale:** Hardcoded patterns cannot be updated without redeployment. An external config file allows rapid response to new injection techniques.
> **Acceptance Criteria:** Injection patterns are loaded from a YAML/JSON config file at startup. Queries matching any pattern are rejected with a generic message (no information leakage about which pattern matched). New patterns can be added to the config file and take effect on restart.

> **REQ-203** | Priority: MUST
> **Description:** The system MUST classify each query's risk level as HIGH, MEDIUM, or LOW using a deterministic keyword taxonomy. The risk level MUST be computed before generation and attached to the pipeline state for downstream use.
> **Rationale:** Incorrect answers in certain domains (electrical specifications, timing constraints, safety compliance) have real consequences. Risk classification enables proportional verification friction — engineers only encounter verification overhead when the stakes justify it.
> **Acceptance Criteria:** Queries containing terms like "voltage", "timing constraint", "iso26262", "safety" are classified as HIGH. Queries containing "procedure", "guideline", "checklist" are classified as MEDIUM. All others default to LOW. Classification is deterministic and auditable. The keyword taxonomy is externalized to a config file.

> **REQ-204** | Priority: SHOULD
> **Description:** When the retrieval pipeline uses an external (non-local) LLM for query processing or generation, the system SHOULD detect and redact PII from the query before it is sent to the external API. PII types include: person names, email addresses, phone numbers, employee IDs, and physical addresses.
> **Rationale:** Sending PII to external LLM providers constitutes a data leak. This guardrail is conditional — it is not needed when using a local LLM (e.g., Ollama) where data stays on-premise.
> **Acceptance Criteria:** When external LLM mode is enabled, PII entities are detected and replaced with typed placeholders (e.g., `[PERSON]`, `[EMAIL]`) before the query leaves the system. The original query with PII is preserved internally for retrieval but never sent externally. PII detection covers at minimum: email regex, phone regex, and named entity recognition for person names.

> **REQ-205** | Priority: MUST
> **Description:** The system MUST reject queries that fail validation or injection detection. Rejected queries MUST return a structured error response (not an exception) with a user-safe message that does not reveal internal system details.
> **Rationale:** Revealing which specific pattern was matched or which validation rule failed gives attackers information to refine their injection attempts.
> **Acceptance Criteria:** Rejected queries return a response object with action="rejected", a generic user-facing message, and an internal log entry with the specific rejection reason.

---

## 5. Retrieval

> **REQ-301** | Priority: MUST
> **Description:** The system MUST support dense vector similarity search using pre-computed document embeddings. The query MUST be embedded at query time using the same embedding model used for document ingestion.
> **Rationale:** Semantic search captures conceptual similarity — queries like "how do I fix a setup violation" will match documents about timing closure even if the exact words differ.
> **Acceptance Criteria:** Vector search returns documents ranked by cosine similarity (or equivalent via L2-normalized dot product). The embedding model is configurable. Query embedding dimensions match document embedding dimensions.

> **REQ-302** | Priority: MUST
> **Description:** The system MUST support BM25 keyword search over the document corpus. BM25 search MUST operate on the full text content of each document chunk.
> **Rationale:** Semantic search alone misses exact terminology — part numbers, specification IDs, tool names, and acronyms. BM25 captures exact lexical matches that vector search may miss.
> **Acceptance Criteria:** A query for "DO-254 DAL-A compliance checklist" returns documents containing those exact terms, even if semantic similarity is low.

> **REQ-303** | Priority: MUST
> **Description:** The system MUST combine vector search and BM25 results using a hybrid fusion strategy. The fusion weight (alpha) MUST be configurable:
>
> - alpha = 0.0: pure BM25
> - alpha = 1.0: pure vector search
> - alpha = 0.5: equal weight (default)
>
> The fusion method MUST normalize scores from both sources to a common scale before combining.
> **Rationale:** Neither search modality is sufficient alone. Hybrid search captures both conceptual and lexical relevance.
> **Acceptance Criteria:** Changing alpha measurably shifts results toward keyword or semantic matches. The default alpha (0.5) produces results that include both exact-term and conceptual matches in the top-N.

> **REQ-304** | Priority: MAY
> **Description:** The system MAY expand queries using a knowledge graph before retrieval. When enabled, KG expansion MUST:
>
> - Match entities in the query against the KG
> - Traverse up to a configurable depth (default 1 hop)
> - Append related terms to the BM25 query (not the vector query)
> - Limit expansion to a configurable number of terms (default 3)
>
> KG expansion MUST be independently toggleable via configuration.
> **Rationale:** KG expansion improves recall for acronyms and related concepts (e.g., expanding "RAG" to "Retrieval-Augmented Generation"). However, over-expansion can introduce noise. This feature is optional.
> **Acceptance Criteria:** When enabled, KG-expanded terms appear in search results that would not have been retrieved without expansion. When disabled, the pipeline operates identically without KG. The feature toggle does not require code changes.

> **REQ-305** | Priority: MUST
> **Description:** The system MUST support metadata filtering at retrieval time. Supported filter dimensions MUST include at minimum: document source (filename), domain, document type, and version. Filters MUST be applied as pre-filtering (before scoring), not post-filtering.
> **Rationale:** Engineers often know which document or domain they want to search within. Pre-filtering reduces noise and improves relevance.
> **Acceptance Criteria:** A query with `source_filter="Power_Spec_v3.pdf"` only returns chunks from that document. Filters can be combined (e.g., domain + version). Filters with no matches return an empty result set (not an error).

> **REQ-306** | Priority: SHOULD
> **Description:** The system SHOULD cache query embeddings using an LRU (Least Recently Used) cache. Repeated or identical queries SHOULD return cached embeddings without recomputation.
> **Rationale:** Embedding computation is the most expensive per-query operation. RAG workloads frequently have repeated queries. Caching eliminates redundant computation.
> **Acceptance Criteria:** A query submitted twice in succession uses the cached embedding on the second call (measurable by latency reduction). The cache has a configurable maximum size. Cache eviction follows LRU policy.

> **REQ-307** | Priority: SHOULD
> **Description:** The system SHOULD maintain a persistent connection pool to the vector database rather than creating a new connection per query. The connection pool SHOULD include health checks on startup and periodic liveness checks.
> **Rationale:** Creating a new database connection per query adds latency and resource overhead. Connection pooling amortizes connection setup cost across queries.
> **Acceptance Criteria:** Multiple concurrent queries reuse connections from the pool. A health check failure on startup prevents the system from accepting queries (fail-fast). Connection failures during operation trigger reconnection without crashing.

> **REQ-308** | Priority: SHOULD
> **Description:** The system SHOULD cache full query results (search + rerank + generation) keyed by `(processed_query, filters)` with a configurable TTL (time-to-live). Cache hits SHOULD bypass all downstream pipeline stages.
> **Rationale:** Most RAG workloads have repeat queries. Caching the full response saves all expensive computation (search, reranking, generation).
> **Acceptance Criteria:** An identical query with identical filters returns a cached response within the TTL window. Responses are evicted after TTL expiry. Cache can be disabled via configuration. Cache keys are normalized (e.g., whitespace-insensitive).

---

## 6. Reranking

> **REQ-401** | Priority: MUST
> **Description:** The system MUST rerank retrieved documents using a cross-encoder model. The reranker MUST score each `(query, document)` pair independently and output a relevance score normalized to the range 0.0–1.0 (via sigmoid).
> **Rationale:** Initial retrieval (BM25 + vector) uses fast but approximate scoring. Cross-encoder reranking provides fine-grained relevance assessment by attending to the full query-document interaction.
> **Acceptance Criteria:** Reranked order differs from initial retrieval order in at least some cases (the reranker is not a no-op). Scores are in the range [0.0, 1.0]. The reranker model is configurable.

> **REQ-402** | Priority: MUST
> **Description:** The reranker MUST return a configurable top-K subset of documents after reranking. The default top-K MUST be configurable without code changes.
> **Rationale:** Only the highest-relevance documents should proceed to generation. Passing too many documents dilutes context quality and increases generation cost.
> **Acceptance Criteria:** Changing `rerank_top_k` from 5 to 3 results in only 3 documents being passed to generation. The parameter is configurable via settings.

> **REQ-403** | Priority: MUST
> **Description:** The system MUST define and enforce reranker score thresholds for interpretation:
>
> | Score Range | Interpretation | Action |
> |-------------|---------------|--------|
> | > 0.75 | Strong match | High retrieval confidence |
> | 0.50–0.75 | Moderate match | Proceed with caution |
> | 0.30–0.50 | Weak match | Flag, consider re-retrieval |
> | < 0.30 | No relevant match | Do not generate |
>
> Documents scoring below the minimum threshold (default 0.30) MUST be excluded from generation context.
> **Rationale:** Generating answers from irrelevant documents is the primary source of hallucination. A hard floor prevents the LLM from receiving junk context.
> **Acceptance Criteria:** No document with a reranker score below 0.30 appears in the generation context. If all documents score below the threshold, the system returns "Insufficient documentation found" instead of generating an answer. Thresholds are configurable.

---


---

## Query and Ranking Requirements Traceability Matrix

| REQ ID | Section | Priority | Pipeline Stage |
|--------|---------|----------|---------------|
| REQ-101 | 3 | MUST | Query Processing |
| REQ-102 | 3 | MUST | Query Processing |
| REQ-103 | 3 | SHOULD | Query Processing |
| REQ-104 | 3 | MUST | Query Processing |
| REQ-1001 | 3a | MUST | Conversation Memory |
| REQ-1002 | 3a | MUST | Conversation Memory |
| REQ-1003 | 3a | SHOULD | Conversation Memory |
| REQ-1004 | 3a | MUST | Conversation Memory |
| REQ-1005 | 3a | MUST | Conversation Memory |
| REQ-1006 | 3a | MUST | Conversation Memory |
| REQ-1007 | 3a | SHOULD | Conversation Memory |
| REQ-1008 | 3a | SHOULD | Conversation Memory |
| REQ-201 | 4 | MUST | Pre-Retrieval Guardrail |
| REQ-202 | 4 | MUST | Pre-Retrieval Guardrail |
| REQ-203 | 4 | MUST | Pre-Retrieval Guardrail |
| REQ-204 | 4 | SHOULD | Pre-Retrieval Guardrail |
| REQ-205 | 4 | MUST | Pre-Retrieval Guardrail |
| REQ-301 | 5 | MUST | Retrieval |
| REQ-302 | 5 | MUST | Retrieval |
| REQ-303 | 5 | MUST | Retrieval |
| REQ-304 | 5 | MAY | Retrieval |
| REQ-305 | 5 | MUST | Retrieval |
| REQ-306 | 5 | SHOULD | Retrieval |
| REQ-307 | 5 | SHOULD | Retrieval |
| REQ-308 | 5 | SHOULD | Retrieval |
| REQ-401 | 6 | MUST | Reranking |
| REQ-402 | 6 | MUST | Reranking |
| REQ-403 | 6 | MUST | Reranking |

**Total Requirements: 28** (MUST: 20, SHOULD: 7, MAY: 1)

For generation, post-generation, observability, and NFR requirements, see `RETRIEVAL_GENERATION_SPEC.md`.
