# Knowledge Graph Subsystem -- Design Sketch

**Date:** 2026-04-08
**Status:** Brainstorm / Pre-Spec
**Author:** Auto-generated design exploration

---

## Goal

Replace the monolithic `src/core/knowledge_graph.py` (558 lines) with a full
`src/knowledge_graph/` package that supports swappable storage backends,
multi-strategy extraction (regex, GLiNER, LLM structured output,
SystemVerilog parser), entity descriptions, two-tier query matching, and a
YAML-driven entity/edge type schema. The new subsystem must integrate
cleanly with the existing LangGraph embedding pipeline (Nodes 10/13) and the
retrieval pipeline's Stage 2 KG expansion, while preserving backward
compatibility for current NetworkX JSON graphs.

---

## Codebase Context Summary

### What exists today

| Component | Location | Role |
|-----------|----------|------|
| Entity extraction (regex) | `src/core/knowledge_graph.py` `EntityExtractor` | CamelCase, acronym, multi-word patterns; sentence-level relation regexes |
| Entity extraction (GLiNER) | `src/core/knowledge_graph.py` `GLiNEREntityExtractor` | Zero-shot NER; delegates aliases and relations back to regex extractor |
| Graph builder | `src/core/knowledge_graph.py` `KnowledgeGraphBuilder` | NetworkX DiGraph with case-insensitive alias dedup, JSON (orjson) persistence |
| Query expansion | `src/core/knowledge_graph.py` `GraphQueryExpander` | Substring entity matching in query text; 1-hop forward + predecessor expansion |
| Obsidian export | `src/core/knowledge_graph.py` `export_obsidian()` | Per-node markdown with wikilinks |
| Ingestion node 10 | `src/ingest/embedding/nodes/knowledge_graph_extraction.py` | Extracts triples from chunks via `EntityExtractor`, stages as `kg_triples` |
| Ingestion node 13 | `src/ingest/embedding/nodes/knowledge_graph_storage.py` | Feeds chunks to `KnowledgeGraphBuilder.add_chunk()` via runtime builder |
| Retrieval Stage 2 | `src/retrieval/pipeline/rag_chain.py` (line ~586) | Loads KG at startup, calls `GraphQueryExpander.expand()`, appends up to 3 terms to BM25 query |
| ABC backend pattern | `src/guardrails/` | `GuardrailBackend` ABC + lazy singleton dispatcher in `__init__.py`; `common/schemas.py` for typed contracts |

### What is lacking

1. **No LLM-based extraction.** Regex patterns miss implicit relations, domain-specific semantics, and anything not in Subject-Verb-Object surface form.
2. **No structural parser.** ASIC codebases have deterministic structure (modules, ports, instances, FSMs) that tree-sitter can extract with 100% precision, but nothing currently does.
3. **No entity descriptions.** Nodes carry only `type`, `sources`, `mention_count`, `aliases` -- no accumulated textual description (the LightRAG pattern for grounding retrieval).
4. **No schema governance.** Entity/edge types are ad-hoc heuristics (`_classify_type`). No validation that extractors produce types the system expects.
5. **Monolithic file.** Extraction, storage, query expansion, and export live in one 558-line file with no ABC abstraction and no room for a second backend.
6. **Weak query matching.** Substring matching produces false positives on short entity names; no fuzzy/embedding-based fallback for paraphrased queries.
7. **No community detection.** No Leiden/Louvain clustering for global retrieval over large graphs.

---

## Approaches

### Approach A: Monolith-to-Package Refactor with Multi-Extractor Registry

Refactor `knowledge_graph.py` into a package with a central **Extractor Registry** -- an ordered list of extractors (regex, GLiNER, LLM, SV parser) that run sequentially. Each extractor implements an `Extractor` protocol and produces a common `ExtractionResult` (entities + triples + descriptions). A `MergeStrategy` collapses overlapping results before they hit the storage backend.

Storage uses a `GraphStorageBackend` ABC (mirroring `GuardrailBackend`), with `NetworkXBackend` as the Phase 1 concrete and `Neo4jBackend` as a Phase 2 stub.

The YAML schema is loaded at init time and injected into every extractor as prompt context (for LLM) or validation filter (for regex/parser).

**Pros:**
- Clean separation: each extractor is an independent file with a testable protocol.
- Registry pattern makes it trivial to add/remove extractors via config.
- YAML schema serves double duty (LLM prompting + runtime validation) without two codepaths.
- Mirrors the proven `src/guardrails/` pattern the team already understands.

**Cons:**
- Sequential extractor execution adds latency per chunk (mitigated by making extractors optional/parallel).
- Merge strategy complexity: overlapping entity spans from regex + GLiNER + LLM need dedup with priority rules.
- The registry pattern may be over-engineered if only 2-3 extractors are ever used.

**Devil's advocate (if rejected):** The registry adds indirection that makes debugging harder -- when an entity appears in the graph, you cannot tell which extractor produced it without logging. For a system with at most 4 extractors, explicit composition (Approach B) may be simpler.

---

### Approach B: Explicit Composition via LangGraph Subgraph (Recommended)

Model the multi-extractor pipeline as a **LangGraph subgraph** within embedding Node 10. The subgraph has parallel branches for each enabled extractor (regex, GLiNER, LLM, SV parser), a merge node that performs entity resolution, and an output that writes the unified `ExtractionResult` to pipeline state. Storage remains a separate node (Node 13) that calls the `GraphStorageBackend` ABC.

The YAML schema is loaded once and passed through the subgraph state. LLM extraction uses it as structured-output instructions; regex/parser extractors use it as a post-extraction type validator.

Entity resolution in the merge node uses a two-pass strategy:
1. **Alias dedup** (current approach, fast) -- exact match + acronym expansion.
2. **Embedding similarity** (Phase 1 stretch / Phase 2) -- embed entity names with the existing BGE-M3 model and merge entities above a configurable cosine threshold.

Query matching upgrades to two-tier:
1. **spaCy rule-based matcher** (token-boundary, fast) replaces substring matching.
2. **LLM fallback** (when spaCy finds zero matches on a non-trivial query) asks the LLM to identify entities from the query given the schema.

**Pros:**
- LangGraph subgraph is native to the existing pipeline architecture -- no new orchestration pattern.
- Parallel branches mean LLM extraction latency does not block regex/parser extraction.
- The merge node is a single, explicit, testable function -- no registry indirection.
- Entity resolution strategy can evolve (alias -> embedding -> LLM) without changing the subgraph topology.
- spaCy matcher is a significant precision upgrade over substring matching with minimal latency cost.

**Cons:**
- LangGraph subgraph adds graph-compilation overhead per invocation (mitigated by compiling once and reusing).
- Tighter coupling to LangGraph -- if the project ever moves away from LangGraph, the extraction pipeline moves with it.
- Parallel branches require careful state merging (LangGraph's reducer pattern handles this, but it is another thing to get right).

**Devil's advocate (if rejected):** LangGraph subgraph coupling is real but acceptable -- the entire ingestion pipeline is already LangGraph. The compilation cost is one-time. The alternative (Approach A registry) would need its own orchestration for parallelism, essentially reimplementing what LangGraph already provides.

---

### Approach C: Standalone Extraction Service (Microservice)

Extract the KG subsystem into an independent service with a gRPC/REST API. Ingestion nodes call the service; retrieval loads a read-only snapshot. The service owns its own storage (NetworkX in-process or Neo4j) and exposes query expansion as an API endpoint.

**Pros:**
- Full decoupling: KG can be developed, deployed, and scaled independently.
- Natural fit for Neo4j backend (service owns the connection pool).
- Could serve multiple consumers beyond RagWeave.

**Cons:**
- Massive operational overhead for a single-team project (deployment, networking, versioning, health checks).
- Serialization cost for every chunk during ingestion (currently zero-copy in-process).
- Adds a network hop to the retrieval hot path (KG expansion is latency-sensitive).
- Premature for current scale -- the graph fits in memory on a single machine.

**Devil's advocate (if rejected):** This approach becomes compelling only if the graph outgrows single-machine memory or Neo4j becomes the primary backend. At current scale (thousands of entities, not millions), in-process is correct. The ABC backend pattern in Approach B provides the hook for a future service boundary without paying the cost now.

---

## Recommendation: Approach B -- Explicit Composition via LangGraph Subgraph

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Extraction architecture** | LangGraph subgraph with parallel extractor branches + merge node | Native to existing pipeline; parallelism is free; merge is explicit and testable |
| **LangGraph integration** | Subgraph within Node 10 (not standalone service) | Avoids network hop; keeps ingestion pipeline self-contained |
| **Entity resolution** | Two-pass: alias dedup (Phase 1) + embedding similarity (Phase 1 stretch) | Alias dedup is proven; embedding similarity is a targeted upgrade, not a rewrite |
| **Storage abstraction** | Rich ABC (`GraphStorageBackend`) with CRUD + query + traversal + stats | Thin ABC would push too much logic into callers; rich ABC lets backends optimize |
| **YAML schema role** | Both: LLM prompt injection AND runtime validation | Single source of truth; LLM sees allowed types, validator rejects anything outside |
| **Query matching** | spaCy rule-based (fast) + LLM fallback (expensive, conditional) | spaCy fixes substring false positives; LLM catches paraphrased entities |

### Component Map

```
src/knowledge_graph/
  __init__.py                       # Public API: get_graph_backend(), get_query_expander()
                                    # Lazy singleton dispatcher (mirrors src/guardrails/__init__.py)
  backend.py                        # GraphStorageBackend ABC
  common/
    schemas.py                      # Entity, Triple, ExtractionResult, EntityDescription dataclasses
    types.py                        # KGConfig, SchemaDefinition (loaded from kg_schema.yaml)
    utils.py                        # Shared helpers: alias normalization, type validation
  extraction/
    __init__.py                     # ExtractionPipeline: compiles and runs the subgraph
    base.py                         # EntityExtractor protocol (extract_entities, extract_triples)
    regex_extractor.py              # Current EntityExtractor, migrated from core/knowledge_graph.py
    gliner_extractor.py             # Current GLiNEREntityExtractor, migrated
    llm_extractor.py                # LLM structured-output extractor (new)
    sv_parser.py                    # tree-sitter-verilog structural extractor (new)
    merge.py                        # Merge node: dedup, alias resolution, type validation
  query/
    entity_matcher.py               # spaCy rule-based matcher (replaces substring matching)
    expander.py                     # GraphQueryExpander (migrated, enhanced with descriptions)
    sanitizer.py                    # Token-boundary matching, alias expansion, fan-out control
    llm_fallback.py                 # LLM entity identification from query (new)
  backends/
    networkx_backend.py             # NetworkX + orjson persistence (migrated from KnowledgeGraphBuilder)
    neo4j_backend.py                # Phase 2 stub (ABC methods raise NotImplementedError)
  community/
    detector.py                     # Phase 2 stub: Leiden algorithm interface
    summarizer.py                   # Phase 2 stub: LLM community summarization
  export/
    obsidian.py                     # Migrated from core/knowledge_graph.py

config/
  kg_schema.yaml                    # Entity types, edge types, phase tags, extraction hints
```

### Integration Points

**Ingestion (Node 10 rewrite):**
```
knowledge_graph_extraction_node(state) ->
  ExtractionPipeline.run(chunks, config) ->
    [parallel: regex | gliner | llm | sv_parser] ->
    merge_node(results, schema) ->
    ExtractionResult(entities, triples, descriptions)
  -> state["kg_extraction_result"] = result
```

**Ingestion (Node 13 rewrite):**
```
knowledge_graph_storage_node(state) ->
  backend = get_graph_backend()
  backend.upsert_entities(result.entities)
  backend.upsert_triples(result.triples)
  backend.upsert_descriptions(result.descriptions)
```

**Retrieval (Stage 2 rewrite):**
```
expander = get_query_expander()
matched = expander.match_entities(query)    # spaCy fast path
if not matched:
    matched = llm_fallback.identify(query)  # LLM slow path
expanded_terms = expander.expand(matched, depth=1)
bm25_query = query + " " + " ".join(expanded_terms[:3])
```

### Scope Boundary

**In scope (Phase 1) -- Prove the architecture:**
- Package structure and all files listed above
- `GraphStorageBackend` ABC + `NetworkXBackend` concrete implementation
- Migrate regex extractor from `src/core/knowledge_graph.py`
- Migrate GLiNER extractor from `src/core/knowledge_graph.py`
- YAML schema with ASIC node/edge types
- Entity descriptions (accumulated rich text per node, see accumulation strategy below)
- spaCy rule-based entity matcher
- Improved query sanitization (token-boundary matching, alias expansion, fan-out control)
- Migration of all functionality from `src/core/knowledge_graph.py`
- Backward-compatible import aliases in `src/core/knowledge_graph.py`
- Update Node 10, Node 13, and `rag_chain.py` Stage 2

**In scope (Phase 1b) -- Net-new extraction capabilities (after architecture is proven):**
- LLM extractor with structured JSON output (using existing LiteLLM router)
- SV parser using tree-sitter-verilog
- LLM query fallback (conditional)

**Out of scope (Phase 2 -- stubbed):**
- Community detection (Leiden algorithm)
- Global retrieval (community-summary search)
- Neo4j backend (full implementation)
- Python/Bash structural parsers
- Embedding-based entity resolution (Phase 1 stretch goal)

---

## Phase 1 vs Phase 2 Delineation

| Capability | Phase 1 | Phase 1b | Phase 2 |
|------------|---------|---------|---------|
| Package structure + ABC | Full implementation | -- | -- |
| NetworkX backend | Full implementation | -- | -- |
| Neo4j backend | Stub (raises `NotImplementedError`) | -- | Full implementation |
| Regex extractor | Migrate from monolith | -- | -- |
| GLiNER extractor | Migrate from monolith | -- | -- |
| LLM extractor | -- | Full implementation | Refinement |
| SV parser (tree-sitter) | -- | Full implementation | -- |
| Python/Bash parsers | -- | -- | Full implementation |
| Entity descriptions | Full implementation | -- | -- |
| YAML schema | Full implementation | -- | Add community-level schema |
| spaCy query matcher | Full implementation | -- | -- |
| Improved query sanitization | Full implementation | -- | -- |
| LLM query fallback | -- | Full implementation | -- |
| Alias-based entity resolution | Full implementation | -- | -- |
| Embedding-based entity resolution | -- | Stretch goal | Full implementation |
| Community detection | Stub interface only | -- | Leiden + LLM summaries |
| Global retrieval | -- | -- | Community-summary search |
| Obsidian export | Migrate from monolith | -- | -- |
| Backward-compatible aliases | `src/core/knowledge_graph.py` shim | -- | Remove after migration period |

---

## Entity Description Accumulation Strategy

Entity descriptions accumulate across multiple chunks that mention the same entity.
The strategy balances completeness (capturing diverse context) with bounded storage.

### Accumulation rules

1. **Append with attribution.** Each new mention of an entity appends the relevant
   sentence or passage to the entity's `raw_mentions` list, tagged with the source
   chunk ID and document path. Example entry:
   ```
   {"text": "The AXI arbiter handles priority-based arbitration between masters.",
    "source": "rtl/axi_arbiter.sv", "chunk_id": "c-0042"}
   ```

2. **Token budget trigger.** When the combined token count of `raw_mentions` exceeds
   a configurable budget (default: **512 tokens**, controlled by
   `kg.entity_description_token_budget`), an LLM summarization pass is triggered to
   condense the mentions into a single `current_summary` field.

3. **Top-K retention.** After summarization, the system retains the **top-K most
   informative mentions** (default K=5, configurable via
   `kg.entity_description_top_k_mentions`). Retention scoring favors:
   - **Recency** -- more recent mentions rank higher.
   - **Source diversity** -- mentions from distinct documents rank higher than
     repeated mentions from the same source.

4. **Dual storage.** Each entity node stores both:
   - `raw_mentions`: the retained top-K mention list (always available, even before
     the first summarization).
   - `current_summary`: the latest LLM-condensed description (empty until the token
     budget is first exceeded).

5. **Retrieval usage.** The `current_summary` field (when present) is used for
   retrieval grounding and Obsidian export. If no summary exists yet, the system
   concatenates `raw_mentions` text as a fallback.

---

## YAML Schema and GLiNER Label Derivation

The YAML schema (`config/kg_schema.yaml`) is the **single source of truth** for all
entity types across every extractor. This section specifies how GLiNER's required
label list is derived from the schema.

### Derivation rules

1. **Direct mapping.** At startup, the system reads `node_types` from the YAML schema
   and builds the GLiNER label list by collecting each type's `name` field.

2. **Optional `gliner_label` override.** Each node type in the YAML schema may include
   an optional `gliner_label` property. When present, this value is used as the
   GLiNER label instead of the type name. This accommodates cases where the
   GLiNER-friendly label differs from the canonical schema type name (e.g., a schema
   type `"finite_state_machine"` might set `gliner_label: "FSM"` for better GLiNER
   recall).

   Example YAML:
   ```yaml
   node_types:
     - name: module
       description: A hardware module definition
     - name: finite_state_machine
       description: An FSM defined in RTL
       gliner_label: FSM
     - name: register
       description: A configuration or status register
   ```

   Resulting GLiNER labels: `["module", "FSM", "register"]`

3. **Replaces hardcoded config.** This derivation replaces the current hardcoded
   `GLINER_ENTITY_LABELS` configuration list. Any downstream code referencing
   `GLINER_ENTITY_LABELS` should be updated to call the schema-driven label builder.

4. **Validation.** At startup, the system validates that every `gliner_label` override
   is unique across all node types and logs a warning if a `gliner_label` collides
   with another type's `name` (potential confusion source).

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **LLM extraction latency blows ingestion budget.** Structured output calls may take 2-5s per chunk. | High | Medium | Run LLM extractor in parallel with regex/parser; make it optional via config; set per-chunk timeout. |
| **Merge node produces duplicates or drops valid entities.** Overlapping entity spans from different extractors are hard to reconcile. | Medium | High | Start with conservative "union + alias dedup" strategy; add embedding similarity only as a tested upgrade. Log merge decisions for debugging. |
| **tree-sitter-verilog grammar gaps.** tree-sitter grammars may not cover all SystemVerilog constructs (e.g., UVM macros, generate blocks). | Medium | Medium | Run parser with `try/except`; fall through to LLM extractor for unparseable constructs. Maintain a known-unsupported-constructs list. |
| **YAML schema drift.** Schema becomes stale as domain evolves; extractors produce types not in schema. | Low | Medium | Schema validation runs at extraction time with `WARN` (not `DROP`) for unknown types in dev mode; strict in production. CI test validates schema against extractor output on sample corpus. |
| **spaCy model size.** Loading a spaCy model at retrieval startup adds memory and init time. | Low | Low | Use `en_core_web_sm` (12 MB) or rule-only `blank("en")` with custom patterns -- no transformer model needed. |
| **Backward-compatibility break.** Callers importing from `src/core/knowledge_graph` break after migration. | Low | High | Keep `src/core/knowledge_graph.py` as a thin shim that re-exports from `src/knowledge_graph/`. Emit deprecation warning. Remove after one release cycle. |
| **Graph size exceeds NetworkX memory.** Large ASIC projects with thousands of files could produce millions of nodes. | Low (Phase 1) | High (Phase 2) | Monitor node/edge counts in ingestion metrics. Neo4j backend (Phase 2) is the escape hatch. Set configurable max-nodes safety limit. |
| **LLM query fallback latency in retrieval hot path.** If spaCy finds no matches, LLM call adds 500ms-2s to retrieval. | Medium | Medium | Gate behind configurable timeout (default 1s); if LLM fallback times out, proceed without expansion. Track fallback rate in metrics. |
