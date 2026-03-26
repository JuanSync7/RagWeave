# @summary
# DatabaseBackend ABC: formal swappable backend contract for all database implementations.
# Exports: DatabaseBackend
# Deps: abc, contextlib, typing, src.database.common.schemas
# @end-summary
"""DatabaseBackend — abstract base class for all database backends.

Defines the formal contract between the ingestion/retrieval pipelines and
any vector store implementation. New backends implement the abstract methods;
``close_client`` is overridden only when the backend requires explicit
teardown (default is a no-op).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Generator, List, Optional

from src.database.common.schemas import SearchResult, SearchFilter


class DatabaseBackend(ABC):
    """Abstract contract for a vector database backend.

    Callers (ingestion and retrieval pipelines) interact only through the
    public API in ``database/__init__.py``, never with backend instances
    directly. Swapping backends requires only a change to the
    ``DATABASE_BACKEND`` config key — no changes to pipeline code.
    """

    @abstractmethod
    def create_persistent_client(self) -> Any:
        """Create a long-lived database client.

        Caller is responsible for calling ``close_client()`` on shutdown.
        Preferred for server/worker processes that serve many queries.

        Returns:
            Backend-specific client handle.
        """
        ...

    @abstractmethod
    @contextmanager
    def get_ephemeral_client(self) -> Generator[Any, None, None]:
        """Context manager for a short-lived database client.

        Opens and closes the client per use — suitable for CLI and batch
        scripts. For server use, prefer ``create_persistent_client()``.

        Yields:
            Backend-specific client handle.
        """
        ...

    @abstractmethod
    def ensure_collection(self, client: Any) -> None:
        """Create the document collection / index if it does not exist.

        Idempotent — safe to call on every startup.
        """
        ...

    @abstractmethod
    def add_documents(
        self,
        client: Any,
        texts: List[str],
        embeddings: List[List[float]],
        metadatas: List[dict],
    ) -> int:
        """Insert documents with pre-computed embeddings.

        Returns:
            Number of documents added.
        """
        ...

    @abstractmethod
    def search(
        self,
        client: Any,
        query: str,
        query_embedding: List[float],
        alpha: float,
        limit: int,
        filters: Optional[List[SearchFilter]] = None,
    ) -> List[SearchResult]:
        """Perform a hybrid (keyword + vector) search.

        Args:
            client: Database client handle.
            query: Text query for the keyword search component.
            query_embedding: Dense vector for the vector search component.
            alpha: Balance between keyword (0.0) and vector (1.0).
            limit: Maximum number of results to return.
            filters: Optional list of metadata filter clauses (AND-combined).

        Returns:
            Ranked list of ``SearchResult`` objects.
        """
        ...

    @abstractmethod
    def delete_collection(self, client: Any) -> None:
        """Drop the entire document collection."""
        ...

    @abstractmethod
    def delete_by_source(self, client: Any, source: str) -> int:
        """Delete all documents matching the given source path.

        Returns:
            Number of documents deleted.
        """
        ...

    @abstractmethod
    def delete_by_source_key(
        self,
        client: Any,
        source_key: str,
        legacy_source: Optional[str] = None,
    ) -> int:
        """Delete documents by stable source_key, with legacy_source fallback.

        Returns:
            Number of documents deleted.
        """
        ...

    def close_client(self, client: Any) -> None:
        """Close a persistent client returned by ``create_persistent_client()``.

        Default is a no-op for backends where the client manages its own
        lifecycle. Override for backends that require explicit teardown.

        Args:
            client: The client handle to close.
        """
