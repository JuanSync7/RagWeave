# Knowledge Graph Phase 2 — Design Sketch

**Date:** 2026-04-08
**Status:** Approved (post-revision)
**Scope:** REQ-KG-700, REQ-KG-701, REQ-KG-702, REQ-KG-703, REQ-KG-609, REQ-KG-505, REQ-KG-313

> **Note on REQ-KG-703 (community stubs):** The stubs in `community/detector.py` were delivered in Phase 1 as forward declarations. Phase 2 replaces them with full implementations. REQ-KG-703 is satisfied by Phase 1 delivery; Phase 2 supersedes the stubs.

---

## Goal

Extend the KG subsystem from local entity-neighbour retrieval to **community-aware global retrieval**: detect thematic clusters via Leiden, generate LLM summaries per cluster, and surface those summaries during query expansion. Simultaneously deliver the Neo4j backend and optional Python/Bash parsers.

---

## 1. Community Detection (REQ-KG-700)

### Approaches Considered

| # | Approach | Description |
|---|----------|-------------|
| A | **python-igraph + leidenalg** | Convert NetworkX graph to igraph, run `leidenalg.find_partition()`, map results back. Dedicated C++ Leiden implementation. |
| B | **cdlib (Community Discovery Library)** | Higher-level wrapper supporting 50+ algorithms. Uses igraph/leidenalg under the hood for Leiden. |
| C | **graspologic (Microsoft)** | Leiden via `graspologic.partition.leiden()`. NetworkX-native API, no igraph conversion needed. |

### Chosen: A — python-igraph + leidenalg

**Rationale:**
- Direct control over resolution parameter and partition quality metric (modularity vs. CPM).
- leidenalg is the canonical Leiden implementation by the algorithm's authors (Traag et al.).
- igraph conversion is a one-time O(V+E) operation; the conversion cost is negligible compared to the algorithm itself.
- cdlib adds a large transitive dependency surface for one algorithm. graspologic's Leiden is a thin wrapper over igraph anyway but pulls in the full graspologic stack (sklearn, scipy, etc.).

**Key decisions:**
- **Resolution parameter**: Expose as `KGConfig.community_resolution: float = 1.0`. Higher values produce more, smaller communities. Default 1.0 matches standard modularity.
- **Partition type**: Use `RBConfigurationVertexPartition` (modularity with resolution) as default; allow config override to `CPMVertexPartition` for constant Potts model.
- **Directed → undirected**: Leiden operates on undirected graphs. Convert the DiGraph to undirected before detection, preserving max edge weight on collapsed edges. This is standard practice (GraphRAG, LightRAG).
- **Storage format**: Store `community_id: int` as a node attribute on each entity. Store community metadata (member count, summary) in a separate dict on `CommunityDetector`, not on individual nodes, to avoid polluting the entity data model.
- **Persistence**: Community assignments survive graph save/load because `community_id` is stored as a node attribute on the backend (serialized with `node_link_data` for NetworkX, persisted server-side for Neo4j). Community summaries and `_previous_assignments` (used by incremental refresh) are persisted to a sidecar JSON file (`<graph_path>.communities.json`) alongside the graph file. On `CommunityDetector.__init__`, if the sidecar exists, it is loaded to restore summaries and previous assignments. This ensures full persistence across process restarts.
- **Minimum community size**: Communities with < 3 entities are merged into a "miscellaneous" bucket (community_id = -1) to avoid summarizing trivially small clusters.

**Devil's advocate on rejected alternatives:**
- **cdlib**: Genuinely useful if we anticipated switching algorithms frequently. We don't — Leiden is the target algorithm per spec. The abstraction layer adds indirection without payoff. If we ever need Louvain/Infomap, a one-function swap in detector.py is simpler than a framework.
- **graspologic**: Attractive NetworkX-native API, but the package is 100+ MB installed with mandatory sklearn/scipy. Our pipeline already has igraph as an optional dep path, making it the lighter choice. graspologic's Leiden also lags behind leidenalg releases.

### Component: `src/knowledge_graph/community/detector.py`
- `CommunityDetector.__init__(backend, config)` — accepts backend + KGConfig
- `detect() -> Dict[int, List[str]]` — runs Leiden, returns `{community_id: [entity_names]}`
- `get_community_for_entity(name) -> Optional[int]` — lookup
- `get_community_members(community_id) -> List[str]` — reverse lookup
- Internal: `_to_igraph()`, `_run_leiden()`, `_assign_communities()`
- **~150 LOC**

---

## 2. Community Summarization (REQ-KG-701)

### Approaches Considered

| # | Approach | Description |
|---|----------|-------------|
| A | **One LLM call per community** | Collect all entity descriptions for a community, concatenate, send as one prompt. |
| B | **Map-reduce summarization** | Chunk entity descriptions, summarize each chunk, then summarize the summaries. |
| C | **Extractive summarization** | TF-IDF or TextRank to select top-K sentences, no LLM. |

### Chosen: A — One LLM call per community (with overflow guard)

**Rationale:**
- ASIC KGs are domain-dense but not web-scale. Typical community sizes are 5-50 entities with 1-5 raw mentions each. A single prompt easily fits within 8K-16K context.
- Map-reduce adds latency (serial LLM calls) and complexity for a case that rarely triggers.
- Extractive methods miss the thematic synthesis that makes community summaries useful for global retrieval.

**Token budgets (two distinct controls):**
- **Input budget** (`community_summary_input_max_tokens`, default 4096): Controls the maximum token count of concatenated entity descriptions sent to the LLM as prompt context. When exceeded, truncate oldest/lowest-mention-count descriptions first. This prevents prompt overflow on large communities.
- **Output budget** (`community_summary_output_max_tokens`, default 512): Controls the `max_tokens` parameter passed to the LLM call, bounding summary length. This ensures summaries are concise regardless of input size.

Both are configurable via `KGConfig`. The input budget is checked pre-call; the output budget is enforced by the LLM provider.

**Key decisions:**
- **Prompt template**: System prompt instructs the LLM to produce a 2-4 sentence thematic summary identifying the community's primary topic, key entities, and relationships. User message contains entity names + descriptions.
- **LLM integration**: Use `LLMProvider.generate()` (sync) via the existing platform layer. Model alias: `"default"` (same as entity extraction). Temperature: 0.2 for deterministic summaries.
- **Storage**: `CommunityDetector` holds `_summaries: Dict[int, CommunitySummary]` where `CommunitySummary` is a new dataclass with `community_id`, `summary_text`, `member_count`, `generated_at` timestamp.
- **Concurrency**: Communities are independent — use `concurrent.futures.ThreadPoolExecutor` with `max_workers=4` for parallel summarization. Each call is I/O-bound (LLM API), so threads are appropriate.

**Devil's advocate on rejected alternatives:**
- **Map-reduce**: Would be necessary if communities had 100+ entities with long descriptions. At that scale, the resolution parameter should be increased to produce smaller communities instead. Map-reduce is the wrong fix for a tuning problem.
- **Extractive**: Fast and cheap, but produces a bag of sentences rather than a coherent theme. The entire value proposition of community summaries is thematic synthesis — extractive methods defeat the purpose.

### Component: `src/knowledge_graph/community/summarizer.py`
- `CommunitySummarizer.__init__(llm_provider, config)` — accepts LLMProvider + KGConfig
- `summarize_community(community_id, members, backend) -> CommunitySummary`
- `summarize_all(communities, backend) -> Dict[int, CommunitySummary]` — parallel
- `_build_prompt(members, backend) -> List[Dict]`
- `_truncate_descriptions(descriptions, max_tokens) -> str`
- **~120 LOC**

### New schema: `src/knowledge_graph/community/schemas.py`
- `CommunitySummary` dataclass: `community_id`, `summary_text`, `member_count`, `member_names`, `generated_at`
- **~25 LOC**

---

## 3. Incremental Refresh (REQ-KG-702)

### Approaches Considered

| # | Approach | Description |
|---|----------|-------------|
| A | **Membership diff** | After re-running Leiden, compare old vs. new community assignments. Re-summarize only communities whose member set changed. |
| B | **Dirty-flag tracking** | Track which entities were added/modified since last detection. Mark their communities dirty, re-detect only subgraph. |
| C | **Content hash** | Hash concatenated descriptions per community. Re-summarize when hash changes. |

### Chosen: A — Membership diff

**Rationale:**
- Leiden is fast enough to re-run on the full graph (sub-second for <100K nodes). The expensive part is LLM summarization, not detection.
- Dirty-flag tracking (B) requires hooks into every write operation on the backend, adding coupling. Partial subgraph re-detection can also produce inconsistent partitions.
- Content hash (C) would miss structural changes (new edges creating new communities) that don't change descriptions.

**Key decisions:**
- `CommunityDetector` stores `_previous_assignments: Dict[str, int]` after each `detect()` call.
- `detect()` returns a `CommunityDiff` object: `new_communities`, `removed_communities`, `changed_communities`, `unchanged_communities`.
- `CommunitySummarizer.refresh(diff, backend)` only re-summarizes communities in `changed_communities | new_communities`.
- First run (no previous assignments) is treated as all-new.

**Devil's advocate on rejected alternatives:**
- **Dirty-flag tracking**: More efficient in theory (avoids full Leiden re-run), but Leiden on graphs under 100K nodes takes <1s. The engineering cost of wiring dirty flags through every backend write method is not justified by sub-second savings.
- **Content hash**: Elegant for description-only changes, but blind to topology changes. A new edge between two existing entities could merge communities without changing any descriptions. Membership diff catches this; content hash does not.

### Component: additions to `detector.py`
- `CommunityDiff` dataclass in `community/schemas.py`
- `_compute_diff()` method on `CommunityDetector`
- **~50 LOC** (across detector + schemas)

---

## 4. Global Retrieval (REQ-KG-609)

### Approaches Considered

| # | Approach | Description |
|---|----------|-------------|
| A | **Inline expansion in GraphQueryExpander** | After neighbour expansion, look up matched entities' communities, append community summary terms. |
| B | **Separate CommunityQueryExpander** | New class that handles community-level queries, composed with GraphQueryExpander. |
| C | **Two-pass retrieval** | First pass: local expansion. Second pass: community-level expansion on a separate index. |

### Chosen: A — Inline expansion in GraphQueryExpander

**Rationale:**
- `GraphQueryExpander.expand()` already has the matched entities and the backend reference. Adding community lookup is 10-15 lines, not a separate class.
- Composition (B) would require a coordinator to merge results from two expanders, adding a layer for minimal benefit.
- Two-pass (C) implies a separate community index/store — overkill when communities are stored as node attributes accessible via the same backend.

**Key decisions:**
- `GraphQueryExpander.__init__` gains an optional `community_detector: Optional[CommunityDetector]` parameter. When provided and `KGConfig.enable_global_retrieval` is True, expansion includes community context.
- **Lifecycle contract**: The `CommunityDetector` passed to the expander MUST have been through both `detect()` and `summarize_all()` before expansion queries. The expander checks `detector.is_ready` (a property that returns True when both detection and summarization have completed at least once). If the detector is injected but not ready, the expander logs a warning and falls back to local-only expansion (no silent failure). The `get_query_expander()` factory in `__init__.py` is responsible for calling `detect()` + `summarize_all()` during initialization when global retrieval is enabled.
- After neighbour expansion, for each matched entity, retrieve its `community_id`, then retrieve the `CommunitySummary`. Extract key terms from the summary (top-N nouns/noun-phrases via simple tokenization, not a full NLP pass).
- Community summary text is also available via `get_context_summary()` for inclusion in the RAG prompt as additional context beyond expansion terms.
- **Ordering**: Local expansion terms come first (higher relevance), community terms fill remaining slots up to `max_terms`.

**Devil's advocate on rejected alternatives:**
- **Separate CommunityQueryExpander**: Better separation of concerns in theory. In practice, community expansion needs the same entity match results as local expansion. Duplicating the match step or passing match results between two expanders is worse than a 15-line addition to the existing method.
- **Two-pass retrieval**: Makes sense when local and global indices are fundamentally different data structures (e.g., vector store for local, BM25 for global). Here, both are lookups on the same graph backend. Two passes add latency without architectural benefit.

### Component: modifications to `src/knowledge_graph/query/expander.py`
- Add `community_detector` parameter to `__init__`
- Add `_expand_with_communities()` private method
- Modify `expand()` to call community expansion when enabled
- **~40 LOC delta**

---

## 5. Neo4j Backend (REQ-KG-505 full implementation)

### Approaches Considered

| # | Approach | Description |
|---|----------|-------------|
| A | **neo4j (official sync driver)** | `neo4j` Python package with bolt protocol. Sync `Session.run()` for all operations. |
| B | **neo4j async driver** | Same package, `AsyncSession` with `await session.run()`. Requires async pipeline. |
| C | **py2neo** | Community OGM (Object-Graph Mapper) layer over Neo4j. |

### Chosen: A — Official sync driver

**Rationale:**
- The entire KG pipeline is synchronous. `GraphStorageBackend` ABC methods are sync. Introducing async for one backend would require either a sync wrapper (defeating the purpose) or an async ABC variant (breaking the contract).
- py2neo is unmaintained (last release 2022) and adds OGM complexity we don't need — our data model is already defined in `schemas.py`.
- The official driver is actively maintained, well-documented, and supports both Community and Enterprise editions.

**Key decisions:**
- **Connection management**: `Neo4jBackend.__init__(uri, auth, database)` creates a `neo4j.Driver` instance. Use driver-managed connection pooling (default pool size 100).
- **Entity resolution**: Server-side via Cypher `MERGE` with case-insensitive matching (`toLower()`). Alias index stored as a node property (list) rather than a separate lookup, since Neo4j's native indexing handles the query load.
- **Indexes**: Create on init: `CREATE INDEX IF NOT EXISTS` for entity name (text index), entity type, and community_id. Full-text index on entity name for fuzzy matching.
- **Transactions**: Batch operations (`upsert_entities`, `upsert_triples`) use explicit write transactions with `UNWIND` for bulk Cypher. Single operations use auto-commit.
- **save/load semantics**: `save()` exports to Cypher script or APOC JSON. `load()` imports from the same format. These are migration/backup operations, not the primary persistence path (Neo4j persists server-side).
- **Community storage**: `community_id` as a node property, queryable via index. Community summaries stored as separate `(:Community {id, summary, member_count, generated_at})` nodes with `[:BELONGS_TO]` edges from entities.

**Devil's advocate on rejected alternatives:**
- **Async driver**: Would be the right choice if the query layer were async (e.g., FastAPI endpoint calling `await backend.query_neighbors()`). The current architecture is sync throughout. Converting to async would be a cross-cutting change affecting every caller. If the server layer goes async in the future, a `Neo4jAsyncBackend` subclass can wrap `AsyncSession` without changing the sync ABC.
- **py2neo**: The OGM pattern (defining Python classes that map to Neo4j node labels) is attractive for schema enforcement. But our schema is YAML-driven and validated at load time, not at the ORM layer. py2neo's OGM would duplicate the schema definition without adding safety. The project is also effectively abandoned.

### Component: `src/knowledge_graph/backends/neo4j_backend.py`
- Full implementation of all 12 abstract methods + 4 concrete overrides
- `_ensure_indexes()` — called on init
- `_resolve()` — server-side entity resolution via MERGE
- `_to_entity()` — Neo4j Record → Entity dataclass
- Bulk Cypher templates as module-level constants
- **~350 LOC**

---

## 6. Python/Bash Parsers (REQ-KG-313, MAY priority)

### Approaches Considered

| # | Approach | Description |
|---|----------|-------------|
| A | **ast module (Python) + tree-sitter-bash** | stdlib ast for Python, tree-sitter for Bash. Two separate extractors. |
| B | **tree-sitter for both** | tree-sitter-python and tree-sitter-bash. Uniform parser interface. |
| C | **Defer to Phase 3** | Skip — MAY priority, focus on MUST deliverables. |

### Chosen: A — ast + tree-sitter-bash (if time permits, else C)

**Rationale:**
- Python's `ast` module is stdlib, zero dependencies, and produces a typed AST with class/function/import extraction trivially.
- tree-sitter-bash is already pattern-established by the SV parser.
- Using tree-sitter-python would add a C extension dependency when `ast` does the same job better (typed nodes, no grammar maintenance).
- This is MAY priority. If the MUST deliverables consume the full budget, defer without guilt.

**Key decisions:**
- Both parsers implement the existing `Extractor` protocol (same as `RegexExtractor`, `LLMExtractor`, etc.).
- Python extractor extracts: classes, functions, imports, global variables → `Entity` + `contains`/`depends_on` triples.
- Bash extractor extracts: functions, sourced files, command invocations → `Entity` + `depends_on` triples.
- New node types in `kg_schema.yaml`: `PythonClass`, `PythonFunction`, `BashFunction`, `BashScript` (all phase_2, structural).

### Components (estimated, MAY scope):
- `src/knowledge_graph/extraction/python_parser.py` — **~120 LOC**
- `src/knowledge_graph/extraction/bash_parser.py` — **~100 LOC**

---

## 7. KGConfig Additions

New fields for `KGConfig` in `src/knowledge_graph/common/types.py`:

```python
# Phase 2: Community detection & global retrieval
enable_global_retrieval: bool = False
community_resolution: float = 1.0
community_min_size: int = 3
community_summary_input_max_tokens: int = 4096
community_summary_output_max_tokens: int = 512
community_summary_temperature: float = 0.2
community_summary_max_workers: int = 4

# Phase 2: Neo4j
neo4j_uri: str = "bolt://localhost:7687"
neo4j_auth_user: str = "neo4j"
neo4j_auth_password: str = ""  # must be set via env/config, not hardcoded
neo4j_database: str = "neo4j"

# Phase 2: Parsers
enable_python_parser: bool = False
enable_bash_parser: bool = False
```

**~15 LOC delta**

---

## 8. LOC Estimates Summary

| Component | File | Est. LOC |
|-----------|------|----------|
| Community detector | `community/detector.py` | ~150 |
| Community summarizer | `community/summarizer.py` | ~120 |
| Community schemas | `community/schemas.py` | ~50 |
| Incremental diff | detector.py + schemas.py | ~50 |
| Global retrieval | `query/expander.py` (delta) | ~40 |
| Neo4j backend | `backends/neo4j_backend.py` | ~350 |
| KGConfig additions | `common/types.py` (delta) | ~15 |
| Python parser (MAY) | `extraction/python_parser.py` | ~120 |
| Bash parser (MAY) | `extraction/bash_parser.py` | ~100 |
| **Total (MUST/SHOULD)** | | **~775** |
| **Total (including MAY)** | | **~995** |

Test code (not counted above): ~400-500 LOC across community, Neo4j, and global retrieval test modules.

---

## 9. Scope Boundary

### In scope
- Leiden community detection on NetworkX and Neo4j backends
- LLM community summarization with parallel execution
- Incremental refresh via membership diff
- Community-aware query expansion in `GraphQueryExpander`
- Full Neo4j backend implementation (sync driver)
- KGConfig extensions for all Phase 2 features
- Community/schemas dataclass additions

### Out of scope
- Async Neo4j driver / async ABC variant
- Neo4j browser visualization (REQ-KG-801, MAY, separate deliverable)
- Hierarchical community detection (multi-resolution Leiden)
- Community-to-community edge detection
- Vector similarity search within communities
- Python/Bash parsers if MUST deliverables consume the budget

---

## 10. Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| leidenalg C extension fails to build on target platform | Blocks community detection | Low | Pin known-good wheel versions; fallback to graspologic if igraph wheel unavailable |
| LLM summarization cost scales with community count | Budget overrun on large graphs | Medium | Cap `max_communities_to_summarize` config; prioritize by community size; skip communities below min_size |
| Neo4j version incompatibility (Community vs Enterprise) | Backend fails on customer infra | Medium | Test against Neo4j 5.x Community; document minimum version; avoid Enterprise-only features (APOC in Community edition) |
| Leiden produces unstable partitions on small graphs (<50 nodes) | Inconsistent community assignments between runs | Medium | Set `seed` parameter for deterministic results; document that small graphs may produce trivial partitions |
| Incremental refresh misses edge-only changes | Stale summaries | Low | Membership diff already catches topology changes that alter community structure; edge-weight-only changes within a community are unlikely to change the summary meaningfully |
| `GraphStorageBackend` ABC needs new methods for community storage | Breaking change to ABC contract | Medium | Store communities outside the backend (on `CommunityDetector` itself) for NetworkX; use node properties for Neo4j. No ABC changes required. |

---

## 11. Dependency Graph

```
KGConfig additions (no deps)
    ↓
community/schemas.py (no deps)
    ↓
community/detector.py (depends on: backend ABC, igraph, leidenalg, schemas)
    ↓
community/summarizer.py (depends on: detector, LLMProvider, schemas)
    ↓
query/expander.py changes (depends on: detector, summarizer)

backends/neo4j_backend.py (depends on: backend ABC, neo4j driver, schemas)
    — independent of community work, can be parallelized

extraction/python_parser.py (depends on: extractor protocol, ast)
extraction/bash_parser.py (depends on: extractor protocol, tree-sitter-bash)
    — independent, lowest priority
```

Recommended implementation order:
1. KGConfig + community schemas (foundation)
2. Neo4j backend (independent, high LOC, benefits from early testing)
3. Community detector (core algorithm)
4. Community summarizer (depends on detector)
5. Global retrieval (depends on detector + summarizer)
6. Incremental refresh (enhancement to detector)
7. Python/Bash parsers (MAY, if time)
