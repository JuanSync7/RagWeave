<!-- @summary
DEPRECATED — nodes/ directory contains ImportError stubs only. All nodes have been migrated to doc_processing/nodes/ and embedding/nodes/.
@end-summary -->

# src/ingest/nodes — DEPRECATED

All nodes have been migrated to the two-phase sub-packages:

- **Phase 1 nodes (1–5):** `src/ingest/doc_processing/nodes/`
- **Phase 2 nodes (6–13):** `src/ingest/embedding/nodes/`

The files in this directory now raise `ImportError` and redirect to the new locations.
