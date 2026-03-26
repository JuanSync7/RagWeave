# @summary
# WeaviateBackend: VectorBackend implementation delegating to src.vector_db.weaviate.store.
# Exports: WeaviateBackend
# Deps: src.vector_db.backend, src.vector_db.common.schemas, src.vector_db.weaviate.store, weaviate
# @end-summary
"""Weaviate implementation of the VectorBackend contract.

Thin delegation layer — all Weaviate-specific logic lives in
``src.vector_db.weaviate.store``. The only logic added here is
``SearchFilter`` → ``weaviate.classes.query.Filter`` translation.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator, List, Optional

from src.vector_db.backend import VectorBackend
from src.vector_db.common.schemas import DocumentRecord, SearchResult, SearchFilter
from src.vector_db.weaviate.store import (
    create_persistent_client as _wv_create_persistent,
    get_weaviate_client as _wv_get_ephemeral,
    ensure_collection as _wv_ensure_collection,
    add_documents as _wv_add_documents,
    hybrid_search as _wv_hybrid_search,
    delete_collection as _wv_delete_collection,
    delete_documents_by_source as _wv_delete_by_source,
    delete_documents_by_source_key as _wv_delete_by_source_key,
)
from config.settings import WEAVIATE_COLLECTION_NAME

logger = logging.getLogger("rag.vector_db.weaviate")


class WeaviateBackend(VectorBackend):
    """Weaviate vector store backend."""

    def _col(self, collection: Optional[str]) -> str:
        return collection or WEAVIATE_COLLECTION_NAME

    def create_persistent_client(self) -> Any:
        return _wv_create_persistent()

    @contextmanager
    def get_ephemeral_client(self) -> Generator[Any, None, None]:
        with _wv_get_ephemeral() as client:
            yield client

    def ensure_collection(self, client: Any, collection: Optional[str] = None) -> None:
        _wv_ensure_collection(client, collection=self._col(collection))

    def add_documents(
        self,
        client: Any,
        documents: List[DocumentRecord],
        collection: Optional[str] = None,
    ) -> int:
        return _wv_add_documents(
            client,
            texts=[d.text for d in documents],
            embeddings=[d.embedding for d in documents],
            metadatas=[d.metadata for d in documents],
            collection=self._col(collection),
        )

    def search(
        self,
        client: Any,
        query: str,
        query_embedding: List[float],
        alpha: float,
        limit: int,
        filters: Optional[List[SearchFilter]] = None,
        collection: Optional[str] = None,
    ) -> List[SearchResult]:
        resolved = self._col(collection)
        wv_filter = self._translate_filters(filters)
        raw = _wv_hybrid_search(
            client, query, query_embedding, alpha, limit, wv_filter,
            collection=resolved,
        )
        return [
            SearchResult(
                text=r["text"],
                score=r["score"],
                metadata=r["metadata"],
                collection=resolved,
            )
            for r in raw
        ]

    def delete_collection(self, client: Any, collection: Optional[str] = None) -> None:
        _wv_delete_collection(client, collection=self._col(collection))

    def delete_by_source(
        self, client: Any, source: str, collection: Optional[str] = None
    ) -> int:
        return _wv_delete_by_source(client, source, collection=self._col(collection))

    def delete_by_source_key(
        self,
        client: Any,
        source_key: str,
        legacy_source: Optional[str] = None,
        collection: Optional[str] = None,
    ) -> int:
        return _wv_delete_by_source_key(
            client, source_key, legacy_source, collection=self._col(collection)
        )

    def close_client(self, client: Any) -> None:
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.debug("Weaviate client close error (ignored)", exc_info=True)

    # ------------------------------------------------------------------
    # Filter translation
    # ------------------------------------------------------------------

    def _translate_filters(self, filters: Optional[List[SearchFilter]]) -> Any:
        if not filters:
            return None
        clauses = [self._single_filter(f) for f in filters]
        result = clauses[0]
        for clause in clauses[1:]:
            result = result & clause
        return result

    @staticmethod
    def _single_filter(f: SearchFilter) -> Any:
        from weaviate.classes.query import Filter as WeaviateFilter
        prop = WeaviateFilter.by_property(f.property)
        ops = {
            "eq": prop.equal,
            "ne": prop.not_equal,
            "like": prop.like,
            "gt": prop.greater_than,
            "lt": prop.less_than,
            "gte": prop.greater_or_equal,
            "lte": prop.less_or_equal,
        }
        fn = ops.get(f.operator.lower())
        if fn is None:
            raise ValueError(
                f"Unsupported filter operator: {f.operator!r}. "
                f"Valid operators: {sorted(ops)}"
            )
        return fn(f.value)
