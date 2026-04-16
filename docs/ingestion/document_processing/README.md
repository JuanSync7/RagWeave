<!-- @summary
Document processing pipeline documentation: Phase 1 spec/design/implementation/tests and Docling chunking spec/design/implementation/tests.
@end-summary -->

# docs/ingestion/document_processing

## Overview

Engineering documentation for Phase 1 of the ingestion pipeline (document processing) and the Docling-based chunking subsystem.

## Files

### Document Processing (Phase 1)

| File | Purpose |
| --- | --- |
| `DOCUMENT_PROCESSING_SPEC.md` | Phase 1 pipeline specification (5 nodes) |
| `DOCUMENT_PROCESSING_SPEC_SUMMARY.md` | Concise summary of Phase 1 spec |
| `DOCUMENT_PROCESSING_DESIGN.md` | Phase 1 design document (task decomposition, contracts, dependency graph) |
| `DOCUMENT_PROCESSING_IMPLEMENTATION.md` | Phase 1 implementation guide |
| `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md` | Phase 1 engineering guide |
| `DOCUMENT_PROCESSING_MODULE_TESTS.md` | Phase 1 module-level test specifications |

### Document Parsing

| File | Purpose |
| --- | --- |
| `DOCUMENT_PARSING_SPEC.md` | Abstract parser contract specification |
| `DOCUMENT_PARSING_SPEC_SUMMARY.md` | Concise summary of parser contract spec |
| `DOCUMENT_PARSING_DESIGN.md` | Design document (task decomposition, interfaces, contracts) |
| `DOCUMENT_PARSING_IMPLEMENTATION.md` | Implementation guide (code-level, module-by-module) |
| `DOCUMENT_PARSING_ENGINEERING_GUIDE.md` | Engineering guide (architecture decisions, operations, troubleshooting) |
| `DOCUMENT_PARSING_TEST_DOCS.md` | Test documentation (unit, integration, contract tests) |

> **Note:** DOCUMENT_PARSING_SPEC.md defines the abstract parser contract. DOCLING_CHUNKING_SPEC.md documents the Docling-specific implementation.

### Docling Chunking

| File | Purpose |
| --- | --- |
| `DOCLING_CHUNKING_SPEC.md` | Docling chunking specification (hybrid chunking strategy) |
| `DOCLING_CHUNKING_SPEC_SUMMARY.md` | Concise summary of Docling chunking spec |
| `DOCLING_CHUNKING_DESIGN.md` | Docling chunking design document |
| `DOCLING_CHUNKING_IMPLEMENTATION.md` | Docling chunking implementation guide |
| `DOCLING_CHUNKING_ENGINEERING_GUIDE.md` | Docling chunking engineering guide |
| `DOCLING_CHUNKING_MODULE_TESTS.md` | Docling chunking module-level test specifications |
