"""Tests for src/platform/observability/backend.py.

Covers ABC enforcement, context manager protocol for Span/Generation/Trace,
start_span() deprecation delegation, and the Tracer backward-compat alias.
"""
import warnings
from unittest.mock import MagicMock, call

import pytest

from src.platform.observability.backend import (
    Generation,
    ObservabilityBackend,
    Span,
    Trace,
    Tracer,
)

# ---------------------------------------------------------------------------
# Test doubles — minimal concrete implementations used throughout this module
# ---------------------------------------------------------------------------


class ConcreteSpan(Span):
    """Concrete Span that records every call to set_attribute and end."""

    def __init__(self):
        self.set_attribute_calls: list[tuple[str, object]] = []
        self.end_calls: list[dict] = []

    def set_attribute(self, key: str, value: object) -> None:
        self.set_attribute_calls.append((key, value))

    def end(self, status: str = "ok", error=None) -> None:
        self.end_calls.append({"status": status, "error": error})


class ConcreteGeneration(Generation):
    """Concrete Generation that records every call to its abstract methods."""

    def __init__(self):
        self.set_output_calls: list[str] = []
        self.set_token_calls: list[tuple[int, int]] = []
        self.end_calls: list[dict] = []

    def set_output(self, output: str) -> None:
        self.set_output_calls.append(output)

    def set_token_counts(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.set_token_calls.append((prompt_tokens, completion_tokens))

    def end(self, status: str = "ok", error=None) -> None:
        self.end_calls.append({"status": status, "error": error})


class ConcreteTrace(Trace):
    """Concrete Trace that vends ConcreteSpan / ConcreteGeneration instances."""

    def span(self, name: str, attributes=None) -> Span:
        return ConcreteSpan()

    def generation(self, name: str, model: str, input: str, metadata=None) -> Generation:
        return ConcreteGeneration()


class ConcreteBackend(ObservabilityBackend):
    """Concrete ObservabilityBackend with all five abstract methods implemented."""

    def span(self, name: str, attributes=None, parent=None) -> Span:
        return ConcreteSpan()

    def trace(self, name: str, metadata=None) -> Trace:
        return ConcreteTrace()

    def generation(self, name: str, model: str, input: str, metadata=None) -> Generation:
        return ConcreteGeneration()

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Spy backend — lets us record span() calls while still returning a real Span
# ---------------------------------------------------------------------------


class SpyBackend(ConcreteBackend):
    """ConcreteBackend whose span() method is a spy."""

    def __init__(self):
        self.span_calls: list[dict] = []
        self._span_return = ConcreteSpan()

    def span(self, name: str, attributes=None, parent=None) -> Span:
        self.span_calls.append({"name": name, "attributes": attributes, "parent": parent})
        return self._span_return


# =============================================================================
# Happy path tests
# =============================================================================


class TestSpanContextManagerHappyPath:
    """Span context manager — no-exception path."""

    def test_enter_returns_self(self):
        span = ConcreteSpan()
        result = span.__enter__()
        assert result is span

    def test_no_exception_calls_end_ok(self):
        span = ConcreteSpan()
        with span as s:
            assert s is span
        assert len(span.end_calls) == 1
        assert span.end_calls[0] == {"status": "ok", "error": None}

    def test_no_exception_exit_returns_false(self):
        span = ConcreteSpan()
        result = span.__exit__(None, None, None)
        assert result is False


class TestSpanContextManagerWithException:
    """Span context manager — exception path."""

    def test_exception_calls_end_error(self):
        span = ConcreteSpan()
        exc = ValueError("boom")
        with pytest.raises(ValueError, match="boom"):
            with span:
                raise exc
        assert len(span.end_calls) == 1
        assert span.end_calls[0]["status"] == "error"
        assert span.end_calls[0]["error"] is exc

    def test_exception_is_reraised(self):
        span = ConcreteSpan()
        with pytest.raises(RuntimeError):
            with span:
                raise RuntimeError("reraise-me")

    def test_exception_exit_returns_false(self):
        span = ConcreteSpan()
        exc = ValueError("x")
        result = span.__exit__(ValueError, exc, None)
        assert result is False


class TestGenerationContextManagerHappyPath:
    """Generation context manager — no-exception path."""

    def test_enter_returns_self(self):
        gen = ConcreteGeneration()
        result = gen.__enter__()
        assert result is gen

    def test_no_exception_calls_end_ok(self):
        gen = ConcreteGeneration()
        with gen:
            pass
        assert len(gen.end_calls) == 1
        assert gen.end_calls[0] == {"status": "ok", "error": None}


class TestGenerationContextManagerWithException:
    """Generation context manager — exception path."""

    def test_exception_calls_end_error(self):
        gen = ConcreteGeneration()
        exc = RuntimeError("llm-fail")
        with pytest.raises(RuntimeError):
            with gen:
                raise exc
        assert gen.end_calls[0]["status"] == "error"
        assert gen.end_calls[0]["error"] is exc

    def test_exception_is_reraised(self):
        gen = ConcreteGeneration()
        with pytest.raises(KeyError):
            with gen:
                raise KeyError("reraise")


class TestTraceContextManager:
    """Trace context manager behaviour."""

    def test_enter_returns_self(self):
        trace = ConcreteTrace()
        result = trace.__enter__()
        assert result is trace

    def test_no_exception_no_error(self):
        trace = ConcreteTrace()
        with trace as t:
            assert t is trace  # no exception raised

    def test_exit_returns_false_no_exception(self):
        trace = ConcreteTrace()
        result = trace.__exit__(None, None, None)
        assert result is False

    def test_exit_returns_false_with_exception(self):
        trace = ConcreteTrace()
        exc = ValueError("trace-exc")
        result = trace.__exit__(ValueError, exc, None)
        assert result is False


class TestStartSpanDelegation:
    """start_span() emits DeprecationWarning and delegates to span()."""

    def test_emits_deprecation_warning(self):
        backend = SpyBackend()
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            backend.start_span("my-span")
        assert len(captured) == 1
        assert issubclass(captured[0].category, DeprecationWarning)
        assert "start_span" in str(captured[0].message)

    def test_delegates_to_span_and_returns_result(self):
        backend = SpyBackend()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = backend.start_span("my-span")
        assert result is backend._span_return
        assert len(backend.span_calls) == 1
        assert backend.span_calls[0]["name"] == "my-span"


class TestTracerAlias:
    """Tracer is a backward-compat alias for ObservabilityBackend."""

    def test_tracer_is_observability_backend(self):
        assert Tracer is ObservabilityBackend


# =============================================================================
# Error scenario tests
# =============================================================================


class TestObservabilityBackendABCEnforcement:
    """Instantiating ObservabilityBackend or incomplete subclasses raises TypeError."""

    def test_cannot_instantiate_abstract_base_directly(self):
        with pytest.raises(TypeError):
            ObservabilityBackend()

    def test_missing_span_raises_type_error(self):
        class MissingSpan(ObservabilityBackend):
            def trace(self, name, metadata=None):
                return ConcreteTrace()

            def generation(self, name, model, input, metadata=None):
                return ConcreteGeneration()

            def flush(self):
                pass

            def shutdown(self):
                pass

        with pytest.raises(TypeError):
            MissingSpan()

    def test_missing_trace_raises_type_error(self):
        class MissingTrace(ObservabilityBackend):
            def span(self, name, attributes=None, parent=None):
                return ConcreteSpan()

            def generation(self, name, model, input, metadata=None):
                return ConcreteGeneration()

            def flush(self):
                pass

            def shutdown(self):
                pass

        with pytest.raises(TypeError):
            MissingTrace()

    def test_missing_generation_raises_type_error(self):
        class MissingGeneration(ObservabilityBackend):
            def span(self, name, attributes=None, parent=None):
                return ConcreteSpan()

            def trace(self, name, metadata=None):
                return ConcreteTrace()

            def flush(self):
                pass

            def shutdown(self):
                pass

        with pytest.raises(TypeError):
            MissingGeneration()

    def test_missing_flush_raises_type_error(self):
        class MissingFlush(ObservabilityBackend):
            def span(self, name, attributes=None, parent=None):
                return ConcreteSpan()

            def trace(self, name, metadata=None):
                return ConcreteTrace()

            def generation(self, name, model, input, metadata=None):
                return ConcreteGeneration()

            def shutdown(self):
                pass

        with pytest.raises(TypeError):
            MissingFlush()

    def test_missing_shutdown_raises_type_error(self):
        class MissingShutdown(ObservabilityBackend):
            def span(self, name, attributes=None, parent=None):
                return ConcreteSpan()

            def trace(self, name, metadata=None):
                return ConcreteTrace()

            def generation(self, name, model, input, metadata=None):
                return ConcreteGeneration()

            def flush(self):
                pass

        with pytest.raises(TypeError):
            MissingShutdown()


class TestSpanABCEnforcement:
    """Span ABC enforcement."""

    def test_cannot_instantiate_span_directly(self):
        with pytest.raises(TypeError):
            Span()

    def test_missing_set_attribute_raises_type_error(self):
        class MissingSetAttribute(Span):
            def end(self, status="ok", error=None):
                pass

        with pytest.raises(TypeError):
            MissingSetAttribute()

    def test_missing_end_raises_type_error(self):
        class MissingEnd(Span):
            def set_attribute(self, key, value):
                pass

        with pytest.raises(TypeError):
            MissingEnd()


class TestGenerationABCEnforcement:
    """Generation ABC enforcement."""

    def test_cannot_instantiate_generation_directly(self):
        with pytest.raises(TypeError):
            Generation()


class TestTraceABCEnforcement:
    """Trace ABC enforcement."""

    def test_cannot_instantiate_trace_directly(self):
        with pytest.raises(TypeError):
            Trace()


# =============================================================================
# Boundary condition tests
# =============================================================================


class TestSpanExitReturnValue:
    """Span.__exit__ must always return False (never suppress exceptions)."""

    def test_returns_false_with_no_exception(self):
        span = ConcreteSpan()
        assert span.__exit__(None, None, None) is False

    def test_returns_false_with_exception(self):
        span = ConcreteSpan()
        exc = Exception("boundary")
        assert span.__exit__(Exception, exc, None) is False


class TestGenerationExitReturnValue:
    """Generation.__exit__ must always return False."""

    def test_returns_false_with_no_exception(self):
        gen = ConcreteGeneration()
        assert gen.__exit__(None, None, None) is False

    def test_returns_false_with_exception(self):
        gen = ConcreteGeneration()
        exc = RuntimeError("gen-boundary")
        assert gen.__exit__(RuntimeError, exc, None) is False


class TestStartSpanBoundaryConditions:
    """start_span() boundary conditions around arguments."""

    def test_parent_none_emits_deprecation_no_error(self):
        backend = SpyBackend()
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            result = backend.start_span("op", parent=None)
        assert any(issubclass(w.category, DeprecationWarning) for w in captured)
        assert result is backend._span_return

    def test_attributes_dict_passed_through_to_span(self):
        backend = SpyBackend()
        attrs = {"env": "test", "version": 42}
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            backend.start_span("op", attributes=attrs)
        assert backend.span_calls[0]["attributes"] == attrs

    def test_warning_message_mentions_span(self):
        backend = SpyBackend()
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            backend.start_span("op")
        msg = str(captured[0].message)
        assert "span()" in msg


# =============================================================================
# Known gaps
# =============================================================================
# - Tracer alias itself does NOT emit a DeprecationWarning on use; the warning
#   is only raised inside start_span(). Asserting `Tracer is ObservabilityBackend`
#   is the correct and only verifiable contract for the alias.
