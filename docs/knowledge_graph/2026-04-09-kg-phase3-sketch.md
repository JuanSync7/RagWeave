# KG Phase 3 Design Sketch

**Date:** 2026-04-09
**Status:** Brainstorm
**Author:** Claude Code (autonomous pipeline)

---

## 1. Goal Statement

Phase 3 transforms the knowledge graph from a static, append-only subsystem into a production-grade incremental graph with cross-module SV connectivity analysis, embedding-based entity resolution, hierarchical community detection, and interactive visualization. These six features close the gap between "graph exists" and "graph is useful for real ASIC design queries" by enabling update-mode correctness (incremental deletes), deeper structural understanding (pyverilog port connectivity), cleaner data (entity dedup), richer community structure (hierarchical Leiden), and human-accessible exploration (Sigma.js export).

---

## 2. Feature-by-Feature Analysis

### 2.1 Incremental Graph Updates

**Current state:**
- The vector pipeline (`embedding_storage.py` lines 43-48) already implements incremental deletes: when `runtime.config.update_mode` is True, it calls `delete_by_source_key()` before re-upserting.
- The KG pipeline (`knowledge_graph_storage.py`) has no equivalent delete step. It only upserts. When a file changes in `--update` mode, old entities/triples from the previous version remain in the graph alongside the new ones.
- Both backends track `sources` per node and per edge, which provides the provenance needed to identify what to delete. NetworkX stores `sources` as a list on both node data and edge data. Neo4j stores `sources` as a list property on Entity nodes and RELATES_TO relationships.

**Gap:**
- No `remove_by_source(source_key)` method on `GraphStorageBackend`.
- `knowledge_graph_storage_node` does not call any delete operation before upserting.
- Nodes that were contributed by multiple sources need source-list pruning, not deletion (delete only when the last source is removed).

**Approach:**
1. Add `remove_by_source(source_key: str) -> RemovalStats` to `GraphStorageBackend` ABC.
2. NetworkX implementation: iterate all nodes and edges, remove `source_key` from `sources` lists, delete nodes/edges whose `sources` become empty. Rebuild `_aliases` and `_case_index` after removals.
3. Neo4j implementation: Cypher query to remove source from lists, then `DETACH DELETE` nodes with empty sources, and delete edges with empty sources.
4. Wire into `knowledge_graph_storage_node`: when `runtime.config.update_mode`, call `backend.remove_by_source(state["source_key"])` before the extraction+upsert loop.
5. Return a `RemovalStats` dataclass (nodes_removed, edges_removed, nodes_pruned) for logging.

**Alternatives considered:**
- *Full graph rebuild on every update*: Simpler but O(N) for the entire corpus on each file change. Rejected because it defeats the purpose of incremental ingestion and would be prohibitively slow for large ASIC projects.
- *Soft-delete with tombstones*: Mark nodes/edges as deleted rather than removing them. Rejected because it adds query-time complexity (filter tombstones everywhere) and the graph is already in-memory for NetworkX, so actual removal is cheap.

**Key decisions:**
- Source-level granularity (not chunk-level). Matches the vector pipeline's `delete_by_source_key` pattern.
- Multi-source nodes are pruned (source removed from list), not deleted, until they have zero sources remaining.
- Edge removal must also check the source list, not just the endpoint nodes.
- Index rebuild (NetworkX `_case_index`, `_aliases`) must happen after batch removal to avoid stale references.

**Integration points:**
- `backend.py`: New abstract method `remove_by_source`.
- `networkx_backend.py` and `neo4j_backend.py`: Concrete implementations.
- `knowledge_graph_storage.py`: Wire delete-before-upsert pattern.
- `common/schemas.py`: New `RemovalStats` dataclass.

**Risk/complexity:** Low. The pattern is well-established in the vector pipeline. Both backends already track sources. The main subtlety is multi-source node pruning and index rebuilding.

---

### 2.2 SV Port Connectivity (Pyverilog DataflowAnalyzer)

**Current state:**
- `parser_extractor.py` uses tree-sitter-verilog for per-file structural extraction: modules, ports, parameters, instances, signals. Produces `contains`, `instantiates`, and `depends_on` triples.
- The schema (`kg_schema.yaml`) already defines a `connects_to` edge type (phase_1b, structural, description: "Signal or port A connects to signal or port B across a module boundary"). No new schema entry needed — pyverilog produces triples using this existing edge type.
- Tree-sitter operates per-file. It cannot resolve cross-module port connections because those require elaboration context (knowing which port of module A connects to which port of module B through an instantiation).

**Gap:**
- No cross-module port connectivity. The graph has "module A instantiates module B" but not "port X of A connects to port Y of B."
- No `.f` filelist support for batch processing.
- No auto-detection of top module.

**Approach:**
Two-tool architecture (tree-sitter stays, pyverilog added):
1. **New module**: `src/knowledge_graph/extraction/sv_connectivity.py` containing `SVConnectivityAnalyzer`.
2. Uses pyverilog `DataflowAnalyzer` as a post-ingestion batch step (not per-chunk).
3. Reads `.f` filelists via `RAG_KG_SV_FILELIST` env var. Parses standard `.f` format (one file per line, `+incdir+` directives, `-f` nesting).
4. Auto-detects top module from graph: query all `RTL_Module` entities, find ones never appearing as targets of `instantiates` edges. Falls back to `RAG_KG_SV_TOP_MODULE` env var if ambiguous.
5. Produces ONLY `connects_to` triples (no entity upserts). This prevents duplication with tree-sitter entities. Uses `extractor_source="sv_connectivity"` to distinguish.
6. Multi-hop traversal: update `GraphQueryExpander` to use `depth >= 2` when `connects_to` edges are present in the graph, so queries can follow port connectivity chains.

**Alternatives considered:**
- *Replace tree-sitter with pyverilog entirely*: Rejected. Tree-sitter is faster for per-file extraction and handles incomplete/partial files gracefully. Pyverilog requires full elaboration context (all files, includes, top module). Using both plays to each tool's strength.
- *Verilator for elaboration*: More complete elaboration but heavyweight C++ dependency, harder to package, and overkill for port connectivity extraction. Rejected for Phase 3; could revisit for future CDC analysis.
- *Per-file connectivity inference from port maps*: Parse `.portname(signal)` syntax in tree-sitter instance nodes. This gives partial connectivity without pyverilog but misses parameterized widths, generate-based connectivity, and hierarchical resolution. Rejected as too incomplete to be useful; better to do it properly with pyverilog.

**Key decisions:**
- Batch step, not per-chunk. Runs after all per-file extractions are complete.
- Triples-only output prevents entity duplication with tree-sitter.
- `connects_to` edge uses existing schema definition (no schema changes needed beyond confirming it is adequate).
- `.f` filelist parsing follows ASIC industry convention: one path per line, `//` comments, `+incdir+`, recursive `-f`.
- Top module auto-detection: "modules never instantiated by another" is the standard heuristic.

**Integration points:**
- New `src/knowledge_graph/extraction/sv_connectivity.py`.
- `config/settings.py`: New `RAG_KG_SV_FILELIST` and `RAG_KG_SV_TOP_MODULE` env vars.
- `KGConfig`: New fields for filelist path and top module override.
- `knowledge_graph_storage.py` or a new post-ingestion hook: trigger batch connectivity analysis after all files are ingested.
- `query/expander.py`: Adjust depth heuristic when `connects_to` edges exist.

**Risk/complexity:** Medium.
- Pyverilog's `DataflowAnalyzer` API can be finicky with complex SV constructs (generate blocks, parameterized widths). Need to handle failures gracefully.
- `.f` filelist parsing has edge cases (relative paths, environment variable expansion in paths).
- Top module auto-detection can be ambiguous in testbench setups (multiple "top" modules).

---

### 2.3 Graph Visualization (Sigma.js + Graphology)

**Current state:**
- Only export format is Obsidian markdown vault (`export/obsidian.py`): one `.md` file per entity with wikilinks. No interactive visualization.

**Gap:**
- No visual graph exploration. Engineers cannot see the graph structure, identify clusters, or navigate community hierarchies interactively.

**Approach:**
1. **New module**: `src/knowledge_graph/export/sigma_html.py` with `export_html(backend, output_path, community_detector=None)`.
2. Uses Sigma.js v3 + graphology via CDN (unpkg/cdnjs). No npm build step, no pip dependency.
3. Generates a single self-contained HTML file with:
   - Embedded graph data as JSON (inline `<script>` tag).
   - Node positions computed by ForceAtlas2 layout (graphology-layout-forceatlas2).
   - Nodes colored by community ID (if communities are available) or by entity type.
   - Node size proportional to mention_count or degree.
   - Community hierarchy as zoom levels: overview shows community clusters, click a cluster to expand and show individual entities within that community.
   - Search box for entity name filtering.
   - Hover tooltips showing entity type, sources, and relationship counts.
4. Template approach: Python string template with placeholder for graph JSON and config. No Jinja2 dependency.

**Alternatives considered:**
- *D3.js force-directed graph*: More flexible but requires significantly more custom code for large graphs (performance degrades past ~1000 nodes). Sigma.js/graphology is purpose-built for large graph rendering with WebGL. Rejected for performance reasons.
- *Pyvis (Python library)*: Generates interactive HTML via vis.js. Simpler API but limited customization, no community hierarchy support, and adds a pip dependency. Rejected because it cannot do hierarchical zoom.
- *Gephi export (GEXF format)*: Requires users to install Gephi desktop app. Not web-accessible. Rejected for usability.
- *Server-based approach (FastAPI + WebSocket)*: More interactive but adds operational complexity. The spec says "no server required" and a static HTML file is shareable via email/Slack. Rejected.

**Key decisions:**
- CDN-only JS dependencies. The HTML file works offline after first load (browsers cache CDN resources), but strictly offline use would require bundling. Acceptable trade-off for Phase 3.
- Community hierarchy via zoom: ForceAtlas2 naturally clusters community members. The zoom interaction shows/hides nodes based on camera zoom level and community membership.
- Single file output. No directory of assets, no build step. Open in any browser.
- Template is embedded in the Python module as a multiline string, not a separate file.

**Integration points:**
- New `src/knowledge_graph/export/sigma_html.py`.
- `__init__.py`: Add `export_html` to public API and `__all__`.
- Community detector (optional): If provided, colors nodes by community and enables hierarchy zoom.

**Risk/complexity:** Medium.
- Template maintenance: the embedded HTML/JS template is a large string that is harder to debug than a separate file. Acceptable for the scope.
- CDN availability: if CDN is down, the file won't render. Mitigated by using stable CDN URLs with version pinning.
- Large graphs (10K+ nodes): Sigma.js handles these well, but the JSON payload in the HTML file could be large. May need to add a node/edge limit or sampling for very large graphs.

---

### 2.4 Entity Resolution (Embedding-Based Dedup)

**Current state:**
- Case-insensitive dedup exists in both backends (`_resolve()` in NetworkX, `name_lower` MERGE in Neo4j).
- Alias-based resolution exists (`_aliases` index in NetworkX, `aliases` property in Neo4j).
- No semantic similarity matching. "AXI4 bus interface" and "AXI4_bus_if" would remain as separate entities despite referring to the same thing.

**Gap:**
- No embedding-based fuzzy matching for entity dedup.
- No configurable alias tables for domain-specific synonyms.
- Entities from different extractors (regex, GLiNER, LLM, parser) may produce semantically identical entities with different surface forms that pass case-insensitive dedup.

**Approach:**
1. **New package**: `src/knowledge_graph/resolution/` with:
   - `resolver.py`: `EntityResolver` class with `resolve(backend) -> MergeReport`.
   - `alias_loader.py`: Load YAML alias tables from `config/kg_aliases.yaml`.
   - `schemas.py`: `MergeCandidate`, `MergeReport` dataclasses.
2. Algorithm:
   a. Load all entities from backend.
   b. Apply YAML alias table merges first (deterministic, fast).
   c. Compute embeddings for all entity names using the configured embedding model (`EMBEDDING_MODEL_PATH`).
   d. For each entity pair of the SAME type, compute cosine similarity.
   e. Pairs above threshold (default 0.85, configurable via `RAG_KG_RESOLUTION_THRESHOLD`) become merge candidates.
   f. Merge: keep the entity with higher mention_count as canonical. Transfer sources, aliases, raw_mentions, and triples from the merged entity. Delete the merged entity.
3. Type-constrained: only compare entities of the same type. "AXI4" (Protocol) will never merge with "AXI4" (RTL_Module).
4. Post-ingestion step: runs after all extraction is complete but before community detection.
5. Reuses the same embedding model the vector pipeline uses, via `EMBEDDING_MODEL_PATH`. No separate model.

**Alternatives considered:**
- *String similarity (Levenshtein/Jaro-Winkler)*: Cheap but misses semantic equivalence. "ethernet_controller" and "eth_ctrl" have low string similarity but high semantic similarity. Rejected as primary method; could be used as a pre-filter to reduce embedding comparisons.
- *LLM-based pairwise judgment*: Most accurate but O(N^2) LLM calls. Prohibitively expensive for graphs with thousands of entities. Rejected for Phase 3; could be used as a refinement step for borderline cases in a future phase.
- *Transitive closure via Union-Find*: If A merges with B and B merges with C, merge all three. This is correct but risky (chain merges can snowball). Approach: implement Union-Find but cap chain length at 3 to prevent over-merging.

**Key decisions:**
- Type-constrained matching is mandatory. This is the single most important guard against false merges.
- Threshold default 0.85 is conservative. Better to under-merge than over-merge (false negatives are recoverable via alias tables; false positives lose information).
- YAML alias table (`config/kg_aliases.yaml`) provides an escape hatch for known domain synonyms that embeddings might miss or get wrong.
- Embedding computation can be batched and cached. For graphs under 5K entities, this runs in seconds on a GPU.

**Integration points:**
- New `src/knowledge_graph/resolution/` package.
- New `config/kg_aliases.yaml` file.
- `KGConfig`: New `resolution_threshold`, `resolution_enabled`, `alias_table_path` fields.
- `config/settings.py`: New `RAG_KG_RESOLUTION_THRESHOLD`, `RAG_KG_RESOLUTION_ENABLED` env vars.
- Pipeline integration: must run AFTER extraction, BEFORE community detection (merged entities produce better communities).
- `backend.py`: Potentially add a `merge_entities(canonical, merged)` method for atomic merge operations, or implement merge as delete+upsert sequence.

**Risk/complexity:** Medium-High.
- Merge correctness: merging entities also requires redirecting all triples that reference the merged entity. This is the trickiest part.
- Embedding model loading: if the vector pipeline hasn't initialized the model yet, entity resolution needs to load it independently. Must handle the case where `EMBEDDING_MODEL_PATH` is not set.
- Performance: O(N^2/2) pairwise comparisons within each type bucket. For a type with 1000 entities, that is 500K comparisons. Mitigation: use FAISS or numpy batch cosine similarity, which handles this in milliseconds.

---

### 2.5 Hierarchical Leiden Community Detection

**Current state:**
- `community/detector.py` runs flat Leiden via `leidenalg.find_partition()` with `RBConfigurationVertexPartition`.
- Produces a single-level partition: `{community_id: [member_names]}`.
- Small communities (< `community_min_size`) are merged into bucket -1.
- Per-community LLM summaries via `community/summarizer.py`.
- Sidecar persistence for summaries and previous assignments.

**Gap:**
- No hierarchy. All communities are flat at one level. For large graphs, this produces either too many small communities (high resolution) or too few large ones (low resolution).
- Query expander cannot pick a community level based on query specificity. A broad query ("what is the memory subsystem?") should match a high-level community; a specific query ("what drives the AXI read channel FIFO?") should match a leaf-level community.

**Approach:**
1. Replace `find_partition` with `leidenalg`'s recursive partitioning: use `leidenalg.find_partition` at multiple resolution levels, or use the built-in `RBConfigurationVertexPartition` with `optimise_partition` at different resolutions to build a hierarchy.
   - Alternatively, use `leidenalg.find_partition` once at low resolution for coarse communities, then recursively partition each community at higher resolution.
2. Data structure: `{(level, community_id): [members]}` with a `parent_map: Dict[(level, cid), (level-1, parent_cid)]`.
3. Per-level summaries: summarizer runs at each level. Higher-level summaries are coarser.
4. Query expander level selection: estimate query specificity (simple heuristic: more entity matches = more specific = deeper level). Broad queries use level 0 (coarsest); specific queries use the deepest level.
5. Backward compatibility: level 0 is equivalent to the current flat partition. Callers that don't know about hierarchy see the same behavior.

**Alternatives considered:**
- *Louvain instead of Leiden*: Louvain is simpler but has known issues with poorly-connected communities. Leiden is the strict improvement. Already using Leiden, no reason to switch.
- *Fixed 3-level hierarchy*: Run Leiden at resolution 0.5, 1.0, 2.0. Simple but inflexible. Rejected in favor of recursive partitioning which adapts to graph structure.
- *Agglomerative clustering on entity embeddings*: Would give a dendrogram but ignores graph topology. The whole point of Leiden is topology-aware clustering. Rejected.

**Key decisions:**
- Recursive partitioning: partition at level 0, then sub-partition each community with `min_size > threshold`. Stop recursion when communities are below a minimum size or when Leiden returns a single community.
- Maximum 4 levels (configurable). Prevents over-fragmentation.
- Summary generation: only summarize levels 0 and 1 by default (configurable). Deeper levels are navigable but not pre-summarized to save LLM costs.
- Sidecar format: extend the existing `communities.json` sidecar to include level information.

**Integration points:**
- `community/detector.py`: Major refactor. Replace flat `_communities` dict with hierarchical structure.
- `community/schemas.py`: New `HierarchicalPartition` dataclass or extend `CommunitySummary` with `level` field.
- `community/summarizer.py`: Accept level parameter, summarize at specified levels.
- `query/expander.py`: Level-selection logic based on query specificity.
- `export/sigma_html.py`: Use hierarchy for zoom levels.
- `KGConfig`: New `community_max_levels`, `community_summarize_levels` fields.

**Risk/complexity:** Medium.
- Recursive Leiden is supported natively by `leidenalg` but the API for it is less documented than flat partitioning. Need to verify the exact API surface.
- Level selection heuristic for query expansion is inherently fuzzy. May need tuning.
- Sidecar format change must be backward-compatible (old sidecars without levels should still load as level-0 flat partitions).

---

### 2.6 Update pyproject.toml (Dependency Management)

**Current state:**
- `pyproject.toml` has no tree-sitter, pyverilog, igraph, leidenalg, or neo4j dependencies.
- tree-sitter-verilog is imported with try/except in `parser_extractor.py`.
- igraph/leidenalg are imported with try/except in `community/detector.py`.
- neo4j is imported with try/except in `neo4j_backend.py`.

**Gap:**
- Users must manually install these packages. No guidance in pyproject.toml.
- tree-sitter-verilog and pyverilog are lightweight enough to be default dependencies for an ASIC-focused tool.

**Approach:**
1. Add to default `dependencies`:
   - `tree-sitter` and `tree-sitter-verilog` (both lightweight, pure Python wheels available).
   - `pyverilog` (lightweight, pure Python).
2. Add optional dependency groups:
   - `[project.optional-dependencies]` section additions:
     - `kg-community = ["igraph", "leidenalg"]` — for hierarchical Leiden.
     - `kg-neo4j = ["neo4j"]` — for Neo4j backend.
3. Update the `all` group to include the new optional groups.
4. Keep try/except guards in the code for graceful degradation when optional deps are missing.

**Alternatives considered:**
- *Make everything optional*: Even tree-sitter-verilog. Rejected because this is an ASIC-focused tool and SV parsing is a core capability, not optional.
- *Single `kg` optional group for everything*: Lumps Neo4j (which requires a running server) with igraph (which is purely algorithmic). Rejected because users who want community detection shouldn't be forced to install the neo4j driver.

**Key decisions:**
- tree-sitter + tree-sitter-verilog + pyverilog as default deps. They are small and have no heavy native dependencies.
- igraph + leidenalg as optional because leidenalg has a C extension that can be tricky to build on some platforms.
- neo4j driver as optional because it is useless without a running Neo4j server.

**Integration points:**
- `pyproject.toml`: Modify `dependencies` and `[project.optional-dependencies]`.
- `tool.deptry`: May need to update ignore rules if deptry flags the new optional deps.

**Risk/complexity:** Low. Straightforward dependency management.

---

## 3. Cross-Feature Interactions

### Execution Order Dependencies

```
                 [6. pyproject.toml]
                        |
          (install deps, enables all below)
                        |
     +------------------+------------------+
     |                                     |
[1. Incremental Updates]          [2. SV Connectivity]
     |                                     |
     +------------------+------------------+
                        |
                [4. Entity Resolution]
                        |
                [5. Hierarchical Leiden]
                        |
                [3. Graph Visualization]
```

### Key Interactions

1. **Incremental updates + SV connectivity**: When a file changes, `remove_by_source` deletes its old entities/triples. The pyverilog batch step must re-run after incremental updates to regenerate `connects_to` triples for the affected modules. This means the batch step needs to know which sources were updated, or it must re-run on the full filelist (simpler, acceptable for batch).

2. **Incremental updates + Entity resolution**: After removing old data and upserting new data, entity resolution should re-run to catch any new duplicate entities introduced by the update. This is already handled by the ordering (resolution runs after all extraction).

3. **Entity resolution + Hierarchical Leiden**: Resolution MUST run before community detection. Merged entities produce better community structure. If two entities representing the same thing are in different communities, the graph topology is misleading.

4. **Hierarchical Leiden + Graph visualization**: The Sigma.js export uses community hierarchy for zoom levels. The visualization must handle the case where communities are not yet computed (fall back to flat display by entity type).

5. **SV connectivity + Graph visualization**: `connects_to` edges should be visually distinguishable (different color/style) from structural edges like `contains` and `instantiates`. The visualization template should support edge-type-based styling.

6. **SV connectivity + Query expansion**: `connects_to` edges enable multi-hop traversal for connectivity queries. The expander should increase `max_depth` when the matched entity has `connects_to` edges, or the user should be able to configure a higher default depth.

7. **Entity resolution + Incremental updates**: When `remove_by_source` removes a source from a merged entity, the entity should not be deleted if it still has other sources. The merge metadata (which entities were merged) should be tracked so that resolution can be re-evaluated after incremental updates.

---

## 4. Execution Order

### Recommended Implementation Sequence

**Phase 3a (Foundation):**
1. **pyproject.toml** (30 min) -- Unblocks all other features by making dependencies available.
2. **Incremental graph updates** (1-2 days) -- Foundation for correctness. Every subsequent feature depends on the graph being in a consistent state after updates.

**Phase 3b (Extraction + Resolution):**
3. **SV port connectivity** (2-3 days) -- New extraction capability. Independent of resolution and community detection. Can be developed and tested in isolation.
4. **Entity resolution** (2-3 days) -- Must come after incremental updates (needs clean graph state). Must come before hierarchical Leiden (better communities from merged entities).

**Phase 3c (Analysis + Visualization):**
5. **Hierarchical Leiden** (2-3 days) -- Depends on entity resolution being complete. Refactors existing detector.
6. **Graph visualization** (2-3 days) -- Last because it consumes all other features' outputs (communities, connectivity, resolved entities). Can be developed in parallel with Leiden if the community interface is agreed upon first.

**Justification:**
- pyproject.toml first is trivial and unblocks imports.
- Incremental updates before everything else because correctness > features.
- SV connectivity and entity resolution are independent of each other but both must precede Leiden.
- Visualization last because it is a read-only consumer of the graph.

---

## 5. Scope Boundary

### Explicitly OUT of scope for Phase 3

- **Clock domain crossing (CDC) analysis**: Listed in `KNOWN_UNSUPPORTED` in parser_extractor.py. Requires deep dataflow analysis beyond pyverilog's capabilities. Deferred to Phase 4+.
- **Real-time graph updates via WebSocket**: The Sigma.js export is a static HTML snapshot. Live-updating visualization requires a server component.
- **LLM-based entity resolution refinement**: Using an LLM to judge borderline merge candidates. Too expensive at scale for Phase 3.
- **Neo4j-native community detection (GDS)**: Neo4j Graph Data Science library has its own Leiden implementation. Could replace igraph for Neo4j backend users, but adds a GDS dependency and splits the community detection codepath.
- **Cross-language connectivity**: Connecting SV entities to Python/Bash entities via shared signal names or register names. Requires a cross-language resolution strategy.
- **Graph versioning/history**: Tracking graph state over time (git-like snapshots). Would enable diff visualization but is a separate infrastructure feature.
- **Offline Sigma.js bundle**: Embedding all JS dependencies inline for fully offline HTML files. CDN-based is acceptable for Phase 3.
- **Entity resolution across types**: Merging entities of different types (e.g., an RTL_Module and a Specification that refer to the same design block). Type-constrained matching only in Phase 3.
- **Automated resolution threshold tuning**: Automatically finding the optimal cosine similarity threshold. Phase 3 uses a fixed configurable default.
- **Pyverilog SystemVerilog 2017+ features**: Pyverilog's SV support is incomplete for newer language features. If DataflowAnalyzer fails on modern SV constructs, those files are skipped with a warning.

---

## 6. Open Questions and Risks

1. **Pyverilog API stability**: Pyverilog is not actively maintained (last PyPI release may be old). Need to verify it works with Python 3.10+ and handles the project's SV dialect. Mitigation: pin version, add integration test with sample SV files.

2. **Entity resolution merge atomicity**: Merging two entities requires updating all triples that reference the merged entity. In NetworkX this is straightforward (graph mutation). In Neo4j this requires a multi-statement transaction. Need to ensure atomicity.

3. **Hierarchical Leiden API**: The exact `leidenalg` API for recursive partitioning needs verification. The documented approach uses `find_partition` at multiple resolutions, but there may be a more direct recursive API. Spike needed.

4. **Sigma.js template size**: For large graphs (5K+ nodes), the inline JSON in the HTML file could be several MB. Need to test browser performance and consider a node/edge limit with a "showing top N entities" warning.

5. **Interaction between incremental updates and pyverilog batch**: If only one SV file changes, does the pyverilog batch step need to re-analyze all files (because connectivity is cross-module)? Likely yes. This means incremental updates for SV connectivity are "re-run batch for all SV files" rather than "update only changed files." This is acceptable if the filelist is not enormous.
