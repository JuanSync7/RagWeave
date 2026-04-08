# @summary
# Human-in-the-loop gate for LangGraph workflows.
# Exports: human_gate
# Deps: langgraph.types, src.common.llm.schemas
# @end-summary
"""Human-in-the-loop interrupt gate for workflow nodes."""

from __future__ import annotations

import logging
from typing import Any

from src.common.llm.schemas import GateDecision

__all__ = ["human_gate"]

logger = logging.getLogger(__name__)

_HAS_INTERRUPT = False
_interrupt_fn: Any = None

try:
    from langgraph.types import interrupt as _interrupt_fn  # type: ignore[assignment]

    _HAS_INTERRUPT = True
except ImportError:
    pass


def human_gate(
    question: str,
    *,
    provisional: Any | None = None,
) -> GateDecision:
    """Pause the workflow for human input.

    Args:
        question: The prompt shown to the human operator.
        provisional: If provided and no interrupt mechanism is available,
            the workflow continues immediately with this provisional value.

    Returns:
        A ``GateDecision`` indicating the human's response or a provisional
        pass-through.
    """
    if _HAS_INTERRUPT:
        human_response = _interrupt_fn(question)
        return GateDecision(approved=True, input=str(human_response))

    if provisional is not None:
        return GateDecision(approved=True, input=None, provisional=True)

    logger.warning(
        "human_gate called without LangGraph interrupt support and no "
        "provisional value — auto-approving. Human gating requires "
        "LangGraph runtime."
    )
    return GateDecision(approved=True, provisional=True)
