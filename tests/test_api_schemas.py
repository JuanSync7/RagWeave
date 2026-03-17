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
