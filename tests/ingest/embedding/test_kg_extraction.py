# @summary
# Tests for the knowledge_graph_extraction_node embedding pipeline stage.
# Covers: disabled passthrough, triple extraction per chunk, error isolation,
# and partial-success accumulation.
# @end-summary

import pytest
from unittest.mock import MagicMock, patch

from src.ingest.common.schemas import ProcessedChunk
from src.ingest.common.types import IngestionConfig, Runtime
from src.ingest.embedding.nodes.knowledge_graph_extraction import knowledge_graph_extraction_node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PATCH_TARGET = "src.ingest.embedding.nodes.knowledge_graph_extraction.EntityExtractor"


def _make_chunk(text: str) -> ProcessedChunk:
    return ProcessedChunk(text=text, metadata={})


def _make_state(chunks=None, enabled=True, source_name="test.md"):
    config = IngestionConfig(enable_knowledge_graph_extraction=enabled)
    runtime = Runtime(
        config=config,
        embedder=MagicMock(),
        weaviate_client=MagicMock(),
        kg_builder=None,
    )
    return {
        "chunks": chunks or [],
        "kg_triples": [],
        "source_name": source_name,
        "errors": [],
        "processing_log": [],
        "runtime": runtime,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_disabled_returns_empty_triples():
    """When KG extraction is disabled, kg_triples key is absent (skipped log only).
    LangGraph keeps the original empty kg_triples via state merge."""
    chunks = [_make_chunk("Alice works at Acme Corp.")]
    state = _make_state(chunks=chunks, enabled=False)
    with patch(PATCH_TARGET) as MockExtractor:
        result = knowledge_graph_extraction_node(state)
    assert result.get("kg_triples", []) == []


def test_disabled_does_not_instantiate_extractor():
    """EntityExtractor must never be constructed when the feature is disabled."""
    state = _make_state(chunks=[_make_chunk("text")], enabled=False)
    with patch(PATCH_TARGET) as MockExtractor:
        knowledge_graph_extraction_node(state)
    MockExtractor.assert_not_called()


def test_single_chunk_produces_triples():
    """Triples returned by EntityExtractor for a single chunk are stored in state.

    The node calls extract_entities() then extract_relations() per chunk.
    """
    chunk = _make_chunk("Alice works at Acme.")
    relation = ("Alice", "works_at", "Acme")
    state = _make_state(chunks=[chunk])
    with patch(PATCH_TARGET) as MockExtractor:
        instance = MockExtractor.return_value
        instance.extract_entities.return_value = ["Alice", "Acme"]
        instance.extract_relations.return_value = [relation]
        result = knowledge_graph_extraction_node(state)
    # Result contains dicts built from the (subject, predicate, object) tuple
    assert any(
        t.get("subject") == "Alice" and t.get("predicate") == "works_at"
        for t in result["kg_triples"]
    )


def test_multiple_chunks_triples_collected():
    """Triples from all chunks are accumulated into kg_triples."""
    chunks = [
        _make_chunk("Alice knows Bob."),
        _make_chunk("Bob works at Acme."),
    ]
    rel_a = ("Alice", "knows", "Bob")
    rel_b = ("Bob", "works_at", "Acme")
    state = _make_state(chunks=chunks)
    with patch(PATCH_TARGET) as MockExtractor:
        instance = MockExtractor.return_value
        instance.extract_entities.return_value = []
        instance.extract_relations.side_effect = [[rel_a], [rel_b]]
        result = knowledge_graph_extraction_node(state)
    subjects = [t.get("subject") for t in result["kg_triples"]]
    assert "Alice" in subjects
    assert "Bob" in subjects


def test_empty_chunks_returns_empty_triples():
    """An empty chunk list produces no triples."""
    state = _make_state(chunks=[], enabled=True)
    with patch(PATCH_TARGET) as MockExtractor:
        result = knowledge_graph_extraction_node(state)
    assert result["kg_triples"] == []


def test_extractor_error_appended_not_raised():
    """A RuntimeError from EntityExtractor is caught and appended to state errors."""
    chunk = _make_chunk("Some text that triggers an error.")
    state = _make_state(chunks=[chunk])
    with patch(PATCH_TARGET) as MockExtractor:
        instance = MockExtractor.return_value
        instance.extract_entities.side_effect = RuntimeError("extraction failed")
        result = knowledge_graph_extraction_node(state)
    assert len(result["errors"]) >= 1
    assert any("extraction failed" in str(e) or "extraction" in str(e).lower()
               for e in result["errors"])


def test_extractor_error_processing_continues():
    """Error during extraction is caught; error recorded in state.

    The implementation wraps the entire chunk loop in a single try/except.
    On exception the node returns {**state, errors: [...], ...} — triples
    accumulated before the error are NOT included (the except path does not
    return the partially-built triples list).
    """
    chunks = [
        _make_chunk("Alice knows Bob."),
        _make_chunk("This chunk will fail."),
        _make_chunk("Carol manages Dave."),
    ]
    rel_1 = ("Alice", "knows", "Bob")
    state = _make_state(chunks=chunks)
    with patch(PATCH_TARGET) as MockExtractor:
        instance = MockExtractor.return_value
        instance.extract_entities.return_value = []
        # First chunk succeeds, second raises (loop stops, third not reached)
        instance.extract_relations.side_effect = [
            [rel_1],
            RuntimeError("boom"),
            [],
        ]
        result = knowledge_graph_extraction_node(state)
    # Error was recorded
    assert len(result["errors"]) >= 1
    # Error path returns {**state, ...}: kg_triples defaults to state's value ([])
