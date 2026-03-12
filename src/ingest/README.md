<!-- @summary
Document ingestion package with a modular 13-node LangGraph workflow, shared utilities, and processing primitives.
@end-summary -->

# ingest

## Overview

This package powers embedding ingestion for the RAG system. The workflow is organized as:

- top-level graph composition (`pipeline_workflow.py`)
- node-per-file stage implementations (`nodes/`)
- shared schema/config/types (`pipeline_types.py`)
- shared helper logic (`pipeline_shared.py`, `pipeline_llm.py`)
- public interface facade package (`pipeline/`)

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `document_processor.py` | Metadata extraction and plain-text preprocessing helpers | `process_document`, `extract_metadata`, `metadata_to_dict`, `chunk_text` |
| `markdown_processor.py` | Markdown-aware cleaning and chunking primitives | `chunk_markdown`, `clean_document`, `ProcessedChunk` |
| `pipeline/__init__.py` | Public API facade for ingestion pipeline | `IngestionConfig`, `ingest_directory`, `ingest_file` |
| `pipeline_impl.py` | Runtime orchestration, graph invocation, and directory-level ingestion loop | `ingest_directory`, `ingest_file`, `verify_core_design` |
| `pipeline_workflow.py` | Top-level LangGraph `StateGraph` composition wiring all nodes | `build_graph` |
| `pipeline_types.py` | Shared dataclasses and typed state schema | `IngestionConfig`, `IngestionRunSummary`, `IngestState` |
| `pipeline_shared.py` | Shared file/json/hash/quality helper functions | `_load_manifest`, `_save_manifest`, `_sha256_path`, `_parse_json_object` |
| `pipeline_llm.py` | LLM JSON utility for configurable Ollama-backed node calls | `_ollama_json` |

## Internal Dependencies

- `pipeline_impl.py` depends on `pipeline_workflow.py` for graph assembly and `pipeline_types.py` for schema/runtime types.
- `pipeline_workflow.py` imports all stage nodes from `nodes/` and wires conditional graph transitions.
- Node modules consume shared helpers from `pipeline_shared.py` and optional LLM calls through `pipeline_llm.py`.

## Subdirectories

- `nodes/`: one file per pipeline stage with stage-specific logic and clear boundaries.

## Engineering Documentation

- `docs/embedding/INGESTION_PIPELINE_ENGINEERING_GUIDE.md`: implementation-oriented walkthrough of architecture, stage contracts, config/routing decisions, extension steps, and troubleshooting.
- `docs/embedding/INGESTION_NEW_ENGINEER_ONBOARDING_CHECKLIST.md`: one-page onboarding checklist for first-day setup, first change workflow, and common gotchas.

## Runtime Controls

- `RAG_INGESTION_VERBOSE_STAGE_LOGS=true` enables per-stage progress logs for every document.
- `ingest.py --verbose-stages` forces per-stage logs on for that run.
- `ingest.py --no-verbose-stages` forces per-stage logs off for that run.
- Omitting both flags keeps the config default (`RAG_INGESTION_VERBOSE_STAGE_LOGS`).
- `RAG_INGESTION_PERSIST_REFACTOR_MIRROR=true` persists original/refactored mirror files plus chunk provenance mappings.
- Source identity is tracked with `source_key`, `source_id`, and `source_uri` metadata so files remain unique across directories/connectors and retrieval can reference original location.

## Source Identity Notes

- `source_key` is the stable ingestion identity used for update cleanup and manifest indexing.
- `source_uri` is the canonical retrieval location shown to users/operators.
- Chunk metadata always carries both `source` (human-readable display/filter field) and `source_key` (stable identity field for idempotent chunk IDs).
- Filename equality does not imply identity equality; files with the same name in different directories are treated as distinct sources.
- Refactoring never mutates original source files; mirror artifacts are written under `processed/refactor_mirror/`.
- Chunk metadata stores provenance (`original_char_*`, `refactored_char_*`, `provenance_*`) to map retrieval chunks back to source text.
