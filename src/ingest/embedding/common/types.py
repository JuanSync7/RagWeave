# @summary
# Typed contracts for the Embedding Pipeline's deduplication subsystem.
# Exports: MergeEvent, create_merge_event
# Deps: datetime
# @end-summary
"""Typed contracts for the cross-document deduplication subsystem.

This module defines the MergeEvent TypedDict and its factory function.
Both are referenced by the dedup node and surfaced in the pipeline merge report.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TypedDict


class MergeEvent(TypedDict):
    """A single deduplication merge event record.

    Conforms to FR-3440 schema. No full chunk text is included (SC-3510).
    """

    canonical_content_hash: str  # SHA-256 hex of canonical chunk
    canonical_chunk_id: str  # Weaviate UUID
    merged_source_key: str  # source_key of the merged document
    merged_section: str  # section path from chunk metadata
    match_tier: str  # "exact" or "fuzzy"
    similarity_score: float  # 1.0 for exact, Jaccard estimate for fuzzy
    canonical_replaced: bool  # true if canonical was replaced (Tier 2)
    timestamp: str  # ISO 8601


def create_merge_event(
    *,
    canonical_content_hash: str,
    canonical_chunk_id: str,
    merged_source_key: str,
    merged_section: str,
    match_tier: str,
    similarity_score: float,
    canonical_replaced: bool,
) -> MergeEvent:
    """Construct a MergeEvent with the current ISO 8601 timestamp."""
    return MergeEvent(
        canonical_content_hash=canonical_content_hash,
        canonical_chunk_id=canonical_chunk_id,
        merged_source_key=merged_source_key,
        merged_section=str(merged_section),
        match_tier=match_tier,
        similarity_score=similarity_score,
        canonical_replaced=canonical_replaced,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
