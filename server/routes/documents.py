# @summary
# Document & Collection Management API routes (read-only browsing endpoints).
# Exports: create_documents_router
# Deps: fastapi, server.schemas, server.common.schemas, src.db, src.vector_db,
#       src.platform.security.auth, src.platform.security.tenancy
# @end-summary
"""Document & Collection Management API routes.

Provides read-only endpoints for browsing ingested documents and vector
collections. All route handlers are thin — business logic is delegated to
``src.db`` and ``src.vector_db`` backend functions.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from server.common import (
    ApiErrorDetail,
    ApiErrorResponse,
)
from server.schemas import (
    CollectionItem,
    CollectionListResponse,
    CollectionStatsResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentSummary,
    DocumentUrlResponse,
    SourceListResponse,
    SourceSummary,
)
from src.platform.security import (
    Principal,
    authenticate_request,
)
from src.platform.security import resolve_tenant_id
import src.db as db
import src.vector_db as vector_db

logger = logging.getLogger("rag.server.routes.documents")

# Upper bound on documents fetched from MinIO for in-memory pagination.
# TODO: push pagination down to the storage layer for large collections.
_MAX_DOCUMENT_FETCH = int(
    __import__("os").environ.get("RAG_DOCUMENTS_MAX_FETCH", "1000")
)


# ---------------------------------------------------------------------------
# Error helpers
# ---------------------------------------------------------------------------


def _not_found(item_type: str, identifier: str) -> HTTPException:
    """Return HTTP 404 with ApiErrorResponse body."""
    return HTTPException(
        status_code=404,
        detail=ApiErrorResponse(
            error=ApiErrorDetail(
                code="not_found",
                message=f"{item_type} '{identifier}' not found.",
            ),
        ).model_dump(),
    )


def _service_unavailable(detail: str) -> HTTPException:
    """Return HTTP 503 with ApiErrorResponse body."""
    return HTTPException(
        status_code=503,
        detail=ApiErrorResponse(
            error=ApiErrorDetail(
                code="service_unavailable",
                message=detail,
            ),
        ).model_dump(),
    )


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_documents_router(
    db_client: Any,
    vector_client: Any,
) -> APIRouter:
    """Return a FastAPI router with all document management endpoints."""

    standard_error_responses = {
        401: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        422: {"model": ApiErrorResponse},
        503: {"model": ApiErrorResponse},
    }
    router = APIRouter()

    # -----------------------------------------------------------------------
    # GET /api/v1/documents
    # -----------------------------------------------------------------------

    @router.get(
        "/api/v1/documents",
        response_model=DocumentListResponse,
        responses=standard_error_responses,
    )
    async def list_documents_endpoint(
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        source_filter: Optional[str] = Query(None, max_length=500),
        connector_filter: Optional[str] = Query(None, max_length=100),
        collection: Optional[str] = Query(None, max_length=128),
        principal: Principal = Depends(authenticate_request),
    ) -> DocumentListResponse:
        resolve_tenant_id(principal, None)
        try:
            minio_docs = db.list_documents(db_client, limit=_MAX_DOCUMENT_FETCH)
        except Exception as exc:
            logger.error("MinIO list_documents failed: %s", exc)
            raise _service_unavailable(f"Document store unavailable: {exc}")

        # Attempt to get chunk counts from Weaviate; degrade gracefully
        chunk_lookup: dict[str, int] = {}
        weaviate_available = True
        try:
            agg_rows = vector_db.aggregate_by_source(
                vector_client, collection=collection
            )
            chunk_lookup = {
                row["source_key"]: row["chunk_count"] for row in agg_rows
            }
        except Exception:
            logger.warning(
                "Weaviate aggregate_by_source unavailable; chunk_count will be null"
            )
            weaviate_available = False

        # Build document summaries, applying filters
        summaries: list[DocumentSummary] = []
        for doc in minio_docs:
            sk = doc["source_key"]
            if source_filter and source_filter not in sk:
                continue
            chunk_count = chunk_lookup.get(sk, 0) if weaviate_available else None
            connector = "unknown"
            # Try to get connector from aggregate data
            if weaviate_available:
                for row in agg_rows:
                    if row["source_key"] == sk:
                        connector = row.get("connector", "unknown")
                        break
            if connector_filter and connector != connector_filter:
                continue
            summaries.append(
                DocumentSummary(
                    document_id=doc["document_id"],
                    source=sk,
                    source_key=sk,
                    connector=connector,
                    chunk_count=chunk_count,
                    ingested_at=doc.get("last_modified"),
                )
            )

        # Sort by source ascending (AC-3000-5)
        summaries.sort(key=lambda s: s.source)
        total = len(summaries)
        page = summaries[offset: offset + limit]
        return DocumentListResponse(
            documents=page, total=total, limit=limit, offset=offset
        )

    # -----------------------------------------------------------------------
    # GET /api/v1/documents/{document_id}
    # -----------------------------------------------------------------------

    @router.get(
        "/api/v1/documents/{document_id}",
        response_model=DocumentDetailResponse,
        responses=standard_error_responses,
    )
    async def get_document_endpoint(
        document_id: str,
        principal: Principal = Depends(authenticate_request),
    ) -> DocumentDetailResponse:
        resolve_tenant_id(principal, None)
        try:
            doc = db.get_document(db_client, document_id)
        except Exception as exc:
            logger.error("get_document failed: %s", exc)
            raise _service_unavailable(f"Document store unavailable: {exc}")

        if doc is None:
            raise _not_found("Document", document_id)

        # Optionally get chunk count
        chunk_count: Optional[int] = None
        try:
            agg_rows = vector_db.aggregate_by_source(vector_client)
            source_key = doc.metadata.get("source_key", "") if hasattr(doc, "metadata") else ""
            for row in agg_rows:
                if row["source_key"] == source_key:
                    chunk_count = row["chunk_count"]
                    break
        except Exception:
            logger.debug("Weaviate chunk count lookup unavailable; chunk_count stays None", exc_info=True)

        content = doc.content if hasattr(doc, "content") else str(doc)
        metadata = doc.metadata if hasattr(doc, "metadata") else {}

        return DocumentDetailResponse(
            document_id=document_id,
            content=content,
            metadata=metadata,
            chunk_count=chunk_count,
        )

    # -----------------------------------------------------------------------
    # GET /api/v1/documents/{document_id}/url
    # -----------------------------------------------------------------------

    @router.get(
        "/api/v1/documents/{document_id}/url",
        response_model=DocumentUrlResponse,
        responses=standard_error_responses,
    )
    async def get_document_url_endpoint(
        document_id: str,
        expires_in: int = Query(3600, ge=60, le=86400),
        principal: Principal = Depends(authenticate_request),
    ) -> DocumentUrlResponse:
        resolve_tenant_id(principal, None)
        try:
            exists = db.document_exists(db_client, document_id)
        except Exception as exc:
            logger.error("document_exists check failed: %s", exc)
            raise _service_unavailable(f"Document store unavailable: {exc}")

        if not exists:
            raise _not_found("Document", document_id)

        try:
            url = db.get_document_url(
                db_client, document_id, expires_in_seconds=expires_in
            )
        except Exception as exc:
            logger.error("get_document_url failed: %s", exc)
            raise _service_unavailable(f"Document store unavailable: {exc}")

        return DocumentUrlResponse(
            document_id=document_id, url=url, expires_in=expires_in
        )

    # -----------------------------------------------------------------------
    # GET /api/v1/sources
    # -----------------------------------------------------------------------

    @router.get(
        "/api/v1/sources",
        response_model=SourceListResponse,
        responses=standard_error_responses,
    )
    async def list_sources_endpoint(
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        connector_filter: Optional[str] = Query(None, max_length=100),
        collection: Optional[str] = Query(None, max_length=128),
        principal: Principal = Depends(authenticate_request),
    ) -> SourceListResponse:
        resolve_tenant_id(principal, None)
        try:
            agg_rows = vector_db.aggregate_by_source(
                vector_client,
                collection=collection,
                connector_filter=connector_filter,
            )
        except Exception as exc:
            logger.error("aggregate_by_source failed: %s", exc)
            raise _service_unavailable(f"Vector store unavailable: {exc}")

        # Group by source to compute document_count (distinct source_key per source)
        source_map: dict[str, dict] = {}
        for row in agg_rows:
            source = row.get("source", row.get("source_key", ""))
            connector = row.get("connector", "unknown")
            key = f"{source}:{connector}"
            if key not in source_map:
                source_map[key] = {
                    "source": source,
                    "connector": connector,
                    "document_count": 0,
                    "chunk_count": 0,
                }
            source_map[key]["document_count"] += 1
            source_map[key]["chunk_count"] += row.get("chunk_count", 0)

        summaries = [SourceSummary(**v) for v in source_map.values()]
        summaries.sort(key=lambda s: s.source)
        total = len(summaries)
        page = summaries[offset: offset + limit]
        return SourceListResponse(
            sources=page, total=total, limit=limit, offset=offset
        )

    # -----------------------------------------------------------------------
    # GET /api/v1/collections
    # -----------------------------------------------------------------------

    @router.get(
        "/api/v1/collections",
        response_model=CollectionListResponse,
        responses=standard_error_responses,
    )
    async def list_collections_endpoint(
        principal: Principal = Depends(authenticate_request),
    ) -> CollectionListResponse:
        resolve_tenant_id(principal, None)
        try:
            rows = vector_db.list_collections(vector_client)
        except Exception as exc:
            logger.error("list_collections failed: %s", exc)
            raise _service_unavailable(f"Vector store unavailable: {exc}")

        return CollectionListResponse(
            collections=[CollectionItem(**row) for row in rows]
        )

    # -----------------------------------------------------------------------
    # GET /api/v1/collections/{collection_name}/stats
    # -----------------------------------------------------------------------

    @router.get(
        "/api/v1/collections/{collection_name}/stats",
        response_model=CollectionStatsResponse,
        responses=standard_error_responses,
    )
    async def get_collection_stats_endpoint(
        collection_name: str,
        principal: Principal = Depends(authenticate_request),
    ) -> CollectionStatsResponse:
        resolve_tenant_id(principal, None)
        try:
            stats = vector_db.get_collection_stats(
                vector_client, collection=collection_name
            )
        except Exception as exc:
            logger.error("get_collection_stats failed: %s", exc)
            raise _service_unavailable(f"Vector store unavailable: {exc}")

        if stats is None:
            raise _not_found("Collection", collection_name)

        return CollectionStatsResponse(
            collection_name=collection_name, **stats
        )

    return router


__all__ = ["create_documents_router"]
