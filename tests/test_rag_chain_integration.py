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


def _build_chain_without_model_init() -> RAGChain:
    from collections import OrderedDict
    chain = object.__new__(RAGChain)
    chain.tracer = _DummyTracer()
    chain.retry_provider = _DummyRetryProvider()
    chain.retry_policy = object()
    chain._persistent_weaviate = False
    chain._weaviate_client = None
    chain._kg_expander = None
    chain._generator = None
    chain.embeddings = None
    chain.reranker = None
    chain._guardrails_input_executor = None
    chain._guardrails_output_executor = None
    chain._embedding_cache = OrderedDict()
    chain._embedding_cache_max = 128
    return chain


def test_rag_chain_returns_ask_user(monkeypatch):
    monkeypatch.setattr(
        "src.retrieval.pipeline.rag_chain.process_query",
        lambda *args, **kwargs: QueryResult(
            processed_query="x",
            confidence=0.1,
            action=QueryAction.ASK_USER,
            clarification_message="clarify",
            iterations=1,
        ),
    )
    chain = _build_chain_without_model_init()
    response = chain.run("x")
    assert response.action == "ask_user"
    assert response.clarification_message == "clarify"
