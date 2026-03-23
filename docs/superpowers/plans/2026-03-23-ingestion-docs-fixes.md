# Ingestion Documentation Fixes Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all consistency, alignment, and granularity issues found across the 10 ingestion documents.

**Architecture:** Four parallel workstreams touching different files — no conflicts. Each workstream handles a logical group of related fixes.

**Tech Stack:** Markdown documentation edits only.

---

## Workstream A: Document Processing Summary + Implementation

**Files:**
- Modify: `docs/ingestion/DOCUMENT_PROCESSING_SPEC_SUMMARY.md`
- Modify: `docs/ingestion/DOCUMENT_PROCESSING_IMPLEMENTATION.md`

### Task A1: Fix naming inconsistencies in Doc Processing Summary

- [ ] Replace `PipelineDocument` with `DocumentProcessingState` (lines ~128, ~229)
- [ ] Remove `BaseNode` glossary entry (line ~231) — implementation uses plain functions, not classes
- [ ] Replace `skip_refactoring` with `enable_refactoring` (line ~176)

### Task A2: Fix Doc Processing Implementation issues

- [ ] Fix verification comment from "All 51 requirements" to "All 53 requirements" (line ~437)
- [ ] Add review_tier assignment logic note to Task S.1 or Task 1.4
- [ ] Add scope clarification note to FR-510/FR-511 in Task 2.3 (provenance metadata only, chunk/citation enforcement is downstream)
- [ ] Add note to Task 1.11 that Embedding Pipeline triggering is a platform-level integration concern

---

## Workstream B: Embedding Pipeline Summary

**Files:**
- Modify: `docs/ingestion/EMBEDDING_PIPELINE_SPEC_SUMMARY.md`

### Task B1: Fix naming inconsistencies in Embedding Summary

- [ ] Replace `PipelineDocument` with `EmbeddingPipelineState` (line ~226)
- [ ] Remove `BaseNode` glossary entry (line ~365) — implementation uses plain functions
- [ ] Fix BYOM misattribution: remove "BYOM pre-chunked input mode" from Chunking section summary, clarify BYOM applies to embeddings (FR-1205) not chunking
- [ ] Add "table atomic chunking" and "adjacency links" mentions to Chunking section summary

---

## Workstream C: Embedding Pipeline Implementation

**Files:**
- Modify: `docs/ingestion/EMBEDDING_PIPELINE_IMPLEMENTATION.md`

### Task C1: Fix chunk ID formula contradiction (FR-605)

- [ ] Update Task 1.6 subtask 3: change `SHA-256(source_key + ":" + str(ordinal))[:24]` to include content hash: `SHA-256(source_key + ":" + str(ordinal) + ":" + content_hash)[:24]`

### Task C2: Fix enriched_content contradiction (FR-702)

- [ ] Update Task 2.2 subtask 2: change `enriched_content = context_header + chunk_text` to `enriched_content = chunk_text + boundary_context`. Clarify that context_header is stored in metadata but NOT embedded by default per FR-702.

### Task C3: Add missing subtasks for 6 FRs

- [ ] Task 1.6: Add subtask for FR-604 (table atomic chunking — keep tables as indivisible units, prepend header row on oversized splits)
- [ ] Task 1.6 or 2.1: Add subtask for FR-606 (adjacency links — generate previous_chunk_id/next_chunk_id on each chunk)
- [ ] Task 2.1: Add subtask for FR-609 (content type tagging — tag each chunk as text/table/figure/code/equation/list/heading)
- [ ] Task 1.7 or 1.8: Add subtask for FR-1203 (dimensionality validation — validate embedding output dimensions match model config, halt on mismatch)
- [ ] Task 1.8: Add subtask for FR-1206 (asymmetric embedding prefixes — support document/query prefix configuration)
- [ ] Task 1.8: Add subtask for FR-1207 (hybrid search — configure BM25 indexing alongside vector indexing)

### Task C4: Split oversized tasks

- [ ] Split Task 2.2 into Task 2.2a (Node 7: Chunk Enrichment, FR-701-705) and Task 2.2b (Node 8: Metadata Generation, FR-801-806)
- [ ] Split Task 3.3 into Task 3.3a (Triple Extraction, FR-1001-1009), Task 3.3b (Entity Consolidation), Task 3.3c (Graph Store Writer, FR-1301-1304)
- [ ] Update dependency graph and task-to-requirement mapping table

---

## Workstream D: Cross-cutting Documents

**Files:**
- Modify: `docs/ingestion/FR_BLOCK_FORMATTING_METHOD.md`
- Modify: `docs/ingestion/INGESTION_NEW_ENGINEER_ONBOARDING_CHECKLIST.md`
- Modify: `docs/ingestion/INGESTION_PIPELINE_ENGINEERING_GUIDE.md`

### Task D1: Fix FR Block Formatting Method

- [ ] Replace all 4 references to `INGESTION_PIPELINE_SPEC.md` with references to the three current spec files
- [ ] Update script invocation examples to target current spec files

### Task D2: Fix Onboarding Checklist

- [ ] Add `INGESTION_PLATFORM_SPEC.md` as reading item 2 (after src/ingest/README.md, before engineering guide)
- [ ] Fix FR range from "FR-600-FR-1304" to "FR-591-FR-1304"
- [ ] Add `DOCUMENT_PROCESSING_IMPLEMENTATION.md` and `EMBEDDING_PIPELINE_IMPLEMENTATION.md` to reading list

### Task D3: Update Engineering Guide header

- [ ] Add a new section after "System at a Glance" titled "Target Architecture: Two-Phase Pipeline" explaining:
  - The Document Processing → Clean Document Store → Embedding Pipeline split
  - DocumentProcessingState and EmbeddingPipelineState as separate state objects
  - Two-phase change detection (source_hash vs clean_hash)
  - References to the three companion specs
  - Note that the current 13-node implementation is the pre-split monolithic version
- [ ] Add brief mentions of review tiers and domain vocabulary concepts
- [ ] Map implementation field names to spec terminology (content_hash → source_hash/clean_hash)
