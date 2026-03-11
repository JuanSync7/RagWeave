from src.retrieval.reranker import LocalBGEReranker


def test_reranker_returns_top_k():
    reranker = LocalBGEReranker()
    docs = [
        {"text": "doc one", "metadata": {"source": "a"}},
        {"text": "doc two", "metadata": {"source": "b"}},
    ]
    ranked = reranker.rerank("query", docs, top_k=1)
    assert len(ranked) == 1
