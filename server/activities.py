# @summary
# Temporal activity that executes RAG queries against a preloaded RAGChain singleton.
# The singleton is initialized once by the worker at startup — not per request.
# Exports: execute_rag_query, init_rag_chain, shutdown_rag_chain
# Deps: temporalio, src.retrieval.rag_chain, dataclasses
# @end-summary
"""Temporal activities for the RAG query pipeline.

The RAGChain singleton is loaded once at worker startup. Activities run
inference against models already in memory — no per-request init cost.
"""

import logging
import time
from dataclasses import asdict
from typing import Optional

from temporalio import activity

logger = logging.getLogger("rag.server.activities")

_rag_chain = None


def init_rag_chain() -> None:
    """Load RAGChain once at worker startup. Called before the worker loop starts."""
    global _rag_chain
    if _rag_chain is not None:
        logger.warning("RAGChain already initialized, skipping re-init")
        return

    from src.retrieval.rag_chain import RAGChain
    logger.info("Initializing RAGChain (loading models into memory)...")
    start = time.time()
    _rag_chain = RAGChain()
    logger.info("RAGChain ready in %.1fs", time.time() - start)


def shutdown_rag_chain() -> None:
    """Release the RAGChain singleton and its resources (for graceful shutdown)."""
    global _rag_chain
    if _rag_chain is not None:
        _rag_chain.close()
    _rag_chain = None
    logger.info("RAGChain released")


def get_rag_chain():
    """Get the preloaded RAGChain. Raises if not initialized."""
    if _rag_chain is None:
        raise RuntimeError(
            "RAGChain not initialized. The worker must call init_rag_chain() at startup."
        )
    return _rag_chain


@activity.defn
def execute_rag_query(request: dict) -> dict:
    """Run a RAG query against the preloaded models.

    This activity runs synchronously in a ThreadPoolExecutor managed by the
    Temporal worker. The RAGChain and all GPU models are already in memory.
    """
    rag = get_rag_chain()

    query = request["query"]
    source_filter: Optional[str] = request.get("source_filter")
    heading_filter: Optional[str] = request.get("heading_filter")
    alpha: float = request.get("alpha", 0.5)
    search_limit: int = request.get("search_limit", 10)
    rerank_top_k: int = request.get("rerank_top_k", 5)
    skip_generation: bool = request.get("skip_generation", False)

    activity.logger.info("Processing query: %s", query[:80])

    start = time.perf_counter()
    response = rag.run(
        query=query,
        alpha=alpha,
        search_limit=search_limit,
        rerank_top_k=rerank_top_k,
        source_filter=source_filter,
        heading_filter=heading_filter,
        skip_generation=skip_generation,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    result = asdict(response)
    result["latency_ms"] = round(elapsed_ms, 1)

    activity.logger.info(
        "Query complete in %.0fms — %d results, action=%s, generation=%s",
        elapsed_ms,
        len(response.results),
        response.action,
        "skipped" if skip_generation else "included",
    )
    return result
