# @summary
# Shared deterministic retrieval helpers (for example resilient JSON-object parsing).
# Exports: parse_json_object
# Deps: src.common.utils
# @end-summary
"""Deterministic utility helpers for retrieval modules."""

from __future__ import annotations

from src.common.utils import parse_json_object

__all__ = ["parse_json_object"]
