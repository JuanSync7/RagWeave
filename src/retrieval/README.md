<!-- @summary
Retrieval subsystem for query processing, hybrid search, reranking, and optional LLM generation with timing/observability support.
@end-summary -->

# retrieval

## Overview

This directory contains the runtime retrieval path used by query serving, including:

- LangGraph-based query processing and confidence routing,
- hybrid vector + keyword retrieval orchestration,
- reranking and optional answer generation,
- stage timing instrumentation for retrieval vs generation latency splits.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `generator.py` | Ollama-based answer synthesis for non-stream and stream generation paths | `OllamaGenerator` |
| `query_processor.py` | Query sanitize/reformulate/evaluate state machine with confidence-based routing | `process_query`, `QueryResult`, `QueryAction`, `warm_up_ollama` |
| `rag_chain.py` | End-to-end retrieval orchestration (query processing, KG expansion, hybrid search, reranking, optional generation) | `RAGChain`, `RAGResponse` |
| `reranker.py` | Local reranker wrapper for final candidate ordering | `LocalBGEReranker`, `RankedResult` |

## Internal Dependencies

- `rag_chain.py` composes `query_processor.py`, `reranker.py`, `generator.py`, and core vector/KG modules.
- `query_processor.py` depends on prompt files in `prompts/` plus observability/retry providers.
- `generator.py` and `query_processor.py` both rely on Ollama HTTP endpoints and retry policies.

## Engineering Documentation

- `docs/retrieval/RETRIEVAL_ENGINEERING_GUIDE.md`: implementation walkthrough for architecture, flow, decisions, and troubleshooting.
- `docs/retrieval/RETRIEVAL_NEW_ENGINEER_ONBOARDING_CHECKLIST.md`: one-page onboarding checklist for setup, first change flow, and gotchas.

## Subdirectories

None
