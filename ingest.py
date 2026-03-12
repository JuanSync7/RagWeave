#!/usr/bin/env python3
# @summary
# Ingest documents from documents/ into Weaviate. Main exports: ingest, KnowledgeGraphBuilder, LocalBGEEmbeddings. Deps: pathlib, json, src.core.embeddings, src.ingest.markdown_processor, src.ingest.document_processor, src.core.knowledge_graph, src.core.vector_store, config.settings
# @end-summary
"""Ingest documents from the documents/ folder into Weaviate and build knowledge graph."""

import logging
import sys
from pathlib import Path

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
) -> None:
    """Ingest all text files from the documents directory.

    Args:
        documents_dir: Path to the directory containing documents.
        fresh: If True, delete existing collection before ingesting.
        build_kg: If True, build a knowledge graph from the chunks.
        obsidian_export: If True, export KG as Obsidian-compatible markdown files.
        semantic_chunking: If True, use semantic similarity for chunk splitting.
        export_processed: If True, save cleaned docs and chunks to processed/ dir.
    """
    documents_dir = validate_documents_dir(documents_dir, PROJECT_ROOT)
    cfg = IngestionConfig(
        semantic_chunking=semantic_chunking,
        build_kg=build_kg,
        export_processed=export_processed,
        enable_knowledge_graph_extraction=build_kg,
        enable_knowledge_graph_storage=build_kg,
    )
    summary = ingest_directory(
        documents_dir=documents_dir,
        config=cfg,
        fresh=fresh,
        update=update,
        obsidian_export=obsidian_export,
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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingest documents into RAG system")
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
    args = parser.parse_args()

    ingest(
        fresh=not args.update,
        update=args.update,
        build_kg=not args.no_kg,
        obsidian_export=args.export_obsidian,
        semantic_chunking=not args.no_semantic,
        export_processed=args.export_processed,
    )
