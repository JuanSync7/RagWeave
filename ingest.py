#!/usr/bin/env python3
# @summary
# Ingest documents from documents/ into Weaviate. Main exports: ingest, KnowledgeGraphBuilder, LocalBGEEmbeddings. Deps: pathlib, json, src.core.embeddings, src.ingest.markdown_processor, src.ingest.document_processor, src.core.knowledge_graph, src.core.vector_store, config.settings
# @end-summary
"""Ingest documents from the documents/ folder into Weaviate and build knowledge graph."""

import hashlib
import logging
import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent))

import json

from config.settings import (
    DOCUMENTS_DIR,
    KG_PATH,
    KG_OBSIDIAN_EXPORT_DIR,
    GLINER_ENABLED,
    PROCESSED_DIR,
    INGESTION_MANIFEST_PATH,
    PROJECT_ROOT,
)
from src.core.embeddings import LocalBGEEmbeddings
from src.ingest.markdown_processor import process_document_markdown, clean_document
from src.ingest.document_processor import extract_metadata, metadata_to_dict
from src.core.knowledge_graph import KnowledgeGraphBuilder, export_obsidian
from src.core.vector_store import (
    get_weaviate_client,
    ensure_collection,
    add_documents,
    delete_collection,
    delete_documents_by_source,
)
from src.platform.observability.providers import get_tracer
from src.platform.reliability.providers import get_retry_provider
from src.platform.validation import validate_documents_dir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("rag.ingest")
tracer = get_tracer()
retry_provider = get_retry_provider()


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest() -> dict:
    if not INGESTION_MANIFEST_PATH.exists():
        return {}
    try:
        return json.loads(INGESTION_MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_manifest(manifest: dict) -> None:
    INGESTION_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    INGESTION_MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


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
    # Gather document files
    documents_dir = validate_documents_dir(documents_dir, PROJECT_ROOT)
    manifest = _load_manifest()
    doc_files = sorted(documents_dir.glob("*.txt"))
    if not doc_files:
        logger.info("No .txt files found in %s", documents_dir)
        return

    logger.info("Found %d document(s) to ingest.", len(doc_files))
    root_span = tracer.start_span("ingest.run", {"doc_count": len(doc_files), "update_mode": update})
    span_status = "ok"
    span_error = None
    try:
        existing_sources = {f.name for f in doc_files}
        removed_sources = sorted(set(manifest.keys()) - existing_sources) if update else []

        if update:
            changed_files = []
            for doc_file in doc_files:
                content_hash = _sha256_path(doc_file)
                if manifest.get(doc_file.name, {}).get("content_hash") != content_hash:
                    changed_files.append(doc_file)
            doc_files = changed_files
            fresh = False
            logger.info(
                "Update mode: %d changed, %d removed, %d unchanged",
                len(doc_files),
                len(removed_sources),
                len(existing_sources) - len(doc_files),
            )

        # Load embedder FIRST so it can be shared for semantic chunking + final embedding
        logger.info("Loading embedding model...")
        embedder = LocalBGEEmbeddings()

        # Process documents into chunks
        all_chunks = []
        kg_builder = KnowledgeGraphBuilder(use_gliner=GLINER_ENABLED) if build_kg else None

        if export_processed:
            PROCESSED_DIR.mkdir(exist_ok=True)

        for doc_file in doc_files:
            logger.info("Processing: %s", doc_file.name)
            file_span = tracer.start_span("ingest.process_document", {"source": doc_file.name}, parent=root_span)
            raw_text = doc_file.read_text(encoding="utf-8")
            chunks = process_document_markdown(
                raw_text,
                source=doc_file.name,
                embedder=embedder if semantic_chunking else None,
            )
            all_chunks.extend(chunks)
            manifest[doc_file.name] = {
                "content_hash": _sha256_path(doc_file),
                "chunk_count": len(chunks),
            }

            # Feed chunks to knowledge graph builder
            if kg_builder:
                for chunk in chunks:
                    kg_builder.add_chunk(chunk.text, source=doc_file.name)

            # Export processed document for inspection
            if export_processed:
                stem = doc_file.stem
                # Save cleaned document (post-processing, pre-chunking)
                cleaned_text = clean_document(raw_text)
                doc_metadata = extract_metadata(raw_text, doc_file.name)
                (PROCESSED_DIR / f"{stem}.cleaned.md").write_text(
                    cleaned_text, encoding="utf-8"
                )
                # Save chunks as JSON with metadata
                chunks_data = [
                    {"chunk_index": i, "text": c.text, "metadata": c.metadata}
                    for i, c in enumerate(chunks)
                ]
                (PROCESSED_DIR / f"{stem}.chunks.json").write_text(
                    json.dumps(chunks_data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            file_span.end(status="ok")

        logger.info("Total chunks after processing: %d", len(all_chunks))
        if export_processed:
            logger.info("Processed documents exported to: %s", PROCESSED_DIR)

        # Generate embeddings (reuses same embedder instance — model already loaded)
        logger.info("Generating embeddings...")
        embed_span = tracer.start_span("ingest.embed_documents", {"chunk_count": len(all_chunks)}, parent=root_span)
        texts = [c.text for c in all_chunks]
        metadatas = [c.metadata for c in all_chunks]
        embeddings = embedder.embed_documents(texts) if texts else []
        embed_span.end(status="ok")

        # Store in Weaviate
        logger.info("Storing in Weaviate...")
        store_span = tracer.start_span("ingest.store", parent=root_span)
        with get_weaviate_client() as client:
            if fresh:
                logger.info("Deleting existing collection for fresh ingestion...")
                delete_collection(client)
                manifest = {}
            elif update:
                for source in removed_sources:
                    delete_documents_by_source(client, source)
                    manifest.pop(source, None)
                for doc_file in doc_files:
                    delete_documents_by_source(client, doc_file.name)
            ensure_collection(client)
            count = 0
            if texts:
                count = retry_provider.execute(
                    operation_name="weaviate_add_documents",
                    fn=lambda: add_documents(client, texts, embeddings, metadatas),
                    idempotency_key=f"ingest:{'fresh' if fresh else 'update'}:{len(texts)}",
                )
            logger.info("Stored %d chunks in Weaviate.", count)
        store_span.end(status="ok")
        _save_manifest(manifest)

        # Save knowledge graph
        if kg_builder:
            kg_builder.save(KG_PATH)
            stats = kg_builder.stats()
            logger.info("Knowledge graph: %s nodes, %s edges -> %s", stats["nodes"], stats["edges"], KG_PATH)

            if obsidian_export:
                n = export_obsidian(kg_builder.graph, KG_OBSIDIAN_EXPORT_DIR)
                logger.info("Obsidian export: %d files -> %s", n, KG_OBSIDIAN_EXPORT_DIR)

        logger.info("Ingestion complete.")
    except Exception as exc:
        span_status = "error"
        span_error = exc
        raise
    finally:
        root_span.end(status=span_status, error=span_error)


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
