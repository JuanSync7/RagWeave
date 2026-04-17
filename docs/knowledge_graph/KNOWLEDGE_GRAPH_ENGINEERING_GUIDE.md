# Knowledge Graph Subsystem — Engineering Guide

**System:** RagWeave Knowledge Graph Subsystem
**Date:** 2026-04-09
**Status:** Phase 1 complete, Phase 1b complete, Phase 2 complete, Phase 3 complete

---

## 1. Architecture Overview

The KG subsystem replaces the monolithic `src/core/knowledge_graph.py` with a modular package at `src/knowledge_graph/`. It mirrors the `src/guardrails/` ABC backend pattern: swappable backends behind a stable public API with lazy singleton dispatch.

### Package Layout

```
src/knowledge_graph/
├── __init__.py                  # Public API: get_graph_backend(), get_query_expander(), run_post_ingestion_steps()
├── backend.py                   # GraphStorageBackend ABC (13 abstract + 4 concrete methods)
├── common/
│   ├── schemas.py               # Entity, Triple, ExtractionResult, EntityDescription
│   ├── types.py                 # KGConfig (incl. Phase 3 fields), SchemaDefinition, load_schema()
│   ├── utils.py                 # normalize_alias, validate_type, derive_gliner_labels
│   └── description_manager.py   # Token-budgeted description accumulation
├── extraction/
│   ├── base.py                  # EntityExtractor protocol
│   ├── regex_extractor.py       # Migrated rule-based extractor (Phase 1)
│   ├── gliner_extractor.py      # Migrated GLiNER zero-shot NER (Phase 1)
│   ├── llm_extractor.py         # LLM structured output (Phase 1b)
│   ├── parser_extractor.py      # SV tree-sitter parser (Phase 1b)
│   ├── python_parser.py         # AST-based Python extractor (Phase 2)
│   ├── bash_parser.py           # Regex-based Bash extractor (Phase 2)
│   └── sv_connectivity.py       # Cross-module SV port connectivity via pyverilog (Phase 3)
├── resolution/                  # Entity resolution package (Phase 3)
│   ├── schemas.py               # MergeCandidate, ResolutionReport dataclasses
│   ├── resolver.py              # EntityResolver orchestrator (alias → embedding pipeline)
│   ├── alias_resolver.py        # YAML alias-table-based deterministic merging
│   └── embedding_resolver.py    # Cosine-similarity embedding-based fuzzy merging
├── query/
│   ├── entity_matcher.py        # spaCy PhraseMatcher + substring fallback
│   ├── expander.py              # GraphQueryExpander + connects_to depth boost (Phase 3)
│   └── sanitizer.py             # Query normalization, alias expansion
├── backends/
│   ├── networkx_backend.py      # NetworkX DiGraph implementation (incl. Phase 3 methods)
│   └── neo4j_backend.py         # Full Neo4j sync-driver implementation (incl. Phase 3 methods)
├── community/
│   ├── schemas.py               # CommunitySummary, CommunityDiff dataclasses (Phase 2)
│   ├── detector.py              # Leiden + hierarchical Leiden detection (Phase 2/3)
│   └── summarizer.py            # LLM-based community summarization (Phase 2)
└── export/
    ├── obsidian.py              # Obsidian markdown vault export
    └── sigma_export.py          # Interactive Sigma.js HTML visualization (Phase 3)
```

### External Files

- `config/kg_schema.yaml` — YAML schema defining all node/edge types with phase tags
- `config/settings.py` — Environment variable bindings (`RAG_KG_*`)
- `src/core/knowledge_graph.py` — Backward compatibility shim (DeprecationWarning)

---

## 2. Module-by-Module Guide

### `__init__.py` — Public API

The only import surface for callers. Provides:

- `get_graph_backend(config=None)` — Lazy singleton; constructs NetworkX backend, loads graph from disk if exists
- `get_query_expander(backend=None, config=None)` — Builds expander with matcher + sanitizer. In Phase 2, when `config.enable_global_retrieval=True`, also initializes `CommunityDetector` and `CommunitySummarizer` and injects them into the expander.
- `reset_singletons()` — For tests
- Re-exports: `GraphStorageBackend`, `GraphQueryExpander`, `Entity`, `Triple`, `ExtractionResult`, `EntityDescription`, `export_obsidian`

**Phase 2 wiring fix**: `_build_kg_config()` was corrected to construct `KGConfig` from env vars directly (the previously referenced `KGConfig.from_env()` class method did not exist). `Neo4jBackend` is now constructed as `Neo4jBackend(config=config)` instead of no-args.

### `backend.py` — ABC Contract

Defines `GraphStorageBackend` with two new Phase 3 dataclasses and two new abstract methods:

**New dataclasses:**
- **`RemovalStats`**: `entities_removed`, `entities_pruned`, `triples_removed`, `source_key` — returned by `remove_by_source()`
- **`MergeReport`**: `merges` (list of `(canonical, duplicate)` tuples), `triples_redirected`, `aliases_transferred` — for external reporting of merge operations

| Method | Abstract? | Purpose |
|--------|-----------|---------|
| `add_node(name, type, source, aliases)` | Yes | Upsert single entity |
| `add_edge(subject, object, relation, source)` | Yes | Upsert single edge |
| `upsert_entities(entities)` | Yes | Batch entity upsert |
| `upsert_triples(triples)` | Yes | Batch triple upsert |
| `upsert_descriptions(descriptions)` | Yes | Append entity mentions |
| `remove_by_source(source_key)` | Yes | Remove/prune all data for a source document (Phase 3) |
| `merge_entities(canonical, duplicate)` | Yes | Absorb duplicate into canonical, redirect all edges (Phase 3) |
| `query_neighbors(entity, depth)` | Yes | N-hop traversal |
| `get_entity(name)` | Yes | Lookup by name (case-insensitive) |
| `get_predecessors(entity)` | Yes | Incoming edges |
| `save(path)` / `load(path)` | Yes | Persistence |
| `stats()` | Yes | Node/edge counts |
| `get_all_entities()` | No | All entities (concrete default) |
| `get_all_node_names_and_aliases()` | No | Name→canonical index |
| `get_outgoing_edges(node_id)` | No | Returns `[]` by default |
| `get_incoming_edges(node_id)` | No | Returns `[]` by default |

**`remove_by_source` contract:** Entities whose `sources` list contains `source_key` as the sole source are deleted entirely. Entities appearing in other sources have `source_key` pruned from their list but the node survives (`entities_pruned`). All triples whose `source` matches `source_key` are removed unconditionally.

**`merge_entities` contract:** All edges referencing `duplicate` as subject or object are redirected to `canonical`. Aliases, mention counts, `raw_mentions`, and `sources` from `duplicate` are merged into `canonical`. The `duplicate` node is deleted. Self-loops that would result from the redirect are dropped silently.

### `common/schemas.py` — Data Contracts

- **`EntityDescription`**: `text`, `source`, `chunk_id` — one mention of an entity
- **`Entity`**: `name`, `type`, `sources`, `mention_count`, `aliases`, `raw_mentions`, `current_summary`, `extractor_source`
- **`Triple`**: `subject`, `predicate`, `object`, `source`, `weight`, `extractor_source`
- **`ExtractionResult`**: `entities`, `triples`, `descriptions` — output of any extractor

### `common/types.py` — Configuration

- **`KGConfig`**: All config fields (constructed by `_build_kg_config()` in `__init__.py`)
- **`SchemaDefinition`**: Parsed YAML schema with `active_node_types(phase)` and `active_edge_types(phase)` query methods
- **`load_schema(path)`**: YAML loader with 5 validation rules (duplicate names, invalid category, invalid phase, duplicate gliner_labels, cross-name collision)

### `common/utils.py` — Helpers

- `normalize_alias(term, aliases, case_index)` — Acronym expansion + case dedup
- `validate_type(entity_type, schema, runtime_phase)` — Schema membership check
- `derive_gliner_labels(schema, runtime_phase)` — GLiNER label list from active schema types
- `is_phase_active(type_phase, runtime_phase)` — Phase ordering: `phase_1 < phase_1b < phase_2`

### `common/description_manager.py` — Description Accumulation

- `add_mention(raw_mentions, text, source, chunk_id)` — Append with dedup, trim to budget
- `build_summary(raw_mentions)` — Concatenate with source attribution
- `get_retrieval_text(current_summary, raw_mentions)` — Best text for retrieval context
- Token budget defaults to 512 words (configurable via `RAG_KG_DESCRIPTION_TOKEN_BUDGET`)

### `extraction/` — Entity Extractors

All extractors implement `extract(text, source) -> ExtractionResult`.

- **`RegexEntityExtractor`**: Migrated from monolith. CamelCase, acronym, multi-word patterns + 7 relation patterns. No dependencies.
- **`GLiNEREntityExtractor`**: Zero-shot NER with YAML-schema-driven labels. Falls back to regex if GLiNER unavailable.
- **`LLMEntityExtractor`**: Schema-guided LLM structured JSON extraction via LiteLLM. Injects active YAML schema types into prompt, validates output, retries on malformed JSON. Key value-add: extracts entity descriptions (the LightRAG pattern).
- **`SVParserExtractor`**: Deterministic tree-sitter-verilog AST extraction. Extracts modules, ports, parameters, instances, signals, interfaces, packages. Derives structural relationships (contains, instantiates, depends_on). Handles syntax errors gracefully.

### `query/` — Query Processing

- **`EntityMatcher`**: spaCy `PhraseMatcher` (Tier 1, token-boundary aware) with substring fallback. LLM fallback (Tier 2): when primary matching returns empty and `enable_llm_query_fallback=true`, sends query + entity names grouped by type to LLM, filters response to canonical names.
- **`GraphQueryExpander`**: Matches entities → fans out N hops → returns expansion terms. Uses `EntityMatcher` + `QuerySanitizer`. Same class name as legacy for easy migration. Phase 2 addition: accepts optional `community_detector` and `enable_global_retrieval` constructor parameters. When global retrieval is enabled, community-derived terms fill remaining slots after local graph expansion. `get_context_summary()` includes community summary text when available. Fully backward-compatible — no change required for existing callers.
- **`QuerySanitizer`**: Lowercase + normalize whitespace + alias expansion. `sanitize_cypher()` is a stub for future Cypher sanitization.

### `backends/networkx_backend.py` — NetworkX Implementation

Full implementation of `GraphStorageBackend` using `nx.DiGraph`. Features:
- Entity resolution via `_resolve()` (alias + case-insensitive dedup)
- Edge weight accumulation on repeated mentions
- Entity description accumulation with token budget
- `orjson` + `node_link_data` serialization (backward-compatible with legacy format)
- Overrides all 4 concrete defaults for efficiency

### `backends/neo4j_backend.py` — Neo4j Implementation (Phase 2)

Full `GraphStorageBackend` implementation using the official `neo4j` sync driver (~810 LOC).

Key design points:
- **MERGE-based entity resolution**: All entity upserts use `MERGE` on `name_lower` (lowercased canonical name) to ensure case-insensitive deduplication without loading the graph into memory.
- **UNWIND bulk operations**: `upsert_entities()` and `upsert_triples()` send batches via `UNWIND` to minimise round trips.
- **Index creation on init**: Creates indexes on `Entity.name_lower`, `Entity.name`, and `Community.community_id` during `__init__` using `CREATE INDEX IF NOT EXISTS`.
- **JSON interop**: `save(path)` exports to the same NetworkX `node_link_data` JSON format; `load(path)` imports it back. This allows seamless migration between NetworkX and Neo4j backends.
- **Community persistence**: `upsert_community(community_id, member_names)` creates `Community` nodes and `BELONGS_TO` edges from member entities.
- **Constructor**: `Neo4jBackend(config=config)` — reads `neo4j_uri`, `neo4j_auth_user`, `neo4j_auth_password` from `KGConfig`.

### `community/schemas.py` — Community Data Contracts (Phase 2)

Defines typed dataclasses shared by detector and summarizer:

- **`CommunitySummary`**: `community_id` (int), `summary_text` (str), `member_count` (int), `member_names` (list[str]), `generated_at` (datetime)
- **`CommunityDiff`**: `new` (set[int]), `removed` (set[int]), `changed` (set[int]), `unchanged` (set[int]) — community IDs partitioned by change type between two runs

### `community/detector.py` — Community Detection (Phase 2)

`CommunityDetector(backend, config, graph_path)` runs Leiden community detection via `igraph` + `leidenalg`.

| Method / Property | Purpose |
|-------------------|---------|
| `detect()` | Run Leiden, return `{community_id: [entity_names]}` |
| `get_community_for_entity(name)` | Look up which community an entity belongs to |
| `get_summary()` | Return community size distribution stats |
| `is_ready` | Lifecycle property — True once `detect()` has run successfully |
| `diff(previous)` | Compute `CommunityDiff` against a prior detection result |

Behavior notes:
- Communities smaller than `config.community_min_size` (default 3) are merged into bucket `-1` (noise).
- Results are persisted as a sidecar JSON file at `<graph_path>.communities.json` so they survive process restarts.
- If `igraph` or `leidenalg` is not installed, `detect()` raises `ImportError` with a clear install hint; `is_ready` stays False.
- `community_resolution` (Leiden resolution parameter, default 1.0) controls cluster granularity — higher values produce more, smaller communities.

### `community/summarizer.py` — Community Summarization (Phase 2)

`CommunitySummarizer(config, llm_provider)` generates natural-language summaries for each community using an LLM.

| Method | Purpose |
|--------|---------|
| `summarize_all(communities)` | Summarize all communities; returns `{community_id: CommunitySummary}` |
| `refresh(diff, communities, existing)` | Re-summarize only new/changed communities; preserve unchanged |

Implementation details:
- Uses `ThreadPoolExecutor` for parallel LLM calls (degree of parallelism controlled by `config.community_summary_max_workers`, default 4).
- Input token budget: 4096 tokens (truncates member entity list if exceeded).
- Output token budget: 512 tokens.
- Empty or noise bucket `-1` communities are skipped automatically.

### `extraction/python_parser.py` — Python AST Extractor (Phase 2)

`PythonParserExtractor` uses the stdlib `ast` module to extract code entities from Python source.

Extracted entity types (mapped to Phase 2 YAML schema):
- `PythonClass` — class definitions with base classes
- `PythonFunction` — top-level and method definitions
- `PythonImport` — `import` and `from ... import` statements
- `PythonVariable` — module-level constants and assignments

Derived relationships: `contains` (module→class, class→method), `depends_on` (module→import), `defines` (module→constant).

Returns the standard `ExtractionResult` interface — drop-in compatible with all other extractors.

### `extraction/bash_parser.py` — Bash Regex Extractor (Phase 2)

`BashParserExtractor` uses regex patterns to extract entities from Bash/shell scripts (no external parser dependency).

Extracted entity types:
- `BashFunction` — `function foo()` and `foo()` style declarations
- `BashScript` — sourced scripts via `. file` or `source file`
- `BashVariable` — `export VAR=value` exported variables

Derived relationships: `sources` (script→sourced script), `exports` (script→variable), `defines` (script→function).

Returns the standard `ExtractionResult` interface.

### `extraction/sv_connectivity.py` — SV Port Connectivity (Phase 3)

`SVConnectivityAnalyzer(filelist_path, backend, top_module=None)` uses pyverilog's `DataflowAnalyzer` to resolve cross-module port connections and produce `connects_to` triples.

Key design points:
- **Triples only**: produces no entity upserts — entity nodes are created by the per-file tree-sitter parser. This prevents duplication.
- **Synthetic source key**: all pyverilog-generated triples use `SV_CONNECTIVITY_SOURCE = "__sv_connectivity_batch__"` as their source, enabling clean removal via `remove_by_source()` on incremental re-runs.
- **`.f` filelist parser**: `parse_filelist()` supports one path per line, `// ` line comments, `+incdir+<path>` include directives, and `-f <path>` recursive filelist inclusion. Relative paths are resolved from the filelist's parent directory. Circular references are detected and skipped.
- **Top module auto-detection**: if `top_module` is not set, scans `RTL_Module` entities in the graph and finds those never targeted by an `instantiates` edge. Falls back to the first alphabetical candidate when multiple tops are found.
- **Graceful degradation**: if pyverilog is not installed, `analyze()` logs a warning and returns `[]`. If the filelist is missing or pyverilog analysis throws, returns `[]` without propagating the exception.

`analyze()` returns a `List[Triple]` with predicate `"connects_to"`. Callers upsert these via `backend.upsert_triples()`.

Install dependency: `pip install pyverilog` (already in `pyproject.toml` core dependencies).

### `resolution/` — Entity Resolution Package (Phase 3)

#### `resolution/schemas.py`

Typed dataclasses for resolution operations:
- **`MergeCandidate`**: `canonical` (str), `duplicate` (str), `similarity` (float), `reason` (str)
- **`ResolutionReport`**: `merges` (list of `MergeCandidate`), `total_merged` (int)

#### `resolution/resolver.py` — Orchestrator

`EntityResolver(backend, config, embed_fn=None)` runs the two-stage pipeline:

1. **Alias merges** (deterministic): `AliasResolver.find_candidates()` → `backend.merge_entities()` for each match
2. **Embedding merges** (fuzzy): `EmbeddingResolver.find_candidates()` → `backend.merge_entities()` for each match above threshold

Controlled by `config.enable_entity_resolution` (default `False`). When disabled, `resolve()` returns an empty `ResolutionReport` without touching the graph.

Optional `embed_fn` parameter: a `Callable[[List[str]], List[List[float]]]` injected for testing or custom models. If omitted, `EmbeddingResolver` lazy-loads from `EMBEDDING_MODEL_PATH` / `RAG_EMBEDDING_MODEL`.

#### `resolution/alias_resolver.py`

`AliasResolver(alias_path="config/kg_aliases.yaml")` loads a YAML alias table of the form:

```yaml
aliases:
  - canonical: "AXI4_Arbiter"
    variants:
      - "axi4_arb"
      - "AXI_ARB"
```

Matching is case-insensitive. Returns `MergeCandidate` objects with `similarity=1.0` and `reason="alias_table"`. If the alias file is absent, operates with an empty table (no merges, no error).

#### `resolution/embedding_resolver.py`

`EmbeddingResolver(threshold=0.85, embed_fn=None)` groups all entities by type, computes pairwise cosine similarity within each type bucket, and returns pairs above `threshold` as merge candidates. Canonical is chosen as the entity with the higher `mention_count`. Already-merged duplicates are skipped.

Type-constrained: entities of different types are never compared, preventing cross-type false merges.

Requires `numpy` and either an injected `embed_fn` or `sentence-transformers` installed with `EMBEDDING_MODEL_PATH` set. If neither is available, returns `[]` with a warning log.

### `export/sigma_export.py` — Interactive HTML Visualization (Phase 3)

`export_html(backend, output_path, community_detector=None) -> int` generates a single self-contained HTML file with Sigma.js v3 + graphology loaded from CDN — no pip dependency required.

Features:
- **ForceAtlas2 layout**: run for 100 iterations at export time, positions embedded in the output file.
- **Node sizing**: proportional to `mention_count` (clamped 3–20).
- **Node coloring**: by entity type (deterministic MD5-based palette), overridden by community color when a `CommunityDetector` is provided and `is_ready=True`.
- **Edge styling**: predefined styles per predicate — `connects_to` (red dashed), `contains` (grey solid), `instantiates` (blue solid), `depends_on` (green solid), `specified_by` (purple dotted). Unknown predicates use a default grey.
- **Interactive features**: entity search (hides non-matching nodes), hover tooltip showing type/mentions/sources, node/edge count info panel, and a type-color legend.
- **Community coloring**: if a `CommunityDetector` is passed and ready, node colors reflect community membership instead of type.

Returns the count of nodes rendered. The output file is written atomically via `Path.write_text`.

### `community/detector.py` — Hierarchical Leiden (Phase 3 additions)

The `CommunityDetector` gained hierarchical Leiden support in Phase 3:

| Method / Property | Purpose |
|-------------------|---------|
| `detect_hierarchical()` | Recursive sub-partitioning up to `config.community_max_levels` levels |
| `hierarchy` | `{(level, community_id): [entity_names]}` after hierarchical detection |
| `parent_map` | `{(level, cid): (level-1, parent_cid)}` — parent community for each partition |
| `hierarchy_summaries` | Per-level `CommunitySummary` objects (settable) |

**`detect_hierarchical()` algorithm:**
1. Run flat `detect()` to produce level-0 communities.
2. For each subsequent level up to `community_max_levels`, take communities from the previous level that have at least `community_min_size * 2` members.
3. Build an igraph subgraph for each such community and re-run Leiden.
4. Keep sub-partitions only when they produce at least 2 real communities (non-noise). Stop early if no level produces any splits.
5. Assign unique `(level, composite_id)` keys where composite IDs are offset by `parent_cid * 1000` to avoid collisions.

Level 0 is the coarsest (fewest, largest communities). Hierarchical summaries can be generated by calling `CommunitySummarizer` on each level's communities separately.

### `__init__.py` — Phase 3 additions

Phase 3 adds:
- **`run_post_ingestion_steps(backend, config, update_mode=False)`**: executes the three-step post-ingestion batch in fixed order (see Section 4 — Post-Ingestion Pipeline).
- **`export_html`**: re-exported from `export/sigma_export.py`.
- Phase 3 config loading: reads `RAG_KG_SV_FILELIST`, `RAG_KG_SV_TOP_MODULE`, `RAG_KG_ENABLE_ENTITY_RESOLUTION`, `RAG_KG_ENTITY_RESOLUTION_THRESHOLD`, `RAG_KG_ENTITY_RESOLUTION_ALIAS_PATH`, `RAG_KG_COMMUNITY_MAX_LEVELS` from `config.settings`.

### `query/expander.py` — Phase 3 additions

Phase 3 adds automatic depth boosting for `connects_to` edges. When the configured depth is less than 2 and a seed entity has outgoing `connects_to` edges, `expand()` silently increases `effective_depth` to 2 for that query. This ensures SV port connectivity chains (signal → signal → signal) are traversed without requiring callers to manually set a higher depth.

---

## 3. Configuration

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `RAG_KG_ENABLED` | `true` | Enable/disable KG subsystem |
| `RAG_KG_SCHEMA_PATH` | `config/kg_schema.yaml` | YAML schema file path |
| `RAG_KG_GRAPH_PATH` | `.knowledge_graph.json` | Graph persistence path |
| `RAG_KG_OBSIDIAN_EXPORT_DIR` | `obsidian_graph` | Obsidian export directory |
| `RAG_KG_RUNTIME_PHASE` | `phase_1` | Active phase (phase_1/phase_1b/phase_2) |
| `RAG_GLINER_ENABLED` | `false` | Use GLiNER for extraction |
| `RAG_KG_MAX_EXPANSION_DEPTH` | `1` | Max graph traversal hops |
| `RAG_KG_MAX_EXPANSION_TERMS` | `3` | Max expansion terms for BM25 |
| `RAG_KG_DESCRIPTION_TOKEN_BUDGET` | `512` | Max words per entity description |
| `RAG_STAGE_BUDGET_KG_EXPANSION_MS` | `1000` | Query expansion time budget |

#### Phase 2 Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `RAG_KG_BACKEND` | `networkx` | Storage backend: `networkx` or `neo4j` |
| `RAG_KG_NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt connection URI |
| `RAG_KG_NEO4J_AUTH_USER` | `neo4j` | Neo4j username |
| `RAG_KG_NEO4J_AUTH_PASSWORD` | _(required)_ | Neo4j password |
| `RAG_KG_NEO4J_DATABASE` | `neo4j` | Neo4j database name |
| `RAG_KG_ENABLE_GLOBAL_RETRIEVAL` | `false` | Enable community detection, summarization, and global retrieval |
| `RAG_KG_COMMUNITY_RESOLUTION` | `1.0` | Leiden resolution parameter (higher = more, smaller communities) |
| `RAG_KG_COMMUNITY_MIN_SIZE` | `3` | Minimum members; smaller communities go to bucket -1 |
| `RAG_KG_COMMUNITY_SUMMARY_INPUT_MAX_TOKENS` | `4096` | Token budget for entity descriptions in LLM prompt |
| `RAG_KG_COMMUNITY_SUMMARY_OUTPUT_MAX_TOKENS` | `512` | Max tokens for LLM summary generation |
| `RAG_KG_COMMUNITY_SUMMARY_TEMPERATURE` | `0.2` | LLM temperature for community summarization |
| `RAG_KG_COMMUNITY_SUMMARY_MAX_WORKERS` | `4` | ThreadPoolExecutor parallelism for summarization |
| `RAG_KG_ENABLE_PYTHON_PARSER` | `false` | Enable Python AST extractor for .py sources |
| `RAG_KG_ENABLE_BASH_PARSER` | `false` | Enable Bash regex extractor for .sh sources |

#### Phase 3 Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `RAG_KG_SV_FILELIST` | `""` | Path to a `.f` filelist for pyverilog cross-module connectivity analysis |
| `RAG_KG_SV_TOP_MODULE` | `""` | Top-level SV module name for pyverilog; auto-detected from graph if empty |
| `RAG_KG_ENABLE_ENTITY_RESOLUTION` | `false` | Enable post-ingestion entity deduplication (alias + embedding) |
| `RAG_KG_ENTITY_RESOLUTION_THRESHOLD` | `0.85` | Cosine similarity cutoff for embedding-based entity merging |
| `RAG_KG_ENTITY_RESOLUTION_ALIAS_PATH` | `config/kg_aliases.yaml` | Path to YAML alias table for deterministic entity merging |
| `RAG_KG_COMMUNITY_MAX_LEVELS` | `3` | Maximum recursion depth for hierarchical Leiden community detection |

### YAML Schema (`config/kg_schema.yaml`)

Defines all node and edge types with phase tags. Each type has:
- `description` — Human-readable purpose
- `category` — `structural` or `semantic`
- `extraction` — `parser`, `llm`, `regex`, or `both`
- `phase` — `phase_1`, `phase_1b`, or `phase_2`
- `properties` — Field names for this type
- `gliner_label` — Optional GLiNER label override

---

## 4. Data Flow

### Ingestion Path

```
Document chunks
    → Node 10 (knowledge_graph_extraction_node)
        → RegexEntityExtractor.extract() or GLiNEREntityExtractor.extract()
        → ExtractionResult (entities + triples)
        → Stored as kg_triples in pipeline state (legacy dict format)
    → Node 13 (knowledge_graph_storage_node)
        → get_graph_backend() → NetworkXBackend
        → backend.upsert_entities() + upsert_triples() + upsert_descriptions()
        → Graph persisted to .knowledge_graph.json
```

### Retrieval Path (Local Expansion)

```
User query
    → get_query_expander() → GraphQueryExpander
    → EntityMatcher.match(query) — spaCy or substring
    → GraphQueryExpander.expand(query, depth=1)
        → backend.query_neighbors() + get_predecessors()
        → Filter terms already in query
        → Cap at max_expansion_terms
    → BM25 query augmented with top expansion terms
```

### Community Detection Flow (Phase 2)

```
Post-ingestion (after backend.upsert_entities / upsert_triples)
    → CommunityDetector.detect()
        → Pull all entities + edges from backend
        → Build igraph.Graph
        → Run leidenalg.find_partition() with CPMVertexPartition
        → Filter communities below community_min_size → bucket -1
        → Persist sidecar JSON: <graph_path>.communities.json
        → Return {community_id: [entity_names]}
    → CommunitySummarizer.summarize_all(communities)  [if enabled]
        → ThreadPoolExecutor: parallel LLM calls per community
        → Each call: member list → LLM → summary_text
        → Return {community_id: CommunitySummary}
    → Neo4jBackend.upsert_community()  [if neo4j backend]
        → MERGE Community nodes + BELONGS_TO edges
```

### Global Retrieval Flow (Phase 2)

```
User query  [when enable_global_retrieval=True]
    → GraphQueryExpander.expand(query, depth=1)
        → [Local expansion as above — fills up to max_expansion_terms]
        → If slots remain after local expansion:
            → CommunityDetector.get_community_for_entity(matched_entity)
            → Fetch sibling entity names from that community
            → Append community summary text to context
            → Fill remaining slots with community-derived terms
    → BM25 query augmented with local + community terms
    → get_context_summary() includes community summary text
```

### Post-Ingestion Pipeline (Phase 3)

`run_post_ingestion_steps(backend, config, update_mode=False)` executes three steps in fixed order after all document chunks have been ingested:

```
run_post_ingestion_steps()
    Step 1: SV connectivity  [if config.sv_filelist is set]
        → If update_mode:
            backend.remove_by_source(SV_CONNECTIVITY_SOURCE)  # clean previous batch
        → SVConnectivityAnalyzer(filelist_path, backend, top_module).analyze()
            → pyverilog DataflowAnalyzer → connects_to triples
        → backend.upsert_triples(triples)

    Step 2: Entity resolution  [if config.enable_entity_resolution]
        → EntityResolver(backend, config).resolve()
            → AliasResolver.find_candidates() → backend.merge_entities() per candidate
            → EmbeddingResolver.find_candidates() → backend.merge_entities() per candidate
        → Logs total entities merged

    Step 3: Community detection  [if config.enable_global_retrieval]
        → CommunityDetector(backend, config, graph_path)
        → If config.community_max_levels > 1:
            detector.detect_hierarchical()
        → Else:
            detector.detect()
        → CommunitySummarizer.summarize_all(communities, backend)
        → detector.summaries = summaries
        → detector.save_sidecar()  # atomic write to <graph_path>.communities.json
```

The ordering is load-bearing: SV connectivity must run before entity resolution (so that `connects_to` triples reference real entity names), and entity resolution must run before community detection (so that merged entities are not split across communities).

**Incremental re-runs**: set `update_mode=True` to remove and re-generate SV connectivity triples before re-running the analysis. Entity resolution and community detection always operate on the current full graph state.

---

## 5. Integration Points

### Ingest Pipeline

- **Node 10**: `src/ingest/embedding/nodes/knowledge_graph_extraction.py` — imports from `src.knowledge_graph.extraction`
- **Node 13**: `src/ingest/embedding/nodes/knowledge_graph_storage.py` — uses `get_graph_backend()` with legacy fallback

### Retrieval Pipeline

- **Stage 2**: `src/retrieval/pipeline/rag_chain.py` — calls `get_query_expander()` during init, uses `expander.expand()` at query time

### Backward Compatibility

- `src/core/knowledge_graph.py` — Shim with `DeprecationWarning`. Re-exports `KnowledgeGraphBuilder`, `EntityExtractor`, `GraphQueryExpander`, `GLiNEREntityExtractor`, `export_obsidian` under their old names.

---

## 6. Extension Guide

### Adding a New Entity Type

1. Add the type to `config/kg_schema.yaml` under `node_types.structural` or `node_types.semantic`
2. Set `phase` to the appropriate phase
3. If it needs a custom GLiNER label, set `gliner_label`
4. Run `load_schema()` validation — it will catch duplicates and invalid phases

### Adding a New Extractor

1. Create `src/knowledge_graph/extraction/my_extractor.py`
2. Implement the `EntityExtractor` protocol from `extraction/base.py`:
   - `name` property
   - `extract_entities(text) -> Set[str]`
   - `extract_relations(text, known_entities) -> List[Triple]`
3. Add an `extract(text, source) -> ExtractionResult` convenience method
4. Register in the extraction node (Node 10) — add config flag to select it

### Adding a New Backend

1. Create `src/knowledge_graph/backends/my_backend.py`
2. Subclass `GraphStorageBackend` from `backend.py`
3. Implement all 11 abstract methods (see ABC contract table in Section 2)
4. Override the 4 concrete defaults (`get_all_entities`, `get_all_node_names_and_aliases`, `get_outgoing_edges`, `get_incoming_edges`) for efficiency
5. If the backend supports community storage, implement `upsert_community(community_id, member_names)` (not part of the ABC — community detection calls it conditionally via `hasattr`)
6. Add the backend name to the dispatcher in `__init__.py` and wire the config key via `RAG_KG_BACKEND`

Reference implementation: `backends/neo4j_backend.py` (Phase 2) shows bulk UNWIND patterns, index management, and JSON interop.

### Adding a New Parser Extractor

1. Create `src/knowledge_graph/extraction/my_parser.py`
2. Implement a class with `extract(text, source) -> ExtractionResult` (same protocol as all other extractors)
3. Use `common/schemas.py` types: build `Entity` objects and `Triple` objects, return them in an `ExtractionResult`
4. Add corresponding node types to `config/kg_schema.yaml` with the appropriate `phase` tag and `extraction: parser`
5. Add a config flag to `KGConfig` (e.g. `my_parser_enabled: bool = False`) and the matching env var entry in `config/settings.py`
6. Register the extractor in the extraction node (Node 10) — guard with the config flag

Reference implementations: `extraction/python_parser.py` (AST-based) and `extraction/bash_parser.py` (regex-based).

---

## 7. Migration Notes

### From `src/core/knowledge_graph.py`

| Old Import | New Import |
|------------|-----------|
| `from src.core.knowledge_graph import KnowledgeGraphBuilder` | `from src.knowledge_graph import get_graph_backend` |
| `from src.core.knowledge_graph import GraphQueryExpander` | `from src.knowledge_graph import get_query_expander` |
| `from src.core.knowledge_graph import EntityExtractor` | `from src.knowledge_graph.extraction import RegexEntityExtractor` |
| `from src.core.knowledge_graph import export_obsidian` | `from src.knowledge_graph import export_obsidian` |
| `builder = KnowledgeGraphBuilder.load(path)` | `backend = get_graph_backend()` (auto-loads) |
| `expander = GraphQueryExpander(builder.graph)` | `expander = get_query_expander()` |

The shim in `src/core/knowledge_graph.py` preserves old imports with a `DeprecationWarning`. Update imports at your convenience.

---

## 8. Troubleshooting

### "spaCy not available" warning
The `EntityMatcher` falls back to substring matching. Install spaCy with `pip install spacy` for token-boundary-aware matching. No model download needed — uses `spacy.blank("en")`.

### Graph file not loading
Check `RAG_KG_GRAPH_PATH` points to a valid JSON file. The format is NetworkX `node_link_data` with `orjson`. The new backend reads the same format as the legacy `KnowledgeGraphBuilder`.

### DeprecationWarning on import
Update imports from `src.core.knowledge_graph` to `src.knowledge_graph`. See migration table above.

### GLiNER labels empty
Ensure `config/kg_schema.yaml` has node types with `phase` matching `RAG_KG_RUNTIME_PHASE`. Phase 1 activates 7 structural + 17 semantic types by default.

### Entity descriptions growing too large
Adjust `RAG_KG_DESCRIPTION_TOKEN_BUDGET` (default 512 words). The `DescriptionManager` trims oldest mentions when the budget is exceeded.

### "igraph / leidenalg not available" error (Phase 2)
Community detection requires both `igraph` and `leidenalg`. Install them with:
```
pip install igraph leidenalg
```
If these packages are unavailable, `CommunityDetector.detect()` raises `ImportError` with a clear message and `is_ready` remains False. Community-dependent features (summarization, global retrieval) are silently skipped when `is_ready` is False — the rest of the pipeline continues unaffected.

### Neo4j connection refused (Phase 2)
Check that:
1. Neo4j is running and reachable at `RAG_KG_NEO4J_URI` (default `bolt://localhost:7687`)
2. `RAG_KG_NEO4J_AUTH_USER` and `RAG_KG_NEO4J_AUTH_PASSWORD` are set correctly
3. The Neo4j Bolt port (7687) is open in any firewall/Docker network rules
4. The `neo4j` Python driver is installed: `pip install neo4j`

On first connection, the backend creates indexes. If index creation fails (e.g. insufficient permissions), the backend will raise at init time — check Neo4j user roles.

### Community detection returns only bucket -1 (Phase 2)
All entities are being merged into the noise bucket. This happens when:
- The graph has fewer entities than `community_min_size` (default 3) — community detection requires a minimum connected structure
- The graph has many isolated nodes with no edges — Leiden treats disconnected nodes as size-1 communities, which fall below the min-size threshold
- `community_resolution` is set very high, over-fragmenting clusters

Try lowering `RAG_KG_COMMUNITY_MIN_SIZE` to `1` or reducing `RAG_KG_COMMUNITY_RESOLUTION`. Ensure the graph has been populated with triples (edges) before running detection.

### Community summaries not updating after re-ingestion (Phase 2)
`CommunitySummarizer.summarize_all()` generates summaries for all communities. For incremental re-runs, use `refresh(diff, communities, existing)` — it re-summarizes only `new` and `changed` communities from the `CommunityDiff`, preserving `unchanged` summaries. The `CommunityDetector` sidecar JSON (`<graph_path>.communities.json`) must exist for diff computation.

### pyverilog not installed or no connects_to triples produced (Phase 3)
If `pyverilog` is missing, `SVConnectivityAnalyzer.analyze()` logs a warning and returns an empty list. Install it with `pip install pyverilog` (included in `pyproject.toml` core dependencies). If `analyze()` returns `[]` with pyverilog installed, check:
1. `RAG_KG_SV_FILELIST` points to an existing `.f` filelist file.
2. The filelist contains valid absolute or relative paths to `.sv`/`.v` files.
3. `RAG_KG_SV_TOP_MODULE` is set (or the graph has `RTL_Module` entities for auto-detection).
4. The pyverilog `DataflowAnalyzer` may fail on elaboration errors — check logs for `DataflowAnalyzer failed for top=` warnings.

### Entity resolution merging wrong entities (Phase 3)
If embedding-based resolution merges entities that should be distinct:
- Lower `RAG_KG_ENTITY_RESOLUTION_THRESHOLD` (default `0.85`) is already high — raising it will reduce false positives.
- The resolver is type-constrained: entities of different types are never compared. If two distinct entities share a type and similar names, add the correct canonical/variant pair to `config/kg_aliases.yaml` with the wrong one explicitly mapped — alias matches run first and take precedence.
- Inspect the `ResolutionReport.merges` list returned by `EntityResolver.resolve()` to audit what was merged.

### No entities to merge after alias table update (Phase 3)
The `AliasResolver` only creates merge candidates when **both** the canonical name and the variant name exist as separate entity nodes in the graph. If one or both are absent (e.g. the canonical was already merged away), no candidate is produced. Verify entity names with `backend.get_entity(name)` before adding aliases.

### Hierarchical Leiden produces only level 0 (Phase 3)
`detect_hierarchical()` skips sub-partitioning for any community with fewer than `community_min_size * 2` members. If all communities are small (e.g. `community_min_size=3` and all communities have 5 members), the second level is never created. Lower `RAG_KG_COMMUNITY_MIN_SIZE` or ingest more documents to build a larger graph. Also check that `RAG_KG_COMMUNITY_MAX_LEVELS` is greater than `1`.

### Sigma.js HTML export shows no nodes (Phase 3)
`export_html()` calls `backend.get_all_entities()` and `backend.get_outgoing_edges()`. If the graph is empty (backend not loaded from disk), the output will contain zero nodes. Ensure `get_graph_backend()` has been called and the graph file at `RAG_KG_GRAPH_PATH` is present before exporting. If nodes appear but no edges, verify that `get_outgoing_edges()` is overridden in the backend (NetworkX and Neo4j both override it; the default ABC returns `[]`).

### SV connectivity triples persist after removing a source file (Phase 3)
SV connectivity triples use the synthetic source key `"__sv_connectivity_batch__"` rather than individual file paths. To remove them, call `backend.remove_by_source("__sv_connectivity_batch__")` directly, or run `run_post_ingestion_steps(update_mode=True)` which does this automatically before re-running the analyzer.
