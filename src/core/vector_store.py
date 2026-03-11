# @summary
# Weaviate vector store with hybrid search (BM25 + dense vector).
# Key exports: get_weaviate_client, ensure_collection, add_documents, hybrid_search, delete_collection
# Deps: weaviate, typing, contextlib, os, from config.settings import *
# @end-summary
"""Weaviate vector store with hybrid search (BM25 + dense vector)."""

import hashlib
import logging
from typing import List, Optional
from contextlib import contextmanager

import weaviate
from weaviate.classes.config import Configure, Property, DataType
from weaviate.classes.query import Filter, HybridFusion, MetadataQuery

from config.settings import (
    WEAVIATE_COLLECTION_NAME,
    WEAVIATE_DATA_DIR,
    HYBRID_SEARCH_ALPHA,
    SEARCH_LIMIT,
)
from src.platform.observability.providers import get_tracer

logger = logging.getLogger("rag.vector_store")
tracer = get_tracer()


def create_persistent_client() -> weaviate.WeaviateClient:
    """Create a long-lived Weaviate embedded client.

    Caller is responsible for calling client.close() on shutdown.
    Preferred for server/worker processes that serve many queries.
    """
    span = tracer.start_span("vector_store.create_persistent_client")
    client = weaviate.connect_to_embedded(
        persistence_data_path=WEAVIATE_DATA_DIR,
    )
    span.end(status="ok")
    return client


@contextmanager
def get_weaviate_client():
    """Context manager for Weaviate embedded client.

    Opens and closes the embedded instance per use — suitable for CLI
    and batch scripts. For server use, prefer create_persistent_client().
    """
    span = tracer.start_span("vector_store.get_weaviate_client")
    client = weaviate.connect_to_embedded(
        persistence_data_path=WEAVIATE_DATA_DIR,
    )
    try:
        yield client
    finally:
        client.close()
        span.end(status="ok")


def ensure_collection(client: weaviate.WeaviateClient) -> None:
    """Create the document collection if it doesn't exist."""
    span = tracer.start_span("vector_store.ensure_collection")
    if client.collections.exists(WEAVIATE_COLLECTION_NAME):
        span.end(status="ok")
        return

    client.collections.create(
        name=WEAVIATE_COLLECTION_NAME,
        vectorizer_config=Configure.Vectorizer.none(),
        properties=[
            Property(name="text", data_type=DataType.TEXT),
            Property(name="source", data_type=DataType.TEXT),
            Property(name="title", data_type=DataType.TEXT),
            Property(name="author", data_type=DataType.TEXT),
            Property(name="date", data_type=DataType.TEXT),
            Property(name="tags", data_type=DataType.TEXT),
            Property(name="chunk_index", data_type=DataType.INT),
            Property(name="total_chunks", data_type=DataType.INT),
            Property(name="section_path", data_type=DataType.TEXT),
            Property(name="heading", data_type=DataType.TEXT),
            Property(name="heading_level", data_type=DataType.INT),
        ],
    )
    span.end(status="ok")


def build_chunk_id(source: str, chunk_index: int, text: str) -> str:
    """Deterministic chunk ID for idempotent upserts."""
    payload = f"{source}:{chunk_index}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def add_documents(
    client: weaviate.WeaviateClient,
    texts: List[str],
    embeddings: List[List[float]],
    metadatas: Optional[List[dict]] = None,
) -> int:
    """Add documents with pre-computed embeddings to Weaviate.

    Returns:
        Number of documents added.
    """
    span = tracer.start_span("vector_store.add_documents", {"count": len(texts)})
    collection = client.collections.get(WEAVIATE_COLLECTION_NAME)

    if metadatas is None:
        metadatas = [{}] * len(texts)

    with collection.batch.dynamic() as batch:
        for text, embedding, metadata in zip(texts, embeddings, metadatas):
            source = metadata.get("source", "unknown")
            chunk_index = metadata.get("chunk_index", 0)
            chunk_id = metadata.get("chunk_id") or build_chunk_id(source, chunk_index, text)
            properties = {
                "text": text,
                "source": source,
                "title": metadata.get("title", ""),
                "author": metadata.get("author", ""),
                "date": metadata.get("date", ""),
                "tags": metadata.get("tags", ""),
                "chunk_index": metadata.get("chunk_index", 0),
                "total_chunks": metadata.get("total_chunks", 0),
                "section_path": metadata.get("section_path", ""),
                "heading": metadata.get("heading", ""),
                "heading_level": metadata.get("heading_level", 0),
            }
            batch.add_object(properties=properties, vector=embedding, uuid=chunk_id)

    span.end(status="ok")
    return len(texts)


def hybrid_search(
    client: weaviate.WeaviateClient,
    query: str,
    query_embedding: List[float],
    alpha: float = HYBRID_SEARCH_ALPHA,
    limit: int = SEARCH_LIMIT,
    filters: Optional[Filter] = None,
) -> List[dict]:
    """Perform hybrid search (BM25 + vector) on the collection.

    Args:
        client: Weaviate client.
        query: Text query for BM25 component.
        query_embedding: Dense vector for the vector component.
        alpha: Balance between BM25 (0.0) and vector (1.0).
        limit: Max results to return.
        filters: Optional Weaviate Filter for metadata pre-filtering.

    Returns:
        List of dicts with 'text', 'metadata', and 'score' keys.
    """
    span = tracer.start_span(
        "vector_store.hybrid_search",
        {"alpha": alpha, "limit": limit, "has_filters": filters is not None},
    )
    collection = client.collections.get(WEAVIATE_COLLECTION_NAME)

    results = collection.query.hybrid(
        query=query,
        vector=query_embedding,
        alpha=alpha,
        limit=limit,
        filters=filters,
        fusion_type=HybridFusion.RELATIVE_SCORE,
        return_metadata=MetadataQuery(score=True),
    )

    documents = []
    for obj in results.objects:
        documents.append({
            "text": obj.properties.get("text", ""),
            "metadata": {
                "source": obj.properties.get("source", "unknown"),
                "title": obj.properties.get("title", ""),
                "author": obj.properties.get("author", ""),
                "date": obj.properties.get("date", ""),
                "tags": obj.properties.get("tags", ""),
                "chunk_index": obj.properties.get("chunk_index", 0),
                "total_chunks": obj.properties.get("total_chunks", 0),
                "section_path": obj.properties.get("section_path", ""),
                "heading": obj.properties.get("heading", ""),
                "heading_level": obj.properties.get("heading_level", 0),
            },
            "score": obj.metadata.score if obj.metadata else 0.0,
        })
    span.set_attribute("result_count", len(documents))
    span.end(status="ok")
    return documents


def delete_collection(client: weaviate.WeaviateClient) -> None:
    """Delete the document collection (useful for re-ingestion)."""
    span = tracer.start_span("vector_store.delete_collection")
    if client.collections.exists(WEAVIATE_COLLECTION_NAME):
        client.collections.delete(WEAVIATE_COLLECTION_NAME)
    span.end(status="ok")


def delete_documents_by_source(client: weaviate.WeaviateClient, source: str) -> int:
    """Delete chunks by source metadata value."""
    span = tracer.start_span("vector_store.delete_documents_by_source", {"source": source})
    collection = client.collections.get(WEAVIATE_COLLECTION_NAME)
    where = Filter.by_property("source").equal(source)
    result = collection.data.delete_many(where=where)
    deleted = getattr(result, "matches", 0) or 0
    span.set_attribute("deleted_count", deleted)
    span.end(status="ok")
    return deleted
