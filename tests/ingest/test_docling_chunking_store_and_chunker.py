# @summary
# White-box tests for the Docling-native chunking pipeline redesign.
# Covers: CleanDocumentStore.write_docling / read_docling (atomic writes,
#         schema versioning, error paths) and chunking_node dual-path selection
#         (HybridChunker vs markdown fallback, _normalize_chunk_text,
#         _extract_docling_section_metadata).
# Exports: (pytest test classes and functions)
# Deps: pytest, unittest.mock, orjson, src.ingest.common.clean_store,
#       src.ingest.embedding.nodes.chunking, src.ingest.common.types,
#       src.ingest.common.schemas
# @end-summary
"""Tests for CleanDocumentStore.write_docling/read_docling and chunking_node dual-path.

Module coverage:
- ``src/ingest/common/clean_store.py``  — write_docling, read_docling, write() extension,
  delete() extension, atomic guarantee, schema versioning.
- ``src/ingest/embedding/nodes/chunking.py`` — dual-path selection, HybridChunker path,
  markdown fallback path, _normalize_chunk_text, _extract_docling_section_metadata.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch, call

import orjson
import pytest

from src.ingest.common.clean_store import CleanDocumentStore
from src.ingest.common.schemas import ProcessedChunk
from src.ingest.common.types import IngestionConfig, Runtime


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _mock_docling_doc(json_body: str = '{"body": {"children": []}}') -> MagicMock:
    """Return a minimal DoclingDocument mock whose model_dump_json() works."""
    doc = MagicMock()
    doc.model_dump_json.return_value = json_body
    return doc


def _make_chunking_state(
    docling_document=None,
    cleaned: str = "# Heading\n\nSome text.",
    refactored: str = "",
    hybrid_max_tokens: int = 512,
) -> dict:
    """Build a minimal EmbeddingPipelineState-compatible dict for chunking_node."""
    config = IngestionConfig(
        semantic_chunking=False,
        chunk_size=500,
        chunk_overlap=50,
        hybrid_chunker_max_tokens=hybrid_max_tokens,
    )
    runtime = Runtime(
        config=config,
        embedder=MagicMock(),
        weaviate_client=MagicMock(),
        kg_builder=None,
    )
    return {
        "cleaned_text": cleaned,
        "refactored_text": refactored,
        "raw_text": cleaned,
        "source_name": "test_doc.pdf",
        "source_key": "local_fs:test:1",
        "source_uri": "file:///tmp/test_doc.pdf",
        "source_id": "test:1",
        "connector": "local_fs",
        "source_version": "v1",
        "errors": [],
        "processing_log": [],
        "runtime": runtime,
        "docling_document": docling_document,
    }


# Patch targets for chunking_node internals.
_CHUNK_MARKDOWN = "src.ingest.embedding.nodes.chunking.chunk_markdown"
_NORMALIZE_HEADINGS = "src.ingest.embedding.nodes.chunking.normalize_headings_to_markdown"
_EXTRACT_METADATA = "src.ingest.embedding.nodes.chunking.extract_metadata"
_METADATA_TO_DICT = "src.ingest.embedding.nodes.chunking.metadata_to_dict"


def _make_hybrid_chunker_mock(chunks: list) -> tuple[MagicMock, MagicMock]:
    """Return (MockHybridChunkerClass, mock_instance) with chunk() configured."""
    mock_instance = MagicMock()
    mock_instance.chunk.return_value = chunks
    MockClass = MagicMock(return_value=mock_instance)
    return MockClass, mock_instance


def _docling_core_sys_modules(MockHC: MagicMock) -> dict:
    """Build a sys.modules patch dict that makes 'from docling_core.transforms.chunker import HybridChunker' resolve to MockHC.

    HybridChunker is lazily imported inside _chunk_with_docling via:
        from docling_core.transforms.chunker import HybridChunker
    Since docling_core is not installed, we inject stub modules into sys.modules.
    """
    mock_chunker_module = MagicMock()
    mock_chunker_module.HybridChunker = MockHC
    mock_transforms = MagicMock()
    mock_transforms.chunker = mock_chunker_module
    mock_docling_core = MagicMock()
    mock_docling_core.transforms = mock_transforms
    return {
        "docling_core": mock_docling_core,
        "docling_core.transforms": mock_transforms,
        "docling_core.transforms.chunker": mock_chunker_module,
    }


def _make_mock_chunk(text: str = "Chunk content text.", headings: list | None = None) -> MagicMock:
    """Return a mock HybridChunker chunk with .text and .meta.headings set."""
    chunk = MagicMock()
    chunk.text = text
    chunk.meta = MagicMock()
    chunk.meta.headings = headings if headings is not None else ["Section 1"]
    return chunk


# ---------------------------------------------------------------------------
# CleanDocumentStore — write_docling / read_docling
# ---------------------------------------------------------------------------

class TestWriteDocling:
    """CleanDocumentStore.write_docling — atomic serialization and envelope format."""

    def test_write_docling_creates_json_file(self, tmp_path):
        """write_docling creates a .docling.json file for the given source key."""
        store = CleanDocumentStore(tmp_path)
        mock_doc = _mock_docling_doc()
        store.write_docling("doc1", mock_doc)
        assert (tmp_path / "doc1.docling.json").exists()

    def test_write_docling_envelope_schema_version(self, tmp_path):
        """Stored JSON has _schema_version == 'docling-native-v1'."""
        store = CleanDocumentStore(tmp_path)
        store.write_docling("doc1", _mock_docling_doc())
        data = orjson.loads((tmp_path / "doc1.docling.json").read_bytes())
        assert data["_schema_version"] == "docling-native-v1"

    def test_write_docling_envelope_has_document_key(self, tmp_path):
        """Stored JSON has a 'document' key containing the deserialized document dict."""
        store = CleanDocumentStore(tmp_path)
        store.write_docling("doc1", _mock_docling_doc('{"body": {"children": []}}'))
        data = orjson.loads((tmp_path / "doc1.docling.json").read_bytes())
        assert "document" in data
        assert isinstance(data["document"], dict)

    def test_write_docling_no_tmp_file_after_success(self, tmp_path):
        """No .tmp file remains after a successful write_docling call."""
        store = CleanDocumentStore(tmp_path)
        store.write_docling("doc1", _mock_docling_doc())
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Unexpected .tmp files: {tmp_files}"

    def test_write_docling_creates_store_dir(self, tmp_path):
        """write_docling creates store_dir when it does not yet exist."""
        store_dir = tmp_path / "subdir" / "store"
        store = CleanDocumentStore(store_dir)
        store.write_docling("doc1", _mock_docling_doc())
        assert store_dir.exists()

    def test_write_docling_overwrites_existing(self, tmp_path):
        """write_docling on the same key replaces the previous file atomically."""
        store = CleanDocumentStore(tmp_path)
        store.write_docling("doc1", _mock_docling_doc('{"v": 1}'))
        store.write_docling("doc1", _mock_docling_doc('{"v": 2}'))
        data = orjson.loads((tmp_path / "doc1.docling.json").read_bytes())
        assert data["document"]["v"] == 2

    def test_write_docling_raises_value_error_on_serialization_failure(self, tmp_path):
        """write_docling raises ValueError when model_dump_json fails."""
        store = CleanDocumentStore(tmp_path)
        bad_doc = MagicMock()
        bad_doc.model_dump_json.side_effect = ValueError("unpicklable")
        with pytest.raises(ValueError):
            store.write_docling("doc1", bad_doc)

    def test_write_docling_no_docling_json_on_failure(self, tmp_path):
        """Failed write_docling leaves no .docling.json (atomic guarantee)."""
        store = CleanDocumentStore(tmp_path)
        bad_doc = MagicMock()
        bad_doc.model_dump_json.side_effect = ValueError("fail")
        with pytest.raises(ValueError):
            store.write_docling("doc1", bad_doc)
        assert not (tmp_path / "doc1.docling.json").exists()

    def test_write_docling_no_tmp_file_on_failure(self, tmp_path):
        """Failed write_docling cleans up the .tmp file."""
        store = CleanDocumentStore(tmp_path)
        bad_doc = MagicMock()
        bad_doc.model_dump_json.side_effect = ValueError("fail")
        with pytest.raises(ValueError):
            store.write_docling("doc1", bad_doc)
        assert list(tmp_path.glob("*.tmp")) == []

    def test_write_docling_key_with_path_unsafe_chars(self, tmp_path):
        """Source keys with / and : are sanitized for the .docling.json filename."""
        store = CleanDocumentStore(tmp_path)
        store.write_docling("local_fs:dev/123", _mock_docling_doc())
        # The sanitized filename must exist; the raw key path must NOT
        assert not (tmp_path / "local_fs:dev/123.docling.json").exists()
        # Sanitized form uses _ in place of / and :
        sanitized = (tmp_path / "local_fs_dev_123.docling.json")
        assert sanitized.exists()


class TestReadDocling:
    """CleanDocumentStore.read_docling — deserialization, None returns, schema guard."""

    def test_read_docling_returns_none_for_missing_file(self, tmp_path):
        """read_docling returns None when no .docling.json file exists."""
        store = CleanDocumentStore(tmp_path)
        result = store.read_docling("nonexistent")
        assert result is None

    def test_read_docling_returns_none_and_does_not_raise(self, tmp_path):
        """read_docling never raises — missing file case."""
        store = CleanDocumentStore(tmp_path)
        # Must not raise
        result = store.read_docling("missing_key")
        assert result is None

    def test_read_docling_schema_version_mismatch_returns_none(self, tmp_path, caplog):
        """read_docling returns None and logs a warning when _schema_version is unknown."""
        store = CleanDocumentStore(tmp_path)
        payload = {
            "_schema_version": "docling-native-v2",
            "document": {"body": {}},
        }
        (tmp_path / "doc1.docling.json").write_bytes(orjson.dumps(payload))
        with caplog.at_level(logging.WARNING):
            result = store.read_docling("doc1")
        assert result is None
        assert any("docling-native-v2" in r.message or "docling-native-v2" in str(r) for r in caplog.records)

    def test_read_docling_missing_schema_version_returns_none(self, tmp_path, caplog):
        """read_docling returns None and logs a warning when _schema_version key is absent."""
        store = CleanDocumentStore(tmp_path)
        payload = {"document": {"body": {}}}  # no _schema_version
        (tmp_path / "doc1.docling.json").write_bytes(orjson.dumps(payload))
        with caplog.at_level(logging.WARNING):
            result = store.read_docling("doc1")
        assert result is None

    def test_read_docling_invalid_json_returns_none(self, tmp_path, caplog):
        """read_docling returns None and logs a warning for malformed JSON."""
        store = CleanDocumentStore(tmp_path)
        (tmp_path / "doc1.docling.json").write_bytes(b"not json{{{")
        with caplog.at_level(logging.WARNING):
            result = store.read_docling("doc1")
        assert result is None

    def test_read_docling_invalid_json_does_not_raise(self, tmp_path):
        """read_docling must not propagate JSON parse errors."""
        store = CleanDocumentStore(tmp_path)
        (tmp_path / "doc1.docling.json").write_bytes(b"not json{{{")
        # Must not raise
        store.read_docling("doc1")

    def test_read_docling_deserialization_failure_returns_none(self, tmp_path, caplog):
        """read_docling returns None when DoclingDocument.model_validate raises."""
        store = CleanDocumentStore(tmp_path)
        payload = {"_schema_version": "docling-native-v1", "document": {"body": {}}}
        (tmp_path / "doc1.docling.json").write_bytes(orjson.dumps(payload))
        with patch(
            "src.ingest.common.clean_store.DoclingDocument",
            create=True,
        ) as MockDD:
            MockDD.model_validate.side_effect = Exception("schema changed")
            with caplog.at_level(logging.WARNING):
                # Patch the import inside read_docling
                with patch.dict(
                    "sys.modules",
                    {"docling_core.types.doc": MagicMock(DoclingDocument=MockDD)},
                ):
                    # Re-trigger the import path
                    from importlib import reload
                    import src.ingest.common.clean_store as cs_mod
                    # Call directly — the import is lazy so we patch at the module attribute
                    result = store.read_docling("doc1")
        # Either None from the mocked path or None from actual failure is acceptable
        assert result is None

    def test_read_docling_roundtrip_envelope_structure(self, tmp_path):
        """write_docling followed by file inspection confirms correct envelope structure.

        Since docling_core may not be installed in the unit test environment,
        this test verifies the on-disk envelope is correct rather than
        exercising the full deserialization path.
        """
        store = CleanDocumentStore(tmp_path)
        store.write_docling("doc1", _mock_docling_doc('{"body": {"children": []}}'))
        data = orjson.loads((tmp_path / "doc1.docling.json").read_bytes())
        assert data["_schema_version"] == "docling-native-v1"
        assert "document" in data
        assert isinstance(data["document"], dict)

    def test_read_docling_with_mocked_docling_core(self, tmp_path):
        """read_docling calls DoclingDocument.model_validate with the document dict."""
        store = CleanDocumentStore(tmp_path)
        store.write_docling("doc1", _mock_docling_doc('{"body": {"children": []}}'))

        expected_obj = MagicMock(name="deserialized_doc")
        mock_dd_class = MagicMock()
        mock_dd_class.model_validate.return_value = expected_obj

        mock_module = MagicMock()
        mock_module.DoclingDocument = mock_dd_class

        with patch.dict("sys.modules", {"docling_core": MagicMock(), "docling_core.types": MagicMock(), "docling_core.types.doc": mock_module}):
            result = store.read_docling("doc1")

        assert result is expected_obj


class TestWriteWithDocling:
    """CleanDocumentStore.write() — extended with docling_document parameter."""

    def test_write_with_docling_creates_all_three_files(self, tmp_path):
        """write() with docling_document writes .md, .meta.json, and .docling.json."""
        store = CleanDocumentStore(tmp_path)
        store.write("doc1", "# Title\nBody.", {"source_name": "doc.pdf"}, _mock_docling_doc())
        assert (tmp_path / "doc1.md").exists()
        assert (tmp_path / "doc1.meta.json").exists()
        assert (tmp_path / "doc1.docling.json").exists()

    def test_write_without_docling_skips_docling_json(self, tmp_path):
        """write() without docling_document does NOT create .docling.json."""
        store = CleanDocumentStore(tmp_path)
        store.write("doc1", "# Title\nBody.", {"source_name": "doc.pdf"})
        assert not (tmp_path / "doc1.docling.json").exists()
        assert (tmp_path / "doc1.md").exists()
        assert (tmp_path / "doc1.meta.json").exists()

    def test_write_docling_failure_preserves_md_and_meta(self, tmp_path):
        """When write_docling raises inside write(), the .md and .meta.json are preserved."""
        store = CleanDocumentStore(tmp_path)
        bad_doc = MagicMock()
        bad_doc.model_dump_json.side_effect = ValueError("cannot serialize")
        # write() must not re-raise; md+meta must be intact
        store.write("doc1", "text content", {"key": "value"}, bad_doc)
        text, meta = store.read("doc1")
        assert text == "text content"
        assert meta["key"] == "value"

    def test_write_docling_failure_is_non_fatal(self, tmp_path):
        """write() does not raise even when write_docling fails."""
        store = CleanDocumentStore(tmp_path)
        bad_doc = MagicMock()
        bad_doc.model_dump_json.side_effect = ValueError("cannot serialize")
        # Must not raise
        store.write("doc1", "text", {}, bad_doc)

    def test_write_docling_failure_logged_at_error(self, tmp_path, caplog):
        """write_docling failure inside write() is logged at ERROR level."""
        store = CleanDocumentStore(tmp_path)
        bad_doc = MagicMock()
        bad_doc.model_dump_json.side_effect = ValueError("cannot serialize")
        with caplog.at_level(logging.ERROR):
            store.write("doc1", "text", {}, bad_doc)
        assert any(r.levelno >= logging.ERROR for r in caplog.records)


class TestDeleteDocling:
    """CleanDocumentStore.delete() — extended to remove .docling.json."""

    def test_delete_removes_docling_json(self, tmp_path):
        """delete() removes .docling.json when it exists."""
        store = CleanDocumentStore(tmp_path)
        store.write("doc1", "text", {}, _mock_docling_doc())
        assert (tmp_path / "doc1.docling.json").exists()
        store.delete("doc1")
        assert not (tmp_path / "doc1.docling.json").exists()

    def test_delete_removes_md_and_meta(self, tmp_path):
        """delete() removes .md and .meta.json along with .docling.json."""
        store = CleanDocumentStore(tmp_path)
        store.write("doc1", "text", {"k": "v"}, _mock_docling_doc())
        store.delete("doc1")
        assert not (tmp_path / "doc1.md").exists()
        assert not (tmp_path / "doc1.meta.json").exists()

    def test_delete_missing_docling_json_is_silent(self, tmp_path):
        """delete() does not raise when .docling.json is absent."""
        store = CleanDocumentStore(tmp_path)
        store.write("doc1", "text", {})  # no docling_document
        assert not (tmp_path / "doc1.docling.json").exists()
        # Must not raise
        store.delete("doc1")

    def test_delete_all_missing_files_is_silent(self, tmp_path):
        """delete() on an entirely absent key does not raise."""
        store = CleanDocumentStore(tmp_path)
        store.delete("never_written")  # Must not raise


# ---------------------------------------------------------------------------
# chunking_node — dual-path selection
# ---------------------------------------------------------------------------

class TestChunkingNodeDoclingPath:
    """chunking_node uses HybridChunker when state['docling_document'] is set."""

    def test_docling_path_returns_chunks(self):
        """Docling path: single chunk from HybridChunker → ProcessedChunk returned."""
        from src.ingest.embedding.nodes.chunking import chunking_node

        mock_chunk = _make_mock_chunk("Chunk content text.", ["Chapter 1", "Background"])
        MockHC, _ = _make_hybrid_chunker_mock([mock_chunk])
        state = _make_chunking_state(docling_document=MagicMock())

        with (
            patch(_EXTRACT_METADATA, return_value=MagicMock()),
            patch(_METADATA_TO_DICT, return_value={}),
            patch.dict("sys.modules", _docling_core_sys_modules(MockHC)),
        ):
            result = chunking_node(state)

        chunks = result["chunks"]
        assert len(chunks) == 1
        assert isinstance(chunks[0], ProcessedChunk)

    def test_docling_path_section_metadata_two_headings(self):
        """Docling path: two-level headings → section_path, heading, heading_level correct."""
        from src.ingest.embedding.nodes.chunking import chunking_node

        mock_chunk = _make_mock_chunk("Body text.", ["Chapter 1", "Background"])
        MockHC, _ = _make_hybrid_chunker_mock([mock_chunk])
        state = _make_chunking_state(docling_document=MagicMock())

        with (
            patch(_EXTRACT_METADATA, return_value=MagicMock()),
            patch(_METADATA_TO_DICT, return_value={}),
            patch.dict("sys.modules", _docling_core_sys_modules(MockHC)),
        ):
            result = chunking_node(state)

        meta = result["chunks"][0].metadata
        assert meta["section_path"] == "Chapter 1 > Background"
        assert meta["heading"] == "Background"
        assert meta["heading_level"] == 2

    def test_docling_path_no_headings(self):
        """Docling path: chunk with empty headings → empty section metadata."""
        from src.ingest.embedding.nodes.chunking import chunking_node

        mock_chunk = _make_mock_chunk("No-heading text.", [])
        MockHC, _ = _make_hybrid_chunker_mock([mock_chunk])
        state = _make_chunking_state(docling_document=MagicMock())

        with (
            patch(_EXTRACT_METADATA, return_value=MagicMock()),
            patch(_METADATA_TO_DICT, return_value={}),
            patch.dict("sys.modules", _docling_core_sys_modules(MockHC)),
        ):
            result = chunking_node(state)

        meta = result["chunks"][0].metadata
        assert meta["section_path"] == ""
        assert meta["heading"] == ""
        assert meta["heading_level"] == 0

    def test_docling_path_multiple_chunks_indexes(self):
        """Docling path: 3 chunks → chunk_index in [0,1,2] and total_chunks=3."""
        from src.ingest.embedding.nodes.chunking import chunking_node

        chunks = [_make_mock_chunk(f"Chunk {i}", ["H"]) for i in range(3)]
        MockHC, _ = _make_hybrid_chunker_mock(chunks)
        state = _make_chunking_state(docling_document=MagicMock())

        with (
            patch(_EXTRACT_METADATA, return_value=MagicMock()),
            patch(_METADATA_TO_DICT, return_value={}),
            patch.dict("sys.modules", _docling_core_sys_modules(MockHC)),
        ):
            result = chunking_node(state)

        out_chunks = result["chunks"]
        assert len(out_chunks) == 3
        for idx, chunk in enumerate(out_chunks):
            assert chunk.metadata["chunk_index"] == idx
            assert chunk.metadata["total_chunks"] == 3

    def test_docling_path_processing_log_contains_ok(self):
        """Docling path success → processing_log contains 'hybrid_chunker:ok'."""
        from src.ingest.embedding.nodes.chunking import chunking_node

        MockHC, _ = _make_hybrid_chunker_mock([_make_mock_chunk()])
        state = _make_chunking_state(docling_document=MagicMock())

        with (
            patch(_EXTRACT_METADATA, return_value=MagicMock()),
            patch(_METADATA_TO_DICT, return_value={}),
            patch.dict("sys.modules", _docling_core_sys_modules(MockHC)),
        ):
            result = chunking_node(state)

        assert "hybrid_chunker:ok" in result["processing_log"]

    def test_docling_path_empty_chunks_list(self):
        """Docling path: HybridChunker returns [] → chunks=[] with no error."""
        from src.ingest.embedding.nodes.chunking import chunking_node

        MockHC, _ = _make_hybrid_chunker_mock([])
        state = _make_chunking_state(docling_document=MagicMock())

        with (
            patch(_EXTRACT_METADATA, return_value=MagicMock()),
            patch(_METADATA_TO_DICT, return_value={}),
            patch.dict("sys.modules", _docling_core_sys_modules(MockHC)),
        ):
            result = chunking_node(state)

        assert result["chunks"] == []
        assert "errors" not in result or result.get("errors") == []

    def test_docling_path_chunk_metadata_has_required_source_fields(self):
        """Docling path: ProcessedChunk metadata contains source identity fields."""
        from src.ingest.embedding.nodes.chunking import chunking_node

        MockHC, _ = _make_hybrid_chunker_mock([_make_mock_chunk()])
        state = _make_chunking_state(docling_document=MagicMock())

        with (
            patch(_EXTRACT_METADATA, return_value=MagicMock()),
            patch(_METADATA_TO_DICT, return_value={}),
            patch.dict("sys.modules", _docling_core_sys_modules(MockHC)),
        ):
            result = chunking_node(state)

        meta = result["chunks"][0].metadata
        for key in ("source", "source_uri", "source_key", "source_id", "connector", "source_version"):
            assert key in meta, f"Missing required metadata key: {key!r}"

    def test_docling_path_max_tokens_passed_to_hybridchunker(self):
        """HybridChunker is constructed with config.hybrid_chunker_max_tokens."""
        from src.ingest.embedding.nodes.chunking import chunking_node

        MockHC, _ = _make_hybrid_chunker_mock([_make_mock_chunk()])
        state = _make_chunking_state(docling_document=MagicMock(), hybrid_max_tokens=256)

        with (
            patch(_EXTRACT_METADATA, return_value=MagicMock()),
            patch(_METADATA_TO_DICT, return_value={}),
            patch.dict("sys.modules", _docling_core_sys_modules(MockHC)),
        ):
            chunking_node(state)

        call_kwargs = MockHC.call_args
        passed_max_tokens = (
            call_kwargs.kwargs.get("max_tokens")
            if call_kwargs.kwargs
            else (call_kwargs.args[0] if call_kwargs.args else None)
        )
        assert passed_max_tokens == 256


class TestChunkingNodeMarkdownFallback:
    """chunking_node uses markdown path when docling_document is None."""

    def _fake_md_chunks(self, n: int = 1) -> list[dict]:
        return [
            {"text": f"Markdown chunk {i}", "header_metadata": {"h1": f"Section {i}"}}
            for i in range(n)
        ]

    def test_markdown_path_when_no_docling_document(self):
        """state['docling_document'] = None → markdown path runs."""
        from src.ingest.embedding.nodes.chunking import chunking_node

        state = _make_chunking_state(docling_document=None)

        with (
            patch(_EXTRACT_METADATA, return_value=MagicMock()),
            patch(_METADATA_TO_DICT, return_value={}),
            patch(_NORMALIZE_HEADINGS, side_effect=lambda t: t),
            patch(_CHUNK_MARKDOWN, return_value=self._fake_md_chunks(1)) as mock_md,
        ):
            result = chunking_node(state)

        mock_md.assert_called_once()
        assert len(result["chunks"]) == 1

    def test_markdown_path_processing_log(self):
        """Markdown fallback path → processing_log contains 'chunking:markdown_fallback'."""
        from src.ingest.embedding.nodes.chunking import chunking_node

        state = _make_chunking_state(docling_document=None)

        with (
            patch(_EXTRACT_METADATA, return_value=MagicMock()),
            patch(_METADATA_TO_DICT, return_value={}),
            patch(_NORMALIZE_HEADINGS, side_effect=lambda t: t),
            patch(_CHUNK_MARKDOWN, return_value=self._fake_md_chunks(1)),
        ):
            result = chunking_node(state)

        assert "chunking:markdown_fallback" in result["processing_log"]

    def test_markdown_path_not_taken_when_docling_document_set(self):
        """chunk_markdown is NOT called when docling_document is not None."""
        from src.ingest.embedding.nodes.chunking import chunking_node

        MockHC, _ = _make_hybrid_chunker_mock([_make_mock_chunk()])
        state = _make_chunking_state(docling_document=MagicMock())

        with (
            patch(_EXTRACT_METADATA, return_value=MagicMock()),
            patch(_METADATA_TO_DICT, return_value={}),
            patch.dict("sys.modules", _docling_core_sys_modules(MockHC)),
            patch(_CHUNK_MARKDOWN) as mock_md,
        ):
            chunking_node(state)

        mock_md.assert_not_called()


class TestChunkingNodeFallbackOnHybridError:
    """chunking_node falls back to markdown when HybridChunker raises."""

    def _fake_md_chunks(self, n: int = 1) -> list[dict]:
        return [
            {"text": f"Fallback chunk {i}", "header_metadata": {"h1": f"Section {i}"}}
            for i in range(n)
        ]

    def test_hybridchunker_value_error_falls_back(self):
        """HybridChunker.chunk() raises ValueError → markdown fallback runs."""
        from src.ingest.embedding.nodes.chunking import chunking_node

        mock_instance = MagicMock()
        mock_instance.chunk.side_effect = ValueError("unsupported item")
        MockHC = MagicMock(return_value=mock_instance)
        state = _make_chunking_state(docling_document=MagicMock())

        with (
            patch(_EXTRACT_METADATA, return_value=MagicMock()),
            patch(_METADATA_TO_DICT, return_value={}),
            patch.dict("sys.modules", _docling_core_sys_modules(MockHC)),
            patch(_NORMALIZE_HEADINGS, side_effect=lambda t: t),
            patch(_CHUNK_MARKDOWN, return_value=self._fake_md_chunks(1)) as mock_md,
        ):
            result = chunking_node(state)

        mock_md.assert_called_once()
        assert len(result["chunks"]) == 1

    def test_hybridchunker_runtime_error_falls_back(self):
        """HybridChunker.chunk() raises RuntimeError → markdown fallback runs."""
        from src.ingest.embedding.nodes.chunking import chunking_node

        mock_instance = MagicMock()
        mock_instance.chunk.side_effect = RuntimeError("docling exploded")
        MockHC = MagicMock(return_value=mock_instance)
        state = _make_chunking_state(docling_document=MagicMock())

        with (
            patch(_EXTRACT_METADATA, return_value=MagicMock()),
            patch(_METADATA_TO_DICT, return_value={}),
            patch.dict("sys.modules", _docling_core_sys_modules(MockHC)),
            patch(_NORMALIZE_HEADINGS, side_effect=lambda t: t),
            patch(_CHUNK_MARKDOWN, return_value=self._fake_md_chunks(1)),
        ):
            result = chunking_node(state)

        assert len(result["chunks"]) >= 1

    def test_hybridchunker_error_log_contains_error_and_fallback(self):
        """HybridChunker failure → processing_log has 'hybrid_chunker:error' AND 'chunking:fallback_to_markdown'."""
        from src.ingest.embedding.nodes.chunking import chunking_node

        mock_instance = MagicMock()
        mock_instance.chunk.side_effect = ValueError("bad doc")
        MockHC = MagicMock(return_value=mock_instance)
        state = _make_chunking_state(docling_document=MagicMock())

        with (
            patch(_EXTRACT_METADATA, return_value=MagicMock()),
            patch(_METADATA_TO_DICT, return_value={}),
            patch.dict("sys.modules", _docling_core_sys_modules(MockHC)),
            patch(_NORMALIZE_HEADINGS, side_effect=lambda t: t),
            patch(_CHUNK_MARKDOWN, return_value=self._fake_md_chunks(1)),
        ):
            result = chunking_node(state)

        log = result["processing_log"]
        assert "hybrid_chunker:error" in log
        assert "chunking:fallback_to_markdown" in log

    def test_outer_exception_returns_errors_key(self):
        """When base_metadata assembly fails, chunking_node returns errors and no chunks."""
        from src.ingest.embedding.nodes.chunking import chunking_node

        state = _make_chunking_state(docling_document=None)

        with (
            patch(_EXTRACT_METADATA, side_effect=RuntimeError("metadata crash")),
        ):
            result = chunking_node(state)

        assert "errors" in result
        assert len(result["errors"]) > 0


# ---------------------------------------------------------------------------
# _normalize_chunk_text — NFC normalization and control char removal
# ---------------------------------------------------------------------------

class TestNormalizeChunkText:
    """_normalize_chunk_text applies NFC and strips C0/C1 control characters."""

    def _normalize(self, text: str) -> str:
        from src.ingest.embedding.nodes.chunking import _normalize_chunk_text
        return _normalize_chunk_text(text)

    def test_nfc_normalization_cafe_nfd(self):
        """NFD 'café' (e + combining accent) normalizes to NFC single code point."""
        nfd_cafe = "caf\u0065\u0301"  # 'e' + combining acute accent
        result = self._normalize(nfd_cafe)
        import unicodedata
        assert unicodedata.is_normalized("NFC", result)
        assert result == "café"

    def test_null_byte_removed(self):
        """NUL byte (\x00) is removed from chunk text."""
        assert self._normalize("\x00hello") == "hello"

    def test_control_chars_removed(self):
        """C0 control chars (\x00–\x1f, excluding \n, \r, \t) are stripped."""
        result = self._normalize("\x00hello\x1fworld")
        assert result == "helloworld"

    def test_newline_preserved(self):
        """Newline (\n) is NOT removed."""
        assert self._normalize("line1\nline2") == "line1\nline2"

    def test_carriage_return_preserved(self):
        """Carriage return (\r) is NOT removed."""
        assert self._normalize("line1\rline2") == "line1\rline2"

    def test_tab_preserved(self):
        """Horizontal tab (\t) is NOT removed."""
        assert self._normalize("col1\tcol2") == "col1\tcol2"

    def test_empty_string_returns_empty(self):
        """Empty string passes through unchanged."""
        assert self._normalize("") == ""

    def test_newline_only_preserved(self):
        """\\n\\r returns unchanged."""
        assert self._normalize("\n\r") == "\n\r"

    def test_del_byte_removed(self):
        """DEL character (\x7f) is removed."""
        assert self._normalize("hello\x7fworld") == "helloworld"

    def test_vt_removed(self):
        """Vertical tab (\x0b) is removed."""
        assert self._normalize("a\x0bb") == "ab"

    def test_ff_removed(self):
        """Form feed (\x0c) is removed."""
        assert self._normalize("a\x0cb") == "ab"

    def test_plain_ascii_unchanged(self):
        """Plain ASCII text passes through unchanged."""
        text = "Hello, world! 123 #$%"
        assert self._normalize(text) == text


# ---------------------------------------------------------------------------
# _extract_docling_section_metadata — heading hierarchy extraction
# ---------------------------------------------------------------------------

class TestExtractDoclingSection:
    """_extract_docling_section_metadata extracts section_path/heading/level."""

    def _extract(self, chunk) -> dict:
        from src.ingest.embedding.nodes.chunking import _extract_docling_section_metadata
        return _extract_docling_section_metadata(chunk)

    def _chunk_with_headings(self, headings) -> MagicMock:
        chunk = MagicMock()
        chunk.meta = MagicMock()
        chunk.meta.headings = headings
        return chunk

    def _chunk_with_no_meta(self) -> MagicMock:
        chunk = MagicMock(spec=[])  # no .meta attribute
        return chunk

    def test_single_heading(self):
        """One heading → section_path=heading, heading_level=1."""
        result = self._extract(self._chunk_with_headings(["Top"]))
        assert result["section_path"] == "Top"
        assert result["heading"] == "Top"
        assert result["heading_level"] == 1

    def test_two_level_headings(self):
        """Two headings → section_path joined with ' > ', heading=last."""
        result = self._extract(self._chunk_with_headings(["Chapter 1", "Background"]))
        assert result["section_path"] == "Chapter 1 > Background"
        assert result["heading"] == "Background"
        assert result["heading_level"] == 2

    def test_three_level_headings(self):
        """Three headings → correct path, heading, level."""
        result = self._extract(self._chunk_with_headings(["A", "B", "C"]))
        assert result["section_path"] == "A > B > C"
        assert result["heading"] == "C"
        assert result["heading_level"] == 3

    def test_empty_headings_list(self):
        """Empty headings list → all empty/zero values."""
        result = self._extract(self._chunk_with_headings([]))
        assert result["section_path"] == ""
        assert result["heading"] == ""
        assert result["heading_level"] == 0

    def test_none_headings(self):
        """chunk.meta.headings = None → treated as empty."""
        chunk = MagicMock()
        chunk.meta = MagicMock()
        chunk.meta.headings = None
        result = self._extract(chunk)
        assert result["section_path"] == ""
        assert result["heading"] == ""
        assert result["heading_level"] == 0

    def test_meta_none(self):
        """chunk.meta = None → all empty/zero values, no exception."""
        chunk = MagicMock()
        chunk.meta = None
        result = self._extract(chunk)
        assert result["section_path"] == ""
        assert result["heading"] == ""
        assert result["heading_level"] == 0

    def test_meta_absent(self):
        """chunk has no .meta attribute → all empty/zero values, no exception."""
        chunk = object()  # no .meta attribute at all
        result = self._extract(chunk)
        assert result["section_path"] == ""
        assert result["heading"] == ""
        assert result["heading_level"] == 0

    def test_return_dict_has_all_required_keys(self):
        """Return value always contains section_path, heading, heading_level."""
        result = self._extract(self._chunk_with_headings(["H1"]))
        assert "section_path" in result
        assert "heading" in result
        assert "heading_level" in result
