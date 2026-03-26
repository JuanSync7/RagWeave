<!-- @summary
Generation and safety documentation: spec, design, implementation plan, engineering guide, and module tests for the retrieval generation sub-pipeline.
@end-summary -->

# docs/retrieval/generation

Documentation for the **generation, safety, and observability** stages of the AION RAG retrieval pipeline — from document formatting through LLM generation, post-generation guardrails, and metrics.

## Files

| File | Purpose |
| --- | --- |
| `RETRIEVAL_GENERATION_SPEC.md` | Normative requirements for document formatting, generation, post-generation guardrails, observability, and NFR (REQ-501 – REQ-903) |
| `RETRIEVAL_GENERATION_DESIGN.md` | Technical design: task decomposition, dependency graph, and code contracts for the generation sub-pipeline |
| `RETRIEVAL_GENERATION_IMPLEMENTATION.md` | Phased implementation plan derived from the design |
| `RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` | Post-implementation reference: architecture, stage-by-stage flow, decision rationale, troubleshooting |
| `RETRIEVAL_GENERATION_MODULE_TESTS.md` | Module-level test specifications and pytest implementation |

## Scope

This sub-pipeline covers:

- Document chunk formatting and metadata injection
- Version conflict detection before generation
- LLM context assembly and answer generation
- Post-generation guardrails (citation verification, hallucination detection, confidence scoring)
- Observability: latency budgets, trace IDs, metrics emission

For query processing, hybrid search, and reranking, see `../query/`.
