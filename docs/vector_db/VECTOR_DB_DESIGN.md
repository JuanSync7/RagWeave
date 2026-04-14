# Vector Store Subsystem — Design Document

| Field | Value |
|-------|-------|
| **Document type** | Design (architecture, contracts, decisions) |
| **Status** | Draft |
| **Version** | v1.0.0 |
| **Last updated** | 2026-04-10 |
| **Companion documents** | `VECTOR_DB_SPEC.md`, `VECTOR_DB_SPEC_SUMMARY.md`, `VECTOR_DB_IMPLEMENTATION_DOCS.md`, `VECTOR_DB_ENGINEERING_GUIDE.md` |

---

## 1) Goals and Non-Goals

### Goals

- **G1.** Provide a backend-agnostic persistence and search interface for all embedding-based retrieval in the platform.
- **G2.** Make backend swaps a one-line configuration change with zero source edits in any consumer.
- **G3.** Support two distinct collection shapes — text chunk and visual page — under one interface.
- **G4.** Enable parallel multi-collection search with cross-collection deduplication.
- **G5.** Guarantee idempotent re-ingestion through deterministic, content-derived chunk identifiers.
- **G6.** Instrument every backend operation for tracing without coupling consumers to the observability layer.

### Non-goals

- Generating embeddings (owned by the embedding pipeline).
- Reranking, query rewriting, or answer synthesis (owned by retrieval).
- Replacing the calling pipeline's responsibility for tenant scoping.
- Tooling for cross-backend data migration.

---

## 2) Architecture

### 2.1 Layer model

```
┌──────────────────────────────────────────────────────┐
│ Layer 1 — Public API (src/vector_db/__init__.py)     │
│   • Stable function set                              │
│   • Lazy backend dispatcher                          │
│   • Default-collection resolution                    │
│   • Multi-collection fan-out + dedup                 │
└──────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────┐
│ Layer 2 — Backend Contract (backend.py)              │
│   • VectorBackend ABC                                │
│   • Abstract methods only (close_client default no-op)│
└──────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────┐
│ Layer 3 — Concrete backend (weaviate/backend.py)     │
│   • Thin adapter — no business logic                 │
│   • SearchFilter → engine filter translation         │
│   • Maps DocumentRecord → engine input               │
└──────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────┐
│ Layer 4 — Engine helpers (weaviate/store.py,         │
│           weaviate/visual_store.py)                  │
│   • Engine-specific operations                       │
│   • Connection, schema, CRUD, search, aggregation    │
│   • Tracing spans                                    │
└──────────────────────────────────────────────────────┘

Sidecar: src/vector_db/common/schemas.py
   • DocumentRecord, SearchResult, SearchFilter
   • Zero engine imports — pure dataclasses
```

### 2.2 Why four layers and not two

A naive two-layer design (public API → engine helpers) was rejected because it conflates two concerns:

1. **Contract** — what every backend must do.
2. **Adaptation** — how one specific engine does it.

Folding both into the same module makes adding a second backend a refactor instead of an addition. Splitting them lets the ABC sit at the boundary of the type system: a partial backend implementation produces an immediate `TypeError` rather than a runtime failure on the first call.

The separation between Layer 3 (concrete backend) and Layer 4 (engine helpers) is also intentional. Layer 3 is the contract adapter. Layer 4 is engine plumbing (connection, schema, CRUD, tracing). Splitting them keeps Layer 3 small enough to scan in one screen and lets Layer 4 evolve (e.g., new search modes) without changing the contract surface.

### 2.3 Module map

| Module | Layer | Lines | Role |
|--------|-------|-------|------|
| `src/vector_db/__init__.py` | 1 | ~440 | Public API + dispatcher + multi_search |
| `src/vector_db/backend.py` | 2 | ~220 | `VectorBackend` ABC |
| `src/vector_db/common/schemas.py` | sidecar | ~75 | Backend-independent dataclasses |
| `src/vector_db/weaviate/backend.py` | 3 | ~240 | `WeaviateBackend` adapter |
| `src/vector_db/weaviate/store.py` | 4 | ~440 | Chunk store engine helpers |
| `src/vector_db/weaviate/visual_store.py` | 4 | ~250 | Visual store engine helpers |

---

## 3) Key Design Decisions

### D1. ABC over duck typing

**Decision.** Use an `abc.ABC` subclass with `@abstractmethod` decorations rather than relying on duck typing.

**Why.** Static guarantees: instantiating an incomplete backend raises `TypeError` at construction time, not on the first method call. The ABC also serves as machine-checkable documentation of what every backend must do.

**Alternative considered.** A `Protocol` from `typing`. Rejected because protocols are checked only by static type checkers; an incomplete implementation still constructs successfully at runtime.

### D2. Lazy singleton dispatcher inside the public API

**Decision.** The dispatcher (`_get_vector_backend`) lives inside `__init__.py` as a lazy module-level singleton. Backend modules are imported only on first call.

**Why.** Importing `src.vector_db` must not pull in the Weaviate client (or any other engine library) — deployments that disable a backend should not need to install its dependencies. Lazy import inside the dispatcher achieves this without an import-time cost.

**Alternative considered.** A factory module (`backends/factory.py`) with explicit registration. Rejected because it pushes one extra layer of indirection without solving the import-time problem and complicates the call site.

### D3. Default collection resolved at the boundary

**Decision.** When a public API call passes `collection=None`, the public API layer resolves it to `VECTOR_COLLECTION_DEFAULT` and forwards the resolved name to the backend. Backends still accept `None` for compatibility but consumers should never see it.

**Why.** Centralising the default in one place avoids backend-by-backend default drift and makes test setups predictable.

### D4. Backend-independent data contracts

**Decision.** `DocumentRecord`, `SearchResult`, and `SearchFilter` are pure dataclasses in `common/schemas.py` with no engine imports.

**Why.** These types cross the public API boundary in both directions. If they imported engine types, every consumer would transitively depend on the active engine — defeating the entire abstraction.

### D5. Pre-computed embeddings only

**Decision.** Backends never call out to embedding model providers. Callers pre-compute every vector and pass it on the `DocumentRecord`.

**Why.** Decoupling vector generation from storage is a precondition for bring-your-own-embeddings mode in the embedding pipeline. It also keeps the backend single-purpose.

### D6. Deterministic chunk IDs from content

**Decision.** `build_chunk_id(source, chunk_index, text)` returns a UUID5 derived from `f"{source}:{chunk_index}:{sha256(text)}"`. The chunk store accepts a caller-supplied `chunk_id` override and generates the deterministic value when none is supplied.

**Why.** Deterministic IDs make re-ingestion idempotent — re-adding the same chunk replaces the same object. The `chunk_id` override exists because some upstream systems already carry stable identifiers and want them preserved.

**Alternative considered.** Per-chunk diffing. Rejected: chunk boundaries shift when content changes, so diffing is unreliable. Delete-by-source-key + deterministic ID covers the same ground without the complexity.

### D7. Source-key delete with legacy fallback

**Decision.** `delete_by_source_key` first attempts a delete on the `source_key` property; if that raises (because the property does not exist on older objects), it retries on the `source` property using a `legacy_source` argument.

**Why.** During the migration from `source` to `source_key`, both schemas coexist. Without the fallback, re-ingestion of a pre-migration document would either silently leak duplicates or hard-fail.

### D8. Multi-collection fan-out runs in parallel

**Decision.** `multi_search` issues per-collection searches concurrently using a thread pool sized to the number of collections, then merges and deduplicates by `object_id` (or text fallback), keeping the highest-scoring instance.

**Why.** Multi-tenant deployments split data across collections. End-to-end latency must approximate the slowest single search, not their sum. Per-collection failures are logged and skipped — never fatal — so a degraded backend cannot block all retrieval.

**Trade-off.** Threads add overhead for small fan-outs; mitigated by falling back to a single direct call when `collections` is empty or `None`.

### D9. Visual collection as a sibling, not a fork

**Decision.** Visual page operations (`ensure_visual_collection`, `add_visual_documents`, `delete_visual_by_source_key`, `search_visual`) live on the same `VectorBackend` ABC as chunk operations and route through the same public API module. The visual collection has its own schema (named vector, `mean_vector`, 128-dim, HNSW, cosine).

**Why.** Splitting visual into a separate subsystem would duplicate dispatcher, lifecycle, and tracing logic. Same interface + different schema is cheaper.

**Trade-off.** The ABC grows by four methods. Acceptable because they share lifecycle and filter semantics with the chunk methods.

### D10. Native aggregation only

**Decision.** `aggregate_by_source`, `get_collection_stats`, and `list_collections` must use the engine's group-by primitives. Iterating every object is forbidden.

**Why.** Full enumeration is unaffordable at production sizes. The engine knows how to do this efficiently; the subsystem must use that knowledge.

### D11. Tracing via the platform observability layer

**Decision.** Every engine helper opens a tracing span at the start of the operation, sets attributes for the collection name and any operation-specific count, and ends the span in success and failure paths. The observability layer is imported through `src.platform.observability`.

**Why.** Vector store operations are the dominant tail-latency contributor in retrieval. Without tracing they are invisible. Routing through the platform layer keeps the tracer provider configurable.

---

## 4) Contracts

### 4.1 Public API (Layer 1)

Functions exported from `src/vector_db/__init__.py`. Pipeline code MUST import only from this module.

| Function | Purpose | Returns |
|----------|---------|---------|
| `create_persistent_client()` | Build a long-lived client | client handle |
| `get_client()` (context manager) | Build an ephemeral client | yields client handle |
| `close_client(client)` | Tear down a persistent client | `None` |
| `ensure_collection(client, collection=None)` | Idempotently create collection | `None` |
| `delete_collection(client, collection=None)` | Drop a collection | `None` |
| `add_documents(client, documents, collection=None)` | Insert `DocumentRecord`s | inserted count |
| `delete_by_source(client, source, collection=None)` | Delete by `source` property | deleted count |
| `delete_by_source_key(client, source_key, legacy_source=None, collection=None)` | Delete by `source_key`, fallback to `source` | deleted count |
| `search(client, query, query_embedding, alpha, limit, filters=None, collection=None)` | Hybrid search on one collection | `list[SearchResult]` |
| `multi_search(client, query, query_embedding, alpha, limit, collections=None, filters=None)` | Parallel fan-out search | `list[SearchResult]` |
| `aggregate_by_source(client, collection=None, source_filter=None, connector_filter=None)` | Group counts by `source_key` | `list[dict]` |
| `get_collection_stats(client, collection=None)` | Aggregate stats | `dict` or `None` |
| `list_collections(client)` | Enumerate all collections | `list[dict]` |
| `ensure_visual_collection(client, collection=None)` | Create visual collection | `None` |
| `add_visual_documents(client, documents, collection=None)` | Insert visual page records | inserted count |
| `delete_visual_by_source_key(client, source_key, collection=None)` | Delete visual records | deleted count |
| `search_visual(client, query_vector, limit, score_threshold, tenant_id=None, collection=None)` | Visual similarity search | `list[dict]` |
| `build_chunk_id(source, chunk_index, text)` | Deterministic UUID | `str` |

### 4.2 ABC (Layer 2)

`VectorBackend` mirrors the public API one-for-one with the following exceptions:

- `create_persistent_client` and `get_ephemeral_client` are separate methods (the public API's `get_client` wraps `get_ephemeral_client` with the backend singleton).
- `multi_search` lives only in the public API — backends only implement `search`.
- `build_chunk_id` is a free function in `weaviate/store.py` re-exported from the public API.
- `close_client` has a default no-op implementation.

### 4.3 Data contracts

```python
@dataclass
class DocumentRecord:
    text: str
    embedding: list[float]
    metadata: dict[str, Any]

@dataclass
class SearchResult:
    text: str
    score: float
    metadata: dict[str, Any]
    object_id: Optional[str] = None
    collection: Optional[str] = None

@dataclass
class SearchFilter:
    property: str
    operator: str  # eq | ne | gt | lt | gte | lte | like
    value: Any
```

### 4.4 Filter operator mapping (Weaviate)

| `SearchFilter.operator` | `weaviate.classes.query.Filter.by_property(...).XYZ` |
|-------------------------|------------------------------------------------------|
| `eq`  | `equal` |
| `ne`  | `not_equal` |
| `gt`  | `greater_than` |
| `lt`  | `less_than` |
| `gte` | `greater_or_equal` |
| `lte` | `less_or_equal` |
| `like`| `like` |

Multi-clause filters AND-combine via the `&` operator on the Weaviate filter type.

---

## 5) Data Flow

### 5.1 Ingestion (text chunks)

```
Embedding pipeline
  ↓ DocumentRecord(text, embedding, metadata)
src.vector_db.add_documents(client, [records], collection)
  ↓
_get_vector_backend()  →  WeaviateBackend
  ↓
WeaviateBackend.add_documents(client, records, collection)
  ↓
weaviate/store.add_documents(client, texts, embeddings, metadatas, collection)
  ↓ for each record:
    chunk_id = _normalize_chunk_uuid(metadata.chunk_id, source_identity, chunk_index, text)
              ↓ if missing, falls back to build_chunk_id(...)
    batch.add_object(properties={...}, vector=embedding, uuid=chunk_id)
  ↓
return inserted_count
```

### 5.2 Retrieval (multi-collection)

```
Retrieval pipeline
  ↓ query, query_embedding, alpha, limit, collections=[A, B, C]
src.vector_db.multi_search(...)
  ↓
ThreadPoolExecutor(max_workers=3)
  ├─ search(client, ..., collection=A)  →  WeaviateBackend.search → store.hybrid_search
  ├─ search(client, ..., collection=B)  →  WeaviateBackend.search → store.hybrid_search
  └─ search(client, ..., collection=C)  →  WeaviateBackend.search → store.hybrid_search
  ↓ collect futures (failures logged, surviving results kept)
dedupe by object_id (or text fallback) — keep max score
  ↓
sort by score desc, truncate to limit
  ↓
return list[SearchResult]
```

### 5.3 Visual search

```
Visual retrieval pipeline
  ↓ query_vector (128-dim), limit, score_threshold, tenant_id
src.vector_db.search_visual(...)
  ↓
WeaviateBackend.search_visual(...)
  ↓
weaviate/visual_store.visual_search(...)
  ↓ near_vector(target_vector="mean_vector", ...)
  ↓ for each result:
       score = 1 - distance
       skip if score < score_threshold
       drop patch_vectors property
  ↓
return list[dict]
```

---

## 6) Error Handling Strategy

| Error class | Where caught | Behaviour |
|-------------|--------------|-----------|
| Unknown `VECTOR_DB_BACKEND` | Dispatcher | Raise `ValueError` with the list of valid values. |
| Engine call failure during single `search` | Layer 3/4 | Propagate to caller. |
| Engine call failure during one collection in `multi_search` | Public API fan-out | Log a warning with the collection name; continue with surviving results. |
| `delete_by_source_key` first-attempt failure | Layer 4 | If `legacy_source` provided, retry on `source`; otherwise return `0`. |
| `get_collection_stats` on missing collection | Layer 4 | Return `None` (do not raise). |
| `delete_collection` on missing collection | Layer 4 | No-op. |
| Unsupported filter operator | Layer 3 | Raise `ValueError` listing valid operators. |
| Persistent client teardown failure | Layer 3 | Log at debug level; do not propagate. |

---

## 7) Open Questions

| Question | Notes |
|----------|-------|
| Will a second backend ship in the next phase? | If yes, parameterise the test suite over backends as part of D1. |
| Should `multi_search` be made async? | Current thread-pool design is sufficient for the expected fan-out width (single-digit collections). |
| Should `aggregate_by_source` accept a `tenant_id` filter directly? | Currently achievable via metadata filters but not first-class. |

---

## 8) Acceptance Criteria for the Design

The design is met when:

1. Pipeline code imports only from `src.vector_db` (verified by `grep`).
2. Importing `src.vector_db` in an environment without the Weaviate client succeeds (verified by uninstall test).
3. Adding a new backend module does not require any change outside `_get_vector_backend()`.
4. Re-running ingestion on unchanged input produces the same chunk count and the same chunk IDs.
5. A degraded collection in `multi_search` does not block results from healthy collections.
