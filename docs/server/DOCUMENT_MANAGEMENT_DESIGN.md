> **Document type:** Design document (Layer 4)
> **Upstream spec:** DOCUMENT_MANAGEMENT_SPEC.md
> **Downstream:** DOCUMENT_MANAGEMENT_ENGINEERING_GUIDE.md
> **Last updated:** 2026-03-27

# Document & Collection Management API — Design (v1.0.0)

---

## 1. Task Decomposition

### Wave 0 — Pydantic Schemas (no dependencies)

**Task W0-A: Add document management schemas to `server/schemas.py`**

- Implements: FR-3060, FR-3061, FR-3062, FR-3063, FR-3064, FR-3065, FR-3066, FR-3067
- Files modified: `server/schemas.py`
- Dependencies: none

Models to add:

| Model | Key fields |
|---|---|
| `DocumentSummary` | `document_id`, `source`, `source_key`, `connector`, `chunk_count: Optional[int]`, `ingested_at: Optional[str]` |
| `DocumentListResponse` | `documents: list[DocumentSummary]`, `total`, `limit`, `offset` |
| `DocumentDetailResponse` | `document_id`, `content`, `metadata: dict`, `chunk_count: Optional[int]` |
| `DocumentUrlResponse` | `document_id`, `url`, `expires_in` |
| `SourceSummary` | `source`, `connector`, `document_count`, `chunk_count` |
| `SourceListResponse` | `sources: list[SourceSummary]`, `total`, `limit`, `offset` |
| `CollectionItem` | `collection_name`, `chunk_count` |
| `CollectionStatsResponse` | `collection_name`, `document_count`, `chunk_count`, `connector_breakdown: dict[str, int]` |
| `CollectionListResponse` | `collections: list[CollectionItem]` |

---

### Wave 1 — MinIO Backend Function (depends on: nothing)

**Task W1-A: Add `list_documents()` to `src/db/minio/store.py`**

- Implements: FR-3040
- Files modified: `src/db/minio/store.py`
- Dependencies: none

**Task W1-B: Extend `DocumentBackend` ABC and `src/db/__init__.py`**

- Implements: FR-3041
- Files modified: `src/db/backend.py`, `src/db/__init__.py`
- Dependencies: W1-A (concrete implementation must exist before ABC is made abstract)

---

### Wave 2 — Weaviate Backend Functions (depends on: nothing)

**Task W2-A: Add `aggregate_by_source()` to `src/vector_db/weaviate/store.py`**

- Implements: FR-3050
- Files modified: `src/vector_db/weaviate/store.py`
- Dependencies: none

**Task W2-B: Add `get_collection_stats()` to `src/vector_db/weaviate/store.py`**

- Implements: FR-3051
- Files modified: `src/vector_db/weaviate/store.py`
- Dependencies: none

**Task W2-C: Add `list_collections()` to `src/vector_db/weaviate/store.py`**

- Implements: FR-3052
- Files modified: `src/vector_db/weaviate/store.py`
- Dependencies: none

---

### Wave 3 — Public API Facade Extensions (depends on: Wave 1, Wave 2)

**Task W3-A: Extend `VectorBackend` ABC and `src/vector_db/__init__.py`**

- Implements: FR-3053
- Files modified: `src/vector_db/backend.py`, `src/vector_db/__init__.py`
- Dependencies: W2-A, W2-B, W2-C

---

### Wave 4 — Route Module (depends on: Wave 0, Wave 3)

**Task W4-A: Create `server/routes/documents.py`**

- Implements: FR-3000, FR-3001, FR-3010, FR-3011, FR-3020, FR-3030, FR-3031, FR-3070, FR-3071
- Files created: `server/routes/documents.py`
- Dependencies: W0-A, W1-B, W3-A

**Task W4-B: Register router in `server/routes/__init__.py`**

- Implements: AC-3070-1
- Files modified: `server/routes/__init__.py`
- Dependencies: W4-A

---

### Wave 5 — Contract Tests (depends on: Wave 0)

**Task W5-A: Schema contract tests**

- Implements: FR-3068
- Files created: `tests/server/test_document_management_schemas.py`
- Dependencies: W0-A

---

## 2. Code Contracts

### Wave 0: Schemas (`server/schemas.py`)

```python
class DocumentSummary(BaseModel):
    document_id: str
    source: str
    source_key: str
    connector: str
    chunk_count: Optional[int] = None
    ingested_at: Optional[str] = None

class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary] = []
    total: int
    limit: int
    offset: int

class DocumentDetailResponse(BaseModel):
    document_id: str
    content: str
    metadata: dict
    chunk_count: Optional[int] = None

class DocumentUrlResponse(BaseModel):
    document_id: str
    url: str
    expires_in: int

class SourceSummary(BaseModel):
    source: str
    connector: str
    document_count: int
    chunk_count: int

class SourceListResponse(BaseModel):
    sources: list[SourceSummary] = []
    total: int
    limit: int
    offset: int

class CollectionItem(BaseModel):
    collection_name: str
    chunk_count: int

class CollectionStatsResponse(BaseModel):
    collection_name: str
    document_count: int
    chunk_count: int
    connector_breakdown: dict[str, int]

class CollectionListResponse(BaseModel):
    collections: list[CollectionItem]
```

---

### Wave 1: MinIO (`src/db/minio/store.py`)

```python
def list_documents(
    client: Minio,
    bucket: str = MINIO_BUCKET,
    prefix: str = "",
    limit: int = 1000,
    offset: int = 0,
) -> list[dict]:
    """List content objects in a bucket, excluding metadata sidecars.

    Each returned dict contains:
        document_id (str)  — UUID derived from source_key via build_document_id()
        source_key  (str)  — read from .meta.json sidecar
        size_bytes  (int)  — object size
        last_modified (str) — ISO-8601 timestamp

    Raises:
        S3Error: propagated if the bucket is unreachable (not NoSuchBucket/NoSuchKey).
    """
```

**Behavior notes:**
- Calls `client.list_objects(bucket, prefix=prefix, recursive=True)`.
- Filters to objects ending with `_CONTENT_SUFFIX` (`.md`).
- For each matched object, fetches its `.meta.json` sidecar to extract `source_key`; if sidecar is missing, `source_key` defaults to the object name stem.
- Applies Python-side slice `[offset : offset + limit]` after collecting all matching objects (MinIO has no server-side offset).
- Creates a tracing span `"document_store.list_documents"`.

**`DocumentBackend` ABC extension (`src/db/backend.py`):**

```python
@abstractmethod
def list_documents(
    self,
    client: Any,
    bucket: Optional[str] = None,
    prefix: str = "",
    limit: int = 1000,
    offset: int = 0,
) -> list[dict]:
    ...
```

**`src/db/__init__.py` public facade:**

```python
def list_documents(
    client: Any,
    bucket: Optional[str] = None,
    prefix: str = "",
    limit: int = 1000,
    offset: int = 0,
) -> list[dict]:
    """List documents from the document store.

    Returns:
        List of dicts with document_id, source_key, size_bytes, last_modified.

    Raises:
        S3Error / backend-specific: if the store is unreachable.
    """
    return _get_db_backend().list_documents(client, bucket, prefix, limit, offset)
```

Add `"list_documents"` to `__all__`.

---

### Wave 2: Weaviate (`src/vector_db/weaviate/store.py`)

```python
def aggregate_by_source(
    client: weaviate.WeaviateClient,
    collection: str = WEAVIATE_COLLECTION_NAME,
    source_filter: Optional[str] = None,
    connector_filter: Optional[str] = None,
) -> list[dict]:
    """Return chunk counts grouped by source_key.

    Each returned dict contains:
        source_key  (str)
        source      (str)
        connector   (str)
        chunk_count (int)

    Uses Weaviate aggregate + groupBy on source_key.
    Applies source_filter as a LIKE/Contains filter when provided.
    Applies connector_filter as an Equal filter when provided.

    Raises:
        weaviate.exceptions.WeaviateQueryError: on query failure.
        KeyError: if the collection does not exist.
    """
```

```python
def get_collection_stats(
    client: weaviate.WeaviateClient,
    collection: str = WEAVIATE_COLLECTION_NAME,
) -> Optional[dict]:
    """Return aggregate statistics for a collection.

    Returns dict with:
        chunk_count         (int)  — total object count
        document_count      (int)  — distinct source_key values
        connector_breakdown (dict[str, int]) — chunk count per connector

    Returns None if the collection does not exist.
    Uses aggregate queries only (no full object iteration).

    Raises:
        weaviate.exceptions.WeaviateQueryError: on unexpected query failure.
    """
```

```python
def list_collections(
    client: weaviate.WeaviateClient,
) -> list[dict]:
    """Return all collections visible to this client.

    Each returned dict contains:
        collection_name (str)
        chunk_count     (int)

    Uses client.collections.list_all() for enumeration.
    chunk_count is obtained via a count aggregate per collection.

    Raises:
        weaviate.exceptions.WeaviateConnectionError: if client is not connected.
    """
```

---

### Wave 3: VectorBackend ABC + public facade

**`VectorBackend` ABC extensions (`src/vector_db/backend.py`):**

```python
@abstractmethod
def aggregate_by_source(
    self,
    client: Any,
    collection: Optional[str] = None,
    source_filter: Optional[str] = None,
    connector_filter: Optional[str] = None,
) -> list[dict]: ...

@abstractmethod
def get_collection_stats(
    self,
    client: Any,
    collection: Optional[str] = None,
) -> Optional[dict]: ...

@abstractmethod
def list_collections(self, client: Any) -> list[dict]: ...
```

**`src/vector_db/__init__.py` public facades:**

```python
def aggregate_by_source(
    client: Any,
    collection: Optional[str] = None,
    source_filter: Optional[str] = None,
    connector_filter: Optional[str] = None,
) -> list[dict]:
    """Group chunk counts by source_key, with optional filters."""
    return _get_vector_backend().aggregate_by_source(
        client, _resolve_collection(collection), source_filter, connector_filter
    )

def get_collection_stats(
    client: Any,
    collection: Optional[str] = None,
) -> Optional[dict]:
    """Return aggregate stats for a collection; None if it does not exist."""
    return _get_vector_backend().get_collection_stats(
        client, _resolve_collection(collection)
    )

def list_collections(client: Any) -> list[dict]:
    """Return all collections with their chunk counts."""
    return _get_vector_backend().list_collections(client)
```

Add `"aggregate_by_source"`, `"get_collection_stats"`, `"list_collections"` to `__all__`.

---

### Wave 4: Route module (`server/routes/documents.py`)

**Factory function (mirrors `create_query_router`):**

```python
def create_documents_router(
    db_client: Any,
    vector_client: Any,
) -> APIRouter:
    """Return a FastAPI router with all document management endpoints."""
```

**Endpoint signatures:**

```python
@router.get("/api/v1/documents", response_model=DocumentListResponse)
async def list_documents_endpoint(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    source_filter: Optional[str] = Query(None, max_length=500),
    connector_filter: Optional[str] = Query(None, max_length=100),
    collection: Optional[str] = Query(None, max_length=128),
    principal: Principal = Depends(authenticate_request),
) -> DocumentListResponse: ...

@router.get("/api/v1/documents/{document_id}", response_model=DocumentDetailResponse)
async def get_document_endpoint(
    document_id: str,
    principal: Principal = Depends(authenticate_request),
) -> DocumentDetailResponse: ...

@router.get("/api/v1/documents/{document_id}/url", response_model=DocumentUrlResponse)
async def get_document_url_endpoint(
    document_id: str,
    expires_in: int = Query(3600, ge=60, le=86400),
    principal: Principal = Depends(authenticate_request),
) -> DocumentUrlResponse: ...

@router.get("/api/v1/sources", response_model=SourceListResponse)
async def list_sources_endpoint(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    connector_filter: Optional[str] = Query(None, max_length=100),
    collection: Optional[str] = Query(None, max_length=128),
    principal: Principal = Depends(authenticate_request),
) -> SourceListResponse: ...

@router.get("/api/v1/collections", response_model=CollectionListResponse)
async def list_collections_endpoint(
    principal: Principal = Depends(authenticate_request),
) -> CollectionListResponse: ...

@router.get("/api/v1/collections/{collection_name}/stats", response_model=CollectionStatsResponse)
async def get_collection_stats_endpoint(
    collection_name: str,
    principal: Principal = Depends(authenticate_request),
) -> CollectionStatsResponse: ...
```

**Error handling helpers (internal to module):**

```python
def _not_found(document_id: str) -> HTTPException:
    """Return HTTP 404 with ApiErrorResponse body."""

def _service_unavailable(detail: str) -> HTTPException:
    """Return HTTP 503 with ApiErrorResponse body."""
```

**`server/routes/__init__.py` addition:**

```python
from server.routes.documents import create_documents_router

__all__ = [
    ...,
    "create_documents_router",
]
```

---

## 3. Dependency DAG

```
W0-A (schemas)
    │
    ├──────────────────────────────┐
    │                              │
W1-A (minio list_documents)   W2-A (weaviate aggregate_by_source)
W1-B (db ABC + facade)        W2-B (weaviate get_collection_stats)
    │                         W2-C (weaviate list_collections)
    │                              │
    │                         W3-A (vector_db ABC + facade)
    │                              │
    └──────────────┬───────────────┘
                   │
              W4-A (documents route module)
                   │
              W4-B (router factory export)

W0-A ──► W5-A (schema contract tests)   [independent of W1–W4]
```

Wave 1 (W1-A, W1-B) and Wave 2 (W2-A, W2-B, W2-C) are fully independent and can be executed in parallel. W3-A may not start until all of Wave 2 is complete. W4-A may not start until W0-A, W1-B, and W3-A are complete.

---

## 4. Error Matrix

| Function | Error condition | Behavior |
|---|---|---|
| `minio.store.list_documents` | Bucket unreachable (`S3Error` other than NoSuchBucket) | Re-raise; caller handles as 503 |
| `minio.store.list_documents` | Sidecar `.meta.json` missing for an object | Log WARNING, use object name stem as `source_key` |
| `db.get_document` (existing) | Object not found (`NoSuchKey`) | Return `None` → route returns 404 |
| `weaviate.store.aggregate_by_source` | Collection not found | Raise `KeyError`; route catches as 404 |
| `weaviate.store.aggregate_by_source` | Weaviate unreachable | Raise `WeaviateConnectionError`; route catches as 503 |
| `weaviate.store.get_collection_stats` | Collection not found | Return `None`; route returns 404 |
| `weaviate.store.get_collection_stats` | Weaviate unreachable | Raise `WeaviateConnectionError`; route catches as 503 |
| `weaviate.store.list_collections` | Weaviate unreachable | Raise `WeaviateConnectionError`; route catches as 503 |
| Route: `list_documents_endpoint` | Weaviate unreachable (FR-3001 AC-3001-3) | Return documents from MinIO with `chunk_count: null`; do not fail the request |
| Route: `get_document_endpoint` | Document not found in MinIO | HTTP 404, `ApiErrorResponse` |
| Route: `get_document_url_endpoint` | Document not found in MinIO | HTTP 404, `ApiErrorResponse` |
| Route: `get_collection_stats_endpoint` | Collection not found | HTTP 404, `ApiErrorResponse` |
| Any route | MinIO/Weaviate backend raises unexpected exception | HTTP 503, `ApiErrorResponse`, log at ERROR with structured context |
| Any route | Query param constraint violated | HTTP 422, FastAPI default validation response |
| Any route | Authentication fails | HTTP 401, delegated to `authenticate_request` |

**503 envelope (used by `_service_unavailable`):**

```python
raise HTTPException(
    status_code=503,
    detail=ApiErrorResponse(
        error="service_unavailable",
        message=detail,
    ).model_dump(),
)
```

**404 envelope (used by `_not_found`):**

```python
raise HTTPException(
    status_code=404,
    detail=ApiErrorResponse(
        error="not_found",
        message=f"Document '{document_id}' not found.",
    ).model_dump(),
)
```

---

## 5. NFR Constraints on Implementation

| NFR | Implementation note |
|---|---|
| NFR-3000 latency | `aggregate_by_source` must use Weaviate `aggregate()`, never full `query.get()` iteration |
| NFR-3001 pagination | Enforce `le=100` on `/documents` and `le=500` on `/sources` via FastAPI `Query(...)` |
| NFR-3002 backward compat | New ABC methods get concrete implementations in `MinioBackend`/`WeaviateBackend` before being declared `@abstractmethod` |
| NFR-3003 observability | Each new store function wraps its body in a `tracer.start_span(...)` / `span.end(...)` block, consistent with existing functions |
| NFR-3004 tenant isolation | All route handlers call `resolve_tenant_id(principal)` and pass the result as a Weaviate `Filter` when the tenant is not the system default |
