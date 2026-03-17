# Ingestion Pipeline — Implementation Guide

| Field              | Value                                              |
|--------------------|----------------------------------------------------|
| **Document**       | Ingestion Pipeline Implementation Guide            |
| **Version**        | 1.0.0                                              |
| **Status**         | Active                                             |
| **Spec Reference** | `RAG_embedding_pipeline_spec.md` v2.0.0            |
| **Created**        | 2026-03-13                                         |
| **Last Updated**   | 2026-03-13                                         |

> **Document Intent.** This guide translates the requirements defined in
> `RAG_embedding_pipeline_spec.md` (FR-100 through FR-2100) into a phased,
> task-oriented implementation plan. Each task maps directly to one or more
> specification requirements and includes subtasks, complexity estimates,
> dependencies, and testing strategies. Part B provides representative code
> snippets that illustrate the key architectural patterns.

---

## Part A: Task-Oriented Overview

The implementation is organised into four sequential phases. Each phase
produces a shippable increment; later phases depend on artefacts from earlier
ones but can be started in parallel where the dependency graph allows.

---

### Phase 1: Core Pipeline (MVP)

The goal of Phase 1 is a working end-to-end ingestion pipeline that accepts
documents, extracts text, chunks deterministically, embeds, and upserts into
the vector store. Re-ingestion (idempotent overwrite) must work from day one.

#### Task 1.1 — Pipeline Configuration System

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement the hierarchical configuration loader that merges defaults, environment variables, and per-run overrides into a frozen `PipelineConfig` dataclass. Validate all values at startup and fail fast on invalid combinations. |
| **Requirements Covered** | FR-100, FR-110, FR-120 |
| **Dependencies**       | None |
| **Complexity**         | S |

**Subtasks**

1. Define `PipelineConfig` and `NodeConfig` dataclasses in `src/ingest/pipeline_types.py`.
2. Implement config loading and merging logic (env vars override file values).
3. Add Pydantic-style validation with clear error messages.
4. Write unit tests covering merge precedence and invalid-value rejection.

**Testing Strategy** — Unit tests only; no external services required.

---

#### Task 1.2 — Pipeline Workflow Skeleton (LangGraph DAG)

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Build the LangGraph `StateGraph` in `src/ingest/pipeline_workflow.py` with all 13 node slots. Phase 1 wires only the MVP nodes (1, 2, 4, 6, 7, 11, 12); remaining nodes are no-op pass-throughs that forward state unchanged. Conditional edges route based on content type and feature flags. |
| **Requirements Covered** | FR-200, FR-210, FR-220, FR-230 |
| **Dependencies**       | Task 1.1 |
| **Complexity**         | M |

**Subtasks**

1. Define `PipelineState` TypedDict in `pipeline_types.py` with all required keys.
2. Create the `build_graph()` factory in `pipeline_workflow.py`.
3. Implement conditional routing functions (content-type router, feature-flag router).
4. Register no-op stubs for Phase 2+ nodes.
5. Expose `compile()` → `CompiledGraph` via the public API facade in `__init__.py`.

**Testing Strategy** — Verify graph topology with LangGraph's built-in introspection; run a synthetic document through the stub graph and assert state keys are preserved.

**Risks** — LangGraph API surface is still evolving; pin the dependency version.

---

#### Task 1.3 — Node 1: Document Intake

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement the intake node in `src/ingest/nodes/intake.py`. Accepts a file path or byte stream, detects MIME type, validates against the allow-list, and populates initial `PipelineState` fields (source path, file hash, detected type, timestamp). |
| **Requirements Covered** | FR-300, FR-310, FR-320 |
| **Dependencies**       | Task 1.2 |
| **Complexity**         | S |

**Subtasks**

1. Implement MIME detection (python-magic with libmagic fallback).
2. Compute SHA-256 file hash for deduplication and deterministic IDs.
3. Populate `PipelineState` with intake metadata.
4. Reject unsupported types with a structured error.

**Testing Strategy** — Unit tests with fixture files of each supported MIME type.

---

#### Task 1.4 — Node 2: Text Extraction

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement the text extraction node in `src/ingest/nodes/extract.py`. Dispatches to format-specific extractors (PDF via PyMuPDF, DOCX via python-docx, Markdown/plain-text pass-through). Outputs raw text plus structural markers (page breaks, headings). |
| **Requirements Covered** | FR-400, FR-410, FR-420, FR-430 |
| **Dependencies**       | Task 1.3 |
| **Complexity**         | M |

**Subtasks**

1. Define the `Extractor` protocol (abstract base) in `pipeline_types.py`.
2. Implement `PdfExtractor`, `DocxExtractor`, `MarkdownExtractor`, `PlainTextExtractor`.
3. Build the extractor registry and dispatcher.
4. Preserve structural markers (page numbers, heading levels) in extraction output.
5. Add fallback to plain-text extraction on extractor failure.

**Testing Strategy** — Unit tests with real fixture documents; property tests asserting extracted text is non-empty and structural markers are present.

**Risks** — PDF extraction quality varies across documents; fallback chunking (Task 1.7) mitigates this.

---

#### Task 1.5 — Node 4: Cleaning & Normalisation

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement the text cleaning node in `src/ingest/nodes/clean.py`. Normalises Unicode, collapses whitespace, strips boilerplate headers/footers, and removes control characters. Output is clean UTF-8 text with structural markers intact. |
| **Requirements Covered** | FR-500, FR-510 |
| **Dependencies**       | Task 1.4 |
| **Complexity**         | S |

**Subtasks**

1. Implement Unicode normalisation (NFC).
2. Implement whitespace collapsing (preserve paragraph boundaries).
3. Implement boilerplate removal (configurable regex patterns).
4. Add guard: reject documents that are empty after cleaning.

**Testing Strategy** — Unit tests with adversarial inputs (mixed encodings, excessive whitespace, control characters).

---

#### Task 1.6 — Node 6: Chunking (Rule-Based MVP)

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement the chunking node in `src/ingest/nodes/chunk.py`. Phase 1 uses deterministic, rule-based chunking: split on structural markers first, then recursive character splitting with configurable `chunk_size` and `overlap`. Each chunk receives a deterministic ID derived from the document hash and chunk ordinal. |
| **Requirements Covered** | FR-600, FR-610, FR-620, FR-630 |
| **Dependencies**       | Task 1.5 |
| **Complexity**         | M |

**Subtasks**

1. Implement heading-aware structural splitting.
2. Implement recursive character splitter as fallback.
3. Generate deterministic chunk IDs (see Part B, Snippet B.3).
4. Attach chunk metadata (ordinal, parent document ID, character offsets).
5. Validate chunk sizes against configured min/max bounds.

**Testing Strategy** — Unit tests asserting deterministic output (same input always produces same chunk IDs); property tests on chunk size bounds.

---

#### Task 1.7 — Node 7: Embedding

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement the embedding node in `src/ingest/nodes/embed.py`. Sends chunk text to the configured embedding model (OpenAI `text-embedding-3-small` default) with batching, retry, and rate-limit handling. Attaches the resulting vectors to chunk state. |
| **Requirements Covered** | FR-700, FR-710, FR-720 |
| **Dependencies**       | Task 1.6 |
| **Complexity**         | M |

**Subtasks**

1. Implement batched embedding calls with configurable batch size.
2. Add exponential backoff retry with jitter on transient errors (429, 5xx).
3. Add token-count pre-validation (reject chunks exceeding model context window).
4. Attach embedding vectors and model metadata to chunk state.

**Testing Strategy** — Unit tests with mocked embedding API; integration test with live API behind a feature flag.

**Risks** — Rate limits under batch load; mitigated by configurable concurrency and backoff.

---

#### Task 1.8 — Node 11: Vector Store Upsert

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement the upsert node in `src/ingest/nodes/upsert.py`. Writes embedded chunks to the vector store (Qdrant). Uses deterministic IDs so that re-ingestion overwrites existing vectors rather than creating duplicates. |
| **Requirements Covered** | FR-1100, FR-1110, FR-1120 |
| **Dependencies**       | Task 1.7 |
| **Complexity**         | M |

**Subtasks**

1. Implement Qdrant upsert with payload metadata.
2. Implement batched upsert with configurable batch size.
3. Add retry logic for transient Qdrant errors.
4. Verify idempotency: re-upserting the same chunk ID overwrites, not duplicates.

**Testing Strategy** — Integration tests against a Qdrant test collection; verify point count does not increase on re-upsert.

---

#### Task 1.9 — Node 12: Result Reporting

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement the reporting node in `src/ingest/nodes/report.py`. Collects per-document statistics (chunks produced, chunks upserted, errors, timings) and writes a structured JSON report. Logs a human-readable summary. |
| **Requirements Covered** | FR-1200, FR-1210 |
| **Dependencies**       | Task 1.8 |
| **Complexity**         | S |

**Subtasks**

1. Define `IngestionReport` dataclass.
2. Aggregate statistics from `PipelineState`.
3. Emit structured JSON report to configured output path.
4. Log human-readable summary at INFO level.

**Testing Strategy** — Unit tests asserting report structure and completeness.

---

#### Task 1.10 — Re-Ingestion Flow (Delete-and-Reinsert)

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement the re-ingestion path in `src/ingest/pipeline_impl.py`. When a document is re-ingested, the pipeline first deletes all existing chunks for that document (by document ID filter) from the vector store, then proceeds with normal ingestion. This ensures stale chunks from a previous version do not persist. |
| **Requirements Covered** | FR-1300, FR-1310, FR-1320 |
| **Dependencies**       | Task 1.8 |
| **Complexity**         | M |

**Subtasks**

1. Implement document-level deletion by document ID filter in Qdrant.
2. Add re-ingestion detection (compare file hash against stored metadata).
3. Wire delete-then-ingest sequence in the runtime orchestrator.
4. Add dry-run mode that reports what would be deleted without executing.

**Testing Strategy** — Integration test: ingest a document, modify it, re-ingest, verify old chunks are gone and new ones are present.

**Risks** — Race condition if two re-ingestions of the same document run concurrently; mitigate with advisory locking.

---

#### Task 1.11 — CLI Entry Point

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement the CLI in `ingest.py` using `argparse` or `click`. Supports single-file and directory-glob modes, config file path, verbosity, and dry-run. |
| **Requirements Covered** | FR-1400, FR-1410 |
| **Dependencies**       | Task 1.2, Task 1.1 |
| **Complexity**         | S |

**Subtasks**

1. Define CLI argument schema (input path, config, verbosity, dry-run, force-reindex).
2. Wire CLI to pipeline public API facade.
3. Implement directory walking with glob patterns and file-type filtering.
4. Add progress bar for batch mode (tqdm).

**Testing Strategy** — CLI smoke tests via subprocess; verify exit codes and report output.

---

### Phase 2: LLM Enhancement

Phase 2 adds LLM-powered intelligence to chunking and metadata enrichment,
improving retrieval quality.

#### Task 2.1 — Node 6: LLM-Assisted Chunking

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Extend the chunking node to support an LLM-assisted mode. When enabled via config, the node sends text segments to an LLM to identify semantically coherent chunk boundaries. Falls back to rule-based chunking on LLM failure or timeout. |
| **Requirements Covered** | FR-640, FR-650, FR-660 |
| **Dependencies**       | Task 1.6 |
| **Complexity**         | L |

**Subtasks**

1. Design the LLM prompt for boundary detection.
2. Implement LLM chunking strategy behind a strategy pattern interface.
3. Add fallback: on LLM error, degrade to rule-based chunking.
4. Cache LLM chunking decisions keyed by content hash to avoid redundant calls.
5. Add cost tracking (token usage) to the report.

**Testing Strategy** — Unit tests with mocked LLM; A/B evaluation comparing rule-based vs. LLM chunk quality on a held-out document set.

**Risks** — LLM latency adds significant wall-clock time; mitigate with caching and parallelism.

---

#### Task 2.2 — Node 8: Metadata Enrichment & Keyword Validation

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement Node 8 in `src/ingest/nodes/enrich.py`. Uses an LLM to extract structured metadata (title, summary, keywords, topic tags) from each chunk. Validates extracted keywords against the domain vocabulary. |
| **Requirements Covered** | FR-800, FR-810, FR-820, FR-830 |
| **Dependencies**       | Task 1.6 |
| **Complexity**         | M |

**Subtasks**

1. Design the metadata extraction prompt (structured JSON output).
2. Implement keyword validation against the domain vocabulary file.
3. Add metadata fields to `PipelineState` chunk records.
4. Implement retry and fallback (empty metadata on LLM failure, not a pipeline error).
5. Wire Node 8 into the graph between chunking and embedding.

**Testing Strategy** — Unit tests with mocked LLM verifying JSON schema compliance; integration test verifying keywords appear in Qdrant payload.

---

#### Task 2.3 — Node 5: Pre-Chunk Analysis & Refactoring

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement Node 5 in `src/ingest/nodes/analyse.py`. Analyses the cleaned document to determine optimal chunking strategy (rule-based vs. LLM), estimate chunk count, and detect structural patterns (tables, lists, code blocks) that require special handling. |
| **Requirements Covered** | FR-500, FR-520, FR-530 |
| **Dependencies**       | Task 2.1 |
| **Complexity**         | M |

**Subtasks**

1. Implement document structure analysis (detect headings, tables, code blocks).
2. Implement chunking strategy selector based on document characteristics.
3. Pass analysis results downstream via `PipelineState` for the chunking node to consume.
4. Wire Node 5 into the graph between cleaning and chunking.

**Testing Strategy** — Unit tests with documents of varying structure; verify correct strategy selection.

---

#### Task 2.4 — Domain Vocabulary System

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement the domain vocabulary loader and management utilities. The vocabulary is a curated list of domain-specific terms used for keyword validation (Task 2.2) and query expansion in retrieval. Stored as a versioned JSON file. |
| **Requirements Covered** | FR-840, FR-850 |
| **Dependencies**       | None |
| **Complexity**         | S |

**Subtasks**

1. Define vocabulary schema (term, synonyms, category, weight).
2. Implement vocabulary loader with file-watching for hot reload.
3. Add CLI subcommand for vocabulary management (add, remove, list).
4. Seed initial vocabulary from existing document corpus.

**Testing Strategy** — Unit tests for loading, validation, and lookup.

---

### Phase 3: Extended Features

Phase 3 adds multi-modal support, cross-document linking, and knowledge graph
construction.

#### Task 3.1 — Node 3: VLM-Based Visual Extraction

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement Node 3 in `src/ingest/nodes/visual.py`. Uses a Vision-Language Model to extract text and descriptions from images, diagrams, and charts embedded in documents. Outputs are merged into the text stream before chunking. |
| **Requirements Covered** | FR-300, FR-330, FR-340 |
| **Dependencies**       | Task 1.4 |
| **Complexity**         | L |

**Subtasks**

1. Implement image extraction from PDF and DOCX documents.
2. Integrate VLM API (GPT-4V or equivalent) for image description.
3. Design the merge strategy for visual content into the text stream.
4. Add cost tracking for VLM calls.
5. Implement fallback: skip visual extraction on VLM failure.

**Testing Strategy** — Integration tests with image-heavy documents; human evaluation of extracted descriptions.

**Risks** — VLM costs can be significant for image-heavy documents; mitigate with configurable per-document image limits.

---

#### Task 3.2 — Node 9: Cross-Document References

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement Node 9 in `src/ingest/nodes/crossref.py`. Detects explicit references between documents (citations, hyperlinks, "see also" patterns) and stores them as edges in chunk metadata. Enables retrieval-time expansion across related documents. |
| **Requirements Covered** | FR-900, FR-910, FR-920 |
| **Dependencies**       | Task 2.2 |
| **Complexity**         | M |

**Subtasks**

1. Implement reference pattern detection (regex + LLM hybrid).
2. Resolve references to existing document IDs in the vector store.
3. Store cross-reference edges in chunk metadata payload.
4. Handle dangling references gracefully (log warning, do not fail).

**Testing Strategy** — Unit tests with synthetic cross-referencing documents; verify edge creation in Qdrant payload.

---

#### Task 3.3 — Nodes 10 & 13: Knowledge Graph Construction

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement Node 10 (`src/ingest/nodes/kg_extract.py`) for entity and relation extraction, and Node 13 (`src/ingest/nodes/kg_write.py`) for writing triples to the knowledge graph store. Node 10 uses an LLM to extract (subject, predicate, object) triples; Node 13 upserts them into the graph database. |
| **Requirements Covered** | FR-1000, FR-1010, FR-1020, FR-1300, FR-1310 |
| **Dependencies**       | Task 2.2 |
| **Complexity**         | L |

**Subtasks**

1. Design the entity/relation extraction prompt.
2. Implement triple normalisation (entity deduplication, canonical forms).
3. Implement graph store writer (Neo4j or equivalent).
4. Add provenance tracking (which chunk produced which triple).
5. Wire Nodes 10 and 13 into the graph with conditional activation via feature flag.

**Testing Strategy** — Unit tests with mocked LLM; integration tests verifying triples in graph store; evaluate extraction precision on annotated test set.

**Risks** — Entity deduplication is inherently noisy; plan for iterative prompt refinement.

---

#### Task 3.4 — Review Tier System

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement a configurable review tier system that gates certain documents for human review before they become searchable. Tiers are based on document source, sensitivity classification, or extraction confidence scores. |
| **Requirements Covered** | FR-1500, FR-1510 |
| **Dependencies**       | Task 1.9 |
| **Complexity**         | M |

**Subtasks**

1. Define tier classification rules (configurable per source).
2. Add a `review_status` field to chunk metadata.
3. Implement review queue (database-backed, exposed via API).
4. Add CLI subcommand for review management (approve, reject, list pending).

**Testing Strategy** — Unit tests for tier classification; integration test for the full review lifecycle.

---

#### Task 3.5 — PPTX and XLSX Extractors

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Add extractors for PowerPoint (PPTX) and Excel (XLSX) file formats to the Node 2 extractor registry. PPTX extracts slide text and speaker notes; XLSX extracts cell values with sheet and header context. |
| **Requirements Covered** | FR-440, FR-450 |
| **Dependencies**       | Task 1.4 |
| **Complexity**         | M |

**Subtasks**

1. Implement `PptxExtractor` using python-pptx; preserve slide ordering and speaker notes.
2. Implement `XlsxExtractor` using openpyxl; include header rows as context for data cells.
3. Register new extractors in the dispatcher.
4. Add fixture files and unit tests.

**Testing Strategy** — Unit tests with representative PPTX and XLSX fixtures.

---

### Phase 4: Quality & Operations

Phase 4 hardens the pipeline for production: evaluation, observability, batch
processing at scale, and schema evolution.

#### Task 4.1 — Evaluation Framework & Dataset

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Build an evaluation framework that measures ingestion quality across dimensions: chunking coherence, metadata accuracy, embedding fidelity, and end-to-end retrieval relevance. Includes a curated evaluation dataset with ground-truth annotations. |
| **Requirements Covered** | FR-1600, FR-1610, FR-1620 |
| **Dependencies**       | Phase 1 complete |
| **Complexity**         | L |

**Subtasks**

1. Define evaluation metrics (chunk coherence score, metadata precision/recall, retrieval MRR).
2. Curate an evaluation dataset (minimum 50 documents with annotations).
3. Implement automated evaluation harness runnable via CLI.
4. Add regression detection: alert if metrics drop below configured thresholds.
5. Integrate evaluation into CI pipeline.

**Testing Strategy** — The evaluation framework is itself the testing strategy for the pipeline.

---

#### Task 4.2 — Langfuse Observability Integration

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Integrate Langfuse for end-to-end pipeline observability. Each pipeline run creates a trace; each node creates a span. LLM calls are captured with token counts, latencies, and costs. Errors are tagged and searchable. |
| **Requirements Covered** | FR-1700, FR-1710, FR-1720 |
| **Dependencies**       | Task 1.2 |
| **Complexity**         | M |

**Subtasks**

1. Add Langfuse SDK dependency and configuration.
2. Instrument the pipeline runtime (`pipeline_impl.py`) with trace creation.
3. Instrument each node with span creation and metadata tagging.
4. Capture LLM calls via the shared LLM helper (`pipeline_llm.py`).
5. Add error tagging and alerting rules.

**Testing Strategy** — Integration test verifying traces appear in Langfuse; unit tests with mocked Langfuse client.

---

#### Task 4.3 — Batch Processing Hardening

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Harden the pipeline for large batch runs (1000+ documents). Add concurrency controls, progress checkpointing, partial failure recovery, and memory management for large documents. |
| **Requirements Covered** | FR-1800, FR-1810, FR-1820, FR-1830 |
| **Dependencies**       | Task 1.11 |
| **Complexity**         | L |

**Subtasks**

1. Implement configurable concurrency (async semaphore for parallel document processing).
2. Add progress checkpointing: persist completed document IDs so a crashed batch can resume.
3. Implement partial failure isolation: a single document failure does not abort the batch.
4. Add memory profiling and per-document memory limits for large files.
5. Add batch-level reporting (aggregate statistics across all documents).

**Testing Strategy** — Load test with 500+ synthetic documents; verify checkpoint recovery after simulated crash.

**Risks** — Memory pressure from large documents; mitigate with streaming extraction and chunk-at-a-time processing.

---

#### Task 4.4 — Schema Migration

| Attribute              | Detail |
|------------------------|--------|
| **Description**        | Implement schema migration tooling for the vector store and metadata payloads. As the pipeline evolves, chunk metadata schemas change; this task ensures existing data can be migrated forward without full re-ingestion. |
| **Requirements Covered** | FR-2000, FR-2010, FR-2100 |
| **Dependencies**       | Task 1.8 |
| **Complexity**         | M |

**Subtasks**

1. Define a metadata schema version field in chunk payloads.
2. Implement migration registry (version → migration function).
3. Implement CLI subcommand for running migrations (`ingest.py migrate`).
4. Add dry-run mode for migrations.
5. Add rollback support for failed migrations.

**Testing Strategy** — Unit tests for each migration function; integration test verifying migration on a populated test collection.

---

### Task Dependency Graph

```
Task 1.1  ──────────────────────┐
  │                             │
  v                             v
Task 1.2  ──> Task 1.11       Task 2.4
  │
  v
Task 1.3
  │
  v
Task 1.4 ──────────────────> Task 3.1 (VLM)
  │                         Task 3.5 (PPTX/XLSX)
  v
Task 1.5
  │
  v
Task 1.6 ──> Task 2.1 (LLM Chunking) ──> Task 2.3
  │           Task 2.2 (Metadata)      ──> Task 3.2
  v                                    ──> Task 3.3
Task 1.7
  │
  v
Task 1.8 ──> Task 1.10 (Re-ingestion)
  │           Task 4.4  (Schema Migration)
  v
Task 1.9 ──> Task 3.4 (Review Tiers)

Task 1.2 ──> Task 4.2 (Langfuse)
Task 1.11 ─> Task 4.3 (Batch Hardening)
Phase 1  ──> Task 4.1 (Evaluation)
```

---

### Task-to-Requirement Mapping

| Requirement | Description                      | Task(s)          |
|-------------|----------------------------------|------------------|
| FR-100      | Pipeline configuration           | 1.1              |
| FR-110      | Environment variable overrides   | 1.1              |
| FR-120      | Configuration validation         | 1.1              |
| FR-200      | LangGraph DAG topology           | 1.2              |
| FR-210      | Conditional edge routing         | 1.2              |
| FR-220      | Node registration                | 1.2              |
| FR-230      | Graph compilation                | 1.2              |
| FR-300      | Document intake                  | 1.3, 3.1         |
| FR-310      | MIME type detection               | 1.3              |
| FR-320      | File hash computation            | 1.3              |
| FR-330      | Visual content extraction        | 3.1              |
| FR-340      | VLM integration                  | 3.1              |
| FR-400      | Text extraction (PDF)            | 1.4              |
| FR-410      | Text extraction (DOCX)           | 1.4              |
| FR-420      | Text extraction (Markdown)       | 1.4              |
| FR-430      | Structural marker preservation   | 1.4              |
| FR-440      | Text extraction (PPTX)           | 3.5              |
| FR-450      | Text extraction (XLSX)           | 3.5              |
| FR-500      | Text cleaning                    | 1.5, 2.3         |
| FR-510      | Unicode normalisation            | 1.5              |
| FR-520      | Document structure analysis      | 2.3              |
| FR-530      | Chunking strategy selection      | 2.3              |
| FR-600      | Rule-based chunking              | 1.6              |
| FR-610      | Chunk size configuration         | 1.6              |
| FR-620      | Overlap configuration            | 1.6              |
| FR-630      | Deterministic chunk IDs          | 1.6              |
| FR-640      | LLM-assisted chunking           | 2.1              |
| FR-650      | LLM chunking fallback           | 2.1              |
| FR-660      | Chunking cost tracking           | 2.1              |
| FR-700      | Embedding generation             | 1.7              |
| FR-710      | Embedding batching               | 1.7              |
| FR-720      | Embedding retry logic            | 1.7              |
| FR-800      | Metadata extraction              | 2.2              |
| FR-810      | Keyword extraction               | 2.2              |
| FR-820      | Keyword validation               | 2.2              |
| FR-830      | Metadata schema                  | 2.2              |
| FR-840      | Domain vocabulary                | 2.4              |
| FR-850      | Vocabulary management            | 2.4              |
| FR-900      | Cross-document references        | 3.2              |
| FR-910      | Reference resolution             | 3.2              |
| FR-920      | Reference storage                | 3.2              |
| FR-1000     | Entity extraction                | 3.3              |
| FR-1010     | Relation extraction              | 3.3              |
| FR-1020     | Triple normalisation             | 3.3              |
| FR-1100     | Vector store upsert              | 1.8              |
| FR-1110     | Batched upsert                   | 1.8              |
| FR-1120     | Upsert idempotency               | 1.8              |
| FR-1200     | Result reporting                 | 1.9              |
| FR-1210     | Report format                    | 1.9              |
| FR-1300     | Re-ingestion delete              | 1.10, 3.3        |
| FR-1310     | Re-ingestion detection           | 1.10, 3.3        |
| FR-1320     | Re-ingestion dry-run             | 1.10             |
| FR-1400     | CLI entry point                  | 1.11             |
| FR-1410     | CLI batch mode                   | 1.11             |
| FR-1500     | Review tier classification       | 3.4              |
| FR-1510     | Review queue                     | 3.4              |
| FR-1600     | Evaluation metrics               | 4.1              |
| FR-1610     | Evaluation dataset               | 4.1              |
| FR-1620     | Regression detection             | 4.1              |
| FR-1700     | Langfuse trace creation          | 4.2              |
| FR-1710     | Langfuse span instrumentation    | 4.2              |
| FR-1720     | LLM call capture                 | 4.2              |
| FR-1800     | Concurrency controls             | 4.3              |
| FR-1810     | Progress checkpointing           | 4.3              |
| FR-1820     | Partial failure recovery         | 4.3              |
| FR-1830     | Memory management                | 4.3              |
| FR-2000     | Metadata schema versioning       | 4.4              |
| FR-2010     | Schema migration tooling         | 4.4              |
| FR-2100     | Migration rollback               | 4.4              |

---

## Part B: Code Appendix

The following snippets illustrate the key design patterns used in the
pipeline. They are representative, not exhaustive — consult the source code
for the full implementation.

---

### B.1 — Pipeline Workflow Composition (LangGraph DAG)

**Covers:** Task 1.2 | **Requirements:** FR-200, FR-210, FR-220, FR-230

```python
# src/ingest/pipeline_workflow.py

from langgraph.graph import StateGraph, END
from src.ingest.pipeline_types import PipelineState, PipelineConfig
from src.ingest.nodes.intake import intake_node
from src.ingest.nodes.extract import extract_node
from src.ingest.nodes.clean import clean_node
from src.ingest.nodes.analyse import analyse_node
from src.ingest.nodes.chunk import chunk_node
from src.ingest.nodes.embed import embed_node
from src.ingest.nodes.enrich import enrich_node
from src.ingest.nodes.visual import visual_node
from src.ingest.nodes.crossref import crossref_node
from src.ingest.nodes.kg_extract import kg_extract_node
from src.ingest.nodes.upsert import upsert_node
from src.ingest.nodes.report import report_node
from src.ingest.nodes.kg_write import kg_write_node


def _route_after_extract(state: PipelineState) -> str:
    """Route to VLM node if images are present and feature is enabled."""
    if state.get("has_images") and state["config"].enable_vlm:
        return "visual"
    return "clean"


def _route_after_chunk(state: PipelineState) -> str:
    """Route to metadata enrichment if LLM features are enabled."""
    if state["config"].enable_metadata_enrichment:
        return "enrich"
    return "embed"


def _route_after_upsert(state: PipelineState) -> str:
    """Route to KG extraction if knowledge graph is enabled."""
    if state["config"].enable_knowledge_graph:
        return "kg_extract"
    return "report"


def build_graph(config: PipelineConfig) -> StateGraph:
    """Construct the 13-node ingestion DAG."""
    graph = StateGraph(PipelineState)

    # Register all nodes
    graph.add_node("intake", intake_node)
    graph.add_node("extract", extract_node)
    graph.add_node("visual", visual_node)
    graph.add_node("clean", clean_node)
    graph.add_node("analyse", analyse_node)
    graph.add_node("chunk", chunk_node)
    graph.add_node("enrich", enrich_node)
    graph.add_node("embed", embed_node)
    graph.add_node("crossref", crossref_node)
    graph.add_node("kg_extract", kg_extract_node)
    graph.add_node("upsert", upsert_node)
    graph.add_node("report", report_node)
    graph.add_node("kg_write", kg_write_node)

    # Define edges
    graph.set_entry_point("intake")
    graph.add_edge("intake", "extract")
    graph.add_conditional_edges("extract", _route_after_extract,
                                {"visual": "visual", "clean": "clean"})
    graph.add_edge("visual", "clean")
    graph.add_edge("clean", "analyse")
    graph.add_edge("analyse", "chunk")
    graph.add_conditional_edges("chunk", _route_after_chunk,
                                {"enrich": "enrich", "embed": "embed"})
    graph.add_edge("enrich", "embed")
    graph.add_edge("embed", "crossref")
    graph.add_edge("crossref", "upsert")
    graph.add_conditional_edges("upsert", _route_after_upsert,
                                {"kg_extract": "kg_extract", "report": "report"})
    graph.add_edge("kg_extract", "kg_write")
    graph.add_edge("kg_write", "report")
    graph.add_edge("report", END)

    return graph
```

**Key design decisions:**

- **Conditional edges** are driven by `PipelineConfig` feature flags, not by
  removing nodes from the graph. This keeps the topology static and
  debuggable; disabled nodes simply are never reached.
- **Single entry point** (`intake`) and single exit point (`report`) simplify
  observability — every trace has the same shape.
- **Node functions** are plain functions, not classes, matching LangGraph
  conventions. Shared state is passed via `PipelineState`; side-effect
  dependencies (API clients, DB connections) are injected through the config.

---

### B.2 — Node Base Pattern and Sample Node Implementation

**Covers:** Tasks 1.3, 1.4, 1.5, 1.6 | **Requirements:** FR-300, FR-400, FR-500, FR-600

```python
# src/ingest/pipeline_types.py  (excerpt)

from typing import TypedDict, Any, Protocol
from dataclasses import dataclass


class PipelineState(TypedDict, total=False):
    """Shared state flowing through every node in the DAG."""
    config: "PipelineConfig"
    source_path: str
    file_hash: str
    mime_type: str
    raw_text: str
    has_images: bool
    cleaned_text: str
    analysis: dict[str, Any]
    chunks: list["ChunkRecord"]
    embeddings: list[list[float]]
    enrichment: list[dict[str, Any]]
    cross_refs: list[dict[str, str]]
    kg_triples: list[tuple[str, str, str]]
    upsert_results: dict[str, Any]
    report: dict[str, Any]
    errors: list[dict[str, Any]]
    timings: dict[str, float]


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    ordinal: int
    text: str
    char_offset_start: int
    char_offset_end: int
    metadata: dict[str, Any]


# --- Sample Node ---
# src/ingest/nodes/intake.py

import hashlib
import time
from pathlib import Path
import magic

from src.ingest.pipeline_types import PipelineState


SUPPORTED_MIME_TYPES = frozenset({
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "text/markdown",
})


def intake_node(state: PipelineState) -> PipelineState:
    """Node 1: Validate input file and populate initial state."""
    start = time.perf_counter()

    source_path = state["source_path"]
    path = Path(source_path)

    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    # Detect MIME type
    mime_type = magic.from_file(str(path), mime=True)
    if mime_type not in SUPPORTED_MIME_TYPES:
        raise ValueError(
            f"Unsupported file type: {mime_type} for {source_path}"
        )

    # Compute SHA-256 hash for deterministic ID generation
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            hasher.update(block)
    file_hash = hasher.hexdigest()

    elapsed = time.perf_counter() - start
    return {
        **state,
        "file_hash": file_hash,
        "mime_type": mime_type,
        "has_images": mime_type == "application/pdf",
        "errors": state.get("errors", []),
        "timings": {**state.get("timings", {}), "intake": elapsed},
    }
```

**Key design decisions:**

- **Nodes are pure functions** that accept `PipelineState` and return a new
  (or updated) `PipelineState`. This makes them independently testable — no
  graph runtime needed.
- **Immutable return pattern** — nodes spread the incoming state and override
  only the keys they own. This prevents accidental mutation of upstream data.
- **Timing instrumentation** is built into every node from the start, not
  bolted on later. The `timings` dict accumulates per-node wall-clock
  durations for the reporting node and Langfuse spans.
- **Fail-fast validation** — the intake node raises immediately on unsupported
  types rather than letting invalid data flow downstream.

---

### B.3 — Deterministic ID Generation

**Covers:** Task 1.6 | **Requirements:** FR-630

```python
# src/ingest/pipeline_shared.py  (excerpt)

import hashlib


def generate_document_id(file_hash: str, source_path: str) -> str:
    """Generate a deterministic document ID from file content hash and path.

    The ID is stable across re-ingestion of the same file at the same path.
    Changing the file content changes the hash; moving the file changes the
    path component — both produce a new ID, which is the desired behaviour
    for the re-ingestion flow (delete old, insert new).
    """
    composite = f"{file_hash}:{source_path}"
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()[:24]


def generate_chunk_id(document_id: str, chunk_ordinal: int) -> str:
    """Generate a deterministic chunk ID from document ID and ordinal.

    Because the document ID already encodes file content, and the ordinal
    is determined by the chunking algorithm (which is deterministic for a
    given configuration), the chunk ID is fully reproducible. Re-ingesting
    the same unchanged file produces the same chunk IDs, enabling
    idempotent upserts.
    """
    composite = f"{document_id}:chunk:{chunk_ordinal}"
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()[:24]
```

**Key design decisions:**

- **Content-addressable IDs** — the document ID is derived from the file hash,
  so identical content always maps to the same ID regardless of when ingestion
  occurs.
- **Ordinal-based chunk IDs** — chunk IDs incorporate the chunk ordinal, not
  the chunk text hash. This is deliberate: if two chunks happen to have
  identical text (e.g., repeated boilerplate), they still receive distinct IDs
  and occupy distinct vectors.
- **Truncation to 24 hex characters** — 96 bits of entropy is sufficient for
  collision avoidance at the expected corpus scale (< 10M documents) while
  keeping IDs human-readable in logs and debugger output.
- **Path inclusion** — including the source path means the same file ingested
  from two different locations produces two separate document entries. This
  supports multi-tenant or multi-collection use cases.

---

### B.4 — Re-Ingestion Flow (Delete-and-Reinsert)

**Covers:** Task 1.10 | **Requirements:** FR-1300, FR-1310, FR-1320

```python
# src/ingest/pipeline_impl.py  (excerpt)

import logging
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

from src.ingest.pipeline_shared import generate_document_id
from src.ingest.pipeline_types import PipelineConfig, PipelineState
from src.ingest.pipeline_workflow import build_graph

logger = logging.getLogger(__name__)


class PipelineRuntime:
    """Orchestrates pipeline execution with re-ingestion support."""

    def __init__(self, config: PipelineConfig, qdrant: QdrantClient):
        self._config = config
        self._qdrant = qdrant
        self._graph = build_graph(config).compile()

    def _delete_existing_chunks(
        self, collection: str, document_id: str, *, dry_run: bool = False
    ) -> int:
        """Delete all chunks belonging to a document. Returns count deleted."""
        doc_filter = Filter(
            must=[
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=document_id),
                )
            ]
        )

        # Count existing points for reporting
        existing = self._qdrant.count(
            collection_name=collection, count_filter=doc_filter, exact=True
        )
        count = existing.count

        if count == 0:
            return 0

        if dry_run:
            logger.info(
                "Dry-run: would delete %d chunks for document %s",
                count, document_id,
            )
            return count

        self._qdrant.delete(
            collection_name=collection, points_selector=doc_filter
        )
        logger.info(
            "Deleted %d existing chunks for document %s", count, document_id
        )
        return count

    def ingest(
        self,
        source_path: str,
        file_hash: str,
        *,
        force: bool = False,
        dry_run: bool = False,
    ) -> PipelineState:
        """Run the ingestion pipeline for a single document.

        If the document has been previously ingested (detected via document
        ID lookup in the vector store), existing chunks are deleted first
        to prevent stale data. The ``force`` flag skips the hash comparison
        and always re-ingests.
        """
        document_id = generate_document_id(file_hash, source_path)
        collection = self._config.qdrant_collection

        # Check for prior ingestion
        doc_filter = Filter(
            must=[
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=document_id),
                )
            ]
        )
        existing = self._qdrant.count(
            collection_name=collection, count_filter=doc_filter, exact=True
        )

        if existing.count > 0:
            if not force:
                # Compare stored hash — if unchanged, skip re-ingestion
                stored = self._qdrant.scroll(
                    collection_name=collection,
                    scroll_filter=doc_filter,
                    limit=1,
                    with_payload=["file_hash"],
                )
                if stored[0] and stored[0][0].payload.get("file_hash") == file_hash:
                    logger.info(
                        "Document %s unchanged (hash match), skipping. "
                        "Use --force to re-ingest.",
                        source_path,
                    )
                    return {"skipped": True, "document_id": document_id}

            # Delete existing chunks before re-ingestion
            self._delete_existing_chunks(collection, document_id, dry_run=dry_run)

        if dry_run:
            logger.info("Dry-run: would ingest %s", source_path)
            return {"dry_run": True, "document_id": document_id}

        # Run the pipeline graph
        initial_state: PipelineState = {
            "config": self._config,
            "source_path": source_path,
            "file_hash": file_hash,
        }
        result = self._graph.invoke(initial_state)
        return result
```

**Key design decisions:**

- **Delete-before-insert, not update-in-place** — when a document changes,
  the chunk count and boundaries may differ from the previous version. Deleting
  all old chunks and inserting fresh ones is simpler and more correct than
  attempting per-chunk diffing.
- **Hash-based skip** — if the file hash has not changed since the last
  ingestion, the pipeline skips entirely. This makes batch re-runs cheap
  when only a few files have changed.
- **Dry-run support** — the `--dry-run` CLI flag flows through to this layer,
  enabling operators to preview what a re-ingestion would do without modifying
  the vector store.
- **Force flag** — overrides the hash comparison, useful when the pipeline
  code has changed (e.g., new chunking strategy) and all documents need
  re-processing even though their content has not changed.
