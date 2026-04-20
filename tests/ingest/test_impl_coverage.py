"""Targeted coverage tests for src/ingest/impl.py.

Covers the specific uncovered lines:
- _safe_relative ValueError branch (lines 104-105)
- _write_refactor_mirror_artifacts full execution (lines 161-195)
- _normalize_manifest_entries edge cases (lines 212, 216-221)
- ingest_file mirror path (lines 632-641)
- ingest_directory: removed sources, KG save, db close, obsidian export (855-876, 913-920)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Helpers to access private functions
# ---------------------------------------------------------------------------

from src.ingest.impl import (
    _safe_relative,
    _write_refactor_mirror_artifacts,
    _normalize_manifest_entries,
    _mirror_file_stem,
)
from src.ingest.common.types import IngestionConfig


# ---------------------------------------------------------------------------
# _safe_relative
# ---------------------------------------------------------------------------


class TestSafeRelative:
    def test_mock_path_within_root_returns_relative(self, tmp_path):
        """When path is under root, relative path string is returned."""
        root = tmp_path
        child = tmp_path / "subdir" / "file.txt"
        result = _safe_relative(child, root)
        assert result == str(Path("subdir/file.txt"))

    def test_mock_path_outside_root_returns_absolute(self, tmp_path):
        """When path is outside root, absolute path string is returned (ValueError branch)."""
        root = tmp_path / "root_dir"
        other = tmp_path / "other_dir" / "file.txt"
        # path.resolve().relative_to(root.resolve()) will raise ValueError
        result = _safe_relative(other, root)
        assert result == str(other.resolve())

    def test_mock_path_is_root_returns_dot_or_empty(self, tmp_path):
        """Path equal to root — relative_to returns '.', not ValueError."""
        result = _safe_relative(tmp_path, tmp_path)
        assert result == "."


# ---------------------------------------------------------------------------
# _write_refactor_mirror_artifacts
# ---------------------------------------------------------------------------


class TestWriteRefactorMirrorArtifacts:
    def _make_chunk(self, idx: int) -> MagicMock:
        chunk = MagicMock()
        chunk.metadata = {
            "chunk_index": idx,
            "chunk_id": f"cid-{idx}",
            "retrieval_text_origin": "original",
            "original_char_start": idx * 10,
            "original_char_end": idx * 10 + 9,
            "refactored_char_start": idx * 10,
            "refactored_char_end": idx * 10 + 9,
            "provenance_method": "exact",
            "provenance_confidence": 0.99,
        }
        return chunk

    def test_mock_writes_mirror_files(self, tmp_path):
        """All three mirror files are written with expected content."""
        config = IngestionConfig(mirror_output_dir=str(tmp_path))
        source = {
            "source_path": "/docs/test.md",
            "source_name": "test.md",
            "source_uri": "file:///docs/test.md",
            "source_key": "local_fs:123:456",
            "source_id": "123:456",
            "connector": "local_fs",
            "source_version": "1000000",
        }
        chunks = [self._make_chunk(0), self._make_chunk(1)]
        result = {
            "raw_text": "original text",
            "refactored_text": "refactored text",
            "chunks": chunks,
        }

        _write_refactor_mirror_artifacts(source, result, config)

        stem = _mirror_file_stem(source["source_name"], source["source_key"])
        original_path = tmp_path / f"{stem}.original.md"
        refactored_path = tmp_path / f"{stem}.refactored.md"
        mapping_path = tmp_path / f"{stem}.mapping.json"

        assert original_path.exists()
        assert refactored_path.exists()
        assert mapping_path.exists()

        assert original_path.read_text(encoding="utf-8") == "original text"
        assert refactored_path.read_text(encoding="utf-8") == "refactored text"

        mapping = json.loads(mapping_path.read_bytes())
        assert mapping["source"] == "test.md"
        assert mapping["source_key"] == "local_fs:123:456"
        assert len(mapping["chunks"]) == 2
        assert mapping["chunks"][0]["chunk_index"] == 0
        assert mapping["chunks"][1]["chunk_id"] == "cid-1"
        assert mapping["chunks"][0]["provenance_confidence"] == 0.99

    def test_mock_uses_default_mirror_dir_when_none(self, tmp_path, monkeypatch):
        """When mirror_output_dir is None/empty, falls back to RAG_INGESTION_MIRROR_DIR."""
        import src.ingest.impl as impl_mod

        monkeypatch.setattr(impl_mod, "RAG_INGESTION_MIRROR_DIR", tmp_path)
        config = IngestionConfig(mirror_output_dir=None)
        source = {
            "source_path": "/docs/test.md",
            "source_name": "test.md",
            "source_uri": "file:///docs/test.md",
            "source_key": "local_fs:1:1",
            "source_id": "1:1",
            "connector": "local_fs",
            "source_version": "100",
        }
        result = {"raw_text": "raw", "refactored_text": "ref", "chunks": []}

        _write_refactor_mirror_artifacts(source, result, config)

        # Files should have been written under tmp_path (the patched dir)
        written = list(tmp_path.iterdir())
        assert len(written) == 3

    def test_mock_empty_chunks_creates_valid_mapping(self, tmp_path):
        """Empty chunks list still produces a valid mapping JSON."""
        config = IngestionConfig(mirror_output_dir=str(tmp_path))
        source = {
            "source_path": "/x.md",
            "source_name": "x.md",
            "source_uri": "file:///x.md",
            "source_key": "local_fs:0:0",
            "source_id": "0:0",
            "connector": "local_fs",
            "source_version": "0",
        }
        result = {"raw_text": "", "refactored_text": "", "chunks": []}
        _write_refactor_mirror_artifacts(source, result, config)

        stem = _mirror_file_stem(source["source_name"], source["source_key"])
        mapping = json.loads((tmp_path / f"{stem}.mapping.json").read_bytes())
        assert mapping["chunks"] == []


# ---------------------------------------------------------------------------
# _normalize_manifest_entries edge cases
# ---------------------------------------------------------------------------


class TestNormalizeManifestEntries:
    def test_mock_skips_non_dict_entries(self):
        """Non-dict values in the manifest are silently skipped."""
        raw = {"key1": "not a dict", "key2": 42, "key3": None}
        result = _normalize_manifest_entries(raw)
        assert len(result) == 0

    def test_mock_key_without_source_key_uses_raw_key_for_local_fs(self):
        """Entry with no source_key but raw_key starting with 'local_fs:' uses raw key."""
        raw = {
            "local_fs:99:88": {
                "source_name": "file.md",
            }
        }
        result = _normalize_manifest_entries(raw)
        assert "local_fs:99:88" in result
        assert result["local_fs:99:88"]["source_key"] == "local_fs:99:88"

    def test_mock_key_without_source_key_gets_legacy_name(self):
        """Entry with no source_key and non-local raw key gets legacy_name: prefix."""
        raw = {
            "somefile.md": {
                "source_name": "somefile.md",
            }
        }
        result = _normalize_manifest_entries(raw)
        expected_key = "legacy_name:somefile.md"
        assert expected_key in result
        assert result[expected_key]["legacy_name"] == "somefile.md"
        assert result[expected_key]["source_key"] == expected_key

    def test_mock_sets_default_lifecycle_fields(self):
        """Pre-1.0.0 manifests get all lifecycle fields defaulted."""
        raw = {
            "local_fs:1:2": {
                "source_key": "local_fs:1:2",
                "source_name": "doc.md",
            }
        }
        result = _normalize_manifest_entries(raw)
        entry = result["local_fs:1:2"]
        assert entry["schema_version"] == "0.0.0"
        assert entry["trace_id"] == ""
        assert entry["batch_id"] == ""
        assert entry["deleted"] is False
        assert entry["deleted_at"] == ""
        assert entry["validation"] == {}
        assert entry["clean_hash"] == ""

    def test_mock_existing_source_key_not_overwritten(self):
        """When entry already has source_key, it is preserved as the dict key."""
        raw = {
            "old_raw_key": {
                "source_key": "local_fs:stable:key",
                "source_name": "stable.md",
            }
        }
        result = _normalize_manifest_entries(raw)
        assert "local_fs:stable:key" in result
        assert "old_raw_key" not in result


# ---------------------------------------------------------------------------
# ingest_file: persist_refactor_mirror path (lines 632-641)
# ---------------------------------------------------------------------------


class TestIngestFileMirrorPath:
    def test_mock_write_refactor_mirror_called_when_flag_set(self, tmp_path):
        """When persist_refactor_mirror=True, _write_refactor_mirror_artifacts is called."""
        from src.ingest.impl import ingest_file
        import src.ingest.impl as impl_mod

        config = IngestionConfig(
            persist_refactor_mirror=True,
            mirror_output_dir=str(tmp_path),
        )
        runtime = MagicMock()
        runtime.config = config

        fake_phase1 = {
            "errors": [],
            "raw_text": "raw",
            "refactored_text": "ref",
            "cleaned_text": "clean",
            "source_hash": "abc123",
            "processing_log": [],
            "chunks": [],
        }
        fake_phase2 = MagicMock()
        fake_phase2.errors = []
        fake_phase2.stored_count = 0
        fake_phase2.metadata_summary = ""
        fake_phase2.metadata_keywords = []
        fake_phase2.processing_log = []
        fake_phase2.source_hash = "abc123"
        fake_phase2.clean_hash = "def456"
        fake_phase2.trace_id = "trace-mock"
        fake_phase2.validation = {}

        mirror_calls = []

        def _fake_write_mirror(source, result, cfg):
            mirror_calls.append((source, result, cfg))

        source_file = tmp_path / "doc.md"
        source_file.write_text("hello")

        with patch.object(impl_mod, "run_document_processing", return_value=fake_phase1), \
             patch.object(impl_mod, "run_embedding_pipeline", return_value=fake_phase2), \
             patch.object(impl_mod, "_write_refactor_mirror_artifacts", side_effect=_fake_write_mirror):
            result = ingest_file(
                source_path=source_file,
                runtime=runtime,
                source_name="doc.md",
                source_uri="file:///tmp/doc.md",
                source_key="local_fs:1:1",
                source_id="1:1",
                connector="local_fs",
                source_version="100",
            )

        assert len(mirror_calls) == 1
        source_arg = mirror_calls[0][0]
        assert source_arg["source_name"] == "doc.md"


# ---------------------------------------------------------------------------
# ingest_directory: db client, KG save, obsidian export, removed sources
# ---------------------------------------------------------------------------


class TestIngestDirectoryPaths:
    """Tests for ingest_directory paths that handle optional components."""

    def _make_minimal_config(self, **kwargs) -> IngestionConfig:
        base = dict(
            chunk_size=512,
            chunk_overlap=64,
            enable_knowledge_graph_storage=False,
            enable_knowledge_graph_extraction=False,
            build_kg=False,
            store_documents=False,
            export_processed=False,
            enable_docling_parser=False,
            enable_vision_processing=False,
        )
        base.update(kwargs)
        return IngestionConfig(**base)

    def test_mock_db_client_closed_after_ingestion(self, tmp_path):
        """When store_documents=True, db client is created and closed after run."""
        import src.ingest.impl as impl_mod

        config = self._make_minimal_config(store_documents=True, target_bucket="test-bucket")
        doc_file = tmp_path / "doc.md"
        doc_file.write_text("content")

        fake_db_client = MagicMock()

        # We'll mock at the module level to avoid hitting real services
        with patch.object(impl_mod, "load_manifest", return_value={}), \
             patch.object(impl_mod, "save_manifest"), \
             patch.object(impl_mod, "get_client") as mock_get_client, \
             patch.object(impl_mod, "ensure_collection"), \
             patch.object(impl_mod, "delete_collection"), \
             patch.object(impl_mod, "get_embedding_provider", return_value=MagicMock()), \
             patch.object(impl_mod, "ParserRegistry", return_value=MagicMock()), \
             patch("src.db.create_persistent_client", return_value=fake_db_client), \
             patch("src.db.ensure_bucket"), \
             patch("src.db.close_client") as mock_close, \
             patch.object(impl_mod, "ingest_file") as mock_ingest_file:

            ctx_client = MagicMock()
            mock_get_client.return_value.__enter__ = MagicMock(return_value=ctx_client)
            mock_get_client.return_value.__exit__ = MagicMock(return_value=False)

            mock_result = MagicMock()
            mock_result.errors = []
            mock_result.stored_count = 1
            mock_result.metadata_summary = "summary"
            mock_result.metadata_keywords = []
            mock_result.processing_log = []
            mock_result.source_hash = "hash123"
            mock_result.clean_hash = "clean456"
            mock_result.trace_id = "tid-001"
            mock_result.validation = {}
            mock_ingest_file.return_value = mock_result

            from src.ingest.impl import ingest_directory
            summary = ingest_directory(tmp_path, config=config)

        # close_client should have been called
        mock_close.assert_called_once_with(fake_db_client)

    def test_mock_kg_saved_when_kg_builder_present(self, tmp_path):
        """When kg_builder is present, save() is called after all files processed."""
        import src.ingest.impl as impl_mod

        config = self._make_minimal_config(build_kg=True, enable_knowledge_graph_extraction=True)
        doc_file = tmp_path / "doc.md"
        doc_file.write_text("content")

        fake_kg_builder = MagicMock()

        with patch.object(impl_mod, "load_manifest", return_value={}), \
             patch.object(impl_mod, "save_manifest"), \
             patch.object(impl_mod, "get_client") as mock_get_client, \
             patch.object(impl_mod, "ensure_collection"), \
             patch.object(impl_mod, "get_embedding_provider", return_value=MagicMock()), \
             patch.object(impl_mod, "KnowledgeGraphBuilder", return_value=fake_kg_builder), \
             patch.object(impl_mod, "ParserRegistry", return_value=MagicMock()), \
             patch.object(impl_mod, "ingest_file") as mock_ingest_file:

            ctx_client = MagicMock()
            mock_get_client.return_value.__enter__ = MagicMock(return_value=ctx_client)
            mock_get_client.return_value.__exit__ = MagicMock(return_value=False)

            mock_result = MagicMock()
            mock_result.errors = []
            mock_result.stored_count = 1
            mock_result.metadata_summary = ""
            mock_result.metadata_keywords = []
            mock_result.processing_log = []
            mock_result.source_hash = "hash"
            mock_result.clean_hash = "chash"
            mock_result.trace_id = "t1"
            mock_result.validation = {}
            mock_ingest_file.return_value = mock_result

            from src.ingest.impl import ingest_directory, KG_PATH
            ingest_directory(tmp_path, config=config)

        fake_kg_builder.save.assert_called_once()

    def test_mock_obsidian_export_called_when_enabled(self, tmp_path):
        """When obsidian_export=True, export_obsidian is called after KG save."""
        import src.ingest.impl as impl_mod

        config = self._make_minimal_config(build_kg=True, enable_knowledge_graph_extraction=True)
        doc_file = tmp_path / "doc.md"
        doc_file.write_text("content")

        fake_kg_builder = MagicMock()

        with patch.object(impl_mod, "load_manifest", return_value={}), \
             patch.object(impl_mod, "save_manifest"), \
             patch.object(impl_mod, "get_client") as mock_get_client, \
             patch.object(impl_mod, "ensure_collection"), \
             patch.object(impl_mod, "get_embedding_provider", return_value=MagicMock()), \
             patch.object(impl_mod, "KnowledgeGraphBuilder", return_value=fake_kg_builder), \
             patch.object(impl_mod, "export_obsidian") as mock_export, \
             patch.object(impl_mod, "ParserRegistry", return_value=MagicMock()), \
             patch.object(impl_mod, "ingest_file") as mock_ingest_file:

            ctx_client = MagicMock()
            mock_get_client.return_value.__enter__ = MagicMock(return_value=ctx_client)
            mock_get_client.return_value.__exit__ = MagicMock(return_value=False)

            mock_result = MagicMock()
            mock_result.errors = []
            mock_result.stored_count = 1
            mock_result.metadata_summary = ""
            mock_result.metadata_keywords = []
            mock_result.processing_log = []
            mock_result.source_hash = "h"
            mock_result.clean_hash = "ch"
            mock_result.trace_id = "t2"
            mock_result.validation = {}
            mock_ingest_file.return_value = mock_result

            from src.ingest.impl import ingest_directory
            ingest_directory(tmp_path, config=config, obsidian_export=True)

        mock_export.assert_called_once()

    def test_mock_ingest_file_error_continues_loop(self, tmp_path):
        """ingest_file returning errors increments failed counter and continues."""
        import src.ingest.impl as impl_mod

        config = self._make_minimal_config()
        for name in ["a.md", "b.md"]:
            (tmp_path / name).write_text("content")

        with patch.object(impl_mod, "load_manifest", return_value={}), \
             patch.object(impl_mod, "save_manifest"), \
             patch.object(impl_mod, "get_client") as mock_get_client, \
             patch.object(impl_mod, "ensure_collection"), \
             patch.object(impl_mod, "get_embedding_provider", return_value=MagicMock()), \
             patch.object(impl_mod, "ParserRegistry", return_value=MagicMock()), \
             patch.object(impl_mod, "ingest_file") as mock_ingest_file:

            ctx_client = MagicMock()
            mock_get_client.return_value.__enter__ = MagicMock(return_value=ctx_client)
            mock_get_client.return_value.__exit__ = MagicMock(return_value=False)

            # First file fails, second succeeds
            fail_result = MagicMock()
            fail_result.errors = ["some error"]
            fail_result.stored_count = 0
            fail_result.metadata_summary = ""
            fail_result.metadata_keywords = []
            fail_result.processing_log = []
            fail_result.source_hash = ""
            fail_result.clean_hash = ""
            fail_result.trace_id = ""
            fail_result.validation = {}

            ok_result = MagicMock()
            ok_result.errors = []
            ok_result.stored_count = 2
            ok_result.metadata_summary = "ok"
            ok_result.metadata_keywords = []
            ok_result.processing_log = []
            ok_result.source_hash = "h"
            ok_result.clean_hash = "ch"
            ok_result.trace_id = "t"
            ok_result.validation = {}

            mock_ingest_file.side_effect = [fail_result, ok_result]

            from src.ingest.impl import ingest_directory
            summary = ingest_directory(tmp_path, config=config)

        assert summary.failed == 1
        assert summary.processed == 1

    def test_mock_removed_sources_deleted_in_update_mode(self, tmp_path):
        """In update mode, sources present in manifest but not on disk are deleted."""
        import src.ingest.impl as impl_mod

        config = self._make_minimal_config()
        doc_file = tmp_path / "current.md"
        doc_file.write_text("content")

        # Manifest has a stale entry "local_fs:old:key" not present on disk
        old_manifest = {
            "local_fs:old:key": {
                "source_key": "local_fs:old:key",
                "source_name": "old.md",
                "source": "old.md",
                "schema_version": "1.0.0",
                "trace_id": "t0",
                "batch_id": "",
                "deleted": False,
                "deleted_at": "",
                "validation": {},
                "clean_hash": "",
            }
        }

        delete_calls = []

        with patch.object(impl_mod, "load_manifest", return_value=old_manifest), \
             patch.object(impl_mod, "save_manifest"), \
             patch.object(impl_mod, "get_client") as mock_get_client, \
             patch.object(impl_mod, "ensure_collection"), \
             patch.object(impl_mod, "delete_by_source_key", side_effect=lambda c, k, **kw: delete_calls.append(k)), \
             patch.object(impl_mod, "get_embedding_provider", return_value=MagicMock()), \
             patch.object(impl_mod, "ParserRegistry", return_value=MagicMock()), \
             patch.object(impl_mod, "ingest_file") as mock_ingest_file:

            ctx_client = MagicMock()
            mock_get_client.return_value.__enter__ = MagicMock(return_value=ctx_client)
            mock_get_client.return_value.__exit__ = MagicMock(return_value=False)

            ok_result = MagicMock()
            ok_result.errors = []
            ok_result.stored_count = 1
            ok_result.metadata_summary = ""
            ok_result.metadata_keywords = []
            ok_result.processing_log = []
            ok_result.source_hash = "h"
            ok_result.clean_hash = "ch"
            ok_result.trace_id = "t1"
            ok_result.validation = {}
            mock_ingest_file.return_value = ok_result

            from src.ingest.impl import ingest_directory
            ingest_directory(tmp_path, config=config, update=True)

        assert "local_fs:old:key" in delete_calls

    def test_mock_manifest_key_migration_on_success(self, tmp_path):
        """When matched_key != source_key, old key is removed from manifest."""
        import src.ingest.impl as impl_mod

        config = self._make_minimal_config()
        doc_file = tmp_path / "doc.md"
        doc_file.write_text("content")

        stat = doc_file.stat()
        current_source_key = f"local_fs:{stat.st_dev}:{stat.st_ino}"

        # Old manifest uses a legacy key for same content but different source_key
        old_manifest = {
            "local_fs:0:9999": {
                "source_key": "local_fs:0:9999",
                "source_uri": doc_file.as_uri(),  # match by URI
                "source_name": "doc.md",
                "source": "doc.md",
                "content_hash": "",
                "schema_version": "1.0.0",
                "trace_id": "t-old",
                "batch_id": "",
                "deleted": False,
                "deleted_at": "",
                "validation": {},
                "clean_hash": "",
            }
        }

        with patch.object(impl_mod, "load_manifest", return_value=old_manifest), \
             patch.object(impl_mod, "save_manifest") as mock_save, \
             patch.object(impl_mod, "get_client") as mock_get_client, \
             patch.object(impl_mod, "ensure_collection"), \
             patch.object(impl_mod, "get_embedding_provider", return_value=MagicMock()), \
             patch.object(impl_mod, "ParserRegistry", return_value=MagicMock()), \
             patch.object(impl_mod, "ingest_file") as mock_ingest_file:

            ctx_client = MagicMock()
            mock_get_client.return_value.__enter__ = MagicMock(return_value=ctx_client)
            mock_get_client.return_value.__exit__ = MagicMock(return_value=False)

            ok_result = MagicMock()
            ok_result.errors = []
            ok_result.stored_count = 1
            ok_result.metadata_summary = ""
            ok_result.metadata_keywords = []
            ok_result.processing_log = []
            ok_result.source_hash = "h"
            ok_result.clean_hash = "ch"
            ok_result.trace_id = "t-new"
            ok_result.validation = {}
            mock_ingest_file.return_value = ok_result

            from src.ingest.impl import ingest_directory
            ingest_directory(tmp_path, config=config, update=True)

        # The final manifest passed to save_manifest should not contain the old key
        last_call_manifest = mock_save.call_args_list[-1][0][0]
        assert "local_fs:0:9999" not in last_call_manifest
