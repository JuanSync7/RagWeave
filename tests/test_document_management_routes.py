# @summary
# Route handler tests for Document & Collection Management API endpoints.
# Covers: GET /documents, /documents/{id}, /documents/{id}/url, /sources, /collections, /collections/{name}/stats
# Deps: pytest, unittest.mock, fastapi.testclient, server.routes.documents
# @end-summary
"""Route handler tests for the Document & Collection Management API.

Uses FastAPI TestClient with mocked backends. Tests happy paths, 404, 503,
graceful degradation, and pagination/validation edge cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routes.documents import create_documents_router
from src.platform.security.auth import Principal, authenticate_request


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_FAKE_PRINCIPAL = Principal(
    subject="test-user",
    tenant_id="test-tenant",
    roles=["user"],
    auth_type="api_key",
)


@dataclass
class _FakeDoc:
    """Mimics StoredDocument for route handler access patterns."""
    document_id: str = "doc-1"
    content: str = "# Hello"
    metadata: dict[str, Any] = field(default_factory=lambda: {"source_key": "test/doc"})


def _build_app() -> FastAPI:
    """Build a FastAPI app with auth bypassed and the documents router mounted."""
    app = FastAPI()
    router = create_documents_router(MagicMock(), MagicMock())
    app.include_router(router)
    app.dependency_overrides[authenticate_request] = lambda: _FAKE_PRINCIPAL
    return app


def _build_client() -> TestClient:
    """Return a TestClient with auth bypassed."""
    return TestClient(_build_app())


# ===========================================================================
# GET /api/v1/documents
# ===========================================================================


class TestListDocumentsEndpoint:
    """Tests for GET /api/v1/documents (MT-R-01 through MT-R-09)."""

    def test_happy_path(self):
        """MT-R-01: 3 docs with chunk counts returns 200."""
        docs = [
            {"document_id": "d1", "source_key": "a", "size_bytes": 100, "last_modified": "2026-01-01"},
            {"document_id": "d2", "source_key": "b", "size_bytes": 200, "last_modified": "2026-01-02"},
            {"document_id": "d3", "source_key": "c", "size_bytes": 300, "last_modified": "2026-01-03"},
        ]
        agg = [
            {"source_key": "a", "source": "a", "connector": "local_fs", "chunk_count": 5},
            {"source_key": "b", "source": "b", "connector": "confluence", "chunk_count": 3},
            {"source_key": "c", "source": "c", "connector": "local_fs", "chunk_count": 7},
        ]
        with (
            patch("server.routes.documents.db.list_documents", return_value=docs),
            patch("server.routes.documents.vector_db.aggregate_by_source", return_value=agg),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/documents")
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["documents"]) == 3
            assert body["total"] == 3
            assert body["documents"][0]["chunk_count"] is not None

    def test_weaviate_down_graceful_degradation(self):
        """MT-R-02: Weaviate down -> 200, chunk_count null, connector unknown."""
        docs = [
            {"document_id": "d1", "source_key": "a", "size_bytes": 100, "last_modified": "2026-01-01"},
        ]
        with (
            patch("server.routes.documents.db.list_documents", return_value=docs),
            patch("server.routes.documents.vector_db.aggregate_by_source", side_effect=ConnectionError("refused")),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/documents")
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["documents"]) == 1
            assert body["documents"][0]["chunk_count"] is None
            assert body["documents"][0]["connector"] == "unknown"

    def test_source_filter(self):
        """MT-R-03: source_filter filters documents by source_key substring."""
        docs = [
            {"document_id": "d1", "source_key": "wiki/a", "size_bytes": 100, "last_modified": None},
            {"document_id": "d2", "source_key": "docs/b", "size_bytes": 200, "last_modified": None},
            {"document_id": "d3", "source_key": "wiki/c", "size_bytes": 300, "last_modified": None},
        ]
        agg = [
            {"source_key": "wiki/a", "source": "wiki/a", "connector": "c", "chunk_count": 1},
            {"source_key": "docs/b", "source": "docs/b", "connector": "c", "chunk_count": 2},
            {"source_key": "wiki/c", "source": "wiki/c", "connector": "c", "chunk_count": 3},
        ]
        with (
            patch("server.routes.documents.db.list_documents", return_value=docs),
            patch("server.routes.documents.vector_db.aggregate_by_source", return_value=agg),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/documents", params={"source_filter": "wiki"})
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 2

    def test_connector_filter(self):
        """MT-R-04: connector_filter filters to matching connectors only."""
        docs = [
            {"document_id": "d1", "source_key": "a", "size_bytes": 100, "last_modified": None},
            {"document_id": "d2", "source_key": "b", "size_bytes": 200, "last_modified": None},
        ]
        agg = [
            {"source_key": "a", "source": "a", "connector": "confluence", "chunk_count": 5},
            {"source_key": "b", "source": "b", "connector": "local_fs", "chunk_count": 3},
        ]
        with (
            patch("server.routes.documents.db.list_documents", return_value=docs),
            patch("server.routes.documents.vector_db.aggregate_by_source", return_value=agg),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/documents", params={"connector_filter": "confluence"})
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 1
            assert body["documents"][0]["connector"] == "confluence"

    def test_sorted_by_source_ascending(self):
        """MT-R-05: Documents sorted by source ascending."""
        docs = [
            {"document_id": "d3", "source_key": "c", "size_bytes": 1, "last_modified": None},
            {"document_id": "d1", "source_key": "a", "size_bytes": 1, "last_modified": None},
            {"document_id": "d2", "source_key": "b", "size_bytes": 1, "last_modified": None},
        ]
        agg = [
            {"source_key": "a", "source": "a", "connector": "c", "chunk_count": 1},
            {"source_key": "b", "source": "b", "connector": "c", "chunk_count": 1},
            {"source_key": "c", "source": "c", "connector": "c", "chunk_count": 1},
        ]
        with (
            patch("server.routes.documents.db.list_documents", return_value=docs),
            patch("server.routes.documents.vector_db.aggregate_by_source", return_value=agg),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/documents")
            body = resp.json()
            sources = [d["source"] for d in body["documents"]]
            assert sources == sorted(sources)

    def test_pagination(self):
        """MT-R-06: limit=2, offset=0 on 5 docs returns 2 docs, total=5."""
        docs = [
            {"document_id": f"d{i}", "source_key": f"k{i}", "size_bytes": 1, "last_modified": None}
            for i in range(5)
        ]
        agg = [
            {"source_key": f"k{i}", "source": f"k{i}", "connector": "c", "chunk_count": 1}
            for i in range(5)
        ]
        with (
            patch("server.routes.documents.db.list_documents", return_value=docs),
            patch("server.routes.documents.vector_db.aggregate_by_source", return_value=agg),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/documents", params={"limit": 2, "offset": 0})
            body = resp.json()
            assert len(body["documents"]) == 2
            assert body["total"] == 5

    def test_limit_exceeds_max_422(self):
        """MT-R-07: limit > 100 -> 422."""
        resp = _build_client().get("/api/v1/documents", params={"limit": 101})
        assert resp.status_code == 422

    def test_negative_offset_422(self):
        """MT-R-08: offset < 0 -> 422."""
        resp = _build_client().get("/api/v1/documents", params={"offset": -1})
        assert resp.status_code == 422

    def test_minio_s3error_503(self):
        """MT-R-09: S3Error from list_documents -> 503."""
        with (
            patch("server.routes.documents.db.list_documents", side_effect=Exception("S3 down")),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/documents")
            assert resp.status_code == 503
            body = resp.json()
            assert body["detail"]["error"]["code"] == "service_unavailable"


# ===========================================================================
# GET /api/v1/documents/{document_id}
# ===========================================================================


class TestGetDocumentEndpoint:
    """Tests for GET /api/v1/documents/{document_id} (MT-R-10 through MT-R-13)."""

    def test_happy_path(self):
        """MT-R-10: returns 200 with document detail."""
        fake_doc = _FakeDoc(document_id="doc-1", content="# Hello", metadata={"source_key": "test"})
        with (
            patch("server.routes.documents.db.get_document", return_value=fake_doc),
            patch("server.routes.documents.vector_db.aggregate_by_source", return_value=[
                {"source_key": "test", "chunk_count": 5, "source": "test", "connector": "c"},
            ]),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/documents/doc-1")
            assert resp.status_code == 200
            body = resp.json()
            assert body["document_id"] == "doc-1"
            assert body["content"] == "# Hello"
            assert "metadata" in body

    def test_not_found_404(self):
        """MT-R-11: Document not found -> 404."""
        with (
            patch("server.routes.documents.db.get_document", return_value=None),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/documents/missing-id")
            assert resp.status_code == 404
            body = resp.json()
            assert body["detail"]["error"]["code"] == "not_found"

    def test_weaviate_down_chunk_count_null(self):
        """MT-R-12: Weaviate down -> 200, chunk_count is null."""
        fake_doc = _FakeDoc()
        with (
            patch("server.routes.documents.db.get_document", return_value=fake_doc),
            patch("server.routes.documents.vector_db.aggregate_by_source", side_effect=ConnectionError("refused")),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/documents/doc-1")
            assert resp.status_code == 200
            body = resp.json()
            assert body["chunk_count"] is None

    def test_minio_down_503(self):
        """MT-R-13: MinIO backend down -> 503."""
        with (
            patch("server.routes.documents.db.get_document", side_effect=Exception("S3 down")),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/documents/doc-1")
            assert resp.status_code == 503


# ===========================================================================
# GET /api/v1/documents/{document_id}/url
# ===========================================================================


class TestGetDocumentUrlEndpoint:
    """Tests for GET /api/v1/documents/{document_id}/url (MT-R-14 through MT-R-18)."""

    def test_happy_path(self):
        """MT-R-14: returns 200 with presigned URL."""
        with (
            patch("server.routes.documents.db.document_exists", return_value=True),
            patch("server.routes.documents.db.get_document_url", return_value="https://minio.local/bucket/doc-1?sig=abc"),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/documents/doc-1/url", params={"expires_in": 7200})
            assert resp.status_code == 200
            body = resp.json()
            assert "url" in body
            assert body["expires_in"] == 7200

    def test_not_found_404(self):
        """MT-R-15: Document not found -> 404."""
        with (
            patch("server.routes.documents.db.document_exists", return_value=False),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/documents/missing-id/url")
            assert resp.status_code == 404

    def test_expires_in_too_low_422(self):
        """MT-R-16: expires_in < 60 -> 422."""
        resp = _build_client().get("/api/v1/documents/doc-1/url", params={"expires_in": 30})
        assert resp.status_code == 422

    def test_expires_in_too_high_422(self):
        """MT-R-17: expires_in > 86400 -> 422."""
        resp = _build_client().get("/api/v1/documents/doc-1/url", params={"expires_in": 100000})
        assert resp.status_code == 422

    def test_expires_in_default_3600(self):
        """MT-R-18: default expires_in is 3600."""
        with (
            patch("server.routes.documents.db.document_exists", return_value=True),
            patch("server.routes.documents.db.get_document_url", return_value="https://example.com/signed"),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/documents/doc-1/url")
            assert resp.status_code == 200
            body = resp.json()
            assert body["expires_in"] == 3600


# ===========================================================================
# GET /api/v1/sources
# ===========================================================================


class TestListSourcesEndpoint:
    """Tests for GET /api/v1/sources (MT-R-19 through MT-R-22)."""

    def test_happy_path(self):
        """MT-R-19: aggregated sources returned with document/chunk counts."""
        agg_rows = [
            {"source_key": "a1", "source": "wiki", "connector": "confluence", "chunk_count": 10},
            {"source_key": "a2", "source": "wiki", "connector": "confluence", "chunk_count": 15},
            {"source_key": "b1", "source": "docs", "connector": "local_fs", "chunk_count": 5},
            {"source_key": "b2", "source": "docs", "connector": "local_fs", "chunk_count": 8},
        ]
        with (
            patch("server.routes.documents.vector_db.aggregate_by_source", return_value=agg_rows),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/sources")
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 2
            sources = body["sources"]
            wiki = next(s for s in sources if s["source"] == "wiki")
            assert wiki["document_count"] == 2
            assert wiki["chunk_count"] == 25

    def test_weaviate_down_503(self):
        """MT-R-20: Weaviate down -> 503."""
        with (
            patch("server.routes.documents.vector_db.aggregate_by_source", side_effect=ConnectionError("refused")),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/sources")
            assert resp.status_code == 503
            body = resp.json()
            assert body["detail"]["error"]["code"] == "service_unavailable"

    def test_connector_filter_forwarded(self):
        """MT-R-21: connector_filter is passed to backend."""
        with (
            patch("server.routes.documents.vector_db.aggregate_by_source", return_value=[]) as mock_agg,
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/sources", params={"connector_filter": "confluence"})
            assert resp.status_code == 200
            _, kwargs = mock_agg.call_args
            assert kwargs.get("connector_filter") == "confluence"

    def test_limit_exceeds_max_422(self):
        """MT-R-22: limit > 500 -> 422."""
        resp = _build_client().get("/api/v1/sources", params={"limit": 501})
        assert resp.status_code == 422


# ===========================================================================
# GET /api/v1/collections
# ===========================================================================


class TestListCollectionsEndpoint:
    """Tests for GET /api/v1/collections (MT-R-23, MT-R-24)."""

    def test_happy_path(self):
        """MT-R-23: returns 200 with collection items."""
        with (
            patch("server.routes.documents.vector_db.list_collections", return_value=[
                {"collection_name": "A", "chunk_count": 100},
                {"collection_name": "B", "chunk_count": 200},
            ]),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/collections")
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["collections"]) == 2

    def test_weaviate_down_503(self):
        """MT-R-24: Weaviate connection error -> 503."""
        with (
            patch("server.routes.documents.vector_db.list_collections", side_effect=ConnectionError("refused")),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/collections")
            assert resp.status_code == 503


# ===========================================================================
# GET /api/v1/collections/{collection_name}/stats
# ===========================================================================


class TestGetCollectionStatsEndpoint:
    """Tests for GET /api/v1/collections/{name}/stats (MT-R-25 through MT-R-27)."""

    def test_happy_path(self):
        """MT-R-25: returns 200 with full stats."""
        stats = {
            "document_count": 10,
            "chunk_count": 150,
            "connector_breakdown": {"local_fs": 100, "confluence": 50},
        }
        with (
            patch("server.routes.documents.vector_db.get_collection_stats", return_value=stats),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/collections/MyCollection/stats")
            assert resp.status_code == 200
            body = resp.json()
            assert body["collection_name"] == "MyCollection"
            assert body["chunk_count"] == 150
            assert body["connector_breakdown"]["local_fs"] == 100

    def test_collection_not_found_404(self):
        """MT-R-26: Collection not found -> 404."""
        with (
            patch("server.routes.documents.vector_db.get_collection_stats", return_value=None),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/collections/ghost/stats")
            assert resp.status_code == 404
            body = resp.json()
            assert body["detail"]["error"]["code"] == "not_found"

    def test_weaviate_error_503(self):
        """MT-R-27: Weaviate error -> 503."""
        with (
            patch("server.routes.documents.vector_db.get_collection_stats", side_effect=RuntimeError("boom")),
            patch("server.routes.documents.resolve_tenant_id", return_value="test-tenant"),
        ):
            resp = _build_client().get("/api/v1/collections/MyCollection/stats")
            assert resp.status_code == 503
