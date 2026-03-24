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

## Key Starting Points

- **New to the codebase?** Start with `INGESTION_PIPELINE_ENGINEERING_GUIDE.md`
- **Understanding requirements?** Read `INGESTION_PLATFORM_SPEC.md`
- **Phase 1 deep dive?** `DOCUMENT_PROCESSING_SPEC.md` + `DOCUMENT_PROCESSING_DESIGN.md`
- **Phase 2 deep dive?** `EMBEDDING_PIPELINE_SPEC.md` + `EMBEDDING_PIPELINE_DESIGN.md`
