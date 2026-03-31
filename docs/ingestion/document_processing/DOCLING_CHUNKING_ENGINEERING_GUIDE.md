> **Document type:** Engineering reference guide (Layer 5 — post-implementation)
> **Companion spec:** `DOCLING_CHUNKING_SPEC.md`
> **Companion design:** `DOCLING_CHUNKING_DESIGN.md`
> **Last updated:** 2026-03-27

# Docling-Native Chunking Pipeline — Engineering Guide

| Field | Value |
|-------|-------|
| **Subsystem** | Docling-Native Chunking Pipeline |
| **Version** | 1.0.0 |
| **Status** | Implemented |
| **Spec Reference** | `DOCLING_CHUNKING_SPEC.md` v1.0.0 |
| **Phases affected** | Phase 1 (Document Processing), Phase 2 (Embedding) |

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-03-27 | Initial guide — covers Wave 1 module sections plus cross-cutting sections. |

---

## Table of Contents

1. [Architecture Overview and Data Flow](#1-architecture-overview-and-data-flow)
2. [Module Layout and Responsibilities](#2-module-layout-and-responsibilities)
3. [Builtin vs External VLM Mode](#3-builtin-vs-external-vlm-mode)
4. [Configuration Reference](#4-configuration-reference)
5. [Error Handling and Fallback Cascade](#5-error-handling-and-fallback-cascade)
6. [How to Extend](#6-how-to-extend)
7. [Troubleshooting and Common Failure Modes](#7-troubleshooting-and-common-failure-modes)

---

## 1. Architecture Overview and Data Flow

### 1.1 Problem Being Solved

The previous pipeline discarded the `DoclingDocument` object immediately after exporting it to a markdown string. All structural information — paragraph boundaries, table cell structure, list hierarchies, figure metadata, and code block delineation — was thrown away at the Phase 1 boundary. Downstream chunking then tried to reconstruct structure heuristically using `MarkdownHeaderTextSplitter`, producing poor table chunks, misaligned split boundaries, and character-count-based limits that did not align with the embedding model's token budget.

This redesign preserves the `DoclingDocument` object through the Phase 1/Phase 2 boundary and uses Docling's own `HybridChunker` to produce structure-aware, token-aware chunks. The markdown pipeline remains active as a fallback for non-Docling sources and for Docling parse failures in non-strict mode.

### 1.2 High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 1: Document Processing Pipeline                              │
│                                                                     │
│  source_file ──► document_ingestion ──► structure_detection_node   │
│                                               │                     │
│           ┌─── Docling enabled? ─────────────┘                     │
│           │                                                         │
│     YES   │  parse_with_docling(vlm_mode)                          │
│           │    ├─ vlm_mode="builtin"  → SmolVLM runs at parse time  │
│           │    └─ vlm_mode≠"builtin"  → no picture description      │
│           │                                                         │
│           │  DoclingParseResult                                     │
│           │    ├─ text_markdown      → raw_text in state            │
│           │    └─ docling_document   → docling_document in state    │
│           │                                                         │
│           │  structure["docling_document_available"] = True         │
│           │    → skips text_cleaning_node                           │
│           │    → skips document_refactoring_node                    │
│           │                                                         │
│     NO    │  regex heuristics                                       │
│           │  structure["docling_document_available"] = False        │
│           │    → text_cleaning_node runs                            │
│           │    → document_refactoring_node runs (if enabled)        │
│           │                                                         │
│           └──► CleanDocumentStore.write(                            │
│                  source_key,                                        │
│                  text=clean_markdown,                               │
│                  meta=metadata,                                     │
│                  docling_document=doc  ← if persist_docling_document│
│                )                                                    │
│                  writes: {key}.md                                   │
│                           {key}.meta.json                           │
│                           {key}.docling.json  ← envelope v1        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                     Phase 1/2 boundary
                    (CleanDocumentStore)
                              │
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 2: Embedding Pipeline                                        │
│                                                                     │
│  CleanDocumentStore.read(key)       → raw_text                      │
│  CleanDocumentStore.read_docling(key) → docling_document (or None)  │
│                                                                     │
│  document_storage_node                                              │
│      │                                                              │
│  chunking_node                                                      │
│      │                                                              │
│      ├─ docling_document present?                                   │
│      │    YES → HybridChunker(max_tokens=hybrid_chunker_max_tokens) │
│      │            .chunk(dl_doc=docling_document)                   │
│      │          → ProcessedChunk list with section_path metadata    │
│      │          on HybridChunker error → fallback to markdown path  │
│      │                                                              │
│      │    NO  → markdown fallback path                              │
│      │          MarkdownHeaderTextSplitter                          │
│      │          + RecursiveCharacterTextSplitter (semantic/char)    │
│      │                                                              │
│  vlm_enrichment_node                                                │
│      │                                                              │
│      ├─ vlm_mode="external"                                         │
│      │    → scan chunk text for ![alt](src) placeholders            │
│      │    → call LiteLLM vision model for each image                │
│      │    → replace placeholder with VLM description text           │
│      │    → respect vision_max_figures per-document budget          │
│      │                                                              │
│      ├─ vlm_mode="builtin"  → no-op (descriptions already in doc)  │
│      └─ vlm_mode="disabled" → no-op                                │
│                                                                     │
│  chunk_enrichment → metadata_generation → [cross_ref] → [kg] →    │
│  quality_validation → embedding_storage → [kg_storage]             │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.3 Key Design Decisions

**`DoclingDocument` is stored as JSON between phases.** The Phase 1 and Phase 2 pipelines are independently restartable. To avoid re-parsing the source document in Phase 2, the `DoclingDocument` is serialized to `{key}.docling.json` in the `CleanDocumentStore`. The file uses a versioned envelope (`_schema_version: "docling-native-v1"`) for forward migration safety. If the file is absent or invalid, Phase 2 falls back to the markdown path.

**`vlm_enrichment_node` is always wired in the Phase 2 graph.** It is never removed via conditional edge routing — it simply short-circuits internally when `vlm_mode != "external"`. This keeps the graph topology stable and avoids routing complexity.

**`text_cleaning_node` and `document_refactoring_node` are skipped when Docling succeeds.** These nodes exist primarily to compensate for the structural information loss that markdown export causes. When a `DoclingDocument` is available, the structural compensation is no longer needed, so the nodes are bypassed via `structure["docling_document_available"]` routing.

**HybridChunker failures fall back to the markdown path — non-fatally.** The chunking node catches any exception from `HybridChunker`, logs it at ERROR level, and proceeds with the markdown path. This is intentional: a single document should not halt the pipeline.

---

## 2. Module Layout and Responsibilities

### 2.1 File Map

```
config/
  settings.py                         ← env var definitions for RAG_INGESTION_VLM_MODE,
                                          RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS,
                                          RAG_INGESTION_PERSIST_DOCLING_DOCUMENT

src/ingest/
  common/
    types.py                          ← IngestionConfig (vlm_mode, hybrid_chunker_max_tokens,
                                          persist_docling_document fields)
    clean_store.py                    ← CleanDocumentStore (write_docling, read_docling, write)

  support/
    docling.py                        ← parse_with_docling (vlm_mode param + SmolVLM wiring),
                                          DoclingParseResult (docling_document field),
                                          warmup_docling_models (with_smolvlm flag),
                                          ensure_docling_ready

  doc_processing/
    state.py                          ← DocumentProcessingState (docling_document field)
    nodes/
      structure_detection.py          ← sets structure["docling_document_available"],
                                          propagates docling_document to state

  embedding/
    state.py                          ← EmbeddingPipelineState (docling_document field)
    workflow.py                       ← build_embedding_graph (vlm_enrichment node wired)
    nodes/
      chunking.py                     ← dual-path: HybridChunker vs markdown fallback
      vlm_enrichment.py               ← external VLM image enrichment (post-chunking)

  impl.py                             ← verify_core_design, _check_docling_chunking_config,
                                          pipeline orchestration entry points
```

### 2.2 Module Responsibilities

#### `config/settings.py`

Owns the raw env var reads. Three variables belong to this subsystem:

- `RAG_INGESTION_VLM_MODE` → `str`, default `"disabled"`
- `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS` → `int`, default `512`
- `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT` → `bool`, default `True`

These are imported by `src/ingest/common/types.py` to set `IngestionConfig` field defaults.

#### `src/ingest/common/types.py`

Contains `IngestionConfig`, the single typed configuration dataclass consumed by all pipeline nodes. Three fields were added by this redesign:

- `vlm_mode: str` — controls VLM strategy across both phases
- `hybrid_chunker_max_tokens: int` — passed directly to `HybridChunker`
- `persist_docling_document: bool` — controls whether Phase 1 writes `{key}.docling.json`

Also owns `PIPELINE_NODE_NAMES`, which includes `"vlm_enrichment"` between `"chunking"` and `"chunk_enrichment"`.

#### `src/ingest/common/clean_store.py`

The Phase 1/2 boundary store. Two new methods were added:

- `write_docling(source_key, docling_document)` — atomically serializes a `DoclingDocument` to `{key}.docling.json` using an envelope with `_schema_version: "docling-native-v1"`.
- `read_docling(source_key)` — deserializes and returns the `DoclingDocument`, or `None` if the file is absent, invalid JSON, or the schema version does not match.

The existing `write()` method was extended to accept an optional `docling_document` parameter. When provided and not `None`, it calls `write_docling()` after writing the markdown and metadata. A `write_docling` failure is logged at ERROR level but does not roll back the already-committed markdown and metadata files.

#### `src/ingest/support/docling.py`

Wraps the Docling library. Changes in this redesign:

- `DoclingParseResult` gained a `docling_document: Any` field. It is always set to the native `DoclingDocument` object returned by `DocumentConverter.convert()`. `None` only appears in error recovery paths.
- `parse_with_docling()` accepts a `vlm_mode` parameter. When `vlm_mode="builtin"`, it constructs `PdfPipelineOptions` with `do_picture_description=True` and `PictureDescriptionVlmEngineOptions.from_preset("smolvlm")` before constructing `DocumentConverter`. SmolVLM errors are caught and logged as warnings — the parse continues without picture description rather than raising.
- `warmup_docling_models()` accepts `with_smolvlm: bool`. When `True`, SmolVLM model artifacts are downloaded alongside the standard layout and TableFormer models.

#### `src/ingest/doc_processing/nodes/structure_detection.py`

Sets the `structure["docling_document_available"]` routing flag. On a successful Docling parse:

1. Stores `parsed.docling_document` in the returned state update under the key `"docling_document"`.
2. Sets `structure["docling_document_available"] = True`.

Downstream conditional edges in the Phase 1 workflow read this flag to skip `text_cleaning_node` and `document_refactoring_node`. In non-strict mode, Docling failures cause the node to fall back to regex heuristics and set `docling_document_available = False` without including `"docling_document"` in the returned update.

#### `src/ingest/embedding/nodes/chunking.py`

Implements the dual-path chunking strategy:

- **Docling path:** `state["docling_document"]` is not `None` → attempts `HybridChunker`. On any exception, falls back to markdown path (non-fatal). Logs `hybrid_chunker:ok` or `hybrid_chunker:error + chunking:fallback_to_markdown`.
- **Markdown fallback path:** `state["docling_document"]` is `None` → `MarkdownHeaderTextSplitter` + `RecursiveCharacterTextSplitter`. Logs `chunking:markdown_fallback`.

Both paths apply `_normalize_chunk_text()` (NFC unicode normalization, control character removal) to every chunk text before assembling `ProcessedChunk` objects.

The Docling path additionally extracts `section_path`, `heading`, and `heading_level` from `chunk.meta.headings` via `_extract_docling_section_metadata()`.

#### `src/ingest/embedding/nodes/vlm_enrichment.py`

Post-chunking VLM enrichment node. Mode dispatch:

- `vlm_mode="external"` → iterate chunks, call `_enrich_chunk_external()` for any chunk containing `![alt](src)` image placeholders. Respects `vision_max_figures` per-document budget. Per-chunk failures are non-fatal.
- `vlm_mode="builtin"` or `vlm_mode="disabled"` → immediate no-op, returns original chunks unchanged.

The node never raises. Any unexpected exception at the outer level is caught, logged at ERROR level, and the original chunks are returned unchanged.

#### `src/ingest/embedding/workflow.py`

Wires `vlm_enrichment_node` as the node immediately after `chunking_node` in the Phase 2 LangGraph graph. The node is always present in the graph topology; it short-circuits internally when VLM enrichment is not needed.

#### `src/ingest/impl.py`

`verify_core_design()` calls `_check_docling_chunking_config()`, which enforces three rules:

1. `vlm_mode` must be one of `{"disabled", "builtin", "external"}` — hard error.
2. `vlm_mode="builtin"` requires `docling` to be installed — hard error.
3. `vlm_mode="external"` without a vision model or router config — warning only.
4. `hybrid_chunker_max_tokens > 512` — warning only (bge-m3 limit).

---

## 3. Builtin vs External VLM Mode

The `vlm_mode` configuration knob controls how figure images in documents are described. The three valid values correspond to architecturally distinct strategies:

### `vlm_mode="disabled"` (default)

No image description takes place. Figure placeholders (`![alt](src)`) remain in chunk text as-is. The `vlm_enrichment_node` is a no-op. This is the correct choice for text-only workloads or when image content is not relevant to retrieval.

### `vlm_mode="builtin"`

SmolVLM runs **at parse time inside `DocumentConverter`**, before the `DoclingDocument` object is returned. Figure descriptions are baked directly into the `DoclingDocument`'s picture items and are included in the markdown export and in the `HybridChunker` output.

This mode is triggered by passing `do_picture_description=True` with `PictureDescriptionVlmEngineOptions.from_preset("smolvlm")` to `PdfPipelineOptions`. The SmolVLM model artifacts must be present locally — call `warmup_docling_models(with_smolvlm=True)` or set `RAG_INGESTION_DOCLING_AUTO_DOWNLOAD=true` with the model download path configured.

The `vlm_enrichment_node` is a no-op in this mode because descriptions are already embedded in the `DoclingDocument` before chunking begins.

**Trade-off:** Builtin VLM runs synchronously during the Phase 1 parse, increasing parse latency. It uses SmolVLM, a lightweight local model. It does not require any external API.

### `vlm_mode="external"`

Figure images are described **post-chunking**, by `vlm_enrichment_node` in Phase 2. The node scans each chunk's text for `![alt](src)` image reference patterns using `_IMAGE_REF_PATTERN` from `src/ingest/support/vision`. For each matched placeholder:

1. The image is loaded and validated against `vision_max_image_bytes`.
2. A LiteLLM vision API call is made to the configured `LLM_VISION_MODEL` (env: `RAG_LLM_VISION_MODEL`).
3. The placeholder is replaced in the chunk text with the returned description.

A per-document figure budget (`vision_max_figures`) limits total API calls per document. The text is rescanned after each replacement to avoid offset drift from prior substitutions.

**Trade-off:** External VLM can use frontier models (GPT-4V, Claude Vision, Gemini) and runs asynchronously from parsing. It requires a configured vision model endpoint and incurs API cost per figure.

### Mode Comparison

| Aspect | `disabled` | `builtin` | `external` |
|--------|-----------|-----------|------------|
| Where it runs | — | Phase 1, during parse | Phase 2, post-chunking |
| Model | — | SmolVLM (local, lightweight) | Any LiteLLM-routed vision model |
| Latency impact | None | Increases parse time | Increases Phase 2 time |
| API cost | None | None | Per-figure API call |
| Requires network | No | No | Yes (unless local Ollama) |
| Description quality | — | Lightweight | Configurable (frontier possible) |
| `vlm_enrichment_node` behavior | no-op | no-op | active |

---

## 4. Configuration Reference

All configuration is controlled through environment variables read at import time by `config/settings.py` and surfaced to nodes via `IngestionConfig`.

### 4.1 Docling-Native Chunking Variables

| Environment Variable | `IngestionConfig` Field | Type | Default | Valid Values | Effect |
|---------------------|------------------------|------|---------|--------------|--------|
| `RAG_INGESTION_VLM_MODE` | `vlm_mode` | `str` | `"disabled"` | `"disabled"`, `"builtin"`, `"external"` | Selects VLM strategy. `"builtin"` runs SmolVLM at parse time. `"external"` runs LiteLLM post-chunking. `"disabled"` skips all image description. |
| `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS` | `hybrid_chunker_max_tokens` | `int` | `512` | Positive integer ≤ 512 recommended | Maximum token count per `HybridChunker` chunk. The bge-m3 embedding model accepts at most 512 tokens. Values above 512 produce a startup warning. |
| `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT` | `persist_docling_document` | `bool` | `true` | `true`, `false`, `1`, `0`, `yes` | When `true`, the `DoclingDocument` is serialized to `{key}.docling.json` in `CleanDocumentStore` at the end of Phase 1. Setting `false` saves disk space but prevents the HybridChunker path from being used on Phase 2 re-runs (falls back to markdown). |

### 4.2 Docling Parser Variables

| Environment Variable | `IngestionConfig` Field | Type | Default | Effect |
|---------------------|------------------------|------|---------|--------|
| `RAG_INGESTION_DOCLING_ENABLED` | `enable_docling_parser` | `bool` | `true` | When `false`, Docling is not invoked at all. The Docling path is disabled. |
| `RAG_INGESTION_DOCLING_MODEL` | `docling_model` | `str` | `"docling-parse-v2"` | Parser model identifier passed to `DocumentConverter` and used for telemetry. |
| `RAG_INGESTION_DOCLING_ARTIFACTS_PATH` | `docling_artifacts_path` | `str` | `""` | Directory for Docling model artifacts. Empty string uses Docling's default cache location (`~/.cache/docling`). |
| `RAG_INGESTION_DOCLING_STRICT` | `docling_strict` | `bool` | `true` | When `true`, a Docling parse failure sets `should_skip=True` and halts the document. When `false`, falls back to regex heuristics. |
| `RAG_INGESTION_DOCLING_AUTO_DOWNLOAD` | `docling_auto_download` | `bool` | `true` | Whether to automatically download missing Docling model artifacts during `ensure_docling_ready()`. |

### 4.3 External VLM Variables

These variables apply only when `RAG_INGESTION_VLM_MODE=external`.

| Environment Variable | `IngestionConfig` Field | Type | Default | Effect |
|---------------------|------------------------|------|---------|--------|
| `RAG_LLM_VISION_MODEL` | _(LiteLLM Router)_ | `str` | `"ollama/qwen2.5vl:3b"` | LiteLLM model string for the vision model. Supports any provider LiteLLM supports. |
| `RAG_INGESTION_VISION_MAX_FIGURES` | `vision_max_figures` | `int` | `4` | Maximum figures to describe per document. Limits API call count. |
| `RAG_INGESTION_VISION_MAX_IMAGE_BYTES` | `vision_max_image_bytes` | `int` | `3145728` (3 MiB) | Maximum image file size to submit for VLM description. Larger images are skipped. |
| `RAG_INGESTION_VISION_MAX_TOKENS` | `vision_max_tokens` | `int` | `220` | Maximum tokens in the VLM description response. |
| `RAG_INGESTION_VISION_TEMPERATURE` | `vision_temperature` | `float` | `0.1` | Temperature for the VLM API call. Lower values produce more deterministic descriptions. |
| `RAG_INGESTION_VISION_TIMEOUT_SECONDS` | `vision_timeout_seconds` | `int` | `60` | Timeout per VLM API call. |
| `RAG_INGESTION_VISION_STRICT` | `vision_strict` | `bool` | `false` | When `false`, VLM call failures are non-fatal. When `true`, any VLM failure stops the node. |

### 4.4 Startup Validation

`verify_core_design(config)` is called at pipeline start (in `ingest_file()`) and enforces the following rules. Hard errors prevent the pipeline from starting; warnings are logged but do not halt.

| Condition | Severity | Message |
|-----------|----------|---------|
| `vlm_mode` is not one of `{"disabled", "builtin", "external"}` | Error | `vlm_mode=... is not valid; must be one of [...]` |
| `vlm_mode="builtin"` and `docling` is not installed | Error | `vlm_mode=builtin requires docling to be installed (uv add docling)` |
| `vlm_mode="external"` and no vision model or router config | Warning | `vlm_mode=external is set but no vision model is configured; VLM enrichment will be skipped at runtime` |
| `hybrid_chunker_max_tokens > 512` | Warning | `hybrid_chunker_max_tokens (...) exceeds bge-m3 maximum input (512); chunks may be silently truncated during embedding` |

---

## 5. Error Handling and Fallback Cascade

### 5.1 Phase 1: structure_detection_node

```
Docling parse attempt
  │
  ├─ Success
  │    → docling_document set in state
  │    → structure["docling_document_available"] = True
  │    → text_cleaning and document_refactoring nodes are skipped
  │
  └─ Exception
       ├─ docling_strict=True (default)
       │    → returns {"errors": [...], "should_skip": True}
       │    → pipeline halts for this document
       │    → logged at ERROR level
       │
       └─ docling_strict=False
            → falls back to regex heuristics (FIGURE_PATTERN, HEADING_PATTERN)
            → structure["docling_document_available"] = False
            → docling_document key NOT included in state update
            → text_cleaning and document_refactoring nodes run normally
            → logged at WARNING level
```

### 5.2 Phase 1 → Phase 2: CleanDocumentStore boundary

```
CleanDocumentStore.write(key, text, meta, docling_document=doc)
  │
  ├─ persist_docling_document=True (default) and doc is not None
  │    ├─ write markdown + metadata atomically (tmp → rename)
  │    └─ write_docling(key, doc)
  │         ├─ Success → {key}.docling.json written
  │         └─ Exception (serialization or OS error)
  │              → logged at ERROR level
  │              → markdown and metadata are NOT rolled back
  │              → Phase 2 will use markdown fallback (no docling.json present)
  │
  └─ persist_docling_document=False
       → only markdown and metadata written
       → Phase 2 will always use markdown fallback
```

### 5.3 Phase 2: chunking_node

```
chunking_node
  │
  ├─ state["docling_document"] is not None
  │    └─ HybridChunker attempt
  │         ├─ Success → ProcessedChunk list, log "hybrid_chunker:ok"
  │         └─ Exception
  │              → logged at ERROR level with source name
  │              → log "hybrid_chunker:error"
  │              → log "chunking:fallback_to_markdown"
  │              → continue with markdown fallback path (non-fatal)
  │
  ├─ state["docling_document"] is None
  │    └─ markdown fallback path
  │         → log "chunking:markdown_fallback"
  │         → chunk_markdown() with semantic or character splitter
  │
  └─ any outer exception (e.g., metadata extraction failure)
       → returns {"errors": [...], "processing_log": updated}
       → fatal for this document (no chunks produced)
```

### 5.4 Phase 2: vlm_enrichment_node

```
vlm_enrichment_node (external mode only)
  │
  ├─ vlm_mode != "external" → immediate no-op (skipped log entry)
  │
  └─ vlm_mode = "external"
       │
       ├─ Per-chunk loop
       │    └─ _enrich_chunk_external(chunk, config, count, source_uri)
       │         ├─ figures_processed_count >= vision_max_figures → skip chunk
       │         ├─ no placeholders found → return chunk unchanged
       │         ├─ image candidate extraction fails
       │         │    → log WARNING, continue (non-fatal per placeholder)
       │         ├─ VLM API call fails
       │         │    → log WARNING, continue (non-fatal per placeholder)
       │         └─ success → chunk text updated with VLM description
       │
       └─ unexpected outer exception
            → log ERROR
            → return original chunks unchanged (non-fatal at node level)
```

### 5.5 Fallback Cascade Summary

The overall cascade ensures that a document can always complete ingestion even if all Docling-related components fail:

```
Docling parse fails (strict=false)
  → regex structure detection
  → text_cleaning + document_refactoring run
  → no docling.json in CleanDocumentStore
  → Phase 2 uses markdown fallback chunking
  → vlm_enrichment is a no-op (disabled/builtin) or runs with image placeholders
  → document is ingested with lower chunk quality, not skipped

Docling parse fails (strict=true)
  → document is skipped (should_skip=True)
  → failure counted in IngestionRunSummary.failed
  → error recorded in manifest

HybridChunker fails
  → markdown fallback chunking
  → document is ingested with fallback chunk quality, not skipped

write_docling fails
  → markdown and metadata are preserved
  → Phase 2 uses markdown fallback chunking
  → document is ingested, not skipped

VLM enrichment fails (per-placeholder)
  → original placeholder text preserved in chunk
  → all other chunks are unaffected
  → document is ingested, not skipped
```

---

## 6. How to Extend

### 6.1 Adding a New VLM Backend

To add a new VLM mode (e.g., `"anthropic"` for a provider-specific mode):

1. **Add the new mode to `config/settings.py`**
   No changes needed — the env var `RAG_INGESTION_VLM_MODE` is a free-form string read by `settings.py`. The validation check is the only gate.

2. **Update `_check_docling_chunking_config()` in `src/ingest/impl.py`**
   Add the new mode to `_VALID_VLM_MODES`:
   ```python
   _VALID_VLM_MODES = {"disabled", "builtin", "external", "anthropic"}
   ```

3. **Add handling in `src/ingest/embedding/nodes/vlm_enrichment.py`**
   The current node short-circuits for `vlm_mode != "external"`. Extend the dispatch:
   ```python
   if config.vlm_mode not in ("external", "anthropic"):
       return {
           "chunks": state.get("chunks", []),
           "processing_log": append_processing_log(state, "vlm_enrichment:skipped"),
       }
   ```
   Then implement a separate enrichment helper (e.g., `_enrich_chunk_anthropic`) following the same pattern as `_enrich_chunk_external`: accept `(chunk, config, figures_processed_count, *, source_uri)`, return `(enriched_chunk_or_original, new_count)`.

4. **Update `PIPELINE_NODE_NAMES` in `src/ingest/common/types.py`** if the new mode requires a new node rather than extending the existing one.

5. **Add configuration variables** to `config/settings.py` for any new provider-specific settings. Add corresponding fields to `IngestionConfig` in `src/ingest/common/types.py`.

### 6.2 Changing the Chunking Strategy

To replace `HybridChunker` with a different Docling-native chunker:

1. **Modify `_chunk_with_docling()` in `src/ingest/embedding/nodes/chunking.py`**
   The function constructs `HybridChunker` and calls `.chunk(dl_doc=...)`. Replace this block with your chosen chunker while preserving the `ProcessedChunk` output format.

   The key contract that must be preserved:
   - Input: `state["docling_document"]` (a `DoclingDocument`)
   - Output: `list[ProcessedChunk]` with `text`, `section_path`, `heading`, `heading_level`, `chunk_index`, `total_chunks`, and all `base_metadata` keys
   - Any exception from the chunker is caught by the outer `try/except` in `chunking_node` and triggers the markdown fallback

2. **Update `hybrid_chunker_max_tokens` semantics** in `config/settings.py` and the config reference if the new chunker uses a different token budget mechanism.

3. **Update `IngestionConfig` docstrings** in `src/ingest/common/types.py` to reflect the new chunker's parameters.

### 6.3 Modifying the CleanDocumentStore Envelope Schema

The `{key}.docling.json` file uses a versioned envelope:
```json
{
  "_schema_version": "docling-native-v1",
  "document": { ... }
}
```

To migrate to a new schema version:

1. **Update `write_docling()`** in `src/ingest/common/clean_store.py` to write the new `_schema_version` string and any restructured fields.
2. **Update `read_docling()`** to accept both the old and new schema versions during the transition period. After migration is complete, remove the old version check.
3. **Preserve the version check** — `read_docling()` must return `None` and log a warning (not raise) for unrecognized schema versions. This prevents old-format files from causing crashes.

### 6.4 Adding a New Document Type to the Docling Path

Docling's `DocumentConverter` supports multiple `InputFormat` values. The current builtin VLM wiring applies only to `InputFormat.PDF`. To enable picture description for other formats (e.g., DOCX):

1. **Modify `parse_with_docling()` in `src/ingest/support/docling.py`**
   ```python
   from docling.datamodel.base_models import InputFormat
   from docling.document_converter import DocxFormatOption

   converter_kwargs["format_options"] = {
       InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_pipeline_options),
       InputFormat.DOCX: DocxFormatOption(pipeline_options=docx_pipeline_options),
   }
   ```
2. **Verify the `PictureDescriptionVlmEngineOptions` preset** is available for the new format — not all formats support `do_picture_description`.
3. **Update `warmup_docling_models()`** if the new format requires additional model artifacts.

---

## 7. Troubleshooting and Common Failure Modes

### 7.1 Docling Parse Failures

**Symptom:** Documents fail with `should_skip=True` and `docling_parse_failed:...` in errors. `IngestionRunSummary.failed` count is non-zero.

**Cause:** `RAG_INGESTION_DOCLING_STRICT=true` (the default) causes any Docling exception to halt the document.

**Resolution:**
- Check the error message: it includes the source name and the underlying exception.
- For format-specific failures (e.g., corrupted PDF, password-protected file), the file must be repaired or excluded.
- To allow Docling failures to fall back gracefully, set `RAG_INGESTION_DOCLING_STRICT=false`. This lowers chunk quality for affected documents but prevents them from being skipped entirely.
- To verify Docling is installed: `python -c "from docling.document_converter import DocumentConverter; print('ok')"`.

---

**Symptom:** `RuntimeError: Docling returned empty markdown output` in logs.

**Cause:** `DocumentConverter.convert()` succeeded but the document exported as empty markdown. Common with image-only PDFs or documents where all text is in figures.

**Resolution:**
- Confirm the source file has extractable text. For scanned-only PDFs, OCR must be enabled (not currently configured in this pipeline).
- Set `RAG_INGESTION_DOCLING_STRICT=false` to fall back to regex heuristics for these files.

---

### 7.2 HybridChunker Failures

**Symptom:** `hybrid_chunker:error` in a document's `processing_log` followed by `chunking:fallback_to_markdown`. Chunk quality is lower than expected for Docling-parsed documents.

**Cause:** `HybridChunker` raised an exception. This can occur if `docling-core` is not installed alongside `docling`, or if the `DoclingDocument` object was deserialized from a schema version mismatch.

**Resolution:**
- Check the ERROR-level log line: `HybridChunker failed for source=...: ...` includes the underlying exception.
- Verify `docling-core` is installed: `uv pip show docling-core`.
- Verify the `{key}.docling.json` schema version matches `"docling-native-v1"`. If schema version is mismatched (stale file from a prior pipeline version), delete the affected `.docling.json` files and re-run Phase 1.

---

### 7.3 Missing `docling_document` in Phase 2

**Symptom:** Phase 2 always uses `chunking:markdown_fallback` even though Phase 1 succeeded with Docling. No `hybrid_chunker:ok` log entries.

**Cause A:** `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT=false`. The `DoclingDocument` was not written to `CleanDocumentStore`.

**Resolution A:** Set `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT=true` (the default) and re-run Phase 1 to regenerate the `.docling.json` files.

**Cause B:** `write_docling()` failed silently during Phase 1 (serialization error). The markdown and metadata were preserved but the `.docling.json` was not written.

**Resolution B:** Check the Phase 1 logs for `CleanDocumentStore: write_docling failed for ...` messages. The underlying cause is usually a `docling_core` serialization error or a disk space issue. Fix the underlying cause and re-run Phase 1.

**Cause C:** The `.docling.json` file exists but has an unrecognized `_schema_version`. `read_docling()` returns `None` and logs a warning.

**Resolution C:** Check for `CleanDocumentStore: unsupported _schema_version` warning messages. Delete the stale `.docling.json` files and re-run Phase 1.

---

### 7.4 VLM Enrichment Issues

**Symptom (builtin):** Documents parsed with `vlm_mode=builtin` contain figure placeholders in chunk text rather than VLM descriptions.

**Cause:** SmolVLM setup failed during `parse_with_docling()`. The warning `vlm_mode='builtin' requested but SmolVLM setup failed (...)` will appear in Phase 1 logs.

**Resolution:**
- Verify SmolVLM artifacts were downloaded: run `warmup_docling_models(with_smolvlm=True)` manually or ensure `RAG_INGESTION_DOCLING_AUTO_DOWNLOAD=true`.
- Verify you are on a `docling` version that ships `PictureDescriptionVlmEngineOptions.from_preset("smolvlm")`.

---

**Symptom (external):** `vlm_enrichment:external:error` in processing log. Image placeholders remain in chunks.

**Cause:** An unexpected exception in the outer `vlm_enrichment_node()` catch block. Per-placeholder failures are non-fatal and only produce WARNING-level logs; the outer-level error indicates a more fundamental failure (e.g., state structure mismatch).

**Resolution:** Check the ERROR-level `vlm_enrichment_node: unexpected error` log for the underlying exception. This should be rare — the per-placeholder failure handling is comprehensive.

---

**Symptom (external):** Vision API calls time out or return errors. Per-placeholder WARNING logs appear.

**Cause:** The configured vision model endpoint is unavailable, slow, or misconfigured.

**Resolution:**
- Verify `RAG_LLM_VISION_MODEL` points to a valid model and provider.
- For Ollama: verify the model is pulled (`ollama pull qwen2.5vl:3b`) and the service is running.
- Increase `RAG_INGESTION_VISION_TIMEOUT_SECONDS` if the model is slow.
- Reduce `RAG_INGESTION_VISION_MAX_FIGURES` to limit API call count and total latency.

---

### 7.5 Configuration Validation Errors

**Symptom:** Pipeline refuses to start with `IngestionDesignCheck.ok=False`. Error message includes `vlm_mode=... is not valid`.

**Cause:** `RAG_INGESTION_VLM_MODE` is set to an unrecognized string (typo or deprecated value).

**Resolution:** Set `RAG_INGESTION_VLM_MODE` to one of `disabled`, `builtin`, or `external`.

---

**Symptom:** Startup warning `hybrid_chunker_max_tokens (...) exceeds bge-m3 maximum input (512)`.

**Cause:** `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS` is set above 512.

**Resolution:** Lower the value to 512 or below. Chunks exceeding 512 tokens will be silently truncated by the bge-m3 embedding model, reducing retrieval quality for oversized chunks.

---

### 7.6 Performance and Memory Considerations

**HybridChunker and large documents:** `HybridChunker` holds the full `DoclingDocument` in memory during chunking. For very large documents (hundreds of pages), this can be significant. The `DoclingDocument` is also serialized to `{key}.docling.json` — file sizes are typically 2–10x the markdown size for content-rich documents.

**SmolVLM (`vlm_mode=builtin`) latency:** SmolVLM runs locally inside `DocumentConverter.convert()` and processes all figures found during parsing. There is currently no per-document figure budget for builtin mode — SmolVLM will process every detected figure. For documents with many figures, parse time can increase substantially. If figure count must be controlled, switch to `vlm_mode=external` and set `RAG_INGESTION_VISION_MAX_FIGURES` to cap the count (that env var only applies to the external VLM post-chunking path).

**Disk space:** Each document with `persist_docling_document=true` writes an additional `.docling.json` file. For workloads where re-parsing is acceptable and storage is constrained, set `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT=false`. Phase 2 will use the markdown fallback path but will not re-run Phase 1.
