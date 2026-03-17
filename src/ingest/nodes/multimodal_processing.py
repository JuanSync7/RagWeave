# @summary
# LangGraph node for optional multimodal note synthesis from detected figure mentions.
# Exports: multimodal_processing_node
# @end-summary

"""Multimodal-processing node implementation."""

from __future__ import annotations

from pathlib import Path

from src.ingest.common.shared import append_processing_log
from src.ingest.common.types import IngestState
from src.ingest.support.vision import generate_vision_notes


def multimodal_processing_node(state: IngestState) -> dict:
    """Generate multimodal notes when figure references are detected and enabled."""
    config = state["runtime"].config
    has_figures = state["structure"].get("has_figures", False)
    if not config.enable_multimodal_processing or not has_figures:
        return {
            "processing_log": append_processing_log(
                state, "multimodal_processing:skipped"
            )
        }
    figures = list(state["structure"].get("figures", []))
    notes = [f"{figure}: referenced in text" for figure in figures]
    described_count = 0
    if config.enable_vision_processing:
        try:
            vision_notes, described_count = generate_vision_notes(
                state["raw_text"],
                source_path=Path(state["source_path"]),
                config=config,
            )
            if vision_notes:
                notes = vision_notes + notes[len(vision_notes) :]
        except Exception as exc:
            if config.vision_strict:
                return {
                    "errors": [f"vision_processing_failed:{state['source_name']}:{exc}"],
                    "should_skip": True,
                    "processing_log": append_processing_log(
                        state,
                        "multimodal_processing:failed",
                    ),
                }

    structure = dict(state.get("structure", {}))
    if config.enable_vision_processing:
        structure["vision_provider"] = config.vision_provider
        structure["vision_model"] = config.vision_model
        structure["vision_described_count"] = described_count

    return {
        "multimodal_notes": notes,
        "structure": structure,
        "processing_log": append_processing_log(state, "multimodal_processing:ok"),
    }
