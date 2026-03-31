# @summary
# Schema contract tests for Document & Collection Management Pydantic models (FR-3068).
# Exports: (test functions)
# Deps: pytest, pydantic, server.schemas
# @end-summary
"""Contract tests for document management Pydantic schemas.

Each new model is tested for:
  - Round-trip serialization (instantiate -> model_dump -> assert fields).
  - Required field omission (ValidationError on missing required field).
  - Default values for Optional fields.
"""

import pytest
from pydantic import ValidationError

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


# ---------------------------------------------------------------------------
# DocumentSummary
# ---------------------------------------------------------------------------


class TestDocumentSummary:
    """FR-3060: DocumentSummary model contract."""

    def test_round_trip(self):
        obj = DocumentSummary(
            document_id="abc-123",
            source="readme.md",
            source_key="docs/readme.md",
            connector="local_fs",
        )
        d = obj.model_dump()
        assert d["document_id"] == "abc-123"
        assert d["source"] == "readme.md"
        assert d["source_key"] == "docs/readme.md"
        assert d["connector"] == "local_fs"
        assert d["chunk_count"] is None
        assert d["ingested_at"] is None

    def test_optional_fields_populated(self):
        obj = DocumentSummary(
            document_id="abc",
            source="s",
            source_key="sk",
            connector="confluence",
            chunk_count=42,
            ingested_at="2026-01-01T00:00:00",
        )
        assert obj.chunk_count == 42
        assert obj.ingested_at == "2026-01-01T00:00:00"

    def test_missing_required_document_id(self):
        with pytest.raises(ValidationError):
            DocumentSummary(source="s", source_key="sk", connector="local_fs")

    def test_missing_required_source(self):
        with pytest.raises(ValidationError):
            DocumentSummary(document_id="x", source_key="sk", connector="local_fs")

    def test_missing_required_source_key(self):
        with pytest.raises(ValidationError):
            DocumentSummary(document_id="x", source="s", connector="local_fs")

    def test_missing_required_connector(self):
        with pytest.raises(ValidationError):
            DocumentSummary(document_id="x", source="s", source_key="sk")


# ---------------------------------------------------------------------------
# DocumentListResponse
# ---------------------------------------------------------------------------


class TestDocumentListResponse:
    """FR-3061: DocumentListResponse model contract."""

    def test_round_trip(self):
        obj = DocumentListResponse(total=0, limit=20, offset=0)
        d = obj.model_dump()
        assert d["documents"] == []
        assert d["total"] == 0
        assert d["limit"] == 20
        assert d["offset"] == 0

    def test_documents_default_empty(self):
        obj = DocumentListResponse(total=5, limit=10, offset=0)
        assert obj.documents == []

    def test_with_documents(self):
        doc = DocumentSummary(
            document_id="a", source="s", source_key="sk", connector="c"
        )
        obj = DocumentListResponse(documents=[doc], total=1, limit=20, offset=0)
        assert len(obj.documents) == 1
        assert obj.documents[0].document_id == "a"

    def test_missing_required_total(self):
        with pytest.raises(ValidationError):
            DocumentListResponse(limit=20, offset=0)

    def test_missing_required_limit(self):
        with pytest.raises(ValidationError):
            DocumentListResponse(total=0, offset=0)

    def test_missing_required_offset(self):
        with pytest.raises(ValidationError):
            DocumentListResponse(total=0, limit=20)


# ---------------------------------------------------------------------------
# DocumentDetailResponse
# ---------------------------------------------------------------------------


class TestDocumentDetailResponse:
    """FR-3062: DocumentDetailResponse model contract."""

    def test_round_trip(self):
        obj = DocumentDetailResponse(
            document_id="id-1",
            content="# Hello",
            metadata={"source_key": "foo"},
        )
        d = obj.model_dump()
        assert d["document_id"] == "id-1"
        assert d["content"] == "# Hello"
        assert d["metadata"] == {"source_key": "foo"}
        assert d["chunk_count"] is None

    def test_with_chunk_count(self):
        obj = DocumentDetailResponse(
            document_id="id-1",
            content="text",
            metadata={},
            chunk_count=10,
        )
        assert obj.chunk_count == 10

    def test_missing_required_content(self):
        with pytest.raises(ValidationError):
            DocumentDetailResponse(document_id="x", metadata={})

    def test_missing_required_metadata(self):
        with pytest.raises(ValidationError):
            DocumentDetailResponse(document_id="x", content="text")


# ---------------------------------------------------------------------------
# DocumentUrlResponse
# ---------------------------------------------------------------------------


class TestDocumentUrlResponse:
    """FR-3063: DocumentUrlResponse model contract."""

    def test_round_trip(self):
        obj = DocumentUrlResponse(
            document_id="id-1",
            url="https://minio.local/bucket/id-1.md?sig=abc",
            expires_in=3600,
        )
        d = obj.model_dump()
        assert d["document_id"] == "id-1"
        assert d["url"].startswith("https://")
        assert d["expires_in"] == 3600

    def test_missing_required_url(self):
        with pytest.raises(ValidationError):
            DocumentUrlResponse(document_id="x", expires_in=3600)

    def test_missing_required_expires_in(self):
        with pytest.raises(ValidationError):
            DocumentUrlResponse(document_id="x", url="https://example.com")


# ---------------------------------------------------------------------------
# SourceSummary
# ---------------------------------------------------------------------------


class TestSourceSummary:
    """FR-3064: SourceSummary model contract."""

    def test_round_trip(self):
        obj = SourceSummary(
            source="docs/readme.md",
            connector="local_fs",
            document_count=3,
            chunk_count=25,
        )
        d = obj.model_dump()
        assert d["source"] == "docs/readme.md"
        assert d["connector"] == "local_fs"
        assert d["document_count"] == 3
        assert d["chunk_count"] == 25

    def test_missing_required_document_count(self):
        with pytest.raises(ValidationError):
            SourceSummary(source="s", connector="c", chunk_count=1)

    def test_missing_required_chunk_count(self):
        with pytest.raises(ValidationError):
            SourceSummary(source="s", connector="c", document_count=1)


# ---------------------------------------------------------------------------
# SourceListResponse
# ---------------------------------------------------------------------------


class TestSourceListResponse:
    """FR-3065: SourceListResponse model contract."""

    def test_round_trip(self):
        obj = SourceListResponse(total=0, limit=50, offset=0)
        d = obj.model_dump()
        assert d["sources"] == []
        assert d["total"] == 0

    def test_sources_default_empty(self):
        obj = SourceListResponse(total=0, limit=50, offset=0)
        assert obj.sources == []

    def test_missing_required_total(self):
        with pytest.raises(ValidationError):
            SourceListResponse(limit=50, offset=0)


# ---------------------------------------------------------------------------
# CollectionItem
# ---------------------------------------------------------------------------


class TestCollectionItem:
    """FR-3067: CollectionItem model contract."""

    def test_round_trip(self):
        obj = CollectionItem(collection_name="RAGDocuments", chunk_count=150)
        d = obj.model_dump()
        assert d["collection_name"] == "RAGDocuments"
        assert d["chunk_count"] == 150

    def test_missing_required_collection_name(self):
        with pytest.raises(ValidationError):
            CollectionItem(chunk_count=10)

    def test_missing_required_chunk_count(self):
        with pytest.raises(ValidationError):
            CollectionItem(collection_name="test")


# ---------------------------------------------------------------------------
# CollectionStatsResponse
# ---------------------------------------------------------------------------


class TestCollectionStatsResponse:
    """FR-3066: CollectionStatsResponse model contract."""

    def test_round_trip(self):
        obj = CollectionStatsResponse(
            collection_name="RAGDocuments",
            document_count=5,
            chunk_count=100,
            connector_breakdown={"local_fs": 80, "confluence": 20},
        )
        d = obj.model_dump()
        assert d["collection_name"] == "RAGDocuments"
        assert d["document_count"] == 5
        assert d["chunk_count"] == 100
        assert d["connector_breakdown"]["local_fs"] == 80

    def test_missing_required_connector_breakdown(self):
        with pytest.raises(ValidationError):
            CollectionStatsResponse(
                collection_name="test", document_count=1, chunk_count=10
            )

    def test_missing_required_chunk_count(self):
        with pytest.raises(ValidationError):
            CollectionStatsResponse(
                collection_name="test",
                document_count=1,
                connector_breakdown={},
            )


# ---------------------------------------------------------------------------
# CollectionListResponse
# ---------------------------------------------------------------------------


class TestCollectionListResponse:
    """FR-3067: CollectionListResponse model contract."""

    def test_round_trip(self):
        item = CollectionItem(collection_name="test", chunk_count=10)
        obj = CollectionListResponse(collections=[item])
        d = obj.model_dump()
        assert len(d["collections"]) == 1
        assert d["collections"][0]["collection_name"] == "test"

    def test_empty_collections(self):
        obj = CollectionListResponse(collections=[])
        assert obj.collections == []

    def test_missing_required_collections(self):
        with pytest.raises(ValidationError):
            CollectionListResponse()
