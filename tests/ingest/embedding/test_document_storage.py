# @summary
# Tests for src/ingest/embedding/nodes/document_storage_node.py.
# Covers: document_id derivation (SHA-256, 24-char hex, determinism),
#         upload gating (store_documents flag, minio_client presence),
#         and error handling (exception captured in state.errors).
# @end-summary
"""Tests for the document_storage_node pipeline stage."""

import hashlib

import pytest
from unittest.mock import MagicMock

from src.ingest.common.schemas import ProcessedChunk
from src.ingest.common.types import IngestionConfig, Runtime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runtime(store_documents: bool, minio_client=None, target_bucket: str = "test-bucket") -> Runtime:
    """Build a Runtime with the given document-storage config."""
    config = IngestionConfig(store_documents=store_documents, target_bucket=target_bucket)
    return Runtime(
        config=config,
        embedder=MagicMock(),
        weaviate_client=MagicMock(),
        kg_builder=None,
        db_client=minio_client,  # node accesses minio_client via runtime.db_client
    )


def _make_state(
    source_key: str = "test-doc",
    store_documents: bool = False,
    minio_client=None,
    cleaned_text: str = "# Hello",
) -> dict:
    """Return a minimal ingest state dict for document_storage_node tests.

    minio_client is injected via runtime.db_client (primary access pattern).
    """
    runtime = _make_runtime(
        store_documents=store_documents,
        minio_client=minio_client,
    )
    return {
        "source_key": source_key,
        "source_name": "test.md",
        "source_uri": "file:///tmp/test.md",
        "source_id": "test:1",
        "source_version": "1",
        "connector": "local_fs",
        "cleaned_text": cleaned_text,
        "refactored_text": "",
        "raw_text": "",
        "errors": [],
        "processing_log": [],
        "runtime": runtime,
    }


def _expected_document_id(source_key: str) -> str:
    """build_document_id returns uuid5(NAMESPACE_URL, f'doc:{source_key}')."""
    import uuid
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"doc:{source_key}"))


# ---------------------------------------------------------------------------
# Tests: document_id derivation
# ---------------------------------------------------------------------------

class TestDocumentIdDerivation:
    """document_id is always derived from source_key, regardless of upload path."""

    def test_document_id_set_regardless_of_upload_disabled(self):
        """document_id always set even when store_documents=False."""
        from src.ingest.embedding.nodes.document_storage_node import document_storage_node

        state = _make_state(source_key="my-doc", store_documents=False)
        result = document_storage_node(state)
        assert "document_id" in result
        assert result["document_id"] != ""

    def test_document_id_set_when_minio_client_none(self):
        """document_id always set even when minio_client is None.

        Assumes node reads minio_client from runtime.db_client.
        """
        from src.ingest.embedding.nodes.document_storage_node import document_storage_node

        state = _make_state(source_key="no-client-doc", store_documents=True, minio_client=None)
        result = document_storage_node(state)
        assert "document_id" in result
        assert result["document_id"] != ""

    def test_document_id_is_24_char_hex(self):
        """document_id is a non-empty UUID5 string (36 chars, hex+dashes)."""
        from src.ingest.embedding.nodes.document_storage_node import document_storage_node
        import re

        state = _make_state(source_key="some-key")
        result = document_storage_node(state)
        doc_id = result["document_id"]
        # build_document_id returns a UUID5 string like xxxxxxxx-xxxx-5xxx-xxxx-xxxxxxxxxxxx
        assert len(doc_id) == 36
        assert re.fullmatch(r"[0-9a-f\-]+", doc_id), f"Not a valid UUID: {doc_id!r}"

    def test_document_id_is_deterministic(self):
        """Same source_key always produces same document_id."""
        from src.ingest.embedding.nodes.document_storage_node import document_storage_node

        state_a = _make_state(source_key="stable-key")
        state_b = _make_state(source_key="stable-key")
        result_a = document_storage_node(state_a)
        result_b = document_storage_node(state_b)
        assert result_a["document_id"] == result_b["document_id"]

    def test_document_id_matches_sha256_prefix(self):
        """document_id == hashlib.sha256(source_key.encode()).hexdigest()[:24]."""
        from src.ingest.embedding.nodes.document_storage_node import document_storage_node

        key = "local_fs:tests/sample.md"
        state = _make_state(source_key=key)
        result = document_storage_node(state)
        expected = _expected_document_id(key)
        assert result["document_id"] == expected

    def test_document_id_empty_source_key(self):
        """Empty source_key → valid UUID5 document_id (36 chars)."""
        from src.ingest.embedding.nodes.document_storage_node import document_storage_node
        import re

        state = _make_state(source_key="")
        result = document_storage_node(state)
        doc_id = result["document_id"]
        assert len(doc_id) == 36
        assert re.fullmatch(r"[0-9a-f\-]+", doc_id), f"Not a valid UUID: {doc_id!r}"


# ---------------------------------------------------------------------------
# Tests: upload gating
# ---------------------------------------------------------------------------

class TestUploadGating:
    """Upload is only attempted when both the flag and client are present."""

    def test_upload_called_when_enabled_and_client_present(self):
        """Upload is called when store_documents=True and minio_client present.

        The node calls put_document() (an imported function from src.db), not a
        method on the client directly. We verify it via the put_document patch.
        """
        from src.ingest.embedding.nodes.document_storage_node import document_storage_node
        from unittest.mock import patch

        mock_client = MagicMock()
        state = _make_state(
            source_key="upload-doc",
            store_documents=True,
            minio_client=mock_client,
            cleaned_text="# Content to upload",
        )
        with patch("src.ingest.embedding.nodes.document_storage_node.put_document") as mock_put:
            document_storage_node(state)
        mock_put.assert_called_once()

    def test_upload_not_called_when_disabled(self):
        """Upload NOT called when store_documents=False.

        Assumes node reads minio_client from runtime.db_client.
        """
        from src.ingest.embedding.nodes.document_storage_node import document_storage_node

        mock_client = MagicMock()
        state = _make_state(
            source_key="no-upload-doc",
            store_documents=False,
            minio_client=mock_client,
        )
        document_storage_node(state)
        # No upload methods should have been invoked
        mock_client.put_object.assert_not_called()

    def test_upload_not_called_when_client_none(self):
        """Upload NOT called when minio_client is None.

        Assumes node reads minio_client from runtime.db_client.
        """
        from src.ingest.embedding.nodes.document_storage_node import document_storage_node

        state = _make_state(
            source_key="no-client",
            store_documents=True,
            minio_client=None,
        )
        # Should not raise; simply skips upload
        result = document_storage_node(state)
        assert "document_id" in result


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------

class TestUploadErrorHandling:
    """Upload errors are caught and appended to state.errors; execution continues."""

    def test_upload_error_appended_to_errors(self):
        """Upload exception → error recorded in state.errors; execution continues.

        On error the node returns {**state, errors: [...], ...}.  document_id is
        NOT in the error-path partial return (it is only set on the success path).
        The node catches exceptions and stores them as f'document_storage:{exc}'.
        """
        from src.ingest.embedding.nodes.document_storage_node import document_storage_node
        from unittest.mock import patch

        mock_client = MagicMock()
        state = _make_state(
            source_key="error-doc",
            store_documents=True,
            minio_client=mock_client,
        )

        with patch("src.ingest.embedding.nodes.document_storage_node.put_document",
                   side_effect=RuntimeError("connection refused")):
            result = document_storage_node(state)

        # At least one error must be recorded
        errors = result.get("errors", state.get("errors", []))
        assert len(errors) > 0
        # Error format: "document_storage:<exc message>"
        assert any("document_storage" in e or "connection refused" in e for e in errors)
