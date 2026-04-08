### `src/ingest/embedding/nodes/visual_embedding.py` — Visual Embedding Node

**Purpose:**

This is the primary LangGraph node for the visual (page-image) embedding track. It extracts
per-page images from a `DoclingDocument`, resizes them, stores them as JPEG objects in MinIO,
runs ColQwen2 batch inference to produce 128-dim patch and mean-pooled vectors, and inserts
the resulting objects into a dedicated Weaviate collection (`RAGVisualPages` by default). It is
positioned between `embedding_storage_node` and `knowledge_graph_storage_node` in the
Embedding Pipeline DAG (FR-601, FR-604). The node owns the entire visual lifecycle for a single
ingestion run and returns a strict partial-state update that never touches any text-track fields
(FR-803).

---

**How it works:**

The public entry point is `visual_embedding_node(state)`. All heavy work is delegated to the
private `_run_visual_embedding` helper so that the outer function stays thin and readable.

**Step 1 — Short-circuit checks (FR-603, NFR-903)**

Before any I/O or model load, the node checks two gating conditions. If either fires it returns
immediately with `visual_stored_count=0` and `page_images=None`, guaranteeing zero cost for
pipelines that do not use visual embedding:

```python
# Short-circuit 1: config flag
if not config.enable_visual_embedding:
    return {"visual_stored_count": 0, "page_images": None,
            "processing_log": append_processing_log(state, "visual_embedding:skipped:disabled")}

# Short-circuit 2: no docling document in state
docling_document = state.get("docling_document")
if docling_document is None:
    return {"visual_stored_count": 0, "page_images": None,
            "processing_log": append_processing_log(state, "visual_embedding:skipped:no_docling_document")}
```

A third implicit short-circuit fires inside `_run_visual_embedding` when `_extract_page_images`
returns an empty list — logged as `visual_embedding:skipped:no_pages`.

**Step 2 — Page image extraction (FR-201 through FR-205)**

Extraction uses a two-path strategy implemented in `_extract_page_images`:

- **Primary path (state `page_images`):** When Docling parsing ran with
  `generate_page_images=True` (enabled automatically when `enable_visual_embedding=True` via the
  `IngestionConfig.generate_page_images` derived property), the parsing node pre-populates
  `state["page_images"]` with a list of already-rendered PIL images. The visual node iterates
  this list, converts each image to RGB, and assigns 1-based page numbers in iteration order.

- **Fallback path (`DoclingDocument.pages`):** When `state["page_images"]` is absent or empty,
  the node reads the `DoclingDocument.pages` dictionary (keyed by page index). Each `PageItem`
  that has a non-None `.image` attribute is extracted; the 0-indexed `page_no` field is
  incremented to produce a 1-based page number. Per-page failures are caught and logged as
  warnings so one bad page does not abort the rest (FR-801).

```python
def _extract_page_images(state, docling_document):
    state_images = state.get("page_images")
    if state_images:
        # Primary path: pre-rendered images in state
        result = []
        for idx, img in enumerate(state_images, start=1):
            pil_img = _to_rgb(img)
            w, h = pil_img.size
            result.append((idx, pil_img, w, h))
        return result
    # Fallback: extract from DoclingDocument.pages
    return _extract_from_docling(docling_document)
```

The return type for both paths is `list[tuple[int, PIL.Image, int, int]]` — a 4-tuple of
`(1-indexed page_number, RGB PIL.Image, original_width_px, original_height_px)`. The original
pixel dimensions are preserved in the tuple so they can be written to Weaviate even after
resizing.

**Step 3 — Aspect-ratio-preserving resize (FR-202, FR-203)**

`_resize_page_images` computes a uniform scale factor so that `max(width, height)` does not
exceed `config.page_image_max_dimension` (default 1024 px). The original dimensions are passed
through unchanged in the tuple — only the embedded `PIL.Image` is replaced with the resized
version. If the longer edge is already within the limit, or if `max_dimension <= 0`, the image
is returned as-is:

```python
longer_edge = max(orig_w, orig_h)
if longer_edge > max_dimension and longer_edge > 0:
    scale = max_dimension / longer_edge
    new_w = max(1, int(orig_w * scale))
    new_h = max(1, int(orig_h * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)
```

`Image.LANCZOS` is used for high-quality downsampling. A per-page exception guard logs a
warning and keeps the original if resize fails, allowing the pipeline to continue.

**Step 4 — Pre-storage cleanup (FR-404, FR-405)**

When running in update mode (re-ingesting an existing document), stale visual data from the
previous run must be removed before writing new data. The node issues two delete calls — one
against MinIO and one against Weaviate — both wrapped in separate `try/except` blocks that log
warnings on failure without aborting the node:

- MinIO: `delete_page_images(minio_client, document_id)` — removes all objects matching the
  prefix `pages/{document_id}/`.
- Weaviate: `delete_visual_by_source_key(weaviate_client, source_key, visual_target_collection)`
  — deletes all `RAGVisualPages` objects whose `source_key` property matches. This is a bulk
  delete by filter, not by Weaviate UUID.

Cleanup is unconditional (not gated on `update_mode`) because it is idempotent — deleting
nothing when the document is new has no side effects.

**Step 5 — MinIO page image storage (FR-401, FR-402, FR-403)**

`store_page_images` is called with the list of `(page_number, PIL.Image)` tuples and the
configured JPEG quality (default 85). It writes each page to MinIO under the key
`pages/{document_id}/{page_number:04d}.jpg`. Each successful upload appends the key to a
returned list. The node parses the returned keys to build a `dict[int, str]` mapping
`page_number → minio_key`, which is later embedded in the Weaviate object so that a retrieval
client can fetch the raw page image. Per-page upload failures are isolated inside
`store_page_images` and logged as warnings (FR-403).

**Step 6 — ColQwen2 load, batch embed, and guaranteed unload (FR-301 through FR-307)**

This is the most resource-intensive step. The pattern is structured so that the model is
**always** unloaded in a `finally` block regardless of inference success or failure:

```python
try:
    ensure_colqwen_ready()          # checks colpali-engine + bitsandbytes importable
except ColQwen2LoadError as exc:
    errors.append(f"visual_embedding:colqwen_load:{exc}")
    return {"visual_stored_count": 0, "page_images": None, "errors": errors,
            "processing_log": append_processing_log(state, "visual_embedding:error:colqwen_load")}

try:
    model, processor = load_colqwen_model(config.colqwen_model_name)
except ColQwen2LoadError as exc:
    errors.append(f"visual_embedding:colqwen_load:{exc}")
    return {"visual_stored_count": 0, "page_images": None, "errors": errors,
            "processing_log": append_processing_log(state, "visual_embedding:error:colqwen_load")}

try:
    embeddings = embed_page_images(
        model, processor, resized_images, config.colqwen_batch_size,
        page_numbers=page_numbers
    )
except VisualEmbeddingError as exc:
    errors.append(f"visual_embedding:inference:{exc}")
finally:
    if model is not None:
        unload_colqwen_model(model)   # always executes — frees GPU VRAM
```

`ensure_colqwen_ready()` verifies that `colpali-engine` and `bitsandbytes` are importable
before attempting to allocate GPU memory; this prevents obscure CUDA errors when optional
dependencies are missing. `load_colqwen_model` applies 4-bit BitsAndBytes quantisation
(`load_in_4bit=True`, `bnb_4bit_compute_dtype=float16`), keeping peak VRAM at or below 4 GB
(NFR-901). `embed_page_images` processes images in batches of `colqwen_batch_size` (default 4);
per-batch and per-page failures skip the affected pages without aborting the run (FR-307).
`unload_colqwen_model` calls `del model`, `torch.cuda.empty_cache()`, and `gc.collect()` to
return VRAM to pre-load levels (FR-305).

Each `ColQwen2PageEmbedding` result carries:
- `page_number` (1-indexed, FR-302)
- `mean_vector` — 128-dim float32 arithmetic mean across all patches (FR-303)
- `patch_vectors` — raw `(n_patches, 128)` float32 tensor serialised as `list[list[float]]`
  for JSON storage (FR-304)
- `patch_count`

**Step 7 — Weaviate visual object insertion (FR-501 through FR-507)**

The node calls `ensure_visual_collection` to idempotently create the `RAGVisualPages` collection
(128-dim HNSW cosine named vector `mean_vector`, 11 scalar properties), then constructs one
document dict per `ColQwen2PageEmbedding` and batch-inserts via `add_visual_documents`:

```python
documents.append({
    "document_id": document_id,
    "page_number": pn,
    "source_key": source_key,
    "source_uri": state.get("source_uri", ""),
    "source_name": state.get("source_name", ""),
    "tenant_id": "",
    "total_pages": total_pages,
    "page_width_px": orig_w,        # original pre-resize dimensions
    "page_height_px": orig_h,
    "minio_key": minio_key_map.get(pn, ""),
    "patch_vectors": json.dumps(emb.patch_vectors),   # JSON text, skip_vectorization=True
    "mean_vector": emb.mean_vector,                   # named vector for ANN search
})
visual_stored_count = add_visual_documents(weaviate_client, documents, config.visual_target_collection)
```

`add_visual_documents` uses Weaviate's dynamic batch API; `mean_vector` is passed as the named
vector and all remaining keys become scalar properties. The function returns the count of
successfully inserted objects (total minus `failed_objects`). Any exception during this block is
caught and appended to `errors` with prefix `visual_embedding:weaviate:`.

**Step 8 — Processing log (FR-701 through FR-705)**

Five timestamped entries are appended to `state["processing_log"]` in sequence:

| Entry | Description |
|-------|-------------|
| `visual_embedding:pages_extracted:<N>` | Pages found after image extraction |
| `visual_embedding:pages_stored_minio:<N>` | Pages successfully uploaded to MinIO |
| `visual_embedding:pages_embedded:<N>` | Pages that produced ColQwen2 embeddings |
| `visual_embedding:pages_indexed:<N>` | Pages inserted into Weaviate |
| `visual_embedding:elapsed_s:<F>` | Wall-clock time for the entire node in seconds |

The `append_processing_log` helper also emits the message to the stage logger when
`config.verbose_stage_logs` is `True`.

**Step 9 — Partial state update (FR-803, FR-606)**

The return dict contains exactly the fields the visual node owns. Text-track fields
(`stored_count`, `chunks`, `enriched_chunks`, `raw_text`, `cleaned_text`,
`refactored_text`, `metadata_summary`, `metadata_keywords`, `cross_references`,
`kg_triples`) are **never written**. `page_images` is explicitly set to `None` to
free the PIL objects from the LangGraph state (FR-606):

```python
result = {
    "visual_stored_count": visual_stored_count,
    "page_images": None,
    "processing_log": processing_log,
}
if errors and errors != list(state.get("errors") or []):
    result["errors"] = errors
return result
```

The node only writes `errors` when new errors were accumulated — it does not clobber the
existing error list with an empty list on success.

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Dual-path image extraction (state `page_images` first, then `DoclingDocument.pages` fallback) | Single path through `DoclingDocument.pages` always | Docling's `generate_page_images=True` pre-renders images at parse time; consuming them from state avoids a second parse pass and re-render, which is expensive for large PDFs. The fallback exists for back-compat with pipeline configurations where `persist_docling_document=True` but `generate_page_images` was not set. |
| ColQwen2 loaded and unloaded per document inside the node | Load once at pipeline startup and hold resident | Holding a 4-bit quantised model resident throughout a multi-document ingestion run would exhaust VRAM when other GPU workloads (e.g., VLM enrichment) run in the same process. Per-document load/unload keeps peak VRAM bounded at the cost of model load overhead per run (~seconds). |
| `finally` block for model unload (not `try/except/else`) | `try/except` with unload in each branch | A `finally` block is the only pattern that guarantees unload whether inference succeeds, raises `VisualEmbeddingError`, or encounters an unexpected exception. Duplicating the unload call in each exception branch is fragile and was rejected. |
| Original dimensions stored in Weaviate despite resize | Store post-resize dimensions | The Weaviate object is a content record for the page, not just the stored image. Retrieval clients need the original document page size for layout-aware applications (e.g., bounding box mapping). The MinIO JPEG already encodes the resized dimensions; keeping originals in Weaviate preserves the metadata. |
| `patch_vectors` stored as JSON `TEXT`, not as a second named vector | Second named vector for patch embeddings | Weaviate named vectors are optimised for ANN queries; multi-vector late interaction (ColBERT-style) over `n_patches × 128` dimensions requires custom scoring that Weaviate does not natively expose. Storing patches as JSON text preserves them for future retrieval implementations without complicating the collection schema today. |
| Pre-cleanup on every run, not only in `update_mode` | Gate cleanup on `config.update_mode` | The node does not own the decision of whether a document is new or updated — that is the orchestrator's job. Making cleanup unconditional means the node is idempotent by construction: re-running it on any document produces the same final state regardless of history. |
| Top-level `try/except Exception` wrapping `_run_visual_embedding` | Let unhandled errors propagate | The visual track must be isolated from the text track. An unhandled exception in visual embedding must not abort the pipeline and lose the already-stored text chunks. The outer guard catches everything, logs it, and returns a zero-result update so the pipeline continues to `knowledge_graph_storage_node`. |
| `ensure_colqwen_ready()` as a separate pre-flight check before `load_colqwen_model` | Let `load_colqwen_model` raise for missing deps | `ensure_colqwen_ready` raises `ColQwen2LoadError` with an explicit `pip install` command message before GPU allocation is attempted. This surfaces the missing-dependency problem clearly rather than burying it inside a CUDA import traceback. |

---

**Configuration:**

All parameters are read from `IngestionConfig` (populated from `config/settings.py` environment
variables). None have side-effects on text-track behavior.

| Parameter | Env Var | Type | Default | Effect |
|-----------|---------|------|---------|--------|
| `enable_visual_embedding` | `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING` | `bool` | `False` | Master switch. `False` → node short-circuits immediately with zero cost (NFR-903). Also controls `IngestionConfig.generate_page_images` which tells the Docling parsing node to pre-render page images. |
| `visual_target_collection` | `RAG_INGESTION_VISUAL_TARGET_COLLECTION` | `str` | `"RAGVisualPages"` | Weaviate collection name for visual page objects. Collection is created idempotently on first use. |
| `colqwen_model_name` | `RAG_INGESTION_COLQWEN_MODEL` | `str` | `"vidore/colqwen2-v1.0"` | HuggingFace model identifier passed to `ColQwen2.from_pretrained`. Must be a ColQwen2-compatible checkpoint. |
| `colqwen_batch_size` | `RAG_INGESTION_COLQWEN_BATCH_SIZE` | `int` | `4` | Images per ColQwen2 forward pass. Larger values increase throughput but raise peak VRAM. Valid range: 1–32. |
| `page_image_quality` | `RAG_INGESTION_PAGE_IMAGE_QUALITY` | `int` | `85` | JPEG compression quality for MinIO uploads. Higher values reduce compression artifacts at the cost of storage size. Valid range: 1–100. |
| `page_image_max_dimension` | `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION` | `int` | `1024` | Maximum pixel length of the longer image edge after resize. Images already within this bound are not resized. Valid range: 256–4096. |

---

**Error behavior:**

The node defines three distinct error severity levels, with different outcomes for each.

**Level 1 — Fatal: `ColQwen2LoadError` (no retry, immediate return)**

Raised by `ensure_colqwen_ready()` when `colpali-engine` or `bitsandbytes` are not importable,
or by `load_colqwen_model()` when the model fails to load from HuggingFace or CUDA. When caught,
the node returns immediately with `visual_stored_count=0`, no Weaviate inserts, and the error
string appended to `state["errors"]` under the key prefix `visual_embedding:colqwen_load:`.
No model unload is needed because the model reference was never successfully assigned. The
text track is completely unaffected.

**Level 2 — Non-fatal: `VisualEmbeddingError` during batch inference**

Raised by `embed_page_images` when the entire batch or an individual page fails during the
forward pass or tensor extraction. The exception is caught in the `except VisualEmbeddingError`
clause inside the `try/finally` block. The `finally` still executes, unloading the model. The
`embeddings` list will be shorter than the page count (failed pages are omitted, not set to
`None`). The Weaviate insert proceeds with whatever embeddings were successfully produced.
The error is recorded in `state["errors"]` under prefix `visual_embedding:inference:`.

**Level 3 — Partial: Weaviate batch insert failure**

Weaviate errors are caught by the outer `except Exception` inside the Weaviate insertion block
and appended to `errors` under prefix `visual_embedding:weaviate:`. The `visual_stored_count`
returned may be less than `len(embeddings)` if some objects in the dynamic batch fail.
`add_visual_documents` itself reports `len(documents) - failed_objects` so partial results are
counted correctly.

**Level 4 — Unhandled: top-level catch-all**

Any exception not caught by the inner handlers is caught by the outer `try/except Exception`
wrapping `_run_visual_embedding`. The node returns `visual_stored_count=0`, appends
`visual_embedding:error:unhandled` to the processing log, and logs the full traceback at
`ERROR` level. The pipeline continues to the next node.

**Invariant across all error levels:** `stored_count`, `chunks`, `enriched_chunks`, and all
other text-track state fields are never set or overwritten by this node (FR-803). The visual
track's failure modes are fully isolated from the text embedding result.
