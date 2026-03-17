# @summary
# Shared ingestion-common typed contracts for manifest entries, source identity, and processed chunks.
# Exports: ManifestEntry, SourceIdentity, ProcessedChunk
# Deps: typing, dataclasses
# @end-summary
"""Shared schema contracts for ingestion.

This module defines lightweight, stable contracts that are used across the
ingestion pipeline to represent:

- The persisted ingestion manifest entries (per source key)
- Source discovery identity payloads
- Processed text chunks ready for embedding/storage
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict


class ManifestEntry(TypedDict, total=False):
    """Canonical manifest entry persisted for each source key.

    The manifest is the primary mechanism for supporting idempotent and
    incremental ingestion across runs.

    Keys are optional to allow partial persistence and forward-compatible
    extensions.
    """

    source: str
    source_uri: str
    source_id: str
    source_key: str
    connector: str
    source_version: str
    content_hash: str
    chunk_count: int
    summary: str
    keywords: list[str]
    processing_log: list[str]
    mirror_stem: str
    legacy_name: str


class SourceIdentity(TypedDict):
    """Stable identity payload used during source discovery and processing."""

    source_path: str
    source_name: str
    source_uri: str
    source_id: str
    source_key: str
    connector: str
    source_version: str


@dataclass
class ProcessedChunk:
    """A processed document chunk ready for embedding.

    Attributes:
        text: Normalized chunk text suitable for embedding.
        metadata: Arbitrary metadata for retrieval attribution (e.g., source
            path, page number, headings).
    """

    text: str
    metadata: dict = field(default_factory=dict)
