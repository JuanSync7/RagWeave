# @summary
# Shared deterministic ingestion utilities for manifest IO, hashing, text reads, and JSON parsing.
# Exports: sha256_path, load_manifest, save_manifest, read_text_with_fallbacks, parse_json_object
# Deps: config.settings, pathlib, json, hashlib, src.common.utils
# @end-summary
"""Deterministic utility helpers shared across ingestion modules."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from config.settings import INGESTION_MANIFEST_PATH
from src.common.utils import parse_json_object

logger = logging.getLogger("rag.ingest.pipeline.stage")


def sha256_path(path: Path) -> str:
    """Compute SHA-256 digest for a file path."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(path: Path = INGESTION_MANIFEST_PATH) -> dict[str, Any]:
    """Load ingestion manifest JSON or return an empty manifest."""
    if not path.exists():
        return {}
    try:
        raw_manifest = json.loads(path.read_text(encoding="utf-8"))
        return raw_manifest if isinstance(raw_manifest, dict) else {}
    except json.JSONDecodeError as exc:
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
    """Persist ingestion manifest JSON to disk atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def read_text_with_fallbacks(path: Path) -> str:
    """Read text content using fallback encodings for legacy docs."""
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")

