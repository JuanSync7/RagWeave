"""Tests for LangfuseBackend and its companion wrapper classes.

Coverage areas:
    - Happy path: all backend and wrapper methods route to the SDK correctly.
    - Error scenarios / fail-open: SDK exceptions are swallowed and noop objects returned
      (except flush() and shutdown() which propagate).
    - Boundary conditions: None attributes, None values, warning log emission.
    - ABC conformance: all concrete classes satisfy their abstract-base contracts.
"""
from __future__ import annotations

import logging
import sys
import types
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Inject a fake 'langfuse' package into sys.modules so that the local import
# inside LangfuseBackend.__init__ resolves without the real SDK being installed.
# This must happen BEFORE importing anything from src.platform.observability.langfuse.
# ---------------------------------------------------------------------------

def _make_fake_langfuse_module():
    """Return a minimal fake langfuse module with a get_client stub."""
    mod = types.ModuleType("langfuse")
    mod.get_client = MagicMock()
    return mod


if "langfuse" not in sys.modules:
    sys.modules["langfuse"] = _make_fake_langfuse_module()


from src.platform.observability.langfuse.backend import (  # noqa: E402
    LangfuseBackend,
    LangfuseSpan,
    LangfuseTrace,
    LangfuseGeneration,
)
from src.platform.observability.noop.backend import NoopSpan, NoopTrace, NoopGeneration
from src.platform.observability.backend import ObservabilityBackend, Span, Trace, Generation


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_langfuse_client():
    """Patch get_client on the fake langfuse module injected into sys.modules.

    Because LangfuseBackend.__init__ uses a local import
    ``from langfuse import get_client``, the call resolves through the
    ``langfuse`` entry in sys.modules at runtime.  Patching
    ``langfuse.get_client`` on that injected module intercepts correctly.
    """
    with patch("langfuse.get_client") as mock_get:
        client = MagicMock()
        mock_get.return_value = client
        yield client


@pytest.fixture
def backend(mock_langfuse_client):
    """Construct a LangfuseBackend with the SDK fully mocked."""
    return LangfuseBackend()


@pytest.fixture
def mock_inner():
    """A generic mock for a Langfuse SDK observation object."""
    return MagicMock()


# ===========================================================================
# --- Happy path tests ---
# ===========================================================================

class TestLangfuseBackendHappyPath:
    """Backend-level happy-path: SDK calls succeed, typed wrappers are returned."""

    def test_span_returns_langfuse_span(self, backend, mock_langfuse_client):
        """backend.span() returns a LangfuseSpan instance (Span ABC subtype)."""
        obs = MagicMock()
        mock_langfuse_client.start_observation.return_value = obs

        result = backend.span("my.op")

        assert isinstance(result, LangfuseSpan)
        assert isinstance(result, Span)
        mock_langfuse_client.start_observation.assert_called_once_with(
            as_type="span", name="my.op", metadata={}
        )

    def test_trace_returns_langfuse_trace(self, backend, mock_langfuse_client):
        """backend.trace() returns a LangfuseTrace instance (Trace ABC subtype)."""
        trace_obj = MagicMock()
        mock_langfuse_client.trace.return_value = trace_obj

        result = backend.trace("pipeline.run")

        assert isinstance(result, LangfuseTrace)
        assert isinstance(result, Trace)
        mock_langfuse_client.trace.assert_called_once_with(
            name="pipeline.run", metadata={}
        )

    def test_generation_returns_langfuse_generation(self, backend, mock_langfuse_client):
        """backend.generation() returns a LangfuseGeneration instance (Generation ABC subtype)."""
        gen_obs = MagicMock()
        mock_langfuse_client.start_observation.return_value = gen_obs

        result = backend.generation("llm.call", "gpt-4", "hello")

        assert isinstance(result, LangfuseGeneration)
        assert isinstance(result, Generation)
        mock_langfuse_client.start_observation.assert_called_once_with(
            as_type="generation",
            name="llm.call",
            model="gpt-4",
            input="hello",
            metadata={},
        )

    def test_flush_calls_client_flush(self, backend, mock_langfuse_client):
        """backend.flush() delegates directly to client.flush()."""
        backend.flush()
        mock_langfuse_client.flush.assert_called_once_with()

    def test_shutdown_calls_client_shutdown(self, backend, mock_langfuse_client):
        """backend.shutdown() delegates directly to client.shutdown()."""
        backend.shutdown()
        mock_langfuse_client.shutdown.assert_called_once_with()

    def test_backend_is_observability_backend_subtype(self, backend):
        """LangfuseBackend satisfies the ObservabilityBackend ABC."""
        assert isinstance(backend, ObservabilityBackend)


class TestLangfuseSpanHappyPath:
    """LangfuseSpan wrapper happy-path tests."""

    def test_set_attribute_calls_inner_update(self, mock_inner):
        """set_attribute forwards to inner.update(metadata={key: value})."""
        span = LangfuseSpan(mock_inner)
        span.set_attribute("k", "v")
        mock_inner.update.assert_called_once_with(metadata={"k": "v"})

    def test_end_ok_calls_inner_end(self, mock_inner):
        """end(status='ok') calls inner.end() without updating level."""
        span = LangfuseSpan(mock_inner)
        span.end(status="ok")
        mock_inner.end.assert_called_once_with()
        mock_inner.update.assert_not_called()

    def test_end_with_error_calls_update_then_end(self, mock_inner):
        """end(status='error', error=...) updates level then ends."""
        span = LangfuseSpan(mock_inner)
        err = ValueError("something broke")
        span.end(status="error", error=err)
        mock_inner.update.assert_called_once_with(
            level="ERROR", status_message=str(err)
        )
        mock_inner.end.assert_called_once_with()

    def test_set_attribute_none_value_calls_inner_update(self, mock_inner):
        """set_attribute accepts None values and still calls inner.update."""
        span = LangfuseSpan(mock_inner)
        span.set_attribute("nullable_key", None)
        mock_inner.update.assert_called_once_with(metadata={"nullable_key": None})


class TestLangfuseGenerationHappyPath:
    """LangfuseGeneration wrapper happy-path tests."""

    def test_set_output_calls_inner_update(self, mock_inner):
        """set_output forwards to inner.update(output=output)."""
        gen = LangfuseGeneration(mock_inner)
        gen.set_output("answer text")
        mock_inner.update.assert_called_once_with(output="answer text")

    def test_set_token_counts_calls_inner_update_with_usage_dict(self, mock_inner):
        """set_token_counts calls inner.update with usage dict keyed 'input'/'output'."""
        gen = LangfuseGeneration(mock_inner)
        gen.set_token_counts(10, 20)
        mock_inner.update.assert_called_once_with(usage={"input": 10, "output": 20})


class TestLangfuseTraceHappyPath:
    """LangfuseTrace wrapper happy-path tests."""

    def test_trace_span_returns_langfuse_span(self):
        """LangfuseTrace.span() returns a LangfuseSpan wrapping the child obs."""
        trace_obj = MagicMock()
        child_obs = MagicMock()
        trace_obj.span.return_value = child_obs

        lt = LangfuseTrace(trace_obj)
        result = lt.span("child.op")

        assert isinstance(result, LangfuseSpan)
        trace_obj.span.assert_called_once_with(name="child.op", metadata={})

    def test_trace_generation_returns_langfuse_generation(self):
        """LangfuseTrace.generation() returns a LangfuseGeneration wrapping the child obs."""
        trace_obj = MagicMock()
        child_obs = MagicMock()
        trace_obj.generation.return_value = child_obs

        lt = LangfuseTrace(trace_obj)
        result = lt.generation("llm.call", "gpt-4", "prompt text")

        assert isinstance(result, LangfuseGeneration)
        trace_obj.generation.assert_called_once_with(
            name="llm.call", model="gpt-4", input="prompt text", metadata={}
        )

    def test_trace_span_passes_attributes(self):
        """LangfuseTrace.span() passes attributes dict as metadata."""
        trace_obj = MagicMock()
        trace_obj.span.return_value = MagicMock()

        lt = LangfuseTrace(trace_obj)
        lt.span("op", attributes={"env": "prod"})

        trace_obj.span.assert_called_once_with(name="op", metadata={"env": "prod"})


# ===========================================================================
# --- Error scenarios / fail-open tests ---
# ===========================================================================

class TestLangfuseBackendFailOpen:
    """Backend-level fail-open: SDK raises, noop objects are returned, no exception to caller."""

    def test_span_sdk_raises_returns_noop_span(self, backend, mock_langfuse_client, caplog):
        """span() returns NoopSpan and logs warning when SDK raises."""
        mock_langfuse_client.start_observation.side_effect = RuntimeError("sdk dead")

        with caplog.at_level(logging.WARNING, logger="rag.observability.langfuse"):
            result = backend.span("failing.op")

        assert isinstance(result, NoopSpan)
        assert any("LangfuseBackend.span failed" in r.message for r in caplog.records)

    def test_trace_sdk_raises_returns_noop_trace(self, backend, mock_langfuse_client, caplog):
        """trace() returns NoopTrace and logs warning when SDK raises."""
        mock_langfuse_client.trace.side_effect = ConnectionError("no server")

        with caplog.at_level(logging.WARNING, logger="rag.observability.langfuse"):
            result = backend.trace("failing.trace")

        assert isinstance(result, NoopTrace)
        assert any("LangfuseBackend.trace failed" in r.message for r in caplog.records)

    def test_generation_sdk_raises_returns_noop_generation(
        self, backend, mock_langfuse_client, caplog
    ):
        """generation() returns NoopGeneration and logs warning when SDK raises."""
        mock_langfuse_client.start_observation.side_effect = ValueError("bad model")

        with caplog.at_level(logging.WARNING, logger="rag.observability.langfuse"):
            result = backend.generation("llm.call", "gpt-4", "prompt")

        assert isinstance(result, NoopGeneration)
        assert any("LangfuseBackend.generation failed" in r.message for r in caplog.records)

    def test_flush_propagates_exception(self, backend, mock_langfuse_client):
        """flush() does NOT catch SDK exceptions — they propagate to caller."""
        mock_langfuse_client.flush.side_effect = TimeoutError("flush timeout")

        with pytest.raises(TimeoutError, match="flush timeout"):
            backend.flush()

    def test_shutdown_propagates_exception(self, backend, mock_langfuse_client):
        """shutdown() does NOT catch SDK exceptions — they propagate to caller."""
        mock_langfuse_client.shutdown.side_effect = OSError("shutdown failed")

        with pytest.raises(OSError, match="shutdown failed"):
            backend.shutdown()


class TestLangfuseSpanFailOpen:
    """LangfuseSpan wrapper fail-open tests."""

    def test_set_attribute_inner_raises_no_exception_to_caller(self, mock_inner, caplog):
        """set_attribute swallows inner.update exceptions and logs a warning."""
        mock_inner.update.side_effect = RuntimeError("update exploded")
        span = LangfuseSpan(mock_inner)

        with caplog.at_level(logging.WARNING, logger="rag.observability.langfuse"):
            result = span.set_attribute("key", "val")

        assert result is None
        assert any("LangfuseSpan.set_attribute failed" in r.message for r in caplog.records)

    def test_end_inner_raises_no_exception_to_caller(self, mock_inner, caplog):
        """end() swallows inner.end exceptions and logs a warning."""
        mock_inner.end.side_effect = RuntimeError("end exploded")
        span = LangfuseSpan(mock_inner)

        with caplog.at_level(logging.WARNING, logger="rag.observability.langfuse"):
            result = span.end(status="ok")

        assert result is None
        assert any("LangfuseSpan.end failed" in r.message for r in caplog.records)

    def test_end_with_error_inner_update_raises_no_exception_to_caller(
        self, mock_inner, caplog
    ):
        """end() with error swallows inner.update exception and logs a warning."""
        mock_inner.update.side_effect = RuntimeError("update exploded")
        span = LangfuseSpan(mock_inner)

        with caplog.at_level(logging.WARNING, logger="rag.observability.langfuse"):
            result = span.end(status="error", error=ValueError("upstream"))

        assert result is None
        assert any("LangfuseSpan.end failed" in r.message for r in caplog.records)


class TestLangfuseGenerationFailOpen:
    """LangfuseGeneration wrapper fail-open tests."""

    def test_set_output_inner_raises_is_swallowed(self, mock_inner, caplog):
        """set_output swallows inner.update exceptions and logs a warning."""
        mock_inner.update.side_effect = RuntimeError("out of space")
        gen = LangfuseGeneration(mock_inner)

        with caplog.at_level(logging.WARNING, logger="rag.observability.langfuse"):
            result = gen.set_output("answer")

        assert result is None
        assert any("LangfuseGeneration.set_output failed" in r.message for r in caplog.records)

    def test_set_token_counts_inner_raises_is_swallowed(self, mock_inner, caplog):
        """set_token_counts swallows inner.update exceptions and logs a warning."""
        mock_inner.update.side_effect = RuntimeError("token error")
        gen = LangfuseGeneration(mock_inner)

        with caplog.at_level(logging.WARNING, logger="rag.observability.langfuse"):
            result = gen.set_token_counts(5, 10)

        assert result is None
        assert any(
            "LangfuseGeneration.set_token_counts failed" in r.message for r in caplog.records
        )


class TestLangfuseTraceFailOpen:
    """LangfuseTrace wrapper fail-open tests."""

    def test_trace_span_raises_returns_noop_span(self, caplog):
        """LangfuseTrace.span() returns NoopSpan and logs warning when SDK raises."""
        trace_obj = MagicMock()
        trace_obj.span.side_effect = RuntimeError("trace span failed")
        lt = LangfuseTrace(trace_obj)

        with caplog.at_level(logging.WARNING, logger="rag.observability.langfuse"):
            result = lt.span("op.name")

        assert isinstance(result, NoopSpan)
        assert any("LangfuseTrace.span failed" in r.message for r in caplog.records)

    def test_trace_generation_raises_returns_noop_generation(self, caplog):
        """LangfuseTrace.generation() returns NoopGeneration and logs warning when SDK raises."""
        trace_obj = MagicMock()
        trace_obj.generation.side_effect = RuntimeError("gen failed")
        lt = LangfuseTrace(trace_obj)

        with caplog.at_level(logging.WARNING, logger="rag.observability.langfuse"):
            result = lt.generation("gen.name", "gpt-4", "prompt")

        assert isinstance(result, NoopGeneration)
        assert any("LangfuseTrace.generation failed" in r.message for r in caplog.records)


class TestLangfuseBackendInitFailOpen:
    """LangfuseBackend.__init__ propagates get_client() exceptions (factory handles fallback)."""

    def test_init_propagates_get_client_exception(self):
        """Exception from get_client() during __init__ propagates to the caller."""
        with patch("langfuse.get_client") as mock_get:
            mock_get.side_effect = RuntimeError("bad credentials")
            with pytest.raises(RuntimeError, match="bad credentials"):
                LangfuseBackend()


# ===========================================================================
# --- Boundary condition tests ---
# ===========================================================================

class TestBoundaryConditions:
    """Edge cases around None arguments, empty dicts, and exception propagation contracts."""

    def test_span_none_attributes_passes_empty_dict_to_sdk(
        self, backend, mock_langfuse_client
    ):
        """span(name, attributes=None) passes metadata={} to the SDK."""
        mock_langfuse_client.start_observation.return_value = MagicMock()
        backend.span("op", attributes=None)
        mock_langfuse_client.start_observation.assert_called_once_with(
            as_type="span", name="op", metadata={}
        )

    def test_span_with_dict_attributes_passes_dict_to_sdk(
        self, backend, mock_langfuse_client
    ):
        """span(name, attributes={...}) passes the dict verbatim to the SDK."""
        mock_langfuse_client.start_observation.return_value = MagicMock()
        attrs = {"env": "staging", "version": "1.2"}
        backend.span("op", attributes=attrs)
        mock_langfuse_client.start_observation.assert_called_once_with(
            as_type="span", name="op", metadata=attrs
        )

    def test_trace_none_metadata_passes_empty_dict_to_sdk(
        self, backend, mock_langfuse_client
    ):
        """trace(name, metadata=None) passes metadata={} to the SDK."""
        mock_langfuse_client.trace.return_value = MagicMock()
        backend.trace("pipeline.run", metadata=None)
        mock_langfuse_client.trace.assert_called_once_with(
            name="pipeline.run", metadata={}
        )

    def test_generation_none_metadata_passes_empty_dict_to_sdk(
        self, backend, mock_langfuse_client
    ):
        """generation() with metadata=None passes metadata={} to the SDK."""
        mock_langfuse_client.start_observation.return_value = MagicMock()
        backend.generation("llm.call", "gpt-4", "prompt", metadata=None)
        mock_langfuse_client.start_observation.assert_called_once_with(
            as_type="generation",
            name="llm.call",
            model="gpt-4",
            input="prompt",
            metadata={},
        )

    def test_flush_does_not_catch_exceptions(self, backend, mock_langfuse_client):
        """Verify flush() propagation: no try/except wraps the SDK call."""
        mock_langfuse_client.flush.side_effect = Exception("network error")
        with pytest.raises(Exception, match="network error"):
            backend.flush()

    def test_shutdown_does_not_catch_exceptions(self, backend, mock_langfuse_client):
        """Verify shutdown() propagation: no try/except wraps the SDK call."""
        mock_langfuse_client.shutdown.side_effect = Exception("conn reset")
        with pytest.raises(Exception, match="conn reset"):
            backend.shutdown()

    def test_set_attribute_none_value_does_not_raise(self, mock_inner):
        """set_attribute with None value is accepted without raising."""
        span = LangfuseSpan(mock_inner)
        span.set_attribute("nullable", None)  # Must not raise
        mock_inner.update.assert_called_once_with(metadata={"nullable": None})

    def test_warning_logged_for_span_fail_open(self, backend, mock_langfuse_client, caplog):
        """Warning is logged (not raised) when span() fail-open path is triggered."""
        mock_langfuse_client.start_observation.side_effect = RuntimeError("oops")

        with caplog.at_level(logging.WARNING, logger="rag.observability.langfuse"):
            backend.span("op")

        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_messages) >= 1
        assert any("LangfuseBackend.span failed" in msg for msg in warning_messages)

    def test_warning_logged_for_langfuse_span_set_attribute_fail_open(
        self, mock_inner, caplog
    ):
        """Warning is logged (not raised) for LangfuseSpan.set_attribute fail-open."""
        mock_inner.update.side_effect = RuntimeError("inner error")
        span = LangfuseSpan(mock_inner)

        with caplog.at_level(logging.WARNING, logger="rag.observability.langfuse"):
            span.set_attribute("key", "val")

        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("LangfuseSpan.set_attribute failed" in msg for msg in warning_messages)

    def test_token_counts_usage_dict_structure(self, mock_inner):
        """Token counts usage dict uses 'input' and 'output' keys specifically."""
        gen = LangfuseGeneration(mock_inner)
        gen.set_token_counts(prompt_tokens=100, completion_tokens=50)
        _, kwargs = mock_inner.update.call_args
        usage = kwargs["usage"]
        assert "input" in usage
        assert "output" in usage
        assert usage["input"] == 100
        assert usage["output"] == 50


# ===========================================================================
# --- ABC conformance tests ---
# ===========================================================================

class TestABCConformance:
    """Verify all concrete classes satisfy their abstract-base contracts."""

    def test_langfuse_backend_is_observability_backend(self, backend):
        assert isinstance(backend, ObservabilityBackend)

    def test_langfuse_span_is_span(self, mock_inner):
        assert isinstance(LangfuseSpan(mock_inner), Span)

    def test_langfuse_trace_is_trace(self):
        assert isinstance(LangfuseTrace(MagicMock()), Trace)

    def test_langfuse_generation_is_generation(self, mock_inner):
        assert isinstance(LangfuseGeneration(mock_inner), Generation)


# ===========================================================================
# --- Context manager protocol tests ---
# ===========================================================================

class TestContextManagerProtocol:
    """Context manager __enter__/__exit__ is inherited from the ABC — verify it works."""

    def test_langfuse_span_context_manager_ok(self, mock_inner):
        """LangfuseSpan can be used as a context manager; end() is called on exit."""
        span = LangfuseSpan(mock_inner)
        with span:
            pass
        mock_inner.end.assert_called_once_with()

    def test_langfuse_span_context_manager_with_exception(self, mock_inner):
        """LangfuseSpan context manager calls end(status='error', error=...) on exception."""
        span = LangfuseSpan(mock_inner)
        exc = ValueError("upstream failure")
        try:
            with span:
                raise exc
        except ValueError:
            pass
        mock_inner.update.assert_called_once_with(
            level="ERROR", status_message=str(exc)
        )
        mock_inner.end.assert_called_once_with()

    def test_langfuse_generation_context_manager_ok(self, mock_inner):
        """LangfuseGeneration can be used as a context manager; end() is called on exit."""
        gen = LangfuseGeneration(mock_inner)
        with gen:
            pass
        mock_inner.end.assert_called_once_with()


# ===========================================================================
# --- Known gaps ---
# ===========================================================================

# KNOWN GAP: Langfuse SDK token field naming may differ ("input" vs "prompt_tokens").
#   Tests above verify dict structure only (keys "input"/"output") — not SDK's internal
#   field mapping. If the SDK renames fields, update set_token_counts and these tests.
#
# KNOWN GAP: Async dispatch (Langfuse SDK background thread) is not testable without
#   a mock server with configurable latency. These tests only verify the synchronous
#   call path; background flushing is outside scope.
#
# KNOWN GAP: Context manager protocol is inherited from the ABC __enter__/__exit__.
#   The tests above verify the delegation to end(), but the ABC's own protocol
#   (return False from __exit__) is not separately asserted here.
