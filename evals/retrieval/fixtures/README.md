<!-- @summary
Placeholder fixture directory for retrieval eval golden query sets.
Populate with golden_queries.json (per domain) before running retrieval evals.
@end-summary -->

# Retrieval Eval Fixtures

This directory holds golden query sets for the standalone retrieval evaluation suite
(`evals/retrieval/`). It is separate from the KG-specific queries in
`evals/knowledge_graph/fixtures/`.

## Expected Structure

```
fixtures/
└── asic/
    └── golden_queries.json   # Queries with expected relevant chunk IDs
```

## Schema

See `evals/knowledge_graph/fixtures/asic/golden_queries.json` for the schema reference.
The retrieval fixture uses the same schema (`version`, `domain`, `queries[]`).

## Status

Not yet populated. Add `golden_queries.json` here when the retrieval eval pipeline
is wired (Phase C of `docs/knowledge_graph/KNOWLEDGE_GRAPH_EVAL_PLAN.md`).
