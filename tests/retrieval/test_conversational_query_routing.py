"""Tests for conversational query routing: backward-reference detection,
context-reset detection, and query result schema extensions."""

import pytest

from src.retrieval.query.schemas import QueryResult, QueryAction, QueryState
from src.retrieval.query.nodes.query_processor import (
    _has_backward_reference,
    _detect_suppress_memory,
)


class TestBackwardReferenceDetection:
    """Tests for _has_backward_reference() — REQ-1103."""

    def test_backward_ref_the_above(self):
        """Explicit 'the above' marker triggers backward-reference detection."""
        assert _has_backward_reference("Tell me more about the above") is True

    def test_backward_ref_you_said(self):
        """'you said' marker triggers backward-reference detection."""
        assert _has_backward_reference("Based on what you said earlier") is True

    def test_backward_ref_elaborate(self):
        """'elaborate' marker triggers backward-reference detection."""
        assert _has_backward_reference("Can you elaborate on that?") is True

    def test_backward_ref_previously(self):
        """'previously' marker triggers backward-reference detection."""
        assert _has_backward_reference("As previously discussed") is True

    def test_backward_ref_tell_me_more(self):
        """Standalone 'tell me more' triggers backward-reference detection."""
        assert _has_backward_reference("Tell me more") is True

    def test_no_backward_ref_clean_query(self):
        """A specific technical query with no backward-reference markers returns False."""
        assert _has_backward_reference("What is the SPI timing spec?") is False

    def test_no_backward_ref_specific(self):
        """A specific technical query with no markers or pronoun density returns False."""
        assert _has_backward_reference("What is the USB clock frequency?") is False

    def test_backward_ref_case_insensitive(self):
        """Backward-reference detection is case-insensitive."""
        assert _has_backward_reference("TELL ME MORE") is True

    def test_backward_ref_pronoun_density(self):
        """High pronoun density triggers backward-reference detection.

        'What about it and its tolerance?' has 6 words and 2 pronouns
        ('it', 'its'), giving density 2/6 ≈ 0.33 which exceeds the 0.15 threshold.
        """
        assert _has_backward_reference("What about it and its tolerance?") is True

    def test_no_backward_ref_low_pronoun_density(self):
        """Low pronoun density with specific nouns does not trigger detection.

        'What about the USB clock frequency for the main board?' has 10 words
        and 0 pronouns, giving density 0.0 which is below the 0.15 threshold.
        """
        assert _has_backward_reference(
            "What about the USB clock frequency for the main board?"
        ) is False


class TestContextResetDetection:
    """Tests for _detect_suppress_memory() — REQ-1105."""

    def test_suppress_forget_past_conversation(self):
        """'Forget about past conversation' triggers context-reset detection."""
        assert _detect_suppress_memory(
            "Forget about past conversation, what is X?"
        ) is True

    def test_suppress_ignore_previous(self):
        """'Ignore previous' triggers context-reset detection."""
        assert _detect_suppress_memory("Ignore previous, tell me about Y") is True

    def test_suppress_new_topic(self):
        """'New topic' triggers context-reset detection."""
        assert _detect_suppress_memory("New topic, what is Z?") is True

    def test_suppress_start_fresh(self):
        """'Start fresh' triggers context-reset detection."""
        assert _detect_suppress_memory("Start fresh, what about timing?") is True

    def test_suppress_fresh_start(self):
        """'Fresh start' triggers context-reset detection."""
        assert _detect_suppress_memory("Fresh start please") is True

    def test_no_suppress_normal_query(self):
        """A normal technical query does not trigger context-reset detection."""
        assert _detect_suppress_memory("What is the timing spec?") is False

    def test_suppress_case_insensitive(self):
        """Context-reset detection is case-insensitive."""
        assert _detect_suppress_memory("FORGET ABOUT PAST CONVO") is True


class TestQueryResultSchema:
    """Tests for QueryResult schema defaults and field access."""

    def test_query_result_defaults(self):
        """Required fields are accepted and optional fields default correctly."""
        result = QueryResult(
            processed_query="test",
            confidence=0.8,
            action=QueryAction.SEARCH,
        )
        assert result.standalone_query == ""
        assert result.suppress_memory is False
        assert result.has_backward_reference is False

    def test_query_result_all_fields(self):
        """All fields can be set and are accessible with correct values."""
        result = QueryResult(
            processed_query="SPI clock frequency",
            confidence=0.95,
            action=QueryAction.SEARCH,
            standalone_query="What is the SPI clock frequency?",
            suppress_memory=True,
            has_backward_reference=False,
            clarification_message=None,
            iterations=2,
        )
        assert result.processed_query == "SPI clock frequency"
        assert result.confidence == 0.95
        assert result.action == QueryAction.SEARCH
        assert result.standalone_query == "What is the SPI clock frequency?"
        assert result.suppress_memory is True
        assert result.has_backward_reference is False
        assert result.clarification_message is None
        assert result.iterations == 2

    def test_query_result_backward_compat(self):
        """Construction without the new conversational fields still works."""
        result = QueryResult(
            processed_query="USB timing",
            confidence=0.75,
            action=QueryAction.ASK_USER,
            clarification_message="Could you provide more detail?",
            iterations=3,
        )
        assert result.processed_query == "USB timing"
        assert result.action == QueryAction.ASK_USER
        assert result.clarification_message == "Could you provide more detail?"
        assert result.iterations == 3
        # New conversational fields are still present with defaults
        assert result.standalone_query == ""
        assert result.suppress_memory is False
        assert result.has_backward_reference is False
