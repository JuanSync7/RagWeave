<!-- @summary
Query processing and ranking documentation: spec, design, implementation plan, engineering guide, and module tests for the retrieval query sub-pipeline.
@end-summary -->

# docs/retrieval/query

Documentation for the **query processing and retrieval** stages of the AION RAG retrieval pipeline — from query intake through hybrid search and reranking.

## Files

| File | Purpose |
| --- | --- |
| `RETRIEVAL_QUERY_SPEC.md` | Normative requirements for query processing, conversation memory, pre-retrieval guardrails, retrieval, and reranking (REQ-101 – REQ-403, REQ-1001 – REQ-1008) |
| `RETRIEVAL_QUERY_DESIGN.md` | Technical design: task decomposition, dependency graph, and code contracts for the query sub-pipeline |
| `RETRIEVAL_QUERY_IMPLEMENTATION.md` | Phased implementation plan derived from the design |
| `RETRIEVAL_QUERY_ENGINEERING_GUIDE.md` | Post-implementation reference: architecture, stage-by-stage flow, decision rationale, troubleshooting |
| `RETRIEVAL_QUERY_MODULE_TESTS.md` | Module-level test specifications and pytest implementation |

## Scope

This sub-pipeline covers:

- Intent classification and query expansion
- Conversation memory and coreference resolution
- Pre-retrieval guardrails (PII, topic safety, toxicity)
- Hybrid search (dense + BM25 fusion)
- Cross-encoder reranking

For generation, post-generation guardrails, and observability, see `../generation/`.
