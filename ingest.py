#!/usr/bin/env python3
# @summary
# Ingest documents from documents/ into Weaviate. Main exports: ingest, KnowledgeGraphBuilder, LocalBGEEmbeddings. Deps: pathlib, json, src.core.embeddings, src.ingest.markdown_processor, src.ingest.document_processor, src.core.knowledge_graph, src.core.vector_store, config.settings
# @end-summary
"""Ingest documents into Weaviate and optionally build a knowledge graph."""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import (
    DOCUMENTS_DIR,
    INGESTION_MANIFEST_PATH,
    PROJECT_ROOT,
)
from src.ingest.pipeline_impl import (
    IngestionConfig,
    ingest_directory,
    _load_manifest as _pipeline_load_manifest,
    _save_manifest as _pipeline_save_manifest,
    _sha256_path as _pipeline_sha256_path,
)
from src.platform.validation import validate_documents_dir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("rag.ingest")


def _sha256_path(path: Path) -> str:
    return _pipeline_sha256_path(path)


def _load_manifest() -> dict:
    return _pipeline_load_manifest(INGESTION_MANIFEST_PATH)


def _save_manifest(manifest: dict) -> None:
    _pipeline_save_manifest(manifest, INGESTION_MANIFEST_PATH)


def ingest(
    documents_dir: Path = DOCUMENTS_DIR,
    fresh: bool = True,
    update: bool = False,
    build_kg: bool = True,
    obsidian_export: bool = False,
    semantic_chunking: bool = True,
    export_processed: bool = False,
    selected_file: Optional[Path] = None,
    verbose_stages: Optional[bool] = None,
    persist_refactor_mirror: Optional[bool] = None,
) -> None:
    """Ingest documents from a directory or a single selected file.

    Args:
        documents_dir: Path to the directory containing documents.
        fresh: If True, delete existing collection before ingesting.
        build_kg: If True, build a knowledge graph from the chunks.
        obsidian_export: If True, export KG as Obsidian-compatible markdown files.
        semantic_chunking: If True, use semantic similarity for chunk splitting.
        export_processed: If True, save cleaned docs and chunks to processed/ dir.
        selected_file: Optional single file to ingest instead of all files.
        verbose_stages: Optional override for stage-by-stage progress logs.
        persist_refactor_mirror: Optional override for refactor mirror artifacts.
    """
    documents_dir = validate_documents_dir(documents_dir, PROJECT_ROOT)
    cfg_kwargs = {
        "semantic_chunking": semantic_chunking,
        "build_kg": build_kg,
        "export_processed": export_processed,
        "enable_knowledge_graph_extraction": build_kg,
        "enable_knowledge_graph_storage": build_kg,
    }
    if verbose_stages is not None:
        cfg_kwargs["verbose_stage_logs"] = verbose_stages
    if persist_refactor_mirror is not None:
        cfg_kwargs["persist_refactor_mirror"] = persist_refactor_mirror

    cfg = IngestionConfig(
        **cfg_kwargs,
    )
    selected_sources = None
    if selected_file is not None:
        selected_sources = [selected_file.resolve()]

    summary = ingest_directory(
        documents_dir=documents_dir,
        config=cfg,
        fresh=fresh,
        update=update,
        obsidian_export=obsidian_export,
        selected_sources=selected_sources,
    )
    logger.info(
        "Ingestion complete. processed=%d skipped=%d failed=%d stored_chunks=%d removed_sources=%d",
        summary.processed,
        summary.skipped,
        summary.failed,
        summary.stored_chunks,
        summary.removed_sources,
    )
    for err in summary.errors:
        logger.warning("Ingestion error: %s", err)
    for warning in summary.design_warnings:
        logger.warning("Ingestion design warning: %s", warning)


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser for ingestion."""
    parser = argparse.ArgumentParser(description="Ingest documents into RAG system")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--file",
        type=Path,
        help="Ingest a single document file only",
    )
    source_group.add_argument(
        "--dir",
        type=Path,
        help="Ingest all supported documents in a specific directory",
    )
    parser.add_argument(
        "--no-kg", action="store_true", help="Skip knowledge graph building"
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Incremental update mode (changed docs only; idempotent writes)",
    )
    parser.add_argument(
        "--export-obsidian",
        action="store_true",
        help="Export knowledge graph as Obsidian markdown files",
    )
    parser.add_argument(
        "--no-semantic",
        action="store_true",
        help="Disable semantic chunking (use character splitting only)",
    )
    parser.add_argument(
        "--export-processed",
        action="store_true",
        help="Export cleaned documents and chunks to processed/ directory",
    )
    # Tri-state by design: None -> use config default, True/False -> explicit override.
    parser.add_argument(
        "--verbose-stages",
        dest="verbose_stages",
        action="store_true",
        help="Print stage-by-stage ingestion progress for each source",
    )
    parser.add_argument(
        "--no-verbose-stages",
        dest="verbose_stages",
        action="store_false",
        help="Disable stage-by-stage ingestion progress for this run",
    )
    parser.set_defaults(verbose_stages=None)
    parser.add_argument(
        "--no-refactor-mirror",
        action="store_true",
        help="Disable writing original/refactored mirror artifacts and mappings",
    )
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()

    selected_file: Optional[Path] = None
    target_documents_dir = DOCUMENTS_DIR
    if args.file is not None:
        selected_file = args.file.resolve()
        if not selected_file.exists() or not selected_file.is_file():
            parser.error(f"--file must point to an existing file: {selected_file}")
        target_documents_dir = selected_file.parent
    elif args.dir is not None:
        target_documents_dir = validate_documents_dir(args.dir, PROJECT_ROOT)

    ingest(
        documents_dir=target_documents_dir,
        fresh=not args.update,
        update=args.update,
        build_kg=not args.no_kg,
        obsidian_export=args.export_obsidian,
        semantic_chunking=not args.no_semantic,
        export_processed=args.export_processed,
        selected_file=selected_file,
        verbose_stages=args.verbose_stages,
        persist_refactor_mirror=not args.no_refactor_mirror,
    )
