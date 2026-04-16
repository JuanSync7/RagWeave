# @summary
# Content hash infrastructure for cross-document deduplication (Tier 1).
# Exports: normalise_chunk_text, compute_content_hash,
#          find_chunk_by_content_hash, append_source_document,
#          remove_source_document_refs
# Deps: hashlib, re, logging
# @end-summary
"""Content hash infrastructure for cross-document deduplication (Tier 1).

Provides SHA-256 content hashing with deterministic text normalisation and
Weaviate helper functions for exact-match dedup lookups and source-document
provenance maintenance.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Optional

logger = logging.getLogger("rag.ingest.embedding.dedup_utils")

_WHITESPACE_RE = re.compile(r"\s+")


def normalise_chunk_text(text: str) -> str:
    """Normalise chunk text for hash computation.

    Strips leading/trailing whitespace, collapses interior whitespace
    sequences to a single ASCII space. Case is preserved (FR-3410).

    >>> normalise_chunk_text("  Hello   World\\n")
    'Hello World'
    >>> normalise_chunk_text("Hello World")
    'Hello World'
    """
    return _WHITESPACE_RE.sub(" ", text.strip())


def compute_content_hash(text: str) -> str:
    """Compute SHA-256 content hash of normalised text.

    Returns a lowercase hex string (64 characters).

    Contract: normalise_chunk_text("  Hello   World\\n") and
    normalise_chunk_text("Hello World") produce identical hashes.
    "Hello World" and "hello world" produce different hashes (FR-3410 AC-2).
    """
    normalised = normalise_chunk_text(text)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def find_chunk_by_content_hash(
    client: Any, content_hash: str
) -> Optional[dict[str, Any]]:
    """Query Weaviate for a chunk with matching content_hash.

    Returns dict with 'uuid', 'source_documents', 'text_length' on match,
    or None if no match or transient error (FR-3411 AC-3).

    Args:
        client: Weaviate client handle.
        content_hash: SHA-256 hex string to match.

    Returns:
        Dict with uuid, source_documents, text_length; or None.
    """
    try:
        from weaviate.classes.query import Filter  # lazy import — Weaviate optional

        collection = client.collections.get("Chunk")
        result = collection.query.fetch_objects(
            filters=Filter.by_property("content_hash").equal(content_hash),
            limit=1,
            return_properties=["content_hash", "source_documents", "text"],
        )
        if not result.objects:
            return None
        obj = result.objects[0]
        return {
            "uuid": str(obj.uuid),
            "source_documents": obj.properties.get("source_documents", []),
            "text_length": len(obj.properties.get("text", "")),
        }
    except Exception:
        logger.warning(
            "Weaviate lookup failed for content_hash=%s; treating as novel",
            content_hash[:16],
            exc_info=True,
        )
        return None


def append_source_document(
    client: Any, chunk_uuid: str, source_key: str
) -> bool:
    """Append source_key to a canonical chunk's source_documents array.

    Deduplicates: does not append if already present (FR-3431 AC-2).
    Returns True on success, False on failure (FR-3431 AC-4).

    Args:
        client: Weaviate client handle.
        chunk_uuid: UUID of the canonical chunk to update.
        source_key: Source key to append.

    Returns:
        True on success, False on error.
    """
    try:
        collection = client.collections.get("Chunk")
        obj = collection.query.fetch_object_by_id(
            chunk_uuid, return_properties=["source_documents"]
        )
        existing = obj.properties.get("source_documents", [])
        if source_key in existing:
            return True  # already present, no-op

        existing.append(source_key)
        collection.data.update(
            uuid=chunk_uuid,
            properties={"source_documents": existing},
        )
        return True
    except Exception:
        logger.error(
            "Failed to append source_document %s to chunk %s",
            source_key,
            chunk_uuid,
            exc_info=True,
        )
        return False


def remove_source_document_refs(client: Any, source_key: str) -> None:
    """Remove source_key from all chunks' source_documents arrays.

    Chunks whose source_documents becomes empty are deleted (FR-3433 AC-3).
    Called during re-ingestion before dedup processing.

    Args:
        client: Weaviate client handle.
        source_key: Source key to remove from all chunk provenance arrays.
    """
    try:
        from weaviate.classes.query import Filter  # lazy import — Weaviate optional

        collection = client.collections.get("Chunk")
        results = collection.query.fetch_objects(
            filters=Filter.by_property("source_documents").contains_any([source_key]),
            limit=10_000,
            return_properties=["source_documents"],
        )
        for obj in results.objects:
            sources = obj.properties.get("source_documents", [])
            updated = [s for s in sources if s != source_key]
            if not updated:
                collection.data.delete_by_id(obj.uuid)
            else:
                collection.data.update(
                    uuid=obj.uuid,
                    properties={"source_documents": updated},
                )
    except Exception:
        logger.error(
            "Failed to clean source_document refs for %s",
            source_key,
            exc_info=True,
        )


def build_fuzzy_fingerprint(text: str, config: Any = None) -> str:
    """Compute a MinHash fingerprint and return a hex-encoded string.

    Convenience facade over ``minhash_engine.compute_fuzzy_fingerprint``
    for callers that already have the config object. When ``config`` is None
    the engine defaults (shingle_size=3, num_hashes=128) are used.

    Args:
        text: Raw chunk text (normalised internally).
        config: IngestionConfig instance, or None to use defaults.

    Returns:
        Hex string of the serialised MinHash signature.

    Raises:
        ImportError: If datasketch is not installed.
    """
    from src.ingest.embedding.support.minhash_engine import compute_fuzzy_fingerprint

    shingle_size = getattr(config, "fuzzy_shingle_size", 3) if config else 3
    num_hashes = getattr(config, "fuzzy_num_hashes", 128) if config else 128
    return compute_fuzzy_fingerprint(text, shingle_size=shingle_size, num_hashes=num_hashes)
