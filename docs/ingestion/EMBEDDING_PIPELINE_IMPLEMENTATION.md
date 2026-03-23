# Embedding Pipeline — Implementation Guide

| Field | Value |
|-------|-------|
| **Document** | Embedding Pipeline Implementation Guide |
| **Version** | 1.0.0 |
| **Status** | Active |
| **Spec Reference** | `EMBEDDING_PIPELINE_SPEC.md` v1.0.0 (FR-591–FR-1304) |
| **Companion Documents** | `EMBEDDING_PIPELINE_SPEC.md`, `EMBEDDING_PIPELINE_SPEC_SUMMARY.md`, `DOCUMENT_PROCESSING_IMPLEMENTATION.md`, `INGESTION_PIPELINE_ENGINEERING_GUIDE.md`, `INGESTION_NEW_ENGINEER_ONBOARDING_CHECKLIST.md`, `INGESTION_PLATFORM_SPEC.md` |
| **Created** | 2026-03-20 |
| **Last Updated** | 2026-03-20 |

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-03-20 | Split from `INGESTION_PIPELINE_IMPLEMENTATION.md` v1.1.0 — Embedding Pipeline phase tasks only. |

> **Document Intent.** This guide translates the requirements defined in `EMBEDDING_PIPELINE_SPEC.md`
> (FR-591–FR-1304) into a phased, task-oriented implementation plan. Each task maps to one or more
> specification requirements and includes subtasks, complexity estimates, dependencies, and testing
> strategies.
>
> The Embedding Pipeline reads clean Markdown documents from the **Clean Document Store** (produced
> by the Document Processing Pipeline) and transforms them into vector embeddings and knowledge
> graph triples stored in the vector database and graph store.
>
> **Entry point:** `{source_key}.md` + `{source_key}.meta.json` in the Clean Document Store.
> See `DOCUMENT_PROCESSING_IMPLEMENTATION.md` → Task S.1 for the writer implementation.
>
> Part A is organised in four groups:
> - **Part A0 — Clean Document Store (Reader):** Task S.2 reads the boundary artifact written by the
>   Document Processing Pipeline.
> - **Phase 1 — Core Embedding (MVP):** Rule-based chunking → enrichment → embedding → storage.
> - **Phase 2 — LLM Enhancement:** Semantic chunking, metadata generation, knowledge enrichment.
> - **Phase 3 — Extended Features:** Cross-references, knowledge graph, review tiers.
> - **Phase 4 — Quality & Operations:** Evaluation, observability, batch hardening, schema migration.

---

# Part A: Task-Oriented Overview

## Part A0: Clean Document Store (Reader)

The Clean Document Store is the storage boundary between the Document Processing Pipeline and this
pipeline. The Document Processing Pipeline writes the store (Task S.1 in
`DOCUMENT_PROCESSING_IMPLEMENTATION.md`); this pipeline reads it. Change detection is based on
`clean_hash` — the SHA-256 of the clean Markdown content — not on the source file hash.

---

### Task S.2 — Clean Document Store Reader and Change Detection

**Description:** Implement the Clean Document Store reader in `src/ingest/clean_store.py`.
Reads and validates metadata envelopes from the Clean Document Store; compares `clean_hash`
against the stored embedding-run manifest to determine whether re-embedding is needed.

**Requirements Covered:** FR-591, FR-592, FR-593, FR-594, FR-595

**Dependencies:** None (reads from disk; no pipeline dependency)

**Complexity:** S

**Subtasks:**
1. Implement `read(source_key) → (md_content, CleanDocumentMetadata)` raising
   `MissingCleanDocumentError` if the `.md` file is absent (FR-591).
2. Implement metadata validation: check all required fields are present; raise
   `InvalidMetadataError` on schema violation (FR-592).
3. Implement `clean_hash` change detection: load the embedding run manifest (keyed by
   `source_key`); compare stored `clean_hash` with the metadata value — skip if unchanged
   (FR-593).
4. Implement `propagate_metadata_to_chunk(chunk, metadata)` helper: attaches `source_key`,
   `source_path`, `review_tier`, and `extraction_confidence` from the metadata envelope to a
   chunk record (FR-594).
5. Optionally verify that the actual SHA-256 of `{source_key}.md` matches the `clean_hash`
   in metadata; log a warning on mismatch without halting (FR-595).

**Testing Strategy:** Unit tests for missing file, malformed JSON, and hash mismatch scenarios.
Verify `propagate_metadata_to_chunk` attaches all required fields.

---

## Phase 1 — Core Embedding Pipeline (MVP)

The goal of Phase 1 is a working end-to-end Embedding Pipeline: clean documents are read from
the store, split into chunks with deterministic IDs, enriched, embedded, and stored in the
vector database. Re-ingestion detection (skipping unchanged documents) must work from day one.

---

### Task 1.2 — Embedding Pipeline DAG Skeleton

**Description:** Build the LangGraph `StateGraph` for the Embedding Pipeline in
`src/ingest/pipeline_workflow.py`. Phase 1 wires only the MVP nodes (clean store read,
chunking, chunk enrichment, quality validation, embedding/storage); optional nodes
(cross-reference, KG extraction, KG storage) are no-op pass-throughs until their tasks are
complete.

**Requirements Covered:** FR-591, FR-901, FR-1001, FR-1301

**Dependencies:** Task S.2

**Complexity:** M

**Subtasks:**
1. Define `EmbeddingPipelineState` TypedDict in `pipeline_types.py` with all required state
   keys (source key, chunks, enriched chunks, metadata, embeddings, KG triples, errors, timings).
2. Create `build_embedding_pipeline_graph()` factory in `pipeline_workflow.py`.
3. Implement conditional routing: post-enrichment optional cross-reference stage (FR-901);
   post-quality optional KG extraction stage (FR-1001); post-storage optional KG write stage
   (FR-1301).
4. Register no-op stubs for Phase 2/3 nodes.
5. Expose `compile()` → `CompiledGraph` via the public API facade in
   `src/ingest/pipeline/__init__.py`.

**Testing Strategy:** Verify graph topology; run a synthetic document through the stub graph
and assert all state keys are preserved end-to-end.

**Risks:** LangGraph API surface evolves; pin the dependency version.

---

### Task 1.6 — Node 6: Chunking (Rule-Based MVP)

**Description:** Implement the chunking node in `src/ingest/nodes/chunking.py`. Phase 1 uses
deterministic, rule-based chunking: split on Markdown heading boundaries first, then
recursive character splitting with configurable `chunk_size` and `overlap`. Each chunk
receives a deterministic ID derived from the document `source_key` and chunk ordinal.

**Requirements Covered:** FR-601, FR-602, FR-603, FR-604, FR-605

**Dependencies:** Task S.2, Task 1.2

**Complexity:** M

**Subtasks:**
1. Implement heading-aware structural splitting: respect Markdown `#`/`##`/`###` boundaries
   as primary split points.
2. Implement recursive character splitter as secondary fallback when a section exceeds the
   configured chunk size.
3. Generate deterministic chunk IDs: `SHA-256(source_key + ":" + str(ordinal) + ":" + content_hash)[:24]`
   where `content_hash = SHA-256(chunk_text)[:16]` — same input always produces the same IDs
   (see Part B, Snippet B.3). The content hash component ensures that if a chunk's content
   changes during re-chunking (while keeping the same ordinal position), the ID changes
   accordingly, enabling accurate change detection per FR-605.
4. Attach chunk metadata: ordinal, `source_key`, character offsets, heading path context.
5. Validate chunk sizes against configured `min_chunk_tokens` and `max_chunk_tokens`; split
   oversized chunks and log undersized ones.
6. **Table atomic chunking (FR-604):** Treat tables as indivisible chunks. If a table exceeds
   `max_chunk_tokens`, split by row groups while prepending the header row to each resulting
   chunk. Respect the `tables.keep_atomic` configuration flag.
7. **Adjacency links (FR-606):** After chunking, assign `previous_chunk_id` and
   `next_chunk_id` to each chunk. First chunk has `previous_chunk_id = null`; last chunk has
   `next_chunk_id = null`. These links enable sequential navigation at retrieval time.

**Testing Strategy:** Unit tests asserting deterministic output (same input always produces
same chunk IDs); property tests on chunk size bounds.

---

### Task 1.7 — Node 12: Embedding Generation

**Description:** Implement the embedding generation node in `src/ingest/nodes/embedding_storage.py`.
Sends `enriched_content` from each chunk to the configured embedding model with batching,
retry, and rate-limit handling. In BYOM mode, accepts pre-computed vectors instead of calling
the embedding API.

**Requirements Covered:** FR-1201, FR-1202, FR-1203, FR-1204

**Dependencies:** Task 1.6 (or Task 2.2a when enrichment is enabled)

**Complexity:** M

**Subtasks:**
1. Implement batched embedding calls with configurable batch size.
2. Add exponential backoff retry with jitter on transient errors (429, 5xx).
3. Add token-count pre-validation: reject chunks exceeding model context window before sending.
4. Implement BYOM mode: when `config.byom_mode = true`, accept pre-computed vector field from
   chunk state instead of calling the API.
5. Attach embedding vectors and model metadata (`model_name`, `dimension`) to chunk state.
6. **Dimensionality validation (FR-1203):** After generating embeddings, validate that the
   output vector dimension matches the expected dimension from model configuration. If mismatch
   detected, halt the pipeline with a clear error message naming the expected vs actual
   dimensions.

**Testing Strategy:** Unit tests with mocked embedding API; integration test with live API
behind a feature flag. Verify BYOM mode bypasses the API call entirely.

**Risks:** Rate limits under batch load; mitigate with configurable concurrency and backoff.

---

### Task 1.8 — Node 12: Vector Store Upsert

**Description:** Implement the vector store write step within `src/ingest/nodes/embedding_storage.py`.
Writes embedded chunks to the vector store (Weaviate). Uses deterministic IDs so that
re-ingestion overwrites existing vectors without creating duplicates. On re-ingestion, deletes
all existing chunks for the document before inserting fresh ones.

**Requirements Covered:** FR-1205, FR-1206, FR-1207, FR-1208, FR-1209

**Dependencies:** Task 1.7

**Complexity:** M

**Subtasks:**
1. Implement Weaviate upsert with full chunk payload (embedding + metadata + review tier).
2. Implement batched upsert with configurable batch size.
3. Implement re-ingestion delete-and-reinsert: before inserting, delete all existing vectors
   keyed by `source_key` filter; this ensures stale chunks from a previous version do not
   persist.
4. Add retry logic for transient vector store errors.
5. Verify idempotency: re-upserting the same chunk ID overwrites, not duplicates. Verify point
   count does not increase on re-run of an unchanged document.
6. **Asymmetric embedding prefixes (FR-1206):** Support configurable document and query
   prefixes for asymmetric embedding models (e.g., `passage:` for documents, `query:` for
   queries). Read prefix configuration from `embedding.document_prefix` and
   `embedding.query_prefix` config keys. Apply document prefix during ingestion; query prefix
   is applied at retrieval time.
7. **Hybrid search setup (FR-1207):** Configure BM25 keyword indexing alongside vector
   indexing in the vector store. Enable via `storage.enable_bm25` configuration flag (default:
   `true`). The BM25 index uses the same `enriched_content` text as the vector embedding.

**Testing Strategy:** Integration tests against a Weaviate test collection; verify point count
does not increase on re-upsert; verify stale chunks are gone after re-ingestion of a changed
document.

---

### Task 1.9 — Result Reporting

**Description:** Implement the reporting node in `src/ingest/nodes/embedding_storage.py` (or
a dedicated `report.py`). Collects per-document statistics (chunks produced, chunks embedded,
chunks upserted, quality-filter rejections, errors, timings) and writes a structured JSON
report. Logs a human-readable summary.

**Requirements Covered:** FR-1201 (storage completeness reporting)

**Dependencies:** Task 1.8

**Complexity:** S

**Subtasks:**
1. Define `EmbeddingReport` dataclass with all relevant metrics.
2. Aggregate statistics from `EmbeddingPipelineState`.
3. Emit structured JSON report to the configured output path.
4. Log human-readable summary at INFO level.

**Testing Strategy:** Unit tests asserting report structure and completeness.

---

### Task 1.10 — Re-Ingestion Flow (Delete-and-Reinsert)

**Description:** Implement the re-ingestion path in `src/ingest/pipeline_impl.py`. When a
document's `clean_hash` has changed, the pipeline first deletes all existing chunks for that
document from the vector store, then proceeds with normal embedding. A dry-run mode reports
what would be deleted without executing.

**Requirements Covered:** FR-593, FR-1205, FR-1208

**Dependencies:** Task S.2, Task 1.8

**Complexity:** M

**Subtasks:**
1. Implement document-level deletion from Weaviate by `source_key` filter.
2. Wire the `clean_hash` comparison (Task S.2) into the pipeline runtime: if unchanged, skip
   the entire embedding graph invocation.
3. Implement `force` flag to bypass hash comparison and always re-embed.
4. Add dry-run mode: report what would be deleted without executing.

**Testing Strategy:** Integration test: ingest a document, modify the clean Markdown, re-ingest,
verify old chunks are gone and new ones are present.

**Risks:** Race condition if two re-ingestions of the same document run concurrently; mitigate
with advisory locking.

---

## Part A0 ends — Phase 2 begins

---

## Phase 2 — LLM Enhancement

Phase 2 adds LLM-powered intelligence to chunking, chunk enrichment, and metadata generation,
improving retrieval quality through semantic boundary detection and structured keyword/entity
extraction.

---

### Task 2.1 — Node 6: LLM-Assisted Chunking

**Description:** Extend the chunking node to support an LLM-assisted mode. When enabled via
config, the node sends text segments to an LLM to identify semantically coherent chunk
boundaries. Falls back to rule-based chunking on LLM failure or timeout.

**Requirements Covered:** FR-606, FR-607, FR-608, FR-609, FR-610, FR-611

**Dependencies:** Task 1.6

**Complexity:** L

**Subtasks:**
1. Design the LLM prompt for boundary detection: given a document section, identify where
   semantic topic transitions occur.
2. Implement LLM chunking strategy behind the same strategy interface used by the rule-based
   chunker.
3. Add fallback: on LLM error, degrade to rule-based chunking transparently.
4. Cache LLM chunking decisions keyed by `clean_hash` + section ordinal to avoid redundant
   calls on unchanged documents.
5. Add token usage tracking to the run report.
6. **Content type tagging (FR-609):** Tag each chunk with its dominant content type: `text`,
   `table`, `figure`, `code`, `equation`, `list`, or `heading`. Derive the tag from the
   chunk's source structure (e.g., Markdown table syntax -> `table`, code fences -> `code`).
   Store as `content_type` field in chunk metadata.

**Testing Strategy:** Unit tests with mocked LLM; A/B evaluation comparing rule-based vs. LLM
chunk quality on a held-out document set.

**Risks:** LLM latency adds significant wall-clock time; mitigate with caching and
section-level parallelism.

---

### Task 2.2a — Node 7: Chunk Enrichment (FR-701–FR-705)

**Description:** Implement Node 7 (`src/ingest/nodes/chunk_enrichment.py`) for boundary
context attachment, metadata header construction, and cross-chunk overlap. This stage
prepares the enriched content that will be embedded.

**Requirements Covered:** FR-701, FR-702, FR-703, FR-704, FR-705

**Dependencies:** Task 1.6

**Complexity:** M

**Subtasks:**
1. **Boundary context window:** Attach `context_header` to each chunk: a brief text header
   summarising the document source, section path, and review tier (FR-701, FR-702).
2. **Enriched content computation:** Compute `enriched_content = chunk_text + boundary_context`
   — this is the text that will be embedded (FR-703). The `context_header` (document title,
   section path, source metadata) is stored alongside the chunk for retrieval display but is
   NOT included in the embedding input by default (FR-702). Only the chunk text plus boundary
   context from adjacent sections is embedded. A configuration flag `embed_context_header`
   (default: `false`) can override this behavior.
3. **Context header assembly:** Store `context_header` separately in metadata for retrieval
   display (FR-704).
4. **Section path breadcrumb:** Include the full heading path (e.g., `# Title > ## Section >
   ### Subsection`) in the context header for hierarchical context (FR-701).
5. **Cross-chunk overlap:** Add boundary overlap: include the last N tokens from the previous
   chunk and first N tokens from the next chunk as optional context (FR-705).

**Testing Strategy:** Unit tests verifying `enriched_content` contains chunk text plus boundary
context but not context header by default; integration test verifying context header is stored
in metadata payload.

---

### Task 2.2b — Node 8: Metadata Generation (FR-801–FR-806)

**Description:** Implement Node 8 (`src/ingest/nodes/metadata_generation.py`) for LLM-based
keyword and entity extraction, domain vocabulary validation, and document-level summary
aggregation. This stage runs after chunk enrichment and adds structured metadata to each chunk.

**Requirements Covered:** FR-801, FR-802, FR-803, FR-804, FR-805, FR-806

**Dependencies:** Task 2.2a

**Complexity:** M

**Subtasks:**
1. **LLM keyword extraction:** Use an LLM to extract structured metadata per chunk:
   title, summary, keywords, topic tags (FR-801).
2. **TF-IDF fallback (FR-805):** When the LLM fails or times out, fall back to TF-IDF-based
   keyword extraction to ensure every chunk has keywords.
3. **BM25 keyword validation (FR-803):** Validate extracted keywords against the domain
   vocabulary; retain only vocabulary-validated keywords for the BM25 index field
   (FR-802, FR-803, FR-804).
4. **Domain vocabulary injection (FR-806):** Inject domain vocabulary terms that appear in the
   chunk text but were not extracted by the LLM, ensuring domain coverage.
5. **Document-level summary aggregation:** Generate a document-level summary by aggregating
   chunk summaries (FR-805, FR-806).

**Testing Strategy:** Unit tests with mocked LLM verifying JSON schema compliance; integration
test verifying keywords appear in the Weaviate payload; test TF-IDF fallback activates on LLM
failure.

---

### Task 2.4 — Domain Vocabulary System

**Description:** Implement the domain vocabulary loader and management utilities. The vocabulary
is a curated list of domain-specific terms used for keyword validation (Task 2.2b) and query
expansion in retrieval. Stored as a versioned YAML file (`domain_vocabulary.yaml`).

**Requirements Covered:** FR-803, FR-804

**Dependencies:** None

**Complexity:** S

**Subtasks:**
1. Define vocabulary schema: term, synonyms, category, weight.
2. Implement vocabulary loader with hot-reload on file change.
3. Add CLI subcommand for vocabulary management: `add`, `remove`, `list`, `validate`.
4. Seed initial vocabulary from existing document corpus via frequency analysis.

**Testing Strategy:** Unit tests for loading, validation, and lookup; test hot-reload triggers
correctly on file modification.

---

## Phase 3 — Extended Features

Phase 3 adds cross-document relationship detection, knowledge graph construction, and the review
tier system — enabling relationship-aware retrieval and trust-filtered search results.

---

### Task 3.2 — Node 9: Cross-Reference Extraction

**Description:** Implement Node 9 in `src/ingest/nodes/cross_reference_extraction.py`. Detects
explicit references between documents (citations, hyperlinks, "see also" patterns) and stores
them as edge metadata in chunk records. Enables retrieval-time expansion across related
documents.

**Requirements Covered:** FR-901, FR-902, FR-903, FR-904, FR-905

**Dependencies:** Task 2.2b

**Complexity:** M

**Subtasks:**
1. Implement reference pattern detection using a regex + LLM hybrid approach (FR-901).
2. Resolve detected references to existing `source_key` values in the vector store (FR-902).
3. Store cross-reference edges in chunk metadata payload as a list of `{target_source_key,
   reference_type}` objects (FR-903).
4. Handle dangling references gracefully: log a warning and store the unresolved reference
   text, but do not fail (FR-904, FR-905).

**Testing Strategy:** Unit tests with synthetic cross-referencing documents; verify edge
creation in Weaviate payload.

---

### Task 3.3a — Node 10: Triple Extraction (FR-1001–FR-1009)

**Description:** Implement Node 10 (`src/ingest/nodes/knowledge_graph_extraction.py`) for
LLM-based entity and relation triple extraction. Extracts structured (subject, predicate,
object) triples from enriched chunks with provenance tracking and structural fallback.

**Requirements Covered:** FR-1001, FR-1002, FR-1003, FR-1004, FR-1005, FR-1006, FR-1007, FR-1008, FR-1009

**Dependencies:** Task 2.2a

**Complexity:** L

**Subtasks:**
1. **LLM-based triple extraction:** Design the entity/relation extraction prompt: output
   structured JSON triples with subject, predicate, object, and provenance chunk ID (FR-1001,
   FR-1002).
2. **Entity normalization:** Normalize entity surface forms to canonical representations
   (e.g., casing, abbreviation expansion) (FR-1003, FR-1004).
3. **Relation typing:** Classify extracted relations into a controlled vocabulary of relation
   types (FR-1005, FR-1006).
4. **Provenance tracking:** Each triple includes the chunk ID from which it was extracted
   (FR-1008).
5. **Structural triple fallback (FR-1007):** When the LLM fails or times out, extract triples
   from structural cues (e.g., Markdown headings as entities, list items as relations) to
   ensure baseline coverage.
6. **Conditional activation:** Wire Node 10 into the graph with conditional activation via
   feature flag (FR-1009).

**Testing Strategy:** Unit tests with mocked LLM verifying triple JSON schema; evaluate
extraction precision on annotated test set.

**Risks:** Entity deduplication is inherently noisy; plan for iterative prompt refinement.

---

### Task 3.3b — Entity Consolidation

**Description:** Implement entity consolidation as a support module used by both triple
extraction and graph storage. Handles entity deduplication, alias resolution, and confidence
scoring for entity merges across chunks and documents.

**Requirements Covered:** FR-1003, FR-1004, FR-1005

**Dependencies:** Task 3.3a

**Complexity:** M

**Subtasks:**
1. **Entity deduplication:** Detect and merge duplicate entities across chunks using
   string similarity and embedding-based matching.
2. **Alias resolution:** Maintain an alias table mapping variant surface forms to canonical
   entity identifiers (e.g., "ML" -> "Machine Learning").
3. **Confidence scoring for entity merges:** Assign confidence scores to proposed entity merges
   based on string similarity, co-occurrence frequency, and context overlap. Only merge above
   a configurable confidence threshold.

**Testing Strategy:** Unit tests with known duplicate entity sets; verify merge decisions and
confidence scores on synthetic entity pairs.

---

### Task 3.3c — Node 13: Graph Store Writer (FR-1301–FR-1304)

**Description:** Implement Node 13 (`src/ingest/nodes/knowledge_graph_storage.py`) for writing
consolidated triples to the graph store. Supports Weaviate cross-references as the primary
backend with an optional Neo4j backend, and handles re-ingestion cleanup.

**Requirements Covered:** FR-1301, FR-1302, FR-1303, FR-1304

**Dependencies:** Task 3.3a, Task 3.3b

**Complexity:** M

**Subtasks:**
1. **Weaviate cross-reference writing:** Implement the graph store writer using Weaviate
   cross-references as v1 backend (FR-1301).
2. **Optional Neo4j backend:** Implement Neo4j as a planned v2 upgrade path for richer graph
   query capabilities (FR-1302).
3. **Backend swapping via config (FR-1303):** Support switching between Weaviate and Neo4j
   backends via `graph_store.backend` configuration key without code changes.
4. **Re-ingestion cleanup:** On re-embedding, delete all existing triples for the document
   before inserting fresh ones to prevent stale graph data (FR-1304).

**Testing Strategy:** Integration tests verifying triples in graph store; verify re-ingestion
deletes old triples before inserting new ones; test backend swapping via config.

**Risks:** Graph store migration (Weaviate -> Neo4j v2) must be treated as a schema migration
event.

---

### Task 3.4 — Review Tier System

**Description:** Implement a configurable review tier system that gates documents for human
review before they become fully searchable. Tiers (`Fully Reviewed`, `Partially Reviewed`,
`Self Reviewed`) are read from the `review_tier` field in the Clean Document Store metadata
envelope and propagated to every chunk from that document.

**Requirements Covered:** FR-594, FR-803

**Dependencies:** Task S.2, Task 2.2b

**Complexity:** M

**Subtasks:**
1. Read `review_tier` from `CleanDocumentMetadata` and attach to every chunk via
   `propagate_metadata_to_chunk` (FR-594).
2. Ensure `review_tier` is stored as a Weaviate filterable field on every chunk record (FR-803).
3. Implement review queue: a database-backed list of documents at `Self Reviewed` tier pending
   promotion.
4. Add CLI subcommand for review management: `approve`, `reject`, `list-pending`.

**Testing Strategy:** Unit tests for tier propagation; integration test for the full review
lifecycle (ingest → self-reviewed → approve → fully-reviewed visible in search).

---

## Phase 4 — Quality and Operations

Phase 4 hardens the pipeline for production: quality validation, evaluation, observability,
batch processing at scale, and schema evolution.

---

### Task 4.0 — Node 11: Quality Validation

**Description:** Implement Node 11 in `src/ingest/nodes/quality_validation.py`. Filters
low-quality chunks (below a configurable quality score threshold), deduplicates near-identical
chunks, and assigns quality scores to all surviving chunks.

**Requirements Covered:** FR-1101, FR-1102, FR-1103, FR-1104, FR-1105

**Dependencies:** Task 2.2b

**Complexity:** S

**Subtasks:**
1. Implement quality scoring: combine chunk length, keyword density, and structural
   completeness into a [0.0–1.0] quality score.
2. Filter chunks below `config.min_quality_score` — rejected chunks are logged but not
   embedded.
3. Implement near-duplicate detection: hash-based deduplication for exact duplicates; optional
   cosine similarity deduplication for near-duplicates.
4. Attach `quality_score` field to all surviving chunk records for downstream filtering.

**Testing Strategy:** Unit tests with known-quality fixture chunks; assert filter thresholds
behave correctly at boundary values.

---

### Task 4.1 — Evaluation Framework and Dataset

**Description:** Build an evaluation framework that measures embedding pipeline quality across
dimensions: chunking coherence, metadata accuracy, embedding fidelity, and end-to-end retrieval
relevance. Includes a curated evaluation dataset with ground-truth annotations.

**Requirements Covered:** (cross-cutting — no dedicated FR in this spec)

**Dependencies:** Phase 1 complete

**Complexity:** L

**Subtasks:**
1. Define evaluation metrics: chunk coherence score, metadata precision/recall, retrieval MRR.
2. Curate an evaluation dataset (minimum 50 documents with annotations and expected retrieval
   results).
3. Implement automated evaluation harness runnable via CLI.
4. Add regression detection: alert if metrics drop below configured thresholds.
5. Integrate evaluation into CI pipeline.

**Testing Strategy:** The evaluation framework is itself the testing strategy for the pipeline.

---

### Task 4.2 — Langfuse Observability Integration

**Description:** Integrate Langfuse for end-to-end pipeline observability. Each pipeline run
creates a trace; each node creates a span. LLM calls are captured with token counts, latencies,
and costs. Errors are tagged and searchable.

**Requirements Covered:** (cross-cutting — no dedicated FR in this spec)

**Dependencies:** Task 1.2

**Complexity:** M

**Subtasks:**
1. Add Langfuse SDK dependency and configuration.
2. Instrument the pipeline runtime (`pipeline_impl.py`) with trace creation per document.
3. Instrument each node with span creation and metadata tagging (node name, input size, output
   size).
4. Capture LLM calls via the shared LLM helper (`pipeline_llm.py`): token counts, model,
   latency, cost.
5. Add error tagging and alerting rules for failed node executions.

**Testing Strategy:** Integration test verifying traces appear in Langfuse; unit tests with
mocked Langfuse client.

---

### Task 4.3 — Batch Processing Hardening

**Description:** Harden the pipeline for large batch runs (1000+ documents). Add concurrency
controls, progress checkpointing, partial failure recovery, and memory management for large
documents.

**Requirements Covered:** (cross-cutting — no dedicated FR in this spec)

**Dependencies:** Task 1.10

**Complexity:** L

**Subtasks:**
1. Implement configurable concurrency: async semaphore for parallel document processing.
2. Add progress checkpointing: persist completed `source_key` values so a crashed batch can
   resume without re-processing completed documents.
3. Implement partial failure isolation: a single document failure does not abort the batch;
   log the failure and continue.
4. Add per-document memory limits for large files; implement streaming chunking to avoid
   loading the full document into memory.
5. Add batch-level reporting: aggregate statistics across all documents in a run.

**Testing Strategy:** Load test with 500+ synthetic documents; verify checkpoint recovery after
a simulated crash at the midpoint.

**Risks:** Memory pressure from large documents; mitigate with streaming chunk-at-a-time
processing rather than whole-document state.

---

### Task 4.4 — Schema Migration

**Description:** Implement schema migration tooling for the vector store and chunk metadata
payloads. As the pipeline evolves, chunk metadata schemas change; this task ensures existing
data can be migrated forward without full re-ingestion.

**Requirements Covered:** (cross-cutting — no dedicated FR in this spec)

**Dependencies:** Task 1.8

**Complexity:** M

**Subtasks:**
1. Define a `metadata_schema_version` field in all chunk payloads.
2. Implement migration registry: `{version → migration_function}`.
3. Implement `ingest.py migrate` CLI subcommand.
4. Add dry-run mode for migrations.
5. Add rollback support for failed migrations.

**Testing Strategy:** Unit tests for each migration function; integration test verifying
migration on a populated Weaviate test collection.

---

## Task Dependency Graph

```
Part A0 (Clean Document Store — Boundary)
└── Task S.2: Clean Store Reader ────────────────────────────────────┐

Phase 1 (Core Embedding — MVP)                                       │
├── Task 1.2: Embedding Pipeline DAG Skeleton ◄─── Task S.2 ────────┤ [CRITICAL]
├── Task 1.6: Node 6 Chunking ◄─── Task S.2, Task 1.2              │ [CRITICAL]
├── Task 1.7: Node 12 Embedding Generation ◄─── Task 1.6           │ [CRITICAL]
├── Task 1.8: Vector Store Upsert ◄─── Task 1.7                    │ [CRITICAL]
├── Task 1.9: Result Reporting ◄─── Task 1.8                        │
└── Task 1.10: Re-Ingestion Flow ◄─── Task S.2, Task 1.8            │

Phase 2 (LLM Enhancement)                                            │
├── Task 2.1: LLM-Assisted Chunking ◄─── Task 1.6 ─────────────────┤
├── Task 2.2a: Chunk Enrichment ◄─── Task 1.6                      │ [CRITICAL if LLM enabled]
├── Task 2.2b: Metadata Generation ◄─── Task 2.2a                  │ [CRITICAL if LLM enabled]
└── Task 2.4: Domain Vocabulary ◄─── None (parallel with Phase 1)   │

Phase 3 (Extended Features)                                          │
├── Task 3.2: Node 9 Cross-Reference Extraction ◄─── Task 2.2b     │
├── Task 3.3a: Node 10 Triple Extraction ◄─── Task 2.2a            │
├── Task 3.3b: Entity Consolidation ◄─── Task 3.3a                 │
├── Task 3.3c: Node 13 Graph Store Writer ◄─── Task 3.3a, 3.3b     │
└── Task 3.4: Review Tier System ◄─── Task S.2, Task 2.2b          │

Phase 4 (Quality & Operations)                                       │
├── Task 4.0: Node 11 Quality Validation ◄─── Task 2.2b            │ [CRITICAL]
├── Task 4.1: Evaluation Framework ◄─── Phase 1 complete            │
├── Task 4.2: Langfuse Observability ◄─── Task 1.2                  │
├── Task 4.3: Batch Processing Hardening ◄─── Task 1.10             │
└── Task 4.4: Schema Migration ◄─── Task 1.8                        │

Critical path (MVP): S.2 → 1.2 → 1.6 → 1.7 → 1.8
Critical path (full): + 2.2a → 2.2b → 4.0 → (embedding of enriched content)
```

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|------|---------------------|
| S.2 Clean Document Store Reader | FR-591, FR-592, FR-593, FR-594, FR-595 |
| 1.2 Embedding Pipeline DAG Skeleton | FR-591, FR-901, FR-1001, FR-1301 |
| 1.6 Node 6: Chunking (Rule-Based) | FR-601, FR-602, FR-603, FR-604, FR-605, FR-606 |
| 1.7 Node 12: Embedding Generation | FR-1201, FR-1202, FR-1203, FR-1204 |
| 1.8 Vector Store Upsert | FR-1205, FR-1206, FR-1207, FR-1208, FR-1209 |
| 1.9 Result Reporting | FR-1201 |
| 1.10 Re-Ingestion Flow | FR-593, FR-1205, FR-1208 |
| 2.1 LLM-Assisted Chunking | FR-606, FR-607, FR-608, FR-609, FR-610, FR-611 |
| 2.2a Node 7: Chunk Enrichment | FR-701, FR-702, FR-703, FR-704, FR-705 |
| 2.2b Node 8: Metadata Generation | FR-801, FR-802, FR-803, FR-804, FR-805, FR-806 |
| 2.4 Domain Vocabulary System | FR-803, FR-804 |
| 3.2 Node 9: Cross-Reference Extraction | FR-901, FR-902, FR-903, FR-904, FR-905 |
| 3.3a Node 10: Triple Extraction | FR-1001, FR-1002, FR-1003, FR-1004, FR-1005, FR-1006, FR-1007, FR-1008, FR-1009 |
| 3.3b Entity Consolidation | FR-1003, FR-1004, FR-1005 |
| 3.3c Node 13: Graph Store Writer | FR-1301, FR-1302, FR-1303, FR-1304 |
| 3.4 Review Tier System | FR-594, FR-803 |
| 4.0 Node 11: Quality Validation | FR-1101, FR-1102, FR-1103, FR-1104, FR-1105 |
| 4.1 Evaluation Framework | — (cross-cutting) |
| 4.2 Langfuse Observability | — (cross-cutting) |
| 4.3 Batch Processing Hardening | — (cross-cutting) |
| 4.4 Schema Migration | — (cross-cutting) |

<!-- VERIFY: All FR-591–FR-1304 requirements from EMBEDDING_PIPELINE_SPEC.md appear above. -->

---

# Part B: Code Appendix

The following snippets illustrate the key design patterns used in the Embedding Pipeline. They
are representative, not exhaustive — consult the source code for the full implementation.

For node base pattern and deterministic ID generation utilities, see
`DOCUMENT_PROCESSING_IMPLEMENTATION.md` Part B (B.2 and B.3) — these are shared across both
pipelines.

---

## B.1 — Embedding Pipeline DAG (LangGraph StateGraph)

Constructs the 8-stage Embedding Pipeline graph with three conditional routing points:
cross-reference extraction (optional), KG extraction (optional), and KG storage (conditional
on KG extraction having run). Supports Tasks 1.2, 3.2, 3.3, and 4.0.

**Tasks:** Task 1.2, Task 3.2, Task 3.3a, Task 3.3c, Task 4.0
**Requirements:** FR-901, FR-1001, FR-1301

```python
# src/ingest/pipeline_workflow.py  (Embedding Pipeline section)

from langgraph.graph import StateGraph, END
from src.ingest.pipeline_types import EmbeddingPipelineState, PipelineConfig
from src.ingest.nodes.chunking import chunking_node
from src.ingest.nodes.chunk_enrichment import chunk_enrichment_node
from src.ingest.nodes.metadata_generation import metadata_generation_node
from src.ingest.nodes.cross_reference_extraction import cross_reference_extraction_node
from src.ingest.nodes.knowledge_graph_extraction import knowledge_graph_extraction_node
from src.ingest.nodes.quality_validation import quality_validation_node
from src.ingest.nodes.embedding_storage import embedding_storage_node
from src.ingest.nodes.knowledge_graph_storage import knowledge_graph_storage_node


def _route_after_metadata(state: EmbeddingPipelineState) -> str:
    """Route to cross-reference extraction if enabled (FR-901)."""
    if state["config"].enable_cross_references:
        return "cross_reference_extraction"
    return "knowledge_graph_extraction" if state["config"].enable_knowledge_graph else "quality_validation"


def _route_after_crossref(state: EmbeddingPipelineState) -> str:
    """Route to KG extraction if enabled (FR-1001)."""
    if state["config"].enable_knowledge_graph:
        return "knowledge_graph_extraction"
    return "quality_validation"


def _route_after_storage(state: EmbeddingPipelineState) -> str:
    """Write KG triples only if KG extraction produced triples (FR-1301)."""
    if state.get("kg_triples") and state["config"].enable_knowledge_graph:
        return "knowledge_graph_storage"
    return END


def build_embedding_pipeline_graph(config: PipelineConfig) -> StateGraph:
    """Construct the 8-node Embedding Pipeline DAG.

    Flow:
        chunking → chunk_enrichment → metadata_generation
            → [cross_reference_extraction]  (conditional: enabled in config)
            → [knowledge_graph_extraction]  (conditional: enabled in config)
            → quality_validation
            → embedding_storage
            → [knowledge_graph_storage]     (conditional: KG triples produced)
    """
    graph = StateGraph(EmbeddingPipelineState)

    graph.add_node("chunking", chunking_node)
    graph.add_node("chunk_enrichment", chunk_enrichment_node)
    graph.add_node("metadata_generation", metadata_generation_node)
    graph.add_node("cross_reference_extraction", cross_reference_extraction_node)
    graph.add_node("knowledge_graph_extraction", knowledge_graph_extraction_node)
    graph.add_node("quality_validation", quality_validation_node)
    graph.add_node("embedding_storage", embedding_storage_node)
    graph.add_node("knowledge_graph_storage", knowledge_graph_storage_node)

    graph.set_entry_point("chunking")
    graph.add_edge("chunking", "chunk_enrichment")
    graph.add_edge("chunk_enrichment", "metadata_generation")
    graph.add_conditional_edges(
        "metadata_generation",
        _route_after_metadata,
        {
            "cross_reference_extraction": "cross_reference_extraction",
            "knowledge_graph_extraction": "knowledge_graph_extraction",
            "quality_validation": "quality_validation",
        },
    )
    graph.add_conditional_edges(
        "cross_reference_extraction",
        _route_after_crossref,
        {
            "knowledge_graph_extraction": "knowledge_graph_extraction",
            "quality_validation": "quality_validation",
        },
    )
    graph.add_edge("knowledge_graph_extraction", "quality_validation")
    graph.add_edge("quality_validation", "embedding_storage")
    graph.add_conditional_edges(
        "embedding_storage",
        _route_after_storage,
        {"knowledge_graph_storage": "knowledge_graph_storage", END: END},
    )
    graph.add_edge("knowledge_graph_storage", END)

    return graph
```

**Key design decisions:**

- **Three independent conditional branches** (cross-reference, KG extraction, KG storage) are
  all driven by config flags, not by removing nodes. The topology is always the same; disabled
  stages are simply never reached.
- **KG storage is guarded by both a config flag AND the presence of triples** — if KG
  extraction was disabled or produced nothing, the KG storage step is skipped without error.
- **Quality validation always runs** — it is not optional. Every chunk that reaches embedding
  must pass the quality gate.

---

## B.2 — Re-Ingestion Flow (Delete-and-Reinsert)

Implements the pipeline runtime's change-detection and re-ingestion logic. Reads `clean_hash`
from the Clean Document Store metadata envelope and compares it against the stored embedding
run manifest to decide whether to re-embed. Supports Tasks S.2, 1.10.

**Tasks:** Task S.2, Task 1.10
**Requirements:** FR-593, FR-1205, FR-1208

```python
# src/ingest/pipeline_impl.py  (excerpt)

import logging
from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from src.ingest.clean_store import CleanDocumentStore
from src.ingest.pipeline_types import PipelineConfig, EmbeddingPipelineState
from src.ingest.pipeline_workflow import build_embedding_pipeline_graph

logger = logging.getLogger(__name__)


class EmbeddingPipelineRuntime:
    """Orchestrates Embedding Pipeline execution with re-ingestion support."""

    def __init__(self, config: PipelineConfig, weaviate: WeaviateClient):
        self._config = config
        self._weaviate = weaviate
        self._store = CleanDocumentStore(config.clean_docs_dir)
        self._graph = build_embedding_pipeline_graph(config).compile()

    def _delete_existing_chunks(
        self, source_key: str, *, dry_run: bool = False
    ) -> int:
        """Delete all chunks for a source_key. Returns count deleted."""
        collection = self._weaviate.collections.get(self._config.weaviate_collection)
        doc_filter = Filter.by_property("source_key").equal(source_key)
        count = collection.aggregate.over_all(filters=doc_filter).total_count

        if count == 0:
            return 0

        if dry_run:
            logger.info("Dry-run: would delete %d chunks for %s", count, source_key)
            return count

        collection.data.delete_many(where=doc_filter)
        logger.info("Deleted %d existing chunks for %s", count, source_key)
        return count

    def embed(
        self,
        source_key: str,
        *,
        force: bool = False,
        dry_run: bool = False,
    ) -> EmbeddingPipelineState:
        """Run the Embedding Pipeline for a single clean document.

        If clean_hash is unchanged since the last embedding run, the pipeline
        skips entirely. The ``force`` flag bypasses the hash comparison.
        """
        md_content, metadata = self._store.read(source_key)

        if not force:
            stored_hash = self._load_manifest_hash(source_key)
            if stored_hash == metadata.clean_hash:
                logger.info(
                    "Document %s unchanged (clean_hash match), skipping. "
                    "Use --force to re-embed.",
                    source_key,
                )
                return {"skipped": True, "source_key": source_key}

        # Delete existing chunks before re-embedding (FR-1208)
        self._delete_existing_chunks(source_key, dry_run=dry_run)

        if dry_run:
            logger.info("Dry-run: would embed %s", source_key)
            return {"dry_run": True, "source_key": source_key}

        initial_state: EmbeddingPipelineState = {
            "config": self._config,
            "source_key": source_key,
            "md_content": md_content,
            "metadata": metadata,
        }
        result = self._graph.invoke(initial_state)
        self._save_manifest_hash(source_key, metadata.clean_hash)
        return result

    def _load_manifest_hash(self, source_key: str) -> str | None:
        """Load the previously stored clean_hash for this source_key."""
        # Implementation: read from a JSON manifest file keyed by source_key
        ...

    def _save_manifest_hash(self, source_key: str, clean_hash: str) -> None:
        """Persist the clean_hash after a successful embedding run."""
        ...
```

**Key design decisions:**

- **`clean_hash` as the re-embedding signal** — the Embedding Pipeline is independent of the
  source file. It only cares whether the clean Markdown has changed. This means Document
  Processing can run more frequently (e.g., for config changes) without triggering unnecessary
  re-embedding.
- **Delete-before-insert, not update-in-place** — chunk count and boundaries can change when
  a document changes. Deleting all old chunks and inserting fresh ones is simpler and more
  correct than per-chunk diffing.
- **Force flag** — overrides the hash comparison when the pipeline code has changed (e.g., new
  chunking strategy) and all documents need re-processing regardless of content changes.
