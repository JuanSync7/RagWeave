<!-- @summary
End-to-end RAG orchestration: composes query processing, KG expansion, hybrid search, reranking, document formatting, LLM generation, guardrails, and confidence routing into a single RAGChain.run() call.
@end-summary -->

# retrieval/pipeline

## Overview

This directory contains the pipeline orchestrator — the single entry point that sequences all retrieval stages and returns a `RAGResponse`.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `rag_chain.py` | End-to-end RAG pipeline orchestration | `RAGChain`, `RAGResponse` |

## Stage Sequence

1. **Query processing** — sanitize, reformulate, confidence-route (`query/nodes/query_processor`)
2. **Input guardrails** — parallel with stage 1 when enabled
3. **KG expansion** — broaden BM25 query with knowledge graph terms
4. **Query embedding** — embed processed query (LRU-cached)
5. **Hybrid search** — Weaviate BM25 + vector search
6. **Reranking** — cross-encoder reranker (`query/nodes/reranker`)
7. **Document formatting** — metadata headers, version conflict detection (`generation/nodes/document_formatter`)
8. **LLM generation** — answer synthesis (`generation/nodes/generator`)
9. **Output guardrails** — faithfulness and safety rails
10. **Output sanitization** — remove prompt leakage artifacts (`generation/nodes/output_sanitizer`)
11. **Confidence routing** — 3-signal composite score, post-gen action (`generation/confidence`)

## Dependencies

- Reads schemas from `common/schemas.py` (`RAGRequest`, `RAGResponse`, `RankedResult`) and `query/schemas.py` (`QueryAction`, `QueryResult`).
- Delegates to nodes in `query/nodes/` and `generation/nodes/` — the orchestrator owns sequencing only, not node logic.
