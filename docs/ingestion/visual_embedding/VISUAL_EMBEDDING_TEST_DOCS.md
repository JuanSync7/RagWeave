# Visual Embedding Pipeline — Test Docs

> **For write-module-tests agents:** This document is your source of truth.
> Read ONLY your assigned module section. Do not read source files, implementation code,
> or other modules' test specs.

**Engineering guide:** `docs/ingestion/visual_embedding/VISUAL_EMBEDDING_ENGINEERING_GUIDE.md`
**Phase 0 contracts:** `docs/ingestion/visual_embedding/VISUAL_EMBEDDING_IMPLEMENTATION.md`
**Spec:** `docs/ingestion/visual_embedding/VISUAL_EMBEDDING_SPEC.md`
**Produced by:** write-test-docs

---

## Mock/Stub Interface Specifications

### Mock: ColQwen2 Model + Processor

**What it replaces:** `colpali_engine.ColQwen2` model and `ColQwen2Processor`

**Interface to mock:**
```python
def load_colqwen_model(model_name: str) -> tuple[Any, Any]:
    """Returns (mock_model, mock_processor) tuple."""
    ...

def embed_page_images(
    model: Any, processor: Any,
    images: list[Any], batch_size: int,
    page_numbers: list[int] | None = None
) -> list[ColQwen2PageEmbedding]:
    """Returns list of embeddings, one per page."""
    ...

def unload_colqwen_model(model: Any) -> None:
    """Releases GPU memory."""
    ...

def ensure_colqwen_ready() -> None:
    """Raises ColQwen2LoadError if colpali-engine or bitsandbytes missing."""
    ...
```

**Happy path return:**
```python
# load_colqwen_model
(MagicMock(), MagicMock())

# embed_page_images — one per input image
ColQwen2PageEmbedding(
    page_number=N,
    mean_vector=[0.1] * 128,
    patch_vectors=[[0.05] * 128] * 800,
    patch_count=800
)
```

**Error path return:**
```python
# ensure_colqwen_ready
raise ColQwen2LoadError('colpali-engine not installed — pip install "rag[visual]"')

# load_colqwen_model
raise ColQwen2LoadError("Failed to load model: vidore/colqwen2-v1.0")
```

**Used by modules:** `src/ingest/embedding/nodes/visual_embedding.py`

---

### Mock: MinIO Client

**What it replaces:** MinIO Python SDK client (`minio.Minio`)

**Interface to mock:**
```python
def put_object(bucket: str, key: str, data: BinaryIO, length: int, content_type: str = "application/octet-stream") -> None:
    ...

def list_objects(bucket: str, prefix: str = "", recursive: bool = False) -> Iterable[Any]:
    """Each item has .object_name attribute."""
    ...

def remove_object(bucket: str, object_name: str) -> None:
    ...
```

**Happy path return:**
```python
# put_object
None  # success

# list_objects
iter([MagicMock(object_name="pages/uuid/0001.jpg"), ...])

# remove_object
None  # success
```

**Error path return:**
```python
# put_object
raise Exception("connection refused")

# list_objects
raise Exception("listing failed")

# remove_object
raise Exception("removal failed")
```

**Used by modules:** `src/ingest/embedding/nodes/visual_embedding.py`, `src/db/minio/store.py`

---

### Mock: Weaviate v4 Client

**What it replaces:** Weaviate Python v4 client

**Interface to mock:**
```python
# Collection management
client.collections.exists(name: str) -> bool
client.collections.create(name: str, **kwargs) -> None
client.collections.get(name: str) -> CollectionHandle

# Batch operations
col.batch.dynamic()  # context manager
col.batch.failed_objects  # list of failed objects

# Data operations
col.data.delete_many(where: Filter) -> DeleteManyResult
# result.matches: int | None
```

**Happy path return:**
```python
# exists
False  # first call (create), True on subsequent

# batch.failed_objects
[]  # no failures

# delete_many result
MagicMock(matches=0)  # no prior objects
```

**Error path return:**
```python
# collections.get
raise WeaviateConnectionError("Cannot connect to Weaviate")

# batch with failures
col.batch.failed_objects = [MagicMock(), MagicMock()]

# delete_many with missing attribute
MagicMock(spec=[])  # no matches attribute → getattr fallback returns 0
```

**Used by modules:** `src/ingest/embedding/nodes/visual_embedding.py`, `src/vector_db/weaviate/visual_store.py`

---

### Mock: PIL Image

**What it replaces:** Real `PIL.Image.Image` objects rendered from PDF pages

**Interface to mock:**
```python
image.size          # (width: int, height: int)
image.mode          # str, e.g. "RGB", "RGBA"
image.convert(mode: str) -> Image
image.resize(size: tuple[int, int], resample: int) -> Image
image.save(buffer: BinaryIO, format: str, quality: int) -> None
```

**Happy path return:**
```python
# A4 at 100 DPI
MagicMock(size=(842, 1190), mode="RGB")
```

**Error path return:**
```python
# convert raises
image.convert.side_effect = Exception("conversion error")

# save raises
image.save.side_effect = Exception("JPEG encoding failed")
```

**Used by modules:** `src/ingest/embedding/nodes/visual_embedding.py`, `src/db/minio/store.py`, `src/ingest/support/docling.py`

---

### Mock: Docling DocumentConverter

**What it replaces:** `docling.DocumentConverter` and its `ConversionResult`

**Interface to mock:**
```python
converter.convert(path: str | Path) -> ConversionResult
conv_result.pages       # iterable of page objects with .image.pil_image
conv_result.document.pages  # fallback access path (Strategy 2)
```

**Happy path return:**
```python
# conv_result.pages — 10 page objects
[MagicMock(image=MagicMock(pil_image=mock_pil_image)) for _ in range(10)]
```

**Error path return:**
```python
# Both strategies empty
conv_result.pages = []
conv_result.document.pages = {}

# Individual page missing image
MagicMock(image=None)  # causes AttributeError on .pil_image access
```

**Used by modules:** `src/ingest/support/docling.py`

---

## Per-Module Test Specifications

### `src/ingest/support/colqwen.py` — ColQwen2 Model Adapter

**Module purpose:** A lifecycle-complete adapter for the ColQwen2 vision-language model that accepts PIL-compatible page images, runs batch inference under 4-bit quantization, and returns structured per-page embedding records with 128-dim mean-pooled vectors and raw patch vectors.

**In scope:**
- Guarded import of `colpali_engine` and `bitsandbytes` with user-friendly error messaging (`ensure_colqwen_ready`)
- Loading ColQwen2 from HuggingFace with 4-bit quantization config and `device_map="auto"` (`load_colqwen_model`)
- Batched image inference, patch tensor extraction, mean-pooling, and construction of `ColQwen2PageEmbedding` records (`embed_page_images`)
- Progress logging at ~10% intervals for large page counts
- Per-batch and per-page error handling with WARNING logs and graceful skipping
- GPU memory release via `del model`, `torch.cuda.empty_cache()`, and `gc.collect()` (`unload_colqwen_model`)
- 1-indexed page numbering (default sequential if `page_numbers` is None)

**Out of scope:**
- Decisions about when to call the adapter (belongs to the visual embedding node/caller)
- Storing embeddings in any database or vector store
- Image preprocessing or resizing (delegated to `processor.process_images`)
- Retry logic on load failures (callers must abort the visual track on `ColQwen2LoadError`)
- Reporting `visual_stored_count` or modifying pipeline state (belongs to the calling node)
- Direct exposure of colpali-engine internals to the rest of the pipeline (NFR-910)

---

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Model loads with 4-bit quantization (FR-301) | Valid HuggingFace model name (e.g. `"vidore/colqwen2-v1.0"`), `colpali_engine` and `bitsandbytes` installed | `(model, processor)` tuple returned; `model.eval()` called; model loaded with `BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)` and `device_map="auto"` |
| Batch sizing produces correct call count (FR-302) | 20 PIL images, `batch_size=4` | Exactly 5 inference calls made (4 images × 5 batches = 20 pages); each page produces a `ColQwen2PageEmbedding` |
| Each page embedding has correct patch vector range (FR-302) | Single page image with realistic content | `patch_count` in range [500, 1200]; `len(patch_vectors) == patch_count`; each patch vector has `len == 128` |
| Mean vector is correct arithmetic mean (FR-303) | Synthetic tensor: page with 800 patch vectors each of dim 128, values known | `mean_vector` is 128-dim list[float]; each element equals arithmetic mean of that dimension across 800 patches; dtype float32 |
| Patch vectors are JSON-serializable (FR-304) | Page producing 1000 patch vectors of dim 128 | `json.dumps(embedding.patch_vectors)` succeeds without error; serialized output is list-of-lists-of-float |
| Patch vector serialized size within spec (FR-304) | 1000 patches × 128 dims | Serialized JSON size between 500KB and 1MB |
| Page numbers default to 1-indexed sequential (FR-302) | 5 images, `page_numbers=None` | Returned embeddings have `page_number` values `[1, 2, 3, 4, 5]` in order |
| Explicit page numbers are respected | 3 images, `page_numbers=[10, 20, 30]` | Returned embeddings have `page_number` values `[10, 20, 30]` |
| Progress logging for large document (FR-306) | 100 images | At least ~9–10 WARNING/INFO log entries at roughly 10-page intervals emitted during inference |
| No intermediate progress logs for small document (FR-306) | 5 images | Zero intermediate progress log entries emitted (only final completion, if any) |
| `ensure_colqwen_ready` succeeds when dependencies present | `colpali_engine` and `bitsandbytes` importable | Returns without raising; no exception |
| GPU memory released after unload (FR-305) | Loaded model, post-inference | After `unload_colqwen_model(model)`, `torch.cuda.memory_allocated()` returns to within 200MB of pre-load level; no reference to model object remains |

---

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `ColQwen2LoadError` on missing `colpali_engine` (FR-806) | `colpali_engine` not installed, `ensure_colqwen_ready()` called | Raises `ColQwen2LoadError`; error message contains the string `"colpali-engine"` and the string `'pip install "rag[visual]"'`; no raw `ImportError` traceback propagated |
| `ColQwen2LoadError` on missing `bitsandbytes` (FR-806) | `bitsandbytes` not installed, `ensure_colqwen_ready()` called | Raises `ColQwen2LoadError`; message contains install command; no `ImportError` propagated |
| `ColQwen2LoadError` on invalid model name (FR-802) | `load_colqwen_model("nonexistent/model-xyz")` called with HuggingFace returning an error | Raises `ColQwen2LoadError`; original exception is wrapped (not swallowed); error is a subclass of `VisualEmbeddingError` |
| `ColQwen2LoadError` is subclass of `VisualEmbeddingError` | Catch with `except VisualEmbeddingError` | `isinstance(ColQwen2LoadError(...), VisualEmbeddingError)` is True; stable catch target works |
| Per-batch preprocessing failure (FR-307) | One batch of images causes `processor.process_images` to raise an exception | Failed batch is skipped; `logger.warning` emitted; remaining batches processed normally; no exception raised from `embed_page_images` |
| Per-page tensor extraction failure (FR-307) | One page within a batch causes tensor extraction to raise | That single page skipped; `logger.warning` emitted; other pages in the same batch still returned; no exception raised |
| Partial page embeddings returned on mid-document error (FR-307) | 10-page document, page 5 causes extraction error | Embeddings returned for pages 1–4 and 6–10 (9 total); warning logged for page 5; `embed_page_images` returns list of length 9 without raising |
| `embed_page_images` returns fewer entries than input images | Batch preprocessing failure drops 4 images in one batch | Returned list has fewer entries than `len(images)`; caller detects gap by comparing `page_number` fields |

---

#### Boundary conditions

- **Batch boundary at exactly `batch_size` multiple (FR-302):** 20 images with `batch_size=4` must produce exactly 5 calls, not 6 (no empty trailing batch).
- **Batch boundary at non-multiple:** 21 images with `batch_size=4` must produce 6 calls (5 full + 1 with 1 image); final batch of 1 is processed correctly.
- **Single image input:** `embed_page_images(model, processor, [one_image])` returns a list with exactly 1 entry; no logging for small batch.
- **Empty image list:** `embed_page_images(model, processor, [])` returns an empty list without error.
- **Minimum patch count boundary (FR-302):** `patch_count` must be ≥ 1 for any successfully processed page (0-patch result would be degenerate — mean-pooling over empty tensor is undefined).
- **Patch vector dimension invariant (FR-303):** Every `mean_vector` must have exactly 128 elements regardless of `patch_count`; tested against both minimum and maximum patch counts.
- **`page_numbers` length mismatch:** If `len(page_numbers) != len(images)`, behavior should be documented — test should assert that an appropriate error is raised or that `page_numbers[:len(images)]` is used (based on actual implementation).
- **`last_hidden_state` attribute present vs. absent:** Tensor extraction checks `last_hidden_state` first and falls back to raw tensor; both paths must produce a valid 128-dim mean vector.
- **Progress log threshold (FR-306):** Exactly 10 images — boundary case; test whether "> 10" is exclusive (10 images → no logs) or inclusive.
- **NFR-901 peak memory:** 4-page batch at 1024px max dimension must not exceed 4GB peak GPU memory (`torch.cuda.max_memory_allocated()`).

---

#### Integration points

- **Called by:** Visual embedding node (pipeline node that drives the four-phase lifecycle). The node calls `ensure_colqwen_ready()`, then `load_colqwen_model()`, then `embed_page_images()`, then `unload_colqwen_model()`. The node owns state updates (`visual_stored_count`, `state["errors"]`).
- **Calls into:** `colpali_engine` (processor and model classes), `bitsandbytes` (`BitsAndBytesConfig`), `torch` (inference mode, device movement, `cuda.empty_cache`), `gc` (`gc.collect`), HuggingFace Hub (model download on first load).
- **Data contract output:** Returns `list[ColQwen2PageEmbedding]` — consumed by the visual embedding node for storage. The node, not this module, decides what to do with gaps or empty results.
- **NFR-910 isolation:** Pipeline nodes must import only through this adapter's interface — no direct `from colpali_engine import ...` in calling nodes.

---

#### Known test gaps

- **Real GPU hardware required for NFR-901:** Peak memory test (`≤ 4GB for 4-page batch at 1024px`) requires a physical CUDA device. This test cannot run in CPU-only CI environments and should be gated behind a `pytest.mark.gpu` marker or a separate hardware test suite.
- **Real GPU hardware required for FR-305:** `torch.cuda.memory_allocated()` delta test requires a CUDA device. Mock-based tests can verify `del model` and `gc.collect()` are called but cannot confirm actual memory reclamation.
- **HuggingFace model download:** `load_colqwen_model` tests that exercise the real load path require network access and a downloaded model. CI tests must use mocks for `colpali_engine` classes to avoid network dependency.
- **`patch_count` range is non-deterministic (FR-302):** The 500–1200 patch count range depends on the actual model's output for real images. With mocked tensors the range is artificial; with real images it requires representative test fixtures.
- **Serialized JSON size (FR-304):** The 500KB–1MB range for 1000 patches × 128 dims is a rough heuristic. The actual size depends on float precision and JSON encoder. Test should use a deterministic synthetic tensor to get a stable size measurement.
- **Progress log interval exactness (FR-306):** "~every 10 pages" for a 100-page document — the implementation may log at 10%, 20%, ... (every 10 pages exactly) or at floating-point intervals. Tests should allow a ±1 page tolerance on log timing.
- **`page_numbers` length mismatch behavior:** The engineering guide does not specify what happens if `len(page_numbers) != len(images)`. This is an unspecified boundary and cannot be tested without knowing the implementation's contract. Flagged as a spec gap.
- **`last_hidden_state` fallback path:** Testing the fallback from `last_hidden_state` to raw tensor requires mocking a model output object that lacks the attribute. The test is valid but depends on mock fidelity to the colpali-engine output structure.

---

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### `src/vector_db/weaviate/visual_store.py` + `backend.py` — Weaviate Visual Collection Store

**Module purpose:** Manages the `RAGVisualPages` Weaviate collection with idempotent creation, batch insert with named-vector support, and filter-based deletion by source key, exposed through abstract-base-class additions and WeaviateBackend delegation.

**In scope:**
- `ensure_visual_collection`: idempotent collection creation with exact schema (11 scalar properties + `mean_vector` named vector, 128-dim HNSW cosine, `patch_vectors` skip_vectorization flag)
- `add_visual_documents`: batch insert with mean_vector split, failed-object counting, empty-input short-circuit, and return of inserted count
- `delete_visual_by_source_key`: filter-based deletion via `source_key` equality, returning match count with safe fallback to 0
- VectorBackend ABC: three new abstract method signatures (ensure_visual_collection, add_visual_documents, delete_visual_by_source_key)
- WeaviateBackend delegation: `collection or "RAGVisualPages"` default resolution and forwarding to store functions
- Exception propagation: Weaviate client exceptions passed through without wrapping

**Out of scope:**
- ANN query / similarity search logic (tested under retrieval pipeline)
- MaxSim reranking against `patch_vectors` (app-side, not a store responsibility)
- MinIO storage operations (separate backend)
- Schema migration or diff detection when collection exists with wrong schema
- Text collection (`RAGTextPages`) and its interactions with visual collection
- Authentication or connection management for the Weaviate client

---

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Create collection when absent (FR-502, FR-504) | `client.collections.exists` returns False; no existing collection | `client.collections.create` called once with `"mean_vector"` NamedVector, 128-dim, cosine HNSW; all 11 scalar properties present; `patch_vectors` has `skip_vectorization=True`; function returns None without error |
| Idempotent: collection already exists (FR-502) | `client.collections.exists` returns True | `client.collections.create` is NOT called; function returns immediately without error |
| Batch insert 50 documents, zero failures (FR-507) | List of 50 dicts each containing `mean_vector` (128-float list) + all required properties; `col.batch.failed_objects` is empty | Returns 50; each `batch.add_object` call receives `properties` dict without `mean_vector` key and `vector={"mean_vector": <128-float list>}` |
| Batch insert with partial failures (FR-507 edge) | List of 10 dicts; `col.batch.failed_objects` contains 2 entries | Returns 8 (10 - 2) |
| Empty document list (FR-507 boundary) | `documents = []` | Returns 0 immediately; `client.collections.get` is NOT called |
| Delete matching objects (FR-506) | `source_key="doc_abc"`; result has `matches=3` | Returns 3; filter applied as `Filter.by_property("source_key").equal("doc_abc")` |
| Delete with zero matches (FR-506) | `source_key="nonexistent"`; result has `matches=0` | Returns 0; no error raised |
| WeaviateBackend delegates with explicit collection | `backend.ensure_visual_collection(client, collection="CustomCollection")` | Forwards to store function with `collection="CustomCollection"` |
| WeaviateBackend defaults collection name | `backend.add_visual_documents(client, documents)` with `collection=None` | Resolves to `"RAGVisualPages"` before forwarding; store function called with `collection="RAGVisualPages"` |
| All 11 properties present on inserted object (FR-503) | Single doc dict containing document_id, page_number, source_key, source_uri, source_name, tenant_id, total_pages, page_width_px, page_height_px, minio_key, patch_vectors, mean_vector | `batch.add_object` properties dict contains all 10 scalar keys (mean_vector excluded); none missing |
| `patch_vectors` is stored as JSON-serializable TEXT (FR-505) | `patch_vectors` is a list of 8 lists each with 128 floats | Property passed through as-is to Weaviate (no coercion); can be deserialized back to `list[list[float]]` |
| ABC contract: all three methods abstract | Subclass omitting any one of the three new methods | Instantiation raises `TypeError` at class definition time |
| NFR-909: existing VectorBackend methods unchanged | Inspect VectorBackend method signatures before and after patch | All pre-existing method signatures identical; no existing method removed or renamed |

---

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| Weaviate connection error on `ensure_visual_collection` | `client.collections.exists` raises `WeaviateConnectionError` | Exception propagates to caller unwrapped; no suppression or re-wrapping |
| Weaviate connection error on `add_visual_documents` | `client.collections.get` raises `WeaviateConnectionError` | Exception propagates to caller unwrapped |
| Weaviate query error on `delete_visual_by_source_key` | `col.data.delete_many` raises `WeaviateQueryError` | Exception propagates to caller unwrapped |
| All documents fail batch insert | `col.batch.failed_objects` has same length as input (all fail) | Returns 0 (not negative); no exception raised |
| `DeleteManyResult` missing `matches` attribute | `delete_visual_by_source_key` result object has no `matches` attribute | Returns 0 via `getattr(result, "matches", 0) or 0` fallback; no AttributeError raised |
| `DeleteManyResult.matches` is None or 0 | result.matches is None | Returns 0; `or 0` guard handles falsy value |
| Weaviate error on `add_visual_documents` during batch context | Exception raised inside `col.batch.dynamic()` context manager body | Exception propagates to caller; no count returned |
| WeaviateBackend delegation error: connection error | `backend.delete_visual_by_source_key(client, "key")` and client raises | Exception propagates through delegation unchanged; no extra wrapping at backend layer |

---

#### Boundary conditions

- **Empty documents list** (`add_visual_documents`): must return 0 without calling `client.collections.get` — guard must be before any client interaction (FR-507).
- **Exactly 1 document**: batch path exercised for single-element list; not short-circuited.
- **`mean_vector` exactly 128 dimensions**: collection schema specifies 128 dims; inserting a 127- or 129-dim vector is a caller error, but the store must not silently truncate or pad — it passes through as-is and lets Weaviate reject it (not a store concern to validate).
- **`patch_vectors` inner list count**: each inner list must have exactly 128 elements per FR-505; store passes value through without validation — boundary is a caller/ingestion concern, but downstream deserialization test should verify round-trip integrity.
- **`collection` parameter is empty string `""`**: WeaviateBackend must treat `""` as falsy and substitute `"RAGVisualPages"` (since `collection or default` resolves `""` to default).
- **`collection` parameter is explicitly `"RAGVisualPages"`**: behaves identically to `None` after default resolution.
- **`failed_objects` attribute absent on batch result**: fallback to 0 must be safe (guard via `getattr` or equivalent).
- **`delete_visual_by_source_key` with `source_key=""` (empty string)**: filter applied with empty string; store does not guard against this — behavior is Weaviate-defined, but function must not raise before the Weaviate call.
- **NFR-909 boundary**: adding three new abstract methods must not change argument count, name, or default values of any pre-existing VectorBackend abstract method.

---

#### Integration points

- **Callers of `ensure_visual_collection`**: visual ingestion pipeline (embedding workflow) calls this before inserting visual page objects; passes in live Weaviate client handle.
- **Callers of `add_visual_documents`**: embedding pipeline's visual-store node passes a list of dicts built from VLM enrichment output; expected key set is `{mean_vector, document_id, source_key, source_uri, source_name, tenant_id, page_number, total_pages, page_width_px, page_height_px, minio_key, patch_vectors}`.
- **Callers of `delete_visual_by_source_key`**: clean-store / document deletion flow calls this when a document is removed; source_key is the canonical document identifier shared with MinIO.
- **WeaviateBackend**: implements the three new abstract methods; callers interact with `VectorBackend` interface only — store functions are internal to the weaviate subpackage.
- **Return values consumed by callers**:
  - `ensure_visual_collection` → None (fire-and-forget)
  - `add_visual_documents` → int inserted count (used for telemetry/logging)
  - `delete_visual_by_source_key` → int match count (used for telemetry/logging; 0 is ambiguous but acceptable per error-behavior spec)

---

#### Known test gaps

- **Schema validation on existing collection** (FR-502 / FR-504): the function returns without error if the collection exists with wrong dimensions or missing properties. There is no test that can verify incorrect-schema detection because the module intentionally does not detect it. Tests can only assert the function does not raise — they cannot assert correctness of an existing schema.
- **`patch_vectors` round-trip fidelity** (FR-505): the store passes `patch_vectors` through as-is without serialization. A full round-trip test (insert → retrieve → deserialize) requires a live or realistic Weaviate mock that stores and returns properties. Unit tests with simple mocks cannot cover this path end-to-end.
- **Weaviate batch partial-failure internals**: `col.batch.failed_objects` behavior depends on the Weaviate Python client's batch implementation. Tests must mock this attribute carefully; incorrect mock behavior could produce false positives.
- **True isolation of visual vs. text collection** (FR-501): confirming that a visual insert does not affect the text collection requires either a full integration test or a mock that asserts no cross-collection calls occur. Unit-level mocks can assert the correct collection name is used, but cannot confirm actual Weaviate isolation.
- **`DeleteManyResult` ambiguity**: the spec documents that 0 returned cannot distinguish "nothing deleted" from "count unavailable." There is no test that can distinguish these two cases at the store level — acceptance tests for FR-506 must rely on a subsequent query confirming object absence rather than on the return value alone.

---

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### `src/db/minio/store.py` — MinIO Page Image Storage

**Module purpose:** Stores and deletes page image files in MinIO under the `pages/` key namespace, reusing the shared MinIO client and bucket conventions.

**In scope:**
- Key generation: `pages/{document_id}/{page_number:04d}.jpg` (1-indexed, zero-padded to 4 digits)
- Per-page JPEG serialization via `io.BytesIO` buffer (format=JPEG, configurable quality)
- `put_object` calls with correct `content_type="image/jpeg"` and byte-accurate `length`
- Per-page failure isolation: log WARNING and continue; no exception propagated to caller
- Listing objects under `pages/{document_id}/` prefix for deletion
- Per-object `remove_object` calls with early exit on first removal failure
- Listing failure path: log WARNING and return 0 immediately
- Return value semantics: `store_page_images` returns list of successfully stored keys; `delete_page_images` returns integer count of removed objects

**Out of scope:**
- Ordering relative to ColQwen2 model loading (caller/orchestrator responsibility — FR-403)
- Bucket creation or selection (bucket is a caller-provided or module-default constant)
- Deciding whether a partial store result is a fatal error (caller responsibility)
- Deciding whether a partial delete count is a fatal error (caller responsibility)
- Image acquisition or rendering (caller passes pre-rendered PIL images)

---

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Store 10 pages, all succeed | `document_id="abc-123"`, 10 PIL images, default `quality=85` | Returns list of 10 keys: `["pages/abc-123/0001.jpg", ..., "pages/abc-123/0010.jpg"]`; `put_object` called 10 times with correct keys |
| Key format: page numbering is 1-indexed and zero-padded | `document_id="doc-1"`, 1 PIL image | First key is `"pages/doc-1/0001.jpg"` (not `0000.jpg`) |
| Key format: page 10 is zero-padded to 4 digits | `document_id="doc-1"`, 10 images | Last key is `"pages/doc-1/0010.jpg"` |
| Key format: page 1000 fits in 4-digit field | `document_id="doc-x"`, image for page 1000 | Key is `"pages/doc-x/1000.jpg"` |
| Store uses custom quality | `quality=50`, 1 image | `image.save` called with `quality=50` |
| Store uses default quality=85 | No `quality` arg, 1 image | `image.save` called with `quality=85` |
| Store uses custom bucket | `bucket="custom-bucket"`, 1 image | `put_object` called with `bucket="custom-bucket"` |
| `put_object` receives correct content_type | Any valid call | `content_type="image/jpeg"` passed to every `put_object` |
| `put_object` receives byte-accurate length | Any valid call | `length` equals `buffer.tell()` after `image.save` (i.e., after seek-to-end, before rewind) |
| Delete all 10 pages for a document | `document_id="abc-123"`, listing returns 10 objects | Returns `10`; `remove_object` called 10 times |
| Delete with custom bucket | `bucket="custom-bucket"` | `list_objects` and `remove_object` called with `"custom-bucket"` |
| Delete uses correct prefix | `document_id="abc-123"` | `list_objects` called with `prefix="pages/abc-123/"` and `recursive=True` |
| Delete zero pages (document had no pages) | listing returns 0 objects | Returns `0`; no `remove_object` calls |
| Store empty page list | `pages=[]` | Returns `[]`; `put_object` not called |

---

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| Single page store failure | `put_object` raises exception for one page | That page's key is NOT in `stored_keys`; WARNING logged with page_number, document_id, exception; remaining pages continue; no exception raised to caller |
| All pages fail to store | `put_object` raises exception for every page | Returns `[]`; WARNING logged per page; no exception raised |
| First page fails, rest succeed | `put_object` raises on page 1 only | `stored_keys` has N-1 entries; page 1 key absent; function returns normally |
| Listing fails during delete | `list_objects` raises exception | WARNING logged; returns `0` immediately; no `remove_object` calls |
| First object removal fails | `remove_object` raises on first object | WARNING logged; returns `0` (early exit with current `deleted` count before increment) |
| Mid-sequence object removal fails | `remove_object` raises on object k of N | Returns `k-1` (count of successfully removed objects before failure); early exit |
| `image.save` raises for a page | `image.save` raises exception | That page skipped; WARNING logged; remaining pages processed; no exception raised |

---

#### Boundary conditions

- **FR-401 key pattern**: Page 1 produces `0001.jpg`; page 10 produces `0010.jpg`; page 9999 produces `9999.jpg`. Numbering is strictly 1-indexed (no `0000.jpg` key ever produced).
- **FR-402 JPEG validity**: Buffer passed to `put_object` must contain valid JPEG bytes (verifiable by opening with PIL after retrieval). Quality parameter must be forwarded accurately to `image.save`.
- **FR-404 namespace isolation**: All keys are under `pages/` prefix; no key begins with `documents/`. Verifiable by asserting the prefix of every key in `stored_keys`.
- **FR-405 re-ingestion idempotence**: After deleting old page images and storing new ones, only 8 keys exist for a document previously ingested with 10 pages. This boundary condition is owned by the caller (delete then store), but `delete_page_images` must return `10` for a complete prior-run cleanup, and `store_page_images` must return exactly 8 new keys.
- **Partial store detection**: `len(stored_keys) < len(pages)` is the only signal for partial failure. The module must never silently add extra keys or skip keys without logging.
- **Buffer rewind**: `buffer.seek(0)` must be called after `length = buffer.tell()` so MinIO client reads from the start. If not rewound, `put_object` receives 0 bytes — a regression-prone detail to cover.
- **Single-page document**: `pages` list with one element produces exactly one key (`0001.jpg`).

---

#### Integration points

- **Caller: visual embedding node (ingest pipeline)**
  - Passes: shared MinIO `client` instance, `document_id` string, list of `(page_number: int, image: PIL.Image.Image)` tuples, optional `quality` int, optional `bucket` string
  - Receives: `list[str]` of stored MinIO keys (used to populate page image metadata for ColQwen2)
  - Caller checks `len(stored_keys) == len(pages)` to detect partial upload before proceeding

- **Caller: cleanup/re-ingestion path**
  - Passes: shared MinIO `client` instance, `document_id` string, optional `bucket` string
  - Receives: `int` count of deleted objects
  - Caller treats `count < expected` as a soft error (logs or retries at its discretion)

- **MinIO client interface (mocked in tests)**
  - `client.put_object(bucket, key, data, length, content_type=...)`
  - `client.list_objects(bucket, prefix=..., recursive=True)` → iterable of objects with `.object_name`
  - `client.remove_object(bucket, object_name)`

---

#### Known test gaps

- **Real JPEG byte validation (FR-402 full coverage)**: Unit tests mock `image.save` and `put_object`, so they cannot verify that bytes captured in the buffer constitute a valid JPEG. An integration test with a real PIL image and a real or in-memory MinIO is needed to fully satisfy FR-402. Marked as integration-only.
- **File size range check (FR-402 30KB–300KB)**: Size bounds for "typical document pages at quality 85" depend on image content. Cannot be covered by unit tests with synthetic images. Requires a fixture set of representative document page images in an integration suite.
- **FR-403 ordering (out of scope for this module)**: Whether `store_page_images` completes before ColQwen2 model loading is an orchestration invariant owned by the calling node, not testable here.
- **Concurrent store calls**: Behavior when two calls with the same `document_id` run in parallel is not specified. No concurrency tests planned at unit level.
- **Object name attribute contract**: Tests assume `obj.object_name` is the correct attribute on objects returned by `list_objects`. If the MinIO SDK changes this attribute, tests must be updated. Covered by pinning the SDK version in `pyproject.toml`.

---

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### `src/ingest/embedding/nodes/visual_embedding.py` — Visual Embedding Node

**Module purpose:** Orchestrates the visual (page-image) embedding track — image extraction, resize, MinIO storage, ColQwen2 inference, and Weaviate insertion — as a single LangGraph node that owns only its own state fields.

**In scope:**
- Short-circuit behavior when `enable_visual_embedding=False` (FR-101/FR-603)
- Short-circuit behavior when `docling_document` is `None` (FR-603)
- Short-circuit behavior when page extraction yields zero images (FR-203/FR-603)
- Image extraction from `state["page_images"]` primary path and `DoclingDocument.pages` fallback
- Per-page resize logic (max-dimension scaling with LANCZOS, preserving originals in output tuple)
- Pre-cleanup calls (`delete_page_images`, `delete_visual_by_source_key`) and their failure tolerance
- MinIO storage call and page-number-to-key mapping construction
- ColQwen2 model lifecycle: `ensure_colqwen_ready`, `load_colqwen_model`, `embed_page_images`, `unload_colqwen_model` (via `finally`)
- Weaviate collection creation (`ensure_visual_collection`) and batch insertion (`add_visual_documents`)
- Processing log composition: five canonical entries (FR-701–FR-705)
- Partial state update: only `visual_stored_count`, `page_images=None`, `processing_log`, and `errors` written
- State isolation: text-track fields (`stored_count`, `chunks`, `enriched_chunks`, `metadata_summary`, `metadata_keywords`) are never written
- All error levels: fatal ColQwen2 load failure, non-fatal inference errors, partial Weaviate batch failure, catch-all top-level exception
- `page_images` set to `None` in returned state after processing (FR-606)

**Out of scope:**
- Internal ColQwen2 model loading, batching, and inference logic (delegated to `colqwen.py`)
- MinIO upload mechanics, key naming, and bucket management (delegated to `minio/store.py`)
- Weaviate schema creation details and low-level insertion batching (delegated to `visual_store.py`)
- PIL image I/O (delegated to PIL/Pillow)
- Docling document parsing (delegated to `support/docling.py`)

---

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Standard 10-page document | `enable_visual_embedding=True`, `docling_document` set, `page_images` list of 10 valid PIL images, all ColQwen2 and Weaviate calls succeed | `visual_stored_count=10`, `page_images=None`, processing log contains exactly `pages_extracted:10`, `pages_stored_minio:10`, `pages_embedded:10`, `pages_indexed:10`, `elapsed_s:<float>` |
| Resize applied — image exceeds max_dimension | One image with `max(w,h) > config.max_dimension` | Resize called with LANCZOS; original dimensions preserved in Weaviate property dict; resized image passed to ColQwen2 |
| Resize skipped — image within max_dimension | One image with `max(w,h) <= config.max_dimension` | Resize not applied; image passed as-is to ColQwen2 |
| Fallback extraction path used | `state["page_images"]` is absent or empty; `docling_document.pages` dict populated with `PageItem` objects each having `.image.pil_image` | Images extracted from `DoclingDocument.pages`; 1-based page numbers assigned correctly |
| Pre-cleanup succeeds | `delete_page_images` and `delete_visual_by_source_key` both return without exception | Both calls made before MinIO storage; execution continues normally |

---

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `enable_visual_embedding=False` (FR-101/FR-603, NFR-903) | Config flag `False` | Returns immediately: `visual_stored_count=0`, `page_images=None`, log entry `"visual_embedding:skipped:disabled"`, no ColQwen2 loaded, no MinIO call, no Weaviate call, wall-clock < 10 ms |
| `docling_document=None` (FR-603) | `state["docling_document"]` is `None` | Returns: `visual_stored_count=0`, `page_images=None`, log entry `"visual_embedding:skipped:no_docling_document"`, no downstream I/O |
| Zero pages extracted (FR-203/FR-603) | `_extract_page_images` returns empty list | Returns: `visual_stored_count=0`, log entry `"visual_embedding:skipped:no_pages"`, no model loaded, no MinIO, no Weaviate |
| `ensure_colqwen_ready` raises `ColQwen2LoadError` (FR-802) | Monkeypatched to raise | Returns immediately: `visual_stored_count=0`, error string in `state["errors"]`, text-track fields (`stored_count`, `chunks`, `enriched_chunks`) unchanged, no `unload_colqwen_model` call (model never loaded) |
| `load_colqwen_model` raises `ColQwen2LoadError` (FR-802) | Monkeypatched to raise | Same as above; `unload_colqwen_model` not called |
| colpali-engine not installed (FR-806) | `ensure_colqwen_ready` raises `ColQwen2LoadError` with "colpali-engine" in message | Error log contains `"colpali-engine"` text and install command; `visual_stored_count=0` |
| Per-page inference exception — pages 3 and 7 of 10 (FR-801) | `embed_page_images` raises `VisualEmbeddingError` for pages 3 and 7 | Embeddings produced for remaining 8 pages; warning logs emitted for pages 3 and 7; `visual_stored_count=8`; `finally` block still calls `unload_colqwen_model`; pipeline continues |
| MinIO failure for page 5 of 10 (FR-804) | `store_page_images` raises/fails for page 5 | 9 pages in MinIO, 9 visual objects in Weaviate, warning log for page 5, `visual_stored_count=9` |
| Weaviate batch insertion failure (FR-805) | `add_visual_documents` raises exception | Error in `state["errors"]`, `visual_stored_count=0`, pipeline continues (no re-raise) |
| Pre-cleanup failure — `delete_page_images` raises | Exception inside `delete_page_images` | Warning logged, execution continues to MinIO storage step; no propagation |
| Pre-cleanup failure — `delete_visual_by_source_key` raises | Exception inside `delete_visual_by_source_key` | Warning logged, execution continues; no propagation |
| Per-page resize failure | LANCZOS resize raises for one page | Warning logged for that page; original (unresized) image used and processing continues |
| Unhandled exception inside `_run_visual_embedding` (catch-all) | Arbitrary exception not caught by inner handlers | Top-level `except Exception` catches it; full traceback logged at ERROR level; `visual_stored_count=0` returned; pipeline continues (no re-raise) |

---

#### Boundary conditions

- **Exactly 1 page:** `visual_stored_count=1`; all five processing log entries reflect count of 1; ColQwen2 lifecycle runs once.
- **Image dimensions exactly equal `max_dimension`:** Resize is NOT applied (strictly greater than triggers resize).
- **`page_images` key present but empty list:** Falls through to fallback path (`DoclingDocument.pages`) rather than returning no-pages short-circuit immediately (short-circuit only fires if `_extract_page_images` returns empty after both paths attempted).
- **`page_images` key absent from state:** Fallback path used cleanly without `KeyError`.
- **Processing log accumulation:** Entries are appended (not overwritten) to any existing `processing_log` in state; the five canonical entries always appear at the tail in order.
- **`errors` key absent from state initially:** Node initializes `errors` list before appending; no `KeyError`.
- **All pages fail resize:** All images kept at original dimensions; processing continues; log reflects `pages_extracted:N`.
- **Text-track field isolation (FR-803):** `stored_count`, `chunks`, `enriched_chunks`, `metadata_summary`, `metadata_keywords` values in state are byte-identical before and after node invocation regardless of visual node outcome.
- **`page_images=None` in returned dict (FR-606):** Even on error paths (not only success), the returned dict sets `page_images=None`.
- **`visual_stored_count` type:** Always an `int`, never `None`, regardless of code path taken.

---

#### Integration points

**Node reads from state:**
- `config.enable_visual_embedding` — bool flag, checked first
- `docling_document` — presence/absence drives second short-circuit
- `page_images` — primary image source (list of PIL images)
- `source_key` — used by pre-cleanup calls
- `processing_log` — extended (not replaced) by this node
- `errors` — extended only when new errors occur

**Node calls (all must be mockable in tests):**
- `_extract_page_images(state)` — internal helper
- `delete_page_images(source_key)` — pre-cleanup
- `delete_visual_by_source_key(source_key)` — pre-cleanup
- `store_page_images(images)` → `list[str]` — MinIO storage
- `ensure_colqwen_ready()` — raises `ColQwen2LoadError` on failure
- `load_colqwen_model(config.colqwen_model_name)` → `(model, processor)` — raises `ColQwen2LoadError`
- `embed_page_images(model, processor, images, batch_size, page_numbers)` → `list[ColQwen2PageEmbedding]`
- `unload_colqwen_model(model)` — always via `finally`
- `ensure_visual_collection()` — Weaviate collection setup
- `add_visual_documents(docs)` → `int` — returns count inserted

**Node returns (partial state dict):**
- `visual_stored_count: int` — always present
- `page_images: None` — always `None` in return
- `processing_log: list[str]` — extended list
- `errors: list[str]` — only when new errors were accumulated

**Node NEVER returns:**
- `stored_count`, `chunks`, `enriched_chunks`, `metadata_summary`, `metadata_keywords`, or any other text-track field

---

#### Known test gaps

- **GPU allocation assertion (NFR-903):** Verifying "no GPU allocation" in the disabled path requires inspecting PyTorch/CUDA state, which is environment-dependent. Tests can only assert that no ColQwen2 functions were called; actual GPU non-allocation must be verified in integration/hardware tests.
- **Exact wall-clock < 10 ms (NFR-903):** Timing assertions are flaky in CI under load. The wall-clock guard for the disabled path is best treated as a performance smoke test run in isolation rather than a unit test gate.
- **LANCZOS filter identity:** Tests verify resize is called with correct scale factor but cannot assert pixel-level LANCZOS output correctness without image fixture management — this is out of scope for unit tests.
- **`finally` + `ColQwen2LoadError` interaction:** When the error is raised before model assignment, `unload_colqwen_model` must NOT be called (no valid model handle). Tests must verify call count is zero, but distinguishing "not called because model was never assigned" vs. "not called due to logic error" requires careful mock setup.
- **Partial MinIO failure (FR-804):** The engineering guide describes `store_page_images` returning stored keys; whether per-page atomicity is enforced inside that function or inside this node is unclear from the spec alone. Tests assume the node receives a partial key list and constructs the mapping accordingly — this assumption should be validated when `visual_store.py` implementation is available.

---

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files, other modules' test specs, or the engineering guide directly.

---

### `config/settings.py` + `src/ingest/common/types.py` + `src/ingest/embedding/state.py` + `src/ingest/embedding/workflow.py` — Configuration, State, and Pipeline Wiring

**Module purpose:** These four files collectively define the visual embedding feature's configuration surface (env-var constants and their IngestionConfig fields), the validation logic for those fields, the state extensions for passing image data through the pipeline, and the LangGraph graph topology that wires the visual embedding node into the DAG.

**In scope:**
- Env-var constant parsing for all six `RAG_INGESTION_*` visual embedding variables (default values, type coercion, truthy/falsy boolean rules)
- `IngestionConfig` field defaults, the `generate_page_images` property alias, and `_check_visual_embedding_config` validation logic
- `IngestFileResult.visual_stored_count` field default
- `PIPELINE_NODE_NAMES` list membership and ordering
- `EmbeddingPipelineState` new fields (`visual_stored_count`, `page_images`) and backward-compatibility of existing fields
- `build_embedding_graph()` DAG topology: node presence, edge ordering, and short-circuit placement

**Out of scope:**
- Runtime behavior of the `visual_embedding_node` itself (model loading, image rendering, Weaviate writes)
- `impl.py` orchestration and `_check_visual_embedding_config` call site behavior beyond what the function itself returns
- Text-track correctness or other pipeline nodes' logic
- Dependency installation (colpali-engine, bitsandbytes) tested separately under NFR-906

---

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| All defaults — no env vars set | No `RAG_INGESTION_*` env vars present | `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING=False`, `RAG_INGESTION_VISUAL_TARGET_COLLECTION="RAGVisualPages"`, `RAG_INGESTION_COLQWEN_MODEL="vidore/colqwen2-v1.0"`, `RAG_INGESTION_COLQWEN_BATCH_SIZE=4`, `RAG_INGESTION_PAGE_IMAGE_QUALITY=85`, `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION=1024` |
| Boolean enable via `"true"` | `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING="true"` | Constant evaluates to `True` |
| Boolean enable via `"1"` | `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING="1"` | Constant evaluates to `True` |
| Boolean enable via `"yes"` | `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING="yes"` | Constant evaluates to `True` |
| Boolean disable (explicit false) | `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING="false"` | Constant evaluates to `False` |
| Custom collection name | `RAG_INGESTION_VISUAL_TARGET_COLLECTION="TestVisual"` | Constant is `"TestVisual"` |
| Custom model name | `RAG_INGESTION_COLQWEN_MODEL="vidore/other-model"` | Constant is `"vidore/other-model"` |
| Integer env var — batch size | `RAG_INGESTION_COLQWEN_BATCH_SIZE="8"` | Constant is integer `8` |
| Integer env var — image quality | `RAG_INGESTION_PAGE_IMAGE_QUALITY="90"` | Constant is integer `90` |
| Integer env var — max dimension | `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION="2048"` | Constant is integer `2048` |
| IngestionConfig defaults | `IngestionConfig()` constructed with no args | All six visual fields match the six settings.py constants exactly |
| `generate_page_images` when enabled | `IngestionConfig(enable_visual_embedding=True)` | `config.generate_page_images` returns `True` |
| `generate_page_images` when disabled | `IngestionConfig(enable_visual_embedding=False)` | `config.generate_page_images` returns `False` |
| `_check_visual_embedding_config` disabled fast-path | `enable_visual_embedding=False` (any other values) | Returns `([], [])` immediately, no validation performed |
| `_check_visual_embedding_config` valid config | `enable_visual_embedding=True`, `enable_docling_parser=True`, `colqwen_batch_size=16`, `page_image_quality=75`, `page_image_max_dimension=1024` | Returns `([], [])` |
| `_check_visual_embedding_config` boundary — minimum valid batch size | `colqwen_batch_size=1` | No error for batch size |
| `_check_visual_embedding_config` boundary — maximum valid batch size | `colqwen_batch_size=32` | No error for batch size |
| `_check_visual_embedding_config` boundary — minimum valid quality | `page_image_quality=1` | No error for quality |
| `_check_visual_embedding_config` boundary — maximum valid quality | `page_image_quality=100` | No error for quality |
| `_check_visual_embedding_config` boundary — minimum valid dimension | `page_image_max_dimension=256` | No error for dimension |
| `_check_visual_embedding_config` boundary — maximum valid dimension | `page_image_max_dimension=4096` | No error for dimension |
| `PIPELINE_NODE_NAMES` membership | Import `PIPELINE_NODE_NAMES` | `"visual_embedding"` is present in the list |
| `PIPELINE_NODE_NAMES` ordering | Import `PIPELINE_NODE_NAMES` | `"visual_embedding"` appears immediately after `"embedding_storage"` and immediately before `"knowledge_graph_storage"` |
| `PIPELINE_NODE_NAMES` total count | Import `PIPELINE_NODE_NAMES` | Length is exactly 15 |
| `IngestFileResult` default `visual_stored_count` | `IngestFileResult()` constructed | `visual_stored_count` field is `0` |
| `EmbeddingPipelineState` new fields accessible | State dict with both new fields set | `state["visual_stored_count"]` and `state["page_images"]` are accessible |
| `EmbeddingPipelineState` new field absent — safe default | State dict without `visual_stored_count` key | `state.get("visual_stored_count", 0)` returns `0` without KeyError |
| `EmbeddingPipelineState` `page_images` accepts None | `page_images=None` | No type error; field holds `None` |
| `EmbeddingPipelineState` `page_images` accepts list | `page_images=[mock_image_1, mock_image_2]` | Field holds the list |
| `build_embedding_graph()` returns compiled graph | Call with valid config | Returns a compiled LangGraph object without error |
| `build_embedding_graph()` node count | Inspect compiled graph | DAG contains exactly 10 nodes |
| `build_embedding_graph()` includes `visual_embedding` node | Inspect compiled graph nodes | `"visual_embedding"` is present as a node |
| `build_embedding_graph()` edge: `embedding_storage` → `visual_embedding` | Inspect graph edges | Unconditional edge from `embedding_storage` to `visual_embedding` exists |
| `build_embedding_graph()` edge: `visual_embedding` → `knowledge_graph_storage` | Graph built with `enable_knowledge_graph_storage=True` | Conditional edge routes from `visual_embedding` to `knowledge_graph_storage` |
| `build_embedding_graph()` edge: `visual_embedding` → END | Graph built with `enable_knowledge_graph_storage=False` | Conditional edge routes from `visual_embedding` to END |
| Legacy edge removed | Inspect graph edges | No direct edge from `embedding_storage` to `knowledge_graph_storage` |

---

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `ValueError` on non-integer batch size | `RAG_INGESTION_COLQWEN_BATCH_SIZE="abc"` at module import | `ValueError` raised at settings.py import time (not deferred) |
| `ValueError` on non-integer quality | `RAG_INGESTION_PAGE_IMAGE_QUALITY="abc"` at module import | `ValueError` raised at settings.py import time |
| `ValueError` on non-integer max dimension | `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION="abc"` at module import | `ValueError` raised at settings.py import time |
| `_check_visual_embedding_config` — Docling not enabled | `enable_visual_embedding=True`, `enable_docling_parser=False` | Returns non-empty `errors` list; error message names the Docling requirement |
| `_check_visual_embedding_config` — batch size below range | `enable_visual_embedding=True`, `enable_docling_parser=True`, `colqwen_batch_size=0` | Returns error naming `colqwen_batch_size` and valid range `1–32` |
| `_check_visual_embedding_config` — batch size above range | `enable_visual_embedding=True`, `enable_docling_parser=True`, `colqwen_batch_size=64` | Returns error naming `colqwen_batch_size` and valid range `1–32` |
| `_check_visual_embedding_config` — quality below range | `enable_visual_embedding=True`, `enable_docling_parser=True`, `page_image_quality=0` | Returns error naming `page_image_quality` and valid range `1–100` |
| `_check_visual_embedding_config` — quality above range | `enable_visual_embedding=True`, `enable_docling_parser=True`, `page_image_quality=101` | Returns error naming `page_image_quality` and valid range `1–100` |
| `_check_visual_embedding_config` — dimension below range | `enable_visual_embedding=True`, `enable_docling_parser=True`, `page_image_max_dimension=128` | Returns error naming `page_image_max_dimension` and valid range `256–4096` |
| `_check_visual_embedding_config` — dimension above range | `enable_visual_embedding=True`, `enable_docling_parser=True`, `page_image_max_dimension=8192` | Returns error naming `page_image_max_dimension` and valid range `256–4096` |
| `_check_visual_embedding_config` — multiple simultaneous violations | `colqwen_batch_size=0`, `page_image_quality=0`, `page_image_max_dimension=128` (all out of range, with `enable_docling_parser=True`) | `errors` list contains one entry per violation (at least 3 errors) |
| `ImportError` on missing colpali dependency | `visual_embedding_node` module fails to import due to absent colpali-engine | `workflow.py` itself raises `ImportError` on import; worker startup fails with a clear import error |
| `_check_visual_embedding_config` returns tuple | Call with any valid `IngestionConfig` | Return value is always a 2-tuple `(list, list)`, never raises |

---

#### Boundary conditions

- **Boolean env var parsing**: Only `"true"`, `"1"`, and `"yes"` (case-sensitive as specified) evaluate to `True`; any other string including `"yes_please"`, `"TRUE"`, `"YES"`, `"on"`, and empty string `""` silently evaluate to `False`. Tests should confirm the exact set of truthy strings.
- **Integer env var type**: The settings.py constants for batch size, quality, and max dimension must be Python `int` (not `str`). Tests should assert `isinstance(value, int)`.
- **Range boundaries are inclusive**: `colqwen_batch_size=1` and `colqwen_batch_size=32` are both valid; `0` and `33` are both errors. Same inclusive treatment for quality (`1–100`) and dimension (`256–4096`). Tests must probe both the last valid value and the first invalid value on each boundary.
- **`_check_visual_embedding_config` fast-path**: When `enable_visual_embedding=False`, range checks must NOT run even if range values are set to invalid integers (e.g., batch size 0). This ensures no startup cost and no spurious errors for disabled features.
- **`generate_page_images` is a property, not a field**: It must not appear as a stored key in the dataclass `__dict__`; it is a derived view of `enable_visual_embedding`.
- **`EmbeddingPipelineState` total=False field**: `visual_stored_count` and `page_images` must be genuinely optional — constructing a state dict without them must not raise a TypedDict validation error. Accessing them with `.get()` must return defaults.
- **`page_images` cleared after node**: Although clearing is the node's responsibility, state.py's type annotation must accept `None` as a valid value for `page_images`.
- **`PIPELINE_NODE_NAMES` ordering**: The test must assert positional adjacency (index of `"visual_embedding"` == index of `"embedding_storage"` + 1), not merely membership.
- **Env var isolation**: Tests that modify env vars must restore the original environment (use `monkeypatch.setenv` / `monkeypatch.delenv` or `unittest.mock.patch.dict`). Since constants are read at module-import time, tests that need to verify different env-var values must reload the module (via `importlib.reload`) within the patched environment.

---

#### Integration points

- **`config/settings.py` → `types.py`**: `IngestionConfig` imports the six constants as field defaults. If settings.py raises at import (invalid integer env var), all of `types.py` and everything that imports it will also fail to import.
- **`types.py` → `impl.py`**: `_check_visual_embedding_config` is defined in `types.py` but called in `impl.py`. Tests here only cover the function's own return contract; the call site (error propagation, startup abort) is tested in the impl module's test section.
- **`types.py` → `workflow.py`**: `workflow.py` reads `IngestionConfig` fields (specifically `enable_knowledge_graph_storage`) to set conditional routing out of `visual_embedding`. Workflow tests must construct an `IngestionConfig` and pass it to `build_embedding_graph()`.
- **`state.py` → `visual_embedding_node`**: The node reads `page_images` and writes `visual_stored_count`. State tests verify field presence and type annotations; node behavior is out of scope here.
- **`workflow.py` → `visual_embedding_node` module**: `workflow.py` imports `visual_embedding_node` at module load time. The `ImportError` propagation test therefore exercises the `workflow.py` import path, not a function call.
- **`PIPELINE_NODE_NAMES` → progress reporting / result aggregation**: Callers that iterate over `PIPELINE_NODE_NAMES` to build progress dicts or validate result keys will break if `"visual_embedding"` is absent or misplaced. The count and ordering tests guard this contract.

---

#### Known test gaps

- **Case-sensitivity of boolean truthy strings**: The spec states truthy strings are `"true"/"1"/"yes"`. It is unspecified whether `"True"`, `"TRUE"`, or `"YES"` are also accepted. Tests should document observed behavior and flag this as a spec clarification needed if uppercase forms do not match the spec's intent.
- **Module-reload env var tests**: Because constants are read at import time, testing different env var values requires `importlib.reload(settings)`. This pattern is fragile in test suites that share a process; isolation via subprocess or dedicated test modules may be needed but is not mandated here.
- **`_check_visual_embedding_config` warning list**: The spec defines the return as `(errors, warnings)` but only specifies error conditions. No warning-triggering conditions are documented. Tests cannot cover warning output until warnings are specified; this is a known gap.
- **`EmbeddingPipelineState` runtime validation**: `state.py` explicitly has no runtime validation. There are no tests for invalid field types because the TypedDict contract is structural, not enforced at runtime. Mypy/pyright type checking is outside the scope of pytest tests.
- **Graph compilation internals**: Tests inspect node presence and edge topology via the LangGraph compiled graph's public API. If LangGraph does not expose a stable introspection API, edge topology tests may need to be implemented as smoke-run integration tests rather than structural unit tests.
- **`IngestFileResult.visual_stored_count` non-zero values**: FR-605 states that after a 10-page doc with visual enabled, `visual_stored_count=10`. This end-to-end count correctness is owned by the visual embedding node test section, not this config/state section.

---

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files, other modules' test specs, or the engineering guide directly.

---

### `src/ingest/support/docling.py` — Docling Page Image Extraction

**Module purpose:** Additive extension to the Docling parsing integration that optionally extracts per-page PIL images and page count from PDF conversion results, controlled by a `generate_page_images` flag.

**In scope:**
- `DoclingParseResult` dataclass extension: `page_images` (list[Any]) and `page_count` (int) fields
- `parse_with_docling()` new `generate_page_images: bool = False` parameter
- `PdfPipelineOptions(generate_page_images=True)` construction and injection before `convert()`
- `_extract_page_images_from_result()` dual-strategy image extraction (Strategy 1: `conv_result.pages`, Strategy 2: `conv_result.document.pages`)
- Per-image RGB conversion via `image.convert("RGB")`
- Per-page failure handling: WARNING log + skip, no exception propagation
- `page_count` derivation from document structure (independent of image extraction success)

**Out of scope:**
- Docling internals (`PdfPipelineOptions` implementation, `convert()` behavior)
- Downstream ColQwen2 VLM embedding consumption of page images
- Non-PDF document types
- Image persistence or serialization
- Markdown text extraction (existing baseline behavior, not modified)

---

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Default (no images) | `parse_with_docling(path, generate_page_images=False)` | `page_images=[]`, `page_count=0`, `text_markdown` populated, existing fields unaffected |
| 10-page PDF with images enabled | `parse_with_docling(path, generate_page_images=True)` on 10-page PDF | `len(page_images) == 10`, `page_count == 10` |
| Page count matches image count | 10-page PDF, all pages accessible | `page_count == 10`, `len(page_images) == 10` |
| RGB normalization | PDF page image in RGBA mode, `generate_page_images=True` | Returned image has exactly 3 channels (RGB mode), no exception raised |
| RGB passthrough | PDF page image already in RGB mode | Image returned as-is with RGB mode, no double-conversion error |
| Baseline text track preserved | `generate_page_images=True` on valid PDF | `text_markdown`, `has_figures`, `figures`, `headings`, `parser_model` all populated as before |
| Strategy 1 extraction | `conv_result.pages` accessible with `.image.pil_image` | Images extracted via Strategy 1; Strategy 2 not invoked |
| Strategy 2 fallback extraction | `conv_result.pages` inaccessible or empty; `conv_result.document.pages` accessible | Images extracted via Strategy 2; same result shape as Strategy 1 |
| DoclingParseResult default fields | Instantiate `DoclingParseResult(text_markdown="x", ...)` without providing `page_images`/`page_count` | `page_images == []`, `page_count == 0` |

---

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| Both strategies yield no images | `conv_result.pages` and `conv_result.document.pages` both inaccessible or empty | `page_images=[]`, `page_count` still set from document structure, no exception raised |
| Single page `.image` attribute missing | One page in `conv_result.pages` lacks `.image` or `.image.pil_image` | That page skipped, WARNING logged, remaining pages returned, `len(page_images) < page_count` allowed |
| RGB conversion failure on one page | `image.convert("RGB")` raises for one page | That page skipped, WARNING logged, other pages continue unaffected |
| Full image extraction failure | All pages fail `.image.pil_image` access | `page_images=[]`, `page_count` reflects total pages, `text_markdown` unaffected, no exception to caller |
| `page_count` independent of image failures | 10-page PDF, 3 pages fail extraction | `page_count == 10`, `len(page_images) == 7` |
| `generate_page_images=True` on non-PDF | Non-PDF file passed with flag enabled | Behavior follows existing Docling `convert()` behavior; `page_images=[]`, `page_count=0` (no crash guarantee from this module) |

---

#### Boundary conditions

- **FR-201**: Exactly 10 images extracted for a 10-page PDF (not 9, not 11) — validates off-by-one in page iteration
- **FR-205 (RGB conversion)**: An image in RGBA mode (4 channels) must be converted to RGB (3 channels) before inclusion in `page_images`; resulting image must have `mode == "RGB"` and exactly 3 channels
- **page_count invariant**: `page_count` must equal total document pages regardless of how many images were successfully extracted; it must never be derived from `len(page_images)`
- **Default field initialization**: `DoclingParseResult` constructed without `page_images` and `page_count` must use `field(default_factory=list)` so different instances do not share the same list object
- **Zero-page document**: Document with 0 pages — `page_images=[]`, `page_count=0`, no exception
- **Single-page document**: 1-page PDF — `len(page_images) == 1` (or 0 on failure), `page_count == 1`
- **`generate_page_images=False` is a complete no-op**: `PdfPipelineOptions` with image generation must NOT be constructed when flag is False; existing behavior must be identical

---

#### Integration points

- **Called by**: `src/ingest/embedding/nodes/vlm_enrichment.py` (visual track) indirectly via the ingest pipeline, which invokes `parse_with_docling()` with `generate_page_images=True` when `IngestionConfig.enable_visual_embedding=True`
- **Calls into**: Docling `DocumentConverter.convert()`, `PdfPipelineOptions`, PIL `Image.convert()`
- **Returns**: `DoclingParseResult` dataclass — callers access `.page_images` (list of PIL Image objects) and `.page_count` (int) for downstream VLM embedding
- **Config gate**: `IngestionConfig.generate_page_images` (FR-107) controls whether this extension activates; when False, result is indistinguishable from pre-extension baseline
- **Text track decoupling**: `text_markdown` and all existing fields must remain valid and complete even when image extraction fails entirely

---

#### Known test gaps

- **Live PDF conversion not tested**: Tests should mock `DocumentConverter.convert()` to avoid filesystem and Docling runtime dependencies; actual PDF rendering fidelity is out of scope for unit tests
- **Strategy 1 vs. Strategy 2 distinction in same Docling version**: Both strategies may succeed simultaneously in some Docling versions; test must explicitly mock one path unavailable to verify fallback
- **RGBA source image provenance**: Tests use synthetically constructed RGBA PIL images; real Docling RGBA output may differ in edge cases (e.g., transparency masks)
- **Concurrent/thread-safety of `page_images` list**: Not tested; list construction is sequential in the current design
- **Non-PDF page count behavior**: `page_count` derivation for DOCX or HTML inputs is not specified and not tested
- **Warning log content**: Tests verify WARNING is emitted but do not assert log message text (avoids brittleness)

---

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files, other modules' test specs, or the engineering guide directly.

---

## Integration Test Specification

### Scenario 1: Happy Path — 10-Page PDF, Visual Enabled

**Description:** Full end-to-end ingestion of a 10-page PDF with visual embedding enabled, exercising all four external service integrations and both text and visual tracks to completion.

**Entry point:**

```python
visual_embedding_node(state: EmbeddingPipelineState) -> dict
```

Called as a LangGraph node after `embedding_storage` completes. The `state` passed in carries the completed text-track output plus `page_images` and `docling_document` from the parse stage.

**Flow:**

Step 1 — Docling parse (upstream, provides initial state)

`parse_with_docling(path, generate_page_images=True)` is called. `PdfPipelineOptions(generate_page_images=True)` is constructed before `converter.convert(path)`.

State entering `visual_embedding_node`:

```python
{
    "config": IngestionConfig(
        enable_visual_embedding=True,
        colqwen_batch_size=4,
        page_image_max_dimension=1024,
        page_image_quality=85
    ),
    "document_id": "<uuid>",
    "source_key": "docs/<uuid>/file.pdf",
    "source_uri": "s3://bucket/docs/<uuid>/file.pdf",
    "source_name": "file.pdf",
    "raw_text": "<str>",
    "docling_document": DoclingDocument(...),
    "page_images": [PIL.Image × 10],   # RGB, size=(842, 1190) each
    "page_count": 10,
    # text track completed:
    "stored_count": 47,
    "chunks": [...],
    "enriched_chunks": [...],
    "metadata_summary": "<str>",
    "metadata_keywords": [...],
    "processing_log": [...],   # entries from text track
    "errors": []
}
```

Step 2 — Short-circuit check

`config.enable_visual_embedding` is `True` and `docling_document` is present. Node proceeds.

Step 3 — Image extraction

`state["page_images"]` has 10 items — primary path taken. Fallback to `DoclingDocument.pages` is not invoked.

Step 4 — Image resize

Longer edge of each image is 1190 px, which exceeds `page_image_max_dimension=1024`. Scale factor ≈ 0.860. Each image resized to 724×1024 via `PIL.Image.resize`.

State at resize boundary:

```python
resized_images: [PIL.Image × 10]   # size=(724, 1024), mode="RGB"
```

Step 5 — Pre-cleanup

`delete_page_images(minio_client, document_id, bucket)` called — returns `0` (first-run document, no prior MinIO objects).
`delete_visual_by_source_key(weaviate_client, source_key, collection="RAGVisualPages")` called — returns `0`.

Step 6 — MinIO storage

`store_page_images(minio_client, document_id, pages=resized_images, quality=85, bucket=...)` called.

10 JPEG objects uploaded via `client.put_object`. Keys follow the pattern:

```
pages/<uuid>/0001.jpg
pages/<uuid>/0002.jpg
...
pages/<uuid>/0010.jpg
```

State at MinIO boundary:

```python
minio_keys: [
    "pages/<uuid>/0001.jpg",
    "pages/<uuid>/0002.jpg",
    # ... 10 total
    "pages/<uuid>/0010.jpg"
]
minio_key_map: {1: "pages/<uuid>/0001.jpg", ..., 10: "pages/<uuid>/0010.jpg"}
```

Step 7 — ColQwen2 inference

`ensure_colqwen_ready()` passes without raising. `load_colqwen_model(model_name)` returns `(mock_model, mock_processor)`.

`embed_page_images(model, processor, images=resized_images, batch_size=4, page_numbers=[1..10])` runs 3 batches: (pages 1–4), (pages 5–8), (pages 9–10).

Returns 10 embeddings:

```python
embeddings: [
    ColQwen2PageEmbedding(
        page_number=N,
        mean_vector=[0.1] * 128,
        patch_vectors=[[0.05] * 128] * 800,
        patch_count=800
    )
    for N in range(1, 11)
]
```

`unload_colqwen_model(model)` is called in `finally` regardless of outcome.

Step 8 — Weaviate indexing

`ensure_visual_collection(weaviate_client, collection="RAGVisualPages")` called. Mock `exists` returns `False` on first call → `create` called.

10 document dicts assembled, one per page:

```python
{
    "document_id": "<uuid>",
    "source_key": "docs/<uuid>/file.pdf",
    "source_uri": "s3://bucket/docs/<uuid>/file.pdf",
    "source_name": "file.pdf",
    "page_number": N,
    "minio_key": "pages/<uuid>/000N.jpg",
    "mean_vector": [0.1] * 128,
    "patch_vectors": [[0.05] * 128] * 800,
    "patch_count": 800
}
```

`add_visual_documents(weaviate_client, docs, collection="RAGVisualPages")` returns `10`. `batch.failed_objects = []`.

Step 9 — Node return

```python
{
    "visual_stored_count": 10,
    "page_images": None,
    "processing_log": [
        # ...prior text-track entries preserved...,
        "visual_embedding:pages_extracted:10",
        "visual_embedding:pages_stored_minio:10",
        "visual_embedding:pages_embedded:10",
        "visual_embedding:pages_indexed:10",
        "visual_embedding:elapsed_s:<float>"
    ]
    # no "errors" key (zero errors)
}
```

`IngestFileResult`: `stored_count=47`, `visual_stored_count=10`.

**What to assert:**

- `result["visual_stored_count"] == 10`
- `result["page_images"] is None`
- `"visual_embedding:pages_extracted:10"` appears in `result["processing_log"]`
- `"visual_embedding:pages_stored_minio:10"` appears in `result["processing_log"]`
- `"visual_embedding:pages_embedded:10"` appears in `result["processing_log"]`
- `"visual_embedding:pages_indexed:10"` appears in `result["processing_log"]`
- `"visual_embedding:elapsed_s:"` prefix appears in at least one entry of `result["processing_log"]`
- `"errors"` key is absent from `result` (no errors occurred)
- Text-track isolation: `"stored_count"` is absent from `result`
- Text-track isolation: `"chunks"` is absent from `result`
- Text-track isolation: `"enriched_chunks"` is absent from `result`
- Text-track isolation: `"metadata_summary"` is absent from `result`
- Text-track isolation: `"metadata_keywords"` is absent from `result`
- Mock ColQwen2 `load_colqwen_model` called exactly once
- Mock ColQwen2 `unload_colqwen_model` called exactly once (in `finally`)
- Mock ColQwen2 `embed_page_images` called with `batch_size=4` and `page_numbers` spanning pages 1–10
- Mock MinIO `put_object` called exactly 10 times
- Mock MinIO `remove_object` called 0 times during pre-cleanup (no prior objects)
- Mock Weaviate `client.collections.create` called once (collection did not exist)
- Mock Weaviate `col.batch.failed_objects` is empty list

**Mocks required:**

- Mock: ColQwen2 Model + Processor
- Mock: MinIO Client
- Mock: Weaviate v4 Client
- Mock: PIL Image
- Mock: Docling DocumentConverter (for the upstream parse step that populates `page_images`)

---

### Scenario 2: Disabled Path — Zero-Overhead Short-Circuit

**Description:** When `enable_visual_embedding=False`, the node returns immediately without invoking any external service, model, or I/O operation.

**Entry point:**

```python
visual_embedding_node(state: EmbeddingPipelineState) -> dict
```

Called as a LangGraph node. `state["config"].enable_visual_embedding` is `False`.

**Flow:**

Step 1 — Docling parse (upstream)

`parse_with_docling(path, generate_page_images=False)` called. No `PdfPipelineOptions` with `generate_page_images=True` is constructed.

State entering `visual_embedding_node`:

```python
{
    "config": IngestionConfig(enable_visual_embedding=False),
    "document_id": "<uuid>",
    "source_key": "docs/<uuid>/file.pdf",
    "docling_document": DoclingDocument(...),
    "page_images": [],        # empty — generate_page_images=False
    "page_count": 0,
    "stored_count": 47,
    "chunks": [...],
    "processing_log": [...],
    "errors": []
}
```

Step 2 — Short-circuit evaluation

```python
if not config.enable_visual_embedding:
    return {
        "visual_stored_count": 0,
        "page_images": None,
        "processing_log": append_processing_log(state, "visual_embedding:skipped:disabled")
    }
```

Node returns in microseconds. No image resize, no pre-cleanup, no MinIO I/O, no model load, no Weaviate call.

Step 3 — Node return

```python
{
    "visual_stored_count": 0,
    "page_images": None,
    "processing_log": [
        # ...prior entries...,
        "visual_embedding:skipped:disabled"
    ]
}
```

`IngestFileResult`: `stored_count=47`, `visual_stored_count=0`.

**What to assert:**

- `result["visual_stored_count"] == 0`
- `result["page_images"] is None`
- `"visual_embedding:skipped:disabled"` appears in `result["processing_log"]`
- Mock ColQwen2 Model + Processor: `load_colqwen_model` is never called
- Mock ColQwen2 Model + Processor: `embed_page_images` is never called
- Mock ColQwen2 Model + Processor: `unload_colqwen_model` is never called
- Mock MinIO Client: `put_object` is never called
- Mock MinIO Client: `remove_object` is never called
- Mock MinIO Client: `list_objects` is never called
- Mock Weaviate v4 Client: `client.collections.exists` is never called
- Mock Weaviate v4 Client: `client.collections.create` is never called
- Mock Weaviate v4 Client: `add_visual_documents` is never called
- Mock PIL Image: `.resize` is never called

**Mocks required:**

- Mock: ColQwen2 Model + Processor (asserted as never called)
- Mock: MinIO Client (asserted as never called)
- Mock: Weaviate v4 Client (asserted as never called)
- Mock: PIL Image (asserted as never called for resize)
- Mock: Docling DocumentConverter (for upstream parse step with `generate_page_images=False`)

---

### Scenario 3: Partial Failure — Some Pages Fail Inference

**Description:** Visual embedding proceeds normally through MinIO storage but pages 3 and 7 fail during ColQwen2 batch inference, producing 8 indexed pages while 10 are stored in MinIO, surfacing the partial failure signal in the processing log.

**Entry point:**

```python
visual_embedding_node(state: EmbeddingPipelineState) -> dict
```

Called as a LangGraph node. `state["config"].enable_visual_embedding` is `True`. All 10 pages present in `state["page_images"]`.

**Flow:**

Step 1 — State entering `visual_embedding_node`

```python
{
    "config": IngestionConfig(
        enable_visual_embedding=True,
        colqwen_batch_size=4,
        page_image_max_dimension=1024,
        page_image_quality=85
    ),
    "document_id": "<uuid>",
    "source_key": "docs/<uuid>/file.pdf",
    "docling_document": DoclingDocument(...),
    "page_images": [PIL.Image × 10],
    "page_count": 10,
    "stored_count": 47,
    "processing_log": [...],
    "errors": []
}
```

Step 2 — Short-circuit check

`config.enable_visual_embedding` is `True`, `docling_document` present. Node proceeds.

Step 3 — Image extraction and resize

All 10 images extracted from `state["page_images"]`. Resize applied. 10 resized images produced.

Step 4 — Pre-cleanup

`delete_page_images` returns `0`. `delete_visual_by_source_key` returns `0`.

Step 5 — MinIO storage

All 10 pages succeed. `store_page_images` returns 10 keys.

State at MinIO boundary:

```python
minio_keys: [
    "pages/<uuid>/0001.jpg",
    # ...
    "pages/<uuid>/0010.jpg"
]  # length 10
minio_key_map: {1: "pages/<uuid>/0001.jpg", ..., 10: "pages/<uuid>/0010.jpg"}
```

Step 6 — ColQwen2 inference (partial failure)

`ensure_colqwen_ready()` passes. `load_colqwen_model(model_name)` returns `(mock_model, mock_processor)`.

`embed_page_images` processes three batches. Pages 3 and 7 raise per-page errors during inference:

```
Batch 1 (pages 1–4): page 3 fails → WARNING logged, skipped
Batch 2 (pages 5–8): page 7 fails → WARNING logged, skipped
Batch 3 (pages 9–10): both succeed
```

Return value from `embed_page_images`:

```python
embeddings: [
    ColQwen2PageEmbedding(page_number=1,  mean_vector=[0.1]*128, patch_vectors=[[0.05]*128]*800, patch_count=800),
    ColQwen2PageEmbedding(page_number=2,  mean_vector=[0.1]*128, patch_vectors=[[0.05]*128]*800, patch_count=800),
    # page 3 absent
    ColQwen2PageEmbedding(page_number=4,  mean_vector=[0.1]*128, patch_vectors=[[0.05]*128]*800, patch_count=800),
    ColQwen2PageEmbedding(page_number=5,  mean_vector=[0.1]*128, patch_vectors=[[0.05]*128]*800, patch_count=800),
    ColQwen2PageEmbedding(page_number=6,  mean_vector=[0.1]*128, patch_vectors=[[0.05]*128]*800, patch_count=800),
    # page 7 absent
    ColQwen2PageEmbedding(page_number=8,  mean_vector=[0.1]*128, patch_vectors=[[0.05]*128]*800, patch_count=800),
    ColQwen2PageEmbedding(page_number=9,  mean_vector=[0.1]*128, patch_vectors=[[0.05]*128]*800, patch_count=800),
    ColQwen2PageEmbedding(page_number=10, mean_vector=[0.1]*128, patch_vectors=[[0.05]*128]*800, patch_count=800),
]  # length 8
```

`unload_colqwen_model(model)` called in `finally`.

Step 7 — Weaviate indexing

`ensure_visual_collection` called. 8 document dicts assembled (pages 1, 2, 4, 5, 6, 8, 9, 10).

For failed pages:

```python
minio_key_map.get(3, "")  # → "" (orphaned MinIO object, no embedding)
minio_key_map.get(7, "")  # → "" (orphaned MinIO object, no embedding)
```

Pages 3 and 7 have MinIO objects but no Weaviate documents. `add_visual_documents` returns `8`.

Step 8 — Node return

```python
{
    "visual_stored_count": 8,
    "page_images": None,
    "processing_log": [
        # ...prior entries...,
        "visual_embedding:pages_extracted:10",
        "visual_embedding:pages_stored_minio:10",
        "visual_embedding:pages_embedded:8",
        "visual_embedding:pages_indexed:8",
        "visual_embedding:elapsed_s:<float>"
    ]
}
```

`IngestFileResult`: `stored_count=47`, `visual_stored_count=8`.

**What to assert:**

- `result["visual_stored_count"] == 8`
- `result["page_images"] is None`
- `"visual_embedding:pages_extracted:10"` appears in `result["processing_log"]`
- `"visual_embedding:pages_stored_minio:10"` appears in `result["processing_log"]`
- `"visual_embedding:pages_embedded:8"` appears in `result["processing_log"]`
- `"visual_embedding:pages_indexed:8"` appears in `result["processing_log"]`
- Both `pages_embedded:8` and `pages_extracted:10` present simultaneously — operator partial failure signal is readable from log alone
- `"visual_embedding:elapsed_s:"` prefix appears in at least one processing log entry
- Mock MinIO `put_object` called exactly 10 times (all pages uploaded despite inference failures)
- Mock ColQwen2 `unload_colqwen_model` called exactly once (in `finally`, even after partial failure)
- Mock Weaviate `add_visual_documents` called with exactly 8 document dicts (pages 3 and 7 excluded)
- Weaviate document dicts do not contain entries for `page_number=3` or `page_number=7`
- `"errors"` key is absent from `result` (per-page inference failures are warnings, not errors)

**Mocks required:**

- Mock: ColQwen2 Model + Processor (configured to skip/fail pages 3 and 7 during `embed_page_images`)
- Mock: MinIO Client
- Mock: Weaviate v4 Client
- Mock: PIL Image
- Mock: Docling DocumentConverter (for upstream parse step)

---

## FR-to-Test Traceability Matrix

### Configuration (FR-101 to FR-109)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-101 | MUST | enable_visual_embedding flag; disabled node short-circuits with zero overhead | module_config_state — default False, module_visual_node — disabled short-circuit | integration_disabled |
| FR-102 | MUST | visual_target_collection configurable, defaults to "RAGVisualPages" | module_config_state — default value | integration_happy |
| FR-103 | MUST | colqwen_model_name configurable, defaults to "vidore/colqwen2-v1.0" | module_config_state — default model name | integration_happy |
| FR-104 | MUST | colqwen_batch_size configurable int, range 1-32, default 4 | module_config_state — range validation, module_colqwen — batch inference | integration_happy — 3 batches for 10 pages |
| FR-105 | MUST | page_image_quality configurable int, default 85, range 1-100 | module_config_state — range validation, module_minio — JPEG quality | integration_happy |
| FR-106 | MUST | page_image_max_dimension configurable int, default 1024, range 256-4096 | module_config_state — range validation, module_visual_node — resize applied | integration_happy |
| FR-107 | MUST | generate_page_images derived from enable_visual_embedding; passed to parse_with_docling | module_config_state — property derivation, module_docling — parameter gating | integration_happy — 10 images extracted |
| FR-108 | MUST | config validation at startup; visual requires Docling, range checks enforced | module_config_state — _check_visual_embedding_config all 4 rules | integration_happy |
| FR-109 | MUST | all params as RAG_INGESTION_* env vars (6 env vars) | module_config_state — all 6 env vars mapped | integration_happy |

### Page Image Extraction (FR-201 to FR-205)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-201 | MUST | extract page images from docling_document, 1-indexed page numbers | module_docling — 10 images for 10-page PDF, module_visual_node — extract from state + fallback | integration_happy — 10 pages extracted |
| FR-202 | MUST | resize so longer edge ≤ page_image_max_dimension, preserve aspect ratio | module_visual_node — resize LANCZOS | integration_happy |
| FR-203 | MUST | zero extractable pages → short-circuit, visual_stored_count=0, log no_pages | module_visual_node — zero pages short-circuit | Not covered — known gap: requires synthetic doc with zero pages |
| FR-204 | MUST | record original dimensions (page_width_px, page_height_px) in Weaviate | module_visual_node — original dims in Weaviate dict | integration_happy |
| FR-205 | SHOULD | convert page images to RGB before processing | module_docling — RGB conversion from RGBA | Not covered — known gap: live PDF mocking with RGBA needed |

### ColQwen2 Embedding (FR-301 to FR-307)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-301 | MUST | load ColQwen2 with 4-bit quant via bitsandbytes, after MinIO storage | module_colqwen — 4-bit load | integration_happy |
| FR-302 | MUST | batch inference at colqwen_batch_size; each page → 128-dim patches (500-1200) | module_colqwen — batch count, page numbering, patch range | integration_happy — 3 batches for 10 pages |
| FR-303 | MUST | mean-pool all patch vectors → single 128-dim float32 mean_vector | module_colqwen — mean vector arithmetic mean, 128-dim | integration_happy |
| FR-304 | MUST | retain raw patch_vectors as JSON-serializable list[list[float]] | module_colqwen — JSON serializable, size range | integration_happy |
| FR-305 | MUST | unload model + release GPU VRAM after all pages processed (always via finally) | module_colqwen — GPU release in finally block, module_visual_node — unload called in finally despite partial | integration_partial |
| FR-306 | SHOULD | log inference progress ~every 10% for docs >10 pages | module_colqwen — progress logging intervals | Not covered — known gap: interval exactness flaky in CI |
| FR-307 | MUST | per-page inference failures → warning log + skip page, continue remaining | module_colqwen — per-page skip with warning, module_visual_node — per-item error boundary | integration_partial — pages 3,7 skipped with warning |

### MinIO Page Image Storage (FR-401 to FR-405)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-401 | MUST | key pattern pages/{document_id}/{page_number:04d}.jpg, 1-indexed, zero-padded | module_minio — key pattern 1-indexed zero-padded | integration_happy — 10 MinIO keys pattern |
| FR-402 | MUST | JPEG encoding at configured quality, using resized image | module_minio — JPEG quality, buffer correctness | Not covered — known gap: JPEG byte validity needs real PIL+MinIO integration |
| FR-403 | MUST | MinIO storage before ColQwen2 model load | module_visual_node — ordering via orchestration (caller responsibility) | integration_happy — MinIO called before model load |
| FR-404 | MUST | reuse existing MinIO client and bucket, pages/ prefix | module_minio — pages/ prefix, same bucket | integration_happy |
| FR-405 | MUST | delete existing page images before storing new ones (update mode cleanup) | module_minio — delete-before-insert delete_page_images | integration_happy — pre-cleanup called |

### Weaviate Visual Collection (FR-501 to FR-507)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-501 | MUST | dedicated collection distinct from text collection | module_visual_store — dedicated collection | integration_happy — collection created |
| FR-502 | MUST | idempotent ensure_visual_collection (create if absent, no-op if present) | module_visual_store — idempotent create | integration_happy |
| FR-503 | MUST | 11 scalar properties per page object | module_visual_store — all 11 properties | integration_happy — document dict properties |
| FR-504 | MUST | mean_vector named vector, 128-dim HNSW cosine, for ANN | module_visual_store — mean_vector named vector 128-dim | integration_happy |
| FR-505 | MUST | patch_vectors as JSON TEXT property, skip_vectorization=True | module_visual_store — patch_vectors TEXT skip_vectorization | Not covered — known gap: patch_vectors round-trip needs live Weaviate |
| FR-506 | MUST | delete_visual_by_source_key for update mode cleanup | module_visual_store — delete by source_key, module_visual_node — pre-cleanup called | integration_happy — pre-cleanup called |
| FR-507 | MUST | batch insert add_visual_documents | module_visual_store — batch insert, count returned | integration_happy — 10 docs inserted, integration_partial — 8 docs inserted |

### Pipeline Integration (FR-601 to FR-606)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-601 | MUST | visual_embedding node in LangGraph DAG, after embedding_storage, before knowledge_graph_storage | module_config_state — DAG edges, node count=10, module_visual_node — node wired in DAG | integration_happy — node wired correctly |
| FR-602 | MUST | EmbeddingPipelineState extended with visual_stored_count and page_images | module_config_state — EmbeddingPipelineState new fields | integration_happy |
| FR-603 | MUST | short-circuit on False flag, None docling_document, zero pages; log reason; visual_stored_count=0 | module_visual_node — 3 short-circuit conditions, module_config_state — disabled path | integration_disabled — skipped:disabled log entry |
| FR-604 | MUST | "visual_embedding" in PIPELINE_NODE_NAMES, between embedding_storage and knowledge_graph_storage | module_config_state — PIPELINE_NODE_NAMES count=15, ordering | Not covered — known gap: graph introspection API stability |
| FR-605 | MUST | IngestFileResult.visual_stored_count field, default 0 | module_config_state — IngestFileResult.visual_stored_count default=0, module_visual_node — visual_stored_count always int | integration_happy — visual_stored_count=10, integration_partial — visual_stored_count=8 |
| FR-606 | MUST | page_images set to None after node completes (memory cleanup) | module_visual_node — page_images=None on return | integration_happy, integration_disabled, integration_partial |

### Format-Specific Handling (FR-701 to FR-705)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-701 | MUST | PDF support, one image per page, correct ordering | module_docling — 10 images for 10-page PDF, module_visual_node — processing log entries | integration_happy — PDF → 10 pages |
| FR-702 | MUST | PPTX support, one image per slide, correct ordering | module_docling — slide extraction via Docling | Not covered — known gap: PPTX integration test needed |
| FR-703 | SHOULD | DOCX support via Docling layout engine | module_docling — DOCX handling | Not covered — known gap: DOCX integration test needed |
| FR-704 | MUST | pure image files (JPG/PNG) as single-page document | module_visual_node — processing log entries | Not covered — known gap: image file integration test needed |
| FR-705 | MUST | format-specific failures → log warning, visual_stored_count=0, no exception, text track unaffected | module_visual_node — format failure handling, module_config_state — backward compat | Not covered — known gap: format-specific error scenarios in integration |

### Error Handling (FR-801 to FR-806)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-801 | MUST | per-item try/except per page; failure on one page doesn't prevent others | module_visual_node — per-item error boundary, module_colqwen — per-page skip with warning | integration_partial — pages 3,7 skipped with warning |
| FR-802 | MUST | ColQwen2 load failure → fatal for visual track, log error, visual_stored_count=0, add to errors, no retry | module_colqwen — ColQwen2LoadError fatal, module_visual_node — ensure/load raise handling | Not covered — known gap: requires model load failure integration scenario |
| FR-803 | MUST | never write to text-track state fields (stored_count, chunks, enriched_chunks, etc.) | module_visual_node — text-track isolation invariant | integration_happy — text-track fields absent from result |
| FR-804 | MUST | MinIO failure for a page → non-fatal, warn, skip that page's embedding | module_visual_node — MinIO partial skip, module_minio — per-page failure isolation | integration_partial — partial MinIO semantics |
| FR-805 | MUST | Weaviate batch failure → add to errors, visual_stored_count=0 or partial, no exception | module_visual_node — Weaviate batch failure, module_visual_store — batch insert count returned | Not covered — known gap: Weaviate batch failure integration scenario needed |
| FR-806 | SHOULD | pre-check colpali-engine + bitsandbytes installed; clear error with install command | module_colqwen — ColQwen2LoadError message content, module_visual_node — ensure_colqwen_ready error message | Not covered — known gap: import error handling integration test |

### Non-Functional Requirements (NFR-901 to NFR-910)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| NFR-901 | MUST | peak VRAM ≤4GB during ColQwen2 inference (4-page batch at 1024px) | module_colqwen — peak memory test | Not covered — known gap: requires GPU hardware measurement |
| NFR-902 | MUST | ≤5 seconds/page average on target hardware (RTX 2060) | Not covered — known gap: requires target hardware benchmark | Not covered — known gap: requires target hardware benchmark |
| NFR-903 | MUST | zero overhead when disabled; wall-clock <10ms; no GPU alloc; no I/O | module_config_state — disabled path, module_visual_node — disabled path <10ms gap | integration_disabled — no external service calls |
| NFR-904 | SHOULD | MinIO page image size 30-300KB per page at quality=85 | module_minio — JPEG quality | Not covered — known gap: byte size validation needs real PIL+MinIO |
| NFR-905 | MUST | all behavioral params configurable without code changes | module_config_state — configurable | integration_happy |
| NFR-906 | MUST | colpali-engine + bitsandbytes as optional [visual] extras in pyproject.toml | module_config_state — backward compat | integration_disabled — no import error when disabled |
| NFR-907 | SHOULD | idempotent re-ingestion (same doc → same objects in Weaviate) | module_visual_store — idempotent create, module_minio — delete-before-insert | Not covered — known gap: idempotence round-trip verification needed |
| NFR-908 | SHOULD | deterministic embeddings for same page image across runs | module_colqwen — adapter isolation | Not covered — known gap: requires determinism verification across runs |
| NFR-909 | MUST | no breaking changes to existing text pipeline API/state/behavior | module_config_state — backward compat, module_visual_store — existing methods unchanged, module_visual_node — text-track isolation invariant | integration_happy — text-track fields absent from result |
| NFR-910 | SHOULD | ColQwen2 adapter follows docling.py pattern, isolates colpali-engine | module_colqwen — adapter isolation | integration_happy |
