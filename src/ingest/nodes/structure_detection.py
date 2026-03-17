# @summary
# LangGraph node for structure cues extraction (headings and figure references).
# Exports: structure_detection_node
# @end-summary

"""Structure-detection node implementation."""

from __future__ import annotations

import re
from pathlib import Path

from src.ingest.support.docling import parse_with_docling
from src.ingest.common.shared import append_processing_log
from src.ingest.common.types import IngestState


def structure_detection_node(state: IngestState) -> dict:
    """Extract lightweight structural signals from raw document text."""
    config = state["runtime"].config
    raw_text = state["raw_text"]
    figures: list[str] = []
    headings: list[str] = []
    parsed_text = raw_text

    if config.enable_docling_parser:
        try:
            parsed = parse_with_docling(
                Path(state["source_path"]),
                parser_model=config.docling_model,
                artifacts_path=config.docling_artifacts_path,
            )
            parsed_text = parsed.text_markdown
            figures = list(parsed.figures)
            headings = list(parsed.headings)
        except Exception as exc:
            if config.docling_strict:
                return {
                    "errors": [f"docling_parse_failed:{state['source_name']}:{exc}"],
                    "should_skip": True,
                    "processing_log": append_processing_log(
                        state,
                        "structure_detection:failed",
                    ),
                }
            figures = re.findall(
                r"\b(?:Figure|Fig\.)\s*\d+[A-Za-z]?\b", raw_text, flags=re.IGNORECASE
            )
            headings = re.findall(
                r"^\s*(?:#{1,6}\s+.+|\d+(?:\.\d+)*\.?\s+[A-Z].+)$",
                raw_text,
                flags=re.MULTILINE,
            )
    else:
        figures = re.findall(
            r"\b(?:Figure|Fig\.)\s*\d+[A-Za-z]?\b", raw_text, flags=re.IGNORECASE
        )
        headings = re.findall(
            r"^\s*(?:#{1,6}\s+.+|\d+(?:\.\d+)*\.?\s+[A-Z].+)$",
            raw_text,
            flags=re.MULTILINE,
        )

    return {
        "raw_text": parsed_text,
        "structure": {
            "has_figures": bool(figures),
            "figures": figures[:32],
            "heading_count": len(headings),
            "docling_enabled": bool(config.enable_docling_parser),
            "docling_model": str(config.docling_model),
        },
        "processing_log": append_processing_log(state, "structure_detection:ok"),
    }
