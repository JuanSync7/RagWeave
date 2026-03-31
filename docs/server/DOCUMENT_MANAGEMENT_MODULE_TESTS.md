> **Document type:** Test planning document (Layer 7)
> **Upstream:** DOCUMENT_MANAGEMENT_ENGINEERING_GUIDE.md, DOCUMENT_MANAGEMENT_SPEC.md, DOCUMENT_MANAGEMENT_IMPLEMENTATION.md
> **Last updated:** 2026-03-27

# Document & Collection Management API — Module Test Specifications (v1.0.0)

---

## 1. Mock / Stub Interface Specifications

### 1.1 MinIO Client Mock

| Method | Return type | Notes |
|---|---|---|
| `list_objects(bucket, prefix, recursive)` | `Iterator[Object]` | Each `Object` has `.object_name`, `.size`, `.last_modified` |
| `get_object(bucket, key)` | `Response` | Supports `.read()`, `.close()`, `.release_conn()` |
| `stat_object(bucket, key)` | `ObjectStat` | Raises `S3Error("NoSuchKey")` when object missing |
| `presigned_get_object(bucket, key, expires)` | `str` | Returns a URL string |

**Factory helper:**

```python
def make_minio_mock(objects: list[dict]) -> MagicMock:
    """
    objects: [{"name": "docs/foo.md", "size": 100, "last_modified": datetime(...)}]
    Configures list_objects to yield fake Object stubs.
    Configures get_object to return JSON bytes for *.meta.json keys.
    """
```

**Preconditions:** All sidecar content must be pre-registered in the factory.
**S3Error simulation:** `mock.list_objects.side_effect = S3Error(...)`.

---

### 1.2 Weaviate Client Mock

| Method | Return type | Notes |
|---|---|---|
| `client.collections.get(name)` | Collection stub | Must expose `.aggregate.over_all(...)` |
| `client.collections.exists(name)` | `bool` | Controls `get_collection_stats` early exit |
| `client.collections.list_all(simple=True)` | `list[str]` | Names only |
| `col.aggregate.over_all(group_by, filters, total_count)` | AggregateResult stub | `.groups` list and `.total_count` |

**Group stub shape:**

```python
group.grouped_by.value          # str — the grouped property value
group.total_count               # int
group.properties["source"]["top_occurrences"][0]["value"]
group.properties["connector"]["top_occurrences"][0]["value"]
```

**Preconditions:** Mocks must be constructed per-test to avoid cross-test state pollution.
**Error simulation:** `client.collections.get.side_effect = WeaviateConnectionError(...)`.

---

## 2. Per-Module Test Specifications

### 2.1 `src/db/minio/store.py` — `list_documents`

**Agent isolation contract:** Receive this section and Phase 0 stub contracts. Do not read the route module or Weaviate store.

#### 2.1.1 Happy Path

| ID | Scenario | Setup | Assert |
|---|---|---|---|
| MT-M-01 | Bucket with N docs returns list | 3 `.md` objects + 3 `.meta.json` sidecars | Returns list of 3 dicts; each has `document_id`, `source_key`, `size_bytes`, `last_modified` |
| MT-M-02 | `document_id` is UUID5 of `source_key` | 1 object with `source_key="docs/foo"` | `build_document_id("docs/foo") == result[0]["document_id"]` |
| MT-M-03 | `.meta.json` sidecars excluded from results | 2 `.md` + 2 `.meta.json` | Result length == 2; no `.meta.json` entries |
| MT-M-04 | `prefix` passed to `list_objects` | `prefix="docs/"` | `mock.list_objects.call_args.kwargs["prefix"] == "docs/"` |

#### 2.1.2 Empty / Boundary Conditions

| ID | Scenario | Setup | Assert |
|---|---|---|---|
| MT-M-05 | Empty bucket | `list_objects` yields nothing | Returns `[]` |
| MT-M-06 | Offset beyond result count | 2 docs, `offset=5` | Returns `[]` |
| MT-M-07 | `limit=1` on 5 docs | 5 docs, `limit=1, offset=0` | Returns exactly 1 doc |
| MT-M-08 | `offset=2, limit=2` on 5 docs | 5 docs | Returns docs at index 2 and 3 |
| MT-M-09 | Pagination slicing is Python-side | 100 docs, `offset=90, limit=20` | Returns 10 docs (clamped to list end) |

#### 2.1.3 Missing Sidecar

| ID | Scenario | Setup | Assert |
|---|---|---|---|
| MT-M-10 | `.meta.json` absent → fallback to stem | `get_object("stem.meta.json")` raises `S3Error` | `source_key == "stem"`, WARNING logged, no exception raised |
| MT-M-11 | Partial sidecars (1 of 3 missing) | Sidecar missing for index 1 | Returns 3 docs; index 1 has `source_key` = stem |

#### 2.1.4 Error Scenarios

| ID | Scenario | Setup | Assert |
|---|---|---|---|
| MT-M-12 | `list_objects` raises `S3Error` | `list_objects.side_effect = S3Error(...)` | Exception propagates to caller |
| MT-M-13 | `get_object` raises `S3Error` (sidecar) | Only sidecar fetch raises | Swallowed; document still returned with stem as `source_key` |

#### 2.1.5 Integration Points

- `build_document_id()` from `src/db/minio/store.py` — called per document; not mocked.
- `client.list_objects()` and `client.get_object()` — both mocked.
- Tracer span creation: verify `"document_store.list_documents"` span is started.

#### 2.1.6 Known Test Gaps

- Clock timezone handling in `last_modified.isoformat()` not tested.
- Performance with > 10 000 objects not tested (unit scope).

---

### 2.2 `src/vector_db/weaviate/store.py` — Aggregation Functions

**Agent isolation contract:** Receive this section and Phase 0 stub contracts. Do not read the MinIO store or route module.

#### 2.2.1 `aggregate_by_source`

| ID | Scenario | Setup | Assert |
|---|---|---|---|
| MT-W-01 | Groups correctly | 2 groups: `source_key="a"` (5 chunks), `source_key="b"` (3 chunks) | Returns 2 dicts with correct `chunk_count` values |
| MT-W-02 | `source_filter` forwarded | `source_filter="wiki"` | Weaviate `Filter.by_property("source").like("*wiki*")` used |
| MT-W-03 | `connector_filter` forwarded | `connector_filter="confluence"` | `Filter.by_property("connector").equal("confluence")` used |
| MT-W-04 | Both filters compose with `all_of` | Both provided | `Filter.all_of([...])` called |
| MT-W-05 | No filters → no filter arg | Neither filter provided | `filters=None` passed to `over_all` |
| MT-W-06 | `source` / `connector` extracted from `top_occurrences` | Group has `top_occurrences` | `result["source"]` == first occurrence value |
| MT-W-07 | Collection not found → `KeyError` | `collections.get.side_effect = KeyError` | `KeyError` propagates |
| MT-W-08 | `WeaviateQueryError` propagates | `over_all.side_effect = WeaviateQueryError` | Exception propagates |

#### 2.2.2 `get_collection_stats`

| ID | Scenario | Setup | Assert |
|---|---|---|---|
| MT-W-09 | Collection exists → full stats returned | `exists=True`, total=50, 3 source keys, 2 connectors | Returns dict with `chunk_count=50`, `document_count=3`, `connector_breakdown={"a":30,"b":20}` |
| MT-W-10 | Collection missing → returns `None` | `exists=False` | Returns `None`; no aggregate queries issued |
| MT-W-11 | Three queries issued | `exists=True` | `over_all` called 3 times (total, by source, by connector) |
| MT-W-12 | Empty collection | `exists=True`, total=0 | Returns `{"chunk_count":0, "document_count":0, "connector_breakdown":{}}` |
| MT-W-13 | `WeaviateQueryError` propagates | `over_all.side_effect = WeaviateQueryError` | Exception propagates |

#### 2.2.3 `list_collections`

| ID | Scenario | Setup | Assert |
|---|---|---|---|
| MT-W-14 | Returns all collections | `list_all` returns `["A","B"]` | Returns 2 dicts with `collection_name` and `chunk_count` |
| MT-W-15 | N+1 round trips | 3 collections | `over_all` called 3 times |
| MT-W-16 | Empty client | `list_all` returns `[]` | Returns `[]` |
| MT-W-17 | `WeaviateConnectionError` propagates | `list_all.side_effect = WeaviateConnectionError` | Exception propagates |

#### 2.2.4 Integration Points

- Weaviate client mock must correctly simulate `collections.get()`, `collections.exists()`, `collections.list_all()`, and the `aggregate.over_all()` chain.
- Tracer spans: verify `"vector_store.aggregate_by_source"`, `"vector_store.get_collection_stats"`, `"vector_store.list_collections"` started.

#### 2.2.5 Known Test Gaps

- Filter composition edge: exactly one filter (no `all_of`) vs. zero filters not fully exercised.
- `top_occurrences` empty list: fallback value for `source` / `connector` not specified.

---

### 2.3 `server/routes/documents.py` — Route Handlers

**Agent isolation contract:** Receive this section plus Phase 0 stub contracts. Use FastAPI `TestClient`; mock `src.db` and `src.vector_db` facades at the module boundary.

#### 2.3.1 `GET /api/v1/documents`

| ID | Scenario | Backend behavior | Expected response |
|---|---|---|---|
| MT-R-01 | Happy path | 3 MinIO docs + Weaviate agg with chunk counts | 200; `documents` list len 3; `chunk_count` populated |
| MT-R-02 | Weaviate down → graceful degradation | `aggregate_by_source` raises `WeaviateConnectionError` | 200; all `chunk_count == null`; `connector == "unknown"` |
| MT-R-03 | `source_filter` filters docs | 3 docs, filter matches 1 | `total == 1` |
| MT-R-04 | `connector_filter` filters docs | 3 docs with different connectors | Only matching connector returned |
| MT-R-05 | Results sorted by source ascending | Docs returned in random order from MinIO | `documents[0].source <= documents[1].source` |
| MT-R-06 | Pagination: `limit=2, offset=0` on 5 docs | 5 MinIO docs | `len(documents) == 2`, `total == 5` |
| MT-R-07 | `limit` exceeds max (101) → 422 | n/a | 422 validation error |
| MT-R-08 | `offset < 0` → 422 | n/a | 422 validation error |
| MT-R-09 | MinIO `S3Error` → 503 | `list_documents` raises `S3Error` | 503 with `error.code == "service_unavailable"` |

#### 2.3.2 `GET /api/v1/documents/{document_id}`

| ID | Scenario | Backend behavior | Expected response |
|---|---|---|---|
| MT-R-10 | Happy path | `get_document` returns doc dict | 200; `document_id`, `content`, `metadata`, `chunk_count` present |
| MT-R-11 | Document not found | `get_document` returns `None` | 404 with `error.code == "not_found"` |
| MT-R-12 | Weaviate down → chunk_count null | `aggregate_by_source` raises | 200; `chunk_count == null` |
| MT-R-13 | MinIO backend down → 503 | `get_document` raises `S3Error` | 503 |

#### 2.3.3 `GET /api/v1/documents/{document_id}/url`

| ID | Scenario | Backend behavior | Expected response |
|---|---|---|---|
| MT-R-14 | Happy path | `document_exists=True`, `get_document_url` returns URL | 200; `url` present, `expires_in` echoes param |
| MT-R-15 | Document not found | `document_exists=False` | 404 |
| MT-R-16 | `expires_in < 60` → 422 | n/a | 422 |
| MT-R-17 | `expires_in > 86400` → 422 | n/a | 422 |
| MT-R-18 | `expires_in` default is 3600 | Not provided | `expires_in == 3600` in response |

#### 2.3.4 `GET /api/v1/sources`

| ID | Scenario | Backend behavior | Expected response |
|---|---|---|---|
| MT-R-19 | Happy path | `aggregate_by_source` returns 4 rows (2 sources × 2 keys each) | 200; 2 source items; correct `document_count`, `chunk_count` |
| MT-R-20 | Weaviate down → 503 | `aggregate_by_source` raises `WeaviateConnectionError` | 503 with `error.code == "service_unavailable"` |
| MT-R-21 | `connector_filter` forwarded to Weaviate | Any filter value | Backend called with matching `connector_filter` |
| MT-R-22 | `limit` exceeds max (501) → 422 | n/a | 422 |

#### 2.3.5 `GET /api/v1/collections`

| ID | Scenario | Backend behavior | Expected response |
|---|---|---|---|
| MT-R-23 | Happy path | `list_collections` returns 2 items | 200; `collections` list len 2 |
| MT-R-24 | Weaviate connection error → 503 | `list_collections` raises | 503 |

#### 2.3.6 `GET /api/v1/collections/{collection_name}/stats`

| ID | Scenario | Backend behavior | Expected response |
|---|---|---|---|
| MT-R-25 | Happy path | `get_collection_stats` returns stats dict | 200; all fields present including `connector_breakdown` |
| MT-R-26 | Collection not found → 404 | `get_collection_stats` returns `None` | 404 with `error.code == "not_found"` |
| MT-R-27 | Weaviate error → 503 | `get_collection_stats` raises | 503 |

#### 2.3.7 Shared Concerns

- **Authentication:** All endpoints call `authenticate_request`; mock `Principal` to bypass.
- **Tenant isolation:** `resolve_tenant_id(principal)` called on every handler; verify via spy.
- **Error body shape:** All 404 responses must have `error.code == "not_found"`. All 503 responses must have `error.code == "service_unavailable"`. Passing a plain `dict` to `ApiErrorResponse` raises `ValidationError` — tests must construct `ApiErrorDetail` correctly.

#### 2.3.8 Known Test Gaps

- Multi-tenant Weaviate filter injection (NFR-3004) not fully testable without a live Weaviate tenant.
- Tracing span emission from route handlers not verified.

---

### 2.4 `server/schemas.py` — Contract Tests

**Agent isolation contract:** Receive this section and Phase 0 model definitions only. Do not read source files.
**Test file:** `tests/server/test_document_management_schemas.py`

#### 2.4.1 Round-Trip Serialization

| Model | Required fields | Optional fields (default None / []) |
|---|---|---|
| `DocumentSummary` | `document_id`, `source`, `source_key`, `connector` | `chunk_count`, `ingested_at` |
| `DocumentListResponse` | `total`, `limit`, `offset` | `documents` (default `[]`) |
| `DocumentDetailResponse` | `document_id`, `content`, `metadata` | `chunk_count` |
| `DocumentUrlResponse` | `document_id`, `url`, `expires_in` | — |
| `SourceSummary` | `source`, `connector`, `document_count`, `chunk_count` | — |
| `SourceListResponse` | `total`, `limit`, `offset` | `sources` (default `[]`) |
| `CollectionItem` | `collection_name`, `chunk_count` | — |
| `CollectionStatsResponse` | `collection_name`, `document_count`, `chunk_count`, `connector_breakdown` | — |
| `CollectionListResponse` | `collections` | — |

For each model: instantiate with valid data, call `.model_dump()`, assert all fields present and types correct.

#### 2.4.2 Required Field Enforcement

| ID | Scenario | Assert |
|---|---|---|
| MT-S-01 | `DocumentSummary` missing `document_id` | `ValidationError` raised |
| MT-S-02 | `DocumentSummary` missing `source` | `ValidationError` raised |
| MT-S-03 | `DocumentDetailResponse` missing `content` | `ValidationError` raised |
| MT-S-04 | `DocumentDetailResponse` missing `metadata` | `ValidationError` raised |
| MT-S-05 | `SourceSummary` missing `document_count` | `ValidationError` raised |
| MT-S-06 | `CollectionStatsResponse` missing `connector_breakdown` | `ValidationError` raised |
| MT-S-07 | `CollectionListResponse` missing `collections` | `ValidationError` raised |

#### 2.4.3 Default Values

| ID | Scenario | Assert |
|---|---|---|
| MT-S-08 | `DocumentSummary` without `chunk_count` | `chunk_count is None` |
| MT-S-09 | `DocumentSummary` without `ingested_at` | `ingested_at is None` |
| MT-S-10 | `DocumentListResponse` without `documents` | `documents == []` |
| MT-S-11 | `SourceListResponse` without `sources` | `sources == []` |

#### 2.4.4 Backend Alignment

| ID | Check |
|---|---|
| MT-S-12 | `CollectionItem.chunk_count` is `int`, not `Optional[int]` |
| MT-S-13 | `SourceSummary.document_count` and `chunk_count` are required `int` (not optional) |
| MT-S-14 | `CollectionStatsResponse.connector_breakdown` accepts `dict[str, int]` with arbitrary keys |

#### 2.4.5 Known Test Gaps

- `DocumentListResponse.total` negative value not validated by Pydantic (no `ge=0` constraint in Phase 0 contracts).
- `CollectionListResponse.collections` has no default — must be supplied; no `None` guard tested.

---

## 3. Integration Test Specifications

**Test file:** `tests/server/test_document_management_integration.py`
**Setup:** TestClient with `MinioBackend` and `WeaviateBackend` mocked at the facade boundary (`src.db` and `src.vector_db` modules).

| ID | Scenario | Steps | Assert |
|---|---|---|---|
| IT-01 | List → get → URL happy path | 1. `GET /api/v1/documents` → extract `document_id`; 2. `GET /api/v1/documents/{id}` → extract `source_key`; 3. `GET /api/v1/documents/{id}/url` | Each step 200; URL in step 3 non-empty |
| IT-02 | MinIO down → `GET /documents` 503 | `db.list_documents` raises `S3Error` | 503 with `error.code == "service_unavailable"` |
| IT-03 | Weaviate down → `GET /documents` degrades | `vector_db.aggregate_by_source` raises; `db.list_documents` succeeds | 200; all `chunk_count == null` |
| IT-04 | Weaviate down → `GET /sources` 503 | `vector_db.aggregate_by_source` raises | 503; does not degrade |
| IT-05 | Collection stats not found | `vector_db.get_collection_stats` returns `None` | 404 |
| IT-06 | Pagination consistency | `GET /documents?limit=2` then `offset=2` | Union of pages equals full list; no duplicates |

---

## 4. FR-to-Test Traceability Matrix

| FR ID | Acceptance Criteria | Covered by |
|---|---|---|
| FR-3000 | AC-3000-1 (response shape) | MT-R-01 |
| FR-3000 | AC-3000-2 (pagination fields) | MT-R-01, MT-R-06 |
| FR-3000 | AC-3000-3 (source_filter) | MT-R-03 |
| FR-3000 | AC-3000-4 (connector_filter) | MT-R-04 |
| FR-3000 | AC-3000-5 (sorted by source) | MT-R-05 |
| FR-3001 | AC-3001-1 (chunk_count from Weaviate) | MT-R-01 |
| FR-3001 | AC-3001-2 (chunk_count=0 for unchunked docs) | MT-R-01 |
| FR-3001 | AC-3001-3 (Weaviate down → null) | MT-R-02, IT-03 |
| FR-3010 | AC-3010-1 (detail response shape) | MT-R-10 |
| FR-3010 | AC-3010-2 (404 on missing) | MT-R-11 |
| FR-3010 | AC-3010-3 (delegates to backend) | MT-R-10 |
| FR-3011 | AC-3011-1 (URL response shape) | MT-R-14 |
| FR-3011 | AC-3011-2 (presigned URL validity) | MT-R-14, MT-R-18 |
| FR-3011 | AC-3011-3 (404 on missing) | MT-R-15 |
| FR-3011 | AC-3011-4 (delegates to backend) | MT-R-14 |
| FR-3020 | AC-3020-1 (source response shape) | MT-R-19 |
| FR-3020 | AC-3020-2 (pagination fields) | MT-R-19 |
| FR-3020 | AC-3020-3 (sources from Weaviate) | MT-R-19 |
| FR-3020 | AC-3020-4 (document_count) | MT-R-19 |
| FR-3030 | AC-3030-1 (stats shape) | MT-R-25, MT-W-09 |
| FR-3030 | AC-3030-2 (404 on missing collection) | MT-R-26, IT-05 |
| FR-3030 | AC-3030-3 (aggregate queries, not iteration) | MT-W-11 |
| FR-3031 | AC-3031-1 (collection list shape) | MT-R-23, MT-W-14 |
| FR-3031 | AC-3031-2 (all collections enumerated) | MT-W-14 |
| FR-3040 | AC-3040-1 (list_documents return shape) | MT-M-01 |
| FR-3040 | AC-3040-2 (excludes sidecars) | MT-M-03 |
| FR-3040 | AC-3040-3 (prefix filtering) | MT-M-04 |
| FR-3040 | AC-3040-4 (offset/limit pagination) | MT-M-06, MT-M-07, MT-M-08 |
| FR-3040 | AC-3040-5 (reads sidecar for source_key) | MT-M-01, MT-M-10 |
| FR-3041 | AC-3041-1 (abstract method semantics) | Integration (facade call) |
| FR-3041 | AC-3041-2 (`__all__` export) | Import smoke test |
| FR-3041 | AC-3041-3 (MinioBackend implements) | IT-01 |
| FR-3050 | AC-3050-1 (aggregate return shape) | MT-W-01 |
| FR-3050 | AC-3050-2 (uses aggregate API) | MT-W-01 (no full iteration) |
| FR-3050 | AC-3050-3 (filters applied) | MT-W-02, MT-W-03, MT-W-04 |
| FR-3051 | AC-3051-1 (stats dict shape) | MT-W-09 |
| FR-3051 | AC-3051-2 (aggregate queries used) | MT-W-11 |
| FR-3051 | AC-3051-3 (None on missing) | MT-W-10 |
| FR-3052 | AC-3052-1 (list shape) | MT-W-14 |
| FR-3052 | AC-3052-2 (uses list_all) | MT-W-14 |
| FR-3053 | AC-3053-1 (abstract methods) | Import smoke test |
| FR-3053 | AC-3053-2 (`__all__` export) | Import smoke test |
| FR-3053 | AC-3053-3 (WeaviateBackend implements) | IT-01 |
| FR-3060 | AC-3060-1 (model validates) | MT-S-01 (round-trip) |
| FR-3060 | AC-3060-2 (chunk_count Optional) | MT-S-08 |
| FR-3061 | AC-3061-1 (documents defaults to []) | MT-S-10 |
| FR-3061 | AC-3061-2 (non-negative int fields) | MT-S-02 (round-trip) |
| FR-3062 | AC-3062-1 (model validates) | MT-S-03, MT-S-04 |
| FR-3063 | — | MT-R-14 (route test exercises schema) |
| FR-3064 | — | MT-S-05 (round-trip) |
| FR-3065 | — | MT-S-11 |
| FR-3066 | — | MT-S-06, MT-S-14 |
| FR-3067 | — | MT-S-07 |
| FR-3068 | AC-3068-1 (round-trip tests) | All MT-S-* round-trip cases |
| FR-3068 | AC-3068-2 (required field omission raises) | MT-S-01 through MT-S-07 |
| FR-3068 | AC-3068-3 (tests in tests/server/) | File location |
| FR-3070 | AC-3070-1 (factory function pattern) | MT-R-01 (router creation) |
| FR-3070 | AC-3070-2 (authenticate_request) | MT-R-01 (mock Principal) |
| FR-3070 | AC-3070-3 (resolve_tenant_id) | MT-R-01 (spy assertion) |
| FR-3070 | AC-3070-4 (thin handlers) | Code review / static; not unit-testable |
| FR-3071 | AC-3071-1 (404 uses ApiErrorResponse) | MT-R-11, MT-R-15, MT-R-26 |
| FR-3071 | AC-3071-2 (503 on backend failure) | MT-R-09, MT-R-20, MT-R-24, IT-02 |
| FR-3071 | AC-3071-3 (422 on invalid params) | MT-R-07, MT-R-08, MT-R-16, MT-R-17, MT-R-22 |
