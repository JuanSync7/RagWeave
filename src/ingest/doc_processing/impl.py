# @summary
# Phase 1 orchestrator: compiles and invokes the Document Processing LangGraph.
# Exports: run_document_processing
# Deps: src.ingest.doc_processing.workflow, src.ingest.doc_processing.state, src.ingest.common.types
# @end-summary

"""Phase 1 runtime implementation for document processing."""

from __future__ import annotations

from src.ingest.common.types import Runtime
from src.ingest.doc_processing.state import DocumentProcessingState
from src.ingest.doc_processing.workflow import build_document_processing_graph

_GRAPH = build_document_processing_graph()


def run_document_processing(
    runtime: Runtime,
    source_path: str,
    source_name: str,
    source_uri: str,
    source_key: str,
    source_id: str,
    connector: str,
    source_version: str,
) -> DocumentProcessingState:
    """Run the Phase 1 Document Processing pipeline for a single source file.

    The caller is responsible for the idempotency check before invoking this
    function. This function always runs the pipeline regardless of any prior
    state.

    Args:
        runtime: Shared runtime dependencies.
        source_path: Absolute path to the source file.
        source_name: Display name for the source.
        source_uri: Stable URI for the source.
        source_key: Stable source identity key.
        source_id: OS-level stable identity.
        connector: Connector identifier.
        source_version: Source version string (mtime nanoseconds).

    Returns:
        Final ``DocumentProcessingState`` after all nodes have run.
    """
    initial_state: DocumentProcessingState = {
        "runtime": runtime,
        "source_path": source_path,
        "source_name": source_name,
        "source_uri": source_uri,
        "source_key": source_key,
        "source_id": source_id,
        "connector": connector,
        "source_version": source_version,
        "source_hash": "",
        "raw_text": "",
        "structure": {},
        "multimodal_notes": [],
        "cleaned_text": "",
        "refactored_text": None,
        "errors": [],
        "processing_log": [],
    }
    return _GRAPH.invoke(initial_state)
