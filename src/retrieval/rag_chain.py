# @summary
# End-to-end RAG pipeline for query processing, KG expansion, hybrid search, and reranking. Main classes: RAGChain, RAGResponse. Key imports: LocalBGEEmbeddings, LocalBGEReranker, KnowledgeGraphBuilder, OllamaGenerator, Filter, get_weaviate_client, ensure_collection, hybrid_search.
# @end-summary
"""Main RAG chain that orchestrates the full retrieval pipeline."""

from dataclasses import dataclass, field
from typing import List, Optional
import logging
import statistics
import time

from src.core.embeddings import LocalBGEEmbeddings
from src.retrieval.reranker import LocalBGEReranker, RankedResult
from src.retrieval.query_processor import process_query, QueryAction, QueryResult
from src.core.knowledge_graph import KnowledgeGraphBuilder, GraphQueryExpander
from src.core.vector_store import get_weaviate_client, ensure_collection, hybrid_search

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
)

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


class RAGChain:
    """End-to-end RAG pipeline: query processing -> KG expansion -> hybrid search -> reranking."""

    def __init__(self):
        from concurrent.futures import ThreadPoolExecutor, Future

        self.tracer = get_tracer()
        self.retry_provider = get_retry_provider()
        self.retry_policy = RetryPolicy(
            max_attempts=RETRY_MAX_ATTEMPTS,
            initial_backoff_seconds=RETRY_INITIAL_BACKOFF_SECONDS,
            max_backoff_seconds=RETRY_MAX_BACKOFF_SECONDS,
            backoff_multiplier=RETRY_BACKOFF_MULTIPLIER,
        )

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

    def run(
        self,
        query: str,
        alpha: float = HYBRID_SEARCH_ALPHA,
        search_limit: int = SEARCH_LIMIT,
        rerank_top_k: int = RERANK_TOP_K,
        source_filter: Optional[str] = None,
        heading_filter: Optional[str] = None,
    ) -> RAGResponse:
        """Execute the full RAG pipeline.

        Steps:
            1. Process and sanitize the query
            2. If confident: KG expand -> embed query -> hybrid search -> rerank -> return results
            3. If not confident: return clarification request

        Args:
            query: Raw user query.
            alpha: Hybrid search balance (0=BM25, 1=vector).
            search_limit: Number of results from hybrid search.
            rerank_top_k: Number of top results after reranking.
            source_filter: Optional source filename to filter results by.
            heading_filter: Optional section heading to filter results by.

        Returns:
            RAGResponse with results or clarification message.
        """
        start = time.perf_counter()
        root_span = self.tracer.start_span("rag_chain.run", {"query_length": len(query)})
        span_status = "ok"
        span_error: Optional[Exception] = None
        try:
            alpha = validate_alpha(alpha)
            search_limit = validate_positive_int("search_limit", search_limit)
            rerank_top_k = validate_positive_int("rerank_top_k", rerank_top_k)
            source_filter = validate_filter_value("source_filter", source_filter)
            heading_filter = validate_filter_value("heading_filter", heading_filter)

            # Step 1: Query processing
            query_span = self.tracer.start_span("rag_chain.process_query", parent=root_span)
            query_result: QueryResult = process_query(query)
            query_span.end(status="ok")

            if query_result.action == QueryAction.ASK_USER:
                return RAGResponse(
                    query=query,
                    processed_query=query_result.processed_query,
                    query_confidence=query_result.confidence,
                    action="ask_user",
                    clarification_message=query_result.clarification_message,
                )

            processed_query = query_result.processed_query

            # Step 2: KG expansion — augment BM25 query with related entity terms
            kg_span = self.tracer.start_span("rag_chain.kg_expand", parent=root_span)
            kg_expanded_terms = []
            if self._kg_expander:
                kg_expanded_terms = self._kg_expander.expand(processed_query, depth=1)
            kg_span.set_attribute("kg_expanded_terms_count", len(kg_expanded_terms))
            kg_span.end(status="ok")

            # BM25 query gets expanded terms for broader keyword matching
            if kg_expanded_terms:
                bm25_query = processed_query + " " + " ".join(kg_expanded_terms[:3])
            else:
                bm25_query = processed_query

            # Step 3: Embed the ORIGINAL query (not augmented) for vector search
            # This keeps the semantic intent pure for the dense vector component
            embed_span = self.tracer.start_span("rag_chain.embed_query", parent=root_span)
            query_embedding = self.embeddings.embed_query(processed_query)
            embed_span.end(status="ok")

            # Step 4: Build metadata filters and run hybrid search
            wv_filter = None
            if source_filter:
                wv_filter = Filter.by_property("source").equal(source_filter)
            if heading_filter:
                hf = Filter.by_property("heading").equal(heading_filter)
                wv_filter = wv_filter & hf if wv_filter else hf

            search_span = self.tracer.start_span("rag_chain.hybrid_search", parent=root_span)

            def _search():
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

            search_results = self.retry_provider.execute(
                operation_name="weaviate_hybrid_search",
                fn=_search,
                policy=self.retry_policy,
                idempotency_key=f"search:{processed_query}:{source_filter}:{heading_filter}:{search_limit}",
            )
            search_span.set_attribute("search_result_count", len(search_results))
            search_span.end(status="ok")

            if not search_results:
                return RAGResponse(
                    query=query,
                    processed_query=processed_query,
                    query_confidence=query_result.confidence,
                    action="search",
                    results=[],
                    kg_expanded_terms=kg_expanded_terms or None,
                )

            # Step 5: Rerank against original query for relevance accuracy
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

            # Step 6: Generate answer from reranked chunks
            generated_answer = None
            if self._generator and reranked:
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

            return RAGResponse(
                query=query,
                processed_query=processed_query,
                query_confidence=query_result.confidence,
                action="search",
                results=reranked,
                kg_expanded_terms=kg_expanded_terms or None,
                generated_answer=generated_answer,
            )
        except Exception as exc:
            span_status = "error"
            span_error = exc
            raise
        finally:
            root_span.set_attribute("duration_ms", int((time.perf_counter() - start) * 1000))
            root_span.end(status=span_status, error=span_error)
