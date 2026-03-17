# @summary
# Shared ingestion-common typed contracts for manifest entries, source identity, and processed chunks.
# Exports: ManifestEntry, SourceIdentity, ProcessedChunk
# Deps: typing, dataclasses
# @end-summary
"""Typed schema contracts shared by ingestion modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict


class ManifestEntry(TypedDict, total=False):
    """Canonical manifest entry persisted for each source key."""

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
    """A processed document chunk ready for embedding."""

    text: str
    metadata: dict = field(default_factory=dict)
