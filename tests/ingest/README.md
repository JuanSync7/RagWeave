<!-- @summary
Ingestion-focused tests covering pipeline schema, helper behavior, and incremental idempotency.
@end-summary -->

# tests/ingest

## Overview
This directory contains tests specific to ingestion and embedding workflows.

## Files
| File | Purpose |
| --- | --- |
| `test_pipeline_schema.py` | Verifies pipeline helper behavior, node list, and design checks. |
| `test_idempotency_incremental.py` | Verifies ingestion manifest IO and idempotent chunk ID behavior. |
