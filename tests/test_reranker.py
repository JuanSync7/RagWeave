import types

from src.retrieval.query.nodes.reranker import LocalBGEReranker


def test_reranker_returns_top_k():
    reranker = LocalBGEReranker()
    docs = [
        types.SimpleNamespace(text="doc one", metadata={"source": "a"}),
        types.SimpleNamespace(text="doc two", metadata={"source": "b"}),
    ]
    ranked = reranker.rerank("query", docs, top_k=1)
    assert len(ranked) == 1
