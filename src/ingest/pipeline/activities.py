# @summary
# Temporal activity definitions for the two-phase ingestion pipeline.
# Exports: document_processing_activity, embedding_pipeline_activity,
#          prewarm_worker_resources
# Deps: temporalio, src.ingest.doc_processing.impl, src.ingest.embedding.impl,
#       src.ingest.common.types, src.vector_db, src.db, src.core.embeddings
# @end-summary
"""Temporal activities wrapping Phase 1 (document processing) and Phase 2 (embedding).

Each activity creates its own Runtime with fresh per-document clients.
The embedder and MinIO client are module-level singletons initialised once
per worker process via ``prewarm_worker_resources()``.

The CleanDocumentStore is the durable checkpoint between the two phases —
Phase 1 writes to it, Phase 2 reads from it. No large data is passed
between activities through Temporal.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Any, Optional

from temporalio import activity

from config.settings import GLINER_ENABLED
from src.core.embeddings import LocalBGEEmbeddings
from src.core.knowledge_graph import KnowledgeGraphBuilder
from src.ingest.common.types import IngestionConfig, Runtime
from src.ingest.doc_processing.impl import run_document_processing
from src.ingest.embedding.impl import run_embedding_pipeline
import src.db as db
import src.vector_db as vector_db

logger = logging.getLogger("rag.ingest.pipeline.activities")

# ---------------------------------------------------------------------------
# Worker-level singletons (initialised once per worker process)
# ---------------------------------------------------------------------------

_embedder: Optional[LocalBGEEmbeddings] = None
_db_client: Optional[Any] = None


def prewarm_worker_resources() -> None:
    """Load the embedding model and MinIO client before the worker starts.

    Call this once at worker startup so the first activity execution does not
    pay the model-load penalty.
    """
    global _embedder, _db_client
    _embedder = LocalBGEEmbeddings()
    _db_client = db.create_persistent_client()
    logger.info("worker resources prewarmed: embedder + db client ready")


def _get_embedder() -> LocalBGEEmbeddings:
    global _embedder
    if _embedder is None:
        _embedder = LocalBGEEmbeddings()
    return _embedder


def _get_db_client() -> Any:
    global _db_client
    if _db_client is None:
        _db_client = db.create_persistent_client()
    return _db_client


# ---------------------------------------------------------------------------
# Activity input / output contracts
# ---------------------------------------------------------------------------

@dataclass
class SourceArgs:
    """Serializable source identity passed to both activities."""
    source_path: str
    source_name: str
    source_uri: str
    source_key: str
    source_id: str
    connector: str
    source_version: str
    existing_hash: str = ""
    existing_source_uri: str = ""


@dataclass
class ActivityArgs:
    """Full input for either ingestion activity."""
    source: SourceArgs
    config: dict  # IngestionConfig serialised via dataclasses.asdict()


@dataclass
class DocProcessingResult:
    """Output of document_processing_activity."""
    errors: list
    source_hash: str
    clean_hash: str
    processing_log: list


@dataclass
class EmbeddingResult:
    """Output of embedding_pipeline_activity."""
    errors: list
    stored_count: int
    metadata_summary: str
    metadata_keywords: list
    processing_log: list


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deserialise_config(config_dict: dict) -> IngestionConfig:
    """Reconstruct IngestionConfig from a plain dict (Temporal payload)."""
    known = {f.name for f in dataclasses.fields(IngestionConfig)}
    return IngestionConfig(**{k: v for k, v in config_dict.items() if k in known})


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------

@activity.defn
async def document_processing_activity(args: ActivityArgs) -> DocProcessingResult:
    """Phase 1: parse, clean, and optionally refactor a document.

    Saves the clean text to CleanDocumentStore as the durable Phase 1
    checkpoint. The embedding activity reads from there — no large data
    flows through Temporal.
    """
    config = _deserialise_config(args.config)
    s = args.source

    # Phase 1 does not need embedder or vector DB — pass minimal Runtime.
    runtime = Runtime(
        config=config,
        embedder=_get_embedder(),   # not used in Phase 1 but required by Runtime
        weaviate_client=None,       # not needed for doc processing
        kg_builder=None,
        db_client=None,
    )

    result = run_document_processing(
        runtime=runtime,
        source_path=s.source_path,
        source_name=s.source_name,
        source_uri=s.source_uri,
        source_key=s.source_key,
        source_id=s.source_id,
        connector=s.connector,
        source_version=s.source_version,
    )
    return DocProcessingResult(
        errors=result.get("errors", []),
        source_hash=result.get("source_hash", ""),
        clean_hash=result.get("clean_hash", ""),
        processing_log=result.get("processing_log", []),
    )


@activity.defn
async def embedding_pipeline_activity(args: ActivityArgs) -> EmbeddingResult:
    """Phase 2: chunk, embed, store in Weaviate and MinIO.

    Reads clean text from CleanDocumentStore (written by Phase 1).
    Creates a fresh Weaviate client per activity execution.
    """
    config = _deserialise_config(args.config)
    s = args.source

    with vector_db.get_client() as wv_client:
        vector_db.ensure_collection(wv_client, config.target_collection or None)

        runtime = Runtime(
            config=config,
            embedder=_get_embedder(),
            weaviate_client=wv_client,
            kg_builder=KnowledgeGraphBuilder(use_gliner=GLINER_ENABLED)
            if config.build_kg else None,
            db_client=_get_db_client() if config.store_documents else None,
        )

        result = run_embedding_pipeline(
            runtime=runtime,
            source_key=s.source_key,
            source_name=s.source_name,
            source_uri=s.source_uri,
            source_id=s.source_id,
            connector=s.connector,
            source_version=s.source_version,
        )

    return EmbeddingResult(
        errors=result.get("errors", []),
        stored_count=result.get("stored_count", 0),
        metadata_summary=result.get("metadata_summary", ""),
        metadata_keywords=result.get("metadata_keywords", []),
        processing_log=result.get("processing_log", []),
    )
