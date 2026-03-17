# @summary
# Ingestion common package: shared schemas, utilities, state/config types, and node helpers.
# Exports: ManifestEntry, SourceIdentity, ProcessedChunk, IngestState, IngestionConfig, Runtime,
#          PIPELINE_NODE_NAMES, append_processing_log, sha256_path, load_manifest, save_manifest
# Deps: src.ingest.common.schemas, src.ingest.common.utils, src.ingest.common.types, src.ingest.common.shared
# @end-summary
"""Common ingestion contracts, types, and utility exports."""

from src.ingest.common.schemas import ManifestEntry, ProcessedChunk, SourceIdentity
from src.ingest.common.utils import (
    load_manifest,
    parse_json_object,
    read_text_with_fallbacks,
    save_manifest,
    sha256_path,
)
from src.ingest.common.types import (
    IngestionConfig,
    IngestionDesignCheck,
    IngestionRunSummary,
    IngestState,
    PIPELINE_NODE_NAMES,
    Runtime,
)
from src.ingest.common.shared import (
    append_processing_log,
    map_chunk_provenance,
    _extract_keywords_fallback,
    _cross_refs,
    _quality_score,
)

__all__ = [
    "ManifestEntry",
    "ProcessedChunk",
    "SourceIdentity",
    "sha256_path",
    "load_manifest",
    "save_manifest",
    "read_text_with_fallbacks",
    "parse_json_object",
    "IngestionConfig",
    "IngestionDesignCheck",
    "IngestionRunSummary",
    "IngestState",
    "PIPELINE_NODE_NAMES",
    "Runtime",
    "append_processing_log",
    "map_chunk_provenance",
    "_extract_keywords_fallback",
    "_cross_refs",
    "_quality_score",
]
