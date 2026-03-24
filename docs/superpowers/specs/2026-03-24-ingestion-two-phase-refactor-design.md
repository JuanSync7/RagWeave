# Ingestion Two-Phase Refactor — Design Document

**Date:** 2026-03-24
**Status:** Approved
**Scope:** Refactor the monolithic 13-node `src/ingest/` pipeline into two independent sub-pipelines sharing common support libraries.

---

## Problem

The current pipeline has a single `IngestState` TypedDict flowing through all 13 nodes in one `StateGraph`. This couples document processing (format extraction, layout analysis, text cleaning) with embedding/storage (chunking, vector DB, knowledge graph). The implementation docs (`DOCUMENT_PROCESSING_IMPLEMENTATION.md`, `EMBEDDING_PIPELINE_IMPLEMENTATION.md`) specify a two-phase architecture with a persistent `CleanDocumentStore` as the boundary.

---

## Goal

Split the existing fully-functional 13-node pipeline into two independent sub-pipelines under `src/ingest/`, connected by a `CleanDocumentStore`. No stubs. All existing functionality preserved. All documentation updated to reflect new paths.

---

## Architecture

### Two-Phase Split

```
Source File
    │
    ▼
┌─────────────────────────────────────┐
│  Phase 1: Document Processing       │
│  src/ingest/doc_processing/         │
│                                     │
│  Node 1: document_ingestion         │
│  Node 2: structure_detection        │
│  Node 3: multimodal_processing      │
│  Node 4: text_cleaning              │
│  Node 5: document_refactoring       │
└──────────────┬──────────────────────┘
               │ run_document_processing() returns state
               │ orchestrator calls CleanDocumentStore.write()
               ▼
┌─────────────────────────────────────┐
│  CleanDocumentStore                 │
│  src/ingest/clean_store.py          │
│                                     │
│  {source_key}.md                    │
│  {source_key}.meta.json             │
└──────────────┬──────────────────────┘
               │ orchestrator reads text + meta, constructs EmbeddingPipelineState
               ▼
┌─────────────────────────────────────┐
│  Phase 2: Embedding Pipeline        │
│  src/ingest/embedding/              │
│                                     │
│  Node 6:  chunking                  │
│  Node 7:  chunk_enrichment          │
│  Node 8:  metadata_generation       │
│  Node 9:  cross_reference           │
│  Node 10: kg_extraction             │
│  Node 11: quality_validation        │
│  Node 12: embedding_storage         │
│  Node 13: kg_storage                │
└─────────────────────────────────────┘
```

### Directory Structure

```
src/ingest/
├── __init__.py                  # Top-level public API (re-exports ingest_file, ingest_directory)
├── clean_store.py               # NEW — CleanDocumentStore class
├── common/                      # UNCHANGED — shared types, utils, schemas
│   ├── types.py                 # Runtime, IngestionConfig (add clean_store_dir field), IngestionRunSummary
│   ├── schemas.py               # ManifestEntry, SourceIdentity, ProcessedChunk
│   ├── utils.py                 # sha256_path, load/save manifest, read_text_with_fallbacks
│   └── shared.py                # quality_score, keywords, provenance, append_processing_log
├── support/                     # UNCHANGED — processing primitives
│   ├── docling.py               # Docling parser integration
│   ├── vision.py                # VLM image analysis (qwen2.5vl:3b via LiteLLM)
│   ├── llm.py                   # LiteLLM JSON helper
│   ├── document.py              # Text preprocessing
│   └── markdown.py              # Markdown chunking + normalization (all 3 chunk methods)
├── doc_processing/              # NEW — Phase 1 sub-package
│   ├── __init__.py              # re-exports: run_document_processing
│   ├── state.py                 # DocumentProcessingState TypedDict
│   ├── workflow.py              # build_document_processing_graph()
│   ├── impl.py                  # run_document_processing(runtime, initial_state) -> DocumentProcessingState
│   └── nodes/
│       ├── __init__.py
│       ├── document_ingestion.py
│       ├── structure_detection.py
│       ├── multimodal_processing.py
│       ├── text_cleaning.py
│       └── document_refactoring.py
├── embedding/                   # NEW — Phase 2 sub-package
│   ├── __init__.py              # re-exports: run_embedding_pipeline
│   ├── state.py                 # EmbeddingPipelineState TypedDict
│   ├── workflow.py              # build_embedding_graph()
│   ├── impl.py                  # run_embedding_pipeline(runtime, initial_state) -> EmbeddingPipelineState
│   └── nodes/
│       ├── __init__.py
│       ├── chunking.py
│       ├── chunk_enrichment.py
│       ├── metadata_generation.py
│       ├── cross_reference_extraction.py
│       ├── knowledge_graph_extraction.py
│       ├── quality_validation.py
│       ├── embedding_storage.py
│       └── knowledge_graph_storage.py
└── pipeline/                    # MODIFIED — top-level orchestrator
    ├── __init__.py              # re-exports: ingest_file, ingest_directory (stable public API)
    └── impl.py                  # Orchestrates phase 1 → clean_store → phase 2; all manifest mgmt
```

**Files removed during migration:**
- `src/ingest/nodes/` (entire directory) — migrated to `doc_processing/nodes/` and `embedding/nodes/`
- `src/ingest/pipeline/workflow.py` — replaced by `doc_processing/workflow.py` and `embedding/workflow.py`

---

## State Contracts

### `DocumentProcessingState` (`doc_processing/state.py`)

All nodes access config via `state["runtime"].config` (no change from current pattern). No `config` top-level field.

The `should_skip` idempotency check is handled by the **orchestrator** in `pipeline/impl.py` BEFORE invoking phase 1. If the manifest indicates `source_hash` is unchanged AND a clean store entry exists for the `source_key`, the orchestrator skips both phases entirely. `DocumentProcessingState` does not carry `should_skip`, `existing_hash`, or `existing_source_uri` — those are orchestrator-only concerns.

`content_hash` in the existing `IngestState` is renamed to `source_hash` in `DocumentProcessingState` for clarity (matching the spec naming).

| Field | Type | Set by |
|-------|------|--------|
| `runtime` | `Runtime` | orchestrator |
| `source_path` | `str` | node 1 |
| `source_name` | `str` | node 1 |
| `source_uri` | `str` | node 1 |
| `source_key` | `str` | node 1 |
| `source_id` | `str` | node 1 |
| `source_hash` | `str` | node 1 (renamed from `content_hash`) |
| `connector` | `str` | node 1 |
| `source_version` | `str` | node 1 |
| `raw_text` | `str` | node 1 |
| `structure` | `dict` | node 2 (keys: `has_figures`, `figures`, `heading_count`, `docling_enabled`, `docling_model`) |
| `multimodal_notes` | `list[str]` | node 3 (empty list if multimodal disabled) |
| `cleaned_text` | `str` | node 4 |
| `refactored_text` | `str \| None` | node 5 (None if refactoring disabled) |
| `errors` | `list[str]` | any node |
| `processing_log` | `list[str]` | any node |

### `EmbeddingPipelineState` (`embedding/state.py`)

Populated by the orchestrator from `CleanDocumentStore` before phase 2 begins. Field names match the existing node implementations exactly to minimize node changes.

| Field | Type | Set by |
|-------|------|--------|
| `runtime` | `Runtime` | orchestrator |
| `source_key` | `str` | orchestrator (from clean store meta) |
| `source_name` | `str` | orchestrator (from clean store meta) |
| `source_uri` | `str` | orchestrator (from clean store meta) |
| `source_id` | `str` | orchestrator (from clean store meta) |
| `source_version` | `str` | orchestrator (from clean store meta) |
| `connector` | `str` | orchestrator (from clean store meta) |
| `raw_text` | `str` | orchestrator (clean text from store, used as `raw_text` for compat) |
| `cleaned_text` | `str` | orchestrator (same as `raw_text` — clean text is the starting point) |
| `refactored_text` | `str \| None` | orchestrator (from clean store meta if stored) |
| `clean_hash` | `str` | orchestrator (SHA-256 of clean text) |
| `chunks` | `list[ProcessedChunk]` | node 6 |
| `enriched_chunks` | `list[ProcessedChunk]` | node 7 |
| `metadata_summary` | `str` | node 8 (existing field name preserved) |
| `metadata_keywords` | `list[str]` | node 8 (existing field name preserved) |
| `cross_references` | `list[dict]` | node 9 |
| `kg_triples` | `list[dict]` | node 10 (existing field name preserved; flat subject/predicate/object records) |
| `stored_count` | `int` | node 12 |
| `errors` | `list[str]` | any node |
| `processing_log` | `list[str]` | any node |

---

## CleanDocumentStore (`src/ingest/clean_store.py`)

New module. `store_dir` comes from `config.clean_store_dir` (new `IngestionConfig` field, default: `Path("data/clean_store")`). If `clean_store_dir` is `None` or empty string, the store is a no-op passthrough (phase 1 output held in memory and passed directly to phase 2).

```python
class CleanDocumentStore:
    def __init__(self, store_dir: Path) -> None: ...
    def write(self, source_key: str, text: str, meta: dict) -> None: ...
        # Atomic: write to {store_dir}/{source_key}.md.tmp, rename to .md
        # Write meta to {store_dir}/{source_key}.meta.json (atomic same way)
    def read(self, source_key: str) -> tuple[str, dict]: ...
        # Returns (text, meta); raises FileNotFoundError if absent
    def exists(self, source_key: str) -> bool: ...
    def clean_hash(self, source_key: str) -> str: ...
        # Returns SHA-256 of the stored .md file bytes
    def delete(self, source_key: str) -> None: ...
    def list_keys(self) -> list[str]: ...
```

---

## Orchestration (`pipeline/impl.py`)

The top-level orchestrator. `ingest_directory()` and `ingest_file()` signatures unchanged.

**Per-file flow:**

1. Compute `source_identity` and `source_hash`
2. Check manifest: if `source_hash` unchanged AND `clean_store.exists(source_key)` → skip both phases, return cached manifest entry
3. Call `run_document_processing(runtime, initial_state)` → returns `DocumentProcessingState`
4. If `state["errors"]` non-empty → mark file failed, skip phase 2
5. Call `clean_store.write(source_key, final_text, meta_dict)` where `final_text = refactored_text or cleaned_text` and `meta_dict` carries source identity fields + `source_hash`
6. Construct `EmbeddingPipelineState` from store: `clean_store.read(source_key)` → set fields
7. Call `run_embedding_pipeline(runtime, embedding_state)` → returns `EmbeddingPipelineState`
8. If `state["errors"]` non-empty → mark file failed
9. Update manifest with `source_hash`, `clean_hash`, `chunk_count = state["stored_count"]`, `document_summary = state["metadata_summary"]`, `document_keywords = state["metadata_keywords"]`
10. `pipeline/workflow.py` is **deleted** — the module-level `_GRAPH = build_graph()` call in `pipeline/impl.py` is replaced with `from src.ingest.doc_processing.impl import run_document_processing` and `from src.ingest.embedding.impl import run_embedding_pipeline`

---

## Phase 1 Graph (`doc_processing/workflow.py`)

```
document_ingestion_node
    │
    ▼ (conditional: errors? → END)
structure_detection_node
    │
    ▼ (conditional: has_figures AND multimodal_enabled? → multimodal, else → text_cleaning)
multimodal_processing_node ──→ text_cleaning_node
                                      │
                                      ▼ (conditional: refactoring_enabled? → refactoring, else → END)
                               document_refactoring_node → END
```

Graph terminates at `END`. `run_document_processing()` in `doc_processing/impl.py` invokes the compiled graph and returns the final `DocumentProcessingState` dict. The orchestrator then writes to `CleanDocumentStore`.

---

## Phase 2 Graph (`embedding/workflow.py`)

```
chunking_node → chunk_enrichment_node → metadata_generation_node
    │
    ▼ (conditional: cross_ref_enabled?)
cross_reference_extraction_node
    │
    ▼ (conditional: kg_enabled AND kg_builder present?)
knowledge_graph_extraction_node
    │
    ▼
quality_validation_node → embedding_storage_node
    │
    ▼ (conditional: kg_enabled AND kg_builder present?)
knowledge_graph_storage_node → END
```

---

## Node Migration Details

Nodes move with **minimal changes** — only the state import changes:

| Old location | New location | State type change |
|---|---|---|
| `nodes/document_ingestion.py` | `doc_processing/nodes/document_ingestion.py` | `IngestState` → `DocumentProcessingState`; `content_hash` key → `source_hash` |
| `nodes/structure_detection.py` | `doc_processing/nodes/structure_detection.py` | `IngestState` → `DocumentProcessingState` |
| `nodes/multimodal_processing.py` | `doc_processing/nodes/multimodal_processing.py` | `IngestState` → `DocumentProcessingState` |
| `nodes/text_cleaning.py` | `doc_processing/nodes/text_cleaning.py` | `IngestState` → `DocumentProcessingState` |
| `nodes/document_refactoring.py` | `doc_processing/nodes/document_refactoring.py` | `IngestState` → `DocumentProcessingState` |
| `nodes/chunking.py` | `embedding/nodes/chunking.py` | `IngestState` → `EmbeddingPipelineState` |
| `nodes/chunk_enrichment.py` | `embedding/nodes/chunk_enrichment.py` | `IngestState` → `EmbeddingPipelineState` |
| `nodes/metadata_generation.py` | `embedding/nodes/metadata_generation.py` | `IngestState` → `EmbeddingPipelineState` |
| `nodes/cross_reference_extraction.py` | `embedding/nodes/cross_reference_extraction.py` | `IngestState` → `EmbeddingPipelineState` |
| `nodes/knowledge_graph_extraction.py` | `embedding/nodes/knowledge_graph_extraction.py` | `IngestState` → `EmbeddingPipelineState` |
| `nodes/quality_validation.py` | `embedding/nodes/quality_validation.py` | `IngestState` → `EmbeddingPipelineState` |
| `nodes/embedding_storage.py` | `embedding/nodes/embedding_storage.py` | `IngestState` → `EmbeddingPipelineState` |
| `nodes/knowledge_graph_storage.py` | `embedding/nodes/knowledge_graph_storage.py` | `IngestState` → `EmbeddingPipelineState` |

All other business logic (LLM calls, docling, vision, chunking algorithms) is **unchanged**.

---

## Chunking Methods (all three must be operational)

In `embedding/nodes/chunking.py` (migrated from `nodes/chunking.py`), calling `chunk_markdown()` from `support/markdown.py`:

1. **Section-aware splitting** (always on): `MarkdownHeaderTextSplitter` preserves h1/h2/h3 hierarchy in chunk metadata
2. **Semantic chunking** (`config.semantic_chunking = True`): embedder-based cosine similarity sentence splitting within sections
3. **Character/recursive chunking** (`config.semantic_chunking = False`): `RecursiveCharacterTextSplitter` within sections, `embedder=None`

All three paths go through the same `chunk_markdown()` call — behaviour is controlled by the `embedder` argument.

---

## `IngestionConfig` changes (`common/types.py`)

Add one new field:

```python
clean_store_dir: str = "data/clean_store"
# Directory for CleanDocumentStore. Empty string disables persistent store
# (phase 1 output passed directly to phase 2 in memory).
```

Rename (in `IngestState` — this TypedDict is kept for backward compat during transition but deprecated):
- `content_hash` → `source_hash` in `DocumentProcessingState`

---

## Documentation Updates

All of the following must be updated to reflect new sub-package paths:

| File | Change |
|------|--------|
| `docs/ingestion/DOCUMENT_PROCESSING_IMPLEMENTATION.md` | Update file structure, import paths |
| `docs/ingestion/EMBEDDING_PIPELINE_IMPLEMENTATION.md` | Update file structure, import paths |
| `docs/ingestion/INGESTION_PIPELINE_ENGINEERING_GUIDE.md` | Update architecture section, module map |
| `src/ingest/README.md` | New directory structure |
| `src/ingest/doc_processing/README.md` | New file (describe phase 1 sub-package) |
| `src/ingest/embedding/README.md` | New file (describe phase 2 sub-package) |
| `src/ingest/pipeline/README.md` | Update (workflow.py removed) |
| `src/ingest/nodes/README.md` | Delete (directory removed) |
| `src/ingest/__init__.py` | Update imports to new sub-package paths |
| `.context/state.yaml` | Re-run `context-agent update` after migration |

### `pipeline/__init__.py` re-exports (stable public API)

```python
from src.ingest.pipeline.impl import ingest_file, ingest_directory
```

These two symbols are the complete public surface of the package. No other symbols need re-exporting at the top level.

---

## Docling + Vision (verified — no changes needed)

- `support/docling.py`: fully implemented — `parse_with_docling()`, `warmup_docling_models()`, `ensure_docling_ready()`; used by `structure_detection_node`
- `support/vision.py`: fully implemented — `generate_vision_notes()` via LiteLLM (default model: `qwen2.5vl:3b`); used by `multimodal_processing_node`
- Both stay in `support/` and are imported unchanged by their respective nodes in `doc_processing/nodes/`

---

## Success Criteria

- [ ] `ingest_directory()` and `ingest_file()` public API signatures unchanged
- [ ] All 13 node functions fully implemented (no stubs, no `NotImplementedError`, no bare `pass`)
- [ ] `CleanDocumentStore.write()` is atomic (write to `.tmp`, rename)
- [ ] Phase 1 graph returns final `DocumentProcessingState`; orchestrator writes to `CleanDocumentStore`
- [ ] Phase 2 graph reads initial state constructed from `CleanDocumentStore.read()`
- [ ] Semantic chunking, character chunking, and section-aware splitting all exercised via `chunk_markdown()`
- [ ] `src/ingest/nodes/` directory deleted (all nodes migrated)
- [ ] `src/ingest/pipeline/workflow.py` deleted (replaced by sub-package workflows)
- [ ] All documentation paths updated to new sub-package locations
- [ ] `.context/state.yaml` regenerated via `context-agent update`
- [ ] `IngestionConfig.clean_store_dir` field added with default `"data/clean_store"`
- [ ] `pipeline/__init__.py` re-exports exactly `ingest_file` and `ingest_directory`
