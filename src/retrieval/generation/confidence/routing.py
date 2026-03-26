# @summary
# Post-generation confidence routing logic implementing REQ-706.
# Exports: route_by_confidence
# Deps: src.retrieval.generation.confidence.schemas
# @end-summary
"""Post-generation confidence routing.

Implements the routing decision table from REQ-706:

  composite >= high   -> RETURN
  low <= c < high     -> RE_RETRIEVE (if retries left), else FLAG
  c < low             -> RE_RETRIEVE (if retries left), else BLOCK
"""

from __future__ import annotations

from src.retrieval.generation.confidence.schemas import PostGuardrailAction


def route_by_confidence(
    composite: float,
    retry_count: int = 0,
    high_threshold: float = 0.70,
    low_threshold: float = 0.50,
    max_retries: int = 1,
) -> PostGuardrailAction:
    """Determine routing action based on composite confidence score.

    The routing table balances answer quality against latency:
    - High confidence answers are returned immediately.
    - Medium confidence triggers one re-retrieval attempt with broader
      search parameters before falling back to FLAG.
    - Low confidence triggers one re-retrieval attempt before BLOCK.

    Args:
        composite: Composite confidence score in [0.0, 1.0].
        retry_count: Number of re-retrieval attempts already made.
        high_threshold: Score at or above which answers are returned.
            Default 0.70.
        low_threshold: Score below which answers are blocked after
            exhausting retries. Default 0.50.
        max_retries: Maximum number of re-retrieval attempts. Default 1.

    Returns:
        PostGuardrailAction indicating what to do with the answer.
    """
    # Hard safety guard: never allow unbounded retries
    if retry_count >= max(max_retries, 1):
        if composite < low_threshold:
            return PostGuardrailAction.BLOCK
        if composite < high_threshold:
            return PostGuardrailAction.FLAG
        return PostGuardrailAction.RETURN

    if composite >= high_threshold:
        return PostGuardrailAction.RETURN

    if composite >= low_threshold:
        # Medium confidence: try re-retrieval, then flag
        if retry_count < max_retries:
            return PostGuardrailAction.RE_RETRIEVE
        return PostGuardrailAction.FLAG

    # Low confidence: try re-retrieval, then block
    if retry_count < max_retries:
        return PostGuardrailAction.RE_RETRIEVE
    return PostGuardrailAction.BLOCK
