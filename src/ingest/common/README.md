<!-- @summary
Shared ingestion-common contracts, state/config types, node helpers, and deterministic utilities used across nodes and pipeline modules.
@end-summary -->

# ingest/common

## Overview

This directory centralizes cross-cutting ingestion contracts, types, and helpers:

- `schemas.py`: typed schema contracts for common ingestion metadata payloads (`ManifestEntry`, `ProcessedChunk`, `SourceIdentity`).
- `utils.py`: deterministic utility helpers (manifest IO, hashing, text read fallback, JSON parsing).
- `types.py`: state/config dataclasses and typed contracts (`IngestState`, `IngestionConfig`, `Runtime`, `PIPELINE_NODE_NAMES`).
- `shared.py`: universal node helpers -- stage logging, keyword fallback, quality scoring, provenance mapping.

`parse_json_object` is sourced from `src/common/utils.py` to avoid duplicate parser
implementations across ingestion and retrieval packages while preserving the ingestion-local facade.

## Why this exists

This package keeps reusable primitives in one place so stage/node modules stay focused on
business logic while orchestration imports stable, shared contracts. `types.py` and `shared.py`
live here (rather than in `pipeline/`) because they are imported by all 13 nodes -- they are
cross-cutting contracts, not pipeline-internal details.
