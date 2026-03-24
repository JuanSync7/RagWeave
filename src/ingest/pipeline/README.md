<!-- @summary
Pipeline orchestration: public API facade and two-phase runtime lifecycle (doc_processing → CleanDocumentStore → embedding).
@end-summary -->

# ingest/pipeline

## Overview

This directory contains the pipeline orchestration layer — the public API and two-phase runtime lifecycle. It does **not** contain business logic (that lives in `doc_processing/`, `embedding/`, and `support/`).

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `__init__.py` | Public API facade (stable import surface) | `ingest_file`, `ingest_directory` |
| `impl.py` | Two-phase orchestration: Phase 1 → CleanDocumentStore → Phase 2, manifest management, skip detection | `ingest_file`, `ingest_directory` |

Note: `workflow.py` has been replaced by `src/ingest/doc_processing/workflow.py` and `src/ingest/embedding/workflow.py`.

## Import Convention

External consumers should import from `src.ingest.pipeline` (the facade), not from `pipeline.impl` directly. The facade re-exports the stable public API.
