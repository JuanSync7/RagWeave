# @summary
# Public ingestion pipeline exports; delegates implementation to impl.
# Exports: ingest_file, ingest_directory
# Deps: src.ingest.pipeline.impl
# @end-summary

"""Public ingestion pipeline API facade.

This package provides a stable import surface for pipeline entrypoints,
delegating orchestration and implementation details to `impl`.
"""

from src.ingest.pipeline.impl import ingest_file, ingest_directory

__all__ = ["ingest_file", "ingest_directory"]
