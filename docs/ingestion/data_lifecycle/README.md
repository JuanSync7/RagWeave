<!-- @summary
Data lifecycle documentation: GC/sync, durable state boundary, trace ID, schema versioning.
@end-summary -->

# docs/ingestion/data_lifecycle

## Overview

This directory contains specifications, design documents, and summaries for the **Data Lifecycle** subsystem of the AION RAG Document Embedding Pipeline. The data lifecycle subsystem governs how ingested data is created, tracked, aged, garbage-collected, and migrated across all four storage backends (Weaviate, MinIO, Neo4j, and the ingestion manifest).

The subsystem addresses four identified gaps in the ingestion pipeline:

| Gap | Topic | Summary |
|-----|-------|---------|
| Gap 2 | Document GC / Sync | Three-mode garbage collection (manual, scheduled, on-ingest diff) with soft delete and configurable retention across all four stores |
| Gap 4 | Durable State Boundary | Replace local `CleanDocumentStore` filesystem handoff with in-memory state flow and MinIO as the single durable store |
| Gap 7 | Per-Document Trace ID | UUID v4 trace ID per document workflow, carried through both phases, used for end-to-end store consistency validation |
| Gap 11 | Schema Versioning | Version stamp on manifest entries and Weaviate metadata; incremental migration job with three strategy tiers (metadata-only, full Phase 2, KG re-extract) |

## Files

| File | Purpose |
|------|---------|
| `DATA_LIFECYCLE_SPEC.md` | Authoritative L3 requirements specification (FR-3000 through FR-3114, NFR-3180 through NFR-3230) |
| `DATA_LIFECYCLE_SPEC_SUMMARY.md` | Concise summary for stakeholder review |
| `DATA_LIFECYCLE_DESIGN.md` | Design document (task decomposition, interfaces, migration path) |
| `DATA_LIFECYCLE_IMPLEMENTATION.md` | Implementation guide (code-level, module-by-module) |
| `DATA_LIFECYCLE_ENGINEERING_GUIDE.md` | Engineering guide (architecture decisions, operations, troubleshooting, testing) |
| `DATA_LIFECYCLE_TEST_DOCS.md` | Test documentation (unit, integration, contract tests with FR traceability) |

## Relationship to Other Specs

- **`INGESTION_PLATFORM_SPEC.md`** defines the cross-cutting platform requirements (re-ingestion, config, error handling) that this subsystem extends.
- **`DOCUMENT_PROCESSING_SPEC.md`** defines Phase 1 stage requirements; the durable state boundary (Gap 4) changes how Phase 1 output is persisted.
- **`EMBEDDING_PIPELINE_SPEC.md`** defines Phase 2 stage requirements; trace ID propagation (Gap 7) and schema versioning (Gap 11) add metadata to Phase 2 outputs.

## FR Number Range

This subsystem uses FR-3000 through FR-3199 to avoid collision with existing ranges:

| Range | Spec |
|-------|------|
| FR-100 -- FR-589 | Document Processing (`DOCUMENT_PROCESSING_SPEC.md`) |
| FR-591 -- FR-1399 | Embedding Pipeline (`EMBEDDING_PIPELINE_SPEC.md`) |
| FR-2201 -- FR-2313 | Platform (`INGESTION_PLATFORM_SPEC.md`) |
| **FR-3000 -- FR-3199** | **Data Lifecycle (this directory)** |
