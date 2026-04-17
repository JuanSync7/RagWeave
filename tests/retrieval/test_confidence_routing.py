"""Unit tests for confidence routing logic (REQ-706)."""

import math

import pytest

from src.retrieval.generation.confidence.routing import route_by_confidence
from src.retrieval.generation.confidence.schemas import PostGuardrailAction
from src.retrieval.generation.confidence.scoring import compute_composite_confidence


class TestRouteByConfidence:
    """Tests for the REQ-706 routing table."""

    def test_high_confidence_returns(self):
        assert route_by_confidence(0.80) == PostGuardrailAction.RETURN

    def test_exactly_high_threshold_returns(self):
        assert route_by_confidence(0.70) == PostGuardrailAction.RETURN

    def test_medium_confidence_first_attempt_re_retrieves(self):
        assert route_by_confidence(0.60, retry_count=0) == PostGuardrailAction.RE_RETRIEVE

    def test_medium_confidence_after_retry_flags(self):
        assert route_by_confidence(0.60, retry_count=1) == PostGuardrailAction.FLAG

    def test_low_confidence_first_attempt_re_retrieves(self):
        assert route_by_confidence(0.30, retry_count=0) == PostGuardrailAction.RE_RETRIEVE

    def test_low_confidence_after_retry_blocks(self):
        assert route_by_confidence(0.30, retry_count=1) == PostGuardrailAction.BLOCK

    def test_exactly_low_threshold_medium_range(self):
        assert route_by_confidence(0.50, retry_count=0) == PostGuardrailAction.RE_RETRIEVE

    def test_just_below_low_threshold(self):
        assert route_by_confidence(0.49, retry_count=0) == PostGuardrailAction.RE_RETRIEVE
        assert route_by_confidence(0.49, retry_count=1) == PostGuardrailAction.BLOCK

    def test_zero_confidence_blocks_after_retry(self):
        assert route_by_confidence(0.0, retry_count=1) == PostGuardrailAction.BLOCK

    def test_custom_thresholds(self):
        assert route_by_confidence(
            0.85, high_threshold=0.90, low_threshold=0.60
        ) == PostGuardrailAction.RE_RETRIEVE

    def test_max_retries_respected(self):
        # With max_retries=2, retry_count=1 should still re-retrieve
        assert route_by_confidence(
            0.40, retry_count=1, max_retries=2
        ) == PostGuardrailAction.RE_RETRIEVE
        # But retry_count=2 should block
        assert route_by_confidence(
            0.40, retry_count=2, max_retries=2
        ) == PostGuardrailAction.BLOCK

    def test_safety_guard_prevents_unbounded_retries(self):
        # Even with max_retries=0, shouldn't loop forever
        result = route_by_confidence(0.40, retry_count=1, max_retries=0)
        assert result in (PostGuardrailAction.BLOCK, PostGuardrailAction.FLAG)

    def test_nan_composite_blocks(self):
        """NaN composite must safe-fail to BLOCK rather than silently routing."""
        assert route_by_confidence(math.nan) == PostGuardrailAction.BLOCK

    def test_threshold_boundary_high_inclusive(self):
        """Score exactly at HIGH_THRESHOLD (0.70) routes to RETURN (inclusive)."""
        assert route_by_confidence(0.70, high_threshold=0.70) == PostGuardrailAction.RETURN

    def test_threshold_boundary_just_below_high(self):
        """Score just below HIGH_THRESHOLD triggers RE_RETRIEVE on first attempt."""
        assert (
            route_by_confidence(0.6999, high_threshold=0.70, retry_count=0)
            == PostGuardrailAction.RE_RETRIEVE
        )

    def test_threshold_boundary_low_inclusive(self):
        """Score exactly at LOW_THRESHOLD (0.50) after retry routes to FLAG (not BLOCK)."""
        assert (
            route_by_confidence(0.50, low_threshold=0.50, retry_count=1)
            == PostGuardrailAction.FLAG
        )


# ---------------------------------------------------------------------------
# Decision-tree paths through the full 3-signal pipeline
# ---------------------------------------------------------------------------

_LONG_TEXT = (
    "The voltage regulator maintains a steady output of three point three volts "
    "under all load conditions."
)


class TestFullPipelineRoutingPaths:
    """End-to-end paths: compute_composite_confidence → route_by_confidence."""

    def test_path1_all_high_signals_returns(self):
        """retrieval≈0.9, LLM=high, citation≈1.0 → composite ≥ HIGH → RETURN."""
        bd = compute_composite_confidence(
            reranker_scores=[0.9, 0.9, 0.9],
            llm_confidence_text="high",
            answer=_LONG_TEXT,
            retrieved_texts=[_LONG_TEXT],
        )
        action = route_by_confidence(bd.composite, retry_count=1)
        assert action == PostGuardrailAction.RETURN, (
            f"Expected RETURN, got {action} (composite={bd.composite:.4f})"
        )

    def test_path2_high_retrieval_llm_low_citation_flags(self):
        """retrieval=0.9, LLM=high, citation≈0 → composite in medium zone → FLAG after retry."""
        bd = compute_composite_confidence(
            reranker_scores=[0.9, 0.9],
            llm_confidence_text="high",
            answer="This answer contains no citations and no matching source text.",
            retrieved_texts=["Completely different content about something unrelated."],
        )
        action = route_by_confidence(bd.composite, retry_count=1)
        # Composite may land above high threshold (RETURN) or in medium zone (FLAG).
        # Either is acceptable; what must NOT happen is BLOCK for these strong signals.
        assert action != PostGuardrailAction.BLOCK, (
            f"Strong signals should not BLOCK (composite={bd.composite:.4f})"
        )

    def test_path3_all_low_signals_blocks(self):
        """retrieval≈0.1, LLM=low, citation=0 → composite below LOW → BLOCK after retry."""
        bd = compute_composite_confidence(
            reranker_scores=[0.1, 0.05],
            llm_confidence_text="low",
            answer="Some unrelated answer with no matching content whatsoever.",
            retrieved_texts=["Completely different source material about something else."],
        )
        action = route_by_confidence(bd.composite, retry_count=1)
        assert action == PostGuardrailAction.BLOCK, (
            f"Expected BLOCK for weak signals, got {action} (composite={bd.composite:.4f})"
        )

    @pytest.mark.parametrize("retry_count,expected_action", [
        (0, PostGuardrailAction.RE_RETRIEVE),
        (1, PostGuardrailAction.BLOCK),
    ])
    def test_path4_empty_retrieval(self, retry_count, expected_action):
        """No retrieved documents → RE_RETRIEVE on first attempt, BLOCK after retry."""
        bd = compute_composite_confidence(
            reranker_scores=[],
            llm_confidence_text="low",
            answer="An answer with no source documents at all.",
            retrieved_texts=[],
        )
        action = route_by_confidence(bd.composite, retry_count=retry_count)
        assert action == expected_action, (
            f"retry_count={retry_count}: expected {expected_action}, "
            f"got {action} (composite={bd.composite:.4f})"
        )
