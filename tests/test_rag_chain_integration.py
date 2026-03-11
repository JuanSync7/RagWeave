from src.retrieval.rag_chain import RAGChain
from src.retrieval.query_processor import QueryAction, QueryResult


def test_rag_chain_returns_ask_user(monkeypatch):
    monkeypatch.setattr(
        "src.retrieval.rag_chain.process_query",
        lambda q: QueryResult(
            processed_query=q,
            confidence=0.1,
            action=QueryAction.ASK_USER,
            clarification_message="clarify",
            iterations=1,
        ),
    )
    chain = RAGChain()
    response = chain.run("x")
    assert response.action == "ask_user"
    assert response.clarification_message == "clarify"
