# @summary
# Public ingestion pipeline exports; delegates implementation to pipeline_impl.
# @end-summary

"""Public ingestion pipeline API facade.

This package provides a stable import surface for pipeline entrypoints and
types, delegating orchestration and implementation details to `impl`.
"""

from src.ingest.pipeline.impl import (
    PIPELINE_NODE_NAMES,
    IngestionConfig,
    IngestionDesignCheck,
    IngestionRunSummary,
    Runtime,
    ingest_directory,
    ingest_file,
    verify_core_design,
)

__all__ = [
    "PIPELINE_NODE_NAMES",
    "IngestionConfig",
    "IngestionDesignCheck",
    "IngestionRunSummary",
    "Runtime",
    "ingest_directory",
    "ingest_file",
    "verify_core_design",
]
