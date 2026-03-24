"""Tests for CleanDocumentStore atomic read/write."""
import pytest
from pathlib import Path
from src.ingest.clean_store import CleanDocumentStore


def test_write_and_read(tmp_path):
    store = CleanDocumentStore(tmp_path)
    store.write("key1", "hello world", {"source_name": "doc.pdf"})
    text, meta = store.read("key1")
    assert text == "hello world"
    assert meta["source_name"] == "doc.pdf"


def test_exists_false_before_write(tmp_path):
    store = CleanDocumentStore(tmp_path)
    assert not store.exists("missing_key")


def test_exists_true_after_write(tmp_path):
    store = CleanDocumentStore(tmp_path)
    store.write("key2", "content", {})
    assert store.exists("key2")


def test_clean_hash_matches_content(tmp_path):
    import hashlib
    store = CleanDocumentStore(tmp_path)
    store.write("key3", "hello", {})
    expected = hashlib.sha256("hello".encode("utf-8")).hexdigest()
    assert store.clean_hash("key3") == expected


def test_delete_removes_entry(tmp_path):
    store = CleanDocumentStore(tmp_path)
    store.write("key4", "bye", {})
    store.delete("key4")
    assert not store.exists("key4")


def test_list_keys(tmp_path):
    store = CleanDocumentStore(tmp_path)
    store.write("a", "x", {})
    store.write("b", "y", {})
    assert set(store.list_keys()) == {"a", "b"}


def test_read_raises_if_missing(tmp_path):
    store = CleanDocumentStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.read("no_such_key")


def test_write_is_atomic(tmp_path):
    """Interrupted write must not leave partial files."""
    store = CleanDocumentStore(tmp_path)
    store.write("key5", "content", {"x": 1})
    store.write("key5", "new content", {"x": 2})
    text, meta = store.read("key5")
    assert text == "new content"
    assert meta["x"] == 2
    assert not list(tmp_path.glob("*.tmp"))


def test_clean_hash_raises_if_missing(tmp_path):
    store = CleanDocumentStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.clean_hash("no_such_key")


def test_list_keys_empty_if_dir_missing(tmp_path):
    store = CleanDocumentStore(tmp_path / "nonexistent")
    assert store.list_keys() == []


def test_key_with_special_chars_round_trips(tmp_path):
    """Keys containing / and : must survive write/read round-trip."""
    store = CleanDocumentStore(tmp_path)
    store.write("local_fs:dev:123", "content", {"k": "v"})
    assert store.exists("local_fs:dev:123")
    text, meta = store.read("local_fs:dev:123")
    assert text == "content"
    assert meta["k"] == "v"
