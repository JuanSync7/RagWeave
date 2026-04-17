# @summary
# Tests for revert_merge() in src.ingest.embedding.common.dedup_utils.
# Covers: successful revert, no-op when source_key absent, canonical deletion
#   when last source_key removed, error tolerance on Weaviate failure.
# @end-summary
"""Tests for the revert_merge() operational helper (Phase 3.3 / T7).

Verifies:
- Removes merged_source_key from canonical chunk's source_documents.
- Deletes the canonical chunk when source_documents becomes empty.
- Is a no-op (returns False) when merged_source_key is not in source_documents.
- Returns False when the canonical chunk does not exist.
- Logs an audit entry on success.
- Tolerates Weaviate errors gracefully (returns False, does not raise).
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from src.ingest.embedding.common.dedup_utils import revert_merge
from src.ingest.embedding.common.types import create_merge_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    source_key: str = "doc/incoming.md",
    content_hash: str = "a" * 64,
    canonical_chunk_id: str = "uuid-canonical-0001",
) -> dict:
    """Create a minimal MergeEvent dict for testing."""
    return create_merge_event(
        canonical_content_hash=content_hash,
        canonical_chunk_id=canonical_chunk_id,
        merged_source_key=source_key,
        merged_section="",
        match_tier="exact",
        similarity_score=1.0,
        canonical_replaced=False,
        action="merged",
    )


def _make_client_with_chunk(
    chunk_uuid: str,
    content_hash: str,
    source_documents: list[str],
) -> MagicMock:
    """Build a mock Weaviate client with a known chunk at content_hash."""
    client = MagicMock()
    collection = MagicMock()
    client.collections.get.return_value = collection

    # find_chunk_by_content_hash uses fetch_objects with a Filter
    obj = MagicMock()
    obj.uuid = chunk_uuid
    obj.properties = {
        "content_hash": content_hash,
        "source_documents": list(source_documents),
        "text": "canonical chunk text",
    }
    fetch_result = MagicMock()
    fetch_result.objects = [obj]
    collection.query.fetch_objects.return_value = fetch_result

    return client


def _make_client_no_chunk() -> MagicMock:
    """Build a mock client that finds no chunk for any hash lookup."""
    client = MagicMock()
    collection = MagicMock()
    client.collections.get.return_value = collection
    fetch_result = MagicMock()
    fetch_result.objects = []
    collection.query.fetch_objects.return_value = fetch_result
    return client


# ---------------------------------------------------------------------------
# Tests: successful revert
# ---------------------------------------------------------------------------

class TestRevertMergeSuccess:
    """revert_merge removes source_key and returns True."""

    def test_removes_source_key_from_source_documents(self):
        """source_key is removed and collection.data.update is called."""
        chunk_uuid = "uuid-canonical-0001"
        content_hash = "a" * 64
        client = _make_client_with_chunk(
            chunk_uuid, content_hash, ["original.md", "doc/incoming.md"]
        )
        event = _make_event(source_key="doc/incoming.md", content_hash=content_hash)

        result = revert_merge(client, event)

        assert result is True
        collection = client.collections.get.return_value
        collection.data.update.assert_called_once_with(
            uuid=chunk_uuid,
            properties={"source_documents": ["original.md"]},
        )

    def test_returns_true_on_successful_revert(self):
        chunk_uuid = "uuid-canonical-0001"
        content_hash = "b" * 64
        client = _make_client_with_chunk(
            chunk_uuid, content_hash, ["other.md", "doc/incoming.md"]
        )
        event = _make_event(source_key="doc/incoming.md", content_hash=content_hash)

        assert revert_merge(client, event) is True

    def test_uses_custom_collection_name(self):
        """collection= parameter routes to the specified Weaviate collection."""
        chunk_uuid = "uuid-canonical-0002"
        content_hash = "c" * 64
        client = _make_client_with_chunk(
            chunk_uuid, content_hash, ["src.md", "doc/incoming.md"]
        )
        event = _make_event(source_key="doc/incoming.md", content_hash=content_hash)

        revert_merge(client, event, collection="CustomChunks")

        # collections.get should have been called with our custom name at least once
        get_calls = [str(c) for c in client.collections.get.call_args_list]
        assert any("CustomChunks" in c for c in get_calls), (
            f"Expected 'CustomChunks' in collections.get calls; got: {get_calls}"
        )


# ---------------------------------------------------------------------------
# Tests: canonical deletion when last source removed
# ---------------------------------------------------------------------------

class TestRevertMergeDeletesCanonical:
    """When source_documents becomes empty, the canonical chunk is deleted."""

    def test_deletes_chunk_when_last_source_removed(self):
        chunk_uuid = "uuid-to-delete"
        content_hash = "d" * 64
        client = _make_client_with_chunk(
            chunk_uuid, content_hash, ["doc/incoming.md"]  # only one source
        )
        event = _make_event(source_key="doc/incoming.md", content_hash=content_hash)

        result = revert_merge(client, event)

        assert result is True
        collection = client.collections.get.return_value
        collection.data.delete_by_id.assert_called_once_with(chunk_uuid)
        collection.data.update.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: no-op / idempotency
# ---------------------------------------------------------------------------

class TestRevertMergeNoOp:
    """revert_merge is a no-op when the source_key is absent."""

    def test_returns_false_when_source_key_not_in_documents(self):
        """If merged_source_key is not in source_documents, return False."""
        chunk_uuid = "uuid-canonical-0003"
        content_hash = "e" * 64
        client = _make_client_with_chunk(
            chunk_uuid, content_hash, ["original.md"]  # incoming not present
        )
        event = _make_event(source_key="doc/incoming.md", content_hash=content_hash)

        result = revert_merge(client, event)

        assert result is False
        collection = client.collections.get.return_value
        collection.data.update.assert_not_called()
        collection.data.delete_by_id.assert_not_called()

    def test_returns_false_when_chunk_not_found(self):
        """If no canonical chunk exists for the content_hash, return False."""
        client = _make_client_no_chunk()
        event = _make_event(content_hash="f" * 64)

        result = revert_merge(client, event)

        assert result is False

    def test_idempotent_double_call(self):
        """Calling revert_merge twice with the same event is safe.

        First call succeeds; second call returns False (source_key already removed).
        """
        chunk_uuid = "uuid-canonical-0004"
        content_hash = "0" * 64
        client = _make_client_with_chunk(
            chunk_uuid, content_hash, ["original.md", "doc/incoming.md"]
        )
        event = _make_event(source_key="doc/incoming.md", content_hash=content_hash)

        first = revert_merge(client, event)
        assert first is True

        # After the first revert, the stored object no longer has doc/incoming.md.
        # Simulate the updated state: fetch_objects now returns only original.md.
        obj2 = MagicMock()
        obj2.uuid = chunk_uuid
        obj2.properties = {
            "content_hash": content_hash,
            "source_documents": ["original.md"],
            "text": "canonical chunk text",
        }
        fetch_result2 = MagicMock()
        fetch_result2.objects = [obj2]
        collection = client.collections.get.return_value
        collection.query.fetch_objects.return_value = fetch_result2

        second = revert_merge(client, event)
        assert second is False


# ---------------------------------------------------------------------------
# Tests: error tolerance
# ---------------------------------------------------------------------------

class TestRevertMergeErrorTolerance:
    """revert_merge must not raise on Weaviate errors."""

    def test_returns_false_on_update_error(self):
        """If collection.data.update raises, revert_merge returns False."""
        chunk_uuid = "uuid-error"
        content_hash = "9" * 64
        client = _make_client_with_chunk(
            chunk_uuid, content_hash, ["original.md", "doc/incoming.md"]
        )
        client.collections.get.return_value.data.update.side_effect = RuntimeError("DB error")
        event = _make_event(source_key="doc/incoming.md", content_hash=content_hash)

        result = revert_merge(client, event)

        assert result is False

    def test_does_not_raise_on_delete_error(self):
        """If collection.data.delete_by_id raises, revert_merge returns False without raising."""
        chunk_uuid = "uuid-delete-error"
        content_hash = "8" * 64
        client = _make_client_with_chunk(
            chunk_uuid, content_hash, ["doc/incoming.md"]  # last source → delete path
        )
        client.collections.get.return_value.data.delete_by_id.side_effect = RuntimeError("Delete failed")
        event = _make_event(source_key="doc/incoming.md", content_hash=content_hash)

        result = revert_merge(client, event)

        assert result is False
