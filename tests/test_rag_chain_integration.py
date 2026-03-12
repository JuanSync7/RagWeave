from src.retrieval.query_processor import QueryAction, QueryResult
from src.retrieval.rag_chain import RAGChain


class _DummySpan:
    def set_attribute(self, key, value):
        return None

    def end(self, status="ok", error=None):
        return None


class _DummyTracer:
    def start_span(self, name, attrs=None, parent=None):
        return _DummySpan()


class _DummyRetryProvider:
    def execute(self, operation_name, fn, policy, idempotency_key):
        return fn()


def _build_chain_without_model_init() -> RAGChain:
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
    return chain


def test_rag_chain_returns_ask_user(monkeypatch):
    monkeypatch.setattr(
        "src.retrieval.rag_chain.process_query",
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
