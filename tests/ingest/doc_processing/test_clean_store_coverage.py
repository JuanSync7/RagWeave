"""Extended coverage tests for CleanDocumentStore.

Covers tmp-file cleanup on failure, boundary conditions, _safe_key sanitization,
and delete/list behaviour not exercised by tests/ingest/test_clean_store.py.
"""
import hashlib
from pathlib import Path
from unittest.mock import patch

import orjson
import pytest

from src.ingest.common.clean_store import CleanDocumentStore


# ---------------------------------------------------------------------------
# TestCleanStoreTmpCleanup
# ---------------------------------------------------------------------------


class TestCleanStoreTmpCleanup:
    """Verify that tmp files are cleaned up when a write fails mid-way."""

    def test_clean_store_write_cleans_up_tmp_files_on_failure(self, tmp_path):
        """orjson.dumps raising ValueError must leave no .tmp files behind."""
        store = CleanDocumentStore(tmp_path)
        with patch(
            "src.ingest.common.clean_store.orjson.dumps",
            side_effect=ValueError("serialize error"),
        ):
            with pytest.raises(ValueError, match="serialize error"):
                store.write("key", "text", {})

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Unexpected tmp files left: {tmp_files}"

    def test_clean_store_write_does_not_leave_partial_md_on_meta_failure(
        self, tmp_path
    ):
        """When orjson.dumps fails after tmp_md is written, both tmp files are removed."""
        store = CleanDocumentStore(tmp_path)
        with patch(
            "src.ingest.common.clean_store.orjson.dumps",
            side_effect=ValueError("serialize error"),
        ):
            with pytest.raises(ValueError):
                store.write("key2", "some text", {"x": 1})

        assert list(tmp_path.glob("*.md.tmp")) == []
        assert list(tmp_path.glob("*.meta.json.tmp")) == []

    def test_clean_store_write_is_atomic_md_file(self, tmp_path):
        """After write(), the .md file on disk contains the exact text written."""
        store = CleanDocumentStore(tmp_path)
        text = "raw filesystem content check"
        store.write("doc", text, {})

        md_path = tmp_path / "doc.md"
        assert md_path.exists()
        assert md_path.read_text(encoding="utf-8") == text

    def test_clean_store_write_is_atomic_meta_file(self, tmp_path):
        """After write(), the .meta.json file on disk contains the exact metadata."""
        store = CleanDocumentStore(tmp_path)
        meta = {"source_name": "test.pdf"}
        store.write("doc2", "text", meta)

        meta_path = tmp_path / "doc2.meta.json"
        assert meta_path.exists()
        loaded = orjson.loads(meta_path.read_bytes())
        assert loaded == meta


# ---------------------------------------------------------------------------
# TestCleanStoreBoundary
# ---------------------------------------------------------------------------


class TestCleanStoreBoundary:
    """Boundary and edge-case behaviour for CleanDocumentStore."""

    def test_clean_store_write_creates_directory_on_first_write(self, tmp_path):
        """store_dir is created automatically on the first write call."""
        store_dir = tmp_path / "nonexistent" / "store"
        assert not store_dir.exists()

        store = CleanDocumentStore(store_dir)
        store.write("key", "hello", {})

        assert store_dir.exists()
        text, _ = store.read("key")
        assert text == "hello"

    def test_clean_store_write_handles_empty_text(self, tmp_path):
        """Writing empty text produces a zero-byte .md file and reads back correctly."""
        store = CleanDocumentStore(tmp_path)
        store.write("empty-doc", "", {})

        md_path = tmp_path / "empty-doc.md"
        assert md_path.exists()
        assert md_path.stat().st_size == 0

        text, meta = store.read("empty-doc")
        assert text == ""
        assert meta == {}

    def test_clean_store_write_handles_empty_metadata(self, tmp_path):
        """Writing empty metadata dict round-trips back to an empty dict."""
        store = CleanDocumentStore(tmp_path)
        store.write("no-meta", "content", {})

        text, meta = store.read("no-meta")
        assert text == "content"
        assert meta == {}

    def test_clean_store_write_handles_unicode_text(self, tmp_path):
        """Unicode content (latin, emoji, CJK) survives a write/read round-trip."""
        store = CleanDocumentStore(tmp_path)
        unicode_text = "micro=µ emoji=🚀 cjk=中文"
        store.write("unicode-doc", unicode_text, {})

        text, _ = store.read("unicode-doc")
        assert text == unicode_text

    def test_clean_store_read_returns_empty_meta_when_meta_file_missing(
        self, tmp_path
    ):
        """read() returns ({}) when the .meta.json file has been manually removed."""
        store = CleanDocumentStore(tmp_path)
        store.write("key-no-meta", "hello", {"will": "be deleted"})

        meta_path = tmp_path / "key-no-meta.meta.json"
        meta_path.unlink()

        text, meta = store.read("key-no-meta")
        assert text == "hello"
        assert meta == {}

    def test_clean_store_list_keys_returns_empty_for_nonexistent_dir(self, tmp_path):
        """list_keys() returns [] when the store directory has never been created."""
        store = CleanDocumentStore(tmp_path / "never-created")
        assert store.list_keys() == []

    def test_clean_store_write_overwrites_existing_entry(self, tmp_path):
        """A second write to the same key replaces the first entry."""
        store = CleanDocumentStore(tmp_path)
        store.write("overwrite-key", "v1", {"ver": 1})
        store.write("overwrite-key", "v2", {"ver": 2})

        text, meta = store.read("overwrite-key")
        assert text == "v2"
        assert meta == {"ver": 2}


# ---------------------------------------------------------------------------
# TestCleanStoreSafeKey
# ---------------------------------------------------------------------------


class TestCleanStoreSafeKey:
    """Unit tests for the _safe_key() sanitization logic."""

    @pytest.fixture()
    def store(self, tmp_path):
        return CleanDocumentStore(tmp_path)

    def test_clean_store_safe_key_sanitizes_slashes(self, store):
        assert store._safe_key("a/b/c") == "a_b_c"

    def test_clean_store_safe_key_sanitizes_colons(self, store):
        assert store._safe_key("local_fs:42:100") == "local_fs_42_100"

    def test_clean_store_safe_key_sanitizes_double_dots(self, store):
        assert store._safe_key("..hidden") == "__hidden"

    def test_clean_store_safe_key_combined(self, store):
        # Replacement order: "/" → "_", then ":" → "_", then ".." → "__"
        # "local_fs:dev/ino:..test"
        # step 1 (/ → _):  "local_fs:dev_ino:..test"
        # step 2 (: → _):  "local_fs_dev_ino_..test"
        # step 3 (.. → __): "local_fs_dev_ino___test"  (_.. becomes ___)
        assert store._safe_key("local_fs:dev/ino:..test") == "local_fs_dev_ino___test"


# ---------------------------------------------------------------------------
# TestCleanStoreDeleteAndList
# ---------------------------------------------------------------------------


class TestCleanStoreDeleteAndList:
    """Tests for delete() and list_keys() edge cases."""

    def test_clean_store_delete_idempotent_for_missing_key(self, tmp_path):
        """Deleting a key that was never written must not raise any exception."""
        store = CleanDocumentStore(tmp_path)
        store.delete("nonexistent-key")  # should not raise

    def test_clean_store_list_keys_returns_all_stored_keys(self, tmp_path):
        """list_keys() includes every key that has been written."""
        store = CleanDocumentStore(tmp_path)
        store.write("key_a", "a", {})
        store.write("key_b", "b", {})
        store.write("key_c", "c", {})

        keys = store.list_keys()
        assert set(keys) == {"key_a", "key_b", "key_c"}

    def test_clean_store_list_keys_excludes_meta_json_files(self, tmp_path):
        """list_keys() must not include stems derived from .meta.json files."""
        store = CleanDocumentStore(tmp_path)
        store.write("real-key", "content", {})

        # Manually plant a stray .meta.json file in the store directory.
        # Its suffix is .json, so glob("*.md") will not match it.
        stray = tmp_path / "stray.meta.json"
        stray.write_bytes(orjson.dumps({"stray": True}))

        keys = store.list_keys()
        assert "stray.meta" not in keys
        assert "real-key" in keys

    def test_clean_store_clean_hash_is_deterministic(self, tmp_path):
        """clean_hash() returns the same digest for the same content written twice."""
        store = CleanDocumentStore(tmp_path)
        store.write("hash-key", "stable content", {})
        hash1 = store.clean_hash("hash-key")

        store.write("hash-key", "stable content", {})
        hash2 = store.clean_hash("hash-key")

        assert hash1 == hash2

    def test_clean_store_roundtrip_write_read(self, tmp_path):
        """write() followed by read() returns byte-identical text and metadata."""
        store = CleanDocumentStore(tmp_path)
        text = "Hello\nWorld"
        meta = {"k": "v"}
        store.write("roundtrip-key", text, meta)

        returned_text, returned_meta = store.read("roundtrip-key")
        assert returned_text == text
        assert returned_meta == meta
