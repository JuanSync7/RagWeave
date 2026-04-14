# Vector Store Subsystem — Engineering Guide

| Field | Value |
|-------|-------|
| **Document type** | Post-implementation engineering reference |
| **Status** | Living document |
| **Version** | v1.0.0 |
| **Last updated** | 2026-04-10 |
| **Audience** | Engineers extending, debugging, or operating the vector store |

---

## 1) Quick Map

```
src/vector_db/
├── __init__.py              ← public API (start here)
├── backend.py               ← VectorBackend ABC
├── common/
│   ├── __init__.py
│   └── schemas.py           ← DocumentRecord, SearchResult, SearchFilter
└── weaviate/
    ├── __init__.py
    ├── backend.py           ← WeaviateBackend (ABC adapter)
    ├── store.py             ← chunk-store engine helpers
    └── visual_store.py      ← visual-page engine helpers
```

**Read order for newcomers:**

1. `common/schemas.py` (75 lines) — the dataclasses every layer passes around
2. `backend.py` (220 lines) — what every backend must do
3. `__init__.py` (440 lines) — what pipelines actually call
4. `weaviate/backend.py` (240 lines) — how the contract is satisfied
5. `weaviate/store.py` (440 lines) — chunk-store engine plumbing
6. `weaviate/visual_store.py` (250 lines) — visual-store engine plumbing

---

## 2) Architecture Decisions (cross-cutting)

### A1. Why an ABC instead of a Protocol?

Protocols are checked only by static type checkers — an incomplete implementation still constructs at runtime. With `abc.ABC` + `@abstractmethod`, an incomplete backend raises `TypeError` at construction. The tradeoff is a small amount of inheritance boilerplate; we accept it for the runtime guarantee.

### A2. Why a lazy singleton dispatcher in `__init__.py`?

Because the active backend is determined at runtime by `VECTOR_DB_BACKEND`, and because backend modules import engine-specific libraries (`weaviate-client`), we cannot afford to import all of them at module-load time. The lazy singleton:

- defers backend imports until the first call,
- caches the constructed backend for the rest of the process,
- localises the dispatcher into one place that future backends extend.

### A3. Why backend-independent dataclasses in `common/`?

`DocumentRecord`, `SearchResult`, and `SearchFilter` cross the public API boundary in both directions. If they imported anything from `weaviate`, every consumer would transitively depend on the active engine — defeating the abstraction. Keeping them in `common/` with zero engine imports is the type-level guarantee that backends are interchangeable.

### A4. Why deterministic chunk IDs?

Re-ingestion idempotency. If chunk IDs were random, re-adding the same chunk would produce a duplicate object. With a UUID5 derived from `f"{source}:{chunk_index}:{sha256(text)}"`, the same input always produces the same ID, and re-insertion replaces the existing object instead of duplicating it. The fallback override (`metadata.chunk_id`) is for upstream systems that already have a stable identifier.

### A5. Why does `delete_by_source_key` have a `legacy_source` fallback?

Pre-migration objects do not have a `source_key` property. A delete on `source_key` raises on those objects. The fallback retries on the legacy `source` property when `legacy_source` is provided, which lets re-ingestion succeed against mixed-schema collections during the migration. Once all collections are migrated this fallback can be removed.

### A6. Why is `multi_search` parallel?

Multi-tenant deployments split data across collections; the user still wants one ranked answer set. End-to-end latency must approximate the slowest single search, not their sum. A `ThreadPoolExecutor` sized to the number of collections gives concurrency without an async refactor. Per-collection failures are logged and skipped — never fatal — because a degraded collection should not block all retrieval.

### A7. Why visual collections under the same ABC?

Splitting visual into its own subsystem would duplicate dispatcher, lifecycle, tracing, and config wiring. Same interface + different schema (named vector, threshold scoring) is cheaper. The cost is four extra abstract methods on `VectorBackend`.

### A8. Why native group-by aggregation only?

Full enumeration is unaffordable at production sizes. The engine knows how to do this efficiently; the subsystem must use that knowledge. `aggregate_by_source`, `get_collection_stats`, and `list_collections` all route through the engine's group-by primitives.

---

## 3) Module Reference

### 3.1 `common/schemas.py`

**Responsibility.** Define the three data contracts that cross the public API in both directions.

**Exports.** `DocumentRecord`, `SearchResult`, `SearchFilter`.

**Key invariants.**

- Zero engine imports.
- Pure dataclasses, no behaviour.
- `SearchResult.collection` is populated by the backend so multi-search consumers can attribute each result to its source collection.

**Common gotchas.**

- Adding a new field requires updating every backend that constructs `SearchResult` to populate it.
- The `SearchFilter.operator` vocabulary is the contract — adding a new operator means updating the filter translator in every backend.

---

### 3.2 `backend.py` — `VectorBackend` ABC

**Responsibility.** Define the formal contract every concrete backend implements.

**Exports.** `VectorBackend`.

**Key invariants.**

- Every public API operation has a corresponding abstract method.
- Every collection-scoped method takes `collection: Optional[str] = None`.
- Two client lifecycle modes: `create_persistent_client` and `get_ephemeral_client` (the latter is a `@contextmanager`).
- `close_client` has a default no-op so backends without explicit teardown semantics do not need to override it.

**Common gotchas.**

- Forgetting `@abstractmethod` on a new method makes it silently optional. Always combine `@abstractmethod` with the contextmanager decorator (in the right order: `@abstractmethod` outside).
- Adding a new method here without updating every concrete backend will break instantiation with `TypeError` — which is the desired behaviour. Plan the rollout accordingly.

---

### 3.3 `__init__.py` — Public API + Dispatcher

**Responsibility.** The single import point for all consumers. Owns the dispatcher, default-collection resolution, and `multi_search`.

**Exports.** All 18 public functions plus the three schemas and `build_chunk_id`.

**Key state.**

- `_vector_backend: VectorBackend | None` — module-level singleton, set lazily.

**Key flows.**

- **Dispatcher (`_get_vector_backend`).** First call constructs the backend based on `VECTOR_DB_BACKEND`. Subsequent calls return the cached instance. Unknown values raise `ValueError` listing valid options.
- **Default-collection resolution (`_resolve_collection`).** Truthy `collection` argument is returned as-is; otherwise `VECTOR_COLLECTION_DEFAULT` is used. Note that not every public function calls `_resolve_collection` — `add_documents`, `search`, `delete_by_source`, etc. forward `None` to the backend, which resolves it via `_col(...)`. The aggregation/stats functions resolve in the public API layer for parity.
- **`get_client()` context manager.** Wraps `backend.get_ephemeral_client()` so consumers do not need to know about the singleton.
- **`multi_search`.** Parallel fan-out using `ThreadPoolExecutor(max_workers=len(collections))`, dedupe by `object_id` (text fallback), keep highest score, sort, truncate.

**Common gotchas.**

- Adding a new public function but forgetting `__all__` means it imports but does not show up in `from src.vector_db import *`.
- `multi_search` falls back to `search` when `collections` is empty or `None` — do not change this without updating callers that pass an empty list defensively.
- The thread pool is sized to the number of collections, not capped. For very wide fan-outs (>20 collections), consider adding a cap.

---

### 3.4 `weaviate/backend.py` — `WeaviateBackend`

**Responsibility.** Thin adapter from the ABC contract to engine-specific helpers. No business logic.

**Key state.**

- `_VISUAL_COLLECTION_DEFAULT = "RAGVisualPages"` — class-level constant used when no visual collection is provided.

**Key methods.**

- `_col(collection)` — local default-collection resolution falling back to `WEAVIATE_COLLECTION_NAME`.
- `add_documents` — translates `DocumentRecord` lists into `texts/embeddings/metadatas` triples for `store.add_documents`.
- `search` — wraps `store.hybrid_search` and converts the raw dicts into `SearchResult` instances with the resolved collection name.
- `_translate_filters` — single clause or AND-combined multi-clause via the `&` operator.
- `_single_filter` — operator dispatch table covering `eq/ne/like/gt/lt/gte/lte`. Raises `ValueError` for unknowns.
- `close_client` — defensive `client.close()` swallowing errors at debug level.

**Common gotchas.**

- The visual collection methods default to `_VISUAL_COLLECTION_DEFAULT`, not `WEAVIATE_COLLECTION_NAME`. Mixing the two will produce confusing schema errors.
- `_translate_filters` must return `None` (not an empty list) when no filters are passed, or the engine will reject the query.
- Filter operator names are matched case-insensitively.

---

### 3.5 `weaviate/store.py` — Chunk-store engine helpers

**Responsibility.** All engine-specific operations for the chunk collection: connection, schema, CRUD, hybrid search, aggregation, listing.

**Key functions.**

- `create_persistent_client` / `get_weaviate_client` — embedded-mode client construction with `weaviate.connect_to_embedded(persistence_data_path=WEAVIATE_DATA_DIR)`.
- `ensure_collection` — creates the collection with the documented property set if it does not exist; vectorizer is `none`.
- `build_chunk_id(source, chunk_index, text)` — UUID5 of the SHA-256 payload.
- `_normalize_chunk_uuid(candidate, source, chunk_index, text)` — accepts caller-supplied IDs and falls back to `build_chunk_id`.
- `add_documents` — batch insert with `col.batch.dynamic()`. Inspects the collection's actual property set and only writes optional properties that exist (so the function works against both pre- and post-migration schemas).
- `hybrid_search` — `col.query.hybrid(query=..., vector=..., alpha=..., fusion_type=HybridFusion.RELATIVE_SCORE, return_metadata=MetadataQuery(score=True))`.
- `delete_collection`, `delete_documents_by_source`, `delete_documents_by_source_key` (with the legacy fallback).
- `aggregate_by_source` — `col.aggregate.over_all(group_by=GroupByAggregate(prop="source_key"), filters=..., total_count=True)` returning one dict per group.
- `get_collection_stats` — three aggregate calls (total, by source_key, by connector) combined into a stats dict; returns `None` for missing collections.
- `list_collections` — `client.collections.list_all(simple=True)` then a per-collection aggregate for chunk counts.

**Schema (chunk collection).**

The `ensure_collection` schema currently includes (all `TEXT` unless noted): `text`, `source`, `source_uri`, `source_key`, `source_id`, `connector`, `source_version`, `retrieval_text_origin`, `citation_source_uri`, `provenance_method`, `provenance_confidence` (NUMBER), `original_char_start`/`end` (INT), `refactored_char_start`/`end` (INT), `title`, `author`, `date`, `tags`, `chunk_index` (INT), `total_chunks` (INT), `section_path`, `heading`, `heading_level` (INT), `tenant_id`, `document_id`.

**Tracing.** Every helper opens a span (`vector_store.<op>`) with attributes for the collection name and any operation-specific count or limit.

**Common gotchas.**

- The dynamic property writer (`add_documents`) only writes optional properties that exist in the collection. If you add a new property to `ensure_collection`, you must also re-create existing collections or extend the dynamic writer's allowlist.
- `build_chunk_id` uses `uuid.NAMESPACE_URL` — do not change this namespace without a full re-ingest.
- `delete_documents_by_source_key` swallows the first-attempt exception when `legacy_source` is missing and returns `0`. Callers that need a hard error should check the count.
- `aggregate_by_source` uses `group_by` over `source_key`, not `source`. Sources without a `source_key` are silently grouped under an empty key.

---

### 3.6 `weaviate/visual_store.py` — Visual-store engine helpers

**Responsibility.** All engine-specific operations for the visual page collection.

**Key functions.**

- `ensure_visual_collection(client, collection)` — creates the collection with one named vector `mean_vector` (128-dim, HNSW, cosine), property set covering `document_id`, `page_number`, `source_key`, `source_uri`, `source_name`, `tenant_id`, `total_pages`, `page_width_px`, `page_height_px`, `minio_key`, and `patch_vectors` (TEXT, `skip_vectorization=True`).
- `add_visual_documents(client, documents, collection)` — batch insert mapping `mean_vector` into the named vector slot; every other key becomes a property. Returns inserted count, accounting for failed objects.
- `visual_search(client, query_vector, limit, score_threshold, tenant_id, collection)` — `col.query.near_vector(target_vector="mean_vector", ...)`, optional `tenant_id` filter, distance-to-similarity conversion (`score = 1 - distance`), score-threshold drop, explicit `return_properties` list excluding `patch_vectors`.
- `delete_visual_by_source_key(client, source_key, collection)`.

**Common gotchas.**

- `patch_vectors` is stored as opaque text and **never** returned by `visual_search`. If a future caller needs it, add a separate `get_patch_vectors` helper rather than expanding `visual_search`.
- The cosine-distance-to-similarity conversion assumes Weaviate's distance is in `[0, 2]`; with cosine it is effectively `[0, 1]` (0 = identical, 1 = orthogonal). `score = 1 - distance` therefore lives in `[0, 1]`.
- `tenant_id=None` means **no tenant filter**, not "filter to objects with no tenant". Use a sentinel string if the latter is needed.

---

## 4) Configuration Reference

| Key | Default | Source | Effect |
|-----|---------|--------|--------|
| `VECTOR_DB_BACKEND` | `"weaviate"` | env var | Selects the active backend implementation |
| `VECTOR_COLLECTION_DEFAULT` | `WEAVIATE_COLLECTION_NAME` | env var `RAG_VECTOR_COLLECTION_DEFAULT` | Collection used when callers pass `None` |
| `WEAVIATE_COLLECTION_NAME` | `"RAGDocuments"` | constant | Default chunk collection name for the Weaviate backend |
| `WEAVIATE_DATA_DIR` | platform-default path | env var `RAG_WEAVIATE_DATA_DIR` | Persistence directory for embedded mode |
| `HYBRID_SEARCH_ALPHA` | `0.5` | constant | Default alpha used by retrieval; passed per call |
| `SEARCH_LIMIT` | `10` | constant | Default search limit; passed per call |
| `RAG_INGESTION_VISUAL_TARGET_COLLECTION` | `"RAGVisualPages"` | env var | Visual collection name |

---

## 5) Data Flow (concrete example)

### Ingest a 3-chunk document into the chunk collection

```python
from src.vector_db import (
    get_client, ensure_collection, add_documents, DocumentRecord
)

records = [
    DocumentRecord(
        text=chunk_text,
        embedding=embed(chunk_text),  # caller pre-computes
        metadata={
            "source": "/path/to/doc.md",
            "source_key": "stable-doc-key",
            "chunk_index": i,
            "total_chunks": 3,
            "heading": "Section 2.1",
            "tenant_id": "default",
        },
    )
    for i, chunk_text in enumerate(chunks)
]

with get_client() as client:
    ensure_collection(client)            # idempotent, uses default
    inserted = add_documents(client, records)
```

What happens under the hood:

1. `get_client()` → `_get_vector_backend()` → `WeaviateBackend()` (cached).
2. `WeaviateBackend.get_ephemeral_client()` → `weaviate.connect_to_embedded(...)`.
3. `ensure_collection` → `WeaviateBackend.ensure_collection` → `weaviate/store.ensure_collection` → idempotent create.
4. `add_documents` → `WeaviateBackend.add_documents` → `weaviate/store.add_documents` → for each record, generate (or normalise) the chunk UUID, build properties dict, `batch.add_object(...)`.
5. Tracing spans wrap every step.

### Multi-collection retrieval

```python
from src.vector_db import get_client, multi_search, SearchFilter

with get_client() as client:
    results = multi_search(
        client,
        query="hybrid search example",
        query_embedding=embed_query("hybrid search example"),
        alpha=0.7,
        limit=10,
        collections=["RAGDocuments", "RAGNotes"],
        filters=[SearchFilter("tenant_id", "eq", "acme")],
    )
```

What happens:

1. `ThreadPoolExecutor(max_workers=2)` submits two `backend.search(...)` calls in parallel.
2. Each call builds an AND-combined filter (`tenant_id = "acme"`) and runs `hybrid_search` against its collection.
3. The two result lists merge; dedupe keeps the higher score per `object_id`.
4. Final list is sorted by score descending and truncated to 10.

---

## 6) Extension Recipes

### Add a new backend (e.g., Qdrant)

1. Create `src/vector_db/qdrant/` with `__init__.py`, `backend.py` (the ABC adapter), and `store.py` / `visual_store.py` for engine helpers.
2. Implement every abstract method on `VectorBackend`. Run a smoke instantiation to confirm no `TypeError`.
3. Add a branch to `_get_vector_backend()` in `src/vector_db/__init__.py`:

   ```python
   elif VECTOR_DB_BACKEND == "qdrant":
       from src.vector_db.qdrant.backend import QdrantBackend
       _vector_backend = QdrantBackend()
   ```

4. Add the new backend to the `ValueError` message's "Valid values" list.
5. Parameterise the contract test suite to run against both backends (REQ-VDB-1101 becomes mandatory).
6. No edits to consumers (`src/ingest/`, `src/retrieval/`) should be required.

### Add a new operator to `SearchFilter`

1. Add the operator name to the docstring in `common/schemas.py`.
2. Add a translation entry to `_single_filter` in every concrete backend's adapter.
3. Add a test case to the operator-coverage test (REQ-VDB-1102).
4. Update the spec (REQ-VDB-800) to list the new operator.

### Add a new property to the chunk collection

1. Add the `Property(...)` to `ensure_collection` in `weaviate/store.py`.
2. Add the property to the dynamic-write allowlist in `add_documents` (and to the `properties` mapping if it should always be written).
3. Add the property to the read mapping in `hybrid_search` so it round-trips into `SearchResult.metadata`.
4. Re-create existing collections, or write a one-shot migration that adds the property to the live schema.
5. If the property is needed for filtering, no SearchFilter changes are required — `SearchFilter("new_prop", "eq", value)` will just work.

---

## 7) Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `ValueError: Unknown VECTOR_DB_BACKEND: 'X'` | Misspelled or unset env var | Set `VECTOR_DB_BACKEND` to `"weaviate"` (or another supported value) |
| `TypeError: Can't instantiate abstract class WeaviateBackend with abstract method ...` | New abstract method added to `VectorBackend` not yet implemented in the concrete backend | Implement the missing method in `weaviate/backend.py` |
| `ImportError: weaviate` on `import src.vector_db` | A backend module is being imported eagerly somewhere (regression of REQ-VDB-1001) | Find the eager import and move it inside `_get_vector_backend()` |
| Re-ingestion creates duplicate chunks | `chunk_id` not deterministic — likely a custom override that does not normalise | Audit `metadata.chunk_id`; let `_normalize_chunk_uuid` handle it |
| `delete_by_source_key` returns `0` on a known-populated source | Pre-migration objects with no `source_key` property | Pass `legacy_source=<old_source_path>` |
| `multi_search` returns fewer results than expected | One of the per-collection searches failed silently | Check the warning log for `multi_search: collection ... search failed` |
| Visual search returns no results | Score threshold higher than the actual best similarity, OR tenant filter excluding everything | Lower `score_threshold` to 0 to confirm; check `tenant_id` mismatch |
| `aggregate_by_source` returns empty for a populated collection | Collection contains objects with no `source_key` property | They are grouped under an empty key — re-ingest with `source_key` set |

---

## 8) Testing Guide

### Testability map

| Component | Test type | Notes |
|-----------|-----------|-------|
| `build_chunk_id` | Unit | Pure function — no fixtures |
| `SearchFilter` translation | Unit | Use the static `_single_filter` directly with mock Filter |
| `multi_search` dedup | Unit | Use a fake backend that returns canned `SearchResult` lists |
| `multi_search` failure tolerance | Unit | Fake backend that raises for one collection |
| Public API → backend dispatch | Unit | Patch `_vector_backend` to a fake instance |
| `add_documents` round trip | Integration | Embedded Weaviate fixture |
| `hybrid_search` round trip | Integration | Embedded Weaviate fixture |
| `aggregate_by_source` | Integration | Multi-source fixture, assert group counts |
| `visual_search` threshold + tenant | Integration | Embedded Weaviate fixture with named vector |
| Lazy import (REQ-VDB-1001) | Subprocess | Import `src.vector_db` with `weaviate-client` uninstalled |

### Mock boundaries

- **Pipeline tests** mock the public API (`src.vector_db.add_documents`, etc.) and never touch a real backend.
- **Backend adapter tests** mock the engine helpers (`weaviate.store.add_documents`, etc.) and verify translation/dispatch.
- **Engine helper tests** run against an embedded Weaviate instance — these are the only tests that need real engine state.

### Critical scenarios

1. Re-ingest the same document twice → same chunk count, same IDs.
2. Insert with caller-supplied `chunk_id` → the supplied ID wins.
3. `multi_search` over two collections with overlapping results → one entry per dedupe key, higher score wins.
4. `multi_search` where one collection raises → results from surviving collections are returned.
5. `delete_by_source_key` against a pre-migration collection with `legacy_source` → falls back successfully.
6. Filter with all seven operators → each translates to the expected engine clause.
7. Visual search with score threshold 0.9 → returns only results above 0.9.
8. Visual search with `tenant_id="X"` → returns only objects whose `tenant_id == "X"`.
9. `aggregate_by_source` with a `source_filter` containing a glob substring → only matching sources appear.
10. `get_collection_stats` on a non-existent collection → returns `None`, does not raise.
11. `close_client` called twice on the same handle → second call does not raise.
12. Importing `src.vector_db` in a fresh process → backend module is not imported until first call.

---

## 9) Cross-References

- Spec: `VECTOR_DB_SPEC.md` (`REQ-VDB-100`–`REQ-VDB-1199`)
- Spec summary: `VECTOR_DB_SPEC_SUMMARY.md`
- Design rationale: `VECTOR_DB_DESIGN.md` §3 (Key Design Decisions)
- Test plan: `VECTOR_DB_TEST_DOCS.md`
- Upstream consumers: `EMBEDDING_PIPELINE_SPEC.md` (FR-1200–FR-1299), `VISUAL_EMBEDDING_SPEC.md`
- Downstream consumers: `RETRIEVAL_QUERY_SPEC.md`, `VISUAL_RETRIEVAL_SPEC.md`
