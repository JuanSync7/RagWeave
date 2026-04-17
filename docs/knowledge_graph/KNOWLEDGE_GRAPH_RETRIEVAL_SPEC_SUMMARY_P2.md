## 1) Generic System Overview

<!-- SCRAPEABLE SECTION — must be tech-agnostic. No FR-IDs, no technology names, no file names, no threshold values. Written from scratch. 250–450 words across all five sub-sections. -->

### Purpose

The graph-aware retrieval subsystem makes a knowledge graph's typed relationships actionable at query time. Without it, the graph stores domain knowledge — fix policies, dependency chains, specification traceability — but query expansion treats every edge identically and the language model receives no graph-derived context. Phase 1 added typed traversal and structured context formatting. Phase 2 closes the remaining gap: when traversal fans out across multiple graph regions (e.g., a blast-radius query), the language model now receives pre-computed thematic summaries for each affected region, providing the interpretive frame needed to reason about *why* the structural chain matters — not just *what* it touches.

### How It Works

A user query enters the entity matching stage, which identifies seed entities. Those seeds pass through typed edge traversal that follows only edges matching a configured predicate filter, with optional multi-hop path pattern evaluation for ordered edge type sequences. The traversal produces entities, relationship triples, and path chains.

After traversal, the system collects the community membership of every entity it touched — seeds, neighbors, and path intermediaries. For each unique community reached, it looks up a pre-built thematic summary (produced at index time by the community summarization pipeline, not at query time). These summaries are compact descriptions of what each cluster of entities represents as a group.

The graph context formatter assembles a structured text block with four sections: entity summaries, relationship triples grouped by predicate, path narratives articulating multi-hop chains, and community context entries describing the thematic role of each affected graph region. The detailed sections (entities, triples, paths) share one token budget; community summaries have an independent budget so they are never crowded out by detailed content. Path narratives now use configurable verb normalization — predicate labels map to natural-language verb phrases via a schema-defined table, falling back to space-separated label text when no mapping exists.

The formatted block is injected into the generation prompt before document chunks. When empty or disabled, the section is omitted cleanly.

### Tunable Knobs

Operators control which edge types are followed, which path patterns are evaluated, and the token budgets for both detailed graph context and community context independently. A master toggle enables or disables the entire enhancement. Section marker style is configurable for different prompt formats. The maximum number of entities explored per hop during path evaluation is adjustable per deployment. A verb normalization table maps predicate labels to readable phrases, defined alongside edge types in the schema.

### Design Rationale

Community context is additive — it supplements but never replaces detailed traversal results. Summaries are pre-computed at index time, making query-time injection a dictionary lookup with no language model cost. A separate token budget for community context prevents it from competing with path narratives, which encode the highest-value multi-hop reasoning. All new parameters follow the existing configuration pattern: typed fields with safe defaults, environment variable bindings, and validation at startup. When Phase 2 dependencies are unavailable (no community detection, no verb mappings), the system degrades exactly to Phase 1 behavior.

### Boundary Semantics

Entry: seed entities from the upstream entity matcher, the current graph state, and pre-computed community summaries from the index-time summarization pipeline. Exit: typed expansion terms for lexical query augmentation, and a formatted graph context block (now including community thematic framing) forwarded to the generation prompt. The subsystem consumes community summaries but does not produce them — community detection and summarization are owned by the indexing pipeline.

---

## Phase Context

**Phase:** P2
**Prior phases:**
- P1 — Typed edge traversal, path pattern matching, graph context formatting, and prompt injection of structured graph-derived context

**This phase adds:** Community context injection into the graph context block, configurable verb normalization for path narratives, and operator-tunable parameters for marker style, hop fanout, and community budget

---

# Knowledge Graph Retrieval Phase 2 — Specification Summary

**Companion document to:** `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC_P2.md` (v1.0.0, Draft)
**Purpose:** Requirements-level digest for stakeholders, reviewers, and implementers.
**See also:** `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md` (Phase 1 spec), `KNOWLEDGE_GRAPH_SPEC.md` (parent spec), `KNOWLEDGE_GRAPH_RETRIEVAL_ENGINEERING_GUIDE.md`

---

## 2) Scope and Boundaries

**Entry point:** The graph context formatting stage, after typed traversal and path pattern matching have produced their results.

**Exit points:**

- An augmented graph context block (now including community thematic framing) injected into the LLM generation prompt

### In scope

- Community context injection — surfacing pre-built community summaries in the graph context block alongside detailed traversal results
- Operator configurability — exposing marker style, max hop fanout, and verb normalization as configurable parameters

### Out of scope — this spec

- Community detection algorithm changes (resolution, hierarchical levels)
- Community summarization prompt or LLM changes
- Query-time LLM summarization of graph context
- Global search mode (fan out to all communities without seed entity)
- Named path pattern references in schema
- Tokenizer integration for token budget

### Out of scope — this project

- Graph neural network embeddings
- Real-time graph updates during query session
- Cross-graph federation

---

## 3) Architecture / Pipeline Overview

```
User Query
       │
       ▼
  [1] Entity Matching (existing)
       │ seed_entities[]
       ▼
  [2] Typed Edge Traversal + Path Matching (Phase 1)
       │ entities[], triples[], paths[]
       │
       ├──→ BM25 query augmentation
       │
       ├── NEW: collect community_ids from all traversed entities
       ▼
  [3] Graph Context Formatting (Phase 1 + P2)
       │ § Entity Summaries
       │ § Relationship Triples
       │ § Path Narratives         ◄── verb normalization (P2)
       │ § Community Context        ◄── pre-built summaries (P2)
       │
       │ graph_context_block (text)
       ▼
  [4] Prompt Injection (Phase 1)
       │ augmented LLM prompt
       ▼
  LLM Generation
```

Community summaries have an independent token budget; detailed sections retain their own. When community dependencies are unavailable, stages 3–4 produce identical output to Phase 1.

---

## 4) Requirement Framework

- **ID convention:** `REQ-KG-1300`–`REQ-KG-1339`, continuing the parent namespace
- **Priority keywords:** RFC 2119 (`MUST`, `SHOULD`, `MAY`)
- **Per-requirement structure:** Description, Rationale, Acceptance Criteria
- **Traceability matrix:** Section 8 listing all 14 requirements with section, priority, and component

---

## 5) Functional Requirement Domains

The Phase 2 functional requirements cover community context integration, verb normalization, and configuration surface expansion.

- **Community Context Integration** (`REQ-KG-1300`–`REQ-KG-1309`) — community ID collection from traversal, summary lookup, community context section formatting, independent token sub-budget, graceful degradation
- **Verb Normalization** (`REQ-KG-1310`–`REQ-KG-1319`) — configurable predicate-to-verb mapping table, schema co-location, fallback to underscore replacement
- **Configuration Enhancements** (`REQ-KG-1320`–`REQ-KG-1329`) — community context token budget, marker style env var, max hop fanout env var, environment variable convention
- **Non-Functional Requirements** (`REQ-KG-1330`–`REQ-KG-1339`) — community injection latency ceiling, one-time YAML loading, Phase 1 degradation guarantee

---

## 6) Non-Functional and Security Themes

### Non-functional areas (`REQ-KG-1330`–`REQ-KG-1339`)

- **Performance** — latency ceiling for community context injection across the formatting stage
- **Graceful degradation** — all Phase 2 features degrade to Phase 1 behavior when dependencies are unavailable
- **Configuration consistency** — all new parameters follow the existing environment variable convention

The spec does not define a standalone security requirement family.

---

## 7) Design Principles

- **Community context is additive**: supplements detailed graph context, never replaces it; omitted cleanly when unavailable
- **Index-time cost, query-time free**: community summaries are pre-computed; retrieval performs dictionary lookups only
- **Operator-tunable**: every behavioral parameter is exposed as a config field with an environment variable binding

---

## 8) Key Decisions Captured by the Spec

- Community summaries get an independent token sub-budget rather than sharing the detailed context budget — prevents thematic framing from competing with path narratives
- Community context section is placed last in the graph context block (after paths) — specifics-before-context information architecture
- Verb normalization table lives in the edge type schema file — single source of truth for predicate vocabulary and rendering
- Phase 1 open questions resolved: verb normalization in schema (not separate file), named patterns deferred (inline sufficient), chars-per-token approximation kept (soft budget, marginal accuracy gain not worth dependency)

---

## 9) Acceptance, Evaluation, and Feedback

- **System-level acceptance criteria** defined for: community injection latency, verb normalization correctness, budget enforcement, graceful degradation, and configuration surface completeness
- **Per-requirement acceptance criteria:** every requirement carries testable criteria
- **Phase 1 open questions:** all three resolved in Section 9 of the spec

---

## 10) Companion Documents

| Document | Role |
|----------|------|
| `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC_P2.md` | Authoritative Phase 2 requirements baseline |
| `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC_SUMMARY_P2.md` | This document — Phase 2 requirements digest |
| `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md` | Phase 1 specification |
| `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC_SUMMARY.md` | Phase 1 requirements digest |
| `KNOWLEDGE_GRAPH_SPEC.md` | Parent specification (community detection, global retrieval) |
| `config/kg_schema.yaml` | Edge type vocabulary and verb normalization table |

---

## 11) Sync Status

Aligned to `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC_P2.md` v1.0.0 as of 2026-04-14.
