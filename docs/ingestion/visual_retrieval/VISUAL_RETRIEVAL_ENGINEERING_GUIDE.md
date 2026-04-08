# Visual Page Retrieval Pipeline — Engineering Guide

**Subsystem:** Visual Page Retrieval
**Status:** Post-implementation reference
**Last updated:** 2026-04-01
**Companion spec:** `docs/ingestion/visual_retrieval/VISUAL_RETRIEVAL_SPEC.md`
**Companion design:** `docs/ingestion/visual_retrieval/VISUAL_RETRIEVAL_DESIGN.md`

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture Decisions](#2-architecture-decisions)
3. [Module Reference](#3-module-reference)
   - 3.1 [`src/ingest/support/colqwen.py`](#31-srcingestsupportcolqwenpy--colqwen2-model-adapter)
   - 3.2 [`src/vector_db/weaviate/visual_store.py`](#32-srcvector_dbweaviatevisual_storepy--weaviate-visual-collection-store)
   - 3.3 [`src/db/minio/store.py`](#33-srcdbminiostorepy--minio-page-image-store-visual-additions)
   - 3.4 [`src/retrieval/common/schemas.py`](#34-srcretrievalcommonschemaspy--retrieval-pipeline-schemas)
   - 3.5 [`src/retrieval/pipeline/rag_chain.py`](#35-srcretrievalpipelinerag_chainpy--ragchain-visual-retrieval-track)
   - 3.6 [`src/vector_db/backend.py` + `src/vector_db/__init__.py`](#36-srcvector_dbbackendpy--srcvector_db__init__py--vectorbackend-abc-and-public-api)
   - 3.7 [`config/settings.py` — Visual Retrieval Config](#37-configsettingspy--visual-retrieval-configuration-keys)
   - 3.8 [`server/schemas.py` — API Response Schemas](#38-serverschemasspy--api-response-schemas)
4. [End-to-End Data Flow](#4-end-to-end-data-flow)
5. [Configuration Reference](#5-configuration-reference)
6. [Integration Contracts](#6-integration-contracts)
7. [Operational Notes](#7-operational-notes)
8. [Known Limitations](#8-known-limitations)
9. [Extension Guide](#9-extension-guide)
10. [Appendix: Requirement Coverage](#10-appendix-requirement-coverage)

---

## 1. System Overview

### Purpose

The visual page retrieval pipeline adds a second, parallel retrieval track to the existing text-based RAG pipeline. Where the text track finds relevant document chunks by semantic text similarity, the visual track finds relevant document **pages** by visual similarity — matching diagrams, charts, tables, and layout-dense slides that carry meaning the text extraction cannot fully capture.

The pipeline encodes a text query into the ColQwen2 128-dimensional visual embedding space, searches a dedicated Weaviate collection (`RAGVisualPages`) of pre-embedded page images, generates presigned MinIO URLs for matched pages, and returns them alongside the text results in the API response.

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                          RAGChain.run()                         │
│                                                                 │
│   Text Query ─────────────────────────────────────────────────► │
│         │                                                       │
│         ▼                                                       │
│   ┌─────────────────────────────────────────┐                   │
│   │         TEXT TRACK (unchanged)          │                   │
│   │  query_processor → BGE-M3 embed →       │                   │
│   │  Weaviate hybrid search → BGE rerank →  │                   │
│   │  Ollama/LiteLLM generate               │                   │
│   └─────────────────────────────────────────┘                   │
│         │                                                       │
│         ▼  (sequential, after text track)                       │
│   ┌─────────────────────────────────────────┐                   │
│   │       VISUAL TRACK (new)                │                   │
│   │                                         │                   │
│   │  if RAG_VISUAL_RETRIEVAL_ENABLED:       │                   │
│   │                                         │                   │
│   │  processed_query                        │                   │
│   │       │                                 │                   │
│   │       ▼                                 │                   │
│   │  ColQwen2.embed_text_query()            │                   │
│   │  → 128-dim query vector                 │                   │
│   │       │                                 │                   │
│   │       ▼                                 │                   │
│   │  Weaviate.visual_search()               │                   │
│   │  (RAGVisualPages, near_vector,          │                   │
│   │   mean_vector named index, cosine)      │                   │
│   │  → list[page_record]                    │                   │
│   │       │                                 │                   │
│   │       ▼                                 │                   │
│   │  MinIO.get_page_image_url()             │                   │
│   │  → presigned URL per page               │                   │
│   │       │                                 │                   │
│   │       ▼                                 │                   │
│   │  list[VisualPageResult]                 │                   │
│   └─────────────────────────────────────────┘                   │
│         │                                                       │
│         ▼                                                       │
│   RAGResponse(results=[...], visual_results=[...])              │
└─────────────────────────────────────────────────────────────────┘
```

### Design Goals

| Goal | Implementation |
|------|---------------|
| Zero cost when disabled | Visual track is fully gated by `RAG_VISUAL_RETRIEVAL_ENABLED`; ColQwen2 is never loaded if False |
| Additive — no text track regression | New methods on ABC, new fields on response, no modification to existing search or generation code paths |
| Configuration over hardcoding | All thresholds, limits, timeouts, model names, and collection names are env-var driven |
| Schemas first | `VisualPageResult` dataclass defined in `retrieval/common/schemas.py` before any code uses it |
| Single Weaviate instance | Visual collection and text collection share the same Weaviate client, reducing connection overhead |

### Technology Choices

| Component | Technology | Reason |
|-----------|------------|--------|
| Visual embedding model | ColQwen2 (`vidore/colqwen2-v1.0`) | Pre-trained cross-modal model; same model used for ingestion and retrieval ensures query and page vectors are in the same space |
| Model quantization | 4-bit (BitsAndBytes) | Keeps peak VRAM at ≤4 GB (NFR-901), enabling deployment on consumer GPU hardware |
| Vector index | Weaviate named vector `mean_vector`, HNSW, cosine | 128-dim cosine ANN search; HNSW is appropriate for the expected collection size (thousands of pages) |
| Page image store | MinIO, presigned URLs | Time-limited presigned URLs avoid serving binary data through the API server; direct client-to-storage access |

---

## 2. Architecture Decisions

### Decision: Additive visual track — sequential after text track

**Context:** The visual track needs ColQwen2 (GPU) and the text track needs BGE-M3 (GPU). Both models must share one GPU in the target deployment (RTX 2060, 6 GB VRAM).

**Options considered:**
1. **Parallel execution** — run text and visual tracks concurrently using ThreadPoolExecutor
2. **Sequential execution** — run text track first, then visual track after text completes
3. **Single merged model** — replace BGE-M3 with a model that serves both text and visual retrieval

**Choice:** Option 2 — sequential execution.

**Rationale:** Running BGE-M3 and ColQwen2 simultaneously on the same GPU causes CUDA meta-tensor errors and VRAM exhaustion under the 6 GB budget. Sequential execution is deterministic and safe. The total added latency (ColQwen2 inference + Weaviate near-vector query) is budgeted at 10 seconds via `RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS`, which is acceptable for the non-streaming path.

**Consequences:**
- **Positive:** No VRAM contention; predictable latency budget per track.
- **Negative:** Total wall-clock time increases by the visual retrieval stage duration when enabled.
- **Watch for:** If a future deployment has separate GPUs for embedding and visual models, the sequential constraint can be relaxed by running `_run_visual_retrieval` in a ThreadPoolExecutor future alongside the generation stage.

---

### Decision: Lazy ColQwen2 model loading

**Context:** RAGChain is instantiated once per server process (or once per CLI invocation). ColQwen2 weighs ~3 GB loaded at 4-bit precision.

**Options considered:**
1. **Eager load at `__init__`** — load model when RAGChain is constructed
2. **Lazy load on first visual query** — load model on the first call to `_run_visual_retrieval`
3. **External model server** — run ColQwen2 as a separate process, query over gRPC/HTTP

**Choice:** Option 2 — lazy load.

**Rationale:** Eager loading would add ~3 GB VRAM pressure at startup even when no visual queries have been issued. The lazy pattern costs one extra check (`if self._visual_model is not None`) on every subsequent query, which is negligible. Option 3 introduces operational complexity (managing a separate process) that is not justified for a single-GPU deployment.

**Consequences:**
- **Positive:** No VRAM consumed if visual retrieval is enabled but not yet exercised. Server starts faster.
- **Negative:** First visual query incurs a cold-start latency penalty (model load from disk or HuggingFace cache, typically 15–60 seconds).
- **Watch for:** In multi-worker deployments, each worker loads ColQwen2 independently. With N workers, VRAM consumption is N × 3 GB. Limit visual workers explicitly if VRAM is constrained.

---

### Decision: Single Weaviate instance for both text and visual collections

**Context:** The pipeline already maintains a persistent Weaviate client for text retrieval. Visual retrieval needs Weaviate access too.

**Options considered:**
1. **Shared persistent client** — reuse `self._weaviate_client` for visual collection queries
2. **Separate visual client** — open a second persistent connection to Weaviate for visual queries
3. **Separate Weaviate instance** — run a dedicated Weaviate server for visual embeddings

**Choice:** Option 1 — shared persistent client.

**Rationale:** Weaviate's multi-collection model is designed for this use case: one client, multiple named collections. A second connection would consume a TCP socket and handshake overhead for no benefit. A separate Weaviate instance adds operational complexity (separate configuration, health-check, backup). The `RAGVisualPages` collection uses its own named vector index and schema — it is fully isolated from `RAGDocuments` within the same Weaviate instance.

**Consequences:**
- **Positive:** No additional connection management. Visual and text searches can be interleaved without contention.
- **Negative:** If Weaviate is down, both text and visual retrieval fail simultaneously. This is acceptable — text search also fails in this scenario.
- **Watch for:** If visual collection queries start affecting text query latency due to resource contention, consider moving visual queries to an ephemeral client.

---

### Decision: `patch_vectors` stored as JSON TEXT in Weaviate, not indexed

**Context:** ColQwen2 produces a variable number of 128-dimensional patch vectors per page (one per spatial patch, count varies with image resolution). These could be used for MaxSim late-interaction re-scoring.

**Options considered:**
1. **Index patch vectors as a second named vector** — enable ANN search on individual patches
2. **Store as serialized JSON TEXT** — keep in Weaviate as an opaque field for CPU-side retrieval
3. **Store externally** — separate object storage (MinIO or Redis) for patch vectors

**Choice:** Option 2 — JSON TEXT in Weaviate.

**Rationale:** Indexing variable-length patch arrays as individual vectors in Weaviate would require a multi-vector index format not natively supported in the v4 client. External storage would require a second lookup per result. JSON TEXT avoids binary encoding round-trips, remains human-readable in debug queries, and keeps all page metadata co-located. The current pipeline uses only the mean vector for ANN search; patch vectors are retained for future MaxSim re-scoring without requiring a schema change. The field carries `skip_vectorization=True` to prevent Weaviate from misinterpreting the JSON as text to vectorize.

**Consequences:**
- **Positive:** Zero schema changes needed to enable future MaxSim re-scoring; all patch data survives round-trips.
- **Negative:** Patch vectors add storage overhead per object (~`n_patches × 128 × 8 bytes` of JSON per page). Large documents or high-resolution pages increase object size.
- **Watch for:** If Weaviate object size limits become a concern, consider truncating patch vectors to the top-K patches or moving to external storage.

---

### Decision: `visual_results` is `Optional[List[VisualPageResult]]`, not `List` with empty default

**Context:** The `RAGResponse` dataclass needs to carry visual results without breaking existing callers that do not use visual retrieval.

**Options considered:**
1. **`Optional[List]` defaulting to `None`** — absent when not run
2. **`List` defaulting to `[]`** — always present, empty when not run

**Choice:** Option 1 — `Optional[List]` with `None` default.

**Rationale:** `None` allows callers to distinguish "visual retrieval was not run" from "visual retrieval ran and found nothing." This distinction is important for API serialization (`None` fields are omitted from JSON; empty lists are included). It also allows older callers that do not check `visual_results` to safely ignore the field without special-casing an empty list.

**Consequences:**
- **Positive:** Clean API serialization. Clear semantic distinction between "disabled" and "no results."
- **Negative:** Callers must null-check before iterating. Forgetting the null check raises `TypeError`.
- **Watch for:** Server-side serialization must handle `None` gracefully — FastAPI/Pydantic handles this automatically with `Optional` fields.

---

## 3. Module Reference

### 3.1 `src/ingest/support/colqwen.py` — ColQwen2 Model Adapter

**Purpose:**

This module is a minimal, lifecycle-complete adapter around the ColQwen2 vision-language model. It serves two consumers: the ingestion pipeline (which calls `embed_page_images` to produce per-page visual embeddings from document scans), and the retrieval pipeline (which calls `embed_text_query` to encode a text query into the same 128-dimensional vector space). By concentrating all ColQwen2 interactions in one module, the rest of the system treats visual embedding as a black-box operation invoked with a model handle. The `embed_text_query` function is the retrieval-side addition — it is the bridge that makes cross-modal search possible: text queries and page images are both projected into the same 128-dimensional ColQwen2 embedding space, enabling cosine similarity comparison between them.

---

**How it works:**

The module enforces a four-phase lifecycle: dependency validation, model load, inference, and memory release. All four phases are called explicitly by callers; the module holds no global state.

**Phase 1 — Dependency validation (`ensure_colqwen_ready`)**

Before any model I/O, `ensure_colqwen_ready` attempts to import `colpali_engine` and `bitsandbytes` in isolation. If either is absent, it raises `ColQwen2LoadError` with a precise `pip install` command embedded in the message. This fast-fail check lets the calling code surface a clear, actionable error rather than a cryptic `ImportError` from inside model initialization.

**Phase 2 — Model load (`load_colqwen_model`)**

`load_colqwen_model(model_name)` loads ColQwen2 from a HuggingFace model identifier. It builds a `BitsAndBytesConfig` requesting 4-bit integer weights with float16 compute dtype, passes `device_map="auto"` so PyTorch places layers across available CUDA devices automatically, then calls `model.eval()` to disable training-mode behavior. The companion `ColQwen2Processor` is loaded from the same model identifier. The function returns `(model, processor)` as an opaque pair; callers store both and pass them to inference functions.

**Phase 3a — Page image embedding (`embed_page_images`)**

`embed_page_images(model, processor, images, batch_size, *, page_numbers=None)` iterates over `images` in batches, runs each batch through the ColQwen2 processor and model under `torch.inference_mode()`, and extracts per-page tensors. For each page it computes the arithmetic mean across the patch axis to produce a 128-dim mean vector (FR-303), and converts both mean and raw patch vectors to plain Python `list[float]` for JSON serialization (FR-304). Per-batch and per-page failures are caught and logged as warnings; the affected pages are omitted from the returned list (FR-307).

**Phase 3b — Text query encoding (`embed_text_query`) — retrieval-side addition**

`embed_text_query(model, processor, text)` encodes a text string into the same 128-dimensional ColQwen2 space used for page image embeddings. This is what makes cross-modal retrieval possible. The function:

1. Validates that `text` is non-empty (raises `ValueError` with "empty or blank" in the message).
2. Validates that `model` and `processor` are not `None` (raises `ColQwen2LoadError`).
3. Calls `processor.process_queries([text])` — the processor's query-mode tokenizer, distinct from `process_images`.
4. Moves tokenized inputs to the model's device.
5. Runs a forward pass under `torch.inference_mode()`.
6. Extracts the output tensor for the single query: shape `(1, n_tokens, 128)` → slices to `(n_tokens, 128)`.
7. Mean-pools across the token axis (`dim=0`) to produce a single 128-dim vector.
8. Returns the vector as `list[float]`.

```python
def embed_text_query(model: Any, processor: Any, text: str) -> list[float]:
    if not text or not text.strip():
        raise ValueError("Query text is empty or blank")
    if model is None or processor is None:
        raise ColQwen2LoadError(
            "ColQwen2 model or processor is None — call load_colqwen_model() first"
        )
    import torch
    query_inputs = processor.process_queries([text])
    query_inputs = {k: v.to(model.device) for k, v in query_inputs.items()}
    with torch.inference_mode():
        query_output = model(**query_inputs)
    # ColQwen2 query mode produces (1, n_tokens, 128); slice to (n_tokens, 128)
    if hasattr(query_output, "last_hidden_state"):
        q_tensor = query_output.last_hidden_state[0]
    elif isinstance(query_output, torch.Tensor):
        q_tensor = query_output[0]
    else:
        q_tensor = query_output[0]
    return q_tensor.float().mean(dim=0).cpu().tolist()
```

The key point: `processor.process_queries` (not `process_images`) is used. The ColQwen2 processor has separate tokenization paths for images and queries. Using the wrong one would produce vectors that do not align with the indexed page vectors.

**Phase 4 — Memory release (`unload_colqwen_model`)**

`unload_colqwen_model(model)` deletes the model reference, calls `torch.cuda.empty_cache()`, and triggers `gc.collect()`. The three-step sequence is necessary because Python's garbage collector does not guarantee immediate deallocation of CUDA tensors; `empty_cache` returns fragmented unreferenced allocations to the CUDA allocator pool, and `gc.collect` handles cyclic references.

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| 4-bit quantization (BitsAndBytes, float16 compute) | fp16 full precision; 8-bit quantization | 4-bit is the only configuration that keeps peak VRAM at or below 4 GB (NFR-901). 8-bit still exceeds the budget for ColQwen2's parameter count. |
| `torch.inference_mode()` during forward pass | `torch.no_grad()` | `inference_mode` is a strict superset of `no_grad` — it additionally disables version counter tracking, reducing memory and CPU overhead during batched inference. |
| `processor.process_queries` for text encoding | `process_images` with a text-rendered image | ColQwen2 has a dedicated query encoder. Using `process_queries` keeps text in its natural token form rather than rendering it as a fake image, which would degrade embedding quality. |
| Mean-pooling across token axis for text queries | CLS token; max pooling | Mean pooling matches the page-side pooling strategy (mean across patches), producing vectors that are in the same statistical distribution. CLS tokens are model-specific and not reliable for ColQwen2. |
| Per-page and per-batch exception isolation in `embed_page_images` | Fail entire run on first error | Pages are independent. One corrupt image should not abort the entire document's embedding. |
| Optional dependencies under `rag[visual]` extras | Hard dependency in pyproject.toml | ColQwen2 and bitsandbytes carry large transitive deps (CUDA toolkit, Triton). Text-only deployments should not require a GPU environment (NFR-906). |

---

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `model_name` (to `load_colqwen_model`) | `str` | — (required) | HuggingFace model identifier or local path. Passed to `ColQwen2.from_pretrained` and `ColQwen2Processor.from_pretrained`. The production default is `"vidore/colqwen2-v1.0"` set in `config/settings.py`. |
| `batch_size` (to `embed_page_images`) | `int` | — (required) | Number of page images per GPU forward pass. Directly controls peak VRAM. Default of 4 is appropriate for the 4 GB VRAM budget. |
| `page_numbers` (to `embed_page_images`) | `list[int] \| None` | `None` → 1-indexed sequential | Explicit 1-indexed page numbers to assign to each image position. Must match `len(images)` if supplied. |
| `text` (to `embed_text_query`) | `str` | — (required) | Non-empty query text. The function raises `ValueError` on empty or whitespace-only strings. |

The 4-bit quantization dtype and `device_map="auto"` are fixed in `load_colqwen_model` and not exposed as parameters — they are the only configuration satisfying the VRAM budget constraint.

---

**Error behavior:**

**`ColQwen2LoadError` (fatal, subclass of `VisualEmbeddingError`)**
Raised by `ensure_colqwen_ready` (missing packages) and `load_colqwen_model` (any model load failure). Also raised by `embed_text_query` when `model` or `processor` is `None`. Callers must treat this as unrecoverable for the current pipeline run. Retrying with the same parameters will not succeed.

**`VisualEmbeddingError` (non-fatal base)**
Base class. Also raised by `embed_text_query` when the model forward pass raises an unexpected exception (e.g., CUDA OOM). The original exception is chained as `__cause__`. Callers should treat this as a non-fatal visual track failure and return text-only results.

**`ValueError`**
Raised by `embed_text_query` when `text` is empty or whitespace-only. The model is not invoked. The message contains "empty" or "blank".

**Per-page failures in `embed_page_images` (non-fatal, no exception)**
Failures at the batch preprocessing, inference, or tensor extraction level are caught internally, logged at `WARNING` level, and silently skipped. The affected pages are absent from the returned list. Callers must compare the `page_number` fields in the returned list against the expected page set to detect gaps.

---

### 3.2 `src/vector_db/weaviate/visual_store.py` — Weaviate Visual Collection Store

**Purpose:**

This module manages the `RAGVisualPages` Weaviate collection, which holds per-page visual embeddings produced during document ingestion and queried during visual retrieval. It is separate from the text chunk collection because visual pages require a different retrieval strategy and different schema: a 128-dimensional named vector (`mean_vector`) for ANN search, page geometry properties, and a MinIO key for image access. The module now includes `visual_search`, the retrieval-side addition: it accepts a 128-dim query vector, performs near-vector search on the `mean_vector` named index using cosine similarity, filters by `score_threshold`, applies an optional tenant filter, and returns result dicts excluding the bulky `patch_vectors` field.

---

**How it works:**

**Collection creation — `ensure_visual_collection`**

Checks whether the named collection exists via `client.collections.exists(collection)` and returns immediately if it does (idempotent). When absent, creates the collection with:
- A `NamedVectors.none` vector config named `"mean_vector"`: 128-dim, HNSW index, cosine distance. The `none` vectorizer means no automatic re-vectorization.
- Eleven scalar properties: `document_id`, `page_number`, `source_key`, `source_uri`, `source_name`, `tenant_id`, `total_pages`, `page_width_px`, `page_height_px`, `minio_key`, and `patch_vectors` (TEXT with `skip_vectorization=True`).

**Batch insert — `add_visual_documents`**

Iterates a list of document dicts using `col.batch.dynamic()`. For each document, the `"mean_vector"` key is extracted as the named vector argument to `add_object`; all other keys become scalar properties. The Weaviate v4 named-vector pattern requires `vector={"mean_vector": mean_vector}`. Returns the number of successfully inserted objects (total minus failed objects from `col.batch.failed_objects`).

**Delete by source key — `delete_visual_by_source_key`**

Deletes all page objects sharing a `source_key` via a server-side filter-delete in one call. This removes every page of a document atomically without enumerating page numbers.

**Near-vector search — `visual_search` (retrieval-side addition)**

```python
def visual_search(
    client: weaviate.WeaviateClient,
    query_vector: list[float],
    limit: int,
    score_threshold: float,
    tenant_id: Optional[str] = None,
    collection: str = "RAGVisualPages",
) -> list[dict[str, Any]]:
```

Steps:
1. Starts an observability span `vector_store.visual_search`.
2. Gets the collection handle.
3. Builds a `Filter.by_property("tenant_id").equal(tenant_id)` filter when `tenant_id` is not `None`.
4. Declares explicit `return_properties` — the nine result fields — excluding `patch_vectors` to avoid returning large JSON blobs (FR-311).
5. Calls `col.query.near_vector(near_vector=query_vector, target_vector="mean_vector", limit=limit, filters=filters, return_properties=..., return_metadata=MetadataQuery(distance=True))`.
6. For each returned object, converts cosine distance to similarity: `score = 1.0 - distance`. Objects where `score < score_threshold` are discarded.
7. Returns a list of dicts with keys: `document_id`, `page_number`, `source_key`, `source_name`, `minio_key`, `tenant_id`, `total_pages`, `page_width_px`, `page_height_px`, `score`.

The distance-to-similarity conversion (`1.0 - distance`) assumes cosine distance is returned by Weaviate as a value in `[0.0, 1.0]` where 0.0 is identical and 1.0 is orthogonal. This matches Weaviate's cosine metric convention.

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Separate `RAGVisualPages` collection | Single collection with type discriminator; separate Weaviate tenant per modality | Dedicated collection allows the HNSW index to be sized and tuned for 128-dim cosine vectors; avoids schema pollution in the text collection; makes query filters simpler. |
| Named vector `"mean_vector"` with `vectorizer=none` | Default unnamed vector; multi-vector index for both mean and patch | Named vectors are the Weaviate v4 idiomatic pattern for externally supplied embeddings. `none` vectorizer ensures no accidental re-vectorization. |
| `patch_vectors` stored as JSON TEXT, not indexed | Weaviate BLOB property; external store; structured array property | TEXT avoids binary encoding round-trips, is human-readable, and does not require a schema change when patch dimensionality changes. Patch vectors are for future MaxSim re-scoring, not ANN search. |
| Score threshold filtering after Weaviate returns results | Pre-filter using Weaviate's `certainty` parameter | Post-filtering on `score = 1.0 - distance` is explicit and testable. Weaviate's `certainty` parameter behavior varies across versions; explicit post-filtering is version-stable. |
| Exclude `patch_vectors` from `return_properties` | Return all properties | `patch_vectors` can be large (hundreds of floats serialized as JSON). Excluding it from search results avoids transmitting data the retrieval caller never needs (FR-311). |
| Idempotent `ensure_visual_collection` | Fail-fast if absent; caller-managed creation | Idempotent creation removes the need for startup ordering guarantees. Safe to call on every ingestion run. |

---

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `collection` (all functions) | `str` | `"RAGVisualPages"` | Target Weaviate collection name. Must match across creation, insertion, deletion, and search. Override for per-tenant or per-environment isolation. |
| `limit` (to `visual_search`) | `int` | — (required) | Maximum results from Weaviate. Set via `RAG_VISUAL_RETRIEVAL_LIMIT` in the pipeline. |
| `score_threshold` (to `visual_search`) | `float` | — (required) | Minimum cosine similarity. Results below this value are discarded. Set via `RAG_VISUAL_RETRIEVAL_MIN_SCORE` in the pipeline. |
| `tenant_id` (to `visual_search`) | `Optional[str]` | `None` | When provided, only pages with matching `tenant_id` are returned. When `None`, no tenant filter is applied. |
| HNSW dimensions (fixed at collection creation) | `int` | `128` | Fixed to match ColQwen2 output dimensionality. Changing requires collection re-creation. |

---

**Error behavior:**

`ensure_visual_collection` is idempotent — does not validate that an existing collection's schema matches. A schema mismatch (e.g., different dimensions) is not detected; the caller is responsible for ensuring correct collection configuration.

`add_visual_documents` does not raise on partial batch failure. Returns insert count; callers should compare to `len(documents)` to detect partial failure.

`delete_visual_by_source_key` returns `0` both for "nothing matched" and "count unavailable" (older Weaviate client versions). Not suitable as a strict audit signal.

`visual_search` propagates `weaviate.exceptions.WeaviateQueryError` and `weaviate.exceptions.WeaviateConnectionError` directly to the caller. No wrapping. The observability span ends with `status="ok"` only on success; on exception, the span is not explicitly ended (relies on garbage collection).

---

### 3.3 `src/db/minio/store.py` — MinIO Page Image Store (Visual Additions)

**Purpose:**

This module handles all low-level MinIO operations for the RAG system. The visual retrieval pipeline adds one new function to the existing document store module: `get_page_image_url`. This function generates a time-limited presigned GET URL for a page image object stored under the `pages/{document_id}/{page:04d}.jpg` key namespace. It differs from the existing `get_document_url` function in one critical way: it uses the `minio_key` as-is, without appending any suffix. This is necessary because page image keys are already fully-formed object paths; the document key suffix (`.md`) convention does not apply to page images.

The module also provides `store_page_images` and `delete_page_images` for ingestion-time page image storage and cleanup (documented below for completeness, though they are not part of the retrieval path).

---

**How it works:**

**`get_page_image_url` — retrieval-side addition**

```python
def get_page_image_url(
    client: Minio,
    minio_key: str,
    bucket: str = "",
    expires_in_seconds: int = 0,
) -> str:
```

The function uses sentinel defaults: `bucket=""` and `expires_in_seconds=0`. On entry, it resolves both:
- `bucket` defaults to `MINIO_BUCKET` from `config.settings` when empty.
- `expires_in_seconds` defaults to `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` (default: 3600) when 0.

The resolved values are passed to `client.presigned_get_object(bucket, minio_key, expires=timedelta(seconds=expires_in_seconds))`. The function wraps the call in an observability span `document_store.get_page_image_url`. No suffix is appended to `minio_key` — the key is used verbatim (contrast with `get_document_url` which appends `.md`).

MinIO generates presigned URLs without verifying that the object exists. If the `minio_key` does not exist in the bucket, the URL is still generated and returned; the client will receive a 404 when it attempts to use the URL.

**`store_page_images` — ingestion path**

Iterates `(page_number, image)` tuples. Constructs key `pages/{document_id}/{page_number:04d}.jpg`. Serializes each image to JPEG in a `BytesIO` buffer, measures the buffer length by seeking to the end, rewinds, and uploads to MinIO. Per-page failures are isolated — one failed upload does not block others. Returns the list of successfully stored keys.

**`delete_page_images` — ingestion path (update-mode cleanup)**

Constructs the document-level prefix `pages/{document_id}/`, lists all objects under it, and removes each individually. Returns the count of deleted objects. If listing fails, returns 0. If an individual removal fails, returns the partial count (early exit).

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Sentinel defaults (`bucket=""`, `expires_in_seconds=0`) instead of `None` | `Optional[str]` and `Optional[int]` with `None` defaults | The MinIO client's `put_object` and `presigned_get_object` accept bucket as a required positional string. Using `""` as a sentinel avoids an `Optional[str]` annotation that would still require a None check before calling the client. The pattern is explicit about "no override provided." |
| `minio_key` used verbatim (no suffix appended) | Append `.jpg` suffix; use a structured path object | Page image keys are fully-formed at ingestion time (e.g., `pages/{doc_id}/0001.jpg`). The key stored in Weaviate is the exact MinIO object path. Appending any suffix would corrupt the key. |
| Separate `pages/` prefix namespace from document content | Subdirectory under the document key, combined prefix | Keeps page images independently listable and deletable without touching document content. Enables future per-namespace lifecycle policies. |
| JPEG compression with configurable quality | PNG (lossless), WebP | JPEG is broadly supported. Configurable quality (default 85) lets callers tune storage size vs. fidelity. |
| In-memory `BytesIO` buffer for image serialization | `tempfile.NamedTemporaryFile` | Avoids filesystem I/O. `put_object` accepts any file-like object with a known length. |
| Per-page error isolation in `store_page_images` | Abort on first failure | A single corrupted or oversized page should not block all others from being stored. |

---

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `minio_key` (to `get_page_image_url`) | `str` | — (required) | Full MinIO object key for the page image. Used verbatim — no suffix appended. Typically `pages/{document_id}/{page_number:04d}.jpg`. |
| `bucket` (to `get_page_image_url`) | `str` | `""` → resolves to `MINIO_BUCKET` | MinIO bucket containing the page images. Defaults to the shared document bucket. |
| `expires_in_seconds` (to `get_page_image_url`) | `int` | `0` → resolves to `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` (3600) | Presigned URL expiry in seconds. Clamped by `validate_visual_retrieval_config` to [60, 86400]. |
| `quality` (to `store_page_images`) | `int` | `85` | JPEG compression quality. Range 1–95. Set globally via `RAG_INGESTION_PAGE_IMAGE_QUALITY`. |
| `bucket` (to `store_page_images`, `delete_page_images`) | `str` | `MINIO_BUCKET` | MinIO bucket. Override for testing or multi-bucket deployments. |

---

**Error behavior:**

**`get_page_image_url`**
Propagates `minio.error.S3Error` and `minio.error.InvalidResponseError` to the caller. Does not verify object existence before generating the URL (MinIO signs without existence check). The caller (`_run_visual_retrieval` in `rag_chain.py`) wraps this in a per-page `try/except` and logs a warning on failure.

**`store_page_images`**
Each page is wrapped in `try/except`. Failures log a `WARNING` and continue. Returns a list that may be shorter than the input. No exception propagates.

**`delete_page_images`**
Listing failures log a `WARNING` and return 0. Per-object deletion failures log a `WARNING` and return the partial count (early exit). No exception propagates.

---

### 3.4 `src/retrieval/common/schemas.py` — Retrieval Pipeline Schemas

**Purpose:**

This module defines the typed contracts that cross the retrieval pipeline's internal boundaries. It is a pure schema module with no logic. All pipeline stages import from here rather than defining their own types, ensuring a single source of truth. The visual retrieval pipeline adds two new types to this module:

1. **`VisualPageResult`** — the per-page visual retrieval result dataclass carrying document provenance, match score, page geometry, and a presigned MinIO URL.
2. **`RAGResponse.visual_results`** — an `Optional[List[VisualPageResult]]` field on the existing response dataclass. When visual retrieval is disabled or returns no results, this field is `None`. When results are present, it is a non-empty list ordered by descending cosine similarity.

---

**How it works:**

The module defines four dataclasses using Python's standard `@dataclass` decorator.

`VisualPageResult` carries all fields needed to display a matched page to a user — document identity (`document_id`, `source_key`, `source_name`), page location (`page_number`, `total_pages`), match quality (`score`), display metadata (`page_width_px`, `page_height_px`), and a time-limited URL for the page image (`page_image_url`).

```python
@dataclass
class VisualPageResult:
    document_id: str          # Document identifier (FR-501)
    page_number: int          # 1-indexed page number (FR-501)
    source_key: str           # Stable source key for traceability (FR-501)
    source_name: str          # Human-readable source name (FR-501)
    score: float              # Cosine similarity 0.0-1.0 (FR-501)
    page_image_url: str       # Presigned MinIO URL (FR-501, FR-607)
    total_pages: int          # Total pages in source document (FR-501)
    page_width_px: int        # Page image width in pixels (FR-501)
    page_height_px: int       # Page image height in pixels (FR-501)
```

`RAGResponse` carries the visual results as an optional field alongside the existing text retrieval results:

```python
@dataclass
class RAGResponse:
    # ... existing fields ...
    visual_results: Optional[List["VisualPageResult"]] = None  # FR-503
```

`RAGRequest` and `RankedResult` are unchanged by this feature.

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| `VisualPageResult` as a separate dataclass from `RankedResult` | Extend `RankedResult` with optional image fields | Text and visual results have fundamentally different fields. Extending `RankedResult` would produce a bloated type with many `Optional` fields and no compile-time field safety. |
| `visual_results` is `Optional[List]` (None when absent) | `List` with empty default | `None` allows callers to distinguish "visual retrieval not run" from "ran and found nothing." `None` fields are omitted from JSON responses; empty lists are included. |
| `page_image_url` included in the retrieval schema | URL generated at API serialization layer | The URL is generated in the pipeline (RAGChain). Including it in the schema keeps the API layer as a thin serializer with no MinIO knowledge. |
| Python `@dataclass` instead of Pydantic `BaseModel` | Pydantic BaseModel for all types | These are internal pipeline types. Validation happens at the pipeline boundary, not inside the type. Pydantic overhead is unnecessary for in-process data flow. The API layer (`server/schemas.py`) uses Pydantic for the external contract. |

---

**Configuration:**

This module has no configurable parameters. All field values come from the pipeline code that constructs the dataclass instances.

---

**Error behavior:**

This module contains only dataclass definitions and raises no exceptions of its own. Missing required fields at construction time raise Python's standard `TypeError`. No validation is performed on field values (e.g., `score` is not range-checked). All validation is the responsibility of the code that constructs instances.

---

### 3.5 `src/retrieval/pipeline/rag_chain.py` — RAGChain Visual Retrieval Track

**Purpose:**

`RAGChain` orchestrates the full retrieval pipeline. This section documents only the visual retrieval additions — the three new methods and initialization changes that implement the visual track. The visual track runs sequentially after the text retrieval stages (query processing → KG expansion → embedding → hybrid search → reranking → generation) and is entirely gated by `RAG_VISUAL_RETRIEVAL_ENABLED`. When enabled, it encodes the processed query via ColQwen2, searches the `RAGVisualPages` Weaviate collection, generates presigned MinIO URLs for each matched page, and attaches `List[VisualPageResult]` to `RAGResponse.visual_results`. The ColQwen2 model is loaded lazily — only on the first visual query.

---

**How it works:**

**Initialization**

After loading all other pipeline components, the constructor checks `RAG_VISUAL_RETRIEVAL_ENABLED`:

```python
self._visual_retrieval_enabled = RAG_VISUAL_RETRIEVAL_ENABLED
self._visual_model = None
self._visual_processor = None
if self._visual_retrieval_enabled:
    from config.settings import validate_visual_retrieval_config
    validate_visual_retrieval_config()  # fail fast on bad config (FR-111)
    logger.info("Visual retrieval enabled — model will be loaded on first visual query.")
```

`validate_visual_retrieval_config()` raises `ValueError` immediately if configuration is contradictory (empty collection name, `MIN_SCORE` outside [0.0, 1.0], URL expiry outside [60, 86400]). This prevents silent misconfiguration.

**Lazy model loading — `_ensure_visual_model`**

```python
def _ensure_visual_model(self) -> None:
    if self._visual_model is not None:
        return  # warm path — single attribute check
    with self.tracer.span("visual_retrieval.model_load"):
        from src.ingest.support.colqwen import ensure_colqwen_ready, load_colqwen_model
        from config.settings import RAG_INGESTION_COLQWEN_MODEL
        ensure_colqwen_ready()
        self._visual_model, self._visual_processor = load_colqwen_model(RAG_INGESTION_COLQWEN_MODEL)
```

The warm path is a single attribute check. ColQwen2 imports are deferred inside the method to keep visual dependencies out of the text-only import path.

**Visual retrieval track — `_run_visual_retrieval`**

Executes three sequential steps, each wrapped in an observability span:

1. `visual_retrieval.text_encode`: Calls `embed_text_query(self._visual_model, self._visual_processor, processed_query)` after ensuring the model is loaded. Uses the **processed query** (post-reformulation output from `process_query`), not the raw user input.

2. `visual_retrieval.search`: Calls `search_visual(client=self._weaviate_client, query_vector=query_vector, limit=RAG_VISUAL_RETRIEVAL_LIMIT, score_threshold=RAG_VISUAL_RETRIEVAL_MIN_SCORE, tenant_id=tenant_id)`. Reuses the persistent Weaviate client shared with the text retrieval path.

3. `visual_retrieval.presigned_urls`: Creates a new MinIO client (`create_minio_client()`) and iterates `page_records`. For each record, calls `get_page_image_url(minio_client, minio_key=record["minio_key"])`. Per-page URL generation failures are caught, logged as `WARNING`, and the page is skipped. Successful pages are assembled into `VisualPageResult` dataclasses.

**Integration in `run()`**

The `run()` method allocates a stage budget for `"visual_retrieval"` from `stage_budget_overrides` or `RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS`. After the text stages complete, when `self._visual_retrieval_enabled` is True, it calls `_run_visual_retrieval` and attaches the result:

```python
visual_results = self._run_visual_retrieval(processed_query, tenant_id)
response.visual_results = visual_results if visual_results else None
```

An empty list is normalized to `None` — the response field is either `None` or a non-empty list.

**Lifecycle — `close()`**

On close, if the visual model was loaded, `unload_colqwen_model(self._visual_model)` is called to free VRAM, then `_visual_model` and `_visual_processor` are set to `None`.

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Sequential execution after text track | Parallel execution | BGE-M3 and ColQwen2 both use GPU. Concurrent execution causes VRAM contention and CUDA meta-tensor errors on single-GPU deployments (RTX 2060). |
| Lazy model loading | Eager loading at `__init__` | Avoids VRAM consumption when visual retrieval is enabled but no visual queries have arrived. Server starts faster. |
| Use processed query for visual encoding | Use raw user query | The query processor reformulates ambiguous queries before text search; the same improvement applies to visual search. |
| Per-page URL generation failure = skip, not abort | Abort entire visual retrieval on any URL failure | Partial visual results are strictly better than no visual results for the user. |
| New MinIO client per `_run_visual_retrieval` call | Persistent MinIO client | MinIO clients are lightweight (no persistent connection pool). Creating one per call avoids connection lifecycle management. Negligible overhead vs. GPU inference. |
| Config validation at init | Lazy validation at first query | Fail-fast surfaces misconfiguration before any traffic is served. |

---

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `RAG_VISUAL_RETRIEVAL_ENABLED` | `bool` | `False` | Master switch — if False, visual track never executes and ColQwen2 is never loaded |
| `RAG_INGESTION_COLQWEN_MODEL` | `str` | `"vidore/colqwen2-v1.0"` | Model identifier for both ingestion-time embedding and retrieval-time query encoding |
| `RAG_VISUAL_RETRIEVAL_LIMIT` | `int` | `5` | Maximum visual results from Weaviate |
| `RAG_VISUAL_RETRIEVAL_MIN_SCORE` | `float` | `0.3` | Minimum cosine similarity; results below this are discarded |
| `RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS` | `int` | `10000` | Stage time budget in milliseconds for the entire visual retrieval stage |

---

**Error behavior:**

- `ColQwen2LoadError` from `_ensure_visual_model`: Propagates through `_run_visual_retrieval` to `run()`. The caller should catch this, log at ERROR level, and return a text-only `RAGResponse` with `visual_results=None`.
- `ValueError` from `validate_visual_retrieval_config` at init: Propagates immediately. The server or CLI will fail to start. Callers cannot proceed.
- `VisualEmbeddingError` from `embed_text_query`: Propagates from `_run_visual_retrieval`. Treat as non-fatal visual track failure; return text-only results.
- `weaviate.exceptions.WeaviateQueryError` from `search_visual`: Propagates from `_run_visual_retrieval`. Same treatment.
- Per-page MinIO URL generation failure: Caught inside `_run_visual_retrieval`, logged as WARNING, page skipped. Does not raise to `run()`.

---

### 3.6 `src/vector_db/backend.py` + `src/vector_db/__init__.py` — VectorBackend ABC and Public API

**Purpose:**

These two files form the vector store abstraction layer. `backend.py` defines the `VectorBackend` abstract base class — the formal swappable contract between pipeline code and any vector store implementation. `__init__.py` provides the public API: config-driven backend selection, single-collection and multi-collection search, and re-exported schemas. The visual retrieval pipeline extends both files additively:

- `backend.py` gains four new abstract methods declaring the visual collection interface contract: `ensure_visual_collection`, `add_visual_documents`, `delete_visual_by_source_key`, and `search_visual`.
- `__init__.py` gains four corresponding public functions that delegate to the active backend: `ensure_visual_collection`, `add_visual_documents`, `delete_visual_by_source_key`, and `search_visual`.

No existing methods are modified. Swapping the backend still requires only changing `VECTOR_DB_BACKEND`.

---

**How it works:**

**`backend.py` additions — new abstract methods**

Four abstract methods are added after the existing `list_collections` method under a comment block `# -- Visual collection operations --`:

```python
@abstractmethod
def ensure_visual_collection(self, client: Any, collection: Optional[str] = None) -> None: ...

@abstractmethod
def add_visual_documents(self, client: Any, documents: List[dict[str, Any]], collection: Optional[str] = None) -> int: ...

@abstractmethod
def delete_visual_by_source_key(self, client: Any, source_key: str, collection: Optional[str] = None) -> int: ...

@abstractmethod
def search_visual(self, client: Any, query_vector: list[float], limit: int, score_threshold: float, tenant_id: Optional[str] = None, collection: Optional[str] = None) -> list[dict[str, Any]]: ...
```

These abstract methods have identical semantics to the `visual_store.py` functions but with `client: Any` (backend-agnostic) and `collection: Optional[str]` (so backends can apply their own default collection name). Any backend that does not yet support visual operations can raise `NotImplementedError` without affecting any text retrieval code path.

**`__init__.py` additions — public API functions**

`search_visual` is the primary retrieval-facing addition:

```python
def search_visual(
    client: Any,
    query_vector: list[float],
    limit: int,
    score_threshold: float,
    tenant_id: Optional[str] = None,
    collection: Optional[str] = None,
) -> list[dict[str, Any]]:
    return _get_vector_backend().search_visual(
        client, query_vector, limit, score_threshold, tenant_id, collection
    )
```

The public functions add no logic — they delegate entirely to `_get_vector_backend()`. The `_get_vector_backend()` singleton is initialized once per process based on `VECTOR_DB_BACKEND` (currently only `"weaviate"` is supported). The visual functions are included in `__all__`.

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Four new ABC methods, existing methods untouched (NFR-909) | Extend existing methods with a `modality` flag; single `search` method with mode parameter | New distinct methods preserve the existing calling convention and avoid conditionals in existing method bodies. Backend implementors that don't yet support visual collections can raise `NotImplementedError` without affecting text-retrieval code paths. |
| `collection: Optional[str]` in ABC methods | Concrete default collection name in ABC | Backends apply their own defaults. The ABC contract cannot assume the backend's collection naming convention. Passing `None` means "use your default," which is `"RAGVisualPages"` for `WeaviateBackend`. |
| Delegate-only public API functions | Add logic at `__init__.py` level (e.g., default collection resolution) | The public API is a thin facade. Logic belongs in the backend implementation. Keeping `__init__.py` logic-free makes it trivial to swap backends. |

---

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `VECTOR_DB_BACKEND` | `str` | `"weaviate"` | Selects the active backend. Only `"weaviate"` is currently supported. Unknown values raise `ValueError` at first use. |
| `collection` (to public API functions) | `Optional[str]` | `None` → backend default | Visual collection name. `None` uses `WeaviateBackend._VISUAL_COLLECTION_DEFAULT = "RAGVisualPages"`. |

---

**Error behavior:**

`_get_vector_backend()` raises `ValueError` if `VECTOR_DB_BACKEND` is set to an unknown value. This happens at the first call to any public API function.

All four new public functions propagate exceptions from the backend implementation without wrapping. `weaviate.exceptions.WeaviateQueryError` and `weaviate.exceptions.WeaviateConnectionError` can propagate to callers of `search_visual`. Pipeline code in `rag_chain.py` is responsible for catch-and-retry behavior.

---

### 3.7 `config/settings.py` — Visual Retrieval Configuration Keys

**Purpose:**

This section of `config/settings.py` defines the environment variable bindings for all visual retrieval pipeline parameters — both ingestion-side (model, batch, image quality) and retrieval-side (enable flag, search parameters, URL expiry). Constants are assigned at module import time from `os.environ.get()`. The retrieval-side group also provides a `validate_visual_retrieval_config()` function that performs cross-key consistency checks and is called by `RAGChain.__init__` when visual retrieval is enabled.

---

**How it works:**

Each constant reads an environment variable with a typed default. Boolean conversion uses the `in ("true", "1", "yes")` pattern to avoid the `bool("false") == True` trap. Integer and float conversions use `int()` and `float()` directly — non-parseable values raise `ValueError` at module import time, crashing the process before any work begins.

`RAG_VISUAL_RETRIEVAL_LIMIT` applies clamping with a warning:
```python
_raw_visual_limit = int(os.environ.get("RAG_VISUAL_RETRIEVAL_LIMIT", "5"))
if _raw_visual_limit < 1 or _raw_visual_limit > 50:
    logger.warning("RAG_VISUAL_RETRIEVAL_LIMIT=%d out of range [1, 50]; clamping.", _raw_visual_limit)
RAG_VISUAL_RETRIEVAL_LIMIT: int = max(1, min(50, _raw_visual_limit))
```

Values outside [1, 50] are clamped with a warning rather than raising an error — a pragmatic choice for a soft bound.

`validate_visual_retrieval_config()` is called at `RAGChain.__init__` when `RAG_VISUAL_RETRIEVAL_ENABLED` is True. It checks:
- `RAG_INGESTION_VISUAL_TARGET_COLLECTION` is not empty.
- `RAG_VISUAL_RETRIEVAL_MIN_SCORE` is in [0.0, 1.0].
- `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` is in [60, 86400].

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| `validate_visual_retrieval_config()` called at RAGChain init, not at settings load | Validate at import time; lazy validate at first query | Centralizing cross-key validation in a function called at init time separates "parse individual values" (import time) from "check consistency" (startup time). Import-time cross-key checks would require forward references. |
| `RAG_INGESTION_COLQWEN_MODEL` reused for retrieval | Separate `RAG_RETRIEVAL_COLQWEN_MODEL` key | The same model must be used for both ingestion and retrieval to ensure query and page vectors are in the same embedding space. A separate key could allow misconfiguration where they diverge. |
| Clamping `RAG_VISUAL_RETRIEVAL_LIMIT` with warning | Raise `ValueError` on out-of-range | Soft bounds — operators can correct the value without a service restart by updating the env var. A hard error on startup would be disproportionate for an out-of-range result limit. |

---

**Configuration:**

See the complete table in [Section 5: Configuration Reference](#5-configuration-reference).

---

**Error behavior:**

`int()` and `float()` conversions at module import time raise `ValueError` if the environment variable contains a non-numeric string. This is an import-time crash — the process will not start. No fallback.

`validate_visual_retrieval_config()` raises `ValueError` with a descriptive message identifying the conflicting keys. Called from `RAGChain.__init__`, this prevents the chain from being constructed with invalid configuration.

Boolean coercion (`in ("true", "1", "yes")`) cannot fail — it always evaluates to True or False.

---

### 3.8 `server/schemas.py` — API Response Schemas

**Purpose:**

This module defines the Pydantic request/response models for the RAG API server. It is the external serialization layer — the pipeline's internal dataclasses are translated here into API-safe Pydantic models for JSON serialization. The visual retrieval pipeline adds two items:

1. **`VisualPageResultResponse`** — a Pydantic `BaseModel` that maps 1:1 from `VisualPageResult` (the internal dataclass in `retrieval/common/schemas.py`). Its nine fields match exactly.
2. **`QueryResponse.visual_results`** — an `Optional[list[VisualPageResultResponse]] = None` field added to the existing query response model (FR-703).

---

**How it works:**

`VisualPageResultResponse` is a straightforward Pydantic model mirroring the internal dataclass:

```python
class VisualPageResultResponse(BaseModel):
    document_id: str
    page_number: int
    source_key: str
    source_name: str
    score: float              # cosine similarity 0.0-1.0
    page_image_url: str       # presigned MinIO URL
    total_pages: int
    page_width_px: int
    page_height_px: int
```

`QueryResponse` carries the visual results as an optional field:

```python
class QueryResponse(BaseModel):
    # ... existing fields ...
    visual_results: Optional[list[VisualPageResultResponse]] = None  # FR-703
```

FastAPI serializes `None` as absent from the JSON response body (with `response_model_exclude_none=True`, which is the convention in this project). Clients that do not set `RAG_VISUAL_RETRIEVAL_ENABLED` will never see a `visual_results` key in responses.

The `stage_budget_overrides` validator in `QueryRequest` also includes `"visual_retrieval"` as an allowed stage key, enabling callers to override the visual stage budget per request:

```python
allowed = {
    "query_processing", "kg_expansion", "embedding",
    "hybrid_search", "reranking", "generation", "visual_retrieval",
}
```

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Separate `VisualPageResultResponse` from `VisualPageResult` | Reuse the internal dataclass directly | The API layer uses Pydantic for validation and JSON serialization; the pipeline layer uses plain dataclasses for speed. Keeping them separate maintains the API/pipeline boundary. Pydantic models have serialization overhead unsuitable for in-process data flow. |
| `VisualPageResultResponse` has no `tenant_id` field | Include `tenant_id` in the response | `tenant_id` is an internal routing field. Exposing it in the public API would leak multi-tenancy implementation details to clients. The internal `VisualPageResult` carries it; the API response does not need to surface it. |
| `visual_results` defaults to `None` (not `[]`) | Default to empty list | Consistent with the internal `RAGResponse.visual_results`. `None` fields are cleanly omitted from JSON responses. |

---

**Configuration:**

This module has no configurable parameters. Field presence is determined by the pipeline's `RAGResponse.visual_results` field.

---

**Error behavior:**

Pydantic validates field types on model construction. If a `VisualPageResult` with wrong field types is passed to `VisualPageResultResponse`, Pydantic raises `ValidationError` during serialization. This would indicate a bug in the pipeline code, not a user error. The server returns a 500 in this case.

---

## 4. End-to-End Data Flow

### Scenario 1: Happy path — visual retrieval enabled, results found

**Input:** `POST /query` with body `{"query": "quarterly revenue chart Q3 2025", "tenant_id": "acme"}`

**Stage 0 — API entry:**
```
QueryRequest.query = "quarterly revenue chart Q3 2025"
QueryRequest.tenant_id = "acme"
```
The server maps this to `RAGRequest` and calls `RAGChain.run()`.

**Stage 1 — Query processing (text track):**
```python
RAGRequest.query = "quarterly revenue chart Q3 2025"
# After process_query():
processed_query = "Q3 2025 quarterly revenue chart"
query_confidence = 0.88
action = "search"
```
The query processor canonicalizes and expands the query. The processed form is used for both text and visual search.

**Stage 2–5 — Text track (hybrid search, reranking):**
```python
# BGE-M3 embeds processed_query → 768-dim vector
# Weaviate hybrid search → top-10 text chunks
# BGE reranker → top-5 RankedResult
text_results = [RankedResult(text="...", score=0.82, metadata={...}), ...]
```

**Stage 6 — Visual retrieval track:**

`RAGChain._run_visual_retrieval("Q3 2025 quarterly revenue chart", "acme")`:

Step 1 — `_ensure_visual_model()`: warm path, model already loaded.

Step 2 — `embed_text_query(model, processor, "Q3 2025 quarterly revenue chart")`:
```python
# processor.process_queries(["Q3 2025 quarterly revenue chart"])
# → tokenized inputs on GPU
# → model forward pass → (1, n_tokens, 128) tensor
# → mean pool dim=0 → (128,) vector
query_vector = [0.0123, -0.0456, ..., 0.0789]  # list[float], len=128
```

Step 3 — `search_visual(client, query_vector, limit=5, score_threshold=0.3, tenant_id="acme")`:
```python
# Weaviate near_vector on RAGVisualPages, target_vector="mean_vector"
# filter: tenant_id == "acme"
# Returns 3 objects (2 below threshold after score conversion):
page_records = [
    {"document_id": "abc-123", "page_number": 7, "source_key": "reports/q3_2025.pdf",
     "source_name": "Q3 2025 Report", "minio_key": "pages/abc-123/0007.jpg",
     "tenant_id": "acme", "total_pages": 42, "page_width_px": 1024, "page_height_px": 768,
     "score": 0.81},
    {"document_id": "abc-123", "page_number": 8, ..., "score": 0.74},
    {"document_id": "def-456", "page_number": 3, ..., "score": 0.61},
]
```

Step 4 — Presigned URL generation:
```python
# For each page_record:
url = get_page_image_url(minio_client, minio_key="pages/abc-123/0007.jpg")
# → "https://minio.internal:9000/rag-documents/pages/abc-123/0007.jpg?X-Amz-Signature=..."
```

Step 5 — Assemble `VisualPageResult` list:
```python
visual_results = [
    VisualPageResult(document_id="abc-123", page_number=7, source_key="reports/q3_2025.pdf",
                     source_name="Q3 2025 Report", score=0.81,
                     page_image_url="https://...", total_pages=42,
                     page_width_px=1024, page_height_px=768),
    # ... 2 more results
]
```

**Stage 7 — Response assembly:**
```python
RAGResponse(
    query="quarterly revenue chart Q3 2025",
    processed_query="Q3 2025 quarterly revenue chart",
    query_confidence=0.88,
    action="search",
    results=[...text chunks...],
    visual_results=[...3 VisualPageResult...],
)
```

**API response (JSON):**
```json
{
  "query": "quarterly revenue chart Q3 2025",
  "results": [...],
  "visual_results": [
    {
      "document_id": "abc-123",
      "page_number": 7,
      "source_name": "Q3 2025 Report",
      "score": 0.81,
      "page_image_url": "https://minio.internal:9000/...",
      "total_pages": 42,
      "page_width_px": 1024,
      "page_height_px": 768
    }
  ]
}
```

---

### Scenario 2: Visual retrieval disabled

**Input:** Same query, but `RAG_VISUAL_RETRIEVAL_ENABLED=false`.

At `RAGChain.__init__`, `self._visual_retrieval_enabled = False`. ColQwen2 is never loaded. The `_run_visual_retrieval` path in `run()` is never entered. The response is:

```python
RAGResponse(
    ...text results...,
    visual_results=None,  # not set
)
```

The JSON response has no `visual_results` key. Clients that don't expect visual results see an unchanged response.

---

### Scenario 3: ColQwen2 cold start on first visual query

**Input:** First visual query after server start with `RAG_VISUAL_RETRIEVAL_ENABLED=true`.

In `_run_visual_retrieval`:
1. `_ensure_visual_model()` is called. `self._visual_model is None` → cold path.
2. `ensure_colqwen_ready()` checks package availability.
3. `load_colqwen_model("vidore/colqwen2-v1.0")` loads from HuggingFace cache or downloads. Duration: 15–60 seconds. This blocks the request thread.
4. On success, `self._visual_model` and `self._visual_processor` are set. The observability span `visual_retrieval.model_load` captures the duration.
5. Subsequent queries hit the warm path (`if self._visual_model is not None: return`) — negligible overhead.

If `load_colqwen_model` fails (e.g., no GPU, CUDA OOM), `ColQwen2LoadError` propagates to `run()`. The caller should catch it and return text-only results.

---

### Scenario 4: Partial URL generation failure

**Input:** Visual search returns 3 pages. MinIO presigned URL generation fails for page 2 (e.g., transient network error).

In `_run_visual_retrieval`, the URL generation loop:
```python
for record in page_records:
    try:
        url = get_page_image_url(minio_client, minio_key=record["minio_key"])
    except Exception as exc:
        logger.warning("Failed to generate presigned URL for page %s/%d: %s — skipping page.",
                       record.get("document_id", "?"), record.get("page_number", 0), exc)
        continue
    results.append(VisualPageResult(..., page_image_url=url, ...))
```

Page 2 is skipped. The response carries `visual_results` with 2 entries (pages 1 and 3). The warning is logged. No exception propagates.

---

## 5. Configuration Reference

All parameters are environment variables read at module import time in `config/settings.py`.

### Visual Embedding (Ingestion-side)

| Parameter | Type | Default | Valid Range / Options | Effect |
|-----------|------|---------|----------------------|--------|
| `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING` | `bool` | `false` | `"true"`, `"1"`, `"yes"` / other | Master switch for ingestion-time visual embedding. Must be enabled during ingestion to populate `RAGVisualPages`. Independent of the retrieval-side enable flag. |
| `RAG_INGESTION_VISUAL_TARGET_COLLECTION` | `str` | `"RAGVisualPages"` | Any non-empty string | Weaviate collection name for visual page objects. Must match `RAG_INGESTION_VISUAL_TARGET_COLLECTION` used during ingestion and retrieval. |
| `RAG_INGESTION_COLQWEN_MODEL` | `str` | `"vidore/colqwen2-v1.0"` | HuggingFace model ID or local path | ColQwen2 model identifier. **Used for both ingestion-time embedding and retrieval-time query encoding.** The same model must be used for both — mismatched models produce vectors in different spaces, breaking retrieval. |
| `RAG_INGESTION_COLQWEN_BATCH_SIZE` | `int` | `4` | 1–32 (practical: 2–8 for 4 GB VRAM) | Number of page images per GPU forward pass during ingestion. Directly controls peak VRAM. Default of 4 is appropriate for the 4 GB VRAM budget (NFR-901). |
| `RAG_INGESTION_PAGE_IMAGE_QUALITY` | `int` | `85` | 1–95 | JPEG compression quality for stored page images. Higher values produce larger files with fewer compression artifacts. |
| `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION` | `int` | `1024` | 128–4096 (practical) | Maximum pixel dimension (width or height) when resizing page images before embedding. Larger values increase embedding quality and VRAM usage. |

### Visual Retrieval (Retrieval-side)

| Parameter | Type | Default | Valid Range / Options | Effect |
|-----------|------|---------|----------------------|--------|
| `RAG_VISUAL_RETRIEVAL_ENABLED` | `bool` | `false` | `"true"`, `"1"`, `"yes"` / other | Master switch for the visual retrieval track. If false, ColQwen2 is never loaded and `visual_results` is always `None`. Zero cost when disabled. |
| `RAG_VISUAL_RETRIEVAL_LIMIT` | `int` | `5` | 1–50 (clamped with warning) | Maximum number of visual page results returned from Weaviate. Results are ordered by descending cosine similarity before the limit is applied. |
| `RAG_VISUAL_RETRIEVAL_MIN_SCORE` | `float` | `0.3` | 0.0–1.0 (validated at startup) | Minimum cosine similarity threshold. Pages with `score < MIN_SCORE` are discarded after Weaviate returns results. Raise to improve precision; lower to increase recall. |
| `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` | `int` | `3600` | 60–86400 (validated at startup) | Presigned MinIO URL expiry duration in seconds. URLs in the response are valid for this duration from the time of the query. |
| `RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS` | `int` | `10000` | 100–300000 | Stage time budget in milliseconds for the entire visual retrieval stage (model encode + Weaviate search + URL generation). Can be overridden per-request via `stage_budget_overrides.visual_retrieval`. |

> **Note on model key reuse:** `RAG_INGESTION_COLQWEN_MODEL` is the single configuration key that controls the ColQwen2 model for both ingestion and retrieval. There is intentionally no separate `RAG_RETRIEVAL_COLQWEN_MODEL` key — using different models for ingestion and retrieval would produce vectors in different spaces and break retrieval accuracy.

---

## 6. Integration Contracts

### Caller → RAGChain

Callers interact with the visual retrieval pipeline exclusively through `RAGChain.run()`.

**Entry point:**
```python
response = rag_chain.run(
    query="<user query text>",
    tenant_id="<optional tenant>",       # used for visual collection filtering
    stage_budget_overrides={"visual_retrieval": 15000},  # optional ms override
    # ... other existing parameters unchanged
)
```

**Input contract:**
- `query`: Non-empty string. Processed by `process_query` before visual encoding. The visual track uses the processed form.
- `tenant_id`: Optional string. When provided, only visual pages with matching `tenant_id` in Weaviate are returned.
- `stage_budget_overrides["visual_retrieval"]`: Optional int in [100, 300000] ms. Overrides `RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS` for this request only.

**Output contract:**
- `RAGResponse.visual_results`: `Optional[List[VisualPageResult]]`
  - `None` if visual retrieval is disabled or if the track raised an unhandled exception.
  - Non-empty `List[VisualPageResult]` if results were found, ordered by descending `score`.
  - Each `VisualPageResult` has: `document_id`, `page_number`, `source_key`, `source_name`, `score` (float, cosine similarity), `page_image_url` (presigned MinIO URL), `total_pages`, `page_width_px`, `page_height_px`.
  - `page_image_url` is valid for `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` from the time of the response.

### Caller → API Server

**Entry point:** `POST /query`

**Request shape:** `QueryRequest` with optional `stage_budget_overrides` including `"visual_retrieval"` key.

**Response shape:** `QueryResponse.visual_results: Optional[list[VisualPageResultResponse]]`
- `None` (omitted from JSON) when visual retrieval is disabled.
- List of `VisualPageResultResponse` objects when visual results are present.
- `VisualPageResultResponse` carries the same nine fields as `VisualPageResult`, except `tenant_id` is excluded (internal routing field not exposed in API responses).

### External Dependency Contracts

| Dependency | Assumption | Failure Mode |
|------------|------------|--------------|
| ColQwen2 model (`vidore/colqwen2-v1.0`) | Accessible from HuggingFace Hub or local cache at `~/.cache/huggingface/`. CUDA-capable GPU with ≥4 GB VRAM available. | `ColQwen2LoadError` on first visual query. Visual track unavailable until resolved. |
| Weaviate (`RAGVisualPages` collection) | Collection exists and was created by `ensure_visual_collection`. Contains pages embedded by the ingestion pipeline with the same ColQwen2 model. | `WeaviateQueryError` or empty results if collection is absent or empty. |
| MinIO (page images at `pages/{document_id}/{page:04d}.jpg`) | Objects exist for all `minio_key` values returned by Weaviate. MinIO client credentials (`MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`) are valid. | Presigned URL generated even for non-existent objects; client receives 404 when accessing the URL. |
| `colpali-engine` and `bitsandbytes` Python packages | Installed in the environment (under `rag[visual]` extras). | `ColQwen2LoadError` with install instructions from `ensure_colqwen_ready`. |

---

## 7. Operational Notes

### Enabling Visual Retrieval

To enable visual retrieval in a deployment:

1. **Ingest documents with visual embedding enabled:**
   ```bash
   RAG_INGESTION_ENABLE_VISUAL_EMBEDDING=true \
   RAG_INGESTION_COLQWEN_MODEL=vidore/colqwen2-v1.0 \
   python ingest.py
   ```
   This populates the `RAGVisualPages` Weaviate collection and stores page images in MinIO under `pages/`.

2. **Enable visual retrieval in the server:**
   ```bash
   RAG_VISUAL_RETRIEVAL_ENABLED=true \
   RAG_INGESTION_COLQWEN_MODEL=vidore/colqwen2-v1.0 \
   python server/api.py
   ```
   Config validation runs at startup. If `RAG_INGESTION_VISUAL_TARGET_COLLECTION` is empty or score/expiry values are out of range, the server will fail to start with a descriptive `ValueError`.

3. **First request triggers model load.** The ColQwen2 model is loaded on the first visual query. Expect 15–60 seconds of latency on the first visual query (cold start). Subsequent queries use the warm path.

### Monitoring Signals

- `visual_retrieval.model_load` span: appears once per process lifetime, duration indicates cold-start time. Duration > 120 seconds suggests network issues fetching the model.
- `visual_retrieval.text_encode` span: duration of GPU inference for query encoding. Expected: 0.1–2 seconds.
- `visual_retrieval.search` span + attribute `result_count`: number of pages returned by Weaviate before threshold filtering. If `result_count=0` consistently, the collection may be empty or the `MIN_SCORE` threshold may be too high.
- `visual_retrieval.presigned_urls` span: duration of URL generation for all results. Each URL generation is a lightweight MinIO API call.
- `WARNING` log `"Failed to generate presigned URL for page"`: per-page URL generation failure. Occasional failures are acceptable. Sustained failures suggest MinIO connectivity issues.

### Failure Mode Debug Paths

**"Visual results always None despite RAG_VISUAL_RETRIEVAL_ENABLED=true"**
1. Check server startup logs for `ValueError` from `validate_visual_retrieval_config` (startup may have failed silently).
2. Check for `ColQwen2LoadError` in server logs — model may have failed to load on first query.
3. Verify `RAGVisualPages` collection exists in Weaviate with `GET /v1/schema`.

**"Visual results always empty (empty list)"**
1. Check if `RAGVisualPages` collection has objects: Weaviate `GET /v1/objects?class=RAGVisualPages&limit=1`.
2. Lower `RAG_VISUAL_RETRIEVAL_MIN_SCORE` to `0.1` to verify that results exist below the threshold.
3. Verify that ingestion was run with the same `RAG_INGESTION_COLQWEN_MODEL` value as retrieval.

**"Page images return 404 despite valid presigned URLs"**
1. Check MinIO bucket for `pages/{document_id}/` prefix: `mc ls minio/rag-documents/pages/`.
2. If objects are missing, re-run ingestion with `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING=true`.
3. Check URL expiry: if `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` is very short (< 300), URLs may expire before the client accesses them.

---

## 8. Known Limitations

**VRAM constraint — single GPU deployment only**

The ColQwen2 model requires ~3 GB VRAM at 4-bit quantization. In a multi-worker server deployment (e.g., `RAG_WORKER_CONCURRENCY=4`), each worker loads ColQwen2 independently, consuming N × 3 GB. On a GPU with 6 GB VRAM, only one worker can run ColQwen2 at a time. The BGE-M3 model (text embedding) consumes an additional ~1–2 GB. Running both workers simultaneously on a 6 GB GPU will cause CUDA OOM.

**Mitigation:** Set `RAG_WORKER_CONCURRENCY=1` for visual-enabled workers, or run visual queries on a dedicated worker process.

---

**ColQwen2 cold start latency**

The first visual query after server startup triggers ColQwen2 model loading. This can take 15–60 seconds depending on whether the model is already in the HuggingFace cache and GPU initialization time. This latency blocks the first visual query's response.

**Mitigation:** Implement a startup warm-up request (a synthetic visual query that triggers model loading before real traffic arrives). This is not currently implemented.

---

**Thread safety of ColQwen2 model**

`self._visual_model` and `self._visual_processor` are instance attributes on `RAGChain`. In a single-threaded server, lazy loading is safe. In a multi-threaded server where multiple requests could trigger `_ensure_visual_model` concurrently, there is a potential race condition: two threads might both observe `self._visual_model is None` and both attempt `load_colqwen_model`, loading the model twice and wasting VRAM.

**Mitigation:** The current implementation does not use a lock. For multi-threaded servers, add a `threading.Lock` around the model load block in `_ensure_visual_model`.

---

**No result re-ranking for visual results**

Visual results are returned in descending cosine similarity order from Weaviate. There is no cross-modal or hybrid re-ranking step that would combine text and visual signals. A page that scores 0.90 visually but 0.10 textually appears in `visual_results` without reconciliation against text results that may reference the same page.

---

**Presigned URL expiry**

Presigned MinIO URLs expire after `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` (default: 3600 seconds). If a client caches a `QueryResponse` and accesses `page_image_url` after expiry, it receives a 403 from MinIO. Clients must re-query to obtain fresh URLs.

---

**Schema mismatch detection absent**

`ensure_visual_collection` is idempotent but does not validate schema. If the `RAGVisualPages` collection was created with a different embedding dimension (e.g., 256 instead of 128), the function returns without error. Attempts to insert 128-dim vectors or query with a 128-dim vector will fail at the Weaviate level with a shape error.

---

**`patch_vectors` stored but not used for retrieval**

Patch vectors are stored in Weaviate as serialized JSON TEXT (field `patch_vectors`). They are never returned by `visual_search` (excluded from `return_properties`). MaxSim late-interaction re-scoring using patch vectors is not implemented. The data is retained for future use.

---

## 9. Extension Guide

### Adding a second visual search collection (e.g., per-tenant isolation)

1. **Configuration:** Add a new env var (e.g., `RAG_VISUAL_TARGET_COLLECTION_TENANT_X`) or use a naming convention like `RAGVisualPages_tenantX`.
2. **Collection creation:** Call `ensure_visual_collection(client, collection="RAGVisualPages_tenantX")` during setup. The function is parameterized and creates any named collection with the correct schema.
3. **Ingestion:** Pass `target_collection="RAGVisualPages_tenantX"` to the visual embedding node.
4. **Retrieval:** Pass `collection="RAGVisualPages_tenantX"` to `search_visual(...)` in `_run_visual_retrieval`.

No modifications to core files are required — all visual store functions accept a `collection` parameter.

---

### Swapping the visual embedding model (replacing ColQwen2)

1. **Adapter:** Add a new file `src/ingest/support/<model_name>.py` following the same four-function lifecycle as `colqwen.py`: `ensure_ready`, `load_model`, `embed_page_images`, `embed_text_query`.
2. **`embed_text_query` contract:** Must return `list[float]` of the correct dimensionality. The output dimensionality must match the dimensionality configured in `ensure_visual_collection`.
3. **Weaviate collection:** If the new model produces a different dimensionality, the `RAGVisualPages` collection must be dropped and re-created with the new dimension value. This requires re-ingesting all documents.
4. **Settings:** Add a new config key for the model name (or reuse `RAG_INGESTION_COLQWEN_MODEL`).
5. **RAGChain:** Update `_ensure_visual_model` and `_run_visual_retrieval` to import and call the new adapter.
6. **Pitfall:** The ingestion-side model and retrieval-side model must be the same. Using different models produces vectors in different spaces and breaks retrieval. Update both simultaneously.

---

### Adding a new vector store backend with visual support

1. **ABC:** Implement all four abstract visual methods in your new backend class (`ensure_visual_collection`, `add_visual_documents`, `delete_visual_by_source_key`, `search_visual`). The method signatures are in `src/vector_db/backend.py`.
2. **`_get_vector_backend()`:** Add a new branch in `src/vector_db/__init__.py` for the new `VECTOR_DB_BACKEND` value.
3. **`search_visual` contract:** Must return `list[dict]` with the same keys returned by `visual_store.visual_search`. Callers in `rag_chain.py` expect: `document_id`, `page_number`, `source_key`, `source_name`, `minio_key`, `tenant_id`, `total_pages`, `page_width_px`, `page_height_px`, `score`.
4. **Pitfall:** Do not modify existing methods on `VectorBackend` to add visual support. New methods only — this is the NFR-909 contract.

---

### Adding MaxSim re-ranking using patch vectors

1. **Fetch patch vectors:** After `search_visual` returns page records, for each result fetch the full Weaviate object including the `patch_vectors` field via a separate `get` query.
2. **Deserialize:** Parse `patch_vectors` JSON TEXT back to `list[list[float]]`.
3. **MaxSim score:** For each (query token vector, page patch vector) pair, compute dot products and take the max per query token. Sum across query tokens to get the MaxSim score.
4. **Re-rank:** Replace `score` in the result with the MaxSim score, re-sort descending.
5. **Pitfall:** MaxSim requires the raw query token-level vectors (shape `[n_tokens, 128]`), not the mean-pooled 128-dim vector used for ANN search. Modify `embed_text_query` to return both the mean vector (for ANN) and the raw token vectors (for MaxSim re-scoring).

---

## 10. Appendix: Requirement Coverage

| Spec Requirement | Module Section Covering It |
|------------------|-----------------------------|
| FR-101 — Visual retrieval enabled via config flag | `config/settings.py` — `RAG_VISUAL_RETRIEVAL_ENABLED` |
| FR-103 — Model identifier configurable | `config/settings.py` — `RAG_INGESTION_COLQWEN_MODEL` |
| FR-105 — Score threshold configurable | `config/settings.py` — `RAG_VISUAL_RETRIEVAL_MIN_SCORE` |
| FR-107 — URL expiry configurable | `config/settings.py` — `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` |
| FR-109 — Same model for ingestion and retrieval | `config/settings.py` — single shared `RAG_INGESTION_COLQWEN_MODEL` key |
| FR-111 — Fail-fast config validation at startup | `rag_chain.py` — `validate_visual_retrieval_config()` at `__init__` |
| FR-201 — Mean-pool text query to 128-dim vector | `colqwen.py` — `embed_text_query` |
| FR-203 — Use `process_queries` for text encoding | `colqwen.py` — `embed_text_query` |
| FR-205 — Reject empty/whitespace query | `colqwen.py` — `embed_text_query` input validation |
| FR-207 — Reject None model/processor | `colqwen.py` — `embed_text_query` guard |
| FR-301 — 4-bit quantization for VRAM budget | `colqwen.py` — `load_colqwen_model` BitsAndBytesConfig |
| FR-302 — 1-indexed page numbers | `colqwen.py` — `ColQwen2PageEmbedding.page_number` |
| FR-303 — 128-dim mean-pooled vector | `colqwen.py` — `embed_page_images` mean pooling |
| FR-304 — Patch vectors JSON-serializable | `colqwen.py` — `.tolist()` conversion |
| FR-305 — GPU memory release | `colqwen.py` — `unload_colqwen_model` |
| FR-306 — Progress logging at 10% intervals | `colqwen.py` — `embed_page_images` |
| FR-307 — Per-page failure isolation | `colqwen.py` — `embed_page_images` per-page try/except |
| FR-303 (search) — Score threshold filtering | `visual_store.py` — `visual_search` post-filter |
| FR-305 (search) — Tenant filter | `visual_store.py` — `visual_search` Filter.by_property |
| FR-309 — Near-vector search on mean_vector | `visual_store.py` — `visual_search` near_vector query |
| FR-311 — Exclude patch_vectors from results | `visual_store.py` — `visual_search` return_properties |
| FR-313 — `search_visual` ABC method | `backend.py` + `__init__.py` — `search_visual` |
| FR-401 — Key pattern `pages/{doc_id}/{page:04d}.jpg` | `minio/store.py` — `store_page_images` |
| FR-402 — Configurable JPEG quality | `minio/store.py` — `store_page_images` quality param |
| FR-403 — Configurable URL expiry with default | `minio/store.py` — `get_page_image_url` sentinel defaults |
| FR-404 — Bulk delete page images | `minio/store.py` — `delete_page_images` |
| FR-501 — `VisualPageResult` fields | `retrieval/common/schemas.py` — `VisualPageResult` dataclass |
| FR-502 — Idempotent visual collection creation | `visual_store.py` — `ensure_visual_collection` |
| FR-503 — `RAGResponse.visual_results` field | `retrieval/common/schemas.py` — `RAGResponse` |
| FR-504 — Named vector `mean_vector`, 128-dim, HNSW, cosine | `visual_store.py` — `ensure_visual_collection` |
| FR-505 — `patch_vectors` skip vectorization | `visual_store.py` — `ensure_visual_collection` Property |
| FR-506 — Delete by source_key | `visual_store.py` — `delete_visual_by_source_key` |
| FR-507 — Batch insert visual documents | `visual_store.py` — `add_visual_documents` |
| FR-601 — Visual track gated by config | `rag_chain.py` — `self._visual_retrieval_enabled` check |
| FR-603 — Lazy model loading | `rag_chain.py` — `_ensure_visual_model` |
| FR-605 — Encode processed query | `rag_chain.py` — `_run_visual_retrieval` uses `processed_query` |
| FR-607 — Presigned URLs per result | `rag_chain.py` — `_run_visual_retrieval` URL generation loop |
| FR-609 — Search visual collection | `rag_chain.py` — `_run_visual_retrieval` calls `search_visual` |
| FR-611 — Attach results to RAGResponse | `rag_chain.py` — `response.visual_results = visual_results` |
| FR-613 — Unload model on close | `rag_chain.py` — `close()` calls `unload_colqwen_model` |
| FR-617 — Stage budget for visual retrieval | `rag_chain.py` + `config/settings.py` — `RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS` |
| FR-701 — `VisualPageResultResponse` fields | `server/schemas.py` — `VisualPageResultResponse` |
| FR-703 — `QueryResponse.visual_results` field | `server/schemas.py` — `QueryResponse.visual_results` |
| NFR-901 — Peak VRAM ≤ 4 GB | `colqwen.py` — 4-bit quantization |
| NFR-905 — Per-page isolation in retrieval | `rag_chain.py` — per-page URL generation try/except |
| NFR-906 — Optional visual dependencies | `colqwen.py` — deferred imports under `rag[visual]` |
| NFR-909 — No modification to existing ABC methods | `backend.py` — new abstract methods only |
