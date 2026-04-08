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
