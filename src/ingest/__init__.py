# @summary
# Ingestion package public API: entrypoints and typed contracts for file and directory ingestion.
# Exports: ingest_file, ingest_directory, IngestionConfig, IngestFileResult, IngestionRunSummary
# Deps: src.ingest.impl, src.ingest.common.types
# @end-summary

"""Public API for the ingestion subsystem.

This package provides high-level entrypoints for ingesting files or directories
into the system's knowledge stores (e.g., embeddings and optional derived
artifacts). The package exports a small, stable surface so callers do not depend
on internal node implementations.
"""

from src.ingest.common import (
    IngestFileResult,
    IngestionConfig,
    IngestionDesignCheck,
    IngestionRunSummary,
    Runtime,
)
from src.ingest.impl import ingest_directory, ingest_file, verify_core_design

__all__ = [
    "IngestionConfig",
    "IngestionDesignCheck",
    "IngestFileResult",
    "IngestionRunSummary",
    "Runtime",
    "ingest_directory",
    "ingest_file",
    "verify_core_design",
]
