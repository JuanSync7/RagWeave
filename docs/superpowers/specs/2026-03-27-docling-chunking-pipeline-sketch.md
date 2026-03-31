# Docling-Native Chunking Pipeline — Design Sketch

**Date:** 2026-03-27
**Run ID:** 2026-03-27-docling-chunking-pipeline
**Status:** APPROVED (injected from conversation)

## Goal Statement

Redesign the document processing and chunking pipeline to use Docling's `DoclingDocument` object natively with `HybridChunker`, replacing the current markdown-string-based chunking cascade. This gives structure-aware, token-aware chunking that respects document items (paragraphs, tables, lists, figures, code blocks) as natural boundaries. The current markdown-based pipeline becomes the fallback for non-Docling sources.

Additionally, consolidate the VLM (Vision Language Model) image processing to support two modes: Docling's built-in SmolVLM for lightweight use, and external VLM via LiteLLM for frontier-quality diagram understanding. VLM output replaces image placeholders in chunks post-chunking.

## Chosen Approach

**DoclingDocument-native pipeline with HybridChunker + post-chunking VLM injection.**

Reasoning:
- Docling already parses documents into a rich `DoclingDocument` object with structural items, but we currently discard it after `export_to_markdown()` — wasting all structural information
- HybridChunker operates on `DoclingDocument` directly, producing structure-aware + token-aware chunks with table header repetition, undersized chunk merging, and code-aware splitting
- This eliminates 3 pipeline nodes (text_cleaning, document_refactoring, separate multimodal_processing) for Docling-parsed documents
- The VLM step moves to post-chunking: replace `![Figure](...)` placeholders in chunks with rich semantic descriptions
- `semchunk` (HybridChunker's internal text splitter) handles the rare forced-split case for oversized single items — semantic splitting is not needed

Counter-argument considered: Keeping the current pipeline is simpler (no integration work, already working). Rejected because: the current pipeline misses level-1 structural chunking entirely (paragraphs, tables as units), produces poor table chunks, and the text cleaning / refactoring nodes add complexity that Docling's output already handles.

## Key Decisions

1. **Preserve `DoclingDocument` object** — Store it alongside markdown in `DoclingParseResult` and thread it through pipeline state. Serialize to JSON via `docling-core` for CleanDocumentStore persistence.

2. **HybridChunker as primary chunker** — Token-aware, structure-aware, handles tables/code/lists natively. Configured with embedder-aligned `max_tokens`. Falls back to current markdown chunking for non-Docling sources.

3. **Remove text_cleaning_node for Docling path** — Docling already strips layout artifacts, headers/footers, page numbers. Only unicode normalization needed as a lightweight per-chunk post-pass. Keep full cleaning for non-Docling fallback.

4. **Remove document_refactoring_node** — LLM paragraph rewriting was compensating for bad chunk boundaries. With structure-aware chunking, prepend `section_path` metadata at embedding time instead (deterministic, zero-cost).

5. **VLM as post-chunking step** — Two modes via config:
   - `builtin`: Docling's SmolVLM (small, zero infrastructure, basic captioning)
   - `external`: LiteLLM-routed VLM (frontier models for deep diagram understanding)
   - Image placeholders in chunks are replaced with VLM descriptions after HybridChunker runs

6. **Drop semantic splitting** — HybridChunker + semchunk handles all splitting. Semantic splitting (embedding every sentence) adds cost with negligible benefit for technical docs and code, which are the primary document types.

7. **Fallback architecture** — Non-Docling sources use the existing markdown string pipeline: `MarkdownHeaderTextSplitter → RecursiveCharacterTextSplitter`. This path is preserved as-is.

## Component/Module List

| Component | Responsibility |
|---|---|
| `support/docling.py` | Preserve and return `DoclingDocument` in `DoclingParseResult` |
| `structure_detection_node` | Pass `DoclingDocument` into pipeline state |
| `CleanDocumentStore` | Serialize/deserialize `DoclingDocument` JSON alongside markdown |
| `DocumentProcessingState` | New `docling_document` field |
| `EmbeddingPipelineState` | New `docling_document` field |
| `chunking_node` | Dual path: HybridChunker (Docling) or markdown splitter (fallback) |
| `vlm_enrichment` (new/refactored) | Post-chunking VLM image replacement, supports builtin + external modes |
| `support/markdown.py` | Retained as fallback chunking path; add unicode cleanup utility |
| `IngestionConfig` | New config fields: `chunker_mode`, `vlm_mode` (builtin/external) |

## Scope Boundary

### In Scope
- Preserve `DoclingDocument` through pipeline
- Integrate `HybridChunker` as primary chunker with config
- Post-chunking VLM image replacement (builtin SmolVLM + external LiteLLM)
- Lightweight per-chunk unicode normalization
- Fallback to current markdown pipeline for non-Docling sources
- Config surface for new chunking and VLM modes
- State contract updates (both Phase 1 and Phase 2)
- CleanDocumentStore serialization of `DoclingDocument`
- Tests for new chunking path, VLM modes, fallback behavior

### Out of Scope
- Changing Docling version or adding new Docling models beyond SmolVLM
- Knowledge graph extraction changes
- Embedding model changes
- Weaviate schema changes
- CLI/UI changes beyond new config flags
- Removing the old pipeline code (kept as fallback)
- Performance benchmarking of HybridChunker vs current

## Open Questions

1. **DoclingDocument serialization size** — JSON export of DoclingDocument could be large for big documents. May need to evaluate whether to store it or re-parse. Recommendation: store it (avoids re-parsing cost), but add a config toggle to disable persistence if storage is a concern.

2. **SmolVLM model download** — Currently `with_smolvlm=False` in warmup. Enabling it adds download time and disk usage. Should be behind `vlm_mode=builtin` config only.

3. **Token limit alignment** — HybridChunker's `max_tokens` needs to align with the embedding model's token limit (bge-m3). Need to verify the right value during implementation.
