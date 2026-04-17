# @summary
# MinIO-backed durable clean document store for Phase 1 pipeline output.
# Exports: MinioCleanStore
# Deps: orjson, minio, minio.commonconfig, src.ingest.common.schemas
# @end-summary

"""MinIO-backed durable clean document store for Phase 1 output.

Objects are stored under the ``clean/`` prefix:
  - ``clean/{safe_key}.md``          -- UTF-8 clean markdown
  - ``clean/{safe_key}.meta.json``   -- JSON metadata envelope (FR-3033)

The ``.meta.json`` is written last as the commit marker so readers can
treat its presence as proof that both objects are consistent.
"""

from __future__ import annotations

import io
import logging
import re
import orjson
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("rag.ingest.minio_clean_store")

_UNSAFE_CHARS = re.compile(r'[/\\:*?"<>|]')
_CLEAN_PREFIX = "clean/"


def _safe_key(source_key: str) -> str:
    """Sanitize source_key for use in MinIO object keys."""
    return _UNSAFE_CHARS.sub("_", source_key).replace("..", "__")


class MinioCleanStore:
    """Durable clean document store backed by MinIO.

    Uses the raw MinIO client for all storage operations, keeping this
    module decoupled from the ``src.db`` UUID-based document store layer.
    Clients should be obtained via ``src.db.create_persistent_client()``.

    Object key layout::

        clean/{safe_key}.md          -- UTF-8 clean markdown (written first)
        clean/{safe_key}.meta.json   -- JSON metadata envelope (commit marker)
        deleted/{safe_key}.md        -- Tombstone after soft_delete()
        deleted/{safe_key}.meta.json -- Tombstone after soft_delete()

    Args:
        client: A MinIO client handle (from ``src.db.create_persistent_client()``).
        bucket: Target bucket name.
    """

    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    # -- Object key helpers ------------------------------------------------

    @staticmethod
    def _object_key_md(source_key: str) -> str:
        """Return the MinIO object key for the clean markdown object."""
        return f"{_CLEAN_PREFIX}{_safe_key(source_key)}.md"

    @staticmethod
    def _object_key_meta(source_key: str) -> str:
        """Return the MinIO object key for the metadata envelope (commit marker)."""
        return f"{_CLEAN_PREFIX}{_safe_key(source_key)}.meta.json"

    # -- Write -------------------------------------------------------------

    def write(
        self,
        source_key: str,
        text: str,
        meta: dict[str, Any],
    ) -> None:
        """Write clean markdown and metadata to MinIO.

        The markdown object is written first; the ``.meta.json`` is written
        last as the commit marker (FR-3033 AC4). Content types are set to
        ``text/markdown`` and ``application/json`` respectively.

        Args:
            source_key: Stable source identity key.
            text: Clean markdown text (UTF-8).
            meta: Metadata envelope dict. Must include source identity fields,
                ``source_hash``, ``clean_hash``, ``schema_version``, ``trace_id``.
        """
        md_key = self._object_key_md(source_key)
        meta_key = self._object_key_meta(source_key)

        # Ensure created_at is present
        if "created_at" not in meta:
            meta["created_at"] = datetime.now(timezone.utc).isoformat()

        # Write markdown first
        md_bytes = text.encode("utf-8")
        self._client.put_object(
            self._bucket,
            md_key,
            io.BytesIO(md_bytes),
            length=len(md_bytes),
            content_type="text/markdown",
        )

        # Write metadata envelope last (commit marker)
        meta_bytes = orjson.dumps(meta, option=orjson.OPT_INDENT_2)
        self._client.put_object(
            self._bucket,
            meta_key,
            io.BytesIO(meta_bytes),
            length=len(meta_bytes),
            content_type="application/json",
        )

        logger.debug(
            "minio_clean_store_write source_key=%s md_key=%s meta_key=%s",
            source_key,
            md_key,
            meta_key,
        )

    # -- Read --------------------------------------------------------------

    def read(self, source_key: str) -> tuple[str, dict[str, Any]]:
        """Read clean markdown and metadata from MinIO.

        Args:
            source_key: Stable source identity key.

        Returns:
            Tuple of (clean_markdown_text, metadata_dict).

        Raises:
            Exception: If objects do not exist or cannot be read.
        """
        md_key = self._object_key_md(source_key)
        meta_key = self._object_key_meta(source_key)

        md_response = self._client.get_object(self._bucket, md_key)
        text = md_response.read().decode("utf-8")
        md_response.close()
        md_response.release_conn()

        meta_response = self._client.get_object(self._bucket, meta_key)
        meta = orjson.loads(meta_response.read())
        meta_response.close()
        meta_response.release_conn()

        return text, meta

    # -- Exists ------------------------------------------------------------

    def exists(self, source_key: str) -> bool:
        """Check if a clean document exists in MinIO for this source_key.

        Checks for the ``.meta.json`` object (the commit marker). A missing
        markdown file with a present meta file indicates a partial write, but
        the meta file's presence is the canonical existence signal (FR-3033 AC4).

        Args:
            source_key: Stable source identity key.

        Returns:
            True if the metadata commit marker exists, False otherwise.
        """
        meta_key = self._object_key_meta(source_key)
        try:
            self._client.stat_object(self._bucket, meta_key)
            return True
        except Exception:
            return False

    # -- Delete ------------------------------------------------------------

    def delete(self, source_key: str) -> None:
        """Remove both clean markdown and metadata objects from MinIO (hard delete).

        Missing objects are silently tolerated; errors are logged as warnings
        but do not raise (per GC store-isolation contract, NFR-3210).

        Args:
            source_key: Stable source identity key.
        """
        for key in (self._object_key_md(source_key), self._object_key_meta(source_key)):
            try:
                self._client.remove_object(self._bucket, key)
            except Exception as exc:
                logger.warning(
                    "minio_clean_store_delete_failed key=%s error=%s",
                    key,
                    exc,
                )

    # -- Soft delete (for GC) ----------------------------------------------

    def soft_delete(self, source_key: str) -> None:
        """Move clean objects to the ``deleted/`` prefix for retention (FR-3020).

        Copies both ``.md`` and ``.meta.json`` from ``clean/{safe_key}.*``
        to ``deleted/{safe_key}.*``, then removes the originals under ``clean/``.

        Errors per object are logged as warnings and do not raise, consistent
        with the GC store-isolation contract (NFR-3210).

        Args:
            source_key: Stable source identity key.
        """
        safe = _safe_key(source_key)
        for suffix in (".md", ".meta.json"):
            src_key = f"{_CLEAN_PREFIX}{safe}{suffix}"
            dst_key = f"deleted/{safe}{suffix}"
            try:
                from minio.commonconfig import CopySource

                self._client.copy_object(
                    self._bucket,
                    dst_key,
                    CopySource(self._bucket, src_key),
                )
                self._client.remove_object(self._bucket, src_key)
            except Exception as exc:
                logger.warning(
                    "minio_clean_store_soft_delete_failed src=%s dst=%s error=%s",
                    src_key,
                    dst_key,
                    exc,
                )

    # -- List keys ---------------------------------------------------------

    def list_keys(self) -> list[str]:
        """List all source_keys with clean documents in MinIO.

        Enumerates ``.meta.json`` objects under the ``clean/`` prefix and
        strips the prefix and suffix to recover the safe key. Only returns
        keys under ``clean/`` (not tombstoned ``deleted/`` objects).

        Returns:
            List of safe_key strings (sanitized source_keys).
        """
        keys: list[str] = []
        objects = self._client.list_objects(
            self._bucket, prefix=_CLEAN_PREFIX, recursive=True
        )
        for obj in objects:
            name = obj.object_name or ""
            if name.endswith(".meta.json"):
                # Extract safe_key: strip "clean/" prefix and ".meta.json" suffix
                safe = name[len(_CLEAN_PREFIX): -len(".meta.json")]
                keys.append(safe)
        return keys
