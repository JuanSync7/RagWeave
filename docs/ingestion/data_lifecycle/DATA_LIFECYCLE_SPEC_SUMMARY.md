# Data Lifecycle — Specification Summary

> **Document type:** Specification summary (Layer 2)
> **Upstream:** DATA_LIFECYCLE_SPEC.md
> **Last updated:** 2026-04-15

---

## 1) System Overview

### Purpose

When a document ingestion system writes data to multiple independent storage backends, deletions, updates, and schema changes create lifecycle problems that no single store can solve alone. Source documents are deleted but their derived data persists as orphans across stores, consuming resources and polluting search results. Inter-phase handoffs that rely on a single node's local filesystem prevent the system from scaling horizontally. Documents flow through the pipeline without a unique trace identifier, making end-to-end debugging impossible when partial failures leave stores in inconsistent states. Pipeline upgrades change metadata schemas, but without version tracking there is no way to selectively re-process only the documents that need migration — the only option is an expensive full re-ingestion.

### Pipeline Flow

The data lifecycle subsystem operates across the entire ingestion pipeline, not as a single stage. It provides four cross-cutting capabilities. First, a garbage collection and sync mechanism compares the current source file inventory against the system's record of what has been ingested, classifying documents as added, modified, or deleted. Deleted documents undergo reconciliation across all storage backends — not just one or two. Second, the inter-phase boundary between document processing and embedding is replaced: instead of writing intermediate files to a local directory, the first phase returns its output in memory while a durable object store holds the authoritative copy. Third, every document ingestion receives a unique trace identifier at the start of its workflow, and that identifier is carried through both pipeline phases and written into every output artifact in every store. At pipeline completion, an end-to-end validation step queries all stores by trace identifier to verify consistency. Fourth, every ingested document is stamped with the pipeline's schema version. When the pipeline is upgraded, a migration job identifies documents with stale schema versions and applies the minimum re-processing required — metadata-only updates when only properties changed, a full embedding re-run when the model changed, or targeted re-extraction when knowledge graph logic changed.

### Tunable Knobs

Operators can configure the garbage collection trigger mode (manual, scheduled, or on-ingest), the delete mode (soft with configurable retention period, or immediate hard delete), whether a debug export of intermediate files is produced for development purposes, and the schema version changelog that maps version transitions to migration strategies. All configuration follows the existing pattern of environment variables with sensible defaults.

### Design Rationale

Three principles govern the design. Durability without locality means the system persists all inter-phase data to a shared object store, eliminating single-node coupling while keeping the in-memory path fast for normal operation. Safety-first deletion means soft delete is the default, providing a recovery window before data is irrevocably purged. Minimum-cost migration means schema changes are classified by their re-processing impact, so the cheapest path is always taken rather than defaulting to full re-ingestion.

### Boundary Semantics

The subsystem's entry points are the source directory (ground truth for what files exist), the ingestion manifest (record of what has been ingested), and the four storage backends. Its exit points are reconciled stores with orphaned data removed, validated consistency across all stores for each trace identifier, and a manifest annotated with schema versions and validation results. The subsystem does not modify pipeline stage logic — it governs when and how data is created, tracked, aged, garbage-collected, and migrated across all backends.

---

## 2) Scope and Boundaries

**Entry points:** Source directory, ingestion manifest, four storage backends (vector store, object store, graph store, manifest).

**Exit points:** Reconciled stores, validated consistency per trace ID, version-stamped manifest entries.

**In scope:** Document GC/sync, soft and hard delete with retention, durable state boundary (eliminating local filesystem handoff), per-document trace ID, end-to-end store validation, schema versioning, incremental migration with strategy classification.

**Out of scope:** Pipeline stage logic (Phase 1 and Phase 2), cross-document deduplication, priority queue mechanics, LangGraph checkpointing, incremental chunk-level re-embedding, progress reporting UI, retrieval and query processing.

---

## 3) Garbage Collection and Sync (FR-3000–FR-3022)

The sync operation (FR-3000) diffs source files against the manifest to identify additions, modifications, and deletions. Deletions trigger four-store reconciliation (FR-3001) — Weaviate chunks, MinIO blobs, Neo4j triples, and the manifest entry are all cleaned, unlike the current implementation which only handles Weaviate and the manifest. An orphan detection report (FR-3002) scans for store data with no manifest entry.

Three trigger modes are supported: manual CLI command with dry-run and mode flags (FR-3010), scheduled GC via cron-like configuration (FR-3011), and on-ingest diff during incremental update runs (FR-3012). Soft delete is the default (FR-3020) — data is marked with a `deleted_at` timestamp, hidden from retrieval, and purged after a configurable retention period (default 30 days). Hard delete (FR-3021) is available as an explicit override for urgent purges. Retention purge (FR-3022) runs on every GC cycle to clean expired soft deletes. Key decision: partial store failures during GC are logged but do not block cleanup of remaining stores.

---

## 4) Durable State Boundary (FR-3030–FR-3034)

The local `CleanDocumentStore` is eliminated. Phase 1 returns clean markdown and metadata in-memory to the orchestrator (FR-3030), which passes them directly to Phase 2 with no local filesystem read or write. MinIO serves as the single durable store for processed documents (FR-3031), with objects keyed by `source_key` under a `clean/` prefix. The `DoclingDocument` is encapsulated inside the parser and is no longer persisted to any store (FR-3032). The MinIO clean store uses a two-object schema per document: `.md` and `.meta.json` (FR-3033). An opt-in debug export mode (FR-3034) retains local file output for development convenience.

Key trade-off: the in-memory handoff is fast for normal operation, while MinIO provides durability for recovery, GC, and migration without coupling the pipeline to a single node's filesystem.

---

## 5) Per-Document Trace ID and Validation (FR-3050–FR-3062)

Each `IngestDocumentWorkflow` generates a UUID v4 trace ID at workflow start (FR-3050). The trace ID is injected into Phase 1 LangGraph state (FR-3051), propagated through Phase 2 (FR-3052), and stored in every output artifact across all four stores. An optional batch ID (FR-3053) groups multi-document ingestions for aggregate reporting without affecting processing.

End-to-end validation (FR-3060) runs after Phase 2 completes, querying all enabled stores by trace ID to confirm each received the document's data. Validation results are recorded in the manifest (FR-3061) with per-store boolean status. Disabled stores are skipped and reported as null (FR-3062). Key decision: validation failure surfaces the inconsistency for operator review rather than automatically retrying the pipeline.

---

## 6) Schema Versioning and Migration (FR-3100–FR-3114)

Every manifest entry (FR-3100), Weaviate chunk (FR-3101), and MinIO metadata envelope (FR-3102) carries a `schema_version` field. Pre-versioning data defaults to `"0.0.0"`. A migration job (FR-3110) queries for documents with stale schema versions and re-processes only those.

Migration strategy classification (FR-3111) is the central design decision: metadata-only updates use Weaviate batch partial updates (cheapest), embedding model changes trigger a full Phase 2 re-run reading from MinIO, and KG logic changes trigger targeted triple re-extraction. Adding new KG relationship types does not require re-extraction. Migration is idempotent (FR-3112) — interrupted runs resume safely. A machine-readable schema changelog (FR-3113) maps version transitions to strategies. Manifest extensions are backward-compatible with optional fields and explicit defaults (FR-3114).

---

## 7) Non-Functional and Security Themes

- **Performance:** GC scan completes in O(n) relative to manifest entries (NFR-3180). Metadata-only migrations process at least 100 documents/second (NFR-3181).
- **Reliability:** Partial GC failure in one store does not block cleanup of others (NFR-3210). Interrupted migrations are resumable (NFR-3211).
- **Observability:** Trace ID appears in every log line during ingestion (NFR-3220). Every GC operation produces an audit log entry (NFR-3221).
- **Security:** Hard delete via CLI requires explicit confirmation (NFR-3230).

---

## 8) Key Design Decisions

- **Four-store reconciliation for GC:** All backends are cleaned on deletion, not just the vector store and manifest. This prevents orphan accumulation that the current implementation allows.
- **In-memory handoff + MinIO durable copy:** Normal operation uses the fast in-memory path; MinIO provides recovery, migration, and multi-node access without local filesystem coupling.
- **DoclingDocument encapsulation:** Parser-internal types no longer cross the pipeline boundary, enabling pluggable parser swappability.
- **Three-tier migration classification:** Schema changes are mapped to minimum-cost re-processing strategies, avoiding unnecessary full re-ingestion.
- **Soft delete as default:** A 30-day retention window protects against accidental deletions from temporarily moved or renamed source files.
- **Trace ID as universal correlation key:** A single UUID v4 per document ingestion enables cross-store debugging and end-to-end consistency validation.

---

## 9) Requirement Summary

The spec covers **29 functional requirements** and **7 non-functional/security requirements** across four gaps:

| ID Range | Domain | Count |
|----------|--------|-------|
| FR-3000–FR-3022 | GC/Sync, Soft/Hard Delete, Retention | 9 |
| FR-3030–FR-3034 | Durable State Boundary (MinIO) | 5 |
| FR-3050–FR-3062 | Trace ID, Batch ID, E2E Validation | 7 |
| FR-3100–FR-3114 | Schema Versioning, Migration | 8 |
| NFR-3180–NFR-3230 | Performance, Reliability, Observability, Security | 7 |

---

## 10) Companion Documents

| Document | Purpose |
|----------|---------|
| DATA_LIFECYCLE_SPEC.md | Authoritative requirements specification — source of truth |
| DATA_LIFECYCLE_SPEC_SUMMARY.md (this document) | Stakeholder-ready digest |
| DATA_LIFECYCLE_DESIGN.md | Task decomposition and implementation contracts |
| INGESTION_PLATFORM_SPEC.md | Cross-cutting platform requirements (re-ingestion, config, error handling) |
| DOCUMENT_PROCESSING_SPEC.md | Phase 1 functional requirements |
| EMBEDDING_PIPELINE_SPEC.md | Phase 2 functional requirements |

---

## 11) Sync Status

- **Spec version aligned to:** DATA_LIFECYCLE_SPEC.md v1.0.0
- **Last synced:** 2026-04-15
- **Sync method:** Manual review
