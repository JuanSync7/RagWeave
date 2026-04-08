# Visual Embedding Pipeline — Engineering Guide

## 1. System Overview

### Purpose

The Visual Embedding Pipeline adds a second, parallel track to the document ingestion system that produces page-level visual embeddings alongside the existing text chunk embeddings. Where the text track extracts structured prose, tokenizes it into overlapping chunks, and encodes each chunk with BGE-M3 into a dense semantic vector, the visual track renders each document page as a JPEG image, encodes it with the ColQwen2 vision-language model, and stores both a compact 128-dimensional mean-pooled vector and a full set of per-patch vectors. The mean vector enables fast approximate-nearest-neighbor (ANN) retrieval from a dedicated Weaviate collection; the patch vectors are stored as JSON text for application-side MaxSim re-scoring, following the ColBERT late-interaction paradigm.

The two tracks are independent: a failure in the visual track cannot corrupt text-chunk state, and disabling visual embedding incurs zero overhead on the ingestion hot path. The feature is opt-in via a single environment variable.

### ASCII Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Document Ingestion Pipeline                           │
│                                                                              │
│  ┌──────────────┐    ┌──────────────────┐    ┌─────────────────────────┐    │
│  │  File Input  │───▶│  Docling Parser  │───▶│  HybridChunker / BGE-M3 │    │
│  └──────────────┘    │  (parse_with_    │    │  (text track)           │    │
│                      │   docling)       │    └────────────┬────────────┘    │
│                      │                  │                 │                  │
│                      │  generate_page_  │    ┌────────────▼────────────┐    │
│                      │  images=True ──▶│    │  embedding_storage_node  │    │
│                      │  page_images[]   │    │  (Weaviate text coll.)  │    │
│                      └──────────────────┘    └────────────┬────────────┘    │
│                               │                           │                  │
│                    ┌──────────▼──────────┐               │                  │
│                    │ EmbeddingPipelineState│              │                  │
│                    │  .page_images        │              │                  │
│                    │  .docling_document   │              │                  │
│                    └──────────┬──────────┘               │                  │
│                               │                           │                  │
│              ┌────────────────▼────────────────┐         │                  │
│              │       visual_embedding_node       │◀────────┘                │
│              │  (FR-601: between emb_storage     │                          │
│              │   and kg_storage)                 │                          │
│              │                                   │                          │
│              │  1. Extract page images            │                          │
│              │     (state.page_images or          │                          │
│              │      DoclingDocument.pages)        │                          │
│              │  2. Resize (max_dimension=1024)    │                          │
│              │  3. MinIO JPEG upload              │                          │
│              │     pages/{doc_id}/{page:04d}.jpg  │                          │
│              │  4. ColQwen2 inference             │                          │
│              │     (4-bit quant, batch_size=4)    │                          │
│              │     → mean_vector [128-dim]        │                          │
│              │     → patch_vectors [N×128]        │                          │
│              │  5. Weaviate insert                │                          │
│              │     RAGVisualPages collection      │                          │
│              │     named vector: mean_vector      │                          │
│              │  6. Clear page_images from state   │                          │
│              └───────────────┬───────────────────┘                          │
│                              │                                                │
│              ┌───────────────▼───────────────────┐                          │
│              │   knowledge_graph_storage_node     │                          │
│              └───────────────────────────────────┘                          │
│                                                                              │
│  ═══════════════ TRACK 1: TEXT ════════════════════════════════════════════  │
│  Docling → HybridChunker → BGE-M3 → Weaviate (text collection)              │
│                                                                              │
│  ═══════════════ TRACK 2: VISUAL ══════════════════════════════════════════  │
│  Docling (page images) → resize → MinIO JPEG → ColQwen2 → RAGVisualPages     │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Design Goals

1. **Zero-overhead opt-out.** When `enable_visual_embedding=False` (the default), the visual track introduces no runtime cost — no model load, no image extraction, no storage I/O. The short-circuit fires before any side effects.

2. **GPU budget isolation.** BGE-M3 and ColQwen2 are never resident in VRAM simultaneously. BGE-M3 finishes and releases its allocations before ColQwen2 loads, keeping peak VRAM at or below 4 GB on an RTX 2060-class card.

3. **Text-track isolation.** A failure in the visual track must never corrupt, overwrite, or abort text-track state. The visual node returns only the fields it owns and is wrapped by a top-level catch-all that prevents unhandled exceptions from propagating to downstream nodes.

4. **Two-tier retrieval readiness.** The visual collection stores both a compact mean vector (indexed for ANN search) and the full patch vectors (stored as JSON for application-side MaxSim re-scoring), so future retrieval implementations can choose either strategy without a schema migration.

5. **Additive, non-breaking integration.** All visual-track code is opt-in and additive. Existing text-track nodes, schemas, and tests are unchanged. Optional Python dependencies (`colpali-engine`, `bitsandbytes`) are declared under a `[visual]` extras group so text-only deployments install without a GPU environment.

### Technology Choices

| Layer | Choice | Reason |
|---|---|---|
| Visual encoder | ColQwen2 (`vidore/colqwen2-v1.0`) via `colpali-engine` | ColPali-family model optimised for document page retrieval; produces patch-level token embeddings suitable for MaxSim late interaction |
| Quantization | 4-bit via `bitsandbytes` (BnB `load_in_4bit`, `bnb_4bit_compute_dtype=float16`) | Only quantization level that fits ColQwen2 within the 4 GB VRAM budget |
| Image format | JPEG in MinIO, configurable quality (default 85) | Broad compatibility, acceptable quality for document pages; lossless PNG unnecessary and ~3× larger |
| Vector store | Weaviate v4, named vector API, HNSW cosine | Named vectors allow multi-vector schemas; HNSW is the standard ANN index for medium-scale retrieval |
| Object store | MinIO | Shared with the existing document storage layer; same client, same bucket |
| Image extraction | Docling `generate_page_images=True` at parse time | Page images exist only in memory during `convert()`; must be captured before the `ConversionResult` is discarded |
| Pipeline wiring | LangGraph unconditional node | Keeps graph topology static; short-circuit logic inside the node rather than on the edge |

---

## 2. Architecture Decisions

### Decision: Sequential GPU Usage — BGE-M3 Finishes Before ColQwen2 Loads

**Context:**
The text track uses BGE-M3 (approximately 1.5 GB VRAM) to encode text chunks. The visual track uses ColQwen2 at 4-bit quantization (approximately 2 GB VRAM). Both models require a CUDA device. A naive implementation might load both models at startup and hold them resident, or attempt parallel inference.

**Options considered:**
- Load both models at pipeline startup, hold resident throughout the run.
- Load both at startup, share a single GPU inference queue, run in parallel across batches.
- Sequential: BGE-M3 completes text embedding, releases VRAM, then ColQwen2 is loaded on demand.

**Choice:**
Sequential GPU usage. BGE-M3 runs and finishes (via the text embedding nodes) before the visual node loads ColQwen2. ColQwen2 is loaded at the start of the visual node and unloaded in a `finally` block at the end.

**Rationale:**
1.5 GB + 2 GB = 3.5 GB, which is within the 4 GB budget only if both peaks do not overlap. In practice, PyTorch CUDA allocators retain fragmented memory after `del`, so simultaneous residency easily pushes over 4 GB even if the theoretical sum is within budget. Sequential loading guarantees that VRAM at any point in time is bounded by the larger of the two models, not their sum. The overhead is the ColQwen2 load time (approximately 10–30 seconds depending on disk speed), which is acceptable relative to the time spent on image extraction and inference for a typical document.

**Consequences:**
- Positive: Deterministic VRAM ceiling; works on 4 GB cards.
- Positive: Text track failures cannot strand a loaded ColQwen2 model.
- Negative: Model load overhead per document; not amortised across a batch of documents in a single pipeline run.
- Watch for: If future pipeline changes make text and visual nodes run in separate Temporal activities on the same worker, the sequential guarantee must be enforced at the activity level, not at the node level.

---

### Decision: Two-Tier Retrieval — Mean Vector ANN + Patch Vectors Application-Side MaxSim

**Context:**
ColQwen2 produces per-patch embedding tensors of shape `[n_patches, 128]`. The ColBERT late-interaction MaxSim scoring requires comparing each query patch against all document page patches and summing the maximum similarities. This is fundamentally a CPU/GPU re-scoring operation over a shortlist, not a native ANN operation.

**Options considered:**
- Store only mean-pooled vectors; use cosine ANN for retrieval, no re-scoring.
- Store patch vectors as a second named vector in Weaviate and rely on native multi-vector support.
- Store mean vector as named vector for ANN; store patch vectors as JSON TEXT for application-side re-scoring.
- Store patch vectors only in a separate external store (Redis, custom service).

**Choice:**
Two-tier: mean vector as a 128-dim HNSW named vector for ANN recall; patch vectors serialized as JSON TEXT in the same Weaviate object, with `skip_vectorization=True`.

**Rationale:**
Weaviate's current named-vector API does not expose a native MaxSim operator over multi-vector fields. Indexing `n_patches × 128` values as a second named vector would create an index over thousands of dimensions per object, which is computationally expensive and unsupported. Storing patch vectors as JSON TEXT is a practical interim solution: the ANN pass produces a shortlist of candidate pages, and the application layer deserialises the patch vectors from the TEXT field and applies MaxSim in Python/NumPy. This separates the concern of fast candidate retrieval (Weaviate HNSW) from precise re-scoring (application), without requiring a schema change when native MaxSim becomes available.

**Consequences:**
- Positive: Weaviate schema stays simple; no multi-vector index overhead.
- Positive: MaxSim implementation can be changed without touching the ingestion pipeline.
- Negative: Patch vectors are not indexed; full-dataset MaxSim without ANN pre-filtering is not feasible.
- Negative: JSON TEXT field size grows linearly with patch count; large pages produce large objects.
- Watch for: Weaviate adding native multi-vector/late-interaction support — at that point `ensure_visual_collection` should be updated to declare a proper patch-vector index, and patch data should be migrated from TEXT to the native type.

---

### Decision: Optional `[visual]` Extras in pyproject.toml

**Context:**
`colpali-engine` and `bitsandbytes` carry large transitive dependencies including CUDA toolkit bindings, Triton, and specific PyTorch builds. Text-only deployments (cloud VMs without GPU, CI environments) should not be forced to install GPU libraries.

**Options considered:**
- Hard dependency in `pyproject.toml` `[project.dependencies]`.
- Separate `rag-visual` package on PyPI.
- Optional extras declared as `[visual]` in `pyproject.toml`.

**Choice:**
Optional `[visual]` extras. `pip install "rag[visual]"` installs `colpali-engine` and `bitsandbytes` in addition to the base package. The base package installs without them.

**Rationale:**
Optional extras are the standard Python packaging mechanism for conditional feature sets. They allow the visual track code to be present in the source tree (enabling IDE support and import validation) while remaining inert at runtime when the packages are absent. `ensure_colqwen_ready()` catches the `ImportError` at call time and surfaces a precise install command rather than a cryptic traceback.

**Consequences:**
- Positive: Text-only deployments have no GPU library overhead.
- Positive: CI pipelines can test the text track without a CUDA environment.
- Negative: Operators must remember to install the extras when enabling the visual track; `ensure_colqwen_ready` provides a clear error message to guide them.
- Watch for: Version incompatibilities between `colpali-engine`, `bitsandbytes`, and the installed PyTorch version — pin versions in the extras declaration.

---

### Decision: Unconditional LangGraph Node with Internal Short-Circuit

**Context:**
The visual embedding node can be disabled via `enable_visual_embedding=False`. LangGraph supports conditional edges that route around nodes entirely based on state values. An alternative design would use a conditional edge from `embedding_storage` that routes to either `visual_embedding` or directly to `knowledge_graph_storage` based on the config flag.

**Options considered:**
- Conditional edge: `embedding_storage → [if enabled: visual_embedding | else: knowledge_graph_storage]`.
- Unconditional edge into `visual_embedding`; short-circuit implemented inside the node as an early return.

**Choice:**
Unconditional edge; short-circuit inside the node.

**Rationale:**
Conditional graph topology requires the routing function to read config at graph-compile time. If the config changes between pipeline invocations (for example via environment variable reload), the compiled graph would need to be rebuilt. An unconditional topology means the graph is always the same 10-node DAG; the enable/disable decision is a runtime check inside the node. This makes the graph easier to inspect, visualise, and test — the topology is always the same regardless of config. The short-circuit fires before any I/O, so the cost of entering the node when disabled is two attribute reads and an early return.

**Consequences:**
- Positive: Static, inspectable graph topology.
- Positive: No graph recompile on config change.
- Negative: The node is always "present" in traces and logs even when it no-ops; operators may see `visual_embedding_node` in pipeline traces and wonder if it ran.
- Watch for: If short-circuit logic grows complex (multiple conditions, state mutations), consider moving to a router function while keeping the topology unconditional.

---

### Decision: Separate `RAGVisualPages` Weaviate Collection

**Context:**
The existing text collection holds chunk objects with properties like `chunk_text`, `chunk_index`, `heading_path`, and a default unnamed vector. Visual page objects need different properties (`page_number`, `minio_key`, `patch_vectors`, `page_width_px`, `page_height_px`) and require a named vector API with specific HNSW dimensionality (128).

**Options considered:**
- Single collection with a `modality` discriminator field (`text` vs `visual`).
- Separate Weaviate tenant per modality within the same collection class.
- Dedicated `RAGVisualPages` collection with its own schema and HNSW index.

**Choice:**
Dedicated `RAGVisualPages` collection.

**Rationale:**
A shared collection would require every query to include a `modality` filter, pollute the HNSW index with mixed-dimensionality vectors (BGE-M3 produces 1024-dim, ColQwen2 mean-pooling produces 128-dim), and force all visual properties into the text schema. A dedicated collection keeps the HNSW index tuned for 128-dim cosine, the schema clean, and query logic simple. The `RAGVisualPages` name is parameterised throughout (via `visual_target_collection` config), so tenant isolation can be achieved by passing a per-tenant prefix without code changes.

**Consequences:**
- Positive: Schema independence; each collection optimised for its modality.
- Positive: Tenant isolation achievable via naming convention.
- Negative: Clients that want to retrieve both text and visual results must query two collections and merge results.
- Watch for: Collection count grows with number of tenants if per-tenant naming is adopted; monitor Weaviate collection overhead.

---

## 3. Module Reference

The six sections below are the authoritative per-module documentation for the visual embedding pipeline. They document purpose, implementation details, design decisions, configuration, and error behavior for each component.

---

### MODULE 1: src/ingest/support/colqwen.py — ColQwen2 Model Adapter

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

---

### MODULE 2: src/vector_db/weaviate/visual_store.py + backend.py additions — Weaviate Visual Collection Store

**Purpose:**

The Visual Collection Store manages the `RAGVisualPages` Weaviate collection, which holds per-page visual embeddings produced by the Visual Embedding Pipeline. It is intentionally separate from the text embedding collection because visual pages require a fundamentally different retrieval strategy: a two-tier approach where a compact 128-dimensional mean vector enables fast approximate-nearest-neighbor (ANN) search to retrieve a shortlist of candidate pages, and a full set of patch vectors stored as a JSON-serialised TEXT field enables a second-pass MaxSim re-scoring pass that refines the shortlist without requiring dense patch vectors to be indexed by the vector database.

Keeping visual pages in their own collection preserves schema independence (visual properties such as `page_width_px`, `page_height_px`, and `minio_key` are meaningless for text chunks), allows the HNSW index to be tuned exclusively for 128-dimensional cosine similarity, and prevents the visual ingestion path from touching or risking corruption of text embeddings. The `RAGVisualPages` name is the default but is parameterised throughout, so deployments that need collection-name isolation (for example per-tenant prefixing) can pass a different name without code changes.

The three source files covered here form a single logical unit:

- `visual_store.py` — the collection-level store functions (create, insert, delete).
- `backend.py` additions — three new abstract methods on the `VectorBackend` ABC that declare the visual interface contract without modifying any existing methods (NFR-909).
- `weaviate/backend.py` additions — the `WeaviateBackend` concrete class that delegates each abstract method call to the corresponding `visual_store` function.

---

**How it works:**

**1. Collection creation — `ensure_visual_collection` (FR-502, FR-504)**

On first use the collection must be created. `ensure_visual_collection` checks whether the named collection already exists via `client.collections.exists(collection)` and returns immediately if it does, making the call idempotent. When the collection is absent it builds:

- A `NamedVectors.none` vector configuration named `"mean_vector"` with a 128-dimensional HNSW index using cosine distance. The `none` vectorizer means Weaviate never tries to vectorize objects automatically; all vectors are supplied by the caller at insert time.
- Eleven scalar properties covering document provenance (`document_id`, `source_key`, `source_uri`, `source_name`, `tenant_id`), page geometry (`page_number`, `total_pages`, `page_width_px`, `page_height_px`), storage location (`minio_key`), and the serialised patch payload (`patch_vectors`).

The `patch_vectors` property carries `skip_vectorization=True`, which prevents Weaviate from attempting module-level vectorization on a field that is intentionally raw JSON text (FR-505).

**2. Batch insert — `add_visual_documents` (FR-507)**

```python
def add_visual_documents(
    client: weaviate.WeaviateClient,
    documents: List[dict[str, Any]],
    collection: str = "RAGVisualPages",
) -> int:
    if not documents:
        return 0
    col = client.collections.get(collection)
    with col.batch.dynamic() as batch:
        for doc in documents:
            mean_vector = doc["mean_vector"]
            properties = {k: v for k, v in doc.items() if k != "mean_vector"}
            batch.add_object(properties=properties, vector={"mean_vector": mean_vector})
    failed = len(col.batch.failed_objects) if hasattr(col.batch, "failed_objects") else 0
    return len(documents) - failed
```

The Weaviate v4 named-vector pattern requires the `vector` argument to `add_object` to be a dictionary keyed by vector name rather than a plain list. Here `{"mean_vector": mean_vector}` is the named-vector envelope that associates the 128-dim float list with the index configured in step 1. All other keys in the document dict become scalar properties. The function uses `col.batch.dynamic()` which lets Weaviate auto-tune batch sizing, and returns the number of objects successfully inserted (total minus failed). If `documents` is empty the function short-circuits and returns `0` without touching the client.

**3. Delete by source key — `delete_visual_by_source_key` (FR-506)**

```python
where = Filter.by_property("source_key").equal(source_key)
result = col.data.delete_many(where=where)
return getattr(result, "matches", 0) or 0
```

All visual page objects for a document share the same `source_key` (the canonical object storage key for the source file). Deleting by `source_key` therefore removes every page of a document atomically in a single server-side filter operation, without the caller needing to enumerate page numbers. The return value is the count of matched (and deleted) objects from the Weaviate `DeleteManyResult`, falling back to `0` if the attribute is absent on older client versions.

**4. ABC → WeaviateBackend delegation chain**

The `VectorBackend` abstract base class declares three new abstract methods (`ensure_visual_collection`, `add_visual_documents`, `delete_visual_by_source_key`) with identical signatures to the store functions but with `client` typed as `Any` and `collection` as `Optional[str]` to remain backend-agnostic. This means any alternative backend (for example a future Qdrant or pgvector backend) must implement the same three visual methods to satisfy the interface contract.

`WeaviateBackend` implements each method by resolving the collection name — using the caller-supplied value if provided, falling back to the class-level constant `_VISUAL_COLLECTION_DEFAULT = "RAGVisualPages"` — and then forwarding the call to the corresponding `visual_store` function imported with a `_wv_` prefix alias. The delegation layer adds no logic of its own; it exists solely to honour the ABC contract and inject the default collection name.

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Separate `RAGVisualPages` collection (FR-501) | Single collection with a type discriminator field; separate Weaviate tenant per modality | A dedicated collection allows the HNSW index to be sized and tuned purely for 128-dim cosine vectors, avoids schema pollution in the text collection, and makes query filters simpler (no type-discriminator clause needed on every visual query). |
| Named vector `"mean_vector"` with `vectorizer=none` (FR-504) | Default unnamed vector; multi-vector index for both mean and patch | Named vectors are the Weaviate v4 idiomatic pattern for externally supplied embeddings; `none` vectorizer ensures no accidental re-vectorization. A separate named vector for patch vectors was rejected because patch vectors are used only for CPU-side MaxSim re-scoring, not ANN search, making indexing them wasteful. |
| `patch_vectors` stored as serialised JSON TEXT (FR-505) | Weaviate BLOB property; separate object or external store; structured array property | TEXT avoids binary encoding round-trips, is human-readable in debug queries, and does not require a schema change when patch dimensionality changes. Storing patches externally would add a second lookup per page during re-scoring. |
| Idempotent `ensure_visual_collection` (FR-502) | Fail-fast if collection absent; caller-managed creation | Idempotent creation removes the need for startup ordering guarantees between the pipeline and an admin setup script. It is safe to call on every ingestion run; the existence check is a single lightweight Weaviate metadata call. |
| Delete by `source_key` rather than UUID list (FR-506) | Store per-page UUIDs and delete individually; delete by `document_id` | `source_key` is the stable, externally visible identity of a file. Deleting by `source_key` on the server side is a single atomic filter-delete; UUID-by-UUID deletion would require a prior query to enumerate UUIDs and would be non-atomic. |
| `add_visual_documents` returns insert count (FR-507) | Return `None`; raise on any failure; return list of failed objects | A count is the minimal, backend-neutral success signal. Callers that need stricter guarantees can compare the returned count to `len(documents)` and decide whether to retry or raise; the function itself does not raise on partial failure to allow the caller to apply its own retry policy. |
| Three new ABC methods, existing methods untouched (NFR-909) | Extend existing `add_documents` / `delete_documents` signatures with a `modality` flag | Adding three distinct methods preserves the existing calling convention and avoids conditionals in existing method bodies. Backend implementors that do not yet support visual collections can raise `NotImplementedError` without affecting any text-retrieval code path. |

---

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `collection` (store functions) | `str` | `"RAGVisualPages"` | The Weaviate collection name targeted by all three store operations. Override to isolate visual pages by tenant or deployment environment. Must match the name used for creation, insertion, and deletion — passing different names to create and insert will result in a missing collection error. |
| `dimensions` (HNSW config, set at collection creation) | `int` | `128` | The expected dimensionality of `mean_vector` embeddings. This is fixed at collection-creation time; changing it requires dropping and re-creating the collection. Set to match the output dimensionality of the visual mean-pooling model. |
| `distance_metric` (HNSW config, set at collection creation) | `VectorDistances` enum | `VectorDistances.COSINE` | The distance metric used for ANN search. Cosine is appropriate for normalised visual embedding vectors. Changing this requires collection re-creation. |
| `_VISUAL_COLLECTION_DEFAULT` (WeaviateBackend class constant) | `str` | `"RAGVisualPages"` | The fallback collection name used by `WeaviateBackend` when the caller passes `collection=None`. Changing this constant at the class level renames the default target for all visual operations on that backend instance. |

---

**Error behavior:**

`ensure_visual_collection` is the only operation with meaningful idempotency guarantees. If the collection already exists, the function returns without error regardless of whether the existing schema matches the expected schema. A schema mismatch (for example an existing collection with the same name but different properties or vector dimensions) will not be detected or corrected; the caller is responsible for ensuring that the collection was originally created by this function or an equivalent configuration.

`add_visual_documents` does not raise on partial batch failure. Weaviate's `batch.dynamic()` context manager absorbs per-object errors internally. The function reads `col.batch.failed_objects` after the context exits and subtracts the failed count from the total to compute the return value. Callers should treat a return value less than `len(documents)` as a partial failure and apply their own retry or alerting logic. If `documents` is an empty list the function returns `0` immediately without contacting Weaviate.

`delete_visual_by_source_key` returns `0` both when no objects matched the filter and when the `DeleteManyResult` object does not carry a `matches` attribute (older Weaviate client versions). Callers that need to distinguish "nothing to delete" from "delete count unavailable" should not rely on this return value as a strict audit signal; it is best used as an approximate progress counter or log annotation.

All three store functions propagate Weaviate client exceptions (`weaviate.exceptions.WeaviateConnectionError`, `weaviate.exceptions.WeaviateQueryError`, and similar) directly to the caller without wrapping. The `WeaviateBackend` delegation layer adds no exception handling either. Callers at the pipeline orchestration level are responsible for catch-and-retry behaviour on transient connection errors.

---

### MODULE 3: src/db/minio/store.py — MinIO Page Image Storage (Visual Track Addition)

**Purpose:**

This section documents the two page-image functions added to the existing document store module as part of the visual embedding pipeline track: `store_page_images` and `delete_page_images`. These functions are additive extensions to a module that already handles document-level file storage (Markdown content under `docs/{source_key}/content.md`). Page image storage is kept in the same module because it shares the same MinIO client, bucket configuration, and error-handling conventions — adding a new key namespace (`pages/`) rather than a new abstraction layer. `store_page_images` serializes in-memory PIL-compatible image objects to JPEG and uploads them to MinIO under a structured key. `delete_page_images` removes all images for a document in bulk, used to clean up stale page data before re-ingesting an updated document.

---

**How it works:**

**`store_page_images`**

The function iterates over a list of `(page_number, image)` tuples. For each page, it constructs the object key using a fixed pattern:

```python
key = f"pages/{document_id}/{page_number:04d}.jpg"
```

Page numbers are 1-indexed and zero-padded to four digits (e.g., page 1 → `pages/<uuid>/0001.jpg`, page 42 → `pages/<uuid>/0042.jpg`). This ensures lexicographic sort order is consistent with page order for any document up to 9,999 pages.

The image is serialized to JPEG in memory using a `BytesIO` buffer rather than a temporary file on disk:

```python
buffer = io.BytesIO()
image.save(buffer, format="JPEG", quality=quality)
buffer.seek(0, 2)   # seek to end to measure length
length = buffer.tell()
buffer.seek(0)       # rewind before upload
```

The buffer length is measured by seeking to the end before rewinding to the start. This is required because `put_object` needs an explicit `length` parameter when the data source is a stream (MinIO does not auto-detect stream length). The buffer is then passed directly to `put_object` with `content_type="image/jpeg"`. On success, the key is appended to `stored_keys`. On any exception, a warning is logged and the loop continues to the next page. The function returns `stored_keys` — the list of MinIO object keys that were successfully uploaded (FR-403).

**`delete_page_images`**

The function constructs the document-level prefix:

```python
prefix = f"pages/{document_id}/"
```

It calls `list_objects` with `recursive=True` to enumerate all objects under that prefix, then removes each one individually with `remove_object`. A running count `deleted` tracks how many objects were removed. If listing fails, a warning is logged and the function returns 0. If an individual object removal fails, a warning is logged and the function returns the count accumulated up to that point (early exit on first per-object failure).

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| JPEG compression with configurable quality | PNG (lossless), WebP, fixed quality | JPEG is broadly supported and suitable for page images where minor compression artefacts are acceptable. Configurable quality (default 85) lets callers tune storage size vs. fidelity without code changes (FR-402). |
| In-memory `BytesIO` buffer instead of temp files | `tempfile.NamedTemporaryFile`, writing to disk then streaming | Avoids filesystem I/O and temp-file cleanup. `put_object` accepts any file-like object, making the buffer a direct drop-in with no intermediate state on disk. |
| Zero-padded 4-digit page number in key | No padding, 3-digit padding, hash-based key | Lexicographic sort in MinIO prefix listings naturally reflects page order. Four digits supports up to 9,999 pages while staying compact. |
| Per-page error isolation in `store_page_images` | Abort on first failure, batch error handling | A single corrupted or oversized page should not block all other pages from being stored. Callers can detect partial success by comparing the length of `stored_keys` to the input list (FR-401). |
| Early-exit on first per-object error in `delete_page_images` | Continue deleting remaining objects on failure | A removal failure may indicate a permission or connectivity issue that will affect subsequent removals too. Returning a partial count lets callers detect incomplete deletes and retry or surface an error, rather than masking a systemic problem. |
| Separate `pages/` prefix namespace from `docs/` | Subdirectory under the document key, combined prefix | Keeps page images independently listable and deletable without touching document content keys. Enables future per-namespace lifecycle policies (e.g., separate bucket or TTL). |

---

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `client` | `minio.Minio` | (required) | The MinIO client instance used for all object operations. |
| `document_id` | `str` | (required) | UUID string identifying the document. Forms the second path segment of every key: `pages/{document_id}/`. |
| `pages` | `list[tuple[int, object]]` | (required) | List of `(page_number, image)` pairs. `page_number` is an integer (1-indexed). `image` must support `.save(buffer, format=..., quality=...)` (PIL/Pillow `Image` interface). |
| `quality` | `int` | `85` | JPEG compression quality passed to `image.save`. Range 1–95; higher values produce larger files with fewer artefacts (FR-402). |
| `bucket` | `str` | `MINIO_BUCKET` (module constant) | MinIO bucket name. Defaults to the shared bucket used by the rest of the document store. Override for testing or multi-bucket deployments. |

The `delete_page_images` function shares the `client`, `document_id`, and `bucket` parameters with the same semantics; it has no `quality` or `pages` parameters.

---

**Error behavior:**

**`store_page_images` — per-page isolation**

Each page upload is wrapped in its own `try/except`. If serialization or upload fails for a page, the exception is caught, a `WARNING`-level log entry is emitted (including `page_number`, `document_id`, and the exception), and the loop advances to the next page. The failed page's key is not added to `stored_keys`. The caller receives a list that may be shorter than the input `pages` list. To detect partial failure, compare `len(stored_keys)` to `len(pages)`. No exception is raised to the caller under any per-page failure scenario.

**`delete_page_images` — partial delete on per-object failure**

Prefix listing is wrapped in an outer `try/except`: if `list_objects` raises, a warning is logged and the function returns `0` immediately. Individual `remove_object` calls are wrapped in a per-object `try/except`: if removal fails, a warning is logged and the function returns the `deleted` count accumulated so far (early exit). This means the return value is the count of objects successfully deleted before the first failure, not a guarantee that all objects under the prefix were removed. Callers that require complete cleanup (for example, update-mode pre-storage cleanup per FR-405) should treat a returned count less than the expected number of pages as a soft error and surface it or retry.

In both functions, no exception propagates to the caller. All failures are communicated through the return value (shorter key list or lower deleted count) and the warning log.

---

### MODULE 4: src/ingest/embedding/nodes/visual_embedding.py — Visual Embedding Node

**Purpose:**

This is the primary LangGraph node for the visual (page-image) embedding track. It extracts per-page images from a `DoclingDocument`, resizes them, stores them as JPEG objects in MinIO, runs ColQwen2 batch inference to produce 128-dim patch and mean-pooled vectors, and inserts the resulting objects into a dedicated Weaviate collection (`RAGVisualPages` by default). It is positioned between `embedding_storage_node` and `knowledge_graph_storage_node` in the Embedding Pipeline DAG (FR-601, FR-604). The node owns the entire visual lifecycle for a single ingestion run and returns a strict partial-state update that never touches any text-track fields (FR-803).

---

**How it works:**

The public entry point is `visual_embedding_node(state)`. All heavy work is delegated to the private `_run_visual_embedding` helper so that the outer function stays thin and readable.

**Step 1 — Short-circuit checks (FR-603, NFR-903)**

Before any I/O or model load, the node checks two gating conditions. If either fires it returns immediately with `visual_stored_count=0` and `page_images=None`, guaranteeing zero cost for pipelines that do not use visual embedding:

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

A third implicit short-circuit fires inside `_run_visual_embedding` when `_extract_page_images` returns an empty list — logged as `visual_embedding:skipped:no_pages`.

**Step 2 — Page image extraction (FR-201 through FR-205)**

Extraction uses a two-path strategy implemented in `_extract_page_images`:

- **Primary path (state `page_images`):** When Docling parsing ran with `generate_page_images=True` (enabled automatically when `enable_visual_embedding=True` via the `IngestionConfig.generate_page_images` derived property), the parsing node pre-populates `state["page_images"]` with a list of already-rendered PIL images. The visual node iterates this list, converts each image to RGB, and assigns 1-based page numbers in iteration order.

- **Fallback path (`DoclingDocument.pages`):** When `state["page_images"]` is absent or empty, the node reads the `DoclingDocument.pages` dictionary (keyed by page index). Each `PageItem` that has a non-None `.image` attribute is extracted; the 0-indexed `page_no` field is incremented to produce a 1-based page number. Per-page failures are caught and logged as warnings so one bad page does not abort the rest (FR-801).

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

The return type for both paths is `list[tuple[int, PIL.Image, int, int]]` — a 4-tuple of `(1-indexed page_number, RGB PIL.Image, original_width_px, original_height_px)`. The original pixel dimensions are preserved in the tuple so they can be written to Weaviate even after resizing.

**Step 3 — Aspect-ratio-preserving resize (FR-202, FR-203)**

`_resize_page_images` computes a uniform scale factor so that `max(width, height)` does not exceed `config.page_image_max_dimension` (default 1024 px). The original dimensions are passed through unchanged in the tuple — only the embedded `PIL.Image` is replaced with the resized version. If the longer edge is already within the limit, or if `max_dimension <= 0`, the image is returned as-is:

```python
longer_edge = max(orig_w, orig_h)
if longer_edge > max_dimension and longer_edge > 0:
    scale = max_dimension / longer_edge
    new_w = max(1, int(orig_w * scale))
    new_h = max(1, int(orig_h * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)
```

`Image.LANCZOS` is used for high-quality downsampling. A per-page exception guard logs a warning and keeps the original if resize fails, allowing the pipeline to continue.

**Step 4 — Pre-storage cleanup (FR-404, FR-405)**

When running in update mode (re-ingesting an existing document), stale visual data from the previous run must be removed before writing new data. The node issues two delete calls — one against MinIO and one against Weaviate — both wrapped in separate `try/except` blocks that log warnings on failure without aborting the node:

- MinIO: `delete_page_images(minio_client, document_id)` — removes all objects matching the prefix `pages/{document_id}/`.
- Weaviate: `delete_visual_by_source_key(weaviate_client, source_key, visual_target_collection)` — deletes all `RAGVisualPages` objects whose `source_key` property matches. This is a bulk delete by filter, not by Weaviate UUID.

Cleanup is unconditional (not gated on `update_mode`) because it is idempotent — deleting nothing when the document is new has no side effects.

**Step 5 — MinIO page image storage (FR-401, FR-402, FR-403)**

`store_page_images` is called with the list of `(page_number, PIL.Image)` tuples and the configured JPEG quality (default 85). It writes each page to MinIO under the key `pages/{document_id}/{page_number:04d}.jpg`. Each successful upload appends the key to a returned list. The node parses the returned keys to build a `dict[int, str]` mapping `page_number → minio_key`, which is later embedded in the Weaviate object so that a retrieval client can fetch the raw page image. Per-page upload failures are isolated inside `store_page_images` and logged as warnings (FR-403).

**Step 6 — ColQwen2 load, batch embed, and guaranteed unload (FR-301 through FR-307)**

This is the most resource-intensive step. The pattern is structured so that the model is **always** unloaded in a `finally` block regardless of inference success or failure:

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

**Step 7 — Weaviate visual object insertion (FR-501 through FR-507)**

The node calls `ensure_visual_collection` to idempotently create the `RAGVisualPages` collection (128-dim HNSW cosine named vector `mean_vector`, 11 scalar properties), then constructs one document dict per `ColQwen2PageEmbedding` and batch-inserts via `add_visual_documents`:

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

**Step 8 — Processing log (FR-701 through FR-705)**

Five timestamped entries are appended to `state["processing_log"]` in sequence:

| Entry | Description |
|-------|-------------|
| `visual_embedding:pages_extracted:<N>` | Pages found after image extraction |
| `visual_embedding:pages_stored_minio:<N>` | Pages successfully uploaded to MinIO |
| `visual_embedding:pages_embedded:<N>` | Pages that produced ColQwen2 embeddings |
| `visual_embedding:pages_indexed:<N>` | Pages inserted into Weaviate |
| `visual_embedding:elapsed_s:<F>` | Wall-clock time for the entire node in seconds |

**Step 9 — Partial state update (FR-803, FR-606)**

The return dict contains exactly the fields the visual node owns. Text-track fields (`stored_count`, `chunks`, `enriched_chunks`, `raw_text`, `cleaned_text`, `refactored_text`, `metadata_summary`, `metadata_keywords`, `cross_references`, `kg_triples`) are **never written**. `page_images` is explicitly set to `None` to free the PIL objects from the LangGraph state (FR-606).

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

---

**Configuration:**

All parameters are read from `IngestionConfig` (populated from `config/settings.py` environment variables). None have side-effects on text-track behavior.

| Parameter | Env Var | Type | Default | Effect |
|-----------|---------|------|---------|--------|
| `enable_visual_embedding` | `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING` | `bool` | `False` | Master switch. `False` → node short-circuits immediately with zero cost (NFR-903). |
| `visual_target_collection` | `RAG_INGESTION_VISUAL_TARGET_COLLECTION` | `str` | `"RAGVisualPages"` | Weaviate collection name for visual page objects. |
| `colqwen_model_name` | `RAG_INGESTION_COLQWEN_MODEL` | `str` | `"vidore/colqwen2-v1.0"` | HuggingFace model identifier passed to `ColQwen2.from_pretrained`. |
| `colqwen_batch_size` | `RAG_INGESTION_COLQWEN_BATCH_SIZE` | `int` | `4` | Images per ColQwen2 forward pass. |
| `page_image_quality` | `RAG_INGESTION_PAGE_IMAGE_QUALITY` | `int` | `85` | JPEG compression quality for MinIO uploads. |
| `page_image_max_dimension` | `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION` | `int` | `1024` | Maximum pixel length of the longer image edge after resize. |

---

**Error behavior:**

**Level 1 — Fatal: `ColQwen2LoadError` (no retry, immediate return)**

Raised by `ensure_colqwen_ready()` when `colpali-engine` or `bitsandbytes` are not importable, or by `load_colqwen_model()` when the model fails to load. Returns immediately with `visual_stored_count=0`. Text track is completely unaffected.

**Level 2 — Non-fatal: `VisualEmbeddingError` during batch inference**

Caught in `except VisualEmbeddingError` inside the `try/finally` block. `finally` still executes, unloading the model. Weaviate insert proceeds with whatever embeddings were successfully produced.

**Level 3 — Partial: Weaviate batch insert failure**

Caught by outer `except Exception` in the Weaviate insertion block. `visual_stored_count` may be less than `len(embeddings)`.

**Level 4 — Unhandled: top-level catch-all**

Any exception not caught by inner handlers is caught by the outer `try/except Exception` wrapping `_run_visual_embedding`. Returns `visual_stored_count=0`, logs full traceback at `ERROR` level. Pipeline continues to the next node.

**Invariant across all error levels:** `stored_count`, `chunks`, `enriched_chunks`, and all other text-track state fields are never set or overwritten by this node (FR-803).

---

### MODULE 5: config/settings.py + types.py + state.py + workflow.py — Configuration, State, and Pipeline Wiring

**config/settings.py:**

Purpose: Declares the six environment-variable-backed constants that control the visual embedding pipeline. Default for `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING` is `"false"` (opt-in). Each constant is read from `os.environ` at module-import time.

| Environment Variable | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING` | bool | `false` | `true`/`false` | Activates the dual-track visual embedding pipeline (FR-101). |
| `RAG_INGESTION_VISUAL_TARGET_COLLECTION` | str | `"RAGVisualPages"` | Any non-empty string | Weaviate collection name (FR-102). |
| `RAG_INGESTION_COLQWEN_MODEL` | str | `"vidore/colqwen2-v1.0"` | Any HuggingFace model identifier | ColQwen2 model (FR-103). |
| `RAG_INGESTION_COLQWEN_BATCH_SIZE` | int | `4` | 1–32 | Batch size (FR-104). |
| `RAG_INGESTION_PAGE_IMAGE_QUALITY` | int | `85` | 1–100 | JPEG quality (FR-105). |
| `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION` | int | `1024` | 256–4096 | Max pixel dimension (FR-106). |

**types.py:**

Six new fields appended to `IngestionConfig` dataclass. `generate_page_images` is a derived property alias for `enable_visual_embedding`. `IngestFileResult.visual_stored_count` defaults to 0. `PIPELINE_NODE_NAMES` gains `"visual_embedding"` between `"embedding_storage"` and `"knowledge_graph_storage"` (15 entries total, FR-604).

**state.py:**

Two new fields in `EmbeddingPipelineState` (total=False TypedDict):
- `visual_stored_count: int` — accumulates successfully stored page objects
- `page_images: Optional[List[Any]]` — PIL images from Docling; cleared to None after the visual node (FR-606)

**workflow.py:**

`build_embedding_graph()` adds `visual_embedding_node` as an unconditional node. Edge change: `embedding_storage → visual_embedding → [knowledge_graph_storage or END]`. Now a 10-node DAG. The short-circuit logic for disabled visual embedding lives inside the node, keeping the topology static (easier to inspect and test).

Key decision: Unconditional edge into `visual_embedding` — disable logic inside the node keeps graph topology static and inspectable. A conditional edge would require topology to vary based on config at graph-compile time.

---

### MODULE 6: src/ingest/support/docling.py — Docling Page Image Extraction (Visual Track Addition)

**Purpose:**

This module is an additive extension to the existing Docling parsing integration. The base module converts documents to markdown for ingestion; the visual track addition extends it to also extract per-page PIL images during the same parse pass.

Two fields are added to `DoclingParseResult`: `page_images` (a list of `PIL.Image` objects, one per extracted page) and `page_count` (the total number of pages in the source document). A new `generate_page_images` boolean parameter gates this extraction in `parse_with_docling`.

Page image extraction must happen at parse time — not afterward — because Docling's `generate_page_images` option must be set on `PdfPipelineOptions` **before** `convert()` is called. The rendered page images exist only in memory as part of the `ConversionResult` and are not persisted in the serialized `DoclingDocument` JSON.

---

**How it works:**

1. `generate_page_images` parameter added to `parse_with_docling`. When `False`, no page extraction logic runs.
2. When `generate_page_images=True`, `PdfPipelineOptions(generate_page_images=True)` is constructed and passed to the Docling converter before `convert()` is called.
3. `_extract_page_images_from_result(conv_result)` attempts two access strategies:
   - Strategy 1: `conv_result.pages` → `.image.pil_image`
   - Strategy 2: `conv_result.document.pages` → `.image.pil_image` (fallback for different Docling versions)
4. Each image converted to RGB via `image.convert("RGB")` (FR-204).
5. `page_count` set regardless of extraction success (FR-205).

`DoclingParseResult` extension:
```python
page_images: list[Any] = field(default_factory=list)  # FR-201, FR-204
page_count: int = 0                   # FR-205
```

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Gate behind `generate_page_images=False` default | Always extract page images | VRAM/compute cost only when visual track active. Zero regression for existing callers. |
| Extract images during Docling parse pass | Separate post-parse step | `generate_page_images` flag must be set before `convert()`. Images not persisted in DoclingDocument JSON. |
| Two-strategy fallback | Single access path | Docling's internal API has varied across versions; both strategies improve robustness across releases. |
| Silent failure on extraction | Raise on failure | Text-track pipeline must not be blocked by image extraction failures. |
| `page_count` always set even on partial failure | Set only when all images extracted | Callers need `page_count` for telemetry regardless of image availability. |

---

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `generate_page_images` | `bool` | `False` | When `True`, extracts PIL.Image objects from each page of ConversionResult. Derived from `IngestionConfig.enable_visual_embedding` (FR-107). |

---

**Error behavior:**

- Full extraction failure → `page_images=[]`, no exception raised, text output intact.
- Individual page failure → that page skipped with warning log, remaining pages continue.
- `page_count` invariant: always reflects total document pages, independent of image extraction success (FR-205).

---

## 4. End-to-End Data Flow

### Scenario 1: Happy Path — 10-Page PDF with Visual Embedding Enabled

**Setup:** `enable_visual_embedding=True`, `colqwen_batch_size=4`, `page_image_max_dimension=1024`, `page_image_quality=85`.

**Stage 1: Docling parse node**

`parse_with_docling` is called with `generate_page_images=True` (derived from `IngestionConfig.enable_visual_embedding`). Docling converts the PDF with `PdfPipelineOptions(generate_page_images=True)`. The returned `DoclingParseResult` carries:

```
DoclingParseResult:
  markdown: str              # 10 pages of text content
  docling_document: DoclingDocument
  page_images: [PIL.Image × 10]   # one per page, already RGB
  page_count: 10
```

These are committed to `EmbeddingPipelineState`:

```
state (after parse):
  raw_text: str
  docling_document: DoclingDocument
  page_images: [PIL.Image × 10]
  page_count: 10
```

**Stage 2: Text embedding nodes (chunking, BGE-M3, embedding_storage)**

The text track runs to completion. BGE-M3 encodes chunks, writes to the text Weaviate collection, and releases its VRAM allocations. State after `embedding_storage_node`:

```
state (after embedding_storage):
  stored_count: 47           # example: 47 text chunks stored
  chunks: [...]
  page_images: [PIL.Image × 10]   # still in state, awaiting visual node
  docling_document: DoclingDocument
```

**Stage 3: visual_embedding_node (inside `_run_visual_embedding`)**

- Short-circuit check: `enable_visual_embedding=True`, `docling_document` present — proceed.
- Image extraction: `state["page_images"]` has 10 items → primary path. Each image converted to RGB and assigned 1-based page numbers. Result: `[(1, PIL, 842, 1190), ..., (10, PIL, 842, 1190)]`.
- Resize: longer edge = 1190 > 1024. Scale = 1024/1190 ≈ 0.860. New dimensions: 724×1024. 10 images resized.
- Pre-cleanup: `delete_page_images` and `delete_visual_by_source_key` both called (idempotent, delete 0 objects on first run).
- MinIO storage: 10 JPEG uploads at quality 85. Keys: `pages/<uuid>/0001.jpg` … `pages/<uuid>/0010.jpg`. Returns 10 keys.
- ColQwen2: `ensure_colqwen_ready()` passes. `load_colqwen_model("vidore/colqwen2-v1.0")` loads (≈2 GB VRAM). `embed_page_images` iterates 3 batches (4, 4, 2 pages). Each page produces `mean_vector[128]` and `patch_vectors[N×128]`. 10 `ColQwen2PageEmbedding` records returned. `unload_colqwen_model` called in `finally`.
- Weaviate insert: `ensure_visual_collection` checks existence (creates on first run). 10 document dicts assembled. `add_visual_documents` returns 10.
- Processing log entries appended: `pages_extracted:10`, `pages_stored_minio:10`, `pages_embedded:10`, `pages_indexed:10`, `elapsed_s:62.3` (example).

**Final state update returned by visual_embedding_node:**

```
{
  "visual_stored_count": 10,
  "page_images": None,          # cleared — PIL objects freed
  "processing_log": [..., "visual_embedding:pages_extracted:10",
                          "visual_embedding:pages_stored_minio:10",
                          "visual_embedding:pages_embedded:10",
                          "visual_embedding:pages_indexed:10",
                          "visual_embedding:elapsed_s:62.3"]
}
```

**IngestFileResult (final):**

```
IngestFileResult:
  stored_count: 47
  visual_stored_count: 10
  processing_log: [...]
```

---

### Scenario 2: Disabled Path — Visual Embedding Disabled (Zero-Overhead Short-Circuit)

**Setup:** `enable_visual_embedding=False` (default).

The Docling parse node is called with `generate_page_images=False`. No `PdfPipelineOptions` are built; no page images are extracted. `page_images=[]` in `DoclingParseResult`.

In `visual_embedding_node`, the first short-circuit fires immediately:

```python
if not config.enable_visual_embedding:
    return {"visual_stored_count": 0, "page_images": None,
            "processing_log": append_processing_log(state, "visual_embedding:skipped:disabled")}
```

No model load, no MinIO I/O, no Weaviate call. The node returns in microseconds. `IngestFileResult.visual_stored_count = 0`.

---

### Scenario 3: Partial Failure — ColQwen2 Loads but Some Pages Fail Inference

**Setup:** `enable_visual_embedding=True`, 10 pages. Pages 3 and 7 produce malformed tensors during inference.

- Image extraction succeeds for all 10 pages.
- MinIO storage succeeds for all 10 pages. `stored_keys` has 10 entries.
- ColQwen2 loads successfully.
- Batch 1 (pages 1–4): pages 1, 2, 4 produce valid embeddings. Page 3 tensor extraction fails → `logger.warning` emitted, page 3 skipped. Batch continues.
- Batch 2 (pages 5–8): pages 5, 6, 8 produce valid embeddings. Page 7 fails → skipped with warning.
- Batch 3 (pages 9–10): both succeed.
- `embed_page_images` returns 8 `ColQwen2PageEmbedding` records (pages 1, 2, 4, 5, 6, 8, 9, 10).
- ColQwen2 unloaded in `finally`.
- Weaviate insert: 8 documents assembled. `minio_key_map.get(3, "")` and `minio_key_map.get(7, "")` return `""` for the absent pages (those pages have MinIO objects but no embeddings — orphaned images, a known limitation). `add_visual_documents` returns 8.
- Processing log: `pages_extracted:10`, `pages_stored_minio:10`, `pages_embedded:8`, `pages_indexed:8`.
- `IngestFileResult.visual_stored_count = 8`.

**Operator signal:** `pages_embedded < pages_extracted` in the processing log indicates partial inference failure. The WARNING logs include specific page numbers.

---

## 5. Configuration Reference

All six visual embedding parameters are read from environment variables at module-import time in `config/settings.py` and stored as fields on `IngestionConfig`. They are grouped here by module for clarity.

### Ingestion Config (`IngestionConfig` dataclass, sourced from `config/settings.py`)

| Parameter | Env Var | Type | Default | Valid Range | FR | Effect |
|---|---|---|---|---|---|---|
| `enable_visual_embedding` | `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING` | `bool` | `False` | `true`/`false` | FR-101 | Master switch. When `False`, the visual node short-circuits at entry with zero I/O. When `True`, activates the full dual-track pipeline. |
| `visual_target_collection` | `RAG_INGESTION_VISUAL_TARGET_COLLECTION` | `str` | `"RAGVisualPages"` | Any non-empty string | FR-102 | Weaviate collection name for visual page objects. Must be consistent across all ingestion runs that share a Weaviate instance. |
| `colqwen_model_name` | `RAG_INGESTION_COLQWEN_MODEL` | `str` | `"vidore/colqwen2-v1.0"` | Any valid HuggingFace model ID or local path | FR-103 | The ColQwen2 checkpoint to load. Changing this to a different model may produce vectors of a different dimensionality — also update the Weaviate HNSW dimension if so. |
| `colqwen_batch_size` | `RAG_INGESTION_COLQWEN_BATCH_SIZE` | `int` | `4` | 1–32 | FR-104 | Number of page images per ColQwen2 forward pass. Higher values increase throughput but risk GPU OOM. 4 is tuned for the 4 GB VRAM budget. |
| `page_image_quality` | `RAG_INGESTION_PAGE_IMAGE_QUALITY` | `int` | `85` | 1–100 | FR-105 | JPEG compression quality for MinIO uploads. Higher values produce larger objects with fewer artefacts. 85 is a good balance for document pages. |
| `page_image_max_dimension` | `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION` | `int` | `1024` | 256–4096 | FR-106 | Maximum pixel length of the longer image edge after aspect-ratio-preserving resize. Larger values retain more detail at the cost of higher memory and storage. |

### Derived Config

| Parameter | Source | Type | Default | FR | Effect |
|---|---|---|---|---|---|
| `generate_page_images` | Derived from `enable_visual_embedding` | `bool` | `False` | FR-107 | Property alias on `IngestionConfig`. Passed to `parse_with_docling` to enable page image extraction during the Docling parse pass. |

### State Schema (`EmbeddingPipelineState`, `state.py`)

| Field | Type | Default | FR | Description |
|---|---|---|---|---|
| `visual_stored_count` | `int` | `0` | FR-605 | Number of visual page objects successfully inserted into Weaviate for the current document. Written by `visual_embedding_node`. |
| `page_images` | `Optional[List[Any]]` | `None` | FR-602 | PIL images populated by Docling parse node. Consumed and cleared to `None` by `visual_embedding_node` to free memory (FR-606). |

### Pipeline Constants (`types.py`)

| Constant | Value | FR | Description |
|---|---|---|---|
| `PIPELINE_NODE_NAMES` (partial) | `[..., "embedding_storage", "visual_embedding", "knowledge_graph_storage", ...]` | FR-604 | Registry of 15 node names in the embedding pipeline DAG. `"visual_embedding"` is at index 8 (0-based), between `"embedding_storage"` and `"knowledge_graph_storage"`. |

### Weaviate Visual Collection Schema (fixed at `ensure_visual_collection`)

| Property | Weaviate Type | Skip Vectorization | FR | Description |
|---|---|---|---|---|
| `document_id` | TEXT | false | FR-503 | UUID of the ingested document |
| `source_key` | TEXT | false | FR-503, FR-506 | Canonical object-store key for the source file; used as delete key |
| `source_uri` | TEXT | false | FR-503 | URI of the source file |
| `source_name` | TEXT | false | FR-503 | Human-readable source file name |
| `tenant_id` | TEXT | false | FR-503 | Tenant identifier (empty string for single-tenant deployments) |
| `page_number` | INT | — | FR-503 | 1-indexed page number |
| `total_pages` | INT | — | FR-503 | Total pages in the source document |
| `page_width_px` | INT | — | FR-503 | Original page width in pixels (pre-resize) |
| `page_height_px` | INT | — | FR-503 | Original page height in pixels (pre-resize) |
| `minio_key` | TEXT | false | FR-503 | MinIO object key for the stored JPEG |
| `patch_vectors` | TEXT | **true** | FR-505 | JSON-serialised `list[list[float]]` of per-patch ColQwen2 embeddings |
| `mean_vector` (named vector) | HNSW, 128-dim, cosine | — | FR-504 | 128-dim mean-pooled vector; used for ANN search |

### Config Validation (`settings.py`, FR-108)

On startup with `enable_visual_embedding=True`, the following checks must pass or the ingestion worker exits with a clear error:

- Docling must be installed (required for `generate_page_images=True`).
- `colqwen_batch_size` must be in range [1, 32].
- `page_image_quality` must be in range [1, 100].
- `page_image_max_dimension` must be in range [256, 4096].

---

## 6. Integration Contracts

### Entry Point

```python
visual_embedding_node(state: EmbeddingPipelineState) -> dict
```

The node is a standard LangGraph node function. It receives the full `EmbeddingPipelineState` and returns a partial state dict containing only the keys it owns. It does not raise exceptions to the graph orchestrator under any failure mode — all errors are caught internally and result in `visual_stored_count=0`.

### Input Contract

The following state fields are **read** by `visual_embedding_node`:

| Field | Required | Description |
|---|---|---|
| `config` | Yes | `IngestionConfig` instance; must be present and valid |
| `document_id` | Yes | `str` UUID of the document being ingested |
| `source_key` | Yes | `str` canonical storage key for the source file |
| `docling_document` | Conditional | `DoclingDocument` object; if absent, node short-circuits with `visual_embedding:skipped:no_docling_document` |
| `page_images` | Optional | `list[PIL.Image]` pre-rendered by Docling parse; if absent, fallback to `DoclingDocument.pages` |
| `source_uri` | Optional | `str` used to populate Weaviate `source_uri` property |
| `source_name` | Optional | `str` used to populate Weaviate `source_name` property |
| `processing_log` | Optional | Existing log list; new entries appended and returned |
| `errors` | Optional | Existing error list; new entries appended and returned |

External runtime dependencies (passed via config/environment, not via state):

| Dependency | How provided | Requirement |
|---|---|---|
| Weaviate v4 client | `state["runtime"].weaviate_client` or equivalent | Weaviate must be running and reachable; `RAGVisualPages` collection will be created on first use |
| MinIO client | `state["runtime"].minio_client` or equivalent | MinIO must be running; target bucket must exist |
| CUDA-capable GPU | System environment | Required for ColQwen2 inference; at least 4 GB VRAM free when the visual node runs |
| `colpali-engine` + `bitsandbytes` | Python environment | Must be installed via `pip install "rag[visual]"`; absence causes a fatal `ColQwen2LoadError` |

### Output Contract

The node returns a dict with the following keys. All text-track keys are **absent**:

| Key | Type | Description |
|---|---|---|
| `visual_stored_count` | `int` | Number of visual page objects inserted into Weaviate. 0 on any failure or short-circuit. |
| `page_images` | `None` | Always `None` on return; clears PIL objects from LangGraph state to free memory (FR-606). |
| `processing_log` | `list[str]` | Updated processing log with up to 5 new entries (FR-701 through FR-705). |
| `errors` | `list[str]` | Updated error list; present only on non-zero error conditions. |

### Install Requirements

```bash
# Minimal: text track only (no GPU required)
pip install rag

# Full: text + visual track (requires CUDA environment)
pip install "rag[visual]"

# Equivalent explicit install
pip install rag colpali-engine bitsandbytes
```

The `[visual]` extras gate is enforced at runtime by `ensure_colqwen_ready()`, not at import time. The visual embedding module can be imported in any environment; the failure only occurs when `visual_embedding_node` attempts to load the model.

### External Service Assumptions

| Service | Version | Assumption |
|---|---|---|
| Weaviate | v4 | Named vector API available (`weaviate.classes.config.NamedVectors`); `batch.dynamic()` supported |
| MinIO | Any | Bucket pre-created; `put_object`, `list_objects`, `remove_object` available |
| HuggingFace Hub | — | Accessible on first run for model download; subsequent runs use local cache |

---

## 7. Operational Notes

### Activating Visual Embedding

Set the master switch before starting the ingestion worker:

```bash
export RAG_INGESTION_ENABLE_VISUAL_EMBEDDING=true
```

On first run with a new Weaviate instance, `ensure_visual_collection` will create the `RAGVisualPages` collection automatically. No manual schema migration is required.

### VRAM Budget

The visual embedding pipeline is designed for an RTX 2060 (6 GB VRAM) but validated against the 4 GB constraint (NFR-901):

| Model | VRAM footprint | When resident |
|---|---|---|
| BGE-M3 | ~1.5 GB | During text embedding nodes only |
| ColQwen2 @ 4-bit | ~2.0 GB | During visual_embedding_node only |
| Peak overlap | 0 GB | Sequential: BGE-M3 fully unloads before ColQwen2 loads |
| Peak ceiling | ~2.0 GB | At any single point |

**Do not** hold BGE-M3 resident across the visual node. If the text embedding implementation changes to cache the model between documents, verify that the cache is flushed before the visual node runs.

### Model Download (First Run)

On the first run with `enable_visual_embedding=True`, `load_colqwen_model("vidore/colqwen2-v1.0")` will download approximately 2 GB of model weights from HuggingFace Hub. Subsequent runs use the local cache (`~/.cache/huggingface/`). In air-gapped environments, pre-download the model and set `RAG_INGESTION_COLQWEN_MODEL` to the local path.

### Monitoring Signals

The `processing_log` list in `IngestFileResult` provides five telemetry signals per document for the visual track:

| Signal | Normal range | Action if abnormal |
|---|---|---|
| `visual_embedding:pages_extracted:<N>` | N = total pages | N=0: check `generate_page_images` derivation and Docling parse result |
| `visual_embedding:pages_stored_minio:<N>` | N = pages_extracted | N < extracted: check MinIO connectivity and disk space |
| `visual_embedding:pages_embedded:<N>` | N = pages_extracted | N < extracted: check GPU memory, inspect WARNING logs for page numbers |
| `visual_embedding:pages_indexed:<N>` | N = pages_embedded | N < embedded: check Weaviate connectivity and collection health |
| `visual_embedding:elapsed_s:<F>` | F ≈ 5–10 s/page | F >> expected: GPU contention or slow model load |

`IngestFileResult.visual_stored_count` provides the summary count for upstream monitoring.

### Failure Modes and Debug Paths

**`ColQwen2LoadError`: packages not installed**

```
ERROR visual_embedding:colqwen_load:Required package(s) not installed: colpali-engine, bitsandbytes.
Install with: pip install "rag[visual]"
```

Resolution: run `pip install "rag[visual]"` in the worker environment and restart.

**`ColQwen2LoadError`: model download fails**

The `from_pretrained` call raises and is wrapped in `ColQwen2LoadError`. Check network access to `huggingface.co`, or set `RAG_INGESTION_COLQWEN_MODEL` to a local cached path.

**Partial MinIO upload (`pages_stored_minio < pages_extracted`)**

Inspect WARNING logs for `store_page_images` entries. Common causes: MinIO bucket full, network timeout, oversized page image. The orphaned JPEG (if any) will be cleaned up on the next ingestion run of the same document.

**Partial Weaviate indexing (`pages_indexed < pages_embedded`)**

`add_visual_documents` returned a count below `len(documents)`. Inspect Weaviate logs for batch insert errors. Common causes: Weaviate disk full, schema mismatch (collection exists with wrong vector dimensions), client version incompatibility.

**`visual_embedding:skipped:no_docling_document`**

The `docling_document` field was absent from state. This can happen if `persist_docling_document=False` in the ingestion config and the Docling parse result was not forwarded to the embedding pipeline. Ensure `persist_docling_document=True` when `enable_visual_embedding=True`.

---

## 8. Known Limitations

**1. Retrieval side not yet implemented.**
The `RAGVisualPages` collection is populated and queryable, but no retrieval node performs ANN search against `mean_vector` or MaxSim re-scoring against `patch_vectors`. The patch vectors are stored in preparation for a future retrieval implementation. Retrieval clients must query Weaviate directly using the named-vector API until a retrieval node is added.

**2. `patch_vectors` stored as JSON TEXT, not natively indexed.**
MaxSim re-scoring requires deserialising the `patch_vectors` TEXT field and running the scoring computation in application-side Python/NumPy. There is no native MaxSim operator in Weaviate's current API. Full-dataset MaxSim without ANN pre-filtering is not feasible at scale. This is a design trade-off, not an oversight — see the Architecture Decisions section for rationale.

**3. Slide-boundary handling for PPTX is out of scope.**
The current implementation treats each Docling-rendered page as a uniform unit. For PowerPoint presentations, slide boundaries may not align cleanly with Docling's page segmentation. Per-slide visual embedding for PPTX is not addressed in this release.

**4. Multi-GPU parallelism not supported.**
`device_map="auto"` can shard ColQwen2 across multiple GPUs if available, but the batch inference loop does not explicitly parallelise across GPUs or across documents. Each document is processed sequentially in a single forward pass sequence.

**5. Page images are ephemeral — not re-creatable from persisted `DoclingDocument`.**
The `generate_page_images=True` flag must be set at parse time. Page images are rendered by Docling during `convert()` and are not serialised into the `DoclingDocument` JSON. If the `DoclingDocument` is stored but the parse result's `page_images` list is lost (e.g., due to a worker restart between parse and embedding stages), the images cannot be recovered without re-parsing the source file.

**6. Schema mismatch on `ensure_visual_collection` is silent.**
If the `RAGVisualPages` collection exists with a different HNSW dimension or distance metric, `ensure_visual_collection` will not detect or correct the discrepancy — it returns immediately on existence. Inserts into a schema-mismatched collection will fail at the Weaviate level. Operators must drop and recreate the collection manually if the schema needs to change.

**7. `delete_page_images` early-exits on first per-object failure.**
If a MinIO `remove_object` call fails mid-cleanup, remaining objects under the `pages/{document_id}/` prefix are not deleted. Re-running the ingestion will attempt cleanup again, but orphaned objects may accumulate if cleanup failures are systematic (e.g., permission issues).

---

## 9. Extension Guide

### Adding a New Visual Model (Not ColQwen2)

The ColQwen2 adapter is self-contained in `src/ingest/support/colqwen.py`. To add a new model (e.g., a different ColPali checkpoint or an entirely different vision encoder):

1. Create `src/ingest/support/<modelname>.py` following the same four-phase lifecycle pattern: `ensure_<model>_ready`, `load_<model>_model`, `embed_page_images_<model>`, `unload_<model>_model`. The return type must be a list of records with `page_number`, `mean_vector: list[float]`, and (optionally) `patch_vectors: list[list[float]]`.
2. Add the model name to a `visual_model_backend` config field in `IngestionConfig` (new field in `types.py`, new env var in `settings.py`).
3. In `visual_embedding.py`, add a dispatch block that selects the correct adapter based on `config.visual_model_backend`. The rest of the node (MinIO storage, Weaviate insert) remains unchanged.
4. If the new model produces a different vector dimensionality, also update the `dimensions` parameter in `ensure_visual_collection`. Note: changing dimensions requires recreating the `RAGVisualPages` collection.
5. Declare the new model's dependencies under a new `[visual-<modelname>]` extras group in `pyproject.toml` to preserve the optional-dependency pattern.

### Changing the Visual Collection Schema

The `RAGVisualPages` schema is defined in `ensure_visual_collection` in `src/vector_db/weaviate/visual_store.py`. To add, remove, or rename properties:

1. Update the property list in `ensure_visual_collection`.
2. **Important:** `ensure_visual_collection` is idempotent on creation but does not migrate existing schemas. A collection with the old schema will not be updated. You must drop the collection and re-create it:
   ```python
   client.collections.delete("RAGVisualPages")
   ensure_visual_collection(client, "RAGVisualPages")
   ```
3. Re-ingest all documents to repopulate the collection with the new schema.
4. If adding a property that the ingestion node should populate, update the document dict construction in `visual_embedding_node` (the `documents.append(...)` block in step 7).

### Adding Native MaxSim to Weaviate

When Weaviate adds native multi-vector late-interaction support:

1. In `ensure_visual_collection`, add a second named vector (e.g., `"patch_vectors"`) with the appropriate multi-vector configuration. The dimensionality will be `[n_patches, 128]`, which requires a Weaviate multi-vector index type.
2. In `add_visual_documents`, update the `vector` dict to include both `"mean_vector"` and `"patch_vectors"` (deserialised from JSON back to a list-of-lists).
3. Remove or deprecate the `patch_vectors` TEXT property (or keep it for backward compatibility with old clients).
4. Update the retrieval layer to use the native MaxSim operator instead of application-side scoring.
5. The ingestion side (ColQwen2 inference, `patch_vectors` extraction) requires no changes — the data is already being produced.

### Enabling Per-Tenant Collection Isolation

The `visual_target_collection` config parameter accepts any string. To isolate visual pages by tenant:

1. Set `RAG_INGESTION_VISUAL_TARGET_COLLECTION=RAGVisualPages_<tenant_id>` per tenant (e.g., via per-tenant environment variable injection in your orchestration layer).
2. `ensure_visual_collection` will create the tenant-specific collection on first use (idempotent).
3. `delete_visual_by_source_key` and `add_visual_documents` will target the tenant-specific collection when called with the tenant-prefixed name.
4. The retrieval layer must be updated to query the correct per-tenant collection name. Expose the collection name as a query parameter or tenant context.
5. Monitor collection count in Weaviate — each tenant creates one collection. If tenant count is large, evaluate whether Weaviate multi-tenancy (single collection with tenant partitioning) is a better fit than per-tenant collections.

---

## Appendix: Requirement Coverage

This table maps each functional requirement (FR) and non-functional requirement (NFR) from the companion spec to the module(s) that implement it.

| Requirement | Description (abbreviated) | Implementing Module(s) |
|---|---|---|
| FR-101 | `enable_visual_embedding` bool flag, default False | `config/settings.py`, `types.py`, `visual_embedding.py` |
| FR-102 | `visual_target_collection` str, default "RAGVisualPages" | `config/settings.py`, `types.py`, `visual_embedding.py`, `visual_store.py` |
| FR-103 | `colqwen_model_name` str, default "vidore/colqwen2-v1.0" | `config/settings.py`, `types.py`, `colqwen.py` |
| FR-104 | `colqwen_batch_size` int, default 4, range 1–32 | `config/settings.py`, `types.py`, `colqwen.py` |
| FR-105 | `page_image_quality` int, default 85, range 1–100 | `config/settings.py`, `types.py`, `store.py` (MinIO) |
| FR-106 | `page_image_max_dimension` int, default 1024, range 256–4096 | `config/settings.py`, `types.py`, `visual_embedding.py` |
| FR-107 | `generate_page_images` derived from `enable_visual_embedding` | `types.py`, `docling.py` |
| FR-108 | Validate config at startup | `config/settings.py`, `types.py` |
| FR-109 | All 6 params as `RAG_INGESTION_*` env vars | `config/settings.py` |
| FR-201 | Extract page images from `docling_document`; 1-indexed | `docling.py`, `visual_embedding.py` |
| FR-202 | Resize pages, preserve aspect ratio | `visual_embedding.py` |
| FR-203 | Short-circuit when 0 extractable pages | `visual_embedding.py` |
| FR-204 | Convert each page to RGB color space | `docling.py`, `visual_embedding.py` |
| FR-205 | `page_count` always set even on partial failure | `docling.py` |
| FR-301 | Load via colpali-engine with 4-bit bitsandbytes quantization | `colqwen.py` |
| FR-302 | Per-page embeddings with 1-indexed page numbers | `colqwen.py` |
| FR-303 | 128-dim mean-pooled vector via mean over patch axis | `colqwen.py` |
| FR-304 | Raw patch vectors as `list[list[float]]` (JSON-serializable) | `colqwen.py` |
| FR-305 | Unload model after inference | `colqwen.py`, `visual_embedding.py` |
| FR-306 | Log progress at ~10% intervals for >10 pages | `colqwen.py` |
| FR-307 | Individual page failures skip that page | `colqwen.py` |
| FR-401 | Per-page error isolation in MinIO storage | `store.py` (MinIO) |
| FR-402 | Configurable JPEG quality | `store.py` (MinIO) |
| FR-403 | Return stored key list | `store.py` (MinIO) |
| FR-404 | Pre-cleanup of existing visual data before re-ingest | `visual_embedding.py` |
| FR-405 | Update-mode cleanup | `visual_embedding.py`, `store.py` (MinIO) |
| FR-501 | Dedicated Weaviate collection for visual pages | `visual_store.py`, `backend.py` |
| FR-502 | Idempotent collection creation | `visual_store.py` |
| FR-503 | Collection schema properties (11 properties) | `visual_store.py` |
| FR-504 | Named vector "mean_vector" 128-dim HNSW cosine | `visual_store.py` |
| FR-505 | `patch_vectors` stored as TEXT with `skip_vectorization=True` | `visual_store.py` |
| FR-506 | Delete by `source_key` (bulk filter delete) | `visual_store.py` |
| FR-507 | Batch insert, return count | `visual_store.py` |
| FR-601 | `visual_embedding` node positioned between `embedding_storage` and `kg_storage` | `workflow.py` |
| FR-602 | `page_images` field in `EmbeddingPipelineState` | `state.py` |
| FR-603 | Short-circuit when disabled | `visual_embedding.py` |
| FR-604 | `"visual_embedding"` in `PIPELINE_NODE_NAMES` | `types.py` |
| FR-605 | `visual_stored_count` in `IngestFileResult` | `types.py` |
| FR-606 | Clear `page_images` after node to free memory | `visual_embedding.py` |
| FR-701 | `visual_embedding:pages_extracted:<N>` log entry | `visual_embedding.py` |
| FR-702 | `visual_embedding:pages_stored_minio:<N>` log entry | `visual_embedding.py` |
| FR-703 | `visual_embedding:pages_embedded:<N>` log entry | `visual_embedding.py` |
| FR-704 | `visual_embedding:pages_indexed:<N>` log entry | `visual_embedding.py` |
| FR-705 | `visual_embedding:elapsed_s:<F>` log entry | `visual_embedding.py` |
| FR-801 | Per-page failure isolation | `colqwen.py`, `store.py`, `visual_embedding.py` |
| FR-802 | ColQwen2 model load failure is fatal | `colqwen.py`, `visual_embedding.py` |
| FR-803 | Visual track failures must not affect text track state | `visual_embedding.py` |
| FR-806 | `ensure_colqwen_ready` raises with pip install command | `colqwen.py` |
| NFR-901 | Peak VRAM ≤ 4 GB during visual inference | `colqwen.py` (4-bit quant), `visual_embedding.py` (sequential GPU) |
| NFR-902 | 4-bit quantization required (float16 compute dtype) | `colqwen.py` |
| NFR-903 | Zero overhead when visual embedding disabled | `visual_embedding.py` (short-circuit at entry) |
| NFR-905 | Config validation before processing | `config/settings.py`, `types.py` |
| NFR-906 | `colpali-engine` + `bitsandbytes` as optional `[visual]` extras | `pyproject.toml`, `colqwen.py` |
| NFR-909 | Existing ABC methods untouched by visual additions | `backend.py` (three new methods only) |
