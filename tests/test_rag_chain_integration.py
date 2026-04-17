import pytest

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
    chain._guardrails_merge_gate = None
    chain._visual_retrieval_enabled = False
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


# ---------------------------------------------------------------------------
# Hybrid search alpha blending tests
# ---------------------------------------------------------------------------


class _DummyCtxMgr:
    """Context manager that returns a dummy Weaviate client."""

    def __enter__(self):
        return object()

    def __exit__(self, *_args):
        return False


@pytest.mark.parametrize("alpha,label", [
    (0.0, "BM25 only"),
    (1.0, "vector only"),
    (0.5, "balanced blend"),
])
def test_do_search_passes_alpha_to_search(monkeypatch, alpha, label):
    """alpha value must be forwarded to the search layer unchanged."""
    captured = {}

    def _fake_search(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr("src.retrieval.pipeline.rag_chain.search", _fake_search)
    monkeypatch.setattr("src.retrieval.pipeline.rag_chain.get_client", _DummyCtxMgr)
    monkeypatch.setattr("src.retrieval.pipeline.rag_chain.ensure_collection", lambda *a, **k: None)

    chain = _build_chain_without_model_init()
    chain._do_search("test query", [0.1, 0.2, 0.3], alpha=alpha, search_limit=5, filters=None)

    assert abs(captured.get("alpha") - alpha) < 1e-9, f"{label}: expected alpha={alpha}"
