### `src/ingest/impl.py` — Ingestion Orchestrator

**Purpose:**

This module is the public-facing orchestrator for the ingestion pipeline. It provides `ingest_file` (single-file two-phase ingestion), `ingest_directory` (batch ingestion with idempotency), and `verify_core_design` (configuration validation). In the context of the Docling-native chunking redesign, two key responsibilities were added: (1) passing `docling_document` from the Phase 1 output to `CleanDocumentStore` — conditioned on `config.persist_docling_document` — and (2) reading it back for Phase 2 initialization via `store.read_docling()`. The module also hosts `_check_docling_chunking_config`, which validates the three new config fields before any processing begins. (FR-2009, FR-2401)

**How it works:**

**`verify_core_design(config)`** validates the full `IngestionConfig`. After the redesign it delegates to `_check_docling_chunking_config(config)` which checks:
1. `vlm_mode` must be one of `{"disabled", "builtin", "external"}` — invalid values become hard errors.
2. If `vlm_mode == "builtin"`: tries `from docling.document_converter import DocumentConverter`. If this import fails, adds a hard error: `"vlm_mode=builtin requires docling to be installed"`.
3. If `vlm_mode == "external"` and neither `config.vision_model` nor `LLM_ROUTER_CONFIG` is set: adds a warning (not an error) that VLM enrichment will be skipped at runtime.
4. If `hybrid_chunker_max_tokens > 512`: adds a warning that chunks may be silently truncated during embedding.

Errors from `_check_docling_chunking_config` are appended to the main errors list. Warnings are appended to the warnings list. `verify_core_design` returns `IngestionDesignCheck(ok=not errors, errors=errors, warnings=warnings)`. `ingest_directory` calls `verify_core_design` and raises `ValueError` if `design.ok` is `False`.

**`ingest_file(...)` — Phase 1/Phase 2 boundary handoff:**
The critical Docling-native chunking logic is in the Phase 1 → CleanDocumentStore → Phase 2 sequence:

```python
# Phase 1 → CleanDocumentStore write:
store.write(
    source_key,
    clean_text,
    meta,
    docling_document=phase1.get("docling_document") if config.persist_docling_document else None,
)

# Phase 2 initialization with DoclingDocument:
phase2 = run_embedding_pipeline(
    ...
    docling_document=store.read_docling(source_key) if store is not None else None,
)
```

When `config.persist_docling_document` is `True` and `phase1.get("docling_document")` is not `None`, the `DoclingDocument` is written to `CleanDocumentStore`. When Phase 2 starts, `store.read_docling(source_key)` deserializes it and passes it to `run_embedding_pipeline`, which loads it into `EmbeddingPipelineState["docling_document"]`. `chunking_node` then reads `state.get("docling_document")` and selects the HybridChunker path.

When `config.persist_docling_document` is `False`, `None` is passed to `store.write()` (no `.docling.json` written), and `store.read_docling()` returns `None` — `chunking_node` falls back to markdown.

When `clean_store_dir` is empty (no persistent store), `store` is `None` and `docling_document=None` is passed to `run_embedding_pipeline` — the Docling path is unavailable without a store.

**`ingest_directory`** orchestrates source discovery, idempotency checks, manifest management, and the `Runtime` construction. It calls `ingest_file` for each new or changed source. The Docling-native chunking features are transparent at this level — they are controlled entirely by `IngestionConfig` fields.

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| `persist_docling_document=False` falls back to markdown (no re-parse) | Re-parse the source file in Phase 2 when no `.docling.json` exists | Re-parsing requires the original source file to be accessible during Phase 2, which breaks the phase decoupling principle. Markdown fallback is always available from the CleanDocumentStore. |
| `_check_docling_chunking_config` as a private helper called by `verify_core_design` | Inline checks inside `ingest_directory`; check inside each node | A centralized validation function means all config errors are surfaced before any document is processed. Inline checks in nodes would produce per-document errors. |
| `vlm_mode=builtin` import check at validation time (not parse time) | Check only when `parse_with_docling` is called | Early validation provides a clear error message before expensive batch processing starts. A missing Docling install with `vlm_mode=builtin` should fail fast and loudly, not silently fall back mid-batch. |
| Phase 2 reads DoclingDocument from store (round-trip through disk) | Pass DoclingDocument in-memory from Phase 1 to Phase 2 | Disk persistence preserves the phase decoupling contract — Phase 2 can be re-run independently. In-memory passing would couple the two phases and prevent independent re-embedding. |

**Configuration:**

| Parameter | Type | Default | Valid Range / Options | Effect |
|-----------|------|---------|----------------------|--------|
| `config.persist_docling_document` | `bool` | `True` | `True` or `False` | When `True`, DoclingDocument is written to CleanDocumentStore and read back for Phase 2. When `False`, Phase 2 always uses the markdown path. |
| `config.vlm_mode` | `str` | `"disabled"` | `"disabled"`, `"builtin"`, `"external"` | Validated by `_check_docling_chunking_config` before processing. `"builtin"` requires Docling installed. `"external"` without vision model configured emits a warning. |
| `config.hybrid_chunker_max_tokens` | `int` | `512` | Positive integer | Values above 512 emit a warning from `_check_docling_chunking_config`. No hard error. |
| `config.clean_store_dir` | `str` | `"data/clean_store"` | Filesystem path or empty string | Empty string disables the persistent CleanDocumentStore. Without a store, the DoclingDocument cannot be passed to Phase 2, so the markdown path is always used. |

**Error behavior:**

`verify_core_design` never raises. It returns `IngestionDesignCheck(ok=False, errors=[...])` on invalid config.

`ingest_directory` raises `ValueError` with a formatted message if `verify_core_design` returns `ok=False`.

`ingest_file` catches `OSError`, `ValueError`, and `RuntimeError` from sub-calls. Other exceptions propagate. Phase 1 errors are returned in `IngestFileResult.errors`. Phase 2 errors are also returned in `IngestFileResult.errors`. `write_docling` failure during CleanDocumentStore write is logged as an error but does not populate `IngestFileResult.errors` — the document continues to Phase 2 using the markdown path.

`ingest_directory` catches `OSError`, `ValueError`, `RuntimeError` per-source and logs them as `"unhandled:<source_name>:<exc>"`. A single source failure does not halt the batch.
