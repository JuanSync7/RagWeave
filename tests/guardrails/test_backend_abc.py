"""Tests for GuardrailBackend ABC contract enforcement."""
import pytest
from src.guardrails.backend import GuardrailBackend
from src.guardrails.common.schemas import InputRailResult, OutputRailResult


class _FullBackend(GuardrailBackend):
    """Minimal concrete backend that satisfies all abstract methods."""

    def run_input_rails(self, query, tenant_id=""):
        return InputRailResult()

    def run_output_rails(self, answer, context_chunks):
        return OutputRailResult(final_answer=answer)

    def redact_pii(self, text):
        return text, []


class _MissingRunOutputRails(GuardrailBackend):
    def run_input_rails(self, query, tenant_id=""):
        return InputRailResult()

    def redact_pii(self, text):
        return text, []


class _MissingRedactPii(GuardrailBackend):
    def run_input_rails(self, query, tenant_id=""):
        return InputRailResult()

    def run_output_rails(self, answer, context_chunks):
        return OutputRailResult(final_answer=answer)


def test_full_backend_instantiates():
    backend = _FullBackend()
    assert isinstance(backend, GuardrailBackend)


def test_missing_run_output_rails_raises():
    with pytest.raises(TypeError):
        _MissingRunOutputRails()


def test_missing_redact_pii_raises():
    with pytest.raises(TypeError):
        _MissingRedactPii()


def test_register_rag_chain_is_noop_by_default():
    backend = _FullBackend()
    # Should not raise
    backend.register_rag_chain(object())


def test_run_input_rails_returns_input_rail_result():
    backend = _FullBackend()
    result = backend.run_input_rails("test query")
    assert isinstance(result, InputRailResult)


def test_run_output_rails_returns_output_rail_result():
    backend = _FullBackend()
    result = backend.run_output_rails("answer", ["chunk1"])
    assert isinstance(result, OutputRailResult)


def test_redact_pii_returns_tuple():
    backend = _FullBackend()
    redacted, detections = backend.redact_pii("hello world")
    assert isinstance(redacted, str)
    assert isinstance(detections, list)
