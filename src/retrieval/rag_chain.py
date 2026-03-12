# @summary
# End-to-end RAG pipeline for query processing, KG expansion, hybrid search, and reranking. Main classes: RAGChain, RAGResponse. Key imports: LocalBGEEmbeddings, LocalBGEReranker, KnowledgeGraphBuilder, OllamaGenerator, Filter, get_weaviate_client, ensure_collection, hybrid_search.
# @end-summary
"""Main RAG chain that orchestrates the full retrieval pipeline."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import logging
import statistics
import time

from src.core.embeddings import LocalBGEEmbeddings
from src.retrieval.reranker import LocalBGEReranker, RankedResult
from src.retrieval.query_processor import process_query, QueryAction, QueryResult
from src.core.knowledge_graph import KnowledgeGraphBuilder, GraphQueryExpander
from src.core.vector_store import (
    create_persistent_client,
    get_weaviate_client,
    ensure_collection,
    hybrid_search,
)

from weaviate.classes.query import Filter
from src.retrieval.generator import OllamaGenerator
from src.platform.observability.providers import get_tracer
from src.platform.reliability.providers import get_retry_provider
from src.platform.schemas.reliability import RetryPolicy
from src.platform.validation import (
    validate_alpha,
    validate_filter_value,
    validate_positive_int,
)
from config.settings import (
    HYBRID_SEARCH_ALPHA, SEARCH_LIMIT, RERANK_TOP_K,
    KG_PATH, KG_ENABLED, GENERATION_ENABLED,
    RETRY_BACKOFF_MULTIPLIER,
    RETRY_INITIAL_BACKOFF_SECONDS,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_BACKOFF_SECONDS,
    MAX_SANITIZATION_ITERATIONS,
    RAG_DEFAULT_FAST_PATH,
    RAG_RETRIEVAL_TIMEOUT_MS,
    RAG_STAGE_BUDGET_QUERY_PROCESSING_MS,
    RAG_STAGE_BUDGET_KG_EXPANSION_MS,
    RAG_STAGE_BUDGET_EMBEDDING_MS,
    RAG_STAGE_BUDGET_HYBRID_SEARCH_MS,
    RAG_STAGE_BUDGET_RERANKING_MS,
    RAG_STAGE_BUDGET_GENERATION_MS,
)
from src.platform.metrics import PIPELINE_STAGE_MS

logger = logging.getLogger("rag.rag_chain")


@dataclass
class RAGResponse:
    """Complete response from the RAG pipeline."""
    query: str
    processed_query: str
    query_confidence: float
    action: str  # "search" or "ask_user"
    results: List[RankedResult] = field(default_factory=list)
    clarification_message: Optional[str] = None
    kg_expanded_terms: Optional[List[str]] = None
    generated_answer: Optional[str] = None
    stage_timings: List[Dict[str, Any]] = field(default_factory=list)
    timing_totals: Dict[str, float] = field(default_factory=dict)
    budget_exhausted: bool = False
    budget_exhausted_stage: Optional[str] = None


class RAGChain:
    """End-to-end RAG pipeline: query processing -> KG expansion -> hybrid search -> reranking."""

    def __init__(self, persistent_weaviate: bool = True):
        from concurrent.futures import ThreadPoolExecutor, Future

        self.tracer = get_tracer()
        self.retry_provider = get_retry_provider()
        self.retry_policy = RetryPolicy(
            max_attempts=RETRY_MAX_ATTEMPTS,
            initial_backoff_seconds=RETRY_INITIAL_BACKOFF_SECONDS,
            max_backoff_seconds=RETRY_MAX_BACKOFF_SECONDS,
            backoff_multiplier=RETRY_BACKOFF_MULTIPLIER,
        )

        # Persistent Weaviate connection avoids per-query startup cost
        self._persistent_weaviate = persistent_weaviate
        self._weaviate_client = None
        if persistent_weaviate:
            logger.info("Opening persistent Weaviate connection...")
            self._weaviate_client = create_persistent_client()
            ensure_collection(self._weaviate_client)
            logger.info("Weaviate connected (persistent mode).")

        # GPU models must load sequentially (parallel .to(cuda) causes meta
        # tensor errors), but KG + generator can load concurrently with them.
        def _load_kg() -> Optional[GraphQueryExpander]:
            if KG_ENABLED and KG_PATH.exists():
                try:
                    builder = KnowledgeGraphBuilder.load(KG_PATH)
                    stats = builder.stats()
                    logger.info("Knowledge graph loaded: %s nodes, %s edges", stats["nodes"], stats["edges"])
                    return GraphQueryExpander(builder.graph)
                except Exception as e:
                    logger.warning("Could not load knowledge graph: %s", e)
            elif not KG_ENABLED:
                logger.info("Knowledge graph disabled (set RAG_KG_ENABLED=true to enable).")
            else:
                logger.info("No knowledge graph found (run ingest.py first to build it).")
            return None

        def _load_generator() -> Optional[OllamaGenerator]:
            if GENERATION_ENABLED:
                gen = OllamaGenerator()
                if gen.is_available():
                    logger.info("Ollama generator ready (model: %s).", gen.model)
                    return gen
                else:
                    logger.warning("Ollama not available. Generation disabled.")
            else:
                logger.info("Generation disabled (set RAG_GENERATION_ENABLED=true to enable).")
            return None

        def _load_models_sequential():
            """Load GPU models one at a time to avoid meta tensor conflicts."""
            logger.info("Loading embedding model...")
            emb = LocalBGEEmbeddings()
            logger.info("Loading reranker model...")
            rer = LocalBGEReranker()
            return emb, rer

        with ThreadPoolExecutor(max_workers=3) as pool:
            fut_models = pool.submit(_load_models_sequential)
            fut_kg = pool.submit(_load_kg)
            fut_gen = pool.submit(_load_generator)

            self.embeddings, self.reranker = fut_models.result()
            self._kg_expander: Optional[GraphQueryExpander] = fut_kg.result()
            self._generator: Optional[OllamaGenerator] = fut_gen.result()

        logger.info("RAG chain ready.")

    def close(self) -> None:
        """Release persistent resources (Weaviate connection)."""
        if self._weaviate_client is not None:
            try:
                self._weaviate_client.close()
            except Exception as e:
                logger.warning("Error closing Weaviate client: %s", e)
            self._weaviate_client = None
            logger.info("Weaviate connection closed.")

    def _do_search(self, bm25_query, query_embedding, alpha, search_limit, wv_filter):
        """Run hybrid search against Weaviate (persistent or transient client)."""
        if self._weaviate_client is not None:
            return hybrid_search(
                client=self._weaviate_client,
                query=bm25_query,
                query_embedding=query_embedding,
                alpha=alpha,
                limit=search_limit,
                filters=wv_filter,
            )
        with get_weaviate_client() as client:
            ensure_collection(client)
            return hybrid_search(
                client=client,
                query=bm25_query,
                query_embedding=query_embedding,
                alpha=alpha,
                limit=search_limit,
                filters=wv_filter,
            )

    def run(
        self,
        query: str,
        alpha: float = HYBRID_SEARCH_ALPHA,
        search_limit: int = SEARCH_LIMIT,
        rerank_top_k: int = RERANK_TOP_K,
        source_filter: Optional[str] = None,
        heading_filter: Optional[str] = None,
        skip_generation: bool = False,
        tenant_id: Optional[str] = None,
        max_query_iterations: int = MAX_SANITIZATION_ITERATIONS,
        fast_path: Optional[bool] = None,
        overall_timeout_ms: int = RAG_RETRIEVAL_TIMEOUT_MS,
        stage_budget_overrides: Optional[Dict[str, int]] = None,
    ) -> RAGResponse:
        """Execute the full RAG pipeline.

        Args:
            query: Raw user query.
            alpha: Hybrid search balance (0=BM25, 1=vector).
            search_limit: Number of results from hybrid search.
            rerank_top_k: Number of top results after reranking.
            source_filter: Optional source filename to filter results by.
            heading_filter: Optional section heading to filter results by.
            skip_generation: If True, skip LLM generation (stages 1-5 only).
                Useful when the caller will stream generation separately.

        Returns:
            RAGResponse with results or clarification message.
        """
        pipeline_start = time.perf_counter()
        stage_timings: List[Dict[str, Any]] = []
        stage_budget_overrides = stage_budget_overrides or {}
        stage_budgets = {
            "query_processing": int(stage_budget_overrides.get("query_processing", RAG_STAGE_BUDGET_QUERY_PROCESSING_MS)),
            "kg_expansion": int(stage_budget_overrides.get("kg_expansion", RAG_STAGE_BUDGET_KG_EXPANSION_MS)),
            "embedding": int(stage_budget_overrides.get("embedding", RAG_STAGE_BUDGET_EMBEDDING_MS)),
            "hybrid_search": int(stage_budget_overrides.get("hybrid_search", RAG_STAGE_BUDGET_HYBRID_SEARCH_MS)),
            "reranking": int(stage_budget_overrides.get("reranking", RAG_STAGE_BUDGET_RERANKING_MS)),
            "generation": int(stage_budget_overrides.get("generation", RAG_STAGE_BUDGET_GENERATION_MS)),
        }
        root_span = self.tracer.start_span("rag_chain.run", {"query_length": len(query)})
        span_status = "ok"
        span_error: Optional[Exception] = None
        budget_exhausted = False
        budget_exhausted_stage: Optional[str] = None

        def _record_stage(stage: str, bucket: str, started_at: float) -> None:
            ms = round((time.perf_counter() - started_at) * 1000, 1)
            stage_timings.append(
                {
                    "stage": stage,
                    "bucket": bucket,
                    "ms": ms,
                    "budget_ms": stage_budgets.get(stage),
                    "within_budget": ms <= float(stage_budgets.get(stage, 10**9)),
                }
            )
            PIPELINE_STAGE_MS.labels(stage=stage, bucket=bucket).observe(ms)

        def _compute_totals() -> Dict[str, float]:
            retrieval_ms = sum(
                float(s["ms"]) for s in stage_timings if s.get("bucket") == "retrieval"
            )
            generation_ms = sum(
                float(s["ms"]) for s in stage_timings if s.get("bucket") == "generation"
            )
            return {
                "retrieval_ms": round(retrieval_ms, 1),
                "generation_ms": round(generation_ms, 1),
                "total_ms": round(retrieval_ms + generation_ms, 1),
            }

        def _is_overall_budget_exhausted() -> bool:
            elapsed = (time.perf_counter() - pipeline_start) * 1000
            return elapsed > float(overall_timeout_ms)

        def _mark_budget_exhausted(stage: str) -> None:
            nonlocal budget_exhausted, budget_exhausted_stage
            budget_exhausted = True
            budget_exhausted_stage = stage

        try:
            alpha = validate_alpha(alpha)
            search_limit = validate_positive_int("search_limit", search_limit)
            rerank_top_k = validate_positive_int("rerank_top_k", rerank_top_k)
            source_filter = validate_filter_value("source_filter", source_filter)
            heading_filter = validate_filter_value("heading_filter", heading_filter)

            # Stage 1: Query processing
            t0 = time.perf_counter()
            query_span = self.tracer.start_span("rag_chain.process_query", parent=root_span)
            query_result: QueryResult = process_query(
                query,
                max_iterations=max_query_iterations,
                fast_path=RAG_DEFAULT_FAST_PATH if fast_path is None else bool(fast_path),
            )
            query_span.end(status="ok")
            _record_stage("query_processing", "retrieval", t0)
            if stage_timings[-1]["ms"] > stage_budgets["query_processing"] or _is_overall_budget_exhausted():
                _mark_budget_exhausted("query_processing")

            if query_result.action == QueryAction.ASK_USER:
                return RAGResponse(
                    query=query,
                    processed_query=query_result.processed_query,
                    query_confidence=query_result.confidence,
                    action="ask_user",
                    clarification_message=query_result.clarification_message,
                    stage_timings=stage_timings,
                    timing_totals=_compute_totals(),
                    budget_exhausted=budget_exhausted,
                    budget_exhausted_stage=budget_exhausted_stage,
                )

            processed_query = query_result.processed_query

            # Stage 2: KG expansion
            t0 = time.perf_counter()
            kg_span = self.tracer.start_span("rag_chain.kg_expand", parent=root_span)
            kg_expanded_terms = []
            if self._kg_expander:
                kg_expanded_terms = self._kg_expander.expand(processed_query, depth=1)
            kg_span.set_attribute("kg_expanded_terms_count", len(kg_expanded_terms))
            kg_span.end(status="ok")
            _record_stage("kg_expansion", "retrieval", t0)
            if stage_timings[-1]["ms"] > stage_budgets["kg_expansion"] or _is_overall_budget_exhausted():
                _mark_budget_exhausted("kg_expansion")

            if kg_expanded_terms:
                bm25_query = processed_query + " " + " ".join(kg_expanded_terms[:3])
            else:
                bm25_query = processed_query

            # Stage 3: Query embedding
            t0 = time.perf_counter()
            embed_span = self.tracer.start_span("rag_chain.embed_query", parent=root_span)
            query_embedding = self.embeddings.embed_query(processed_query)
            embed_span.end(status="ok")
            _record_stage("embedding", "retrieval", t0)
            if stage_timings[-1]["ms"] > stage_budgets["embedding"] or _is_overall_budget_exhausted():
                _mark_budget_exhausted("embedding")

            # Stage 4: Hybrid search
            t0 = time.perf_counter()
            wv_filter = None
            if source_filter:
                wv_filter = Filter.by_property("source").equal(source_filter)
            if heading_filter:
                hf = Filter.by_property("heading").equal(heading_filter)
                wv_filter = wv_filter & hf if wv_filter else hf
            if tenant_id:
                tf = Filter.by_property("tenant_id").equal(tenant_id)
                wv_filter = wv_filter & tf if wv_filter else tf

            search_span = self.tracer.start_span("rag_chain.hybrid_search", parent=root_span)

            search_results = self.retry_provider.execute(
                operation_name="weaviate_hybrid_search",
                fn=lambda: self._do_search(
                    bm25_query, query_embedding, alpha, search_limit, wv_filter,
                ),
                policy=self.retry_policy,
                idempotency_key=f"search:{processed_query}:{source_filter}:{heading_filter}:{search_limit}",
            )
            search_span.set_attribute("search_result_count", len(search_results))
            search_span.end(status="ok")
            _record_stage("hybrid_search", "retrieval", t0)
            if stage_timings[-1]["ms"] > stage_budgets["hybrid_search"] or _is_overall_budget_exhausted():
                _mark_budget_exhausted("hybrid_search")

            if not search_results:
                timing_totals = _compute_totals()
                self._log_timings(stage_timings, timing_totals)
                return RAGResponse(
                    query=query,
                    processed_query=processed_query,
                    query_confidence=query_result.confidence,
                    action="search",
                    results=[],
                    kg_expanded_terms=kg_expanded_terms or None,
                    stage_timings=stage_timings,
                    timing_totals=timing_totals,
                    budget_exhausted=budget_exhausted,
                    budget_exhausted_stage=budget_exhausted_stage,
                )

            # Stage 5: Reranking
            t0 = time.perf_counter()
            rerank_span = self.tracer.start_span("rag_chain.rerank", parent=root_span)
            reranked = self.reranker.rerank(
                query=processed_query,
                documents=search_results,
                top_k=rerank_top_k,
            )
            scores = [r.score for r in reranked]
            if scores:
                rerank_span.set_attribute("rerank_score_min", min(scores))
                rerank_span.set_attribute("rerank_score_max", max(scores))
                rerank_span.set_attribute("rerank_score_mean", statistics.mean(scores))
            rerank_span.end(status="ok")
            _record_stage("reranking", "retrieval", t0)
            if stage_timings[-1]["ms"] > stage_budgets["reranking"] or _is_overall_budget_exhausted():
                _mark_budget_exhausted("reranking")

            # Stage 6: Generation (skippable for streaming callers)
            generated_answer = None
            if not skip_generation and self._generator and reranked and not budget_exhausted:
                t0 = time.perf_counter()
                generate_span = self.tracer.start_span("rag_chain.generate", parent=root_span)
                context_chunks = [r.text for r in reranked]
                scores = [r.score for r in reranked]
                generated_answer = self._generator.generate(
                    query=processed_query,
                    context_chunks=context_chunks,
                    scores=scores,
                )
                generate_span.set_attribute("generated_answer_present", bool(generated_answer))
                generate_span.end(status="ok")
                _record_stage("generation", "generation", t0)
                if stage_timings[-1]["ms"] > stage_budgets["generation"] or _is_overall_budget_exhausted():
                    _mark_budget_exhausted("generation")

            timing_totals = _compute_totals()
            self._log_timings(stage_timings, timing_totals)

            return RAGResponse(
                query=query,
                processed_query=processed_query,
                query_confidence=query_result.confidence,
                action="search",
                results=reranked,
                kg_expanded_terms=kg_expanded_terms or None,
                generated_answer=generated_answer,
                stage_timings=stage_timings,
                timing_totals=timing_totals,
                budget_exhausted=budget_exhausted,
                budget_exhausted_stage=budget_exhausted_stage,
            )
        except Exception as exc:
            span_status = "error"
            span_error = exc
            raise
        finally:
            root_span.set_attribute("duration_ms", int((time.perf_counter() - pipeline_start) * 1000))
            root_span.end(status=span_status, error=span_error)

    def _log_timings(self, stage_timings: List[Dict[str, Any]], totals: Dict[str, float]) -> None:
        if not stage_timings:
            return
        parts = " | ".join(
            f"{s['bucket']}.{s['stage']}: {float(s['ms']):.0f}ms" for s in stage_timings
        )
        logger.info(
            "Pipeline timings — %s | retrieval: %.0fms | generation: %.0fms | total: %.0fms",
            parts,
            totals.get("retrieval_ms", 0.0),
            totals.get("generation_ms", 0.0),
            totals.get("total_ms", 0.0),
        )
