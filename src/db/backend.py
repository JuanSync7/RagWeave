# @summary
# DocumentBackend ABC: formal swappable backend contract for all document store implementations.
# Exports: DocumentBackend
# Deps: abc, contextlib, typing, src.db.common.schemas
# @end-summary
"""DocumentBackend — abstract base class for all document store backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Generator, Optional

from src.db.common.schemas import StoredDocument


class DocumentBackend(ABC):
    """Abstract contract for a document store backend.

    Callers interact only through the public API in ``db/__init__.py``,
    never with backend instances directly. Swapping backends requires only a
    change to the ``DATABASE_BACKEND`` config key.
    """

    @abstractmethod
    def create_persistent_client(self) -> Any:
        """Create a long-lived client. ``close_client()`` is a no-op for stateless backends."""
        ...

    @abstractmethod
    @contextmanager
    def get_ephemeral_client(self) -> Generator[Any, None, None]:
        """Context manager for a short-lived client."""
        ...

    @abstractmethod
    def ensure_bucket(self, client: Any, bucket: Optional[str] = None) -> None:
        """Create the storage bucket if it does not exist (idempotent)."""
        ...

    @abstractmethod
    def put_document(
        self,
        client: Any,
        document_id: str,
        content: str,
        metadata: dict,
        bucket: Optional[str] = None,
    ) -> None:
        """Store or overwrite a document."""
        ...

    @abstractmethod
    def get_document(
        self,
        client: Any,
        document_id: str,
        bucket: Optional[str] = None,
    ) -> Optional[StoredDocument]:
        """Fetch a document by ID. Returns None if not found."""
        ...

    @abstractmethod
    def delete_document(
        self,
        client: Any,
        document_id: str,
        bucket: Optional[str] = None,
    ) -> bool:
        """Remove a document. Returns True if it existed."""
        ...

    @abstractmethod
    def document_exists(
        self,
        client: Any,
        document_id: str,
        bucket: Optional[str] = None,
    ) -> bool:
        """Check whether a document exists without fetching its content."""
        ...

    @abstractmethod
    def get_document_url(
        self,
        client: Any,
        document_id: str,
        bucket: Optional[str] = None,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Return a presigned URL for direct download of the document."""
        ...

    def close_client(self, client: Any) -> None:
        """Close a persistent client. Default is a no-op (stateless backends)."""
