# @summary
# Typed contracts for the Embedding Pipeline's deduplication subsystem.
# Exports: MergeEvent, create_merge_event
# Deps: datetime
# MergeEvent.action field added (Phase 3.3): "merged", "replaced", "skipped",
#   or "override_skipped" — distinguishes normal dedup merges from per-source
#   override bypasses.
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

    Fields
    ------
    canonical_content_hash : str
        SHA-256 hex of the canonical chunk's text.
    canonical_chunk_id : str
        Weaviate UUID of the canonical chunk (empty string for override events).
    merged_source_key : str
        source_key of the document whose chunk was merged or bypassed.
    merged_section : str
        Section heading path from chunk metadata (may be empty).
    match_tier : str
        ``"exact"`` (Tier 1 SHA-256), ``"fuzzy"`` (Tier 2 MinHash), or
        ``"override"`` (per-source bypass).
    similarity_score : float
        Jaccard similarity for fuzzy matches; 1.0 for exact; 0.0 for overrides.
    canonical_replaced : bool
        True only for Tier 2 matches where the incoming chunk replaced the
        canonical (longer chunk wins rule).
    action : str
        What happened to the incoming chunk:
        ``"merged"`` — dropped, canonical updated with new source_key.
        ``"replaced"`` — dropped, canonical content replaced by incoming chunk.
        ``"skipped"`` — passed through as novel (no match found).
        ``"override_skipped"`` — passed through as independent canonical because
        the source_key is in ``dedup_override_sources``.
    timestamp : str
        ISO 8601 UTC timestamp.
    """

    canonical_content_hash: str
    canonical_chunk_id: str
    merged_source_key: str
    merged_section: str
    match_tier: str
    similarity_score: float
    canonical_replaced: bool
    action: str
    timestamp: str


def create_merge_event(
    *,
    canonical_content_hash: str,
    canonical_chunk_id: str,
    merged_source_key: str,
    merged_section: str,
    match_tier: str,
    similarity_score: float,
    canonical_replaced: bool,
    action: str = "merged",
) -> MergeEvent:
    """Construct a MergeEvent with the current ISO 8601 timestamp.

    Args:
        canonical_content_hash: SHA-256 hex of the canonical chunk.
        canonical_chunk_id: Weaviate UUID of the canonical (empty for overrides).
        merged_source_key: source_key of the incoming document.
        merged_section: Section heading path (may be empty).
        match_tier: ``"exact"``, ``"fuzzy"``, or ``"override"``.
        similarity_score: Jaccard similarity; 1.0 for exact; 0.0 for override.
        canonical_replaced: True if incoming chunk replaced canonical content.
        action: One of ``"merged"``, ``"replaced"``, ``"skipped"``,
            ``"override_skipped"``. Defaults to ``"merged"``.

    Returns:
        A fully populated MergeEvent dict.
    """
    return MergeEvent(
        canonical_content_hash=canonical_content_hash,
        canonical_chunk_id=canonical_chunk_id,
        merged_source_key=merged_source_key,
        merged_section=str(merged_section),
        match_tier=match_tier,
        similarity_score=similarity_score,
        canonical_replaced=canonical_replaced,
        action=action,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
