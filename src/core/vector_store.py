# @summary
# Weaviate vector store with hybrid search (BM25 + dense vector).
# Key exports: get_weaviate_client, ensure_collection, add_documents, hybrid_search, delete_collection
# Deps: weaviate, typing, contextlib, os, from config.settings import *
# @end-summary
"""Weaviate vector store with hybrid search (BM25 + dense vector)."""

import hashlib
import logging
import uuid
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
            Property(name="source_uri", data_type=DataType.TEXT),
            Property(name="source_key", data_type=DataType.TEXT),
            Property(name="source_id", data_type=DataType.TEXT),
            Property(name="connector", data_type=DataType.TEXT),
            Property(name="source_version", data_type=DataType.TEXT),
            Property(name="retrieval_text_origin", data_type=DataType.TEXT),
            Property(name="citation_source_uri", data_type=DataType.TEXT),
            Property(name="provenance_method", data_type=DataType.TEXT),
            Property(name="provenance_confidence", data_type=DataType.NUMBER),
            Property(name="original_char_start", data_type=DataType.INT),
            Property(name="original_char_end", data_type=DataType.INT),
            Property(name="refactored_char_start", data_type=DataType.INT),
            Property(name="refactored_char_end", data_type=DataType.INT),
            Property(name="title", data_type=DataType.TEXT),
            Property(name="author", data_type=DataType.TEXT),
            Property(name="date", data_type=DataType.TEXT),
            Property(name="tags", data_type=DataType.TEXT),
            Property(name="chunk_index", data_type=DataType.INT),
            Property(name="total_chunks", data_type=DataType.INT),
            Property(name="section_path", data_type=DataType.TEXT),
            Property(name="heading", data_type=DataType.TEXT),
            Property(name="heading_level", data_type=DataType.INT),
            Property(name="tenant_id", data_type=DataType.TEXT),
        ],
    )
    span.end(status="ok")


def build_chunk_id(source: str, chunk_index: int, text: str) -> str:
    """Deterministic UUID chunk ID for idempotent upserts."""
    payload = f"{source}:{chunk_index}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, payload))


def _normalize_chunk_uuid(candidate: object, source: str, chunk_index: int, text: str) -> str:
    """Return a valid UUID string for Weaviate object insertion."""
    if candidate is not None:
        raw_value = str(candidate).strip()
        if raw_value:
            try:
                return str(uuid.UUID(raw_value))
            except ValueError:
                # Preserve deterministic behavior for legacy non-UUID IDs.
                return str(uuid.uuid5(uuid.NAMESPACE_URL, raw_value))
    return build_chunk_id(source, chunk_index, text)


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
    try:
        config = collection.config.get()
        raw_props = getattr(config, "properties", []) or []
        collection_props = {
            getattr(prop, "name", "")
            for prop in raw_props
            if getattr(prop, "name", "")
        }
    except Exception:
        collection_props = set()

    if metadatas is None:
        metadatas = [{}] * len(texts)

    with collection.batch.dynamic() as batch:
        for text, embedding, metadata in zip(texts, embeddings, metadatas):
            source = str(metadata.get("source") or "").strip() or "unknown"
            source_identity = str(metadata.get("source_key") or "").strip() or source
            chunk_index = metadata.get("chunk_index", 0)
            chunk_id = _normalize_chunk_uuid(
                metadata.get("chunk_id"),
                source_identity,
                chunk_index,
                text,
            )
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
                "tenant_id": metadata.get("tenant_id", "default"),
            }
            if "source_uri" in collection_props:
                properties["source_uri"] = metadata.get("source_uri", "")
            if "source_key" in collection_props:
                properties["source_key"] = metadata.get("source_key", "")
            if "source_id" in collection_props:
                properties["source_id"] = metadata.get("source_id", "")
            if "connector" in collection_props:
                properties["connector"] = metadata.get("connector", "local_fs")
            if "source_version" in collection_props:
                properties["source_version"] = metadata.get("source_version", "")
            if "retrieval_text_origin" in collection_props:
                properties["retrieval_text_origin"] = metadata.get("retrieval_text_origin", "original")
            if "citation_source_uri" in collection_props:
                properties["citation_source_uri"] = metadata.get("citation_source_uri", "")
            if "provenance_method" in collection_props:
                properties["provenance_method"] = metadata.get("provenance_method", "")
            if "provenance_confidence" in collection_props:
                properties["provenance_confidence"] = float(metadata.get("provenance_confidence", 0.0))
            if "original_char_start" in collection_props:
                properties["original_char_start"] = int(metadata.get("original_char_start", -1))
            if "original_char_end" in collection_props:
                properties["original_char_end"] = int(metadata.get("original_char_end", -1))
            if "refactored_char_start" in collection_props:
                properties["refactored_char_start"] = int(metadata.get("refactored_char_start", -1))
            if "refactored_char_end" in collection_props:
                properties["refactored_char_end"] = int(metadata.get("refactored_char_end", -1))
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
                "source_uri": obj.properties.get("source_uri", ""),
                "source_key": obj.properties.get("source_key", ""),
                "source_id": obj.properties.get("source_id", ""),
                "connector": obj.properties.get("connector", "local_fs"),
                "source_version": obj.properties.get("source_version", ""),
                "retrieval_text_origin": obj.properties.get("retrieval_text_origin", "original"),
                "citation_source_uri": obj.properties.get("citation_source_uri", ""),
                "provenance_method": obj.properties.get("provenance_method", ""),
                "provenance_confidence": obj.properties.get("provenance_confidence", 0.0),
                "original_char_start": obj.properties.get("original_char_start", -1),
                "original_char_end": obj.properties.get("original_char_end", -1),
                "refactored_char_start": obj.properties.get("refactored_char_start", -1),
                "refactored_char_end": obj.properties.get("refactored_char_end", -1),
                "title": obj.properties.get("title", ""),
                "author": obj.properties.get("author", ""),
                "date": obj.properties.get("date", ""),
                "tags": obj.properties.get("tags", ""),
                "chunk_index": obj.properties.get("chunk_index", 0),
                "total_chunks": obj.properties.get("total_chunks", 0),
                "section_path": obj.properties.get("section_path", ""),
                "heading": obj.properties.get("heading", ""),
                "heading_level": obj.properties.get("heading_level", 0),
                "tenant_id": obj.properties.get("tenant_id", "default"),
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


def delete_documents_by_source_key(
    client: weaviate.WeaviateClient,
    source_key: str,
    legacy_source: Optional[str] = None,
) -> int:
    """Delete chunks by stable source_key metadata value."""
    span = tracer.start_span(
        "vector_store.delete_documents_by_source_key",
        {"source_key": source_key},
    )
    collection = client.collections.get(WEAVIATE_COLLECTION_NAME)
    try:
        where = Filter.by_property("source_key").equal(source_key)
        result = collection.data.delete_many(where=where)
    except Exception:
        # Backward-compat fallback for collections created before source_key existed.
        if not legacy_source:
            span.end(status="ok")
            return 0
        where = Filter.by_property("source").equal(legacy_source)
        result = collection.data.delete_many(where=where)
    deleted = getattr(result, "matches", 0) or 0
    span.set_attribute("deleted_count", deleted)
    span.end(status="ok")
    return deleted
