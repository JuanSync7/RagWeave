# @summary
# Embedding Pipeline — Phase 2 of the two-phase ingestion pipeline.
# Exports: run_embedding_pipeline
# Deps: src.ingest.embedding.impl
# @end-summary

"""Embedding Pipeline — Phase 2 of the two-phase ingestion pipeline."""

from src.ingest.embedding.impl import run_embedding_pipeline

__all__ = ["run_embedding_pipeline"]
