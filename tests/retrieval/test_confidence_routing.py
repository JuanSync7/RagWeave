"""Unit tests for confidence routing logic (REQ-706)."""

import pytest

from src.retrieval.generation.confidence.routing import route_by_confidence
from src.retrieval.generation.confidence.schemas import PostGuardrailAction


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
