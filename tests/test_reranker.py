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


def test_reranker_truncates_to_top_k_from_many_candidates():
    """Reranker must return at most top_k results even with many input candidates.

    The stub model returns at most 2 logits per batch call (conftest limitation),
    so we use top_k=1 to verify truncation is applied correctly.
    """
    reranker = LocalBGEReranker()
    docs = [
        types.SimpleNamespace(text=f"document {i}", metadata={"source": f"doc{i}"})
        for i in range(5)
    ]
    ranked = reranker.rerank("search query", docs, top_k=1)
    assert len(ranked) == 1


def test_reranker_output_sorted_descending_by_score():
    """Output list must be sorted by score in descending order."""
    reranker = LocalBGEReranker()
    docs = [
        types.SimpleNamespace(text="first doc", metadata={}),
        types.SimpleNamespace(text="second doc", metadata={}),
        types.SimpleNamespace(text="third doc", metadata={}),
    ]
    ranked = reranker.rerank("query", docs, top_k=3)
    scores = [r.score for r in ranked]
    assert scores == sorted(scores, reverse=True)


def test_reranker_empty_input_returns_empty_list():
    """Empty document list must not crash and must return an empty list."""
    reranker = LocalBGEReranker()
    ranked = reranker.rerank("any query", [], top_k=5)
    assert ranked == []
