### Integration Test Specification

---

#### Scenario 1: Happy Path — 10-Page PDF, Visual Enabled

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

`ensure_visual_collection(weaviate_client, collection="RAGVisualPages")` called. Mock `exists` returns `False` on first call → `create` called. Returns `True` on subsequent checks.

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

#### Scenario 2: Disabled Path — Zero-Overhead Short-Circuit

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

#### Scenario 3: Partial Failure — Some Pages Fail Inference

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
