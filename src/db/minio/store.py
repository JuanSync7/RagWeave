# @summary
# MinIO low-level helpers: bucket management, document put/get/delete/exists, presigned URLs, listing.
# Exports: create_client, ensure_bucket, put_document, get_document,
#          delete_document, document_exists, get_document_url, build_document_id, list_documents
# Deps: minio, minio.error, json, io, uuid, datetime, config.settings, src.platform.observability
# @end-summary
"""Low-level MinIO document store operations."""

from __future__ import annotations

import io
import json
import logging
import uuid
from datetime import timedelta
from typing import Optional

from minio import Minio
from minio.error import S3Error

from config.settings import (
    MINIO_ENDPOINT,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY,
    MINIO_BUCKET,
    MINIO_SECURE,
)
from src.platform.observability.providers import get_tracer

logger = logging.getLogger("rag.db.minio.store")
tracer = get_tracer()

_METADATA_SUFFIX = ".meta.json"
_CONTENT_SUFFIX = ".md"


def build_document_id(source_key: str) -> str:
    """Deterministic UUID for a document, stable across ingestion runs."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"doc:{source_key}"))


def create_client() -> Minio:
    """Create a MinIO client. The client is stateless and safe to share."""
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )


def ensure_bucket(client: Minio, bucket: str = MINIO_BUCKET) -> None:
    """Create the bucket if it does not exist (idempotent)."""
    span = tracer.start_span("document_store.ensure_bucket", {"bucket": bucket})
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    span.end(status="ok")


def put_document(
    client: Minio,
    document_id: str,
    content: str,
    metadata: Optional[dict] = None,
    bucket: str = MINIO_BUCKET,
) -> None:
    """Store or overwrite a document and its metadata sidecar.

    Two objects are written:
      - ``<document_id>.md``        — the markdown content
      - ``<document_id>.meta.json`` — the metadata dict as JSON
    """
    span = tracer.start_span(
        "document_store.put_document",
        {"document_id": document_id, "bucket": bucket, "content_bytes": len(content)},
    )
    content_bytes = content.encode("utf-8")
    client.put_object(
        bucket,
        f"{document_id}{_CONTENT_SUFFIX}",
        io.BytesIO(content_bytes),
        length=len(content_bytes),
        content_type="text/markdown; charset=utf-8",
    )
    meta_payload = json.dumps(metadata or {}, ensure_ascii=False).encode("utf-8")
    client.put_object(
        bucket,
        f"{document_id}{_METADATA_SUFFIX}",
        io.BytesIO(meta_payload),
        length=len(meta_payload),
        content_type="application/json; charset=utf-8",
    )
    span.end(status="ok")


def get_document(
    client: Minio,
    document_id: str,
    bucket: str = MINIO_BUCKET,
) -> Optional[dict]:
    """Fetch a document's content and metadata.

    Returns:
        Dict with ``document_id``, ``content``, ``metadata`` keys, or ``None``
        if not found.
    """
    span = tracer.start_span(
        "document_store.get_document",
        {"document_id": document_id, "bucket": bucket},
    )
    try:
        resp = client.get_object(bucket, f"{document_id}{_CONTENT_SUFFIX}")
        content = resp.read().decode("utf-8")
        resp.close()
        resp.release_conn()
    except S3Error as exc:
        if exc.code in ("NoSuchKey", "NoSuchBucket"):
            span.end(status="ok")
            return None
        raise

    metadata: dict = {}
    try:
        resp_meta = client.get_object(bucket, f"{document_id}{_METADATA_SUFFIX}")
        metadata = json.loads(resp_meta.read().decode("utf-8"))
        resp_meta.close()
        resp_meta.release_conn()
    except S3Error:
        pass  # metadata sidecar missing — not fatal

    span.end(status="ok")
    return {"document_id": document_id, "content": content, "metadata": metadata}


def delete_document(
    client: Minio,
    document_id: str,
    bucket: str = MINIO_BUCKET,
) -> bool:
    """Remove a document and its metadata sidecar.

    Returns:
        True if the content object existed, False otherwise.
    """
    span = tracer.start_span(
        "document_store.delete_document",
        {"document_id": document_id, "bucket": bucket},
    )
    existed = document_exists(client, document_id, bucket)
    for suffix in (_CONTENT_SUFFIX, _METADATA_SUFFIX):
        try:
            client.remove_object(bucket, f"{document_id}{suffix}")
        except S3Error:
            pass
    span.end(status="ok")
    return existed


def document_exists(
    client: Minio,
    document_id: str,
    bucket: str = MINIO_BUCKET,
) -> bool:
    """Return True if the content object exists in the bucket."""
    try:
        client.stat_object(bucket, f"{document_id}{_CONTENT_SUFFIX}")
        return True
    except S3Error:
        return False


def get_document_url(
    client: Minio,
    document_id: str,
    bucket: str = MINIO_BUCKET,
    expires_in_seconds: int = 3600,
) -> str:
    """Return a presigned URL for direct download of the document content."""
    return client.presigned_get_object(
        bucket,
        f"{document_id}{_CONTENT_SUFFIX}",
        expires=timedelta(seconds=expires_in_seconds),
    )


def list_documents(
    client: Minio,
    bucket: str = MINIO_BUCKET,
    prefix: str = "",
    limit: int = 1000,
    offset: int = 0,
) -> list[dict]:
    """List content objects in a bucket, excluding metadata sidecars.

    Returns dicts with: document_id, source_key, size_bytes, last_modified (ISO-8601).
    Sidecars (.meta.json) are excluded from results.
    Applies Python-side pagination (offset/limit) after collecting all matches.
    Logs WARNING and falls back to object name stem when sidecar is missing.

    Raises:
        S3Error: re-raised if bucket is unreachable (not NoSuchKey/NoSuchBucket).
    """
    span = tracer.start_span(
        "document_store.list_documents",
        {"bucket": bucket, "prefix": prefix, "limit": limit, "offset": offset},
    )
    results: list[dict] = []
    for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
        name: str = obj.object_name
        if not name.endswith(_CONTENT_SUFFIX):
            continue
        stem = name[: -len(_CONTENT_SUFFIX)]
        source_key = stem
        try:
            resp = client.get_object(bucket, f"{stem}{_METADATA_SUFFIX}")
            meta = json.loads(resp.read().decode("utf-8"))
            resp.close()
            resp.release_conn()
            source_key = meta.get("source_key", stem)
        except S3Error:
            logger.warning(
                "list_documents: sidecar missing for %r; using stem as source_key", name
            )
        results.append({
            "document_id": build_document_id(source_key),
            "source_key": source_key,
            "size_bytes": obj.size,
            "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
        })
    span.end(status="ok")
    return results[offset: offset + limit]
