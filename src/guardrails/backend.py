# @summary
# GuardrailBackend ABC: formal swappable backend contract for all guardrail implementations.
# Exports: GuardrailBackend
# Deps: abc, typing, src.guardrails.common.schemas
# @end-summary
"""GuardrailBackend — abstract base class for all guardrail backends.

Defines the formal contract between the retrieval pipeline and any guardrail
implementation. New backends implement the three abstract methods; the concrete
``register_rag_chain`` method is overridden only when the backend needs a
reference to the RAG chain (e.g., for Colang action handlers).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Tuple

from src.guardrails.common import (
    InputRailResult,
    OutputRailResult,
)


class GuardrailBackend(ABC):
    """Abstract contract for a guardrail backend.

    Callers (``rag_chain.py``) interact only through these methods.
    Swapping backends requires only a change to the ``GUARDRAIL_BACKEND``
    config key — no changes to retrieval code.
    """

    @abstractmethod
    def run_input_rails(self, query: str, tenant_id: str = "") -> InputRailResult:
        """Run all input rails (intent, injection, PII, toxicity, topic safety).

        Args:
            query: Raw user query text.
            tenant_id: Optional tenant identifier for policy routing and logging.

        Returns:
            Aggregated ``InputRailResult``.
        """
        ...

    @abstractmethod
    def run_output_rails(self, answer: str, context_chunks: List[str]) -> OutputRailResult:
        """Run all output rails (faithfulness, PII, toxicity).

        Args:
            answer: Generated assistant answer text.
            context_chunks: Source context snippets used to generate the answer.

        Returns:
            Aggregated ``OutputRailResult``.
        """
        ...

    @abstractmethod
    def redact_pii(self, text: str) -> Tuple[str, list]:
        """Redact PII from text before it is forwarded to the LLM.

        Used by the pre-LLM PII gate in ``rag_chain.run()``. Called
        synchronously, before the parallel query-processing / input-rail stage.

        Args:
            text: Raw input text (typically the user query).

        Returns:
            ``(redacted_text, detections)`` where ``detections`` is the list of
            PII findings (may be empty). The caller treats a non-empty list as a
            signal that redaction occurred.
        """
        ...

    def register_rag_chain(self, rag_chain: object) -> None:
        """Optional hook for backends that need a reference to the RAG chain.

        Default is a no-op. Override in backends that register Colang action
        handlers or other callback mechanisms that require a RAG chain reference
        (e.g., ``NemoBackend`` calls
        ``config.guardrails.actions.set_rag_chain(rag_chain)``).

        Args:
            rag_chain: The ``RAGChain`` instance (passed as ``object`` to avoid
                a circular import between retrieval and guardrails).
        """
