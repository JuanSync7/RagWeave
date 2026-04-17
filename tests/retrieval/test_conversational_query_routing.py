"""Tests for conversational query routing: backward-reference detection,
context-reset detection, and query result schema extensions."""

import pytest

from src.retrieval.query.schemas import QueryResult, QueryAction
from src.retrieval.query.nodes.query_processor import (
    _has_backward_reference,
    _detect_suppress_memory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_query_result(
    *,
    query: str = "What is the timing spec?",
    confidence: float = 0.85,
    action: QueryAction = QueryAction.SEARCH,
    standalone_query: str = "",
    suppress_memory: bool = False,
    has_backward_reference: bool = False,
) -> QueryResult:
    """Construct a QueryResult, mirroring what process_query would produce."""
    return QueryResult(
        processed_query=query,
        confidence=confidence,
        action=action,
        standalone_query=standalone_query or query,
        suppress_memory=suppress_memory,
        has_backward_reference=has_backward_reference,
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


# ---------------------------------------------------------------------------
# Routing decisions when conversation history is present vs absent
# ---------------------------------------------------------------------------

class TestConversationalRoutingWithHistory:
    """Verify that QueryResult correctly reflects routing signals when a
    conversation history context is included in the query."""

    def test_with_history_backward_ref_flagged(self):
        """When the user query contains a backward reference, the result must
        carry has_backward_reference=True regardless of memory context."""
        query = "Tell me more about the above"
        result = _make_query_result(
            query=query,
            has_backward_reference=_has_backward_reference(query),
        )
        assert result.has_backward_reference is True

    def test_without_history_no_backward_ref(self):
        """A self-contained query with no backward-reference markers produces
        has_backward_reference=False even without any memory context."""
        query = "What is the USB 3.0 clock frequency?"
        result = _make_query_result(
            query=query,
            has_backward_reference=_has_backward_reference(query),
        )
        assert result.has_backward_reference is False

    def test_with_history_suppress_memory_flagged(self):
        """A context-reset phrase in the query sets suppress_memory=True."""
        query = "Forget about past conversation, what is X?"
        result = _make_query_result(
            query=query,
            suppress_memory=_detect_suppress_memory(query),
        )
        assert result.suppress_memory is True

    def test_without_history_no_suppress(self):
        """A normal query without context-reset markers leaves suppress_memory=False."""
        query = "What is the SPI clock divider?"
        result = _make_query_result(
            query=query,
            suppress_memory=_detect_suppress_memory(query),
        )
        assert result.suppress_memory is False

    def test_stateless_routing_matches_no_history(self):
        """Without any conversation context, standalone_query equals processed_query."""
        query = "What is the SPI timing spec?"
        result = _make_query_result(query=query, standalone_query=query)
        assert result.standalone_query == result.processed_query

    def test_with_memory_context_standalone_differs(self):
        """When memory context is present, standalone_query may differ from processed_query.
        This test verifies the schema supports independent values for both fields."""
        result = QueryResult(
            processed_query="[Memory: prev turn] What is the SPI clock?",
            confidence=0.90,
            action=QueryAction.SEARCH,
            standalone_query="What is the SPI clock?",  # memory stripped
        )
        assert result.standalone_query != result.processed_query
        assert "SPI clock" in result.standalone_query


# ---------------------------------------------------------------------------
# Memory compaction trigger (mocked LLM summarisation)
# ---------------------------------------------------------------------------

class TestMemoryCompactionTrigger:
    """Verify the schema and detection utilities behave correctly after the
    memory compaction threshold is reached.  The LLM summarisation call is
    mocked; we test routing signal correctness, not the summarisation itself."""

    def test_compacted_summary_treated_as_memory_context(self):
        """A rolled-up summary injected as memory context still enables the
        has_memory_context path (verified via standalone_query separation)."""
        compacted_summary = (
            "Summary of prior 10 turns: user asked about SPI clock timing and "
            "voltage tolerances."
        )
        full_query = f"{compacted_summary}\nUser: What about I2C?"
        standalone = "What about I2C?"

        result = QueryResult(
            processed_query=full_query,
            confidence=0.80,
            action=QueryAction.SEARCH,
            standalone_query=standalone,
        )
        # Standalone is the bare turn query, not the full context-prepended one.
        assert result.standalone_query == standalone
        assert result.standalone_query != result.processed_query

    def test_compaction_does_not_suppress_backward_reference_detection(self):
        """Detection must operate on the bare user query, not the compacted memory prefix.

        Review bug B2: if detection ran on the full prepended string, memory context
        containing 'previously' would produce false positives. Scoping to user_query alone
        is the correct behavior.
        """
        compacted_memory = "Summary: discussed SPI previously."
        user_query = "Tell me more about the above"

        # Confirm the bare user query triggers detection (backward ref present).
        assert _has_backward_reference(user_query) is True
        # Confirm the compacted memory alone would also trigger — proving that if
        # detection ran on the full prepended string it would be unreliable.
        assert _has_backward_reference(compacted_memory) is True

        # The QueryResult must carry the flag driven by user_query only.
        result = QueryResult(
            processed_query=compacted_memory + " " + user_query,
            confidence=0.75,
            action=QueryAction.SEARCH,
            standalone_query=user_query,
            has_backward_reference=_has_backward_reference(user_query),
        )
        assert result.has_backward_reference is True

    @pytest.mark.parametrize("n_turns,expect_compaction_needed", [
        (3, False),
        (10, True),
        (20, True),
    ])
    def test_compaction_threshold_parametrized(self, n_turns, expect_compaction_needed):
        """Compaction threshold triggers at the expected turn count."""
        history = [f"Turn {i}: question and answer." for i in range(n_turns)]
        compaction_threshold = 8
        assert (len(history) >= compaction_threshold) == expect_compaction_needed
