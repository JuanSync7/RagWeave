import pytest
from pydantic import ValidationError

from server.schemas import QueryRequest


def test_query_request_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        QueryRequest(query="hello", unexpected=True)


def test_query_request_rejects_unknown_stage_budget_key():
    with pytest.raises(ValidationError):
        QueryRequest(
            query="hello",
            stage_budget_overrides={"unknown_stage": 1000},
        )


def test_query_request_accepts_valid_stage_budget_overrides():
    req = QueryRequest(
        query="hello",
        stage_budget_overrides={
            "query_processing": 1200,
            "hybrid_search": 900,
        },
    )
    assert req.stage_budget_overrides["query_processing"] == 1200


def test_query_request_accepts_memory_fields():
    req = QueryRequest(
        query="follow-up question",
        conversation_id="conv_123abc",
        memory_enabled=True,
        memory_turn_window=8,
        compact_now=False,
    )
    assert req.conversation_id == "conv_123abc"
    assert req.memory_enabled is True
    assert req.memory_turn_window == 8


def test_query_request_missing_required_field_raises():
    """A QueryRequest without the required `query` field raises ValidationError."""
    with pytest.raises(ValidationError):
        QueryRequest()  # type: ignore[call-arg]


def test_query_request_out_of_range_alpha_raises():
    """alpha must be between 0.0 and 1.0 inclusive."""
    with pytest.raises(ValidationError):
        QueryRequest(query="hello", alpha=2.5)


def test_query_request_out_of_range_search_limit_raises():
    """search_limit must be between 1 and 100."""
    with pytest.raises(ValidationError):
        QueryRequest(query="hello", search_limit=0)

    with pytest.raises(ValidationError):
        QueryRequest(query="hello", search_limit=101)


def test_query_request_out_of_range_rerank_top_k_raises():
    """rerank_top_k must be between 1 and 50."""
    with pytest.raises(ValidationError):
        QueryRequest(query="hello", rerank_top_k=0)

    with pytest.raises(ValidationError):
        QueryRequest(query="hello", rerank_top_k=51)


def test_query_request_valid_minimal():
    """A QueryRequest with only the required field should be accepted."""
    req = QueryRequest(query="what is RAG?")
    assert req.query == "what is RAG?"
    assert req.alpha == 0.5
    assert req.search_limit == 10
