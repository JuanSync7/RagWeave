### `src/ingest/common/types.py` — IngestionConfig and Pipeline Contracts

**Purpose:**

This module defines the central configuration dataclass (`IngestionConfig`), the node-name registry (`PIPELINE_NODE_NAMES`), and the supporting dataclasses (`Runtime`, `IngestState`, `IngestFileResult`, `IngestionRunSummary`, `IngestionDesignCheck`) used throughout the ingestion pipeline. It is the single source of truth for all pipeline knobs: enabling or disabling optional stages, setting model parameters, and now controlling the Docling-native chunking path via three new fields (`vlm_mode`, `hybrid_chunker_max_tokens`, `persist_docling_document`). It also defines the LangGraph `IngestState` TypedDict that carries state across all pipeline nodes. (FR-2401–FR-2407, FR-2501–FR-2505)

**How it works:**

At module load time, the file imports the three Docling-native chunking constants from `config/settings.py` — `RAG_INGESTION_VLM_MODE`, `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS`, and `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT` — and uses them as default values for new fields on the `IngestionConfig` dataclass.

**`PIPELINE_NODE_NAMES`** is a plain list of string node names in execution order. After the redesign, `"vlm_enrichment"` is inserted between `"chunking"` and `"chunk_enrichment"`. This list is used by logging, monitoring, and the orchestrator to enumerate expected pipeline stages.

**`IngestionConfig`** is a Python `dataclass` with field-level defaults sourced from `config/settings.py`. The three new Docling-native chunking fields are:

- `vlm_mode: str = RAG_INGESTION_VLM_MODE` — controls which VLM enrichment path to use. Valid values: `"disabled"`, `"builtin"`, `"external"`.
- `hybrid_chunker_max_tokens: int = RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS` — the maximum token count per chunk for `HybridChunker`. Defaults to 512 (bge-m3 limit).
- `persist_docling_document: bool = RAG_INGESTION_PERSIST_DOCLING_DOCUMENT` — whether to write the `DoclingDocument` JSON to `CleanDocumentStore`. Defaults to `True`.

All other fields are unchanged from the pre-redesign implementation.

**`IngestState`** is a `TypedDict` (non-total by convention, though declared as `TypedDict` without `total=False` here — nodes return partial dicts that LangGraph merges). The state does not carry `docling_document` directly on `IngestState` — that field lives on `DocumentProcessingState` and `EmbeddingPipelineState` in their respective sub-modules.

**`Runtime`** is a dataclass holding expensive shared dependencies: the embedder, Weaviate client, KG builder, and optional DB client. It is constructed once per batch run and passed into every pipeline node.

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| `IngestionConfig` as `dataclass` with env-var defaults | Pydantic model with validators; plain dict | A dataclass provides typed, IDEable fields with defaults, no validator overhead at construction time. Pydantic would add latency on every instantiation and require explicit validators for cross-field rules. |
| `PIPELINE_NODE_NAMES` as a flat list (not derived from graph) | Derive dynamically from compiled LangGraph | Dynamic derivation couples the list to graph compilation. A flat list is auditable, diffable, and does not require graph compilation at import time. |
| `vlm_enrichment` node added to `PIPELINE_NODE_NAMES` | Add it only in the embedding workflow, not the shared list | The shared list is used for monitoring and logging. Adding the node here ensures it appears in processing logs and dashboards even before the workflow wires it in. |
| Three separate config fields instead of one compound `DoclingConfig` sub-object | A nested `DoclingConfig` dataclass; a dict | Flat fields are simpler to override individually from env vars and are directly accessible without attribute chaining. The number of new fields (3) does not justify nesting overhead. |

**Configuration:**

| Parameter | Type | Default | Valid Range / Options | Effect |
|-----------|------|---------|----------------------|--------|
| `vlm_mode` | `str` | `"disabled"` | `"disabled"`, `"builtin"`, `"external"` | Passed to `parse_with_docling()` and read by `vlm_enrichment_node` to determine which VLM path to activate. |
| `hybrid_chunker_max_tokens` | `int` | `512` | Positive integer; values above 512 trigger a design warning | Passed to `HybridChunker(max_tokens=...)` in `chunking_node`. |
| `persist_docling_document` | `bool` | `True` | `True` or `False` | Read by `ingest_file()` in `src/ingest/impl.py` to decide whether to call `store.write(..., docling_document=...)`. |

**Error behavior:**

`IngestionConfig` construction never raises — all fields have defaults. Validation of field value constraints (e.g., `vlm_mode` must be one of three strings) is deferred to `verify_core_design()` in `src/ingest/impl.py`, which is called before processing begins.

`Runtime` construction can raise if the embedder or Weaviate client initialization fails, but that is unrelated to the Docling-native chunking fields.

`IngestState` is a TypedDict — it has no constructor and raises no errors. Missing fields surface as `KeyError` at runtime in nodes that access them without `state.get()`.
