### `config/settings.py` — Visual Embedding Configuration Constants

**Purpose:** Declares the six environment-variable-backed constants that control the visual embedding pipeline. Every constant has a hardcoded default so the pipeline runs safely without any environment configuration; setting `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING=true` is the only change required to activate the feature.

**How it works:** Each constant is read from `os.environ` at module-import time using `.get(name, default)`. Boolean coercion normalises the strings `"true"`, `"1"`, and `"yes"` to `True`; everything else is `False`. Integer constants use `int(os.environ.get(...))`. The constants are imported by `src/ingest/common/types.py` to seed the `IngestionConfig` dataclass defaults, and by validation logic in `src/ingest/impl.py`.

**Key design decisions:**

| Decision | Rationale |
|---|---|
| All six constants use `os.environ` (FR-109) | Environment-variable backing is the single source of truth; no config file divergence at deploy time. |
| Default for `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING` is `"false"` | Feature is opt-in; existing deployments are unaffected without explicit activation. |
| Boolean uses three-value string set (`"true"`, `"1"`, `"yes"`) | Matches the normalisation convention used by every other boolean constant in this file. |
| Integer coercion done at declaration site | Fails loudly at startup if an env var holds a non-integer string, not silently at first use. |

**Configuration:**

| Environment Variable | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING` | bool | `false` | `true`/`false` (also `1`/`yes`) | Activates the dual-track visual embedding pipeline (FR-101). When `false` the `visual_embedding` node short-circuits immediately. |
| `RAG_INGESTION_VISUAL_TARGET_COLLECTION` | str | `"RAGVisualPages"` | Any non-empty string | Weaviate collection name where visual page objects are stored (FR-102). |
| `RAG_INGESTION_COLQWEN_MODEL` | str | `"vidore/colqwen2-v1.0"` | Any HuggingFace model identifier | ColQwen2 model loaded for multi-vector visual embedding inference (FR-103). |
| `RAG_INGESTION_COLQWEN_BATCH_SIZE` | int | `4` | 1–32 | Number of page images processed per ColQwen2 forward pass (FR-104). |
| `RAG_INGESTION_PAGE_IMAGE_QUALITY` | int | `85` | 1–100 | JPEG compression quality for page images stored in MinIO (FR-105). |
| `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION` | int | `1024` | 256–4096 | Maximum pixel length of the longer edge after proportional resize (FR-106). |

**Error behavior:** Integer constants raise `ValueError` at module import if the corresponding environment variable holds a non-integer string (e.g. `RAG_INGESTION_COLQWEN_BATCH_SIZE=auto`). Out-of-range values (e.g. batch size 0 or 64) are not caught here; they are caught later by `_check_visual_embedding_config` in `src/ingest/impl.py` (FR-108, NFR-905). Boolean constants that receive an unrecognised string (e.g. `"yes_please"`) silently evaluate to `False` due to the membership test.

---

### `src/ingest/common/types.py` — IngestionConfig Visual Extensions

**Purpose:** Extends the `IngestionConfig` dataclass with the six visual-embedding fields and a derived property, and extends `IngestFileResult` with a `visual_stored_count` counter. These additions widen the typed configuration and result contracts used across the ingestion pipeline without breaking existing callers that rely on default values.

**How it works:** Six new fields are appended to the `IngestionConfig` dataclass. Each field's default is the corresponding constant imported from `config/settings.py`, so a caller that instantiates `IngestionConfig()` with no arguments receives the correct environment-driven defaults automatically. The `generate_page_images` property is a derived boolean alias for `enable_visual_embedding`; it exists so node code can query a semantically clear name rather than the configuration flag name. `IngestFileResult.visual_stored_count` defaults to `0` and is incremented by the `visual_embedding` node upon successful storage of each page object. `PIPELINE_NODE_NAMES` gains `"visual_embedding"` between `"embedding_storage"` and `"knowledge_graph_storage"`, bringing the registry to 15 entries (FR-604).

**Key design decisions:**

| Decision | Rationale |
|---|---|
| Fields appended to existing dataclass rather than a separate config class | Avoids a nested config object; all ingestion configuration remains flat and discoverable in one place. |
| Defaults delegate to `config/settings.py` constants | Single source of truth for defaults; tests can override per-instance without touching env vars. |
| `generate_page_images` property instead of a second field (FR-107) | Removes dual-maintenance of a redundant flag; a property makes the derivation explicit and eliminates the possibility of the two flags disagreeing. |
| `visual_stored_count` on `IngestFileResult` (FR-605) | Exposes a measurable output for callers (e.g. Temporal activities, CLI reporting) without coupling them to internal state. |

**Configuration:**

| `IngestionConfig` field | Type | Default | Valid Range | Effect |
|---|---|---|---|---|
| `enable_visual_embedding` | `bool` | `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING` | `True`/`False` | Master switch for the visual embedding track (FR-101). |
| `visual_target_collection` | `str` | `RAG_INGESTION_VISUAL_TARGET_COLLECTION` | Non-empty string | Weaviate collection that receives visual page objects (FR-102). |
| `colqwen_model_name` | `str` | `RAG_INGESTION_COLQWEN_MODEL` | Any HuggingFace model identifier | ColQwen2 model used for multi-vector inference (FR-103). |
| `colqwen_batch_size` | `int` | `RAG_INGESTION_COLQWEN_BATCH_SIZE` | 1–32 | Pages per inference batch (FR-104). Validated at startup. |
| `page_image_quality` | `int` | `RAG_INGESTION_PAGE_IMAGE_QUALITY` | 1–100 | JPEG quality for stored page images (FR-105). Validated at startup. |
| `page_image_max_dimension` | `int` | `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION` | 256–4096 | Max pixel dimension after proportional resize (FR-106). Validated at startup. |

**Error behavior:** `_check_visual_embedding_config` in `src/ingest/impl.py` is called during `verify_core_design()` and returns `(errors, warnings)`. The function returns `([], [])` immediately when `enable_visual_embedding` is `False`, so disabled configurations incur no validation overhead. When visual embedding is enabled, the following conditions produce hard errors that abort startup (FR-108, NFR-905):

- `enable_visual_embedding=True` with `enable_docling_parser=False` — the visual track requires Docling-generated page images; without it the pipeline cannot produce `page_images`.
- `colqwen_batch_size` outside 1–32 — raises a configuration error naming the out-of-range value and the accepted range.
- `page_image_quality` outside 1–100 — raises a configuration error.
- `page_image_max_dimension` outside 256–4096 — raises a configuration error.

---

### `src/ingest/embedding/state.py` — EmbeddingPipelineState Visual Extensions

**Purpose:** Adds two optional fields to `EmbeddingPipelineState` that carry visual-embedding data through the LangGraph DAG. `visual_stored_count` accumulates the number of successfully stored visual page objects. `page_images` holds the list of `PIL.Image` objects produced upstream and consumed by the `visual_embedding` node.

**How it works:** `EmbeddingPipelineState` is a `TypedDict` with `total=False`, meaning all fields are optional by declaration. The two new fields follow the same pattern as every existing field in the dict: they are declared with Python type annotations and no default values (TypedDict does not support defaults). The node that populates `page_images` writes it into the returned state dict; the `visual_embedding` node reads it, processes it, writes `visual_stored_count`, and then writes `page_images` back as `None` or an empty list to release memory (FR-606). Downstream nodes see `visual_stored_count` as a read-only counter; they do not observe `page_images` because it has been cleared.

**Key design decisions:**

| Decision | Rationale |
|---|---|
| `page_images: Optional[List[Any]]` typed as `Any` elements (FR-602) | Avoids a hard import of `PIL.Image` in the state schema module; the concrete type is validated at the node boundary where PIL is already imported. |
| `page_images` cleared after the node (FR-606) | PIL images are large in-memory objects; clearing them immediately after consumption prevents the LangGraph checkpoint from holding onto multi-megabyte buffers for the remainder of the DAG. |
| `visual_stored_count` defaults to `0` by convention | `total=False` means the field may be absent; nodes that read it should use `state.get("visual_stored_count", 0)`. Setting it to `0` on first write is the node's responsibility. |
| Both fields are optional (`total=False`) | Consistent with the rest of `EmbeddingPipelineState`; nodes that run before visual embedding exist can return state dicts that omit these keys entirely without type errors. |

**Configuration:** This module has no configurable parameters.

**Error behavior:** `EmbeddingPipelineState` is a plain `TypedDict` and performs no runtime validation. If `page_images` is absent or `None` when the `visual_embedding` node runs, the node must handle the missing key gracefully (short-circuit or raise a descriptive `KeyError` with context). If `visual_stored_count` is absent in state passed to a downstream consumer, callers must use `state.get("visual_stored_count", 0)` to avoid a `KeyError`. No exceptions originate from this module itself.

---

### `src/ingest/embedding/workflow.py` — LangGraph Workflow Wiring

**Purpose:** Inserts the `visual_embedding` node into the compiled LangGraph DAG and rewires the edge between `embedding_storage` and `knowledge_graph_storage` to route through it. This file owns the graph topology; all short-circuit logic for the disabled case lives inside the node implementation, keeping the wiring unconditional.

**How it works:** `build_embedding_graph()` adds `visual_embedding_node` as a named node, then registers two edges: `embedding_storage → visual_embedding` and `visual_embedding → knowledge_graph_storage` (or `END` via the existing conditional). The previous direct edge from `embedding_storage → knowledge_graph_storage` is removed. The result is a 10-node DAG. The full node order is:

```
document_storage
  → chunking
    → vlm_enrichment
      → chunk_enrichment
        → metadata_generation
          → [cross_reference_extraction →]
            knowledge_graph_extraction
              → quality_validation
                → embedding_storage
                  → visual_embedding
                    → [knowledge_graph_storage]
```

Square brackets denote nodes that are present only when their respective feature flags are enabled via conditional edges. `visual_embedding` itself is always present in the graph; the enable/disable decision is made inside the node body, not by a conditional edge.

**Key design decisions:**

| Decision | Rationale |
|---|---|
| Unconditional edge into `visual_embedding`; disable logic inside the node | Keeps the graph topology static and inspectable. A conditional edge would require the topology to vary based on config at graph-compile time, making the compiled graph harder to reason about and test. |
| `visual_embedding` is placed between `embedding_storage` and `knowledge_graph_storage` (FR-601) | Text embeddings are fully committed before visual embeddings begin, so a failure in the visual track does not roll back text embedding work. Knowledge graph storage, which may depend on chunk IDs produced by embedding storage, is not blocked by visual embedding time. |
| Import of `visual_embedding_node` is local to `workflow.py` | Follows the existing pattern for all other node imports; each node file is independently importable and the workflow file is the single assembly point. |
| Node name `"visual_embedding"` added to `PIPELINE_NODE_NAMES` in `types.py` (FR-604) | The registry is the authoritative list of node names for telemetry, progress reporting, and test fixtures; the string must match the name passed to `graph.add_node`. |

**Configuration:** This module has no configurable parameters. Feature activation is read by the node at runtime from `IngestionConfig.enable_visual_embedding`.

**Error behavior:** If `visual_embedding_node` raises an unhandled exception, LangGraph propagates it to the caller of `graph.invoke()` in the normal way, halting the DAG at that node. Partial results from `embedding_storage` are already committed at that point; the run is not automatically retried or rolled back by this module. If the import of `visual_embedding_node` fails at module load time (e.g. because the `colqwen` dependency is missing), the entire `workflow.py` module fails to import, which surfaces as an `ImportError` on worker startup before any documents are processed.
