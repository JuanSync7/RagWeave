# @summary
# LangGraph node for structure cues extraction (headings and figure references).
# Propagates docling_document from DoclingParseResult into pipeline state and sets
# structure["docling_document_available"] as a routing signal for downstream nodes.
# Exports: structure_detection_node
# Deps: src.ingest.support.docling, src.ingest.common.shared, src.ingest.doc_processing.state
# @end-summary

"""Structure-detection node implementation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.ingest.support import parse_with_docling
from src.ingest.common import append_processing_log
from src.ingest.doc_processing.state import DocumentProcessingState

_FIGURE_PATTERN = re.compile(r"\b(?:Figure|Fig\.)\s*\d+[A-Za-z]?\b", re.IGNORECASE)
_HEADING_PATTERN = re.compile(
    r"^\s*(?:#{1,6}\s+.+|\d+(?:\.\d+)*\.?\s+[A-Z].+)$", re.MULTILINE
)
_MAX_FIGURES = 32


def structure_detection_node(state: DocumentProcessingState) -> dict[str, Any]:
    """Extract lightweight structural signals from raw document text.

    When Docling parsing is enabled, this node attempts to parse the source file
    into markdown and derive figure and heading signals from the parsed output.
    On a successful Docling parse, ``docling_document`` is included in the
    returned state update and ``structure["docling_document_available"]`` is set
    to ``True``.  Downstream conditional edges read this flag to decide whether
    to skip ``text_cleaning_node`` and ``document_refactoring_node`` (which are
    redundant when a rich DoclingDocument is available).

    When Docling is disabled (or fails in non-strict mode), the node falls back
    to regex-based heuristics and ``structure["docling_document_available"]`` is
    set to ``False``; the ``docling_document`` key is absent from the returned
    update.

    Args:
        state: Document processing pipeline state.

    Returns:
        Partial state update containing:
        - Updated ``raw_text`` (may be Docling-generated markdown)
        - A ``structure`` dictionary with figure/heading signals and
          ``docling_document_available`` routing flag
        - Updated ``processing_log``
        - ``docling_document`` (only present on successful Docling parse)

        In strict Docling mode, failures return an error payload with
        ``should_skip=True`` to short-circuit the workflow.
    """
    config = state["runtime"].config
    raw_text = state["raw_text"]
    figures: list[str] = []
    headings: list[str] = []
    parsed_text = raw_text
    # docling_doc is only populated on a successful Docling parse.
    docling_doc = None
    docling_document_available = False

    if config.enable_docling_parser:
        try:
            parsed = parse_with_docling(
                Path(state["source_path"]),
                parser_model=config.docling_model,
                artifacts_path=config.docling_artifacts_path,
                vlm_mode=config.vlm_mode,
            )
            parsed_text = parsed.text_markdown
            figures = list(parsed.figures)
            headings = list(parsed.headings)
            # Capture DoclingDocument for downstream hybrid chunking (FR-2003).
            docling_doc = parsed.docling_document
            docling_document_available = True
        except Exception as exc:
            _is_format_error = "format not allowed" in str(exc).lower() or \
                               "File format not" in str(exc)
            if _is_format_error:
                # Unsupported format — always fall back to regex pipeline
                # regardless of docling_strict. Strict mode protects against
                # parser bugs, not missing format support.
                figures = _FIGURE_PATTERN.findall(raw_text)
                headings = _HEADING_PATTERN.findall(raw_text)
            elif config.docling_strict:
                return {
                    "errors": [f"docling_parse_failed:{state['source_name']}:{exc}"],
                    "should_skip": True,
                    "processing_log": append_processing_log(
                        state,
                        "structure_detection:failed",
                    ),
                }
            else:
                # Non-strict fallback: use regex heuristics; docling_document absent.
                figures = _FIGURE_PATTERN.findall(raw_text)
                headings = _HEADING_PATTERN.findall(raw_text)
    else:
        figures = _FIGURE_PATTERN.findall(raw_text)
        headings = _HEADING_PATTERN.findall(raw_text)

    structure = {
        "has_figures": bool(figures),
        "figures": figures[:_MAX_FIGURES],
        "heading_count": len(headings),
        "docling_enabled": bool(config.enable_docling_parser),
        "docling_model": str(config.docling_model),
        # Routing signal: downstream DAG conditional edges read this flag to
        # skip text_cleaning_node and document_refactoring_node when a full
        # DoclingDocument is available for hybrid chunking (FR-2505).
        "docling_document_available": docling_document_available,
    }

    update: dict[str, Any] = {
        "raw_text": parsed_text,
        "structure": structure,
        "processing_log": append_processing_log(state, "structure_detection:ok"),
    }

    # Only include docling_document in the state update when it was successfully
    # produced.  Callers use state.get("docling_document") to test for presence.
    if docling_document_available:
        update["docling_document"] = docling_doc

    return update
