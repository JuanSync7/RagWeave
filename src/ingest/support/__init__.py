# @summary
# Node support libraries: document parsing (Docling), vision/VLM enrichment,
# LLM helpers, and text processing primitives.
# Deps: src.ingest.support.docling, src.ingest.support.vision, src.ingest.support.llm,
#       src.ingest.support.document, src.ingest.support.markdown
# @end-summary
"""Support libraries for specialized ingestion processing.

This package contains optional helpers used by ingestion pipeline nodes, such as:

- Document parsing via Docling (when enabled)
- Vision/VLM extraction for figures and images (when enabled)
- LLM helpers for metadata enrichment (when enabled)
- Text normalization and markdown-aware chunking utilities
"""
