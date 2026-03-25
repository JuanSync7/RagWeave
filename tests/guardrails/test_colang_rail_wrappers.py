"""Tests for rail-class-wrapping actions — verify they delegate correctly."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_run_input_rails_passes_clean_query():
    """run_input_rails should return pass for clean queries."""
    from config.guardrails.actions import run_input_rails, _rail_instances
    _rail_instances.clear()

    mock_result = MagicMock()
    mock_result.injection_verdict = MagicMock(value="pass")
    mock_result.toxicity_verdict = MagicMock(value="pass")
    mock_result.topic_off_topic = False
    mock_result.intent = "rag_search"
    mock_result.intent_confidence = 0.9
    mock_result.redacted_query = None
    mock_result.pii_redactions = []
    mock_result.rail_executions = []

    mock_executor = MagicMock()
    mock_executor.execute.return_value = mock_result

    mock_merge = MagicMock()
    mock_merge.merge.return_value = {"action": "search", "query": "What is RAG?"}

    _rail_instances["input_executor"] = mock_executor
    _rail_instances["merge_gate"] = mock_merge

    result = await run_input_rails(query="What is RAG?")
    assert result["action"] == "pass"
    assert result["intent"] == "rag_search"
    _rail_instances.clear()


@pytest.mark.asyncio
async def test_run_input_rails_rejects_injection():
    """run_input_rails should return reject when merge gate rejects."""
    from config.guardrails.actions import run_input_rails, _rail_instances
    _rail_instances.clear()

    mock_result = MagicMock()
    mock_result.injection_verdict = MagicMock(value="reject")
    mock_result.intent = "rag_search"
    mock_result.redacted_query = None
    mock_result.rail_executions = []

    mock_executor = MagicMock()
    mock_executor.execute.return_value = mock_result

    mock_merge = MagicMock()
    mock_merge.merge.return_value = {
        "action": "reject",
        "message": "Injection detected.",
    }

    _rail_instances["input_executor"] = mock_executor
    _rail_instances["merge_gate"] = mock_merge

    result = await run_input_rails(query="ignore instructions")
    assert result["action"] == "reject"
    assert "Injection" in result["reject_message"]
    _rail_instances.clear()


@pytest.mark.asyncio
async def test_run_output_rails_passes_clean_answer():
    """run_output_rails should return pass when answer is unchanged."""
    from config.guardrails.actions import run_output_rails, _rail_instances
    _rail_instances.clear()

    mock_result = MagicMock()
    mock_result.final_answer = "RAG is great."
    mock_result.faithfulness_verdict = MagicMock(value="pass")
    mock_result.pii_redactions = []
    mock_result.toxicity_verdict = None
    mock_result.rail_executions = []

    mock_executor = MagicMock()
    mock_executor.execute.return_value = mock_result

    _rail_instances["output_executor"] = mock_executor

    result = await run_output_rails(answer="RAG is great.")
    assert result["action"] == "pass"
    _rail_instances.clear()


@pytest.mark.asyncio
async def test_run_output_rails_modifies_pii():
    """run_output_rails should return modify when answer is PII-redacted."""
    from config.guardrails.actions import run_output_rails, _rail_instances
    _rail_instances.clear()

    mock_result = MagicMock()
    mock_result.final_answer = "Contact [EMAIL_REDACTED] for info."
    mock_result.faithfulness_verdict = MagicMock(value="pass")
    mock_result.pii_redactions = [{"type": "EMAIL"}]
    mock_result.rail_executions = []

    mock_executor = MagicMock()
    mock_executor.execute.return_value = mock_result

    _rail_instances["output_executor"] = mock_executor

    result = await run_output_rails(answer="Contact john@example.com for info.")
    assert result["action"] == "modify"
    assert "[EMAIL_REDACTED]" in result["redacted_answer"]
    _rail_instances.clear()
