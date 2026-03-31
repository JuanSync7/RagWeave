> **Document type:** Authoritative requirements specification (Layer 3)
> **Downstream:** DOCUMENT_MANAGEMENT_DESIGN.md, DOCUMENT_MANAGEMENT_ENGINEERING_GUIDE.md
> **Last updated:** 2026-03-27

# Document & Collection Management API --- Specification (v1.0.0)

**AION RAG Server API**
Version: 1.0.0 | Status: Draft | Domain: Server / Document Browsing

## Document Information

> **Document intent:** This is a formal specification for a **read-only Document & Collection Management API** that enables browsing, retrieving, and inspecting ingested documents and vector collections. The system can already ingest and query; this spec adds the missing ability to list and inspect what has been ingested.
> For existing server API requirements, see `SERVER_API_SPEC.md`.
> For existing ingestion pipeline requirements, see `docs/ingestion/`.

| Field | Value |
|-------|-------|
| System | AION RAG Server API |
| Document Type | Subsystem Specification --- Document & Collection Management |
| Companion Documents | SERVER_API_SPEC.md, PLATFORM_SERVICES_SPEC.md |
| Version | 1.0.0 |
| Status | Draft |
| Supersedes | None (new subsystem) |

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-03-27 | AI Assistant | Initial specification; FR-3000 through FR-3099 |

---

## 1. Scope

### 1.1 In Scope

- Read-only HTTP endpoints for browsing ingested documents and vector collections.
- New backend functions in the document store (`src/db`) and vector store (`src/vector_db`) subsystems to support listing and aggregation.
- Pydantic request/response schemas for all new endpoints.
- Contract tests for new schemas.

### 1.2 Out of Scope

- Mutation endpoints (create, update, delete). Ingestion and deletion are handled by existing pipelines.
- Full-text search over document content (use the existing `/query` endpoint).
- Admin-only collection management (drop, recreate). These exist in the admin routes.

### 1.3 Definitions

| Term | Definition |
|------|-----------|
| **Document** | A source document stored in MinIO (content `.md` + metadata `.meta.json` sidecar). |
| **Chunk** | A vector-embedded segment of a document stored in Weaviate. |
| **Collection** | A named Weaviate collection containing chunks (default: `WEAVIATE_COLLECTION_NAME`). |
| **Source** | The `source` metadata property on Weaviate chunks --- the filename or path of the originating document. |
| **Connector** | The `connector` metadata property identifying the ingestion connector that produced the document (e.g. `local_fs`, `confluence`). |
| **Document ID** | Deterministic UUID5 derived from `source_key` via `build_document_id()`. |

---

## 2. Functional Requirements

### 2.1 Document Listing --- FR-3000 through FR-3009

#### FR-3000: List Ingested Documents

The system SHALL expose `GET /api/v1/documents` returning a paginated list of ingested documents.

**Request parameters** (query string):

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `limit` | int | 20 | 1--100 | Maximum items per page |
| `offset` | int | 0 | >= 0 | Number of items to skip |
| `source_filter` | str | None | max 500 chars | Substring match on source name |
| `connector_filter` | str | None | max 100 chars | Exact match on connector type |
| `collection` | str | None | max 128 chars | Target collection (default if omitted) |

**Acceptance criteria:**
- AC-3000-1: Returns JSON array of document summary objects with `document_id`, `source`, `source_key`, `connector`, `chunk_count`, and `ingested_at` fields.
- AC-3000-2: Response includes `total` count, `limit`, and `offset` for pagination.
- AC-3000-3: When `source_filter` is provided, only documents whose `source` contains the substring are returned.
- AC-3000-4: When `connector_filter` is provided, only documents matching that connector are returned.
- AC-3000-5: Results are ordered by `source` ascending.

#### FR-3001: Document List Aggregation

The document listing endpoint SHALL aggregate data from both MinIO (source document existence) and Weaviate (chunk counts per source).

**Acceptance criteria:**
- AC-3001-1: Each document summary includes `chunk_count` derived from Weaviate group-by aggregation on `source_key`.
- AC-3001-2: Documents present in MinIO but with zero chunks in Weaviate are included with `chunk_count: 0`.
- AC-3001-3: If Weaviate is unreachable, the endpoint returns documents from MinIO alone with `chunk_count: null`.

---

### 2.2 Document Detail --- FR-3010 through FR-3019

#### FR-3010: Get Document by ID

The system SHALL expose `GET /api/v1/documents/{document_id}` returning the full content and metadata of a single document.

**Acceptance criteria:**
- AC-3010-1: Returns `document_id`, `content`, `metadata`, and `chunk_count` fields.
- AC-3010-2: Returns HTTP 404 with `ApiErrorResponse` if the document does not exist.
- AC-3010-3: Delegates to the existing `get_document()` backend function.

#### FR-3011: Get Document Download URL

The system SHALL expose `GET /api/v1/documents/{document_id}/url` returning a presigned download URL.

**Request parameters** (query string):

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `expires_in` | int | 3600 | 60--86400 | URL validity in seconds |

**Acceptance criteria:**
- AC-3011-1: Returns JSON with `document_id` and `url` fields.
- AC-3011-2: The `url` is a presigned MinIO URL valid for `expires_in` seconds.
- AC-3011-3: Returns HTTP 404 if the document does not exist.
- AC-3011-4: Delegates to the existing `get_document_url()` backend function.

---

### 2.3 Source Listing --- FR-3020 through FR-3029

#### FR-3020: List Document Sources

The system SHALL expose `GET /api/v1/sources` returning a list of unique document sources with summary statistics.

**Request parameters** (query string):

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `limit` | int | 50 | 1--500 | Maximum items per page |
| `offset` | int | 0 | >= 0 | Number of items to skip |
| `connector_filter` | str | None | max 100 chars | Filter by connector type |
| `collection` | str | None | max 128 chars | Target collection |

**Acceptance criteria:**
- AC-3020-1: Returns JSON array of source summary objects with `source`, `connector`, `document_count`, and `chunk_count` fields.
- AC-3020-2: Response includes `total`, `limit`, and `offset` for pagination.
- AC-3020-3: Sources are derived from distinct `source` values in Weaviate metadata.
- AC-3020-4: `document_count` reflects distinct `source_key` values per source.

---

### 2.4 Collection Statistics --- FR-3030 through FR-3039

#### FR-3030: Get Collection Stats

The system SHALL expose `GET /api/v1/collections/{collection_name}/stats` returning aggregate statistics for a vector collection.

**Acceptance criteria:**
- AC-3030-1: Returns `collection_name`, `document_count` (distinct `source_key`), `chunk_count` (total objects), and `connector_breakdown` (chunk count per connector).
- AC-3030-2: Returns HTTP 404 if the collection does not exist.
- AC-3030-3: Uses Weaviate aggregate queries, not full object iteration.

#### FR-3031: List Collections

The system SHALL expose `GET /api/v1/collections` returning a list of existing vector collections.

**Acceptance criteria:**
- AC-3031-1: Returns JSON array of objects with `collection_name` and `chunk_count` fields.
- AC-3031-2: Enumerates all collections visible to the configured Weaviate client.

---

### 2.5 Backend: MinIO List Documents --- FR-3040 through FR-3049

#### FR-3040: MinIO `list_documents` Function

A new `list_documents()` function SHALL be added to `src/db/minio/store.py` that enumerates document objects in a bucket.

**Signature:**
```python
def list_documents(
    client: Minio,
    bucket: str = MINIO_BUCKET,
    prefix: str = "",
    limit: int = 1000,
    offset: int = 0,
) -> list[dict]:
```

**Acceptance criteria:**
- AC-3040-1: Returns a list of dicts with `document_id`, `source_key`, `size_bytes`, and `last_modified` for each content object (`.md` suffix).
- AC-3040-2: Excludes metadata sidecar objects (`.meta.json` suffix) from the result list.
- AC-3040-3: Applies `prefix` filtering at the MinIO `list_objects` level.
- AC-3040-4: Applies `offset` and `limit` for pagination.
- AC-3040-5: Reads the metadata sidecar for each matched object to extract `source_key`.

#### FR-3041: Backend ABC and Public API Extension

The `DocumentBackend` ABC SHALL be extended with a `list_documents()` abstract method, and `src/db/__init__.py` SHALL expose a corresponding `list_documents()` public function.

**Acceptance criteria:**
- AC-3041-1: `DocumentBackend.list_documents()` is abstract with the same parameter semantics as FR-3040.
- AC-3041-2: `src/db/__init__.py` exports `list_documents` in `__all__`.
- AC-3041-3: Existing backends (`MinioBackend`) implement the new method.

---

### 2.6 Backend: Weaviate Aggregation --- FR-3050 through FR-3059

#### FR-3050: Weaviate `aggregate_by_source` Function

A new `aggregate_by_source()` function SHALL be added to `src/vector_db/weaviate/store.py` that returns chunk counts grouped by `source_key`.

**Signature:**
```python
def aggregate_by_source(
    client: weaviate.WeaviateClient,
    collection: str = WEAVIATE_COLLECTION_NAME,
    source_filter: Optional[str] = None,
    connector_filter: Optional[str] = None,
) -> list[dict]:
```

**Acceptance criteria:**
- AC-3050-1: Returns list of dicts with `source_key`, `source`, `connector`, and `chunk_count`.
- AC-3050-2: Uses Weaviate's `aggregate` or `group_by` API, not full object iteration.
- AC-3050-3: Applies optional `source_filter` (substring) and `connector_filter` (exact) at the query level.

#### FR-3051: Weaviate `get_collection_stats` Function

A new `get_collection_stats()` function SHALL be added returning aggregate statistics for a collection.

**Signature:**
```python
def get_collection_stats(
    client: weaviate.WeaviateClient,
    collection: str = WEAVIATE_COLLECTION_NAME,
) -> dict:
```

**Acceptance criteria:**
- AC-3051-1: Returns dict with `chunk_count` (total objects), `document_count` (distinct `source_key`), and `connector_breakdown` (dict of connector to chunk count).
- AC-3051-2: Uses aggregate queries for counts.
- AC-3051-3: Returns `None` if the collection does not exist.

#### FR-3052: Weaviate `list_collections` Function

A new `list_collections()` function SHALL be added returning all collection names and their object counts.

**Acceptance criteria:**
- AC-3052-1: Returns list of dicts with `collection_name` and `chunk_count`.
- AC-3052-2: Uses Weaviate client's `collections.list_all()` for enumeration.

#### FR-3053: VectorBackend ABC and Public API Extension

The `VectorBackend` ABC SHALL be extended with `aggregate_by_source()`, `get_collection_stats()`, and `list_collections()` abstract methods. `src/vector_db/__init__.py` SHALL expose corresponding public functions.

**Acceptance criteria:**
- AC-3053-1: All three methods are abstract on `VectorBackend`.
- AC-3053-2: `src/vector_db/__init__.py` exports all three in `__all__`.
- AC-3053-3: `WeaviateBackend` implements all three methods.

---

### 2.7 Pydantic Schemas --- FR-3060 through FR-3069

#### FR-3060: Document Summary Schema

A `DocumentSummary` Pydantic model SHALL be defined in `server/schemas.py`.

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `document_id` | str | Stable UUID |
| `source` | str | Source filename/path |
| `source_key` | str | Stable source key |
| `connector` | str | Connector type |
| `chunk_count` | Optional[int] | Chunks in vector store (null if unavailable) |
| `ingested_at` | Optional[str] | ISO-8601 timestamp |

**Acceptance criteria:**
- AC-3060-1: Model validates successfully with all required fields.
- AC-3060-2: `chunk_count` is Optional, defaulting to None.

#### FR-3061: Document List Response Schema

A `DocumentListResponse` Pydantic model SHALL wrap the paginated document list.

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `documents` | list[DocumentSummary] | Page of results |
| `total` | int | Total matching documents |
| `limit` | int | Page size used |
| `offset` | int | Offset used |

**Acceptance criteria:**
- AC-3061-1: `documents` defaults to an empty list.
- AC-3061-2: `total`, `limit`, `offset` are non-negative integers.

#### FR-3062: Document Detail Response Schema

A `DocumentDetailResponse` Pydantic model SHALL be defined.

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `document_id` | str | Stable UUID |
| `content` | str | Full markdown content |
| `metadata` | dict | Document metadata |
| `chunk_count` | Optional[int] | Chunks in vector store |

**Acceptance criteria:**
- AC-3062-1: Validates with all required fields.

#### FR-3063: Document URL Response Schema

A `DocumentUrlResponse` Pydantic model SHALL be defined.

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `document_id` | str | Stable UUID |
| `url` | str | Presigned download URL |
| `expires_in` | int | Validity in seconds |

#### FR-3064: Source Summary Schema

A `SourceSummary` Pydantic model SHALL be defined.

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `source` | str | Source name |
| `connector` | str | Connector type |
| `document_count` | int | Distinct documents |
| `chunk_count` | int | Total chunks |

#### FR-3065: Source List Response Schema

A `SourceListResponse` Pydantic model SHALL wrap the paginated source list with `sources`, `total`, `limit`, `offset` fields.

#### FR-3066: Collection Stats Response Schema

A `CollectionStatsResponse` Pydantic model SHALL be defined.

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `collection_name` | str | Collection identifier |
| `document_count` | int | Distinct source_keys |
| `chunk_count` | int | Total objects |
| `connector_breakdown` | dict[str, int] | Chunks per connector |

#### FR-3067: Collection List Response Schema

A `CollectionListResponse` Pydantic model SHALL be defined with a `collections` field containing a list of objects with `collection_name` and `chunk_count`.

#### FR-3068: Schema Contract Tests

All new Pydantic models SHALL have contract tests verifying field presence, types, and default values.

**Acceptance criteria:**
- AC-3068-1: Each new model has a round-trip serialization test.
- AC-3068-2: Required field omission raises `ValidationError`.
- AC-3068-3: Tests are co-located in `tests/server/`.

---

### 2.8 Route Module --- FR-3070 through FR-3079

#### FR-3070: Documents Router

A new `server/routes/documents.py` module SHALL define a FastAPI `APIRouter` with prefix `/api/v1` containing all endpoints specified in FR-3000 through FR-3031.

**Acceptance criteria:**
- AC-3070-1: Router is created via a factory function `create_documents_router()` consistent with the existing `create_query_router()` pattern.
- AC-3070-2: All route handlers receive a `Principal` via `Depends(authenticate_request)`.
- AC-3070-3: Tenant isolation is enforced via `resolve_tenant_id()` on all endpoints.
- AC-3070-4: Route handlers are thin --- business logic delegates to backend functions.

#### FR-3071: Error Handling

All document management endpoints SHALL return `ApiErrorResponse` for error conditions.

**Acceptance criteria:**
- AC-3071-1: 404 responses use `ApiErrorResponse` with descriptive `message`.
- AC-3071-2: Backend failures (MinIO/Weaviate unreachable) return HTTP 503 with `ApiErrorResponse`.
- AC-3071-3: Invalid query parameters return HTTP 422 (FastAPI default validation).

---

## 3. Non-Functional Requirements

### NFR-3000: Latency

- Document listing (`GET /documents`) SHALL respond within 500ms for collections under 10,000 documents.
- Collection stats (`GET /collections/{name}/stats`) SHALL respond within 200ms using aggregate queries.

### NFR-3001: Pagination Safety

- All listing endpoints SHALL enforce a maximum `limit` to prevent unbounded result sets.
- No endpoint SHALL return more than 500 items in a single response.

### NFR-3002: Backward Compatibility

- No existing public API in `src/db/__init__.py` or `src/vector_db/__init__.py` SHALL change signature or behavior.
- New abstract methods on `DocumentBackend` and `VectorBackend` SHALL not break existing backend implementations during a phased rollout (implement concrete methods before making them abstract, or provide default implementations).

### NFR-3003: Observability

- All new backend functions SHALL create tracing spans via `get_tracer()` consistent with existing store modules.
- Errors SHALL be logged at WARNING or ERROR level with structured context.

### NFR-3004: Tenant Isolation

- All endpoints SHALL resolve tenant context via the existing `resolve_tenant_id()` mechanism.
- Weaviate queries SHALL include a `tenant_id` filter when the resolved tenant is not the system default.

---

## 4. Traceability Matrix

| FR ID | Endpoint / Function | Schemas | Acceptance Criteria |
|-------|-------------------|---------|-------------------|
| FR-3000 | `GET /api/v1/documents` | DocumentListResponse, DocumentSummary | AC-3000-1 through AC-3000-5 |
| FR-3001 | (aggregation logic) | -- | AC-3001-1 through AC-3001-3 |
| FR-3010 | `GET /api/v1/documents/{id}` | DocumentDetailResponse | AC-3010-1 through AC-3010-3 |
| FR-3011 | `GET /api/v1/documents/{id}/url` | DocumentUrlResponse | AC-3011-1 through AC-3011-4 |
| FR-3020 | `GET /api/v1/sources` | SourceListResponse, SourceSummary | AC-3020-1 through AC-3020-4 |
| FR-3030 | `GET /api/v1/collections/{name}/stats` | CollectionStatsResponse | AC-3030-1 through AC-3030-3 |
| FR-3031 | `GET /api/v1/collections` | CollectionListResponse | AC-3031-1 through AC-3031-2 |
| FR-3040 | `minio.store.list_documents()` | -- | AC-3040-1 through AC-3040-5 |
| FR-3041 | `DocumentBackend` ABC + public API | -- | AC-3041-1 through AC-3041-3 |
| FR-3050 | `weaviate.store.aggregate_by_source()` | -- | AC-3050-1 through AC-3050-3 |
| FR-3051 | `weaviate.store.get_collection_stats()` | -- | AC-3051-1 through AC-3051-3 |
| FR-3052 | `weaviate.store.list_collections()` | -- | AC-3052-1 through AC-3052-2 |
| FR-3053 | `VectorBackend` ABC + public API | -- | AC-3053-1 through AC-3053-3 |
| FR-3060 | -- | DocumentSummary | AC-3060-1, AC-3060-2 |
| FR-3061 | -- | DocumentListResponse | AC-3061-1, AC-3061-2 |
| FR-3062 | -- | DocumentDetailResponse | AC-3062-1 |
| FR-3063 | -- | DocumentUrlResponse | -- |
| FR-3064 | -- | SourceSummary | -- |
| FR-3065 | -- | SourceListResponse | -- |
| FR-3066 | -- | CollectionStatsResponse | -- |
| FR-3067 | -- | CollectionListResponse | -- |
| FR-3068 | Contract tests | All new models | AC-3068-1 through AC-3068-3 |
| FR-3070 | `server/routes/documents.py` | -- | AC-3070-1 through AC-3070-4 |
| FR-3071 | Error handling | ApiErrorResponse | AC-3071-1 through AC-3071-3 |
