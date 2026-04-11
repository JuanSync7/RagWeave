"""Tests for the guardrails dispatcher (__init__.py)."""
import importlib
import sys
from unittest.mock import patch, MagicMock

import pytest

from src.guardrails.common.schemas import InputRailResult, OutputRailResult


def _reset_dispatcher():
    """Reset the dispatcher's cached backend singleton between tests."""
    import src.guardrails as grd
    grd._guardrail_backend = None


# ---------------------------------------------------------------------------
# NoOp backend (GUARDRAIL_BACKEND="" or "none")
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend_value", ["", "none"])
def test_noop_backend_run_input_rails(backend_value):
    _reset_dispatcher()
    with patch("config.settings.GUARDRAIL_BACKEND", backend_value):
        from src.guardrails import run_input_rails
        result = run_input_rails("hello world")
        assert isinstance(result, InputRailResult)
    _reset_dispatcher()


@pytest.mark.parametrize("backend_value", ["", "none"])
def test_noop_backend_run_output_rails(backend_value):
    _reset_dispatcher()
    with patch("config.settings.GUARDRAIL_BACKEND", backend_value):
        from src.guardrails import run_output_rails
        result = run_output_rails("the answer", ["chunk1"])
        assert isinstance(result, OutputRailResult)
        assert result.final_answer == "the answer"
    _reset_dispatcher()


@pytest.mark.parametrize("backend_value", ["", "none"])
def test_noop_backend_redact_pii_passthrough(backend_value):
    _reset_dispatcher()
    with patch("config.settings.GUARDRAIL_BACKEND", backend_value):
        from src.guardrails import redact_pii
        text = "call me at 555-123-4567"
        redacted, detections = redact_pii(text)
        assert redacted == text
        assert detections == []
    _reset_dispatcher()


@pytest.mark.parametrize("backend_value", ["", "none"])
def test_noop_backend_register_rag_chain_noop(backend_value):
    _reset_dispatcher()
    with patch("config.settings.GUARDRAIL_BACKEND", backend_value):
        from src.guardrails import register_rag_chain
        register_rag_chain(object())  # should not raise
    _reset_dispatcher()


# ---------------------------------------------------------------------------
# Unknown backend raises ValueError
# ---------------------------------------------------------------------------


def test_unknown_backend_raises():
    _reset_dispatcher()
    with patch("config.settings.GUARDRAIL_BACKEND", "unknown_backend"):
        with pytest.raises(ValueError, match="Unknown GUARDRAIL_BACKEND"):
            from src.guardrails import run_input_rails
            run_input_rails("query")
    _reset_dispatcher()


# ---------------------------------------------------------------------------
# RailMergeGate re-export
# ---------------------------------------------------------------------------


def test_rail_merge_gate_re_exported():
    from src.guardrails import RailMergeGate
    assert RailMergeGate is not None
    gate = RailMergeGate()
    assert hasattr(gate, "merge")
