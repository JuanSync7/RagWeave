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
- **`model.eval()` side effects:** Verifying `model.eval()` was called requires a mock; the behavioral impact of eval mode is not directly testable without real inference comparisons.

---

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.
