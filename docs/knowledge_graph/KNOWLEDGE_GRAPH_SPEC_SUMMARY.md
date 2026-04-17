## 1) Generic System Overview

<!-- SCRAPEABLE SECTION — must be tech-agnostic. No FR-IDs, no technology names, no file names, no threshold values. Written from scratch. 250–450 words across all five sub-sections. -->

### Purpose

The knowledge graph subsystem extracts entities and relationships from documents during ingestion, persists them in a queryable graph, and uses that graph at query time to broaden lexical search with related concepts. Without it, retrieval matches only literal query terms — paraphrased queries, acronym variants, and conceptually adjacent topics are missed. It replaces an earlier monolithic module with a modular architecture supporting pluggable storage backends.

### How It Works

At ingestion, each chunk passes through a multi-extractor stage whose branches run in parallel: deterministic surface patterns, zero-shot entity recognition against a domain label set, generative-model structured extraction with schema-guided prompting, and source-code parsing. Outputs converge on a merge stage that deduplicates by case-insensitive name plus alias, resolves type conflicts via extractor priority, and validates every type against the active schema. The merged result is upserted into the graph backend, accumulating mention text, sources, and edge weights on existing items. When an entity's mentions exceed a token budget, a summarisation pass condenses them and retains a top-K subset.

At query time, an entity matcher scans the query for known entities using token-boundary rules, with an optional generative-model fallback for paraphrases. Matched entities seed a bounded outward traversal whose neighbours become expansion terms appended to the lexical query.

### Tunable Knobs

Operators choose the storage backend — in-memory for small projects, external for graphs exceeding single-machine memory. Per-extractor toggles control which techniques participate, so minimal-dependency deployments can run with the surface-pattern extractor alone. An active-phase setting filters the schema to a capability tier. Expansion fan-out caps traversal depth and term count appended per query. A description token budget governs when mentions are summarised, and a retained-mention count caps how many raw mentions survive compaction. A fallback timeout bounds the slower paraphrase matcher.

### Design Rationale

A formal type schema is the single source of truth for valid entities and relationships, serving as both prompt context and runtime validator so extractors cannot fragment the graph with ad-hoc categories. Storage sits behind an abstract backend interface, allowing the underlying store to be swapped without touching extraction or query code. Extractors run in parallel so total latency is bounded by the slowest one, and a single extractor's failure never blocks ingestion. Expansion is always bounded so precision degrades gracefully. Phase tagging lets the data model evolve through capability tiers without breaking earlier deployments.

### Boundary Semantics

Ingestion entry: the extraction stage receives chunks with source identifiers and emits a structured extraction result, which the storage stage persists. Query entry: the expansion stage receives a normalised user query and returns extra lexical-query terms. The subsystem owns its persistent graph state but not document parsing, embeddings, reranking, or answer generation. Responsibility ends once entities are stored or expansion terms returned.

---

# Knowledge Graph Subsystem — Specification Summary

**Companion document to:** `KNOWLEDGE_GRAPH_SPEC.md` (v1.1.0, Draft)
**Purpose:** Requirements-level digest for stakeholders, reviewers, and implementers.
**See also:** `KNOWLEDGE_GRAPH_DESIGN.md`, `KNOWLEDGE_GRAPH_IMPLEMENTATION.md`, `KNOWLEDGE_GRAPH_ENGINEERING_GUIDE.md`, `KNOWLEDGE_GRAPH_PHASE1B_DESIGN.md`, `KNOWLEDGE_GRAPH_PHASE2_DESIGN.md`, `KNOWLEDGE_GRAPH_PHASE3_DESIGN.md`, `KNOWLEDGE_GRAPH_TEST_PLAN.md`, `KNOWLEDGE_GRAPH_EVAL_PLAN.md`

---

## 2) Scope and Boundaries

**Entry points:**

- **Ingestion:** Embedding Pipeline Node 10 (extraction) and Node 13 (storage) invoke the subsystem to extract entities/triples from document chunks and persist them.
- **Retrieval:** Retrieval Pipeline Stage 2 invokes the subsystem to match entities in user queries and expand them with graph-derived terms.
- **Configuration:** A YAML schema file defines all valid entity and edge types.

**Exit points:**

- Persisted graph store containing entities, triples, and entity descriptions.
- Expansion terms appended to the lexical retrieval query.
- Optional human-readable export (e.g., wiki-style markdown).

### In scope

- YAML-driven entity/edge type schema with validation
- `GraphStorageBackend` ABC and concrete `NetworkXBackend` implementation
- Multi-extractor architecture: regex, GLiNER, LLM (Phase 1b), SV parser (Phase 1b)
- LangGraph subgraph for extraction pipeline (parallel branches, merge node)
- Entity descriptions: accumulated rich text per node with LLM summarization
- Two-tier query matching: spaCy rule-based + LLM fallback (Phase 1b)
- Query sanitization: token-boundary matching, alias expansion, fan-out control
- Package structure (`src/knowledge_graph/`) with public API and lazy singleton
- Backward compatibility with `src/core/knowledge_graph.py` during migration
- Obsidian export (migrated from monolith)
- Neo4j backend stub (Phase 1 — stub only; full implementation Phase 2)
- Community detection stub (Phase 2)

### Out of scope

- Document parsing, text extraction, cleaning (see `DOCUMENT_PROCESSING_SPEC.md`)
- Vector embedding generation and storage (see `EMBEDDING_PIPELINE_SPEC.md`)
- Answer generation, reranking, guardrails (see `RETRIEVAL_QUERY_SPEC.md`, `RETRIEVAL_GENERATION_SPEC.md`)
- Real-time graph streaming or event-driven updates
- Multi-tenant graph isolation (single-tenant only in Phase 1)

---

## 3) Architecture / Pipeline Overview

```
    INGESTION                                       RETRIEVAL
    =========                                       =========

    Document Chunks                                 User Query
           │                                              │
           ▼                                              ▼
    ┌──────────────────────────────┐         ┌──────────────────────┐
    │  [Node 10] EXTRACTION        │         │  [Stage 2] EXPANSION │
    │                              │         │                      │
    │   Parallel branches:         │         │   Entity matcher     │
    │     • Surface-pattern        │         │     • Token-boundary │
    │     • Zero-shot NER          │         │     • Model fallback │
    │     • Generative model    *  │         │       (Phase 1b)  *  │
    │     • SystemVerilog parser*  │         │                      │
    │                ↓             │         │   Bounded traversal  │
    │           MERGE STAGE        │         │     • Fan-out cap    │
    │     dedup + type validation  │         │     • Depth cap      │
    │                ↓             │         │                      │
    │       ExtractionResult       │         │   Expansion terms    │
    └──────────────┬───────────────┘         └──────────┬───────────┘
                   │                                    │
                   ▼                                    ▼
    ┌──────────────────────────────┐         Lexical query gets
    │  [Node 13] STORAGE           │         appended terms
    │   backend.upsert_entities()  │
    │   backend.upsert_triples()   │
    │   backend.upsert_descriptions│
    └──────────────┬───────────────┘
                   │
                   ▼
            Graph Backend
       (in-memory or external DB)

    * = optional / configurable
```

The extraction subgraph runs branches in parallel so total latency is bounded by the slowest enabled extractor. A single extractor failure does not halt ingestion — surviving branches still produce output. The storage backend abstraction lets the underlying store change without touching extraction or query code.

---

## 4) Requirement Framework

The spec uses a formal requirement framework with the following structural elements:

- **ID convention:** `REQ-KG-xxx` for the core spec; `REQ-KG-1b-xxx` for Phase 1b detailed appendix requirements.
- **Priority keywords:** RFC 2119 (`MUST`, `SHOULD`, `MAY`).
- **Phase tags:** Each requirement is tagged with a delivery phase (`Phase 1`, `Phase 1b`, `Phase 2`, `Phase 3`).
- **Per-requirement structure:** Description, Rationale, Acceptance Criteria.
- **Traceability matrix:** Appendix B in the spec maps requirements to source material.
- **Glossary:** Terminology table in §1.2 of the spec.

---

## 5) Functional Requirement Domains

The functional requirements cover schema governance, package architecture, multi-extractor extraction, entity descriptions, storage, query expansion, community detection, export, integration, and Phase 1b/2/3 extensions.

- **Schema and Configuration** (`REQ-KG-100`–`REQ-KG-199`)
- **Package Architecture** (`REQ-KG-200`–`REQ-KG-299`)
- **Entity Extraction** (`REQ-KG-300`–`REQ-KG-399`)
- **Entity Descriptions** (`REQ-KG-400`–`REQ-KG-499`)
- **Graph Storage** (`REQ-KG-500`–`REQ-KG-599`)
- **Query and Retrieval** (`REQ-KG-600`–`REQ-KG-699`)
- **Community Detection** (`REQ-KG-700`–`REQ-KG-729`, with Phase 2 detail in Appendix D)
- **Export and Visualization** (`REQ-KG-800`–`REQ-KG-899`)
- **Integration Points** (`REQ-KG-900`–`REQ-KG-999`)
- **Phase 1b detailed extractor/query requirements** (`REQ-KG-1b-100`–`REQ-KG-1b-399`, Appendix C)
- **Phase 3 extensions** (`REQ-KG-730`–`REQ-KG-756`, Appendix E) — incremental updates, cross-module connectivity, hierarchical communities, browser visualization, embedding-based entity resolution, dependency management

---

## 6) Non-Functional and Security Themes

### Non-functional areas (`REQ-KG-1000`–`REQ-KG-1099`)

- **Performance** (per-extractor latency budgets, query expansion budget, parallel-bound rather than sequential-sum extraction latency)
- **Scalability** (node/edge thresholds for the in-memory backend, warning thresholds for graph size)
- **Persistence performance** (serialization and deserialization budgets at the documented graph sizes)

### Testing requirements (`REQ-KG-1100`–`REQ-KG-1199`)

- ABC contract tests parameterized across all backend implementations
- Extraction regression tests (migration parity with the legacy module)
- Query expansion correctness tests
- End-to-end ingestion integration tests
- Schema validation tests
- Merge node deduplication and conflict-resolution tests
- Entity description accumulation/summarization tests
- Backward compatibility shim tests

The spec does not define a standalone security/compliance requirement family; security-relevant constraints (e.g., credential masking for the external database backend) are embedded inside their respective config requirements.

---

## 7) Design Principles

- **ABC backend abstraction:** All graph operations route through the storage ABC; swapping backends is a configuration change.
- **YAML schema as single source of truth:** Entity and edge types are defined once and used for prompt context, validation, and runtime type checking.
- **Fail-safe extraction:** A single extractor failure never halts ingestion; surviving extractors still produce output.
- **Explicit composition over registry:** Extractors are composed as a visible parallel subgraph rather than a dynamic registry.
- **Incremental by default:** Graph updates merge new data with existing data without full rebuild; Phase 3 adds source-level deletion for true incremental refresh.
- **Bounded expansion:** Query expansion is always capped by configurable fan-out limits to prevent retrieval noise.

---

## 8) Key Decisions Captured by the Spec

- ABC-based backend abstraction with a lazy singleton public API, mirroring the guardrails subsystem pattern.
- YAML-defined schema with phase tags governs which entity and edge types are active at runtime.
- Extractors run as parallel subgraph branches whose outputs converge on a merge stage with extractor-priority conflict resolution.
- Entity descriptions follow an append-only mention model with token-budgeted summarisation and top-K mention retention.
- Two-tier query matching: rule-based token-boundary fast path with an optional model-based fallback gated by a timeout.
- Backward-compatibility shim re-exports the legacy module's public names with a deprecation warning during migration.
- Phase tagging in the schema lets the data model evolve from baseline through community-aware retrieval and Phase 3 connectivity/visualization features without breaking earlier deployments.
- Phase 3 introduces source-level deletion (`remove_by_source`) to enable correct incremental updates in `--update` mode.

---

## 9) Acceptance, Evaluation, and Feedback

- **Per-requirement acceptance criteria:** Every functional requirement carries explicit, testable acceptance criteria.
- **System-level acceptance:** The spec defines extraction, query, and persistence performance budgets as numeric criteria.
- **Test framework requirements:** Section 14 mandates contract, regression, integration, schema-validation, merge-node, description, and backward-compatibility test suites.
- **Evaluation plan:** A separate `KNOWLEDGE_GRAPH_EVAL_PLAN.md` defines extraction quality, retrieval quality, and entity-resolution metrics with golden fixtures.
- **Phased acceptance:** Each delivery phase (1, 1b, 2, 3) has its own scoped requirement set whose acceptance criteria gate that phase.

---

## 10) External Dependencies

**Required:**

- A graph computation library for the in-memory backend
- A binary JSON serialization library for graph persistence
- A token-level NLP library for query entity matching
- A workflow/graph orchestration library for the extraction subgraph (shared with the rest of the ingestion pipeline)

**Optional / phase-gated:**

- A zero-shot NER model (when that extractor is enabled)
- A generative model provider via the platform's LLM router (for Phase 1b extraction and Phase 1b query fallback)
- A SystemVerilog grammar parser (Phase 1b)
- A community-detection library (Phase 2)
- An external graph database driver (Phase 2 — full backend implementation)
- An elaboration-level SystemVerilog analyzer for cross-module connectivity (Phase 3)
- A browser-based graph visualization library (Phase 3)
- An embedding model and vector index for entity resolution (Phase 3)

**Downstream contract only:**

- The embedding pipeline (Nodes 10 and 13) consumes the extraction and storage interfaces.
- The retrieval pipeline (Stage 2) consumes the query expander interface.

---

## 11) Companion Documents

| Document | Role |
|----------|------|
| `KNOWLEDGE_GRAPH_SPEC.md` | Authoritative requirements baseline |
| `KNOWLEDGE_GRAPH_SPEC_SUMMARY.md` | This document — requirements digest |
| `KNOWLEDGE_GRAPH_DESIGN.md` | Phase 1 design document (task decomposition, contracts) |
| `KNOWLEDGE_GRAPH_PHASE1B_DESIGN.md` | Phase 1b design document |
| `KNOWLEDGE_GRAPH_PHASE2_DESIGN.md` | Phase 2 design document |
| `KNOWLEDGE_GRAPH_PHASE3_DESIGN.md` | Phase 3 design document |
| `KNOWLEDGE_GRAPH_IMPLEMENTATION.md` | Implementation guide |
| `KNOWLEDGE_GRAPH_ENGINEERING_GUIDE.md` | Engineering guide |
| `KNOWLEDGE_GRAPH_BUILD_PLAN.md` | Build plan and phasing |
| `KNOWLEDGE_GRAPH_TEST_PLAN.md` | Test plan |
| `KNOWLEDGE_GRAPH_EVAL_PLAN.md` | Evaluation plan with golden fixtures and quality metrics |
| `EMBEDDING_PIPELINE_SPEC.md` | Upstream contract for Nodes 10 and 13 |
| `RETRIEVAL_QUERY_SPEC.md` | Downstream contract for Stage 2 query expansion |

---

## 12) Sync Status

Aligned to `KNOWLEDGE_GRAPH_SPEC.md` v1.1.0 as of 2026-04-10.
