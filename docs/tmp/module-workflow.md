### `src/ingest/embedding/workflow.py` — Embedding Pipeline DAG

**Purpose:**

This module compiles the Phase 2 LangGraph `StateGraph` for the Embedding Pipeline. It wires 10 nodes together in execution order, connecting `chunking_node` to `vlm_enrichment_node` (new in the Docling-native redesign) to `chunk_enrichment_node` and beyond. The graph is compiled once at call time via `build_embedding_graph()` and re-used for all documents in a batch run. This module contains only topology wiring — no business logic. (FR-2201 DAG placement)

**How it works:**

`build_embedding_graph()` constructs a `StateGraph(EmbeddingPipelineState)`, adds 10 nodes, wires edges, and calls `.compile()`:

**Node order:**
```
document_storage → chunking → vlm_enrichment → chunk_enrichment
→ metadata_generation → [cross_reference_extraction →] knowledge_graph_extraction
→ quality_validation → embedding_storage → [knowledge_graph_storage]
```

**Edges:**
- `document_storage → chunking`: always.
- `chunking → vlm_enrichment`: always. `vlm_enrichment_node` handles the no-op internally for `vlm_mode != "external"`.
- `vlm_enrichment → chunk_enrichment`: always.
- `chunk_enrichment → metadata_generation`: always.
- `metadata_generation → cross_reference_extraction OR knowledge_graph_extraction`: conditional based on `config.enable_cross_reference_extraction`.
- `cross_reference_extraction → knowledge_graph_extraction`: when cross-reference extraction ran.
- `knowledge_graph_extraction → quality_validation → embedding_storage`: always.
- `embedding_storage → knowledge_graph_storage OR end`: conditional based on `config.enable_knowledge_graph_storage`.

The conditional edge lambdas read `state["runtime"].config` directly — they access configuration at graph execution time, not at compilation time.

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| `vlm_enrichment_node` always in graph, no conditional edge to skip it | Conditional edge: skip `vlm_enrichment` if `vlm_mode != "external"` | An always-present node with internal no-op logic keeps the graph topology stable. Adding a conditional edge would require a router function and two explicit routing keys, adding complexity without benefit. The no-op costs only a dict copy and a log append. |
| `build_embedding_graph()` function (not a module-level singleton) | Module-level `_GRAPH = build_embedding_graph()` singleton | A function call allows callers to decide when compilation happens. The document processing module uses a singleton; this module exposes the builder function for flexibility. Callers in `src/ingest/embedding/impl.py` may cache the result themselves. |
| Conditional edges use inline lambdas | Named router functions | The routing conditions are simple one-liners. Named functions would add indirection without clarity benefit for conditions of this simplicity. |

**Configuration:**

This module has no configurable parameters of its own. The graph topology is fixed. Runtime routing is determined by `IngestionConfig` fields accessed within conditional edge lambdas:

| Config field accessed | Effect on routing |
|----------------------|-------------------|
| `config.enable_cross_reference_extraction` | Whether `cross_reference_extraction` node runs |
| `config.enable_knowledge_graph_storage` | Whether `knowledge_graph_storage` node runs |

**Error behavior:**

`build_embedding_graph()` raises `ImportError` if any node module fails to import (e.g., if a dependency is missing). It raises `ValueError` if LangGraph's graph compilation finds structural errors (e.g., unreachable nodes, invalid edge targets). These are programming errors, not runtime errors — they indicate a misconfigured graph definition, not a document processing failure.

At execution time, node exceptions are handled within each node (returning error state updates) rather than propagating through the graph. The graph itself does not catch node exceptions — if a node raises, LangGraph propagates it to the caller of `graph.invoke()`.
