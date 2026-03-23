# Ingestion Pipeline Engineering Guide

## Audience and Goal

This guide is for engineers who need to:

- understand how ingestion works end-to-end,
- safely modify a pipeline stage,
- troubleshoot ingestion behavior in production-like runs.

It focuses on the implemented code (not only the product spec), and explains the key design decisions behind the current architecture.

## System at a Glance

The ingestion subsystem transforms source documents into:

- vector-store records (embeddings plus metadata),
- optional knowledge-graph nodes and relations,
- incremental-ingestion manifest entries.

Top-level entrypoints:

- CLI wrapper: `ingest.py`
- Public package API: `src/ingest/pipeline/__init__.py`
- Runtime implementation: `src/ingest/pipeline_impl.py`
- Graph composition: `src/ingest/pipeline_workflow.py`

The pipeline is implemented as a 13-node LangGraph workflow with config-driven optional stages.

## Why the Code Was Split This Way

The previous monolithic ingestion module was hard to maintain and prone to merge and patch conflicts. The current structure intentionally separates concerns:

1. Public API boundary
   - `src/ingest/pipeline/__init__.py`
   - Keeps import paths stable for callers.
2. Runtime orchestration
   - `src/ingest/pipeline_impl.py`
   - Handles directory iteration, manifest updates, resource lifecycle, and graph invocation.
3. Workflow composition
   - `src/ingest/pipeline_workflow.py`
   - Encodes stage topology and conditional transitions in one place.
4. Node-per-file stage logic
   - `src/ingest/nodes/*.py`
   - Keeps each stage independently understandable and testable.
5. Shared utilities and schema
   - `src/ingest/pipeline_types.py`, `src/ingest/pipeline_shared.py`, `src/ingest/pipeline_llm.py`
   - Prevents helper duplication and keeps state and contracts centralized.

This split improves:

- schema clarity (`IngestState`, `IngestionConfig` in one place),
- safer code review (small, stage-focused changes),
- easier test targeting and onboarding.

## Target Architecture: Two-Phase Pipeline

> **Note:** The current codebase implements a monolithic 13-node LangGraph graph. The target
> architecture described below is defined in the companion specifications and is being
> implemented incrementally.

The ingestion system is being refactored into two independent pipelines connected by the
**Clean Document Store** — a filesystem-based boundary contract:

```
Source Documents
      │
      ▼
┌─────────────────────────┐
│  Document Processing    │  Nodes 1–5 (current graph nodes 1–6)
│  State: DocumentProcessingState
│  Spec: DOCUMENT_PROCESSING_SPEC.md
│  FR-101 through FR-587
└─────────┬───────────────┘
          │
          ▼
    Clean Document Store
    ({source_key}.md + {source_key}.meta.json)
    Two-phase change detection:
      • source_hash — detects source file changes
      • clean_hash  — detects processing output changes
          │
          ▼
┌─────────────────────────┐
│  Embedding Pipeline     │  Nodes 6–13 (current graph nodes 7–13)
│  State: EmbeddingPipelineState
│  Spec: EMBEDDING_PIPELINE_SPEC.md
│  FR-591 through FR-1304
└─────────────────────────┘
```

**Key architectural properties:**
- Each phase can be re-run independently (re-process documents without re-embedding, or re-embed without re-processing).
- The Clean Document Store is the contract surface: Document Processing writes to it, Embedding Pipeline reads from it.
- Cross-cutting concerns (re-ingestion strategy, review tiers, domain vocabulary, error handling, configuration, CLI/API interface) are defined in `INGESTION_PLATFORM_SPEC.md`.

**Mapping current implementation to target:**

| Current Code | Target Phase | Notes |
|---|---|---|
| `IngestState` | `DocumentProcessingState` + `EmbeddingPipelineState` | Will be split into two separate TypedDicts |
| `IngestionConfig` | `PipelineConfig` (per-phase) | Configuration will be phase-scoped |
| `content_hash` field | `source_hash` + `clean_hash` | Two-phase change detection replaces single hash |
| Nodes 1–6 | Document Processing Pipeline | Ingestion, structure detection, multimodal, text cleaning, refactoring, output |
| Nodes 7–13 | Embedding Pipeline | Chunking, enrichment, metadata, cross-refs, KG, quality, embedding/storage |

### Review Tiers

The platform spec defines a three-tier review system (`INGESTION_PLATFORM_SPEC.md` Section 4):
- **Fully Reviewed** — high extraction confidence (>0.8)
- **Partially Reviewed** — moderate confidence (0.5–0.8)
- **Self Reviewed** — low confidence or default

Review tier is stored in the Clean Document Store metadata and propagated to chunk metadata for retrieval-time filtering.

### Domain Vocabulary

The platform spec defines domain vocabulary requirements (`INGESTION_PLATFORM_SPEC.md` Section 5):
- Vocabulary terms are injected into LLM prompts for chunking, metadata generation, and KG extraction
- Vocabulary is managed via configuration and can be updated without re-ingestion

## Package Layout

```text
src/ingest/
  pipeline/__init__.py          # Public API facade
  pipeline_impl.py              # Runtime orchestration (ingest_file/ingest_directory)
  pipeline_workflow.py          # StateGraph composition and conditional routing
  pipeline_types.py             # Dataclasses + typed state schema
  pipeline_shared.py            # Shared deterministic helpers
  pipeline_llm.py               # LLM JSON call helper
  nodes/
    document_ingestion.py
    structure_detection.py
    multimodal_processing.py
    text_cleaning.py
    document_refactoring.py
    chunking.py
    chunk_enrichment.py
    metadata_generation.py
    cross_reference_extraction.py
    knowledge_graph_extraction.py
    quality_validation.py
    embedding_storage.py
    knowledge_graph_storage.py
```

## End-to-End Execution Flow

1. `ingest.py` creates `IngestionConfig` and calls `ingest_directory(...)`.
2. `ingest_directory` in `src/ingest/pipeline_impl.py`:
   - validates config via `verify_core_design(...)`,
   - loads manifest via `_load_manifest(...)`,
   - opens Weaviate client and optional KG builder,
   - iterates source files and calls `ingest_file(...)`.
3. `ingest_file(...)` invokes compiled graph `_GRAPH` from `src/ingest/pipeline_workflow.py`.
4. Each node reads and writes `IngestState` fields.
5. After node execution:
   - vectors and metadata are persisted,
   - optional KG is persisted and optionally exported,
   - manifest is updated and saved.

## Stage-by-Stage Node Contracts

| Node | File | Main Input | Main Output |
| --- | --- | --- | --- |
| `document_ingestion` | `src/ingest/nodes/document_ingestion.py` | `source_path`, `existing_hash` | `raw_text`, `content_hash`, `should_skip` |
| `structure_detection` | `src/ingest/nodes/structure_detection.py` | `raw_text` | `structure` |
| `multimodal_processing` | `src/ingest/nodes/multimodal_processing.py` | `structure`, flags | `multimodal_notes` |
| `text_cleaning` | `src/ingest/nodes/text_cleaning.py` | `raw_text`, `multimodal_notes` | `cleaned_text` |
| `document_refactoring` | `src/ingest/nodes/document_refactoring.py` | `cleaned_text`, flags | `refactored_text` |
| `chunking` | `src/ingest/nodes/chunking.py` | text plus chunk config | `chunks` |
| `chunk_enrichment` | `src/ingest/nodes/chunk_enrichment.py` | `chunks` | enriched chunk metadata (`chunk_id`, `enriched_content`, `source`, `source_key`, provenance span fields) |
| `metadata_generation` | `src/ingest/nodes/metadata_generation.py` | content plus LLM/fallback | `metadata_summary`, `metadata_keywords` |
| `cross_reference_extraction` | `src/ingest/nodes/cross_reference_extraction.py` | refactored text | `cross_references` |
| `knowledge_graph_extraction` | `src/ingest/nodes/knowledge_graph_extraction.py` | chunks | `kg_triples` |
| `quality_validation` | `src/ingest/nodes/quality_validation.py` | chunks plus thresholds | filtered `chunks` |
| `embedding_storage` | `src/ingest/nodes/embedding_storage.py` | chunks plus embedder/vector store | `stored_count` |
| `knowledge_graph_storage` | `src/ingest/nodes/knowledge_graph_storage.py` | chunks plus KG builder | persisted KG side effect |

## Conditional Routing Decisions

Routing is centralized in `src/ingest/pipeline_workflow.py`:

- skip early if unchanged (`should_skip`),
- run multimodal stage only when enabled and figures exist,
- run refactoring only when enabled,
- run cross-reference extraction only when enabled,
- run KG storage only when enabled.

This keeps stage logic and routing policy separate.

## Configuration Model

`IngestionConfig` in `src/ingest/pipeline_types.py` is the single behavior contract.

Important controls:

- model/runtime: `llm_model`, `llm_timeout_seconds`, `ollama_url`
- chunking: `semantic_chunking`, `chunk_size`, `chunk_overlap`
- optional stages:
  - `enable_multimodal_processing`
  - `enable_document_refactoring`
  - `enable_cross_reference_extraction`
  - `enable_knowledge_graph_extraction`
  - `enable_quality_validation`
  - `enable_knowledge_graph_storage`
- run mode: `update_mode`, `export_processed`, `build_kg`
- provenance: `persist_refactor_mirror`, `mirror_output_dir`

Design validation:

- `verify_core_design(...)` blocks contradictory configs (for example, KG storage enabled while KG extraction/build is disabled).

## Deterministic vs LLM-Dependent Behavior

Deterministic helpers in `src/ingest/pipeline_shared.py`:

- hashing, manifest I/O,
- fallback keyword extraction,
- cross-reference regex extraction,
- quality scoring.

LLM-dependent operations:

- refactoring (`document_refactoring_node`)
- metadata generation (`metadata_generation_node`)

LLM calls are wrapped in `src/ingest/pipeline_llm.py` and return parsed JSON objects. On failure, nodes fall back to deterministic behavior when possible.

## Data Persistence and Incremental Ingestion

Incremental behavior is managed by:

- `content_hash` comparison against manifest,
- optional cleanup of removed sources in update mode,
- source-level delete and replace semantics before reinsert.

Manifest responsibilities:

- tracks source hash and processing metadata,
- prevents unnecessary reprocessing for unchanged files.

## Refactor Drift and Provenance Guarantees

Document refactoring can improve retrieval quality by normalizing noisy source text, but it can also introduce representation drift. The implementation treats refactoring as a derived layer and keeps source-of-truth traceability explicit:

- original source files are never modified in place,
- mirror artifacts are persisted as:
  - `<stem>.original.md`
  - `<stem>.refactored.md`
  - `<stem>.mapping.json`
- chunk metadata includes provenance fields:
  - `original_char_start` / `original_char_end`
  - `refactored_char_start` / `refactored_char_end`
  - `provenance_method` / `provenance_confidence`
  - `citation_source_uri`

Practical effect:

- retrieval can use refactored chunk text for semantic quality,
- citations can still point to the original source URI and mapped source span.

## Source Identity and Edge Cases

Source identity is intentionally **not** filename-based. The pipeline now tracks:

- `source_key`: stable primary identity used for manifest and delete/replace operations.
- `source_id`: connector-native immutable identity for the document.
- `source_uri`: canonical location used for retrieval trace-back.
- `connector`: source system name (for example, `local_fs`, SharePoint, S3).
- `source_version`: connector version marker (for example, mtime/etag/revision).

Why this matters:

- same filenames in different directories no longer collide,
- rename and move operations are handled as identity updates (not false duplicates),
- retrieval can show the original location (`source_uri`) for operator traceability.

Current local filesystem identity:

- `source_id` is derived from device and inode,
- `source_key` is `local_fs:<source_id>`,
- `source_uri` is generated from the resolved file path.

Edge-case behavior matrix:

| Scenario | Detection | Expected behavior |
| --- | --- | --- |
| Same filename in two directories | Different `source_key`/`source_uri` | Stored as two distinct sources |
| Content unchanged, path unchanged | Hash and URI match | Skip ingestion |
| Content unchanged, file moved/renamed | Hash match, URI changed | Reprocess metadata path and replace vectors by `source_key` |
| Content changed | Hash changed | Delete old vectors for that source and insert new |
| Source removed (full directory update mode) | Missing from discovered `source_key` set | Delete vectors and manifest entry |

Implementation locations:

- identity construction and manifest normalization: `src/ingest/pipeline_impl.py`
- skip gating: `src/ingest/nodes/document_ingestion.py`
- replace-on-update storage behavior: `src/ingest/nodes/embedding_storage.py`
- vector metadata and retrieval projection: `src/core/vector_store.py`

## How to Add or Change a Node Safely

1. Implement stage logic in a new/existing `src/ingest/nodes/<stage>.py`.
2. Keep I/O explicit: return only fields the node changes.
3. Add/adjust fields in `IngestState` (`src/ingest/pipeline_types.py`) if needed.
4. Wire node and routing in `src/ingest/pipeline_workflow.py`.
5. Update `PIPELINE_NODE_NAMES` in `src/ingest/pipeline_types.py` if node identity changes.
6. Add tests under `tests/ingest/` for:
   - node behavior,
   - config/routing behavior,
   - regression around expected outputs.
7. Update docs (`src/ingest/README.md` and this guide).

## Testing Strategy

Current test location:

- `tests/ingest/`

Baseline coverage includes:

- helper parsing and fallback behavior,
- skip-on-unchanged logic,
- 13-node naming contract,
- configuration design validation,
- idempotency-oriented chunk ID and manifest roundtrip checks,
- manifest corruption recovery (corrupt file quarantine + empty-manifest fallback).

Recommended additions as pipeline evolves:

- per-node unit tests with synthetic state fixtures,
- workflow routing tests for optional-stage combinations,
- integration tests with temporary docs and mocked LLM/vector store.

## Operational Notes

- `ingest.py` remains the canonical CLI entrypoint.
- Vector store and KG persistence are managed in `ingest_directory(...)` runtime scope.
- If `context-agent update` is part of your workflow, run it after structural changes so promoted summaries stay current.

## Common Failure Modes and Debug Path

1. Unexpected skip behavior
   - check manifest hash entry vs source content hash.
   - if JSON corruption occurred, check for `manifest.json.corrupt.<timestamp>` artifacts.
2. Missing stage output
   - check config toggle and route condition in `src/ingest/pipeline_workflow.py`.
3. LLM output parse failures
   - validate JSON-only response assumptions in `src/ingest/pipeline_llm.py`.
4. Duplicate or old vectors on update
   - verify `update_mode` and source cleanup path in `embedding_storage_node`.
5. KG not persisted
   - verify `build_kg`, extraction/storage toggles, and runtime `kg_builder` creation.

## Decision Record (Short Form)

- Decision: use a node-per-file architecture.
  - Why: reduce coupling and improve maintainability.
- Decision: keep state and config contracts centralized.
  - Why: avoid implicit cross-stage dependencies.
- Decision: centralize graph routing in one composer module.
  - Why: make optional stage behavior auditable.
- Decision: keep deterministic fallbacks for LLM-facing stages.
  - Why: preserve reliability during provider and model instability.
