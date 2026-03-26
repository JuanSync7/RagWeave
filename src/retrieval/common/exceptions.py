# @summary
# Shared exception hierarchy for the retrieval subsystem.
# Exports: RetrievalError, ModelLoadError
# Deps: (none)
# @end-summary
"""Retrieval subsystem exception hierarchy.

All retrieval-layer exceptions derive from ``RetrievalError`` so callers
can catch at the right granularity without importing each concrete type.
"""


class RetrievalError(Exception):
    """Base exception for retrieval-subsystem failures."""


class ModelLoadError(RetrievalError):
    """Raised when a local ML model (embeddings, reranker) fails to load.

    Attributes:
        model_path: Filesystem path that was attempted.
    """

    def __init__(self, message: str, model_path: str = "") -> None:
        super().__init__(message)
        self.model_path = model_path


__all__ = ["RetrievalError", "ModelLoadError"]
