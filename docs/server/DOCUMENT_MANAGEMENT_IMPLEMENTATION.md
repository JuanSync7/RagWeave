> **Document type:** Implementation plan (Layer 5)
> **Upstream design:** DOCUMENT_MANAGEMENT_DESIGN.md
> **Last updated:** 2026-03-27

# Document & Collection Management API — Implementation Plan (v1.0.0)

---

## Phase 0: Contract Definitions

### Files Created

| File | Purpose |
|---|---|
| `server/routes/documents.py` | New FastAPI router module |
| `tests/server/test_document_management_schemas.py` | Schema contract tests |

### Files Modified

| File | Change |
|---|---|
| `server/schemas.py` | Add 9 new Pydantic models |
| `src/db/minio/store.py` | Add `list_documents()` function |
| `src/db/minio/backend.py` | Implement `list_documents()` on `MinioBackend` |
| `src/db/backend.py` | Add `list_documents()` abstract method |
| `src/db/__init__.py` | Add `list_documents()` facade + extend `__all__` |
| `src/vector_db/weaviate/store.py` | Add `aggregate_by_source()`, `get_collection_stats()`, `list_collections()` |
| `src/vector_db/weaviate/backend.py` | Implement three new methods on `WeaviateBackend` |
| `src/vector_db/backend.py` | Add three abstract methods |
| `src/vector_db/__init__.py` | Add three facade functions + extend `__all__` |
| `server/routes/__init__.py` | Export `create_documents_router` |

### Import Surface

```python
# server/schemas.py — new exports
from server.schemas import (
    DocumentSummary, DocumentListResponse,
    DocumentDetailResponse, DocumentUrlResponse,
    SourceSummary, SourceListResponse,
    CollectionItem, CollectionStatsResponse, CollectionListResponse,
)

# src/db/__init__.py — new export
from src.db import list_documents

# src/vector_db/__init__.py — new exports
from src.vector_db import aggregate_by_source, get_collection_stats, list_collections

# server/routes/__init__.py — new export
from server.routes import create_documents_router
```

### Stub Contracts (raise NotImplementedError)

```python
# src/db/minio/store.py
def list_documents(
    client: Minio,
    bucket: str = MINIO_BUCKET,
    prefix: str = "",
    limit: int = 1000,
    offset: int = 0,
) -> list[dict]:
    raise NotImplementedError

# src/vector_db/weaviate/store.py
def aggregate_by_source(
    client: weaviate.WeaviateClient,
    collection: str = WEAVIATE_COLLECTION_NAME,
    source_filter: Optional[str] = None,
    connector_filter: Optional[str] = None,
) -> list[dict]:
    raise NotImplementedError

def get_collection_stats(
    client: weaviate.WeaviateClient,
    collection: str = WEAVIATE_COLLECTION_NAME,
) -> Optional[dict]:
    raise NotImplementedError

def list_collections(
    client: weaviate.WeaviateClient,
) -> list[dict]:
    raise NotImplementedError

# server/routes/documents.py
def create_documents_router(db_client: Any, vector_client: Any) -> APIRouter:
    raise NotImplementedError
```

---

## Task W0-A: Pydantic Schemas

**FR:** FR-3060 through FR-3067
**Files modified:** `server/schemas.py`

### Steps

1. Open `server/schemas.py`. Append after existing models (before `__all__` if present).
2. Add these models in order — each has a docstring:

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

3. `Optional` is already imported in `server/schemas.py` — no new imports needed.

**Agent isolation:** Receive this section only. Read the first 10 lines of `server/schemas.py` for the existing import block, then append the models above.

---

## Task W1-A: MinIO `list_documents()`

**FR:** FR-3040
**Files modified:** `src/db/minio/store.py`

### Steps

1. Read `src/db/minio/store.py` for context: `_CONTENT_SUFFIX`, `_METADATA_SUFFIX`, `build_document_id`, tracer pattern.
2. Add the function after `get_document_url`:

```python
def list_documents(
    client: Minio,
    bucket: str = MINIO_BUCKET,
    prefix: str = "",
    limit: int = 1000,
    offset: int = 0,
) -> list[dict]:
    """List content objects in a bucket, excluding metadata sidecars.

    Returns dicts with: document_id, source_key, size_bytes, last_modified (ISO-8601).
    Sidecars (.meta.json) are excluded from results.
    Applies Python-side pagination (offset/limit) after collecting all matches.
    Logs WARNING and falls back to object name stem when sidecar is missing.

    Raises:
        S3Error: re-raised if bucket is unreachable (not NoSuchKey/NoSuchBucket).
    """
    span = tracer.start_span(
        "document_store.list_documents",
        {"bucket": bucket, "prefix": prefix, "limit": limit, "offset": offset},
    )
    results = []
    for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
        name: str = obj.object_name
        if not name.endswith(_CONTENT_SUFFIX):
            continue
        stem = name[: -len(_CONTENT_SUFFIX)]
        source_key = stem
        try:
            resp = client.get_object(bucket, f"{stem}{_METADATA_SUFFIX}")
            meta = json.loads(resp.read().decode("utf-8"))
            resp.close()
            resp.release_conn()
            source_key = meta.get("source_key", stem)
        except S3Error:
            logger.warning(
                "list_documents: sidecar missing for %r; using stem as source_key", name
            )
        results.append({
            "document_id": build_document_id(source_key),
            "source_key": source_key,
            "size_bytes": obj.size,
            "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
        })
    span.end(status="ok")
    return results[offset : offset + limit]
```

**Agent isolation:** Receive this section + Phase 0 contracts. Read `src/db/minio/store.py` in full for pattern context.

---

## Task W1-B: `DocumentBackend` ABC + `src/db` Facade

**FR:** FR-3041
**Files modified:** `src/db/backend.py`, `src/db/minio/backend.py`, `src/db/__init__.py`

### Steps

**`src/db/backend.py`** — add abstract method after `get_document_url`:

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
    """List documents. Returns dicts with document_id, source_key, size_bytes, last_modified."""
    ...
```

**`src/db/minio/backend.py`** — add import and concrete method on `MinioBackend`:

```python
# add to imports at top
from src.db.minio.store import list_documents as _mn_list_documents

# add method to MinioBackend class
def list_documents(
    self,
    client: Any,
    bucket: Optional[str] = None,
    prefix: str = "",
    limit: int = 1000,
    offset: int = 0,
) -> list[dict]:
    return _mn_list_documents(
        client, bucket=self._bucket(bucket), prefix=prefix, limit=limit, offset=offset
    )
```

**`src/db/__init__.py`** — add facade function (insert after `get_document_url`):

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
        S3Error: if the store is unreachable.
    """
    return _get_db_backend().list_documents(client, bucket, prefix, limit, offset)
```

Add `"list_documents"` to `__all__` in `src/db/__init__.py`.

**Agent isolation:** Receive this section + Phase 0 contracts. Read `src/db/backend.py`, `src/db/minio/backend.py`, and `src/db/__init__.py` in full.

**Dependency:** W1-A must be complete (concrete implementation exists before abstract method is declared).

---

## Task W2-A: Weaviate `aggregate_by_source()`

**FR:** FR-3050
**Files modified:** `src/vector_db/weaviate/store.py`

### Steps

1. Read `src/vector_db/weaviate/store.py` lines 1-60 for import block and tracer pattern.
2. Add new import at top: `from weaviate.classes.aggregate import GroupByAggregate` (check Weaviate v4 API; use `client.collections.get(collection).aggregate.over_all()` or `group_by()` as appropriate).
3. Add after `delete_documents_by_source_key`:

```python
def aggregate_by_source(
    client: weaviate.WeaviateClient,
    collection: str = WEAVIATE_COLLECTION_NAME,
    source_filter: Optional[str] = None,
    connector_filter: Optional[str] = None,
) -> list[dict]:
    """Return chunk counts grouped by source_key.

    Each dict: source_key (str), source (str), connector (str), chunk_count (int).
    Uses Weaviate group_by aggregate — no full object iteration.

    Raises:
        KeyError: if the collection does not exist.
        weaviate.exceptions.WeaviateQueryError: on query failure.
    """
    span = tracer.start_span(
        "vector_store.aggregate_by_source",
        {"collection": collection},
    )
    col = client.collections.get(collection)
    filters = []
    if source_filter:
        filters.append(Filter.by_property("source").like(f"*{source_filter}*"))
    if connector_filter:
        filters.append(Filter.by_property("connector").equal(connector_filter))
    combined = filters[0] if len(filters) == 1 else (Filter.all_of(filters) if filters else None)
    response = col.aggregate.over_all(
        group_by=weaviate.classes.aggregate.GroupByAggregate(prop="source_key"),
        filters=combined,
        total_count=True,
    )
    results = []
    for group in response.groups:
        results.append({
            "source_key": group.grouped_by.value,
            "source": group.properties.get("source", {}).get("top_occurrences", [{}])[0].get("value", ""),
            "connector": group.properties.get("connector", {}).get("top_occurrences", [{}])[0].get("value", ""),
            "chunk_count": group.total_count,
        })
    span.end(status="ok")
    return results
```

Note: Import `weaviate.classes.aggregate` as needed. Adjust API calls if the installed Weaviate Python client v4 `aggregate.group_by()` method differs — consult the client's `aggregate` module.

**Agent isolation:** Receive this section + Phase 0 contracts. Read `src/vector_db/weaviate/store.py` in full for import and tracer pattern.

---

## Task W2-B: Weaviate `get_collection_stats()`

**FR:** FR-3051
**Files modified:** `src/vector_db/weaviate/store.py`

### Steps

Add after `aggregate_by_source`:

```python
def get_collection_stats(
    client: weaviate.WeaviateClient,
    collection: str = WEAVIATE_COLLECTION_NAME,
) -> Optional[dict]:
    """Return aggregate statistics for a collection.

    Returns dict with chunk_count, document_count, connector_breakdown.
    Returns None if the collection does not exist.

    Raises:
        weaviate.exceptions.WeaviateQueryError: on unexpected query failure.
    """
    span = tracer.start_span("vector_store.get_collection_stats", {"collection": collection})
    if not client.collections.exists(collection):
        span.end(status="not_found")
        return None
    col = client.collections.get(collection)
    total = col.aggregate.over_all(total_count=True)
    chunk_count = total.total_count or 0
    by_source = col.aggregate.over_all(
        group_by=weaviate.classes.aggregate.GroupByAggregate(prop="source_key"),
        total_count=True,
    )
    document_count = len(by_source.groups)
    by_connector = col.aggregate.over_all(
        group_by=weaviate.classes.aggregate.GroupByAggregate(prop="connector"),
        total_count=True,
    )
    connector_breakdown = {
        g.grouped_by.value: g.total_count for g in by_connector.groups
    }
    span.end(status="ok")
    return {
        "chunk_count": chunk_count,
        "document_count": document_count,
        "connector_breakdown": connector_breakdown,
    }
```

**Agent isolation:** Receive this section + Phase 0 contracts. Depends on W2-A being in the same file; both may be implemented together.

---

## Task W2-C: Weaviate `list_collections()`

**FR:** FR-3052
**Files modified:** `src/vector_db/weaviate/store.py`

### Steps

Add after `get_collection_stats`:

```python
def list_collections(
    client: weaviate.WeaviateClient,
) -> list[dict]:
    """Return all collections visible to this client.

    Each dict: collection_name (str), chunk_count (int).
    Uses client.collections.list_all() for enumeration.

    Raises:
        weaviate.exceptions.WeaviateConnectionError: if client is not connected.
    """
    span = tracer.start_span("vector_store.list_collections")
    all_cols = client.collections.list_all(simple=True)
    results = []
    for name in all_cols:
        col = client.collections.get(name)
        agg = col.aggregate.over_all(total_count=True)
        results.append({
            "collection_name": name,
            "chunk_count": agg.total_count or 0,
        })
    span.end(status="ok")
    return results
```

**Agent isolation:** Receive this section + Phase 0 contracts. May be implemented in the same pass as W2-A and W2-B.

---

## Task W3-A: `VectorBackend` ABC + `src/vector_db` Facade

**FR:** FR-3053
**Files modified:** `src/vector_db/backend.py`, `src/vector_db/weaviate/backend.py`, `src/vector_db/__init__.py`

### Steps

**`src/vector_db/backend.py`** — add after `delete_by_source_key`:

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

**`src/vector_db/weaviate/backend.py`** — add imports and implement on `WeaviateBackend`:

```python
from src.vector_db.weaviate.store import (
    aggregate_by_source as _wv_aggregate_by_source,
    get_collection_stats as _wv_get_collection_stats,
    list_collections as _wv_list_collections,
)

# Methods on WeaviateBackend:
def aggregate_by_source(self, client, collection=None, source_filter=None, connector_filter=None):
    return _wv_aggregate_by_source(client, collection or self._default_collection(),
                                   source_filter, connector_filter)

def get_collection_stats(self, client, collection=None):
    return _wv_get_collection_stats(client, collection or self._default_collection())

def list_collections(self, client):
    return _wv_list_collections(client)
```

Note: Read `src/vector_db/weaviate/backend.py` to confirm the existing default collection resolution pattern before implementing.

**`src/vector_db/__init__.py`** — add facade functions after `multi_search`:

```python
def aggregate_by_source(
    client: Any,
    collection: Optional[str] = None,
    source_filter: Optional[str] = None,
    connector_filter: Optional[str] = None,
) -> list[dict]:
    """Group chunk counts by source_key with optional filters."""
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

Add to `__all__`: `"aggregate_by_source"`, `"get_collection_stats"`, `"list_collections"`.

**Agent isolation:** Receive this section + Phase 0 contracts. Read `src/vector_db/backend.py`, `src/vector_db/weaviate/backend.py`, and `src/vector_db/__init__.py` in full.

**Dependency:** W2-A, W2-B, W2-C must be complete.

---

## Task W4-A: `server/routes/documents.py`

**FR:** FR-3000, FR-3001, FR-3010, FR-3011, FR-3020, FR-3030, FR-3031, FR-3070, FR-3071
**Files created:** `server/routes/documents.py`

### Steps

1. Mirror the header pattern from `server/routes/query.py` (imports, logger).
2. Imports required:

```python
from __future__ import annotations
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
import weaviate.exceptions

from server.common.schemas import ApiErrorResponse
from server.schemas import (
    CollectionListResponse, CollectionStatsResponse,
    DocumentDetailResponse, DocumentListResponse, DocumentUrlResponse,
    SourceListResponse,
)
from src.platform.security.auth import Principal, authenticate_request
from src.platform.security.tenancy import resolve_tenant_id
import src.db as db
import src.vector_db as vector_db
```

3. Define error helpers:

```python
def _not_found(item_type: str, identifier: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=ApiErrorResponse(
            error={"code": "not_found", "message": f"{item_type} '{identifier}' not found."}
        ).model_dump(),
    )

def _service_unavailable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=ApiErrorResponse(
            error={"code": "service_unavailable", "message": detail}
        ).model_dump(),
    )
```

Note: `ApiErrorResponse` uses `ApiErrorDetail` for the `error` field — pass a dict or construct `ApiErrorDetail` directly; check `server/common/schemas.py` for the exact constructor.

4. Implement `create_documents_router(db_client, vector_client)` returning an `APIRouter(prefix="/api/v1")`.

5. Implement each endpoint — thin handlers:

**`GET /api/v1/documents`** (FR-3000, FR-3001):
- Call `db.list_documents(db_client, limit=1000)` to get all MinIO docs.
- Attempt `vector_db.aggregate_by_source(vector_client, collection=collection)` — catch `weaviate.exceptions.WeaviateConnectionError` and set all `chunk_count=None` (AC-3001-3).
- Build chunk lookup dict: `{row["source_key"]: row["chunk_count"] for row in agg_rows}`.
- Apply `source_filter` (substring on `source_key`) and `connector_filter` (from metadata) on the MinIO results.
- Return `DocumentListResponse(documents=page, total=total, limit=limit, offset=offset)`.
- Sort by `source_key` before slicing (AC-3000-5).

**`GET /api/v1/documents/{document_id}`** (FR-3010):
- Call `db.get_document(db_client, document_id)` — returns `None` → raise `_not_found`.
- Optionally call `vector_db.aggregate_by_source(vector_client)` to get `chunk_count`.
- Return `DocumentDetailResponse`.

**`GET /api/v1/documents/{document_id}/url`** (FR-3011):
- Call `db.document_exists(db_client, document_id)` — False → raise `_not_found`.
- Call `db.get_document_url(db_client, document_id, expires_in_seconds=expires_in)`.
- Return `DocumentUrlResponse(document_id=document_id, url=url, expires_in=expires_in)`.

**`GET /api/v1/sources`** (FR-3020):
- Call `vector_db.aggregate_by_source(vector_client, collection=collection, connector_filter=connector_filter)`.
- Group by `source` to compute `document_count` (distinct `source_key` per source).
- Apply pagination and return `SourceListResponse`.
- Catch `weaviate.exceptions.WeaviateConnectionError` → raise `_service_unavailable`.

**`GET /api/v1/collections`** (FR-3031):
- Call `vector_db.list_collections(vector_client)`.
- Return `CollectionListResponse(collections=[CollectionItem(**row) for row in rows])`.

**`GET /api/v1/collections/{collection_name}/stats`** (FR-3030):
- Call `vector_db.get_collection_stats(vector_client, collection=collection_name)`.
- `None` result → raise `_not_found("Collection", collection_name)`.
- Return `CollectionStatsResponse(collection_name=collection_name, **stats)`.

6. All handlers call `resolve_tenant_id(principal)` — pass as Weaviate filter when tenant is not system default (NFR-3004). Consult existing query route for pattern.

7. Wrap unexpected exceptions in `try/except Exception` → `_service_unavailable(str(e))` + `logger.error(...)`.

**Agent isolation:** Receive this section + Phase 0 contracts. Read `server/routes/query.py` lines 1-80, `server/common/schemas.py`, and `server/schemas.py` lines 1-20 for import patterns. Do not read the full query route.

**Dependency:** W0-A, W1-B, W3-A must be complete.

---

## Task W4-B: Register Router

**FR:** AC-3070-1
**Files modified:** `server/routes/__init__.py`

### Steps

1. Read `server/routes/__init__.py` in full.
2. Add import: `from server.routes.documents import create_documents_router`
3. Add `"create_documents_router"` to `__all__`.

**Agent isolation:** Receive this section + Phase 0 contracts. Read `server/routes/__init__.py` in full.

**Dependency:** W4-A must be complete.

---

## Task W5-A: Schema Contract Tests

**FR:** FR-3068
**Files created:** `tests/server/test_document_management_schemas.py`

### Steps

1. Check whether `tests/server/` exists; create it with an empty `__init__.py` if not.
2. For each of the 9 new models, write:
   - A round-trip test: instantiate with valid data, call `.model_dump()`, assert fields present.
   - A required-field omission test: assert `ValidationError` is raised when a required field is missing.
   - Default value tests for `Optional` fields (`chunk_count`, `ingested_at`, `documents`, `sources`).
3. Test fixture pattern:

```python
import pytest
from pydantic import ValidationError
from server.schemas import (
    DocumentSummary, DocumentListResponse, DocumentDetailResponse,
    DocumentUrlResponse, SourceSummary, SourceListResponse,
    CollectionItem, CollectionStatsResponse, CollectionListResponse,
)

def test_document_summary_round_trip():
    obj = DocumentSummary(document_id="abc", source="s", source_key="sk", connector="local_fs")
    d = obj.model_dump()
    assert d["document_id"] == "abc"
    assert d["chunk_count"] is None

def test_document_summary_missing_required():
    with pytest.raises(ValidationError):
        DocumentSummary(source="s", source_key="sk", connector="local_fs")  # missing document_id
```

**Agent isolation:** Receive this section + Phase 0 contracts (schema definitions only). Do not read source files.

**Dependency:** W0-A must be complete.

---

## Module Boundary Map

```
Created:
  server/routes/documents.py          ← imports server.schemas, src.db, src.vector_db,
                                         server.common.schemas, src.platform.security.*
  tests/server/test_document_management_schemas.py  ← imports server.schemas

Modified (append-only, no signature changes to existing functions):
  server/schemas.py                   ← no new imports needed
  server/routes/__init__.py           ← imports server.routes.documents
  src/db/backend.py                   ← no new imports (uses existing Any, Optional)
  src/db/minio/store.py               ← no new imports (json, S3Error, tracer already present)
  src/db/minio/backend.py             ← imports src.db.minio.store.list_documents
  src/db/__init__.py                  ← no new imports
  src/vector_db/backend.py            ← no new imports
  src/vector_db/weaviate/store.py     ← may need weaviate.classes.aggregate import
  src/vector_db/weaviate/backend.py   ← imports new store functions
  src/vector_db/__init__.py           ← no new imports
```

### Execution Order (parallel-safe)

- **Wave 0:** W0-A (no deps)
- **Wave 1+2 in parallel:** W1-A, W2-A, W2-B, W2-C (no deps)
- **After Wave 1+2:** W1-B, W3-A
- **After W0+W1-B+W3-A:** W4-A
- **After W4-A:** W4-B
- **After W0-A:** W5-A (independent of W1–W4)
