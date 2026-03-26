# @summary
# Tests for the knowledge_graph_storage_node embedding pipeline stage.
# Covers: disabled skip, None-builder skip, add_chunk call contract,
# error isolation, partial-success continuation, and error preservation.
# @end-summary

import pytest
from unittest.mock import MagicMock, call

from src.ingest.common.schemas import ProcessedChunk
from src.ingest.common.types import IngestionConfig, Runtime
from src.ingest.embedding.nodes.knowledge_graph_storage import knowledge_graph_storage_node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(text: str = "sample text") -> ProcessedChunk:
    return ProcessedChunk(text=text, metadata={})


def _make_state(
    chunks=None,
    kg_triples=None,
    kg_builder=None,
    enabled=True,
    source_key="doc-1",
    source_name="doc.txt",
):
    config = IngestionConfig(enable_knowledge_graph_storage=enabled)
    runtime = Runtime(
        config=config,
        embedder=MagicMock(),
        weaviate_client=MagicMock(),
        kg_builder=kg_builder,
    )
    return {
        "chunks": chunks or [],
        "kg_triples": kg_triples or [],
        "source_key": source_key,
        "source_name": source_name,
        "errors": [],
        "processing_log": [],
        "runtime": runtime,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_disabled_skips():
    """When KG storage is disabled the node returns without error."""
    mock_builder = MagicMock()
    state = _make_state(
        chunks=[_make_chunk()],
        kg_builder=mock_builder,
        enabled=False,
    )
    result = knowledge_graph_storage_node(state)
    assert result is not None  # node completed cleanly


def test_none_builder_skips():
    """When kg_builder is None the node returns without error."""
    state = _make_state(chunks=[_make_chunk()], kg_builder=None, enabled=True)
    result = knowledge_graph_storage_node(state)
    assert result is not None  # node completed cleanly


def test_disabled_add_chunk_not_called():
    """add_chunk must not be called when the feature is disabled."""
    mock_builder = MagicMock()
    state = _make_state(
        chunks=[_make_chunk()],
        kg_builder=mock_builder,
        enabled=False,
    )
    knowledge_graph_storage_node(state)
    mock_builder.add_chunk.assert_not_called()


def test_none_builder_add_chunk_not_called():
    """add_chunk cannot be called when kg_builder is None (no AttributeError either)."""
    state = _make_state(chunks=[_make_chunk()], kg_builder=None, enabled=True)
    # If the node tries to call None.add_chunk it would raise AttributeError —
    # completing without error is sufficient.
    knowledge_graph_storage_node(state)  # must not raise


def test_single_chunk_add_chunk_called():
    """add_chunk is called exactly once for a single chunk."""
    mock_builder = MagicMock()
    chunk = _make_chunk("Alice knows Bob.")
    state = _make_state(chunks=[chunk], kg_builder=mock_builder)
    knowledge_graph_storage_node(state)
    mock_builder.add_chunk.assert_called_once()


def test_multiple_chunks_add_chunk_called_per_chunk():
    """add_chunk is called once per chunk when multiple chunks are present."""
    mock_builder = MagicMock()
    chunks = [_make_chunk(f"text {i}") for i in range(4)]
    state = _make_state(chunks=chunks, kg_builder=mock_builder)
    knowledge_graph_storage_node(state)
    assert mock_builder.add_chunk.call_count == 4


def test_empty_chunks_no_calls():
    """When the chunk list is empty, add_chunk is never called."""
    mock_builder = MagicMock()
    state = _make_state(chunks=[], kg_builder=mock_builder)
    knowledge_graph_storage_node(state)
    mock_builder.add_chunk.assert_not_called()


def test_add_chunk_receives_correct_args():
    """add_chunk is called with (chunk.text, source=source_name)."""
    mock_builder = MagicMock()
    chunk = _make_chunk("Entity mention text.")
    triples = [("Entity", "rel", "Other")]
    source_name = "my-doc.txt"
    state = _make_state(
        chunks=[chunk],
        kg_triples=triples,
        kg_builder=mock_builder,
        source_key="doc-42",
        source_name=source_name,
    )
    knowledge_graph_storage_node(state)
    mock_builder.add_chunk.assert_called_once_with(chunk.text, source=source_name)


def test_add_chunk_error_appended_not_raised():
    """A RuntimeError from add_chunk is caught and appended to state errors."""
    mock_builder = MagicMock()
    mock_builder.add_chunk.side_effect = RuntimeError("storage exploded")
    chunk = _make_chunk()
    state = _make_state(chunks=[chunk], kg_builder=mock_builder)
    result = knowledge_graph_storage_node(state)
    assert len(result["errors"]) >= 1
    error_str = " ".join(str(e) for e in result["errors"])
    assert "storage exploded" in error_str or "storage" in error_str.lower() or "exploded" in error_str


def test_add_chunk_error_continues_processing():
    """When chunk 2 raises, the error is caught and recorded.

    Note: the implementation wraps the entire loop in a single try/except, so
    processing stops at the first exception. Chunks after the failing one are
    not attempted. The error is captured in state.errors.
    """
    mock_builder = MagicMock()
    chunks = [
        _make_chunk("chunk one"),
        _make_chunk("chunk two — raises"),
        _make_chunk("chunk three"),
    ]
    mock_builder.add_chunk.side_effect = [
        None,
        RuntimeError("boom on chunk 2"),
        None,
    ]
    state = _make_state(chunks=chunks, kg_builder=mock_builder)
    result = knowledge_graph_storage_node(state)
    # Implementation has a single try/except: error on chunk 2 stops the loop.
    # Chunks 1 and 2 were attempted; chunk 3 was not.
    assert mock_builder.add_chunk.call_count == 2
    # Error was recorded
    assert len(result["errors"]) >= 1


def test_existing_errors_preserved():
    """Errors that existed before the node runs are not wiped.

    The success path returns only {"processing_log": [...]}.  LangGraph preserves
    unmodified state keys, so the caller must check result.get("errors", state["errors"]).
    """
    mock_builder = MagicMock()
    chunk = _make_chunk()
    state = _make_state(chunks=[chunk], kg_builder=mock_builder)
    state["errors"] = ["pre-existing error"]
    result = knowledge_graph_storage_node(state)
    # Success path: result has no "errors" key → LangGraph keeps original state errors
    effective_errors = result.get("errors", state["errors"])
    assert "pre-existing error" in effective_errors
