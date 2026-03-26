# @summary
# Backend-agnostic contracts for the document store abstraction layer.
# Exports: StoredDocument
# Deps: dataclasses, typing
# @end-summary
"""Shared data contracts for the db subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StoredDocument:
    """A document retrieved from the document store.

    Attributes:
        document_id: Stable UUID identifying this document across all systems.
        content: Full text content (clean markdown).
        metadata: Document metadata dict (source_key, source_uri, connector, etc.).
    """

    document_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
