# @summary
# LangGraph node for dual-path chunk generation: Docling HybridChunker or markdown fallback.
# Exports: chunking_node, _chunk_with_docling, _chunk_with_markdown, _normalize_chunk_text,
#          _extract_docling_section_metadata
# Deps: unicodedata, re, src.ingest.embedding.state, src.ingest.common.schemas,
#       src.ingest.common.shared, src.ingest.support.document, src.ingest.support.markdown
# @end-summary

"""Chunking node implementation.

Selects between Docling-native (HybridChunker) and markdown fallback chunking
based on whether a DoclingDocument is present in state.
"""

from __future__ import annotations

import logging
import re as _re
import unicodedata
from typing import Any

from src.ingest.support import (
    extract_metadata,
    metadata_to_dict,
)
from src.ingest.common import ProcessedChunk
from src.ingest.support import (
    _build_section_metadata,
    chunk_markdown,
    normalize_headings_to_markdown,
)
from src.ingest.common import append_processing_log
from src.ingest.embedding.state import EmbeddingPipelineState

logger = logging.getLogger("rag.ingest.pipeline.chunking")

# Pre-compiled regex: strips C0/C1 control characters except \n (0x0a), \t (0x09),
# and \r (0x0d).  Range breakdown:
#   \x00-\x08  — NUL through BS
#   \x0b       — VT (vertical tab)
#   \x0c       — FF (form feed)
#   \x0e-\x1f  — SO through US
#   \x7f       — DEL
_CONTROL_CHAR_RE = _re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _normalize_chunk_text(text: str) -> str:
    """Apply NFC unicode normalization and remove control characters.

    Args:
        text: Raw chunk text.

    Returns:
        NFC-normalized text with C0/C1 control characters removed.
        Newlines (0x0a) and carriage returns (0x0d) are preserved.
    """
    normalized = unicodedata.normalize("NFC", text)
    return _CONTROL_CHAR_RE.sub("", normalized)


def _extract_docling_section_metadata(chunk: Any) -> dict[str, Any]:
    """Extract section_path, heading, heading_level from a HybridChunker chunk.

    HybridChunker chunks expose heading hierarchy via chunk.meta.headings
    (list of heading strings, outermost first).

    Returns:
        {"section_path": str, "heading": str, "heading_level": int}
        section_path = " > ".join(headings)
        heading = headings[-1] or ""
        heading_level = len(headings)
    """
    headings: list[str] = []
    meta = getattr(chunk, "meta", None)
    if meta is not None:
        headings = list(getattr(meta, "headings", None) or [])
    heading = headings[-1] if headings else ""
    return {
        "section_path": " > ".join(headings),
        "heading": heading,
        "heading_level": len(headings),
    }


def chunking_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    """Split document into chunks using HybridChunker (Docling path) or
    MarkdownHeaderTextSplitter (fallback path).

    Path selection: if state["docling_document"] is not None → HybridChunker.
    Otherwise → existing markdown path. HybridChunker failures auto-fallback
    to the markdown path (non-fatal).

    Args:
        state: Embedding pipeline state.

    Returns:
        Partial state update: {"chunks": list[ProcessedChunk], "processing_log": updated_log}
    """
    config = state["runtime"].config
    try:
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

        docling_doc = state.get("docling_document")
        if docling_doc is not None:
            # Docling-native path: attempt HybridChunker, fall back on any error.
            try:
                chunks = _chunk_with_docling(state, config, base_metadata)
                processing_log = append_processing_log(state, "hybrid_chunker:ok")
            except Exception as exc:
                logger.error(
                    "HybridChunker failed for source=%s: %s — falling back to markdown",
                    state.get("source_name", "<unknown>"),
                    exc,
                )
                processing_log_tmp = append_processing_log(state, "hybrid_chunker:error")
                # Temporarily graft the partial log so append_processing_log sees it.
                state_with_error_log: dict[str, Any] = {**state, "processing_log": processing_log_tmp}
                chunks = _chunk_with_markdown(state_with_error_log, config, base_metadata)
                processing_log = append_processing_log(state_with_error_log, "chunking:fallback_to_markdown")
        else:
            # Markdown fallback path (no DoclingDocument available).
            chunks = _chunk_with_markdown(state, config, base_metadata)
            processing_log = append_processing_log(state, "chunking:markdown_fallback")

    except Exception as exc:
        return {
            **state,
            "errors": state.get("errors", []) + [f"chunking:{exc}"],
            "processing_log": append_processing_log(state, "chunking:error"),
        }

    return {
        "chunks": chunks,
        "processing_log": processing_log,
    }


def _chunk_with_docling(
    state: EmbeddingPipelineState,
    config: Any,
    base_metadata: dict[str, Any],
) -> list[ProcessedChunk]:
    """Chunk a DoclingDocument using Docling's HybridChunker.

    Args:
        state: state["docling_document"] must be a valid DoclingDocument.
        config: config.hybrid_chunker_max_tokens controls token size limit.
        base_metadata: source, source_uri, source_key, source_id, connector,
            source_version — pre-built by the caller.

    Returns:
        List of ProcessedChunk with section_path, heading, heading_level,
        chunk_index, total_chunks, and all base_metadata keys.

    Raises:
        Any exception from HybridChunker (caller catches and falls back).
    """
    from docling_core.transforms.chunker import HybridChunker  # lazy import

    chunker = HybridChunker(
        max_tokens=config.hybrid_chunker_max_tokens,
        merge_peers=True,
    )
    chunk_iter = chunker.chunk(dl_doc=state["docling_document"])
    raw_chunks = list(chunk_iter)
    total = len(raw_chunks)

    chunks: list[ProcessedChunk] = []
    for idx, chunk in enumerate(raw_chunks):
        section_meta = _extract_docling_section_metadata(chunk)
        normalized_text = _normalize_chunk_text(chunk.text)
        chunks.append(
            ProcessedChunk(
                text=normalized_text,
                metadata={
                    **base_metadata,
                    **section_meta,
                    "chunk_index": idx,
                    "total_chunks": total,
                },
            )
        )
    return chunks


def _chunk_with_markdown(
    state: EmbeddingPipelineState,
    config: Any,
    base_metadata: dict[str, Any],
) -> list[ProcessedChunk]:
    """Chunk markdown text using MarkdownHeaderTextSplitter + RecursiveCharacterTextSplitter.

    Behaviorally identical to the pre-redesign chunking_node body (FR-2305).
    Output is byte-identical to pre-redesign except where _normalize_chunk_text
    alters non-NFC sequences or removes control characters.

    Args:
        state: Pipeline state; uses refactored_text or cleaned_text for chunking.
        config: IngestionConfig; controls semantic_chunking, chunk_size, chunk_overlap.
        base_metadata: Pre-built source metadata dict.

    Returns:
        List of ProcessedChunk objects with full metadata.

    Raises:
        Any exception from the markdown splitters (propagates; markdown path
        failure is fatal for this document unlike HybridChunker failure).
    """
    text_for_chunking = normalize_headings_to_markdown(
        state.get("refactored_text") or state.get("cleaned_text", "")
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
            text=_normalize_chunk_text(chunk["text"]),
            metadata={
                **base_metadata,
                **_build_section_metadata(chunk.get("header_metadata", {})),
                "chunk_index": idx,
                "total_chunks": total_chunks,
            },
        )
        for idx, chunk in enumerate(raw_chunks)
    ]
    return chunks
