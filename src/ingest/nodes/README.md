<!-- @summary
Node-per-file ingestion stages used by the top-level LangGraph workflow composer.
@end-summary -->

# src/ingest/nodes

## Overview
Each ingestion stage is isolated in its own file for clearer ownership, easier testing, and safer iteration.

## Stage Modules
| File | Node |
| --- | --- |
| `document_ingestion.py` | `document_ingestion` |
| `structure_detection.py` | `structure_detection` |
| `multimodal_processing.py` | `multimodal_processing` |
| `text_cleaning.py` | `text_cleaning` |
| `document_refactoring.py` | `document_refactoring` |
| `chunking.py` | `chunking` |
| `chunk_enrichment.py` | `chunk_enrichment` |
| `metadata_generation.py` | `metadata_generation` |
| `cross_reference_extraction.py` | `cross_reference_extraction` |
| `knowledge_graph_extraction.py` | `knowledge_graph_extraction` |
| `quality_validation.py` | `quality_validation` |
| `embedding_storage.py` | `embedding_storage` |
| `knowledge_graph_storage.py` | `knowledge_graph_storage` |
