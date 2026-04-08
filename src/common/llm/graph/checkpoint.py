# @summary
# Factory for LangGraph checkpoint backends.
# Exports: get_checkpointer
# Deps: langgraph.checkpoint.memory
# @end-summary
"""Checkpoint backend factory for LangGraph state persistence."""

from __future__ import annotations

import logging
from typing import Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

__all__ = ["get_checkpointer"]

logger = logging.getLogger(__name__)

_DEFAULT_SQLITE_PATH = ".cache/graph_checkpoints.db"


def get_checkpointer(
    backend: str = "memory",
    *,
    path: Optional[str] = None,
) -> BaseCheckpointSaver:
    """Return a LangGraph-compatible checkpoint saver.

    Args:
        backend: ``"memory"`` (in-process, default) or ``"sqlite"`` (persistent).
        path: File path for the sqlite backend.
              Defaults to ``".cache/graph_checkpoints.db"``.

    Returns:
        A :class:`BaseCheckpointSaver` instance ready for use with a
        LangGraph :func:`StateGraph.compile` call.
    """
    if backend == "memory":
        return MemorySaver()

    if backend == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore[import-untyped]
        except ImportError:
            logger.warning(
                "langgraph-checkpoint-sqlite is not installed; "
                "falling back to in-memory checkpointer."
            )
            return MemorySaver()
        return SqliteSaver.from_conn_string(path or _DEFAULT_SQLITE_PATH)

    raise ValueError(f"Unknown checkpoint backend: {backend!r}")
