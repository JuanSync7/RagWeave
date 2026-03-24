<!-- @summary
Cross-domain shared utilities used by multiple src feature packages.
@end-summary -->

# src/common

## Overview

This directory contains deterministic helpers that are reused across multiple
feature domains in `src/` (for example both `ingest/` and `retrieval/`).

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `utils.py` | Cross-domain utility helpers for JSON parsing and query hashing | `parse_json_object`, `make_query_hash` |

## Rules

- Keep helpers pure and side-effect-light.
- Put only truly cross-domain code here.
- Domain-specific contracts/helpers still belong in local `common/` packages
  (for example `src/ingest/common/`, `src/retrieval/common/`), then can
  re-export cross-domain helpers through local facades when needed.
