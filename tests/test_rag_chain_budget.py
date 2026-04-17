import types

from src.retrieval.query.schemas import QueryAction, QueryResult
from src.retrieval.pipeline.rag_chain import RAGChain


class _DummySpan:
    def set_attribute(self, key, value):
        return None

    def end(self, status="ok", error=None):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _DummyTracer:
    def span(self, name, attributes=None, parent=None):
        return _DummySpan()

    def start_span(self, name, attrs=None, parent=None):
        return _DummySpan()


class _DummyRetryProvider:
    def execute(self, operation_name, fn, policy, idempotency_key):
        return fn()


class _NeverCalledEmbeddings:
    def embed_query(self, _query):
        raise AssertionError("embed_query should not run after budget short-circuit")


def _build_chain_for_budget_tests() -> RAGChain:
    from collections import OrderedDict
    chain = object.__new__(RAGChain)
    chain.tracer = _DummyTracer()
    chain.retry_provider = _DummyRetryProvider()
    chain.retry_policy = object()
    chain._persistent_weaviate = False
    chain._weaviate_client = None
    chain._kg_expander = None
    chain._generator = None
    chain.embeddings = _NeverCalledEmbeddings()
    chain.reranker = None
    chain._guardrails_input_executor = None
    chain._guardrails_output_executor = None
    chain._guardrails_merge_gate = None
    chain._visual_retrieval_enabled = False
    chain._visual_model = None
    chain._visual_processor = None
    chain._embedding_cache = OrderedDict()
    chain._embedding_cache_max = 128
    return chain


def test_ranked_from_search_results_orders_and_limits():
    rows = [
        types.SimpleNamespace(text="b", score=0.1, metadata={"source": "b"}),
        types.SimpleNamespace(text="a", score=0.9, metadata={"source": "a"}),
        types.SimpleNamespace(text="c", score=0.5, metadata={"source": "c"}),
    ]
    ranked = RAGChain._ranked_from_search_results(rows, top_k=2)
    assert len(ranked) == 2
    assert ranked[0].text == "a"
    assert ranked[1].text == "c"


def test_run_short_circuits_on_budget_after_query_processing(monkeypatch):
    chain = _build_chain_for_budget_tests()

    monkeypatch.setattr(
        "src.retrieval.pipeline.rag_chain.process_query",
        lambda *args, **kwargs: QueryResult(
            processed_query="processed",
            confidence=0.8,
            action=QueryAction.SEARCH,
            clarification_message=None,
            iterations=1,
        ),
    )

    # overall_timeout_ms=-1: elapsed_ms() > -1 is always True, guaranteeing
    # budget exhaustion without relying on wall-clock timing.
    response = chain.run(
        "what is rag",
        overall_timeout_ms=-1,
    )

    assert response.action == "ask_user"
    assert response.budget_exhausted is True
    assert response.budget_exhausted_stage == "query_processing"
    assert response.clarification_message is not None


# ---------------------------------------------------------------------------
# Token budget tests
# ---------------------------------------------------------------------------


def test_token_budget_usage_does_not_exceed_100_with_many_large_chunks():
    """Many large chunks must not push usage_percent above 100."""
    from src.platform.token_budget.provider import calculate_budget
    from src.platform.token_budget.schemas import ModelCapabilities

    caps = ModelCapabilities(
        model_name="test-model",
        context_length=2048,
    )
    # 20 chunks of ~200 chars each — deliberately exceeds the effective budget
    large_chunks = ["x" * 200 for _ in range(20)]
    snapshot = calculate_budget(
        capabilities=caps,
        chunks=large_chunks,
        query="what is rag",
    )
    assert snapshot.usage_percent <= 100.0


def test_token_budget_zero_context_length_does_not_raise():
    """context_length=0 edge case must not cause a ZeroDivisionError."""
    from src.platform.token_budget.provider import calculate_budget
    from src.platform.token_budget.schemas import ModelCapabilities

    caps = ModelCapabilities(
        model_name="test-model",
        context_length=0,
    )
    # Should not raise regardless of content
    snapshot = calculate_budget(
        capabilities=caps,
        query="any query",
    )
    # usage_percent is clamped to [0, 100]
    assert 0.0 <= snapshot.usage_percent <= 100.0


def test_token_budget_empty_chunks_gives_low_usage():
    """Empty chunk list + short query should give well below 100% usage."""
    from src.platform.token_budget.provider import calculate_budget
    from src.platform.token_budget.schemas import ModelCapabilities

    caps = ModelCapabilities(
        model_name="test-model",
        context_length=2048,
    )
    snapshot = calculate_budget(
        capabilities=caps,
        chunks=[],
        query="hi",
    )
    assert snapshot.usage_percent < 50.0
    assert snapshot.breakdown.retrieval_chunks == 0
