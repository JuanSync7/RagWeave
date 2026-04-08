# Visual Page Retrieval Pipeline — Test Docs

> **For write-module-tests agents:** This document is your source of truth.
> Read ONLY your assigned module section. Do not read source files, implementation code,
> or other modules' test specs.

**Engineering guide:** `docs/ingestion/visual_retrieval/VISUAL_RETRIEVAL_ENGINEERING_GUIDE.md`
**Phase 0 contracts:** `docs/ingestion/visual_retrieval/VISUAL_RETRIEVAL_IMPLEMENTATION.md`
**Spec:** `docs/ingestion/visual_retrieval/VISUAL_RETRIEVAL_SPEC.md`
**Produced by:** write-test-docs

---

## Table of Contents

1. [Mock / Stub Interface Specifications](#mock--stub-interface-specifications)
2. [Module Test Specifications](#module-test-specifications)
   - 2.1 [EG §3.1 — ColQwen2 Model Adapter (`embed_text_query`)](#eg-31--colqwen2-model-adapter-embed_text_query)
   - 2.2 [EG §3.2 — Weaviate Visual Collection Store (`visual_search`)](#eg-32--weaviate-visual-collection-store-visual_search)
   - 2.3 [EG §3.3 — MinIO Page Image Store (`get_page_image_url`)](#eg-33--minio-page-image-store-get_page_image_url)
   - 2.4 [EG §3.4 — Retrieval Pipeline Schemas](#eg-34--retrieval-pipeline-schemas)
   - 2.5 [EG §3.5 — RAGChain Visual Retrieval Track](#eg-35--ragchain-visual-retrieval-track)
   - 2.6 [EG §3.6 — VectorBackend ABC and Public API](#eg-36--vectorbackend-abc-and-public-api)
   - 2.7 [EG §3.7 — Visual Retrieval Configuration Keys](#eg-37--visual-retrieval-configuration-keys)
   - 2.8 [EG §3.8 — API Response Schemas](#eg-38--api-response-schemas)
3. [Integration Test Specifications](#integration-test-specifications)
4. [FR-to-Test Traceability Matrix](#fr-to-test-traceability-matrix)

---

## Mock / Stub Interface Specifications

### Mock: ColQwen2 Model and Processor

**What it replaces:** The ColQwen2 GPU model and processor loaded by `load_colqwen_model()`. Used in tests for `embed_text_query` and all RAGChain visual-track tests.

**Interface to mock:**

```python
# model mock
model.device  # property → "cpu" or MagicMock device
model(**query_inputs)  # callable → returns mock output with last_hidden_state

# processor mock
processor.process_queries(texts: list[str]) -> dict[str, Any]
# returns tokenized input dict with tensor values that can be moved to device
```

**Happy path return (processor.process_queries):**
```python
{"input_ids": torch.zeros(1, 10, dtype=torch.long), "attention_mask": torch.ones(1, 10)}
```

**Happy path return (model forward pass):**
```python
# object with last_hidden_state attribute, shape (1, n_tokens, 128)
import torch
mock_output = MagicMock()
mock_output.last_hidden_state = torch.randn(1, 10, 128)
```

**Error path:**
```python
# model is None → ColQwen2LoadError raised by embed_text_query before forward pass
# model forward pass RuntimeError → VisualEmbeddingError raised with __cause__
model.side_effect = RuntimeError("CUDA out of memory")
```

**Used by modules:** EG §3.1 (colqwen adapter), EG §3.5 (rag_chain visual track)

---

### Mock: Weaviate Client and Near-Vector Query

**What it replaces:** The live `weaviate.WeaviateClient` used by `visual_search()`.

**Interface to mock:**

```python
client.collections.get(collection_name: str) -> collection_handle
collection_handle.query.near_vector(
    near_vector: list[float],
    target_vector: str,
    limit: int,
    filters: Any,
    return_properties: list[str],
    return_metadata: MetadataQuery,
) -> QueryResult

# Each result object:
result_obj.properties  # dict with document_id, page_number, source_key, etc.
result_obj.metadata.distance  # float cosine distance
```

**Happy path return:**
```python
# QueryResult with 2 objects, distances 0.19 and 0.35 (→ scores 0.81 and 0.65)
mock_obj1 = MagicMock()
mock_obj1.properties = {
    "document_id": "abc-123", "page_number": 7, "source_key": "reports/q3.pdf",
    "source_name": "Q3 Report", "minio_key": "pages/abc-123/0007.jpg",
    "tenant_id": "acme", "total_pages": 42, "page_width_px": 1024, "page_height_px": 768,
}
mock_obj1.metadata.distance = 0.19  # → score = 0.81
```

**Error path:**
```python
collection_handle.query.near_vector.side_effect = weaviate.exceptions.WeaviateQueryError("query failed")
```

**Used by modules:** EG §3.2 (visual_store), EG §3.5 (rag_chain via search_visual)

---

### Mock: MinIO Client (Presigned URL)

**What it replaces:** The `minio.Minio` client used by `get_page_image_url()`.

**Interface to mock:**

```python
client.presigned_get_object(
    bucket_name: str,
    object_name: str,
    expires: timedelta,
) -> str  # presigned URL string
```

**Happy path return:**
```python
"https://minio.internal:9000/rag-documents/pages/abc-123/0007.jpg?X-Amz-Signature=abc123&X-Amz-Expires=3600"
```

**Error path:**
```python
client.presigned_get_object.side_effect = minio.error.S3Error(
    "NoSuchBucket", "The specified bucket does not exist", ...)
```

**Used by modules:** EG §3.3 (minio_store), EG §3.5 (rag_chain presigned URL step)

---

### Mock: RAGChain Text Track (for RAGChain visual-track isolation tests)

**What it replaces:** The full text retrieval pipeline (query_processor, BGE-M3 embed, Weaviate hybrid search, reranking, LLM generation) when testing only the visual track additions.

**Interface to mock:**

```python
# process_query returns a processed query string and action
rag_chain._process_query(query) -> (processed_query: str, action: str, confidence: float)

# text track returns existing RAGResponse with text results, no visual_results set
RAGResponse(query=..., processed_query=..., results=[...], visual_results=None)
```

**Happy path return:**
```python
processed_query = "Q3 2025 quarterly revenue chart"
action = "search"
confidence = 0.88
```

**Used by modules:** EG §3.5 (rag_chain — isolates visual track from text track in unit tests)

---

### Mock: Vector Backend (`search_visual` delegate)

**What it replaces:** The `WeaviateBackend` concrete implementation when testing the `VectorBackend` ABC and `vector_db/__init__.py` public API.

**Interface to mock:**

```python
backend.search_visual(
    client, query_vector, limit, score_threshold,
    tenant_id=None, collection=None
) -> list[dict[str, Any]]
```

**Happy path return:**
```python
[{"document_id": "abc-123", "page_number": 7, "score": 0.81, ...}]
```

**Error path:**
```python
backend.search_visual.side_effect = weaviate.exceptions.WeaviateConnectionError("no connection")
```

**Used by modules:** EG §3.6 (vector_backend_abc public API delegation tests)

---

## Module Test Specifications

---

### EG §3.1 — ColQwen2 Model Adapter (`embed_text_query`)

**Module purpose:** Encodes a text query string into a 128-dimensional float vector using ColQwen2's text encoding pathway, enabling cross-modal retrieval against visually-indexed page embeddings.

**In scope:**
- `embed_text_query(model, processor, text)` — text encoding, mean-pooling, error handling
- Input validation: empty/whitespace text raises `ValueError` before model invocation
- Model/processor None guard: raises `ColQwen2LoadError`
- Inference error wrapping: `RuntimeError` from forward pass → `VisualEmbeddingError` with `__cause__`
- Output shape: exactly 128 float elements
- Determinism: same input + same model state → same output
- Uses `processor.process_queries()` (not `process_images`)
- Uses `torch.inference_mode()` during forward pass

**Out of scope:**
- `load_colqwen_model()` — not part of this section
- `unload_colqwen_model()` — not part of this section
- `embed_page_images()` — image embedding, not tested here
- `ensure_colqwen_ready()` — dependency check, not tested here
- GPU VRAM management — hardware concern, not unit-testable
- Lazy loading orchestration — owned by EG §3.5 (RAGChain)

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Normal non-empty query | `model=<mock>`, `processor=<mock>`, `text="quarterly revenue chart Q3 2025"` | `list[float]` with `len == 128`; all elements are finite floats |
| Single-word query | `text="revenue"` | `list[float]` with `len == 128` |
| Whitespace-padded valid query | `text="  chart  "` | `list[float]` with `len == 128` (non-empty after strip, so valid) |
| Determinism — same input twice | Same `model`, `processor`, `text` called twice | Both calls return identical vector (element-wise equal) |
| Query text routed through `process_queries` | `text="any query"` | `processor.process_queries(["any query"])` called exactly once; `processor.process_images` never called |
| Output dtype is Python float | Any valid query | All elements are Python `float`, not `torch.Tensor` or `numpy.float32` |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|------------|------------------|-------------------|
| `ValueError` | `text=""` (empty string) | raises `ValueError`; message contains `"empty"` or `"blank"`; model forward pass NOT invoked |
| `ValueError` | `text="   "` (whitespace only) | raises `ValueError`; message contains `"empty"` or `"blank"`; model NOT invoked |
| `ColQwen2LoadError` | `model=None` | raises `ColQwen2LoadError`; processor.process_queries NOT called |
| `ColQwen2LoadError` | `processor=None` | raises `ColQwen2LoadError`; model forward pass NOT called |
| `VisualEmbeddingError` | model forward pass raises `RuntimeError("CUDA out of memory")` | raises `VisualEmbeddingError`; original `RuntimeError` accessible as `__cause__` |

#### Boundary conditions

Derived from spec FR-201, FR-203, FR-205, FR-207 acceptance criteria:

- `text` is exactly one non-whitespace character → valid; returns 128-element list (FR-201)
- `text` is a very long string (>1000 characters) → no error raised; returns 128-element list (output dimension is fixed regardless of input length)
- Model forward pass returns tensor of shape `(1, n_tokens, 128)` with `n_tokens=1` (single token) → mean pool of a single row returns that row unchanged; len == 128 (FR-203)
- Output vector elements are dtype float32 (Python `float`), NOT float16 or bfloat16 (FR-203 AC)

#### Integration points

- Calls `processor.process_queries([text])` — expects a dict of tensors (see Mock: ColQwen2 Model and Processor)
- Calls `model(**query_inputs)` — expects object with `last_hidden_state` attribute of shape `(1, n_tokens, 128)` (see Mock)
- On `RuntimeError` from model: wraps in `VisualEmbeddingError` with chain
- Receives calls from: EG §3.5 `_run_visual_retrieval` — must return `list[float]` of length 128

#### Known test gaps

- **CUDA determinism under 4-bit BitsAndBytes quantization** cannot be verified without real GPU hardware; determinism tests use mock model only and cannot confirm actual quantized inference reproducibility.
- **`torch.inference_mode()` enforcement** (that gradients are not tracked) is not directly testable via Python unit tests without introspecting PyTorch internals; tested only indirectly via mock.
- **Token dimension variability** (different `n_tokens` per query length) is verified structurally with mock; actual ColQwen2 tokenizer behavior requires a live model integration test.
- **VRAM consumption** at 4-bit precision (NFR-903) is a hardware integration test; no unit test coverage.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section (EG §3.1)
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### EG §3.2 — Weaviate Visual Collection Store (`visual_search`)

**Module purpose:** Performs nearest-neighbor search on the `mean_vector` named vector of the `RAGVisualPages` Weaviate collection, filtering by score threshold and optional tenant ID, and returns page result dicts excluding the bulky `patch_vectors` field.

**In scope:**
- `visual_search(client, query_vector, limit, score_threshold, tenant_id, collection)` — full function behaviour
- Score conversion: `score = 1.0 - distance` (cosine distance → similarity)
- Post-filtering: objects with `score < score_threshold` are discarded
- Tenant filter: when `tenant_id` is not None, only matching pages returned
- `patch_vectors` excluded from `return_properties`
- Collection parameterisation: defaults to `"RAGVisualPages"`, accepts custom name
- Results ordered by descending score
- Returns empty list (not None) when no results pass threshold

**Out of scope:**
- `ensure_visual_collection()` — collection creation, not tested here
- `add_visual_documents()` — ingestion path, not tested here
- `delete_visual_by_source_key()` — deletion, not tested here
- Weaviate schema validation — not performed by this function
- `patch_vectors` content or format — stored but never returned here

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Two pages above threshold | `query_vector=[0.1]*128`, `limit=5`, `score_threshold=0.3`, `tenant_id=None`; mock returns 2 objects with distances 0.19, 0.35 | List of 2 dicts; scores 0.81, 0.65; ordered descending; no `patch_vectors` key in either dict |
| Tenant filtering applied | `tenant_id="acme"`; mock returns only pages with `tenant_id="acme"` | Weaviate `Filter.by_property("tenant_id").equal("acme")` filter passed to query; results only include `tenant_id="acme"` pages |
| All pages above threshold filtered out | All mocked distances > 0.7 (scores < 0.3) with `score_threshold=0.3` | Returns `[]` (empty list, not None) |
| Custom collection name | `collection="CustomVisualPages"` | `client.collections.get("CustomVisualPages")` called (not `"RAGVisualPages"`) |
| Limit respected | `limit=3`; mock has 5 candidates all above threshold | At most 3 results returned (Weaviate limit=3 passed to query) |
| No tenant filter when tenant_id is None | `tenant_id=None` | No `filters` argument passed to Weaviate query (or filters=None); all tenant pages are candidates |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|------------|------------------|-------------------|
| `WeaviateQueryError` | mock `col.query.near_vector` raises `WeaviateQueryError` | Exception propagates directly to caller; no wrapping |
| `WeaviateConnectionError` | mock client raises `WeaviateConnectionError` | Exception propagates directly to caller; no wrapping |

#### Boundary conditions

Derived from spec FR-301, FR-303, FR-305, FR-307, FR-309, FR-311 acceptance criteria:

- `limit=1` → at most 1 result returned (FR-303)
- `limit=50` → up to 50 results returned (FR-303)
- `score_threshold=0.0` → all results returned regardless of similarity (FR-303)
- `score_threshold=1.0` → only perfect matches (score == 1.0) returned; effectively all mocked results filtered out
- `score_threshold=0.3`, one page at exactly 0.30 → included (≥ threshold); one page at 0.299 → excluded
- Empty collection (mock returns 0 objects) → returns `[]`
- Results dict does NOT contain key `"patch_vectors"` under any circumstances (FR-311)
- Named vector `"mean_vector"` specified as `target_vector` in Weaviate query (FR-309)
- Score conversion: distance 0.0 → score 1.0; distance 1.0 → score 0.0 (FR-309 AC: perfect match = 1.0)

#### Integration points

- Calls `client.collections.get(collection)` → expects Weaviate collection handle (Mock: Weaviate Client)
- Calls `col.query.near_vector(near_vector=query_vector, target_vector="mean_vector", ...)` → expects `QueryResult`
- Returns `list[dict]` to caller (EG §3.5 `_run_visual_retrieval`) — each dict has the 10 specified keys
- On `WeaviateQueryError`: propagates to EG §3.5 which catches and returns empty visual results

#### Known test gaps

- **HNSW approximate-nearest-neighbor accuracy** (that the top-K results are truly the most similar) cannot be verified without a live Weaviate instance; tested only with mock return values.
- **Weaviate `certainty` vs. `distance` return field behaviour** across Weaviate versions cannot be verified in unit tests; the `score = 1.0 - distance` formula is assumed correct per EG §3.2.
- **Observability span emission** (`vector_store.visual_search`) requires a live tracer and is not verified in unit tests; integration test only.
- **Schema mismatch detection** (collection exists with wrong dimensions) is explicitly absent per EG §3.2 — no test written for this; documented gap.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section (EG §3.2)
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### EG §3.3 — MinIO Page Image Store (`get_page_image_url`)

**Module purpose:** Generates a presigned MinIO GET URL for a page image object using the `minio_key` verbatim (no suffix appended), with sentinel defaults for bucket and expiry that resolve to configured values.

**In scope:**
- `get_page_image_url(client, minio_key, bucket, expires_in_seconds)` — full function behaviour
- Sentinel default resolution: `bucket=""` → resolves to `MINIO_BUCKET`; `expires_in_seconds=0` → resolves to `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS`
- Key used verbatim: no suffix appended to `minio_key`
- `client.presigned_get_object(bucket, minio_key, expires=timedelta(seconds=...))` called
- Non-existent object: presigned URL still returned (no existence check)
- Propagation of `S3Error` and `InvalidResponseError` to caller

**Out of scope:**
- `store_page_images()` — ingestion path, not tested here
- `delete_page_images()` — ingestion cleanup, not tested here
- `get_document_url()` — existing document URL function, not tested here
- Actual URL validity against a live MinIO instance
- Observability span emission (integration test only)

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Full key, explicit bucket and expiry | `minio_key="pages/abc-123/0007.jpg"`, `bucket="my-bucket"`, `expires_in_seconds=1800` | `client.presigned_get_object("my-bucket", "pages/abc-123/0007.jpg", expires=timedelta(seconds=1800))` called; returns mock URL string |
| Default bucket sentinel | `minio_key="pages/abc-123/0007.jpg"`, `bucket=""`, `expires_in_seconds=3600` | `client.presigned_get_object(MINIO_BUCKET, ...)` called with the configured bucket name |
| Default expiry sentinel | `minio_key="pages/abc-123/0007.jpg"`, `bucket="b"`, `expires_in_seconds=0` | `client.presigned_get_object("b", ..., expires=timedelta(seconds=RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS))` called |
| Both sentinels default | `minio_key="pages/abc-123/0007.jpg"` (no other args) | Both `MINIO_BUCKET` and `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` used |
| Key used verbatim | `minio_key="pages/def-456/0003.jpg"` | Key passed to `presigned_get_object` unchanged; no `.jpg`, `.md`, or other suffix appended |
| Non-existent object key | `minio_key="pages/nonexistent/9999.jpg"` | URL still returned (mock returns a presigned URL; no existence check performed) |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|------------|------------------|-------------------|
| `S3Error` | `client.presigned_get_object` raises `minio.error.S3Error` | Exception propagates directly to caller (EG §3.5 wraps per-page in try/except) |
| `InvalidResponseError` | `client.presigned_get_object` raises `minio.error.InvalidResponseError` | Exception propagates directly to caller |

#### Boundary conditions

Derived from spec FR-401, FR-403 acceptance criteria:

- `minio_key` with nested path `"pages/doc/subdir/0001.jpg"` → key used verbatim, all path components preserved
- `expires_in_seconds=3600` explicit → `timedelta(seconds=3600)` passed to client; not overridden by default
- `expires_in_seconds=60` (minimum valid per config validation) → `timedelta(seconds=60)` passed
- `expires_in_seconds=86400` (maximum valid) → `timedelta(seconds=86400)` passed
- `bucket="custom-bucket"` explicit → not overridden by `MINIO_BUCKET` default

#### Integration points

- Calls `client.presigned_get_object(bucket, minio_key, expires=timedelta(...))` (Mock: MinIO Client)
- Returns `str` (presigned URL) to caller (EG §3.5 `_run_visual_retrieval` URL loop)
- On `S3Error`: propagates to EG §3.5 per-page try/except which logs warning and skips page

#### Known test gaps

- **URL format validity** (that the returned string is a well-formed presigned URL with correct query parameters) requires a live MinIO instance; unit tests only assert that the mock return value is passed through.
- **Expiry verification** (that the URL actually expires after N seconds) requires a live MinIO integration test; not unit-testable.
- **`timedelta` precision** for very large `expires_in_seconds` values is assumed correct by Python's `datetime.timedelta`; no edge-case test written.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section (EG §3.3)
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### EG §3.4 — Retrieval Pipeline Schemas

**Module purpose:** Defines `VisualPageResult` (a pure-data dataclass with nine typed fields representing a matched visual page) and the `visual_results` extension on `RAGResponse`; contains no logic or validation.

**In scope:**
- `VisualPageResult` dataclass: importable, nine required fields with correct types
- `RAGResponse.visual_results`: optional field, defaults to `None`
- Backward compatibility: `RAGResponse` constructed without `visual_results` has `visual_results=None`
- No exceptions raised by the schema module itself (missing required fields raise standard Python `TypeError`)
- `VisualPageResult` is importable from `retrieval.common.schemas`

**Out of scope:**
- Field value validation (e.g., score range) — no logic in this module
- Serialization (Pydantic) — owned by EG §3.8 (server schemas)
- Construction logic — owned by calling code in EG §3.5

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Construct `VisualPageResult` with all fields | All nine fields provided with correct types | Instance created; all fields accessible with provided values |
| `RAGResponse` without `visual_results` | `RAGResponse(query="q", ...)` constructed without `visual_results` kwarg | `response.visual_results is None` |
| `RAGResponse` with `visual_results` list | `RAGResponse(..., visual_results=[vpr1, vpr2])` | `response.visual_results == [vpr1, vpr2]` |
| `RAGResponse` with empty `visual_results` list | `RAGResponse(..., visual_results=[])` | `response.visual_results == []` |
| Import path | `from retrieval.common.schemas import VisualPageResult` | Import succeeds |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|------------|------------------|-------------------|
| `TypeError` | `VisualPageResult()` called with missing required field | Python raises `TypeError` (standard dataclass behavior); no custom exception |

#### Boundary conditions

Derived from spec FR-501, FR-503 acceptance criteria:

- `score=0.0` field value → accepted without error (no range checking in schema module)
- `score=1.0` → accepted
- `page_number=1` (minimum 1-indexed) → accepted
- `page_image_url=""` (empty string) → accepted at schema level (validation is caller's responsibility)
- `total_pages=1` (single-page document) → accepted
- Existing `RAGResponse` fields (e.g., `results`, `processed_query`) are unaffected by addition of `visual_results` field (backward compatibility; FR-503 AC)

#### Integration points

- `VisualPageResult` instantiated by EG §3.5 `_run_visual_retrieval` — no contract violation expected at this boundary
- `RAGResponse.visual_results` consumed by EG §3.8 server schemas serialization layer
- Receives no external calls; is a pure data definition module

#### Known test gaps

- **Field type enforcement at construction** is not enforced by Python `@dataclass` (no `__post_init__` validation); a `score` of type `str` would be accepted silently. No test for type enforcement — this is a known property of the schema design.
- **Negative `page_number`** and **`score > 1.0`** are accepted without error at the schema layer; the spec states these constraints are the caller's responsibility. No rejection test written.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section (EG §3.4)
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### EG §3.5 — RAGChain Visual Retrieval Track

**Module purpose:** Orchestrates the visual retrieval track within `RAGChain.run()`: lazy ColQwen2 model loading (`_ensure_visual_model`), sequential three-step visual pipeline (`_run_visual_retrieval`), stage timing, graceful degradation on errors, and lifecycle cleanup via `close()`.

**In scope:**
- `__init__`: `_visual_retrieval_enabled` flag, `_visual_model=None`, `_visual_processor=None` initial state; `validate_visual_retrieval_config()` called at init when enabled
- `_ensure_visual_model()`: cold path loads model; warm path returns immediately on `_visual_model is not None`
- `_run_visual_retrieval(processed_query, tenant_id)`: calls `embed_text_query`, `search_visual`, per-page `get_page_image_url`, assembles `VisualPageResult` list
- `run()` integration: visual track runs after text stages complete; `visual_results` attached to `RAGResponse`; uses processed query, not raw query
- Stage timing: `"visual_retrieval"` entry in `stage_timings`
- Graceful degradation: `ColQwen2LoadError`, `VisualEmbeddingError`, `WeaviateQueryError` → `visual_results=[]` or `None`; text results unaffected
- Per-page URL failure: page skipped, warning logged, remaining pages included
- Empty-list normalization: `_run_visual_retrieval` returning `[]` → `response.visual_results = None`
- Disabled path: `RAG_VISUAL_RETRIEVAL_ENABLED=false` → no model load, no visual logic, `visual_results=None`
- `close()`: calls `unload_colqwen_model` if model loaded; sets both references to `None`
- Tenant ID forwarded from `run()` to `search_visual`

**Out of scope:**
- Actual GPU/VRAM management (hardware)
- Text track stages (query processing, BGE-M3, hybrid search, reranking, generation)
- `embed_text_query` internals — mocked
- `visual_search` internals — mocked
- `get_page_image_url` internals — mocked
- Stage budget exhaustion / partial results from budget (FR-617) — see Known Test Gaps
- Thread-safety of lazy load — noted as known limitation in EG §8

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Warm model — visual results found | `RAG_VISUAL_RETRIEVAL_ENABLED=true`, model pre-loaded, `search_visual` returns 3 page records, all URL generation succeeds | `response.visual_results` is list of 3 `VisualPageResult`; each has non-empty `page_image_url` |
| Cold start — first visual query | `_visual_model is None` before call | `_ensure_visual_model` loads model; `_visual_model` is non-None after; subsequent call skips load (warm path) |
| Processed query used, not raw | `run(query="what does fig 3 show?")` with `process_query` returning `"what does figure 3 illustrate?"` | `embed_text_query` called with `"what does figure 3 illustrate?"`, not `"what does fig 3 show?"` |
| Tenant ID forwarded | `run(query="q", tenant_id="acme")` | `search_visual` called with `tenant_id="acme"` |
| Visual track disabled | `RAG_VISUAL_RETRIEVAL_ENABLED=false` | `_ensure_visual_model` never called; `search_visual` never called; `response.visual_results is None` |
| Stage timing recorded | Visual track executes | `response.stage_timings` contains entry with `stage="visual_retrieval"` and numeric `duration_ms` |
| Empty list → None normalization | `search_visual` returns empty list (score threshold filters all) | `response.visual_results is None` (not `[]`) |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|------------|------------------|-------------------|
| `ColQwen2LoadError` from `_ensure_visual_model` | `load_colqwen_model` raises `ColQwen2LoadError` | `response.visual_results` is `[]` or `None`; text results intact; warning/error logged |
| `VisualEmbeddingError` from `embed_text_query` | `embed_text_query` raises `VisualEmbeddingError` | `response.visual_results` is `[]`; text results intact; warning logged |
| `WeaviateQueryError` from `search_visual` | `search_visual` raises `WeaviateQueryError` | `response.visual_results` is `[]`; text results intact; warning logged |
| Per-page URL generation failure | `get_page_image_url` raises `S3Error` for page 2 of 3 | Pages 1 and 3 appear in `visual_results`; page 2 omitted; warning logged; no exception raised to `run()` |
| `validate_visual_retrieval_config` fails at init | Invalid config (e.g., score threshold 1.5) | `ValueError` raised from `__init__`; RAGChain not constructed |

#### Boundary conditions

Derived from spec FR-601, FR-603, FR-605, FR-607, FR-609, FR-611, FR-613, FR-615, FR-617 acceptance criteria:

- After `__init__` with `RAG_VISUAL_RETRIEVAL_ENABLED=true`, `_visual_model is None` (model not pre-loaded; FR-603 AC)
- Second visual query reuses cached model: `load_colqwen_model` called exactly once across two queries (FR-603 AC)
- After `close()`, `_visual_model is None` and `_visual_processor is None` (FR-613 AC)
- `close()` when visual track never used (model never loaded) — no error, `unload_colqwen_model` not called (FR-613 AC)
- `stage_timings` has NO `"visual_retrieval"` entry when `RAG_VISUAL_RETRIEVAL_ENABLED=false` (FR-611 AC)
- Visual search results include only pages matching `tenant_id` when `tenant_id` provided (FR-609 AC)

#### Integration points

- Calls `validate_visual_retrieval_config()` (EG §3.7) at init — expects `ValueError` on bad config
- Calls `embed_text_query(model, processor, processed_query)` (EG §3.1 via Mock: ColQwen2) → expects `list[float]` of length 128
- Calls `search_visual(client, query_vector, limit, score_threshold, tenant_id)` (EG §3.6/§3.2 via Mock: Weaviate) → expects `list[dict]`
- Calls `get_page_image_url(minio_client, minio_key)` (EG §3.3 via Mock: MinIO Client) → expects `str`
- Produces `RAGResponse` with `visual_results: Optional[List[VisualPageResult]]` — consumed by EG §3.8 serialization

#### Known test gaps

- **Stage budget exhaustion (FR-617):** The budget enforcement and partial-result behavior when `RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS` is exceeded requires time-based testing that is difficult to make deterministic in unit tests. No unit test written for the partial-result-on-budget-exhaustion scenario — integration test only.
- **`budget_exhausted_stage="visual_retrieval"` response field (FR-617 AC):** Dependent on budget implementation details not fully captured in EG §3.5 description; gap noted.
- **Thread safety of `_ensure_visual_model`** (EG §8 known limitation): The race condition where two threads simultaneously observe `_visual_model is None` and both call `load_colqwen_model` cannot be reliably tested with standard Python unittest mock patching.
- **NFR-903 VRAM budget compliance** (total < 5.5 GB with all three models): Hardware integration test only; no unit test written.
- **`visual_retrieval.model_load` span emitted only on cold start** (NFR-909): Verifying span presence requires a real or mock tracer implementation; not covered in basic unit tests.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section (EG §3.5)
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### EG §3.6 — VectorBackend ABC and Public API

**Module purpose:** `backend.py` declares four new abstract methods (`ensure_visual_collection`, `add_visual_documents`, `delete_visual_by_source_key`, `search_visual`) on the `VectorBackend` ABC; `vector_db/__init__.py` exposes corresponding public functions that delegate to the active backend via `_get_vector_backend()`.

**In scope:**
- `VectorBackend` ABC has abstract method `search_visual` (and the other three visual methods)
- A concrete subclass that does not implement `search_visual` cannot be instantiated
- `vector_db.__init__.search_visual(...)` delegates to `_get_vector_backend().search_visual(...)`
- Public function adds no logic — pure delegation
- `search_visual` is included in `__all__` of `vector_db/__init__.py`
- Unknown `VECTOR_DB_BACKEND` raises `ValueError` at first use

**Out of scope:**
- `WeaviateBackend` concrete implementation internals — tested in EG §3.2
- `ensure_visual_collection`, `add_visual_documents`, `delete_visual_by_source_key` full behavior — ingestion path, not retrieval path
- Backend connection management

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `search_visual` delegates to backend | `vector_db.search_visual(client, [0.1]*128, limit=5, score_threshold=0.3)` | `_get_vector_backend().search_visual(client, [0.1]*128, 5, 0.3, None, None)` called once; returns backend mock result |
| `search_visual` with optional args | `vector_db.search_visual(..., tenant_id="t1", collection="CustomColl")` | Backend `search_visual` called with `tenant_id="t1"`, `collection="CustomColl"` |
| ABC prevents instantiation without implementation | Concrete class inherits `VectorBackend` but does not implement `search_visual` | `TypeError` raised when attempting to instantiate |
| `search_visual` in `__all__` | `dir(vector_db)` or inspect `__all__` | `"search_visual"` present in `__all__` |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|------------|------------------|-------------------|
| `ValueError` | `VECTOR_DB_BACKEND` set to `"unknown_backend"` | `ValueError` raised from `_get_vector_backend()` at first call to any public function |
| Backend exception propagated | Backend `search_visual` raises `WeaviateConnectionError` | Exception propagates through public function to caller without wrapping |

#### Boundary conditions

Derived from spec FR-313 acceptance criteria:

- `collection=None` passed to public function → forwarded as `None` to backend (backend applies its own default)
- `collection="RAGVisualPages"` explicit → forwarded as-is
- `search_visual` result from backend is returned unchanged by public function (no transformation)

#### Integration points

- `_get_vector_backend()` returns concrete backend (Mock: Vector Backend for unit tests)
- Public `search_visual(...)` → `backend.search_visual(...)` → returns `list[dict[str, Any]]`
- Called by EG §3.5 RAGChain `_run_visual_retrieval` step 2

#### Known test gaps

- **`_get_vector_backend()` singleton lifecycle** (initialized once per process) is difficult to unit-test in isolation without patching module-level state; tests rely on dependency injection or monkeypatching.
- **`ensure_visual_collection`, `add_visual_documents`, `delete_visual_by_source_key` public API delegation** follows the same pattern as `search_visual`; these are tested by pattern analogy, not exhaustively, since they belong to the ingestion path.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section (EG §3.6)
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### EG §3.7 — Visual Retrieval Configuration Keys

**Module purpose:** Reads and validates all visual retrieval environment variables at module import time; provides `validate_visual_retrieval_config()` for cross-key consistency checks called by `RAGChain.__init__`.

**In scope:**
- `RAG_VISUAL_RETRIEVAL_ENABLED` boolean parsing (`"true"`, `"1"`, `"yes"` → True; any other → False)
- `RAG_VISUAL_RETRIEVAL_LIMIT` integer parsing; clamping to [1, 50] with `logger.warning` on out-of-range
- `RAG_VISUAL_RETRIEVAL_MIN_SCORE` float parsing; default 0.3
- `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` integer parsing; default 3600
- `RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS` integer parsing; default 10000
- `validate_visual_retrieval_config()`:
  - raises `ValueError` when `RAG_INGESTION_VISUAL_TARGET_COLLECTION` is empty
  - raises `ValueError` when `RAG_VISUAL_RETRIEVAL_MIN_SCORE` outside [0.0, 1.0]
  - raises `ValueError` when `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` outside [60, 86400]
  - error message identifies the conflicting key(s)
- Default values applied when environment variable is unset

**Out of scope:**
- `RAG_INGESTION_*` keys (ingestion-side configuration) — not tested here except `RAG_INGESTION_VISUAL_TARGET_COLLECTION` as used in validation
- Boolean coercion behavior of `bool("false")` trap — documented rationale; not a failure mode
- Configuration persistence across process restarts (operational concern)

#### Happy path scenarios

| Scenario | Input (env var) | Expected output |
|----------|-----------------|-----------------|
| Default values applied | All visual retrieval env vars unset | `RAG_VISUAL_RETRIEVAL_ENABLED=False`, `LIMIT=5`, `MIN_SCORE=0.3`, `URL_EXPIRY=3600`, `BUDGET=10000` |
| Enabled flag truthy variants | `RAG_VISUAL_RETRIEVAL_ENABLED="true"` / `"1"` / `"yes"` | `RAG_VISUAL_RETRIEVAL_ENABLED=True` for all three |
| Enabled flag falsy variants | `"false"` / `"0"` / `"no"` / `""` / `"TRUE"` (uppercase not listed as valid) | `RAG_VISUAL_RETRIEVAL_ENABLED=False` |
| Limit in valid range | `RAG_VISUAL_RETRIEVAL_LIMIT="10"` | `RAG_VISUAL_RETRIEVAL_LIMIT=10`; no warning logged |
| `validate_visual_retrieval_config` passes | Valid collection name, score in [0,1], expiry in [60,86400] | No exception raised |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|------------|------------------|-------------------|
| `logger.warning` + clamping | `RAG_VISUAL_RETRIEVAL_LIMIT="0"` | `RAG_VISUAL_RETRIEVAL_LIMIT` clamped to 1; warning logged containing `"out of range"` or `"clamping"` |
| `logger.warning` + clamping | `RAG_VISUAL_RETRIEVAL_LIMIT="51"` | `RAG_VISUAL_RETRIEVAL_LIMIT` clamped to 50; warning logged |
| `ValueError` at import time | `RAG_VISUAL_RETRIEVAL_LIMIT="not-a-number"` | `ValueError` raised at module import time (int() conversion fails) |
| `ValueError` from `validate_visual_retrieval_config` | `RAG_INGESTION_VISUAL_TARGET_COLLECTION=""` (empty string) | `ValueError` raised; message identifies `RAG_INGESTION_VISUAL_TARGET_COLLECTION` |
| `ValueError` from `validate_visual_retrieval_config` | `RAG_VISUAL_RETRIEVAL_MIN_SCORE="-0.1"` | `ValueError` raised; message identifies `RAG_VISUAL_RETRIEVAL_MIN_SCORE` |
| `ValueError` from `validate_visual_retrieval_config` | `RAG_VISUAL_RETRIEVAL_MIN_SCORE="1.5"` | `ValueError` raised; message identifies `RAG_VISUAL_RETRIEVAL_MIN_SCORE` |
| `ValueError` from `validate_visual_retrieval_config` | `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS="30"` (< 60) | `ValueError` raised; message identifies `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` |
| `ValueError` from `validate_visual_retrieval_config` | `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS="100000"` (> 86400) | `ValueError` raised; message identifies `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` |

#### Boundary conditions

Derived from spec FR-101, FR-103, FR-105, FR-107, FR-109, FR-111 acceptance criteria:

- `RAG_VISUAL_RETRIEVAL_ENABLED="false"` → `False` (not `True`; verifies `bool("false")` trap is avoided; FR-101)
- `RAG_VISUAL_RETRIEVAL_LIMIT="1"` (minimum valid) → no clamping, no warning (FR-103)
- `RAG_VISUAL_RETRIEVAL_LIMIT="50"` (maximum valid) → no clamping, no warning (FR-103)
- `RAG_VISUAL_RETRIEVAL_MIN_SCORE="0.0"` → valid, no error (FR-105)
- `RAG_VISUAL_RETRIEVAL_MIN_SCORE="1.0"` → valid, no error (FR-105)
- `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS="60"` (minimum valid) → passes validation (FR-107)
- `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS="86400"` (maximum valid) → passes validation (FR-107)

#### Integration points

- Called by: EG §3.5 `RAGChain.__init__` invokes `validate_visual_retrieval_config()` when `RAG_VISUAL_RETRIEVAL_ENABLED=True`
- Raises `ValueError` → propagates out of `__init__`, preventing RAGChain construction

#### Known test gaps

- **Module-level import side effects** (constants assigned at import time) require `importlib.reload()` or `monkeypatch.setenv()` + reimport to test different env var values; test isolation is complex. Tests that patch env vars and reload the module may have order-dependency issues.
- **`RAG_INGESTION_COLQWEN_MODEL` reuse for retrieval** (FR-109): the requirement that no separate `RAG_VISUAL_RETRIEVAL_MODEL` key exists is verified by absence — confirming the key does not appear in `settings.py`. No direct assertion test is written for this "key should not exist" property.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section (EG §3.7)
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### EG §3.8 — API Response Schemas

**Module purpose:** Defines `VisualPageResultResponse` (Pydantic model mirroring `VisualPageResult` without `tenant_id`) and extends `QueryResponse` with an optional `visual_results` field; also adds `"visual_retrieval"` as an allowed key in `QueryRequest.stage_budget_overrides`.

**In scope:**
- `VisualPageResultResponse`: importable from server schemas; nine fields; serializes to JSON; `tenant_id` NOT present
- `QueryResponse.visual_results`: optional field, defaults to `None`; serializes as absent JSON key when `None` with `response_model_exclude_none=True`; serializes as array when non-None
- `QueryRequest.stage_budget_overrides` validator: `"visual_retrieval"` is an allowed key; unknown keys rejected
- Backward compatibility: `QueryResponse` without `visual_results` still valid
- Field types match spec FR-701 exactly

**Out of scope:**
- FastAPI routing (not tested here)
- Database/pipeline logic
- `VisualPageResult` internal dataclass (EG §3.4)
- Presigned URL content or expiry
- `tenant_id` field — intentionally absent from API response schema

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Construct `VisualPageResultResponse` with all nine fields | All fields provided with correct types | Instance created; `.model_dump()` returns dict with all nine fields; no `tenant_id` key |
| `QueryResponse` with `visual_results=None` | `QueryResponse(..., visual_results=None)` | `.model_dump(exclude_none=True)` does NOT include `"visual_results"` key |
| `QueryResponse` with `visual_results` list | `QueryResponse(..., visual_results=[VisualPageResultResponse(...)])` | `.model_dump()` includes `"visual_results"` as list of dicts |
| `QueryRequest` with `stage_budget_overrides={"visual_retrieval": 15000}` | Valid override dict | No validation error raised |
| `VisualPageResultResponse` in OpenAPI schema | Via FastAPI `app.openapi()` | `"VisualPageResultResponse"` present in schema components |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|------------|------------------|-------------------|
| `ValidationError` | `VisualPageResultResponse(page_number="not-an-int", ...)` | Pydantic raises `ValidationError` |
| `ValidationError` | `QueryRequest(stage_budget_overrides={"invalid_stage": 5000})` | Pydantic raises `ValidationError` identifying the disallowed key |

#### Boundary conditions

Derived from spec FR-701, FR-703 acceptance criteria:

- `VisualPageResultResponse` has exactly nine fields (no `tenant_id`, no extra fields from `VisualPageResult`)
- `visual_results=[]` (empty list) → serialized as `"visual_results": []` in JSON (distinct from `None`)
- `score=0.81` (float) → serialized as JSON number, not string
- Existing `QueryResponse` fields (e.g., `results`, `query`, `processed_query`) are unaffected when `visual_results` is added
- `stage_budget_overrides={"visual_retrieval": 10000}` → valid; `{"embedding": 2000}` → still valid (existing stage); `{"nonexistent_stage": 1}` → `ValidationError`

#### Integration points

- `VisualPageResultResponse` populated from `VisualPageResult` dataclass (EG §3.4) by the route handler
- `QueryResponse.visual_results` consumed by FastAPI JSON serialization layer
- `QueryRequest.stage_budget_overrides["visual_retrieval"]` forwarded to `RAGChain.run()` as `stage_budget_overrides`

#### Known test gaps

- **OpenAPI schema generation** (that `VisualPageResultResponse` appears in the auto-generated docs at the correct path) requires a running FastAPI app; marked as integration test.
- **`response_model_exclude_none=True` behavior** at the FastAPI route level (not Pydantic model level) requires a test client with a configured FastAPI app, not a pure unit test.
- **Pydantic v1 vs. v2 compatibility** of `model_dump(exclude_none=True)` vs. `.dict(exclude_none=True)` — assumes Pydantic v2; if the project uses v1, `model_dump` is unavailable. Test must be adapted to project's Pydantic version.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section (EG §3.8)
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

## Integration Test Specifications

### Integration: Happy path — visual retrieval enabled, results found

**Scenario:** A query with `RAG_VISUAL_RETRIEVAL_ENABLED=true` completes the full visual track — text encoding, visual search, presigned URL generation — and returns a `RAGResponse` with both text and visual results.

**Entry point:** `RAGChain.run(query="quarterly revenue chart Q3 2025", tenant_id="acme")`

**Flow:**

1. `run()` receives query; text track stages execute (mocked via Mock: RAGChain Text Track).
   - Output: `processed_query = "Q3 2025 quarterly revenue chart"`, text results populated.
2. `_ensure_visual_model()` called — warm path (model pre-loaded in fixture); returns immediately.
3. `embed_text_query(model, processor, "Q3 2025 quarterly revenue chart")` called.
   - Mock: ColQwen2 Model and Processor returns a 128-element float list `query_vector`.
   - Output: `query_vector: list[float]`, `len == 128`.
4. `search_visual(weaviate_client, query_vector, limit=5, score_threshold=0.3, tenant_id="acme")` called.
   - Mock: Weaviate Client returns 3 page records with scores 0.81, 0.74, 0.61 (all above threshold).
   - Output: `page_records: list[dict]` with 3 entries; each has `minio_key`.
5. Presigned URL loop: `get_page_image_url(minio_client, minio_key=record["minio_key"])` called for each page.
   - Mock: MinIO Client returns a presigned URL string for each call.
   - Output: 3 `VisualPageResult` instances assembled with `page_image_url` set.
6. `run()` attaches `visual_results` to `RAGResponse`:
   - `response.visual_results = [vpr1, vpr2, vpr3]` (non-empty list).
7. `stage_timings` updated: entry with `stage="visual_retrieval"` and numeric `duration_ms` present.

**What to assert:**
- `response.visual_results` is a list of exactly 3 `VisualPageResult` instances
- Each `VisualPageResult.page_image_url` is non-empty string
- `response.visual_results[0].score == 0.81` (highest score first; ordered descending)
- `response.visual_results` has no entry with `page_number` values not returned by mock Weaviate
- `embed_text_query` was called with the **processed** query `"Q3 2025 quarterly revenue chart"` (not the raw query)
- `search_visual` was called with `tenant_id="acme"`
- `stage_timings` contains entry with `stage="visual_retrieval"`
- Text results (`response.results`) are present and unchanged (visual track is additive)

**Mocks required:** Mock: ColQwen2 Model and Processor, Mock: Weaviate Client, Mock: MinIO Client, Mock: RAGChain Text Track

---

### Integration: Visual retrieval disabled — zero-cost path

**Scenario:** With `RAG_VISUAL_RETRIEVAL_ENABLED=false`, a query completes with text results only; no visual infrastructure is touched.

**Entry point:** `RAGChain.run(query="quarterly revenue chart Q3 2025", tenant_id="acme")` with `RAG_VISUAL_RETRIEVAL_ENABLED=false`

**Flow:**

1. `run()` receives query; text track executes normally (mocked).
2. `self._visual_retrieval_enabled` is `False`; visual track branch is not entered.
3. No call to `_ensure_visual_model`, `embed_text_query`, `search_visual`, or `get_page_image_url`.
4. `RAGResponse` returned with `visual_results=None`.

**What to assert:**
- `response.visual_results is None`
- `embed_text_query` was NOT called
- `search_visual` was NOT called
- `get_page_image_url` was NOT called
- `load_colqwen_model` was NOT called
- `stage_timings` does NOT contain an entry with `stage="visual_retrieval"`
- Text results are present and unaffected

**Mocks required:** Mock: RAGChain Text Track (all visual mocks should remain uncalled)

---

### Integration: Error path — ColQwen2 load failure, text results preserved

**Scenario:** On the first visual query, `load_colqwen_model` raises `ColQwen2LoadError`. The pipeline degrades gracefully — text results are returned with `visual_results` set to empty list.

**Entry point:** `RAGChain.run(query="any query", tenant_id=None)` with `RAG_VISUAL_RETRIEVAL_ENABLED=true`, `_visual_model=None`

**Flow:**

1. Text track executes; text results produced (mocked).
2. `_ensure_visual_model()` called — cold path.
3. `load_colqwen_model(...)` raises `ColQwen2LoadError("CUDA not available")`.
4. `_run_visual_retrieval` propagates `ColQwen2LoadError` to `run()`.
5. `run()` catches `ColQwen2LoadError`; sets `visual_results` to `[]` or `None` per degradation policy (NFR-905); logs warning/error.
6. `RAGResponse` returned with text results intact and `visual_results=[]` (indicating failure, not disabled).

**What to assert:**
- `response.visual_results == []` (failure state; distinct from `None` which means disabled)
- `response.results` is non-empty (text track unaffected)
- Warning or error log message emitted referencing `ColQwen2LoadError`
- No unhandled exception raised from `run()`

**Mocks required:** Mock: RAGChain Text Track, Mock: ColQwen2 Model and Processor (configured to raise `ColQwen2LoadError`)

---

### Integration: Partial URL failure — some pages skipped

**Scenario:** Visual search returns 3 page records. MinIO presigned URL generation fails for the middle page (network error). The response contains 2 visual results; the failed page is skipped with a warning.

**Entry point:** `RAGChain._run_visual_retrieval("some query", tenant_id="t1")`

**Flow:**

1. `embed_text_query` returns valid 128-dim vector (mocked).
2. `search_visual` returns 3 page records (pages 1, 2, 3) (mocked).
3. URL generation loop:
   - Page 1: `get_page_image_url` returns valid URL.
   - Page 2: `get_page_image_url` raises `minio.error.S3Error`.
   - Page 3: `get_page_image_url` returns valid URL.
4. Page 2 caught by per-page try/except; warning logged; `continue` to page 3.
5. Returns list of 2 `VisualPageResult` instances (pages 1 and 3).

**What to assert:**
- Return value contains exactly 2 `VisualPageResult` entries
- Page 2 (the one with the `S3Error`) is not present in results
- Pages 1 and 3 are present with valid `page_image_url` fields
- A warning-level log containing `"Failed to generate presigned URL"` or similar was emitted
- No exception propagates from `_run_visual_retrieval`

**Mocks required:** Mock: ColQwen2 Model and Processor, Mock: Weaviate Client, Mock: MinIO Client (configured to raise `S3Error` on second call only)

---

### Integration: Weaviate search failure — empty visual results, text intact

**Scenario:** Weaviate's near-vector query raises `WeaviateQueryError`. The pipeline degrades gracefully.

**Entry point:** `RAGChain.run(query="q", tenant_id=None)` with `RAG_VISUAL_RETRIEVAL_ENABLED=true`

**Flow:**

1. Text track executes; results produced (mocked).
2. `embed_text_query` returns valid 128-dim vector (mocked).
3. `search_visual` raises `weaviate.exceptions.WeaviateQueryError("query failed")` (mocked).
4. `run()` catches `WeaviateQueryError`; sets `visual_results=[]`; logs warning.
5. `RAGResponse` returned with text results intact.

**What to assert:**
- `response.visual_results == []`
- `response.results` is non-empty
- Warning log emitted referencing Weaviate failure
- `get_page_image_url` was NOT called (search failed before URL generation)

**Mocks required:** Mock: RAGChain Text Track, Mock: ColQwen2 Model and Processor, Mock: Weaviate Client (raises `WeaviateQueryError`)

---

### Integration: Score threshold filtering — all results below threshold

**Scenario:** Weaviate returns pages, but after distance-to-similarity conversion, all pages score below the configured threshold. Visual results list is empty (not None), distinct from disabled state.

**Entry point:** `RAGChain.run(query="obscure query", tenant_id=None)` with `RAG_VISUAL_RETRIEVAL_ENABLED=true`, `RAG_VISUAL_RETRIEVAL_MIN_SCORE=0.5`

**Flow:**

1. Text track executes (mocked).
2. `embed_text_query` returns valid vector (mocked).
3. `search_visual` called with `score_threshold=0.5`; Weaviate mock returns 2 objects with distances 0.6, 0.7 (scores 0.4, 0.3 — below threshold); `visual_search` post-filters → returns `[]`.
4. `_run_visual_retrieval` returns `[]`.
5. `run()`: empty list `[]` normalized to `None` per EG §3.5 (`visual_results = visual_results if visual_results else None`).
6. `response.visual_results is None`.

**What to assert:**
- `response.visual_results is None` (empty list normalized to None by `run()`)
- No presigned URL calls made (no pages passed threshold)
- Text results unaffected

**Mocks required:** Mock: RAGChain Text Track, Mock: ColQwen2 Model and Processor, Mock: Weaviate Client (returns objects all below threshold)

---

## FR-to-Test Traceability Matrix

Every FR from the spec appears below. Abbreviations: module test section short names used (full section titles in Module Test Specifications above).

| FR / NFR | Priority | Acceptance Criteria Summary | Module Test Section | Integration Test |
|----------|----------|----------------------------|---------------------|-----------------|
| FR-101 | MUST | `RAG_VISUAL_RETRIEVAL_ENABLED=false` → `visual_results=None`; `=true` → visual track executes | EG §3.7 — happy path (flag parsing) | Integration: disabled path |
| FR-103 | MUST | `LIMIT=3` → at most 3 results; out-of-range → log warning + clamp | EG §3.7 — error scenarios (clamping) | Integration: happy path (limit respected) |
| FR-105 | MUST | Pages below `MIN_SCORE` excluded; all below → empty list (not None) | EG §3.2 — boundary (score threshold); EG §3.7 — validation | Integration: score threshold filtering |
| FR-107 | SHOULD | `URL_EXPIRY=1800` → URLs expire after 1800s; default 3600 | EG §3.3 — happy path (expiry sentinel); EG §3.7 — boundary | Not covered in integration test — see Known Gaps |
| FR-109 | MUST | `RAG_INGESTION_COLQWEN_MODEL` reused; no separate retrieval model key | EG §3.7 — known test gaps | Not directly testable; known gap |
| FR-111 | MUST | Empty collection name or out-of-range score/expiry → config error at startup identifying keys | EG §3.7 — error scenarios (validate_visual_retrieval_config) | Integration: ColQwen2 load failure (validate called at init) |
| FR-201 | MUST | Non-empty query → `list[float]` of exactly 128 elements; deterministic | EG §3.1 — happy path | Integration: happy path (embed step) |
| FR-203 | MUST | Uses `process_queries()`; mean-pools across tokens; dtype float32; `inference_mode` | EG §3.1 — happy path (process_queries routing); boundary | Integration: happy path |
| FR-205 | MUST | Empty or whitespace → `ValueError` with "empty"/"blank"; model not invoked | EG §3.1 — error scenarios | — |
| FR-207 | MUST | `model=None` → `ColQwen2LoadError`; forward pass `RuntimeError` → `VisualEmbeddingError` with `__cause__` | EG §3.1 — error scenarios | Integration: error path (ColQwen2 failure) |
| FR-301 | MUST | 128-dim query vector → list of result dicts ordered by descending score | EG §3.2 — happy path | Integration: happy path (search step) |
| FR-303 | MUST | `limit=5, score_threshold=0.4` → at most 5 results, all ≥ 0.4; empty list when none qualify | EG §3.2 — happy path, boundary | Integration: happy path; score threshold filtering |
| FR-305 | MUST | `tenant_id="tenant_a"` → only matching pages returned; `None` → no filter | EG §3.2 — happy path (tenant filtering) | Integration: happy path (tenant_id forwarded) |
| FR-307 | MUST | `collection="CustomVisualPages"` → queries that collection; default uses `"RAGVisualPages"` | EG §3.2 — happy path (custom collection) | — |
| FR-309 | MUST | `near_vector` on `mean_vector` named vector with cosine; perfect match → score 1.0 | EG §3.2 — boundary (score conversion) | Integration: happy path |
| FR-311 | MUST | `patch_vectors` not in returned dicts | EG §3.2 — boundary (patch_vectors excluded) | Integration: happy path (dict keys asserted) |
| FR-313 | MUST | `VectorBackend` has abstract `search_visual`; Weaviate implements it; `vector_db.__init__` exports it | EG §3.6 — happy path, error scenarios | — |
| FR-401 | MUST | `minio_key="pages/abc/0001.jpg"`, `expires_in_seconds=3600` → presigned URL; no suffix appended | EG §3.3 — happy path | Integration: happy path (URL step) |
| FR-403 | MUST | Default `bucket` → `MINIO_BUCKET`; default `expires_in_seconds` → `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` | EG §3.3 — happy path (sentinel defaults) | — |
| FR-501 | MUST | `VisualPageResult` has all 9 fields with specified types; importable from `retrieval.common.schemas` | EG §3.4 — happy path | Integration: happy path (VisualPageResult fields asserted) |
| FR-503 | MUST | `RAGResponse` without `visual_results` → `None`; with visual track → list or empty; existing fields unaffected | EG §3.4 — happy path, boundary | Integration: all scenarios (visual_results field) |
| FR-601 | MUST | Visual stage timing appears after reranking in `stage_timings`; no visual function before reranking | EG §3.5 — happy path (stage timing) | Integration: happy path (stage ordering) |
| FR-603 | MUST | After `__init__`, no model loaded; after first query, model cached; second query reuses cache | EG §3.5 — happy path (cold start), boundary | Integration: happy path (warm model fixture) |
| FR-605 | MUST | Visual encoding uses processed query, not raw query | EG §3.5 — happy path (processed query) | Integration: happy path (embed_text_query called with processed query) |
| FR-607 | MUST | Each `VisualPageResult.page_image_url` is non-empty presigned URL with correct expiry | EG §3.5 — happy path | Integration: happy path (page_image_url asserted) |
| FR-609 | MUST | `tenant_id` from request forwarded to `search_visual` | EG §3.5 — happy path (tenant forwarding) | Integration: happy path |
| FR-611 | MUST | When visual track executes, `stage_timings` has `"visual_retrieval"` entry with numeric `duration_ms`; absent when disabled | EG §3.5 — happy path, boundary | Integration: happy path; disabled path |
| FR-613 | MUST | After `close()`, `_visual_model is None`; VRAM released | EG §3.5 — boundary (close) | — |
| FR-615 | MUST | `ENABLED=false` → no ColQwen2 imports, no visual search, no URLs, `visual_results=None` | EG §3.5 — happy path (disabled) | Integration: disabled path |
| FR-617 | SHOULD | Stage budget limits visual retrieval wall-clock time; partial results on budget exhaustion; `budget_exhausted_stage` field set | EG §3.5 — known test gaps | Known gap — no integration test (see EG §3.5 known gaps) |
| FR-701 | MUST | `VisualPageResultResponse` has all 9 fields (no `tenant_id`); importable; in OpenAPI schema | EG §3.8 — happy path | Known gap — OpenAPI schema test requires running FastAPI app |
| FR-703 | MUST | `QueryResponse.visual_results`: `None` → absent from JSON; list → array in JSON | EG §3.8 — happy path, boundary | — |
| NFR-901 | SHOULD | Warm-model visual stage < 2000ms P95; cold start may be up to 30s | No unit test — performance benchmark only | No integration test — requires live GPU |
| NFR-903 | MUST | All three models coexist within 5.5 GB VRAM on 6 GB GPU | No unit test — hardware integration test only | No integration test — requires hardware |
| NFR-905 | MUST | Each failure mode (ColQwen2 load, encode, Weaviate search, MinIO URL) → text results intact, `visual_results=[]` | EG §3.5 — error scenarios | Integration: error path scenarios |
| NFR-907 | MUST | All 5 config keys loaded from env vars; missing vars use defaults; no hardcoded values in retrieval code | EG §3.7 — happy path (defaults) | — |
| NFR-909 | MUST | 4 spans emitted: `model_load`, `text_encode`, `search`, `presigned_urls`; attributes per span | EG §3.5 — known test gaps (observability) | Known gap — requires live tracer |
| NFR-911 | SHOULD | INFO log: result count + duration; cold-start INFO: model loaded; DEBUG: vector dimensions + score range | EG §3.5 — known test gaps (logging) | No integration test — log content verification only |

### Known Coverage Gaps Summary

The following requirements have no unit test or integration test coverage, with documented reasons:

| Requirement | Gap Reason |
|-------------|-----------|
| FR-617 (stage budget exhaustion) | Time-based behavior; non-deterministic in unit tests; requires time-mocking infrastructure not currently specified |
| FR-617 (`budget_exhausted_stage` field) | Field presence depends on budget implementation details not fully captured in EG §3.5 |
| FR-109 (no separate retrieval model key) | "Key should not exist" property; verified by code inspection, not by assertion test |
| NFR-901 (latency < 2000ms P95) | Performance benchmark; requires warm GPU hardware and a populated Weaviate collection |
| NFR-903 (VRAM ≤ 5.5 GB) | Hardware integration test; requires GPU with memory profiling |
| NFR-909 (observability spans) | Requires live or injectable tracer; not covered in unit or mock-based integration tests |
| NFR-911 (log content) | Log format and level verification is informational; not safety-critical; integration test only |
| FR-701 OpenAPI schema presence | Requires running FastAPI application; not a unit test concern |
| FR-403 URL expiry functional verification | Actual URL expiry requires live MinIO and waiting for expiry duration |
