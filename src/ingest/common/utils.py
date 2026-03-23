# @summary
# Shared deterministic ingestion utilities for manifest IO, hashing, text reads, and JSON parsing.
# Exports: sha256_path, load_manifest, save_manifest, read_text_with_fallbacks, parse_json_object
# Deps: config.settings, pathlib, json, hashlib, src.common.utils
# @end-summary
"""Deterministic utility helpers shared across ingestion modules.

These utilities are intentionally side-effect-light and stable so they can be
used across pipeline nodes without pulling in heavy dependencies.
"""

from __future__ import annotations

import hashlib
import orjson
import logging
import time
from pathlib import Path
from typing import Any

from config.settings import INGESTION_MANIFEST_PATH
from src.common.utils import parse_json_object

logger = logging.getLogger("rag.ingest.pipeline.stage")


def sha256_path(path: Path) -> str:
    """Compute the SHA-256 digest for a file path.

    Args:
        path: Path to the file to hash.

    Returns:
        Lowercase hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(path: Path = INGESTION_MANIFEST_PATH) -> dict[str, Any]:
    """Load the ingestion manifest JSON or return an empty manifest.

    If the manifest exists but cannot be parsed, the file is moved aside (best
    effort) and an empty manifest is returned.

    Args:
        path: Manifest path on disk.

    Returns:
        Parsed manifest dictionary. Returns an empty dictionary when missing or
        invalid.
    """
    if not path.exists():
        return {}
    try:
        raw_manifest = orjson.loads(path.read_bytes())
        return raw_manifest if isinstance(raw_manifest, dict) else {}
    except orjson.JSONDecodeError as exc:
        backup = path.with_name(f"{path.name}.corrupt.{int(time.time())}")
        try:
            path.replace(backup)
            logger.warning(
                "Corrupted ingestion manifest moved aside: %s -> %s (%s)",
                path,
                backup,
                exc,
            )
        except OSError:
            logger.warning("Corrupted ingestion manifest at %s (%s)", path, exc)
        return {}


def save_manifest(manifest: dict[str, Any], path: Path = INGESTION_MANIFEST_PATH) -> None:
    """Persist the ingestion manifest JSON to disk atomically.

    Args:
        manifest: Manifest payload to persist.
        path: Manifest path on disk.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_bytes(orjson.dumps(manifest, option=orjson.OPT_INDENT_2))
    tmp_path.replace(path)


def read_text_with_fallbacks(path: Path) -> str:
    """Read text content using fallback encodings for legacy documents.

    Args:
        path: Path to a text file to read.

    Returns:
        Decoded text content. Uses replacement characters as a last resort.
    """
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")

