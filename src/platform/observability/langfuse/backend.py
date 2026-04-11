# @summary
# Langfuse v3 backend implementation for the observability subsystem.
# Exports: LangfuseBackend
# Deps: langfuse (SDK — all imports confined here), src.platform.observability.backend
# @end-summary
"""Langfuse v3 backend implementation.

All imports from the langfuse package are confined exclusively to this file.
Consumer code must never import from this module directly — use the public
API at src.platform.observability instead.
"""
from __future__ import annotations

import logging
from typing import Optional

from src.platform.observability.backend import (
    Generation,
    ObservabilityBackend,
    Span,
    Trace,
)
from src.platform.observability.noop import (
    NoopGeneration,
    NoopSpan,
    NoopTrace,
)

logger = logging.getLogger("rag.observability.langfuse")


class LangfuseSpan(Span):
    """Langfuse-backed span wrapper.

    Wraps a Langfuse SDK observation object. All SDK calls are fail-open:
    exceptions are caught and logged as warnings, never propagated.
    """

    def __init__(self, inner_obs) -> None:
        self._inner = inner_obs

    def set_attribute(self, key: str, value: object) -> None:
        """Forward attribute to Langfuse as metadata. Fail-open."""
        try:
            self._inner.update(metadata={key: value})
        except Exception as exc:
            logger.warning("LangfuseSpan.set_attribute failed: %s", exc)

    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        """Finalize this span in Langfuse. Fail-open."""
        try:
            if error is not None:
                self._inner.update(level="ERROR", status_message=str(error))
            self._inner.end()
        except Exception as exc:
            logger.warning("LangfuseSpan.end failed: %s", exc)


class LangfuseGeneration(Generation):
    """Langfuse-backed generation wrapper.

    Wraps a Langfuse SDK generation observation object. All SDK calls are
    fail-open: exceptions are caught and logged as warnings, never propagated.
    """

    def __init__(self, inner_obs) -> None:
        self._inner = inner_obs

    def set_output(self, output: str) -> None:
        """Record the LLM completion output. Fail-open."""
        try:
            self._inner.update(output=output)
        except Exception as exc:
            logger.warning("LangfuseGeneration.set_output failed: %s", exc)

    def set_token_counts(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Record token usage. Fail-open.

        Langfuse expects token counts under the 'usage' key with 'input'/'output' sub-keys.
        """
        try:
            self._inner.update(usage={"input": prompt_tokens, "output": completion_tokens})
        except Exception as exc:
            logger.warning("LangfuseGeneration.set_token_counts failed: %s", exc)

    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        """Finalize this generation in Langfuse. Fail-open."""
        try:
            if error is not None:
                self._inner.update(level="ERROR", status_message=str(error))
            self._inner.end()
        except Exception as exc:
            logger.warning("LangfuseGeneration.end failed: %s", exc)


class LangfuseTrace(Trace):
    """Langfuse-backed trace wrapper.

    Wraps a Langfuse SDK trace object. Child spans and generations are
    created through the trace object for correct parent-child correlation.
    All SDK calls are fail-open: exceptions are caught and return noop objects.
    """

    def __init__(self, trace_obj) -> None:
        self._trace = trace_obj

    def span(self, name: str, attributes: Optional[dict] = None) -> Span:
        """Create a child span under this trace. Fail-open — returns NoopSpan on error."""
        try:
            obs = self._trace.span(name=name, metadata=attributes or {})
            return LangfuseSpan(obs)
        except Exception as exc:
            logger.warning("LangfuseTrace.span failed: %s", exc)
            return NoopSpan()

    def generation(
        self,
        name: str,
        model: str,
        input: str,
        metadata: Optional[dict] = None,
    ) -> Generation:
        """Create a child generation under this trace. Fail-open — returns NoopGeneration on error."""
        try:
            obs = self._trace.generation(
                name=name, model=model, input=input, metadata=metadata or {}
            )
            return LangfuseGeneration(obs)
        except Exception as exc:
            logger.warning("LangfuseTrace.generation failed: %s", exc)
            return NoopGeneration()


class LangfuseBackend(ObservabilityBackend):
    """Langfuse v3 observability backend.

    Connects to Langfuse via the SDK's get_client() singleton. All
    credentials are read from environment variables by the SDK — this class
    accepts no credential parameters.

    Raises:
        Any exception raised by get_client() during construction. The
        observability factory (_init_backend) catches these and falls
        back to NoopBackend.
    """

    def __init__(self) -> None:
        from langfuse import get_client  # SDK import confined here (REQ-201)
        self._client = get_client()  # Raises on misconfiguration — caller handles (REQ-207)

    def span(
        self,
        name: str,
        attributes: Optional[dict] = None,
        parent: Optional[Span] = None,
    ) -> Span:
        """Create a span. Routes through trace object when parent is a LangfuseTrace. Fail-open."""
        try:
            if isinstance(parent, LangfuseTrace):
                obs = parent._trace.span(name=name, metadata=attributes or {})
            else:
                obs = self._client.start_observation(
                    as_type="span", name=name, metadata=attributes or {}
                )
            return LangfuseSpan(obs)
        except Exception as exc:
            logger.warning("LangfuseBackend.span failed: %s", exc)
            return NoopSpan()

    def trace(self, name: str, metadata: Optional[dict] = None) -> Trace:
        """Create a trace root. Fail-open — returns NoopTrace on error."""
        try:
            t = self._client.trace(name=name, metadata=metadata or {})
            return LangfuseTrace(t)
        except Exception as exc:
            logger.warning("LangfuseBackend.trace failed: %s", exc)
            return NoopTrace()

    def generation(
        self,
        name: str,
        model: str,
        input: str,
        metadata: Optional[dict] = None,
    ) -> Generation:
        """Create a standalone generation observation. Fail-open."""
        try:
            obs = self._client.start_observation(
                as_type="generation",
                name=name,
                model=model,
                input=input,
                metadata=metadata or {},
            )
            return LangfuseGeneration(obs)
        except Exception as exc:
            logger.warning("LangfuseBackend.generation failed: %s", exc)
            return NoopGeneration()

    def flush(self) -> None:
        """Drain pending observations to Langfuse. Propagates SDK exceptions (REQ-249)."""
        self._client.flush()

    def shutdown(self) -> None:
        """Shut down the Langfuse client. Propagates SDK exceptions (REQ-251)."""
        self._client.shutdown()
