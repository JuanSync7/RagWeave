# @summary
# Ingestion package exports for document processing and LangGraph pipeline entrypoints.
# Exports: ingest_directory, ingest_file, IngestionConfig, IngestionRunSummary
# Deps: src.ingest.pipeline.impl, src.ingest.common.types
# @end-summary

"""Public API for the ingestion subsystem.

This package provides high-level entrypoints for ingesting files or directories
into the system's knowledge stores (e.g., embeddings and optional derived
artifacts). The package exports a small, stable surface so callers do not depend
on internal node implementations.
"""

from src.ingest.common.types import IngestionConfig, IngestionRunSummary
from src.ingest.pipeline.impl import ingest_directory, ingest_file

__all__ = [
    "IngestionConfig",
    "IngestionRunSummary",
    "ingest_directory",
    "ingest_file",
]
