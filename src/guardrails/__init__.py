# @summary
# Public API for the guardrails subsystem: config-driven backend dispatcher
# and convenience functions. Re-exports common schemas for callers that need them.
# Exports: run_input_rails, run_output_rails, redact_pii, register_rag_chain,
#          RailMergeGate, GuardrailsMetadata, InputRailResult, OutputRailResult,
#          RailExecution, RailVerdict
# Deps: config.settings, src.guardrails.backend, src.guardrails.common.*
# @end-summary
"""Public API for guardrails used by the RAG pipeline.

The retrieval pipeline imports only from this module. Backend selection is
controlled by the ``GUARDRAIL_BACKEND`` config key — changing the key is all
that is needed to swap guardrail implementations.

Dispatcher pattern:
  ``_get_guardrail_backend()`` is a lazy singleton that constructs the configured backend
  on first call. The ``_NoOpBackend`` is used when
  ``GUARDRAIL_BACKEND`` is empty or ``"none"``.
"""

from __future__ import annotations

import logging

from src.guardrails.backend import GuardrailBackend
from src.guardrails.common import RailMergeGate
from src.guardrails.common import (
    GuardrailsMetadata,
    InputRailResult,
    OutputRailResult,
    RailExecution,
    RailVerdict,
)

logger = logging.getLogger("rag.guardrails")

_guardrail_backend: GuardrailBackend | None = None


class _NoOpBackend(GuardrailBackend):
    """Pass-through backend used when GUARDRAIL_BACKEND is empty or 'none'.

    All rail methods return empty/pass-through results so the pipeline runs
    without guardrails without requiring conditional logic in callers.
    """

    def run_input_rails(self, query: str, tenant_id: str = "") -> InputRailResult:
        return InputRailResult()

    def run_output_rails(self, answer: str, context_chunks: list[str]) -> OutputRailResult:
        return OutputRailResult(final_answer=answer)

    def redact_pii(self, text: str) -> tuple[str, list]:
        return text, []


def _get_guardrail_backend() -> GuardrailBackend:
    """Return the process-wide guardrail backend singleton.

    Constructs the backend on first call based on ``GUARDRAIL_BACKEND``.

    Returns:
        The active ``GuardrailBackend`` instance.

    Raises:
        ValueError: If ``GUARDRAIL_BACKEND`` is set to an unknown value.
    """
    global _guardrail_backend
    if _guardrail_backend is None:
        from config.settings import GUARDRAIL_BACKEND
        if GUARDRAIL_BACKEND == "nemo":
            from src.guardrails.nemo_guardrails import NemoBackend
            _guardrail_backend = NemoBackend()
        elif GUARDRAIL_BACKEND in ("", "none"):
            _guardrail_backend = _NoOpBackend()
        else:
            raise ValueError(
                f"Unknown GUARDRAIL_BACKEND: {GUARDRAIL_BACKEND!r}. "
                "Valid values: 'nemo', '' (empty), 'none'."
            )
    return _guardrail_backend


def run_input_rails(query: str, tenant_id: str = "") -> InputRailResult:
    """Run all input rails through the active backend.

    Args:
        query: Raw user query text.
        tenant_id: Optional tenant identifier.

    Returns:
        Aggregated ``InputRailResult``.
    """
    return _get_guardrail_backend().run_input_rails(query, tenant_id)


def run_output_rails(answer: str, context_chunks: list[str]) -> OutputRailResult:
    """Run all output rails through the active backend.

    Args:
        answer: Generated assistant answer text.
        context_chunks: Source context snippets used to generate the answer.

    Returns:
        Aggregated ``OutputRailResult``.
    """
    return _get_guardrail_backend().run_output_rails(answer, context_chunks)


def redact_pii(text: str) -> tuple[str, list]:
    """Redact PII from text using the active backend.

    Args:
        text: Raw input text.

    Returns:
        ``(redacted_text, detections)`` tuple. ``detections`` is empty when PII
        detection is disabled or no PII was found.
    """
    return _get_guardrail_backend().redact_pii(text)


def register_rag_chain(rag_chain: object) -> None:
    """Forward RAG chain registration to the active backend.

    A no-op for backends that do not require a chain reference (e.g.,
    ``_NoOpBackend``). ``NemoBackend`` overrides this to call
    ``config.guardrails.actions.set_rag_chain(rag_chain)``.

    Args:
        rag_chain: The ``RAGChain`` instance.
    """
    _get_guardrail_backend().register_rag_chain(rag_chain)


__all__ = [
    # Dispatcher functions
    "run_input_rails",
    "run_output_rails",
    "redact_pii",
    "register_rag_chain",
    # Re-exported for convenience
    "RailMergeGate",
    "GuardrailsMetadata",
    "InputRailResult",
    "OutputRailResult",
    "RailExecution",
    "RailVerdict",
]
