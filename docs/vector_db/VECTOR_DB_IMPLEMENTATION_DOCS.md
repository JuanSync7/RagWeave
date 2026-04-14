# Vector Store Subsystem — Implementation Plan

| Field | Value |
|-------|-------|
| **Document type** | Implementation plan (task decomposition, build sequence) |
| **Status** | Retrospective — system already built |
| **Version** | v1.0.0 |
| **Last updated** | 2026-04-10 |
| **Companion documents** | `VECTOR_DB_SPEC.md`, `VECTOR_DB_DESIGN.md`, `VECTOR_DB_ENGINEERING_GUIDE.md` |

---

## 0) Note on Status

This subsystem is already implemented in `src/vector_db/`. This document is a **retrospective task decomposition** — it traces the actual build into discrete, ordered tasks that map to spec requirements. Future backend additions should follow the same task pattern.

---

## 1) Task DAG

```
T1. common/schemas.py
       │
       ▼
T2. backend.py (ABC)
       │
       ├──────────────────────────────┐
       ▼                              ▼
T3. weaviate/store.py            T4. weaviate/visual_store.py
       │                              │
       └──────────────┬───────────────┘
                      ▼
              T5. weaviate/backend.py
                      │
                      ▼
              T6. __init__.py (public API + dispatcher)
                      │
                      ├──────────────┐
                      ▼              ▼
              T7. multi_search   T8. tests
              (in __init__.py)
                      │
                      ▼
              T9. observability wiring
              (cross-cutting in T3, T4)
```

Critical path: **T1 → T2 → T3 → T5 → T6 → T7**.

---

## 2) Tasks

### T1 — Backend-independent data contracts

**File:** `src/vector_db/common/schemas.py`

**Spec coverage:** REQ-VDB-900, REQ-VDB-901, REQ-VDB-902, REQ-VDB-903

**Steps.**

1. Create `common/__init__.py` (empty placeholder).
2. Define `DocumentRecord(text, embedding, metadata)` as a dataclass.
3. Define `SearchResult(text, score, metadata, object_id=None, collection=None)` as a dataclass.
4. Define `SearchFilter(property, operator, value)` as a dataclass with the operator vocabulary documented in the docstring.
5. Verify no engine imports leak in.

**Acceptance.** The module imports cleanly with only `dataclasses` and `typing`.

---

### T2 — Backend ABC

**File:** `src/vector_db/backend.py`

**Spec coverage:** REQ-VDB-200, REQ-VDB-201, REQ-VDB-202, REQ-VDB-203

**Steps.**

1. Define `VectorBackend(ABC)`.
2. Add an `@abstractmethod` for each public API operation: `create_persistent_client`, `get_ephemeral_client` (`@contextmanager`), `ensure_collection`, `add_documents`, `search`, `delete_collection`, `delete_by_source`, `delete_by_source_key`, `aggregate_by_source`, `get_collection_stats`, `list_collections`, `ensure_visual_collection`, `add_visual_documents`, `delete_visual_by_source_key`, `search_visual`.
3. Add `close_client(client)` as a non-abstract default no-op method.
4. Every collection-scoped method takes `collection: Optional[str] = None`.

**Acceptance.** Instantiating an empty subclass raises `TypeError`.

---

### T3 — Weaviate chunk store engine helpers

**File:** `src/vector_db/weaviate/store.py`

**Spec coverage:** REQ-VDB-300, REQ-VDB-301, REQ-VDB-302, REQ-VDB-303, REQ-VDB-304, REQ-VDB-400, REQ-VDB-401, REQ-VDB-600, REQ-VDB-601, REQ-VDB-602, REQ-VDB-700, REQ-VDB-701, REQ-VDB-950

**Steps.**

1. Implement `create_persistent_client()` and `get_weaviate_client()` (context manager) using `weaviate.connect_to_embedded(persistence_data_path=WEAVIATE_DATA_DIR)`.
2. Implement `ensure_collection(client, collection)` — check existence, create with the documented property set if missing, configure vectorizer as `none`.
3. Implement `build_chunk_id(source, chunk_index, text)` — UUID5 over the SHA-256 payload.
4. Implement `_normalize_chunk_uuid(candidate, source, chunk_index, text)` — accept caller-supplied IDs, fall back to `build_chunk_id`.
5. Implement `add_documents(client, texts, embeddings, metadatas, collection)` — batch insert with the deterministic UUIDs and a metadata schema-aware property mapper.
6. Implement `hybrid_search(client, query, query_embedding, alpha, limit, filters, collection)` — `col.query.hybrid(...)` with `HybridFusion.RELATIVE_SCORE` and `MetadataQuery(score=True)`.
7. Implement `delete_collection`, `delete_documents_by_source`, `delete_documents_by_source_key` (with the legacy fallback path).
8. Implement `aggregate_by_source` using `col.aggregate.over_all(group_by=GroupByAggregate(prop="source_key"), ...)`.
9. Implement `get_collection_stats` and `list_collections` using `aggregate.over_all` and `collections.list_all(simple=True)`.
10. Wrap every operation in a tracer span (`tracer.start_span(...)`).

**Acceptance.** Round-tripping a document through `add_documents` → `hybrid_search` returns the document with its metadata preserved.

---

### T4 — Weaviate visual store engine helpers

**File:** `src/vector_db/weaviate/visual_store.py`

**Spec coverage:** REQ-VDB-500, REQ-VDB-501, REQ-VDB-502, REQ-VDB-503, REQ-VDB-504

**Steps.**

1. Implement `ensure_visual_collection(client, collection)` — create the collection with a single named vector `mean_vector` (128-dim, HNSW, cosine), the property set defined in REQ-VDB-501, and `patch_vectors` configured with `skip_vectorization=True`.
2. Implement `add_visual_documents(client, documents, collection)` — batch insert mapping the `mean_vector` key into the named vector slot.
3. Implement `visual_search(client, query_vector, limit, score_threshold, tenant_id, collection)` — `col.query.near_vector(target_vector="mean_vector", ...)`, optional `tenant_id` filter, distance-to-similarity conversion (`score = 1 - distance`), score threshold drop, and explicit return-property list excluding `patch_vectors`.
4. Implement `delete_visual_by_source_key(client, source_key, collection)`.
5. Wrap every operation in a tracer span.

**Acceptance.** A visual record inserted via `add_visual_documents` is found by `visual_search` only when its similarity meets the threshold and matches any tenant filter.

---

### T5 — Weaviate ABC adapter

**File:** `src/vector_db/weaviate/backend.py`

**Spec coverage:** REQ-VDB-200, REQ-VDB-202, REQ-VDB-203, REQ-VDB-800, REQ-VDB-801

**Steps.**

1. Define `WeaviateBackend(VectorBackend)`.
2. Implement every abstract method as a thin delegation to the corresponding helper in `weaviate/store.py` or `weaviate/visual_store.py`. No business logic.
3. Translate `DocumentRecord` lists into `texts/embeddings/metadatas` triples for `store.add_documents`.
4. Translate `hybrid_search` raw dicts into `SearchResult` instances and populate the `collection` field.
5. Implement `_translate_filters(filters)` — single-clause and AND-combined multi-clause via `&`.
6. Implement `_single_filter(f)` — operator dispatch table for `eq/ne/like/gt/lt/gte/lte`. Raise `ValueError` for unknowns.
7. Override `close_client` to call `client.close()` defensively, swallowing errors at debug log level.
8. Implement the four visual methods, defaulting to the `_VISUAL_COLLECTION_DEFAULT = "RAGVisualPages"` constant when no collection is supplied.

**Acceptance.** `WeaviateBackend()` instantiates and every method routes to the correct helper.

---

### T6 — Public API and dispatcher

**File:** `src/vector_db/__init__.py`

**Spec coverage:** REQ-VDB-100, REQ-VDB-101, REQ-VDB-102, REQ-VDB-103

**Steps.**

1. Module-level `_vector_backend: VectorBackend | None = None`.
2. Implement `_get_vector_backend()` — lazy-import `WeaviateBackend` based on `VECTOR_DB_BACKEND` value, cache as singleton, raise `ValueError` for unknown values.
3. Implement `_resolve_collection(collection)` — return the argument if truthy, else `VECTOR_COLLECTION_DEFAULT`.
4. Implement every public function as a thin delegation to the cached backend, with default-collection resolution where appropriate.
5. Implement `get_client()` as a `@contextmanager` wrapping the backend's `get_ephemeral_client`.
6. Re-export `DocumentRecord`, `SearchResult`, `SearchFilter`, and `build_chunk_id`.
7. Define `__all__` with the full export set.

**Acceptance.** All consumers in `src/ingest/` and `src/retrieval/` import only from this module (verified by grep).

---

### T7 — Multi-collection fan-out search

**File:** `src/vector_db/__init__.py` (`multi_search`)

**Spec coverage:** REQ-VDB-402, REQ-VDB-1002

**Steps.**

1. If `collections` is empty or `None`, fall back to a single `search(...)` on the default collection.
2. Build a `ThreadPoolExecutor(max_workers=len(collections))` and submit one `backend.search(...)` per collection.
3. As each future completes, append its results to a shared list. On exception, log a warning with the collection name and continue.
4. Build a dedupe map keyed on `r.object_id` (or `r.text` when `object_id` is `None`), keeping the higher-scoring instance.
5. Return `sorted(seen.values(), key=score, reverse=True)[:limit]`.

**Acceptance.** A two-collection fan-out with overlapping results returns one entry per dedupe key with the higher score.

---

### T8 — Test coverage

**Files:** `tests/test_vector_store_integration.py`, future `tests/vector_db/*`

**Spec coverage:** REQ-VDB-1100, REQ-VDB-1101, REQ-VDB-1102, REQ-VDB-1103, REQ-VDB-1104

**Steps.**

1. Determinism unit test for `build_chunk_id` (already shipped).
2. Filter translation operator-coverage unit test (covers REQ-VDB-1102).
3. Multi-search dedup and per-collection-failure unit tests using a fake backend (covers REQ-VDB-1103).
4. Visual round-trip integration test against an embedded Weaviate instance (covers REQ-VDB-1104).
5. Backend-swap import-time test: import `src.vector_db` in an environment without `weaviate-client`, assert no `ImportError` (covers REQ-VDB-1001).
6. Once a second backend exists, parameterise the contract test suite over both (covers REQ-VDB-1101).

---

### T9 — Observability wiring

**Cross-cutting:** every helper in T3 and T4

**Spec coverage:** REQ-VDB-950

**Steps.**

1. Import `get_tracer` from `src.platform.observability`.
2. Open a span at the top of every operation with a stable name (`vector_store.<op>`) and attributes for collection name, count, alpha, limit, etc.
3. End the span in success and failure paths.

**Acceptance.** A traced ingestion + retrieval round trip emits at least one span per called operation.

---

## 3) Build Order Justification

- **T1 first** because every other module depends on the data contracts.
- **T2 second** because it sets the contract every concrete backend must satisfy.
- **T3 and T4 in parallel** — they touch independent helper modules.
- **T5 after T3 and T4** — the adapter wraps both helper modules.
- **T6 after T5** — the dispatcher needs at least one concrete backend.
- **T7 after T6** — `multi_search` lives in the public API and depends on the dispatcher.
- **T8 in parallel with T6/T7** for the parts that can use fakes; integration tests come last.
- **T9 woven into T3 and T4** rather than added at the end, so spans land naturally at the right boundaries.

---

## 4) Definition of Done

A vector_db change is done when:

1. The relevant spec requirement(s) have green acceptance criteria.
2. Public API exports are unchanged (or new exports added to `__all__`).
3. New/changed modules have `@summary` blocks at the top.
4. Affected tests pass; new tests cover any new branch.
5. No file in `src/ingest/` or `src/retrieval/` imports from `src.vector_db.weaviate.*`.
6. Tracing spans cover any new backend operation.
7. Engineering guide updated if module structure or responsibilities changed.
