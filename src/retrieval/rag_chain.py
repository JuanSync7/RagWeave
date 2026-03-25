# @summary
# End-to-end RAG pipeline for query processing, KG expansion, hybrid search, reranking, and LLM generation.
# Main classes: RAGChain, RAGResponse. Deps: src.retrieval.generator, src.retrieval.query_processor, src.core, src.platform.llm
# @end-summary
"""Main RAG chain that orchestrates the full retrieval pipeline."""

from typing import Any, Dict, List, Optional
import logging
import statistics
import time

from src.core.embeddings import LocalBGEEmbeddings
from src.retrieval.reranker import LocalBGEReranker
from src.retrieval.query_processor import process_query
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
from src.retrieval.schemas import QueryAction, QueryResult, RAGResponse, RankedResult
from src.platform.token_budget import calculate_budget, get_capabilities, TokenBudgetSnapshot
from src.retrieval.generator import _SYSTEM_PROMPT as _GEN_SYSTEM_PROMPT
from config.settings import (
    HYBRID_SEARCH_ALPHA, SEARCH_LIMIT, RERANK_TOP_K,
    KG_PATH, KG_ENABLED, GENERATION_ENABLED,
    RETRY_BACKOFF_MULTIPLIER,
    RETRY_INITIAL_BACKOFF_SECONDS,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_BACKOFF_SECONDS,
    MAX_SANITIZATION_ITERATIONS,
    QUERY_CONFIDENCE_THRESHOLD,
    RAG_DEFAULT_FAST_PATH,
    RAG_RETRIEVAL_TIMEOUT_MS,
    RAG_STAGE_BUDGET_QUERY_PROCESSING_MS,
    RAG_STAGE_BUDGET_KG_EXPANSION_MS,
    RAG_STAGE_BUDGET_EMBEDDING_MS,
    RAG_STAGE_BUDGET_HYBRID_SEARCH_MS,
    RAG_STAGE_BUDGET_RERANKING_MS,
    RAG_STAGE_BUDGET_GENERATION_MS,
)
from src.platform.timing import TimingPool
from config.settings import RAG_NEMO_ENABLED
from config.settings import (
    RAG_CONFIDENCE_ROUTING_ENABLED,
    RAG_CONFIDENCE_HIGH_THRESHOLD,
    RAG_CONFIDENCE_LOW_THRESHOLD,
    RAG_CONFIDENCE_RETRIEVAL_WEIGHT,
    RAG_CONFIDENCE_LLM_WEIGHT,
    RAG_CONFIDENCE_CITATION_WEIGHT,
    RAG_CONFIDENCE_RE_RETRIEVE_MAX_RETRIES,
    RAG_DOCUMENT_FORMATTING_ENABLED,
)

logger = logging.getLogger("rag.rag_chain")


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

        # Embedding LRU cache — avoids re-computing embeddings for repeated
        # exact queries (REQ-306). Keyed on the exact query string.
        from collections import OrderedDict
        self._embedding_cache: OrderedDict = OrderedDict()
        self._embedding_cache_max = 128

        # Initialize NeMo Guardrails (REQ-701: once at startup, not per-query)
        self._guardrails_input_executor = None
        self._guardrails_output_executor = None
        self._guardrails_merge_gate = None
        if RAG_NEMO_ENABLED:
            self._init_guardrails()

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

    def _init_guardrails(self) -> None:
        """Initialize NeMo Guardrails runtime and rail executors."""
        from config.settings import (
            RAG_NEMO_CONFIG_DIR,
            RAG_NEMO_FAITHFULNESS_ACTION,
            RAG_NEMO_FAITHFULNESS_ENABLED,
            RAG_NEMO_FAITHFULNESS_SELF_CHECK,
            RAG_NEMO_FAITHFULNESS_THRESHOLD,
            RAG_NEMO_INJECTION_ENABLED,
            RAG_NEMO_INJECTION_LP_THRESHOLD,
            RAG_NEMO_INJECTION_MODEL_ENABLED,
            RAG_NEMO_INJECTION_PERPLEXITY_ENABLED,
            RAG_NEMO_INJECTION_PS_PPL_THRESHOLD,
            RAG_NEMO_INJECTION_SENSITIVITY,
            RAG_NEMO_INTENT_CONFIDENCE_THRESHOLD,
            RAG_NEMO_OUTPUT_PII_ENABLED,
            RAG_NEMO_OUTPUT_TOXICITY_ENABLED,
            RAG_NEMO_PII_ENABLED,
            RAG_NEMO_PII_EXTENDED,
            RAG_NEMO_PII_SCORE_THRESHOLD,
            RAG_NEMO_RAIL_TIMEOUT_SECONDS,
            RAG_NEMO_TOPIC_SAFETY_ENABLED,
            RAG_NEMO_TOPIC_SAFETY_INSTRUCTIONS,
            RAG_NEMO_TOXICITY_ENABLED,
            RAG_NEMO_TOXICITY_THRESHOLD,
        )
        from src.guardrails.executor import (
            InputRailExecutor,
            OutputRailExecutor,
            RailMergeGate,
        )
        from src.guardrails.faithfulness import FaithfulnessChecker
        from src.guardrails.injection import InjectionDetector
        from src.guardrails.intent import IntentClassifier
        from src.guardrails.pii import PIIDetector
        from src.guardrails.runtime import GuardrailsRuntime
        from src.guardrails.topic_safety import TopicSafetyChecker
        from src.guardrails.toxicity import ToxicityFilter

        logger.info("Initializing NeMo Guardrails...")
        runtime = GuardrailsRuntime.get()
        runtime.initialize(RAG_NEMO_CONFIG_DIR)

        # Build input rail components (only if individually enabled)
        intent_classifier = IntentClassifier(
            confidence_threshold=RAG_NEMO_INTENT_CONFIDENCE_THRESHOLD,
        )  # Intent is always enabled when NeMo is on

        injection_detector = (
            InjectionDetector(
                sensitivity=RAG_NEMO_INJECTION_SENSITIVITY,
                enable_perplexity=RAG_NEMO_INJECTION_PERPLEXITY_ENABLED,
                enable_model_classifier=RAG_NEMO_INJECTION_MODEL_ENABLED,
                lp_threshold=RAG_NEMO_INJECTION_LP_THRESHOLD,
                ps_ppl_threshold=RAG_NEMO_INJECTION_PS_PPL_THRESHOLD,
            )
            if RAG_NEMO_INJECTION_ENABLED
            else None
        )
        from config.settings import RAG_NEMO_PII_GLINER_ENABLED

        pii_detector = (
            PIIDetector(
                extended=RAG_NEMO_PII_EXTENDED,
                score_threshold=RAG_NEMO_PII_SCORE_THRESHOLD,
                use_gliner=RAG_NEMO_PII_GLINER_ENABLED,
            )
            if RAG_NEMO_PII_ENABLED
            else None
        )
        toxicity_filter = (
            ToxicityFilter(threshold=RAG_NEMO_TOXICITY_THRESHOLD)
            if RAG_NEMO_TOXICITY_ENABLED
            else None
        )
        # Shared instances for output rails (same config → reuse to avoid
        # loading spacy/Presidio models twice)
        shared_pii = pii_detector  # reuse if output PII uses same config
        shared_toxicity = toxicity_filter
        topic_safety_checker = (
            TopicSafetyChecker(
                custom_instructions=RAG_NEMO_TOPIC_SAFETY_INSTRUCTIONS,
            )
            if RAG_NEMO_TOPIC_SAFETY_ENABLED
            else None
        )

        self._guardrails_input_executor = InputRailExecutor(
            intent_classifier=intent_classifier,
            injection_detector=injection_detector,
            pii_detector=pii_detector,
            toxicity_filter=toxicity_filter,
            topic_safety_checker=topic_safety_checker,
            timeout_seconds=RAG_NEMO_RAIL_TIMEOUT_SECONDS,
        )

        # Build output rail components
        faithfulness_checker = (
            FaithfulnessChecker(
                threshold=RAG_NEMO_FAITHFULNESS_THRESHOLD,
                action=RAG_NEMO_FAITHFULNESS_ACTION,
                use_self_check=RAG_NEMO_FAITHFULNESS_SELF_CHECK,
            )
            if RAG_NEMO_FAITHFULNESS_ENABLED
            else None
        )
        output_pii = shared_pii if RAG_NEMO_OUTPUT_PII_ENABLED else None
        output_toxicity = shared_toxicity if RAG_NEMO_OUTPUT_TOXICITY_ENABLED else None

        self._guardrails_output_executor = OutputRailExecutor(
            faithfulness_checker=faithfulness_checker,
            pii_detector=output_pii,
            toxicity_filter=output_toxicity,
            timeout_seconds=RAG_NEMO_RAIL_TIMEOUT_SECONDS,
        )

        self._guardrails_merge_gate = RailMergeGate()
        logger.info("NeMo Guardrails initialized successfully")

        # Register custom Colang actions with the NeMo runtime
        try:
            from config.guardrails.actions import set_rag_chain
            set_rag_chain(self)
            logger.info("RAG chain reference set for Colang rag_retrieve_and_generate action")
        except ImportError:
            logger.warning("Could not register RAG chain reference — config.guardrails.actions not found")

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

    @staticmethod
    def _ranked_from_search_results(search_results: List[dict], top_k: int) -> List[RankedResult]:
        """Convert hybrid-search dict rows into RankedResult list."""
        ranked = [
            RankedResult(
                text=str(item.get("text", "")),
                score=float(item.get("score", 0.0)),
                metadata=dict(item.get("metadata", {})),
            )
            for item in search_results
        ]
        ranked.sort(key=lambda result: result.score, reverse=True)
        return ranked[:top_k]

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
        memory_context: Optional[str] = None,
        memory_recent_turns: Optional[List[Dict[str, str]]] = None,
        conversation_id: Optional[str] = None,
        _retry_count: int = 0,
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
        stage_budget_overrides = stage_budget_overrides or {}
        stage_budgets = {
            "query_processing": int(stage_budget_overrides.get("query_processing", RAG_STAGE_BUDGET_QUERY_PROCESSING_MS)),
            "kg_expansion": int(stage_budget_overrides.get("kg_expansion", RAG_STAGE_BUDGET_KG_EXPANSION_MS)),
            "embedding": int(stage_budget_overrides.get("embedding", RAG_STAGE_BUDGET_EMBEDDING_MS)),
            "hybrid_search": int(stage_budget_overrides.get("hybrid_search", RAG_STAGE_BUDGET_HYBRID_SEARCH_MS)),
            "reranking": int(stage_budget_overrides.get("reranking", RAG_STAGE_BUDGET_RERANKING_MS)),
            "generation": int(stage_budget_overrides.get("generation", RAG_STAGE_BUDGET_GENERATION_MS)),
        }
        tp = TimingPool(
            overall_budget_ms=float(overall_timeout_ms),
            stage_budgets={k: float(v) for k, v in stage_budgets.items()},
        )
        pipeline_start = tp.pipeline_start  # for final span attribute
        root_span = self.tracer.start_span("rag_chain.run", {"query_length": len(query)})
        span_status = "ok"
        span_error: Optional[Exception] = None

        def _budget_clarification(stage: str) -> str:
            return (
                "This request reached the retrieval timeout budget during "
                f"{stage}. Please narrow the query or try again."
            )

        try:
            alpha = validate_alpha(alpha)
            search_limit = validate_positive_int("search_limit", search_limit)
            rerank_top_k = validate_positive_int("rerank_top_k", rerank_top_k)
            source_filter = validate_filter_value("source_filter", source_filter)
            heading_filter = validate_filter_value("heading_filter", heading_filter)

            # Stage 1: Query processing (+ input rails in parallel if NeMo enabled)
            t0 = time.perf_counter()
            query_span = self.tracer.start_span("rag_chain.process_query", parent=root_span)
            processing_query = query
            if memory_context:
                processing_query = (
                    "Conversation context:\n"
                    f"{memory_context}\n\n"
                    "Current user question:\n"
                    f"{query}"
                )

            # Run query processing and input rails in parallel (REQ-702)
            # PII gate: if PII detection is enabled, scan the query FIRST
            # before sending it to the LLM for reformulation. This prevents
            # PII from being sent to the LLM in the parallel execution window.
            guardrails_metadata = None
            input_rail_result = None
            merge_decision = None
            pii_gated_query = processing_query

            if self._guardrails_input_executor is not None:
                from concurrent.futures import ThreadPoolExecutor as _TP, Future as _Fut

                # PII gate: run PII detection synchronously before parallel stage
                pii_detector = getattr(self._guardrails_input_executor, 'pii_detector', None)
                if pii_detector is not None:
                    try:
                        pii_span = self.tracer.start_span("rag_chain.pii_gate", parent=root_span)
                        redacted_text, pii_detections = pii_detector.redact(query)
                        if pii_detections:
                            # Use redacted query for LLM processing
                            pii_gated_query = redacted_text
                            if memory_context:
                                pii_gated_query = (
                                    "Conversation context:\n"
                                    f"{memory_context}\n\n"
                                    "Current user question:\n"
                                    f"{redacted_text}"
                                )
                            logger.info(
                                "PII gate: %d detections redacted before LLM processing",
                                len(pii_detections),
                            )
                        pii_span.end(status="ok")
                    except Exception as e:
                        logger.warning("PII gate failed: %s — continuing with original query", e)
                        pii_gated_query = processing_query

                with _TP(max_workers=2, thread_name_prefix="stage1") as stage1_pool:
                    qp_future: _Fut = stage1_pool.submit(
                        process_query,
                        pii_gated_query,
                        QUERY_CONFIDENCE_THRESHOLD,
                        max_query_iterations,
                        RAG_DEFAULT_FAST_PATH if fast_path is None else bool(fast_path),
                    )
                    rail_future: _Fut = stage1_pool.submit(
                        self._guardrails_input_executor.execute,
                        query,
                        tenant_id or "",
                        root_span,
                    )

                    query_result = qp_future.result()
                    input_rail_result = rail_future.result()
            else:
                query_result: QueryResult = process_query(
                    processing_query,
                    max_iterations=max_query_iterations,
                    fast_path=RAG_DEFAULT_FAST_PATH if fast_path is None else bool(fast_path),
                )

            query_span.end(status="ok")
            tp.record("query_processing", "retrieval", started_at=t0)
            if tp.check_stage_budget("query_processing"):
                tp.mark_budget_exhausted("query_processing")

            # Apply merge gate if input rails ran (REQ-707)
            if input_rail_result is not None and self._guardrails_merge_gate is not None:
                from src.guardrails.common.schemas import GuardrailsMetadata

                merge_decision = self._guardrails_merge_gate.merge(
                    query_result, input_rail_result
                )

                # Record per-rail timings into the timing pool
                for r in input_rail_result.rail_executions:
                    tp.record(f"input_rail_{r.rail_name}", "guardrails", ms=r.execution_ms)

                guardrails_metadata = {
                    "enabled": True,
                    "input_rails": [
                        {
                            "rail_name": r.rail_name,
                            "verdict": r.verdict.value,
                            "execution_ms": r.execution_ms,
                            "details": r.details,
                        }
                        for r in input_rail_result.rail_executions
                    ],
                    "intent": input_rail_result.intent,
                    "intent_confidence": input_rail_result.intent_confidence,
                    "total_rail_ms": sum(
                        r.execution_ms for r in input_rail_result.rail_executions
                    ),
                }

                # Handle reject/canned responses from merge gate
                if merge_decision["action"] in ("reject", "canned"):
                    return RAGResponse(
                        query=query,
                        processed_query=query_result.processed_query,
                        query_confidence=query_result.confidence,
                        action="ask_user" if merge_decision["action"] == "reject" else "canned",
                        clarification_message=merge_decision["message"],
                        stage_timings=tp.entries(),
                        timing_totals=tp.totals(),
                        budget_exhausted=tp.budget_exhausted,
                        budget_exhausted_stage=tp.budget_exhausted_stage,
                        conversation_id=conversation_id,
                        guardrails=guardrails_metadata,
                    )

            if query_result.action == QueryAction.ASK_USER:
                return RAGResponse(
                    query=query,
                    processed_query=query_result.processed_query,
                    query_confidence=query_result.confidence,
                    action="ask_user",
                    clarification_message=query_result.clarification_message,
                    stage_timings=tp.entries(),
                    timing_totals=tp.totals(),
                    budget_exhausted=tp.budget_exhausted,
                    budget_exhausted_stage=tp.budget_exhausted_stage,
                    conversation_id=conversation_id,
                    guardrails=guardrails_metadata,
                )
            if tp.budget_exhausted:
                tp.log_summary()
                return RAGResponse(
                    query=query,
                    processed_query=query_result.processed_query,
                    query_confidence=query_result.confidence,
                    action="ask_user",
                    clarification_message=_budget_clarification("query processing"),
                    stage_timings=tp.entries(),
                    timing_totals=tp.totals(),
                    budget_exhausted=True,
                    budget_exhausted_stage=tp.budget_exhausted_stage,
                    conversation_id=conversation_id,
                    guardrails=guardrails_metadata,
                )

            # Use PII-redacted query if available from merge gate
            processed_query = (
                merge_decision.get("query", query_result.processed_query)
                if merge_decision
                else query_result.processed_query
            )

            # Stage 2: KG expansion
            t0 = time.perf_counter()
            kg_span = self.tracer.start_span("rag_chain.kg_expand", parent=root_span)
            kg_expanded_terms = []
            if self._kg_expander:
                kg_expanded_terms = self._kg_expander.expand(processed_query, depth=1)
            kg_span.set_attribute("kg_expanded_terms_count", len(kg_expanded_terms))
            kg_span.end(status="ok")
            tp.record("kg_expansion", "retrieval", started_at=t0)
            if tp.check_stage_budget("kg_expansion"):
                tp.mark_budget_exhausted("kg_expansion")
            if tp.budget_exhausted:
                tp.log_summary()
                return RAGResponse(
                    query=query,
                    processed_query=processed_query,
                    query_confidence=query_result.confidence,
                    action="ask_user",
                    clarification_message=_budget_clarification("KG expansion"),
                    kg_expanded_terms=kg_expanded_terms or None,
                    stage_timings=tp.entries(),
                    timing_totals=tp.totals(),
                    budget_exhausted=True,
                    budget_exhausted_stage=tp.budget_exhausted_stage,
                    conversation_id=conversation_id,
                )

            if kg_expanded_terms:
                bm25_query = processed_query + " " + " ".join(kg_expanded_terms[:3])
            else:
                bm25_query = processed_query

            # Stage 3: Query embedding (with LRU cache for exact repeats)
            t0 = time.perf_counter()
            embed_span = self.tracer.start_span("rag_chain.embed_query", parent=root_span)
            cache_hit = processed_query in self._embedding_cache
            if cache_hit:
                query_embedding = self._embedding_cache[processed_query]
                self._embedding_cache.move_to_end(processed_query)
                embed_span.set_attribute("cache_hit", True)
            else:
                query_embedding = self.embeddings.embed_query(processed_query)
                self._embedding_cache[processed_query] = query_embedding
                if len(self._embedding_cache) > self._embedding_cache_max:
                    self._embedding_cache.popitem(last=False)
                embed_span.set_attribute("cache_hit", False)
            embed_span.end(status="ok")
            tp.record("embedding", "retrieval", started_at=t0)
            if tp.check_stage_budget("embedding"):
                tp.mark_budget_exhausted("embedding")
            if tp.budget_exhausted:
                tp.log_summary()
                return RAGResponse(
                    query=query,
                    processed_query=processed_query,
                    query_confidence=query_result.confidence,
                    action="ask_user",
                    clarification_message=_budget_clarification("embedding"),
                    kg_expanded_terms=kg_expanded_terms or None,
                    stage_timings=tp.entries(),
                    timing_totals=tp.totals(),
                    budget_exhausted=True,
                    budget_exhausted_stage=tp.budget_exhausted_stage,
                    conversation_id=conversation_id,
                )

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
            tp.record("hybrid_search", "retrieval", started_at=t0)
            if tp.check_stage_budget("hybrid_search"):
                tp.mark_budget_exhausted("hybrid_search")
            if tp.budget_exhausted:
                tp.log_summary()
                return RAGResponse(
                    query=query,
                    processed_query=processed_query,
                    query_confidence=query_result.confidence,
                    action="search",
                    results=self._ranked_from_search_results(search_results, rerank_top_k),
                    kg_expanded_terms=kg_expanded_terms or None,
                    stage_timings=tp.entries(),
                    timing_totals=tp.totals(),
                    budget_exhausted=True,
                    budget_exhausted_stage=tp.budget_exhausted_stage,
                    conversation_id=conversation_id,
                )

            if not search_results:
                tp.log_summary()
                return RAGResponse(
                    query=query,
                    processed_query=processed_query,
                    query_confidence=query_result.confidence,
                    action="search",
                    results=[],
                    kg_expanded_terms=kg_expanded_terms or None,
                    stage_timings=tp.entries(),
                    timing_totals=tp.totals(),
                    budget_exhausted=tp.budget_exhausted,
                    budget_exhausted_stage=tp.budget_exhausted_stage,
                    conversation_id=conversation_id,
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
            tp.record("reranking", "retrieval", started_at=t0)
            if tp.check_stage_budget("reranking"):
                tp.mark_budget_exhausted("reranking")
            if tp.budget_exhausted:
                tp.log_summary()
                return RAGResponse(
                    query=query,
                    processed_query=processed_query,
                    query_confidence=query_result.confidence,
                    action="search",
                    results=reranked,
                    kg_expanded_terms=kg_expanded_terms or None,
                    stage_timings=tp.entries(),
                    timing_totals=tp.totals(),
                    budget_exhausted=True,
                    budget_exhausted_stage=tp.budget_exhausted_stage,
                    conversation_id=conversation_id,
                )

            # Classify retrieval quality based on reranker scores (REQ-403)
            retrieval_quality = "insufficient"
            retrieval_quality_note = None
            if reranked:
                best_score = max(r.score for r in reranked)
                if best_score >= 0.75:
                    retrieval_quality = "strong"
                elif best_score >= 0.50:
                    retrieval_quality = "moderate"
                elif best_score >= 0.30:
                    retrieval_quality = "weak"
                    retrieval_quality_note = (
                        "Retrieved documents have limited relevance to your query. "
                        "The answer below is based on the best available evidence."
                    )
                else:
                    retrieval_quality = "insufficient"
                    retrieval_quality_note = (
                        "No highly relevant documents were found. The answer below "
                        "is generated from loosely related content and may not be reliable."
                    )

            # Stage 5.5: Document formatting (REQ-501–REQ-503)
            version_conflicts = []
            formatted_context_str = None
            if RAG_DOCUMENT_FORMATTING_ENABLED and reranked:
                t0 = time.perf_counter()
                from src.retrieval.document_formatter import format_context
                fmt_span = self.tracer.start_span("rag_chain.format_context", parent=root_span)
                formatted = format_context(reranked)
                formatted_context_str = formatted.context_string
                version_conflicts = formatted.version_conflicts
                fmt_span.set_attribute("chunk_count", formatted.chunk_count)
                fmt_span.set_attribute("version_conflicts", len(version_conflicts))
                fmt_span.end(status="ok")
                tp.record("document_formatting", "retrieval", started_at=t0)

            # Stage 6: Generation (skippable for streaming callers)
            generated_answer = None
            if not skip_generation and self._generator and reranked and not tp.budget_exhausted:
                t0 = time.perf_counter()
                generate_span = self.tracer.start_span("rag_chain.generate", parent=root_span)
                context_chunks = [r.text for r in reranked]
                scores = [r.score for r in reranked]

                # Use formatted context if document formatting is enabled
                if formatted_context_str:
                    generated_answer = self._generator.generate(
                        query=processed_query,
                        context_chunks=[formatted_context_str],
                        scores=None,
                        memory_context=memory_context,
                        recent_turns=memory_recent_turns,
                    )
                else:
                    generated_answer = self._generator.generate(
                        query=processed_query,
                        context_chunks=context_chunks,
                        scores=scores,
                        memory_context=memory_context,
                        recent_turns=memory_recent_turns,
                    )
                generate_span.set_attribute("generated_answer_present", bool(generated_answer))
                generate_span.end(status="ok")
                tp.record("generation", "generation", started_at=t0)
                if tp.check_stage_budget("generation"):
                    tp.mark_budget_exhausted("generation")

            # Token budget snapshot (post-retrieval, post-generation)
            token_budget = None
            try:
                context_texts = [r.text for r in reranked]
                snapshot = calculate_budget(
                    system_prompt=_GEN_SYSTEM_PROMPT,
                    memory_context=memory_context,
                    chunks=context_texts,
                    query=processed_query,
                    model=self._generator.model if self._generator else None,
                )
                # Enrich with actual token usage from the LLM response
                actual_resp = getattr(self._generator, "_last_response", None) if self._generator else None
                if actual_resp and actual_resp.prompt_tokens:
                    snapshot = TokenBudgetSnapshot(
                        input_tokens=snapshot.input_tokens,
                        context_length=snapshot.context_length,
                        output_reservation=snapshot.output_reservation,
                        usage_percent=snapshot.usage_percent,
                        model_name=snapshot.model_name,
                        breakdown=snapshot.breakdown,
                        actual_prompt_tokens=actual_resp.prompt_tokens,
                        actual_completion_tokens=actual_resp.completion_tokens,
                        actual_total_tokens=actual_resp.total_tokens,
                        cost_usd=actual_resp.cost_usd,
                    )
                token_budget = snapshot
            except Exception as exc:
                logger.debug("Token budget calculation failed: %s", exc)

            # Stage 7: Output rails (REQ-703: parallel with consensus gate)
            if (
                generated_answer
                and self._guardrails_output_executor is not None
                and not tp.budget_exhausted
            ):
                t0 = time.perf_counter()
                output_rail_span = self.tracer.start_span(
                    "rag_chain.output_rails", parent=root_span
                )
                context_chunks = [r.text for r in reranked]
                output_rail_result = self._guardrails_output_executor.execute(
                    answer=generated_answer,
                    context_chunks=context_chunks,
                    parent_span=root_span,
                )
                output_rail_span.end(status="ok")
                tp.record("output_rails", "guardrails", started_at=t0)

                # Record per-rail timings into the timing pool
                for r in output_rail_result.rail_executions:
                    tp.record(f"output_rail_{r.rail_name}", "guardrails", ms=r.execution_ms)

                # Apply output rail results
                generated_answer = output_rail_result.final_answer or generated_answer

                # Add output rail metadata to guardrails
                if guardrails_metadata is None:
                    guardrails_metadata = {"enabled": True, "total_rail_ms": 0.0}
                guardrails_metadata["output_rails"] = [
                    {
                        "rail_name": r.rail_name,
                        "verdict": r.verdict.value,
                        "execution_ms": r.execution_ms,
                        "details": r.details,
                    }
                    for r in output_rail_result.rail_executions
                ]
                guardrails_metadata["faithfulness_score"] = output_rail_result.faithfulness_score
                guardrails_metadata["faithfulness_warning"] = output_rail_result.faithfulness_warning
                guardrails_metadata["total_rail_ms"] = guardrails_metadata.get(
                    "total_rail_ms", 0.0
                ) + sum(
                    r.execution_ms for r in output_rail_result.rail_executions
                )

            # Stage 7.25: Output sanitization (REQ-704)
            if generated_answer:
                from src.retrieval.output_sanitizer import sanitize_answer
                generated_answer = sanitize_answer(
                    generated_answer,
                    system_prompt=_GEN_SYSTEM_PROMPT,
                )

            # Stage 7.5: Composite confidence scoring + routing (REQ-701, REQ-706)
            composite_confidence = None
            confidence_breakdown_dict = None
            post_guardrail_action = None
            verification_warning = None
            re_retrieval_suggested = False
            re_retrieval_params = None

            if (
                RAG_CONFIDENCE_ROUTING_ENABLED
                and generated_answer
                and reranked
                and not tp.budget_exhausted
            ):
                t0 = time.perf_counter()
                conf_span = self.tracer.start_span("rag_chain.confidence_routing", parent=root_span)

                from src.retrieval.confidence.scoring import compute_composite_confidence
                from src.retrieval.confidence.routing import route_by_confidence
                from src.retrieval.confidence.schemas import PostGuardrailAction

                reranker_scores = [r.score for r in reranked]
                llm_confidence_text = (
                    self._generator._last_llm_confidence
                    if self._generator
                    else "medium"
                )
                context_texts = [r.text for r in reranked]

                breakdown = compute_composite_confidence(
                    reranker_scores=reranker_scores,
                    llm_confidence_text=llm_confidence_text,
                    answer=generated_answer,
                    retrieved_texts=context_texts,
                    retrieval_weight=RAG_CONFIDENCE_RETRIEVAL_WEIGHT,
                    llm_weight=RAG_CONFIDENCE_LLM_WEIGHT,
                    citation_weight=RAG_CONFIDENCE_CITATION_WEIGHT,
                )
                composite_confidence = breakdown.composite
                confidence_breakdown_dict = {
                    "retrieval_score": breakdown.retrieval_score,
                    "llm_score": breakdown.llm_score,
                    "citation_score": breakdown.citation_score,
                    "composite": breakdown.composite,
                    "retrieval_weight": breakdown.retrieval_weight,
                    "llm_weight": breakdown.llm_weight,
                    "citation_weight": breakdown.citation_weight,
                }

                action = route_by_confidence(
                    composite=breakdown.composite,
                    retry_count=_retry_count,
                    high_threshold=RAG_CONFIDENCE_HIGH_THRESHOLD,
                    low_threshold=RAG_CONFIDENCE_LOW_THRESHOLD,
                    max_retries=RAG_CONFIDENCE_RE_RETRIEVE_MAX_RETRIES,
                )
                post_guardrail_action = action.value

                conf_span.set_attribute("composite_confidence", breakdown.composite)
                conf_span.set_attribute("routing_action", action.value)
                conf_span.set_attribute("retry_count", _retry_count)
                conf_span.end(status="ok")
                tp.record("confidence_routing", "retrieval", started_at=t0)

                logger.info(
                    "Confidence routing: composite=%.2f action=%s retry=%d "
                    "(retrieval=%.2f llm=%.2f citation=%.2f)",
                    breakdown.composite,
                    action.value,
                    _retry_count,
                    breakdown.retrieval_score,
                    breakdown.llm_score,
                    breakdown.citation_score,
                )

                # Act on routing decision (non-blocking: return first response
                # immediately, suggest re-retrieval for caller to request)
                re_retrieval_suggested = False
                re_retrieval_params = None

                if action == PostGuardrailAction.RE_RETRIEVE:
                    # Don't block — return the first answer and suggest re-retrieval.
                    # The caller (UI/API) can request a second attempt with these
                    # broader params. The user sees both side-by-side and chooses.
                    re_retrieval_suggested = True
                    re_retrieval_params = {
                        "alpha": max(0.0, alpha - 0.15),
                        "search_limit": search_limit + 5,
                        "rerank_top_k": rerank_top_k,
                        "fast_path": True,
                    }
                    verification_warning = (
                        "This answer has moderate confidence. A broader search "
                        "may yield better results — re-retrieval is available."
                    )
                elif action == PostGuardrailAction.BLOCK:
                    generated_answer = (
                        "Insufficient documentation found to provide a reliable answer. "
                        "Please try a more specific query."
                    )
                elif action == PostGuardrailAction.FLAG:
                    verification_warning = (
                        "This answer has limited confidence. "
                        "Please verify against source documents before relying on it."
                    )

            tp.log_summary()

            return RAGResponse(
                query=query,
                processed_query=processed_query,
                query_confidence=query_result.confidence,
                action="search",
                results=reranked,
                kg_expanded_terms=kg_expanded_terms or None,
                generated_answer=generated_answer,
                stage_timings=tp.entries(),
                timing_totals=tp.totals(),
                budget_exhausted=tp.budget_exhausted,
                budget_exhausted_stage=tp.budget_exhausted_stage,
                conversation_id=conversation_id,
                guardrails=guardrails_metadata,
                token_budget=token_budget,
                composite_confidence=composite_confidence,
                confidence_breakdown=confidence_breakdown_dict,
                post_guardrail_action=post_guardrail_action,
                version_conflicts=(
                    [{"spec_stem": c.spec_stem, "versions": c.versions} for c in version_conflicts]
                    if version_conflicts
                    else None
                ),
                retry_count=_retry_count,
                verification_warning=verification_warning,
                retrieval_quality=retrieval_quality,
                retrieval_quality_note=retrieval_quality_note,
                re_retrieval_suggested=re_retrieval_suggested if RAG_CONFIDENCE_ROUTING_ENABLED else False,
                re_retrieval_params=re_retrieval_params,
            )
        except Exception as exc:
            span_status = "error"
            span_error = exc
            raise
        finally:
            root_span.set_attribute("duration_ms", int((time.perf_counter() - pipeline_start) * 1000))
            root_span.end(status=span_status, error=span_error)



__all__ = ["RAGChain", "RAGResponse"]
