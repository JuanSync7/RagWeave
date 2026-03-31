"""Integration tests for the Swappable Observability Subsystem end-to-end flows.

Covers:
    Scenario 3.1 — Happy Path: Full noop pipeline
    Scenario 3.2 — Langfuse Fallback: LangfuseBackend init failure → NoopBackend
    Scenario 3.3 — @observe Decorator Error Path
"""
import sys
import logging
import types

import pytest
from unittest.mock import patch

# --- Langfuse stub injection (module level, before any import that triggers it) ---
# Inject a minimal stub so that importing langfuse.backend does not fail when
# the real langfuse package is not installed.
if "langfuse" not in sys.modules:
    langfuse_stub = types.ModuleType("langfuse")
    langfuse_stub.get_client = lambda: None
    sys.modules["langfuse"] = langfuse_stub

import src.platform.observability as obs_module
from src.platform.observability import get_tracer, observe
from src.platform.observability.noop.backend import NoopBackend, NoopSpan, NoopTrace, NoopGeneration
from src.platform.observability.backend import ObservabilityBackend, Span, Trace, Generation


# ---------------------------------------------------------------------------
# SpyBackend / SpySpan test doubles (module level)
# ---------------------------------------------------------------------------

class SpySpan(Span):
    """Test double for Span — records all calls for assertion."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict = {}
        self.end_calls: list = []

    def set_attribute(self, key: str, value) -> None:
        self.attributes[key] = value

    def end(self, status: str = "ok", error=None) -> None:
        self.end_calls.append({"status": status, "error": error})


class SpyBackend(ObservabilityBackend):
    """Test double for ObservabilityBackend — records span calls."""

    def __init__(self) -> None:
        self.span_calls: list = []
        self._last_span: SpySpan = None

    def span(self, name: str, attributes=None, parent=None) -> SpySpan:
        s = SpySpan(name)
        self.span_calls.append(name)
        self._last_span = s
        return s

    def trace(self, name: str, metadata=None) -> Trace:
        return NoopTrace()

    def generation(self, name: str, model: str, input: str, metadata=None) -> Generation:
        return NoopGeneration()

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the observability singleton before and after every test."""
    obs_module._backend = None
    yield
    obs_module._backend = None


# ---------------------------------------------------------------------------
# --- Integration: Scenario 3.1 Happy Path ---
# ---------------------------------------------------------------------------

class TestScenario31NooopHappyPath:
    """Scenario 3.1 — get_tracer() with OBSERVABILITY_PROVIDER=noop → full noop pipeline.

    config.settings reads RAG_OBSERVABILITY_PROVIDER (not OBSERVABILITY_PROVIDER),
    so we set both to ensure the correct branch is taken regardless of whether
    config.settings is importable.
    """

    def test_get_tracer_returns_noop_backend(self, monkeypatch):
        monkeypatch.setenv("RAG_OBSERVABILITY_PROVIDER", "noop")
        monkeypatch.setenv("OBSERVABILITY_PROVIDER", "noop")
        backend = get_tracer()
        assert isinstance(backend, NoopBackend)

    def test_span_returns_noop_span_instance(self, monkeypatch):
        monkeypatch.setenv("RAG_OBSERVABILITY_PROVIDER", "noop")
        monkeypatch.setenv("OBSERVABILITY_PROVIDER", "noop")
        backend = get_tracer()
        span = backend.span("test.span")
        assert isinstance(span, Span), "span() must return a Span ABC instance"
        assert isinstance(span, NoopSpan)

    def test_span_set_attribute_no_exception(self, monkeypatch):
        monkeypatch.setenv("RAG_OBSERVABILITY_PROVIDER", "noop")
        monkeypatch.setenv("OBSERVABILITY_PROVIDER", "noop")
        backend = get_tracer()
        span = backend.span("test.span")
        # Must not raise
        span.set_attribute("key", "value")

    def test_span_end_no_exception(self, monkeypatch):
        monkeypatch.setenv("RAG_OBSERVABILITY_PROVIDER", "noop")
        monkeypatch.setenv("OBSERVABILITY_PROVIDER", "noop")
        backend = get_tracer()
        span = backend.span("test.span")
        result = span.end(status="ok")
        assert result is None

    def test_trace_returns_trace_instance(self, monkeypatch):
        monkeypatch.setenv("RAG_OBSERVABILITY_PROVIDER", "noop")
        monkeypatch.setenv("OBSERVABILITY_PROVIDER", "noop")
        backend = get_tracer()
        trace = backend.trace("test.trace")
        assert isinstance(trace, Trace)
        assert isinstance(trace, NoopTrace)

    def test_generation_returns_generation_instance(self, monkeypatch):
        monkeypatch.setenv("RAG_OBSERVABILITY_PROVIDER", "noop")
        monkeypatch.setenv("OBSERVABILITY_PROVIDER", "noop")
        backend = get_tracer()
        gen = backend.generation("g", "gpt-4", "hello")
        assert isinstance(gen, Generation)
        assert isinstance(gen, NoopGeneration)

    def test_flush_returns_none_no_exception(self, monkeypatch):
        monkeypatch.setenv("RAG_OBSERVABILITY_PROVIDER", "noop")
        monkeypatch.setenv("OBSERVABILITY_PROVIDER", "noop")
        backend = get_tracer()
        result = backend.flush()
        assert result is None

    def test_shutdown_returns_none_no_exception(self, monkeypatch):
        monkeypatch.setenv("RAG_OBSERVABILITY_PROVIDER", "noop")
        monkeypatch.setenv("OBSERVABILITY_PROVIDER", "noop")
        backend = get_tracer()
        result = backend.shutdown()
        assert result is None

    def test_singleton_identity(self, monkeypatch):
        """Second call to get_tracer() must return the same instance."""
        monkeypatch.setenv("RAG_OBSERVABILITY_PROVIDER", "noop")
        monkeypatch.setenv("OBSERVABILITY_PROVIDER", "noop")
        first = get_tracer()
        second = get_tracer()
        assert first is second, "get_tracer() must return the same singleton instance"

    def test_full_pipeline_no_exceptions(self, monkeypatch):
        """End-to-end: all calls in sequence raise no exceptions."""
        monkeypatch.setenv("RAG_OBSERVABILITY_PROVIDER", "noop")
        monkeypatch.setenv("OBSERVABILITY_PROVIDER", "noop")
        backend = get_tracer()
        span = backend.span("test.span")
        span.set_attribute("key", "value")
        span.end(status="ok")
        trace = backend.trace("test.trace")
        gen = backend.generation("g", "gpt-4", "hello")
        backend.flush()
        backend.shutdown()
        # All isinstance checks
        assert isinstance(span, Span)
        assert isinstance(trace, Trace)
        assert isinstance(gen, Generation)


# ---------------------------------------------------------------------------
# --- Integration: Scenario 3.2 Langfuse Fallback ---
# ---------------------------------------------------------------------------

def _patch_provider_langfuse():
    """Context manager: patch config.settings.OBSERVABILITY_PROVIDER to 'langfuse'.

    config.settings is a module-level singleton already imported; setting the
    env var alone does not retroactively change OBSERVABILITY_PROVIDER, so we
    patch the module attribute directly as well.
    """
    import config.settings as _settings
    return patch.object(_settings, "OBSERVABILITY_PROVIDER", "langfuse")


class TestScenario32LangfuseFallback:
    """Scenario 3.2 — LangfuseBackend init failure → fallback to NoopBackend.

    LangfuseBackend.__init__ does `from langfuse import get_client` at call-time,
    so the correct patch target is `langfuse.get_client` on the stub module in
    sys.modules (not a module-level attribute on the backend file).

    config.settings is already imported by the time tests run, so its
    OBSERVABILITY_PROVIDER module attribute must be patched directly via
    patch.object rather than relying on env var mutation alone.
    """

    def test_get_tracer_does_not_raise_on_langfuse_failure(self):
        with _patch_provider_langfuse():
            with patch.object(
                sys.modules["langfuse"],
                "get_client",
                side_effect=ConnectionError("no server"),
            ):
                backend = get_tracer()
        assert backend is not None

    def test_fallback_returns_noop_backend(self):
        with _patch_provider_langfuse():
            with patch.object(
                sys.modules["langfuse"],
                "get_client",
                side_effect=ConnectionError("no server"),
            ):
                backend = get_tracer()
        assert isinstance(backend, NoopBackend), (
            "Fallback must produce a NoopBackend, got: %s" % type(backend)
        )

    def test_fallback_span_returns_span_instance(self):
        with _patch_provider_langfuse():
            with patch.object(
                sys.modules["langfuse"],
                "get_client",
                side_effect=ConnectionError("no server"),
            ):
                backend = get_tracer()
        span = backend.span("x")
        assert isinstance(span, Span)

    def test_warning_logged_on_fallback(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rag.observability"):
            with _patch_provider_langfuse():
                with patch.object(
                    sys.modules["langfuse"],
                    "get_client",
                    side_effect=ConnectionError("no server"),
                ):
                    get_tracer()
        assert any(
            record.levelno >= logging.WARNING for record in caplog.records
        ), "A WARNING must be logged when falling back from langfuse to noop"

    def test_warning_message_contains_fallback_hint(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rag.observability"):
            with _patch_provider_langfuse():
                with patch.object(
                    sys.modules["langfuse"],
                    "get_client",
                    side_effect=ConnectionError("no server"),
                ):
                    get_tracer()
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_messages, "Expected at least one warning message"


# ---------------------------------------------------------------------------
# --- Integration: Scenario 3.3 @observe Decorator Error Path ---
# ---------------------------------------------------------------------------

class TestScenario33ObserveDecoratorErrorPath:
    """Scenario 3.3 — @observe-decorated function raises → span records error → exception re-raised."""

    def _make_spy_backend(self) -> SpyBackend:
        spy = SpyBackend()
        obs_module._backend = spy
        return spy

    def test_exception_is_reraised(self):
        spy = self._make_spy_backend()

        @observe("test.operation")
        def failing_func():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            failing_func()

    def test_error_attribute_set_on_span(self):
        spy = self._make_spy_backend()

        @observe("test.operation")
        def failing_func():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            failing_func()

        assert spy._last_span is not None, "Expected a span to be created"
        assert spy._last_span.attributes.get("error") == "boom", (
            "Expected span attribute 'error' == 'boom', got: %s" % spy._last_span.attributes
        )

    def test_span_end_called_with_error_status(self):
        spy = self._make_spy_backend()

        @observe("test.operation")
        def failing_func():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            failing_func()

        end_calls = spy._last_span.end_calls
        assert len(end_calls) == 1, "Expected exactly one end() call"
        assert end_calls[0]["status"] == "error", (
            "Expected end(status='error'), got: %s" % end_calls[0]["status"]
        )

    def test_span_end_called_with_exception_object(self):
        spy = self._make_spy_backend()

        @observe("test.operation")
        def failing_func():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            failing_func()

        end_calls = spy._last_span.end_calls
        assert isinstance(end_calls[0]["error"], RuntimeError), (
            "Expected end() to receive the RuntimeError instance"
        )

    def test_span_name_matches_observe_argument(self):
        spy = self._make_spy_backend()

        @observe("test.operation")
        def failing_func():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            failing_func()

        assert spy._last_span.name == "test.operation", (
            "Span name must be 'test.operation', got: %s" % spy._last_span.name
        )

    def test_observe_preserves_dunder_name(self):
        spy = self._make_spy_backend()

        @observe("test.operation")
        def my_special_func():
            pass

        assert my_special_func.__name__ == "my_special_func", (
            "@observe must preserve __name__ via functools.wraps"
        )

    def test_observe_preserves_dunder_qualname(self):
        spy = self._make_spy_backend()

        @observe("test.operation")
        def my_special_func():
            pass

        assert "my_special_func" in my_special_func.__qualname__, (
            "@observe must preserve __qualname__ via functools.wraps"
        )

    def test_spy_span_is_span_abc_instance(self):
        """Sanity check: SpySpan satisfies the Span ABC contract."""
        s = SpySpan("check")
        assert isinstance(s, Span)

    def test_spy_backend_is_backend_abc_instance(self):
        """Sanity check: SpyBackend satisfies the ObservabilityBackend ABC contract."""
        b = SpyBackend()
        assert isinstance(b, ObservabilityBackend)
