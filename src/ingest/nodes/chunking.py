# @summary
# LangGraph node for semantic or recursive chunk generation with base metadata.
# Exports: chunking_node
# @end-summary

"""Chunking node implementation."""

from __future__ import annotations

from src.ingest.support.document import extract_metadata, metadata_to_dict
from src.ingest.common.schemas import ProcessedChunk
from src.ingest.support.markdown import (
    _build_section_metadata,
    chunk_markdown,
    normalize_headings_to_markdown,
)
from src.ingest.common.shared import append_processing_log
from src.ingest.common.types import IngestState


def chunking_node(state: IngestState) -> dict:
    """Split normalized text into chunks with baseline document metadata."""
    config = state["runtime"].config
    base_metadata = metadata_to_dict(
        extract_metadata(state["raw_text"], state["source_name"])
    )
    base_metadata.update(
        {
            "source": state["source_name"],
            "source_uri": state["source_uri"],
            "source_key": state["source_key"],
            "source_id": state["source_id"],
            "connector": state["connector"],
            "source_version": state["source_version"],
        }
    )
    text_for_chunking = normalize_headings_to_markdown(
        state["refactored_text"] or state["cleaned_text"]
    )
    if config.semantic_chunking:
        raw_chunks = chunk_markdown(
            text_for_chunking,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            embedder=state["runtime"].embedder,
        )
    else:
        # Keep markdown section metadata even when semantic splitting is disabled.
        raw_chunks = chunk_markdown(
            text_for_chunking,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            embedder=None,
        )

    total_chunks = len(raw_chunks)
    chunks = [
        ProcessedChunk(
            text=chunk["text"],
            metadata={
                **base_metadata,
                **_build_section_metadata(chunk.get("header_metadata", {})),
                "chunk_index": idx,
                "total_chunks": total_chunks,
            },
        )
        for idx, chunk in enumerate(raw_chunks)
    ]
    return {
        "chunks": chunks,
        "processing_log": append_processing_log(state, "chunking:ok"),
    }
