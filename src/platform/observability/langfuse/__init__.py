# @summary
# Public exports for the Langfuse observability backend package.
# Exports: LangfuseBackend
# Deps: langfuse.backend
# @end-summary
"""Langfuse observability backend package.

Exports only LangfuseBackend. All Langfuse SDK imports are confined
to langfuse/backend.py — no SDK symbols are re-exported from this package.
"""
from src.platform.observability.langfuse.backend import LangfuseBackend

__all__ = ["LangfuseBackend"]
