<!-- @summary
Ingestion pipeline documentation: platform spec, phase specs (doc processing + embedding), design docs, implementation guides, engineering guide, and onboarding checklist.
@end-summary -->

# docs/ingestion

## Overview

Engineering documentation for the two-phase document ingestion pipeline.

## Files

| File | Purpose |
| --- | --- |
| `INGESTION_PLATFORM_SPEC.md` | Master ingestion platform specification (all phases, connectors, config) |
| `DOCUMENT_PROCESSING_SPEC.md` | Phase 1 (Document Processing, 5 nodes) pipeline specification |
| `DOCUMENT_PROCESSING_SPEC_SUMMARY.md` | Concise summary of Phase 1 spec |
| `DOCUMENT_PROCESSING_DESIGN.md` | Phase 1 design document (task decomposition, contracts, dependency graph) |
| `DOCUMENT_PROCESSING_IMPLEMENTATION.md` | Phase 1 implementation guide |
| `EMBEDDING_PIPELINE_SPEC.md` | Phase 2 (Embedding Pipeline, 8 nodes) specification |
| `EMBEDDING_PIPELINE_SPEC_SUMMARY.md` | Concise summary of Phase 2 spec |
| `EMBEDDING_PIPELINE_DESIGN.md` | Phase 2 design document |
| `EMBEDDING_PIPELINE_IMPLEMENTATION.md` | Phase 2 implementation guide |
| `INGESTION_PIPELINE_ENGINEERING_GUIDE.md` | Implementation-oriented walkthrough: architecture, stage contracts, config, extension steps, troubleshooting |
| `INGESTION_NEW_ENGINEER_ONBOARDING_CHECKLIST.md` | One-page onboarding checklist for first-day setup, first change workflow, and common gotchas |
| `FR_BLOCK_FORMATTING_METHOD.md` | FR block formatting reference for writing spec documents |

### Subdirectories

| Directory | Purpose |
| --- | --- |
| `document_processing/` | Phase 1 pipeline specs, design, implementation, and Docling chunking docs |
| `embedding/` | Phase 2 pipeline specs, design, implementation, and cross-document dedup docs |
| `data_lifecycle/` | Data lifecycle specs (GC/sync, durable state boundary, trace ID, schema versioning) |
| `orchestration/` | Ingestion orchestration specs (priority queues, Temporal queue routing, worker slot allocation) |

### Subdirectory Spec Files

| File | Purpose |
| --- | --- |
| `document_processing/DOCUMENT_PARSING_SPEC.md` | Abstract parser contract specification |
| `document_processing/DOCUMENT_PARSING_SPEC_SUMMARY.md` | Concise summary of parser contract spec |
| `embedding/CROSS_DOCUMENT_DEDUP_SPEC.md` | Cross-document deduplication specification |
| `embedding/CROSS_DOCUMENT_DEDUP_SPEC_SUMMARY.md` | Concise summary of cross-document dedup spec |
| `data_lifecycle/DATA_LIFECYCLE_SPEC.md` | Data lifecycle requirements specification (FR-3000 through FR-3114) |
| `data_lifecycle/DATA_LIFECYCLE_SPEC_SUMMARY.md` | Concise summary of data lifecycle spec |
| `data_lifecycle/DATA_LIFECYCLE_DESIGN.md` | Data lifecycle design document |
| `data_lifecycle/DATA_LIFECYCLE_IMPLEMENTATION.md` | Data lifecycle implementation guide |
| `data_lifecycle/DATA_LIFECYCLE_ENGINEERING_GUIDE.md` | Data lifecycle engineering guide |
| `data_lifecycle/DATA_LIFECYCLE_TEST_DOCS.md` | Data lifecycle test documentation |
| `document_processing/DOCUMENT_PARSING_DESIGN.md` | Document parsing design document |
| `document_processing/DOCUMENT_PARSING_IMPLEMENTATION.md` | Document parsing implementation guide |
| `document_processing/DOCUMENT_PARSING_ENGINEERING_GUIDE.md` | Document parsing engineering guide |
| `document_processing/DOCUMENT_PARSING_TEST_DOCS.md` | Document parsing test documentation |
| `orchestration/INGESTION_ORCHESTRATION_SPEC.md` | Ingestion orchestration specification (FR-3550 through FR-3576) |
| `orchestration/INGESTION_ORCHESTRATION_SPEC_SUMMARY.md` | Concise summary of ingestion orchestration spec |
| `orchestration/INGESTION_ORCHESTRATION_DESIGN.md` | Ingestion orchestration design document |
| `orchestration/INGESTION_ORCHESTRATION_IMPLEMENTATION.md` | Ingestion orchestration implementation guide |

## Key Starting Points

- **New to the codebase?** Start with `INGESTION_PIPELINE_ENGINEERING_GUIDE.md`
- **Understanding requirements?** Read `INGESTION_PLATFORM_SPEC.md`
- **Phase 1 deep dive?** `DOCUMENT_PROCESSING_SPEC.md` + `DOCUMENT_PROCESSING_DESIGN.md`
- **Phase 2 deep dive?** `EMBEDDING_PIPELINE_SPEC.md` + `EMBEDDING_PIPELINE_DESIGN.md`
