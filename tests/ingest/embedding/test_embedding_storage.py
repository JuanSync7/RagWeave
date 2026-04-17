# @summary
# Tests for the embedding_storage_node embedding pipeline stage.
# Covers: empty-chunk short-circuit, single/multi-chunk storage, update_mode
# delete-before-insert ordering, collection routing, error isolation,
# and stored_count accuracy.
# @end-summary

import pytest
from unittest.mock import MagicMock, call, patch

from src.ingest.common.schemas import ProcessedChunk
from src.ingest.common.types import IngestionConfig, Runtime
from src.ingest.embedding.nodes.embedding_storage import embedding_storage_node

# Patch targets — functions imported at module level in embedding_storage
_ADD_DOCS = "src.ingest.embedding.nodes.embedding_storage.add_documents"
_DELETE = "src.ingest.embedding.nodes.embedding_storage.delete_by_source_key"
_ENSURE = "src.ingest.embedding.nodes.embedding_storage.ensure_collection"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(text: str = "sample chunk text") -> ProcessedChunk:
    return ProcessedChunk(text=text, metadata={})


def _make_state(
    chunks=None,
    update_mode=False,
    target_collection="Docs",
    source_key="doc-001",
    source_name="doc.md",
):
    config = IngestionConfig(
        update_mode=update_mode,
        target_collection=target_collection,
    )
    mock_weaviate = MagicMock()
    mock_embedder = MagicMock()
    # embed_documents returns a list of vectors (one per chunk)
    mock_embedder.embed_documents.return_value = [[0.1, 0.2, 0.3]]
    runtime = Runtime(
        config=config,
        embedder=mock_embedder,
        weaviate_client=mock_weaviate,
        kg_builder=None,
    )
    return {
        "chunks": chunks or [],
        "source_key": source_key,
        "source_name": source_name,
        "stored_count": 0,
        "errors": [],
        "processing_log": [],
        "runtime": runtime,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_chunks_returns_zero_stored():
    """With no chunks, stored_count must be 0."""
    state = _make_state(chunks=[])
    result = embedding_storage_node(state)
    assert result["stored_count"] == 0


def test_empty_chunks_no_weaviate_call():
    """With no chunks, add_documents must not be called."""
    with patch(_ADD_DOCS) as mock_add, patch(_ENSURE):
        state = _make_state(chunks=[])
        embedding_storage_node(state)
    mock_add.assert_not_called()


def test_single_chunk_stored():
    """A single chunk is embedded and inserted; stored_count becomes 1."""
    state = _make_state(chunks=[_make_chunk()])
    state["runtime"].embedder.embed_documents.return_value = [[0.1, 0.2, 0.3]]
    with patch(_ADD_DOCS, return_value=1) as mock_add, patch(_ENSURE):
        result = embedding_storage_node(state)
    assert result["stored_count"] == 1
    mock_add.assert_called_once()


def test_multiple_chunks_all_stored():
    """All three chunks are stored when no errors occur; stored_count == 3."""
    chunks = [_make_chunk(f"chunk {i}") for i in range(3)]
    state = _make_state(chunks=chunks)
    state["runtime"].embedder.embed_documents.return_value = [
        [0.1] * 3, [0.2] * 3, [0.3] * 3
    ]
    with patch(_ADD_DOCS, return_value=3) as mock_add, patch(_ENSURE):
        result = embedding_storage_node(state)
    assert result["stored_count"] == 3
    mock_add.assert_called_once()


def test_update_mode_delete_called_before_insert():
    """In update mode, delete_by_source_key must be called before add_documents."""
    chunks = [_make_chunk()]
    state = _make_state(chunks=chunks, update_mode=True)
    state["runtime"].embedder.embed_documents.return_value = [[0.1, 0.2, 0.3]]
    call_order = []
    with patch(_DELETE, side_effect=lambda *a, **kw: call_order.append("delete")) as mock_del, \
         patch(_ADD_DOCS, side_effect=lambda *a, **kw: call_order.append("add") or 1) as mock_add, \
         patch(_ENSURE):
        embedding_storage_node(state)
    assert "delete" in call_order, "Expected delete_by_source_key to be called"
    assert "add" in call_order, "Expected add_documents to be called"
    assert call_order.index("delete") < call_order.index("add"), (
        "delete must occur before add in update mode"
    )


def test_update_mode_delete_called_once():
    """In update mode, delete is called exactly once (not per-chunk)."""
    chunks = [_make_chunk(f"chunk {i}") for i in range(3)]
    state = _make_state(chunks=chunks, update_mode=True)
    state["runtime"].embedder.embed_documents.return_value = [
        [0.1] * 3, [0.2] * 3, [0.3] * 3
    ]
    with patch(_DELETE) as mock_del, patch(_ADD_DOCS, return_value=3), patch(_ENSURE):
        embedding_storage_node(state)
    mock_del.assert_called_once()


def test_non_update_mode_delete_not_called():
    """When update_mode is False, delete must never be called."""
    chunks = [_make_chunk()]
    state = _make_state(chunks=chunks, update_mode=False)
    state["runtime"].embedder.embed_documents.return_value = [[0.1, 0.2, 0.3]]
    with patch(_DELETE) as mock_del, patch(_ADD_DOCS, return_value=1), patch(_ENSURE):
        embedding_storage_node(state)
    mock_del.assert_not_called()


def test_correct_collection_used():
    """The configured target_collection name is passed to add_documents."""
    chunks = [_make_chunk()]
    state = _make_state(chunks=chunks, target_collection="MyCollection")
    state["runtime"].embedder.embed_documents.return_value = [[0.1, 0.2, 0.3]]
    with patch(_ADD_DOCS, return_value=1) as mock_add, patch(_ENSURE):
        embedding_storage_node(state)
    call_kwargs = mock_add.call_args
    # collection is passed as keyword arg
    assert call_kwargs is not None
    passed_collection = (
        call_kwargs.kwargs.get("collection")
        or (call_kwargs.args[2] if len(call_kwargs.args) > 2 else None)
    )
    assert passed_collection == "MyCollection"


def test_embed_error_appended_not_raised():
    """An embed_documents error is caught and an error message is appended to state errors."""
    chunk = _make_chunk()
    state = _make_state(chunks=[chunk])
    state["runtime"].embedder.embed_documents.side_effect = RuntimeError("embed boom")
    with patch(_ENSURE):
        result = embedding_storage_node(state)
    assert len(result["errors"]) >= 1
    error_str = " ".join(str(e) for e in result["errors"])
    assert "embed" in error_str.lower() or "embedding" in error_str.lower()


def test_partial_success_stored_count():
    """add_documents returning 2 means stored_count == 2."""
    chunks = [_make_chunk(f"chunk {i}") for i in range(3)]
    state = _make_state(chunks=chunks)
    state["runtime"].embedder.embed_documents.return_value = [
        [0.1] * 3, [0.2] * 3, [0.3] * 3
    ]
    # Simulate add_documents storing only 2 of 3
    with patch(_ADD_DOCS, return_value=2) as mock_add, patch(_ENSURE):
        result = embedding_storage_node(state)
    assert result["stored_count"] == 2


def test_all_chunks_fail_stored_count_zero():
    """When embed_documents fails, stored_count is 0 and error is recorded."""
    chunks = [_make_chunk(f"chunk {i}") for i in range(3)]
    state = _make_state(chunks=chunks)
    state["runtime"].embedder.embed_documents.side_effect = RuntimeError("always fails")
    with patch(_ENSURE):
        result = embedding_storage_node(state)
    assert result.get("stored_count", 0) == 0
    assert len(result.get("errors", [])) >= 1


def test_should_skip_flag_skips_storage():
    """When should_skip=True the node returns stored_count=0 without calling add_documents."""
    chunks = [_make_chunk("some text")]
    state = _make_state(chunks=chunks)
    state["should_skip"] = True
    with patch(_ADD_DOCS) as mock_add, patch(_ENSURE):
        result = embedding_storage_node(state)
    assert result["stored_count"] == 0
    mock_add.assert_not_called()


def test_vector_store_raises_propagated_as_error():
    """When add_documents raises, the error is caught and stored in state.errors."""
    chunks = [_make_chunk()]
    state = _make_state(chunks=chunks)
    state["runtime"].embedder.embed_documents.return_value = [[0.1, 0.2, 0.3]]
    with patch(_ADD_DOCS, side_effect=RuntimeError("weaviate down")), patch(_ENSURE):
        result = embedding_storage_node(state)
    assert len(result.get("errors", [])) >= 1
    assert any("weaviate down" in str(e) or "embedding_storage" in str(e)
               for e in result["errors"])


# ---------------------------------------------------------------------------
# Tests: partial state resilience (optional upstream fields absent/None)
# ---------------------------------------------------------------------------

def test_enriched_content_fallback_to_chunk_text():
    """When enriched_content metadata is absent, node falls back to chunk.text."""
    chunk = _make_chunk("raw chunk text")
    # No enriched_content metadata key set (simulates prior node being skipped).
    assert "enriched_content" not in chunk.metadata
    state = _make_state(chunks=[chunk])
    state["runtime"].embedder.embed_documents.return_value = [[0.1, 0.2, 0.3]]
    with patch(_ADD_DOCS, return_value=1) as mock_add, patch(_ENSURE):
        result = embedding_storage_node(state)
    # Node must not raise; must attempt storage.
    assert result.get("stored_count", 0) == 1
    # Verify the text passed to embedder is the chunk's raw text.
    embed_call_args = state["runtime"].embedder.embed_documents.call_args
    texts_passed = embed_call_args[0][0]
    assert texts_passed == ["raw chunk text"]
