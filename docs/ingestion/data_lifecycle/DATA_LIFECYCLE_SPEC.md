> **Document type:** Authoritative requirements specification (Layer 3)
> **Downstream:** DATA_LIFECYCLE_SPEC_SUMMARY.md, DATA_LIFECYCLE_DESIGN.md
> **Last updated:** 2026-04-15

# Data Lifecycle — Specification (v1.0.0)

## Document Information

> **Document intent:** This is a formal specification for the **Data Lifecycle** subsystem of the AION RAG Document Embedding Pipeline. It defines requirements for document garbage collection and sync, durable state boundary (eliminating the local CleanDocumentStore), per-document trace ID with end-to-end validation, and schema versioning with incremental migration. These capabilities are cross-cutting: they affect both the Document Processing Pipeline and the Embedding Pipeline, and they govern how data flows, persists, ages, and evolves across all four storage backends (Weaviate, MinIO, Neo4j, and the ingestion manifest).
> For Document Processing Pipeline functional requirements (FR-100 through FR-589), see `DOCUMENT_PROCESSING_SPEC.md`.
> For Embedding Pipeline functional requirements (FR-591 through FR-1399), see `EMBEDDING_PIPELINE_SPEC.md`.
> For cross-cutting platform requirements (re-ingestion, config, error handling, data model, NFR), see `INGESTION_PLATFORM_SPEC.md`.

| Field | Value |
|-------|-------|
| System | AION RAG Document Embedding Pipeline |
| Document Type | Subsystem Specification — Data Lifecycle |
| Companion Documents | INGESTION_PLATFORM_SPEC.md (Platform/Cross-Cutting Requirements), DOCUMENT_PROCESSING_SPEC.md (Document Processing Phase), EMBEDDING_PIPELINE_SPEC.md (Embedding Phase), DOCUMENT_PROCESSING_SPEC_SUMMARY.md (Phase 1 Summary), EMBEDDING_PIPELINE_SPEC_SUMMARY.md (Phase 2 Summary) |
| FR Range | FR-3000 through FR-3199 |
| Version | 1.0.0 |
| Status | Draft |

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-04-15 | AI Assistant | Initial specification. Covers four gaps identified during ingestion hardening review: Document GC/Sync (Gap 2), Durable State Boundary (Gap 4), Per-Document Trace ID (Gap 7), Schema Versioning (Gap 11). |

---

## 1. Purpose and Scope

### 1.1 Problem Statement

The AION RAG Document Embedding Pipeline ingests documents through a two-phase pipeline (Document Processing followed by Embedding) and persists results across four storage backends: Weaviate (vector chunks), MinIO (clean markdown blobs and page images), Neo4j (knowledge graph triples), and a JSON ingestion manifest (idempotency ledger). This distributed storage model creates four classes of lifecycle problem that the current implementation does not address:

1. **Orphaned data across stores.** When a source document is deleted from the source directory, the current pipeline removes its Weaviate chunks and manifest entry during incremental update runs, but leaves orphaned blobs in MinIO and triples in Neo4j. Over time, these orphans accumulate storage cost, pollute knowledge graph traversals, and produce phantom retrieval results.

2. **Local filesystem as inter-phase boundary.** The current `CleanDocumentStore` writes `.md`, `.meta.json`, and `.docling.json` files to a local filesystem directory as the handoff between Phase 1 (Document Processing) and Phase 2 (Embedding). This design couples the pipeline to a single node. When the pipeline is orchestrated by Temporal across multiple worker nodes, local filesystem state is not shared, breaking the two-phase handoff and preventing horizontal scaling.

3. **No per-document trace identity.** Documents flow through the pipeline without a unique trace identifier. When a document fails partway through, or when end-to-end validation is needed (did all stores receive this document's data?), there is no correlation key to query across Weaviate, MinIO, Neo4j, and the manifest. Debugging requires manual cross-referencing of logs, timestamps, and source keys.

4. **No schema version tracking.** Pipeline upgrades change metadata schemas (new Weaviate properties, new manifest fields, new KG relationship types). The current system has no mechanism to identify which documents were processed under which schema version, and no way to selectively re-process only the documents that need migration. The only option is a full re-ingestion — expensive and unnecessary when only metadata changed.

### 1.2 Scope

This specification defines the data lifecycle requirements that govern how ingested data is created, tracked, aged, garbage-collected, and migrated across all storage backends.

**In scope:**

- Document garbage collection: detecting orphaned data and reconciling stores against the source of truth
- Sync trigger modes: manual, scheduled, and on-ingest diff
- Soft delete with configurable retention period
- Durable state boundary: replacing the local `CleanDocumentStore` with in-memory state flow and MinIO as the single durable store
- Per-document trace ID: unique identifier assigned at workflow start and carried through both pipeline phases
- End-to-end validation: verifying all stores received data for a given trace ID
- Schema versioning: storing schema version on manifest entries and Weaviate chunk metadata
- Incremental migration: selective re-processing of documents with stale schema versions
- Migration classification: metadata-only updates vs. full re-embedding vs. KG re-extraction

**Out of scope:**

- Document Processing Pipeline stage logic (see `DOCUMENT_PROCESSING_SPEC.md`)
- Embedding Pipeline stage logic (see `EMBEDDING_PIPELINE_SPEC.md`)
- Pluggable parser interface and parser-internal chunking (see planned Parser Abstraction Spec)
- Cross-document deduplication (Gap 12 — separate spec)
- Priority queue mechanics (Gap 13 — separate spec)
- LangGraph intra-phase checkpointing (Gap 1 — deferred)
- Incremental re-embedding at the chunk level (Gap 5 — deferred)
- Progress reporting UI/API (Gap 6 — deferred)
- Query processing, reranking, and answer generation (downstream retrieval layer)
- User authentication and access control
- Real-time push-based document change detection

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| Garbage Collection (GC) | The process of identifying and removing data in downstream stores that no longer corresponds to an active source document |
| Sync | A reconciliation operation that diffs the current source file inventory against the manifest and identifies additions, modifications, and deletions |
| Soft Delete | Marking a document's data as deleted without immediately purging it from storage; data is hidden from retrieval and purged after a configurable retention period |
| Hard Delete | Immediate, irrevocable removal of a document's data from all stores |
| Retention Period | The configurable duration (in days) that soft-deleted data is preserved before hard deletion |
| Manifest | The JSON-persisted ingestion ledger that tracks which source documents have been processed, their content hashes, and metadata; used for idempotency and incremental updates |
| Durable State Boundary | The architectural boundary between pipeline phases where state is persisted to a durable store (MinIO) rather than local filesystem |
| Trace ID | A unique identifier (UUID v4) assigned to each `IngestDocumentWorkflow` execution, carried through all pipeline phases and stored in all output artifacts |
| Batch ID | An optional grouping identifier that correlates multiple document ingestions submitted together; used for reporting only, not correctness |
| Schema Version | A version identifier stored on each document's manifest entry and Weaviate chunk metadata, indicating which pipeline schema produced the data |
| Migration Job | A targeted re-processing run that selects only documents with schema versions older than the current version |
| source_key | Stable deterministic identifier derived from the source file path; used as the primary key for manifest entries and cross-store correlation |
| Clean Markdown | The processed Markdown output of Phase 1 (Document Processing), after parsing, cleaning, and optional VLM enrichment |
| Four Stores | Collective term for the four storage backends: Weaviate (chunks), MinIO (blobs/page images), Neo4j (KG triples), and the ingestion manifest |

### 1.4 Requirement Priority Levels

This specification uses the key words defined in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) to indicate requirement levels:

- **MUST / SHALL**: Absolute requirement.
- **MUST NOT / SHALL NOT**: Absolute prohibition.
- **SHOULD**: Recommended; deviations require documented justification.
- **MAY**: Optional; included for completeness.

---

## 2. Architecture Overview

### 2.1 Storage Topology

The ingestion pipeline writes to four distinct storage backends. Data lifecycle operations MUST address all four to prevent orphaned data:

```
                    ┌─────────────────────────────────────────────────┐
                    │              Source Directory                    │
                    │  (ground truth: what files exist NOW)           │
                    └────────────────────┬────────────────────────────┘
                                         │
                                    source scan
                                         │
                    ┌────────────────────▼────────────────────────────┐
                    │          Ingestion Manifest (JSON)               │
                    │  source_key → hash, schema_version, trace_id,   │
                    │               chunk_count, deleted_at, ...       │
                    │  (idempotency ledger + GC reference)             │
                    └────────────────────┬────────────────────────────┘
                                         │
                      ┌──────────────────┼──────────────────┐
                      │                  │                  │
                      ▼                  ▼                  ▼
              ┌───────────────┐  ┌──────────────┐  ┌──────────────┐
              │   Weaviate    │  │    MinIO      │  │   Neo4j      │
              │  (chunks +    │  │  (clean MD +  │  │  (KG triples │
              │   embeddings) │  │   page imgs)  │  │   + entities)│
              └───────────────┘  └──────────────┘  └──────────────┘
```

### 2.2 Data Flow with Trace ID

Each document ingestion receives a trace ID at workflow start. The trace ID flows through both phases and is persisted in every store:

```
  IngestDocumentWorkflow(source_path)
           │
           ├── trace_id = uuid4()
           ├── batch_id = <optional, from caller>
           │
           ▼
  ┌─────────────────────────────────┐
  │  Phase 1: Document Processing   │
  │  LangGraph state includes:      │
  │    trace_id, source_key         │
  │                                 │
  │  Output: clean_text (in-memory) │
  │          + metadata             │
  └──────────────┬──────────────────┘
                 │
                 │  in-memory handoff (no local FS)
                 │  durable write → MinIO
                 │
  ┌──────────────▼──────────────────┐
  │  Phase 2: Embedding Pipeline    │
  │  LangGraph state includes:      │
  │    trace_id, source_key         │
  │                                 │
  │  Writes to:                     │
  │    Weaviate  (trace_id in meta) │
  │    Neo4j     (trace_id on node) │
  │    Manifest  (trace_id field)   │
  └──────────────┬──────────────────┘
                 │
                 ▼
  ┌─────────────────────────────────┐
  │  E2E Validation                 │
  │  Query all 4 stores by trace_id │
  │  Verify consistency             │
  └─────────────────────────────────┘
```

### 2.3 Durable State Boundary (Current vs. Target)

```
  CURRENT (local filesystem boundary):

  Phase 1 ──write──▶ CleanDocumentStore (local FS)
                        ├── {source_key}.md
                        ├── {source_key}.meta.json
                        └── {source_key}.docling.json    ← ELIMINATED
                                    │
  Phase 2 ◀──read───────────────────┘

  TARGET (in-memory + MinIO):

  Phase 1 ──return──▶ in-memory state (clean_text, metadata)
                        │
                        ├── durable write ──▶ MinIO (clean MD + metadata)
                        │
  Phase 2 ◀─────────────┘  (receives clean_text in-memory, NOT from disk)
```

### 2.4 Schema Migration Classification

```
  ┌──────────────────────────────────────────────────────────────┐
  │              Schema Change Classification                     │
  ├──────────────────────┬───────────────────────────────────────┤
  │  Change Type         │  Migration Strategy                   │
  ├──────────────────────┼───────────────────────────────────────┤
  │  New Weaviate        │  Weaviate batch metadata update       │
  │  metadata property   │  No re-embedding. Cheap.              │
  ├──────────────────────┼───────────────────────────────────────┤
  │  Embedding model     │  Full Phase 2 re-run.                 │
  │  change              │  Expensive. All chunks re-embedded.   │
  ├──────────────────────┼───────────────────────────────────────┤
  │  New KG relationship │  No re-extraction needed.             │
  │  type added          │  Existing triples remain valid.       │
  ├──────────────────────┼───────────────────────────────────────┤
  │  KG extraction logic │  Re-extract affected documents.       │
  │  changed             │  Delete old triples, run KG nodes.    │
  ├──────────────────────┼───────────────────────────────────────┤
  │  Manifest schema     │  Forward-compatible. New fields added │
  │  extended            │  with defaults. No migration needed.  │
  └──────────────────────┴───────────────────────────────────────┘
```

---

## 3. Functional Requirements

### 3.1 Document Garbage Collection and Sync (Gap 2)

#### 3.1.1 Sync Operation

> **FR-3000: Source-to-Manifest Diff**
> The system SHALL provide a sync operation that compares the current source file inventory against the ingestion manifest to identify three categories: **added** (source exists but no manifest entry), **modified** (source exists and manifest hash differs), and **deleted** (manifest entry exists but source file is absent).
> **Rationale:** The manifest is the system's record of what has been ingested. Without a diff operation, deleted source files leave orphaned data in all four stores indefinitely, consuming storage and polluting retrieval results.
> **Acceptance Criteria:**
> 1. The sync operation enumerates all source files matching configured extensions in the source directory.
> 2. The sync operation enumerates all `source_key` entries in the manifest.
> 3. For each manifest entry without a corresponding source file, the entry is classified as "deleted."
> 4. For each source file without a corresponding manifest entry, the file is classified as "added."
> 5. For each source file with a manifest entry where `content_hash` differs from the current file hash, the file is classified as "modified."
> 6. The sync operation returns a structured result containing counts and lists for all three categories.

> **FR-3001: Four-Store Reconciliation**
> When a document is classified as "deleted" by the sync operation, the system SHALL remove or mark as deleted the document's data in ALL four stores: Weaviate (all chunks with matching `source_key`), MinIO (clean markdown blob and any page image blobs with matching `source_key` prefix), Neo4j (all triples and entity nodes with matching `source_key` provenance), and the ingestion manifest (the `source_key` entry).
> **Rationale:** Partial cleanup (e.g., removing only Weaviate chunks but leaving MinIO blobs and KG triples) creates data inconsistency. The current implementation in `ingest_directory` only cleans Weaviate and the manifest, leaving MinIO and Neo4j orphaned.
> **Acceptance Criteria:**
> 1. Weaviate: all objects where `source_key` matches the deleted document are removed (or soft-deleted per FR-3010).
> 2. MinIO: all objects under the `source_key` prefix in the configured bucket are removed (or soft-deleted per FR-3010).
> 3. Neo4j: all triples where the provenance `source_key` matches the deleted document are removed (or soft-deleted per FR-3010).
> 4. Manifest: the entry is updated with deletion metadata (or removed, depending on soft/hard delete mode).
> 5. Failures in any single store cleanup SHALL be logged and SHALL NOT prevent cleanup of the remaining stores.
> 6. The reconciliation result reports per-store success/failure status.

> **FR-3002: Orphan Detection Report**
> The sync operation SHALL produce an orphan detection report listing all data found in downstream stores (Weaviate, MinIO, Neo4j) that has no corresponding manifest entry, regardless of whether the data corresponds to a known deleted source.
> **Rationale:** Data can become orphaned through partial failures, manual store manipulation, or bugs. A report-only orphan scan provides visibility without automatic deletion.
> **Acceptance Criteria:**
> 1. The report queries each store for `source_key` values not present in the manifest.
> 2. The report includes per-store counts and sample `source_key` values.
> 3. The report does not modify any data.
> 4. The report MAY be run independently of the sync operation.

#### 3.1.2 Trigger Modes

> **FR-3010: Manual GC Trigger**
> The system SHALL provide a CLI command and programmatic API endpoint to trigger garbage collection manually. The command SHALL accept parameters for delete mode (`soft` or `hard`), retention period override (days), and dry-run flag.
> **Rationale:** Operators need on-demand GC for maintenance windows, storage reclamation, and debugging.
> **Acceptance Criteria:**
> 1. A CLI command (e.g., `aion ingest gc`) triggers the sync and reconciliation operations.
> 2. The `--dry-run` flag executes the sync diff and reports what would be deleted without modifying any store.
> 3. The `--mode soft|hard` flag controls whether deletion uses soft delete (FR-3020) or immediate hard delete.
> 4. The `--retention-days N` flag overrides the configured default retention period for soft deletes.
> 5. The command returns a structured summary of actions taken or planned (dry-run).

> **FR-3011: Scheduled GC Trigger**
> The system SHALL support scheduling GC runs at configurable intervals via the Temporal scheduler or an equivalent cron-like mechanism.
> **Rationale:** Routine GC prevents unbounded orphan accumulation without operator intervention.
> **Acceptance Criteria:**
> 1. A configuration key (`gc.schedule`) accepts a cron expression or interval string.
> 2. When configured, the system automatically triggers the sync and reconciliation operations at the specified interval.
> 3. Scheduled GC runs use the configured default delete mode and retention period.
> 4. Scheduled GC results are logged and queryable via the same reporting interface as manual runs.

> **FR-3012: On-Ingest Diff Trigger**
> During incremental ingestion runs (update mode), the system SHALL perform the source-to-manifest diff (FR-3000) as part of the ingestion workflow and apply soft deletion (FR-3020) to any documents classified as "deleted."
> **Rationale:** The most natural time to detect deletions is when the pipeline is already scanning the source directory for changes. This is the current behavior in `ingest_directory` for Weaviate and manifest cleanup, but it MUST be extended to all four stores.
> **Acceptance Criteria:**
> 1. When `update=True`, the ingestion run performs the full four-store reconciliation (FR-3001) for deleted documents, not just Weaviate and manifest cleanup.
> 2. On-ingest GC uses soft delete mode by default.
> 3. On-ingest GC does not block or delay processing of added/modified documents — deletions are processed after all additions/modifications complete, or in parallel.
> 4. On-ingest GC results are included in the `IngestionRunSummary`.

#### 3.1.3 Soft Delete and Retention

> **FR-3020: Soft Delete with Retention Period**
> The default GC delete mode SHALL be soft delete. Soft-deleted documents SHALL be marked with a `deleted_at` timestamp in the manifest and hidden from retrieval, but their data SHALL be retained in all stores for a configurable retention period before hard deletion.
> **Rationale:** Soft delete provides a safety window for accidental deletions. Source files may be temporarily moved, renamed, or stored on an unmounted drive. Immediate hard delete is irreversible and risks data loss.
> **Acceptance Criteria:**
> 1. Soft-deleted manifest entries contain a `deleted_at` ISO 8601 timestamp and a `deleted` boolean flag set to `True`.
> 2. Weaviate chunks belonging to soft-deleted documents are excluded from retrieval queries via a filter condition (`deleted != true` or equivalent).
> 3. Neo4j triples belonging to soft-deleted documents are excluded from graph traversal queries.
> 4. MinIO blobs belonging to soft-deleted documents are not served to any pipeline consumer.
> 5. The default retention period is configurable via `gc.retention_days` (default: 30 days).
> 6. Soft-deleted data whose `deleted_at` timestamp is older than the retention period SHALL be hard-deleted by the next GC run.

> **FR-3021: Hard Delete Override**
> The system SHALL support a hard delete mode that immediately and irrevocably removes data from all four stores without a retention period.
> **Rationale:** Operators may need to immediately purge sensitive or erroneous data, or to reclaim storage urgently.
> **Acceptance Criteria:**
> 1. Hard delete removes Weaviate chunks, MinIO blobs, Neo4j triples, and the manifest entry in a single operation.
> 2. Hard delete is available via the `--mode hard` CLI flag and the programmatic API.
> 3. Hard delete logs the `source_key` and store-level deletion results for audit purposes.
> 4. Hard delete SHALL NOT be the default mode for any trigger.

> **FR-3022: Retention Purge**
> Each GC run (manual or scheduled) SHALL scan for soft-deleted manifest entries whose `deleted_at` timestamp exceeds the configured retention period, and SHALL hard-delete those entries and their associated data from all stores.
> **Rationale:** Soft-deleted data that has exceeded its retention window must be purged to prevent indefinite storage growth.
> **Acceptance Criteria:**
> 1. The purge operation queries the manifest for entries where `deleted == True` and `deleted_at < (now - retention_days)`.
> 2. Each qualifying entry undergoes the full four-store hard deletion (FR-3021).
> 3. The purge count is included in the GC run summary.

---

### 3.2 Durable State Boundary — MinIO Clean Store (Gap 4)

#### 3.2.1 Eliminating the Local CleanDocumentStore

> **FR-3030: In-Memory Phase 1 to Phase 2 Handoff**
> Phase 1 (Document Processing) SHALL return its output (clean markdown text and metadata) as in-memory state to the orchestrator. The orchestrator SHALL pass this state directly to Phase 2 (Embedding Pipeline) without writing to or reading from the local filesystem as an inter-phase boundary.
> **Rationale:** The current `CleanDocumentStore` writes `.md`, `.meta.json`, and `.docling.json` files to a local directory. This local filesystem dependency prevents horizontal scaling across multiple Temporal worker nodes, because Phase 2 on a different node cannot read Phase 1's local output. Clean markdown is small enough (typically < 1 MB) to carry in-memory between phases.
> **Acceptance Criteria:**
> 1. Phase 1 returns clean markdown text as a string in its output state (e.g., `clean_text` field).
> 2. Phase 1 returns metadata as a dictionary in its output state (e.g., `metadata` field).
> 3. The orchestrator passes both values directly to Phase 2 as input parameters.
> 4. No local filesystem read or write occurs between Phase 1 completion and Phase 2 start for the purpose of inter-phase data transfer.
> 5. The `CleanDocumentStore` class is removed or deprecated with a migration path.

> **FR-3031: MinIO as Durable Clean Store**
> The system SHALL persist Phase 1 output (clean markdown and source metadata) to MinIO as the single durable store for processed document text. This write serves as the durable backup and as the source of truth for GC, sync, and migration operations.
> **Rationale:** While the inter-phase handoff is in-memory (FR-3030), a durable copy is needed for recovery, re-processing, and audit. MinIO is already used for page image storage and provides the object-store semantics required for multi-node access.
> **Acceptance Criteria:**
> 1. After Phase 1 completes successfully, the clean markdown text is written to MinIO under a deterministic key derived from the `source_key` (e.g., `clean/{source_key}.md`).
> 2. Source metadata is written to MinIO as a companion object (e.g., `clean/{source_key}.meta.json`).
> 3. MinIO writes are atomic or use a write-then-rename pattern to prevent partial reads.
> 4. Phase 2 does NOT read from MinIO during normal operation — it receives data in-memory from the orchestrator.
> 5. MinIO clean store objects are queryable by `source_key` for GC, sync, and migration operations.

> **FR-3032: DoclingDocument Encapsulation**
> The `DoclingDocument` object SHALL NOT be persisted to MinIO, the local filesystem, or any store outside the parser class. The `DoclingDocument` SHALL remain encapsulated inside the parser implementation that produced it.
> **Rationale:** With the pluggable parser interface (Gap 8), downstream pipeline stages cannot assume a `DoclingDocument` exists. Chunking uses the parser's native chunker, which accesses `DoclingDocument` internally. Persisting `DoclingDocument` couples the pipeline to Docling and wastes storage on a large intermediate artifact. The current `.docling.json` storage path is eliminated.
> **Acceptance Criteria:**
> 1. No `.docling.json` file is written to any store (local filesystem, MinIO, or elsewhere).
> 2. The `DoclingDocument` is not included in LangGraph state passed between nodes (except within the parser's own `parse()` / `chunk()` boundary).
> 3. The `write_docling()` and `read_docling()` methods on `CleanDocumentStore` are removed as part of the CleanDocumentStore elimination (FR-3030).
> 4. The parser contract's `chunk()` method accesses `DoclingDocument` from internal parser state set during `parse()`, not from pipeline state or external storage.

#### 3.2.2 Clean Store Data Model in MinIO

> **FR-3033: MinIO Clean Store Object Schema**
> Each source document's Phase 1 output SHALL be stored in MinIO as two objects under a `clean/` prefix:
> - `clean/{source_key}.md` — clean markdown text (UTF-8 encoded)
> - `clean/{source_key}.meta.json` — JSON metadata envelope containing source identity fields, `source_hash`, `clean_hash`, `schema_version`, `trace_id`, and processing timestamp.
>
> **Rationale:** A predictable, deterministic key scheme enables efficient lookup, GC enumeration, and migration queries without a secondary index.
> **Acceptance Criteria:**
> 1. The object key uses the `source_key` as the stem, matching the manifest's primary key.
> 2. The `.meta.json` envelope includes at minimum: `source_key`, `source_name`, `source_uri`, `source_id`, `connector`, `source_version`, `source_hash`, `clean_hash`, `schema_version`, `trace_id`, and `created_at`.
> 3. Objects are written with content-type metadata (`text/markdown` and `application/json` respectively).
> 4. Overwriting an existing object for the same `source_key` (re-ingestion) replaces both objects atomically or in a defined order (`.meta.json` last, as the commit marker).

> **FR-3034: Debug Export Compatibility**
> The system SHOULD retain an opt-in debug export mode that writes Phase 1 output to the local filesystem for development and debugging purposes. This mode SHALL be clearly documented as a development convenience, not a production data path.
> **Rationale:** Developers need local file inspection during development. Removing all local filesystem output without a debug alternative degrades the development experience.
> **Acceptance Criteria:**
> 1. A configuration flag (`export_processed`) enables local filesystem export.
> 2. When enabled, the system writes clean markdown and metadata to the configured local directory in addition to MinIO.
> 3. The local export does NOT participate in the inter-phase handoff — Phase 2 still receives data in-memory.
> 4. The local export does NOT write `.docling.json` files (per FR-3032).

---

### 3.3 Per-Document Trace ID and End-to-End Validation (Gap 7)

#### 3.3.1 Trace ID Assignment and Propagation

> **FR-3050: Trace ID Generation**
> Each `IngestDocumentWorkflow` execution SHALL generate a unique trace ID (UUID v4) at workflow start, before any processing begins.
> **Rationale:** A per-document trace ID enables end-to-end correlation across all stores and logs. Without it, debugging failures requires manual cross-referencing of timestamps and source keys across four stores and multiple log streams.
> **Acceptance Criteria:**
> 1. The trace ID is generated as a UUID v4 string.
> 2. The trace ID is generated once at workflow start and is immutable for the duration of that workflow execution.
> 3. Retries of the same workflow execution (e.g., Temporal activity retries) reuse the same trace ID.
> 4. A new workflow execution for the same source document (e.g., re-ingestion) generates a new trace ID.

> **FR-3051: Phase 1 Trace ID Injection**
> The trace ID SHALL be injected into the Phase 1 (Document Processing) LangGraph state as a top-level field, accessible to all nodes in the processing graph.
> **Rationale:** Phase 1 nodes that write to MinIO or log processing events need the trace ID for correlation.
> **Acceptance Criteria:**
> 1. The LangGraph state TypedDict includes a `trace_id: str` field.
> 2. The trace ID is set before the first node executes.
> 3. All Phase 1 log messages include the trace ID in structured log fields.
> 4. The MinIO clean store metadata envelope (FR-3033) includes the trace ID.

> **FR-3052: Phase 2 Trace ID Propagation**
> The trace ID SHALL be carried from Phase 1 through the orchestrator into Phase 2 (Embedding Pipeline) LangGraph state, and SHALL be stored in every output artifact.
> **Rationale:** End-to-end validation (FR-3060) requires querying all stores by trace ID. Each store must have the trace ID on every artifact it holds for a given document.
> **Acceptance Criteria:**
> 1. The Phase 2 LangGraph state TypedDict includes a `trace_id: str` field.
> 2. Every Weaviate chunk object stored for this document includes `trace_id` as a metadata property.
> 3. Every Neo4j triple and entity node stored for this document includes `trace_id` as a property.
> 4. The manifest entry for this document includes the `trace_id` field.
> 5. All Phase 2 log messages include the trace ID in structured log fields.

> **FR-3053: Optional Batch ID**
> The system SHALL support an optional `batch_id` parameter on ingestion requests that groups multiple document ingestions for reporting purposes. The batch ID SHALL NOT affect correctness, ordering, or error handling of individual documents.
> **Rationale:** When a user submits a directory of 500 documents, a batch ID enables aggregate reporting ("batch X: 498 succeeded, 2 failed") without coupling document processing to batch-level coordination.
> **Acceptance Criteria:**
> 1. The `batch_id` is an optional string parameter on the ingestion API and CLI.
> 2. When provided, the `batch_id` is stored in the manifest entry alongside the `trace_id`.
> 3. The `batch_id` is included in Weaviate chunk metadata as an optional property.
> 4. A query or report endpoint can aggregate results by `batch_id`.
> 5. The absence of a `batch_id` does not affect any pipeline behavior.
> 6. Each document in a batch is processed independently — there is no batch-level wait, transaction, or rollback.

#### 3.3.2 End-to-End Validation

> **FR-3060: Per-Document Store Consistency Validation**
> At the end of a successful document ingestion (after Phase 2 completes without errors), the system SHALL perform an end-to-end validation that verifies all expected stores received data for this `trace_id`.
> **Rationale:** Silent partial failures (e.g., Weaviate write succeeds but Neo4j write fails silently) leave the system in an inconsistent state. Validation at pipeline end catches these inconsistencies before they compound.
> **Acceptance Criteria:**
> 1. The validation queries Weaviate for at least one chunk with the document's `trace_id`.
> 2. The validation queries MinIO for the clean markdown object with the document's `source_key`.
> 3. If knowledge graph extraction is enabled, the validation queries Neo4j for at least one triple with the document's `trace_id`.
> 4. The validation verifies the manifest entry exists and contains the `trace_id`.
> 5. If any store is missing expected data, the validation logs a warning with the `trace_id`, `source_key`, and the name of the failing store.
> 6. Validation failure does NOT automatically retry the pipeline — it surfaces the inconsistency for operator review.

> **FR-3061: Validation Result Recording**
> The end-to-end validation result SHALL be recorded in the manifest entry for the document, including per-store validation status and timestamp.
> **Rationale:** Persisting validation results enables later auditing and targeted re-processing of documents with known inconsistencies.
> **Acceptance Criteria:**
> 1. The manifest entry includes a `validation` object with fields: `validated_at` (ISO 8601 timestamp), `weaviate_ok` (boolean), `minio_ok` (boolean), `neo4j_ok` (boolean or null if KG disabled), and `consistent` (boolean, true only if all enabled stores passed).
> 2. The validation result is written as part of the manifest update at pipeline end.
> 3. A query or report can filter manifest entries by `validation.consistent == false` to find inconsistent documents.

> **FR-3062: Validation Skip for Disabled Stores**
> End-to-end validation SHALL skip checks for stores that are disabled in the current configuration (e.g., if `build_kg=False`, the Neo4j check is skipped).
> **Rationale:** Not all deployments use all four stores. Validation must adapt to the configured store set to avoid false negatives.
> **Acceptance Criteria:**
> 1. The validation reads the current configuration to determine which stores are active.
> 2. Disabled stores are reported as `null` (not `false`) in the validation result.
> 3. A document is considered `consistent` when all enabled stores pass validation.

---

### 3.4 Schema Versioning and Incremental Migration (Gap 11)

#### 3.4.1 Schema Version Tracking

> **FR-3100: Schema Version on Manifest Entries**
> Each manifest entry SHALL include a `schema_version` field that records the pipeline schema version that produced the entry's data. The schema version SHALL be a semantic version string (e.g., `"1.0.0"`).
> **Rationale:** Without a version stamp, there is no way to identify which documents need re-processing after a pipeline upgrade. The only option is full re-ingestion, which is expensive and unnecessary when only metadata changed.
> **Acceptance Criteria:**
> 1. The `ManifestEntry` TypedDict includes a `schema_version: str` field.
> 2. Every new or updated manifest entry is written with the current pipeline schema version.
> 3. Existing manifest entries without a `schema_version` field are treated as version `"0.0.0"` (pre-versioning).
> 4. The current schema version is defined in a single canonical location in the codebase (e.g., a constant in the configuration module).

> **FR-3101: Schema Version on Weaviate Chunk Metadata**
> Every Weaviate chunk object SHALL include a `schema_version` metadata property matching the pipeline schema version at the time of storage.
> **Rationale:** Weaviate is the primary retrieval store. Schema version on chunks enables targeted migration queries directly in Weaviate without cross-referencing the manifest.
> **Acceptance Criteria:**
> 1. The Weaviate collection schema includes a `schema_version` string property.
> 2. Every chunk stored in Weaviate includes `schema_version` with the current pipeline version.
> 3. Existing chunks without `schema_version` are treated as version `"0.0.0"` in migration queries.

> **FR-3102: Schema Version on MinIO Metadata**
> MinIO clean store metadata envelopes (FR-3033) SHALL include the `schema_version` field.
> **Rationale:** Migration jobs need to identify which clean store artifacts were produced under which schema to determine if Phase 1 re-processing is needed.
> **Acceptance Criteria:**
> 1. The `.meta.json` envelope in MinIO includes `schema_version`.
> 2. The version matches the manifest entry's `schema_version` for the same `source_key`.

#### 3.4.2 Migration Job

> **FR-3110: Selective Re-Processing by Schema Version**
> The system SHALL provide a migration job that queries the manifest for documents where `schema_version < current_version` and re-processes only those documents.
> **Rationale:** After a pipeline upgrade, only documents produced under the old schema need re-processing. Full re-ingestion wastes compute on documents that are already current.
> **Acceptance Criteria:**
> 1. A CLI command (e.g., `aion ingest migrate`) triggers the migration job.
> 2. The migration job queries the manifest for entries where `schema_version` is less than the current pipeline schema version.
> 3. The migration job supports a `--dry-run` flag that reports which documents would be re-processed without executing.
> 4. The migration job supports a `--target-version` flag to migrate only to a specific version (not necessarily the latest).
> 5. Re-processed documents receive the current `schema_version` upon successful completion.
> 6. The migration job produces a summary report: total eligible, processed, failed, skipped.

> **FR-3111: Migration Strategy Classification**
> The migration job SHALL classify each schema version transition into one of three migration strategies, and SHALL apply only the minimum re-processing required:
>
> 1. **Metadata-only update:** When the schema change adds or modifies Weaviate metadata properties without affecting embeddings or KG triples, the migration SHALL perform a Weaviate batch metadata update without re-embedding. This is the cheapest migration path.
> 2. **Full Phase 2 re-run:** When the schema change involves an embedding model change (different model, different dimensionality, different normalization), the migration SHALL re-run the full Embedding Pipeline (Phase 2) for affected documents. The clean markdown from MinIO is used as input (no Phase 1 re-run needed).
> 3. **KG re-extraction:** When the schema change involves modifications to the knowledge graph extraction logic, the migration SHALL delete existing triples for affected documents and re-run the KG extraction nodes. Existing triples remain valid when only new relationship types are added — re-extraction is needed only when extraction logic itself changed.
>
> **Rationale:** Different schema changes have vastly different re-processing costs. Treating all changes as "full re-ingestion" wastes GPU time on metadata-only updates. Classifying changes enables the minimum-cost migration path.
> **Acceptance Criteria:**
> 1. The migration system maintains a schema changelog that maps version transitions to migration strategies.
> 2. For metadata-only migrations, no embedding computation occurs — Weaviate objects are updated via batch partial-update API.
> 3. For full Phase 2 re-runs, clean markdown is read from MinIO (FR-3031) and passed through the Embedding Pipeline. Phase 1 is not re-run.
> 4. For KG re-extraction, existing triples with matching `source_key` provenance are deleted before re-extraction.
> 5. New KG relationship types added to the schema do NOT trigger re-extraction of existing documents — only documents processed after the schema change will include the new relationship types.
> 6. The migration strategy for each version transition is documented in the schema changelog and is auditable.

> **FR-3112: Migration Idempotency**
> The migration job SHALL be idempotent: running the same migration job twice for the same version transition SHALL produce the same result and SHALL NOT corrupt or duplicate data.
> **Rationale:** Migration jobs may be interrupted (node failure, timeout) and retried. Idempotency ensures retries are safe.
> **Acceptance Criteria:**
> 1. Re-processing a document that already has the target `schema_version` is a no-op (skipped).
> 2. Partial migrations (interrupted mid-batch) can be resumed by re-running the migration job — already-migrated documents are skipped.
> 3. Weaviate metadata updates use upsert semantics (update-or-insert), not append.
> 4. KG re-extraction deletes existing triples before inserting new ones (delete-then-insert, not append).

> **FR-3113: Schema Changelog**
> The system SHALL maintain a machine-readable schema changelog that records each schema version, the date it was introduced, a description of the changes, and the migration strategy required.
> **Rationale:** The migration job (FR-3110) needs to know which migration strategy to apply for each version transition. A machine-readable changelog enables automated migration planning.
> **Acceptance Criteria:**
> 1. The changelog is stored as a YAML or JSON file in the codebase (e.g., `config/schema_changelog.yaml`).
> 2. Each entry includes: `version`, `date`, `description`, and `migration_strategy` (one of `metadata_only`, `full_phase2`, `kg_reextract`, or `none`).
> 3. The migration job reads the changelog to determine the migration strategy for each document's version gap.
> 4. Adding a new schema version requires adding a changelog entry — the CI system SHOULD validate this.

> **FR-3114: Backward-Compatible Manifest Extension**
> New fields added to the `ManifestEntry` schema SHALL be backward-compatible: existing manifest entries without the new fields SHALL be loadable without error, and the new fields SHALL have documented default values.
> **Rationale:** The manifest is a JSON file that evolves with the pipeline. Breaking changes to the manifest schema would require a separate manifest migration, adding unnecessary complexity. Forward-compatible design avoids this.
> **Acceptance Criteria:**
> 1. All new `ManifestEntry` fields are declared with `total=False` (optional) in the TypedDict.
> 2. Code that reads manifest entries uses `.get()` with explicit defaults for new fields.
> 3. The `_normalize_manifest_entries()` function handles missing fields gracefully.
> 4. A manifest written by an older pipeline version is loadable by a newer pipeline version without error or data loss.

---

## 4. Non-Functional Requirements

### 4.1 Performance

> **NFR-3180: GC Scan Performance**
> The sync diff operation (FR-3000) SHALL complete within O(n) time relative to the number of manifest entries, not O(n*m) where m is the number of objects per store.
> **Rationale:** GC must be efficient enough to run on every incremental ingestion without adding meaningful latency.

> **NFR-3181: Migration Throughput**
> Metadata-only migrations (FR-3111, strategy 1) SHALL process at least 100 documents per second on a single worker node.
> **Rationale:** Metadata updates are cheap (no embedding computation) and should not bottleneck on sequential processing.

### 4.2 Reliability

> **NFR-3210: Partial GC Failure Isolation**
> A failure to clean one store during GC SHALL NOT prevent cleanup of the remaining stores. The system SHALL log the failure and continue with best-effort cleanup.
> **Rationale:** Store-level failures (e.g., Neo4j temporarily unavailable) should not leave the entire GC run in a half-completed state.

> **NFR-3211: Migration Resumability**
> An interrupted migration job SHALL be resumable from the point of interruption without re-processing already-migrated documents.
> **Rationale:** Large migrations (thousands of documents) may take hours. An interruption at document 900 of 1000 should not require re-processing documents 1-899.

### 4.3 Observability

> **NFR-3220: Trace ID in All Log Lines**
> Every log message emitted during a document's ingestion (both phases) SHALL include the document's `trace_id` as a structured log field.
> **Rationale:** Trace ID is useless for debugging if it is not consistently present in logs. This is the primary correlation key for distributed tracing.

> **NFR-3221: GC Audit Log**
> Every GC operation (soft delete, hard delete, retention purge) SHALL produce an audit log entry containing the `source_key`, operation type, affected stores, and operator/trigger identity.
> **Rationale:** GC operations are destructive. An audit trail is essential for incident investigation and compliance.

### 4.4 Security

> **NFR-3230: Hard Delete Confirmation**
> Hard delete operations triggered via CLI SHALL require explicit confirmation (e.g., `--confirm` flag or interactive prompt) unless `--force` is specified.
> **Rationale:** Hard delete is irreversible. Requiring confirmation prevents accidental data loss.

---

## 5. Dependencies and Interactions

### 5.1 Upstream Dependencies

| Dependency | Description |
|-----------|-------------|
| `INGESTION_PLATFORM_SPEC.md` | Re-ingestion strategy, manifest data model, configuration system, error handling |
| `DOCUMENT_PROCESSING_SPEC.md` | Phase 1 stage requirements; defines what Phase 1 outputs |
| `EMBEDDING_PIPELINE_SPEC.md` | Phase 2 stage requirements; defines what Phase 2 writes to stores |

### 5.2 Downstream Consumers

| Consumer | Interaction |
|----------|------------|
| `DATA_LIFECYCLE_DESIGN.md` | Design document implementing these requirements |
| `DATA_LIFECYCLE_SPEC_SUMMARY.md` | Concise summary for stakeholder review |
| Retrieval layer | Relies on soft-delete filtering to exclude deleted documents from search results |
| Temporal workflows | GC and migration jobs are orchestrated as Temporal workflows |

### 5.3 Store-Level Interfaces

| Store | GC Operation | Trace ID Storage | Schema Version Storage |
|-------|-------------|-----------------|----------------------|
| Weaviate | Delete objects by `source_key` filter | `trace_id` metadata property on each chunk | `schema_version` metadata property on each chunk |
| MinIO | Delete objects by `source_key` prefix under `clean/` | `trace_id` in `.meta.json` envelope | `schema_version` in `.meta.json` envelope |
| Neo4j | Delete triples by `source_key` provenance | `trace_id` property on triple/entity nodes | N/A (triples are re-extracted, not versioned) |
| Manifest | Update or remove entry by `source_key` | `trace_id` field on entry | `schema_version` field on entry |

---

## 6. Requirements Traceability Matrix

| FR / NFR | Gap | Category | Priority |
|----------|-----|----------|----------|
| FR-3000 | 2 | GC / Sync | MUST |
| FR-3001 | 2 | GC / Sync | MUST |
| FR-3002 | 2 | GC / Sync | SHOULD |
| FR-3010 | 2 | GC Triggers | MUST |
| FR-3011 | 2 | GC Triggers | SHOULD |
| FR-3012 | 2 | GC Triggers | MUST |
| FR-3020 | 2 | Soft Delete | MUST |
| FR-3021 | 2 | Hard Delete | MUST |
| FR-3022 | 2 | Retention | MUST |
| FR-3030 | 4 | Durable State | MUST |
| FR-3031 | 4 | Durable State | MUST |
| FR-3032 | 4 | Durable State | MUST |
| FR-3033 | 4 | Durable State | MUST |
| FR-3034 | 4 | Durable State | SHOULD |
| FR-3050 | 7 | Trace ID | MUST |
| FR-3051 | 7 | Trace ID | MUST |
| FR-3052 | 7 | Trace ID | MUST |
| FR-3053 | 7 | Trace ID | SHOULD |
| FR-3060 | 7 | Validation | MUST |
| FR-3061 | 7 | Validation | SHOULD |
| FR-3062 | 7 | Validation | MUST |
| FR-3100 | 11 | Schema Version | MUST |
| FR-3101 | 11 | Schema Version | MUST |
| FR-3102 | 11 | Schema Version | MUST |
| FR-3110 | 11 | Migration | MUST |
| FR-3111 | 11 | Migration | MUST |
| FR-3112 | 11 | Migration | MUST |
| FR-3113 | 11 | Migration | SHOULD |
| FR-3114 | 11 | Migration | MUST |
| NFR-3180 | 2 | Performance | SHOULD |
| NFR-3181 | 11 | Performance | SHOULD |
| NFR-3210 | 2 | Reliability | MUST |
| NFR-3211 | 11 | Reliability | MUST |
| NFR-3220 | 7 | Observability | MUST |
| NFR-3221 | 2 | Observability | SHOULD |
| NFR-3230 | 2 | Security | SHOULD |

---

## Appendix A: Manifest Entry Schema (Extended)

The following fields are added to `ManifestEntry` by this specification. All fields are optional (`total=False`) per FR-3114.

```python
class ManifestEntry(TypedDict, total=False):
    # ... existing fields from schemas.py ...
    source: str
    source_uri: str
    source_id: str
    source_key: str
    connector: str
    source_version: str
    content_hash: str
    chunk_count: int
    summary: str
    keywords: list[str]
    processing_log: list[str]
    mirror_stem: str
    legacy_name: str

    # --- Added by DATA_LIFECYCLE_SPEC ---
    schema_version: str        # Pipeline schema version (e.g., "1.0.0")
    trace_id: str              # UUID v4 trace ID for this ingestion run
    batch_id: str              # Optional batch grouping ID
    deleted: bool              # True if soft-deleted
    deleted_at: str            # ISO 8601 timestamp of soft deletion
    validation: dict           # E2E validation result (see FR-3061)
    clean_hash: str            # SHA-256 of clean markdown output
```

## Appendix B: Schema Changelog Format

```yaml
# config/schema_changelog.yaml
schema_versions:
  - version: "0.0.0"
    date: "2026-01-01"
    description: "Pre-versioning baseline. All documents ingested before schema versioning."
    migration_strategy: "none"

  - version: "1.0.0"
    date: "2026-04-15"
    description: >
      Initial versioned schema. Adds schema_version, trace_id, batch_id,
      deleted/deleted_at, validation, and clean_hash to manifest entries.
      Adds schema_version and trace_id to Weaviate chunk metadata.
    migration_strategy: "metadata_only"
    notes: >
      Existing documents can be migrated via Weaviate batch metadata update.
      No re-embedding required. Manifest entries are updated in-place with
      new fields set to defaults.
```

## Appendix C: Current Implementation References

The following source files contain the current implementations that this specification targets for replacement or extension:

| File | Relevance |
|------|-----------|
| `src/ingest/common/clean_store.py` | `CleanDocumentStore` class — replaced by in-memory handoff + MinIO (FR-3030, FR-3031) |
| `src/ingest/common/utils.py` | `load_manifest()`, `save_manifest()` — extended with new fields (FR-3100, FR-3114) |
| `src/ingest/common/schemas.py` | `ManifestEntry` TypedDict — extended with new fields (Appendix A) |
| `src/ingest/impl.py` | `ingest_directory()` — GC logic extended to all four stores (FR-3001, FR-3012); `ingest_file()` — trace ID injection point (FR-3050) |
