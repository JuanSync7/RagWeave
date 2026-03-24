# @summary
# Document Processing Pipeline — Phase 1 of the two-phase ingestion pipeline.
# Exports: run_document_processing
# Deps: src.ingest.doc_processing.impl
# @end-summary

"""Document Processing Pipeline — Phase 1 of the two-phase ingestion pipeline."""

from src.ingest.doc_processing.impl import run_document_processing

__all__ = ["run_document_processing"]
