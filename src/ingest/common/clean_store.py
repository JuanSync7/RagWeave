# @summary
# Atomic persistent store for clean Markdown documents between pipeline phases.
# Exports: CleanDocumentStore
# Deps: orjson, hashlib, pathlib
# @end-summary

"""CleanDocumentStore — atomic read/write of clean Markdown between pipeline phases."""

from __future__ import annotations

import hashlib
import orjson
from pathlib import Path
from typing import Any


class CleanDocumentStore:
    """Persistent store for clean Markdown output from Phase 1.

    Stores each document as two files:
      - ``{store_dir}/{source_key}.md``       — clean Markdown text
      - ``{store_dir}/{source_key}.meta.json`` — source identity metadata

    All writes are atomic: content is written to a ``.tmp`` file and
    then renamed into place, preventing partial reads on failure.

    Args:
        store_dir: Directory in which to store documents. Created on first write.
    """

    def __init__(self, store_dir: Path) -> None:
        self._dir = Path(store_dir)

    def _safe_key(self, source_key: str) -> str:
        """Sanitize source key for use in filesystem paths."""
        return source_key.replace("/", "_").replace(":", "_").replace("..", "__")

    def _md_path(self, source_key: str) -> Path:
        return self._dir / f"{self._safe_key(source_key)}.md"

    def _meta_path(self, source_key: str) -> Path:
        return self._dir / f"{self._safe_key(source_key)}.meta.json"

    def write(self, source_key: str, text: str, meta: dict[str, Any]) -> None:
        """Atomically write clean text and metadata for a source key."""
        self._dir.mkdir(parents=True, exist_ok=True)
        md_path = self._md_path(source_key)
        meta_path = self._meta_path(source_key)

        tmp_md = md_path.with_suffix(".md.tmp")
        tmp_meta = meta_path.with_suffix(".meta.json.tmp")

        try:
            tmp_md.write_text(text, encoding="utf-8")
            tmp_meta.write_bytes(orjson.dumps(meta))
            tmp_md.replace(md_path)
            tmp_meta.replace(meta_path)
        except (OSError, ValueError):
            tmp_md.unlink(missing_ok=True)
            tmp_meta.unlink(missing_ok=True)
            raise

    def read(self, source_key: str) -> tuple[str, dict[str, Any]]:
        """Read clean text and metadata for a source key."""
        md_path = self._md_path(source_key)
        meta_path = self._meta_path(source_key)
        if not md_path.exists():
            raise FileNotFoundError(f"CleanDocumentStore: no entry for {source_key!r}")
        text = md_path.read_text(encoding="utf-8")
        meta = orjson.loads(meta_path.read_bytes()) if meta_path.exists() else {}
        return text, meta

    def exists(self, source_key: str) -> bool:
        """Return True if a clean document entry exists for this key."""
        return self._md_path(source_key).exists()

    def clean_hash(self, source_key: str) -> str:
        """Return the SHA-256 hash of the stored clean text."""
        md_path = self._md_path(source_key)
        if not md_path.exists():
            raise FileNotFoundError(f"CleanDocumentStore: no entry for {source_key!r}")
        return hashlib.sha256(md_path.read_bytes()).hexdigest()

    def delete(self, source_key: str) -> None:
        """Remove the clean document entry for this key (both files)."""
        self._md_path(source_key).unlink(missing_ok=True)
        self._meta_path(source_key).unlink(missing_ok=True)

    def list_keys(self) -> list[str]:
        """Return all source keys currently stored."""
        if not self._dir.exists():
            return []
        return [p.stem for p in self._dir.glob("*.md") if p.suffix == ".md"]
