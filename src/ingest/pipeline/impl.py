# @summary
# 13-node LangGraph ingestion implementation with configurable optional stages.
# @end-summary

"""Ingestion pipeline runtime orchestration and public implementation API.

This module provides the primary entrypoints for running the ingestion workflow
over a file or directory, including:

- Source discovery and stable identity generation
- Idempotency checks using a persisted manifest (incremental updates)
- Orchestration of the compiled LangGraph workflow
- Persistence of processed outputs (vector store, optional mirrors/artifacts)
"""

from __future__ import annotations

import hashlib
import orjson
import logging
from pathlib import Path
from typing import Any, Optional

from config.settings import (
    GLINER_ENABLED,
    KG_OBSIDIAN_EXPORT_DIR,
    KG_PATH,
    PROCESSED_DIR,
    RAG_INGESTION_MIRROR_DIR,
    RAG_INGESTION_EXPORT_EXTENSIONS,
)
from src.core.embeddings import LocalBGEEmbeddings
from src.core.knowledge_graph import KnowledgeGraphBuilder, export_obsidian
from src.core.vector_store import (
    delete_collection,
    delete_documents_by_source_key,
    ensure_collection,
    get_weaviate_client,
)
from src.ingest.support.docling import ensure_docling_ready
from src.ingest.support.vision import ensure_vision_ready
from src.ingest.common.schemas import ManifestEntry, SourceIdentity
from src.ingest.common.utils import load_manifest, save_manifest, sha256_path
from src.ingest.common.shared import _extract_keywords_fallback
from src.ingest.common.types import (
    IngestionConfig,
    IngestionDesignCheck,
    IngestionRunSummary,
    PIPELINE_NODE_NAMES,
    Runtime,
)
from src.ingest.clean_store import CleanDocumentStore
from src.ingest.doc_processing.impl import run_document_processing
from src.ingest.embedding.impl import run_embedding_pipeline

logger = logging.getLogger("rag.ingest.pipeline")
_LOCAL_CONNECTOR = "local_fs"


def _safe_relative(path: Path, root: Path) -> str:
    """Return a stable display path relative to a root when possible.

    Args:
        path: Path to render.
        root: Root directory to attempt making `path` relative to.

    Returns:
        Relative path string when `path` is within `root`, otherwise the resolved
        absolute path string.
    """
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _local_source_identity(path: Path, documents_root: Path) -> SourceIdentity:
    """Build stable source identity fields for local filesystem ingestion.

    Args:
        path: Path to the source file.
        documents_root: Root directory used for display names.

    Returns:
        A `SourceIdentity` mapping containing stable keys suitable for
        idempotency checks and manifest indexing.
    """
    resolved = path.resolve()
    stat = resolved.stat()
    source_id = f"{stat.st_dev}:{stat.st_ino}"
    source_key = f"{_LOCAL_CONNECTOR}:{source_id}"
    return {
        "source_path": str(resolved),
        "source_name": _safe_relative(resolved, documents_root),
        "source_uri": resolved.as_uri(),
        "source_id": source_id,
        "source_key": source_key,
        "connector": _LOCAL_CONNECTOR,
        "source_version": str(stat.st_mtime_ns),
    }


def _mirror_file_stem(source_name: str, source_key: str) -> str:
    """Return a stable mirror filename stem for a source.

    Args:
        source_name: Display name for the source (often relative path).
        source_key: Stable source key used for hashing.

    Returns:
        A filesystem-safe stem value.
    """
    safe_name = source_name.replace("/", "__").replace("\\", "__")
    suffix = hashlib.sha1(source_key.encode("utf-8")).hexdigest()[:8]
    return f"{safe_name}.{suffix}"


def _write_refactor_mirror_artifacts(
    source: SourceIdentity,
    result: dict,
    config: IngestionConfig,
) -> None:
    """Persist original/refactored mirrors plus chunk-level provenance mapping.

    Args:
        source: Source identity payload.
        result: Ingestion graph result payload.
        config: Ingestion configuration controlling mirror directory.
    """
    mirror_dir = Path(config.mirror_output_dir or str(RAG_INGESTION_MIRROR_DIR))
    mirror_dir.mkdir(parents=True, exist_ok=True)
    stem = _mirror_file_stem(source["source_name"], source["source_key"])
    original_path = mirror_dir / f"{stem}.original.md"
    refactored_path = mirror_dir / f"{stem}.refactored.md"
    mapping_path = mirror_dir / f"{stem}.mapping.json"

    original_path.write_text(str(result.get("raw_text", "")), encoding="utf-8")
    refactored_path.write_text(str(result.get("refactored_text", "")), encoding="utf-8")

    mapping_payload = {
        "source": source["source_name"],
        "source_uri": source["source_uri"],
        "source_key": source["source_key"],
        "source_id": source["source_id"],
        "connector": source["connector"],
        "source_version": source["source_version"],
        "original_mirror_path": str(original_path),
        "refactored_mirror_path": str(refactored_path),
        "chunks": [
            {
                "chunk_index": int(chunk.metadata.get("chunk_index", idx)),
                "chunk_id": str(chunk.metadata.get("chunk_id", "")),
                "retrieval_text_origin": str(chunk.metadata.get("retrieval_text_origin", "")),
                "original_char_start": int(chunk.metadata.get("original_char_start", -1)),
                "original_char_end": int(chunk.metadata.get("original_char_end", -1)),
                "refactored_char_start": int(chunk.metadata.get("refactored_char_start", -1)),
                "refactored_char_end": int(chunk.metadata.get("refactored_char_end", -1)),
                "provenance_method": str(chunk.metadata.get("provenance_method", "")),
                "provenance_confidence": float(chunk.metadata.get("provenance_confidence", 0.0)),
            }
            for idx, chunk in enumerate(result.get("chunks", []))
        ],
    }
    mapping_path.write_bytes(orjson.dumps(mapping_payload, option=orjson.OPT_INDENT_2))


def _normalize_manifest_entries(
    manifest: dict[str, Any],
) -> dict[str, ManifestEntry]:
    """Normalize old/new manifest formats into a source_key-indexed mapping.

    Args:
        manifest: Raw manifest mapping loaded from disk.

    Returns:
        Normalized mapping keyed by `source_key`.
    """
    normalized: dict[str, ManifestEntry] = {}
    for raw_key, raw_entry in manifest.items():
        if not isinstance(raw_entry, dict):
            continue
        entry = dict(raw_entry)
        source_key = str(entry.get("source_key", "")).strip()
        if not source_key:
            key_text = str(raw_key)
            if key_text.startswith(f"{_LOCAL_CONNECTOR}:"):
                source_key = key_text
            else:
                source_key = f"legacy_name:{key_text}"
                entry.setdefault("legacy_name", key_text)
        entry["source_key"] = source_key
        normalized[source_key] = entry
    return normalized


def _find_manifest_entry(
    manifest: dict[str, ManifestEntry],
    source: SourceIdentity,
) -> tuple[Optional[str], ManifestEntry]:
    """Find the best manifest match for a discovered source identity.

    Matching proceeds from most-stable to least-stable identifiers:
    ``source_key`` → ``source_id`` → ``source_uri`` → legacy filename.

    Args:
        manifest: Normalized manifest mapping keyed by `source_key`.
        source: Discovered source identity.

    Returns:
        Tuple of ``(matched_key, entry)``. When no match is found, returns
        ``(None, ManifestEntry())``.
    """
    direct = manifest.get(source["source_key"])
    if direct is not None:
        return source["source_key"], direct

    for key, entry in manifest.items():
        if entry.get("source_id") == source["source_id"]:
            return key, entry
    for key, entry in manifest.items():
        if entry.get("source_uri") == source["source_uri"]:
            return key, entry

    leaf_name = Path(source["source_path"]).name
    for key, entry in manifest.items():
        if entry.get("legacy_name") == leaf_name:
            return key, entry
    return None, ManifestEntry()


def verify_core_design(config: IngestionConfig) -> IngestionDesignCheck:
    """Validate ingestion configuration compatibility and return actionable feedback.

    Args:
        config: Ingestion configuration to validate.

    Returns:
        An `IngestionDesignCheck` containing errors and warnings.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if config.chunk_overlap >= config.chunk_size:
        errors.append("chunk_overlap must be < chunk_size")
    if config.enable_knowledge_graph_storage and not config.enable_knowledge_graph_extraction:
        errors.append("knowledge_graph_storage requires knowledge_graph_extraction")
    if config.enable_knowledge_graph_storage and not config.build_kg:
        errors.append("knowledge_graph_storage requires build_kg=True")
    if config.enable_document_refactoring and not config.enable_llm_metadata:
        warnings.append("refactoring enabled but LLM disabled; cleaned text used")
    if config.enable_docling_parser and not str(config.docling_model).strip():
        errors.append("docling parser requires a non-empty docling_model")
    if config.enable_vision_processing:
        if not config.enable_multimodal_processing:
            errors.append("vision processing requires multimodal_processing to be enabled")
    return IngestionDesignCheck(ok=not errors, errors=errors, warnings=warnings)


def ingest_file(
    source_path: Path,
    runtime: Runtime,
    source_name: str,
    source_uri: str,
    source_key: str,
    source_id: str,
    connector: str,
    source_version: str,
    existing_hash: str = "",
    existing_source_uri: str = "",
) -> dict:
    """Run the two-phase ingestion pipeline for a single source file.

    Phase 1 (Document Processing) extracts and cleans the document.
    Phase 2 (Embedding Pipeline) chunks, embeds, and stores vectors.
    The CleanDocumentStore persists Phase 1 output as the boundary.

    Args:
        source_path: Source file path.
        runtime: Runtime container with shared dependencies.
        source_name: Display name for the source.
        source_uri: Stable URI for the source.
        source_key: Stable source key used for idempotency.
        source_id: Stable identity for the source.
        connector: Connector identifier.
        source_version: Source version string.
        existing_hash: Previously stored content hash (for incremental updates).
        existing_source_uri: Previously stored URI (for incremental updates).

    Returns:
        Dict with keys: ``errors`` (list), ``stored_count`` (int),
        ``metadata_summary`` (str), ``metadata_keywords`` (list),
        ``processing_log`` (list), ``source_hash`` (str), ``clean_hash`` (str).
    """
    config = runtime.config
    clean_store_dir = config.clean_store_dir
    store = CleanDocumentStore(Path(clean_store_dir)) if clean_store_dir else None

    # ── Phase 1 ──────────────────────────────────────────────────────────
    phase1 = run_document_processing(
        runtime=runtime,
        source_path=str(source_path),
        source_name=source_name,
        source_uri=source_uri,
        source_key=source_key,
        source_id=source_id,
        connector=connector,
        source_version=source_version,
    )

    if phase1.get("errors"):
        return {
            "errors": phase1["errors"],
            "stored_count": 0,
            "metadata_summary": "",
            "metadata_keywords": [],
            "processing_log": phase1.get("processing_log", []),
            "source_hash": phase1.get("source_hash", ""),
            "clean_hash": "",
        }

    # Determine final clean text
    clean_text: str = phase1.get("refactored_text") or phase1.get("cleaned_text", "")

    # ── Persist to CleanDocumentStore ─────────────────────────────────────
    if store is not None:
        meta = {
            "source_key": source_key,
            "source_name": source_name,
            "source_uri": source_uri,
            "source_id": source_id,
            "connector": connector,
            "source_version": source_version,
            "source_hash": phase1.get("source_hash", ""),
            "refactored_text": phase1.get("refactored_text"),
        }
        store.write(source_key, clean_text, meta)
        clean_hash = store.clean_hash(source_key)
    else:
        clean_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()

    # ── Write mirror artifacts (optional) ─────────────────────────────────
    if config.persist_refactor_mirror:
        source_identity = {
            "source_path": str(source_path),
            "source_name": source_name,
            "source_uri": source_uri,
            "source_key": source_key,
            "source_id": source_id,
            "connector": connector,
            "source_version": source_version,
        }
        _write_refactor_mirror_artifacts(source_identity, phase1, config)

    # ── Phase 2 ──────────────────────────────────────────────────────────
    phase2 = run_embedding_pipeline(
        runtime=runtime,
        source_key=source_key,
        source_name=source_name,
        source_uri=source_uri,
        source_id=source_id,
        connector=connector,
        source_version=source_version,
        clean_text=clean_text,
        clean_hash=clean_hash,
        refactored_text=phase1.get("refactored_text"),
    )

    return {
        "errors": phase2.get("errors", []),
        "stored_count": phase2.get("stored_count", 0),
        "metadata_summary": phase2.get("metadata_summary", ""),
        "metadata_keywords": phase2.get("metadata_keywords", []),
        "processing_log": phase1.get("processing_log", []) + phase2.get("processing_log", []),
        "source_hash": phase1.get("source_hash", ""),
        "clean_hash": clean_hash,
    }


def ingest_directory(
    documents_dir: Path,
    config: Optional[IngestionConfig] = None,
    fresh: bool = True,
    update: bool = False,
    obsidian_export: bool = False,
    selected_sources: Optional[list[Path]] = None,
) -> IngestionRunSummary:
    """Ingest a directory of documents and persist vectors/KG artifacts.

    Args:
        documents_dir: Directory containing source documents.
        config: Optional ingestion configuration. When omitted, defaults are used.
        fresh: Whether to start from a fresh vector store collection.
        update: Whether to run in incremental mode using the manifest.
        obsidian_export: Whether to export the knowledge graph to an Obsidian vault.
        selected_sources: Optional explicit list of files to ingest.

    Returns:
        An `IngestionRunSummary` describing the run outcome.

    Raises:
        ValueError: If configuration validation fails.
        RuntimeError: If required optional dependencies (e.g., Docling or vision)
            are enabled but not available.
    """
    config = config or IngestionConfig()
    config.update_mode = update
    design = verify_core_design(config)
    if not design.ok:
        raise ValueError("Invalid ingestion config: " + "; ".join(design.errors))
    if config.enable_docling_parser:
        ensure_docling_ready(
            parser_model=config.docling_model,
            artifacts_path=config.docling_artifacts_path,
            auto_download=config.docling_auto_download,
        )
    if config.enable_vision_processing:
        ensure_vision_ready(config)

    manifest = _normalize_manifest_entries(load_manifest())
    errors: list[str] = []
    processed = skipped = failed = stored_chunks = 0

    patterns = [
        pattern.strip()
        for pattern in RAG_INGESTION_EXPORT_EXTENSIONS.split(",")
        if pattern.strip()
    ]
    allowed_suffixes = {pattern.lower() for pattern in patterns}
    if selected_sources is None:
        files = sorted(
            {path.resolve() for p in patterns for path in documents_dir.rglob(f"*{p}")}
        )
    else:
        files = sorted(
            {
                path.resolve()
                for path in selected_sources
                if path.is_file() and path.suffix.lower() in allowed_suffixes
            }
        )
    if not files:
        return IngestionRunSummary(0, 0, 0, 0, 0, [], design.warnings)

    sources = [_local_source_identity(path, documents_dir) for path in files]
    source_keys = {source["source_key"] for source in sources}

    removed_sources = (
        sorted(set(manifest.keys()) - source_keys)
        if update and selected_sources is None
        else []
    )

    with get_weaviate_client() as client:
        if fresh:
            delete_collection(client)
            manifest = {}
        ensure_collection(client)

        for source in removed_sources:
            delete_documents_by_source_key(
                client,
                source,
                legacy_source=str(manifest.get(source, {}).get("source", "")),
            )
            manifest.pop(source, None)

        runtime = Runtime(
            config=config,
            embedder=LocalBGEEmbeddings(),
            weaviate_client=client,
            kg_builder=KnowledgeGraphBuilder(use_gliner=GLINER_ENABLED)
            if config.build_kg
            else None,
        )

        if config.export_processed:
            PROCESSED_DIR.mkdir(exist_ok=True)

        for source in sources:
            source_path = Path(source["source_path"])
            logger.info(
                "ingestion_start source=%s source_key=%s",
                source["source_name"],
                source["source_key"],
            )
            matched_key, matched_entry = _find_manifest_entry(manifest, source)
            previous_hash = matched_entry.get("content_hash", "") if update else ""
            previous_uri = matched_entry.get("source_uri", "") if update else ""
            # Idempotency check: skip if source unchanged and clean store entry exists
            if update and previous_hash:
                current_hash = sha256_path(source_path)
                store_ok = (not config.clean_store_dir) or CleanDocumentStore(
                    Path(config.clean_store_dir)
                ).exists(source["source_key"])
                if current_hash == previous_hash and store_ok:
                    skipped += 1
                    if matched_key and matched_key != source["source_key"]:
                        manifest.pop(matched_key, None)
                    manifest[source["source_key"]] = {
                        **matched_entry,
                        "source": source["source_name"],
                        "source_uri": source["source_uri"],
                        "source_id": source["source_id"],
                        "source_key": source["source_key"],
                        "connector": source["connector"],
                        "source_version": source["source_version"],
                        "content_hash": previous_hash,
                    }
                    save_manifest(manifest)
                    logger.info(
                        "ingestion_skipped source=%s source_key=%s reason=unchanged",
                        source["source_name"],
                        source["source_key"],
                    )
                    continue
            try:
                result = ingest_file(
                    source_path,
                    runtime,
                    source_name=source["source_name"],
                    source_uri=source["source_uri"],
                    source_key=source["source_key"],
                    source_id=source["source_id"],
                    connector=source["connector"],
                    source_version=source["source_version"],
                    existing_hash=previous_hash if update else "",
                    existing_source_uri=previous_uri if update else "",
                )
                if result["errors"]:
                    failed += 1
                    errors.extend(result["errors"])
                    logger.error(
                        "ingestion_failed source=%s source_key=%s errors=%s",
                        source["source_name"],
                        source["source_key"],
                        "; ".join(result["errors"]),
                    )
                    continue

                processed += 1
                stored_chunks += int(result["stored_count"])
                logger.info(
                    "ingestion_done source=%s source_key=%s chunks=%d stored=%d stages=%s",
                    source["source_name"],
                    source["source_key"],
                    result.get("stored_count", 0),
                    int(result["stored_count"]),
                    " > ".join(result["processing_log"]),
                )
                if matched_key and matched_key != source["source_key"]:
                    manifest.pop(matched_key, None)
                stem = _mirror_file_stem(source["source_name"], source["source_key"])
                manifest[source["source_key"]] = {
                    "source": source["source_name"],
                    "source_uri": source["source_uri"],
                    "source_id": source["source_id"],
                    "source_key": source["source_key"],
                    "connector": source["connector"],
                    "source_version": source["source_version"],
                    "content_hash": result.get("source_hash", ""),
                    "chunk_count": result.get("stored_count", 0),
                    "summary": result["metadata_summary"],
                    "keywords": result["metadata_keywords"],
                    "processing_log": result["processing_log"][-12:],
                    "mirror_stem": stem,
                }
                save_manifest(manifest)

                if config.export_processed and config.clean_store_dir:
                    _store = CleanDocumentStore(Path(config.clean_store_dir))
                    if _store.exists(source["source_key"]):
                        _clean_text, _ = _store.read(source["source_key"])
                        export_stem = f"{source_path.stem}.{hashlib.sha1(source['source_key'].encode('utf-8')).hexdigest()[:8]}"
                        PROCESSED_DIR.mkdir(exist_ok=True)
                        (PROCESSED_DIR / f"{export_stem}.cleaned.md").write_text(_clean_text, encoding="utf-8")
            except Exception as exc:
                failed += 1
                logger.exception(
                    "ingestion_unhandled_error source=%s error=%s",
                    source.get("source_name", "unknown"),
                    exc,
                )
                errors.append(f"unhandled:{source.get('source_name', 'unknown')}:{exc}")
                continue

        if runtime.kg_builder is not None:
            runtime.kg_builder.save(KG_PATH)
            if obsidian_export:
                export_obsidian(runtime.kg_builder.graph, KG_OBSIDIAN_EXPORT_DIR)

    save_manifest(manifest)
    return IngestionRunSummary(
        processed=processed,
        skipped=skipped,
        failed=failed,
        stored_chunks=stored_chunks,
        removed_sources=len(removed_sources),
        errors=errors,
        design_warnings=design.warnings,
    )


__all__ = [
    "PIPELINE_NODE_NAMES",
    "IngestionConfig",
    "IngestionDesignCheck",
    "IngestionRunSummary",
    "Runtime",
    "ingest_directory",
    "ingest_file",
    "verify_core_design",
]
