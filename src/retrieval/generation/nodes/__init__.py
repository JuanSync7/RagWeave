# @summary
# Generation nodes: LLM generator, document formatter, output sanitizer.
# Exports: OllamaGenerator, format_context, FormattedContext, VersionConflict, sanitize_answer,
#          _render_graph_context_section
# Deps: src.retrieval.generation.schemas, src.retrieval.generation.nodes.generator,
#       src.retrieval.generation.nodes.document_formatter, src.retrieval.generation.nodes.output_sanitizer
# @end-summary

from src.retrieval.generation.schemas import FormattedContext, VersionConflict
from src.retrieval.generation.nodes.generator import OllamaGenerator
from src.retrieval.generation.nodes.document_formatter import format_context
from src.retrieval.generation.nodes.output_sanitizer import sanitize_answer

__all__ = [
    "OllamaGenerator",
    "format_context",
    "FormattedContext",
    "VersionConflict",
    "sanitize_answer",
]

# --- Auto-generated re-exports (fix_encapsulation.py) ---
from src.retrieval.generation.nodes.generator import (
    _build_user_prompt,
    _get_system_prompt,
    _render_graph_context_section,
)
