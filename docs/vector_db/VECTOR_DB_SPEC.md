# Vector Store Subsystem — Specification

| Field | Value |
|-------|-------|
| **Document type** | Authoritative requirements baseline |
| **Status** | Draft |
| **Version** | v1.0.0 |
| **Last updated** | 2026-04-10 |
| **Companion documents** | `VECTOR_DB_SPEC_SUMMARY.md`, `VECTOR_DB_DESIGN.md`, `VECTOR_DB_IMPLEMENTATION_DOCS.md`, `VECTOR_DB_ENGINEERING_GUIDE.md`, `VECTOR_DB_TEST_DOCS.md` |
| **Upstream consumers** | `EMBEDDING_PIPELINE_SPEC.md` (FR-1200–FR-1299), `VISUAL_EMBEDDING_SPEC.md`, `RETRIEVAL_QUERY_SPEC.md`, `VISUAL_RETRIEVAL_SPEC.md` |

---

## 1) Scope and Definitions

### 1.1 Purpose

The vector store subsystem (`src/vector_db/`) is the persistence and search abstraction layer for all embedding-based retrieval in RagWeave. It defines a stable, backend-agnostic interface that the ingestion and retrieval pipelines use to store document chunks with their vectors, perform hybrid keyword-plus-vector search, manage named collections, and run aggregate queries — without depending on any specific vector database engine.

It exists as a separate subsystem (rather than as inline calls to a vector database client) so that the underlying engine can be swapped via a single configuration key without touching pipeline code, and so that visual page embeddings, text chunk embeddings, and any future embedding modalities all share one persistence boundary.

### 1.2 Glossary

| Term | Definition |
|------|------------|
| **Backend** | A concrete implementation of the `VectorBackend` ABC bound to a specific vector database engine. |
| **Collection** | A named container of vectorised objects within the backend, addressed by string name. |
| **Chunk collection** | A collection holding text chunks with one dense vector per chunk plus rich metadata. |
| **Visual collection** | A collection holding per-document-page visual embeddings under a named vector. |
| **Hybrid search** | A single query that combines keyword (BM25-style) scoring with dense-vector similarity, blended by an `alpha` weight. |
| **Multi-search** | Fan-out of one logical query across multiple collections with parallel execution and cross-collection deduplication. |
| **Source key** | Stable identifier for the upstream document a chunk derives from, used for re-ingestion deletes. |
| **Deterministic chunk ID** | A backend object identifier derived deterministically from the chunk's source, position, and text content. |
| **Persistent client** | A long-lived client handle suitable for server processes; explicit shutdown required. |
| **Ephemeral client** | A short-lived client handle scoped to one operation, opened and closed via context manager. |

### 1.3 In Scope

- An abstract `VectorBackend` contract covering client lifecycle, collection management, document insertion, hybrid search, deletion, aggregation, listing, and visual collection operations.
- A backend-agnostic public API module that pipeline code imports, with config-driven backend selection via a lazy singleton.
- Backend-agnostic data contracts (`DocumentRecord`, `SearchResult`, `SearchFilter`).
- A concrete Weaviate backend implementation including embedded-mode client lifecycle, schema definition, hybrid search, filter translation, aggregation, and deletion.
- A separate visual page collection schema and operations (named-vector storage, similarity search with score thresholding).
- Multi-collection fan-out search with parallel execution, cross-collection deduplication, and ranked truncation.
- Deterministic chunk ID generation for idempotent re-ingestion.
- Tracing instrumentation for all backend operations via the platform observability layer.

### 1.4 Out of Scope

- Embedding generation (handled by the embedding pipeline and embedding model providers).
- Reranking, query planning, prompt assembly, and answer generation (downstream retrieval layer).
- Authentication, authorisation, and tenant policy enforcement beyond a metadata `tenant_id` filter.
- Document parsing, text cleaning, chunking, and metadata extraction (upstream document and embedding pipelines).
- Cross-backend data migration tooling.
- Backup and restore of the underlying engine's persistent storage.
- Operational health checks, autoscaling, and capacity planning.
- Vector index tuning beyond what the chosen backend exposes by default.

### 1.5 Requirement Format

Every requirement carries:

- **ID** of the form `REQ-VDB-xxx`.
- **Priority** keyword from RFC 2119: `MUST`/`SHALL`, `SHOULD`/`RECOMMENDED`, `MAY`/`OPTIONAL`.
- **Description** of the required behaviour.
- **Rationale** explaining why this requirement exists.
- **Acceptance criteria** that are testable.

### 1.6 Assumptions and Constraints

| Assumption | Impact if violated |
|------------|--------------------|
| Pipeline code only imports from `src.vector_db`, never from `src.vector_db.weaviate.*` directly. | Backend swap stops being a config-only change; tight coupling reintroduced. |
| Embeddings are pre-computed by the caller before insertion. | The backend cannot be swapped freely because the engine becomes responsible for vectorisation. |
| All collection-scoped operations accept an optional `collection` argument. | Multi-collection support breaks for any operation that hard-codes the default. |
| Chunk IDs are deterministic for a given (source, chunk_index, text) triple. | Re-ingestion idempotency breaks; duplicate chunks accumulate. |

---

## 2) System Overview

```
                ┌────────────────────────────────────────────┐
                │            src/vector_db/__init__.py       │
                │  (public API — pipelines import this only) │
                └─────────────────┬──────────────────────────┘
                                  │
                                  ▼
                ┌────────────────────────────────────────────┐
                │     _get_vector_backend() lazy singleton   │
                │     dispatches on VECTOR_DB_BACKEND        │
                └─────────────────┬──────────────────────────┘
                                  │
                                  ▼
                ┌────────────────────────────────────────────┐
                │           VectorBackend (ABC)              │
                │   abstract methods for every operation     │
                └─────────────────┬──────────────────────────┘
                                  │
              ┌───────────────────┴────────────────────┐
              │                                        │
              ▼                                        ▼
    ┌───────────────────┐                    ┌───────────────────┐
    │  WeaviateBackend  │                    │  Future backends  │
    │  (concrete impl)  │                    │  (Qdrant, etc.)   │
    └─────────┬─────────┘                    └───────────────────┘
              │
              ▼
    ┌────────────────────────────────────────┐
    │  weaviate/store.py     (chunk store)   │
    │  weaviate/visual_store.py (visual)     │
    └────────────────────────────────────────┘
```

The subsystem is organised into four layers:

1. **Public API** — `src/vector_db/__init__.py` re-exports a stable function set used by all pipeline code. No pipeline module imports anything else from `src.vector_db`.
2. **Backend dispatcher** — A lazy singleton inside the public API constructs the active backend on first use, dispatching on `VECTOR_DB_BACKEND`.
3. **Backend contract** — `src/vector_db/backend.py` defines the `VectorBackend` ABC. Every concrete backend implements this contract.
4. **Backend implementations** — `src/vector_db/weaviate/` contains the Weaviate concrete backend, split into a thin ABC adapter (`weaviate/backend.py`) and the engine-specific operation modules (`weaviate/store.py`, `weaviate/visual_store.py`).

Shared, backend-independent data contracts (`DocumentRecord`, `SearchResult`, `SearchFilter`) live in `src/vector_db/common/schemas.py`.

---

## 3) Functional Requirements

### 3.1 Public API and Backend Selection (REQ-VDB-100 – REQ-VDB-199)

#### REQ-VDB-100 — Stable public API surface (MUST)

**Description.** The module `src/vector_db/__init__.py` MUST export a fixed set of functions that pipeline code uses for all vector store operations: `create_persistent_client`, `get_client`, `close_client`, `ensure_collection`, `delete_collection`, `add_documents`, `delete_by_source`, `delete_by_source_key`, `search`, `multi_search`, `aggregate_by_source`, `get_collection_stats`, `list_collections`, `ensure_visual_collection`, `add_visual_documents`, `delete_visual_by_source_key`, `search_visual`, plus the data contracts `DocumentRecord`, `SearchResult`, `SearchFilter`, and the utility `build_chunk_id`.

**Rationale.** A stable public surface is the precondition for backend swappability. Pipeline code must never reach into backend-specific modules.

**Acceptance criteria.**

- `__all__` in `src/vector_db/__init__.py` enumerates exactly these names.
- No file under `src/ingest/` or `src/retrieval/` imports from `src.vector_db.weaviate.*` or from `src.vector_db.backend`.
- Adding a new backend does not require any change to `src/vector_db/__init__.py` beyond the dispatcher branch.

#### REQ-VDB-101 — Config-driven backend selection (MUST)

**Description.** The active backend MUST be selected at runtime by reading the `VECTOR_DB_BACKEND` configuration key. Selection happens lazily on first use and the resulting backend instance is cached as a process-wide singleton for the lifetime of the process.

**Rationale.** Lazy construction avoids importing backend-specific dependencies in deployments where they are not used. Singleton caching avoids re-instantiation overhead per call.

**Acceptance criteria.**

- The first call to any public API function constructs the backend; subsequent calls reuse the same instance.
- An unknown `VECTOR_DB_BACKEND` value raises `ValueError` with a message listing valid values.
- Importing `src.vector_db` does not import any backend-specific module until a public API function is invoked.

#### REQ-VDB-102 — Default collection resolution (MUST)

**Description.** When a public API function accepts a `collection` parameter and the caller passes `None` (or omits it), the subsystem MUST resolve the collection name to the value of `VECTOR_COLLECTION_DEFAULT`.

**Rationale.** Single-collection callers must not need to know the default name. Multi-collection callers must be able to override it freely.

**Acceptance criteria.**

- `_resolve_collection(None)` returns `VECTOR_COLLECTION_DEFAULT`.
- `_resolve_collection("Foo")` returns `"Foo"` regardless of the default.
- All collection-scoped backend methods receive a non-`None` collection name.

#### REQ-VDB-103 — Backwards-compatible new-backend addition (SHOULD)

**Description.** Adding a new backend implementation SHOULD require only: (a) creating a new package under `src/vector_db/<engine>/`, (b) implementing `VectorBackend`, and (c) adding one branch to `_get_vector_backend()`.

**Rationale.** Keeps the cost of new backends low and prevents architectural drift.

**Acceptance criteria.** The dispatcher in `_get_vector_backend()` is the only file in the public API layer that contains any backend-specific name.

---

### 3.2 Backend Contract (REQ-VDB-200 – REQ-VDB-299)

#### REQ-VDB-200 — Abstract base class (MUST)

**Description.** The module `src/vector_db/backend.py` MUST define a `VectorBackend` ABC that declares every operation the public API layer routes through. All operations except `close_client` MUST be `@abstractmethod`. `close_client` MAY have a default no-op implementation.

**Rationale.** A formal ABC produces an immediate `TypeError` if a backend forgets a method, instead of failing at runtime on the first call.

**Acceptance criteria.**

- Every public API function has a corresponding abstract method on `VectorBackend`.
- Instantiating an incomplete subclass raises `TypeError`.

#### REQ-VDB-201 — Pre-computed embeddings only (MUST)

**Description.** Backend implementations MUST accept pre-computed dense vectors from the caller. They MUST NOT call out to embedding model providers.

**Rationale.** Pinning embedding generation to the embedding pipeline makes embedding-model swaps and bring-your-own-embeddings mode possible.

**Acceptance criteria.** No file in `src/vector_db/` imports any embedding model provider.

#### REQ-VDB-202 — Optional collection parameter on every collection-scoped method (MUST)

**Description.** Every method on `VectorBackend` that operates on a single collection MUST accept an `Optional[str]` `collection` parameter defaulting to `None`. Passing `None` MUST resolve to the backend's configured default.

**Rationale.** Multi-collection support requires that every operation can target a non-default collection.

**Acceptance criteria.** No method on `VectorBackend` hard-codes a collection name.

#### REQ-VDB-203 — Two client lifecycle modes (MUST)

**Description.** `VectorBackend` MUST expose both `create_persistent_client()` and `get_ephemeral_client()`. The persistent variant returns a long-lived handle requiring explicit `close_client()`. The ephemeral variant is a context manager that opens and closes the client per use.

**Rationale.** Server processes amortise the cost of client construction across many queries; CLI scripts and one-shot tasks do not.

**Acceptance criteria.**

- Persistent and ephemeral handles are interchangeable arguments to all other backend methods.
- The ephemeral context manager closes the underlying client on context exit even on exception.

---

### 3.3 Document Operations (REQ-VDB-300 – REQ-VDB-399)

#### REQ-VDB-300 — Insert documents with pre-computed embeddings (MUST)

**Description.** `add_documents(client, documents, collection)` MUST insert each `DocumentRecord` into the named collection along with its embedding and metadata. The function MUST return the count of inserted documents.

**Rationale.** Inserting in batches is the dominant ingestion-throughput operation and the count is needed for progress reporting.

**Acceptance criteria.**

- Each inserted object's vector equals the `DocumentRecord.embedding` provided.
- Metadata fields are preserved on the stored object so they are returned by subsequent searches.
- Empty input returns `0` and performs no backend call.

#### REQ-VDB-301 — Deterministic chunk identifiers (MUST)

**Description.** `build_chunk_id(source, chunk_index, text)` MUST return a stable UUID-formatted string derived from the SHA-256 of `f"{source}:{chunk_index}:{sha256(text)}"` via `uuid.uuid5(NAMESPACE_URL, payload)`. The same triple MUST always produce the same ID; any change in source, chunk index, or text MUST produce a different ID.

**Rationale.** Deterministic IDs make re-ingestion idempotent: re-adding the same chunk replaces the same object instead of producing a duplicate.

**Acceptance criteria.**

- Two calls with the same inputs return the same string.
- Calls differing in any input field return different strings.
- The returned value parses as a valid UUID.

#### REQ-VDB-302 — Caller-supplied chunk_id override (MUST)

**Description.** When a `DocumentRecord.metadata` dict contains a `chunk_id` value, the backend MUST use it as the object identifier (after normalising it to a UUID, generating a deterministic UUID5 if it is not already a UUID). When `chunk_id` is absent, the backend MUST fall back to `build_chunk_id` using the metadata's `source_key` (or `source`), `chunk_index`, and the chunk text.

**Rationale.** Lets upstream systems supply external IDs while preserving idempotency for callers that do not.

**Acceptance criteria.** Inserting the same record twice with the same `chunk_id` produces a single stored object.

#### REQ-VDB-303 — Delete by legacy source path (MUST)

**Description.** `delete_by_source(client, source, collection)` MUST delete all objects in the named collection whose `source` metadata property equals `source`. The function MUST return the count of deleted objects.

**Rationale.** Legacy callers identify documents by the `source` field; this entry point preserves their behaviour.

**Acceptance criteria.** The returned count equals the number of objects whose `source` matched.

#### REQ-VDB-304 — Delete by stable source key with legacy fallback (MUST)

**Description.** `delete_by_source_key(client, source_key, legacy_source, collection)` MUST first attempt to delete all objects whose `source_key` metadata property equals `source_key`. If that operation raises (for example because the property does not exist on older objects), and `legacy_source` is provided, the implementation MUST retry the delete using the `source` property and the `legacy_source` value. When `legacy_source` is `None` and the first attempt fails, the function MUST return `0`.

**Rationale.** During the migration from `source` to `source_key`, both schemas coexist. The fallback prevents re-ingestion failures on collections that contain pre-migration objects.

**Acceptance criteria.**

- A normal delete by `source_key` returns the matched count.
- An exception during the `source_key` delete falls back to `source = legacy_source` when `legacy_source` is provided.
- The function never raises through to the caller in the fallback path.

---

### 3.4 Search (REQ-VDB-400 – REQ-VDB-499)

#### REQ-VDB-400 — Hybrid search on a single collection (MUST)

**Description.** `search(client, query, query_embedding, alpha, limit, filters, collection)` MUST perform a hybrid keyword-plus-vector search against the named collection and return up to `limit` results sorted by descending score. The `alpha` parameter MUST blend keyword (`alpha=0.0`) and vector (`alpha=1.0`) scores. The function MUST return a list of `SearchResult` objects.

**Rationale.** Hybrid search outperforms either modality in isolation across diverse query types.

**Acceptance criteria.**

- Setting `alpha=0` is equivalent to a pure keyword search; `alpha=1` is equivalent to a pure vector search.
- Each `SearchResult` carries the populated `text`, `score`, `metadata`, and `collection` fields.
- The result count is `min(limit, available_matches)`.

#### REQ-VDB-401 — AND-combined metadata filters (MUST)

**Description.** When `filters` is a non-empty list, the backend MUST translate each `SearchFilter` to its native filter representation and combine all clauses with an AND. Each filter clause is `(property, operator, value)` where supported operators are `eq`, `ne`, `gt`, `lt`, `gte`, `lte`, and `like`.

**Rationale.** Metadata filters scope retrieval to specific document subsets without requiring per-tenant collections.

**Acceptance criteria.**

- A single filter behaves as the equivalent native query.
- Multiple filters return only objects matching every clause.
- An unsupported operator raises `ValueError` listing the valid operators.

#### REQ-VDB-402 — Multi-collection fan-out search (MUST)

**Description.** `multi_search(client, query, query_embedding, alpha, limit, collections, filters)` MUST issue one search per collection in `collections` in parallel, then combine results into a single ranked list. Cross-collection duplicates MUST be deduplicated using `object_id` when present, otherwise by raw text. The deduplication policy MUST keep the highest-scoring instance of each duplicate. The final list MUST be sorted by descending score and truncated to `limit`.

**Rationale.** Multi-tenant or multi-source deployments split data across collections; users still expect one ranked answer set.

**Acceptance criteria.**

- An empty or `None` `collections` argument falls back to a single search on the default collection.
- Per-collection failures are logged but do not stop the fan-out — surviving collections still contribute results.
- The returned list contains no two results that share the same dedupe key.

---

### 3.5 Visual Collection Operations (REQ-VDB-500 – REQ-VDB-599)

#### REQ-VDB-500 — Visual collection schema (MUST)

**Description.** `ensure_visual_collection(client, collection)` MUST create a collection (idempotently) configured for per-page visual embeddings, with: a single 128-dimensional named vector, an HNSW index, cosine distance, and the property set defined in REQ-VDB-501.

**Rationale.** Visual page retrieval has a different schema, dimensionality, and query model than text chunk retrieval. A separate collection isolates the two without forcing one schema on both.

**Acceptance criteria.**

- Calling on a collection that already exists is a no-op.
- The created collection has exactly one named vector and the configured property set.

#### REQ-VDB-501 — Visual collection properties (MUST)

**Description.** The visual collection schema MUST include the following properties: `document_id` (text), `page_number` (int), `source_key` (text), `source_uri` (text), `source_name` (text), `tenant_id` (text), `total_pages` (int), `page_width_px` (int), `page_height_px` (int), `minio_key` (text), and `patch_vectors` (text, vectorisation skipped). The vectorizer for the named vector MUST be configured as `none` so embeddings are accepted from the caller.

**Rationale.** These properties cover citation rendering, tenant scoping, page geometry, and patch-vector stash needed by downstream consumers.

**Acceptance criteria.** Inspecting the created collection lists every property at the documented type with the documented vectorisation flag.

#### REQ-VDB-502 — Insert visual page documents (MUST)

**Description.** `add_visual_documents(client, documents, collection)` MUST batch-insert visual page records, mapping the `mean_vector` key on each input dict to the named vector slot and storing the remaining keys as object properties. The function MUST return the count of successfully inserted objects.

**Rationale.** Batch inserts amortise per-object overhead; named-vector mapping is engine-specific and must not leak into the caller.

**Acceptance criteria.** Each inserted object has its `mean_vector` accessible under the named vector slot and every other input key as a property.

#### REQ-VDB-503 — Visual similarity search with score thresholding (MUST)

**Description.** `search_visual(client, query_vector, limit, score_threshold, tenant_id, collection)` MUST execute a near-vector query on the named vector using cosine distance, convert distance to similarity (`score = 1 - distance`), exclude any result with `score < score_threshold`, and return up to `limit` results sorted by descending score. When `tenant_id` is provided, the query MUST be filtered to objects whose `tenant_id` property equals it. The `patch_vectors` property MUST NOT be returned in the result dicts.

**Rationale.** Score thresholding prevents low-quality matches from polluting visual retrieval; tenant filtering enforces isolation; excluding `patch_vectors` keeps the response payload small.

**Acceptance criteria.**

- A query with `score_threshold=0` returns all `limit` nearest neighbours.
- A query with `tenant_id="X"` returns only objects whose `tenant_id` property equals `"X"`.
- No returned dict contains a `patch_vectors` key.

#### REQ-VDB-504 — Delete visual by source key (MUST)

**Description.** `delete_visual_by_source_key(client, source_key, collection)` MUST delete all visual page objects whose `source_key` property equals `source_key` and return the count deleted.

**Rationale.** Re-ingestion of a document must atomically remove its prior visual embeddings before the new ones land.

**Acceptance criteria.** A subsequent `search_visual` call returns no results carrying the deleted `source_key`.

---

### 3.6 Aggregation, Listing, and Stats (REQ-VDB-600 – REQ-VDB-699)

#### REQ-VDB-600 — Aggregate chunk counts by source (MUST)

**Description.** `aggregate_by_source(client, collection, source_filter, connector_filter)` MUST return a list of dicts, one per distinct `source_key`, each containing `source_key`, `source`, `connector`, and `chunk_count`. When `source_filter` is provided, results MUST be limited to sources whose `source` field matches a pattern containing `source_filter`. When `connector_filter` is provided, results MUST be limited to objects whose `connector` field equals it. The implementation MUST use the engine's group-by aggregate primitive — never iterate every object.

**Rationale.** Source-level summaries drive the CLI inventory views and re-ingestion planning; full enumeration is too expensive at production sizes.

**Acceptance criteria.** Result count equals the number of distinct `source_key` values matching the filter combination.

#### REQ-VDB-601 — Single-collection statistics (MUST)

**Description.** `get_collection_stats(client, collection)` MUST return a dict containing `chunk_count`, `document_count`, and `connector_breakdown` (a mapping from connector name to count). When the collection does not exist, the function MUST return `None` rather than raising.

**Rationale.** UI inventory views need a quick view of the collection without enumerating chunks. Returning `None` simplifies the missing-collection path.

**Acceptance criteria.** Stats for a populated collection are non-zero; stats for a missing collection return `None`.

#### REQ-VDB-602 — List all collections (MUST)

**Description.** `list_collections(client)` MUST return one entry per existing collection in the active backend, each entry containing `collection_name` and `chunk_count`.

**Rationale.** Multi-collection deployments need a discovery surface that does not depend on out-of-band knowledge.

**Acceptance criteria.** Every collection visible to the client appears in the result; the chunk count for each matches `get_collection_stats(...).chunk_count`.

---

### 3.7 Lifecycle (REQ-VDB-700 – REQ-VDB-799)

#### REQ-VDB-700 — Idempotent collection creation (MUST)

**Description.** `ensure_collection(client, collection)` MUST create the collection if it does not exist and return without error when it does. The implementation MUST NOT delete or rebuild an existing collection.

**Rationale.** Pipelines call `ensure_collection` on every run; the operation must be safe to repeat.

**Acceptance criteria.** Calling `ensure_collection` twice in a row results in exactly one collection-creation call against the backend.

#### REQ-VDB-701 — Collection deletion (MUST)

**Description.** `delete_collection(client, collection)` MUST drop the entire named collection. Calling on a non-existent collection MUST be a no-op rather than raising.

**Rationale.** Reset and test workflows need a single safe entry point.

**Acceptance criteria.** Subsequent `list_collections` does not include the deleted collection.

#### REQ-VDB-702 — Persistent client teardown (MUST)

**Description.** `close_client(client)` MUST cleanly release any resources held by a persistent client. The default ABC implementation MAY be a no-op; backends with explicit shutdown semantics MUST override it. Errors during teardown MUST be logged at debug level and not propagate.

**Rationale.** Shutdown errors should never crash a long-running server process; teardown must be best-effort.

**Acceptance criteria.** A second `close_client` on the same handle does not raise.

---

### 3.8 Filter Translation (REQ-VDB-800 – REQ-VDB-899)

#### REQ-VDB-800 — Operator coverage (MUST)

**Description.** Concrete backends MUST translate every supported `SearchFilter.operator` value (`eq`, `ne`, `gt`, `lt`, `gte`, `lte`, `like`) into a native filter clause. Operator names MUST be matched case-insensitively. An unsupported operator MUST raise `ValueError` listing the valid operators.

**Rationale.** Pipeline code depends on a consistent operator vocabulary regardless of backend.

**Acceptance criteria.** Every supported operator passes a round-trip test; an unknown operator raises with a clear message.

#### REQ-VDB-801 — Multi-clause AND combination (MUST)

**Description.** When multiple `SearchFilter` instances are passed, the backend MUST combine them with a logical AND in the order received.

**Rationale.** Predictable composition allows callers to reason about filter sets without backend-specific tricks.

**Acceptance criteria.** A two-filter query returns only objects matching both clauses.

---

### 3.9 Schemas (REQ-VDB-900 – REQ-VDB-999)

#### REQ-VDB-900 — Backend-independent data contracts (MUST)

**Description.** The module `src/vector_db/common/schemas.py` MUST define `DocumentRecord`, `SearchResult`, and `SearchFilter` with the field shapes documented in §3.10. These types MUST NOT import from any backend-specific module.

**Rationale.** Shared contracts are the type-level guarantee that backends are interchangeable.

**Acceptance criteria.** No file in `common/` imports `weaviate` or any other engine library.

#### REQ-VDB-901 — DocumentRecord shape (MUST)

```python
@dataclass
class DocumentRecord:
    text: str
    embedding: list[float]
    metadata: dict[str, Any]
```

#### REQ-VDB-902 — SearchResult shape (MUST)

```python
@dataclass
class SearchResult:
    text: str
    score: float
    metadata: dict[str, Any]
    object_id: Optional[str] = None
    collection: Optional[str] = None
```

The `collection` field MUST be populated by the backend with the resolved collection name so `multi_search` consumers can attribute each result.

#### REQ-VDB-903 — SearchFilter shape (MUST)

```python
@dataclass
class SearchFilter:
    property: str
    operator: str  # eq | ne | gt | lt | gte | lte | like
    value: Any
```

---

### 3.10 Observability (REQ-VDB-950 – REQ-VDB-999)

#### REQ-VDB-950 — Tracing on every backend operation (MUST)

**Description.** Every backend operation that calls into the underlying engine MUST open a tracing span via the platform observability layer with a stable span name and attributes covering the collection name and any operation-specific count or limit. Each span MUST be ended in both success and failure paths.

**Rationale.** Vector store operations are the dominant tail-latency contributor in retrieval; without tracing they are invisible.

**Acceptance criteria.** A single ingestion + retrieval round trip emits at least one span per called operation.

---

## 4) Non-Functional Requirements

### REQ-VDB-1000 — Backend-swap is config-only (MUST)

Switching `VECTOR_DB_BACKEND` from one valid value to another MUST require zero source code edits in any consumer of `src.vector_db`.

### REQ-VDB-1001 — Lazy backend imports (MUST)

Importing `src.vector_db` MUST NOT import any backend-specific dependency. This is verified by importing the module in an environment where the backend client library is uninstalled and confirming no `ImportError` occurs at import time.

### REQ-VDB-1002 — Multi-search parallelism (SHOULD)

`multi_search` SHOULD execute its per-collection searches concurrently using a thread pool sized to the number of collections, so end-to-end latency approximates the slowest single search rather than their sum.

### REQ-VDB-1003 — Aggregation avoids full scans (MUST)

`aggregate_by_source`, `get_collection_stats`, and `list_collections` MUST use the backend's native aggregation primitives. They MUST NOT iterate every object.

### REQ-VDB-1004 — Idempotent re-ingestion (MUST)

Re-inserting the same document (same source, same chunks) twice MUST result in the same number of stored objects after the second pass as after the first, with the same identifiers. This requirement is satisfied jointly by REQ-VDB-301 (deterministic IDs) and the upstream embedding pipeline's delete-and-reinsert flow.

---

## 5) Testing Requirements (REQ-VDB-1100 – REQ-VDB-1199)

### REQ-VDB-1100 — Deterministic chunk ID test (MUST)

A unit test MUST verify that `build_chunk_id` returns the same value for identical inputs and different values for any one differing input. (Currently satisfied by `tests/test_vector_store_integration.py::test_chunk_id_is_deterministic`.)

### REQ-VDB-1101 — ABC contract tests (SHOULD)

A parameterised test suite SHOULD exercise every public API function against every concrete backend, asserting the public contract is preserved. This becomes mandatory once a second backend exists.

### REQ-VDB-1102 — Filter translation tests (MUST)

A unit test MUST verify that every supported operator in `SearchFilter` translates to the expected native filter clause and that an unknown operator raises `ValueError`.

### REQ-VDB-1103 — Multi-search dedup test (MUST)

A unit test MUST verify that `multi_search` keeps the highest-scoring instance of each duplicate, attributes results to their source collection, and survives a per-collection exception by returning results from the surviving collections.

### REQ-VDB-1104 — Visual collection round-trip test (SHOULD)

An integration test SHOULD insert a small batch of visual page records, run `search_visual`, and verify that results respect the score threshold, exclude `patch_vectors`, and apply the tenant filter.

---

## 6) External Dependencies

**Required:**

- A vector database engine reachable through the configured backend.
- The platform observability layer (`src.platform.observability`) for tracing spans.

**Optional / phase-gated:**

- The `weaviate-client` Python library (for the Weaviate backend only). Not imported unless `VECTOR_DB_BACKEND="weaviate"`.

**Downstream contract only:**

- The embedding pipeline writes through the public API.
- The retrieval pipeline reads through the public API.
- The visual embedding and visual retrieval pipelines use the visual collection operations through the public API.

---

## Appendix A — Open Questions

| Question | Notes |
|----------|-------|
| Is a second backend (e.g., Qdrant, Milvus) on the roadmap? | If yes, REQ-VDB-1101 should be promoted from SHOULD to MUST. |
| Should `multi_search` expose a per-collection `limit` instead of a global `limit`? | Current behaviour: each fan-out search uses `limit` then the merged set is truncated to `limit`. |
| Should aggregation expose tenant-scoped variants? | Currently tenant scoping is achievable through `source_filter` but not first-class. |
