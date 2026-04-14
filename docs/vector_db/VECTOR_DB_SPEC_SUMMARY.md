## 1) Generic System Overview

<!-- SCRAPEABLE SECTION — must be tech-agnostic. No FR-IDs, no technology names, no file names, no threshold values. Written from scratch. 250–450 words across all five sub-sections. -->

### Purpose

The vector store subsystem is the persistence and search abstraction beneath every embedding-based retrieval flow in the platform. It defines a stable, engine-agnostic interface that ingestion writes through and retrieval reads through, so that the underlying vector database can be replaced without touching either pipeline. Without it, every pipeline would be coupled to one vector engine and embedding modalities (text chunks, document pages) would each invent their own persistence path.

### How It Works

The subsystem is layered. A public interface module exposes a fixed function set covering client lifecycle, collection management, document insertion, hybrid keyword-plus-vector search, multi-collection fan-out, deletion by source, aggregation, statistics, and a separate set of operations for visual page collections. A lazy dispatcher inside the interface module reads a backend-selection setting and constructs the active backend on first call, caching it for the process lifetime. An abstract backend contract defines every operation as an abstract method; concrete backends implement that contract by translating each call into engine-specific operations. Backend-independent data contracts describe the input record, the search result, and the metadata filter clause — these are the only types pipeline code ever sees. Single-collection callers omit the collection parameter and the dispatcher resolves the configured default; multi-collection callers pass an explicit name. A fan-out search runs one query per collection in parallel, deduplicates by object identity (preferring the higher-scoring instance), and returns one ranked list. Visual page collections use a separate schema with a named vector and similarity-with-threshold scoring.

### Tunable Knobs

Operators select which backend is active and which collection name is the default for unscoped calls. The hybrid search blend between keyword and vector scoring is set per call, as are result limits and metadata filter clauses. Visual search exposes a similarity threshold below which results are dropped and an optional tenant filter. Persistent and ephemeral client modes let callers choose between long-lived server connections and short-lived per-operation handles.

### Design Rationale

A formal abstract backend contract is the single source of truth for what every backend must do, so backend swaps are a configuration change rather than a refactor. Backend-independent data contracts prevent engine-specific types from leaking into pipeline code. Visual and chunk collections live behind the same interface but with separate schemas, because their dimensionality and query model differ. Aggregation primitives are required to use the engine's native group-by — full enumeration is rejected as too expensive at production sizes. Multi-collection search runs in parallel because end-to-end latency must approximate the slowest single search, not their sum.

### Boundary Semantics

Entry: a public interface call carrying a client handle, optional collection name, and operation-specific arguments. Exit: structured results, counts, or stats. Persistent state lives in the underlying engine; the subsystem owns no state other than the cached backend singleton. Responsibility ends once the backend operation completes — embedding generation, query rewriting, reranking, and answer synthesis are all out of scope.

---

# Vector Store Subsystem — Specification Summary

**Companion document to:** `VECTOR_DB_SPEC.md` (v1.0.0, Draft)
**Purpose:** Requirements-level digest for stakeholders, reviewers, and implementers.
**See also:** `VECTOR_DB_DESIGN.md`, `VECTOR_DB_IMPLEMENTATION_DOCS.md`, `VECTOR_DB_ENGINEERING_GUIDE.md`, `VECTOR_DB_TEST_DOCS.md`, `EMBEDDING_PIPELINE_SPEC.md`, `VISUAL_EMBEDDING_SPEC.md`

---

## 2) Scope and Boundaries

**Entry points:**

- **Ingestion (text):** The embedding pipeline calls the public API to insert chunks with pre-computed embeddings.
- **Ingestion (visual):** The visual embedding pipeline calls the visual collection operations to insert per-page visual records.
- **Retrieval (text):** The retrieval pipeline calls hybrid `search` and `multi_search` to fetch candidate chunks.
- **Retrieval (visual):** The visual retrieval pipeline calls `search_visual` to fetch candidate pages.
- **Operational tools:** CLI inventory and inspection commands call `aggregate_by_source`, `get_collection_stats`, and `list_collections`.

**Exit points:**

- Persisted vectors with metadata in the configured vector database.
- Ranked search results returned to ingestion/retrieval callers.
- Aggregate counts and collection statistics returned to operational tools.

### In scope

- Abstract `VectorBackend` ABC defining every required operation
- Public API module (`src/vector_db/__init__.py`) with stable export surface
- Lazy singleton backend dispatcher driven by `VECTOR_DB_BACKEND`
- Backend-independent data contracts: `DocumentRecord`, `SearchResult`, `SearchFilter`
- Concrete `WeaviateBackend` implementation with thin ABC adapter and engine-specific operation modules
- Chunk collection schema, hybrid search, and source-keyed deletion
- Visual page collection schema (named vector, HNSW, cosine), batch insert, similarity search with threshold
- Multi-collection fan-out with parallel execution and cross-collection deduplication
- Deterministic chunk ID generation (`build_chunk_id`)
- Native group-by aggregation, single-collection statistics, and collection enumeration
- Persistent and ephemeral client lifecycle modes
- Filter operator translation (`eq`, `ne`, `gt`, `lt`, `gte`, `lte`, `like`)
- Tracing spans on every backend operation via the platform observability layer

### Out of scope

- Embedding generation (handled by the embedding pipeline and embedding model providers)
- Reranking, query planning, prompt assembly, and answer generation
- Authentication, authorisation, and tenant policy enforcement beyond a metadata `tenant_id` filter
- Document parsing, text cleaning, chunking, and metadata extraction
- Cross-backend data migration tooling
- Backup and restore of the underlying engine's persistent storage
- Operational health checks, autoscaling, and capacity planning
- Vector index tuning beyond what the chosen backend exposes by default

---

## 3) Architecture / Pipeline Overview

```
        [Pipeline code: ingestion / retrieval / CLI]
                          │
                          ▼
            ┌─────────────────────────────┐
            │  src/vector_db/__init__.py  │
            │      (public API)           │
            └──────────────┬──────────────┘
                           │
                           ▼
            ┌─────────────────────────────┐
            │  Lazy backend dispatcher    │
            │  (VECTOR_DB_BACKEND switch) │
            └──────────────┬──────────────┘
                           │
                           ▼
            ┌─────────────────────────────┐
            │   VectorBackend (ABC)       │
            └──────────────┬──────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
    ┌───────────────────┐     ┌───────────────────┐
    │  WeaviateBackend  │     │  Future backends  │
    │  (concrete impl)  │     │   (Qdrant, …)     │
    └─────────┬─────────┘     └───────────────────┘
              │
              ▼
    ┌────────────────────────────────────┐
    │  weaviate/store.py    (chunks)     │
    │  weaviate/visual_store.py (pages)  │
    └────────────────────────────────────┘
```

The public API is the only import path for pipeline code. The dispatcher is the only place that names a backend implementation. Concrete backends are thin adapters: they translate ABC calls into engine-specific helpers. Schemas live in `common/` and have no engine imports.

---

## 4) Requirement Framework

The spec uses a formal requirement framework with the following structural elements:

- **ID convention:** `REQ-VDB-xxx` for all requirements.
- **Priority keywords:** RFC 2119 (`MUST`/`SHALL`, `SHOULD`/`RECOMMENDED`, `MAY`/`OPTIONAL`).
- **Per-requirement structure:** Description, Rationale, Acceptance Criteria.
- **Glossary:** Terminology table in §1.2 of the spec.
- **Assumptions and constraints:** Tabulated in §1.6 with explicit impact-if-violated notes.

---

## 5) Functional Requirement Domains

The functional requirements cover the public API contract, the abstract backend, and each operational area.

- **Public API and Backend Selection** (`REQ-VDB-100`–`REQ-VDB-199`)
- **Backend Contract (ABC)** (`REQ-VDB-200`–`REQ-VDB-299`)
- **Document Operations** (`REQ-VDB-300`–`REQ-VDB-399`)
- **Search** (`REQ-VDB-400`–`REQ-VDB-499`)
- **Visual Collection Operations** (`REQ-VDB-500`–`REQ-VDB-599`)
- **Aggregation, Listing, Stats** (`REQ-VDB-600`–`REQ-VDB-699`)
- **Lifecycle** (`REQ-VDB-700`–`REQ-VDB-799`)
- **Filter Translation** (`REQ-VDB-800`–`REQ-VDB-899`)
- **Schemas** (`REQ-VDB-900`–`REQ-VDB-949`)
- **Observability** (`REQ-VDB-950`–`REQ-VDB-999`)

---

## 6) Non-Functional and Security Themes

### Non-functional areas (`REQ-VDB-1000`–`REQ-VDB-1099`)

- **Backend-swap surface:** Switching backends is config-only with zero source edits in consumers.
- **Lazy imports:** Importing the public API module never imports any engine-specific dependency until first use.
- **Multi-search parallelism:** Per-collection searches execute concurrently so end-to-end latency approximates the slowest single search.
- **Aggregation efficiency:** Aggregation, statistics, and listing operations use native group-by primitives — no full scans.
- **Re-ingestion idempotency:** Deterministic chunk IDs combined with the upstream delete-and-reinsert flow guarantee idempotent re-ingestion.

### Testing requirements (`REQ-VDB-1100`–`REQ-VDB-1199`)

- Deterministic chunk ID test (currently satisfied)
- ABC contract tests parameterised across all concrete backends (mandatory once a second backend exists)
- Filter translation operator coverage tests
- Multi-search deduplication and per-collection-failure tests
- Visual collection round-trip integration test

The spec does not define a standalone security/compliance requirement family; tenant scoping is achieved through metadata filters at search time and is the responsibility of the calling pipeline.

---

## 7) Design Principles

- **ABC contract as the single source of truth:** Every backend implements one formal interface; consumers depend only on the public API.
- **Lazy, config-driven backend selection:** Backend-specific imports never load until a public API call needs them.
- **Backend-independent data contracts:** Engine types never cross the public API boundary.
- **Idempotency by construction:** Chunk identifiers derive from content so re-ingestion of unchanged data is safe.
- **Native aggregation only:** Aggregation, stats, and listing must use the engine's group-by primitives, never full enumeration.
- **Two client modes, one contract:** Persistent and ephemeral clients are interchangeable arguments to every other backend method.
- **Visual and chunk collections share interface, not schema:** One subsystem, two collection shapes — separated by named vectors and operation surface.

---

## 8) Key Decisions Captured by the Spec

- **ABC-based backend abstraction with a lazy singleton public API,** mirroring the knowledge graph subsystem pattern.
- **Pre-computed embeddings only:** Backends never call out to embedding model providers — the embedding pipeline owns vector generation, enabling bring-your-own-embeddings mode end-to-end.
- **Deterministic chunk IDs from a content hash** with a caller-supplied override, so re-ingestion of unchanged chunks is a no-op and externally identified records remain stable.
- **Delete-by-source-key with legacy fallback:** During the migration from `source` to `source_key` both schemas coexist, and the fallback prevents re-ingestion failures on pre-migration objects.
- **Multi-search fan-out with parallel execution and cross-collection dedup:** Highest-scoring instance wins; per-collection failures are logged and skipped, never fatal.
- **Visual collection as a sibling, not a fork:** A separate schema with a named vector and similarity-threshold scoring lives behind the same `VectorBackend` interface.
- **Aggregation must use native group-by:** Full enumeration is explicitly rejected.
- **Hybrid search blend is per-call:** No global default — every call sets `alpha` so different query types can be tuned independently.

---

## 9) Acceptance, Evaluation, and Feedback

- **Per-requirement acceptance criteria:** Every functional requirement carries explicit, testable acceptance criteria.
- **Backend-swap acceptance:** A consumer recompile-free swap of the backend (config change only) is the system-level acceptance bar for the contract.
- **Re-ingestion correctness:** The spec defines acceptance criteria for deterministic chunk IDs and source-keyed delete behaviour.
- **Test framework requirements:** §5 mandates determinism tests, ABC contract tests, filter translation tests, multi-search dedup tests, and a visual round-trip integration test.

---

## 10) External Dependencies

**Required:**

- A vector database engine reachable through the configured backend
- The platform observability layer (for tracing spans)

**Optional / engine-gated:**

- The Weaviate Python client (only when the Weaviate backend is active)

**Downstream contract only:**

- The embedding pipeline writes through the public API
- The retrieval pipeline reads through the public API
- The visual embedding and visual retrieval pipelines use the visual collection operations through the public API

---

## 11) Companion Documents

| Document | Role |
|----------|------|
| `VECTOR_DB_SPEC.md` | Authoritative requirements baseline (`REQ-VDB-100`–`REQ-VDB-1199`) |
| `VECTOR_DB_SPEC_SUMMARY.md` | This document — requirements digest |
| `VECTOR_DB_DESIGN.md` | Design document — architecture, contracts, key decisions |
| `VECTOR_DB_IMPLEMENTATION_DOCS.md` | Implementation guide — module layout and build sequence |
| `VECTOR_DB_ENGINEERING_GUIDE.md` | Post-implementation engineering reference |
| `VECTOR_DB_TEST_DOCS.md` | Test plan and coverage map |
| `EMBEDDING_PIPELINE_SPEC.md` | Upstream consumer of `add_documents` and `delete_by_source_key` |
| `VISUAL_EMBEDDING_SPEC.md` | Upstream consumer of `add_visual_documents` |
| `RETRIEVAL_QUERY_SPEC.md` | Downstream consumer of `search` and `multi_search` |
| `VISUAL_RETRIEVAL_SPEC.md` | Downstream consumer of `search_visual` |

---

## 12) Sync Status

Aligned to `VECTOR_DB_SPEC.md` v1.0.0 as of 2026-04-10.
