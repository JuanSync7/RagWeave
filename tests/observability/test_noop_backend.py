# @summary
# Pytest tests for the NoopBackend observability module.
# Tests all No-op types: NoopBackend, NoopSpan, NoopTrace, NoopGeneration.
# Exports: (none — test module)
# Deps: pytest, src.platform.observability.backend, src.platform.observability.noop.backend
# @end-summary
"""Test suite for the no-op observability backend.

Tests verify that all Noop types are proper subclasses of their ABCs,
that all methods return expected types, and that all operations are
truly no-ops (accept any input, never raise exceptions).
"""
import pytest

from src.platform.observability.backend import (
    Generation,
    ObservabilityBackend,
    Span,
    Trace,
)
from src.platform.observability.noop.backend import (
    NoopBackend,
    NoopGeneration,
    NoopSpan,
    NoopTrace,
)


# ============================================================================
# Happy Path Tests
# ============================================================================


class TestNoopBackendInstantiation:
    """Test that NoopBackend can be instantiated and is correct type."""

    def test_noop_backend_instance(self):
        """NoopBackend() returns a valid NoopBackend instance."""
        backend = NoopBackend()
        assert isinstance(backend, NoopBackend)

    def test_noop_backend_is_observability_backend(self):
        """NoopBackend is a subclass of ObservabilityBackend ABC."""
        backend = NoopBackend()
        assert isinstance(backend, ObservabilityBackend)


class TestNoopBackendSpan:
    """Test NoopBackend.span() method."""

    def test_span_returns_noop_span(self):
        """NoopBackend.span(name) returns a NoopSpan instance."""
        backend = NoopBackend()
        span = backend.span("test.operation")
        assert isinstance(span, NoopSpan)

    def test_span_returns_span_abc(self):
        """NoopBackend.span(name) returns an instance of Span ABC."""
        backend = NoopBackend()
        span = backend.span("test.operation")
        assert isinstance(span, Span)

    def test_span_with_various_names(self):
        """NoopBackend.span() accepts various valid span names."""
        backend = NoopBackend()
        names = [
            "operation",
            "component.operation",
            "a.b.c.d",
            "underscore_name",
            "UPPERCASE",
            "MixedCase",
            "",
        ]
        for name in names:
            span = backend.span(name)
            assert isinstance(span, Span)

    def test_span_with_attributes(self):
        """NoopBackend.span() accepts attributes parameter."""
        backend = NoopBackend()
        attrs = {"key1": "value1", "key2": 42}
        span = backend.span("test.operation", attributes=attrs)
        assert isinstance(span, Span)

    def test_span_with_parent(self):
        """NoopBackend.span() accepts parent span."""
        backend = NoopBackend()
        parent_span = backend.span("parent")
        child_span = backend.span("child", parent=parent_span)
        assert isinstance(child_span, Span)

    def test_span_with_all_parameters(self):
        """NoopBackend.span() works with all optional parameters."""
        backend = NoopBackend()
        parent_span = backend.span("parent")
        span = backend.span(
            "test.operation",
            attributes={"attr": "value"},
            parent=parent_span,
        )
        assert isinstance(span, Span)


class TestNoopBackendTrace:
    """Test NoopBackend.trace() method."""

    def test_trace_returns_noop_trace(self):
        """NoopBackend.trace(name) returns a NoopTrace instance."""
        backend = NoopBackend()
        trace = backend.trace("test.pipeline")
        assert isinstance(trace, NoopTrace)

    def test_trace_returns_trace_abc(self):
        """NoopBackend.trace(name) returns an instance of Trace ABC."""
        backend = NoopBackend()
        trace = backend.trace("test.pipeline")
        assert isinstance(trace, Trace)

    def test_trace_with_various_names(self):
        """NoopBackend.trace() accepts various valid trace names."""
        backend = NoopBackend()
        names = [
            "pipeline",
            "pipeline.operation",
            "a.b.c",
            "underscore_name",
            "",
        ]
        for name in names:
            trace = backend.trace(name)
            assert isinstance(trace, Trace)

    def test_trace_with_metadata(self):
        """NoopBackend.trace() accepts metadata parameter."""
        backend = NoopBackend()
        metadata = {"request_id": "12345", "user": "test"}
        trace = backend.trace("test.pipeline", metadata=metadata)
        assert isinstance(trace, Trace)


class TestNoopBackendGeneration:
    """Test NoopBackend.generation() method."""

    def test_generation_returns_noop_generation(self):
        """NoopBackend.generation() returns a NoopGeneration instance."""
        backend = NoopBackend()
        gen = backend.generation("gen", "gpt-4", "prompt")
        assert isinstance(gen, NoopGeneration)

    def test_generation_returns_generation_abc(self):
        """NoopBackend.generation() returns an instance of Generation ABC."""
        backend = NoopBackend()
        gen = backend.generation("gen", "gpt-4", "prompt")
        assert isinstance(gen, Generation)

    def test_generation_with_various_models(self):
        """NoopBackend.generation() accepts various model names."""
        backend = NoopBackend()
        models = [
            "gpt-4",
            "gpt-4o",
            "claude-3-5-sonnet",
            "claude-opus",
            "llama-2",
            "",
        ]
        for model in models:
            gen = backend.generation("gen", model, "input")
            assert isinstance(gen, Generation)

    def test_generation_with_various_inputs(self):
        """NoopBackend.generation() accepts various input texts."""
        backend = NoopBackend()
        inputs = [
            "simple input",
            "multi\nline\ninput",
            "special chars: !@#$%^&*()",
            "",
            "very " * 1000 + "long input",
        ]
        for input_text in inputs:
            gen = backend.generation("gen", "model", input_text)
            assert isinstance(gen, Generation)

    def test_generation_with_metadata(self):
        """NoopBackend.generation() accepts metadata parameter."""
        backend = NoopBackend()
        metadata = {"context": "test", "version": 1}
        gen = backend.generation("gen", "model", "input", metadata=metadata)
        assert isinstance(gen, Generation)


class TestNoopBackendFlush:
    """Test NoopBackend.flush() method."""

    def test_flush_returns_none(self):
        """NoopBackend.flush() returns None without raising."""
        backend = NoopBackend()
        result = backend.flush()
        assert result is None

    def test_flush_multiple_calls(self):
        """Multiple flush() calls work without side effects."""
        backend = NoopBackend()
        backend.flush()
        backend.flush()
        backend.flush()
        # Should not raise


class TestNoopBackendShutdown:
    """Test NoopBackend.shutdown() method."""

    def test_shutdown_returns_none(self):
        """NoopBackend.shutdown() returns None without raising."""
        backend = NoopBackend()
        result = backend.shutdown()
        assert result is None

    def test_shutdown_multiple_calls(self):
        """Multiple shutdown() calls work without side effects."""
        backend = NoopBackend()
        backend.shutdown()
        backend.shutdown()
        backend.shutdown()
        # Should not raise


class TestNoopSpanMethods:
    """Test NoopSpan instance methods."""

    def test_span_set_attribute_with_string_value(self):
        """NoopSpan.set_attribute(key, str_value) returns None."""
        span = NoopSpan()
        result = span.set_attribute("key", "value")
        assert result is None

    def test_span_set_attribute_with_int_value(self):
        """NoopSpan.set_attribute(key, int_value) returns None."""
        span = NoopSpan()
        result = span.set_attribute("key", 42)
        assert result is None

    def test_span_set_attribute_with_float_value(self):
        """NoopSpan.set_attribute(key, float_value) returns None."""
        span = NoopSpan()
        result = span.set_attribute("key", 3.14)
        assert result is None

    def test_span_set_attribute_with_dict_value(self):
        """NoopSpan.set_attribute(key, dict_value) returns None."""
        span = NoopSpan()
        result = span.set_attribute("key", {"nested": True, "count": 5})
        assert result is None

    def test_span_set_attribute_with_list_value(self):
        """NoopSpan.set_attribute(key, list_value) returns None."""
        span = NoopSpan()
        result = span.set_attribute("key", [1, 2, 3])
        assert result is None

    def test_span_set_attribute_with_bool_value(self):
        """NoopSpan.set_attribute(key, bool_value) returns None."""
        span = NoopSpan()
        result = span.set_attribute("key", True)
        assert result is None

    def test_span_set_attribute_multiple_times(self):
        """NoopSpan.set_attribute() can be called multiple times."""
        span = NoopSpan()
        span.set_attribute("key1", "value1")
        span.set_attribute("key2", 42)
        span.set_attribute("key3", {"nested": True})
        # Should not raise

    def test_span_end_with_ok_status(self):
        """NoopSpan.end(status='ok') returns None."""
        span = NoopSpan()
        result = span.end(status="ok")
        assert result is None

    def test_span_end_with_error_status(self):
        """NoopSpan.end(status='error') returns None."""
        span = NoopSpan()
        result = span.end(status="error")
        assert result is None

    def test_span_end_with_error_exception(self):
        """NoopSpan.end(error=Exception) returns None."""
        span = NoopSpan()
        exc = ValueError("test error")
        result = span.end(error=exc)
        assert result is None

    def test_span_end_with_error_status_and_exception(self):
        """NoopSpan.end(status='error', error=Exception) returns None."""
        span = NoopSpan()
        exc = RuntimeError("failed")
        result = span.end(status="error", error=exc)
        assert result is None

    def test_span_end_default_parameters(self):
        """NoopSpan.end() with no parameters returns None."""
        span = NoopSpan()
        result = span.end()
        assert result is None

    def test_span_is_span_abc(self):
        """NoopSpan is an instance of Span ABC."""
        span = NoopSpan()
        assert isinstance(span, Span)


class TestNoopGenerationMethods:
    """Test NoopGeneration instance methods."""

    def test_generation_set_output_with_string(self):
        """NoopGeneration.set_output(str) returns None."""
        gen = NoopGeneration()
        result = gen.set_output("output text")
        assert result is None

    def test_generation_set_output_with_empty_string(self):
        """NoopGeneration.set_output('') returns None."""
        gen = NoopGeneration()
        result = gen.set_output("")
        assert result is None

    def test_generation_set_output_with_long_text(self):
        """NoopGeneration.set_output() accepts large output strings."""
        gen = NoopGeneration()
        large_output = "output " * 10000
        result = gen.set_output(large_output)
        assert result is None

    def test_generation_set_output_with_special_chars(self):
        """NoopGeneration.set_output() accepts special characters."""
        gen = NoopGeneration()
        result = gen.set_output("!@#$%^&*(){}[]|\\;:'\",.<>?/")
        assert result is None

    def test_generation_set_output_with_multiline(self):
        """NoopGeneration.set_output() accepts multiline text."""
        gen = NoopGeneration()
        result = gen.set_output("line1\nline2\nline3")
        assert result is None

    def test_generation_set_output_multiple_times(self):
        """NoopGeneration.set_output() can be called multiple times."""
        gen = NoopGeneration()
        gen.set_output("first output")
        gen.set_output("second output")
        gen.set_output("third output")
        # Should not raise

    def test_generation_set_token_counts_with_zero_tokens(self):
        """NoopGeneration.set_token_counts(0, 0) returns None."""
        gen = NoopGeneration()
        result = gen.set_token_counts(0, 0)
        assert result is None

    def test_generation_set_token_counts_with_typical_values(self):
        """NoopGeneration.set_token_counts(10, 20) returns None."""
        gen = NoopGeneration()
        result = gen.set_token_counts(10, 20)
        assert result is None

    def test_generation_set_token_counts_with_large_values(self):
        """NoopGeneration.set_token_counts() accepts large token counts."""
        gen = NoopGeneration()
        result = gen.set_token_counts(100000, 50000)
        assert result is None

    def test_generation_set_token_counts_multiple_times(self):
        """NoopGeneration.set_token_counts() can be called multiple times."""
        gen = NoopGeneration()
        gen.set_token_counts(10, 20)
        gen.set_token_counts(50, 100)
        gen.set_token_counts(0, 0)
        # Should not raise

    def test_generation_end_returns_none(self):
        """NoopGeneration.end() returns None."""
        gen = NoopGeneration()
        result = gen.end()
        assert result is None

    def test_generation_end_with_status(self):
        """NoopGeneration.end(status) returns None."""
        gen = NoopGeneration()
        result = gen.end(status="ok")
        assert result is None

    def test_generation_end_with_error(self):
        """NoopGeneration.end(error=Exception) returns None."""
        gen = NoopGeneration()
        result = gen.end(error=ValueError("test"))
        assert result is None

    def test_generation_is_generation_abc(self):
        """NoopGeneration is an instance of Generation ABC."""
        gen = NoopGeneration()
        assert isinstance(gen, Generation)



class TestNoopTraceMethods:
    """Test NoopTrace instance methods."""

    def test_trace_span_returns_noop_span(self):
        """NoopTrace.span(name) returns a NoopSpan instance."""
        trace = NoopTrace()
        span = trace.span("operation")
        assert isinstance(span, NoopSpan)

    def test_trace_span_returns_span_abc(self):
        """NoopTrace.span(name) returns an instance of Span ABC."""
        trace = NoopTrace()
        span = trace.span("operation")
        assert isinstance(span, Span)

    def test_trace_span_with_various_names(self):
        """NoopTrace.span() accepts various span names."""
        trace = NoopTrace()
        names = [
            "operation",
            "component.operation",
            "nested.op.name",
            "",
        ]
        for name in names:
            span = trace.span(name)
            assert isinstance(span, Span)

    def test_trace_span_with_attributes(self):
        """NoopTrace.span() accepts attributes parameter."""
        trace = NoopTrace()
        span = trace.span("operation", attributes={"key": "value"})
        assert isinstance(span, Span)

    def test_trace_span_multiple_children(self):
        """NoopTrace can create multiple child spans."""
        trace = NoopTrace()
        span1 = trace.span("op1")
        span2 = trace.span("op2")
        span3 = trace.span("op3")
        assert isinstance(span1, Span)
        assert isinstance(span2, Span)
        assert isinstance(span3, Span)

    def test_trace_generation_returns_noop_generation(self):
        """NoopTrace.generation() returns a NoopGeneration instance."""
        trace = NoopTrace()
        gen = trace.generation("gen", "model", "input")
        assert isinstance(gen, NoopGeneration)

    def test_trace_generation_returns_generation_abc(self):
        """NoopTrace.generation() returns an instance of Generation ABC."""
        trace = NoopTrace()
        gen = trace.generation("gen", "model", "input")
        assert isinstance(gen, Generation)

    def test_trace_generation_with_various_inputs(self):
        """NoopTrace.generation() accepts various inputs."""
        trace = NoopTrace()
        inputs = [
            "simple input",
            "multi\nline",
            "",
            "x" * 1000,
        ]
        for input_text in inputs:
            gen = trace.generation("gen", "model", input_text)
            assert isinstance(gen, Generation)

    def test_trace_generation_with_metadata(self):
        """NoopTrace.generation() accepts metadata parameter."""
        trace = NoopTrace()
        gen = trace.generation(
            "gen", "model", "input", metadata={"key": "value"}
        )
        assert isinstance(gen, Generation)

    def test_trace_generation_multiple_children(self):
        """NoopTrace can create multiple generations."""
        trace = NoopTrace()
        gen1 = trace.generation("gen1", "model", "input")
        gen2 = trace.generation("gen2", "model", "input")
        assert isinstance(gen1, Generation)
        assert isinstance(gen2, Generation)

    def test_trace_mixed_children(self):
        """NoopTrace can create both spans and generations."""
        trace = NoopTrace()
        span = trace.span("operation")
        gen = trace.generation("gen", "model", "input")
        assert isinstance(span, Span)
        assert isinstance(gen, Generation)

    def test_trace_is_trace_abc(self):
        """NoopTrace is an instance of Trace ABC."""
        trace = NoopTrace()
        assert isinstance(trace, Trace)


# ============================================================================
# Boundary Condition Tests
# ============================================================================


class TestNoneAndEmptyValues:
    """Test handling of None and empty values."""

    def test_span_set_attribute_with_none_value(self):
        """NoopSpan.set_attribute(key, None) never raises."""
        span = NoopSpan()
        span.set_attribute("key", None)
        # Should not raise

    def test_span_set_attribute_with_empty_string_key(self):
        """NoopSpan.set_attribute('', value) never raises."""
        span = NoopSpan()
        span.set_attribute("", "value")
        # Should not raise

    def test_span_set_attribute_with_none_key_and_value(self):
        """NoopSpan handles None in unexpected places gracefully."""
        span = NoopSpan()
        # This exercises the no-op behavior even with odd inputs
        span.set_attribute("key", None)
        # Should not raise

    def test_span_end_with_error_none(self):
        """NoopSpan.end(error=None) never raises."""
        span = NoopSpan()
        span.end(error=None)
        # Should not raise

    def test_generation_set_output_empty_string(self):
        """NoopGeneration.set_output('') never raises."""
        gen = NoopGeneration()
        gen.set_output("")
        # Should not raise

    def test_generation_set_token_counts_zero_values(self):
        """NoopGeneration.set_token_counts(0, 0) never raises."""
        gen = NoopGeneration()
        gen.set_token_counts(0, 0)
        # Should not raise


class TestABCSubclassRelationships:
    """Test that Noop types are proper ABC subclasses."""

    def test_noop_backend_is_observability_backend_subclass(self):
        """NoopBackend is a registered subclass of ObservabilityBackend."""
        assert issubclass(NoopBackend, ObservabilityBackend)

    def test_noop_span_is_span_subclass(self):
        """NoopSpan is a registered subclass of Span."""
        assert issubclass(NoopSpan, Span)

    def test_noop_generation_is_generation_subclass(self):
        """NoopGeneration is a registered subclass of Generation."""
        assert issubclass(NoopGeneration, Generation)


    def test_noop_trace_is_trace_subclass(self):
        """NoopTrace is a registered subclass of Trace."""
        assert issubclass(NoopTrace, Trace)

    def test_noop_span_implements_all_abstract_methods(self):
        """NoopSpan implements all abstract methods from Span."""
        span = NoopSpan()
        # Verify methods exist and are callable
        assert callable(span.set_attribute)
        assert callable(span.end)

    def test_noop_generation_implements_all_abstract_methods(self):
        """NoopGeneration implements all abstract methods from Generation."""
        gen = NoopGeneration()
        # Verify methods exist and are callable
        assert callable(gen.set_output)
        assert callable(gen.set_token_counts)
        assert callable(gen.end)

    def test_noop_trace_implements_all_abstract_methods(self):
        """NoopTrace implements all abstract methods from Trace."""
        trace = NoopTrace()
        # Verify methods exist and are callable
        assert callable(trace.span)
        assert callable(trace.generation)

    def test_noop_backend_implements_all_abstract_methods(self):
        """NoopBackend implements all abstract methods from ObservabilityBackend."""
        backend = NoopBackend()
        # Verify methods exist and are callable
        assert callable(backend.span)
        assert callable(backend.trace)
        assert callable(backend.generation)
        assert callable(backend.flush)
        assert callable(backend.shutdown)


class TestContextManagerProtocol:
    """Test context manager protocol inherited from ABCs."""

    def test_span_context_manager_success_path(self):
        """NoopSpan works as context manager on success."""
        span = NoopSpan()
        with span as s:
            assert s is span
            # Should not raise

    def test_span_context_manager_exception_path(self):
        """NoopSpan context manager handles exceptions."""
        span = NoopSpan()
        try:
            with span:
                raise ValueError("test error")
        except ValueError:
            pass  # Exception should propagate
        # Should not raise from span

    def test_generation_context_manager_success_path(self):
        """NoopGeneration works as context manager on success."""
        gen = NoopGeneration()
        with gen as g:
            assert g is gen
            # Should not raise

    def test_generation_context_manager_exception_path(self):
        """NoopGeneration context manager handles exceptions."""
        gen = NoopGeneration()
        try:
            with gen:
                raise RuntimeError("test")
        except RuntimeError:
            pass  # Exception should propagate
        # Should not raise from generation

    def test_trace_context_manager_success_path(self):
        """NoopTrace works as context manager on success."""
        trace = NoopTrace()
        with trace as t:
            assert t is trace
            # Should not raise

    def test_trace_context_manager_exception_path(self):
        """NoopTrace context manager handles exceptions."""
        trace = NoopTrace()
        try:
            with trace:
                raise ValueError("test")
        except ValueError:
            pass  # Exception should propagate
        # Should not raise from trace


class TestOptionalParameterHandling:
    """Test proper handling of optional parameters."""

    def test_backend_span_with_none_attributes(self):
        """NoopBackend.span(attributes=None) works."""
        backend = NoopBackend()
        span = backend.span("name", attributes=None)
        assert isinstance(span, Span)

    def test_backend_span_with_none_parent(self):
        """NoopBackend.span(parent=None) works."""
        backend = NoopBackend()
        span = backend.span("name", parent=None)
        assert isinstance(span, Span)

    def test_backend_trace_with_none_metadata(self):
        """NoopBackend.trace(metadata=None) works."""
        backend = NoopBackend()
        trace = backend.trace("name", metadata=None)
        assert isinstance(trace, Trace)

    def test_backend_generation_with_none_metadata(self):
        """NoopBackend.generation(metadata=None) works."""
        backend = NoopBackend()
        gen = backend.generation("gen", "model", "input", metadata=None)
        assert isinstance(gen, Generation)

    def test_trace_span_with_none_attributes(self):
        """NoopTrace.span(attributes=None) works."""
        trace = NoopTrace()
        span = trace.span("name", attributes=None)
        assert isinstance(span, Span)

    def test_trace_generation_with_none_metadata(self):
        """NoopTrace.generation(metadata=None) works."""
        trace = NoopTrace()
        gen = trace.generation("gen", "model", "input", metadata=None)
        assert isinstance(gen, Generation)


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegrationBackendToObjects:
    """Test complete workflows through backend to noop objects."""

    def test_full_backend_to_span_workflow(self):
        """Full workflow: backend -> span -> set_attribute -> end."""
        backend = NoopBackend()
        span = backend.span("operation")
        span.set_attribute("key1", "value1")
        span.set_attribute("key2", 42)
        span.end(status="ok")
        # Should not raise

    def test_full_backend_to_trace_workflow(self):
        """Full workflow: backend -> trace -> child_span -> set_attribute."""
        backend = NoopBackend()
        trace = backend.trace("pipeline")
        span = trace.span("operation")
        span.set_attribute("key", "value")
        span.end()
        # Should not raise

    def test_full_backend_to_generation_workflow(self):
        """Full workflow: backend -> generation -> set_output -> set_tokens -> end."""
        backend = NoopBackend()
        gen = backend.generation("gen", "model", "input")
        gen.set_output("output")
        gen.set_token_counts(10, 20)
        gen.end(status="ok")
        # Should not raise

    def test_backend_span_via_context_manager(self):
        """Backend span works with context manager."""
        backend = NoopBackend()
        with backend.span("operation") as span:
            span.set_attribute("key", "value")
        # Should not raise

    def test_backend_trace_via_context_manager(self):
        """Backend trace works with context manager."""
        backend = NoopBackend()
        with backend.trace("pipeline") as trace:
            span = trace.span("operation")
            span.end()
        # Should not raise

    def test_backend_generation_via_context_manager(self):
        """Backend generation works with context manager."""
        backend = NoopBackend()
        with backend.generation("gen", "model", "input") as gen:
            gen.set_output("output")
        # Should not raise

    def test_nested_spans_from_trace(self):
        """Create nested spans from trace."""
        backend = NoopBackend()
        trace = backend.trace("pipeline")
        span1 = trace.span("op1")
        span2 = trace.span("op2")
        span1.set_attribute("level", 1)
        span2.set_attribute("level", 2)
        span1.end()
        span2.end()
        # Should not raise

    def test_mixed_trace_children(self):
        """Trace can contain both spans and generations."""
        backend = NoopBackend()
        trace = backend.trace("pipeline")
        span = trace.span("operation")
        gen = trace.generation("gen", "model", "input")
        span.set_attribute("key", "value")
        gen.set_output("output")
        span.end()
        gen.end()
        # Should not raise

    def test_backend_flush_and_shutdown_sequence(self):
        """Backend can flush and shutdown without side effects."""
        backend = NoopBackend()
        _ = backend.span("operation")
        _ = backend.trace("pipeline")
        _ = backend.generation("gen", "model", "input")
        backend.flush()
        backend.shutdown()
        # Should not raise


class TestObjectIdentityAndIndependence:
    """Test that objects are independent and not singletons."""

    def test_multiple_backends_are_independent(self):
        """Multiple NoopBackend instances are independent."""
        backend1 = NoopBackend()
        backend2 = NoopBackend()
        assert backend1 is not backend2

    def test_multiple_spans_from_same_backend_are_independent(self):
        """Multiple spans from same backend are independent."""
        backend = NoopBackend()
        span1 = backend.span("op1")
        span2 = backend.span("op2")
        assert span1 is not span2

    def test_multiple_traces_are_independent(self):
        """Multiple traces are independent."""
        backend = NoopBackend()
        trace1 = backend.trace("p1")
        trace2 = backend.trace("p2")
        assert trace1 is not trace2

    def test_multiple_generations_are_independent(self):
        """Multiple generations are independent."""
        backend = NoopBackend()
        gen1 = backend.generation("g1", "m1", "i1")
        gen2 = backend.generation("g2", "m2", "i2")
        assert gen1 is not gen2

    def test_trace_children_are_independent(self):
        """Children from trace are independent objects."""
        trace = NoopTrace()
        span1 = trace.span("op1")
        span2 = trace.span("op2")
        assert span1 is not span2
        # Each span is a new instance
