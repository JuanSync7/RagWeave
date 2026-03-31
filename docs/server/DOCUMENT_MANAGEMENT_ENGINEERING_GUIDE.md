> **Document type:** Engineering guide (Layer 6)
> **Upstream:** DOCUMENT_MANAGEMENT_IMPLEMENTATION.md
> **Last updated:** 2026-03-27

# Document & Collection Management API — Engineering Guide (v1.0.0)

---

## 1. Overview

This subsystem adds read-only HTTP endpoints for browsing ingested documents and
vector collections. Before this work, the AION RAG server could ingest and query
but offered no way to inspect what was already ingested.

**Endpoints delivered:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/documents` | Paginated document list with chunk counts |
| GET | `/api/v1/documents/{id}` | Full content + metadata for one document |
| GET | `/api/v1/documents/{id}/url` | Presigned MinIO download URL |
| GET | `/api/v1/sources` | Unique sources with aggregate statistics |
| GET | `/api/v1/collections` | All Weaviate collections with chunk counts |
| GET | `/api/v1/collections/{name}/stats` | Aggregate stats for one collection |

**Architecture:**

```
HTTP Client
    │
    ▼
FastAPI  ──authenticate_request──► src.platform.security.auth
    │
    ▼
server/routes/documents.py   (thin route handlers)
    │                  │
    ▼                  ▼
src.db              src.vector_db
(facade)            (facade)
    │                  │
    ▼                  ▼
src/db/minio/       src/vector_db/weaviate/
  store.py            store.py
    │                  │
    ▼                  ▼
MinIO (S3)          Weaviate (vector DB)
```

Route handlers are thin: validate parameters, call backend facades, apply
filters, format responses. No business logic lives in the route module.

---

## 2. Module Reference

### 2.1 `server/routes/documents.py`

**Public API:** `create_documents_router(db_client, vector_client) -> APIRouter`

Returns an `APIRouter` (no prefix on the router; each route carries the full
`/api/v1/...` path). The factory pattern mirrors `create_query_router()`.

**Error helpers (module-private):**

- `_not_found(item_type, identifier)` — `HTTPException(404)` with
  `ApiErrorResponse(error=ApiErrorDetail(code="not_found", ...))`.
- `_service_unavailable(detail)` — `HTTPException(503)` with
  `error.code="service_unavailable"`.

`ApiErrorResponse` requires an `ApiErrorDetail` object; passing a plain dict
raises a `ValidationError`.

**Tenant isolation:** Every handler calls `resolve_tenant_id(principal)`. The
result is available for Weaviate tenant filtering when multi-tenant isolation
is needed (NFR-3004).

**Graceful degradation in `list_documents_endpoint`:** If Weaviate
`aggregate_by_source` fails, all documents are still returned from MinIO with
`chunk_count: null` and `connector: "unknown"`. The Weaviate failure is logged
at WARNING; the request returns 200.

---

### 2.2 `server/schemas.py` — Document Management Models

Added at lines 377–456. All are plain Pydantic `BaseModel`.

| Model | Endpoint | Notes |
|-------|---------|-------|
| `DocumentSummary` | `GET /documents` | `chunk_count`, `ingested_at` are `Optional` |
| `DocumentListResponse` | `GET /documents` | Paginated wrapper; `documents` defaults to `[]` |
| `DocumentDetailResponse` | `GET /documents/{id}` | `chunk_count` is `Optional` |
| `DocumentUrlResponse` | `GET /documents/{id}/url` | `expires_in` echoes query param |
| `SourceSummary` | `GET /sources` | `document_count`, `chunk_count` are required ints |
| `SourceListResponse` | `GET /sources` | Paginated wrapper; `sources` defaults to `[]` |
| `CollectionItem` | nested in `CollectionListResponse` | `chunk_count` is required int |
| `CollectionStatsResponse` | `GET /collections/{name}/stats` | `connector_breakdown: dict[str, int]` |
| `CollectionListResponse` | `GET /collections` | `collections` field has no default |

---

### 2.3 `src/db/minio/store.py` — `list_documents()`

Enumerates `.md` content objects in a MinIO bucket, reads each `.meta.json`
sidecar for the stable `source_key`, and returns a structured list.

**How it works:**

1. Calls `client.list_objects(bucket, prefix=prefix, recursive=True)`.
2. Filters to objects ending in `.md`; ignores `.meta.json` sidecars.
3. For each `.md` object, fetches `{stem}.meta.json` to read `source_key`.
   If the sidecar is absent, falls back to `stem` and logs a WARNING.
4. Computes `document_id = build_document_id(source_key)` (UUID5).
5. Collects all matches in memory, then slices `[offset:offset+limit]`.

**Key constraint:** MinIO has no server-side offset; the full object list is
loaded before slicing. For large buckets, use `prefix` to narrow the scan.

**Tracing:** Span `"document_store.list_documents"` with `bucket`, `prefix`,
`limit`, `offset` attributes.

**Error behavior:** `S3Error` from individual sidecar fetches is swallowed
(WARNING logged). `S3Error` from `list_objects` propagates to the caller.

---

### 2.4 `src/vector_db/weaviate/store.py` — Aggregation Functions

Three functions added after `delete_documents_by_source_key`.

**`aggregate_by_source(client, collection, source_filter, connector_filter)`**

Groups chunk counts by `source_key` using
`col.aggregate.over_all(group_by=GroupByAggregate(prop="source_key"))`.
Filters are composed with `Filter.by_property()` and `Filter.all_of()`.
Returns `list[dict]` with `source_key`, `source`, `connector`, `chunk_count`.
`source` and `connector` are the first `top_occurrences` value per group.
Raises `KeyError` if the collection does not exist.

**`get_collection_stats(client, collection)`**

Returns `None` if the collection does not exist (checked via
`client.collections.exists()`). Otherwise issues three sequential aggregate
queries: total count, group-by `source_key` (for `document_count`),
group-by `connector` (for `connector_breakdown`). Returns a `dict`.

**`list_collections(client)`**

Calls `client.collections.list_all(simple=True)` then issues one
`aggregate.over_all(total_count=True)` per collection (N+1 round trips).
Raises `WeaviateConnectionError` if the client is disconnected.

---

### 2.5 Backend ABCs and Public Facades

**`src/db/backend.py`** — `DocumentBackend` ABC extended with abstract
`list_documents()`. Concrete implementation lives in `src/db/minio/backend.py`
(`MinioBackend.list_documents()` delegates to `_mn_list_documents`).
Public facade `src/db/__init__.py` exports `list_documents` in `__all__`.

**`src/vector_db/backend.py`** — `VectorBackend` ABC extended with abstract
`aggregate_by_source()`, `get_collection_stats()`, `list_collections()`.
Concrete implementations in `src/vector_db/weaviate/backend.py`
(`WeaviateBackend`) delegate to the store functions.
Public facade `src/vector_db/__init__.py` exports all three in `__all__`.
`_resolve_collection(collection)` substitutes the configured default when
`collection` is `None`.

**`server/routes/__init__.py`** — exports `create_documents_router`.

---

## 3. Data Flow

### `GET /api/v1/documents`

```
list_documents_endpoint
  → db.list_documents(db_client, limit=1000)           [MinIO: full bucket scan]
  → vector_db.aggregate_by_source(vector_client, ...)  [Weaviate: group_by agg]
      (on failure: chunk_count=null, connector="unknown" for all docs)
  → filter by source_filter / connector_filter
  → sort by source ASC → slice [offset:offset+limit]
  → DocumentListResponse
```

### `GET /api/v1/documents/{document_id}`

```
get_document_endpoint
  → db.get_document(db_client, document_id)   [MinIO: GET .md + .meta.json]
      None → 404
  → vector_db.aggregate_by_source(vector_client)   [find chunk_count for key]
      (on failure: chunk_count=None, silently)
  → DocumentDetailResponse
```

### `GET /api/v1/documents/{document_id}/url`

```
get_document_url_endpoint
  → db.document_exists(db_client, document_id)   [MinIO: stat_object]
      False → 404
  → db.get_document_url(db_client, document_id, expires_in_seconds=expires_in)
  → DocumentUrlResponse
```

### `GET /api/v1/sources`

```
list_sources_endpoint
  → vector_db.aggregate_by_source(vector_client, connector_filter=...)
      (on failure: 503)
  → group rows by (source, connector) → sum document_count, chunk_count
  → sort by source ASC → slice [offset:offset+limit]
  → SourceListResponse
```

### Collection endpoints

```
GET /collections       → vector_db.list_collections(vector_client)
GET /collections/{n}/stats → vector_db.get_collection_stats(vector_client, n)
                              None → 404
```

---

## 4. Configuration

| Variable | Default | Used by |
|----------|---------|---------|
| `MINIO_ENDPOINT` | `localhost:9000` | MinIO client |
| `MINIO_ACCESS_KEY` | — | MinIO client |
| `MINIO_SECRET_KEY` | — | MinIO client |
| `MINIO_BUCKET` | `rag-documents` | `list_documents` default bucket |
| `MINIO_SECURE` | `False` | TLS toggle |
| `WEAVIATE_COLLECTION_NAME` | `Documents` | Default collection for aggregation |

**Pagination caps** (enforced by FastAPI `Query` annotations, not runtime config):
- `/api/v1/documents`: max `limit` = 100
- `/api/v1/sources`: max `limit` = 500

**Presigned URL expiry:** `expires_in` query param; range 60–86400 s,
default 3600 s. MinIO server clock must be in sync with clients.

---

## 5. Error Handling

| HTTP Code | Trigger | Response body |
|-----------|---------|---------------|
| 401 | Auth fails | Delegated to `authenticate_request` middleware |
| 404 | Document or collection not found | `ApiErrorResponse(error.code="not_found")` |
| 422 | Query param out of range | FastAPI default validation response |
| 503 | Backend unreachable or raises | `ApiErrorResponse(error.code="service_unavailable")` |

**Per-store contract:**

| Store | Condition | Behavior |
|-------|-----------|----------|
| MinIO | Sidecar `.meta.json` missing | WARNING logged; `source_key` = object name stem |
| MinIO | `S3Error` from `list_objects` | Propagated → 503 |
| MinIO | `NoSuchKey` from `get_document` | Returns `None` → 404 |
| Weaviate | Collection not found | `aggregate_by_source` raises `KeyError`; `get_collection_stats` returns `None` → 404 |
| Weaviate | `WeaviateQueryError` | Propagated → 503 |
| Weaviate | `WeaviateConnectionError` | Propagated → 503 |

`GET /api/v1/documents` is the only endpoint that degrades gracefully on
Weaviate failure (returns 200 with `chunk_count: null`). All other
Weaviate-dependent endpoints return 503.

---

## 6. Extension Points

### Adding a New Document Store Backend

1. Implement `list_documents()` in the new store module, matching the MinIO
   return shape (`document_id`, `source_key`, `size_bytes`, `last_modified`).
2. Implement `list_documents()` as a concrete method on the new
   `DocumentBackend` subclass.
3. Register the backend in `src/db/__init__.py` via `_get_db_backend()`.
4. No changes needed in the route module — it calls only `db.list_documents()`.

### Adding a New Vector Store Backend

Same pattern for `VectorBackend`: implement `aggregate_by_source()`,
`get_collection_stats()`, and `list_collections()` in the new store module
and backend class.

### Adding a New Endpoint

1. Add Pydantic models to `server/schemas.py` if the response shape is new.
2. Add any required backend function to the store module, wire through the ABC
   and public facade.
3. Add the handler inside `create_documents_router()` — keep it thin.
4. Include the new error models in `standard_error_responses`.
5. Add schema contract tests in `tests/server/`.

---

## 7. Troubleshooting

**`chunk_count` is always `null` in `/api/v1/documents`**
Weaviate is unreachable. Check connectivity and confirm
`WEAVIATE_COLLECTION_NAME` exists. Look for
`"Weaviate aggregate_by_source unavailable"` in server logs (WARNING level).

**`GET /api/v1/documents` is slow (> 500 ms)**
MinIO `list_objects` is O(N objects). Use `prefix` filtering to narrow the
scan, or reduce `limit`. If the bucket has > 10 000 objects, consider adding
a document-registry table to avoid full scans.

**`GET /api/v1/collections/{name}/stats` is slow**
`get_collection_stats()` issues three sequential Weaviate aggregate queries.
Merge into a single GraphQL query or cache with a short TTL to reduce latency.

**HTTP 503 on `/api/v1/sources` but `/api/v1/documents` returns 200**
`/sources` is Weaviate-only and does not degrade gracefully. Check Weaviate.
`/documents` falls back to MinIO-only data when Weaviate is unavailable.

**`connector` shows `"unknown"` for all documents**
Chunks were ingested without a `connector` property. Check the ingestion
pipeline's metadata tagging for the relevant connector type.

**Presigned URLs expire immediately**
MinIO server clock and application server clock are out of sync. Use NTP.

**404 on a document you know was ingested**
The document ID is UUID5 from `source_key`. If `source_key` changed between
ingestion runs (e.g., path normalization), the ID changed. Re-query
`/api/v1/documents` to find the current ID.
