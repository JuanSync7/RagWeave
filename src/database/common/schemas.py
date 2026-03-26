# @summary
# Backend-agnostic contracts for the database abstraction layer.
# Exports: SearchResult, SearchFilter
# Deps: dataclasses, typing
# @end-summary
"""Shared data contracts for the database subsystem.

These types are backend-independent — no weaviate or other store-specific
imports belong here. All DatabaseBackend implementations accept and return
these types at their public boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class SearchResult:
    """A single document returned by the database search layer.

    Attributes:
        text: The document chunk text.
        score: Relevance score assigned by the backend (higher is better).
        metadata: Document metadata dict (source, heading, chunk_index, etc.).
        object_id: Optional backend-native object identifier.
    """

    text: str
    score: float
    metadata: dict[str, Any]
    object_id: Optional[str] = None


@dataclass
class SearchFilter:
    """Generic metadata filter clause for vector store queries.

    Multiple ``SearchFilter`` instances passed to ``database.search()`` are
    AND-combined. Each ``DatabaseBackend`` implementation translates these to
    its native filter representation.

    Attributes:
        property: Document metadata property to filter on (e.g. "source").
        operator: Comparison operator. Supported values:
            ``"eq"`` (equal), ``"ne"`` (not equal),
            ``"gt"`` / ``"lt"`` / ``"gte"`` / ``"lte"`` (numeric comparisons),
            ``"like"`` (glob-style pattern match).
        value: Value to compare against.
    """

    property: str
    operator: str
    value: Any
