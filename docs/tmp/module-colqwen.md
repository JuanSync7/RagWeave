### `src/ingest/support/colqwen.py` — ColQwen2 Model Adapter

**Purpose:**

This module is a minimal, lifecycle-complete adapter around the ColQwen2 vision-language model. Its sole responsibility is to accept a list of PIL-compatible page images, run them through ColQwen2 under 4-bit quantization, and return structured per-page embedding records containing both a 128-dim mean-pooled vector and the raw patch vectors. It also owns model load and GPU memory release, isolating all colpali-engine and bitsandbytes interactions from the rest of the ingestion pipeline. By concentrating these concerns in one module, the rest of the pipeline can treat visual embedding as a black-box operation invoked with a model handle and a list of images.

---

**How it works:**

The module enforces a strict four-phase lifecycle: dependency validation, model load, batch inference, and memory release. Callers are expected to follow this sequence.

**Phase 1 — Dependency validation (`ensure_colqwen_ready`)**

Before attempting any I/O or model load, `ensure_colqwen_ready` imports `colpali_engine` and `bitsandbytes` in isolation to confirm they are installed. If either is absent it raises `ColQwen2LoadError` with a precise `pip install` command (FR-806). This fast-fail check lets the calling node surface a clear error rather than a cryptic `ImportError` deep inside model initialization.

```python
def ensure_colqwen_ready() -> None:
    missing: list[str] = []
    try:
        import colpali_engine  # noqa
    except ImportError:
        missing.append("colpali-engine")
    try:
        import bitsandbytes  # noqa
    except ImportError:
        missing.append("bitsandbytes")
    if missing:
        raise ColQwen2LoadError(
            f"Required package(s) not installed: {', '.join(missing)}. "
            'Install with: pip install "rag[visual]" '
            "or: pip install colpali-engine bitsandbytes"
        )
```

**Phase 2 — Model load (`load_colqwen_model`)**

`load_colqwen_model(model_name)` loads ColQwen2 from a HuggingFace model identifier. It configures a `BitsAndBytesConfig` requesting 4-bit integer weights with float16 compute dtype (FR-301, NFR-902), passes `device_map="auto"` so PyTorch places layers across available devices automatically, then calls `model.eval()` to disable dropout and batch-norm training behaviour. The companion processor is loaded from the same model identifier. The function returns `(model, processor)` as an opaque pair; the caller is responsible for storing and passing them to subsequent phases.

Any failure at the torch/transformers import stage or at `from_pretrained` is wrapped in `ColQwen2LoadError`, marking the error as fatal (FR-802).

**Phase 3 — Batch inference (`embed_page_images`)**

`embed_page_images(model, processor, images, batch_size, *, page_numbers=None)` is the core embedding loop. It iterates over `images` in slices of `batch_size`, processes each slice through the ColQwen2 processor and model, then extracts per-page tensors. Progress is logged at ~10% intervals when the page count exceeds 10 (FR-306).

```python
for batch_start in range(0, n_pages, batch_size):
    batch_end = min(batch_start + batch_size, n_pages)
    batch_images = images[batch_start:batch_end]
    batch_page_numbers = page_numbers[batch_start:batch_end]

    # Pre-processing (may raise on malformed images — skip entire batch)
    try:
        batch_inputs = processor.process_images(batch_images)
        batch_inputs = {k: v.to(model.device) for k, v in batch_inputs.items()}
    except Exception as exc:
        logger.warning("Failed to process image batch (pages %s-%s): %s — skipping.",
                       batch_page_numbers[0], batch_page_numbers[-1], exc)
        continue

    # Inference inside torch.inference_mode (NFR-908, NFR-910)
    try:
        with torch.inference_mode():
            batch_output = model(**batch_inputs)
    except Exception as exc:
        logger.warning("Inference failed for batch (pages %s-%s): %s — skipping.",
                       batch_page_numbers[0], batch_page_numbers[-1], exc)
        continue

    # Tensor extraction — handles ColQwen2's two output shapes
    if hasattr(batch_output, "last_hidden_state"):
        batch_tensor = batch_output.last_hidden_state
    elif isinstance(batch_output, torch.Tensor):
        batch_tensor = batch_output
    else:
        batch_tensor = batch_output  # fallback for future ColQwen2 API changes

    # Per-page mean pooling and serialization
    for idx_in_batch, page_num in enumerate(batch_page_numbers):
        try:
            page_tensor = batch_tensor[idx_in_batch]          # shape: [patches, 128]
            mean_vector = page_tensor.float().mean(dim=0).cpu().tolist()   # FR-303
            patch_vectors = page_tensor.float().cpu().tolist()             # FR-304
            patch_count = page_tensor.shape[0]
            results.append(ColQwen2PageEmbedding(
                page_number=page_num,
                mean_vector=mean_vector,
                patch_vectors=patch_vectors,
                patch_count=patch_count,
            ))
        except Exception as exc:
            logger.warning("Failed to extract embedding for page %d: %s — skipping.", page_num, exc)
```

Mean pooling is performed along `dim=0` (the patch axis) to produce a single 128-dimensional vector per page (FR-303). Both the mean vector and the raw patch vectors are converted to plain Python `list[float]` via `.tolist()`, making them immediately JSON-serializable without further transformation (FR-304). Page numbers default to 1-indexed sequential integers if not supplied by the caller (FR-302).

**Phase 4 — Memory release (`unload_colqwen_model`)**

`unload_colqwen_model(model)` deletes the model reference, calls `torch.cuda.empty_cache()`, and triggers `gc.collect()` (FR-305). This three-step sequence is necessary because Python's garbage collector does not guarantee immediate deallocation of CUDA tensors; `empty_cache` returns fragmented but unreferenced allocations to the CUDA allocator pool, and `gc.collect` handles any cyclic references that delayed deallocation.

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|---|---|---|
| 4-bit quantization via BitsAndBytes (`load_in_4bit=True`, `bnb_4bit_compute_dtype=torch.float16`) | fp16 full precision; 8-bit quantization | 4-bit is the only configuration that keeps peak VRAM at or below the 4 GB budget (NFR-901) while preserving acceptable embedding quality. 8-bit still exceeds the budget for ColQwen2's parameter count. fp16 is out of budget entirely. |
| `torch.inference_mode()` context during forward pass | `torch.no_grad()` | `inference_mode` is a strict superset of `no_grad` — it additionally disables version counter tracking, reducing memory overhead and CPU overhead during batched inference (NFR-908, NFR-910). |
| Per-batch and per-page exception isolation (non-fatal `continue` / `logger.warning`) | Fail the entire embedding run on first error | Document pages are largely independent; one corrupt image or OOM spike on a single page should not abort the remainder of the document. Callers are responsible for detecting incomplete coverage from the returned list (FR-307). |
| Mean-pooling over patch axis to produce 128-dim vector | Max pooling; CLS token; concatenation | Mean pooling produces a translation-invariant summary of patch activations that is compact, consistent in dimension regardless of image resolution, and directly comparable across pages via cosine similarity (FR-303). |
| Optional dependencies declared under `rag[visual]` extras | Hard dependency in `pyproject.toml` | ColQwen2 and bitsandbytes carry large transitive dependency trees (CUDA toolkit, Triton). Marking them optional lets text-only deployments install without a GPU environment (NFR-906). |
| `device_map="auto"` | Explicit `model.to("cuda:0")` | `device_map="auto"` defers device placement to `accelerate`, which can shard layers across multiple GPUs or fall back to CPU offload automatically without per-deployment tuning. |
| Three-step unload: `del model` + `torch.cuda.empty_cache()` + `gc.collect()` | `del model` alone | CUDA tensors held by cyclic references are not freed by `del` alone. The combined sequence guarantees reclamation within the same process, avoiding VRAM exhaustion when the pipeline is reused for multiple documents (FR-305). |

---

**Configuration:**

These parameters are passed at call sites; the module contains no global state or class-level configuration.

| Parameter | Type | Default | Effect |
|---|---|---|---|
| `model_name` (`load_colqwen_model`) | `str` | — (required) | HuggingFace model identifier or local path. Passed to `ColQwen2.from_pretrained` and `ColQwen2Processor.from_pretrained`. Determines which ColQwen2 checkpoint is loaded. |
| `images` (`embed_page_images`) | `list[Any]` | — (required) | Ordered list of PIL-compatible page images. The list order determines default 1-indexed page numbering when `page_numbers` is not supplied. |
| `batch_size` (`embed_page_images`) | `int` | — (required) | Number of page images processed per forward pass. Directly controls peak VRAM usage. Larger values increase throughput but risk OOM on lower-memory GPUs. Recommended starting point: 4 pages per batch under the 4 GB VRAM budget (NFR-901). |
| `page_numbers` (`embed_page_images`) | `list[int] \| None` | `None` → 1-indexed sequential | Explicit 1-indexed page numbers to assign to each image position (FR-302). When `None`, defaults to `[1, 2, ..., len(images)]`. Must match `len(images)` if supplied. |

The 4-bit quantization dtype (`torch.float16`) and `device_map="auto"` are fixed inside `load_colqwen_model` and are not exposed as parameters; they are the only configuration that satisfies the VRAM budget constraint (NFR-901, NFR-902).

---

**Error behavior:**

The module defines two exception classes that signal fundamentally different failure modes.

**`ColQwen2LoadError` (fatal)**

Inherits from `VisualEmbeddingError`. Raised by `ensure_colqwen_ready` and `load_colqwen_model`. Indicates that the visual embedding subsystem cannot operate at all — either because required packages are absent or because the model checkpoint could not be loaded from disk or from HuggingFace Hub.

- `ensure_colqwen_ready` raises it when `colpali_engine` or `bitsandbytes` cannot be imported, embedding a precise install command in the message so the operator can resolve the issue without consulting external documentation (FR-806).
- `load_colqwen_model` raises it when torch/transformers cannot be imported, or when `from_pretrained` fails for any reason (network error, corrupt checkpoint, CUDA initialisation failure) (FR-802).

Callers must treat `ColQwen2LoadError` as unrecoverable for the current pipeline run. The correct response is to abort the visual embedding stage, log the error at `ERROR` level, and surface it to the operator. Retrying with the same parameters will not succeed.

**`VisualEmbeddingError` (non-fatal base)**

The base class for all errors in this module. `ColQwen2LoadError` is its only subclass. The class itself is not raised directly within the module; it exists as a stable catch target for callers who want to handle any visual embedding failure without coupling to the specific subtype.

**Per-page failures (non-fatal, no exception raised)**

Failures during batch preprocessing (`processor.process_images`) and failures during individual page tensor extraction are caught internally, logged at `WARNING` level, and silently skipped — the affected pages are simply absent from the returned list (FR-307). This means `embed_page_images` can return fewer entries than `len(images)`. Callers must compare the `page_number` fields in the returned `ColQwen2PageEmbedding` list against the expected page set to detect gaps. A batch-level inference failure (`model(**batch_inputs)`) also skips the entire batch with a warning, potentially dropping multiple pages at once.

**`ColQwen2PageEmbedding` fields:**

| Field | Type | Description |
|---|---|---|
| `page_number` | `int` | 1-indexed page number (FR-302) |
| `mean_vector` | `list[float]` | 128-dim mean-pooled float32 vector (FR-303) |
| `patch_vectors` | `list[list[float]]` | Raw per-patch vectors, JSON-serializable (FR-304) |
| `patch_count` | `int` | Number of patches produced for this page (FR-302) |
