<!-- @summary
Pipeline orchestration: public API facade, runtime lifecycle, and LangGraph workflow composition.
@end-summary -->

# ingest/pipeline

## Overview

This directory contains the pipeline orchestration layer -- the public API, runtime lifecycle management, and LangGraph graph topology. It does **not** contain business logic (that lives in `nodes/` and `support/`).

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `__init__.py` | Public API facade (stable import surface) | `IngestionConfig`, `ingest_directory`, `ingest_file`, `verify_core_design` |
| `impl.py` | Runtime orchestration: startup checks, directory ingestion loop, manifest management, vector store operations | `ingest_directory`, `ingest_file`, `verify_core_design` |
| `workflow.py` | LangGraph `StateGraph` composition wiring all 13 nodes with conditional transitions | `build_graph` |

## Import Convention

External consumers should import from `src.ingest.pipeline` (the facade), not from `pipeline.impl` directly. The facade re-exports the stable public API.
