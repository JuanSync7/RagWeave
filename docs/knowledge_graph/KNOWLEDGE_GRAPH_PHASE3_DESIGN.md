# KG Phase 3 Design — Task Decomposition and Code Contracts

**Date:** 2026-04-09
**Status:** Draft
**Parent:** `KNOWLEDGE_GRAPH_SPEC.md` Appendix E (REQ-KG-730 through REQ-KG-756)
**Companion:** `2026-04-09-kg-phase3-sketch.md` (approved design sketch)
**Scope:** REQ-KG-730 through REQ-KG-756

---

## Overview

This document decomposes Phase 3 into twelve implementation tasks with full code contracts (typed Python signatures), dependency lists, files modified, requirement traceability, and implementation notes. Each task is independently testable against the acceptance criteria defined in the spec.

Task IDs continue from Phase 2 (which ended at T31). Phase 3 tasks are numbered T32 through T43.

Phase 3 covers six feature areas:

1. **Incremental graph updates** (T32--T35) — `remove_by_source()` on both backends, wired into storage node
2. **SV port connectivity** (T36--T37) — pyverilog `DataflowAnalyzer` batch step producing `connects_to` triples
3. **KGConfig extensions** (T38) — all new configuration fields for Phase 3
4. **Graph visualization** (T39) — Sigma.js interactive HTML export
5. **Entity resolution** (T40) — embedding + alias dedup pipeline with `merge_entities()` backend method
6. **Hierarchical Leiden** (T41) — multi-level community detection with parent map
7. **Query expander updates** (T42) — multi-hop for `connects_to`, hierarchical level selection
8. **Dependency management** (T43) — pyproject.toml and requirements.txt updates

**Execution order constraints:**

```
T43 (deps)  ──→  T38 (config)  ──→  T32-T34 (remove_by_source ABC + impls)
                                 ├──→  T36 (SVConnectivityAnalyzer)
                                 └──→  T40 (entity resolution)

T32-T34  ──→  T35 (incremental wiring)
T36     ──→  T37 (batch step wiring)
T35 + T37 + T40  ──→  T41 (hierarchical Leiden)
T41  ──→  T39 (Sigma.js export)
T41 + T36  ──→  T42 (query expander updates)
```

---

## T32: GraphStorageBackend.remove_by_source() ABC Method

**Req:** REQ-KG-730
**File(s):** `src/knowledge_graph/backend.py`, `src/knowledge_graph/common/schemas.py`
**Depends on:** None

### Contract

```python
# --- src/knowledge_graph/common/schemas.py (add to existing file) ---

@dataclass
class RemovalStats:
    """Statistics from a remove_by_source() operation.

    Attributes:
        nodes_removed: Entities fully deleted (sources list became empty).
        edges_removed: Triples fully deleted (sources list became empty).
        nodes_pruned: Entities where source_key was removed but other sources remain.
    """
    nodes_removed: int = 0
    edges_removed: int = 0
    nodes_pruned: int = 0
```

```python
# --- src/knowledge_graph/backend.py (add to GraphStorageBackend ABC) ---

from src.knowledge_graph.common.schemas import RemovalStats

class GraphStorageBackend(ABC):
    # ... existing methods ...

    # -- Write operations (new) --

    @abstractmethod
    def remove_by_source(self, source_key: str) -> RemovalStats:
        """Remove all entities and triples contributed solely by source_key.

        For entities/triples contributed by multiple sources, prune source_key
        from the sources list. Delete the item only when its sources list
        becomes empty.

        Args:
            source_key: Document path or URI to remove.

        Returns:
            RemovalStats with counts of removed and pruned items.
        """
        ...

    @abstractmethod
    def merge_entities(self, canonical: str, duplicate: str) -> None:
        """Merge duplicate entity into canonical entity.

        Transfers all triples referencing duplicate to reference canonical.
        Merges sources, aliases, and raw_mentions lists. Keeps the higher
        mention_count. Deletes the duplicate entity.

        Args:
            canonical: Name of the entity to keep.
            duplicate: Name of the entity to absorb and delete.

        Raises:
            KeyError: If either entity does not exist.
        """
        ...
```

### Implementation Notes

- `RemovalStats` is added to `common/schemas.py` alongside `Entity`, `Triple`, etc.
- Add `RemovalStats` to `__all__` in `common/schemas.py`.
- `merge_entities` is also added here (used by T40) to keep the ABC changes in one task.
- The import of `RemovalStats` in `backend.py` must be added to the existing import line.

---

## T33: NetworkXBackend.remove_by_source() Implementation

**Req:** REQ-KG-731
**File(s):** `src/knowledge_graph/backends/networkx_backend.py`
**Depends on:** T32

### Contract

```python
# --- src/knowledge_graph/backends/networkx_backend.py ---

class NetworkXBackend(GraphStorageBackend):
    # ... existing methods ...

    def remove_by_source(self, source_key: str) -> RemovalStats:
        """Remove source_key from all nodes and edges in the NetworkX graph.

        Algorithm:
        1. Iterate all edges. For each edge with source_key in its sources:
           a. Remove source_key from the edge's sources list.
           b. If sources list is now empty, mark edge for deletion.
        2. Delete marked edges.
        3. Iterate all nodes. For each node with source_key in its sources:
           a. Remove source_key from the node's sources list.
           b. If sources list is now empty, mark node for deletion.
        4. Delete marked nodes.
        5. Rebuild _case_index and _aliases to remove stale references.
        6. Return RemovalStats.

        Edges are processed before nodes to avoid dangling edge references.
        """
        ...

    def merge_entities(self, canonical: str, duplicate: str) -> None:
        """Merge duplicate into canonical in the NetworkX graph.

        Algorithm:
        1. Resolve both names via _resolve().
        2. Get node data for both entities.
        3. Transfer all edges (in/out) from duplicate to canonical:
           - For each edge involving duplicate, create equivalent edge
             with canonical, merging sources lists.
        4. Merge metadata: union of sources, aliases (add duplicate's name
           to canonical's aliases), raw_mentions. Keep max mention_count.
        5. Remove duplicate node from graph.
        6. Update _case_index and _aliases.
        """
        ...
```

### Implementation Notes

- Edge iteration must use `list(self.graph.edges(data=True))` to avoid mutation-during-iteration.
- Node iteration must similarly snapshot via `list(self.graph.nodes(data=True))`.
- After all removals, call `self._rebuild_indexes()` (or inline the rebuild logic for `_case_index` and `_aliases`).
- For `merge_entities`, when transferring edges, check for pre-existing edges between canonical and the edge's other endpoint. If one exists, merge the sources lists rather than creating a duplicate edge.

---

## T34: Neo4jBackend.remove_by_source() Implementation

**Req:** REQ-KG-732
**File(s):** `src/knowledge_graph/backends/neo4j_backend.py`
**Depends on:** T32

### Contract

```python
# --- src/knowledge_graph/backends/neo4j_backend.py ---

class Neo4jBackend(GraphStorageBackend):
    # ... existing methods ...

    def remove_by_source(self, source_key: str) -> RemovalStats:
        """Remove source_key from all entities and relationships in Neo4j.

        Executes within a single write transaction for atomicity.

        Cypher operations:
        1. Remove source_key from RELATES_TO relationship sources lists.
           Delete relationships whose sources become empty.
        2. Remove source_key from Entity node sources lists.
           DETACH DELETE nodes whose sources become empty.
        3. Collect and return counts.
        """
        ...

    def merge_entities(self, canonical: str, duplicate: str) -> None:
        """Merge duplicate into canonical using a single Cypher transaction.

        Cypher operations within one write transaction:
        1. MATCH both entities by name.
        2. Redirect all relationships from duplicate to canonical
           (both incoming and outgoing), merging sources on existing edges.
        3. Merge metadata lists (sources, aliases, raw_mentions).
        4. Set mention_count to max of both.
        5. Add duplicate's name to canonical's aliases list.
        6. DETACH DELETE duplicate node.
        """
        ...
```

### Implementation Notes

- All Cypher operations within `remove_by_source` must execute in a single write transaction (`session.execute_write()`).
- Use `[x IN node.sources WHERE x <> $source_key]` for list filtering in Cypher.
- Count affected items within the transaction using `RETURN count(...)` before deleting, so `RemovalStats` is accurate.
- For `merge_entities`, use `apoc.refactor.mergeRelationships` if APOC is available, otherwise handle relationship transfer manually with `CREATE` and `DELETE`.

---

## T35: knowledge_graph_storage.py Incremental Wiring

**Req:** REQ-KG-733, REQ-KG-734
**File(s):** `src/ingest/embedding/nodes/knowledge_graph_storage.py`
**Depends on:** T32, T33, T34

### Contract

```python
# --- src/ingest/embedding/nodes/knowledge_graph_storage.py ---

def knowledge_graph_storage_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    """Store processed chunks into the knowledge graph backend.

    Phase 3 addition: when runtime.config.update_mode is True, call
    backend.remove_by_source(state["source_key"]) BEFORE any extraction
    or upsert operations. Log RemovalStats at INFO level.

    In non-update mode (fresh ingestion), remove_by_source is NOT called.
    """
    ...
```

```python
# --- Post-ingestion hook for SV connectivity batch ---

def _run_sv_connectivity_batch(backend: GraphStorageBackend, config: KGConfig) -> None:
    """Run pyverilog batch connectivity step after all per-file extractions.

    Called from the pipeline orchestration layer after all files are processed.

    Algorithm:
    1. Check config.sv_filelist is set and file exists. Skip if not.
    2. If update_mode: remove all triples with source "__sv_connectivity_batch__".
    3. Instantiate SVConnectivityAnalyzer with filelist and top_module config.
    4. Run analysis to produce connects_to triples.
    5. Upsert triples into backend with source="__sv_connectivity_batch__".
    """
    ...
```

### Implementation Notes

- The delete-before-upsert pattern mirrors `embedding_storage.py` lines 43-48.
- `state["source_key"]` is the per-file source identifier (document path).
- The `__sv_connectivity_batch__` synthetic source key is used consistently for all pyverilog-generated triples. This allows full batch removal and regeneration on incremental updates.
- The batch step must run AFTER all per-file `knowledge_graph_storage_node` calls complete. This means it should be wired as a post-processing hook in the pipeline orchestration, not inside the per-file node.
- When `sv_filelist` is not configured, the batch step is skipped silently (no warning).
- When `sv_filelist` points to a non-existent file, log a WARNING and skip.

---

## T36: SVConnectivityAnalyzer

**Req:** REQ-KG-735, REQ-KG-736, REQ-KG-738, REQ-KG-739
**File(s):** `src/knowledge_graph/extraction/sv_connectivity.py` (new file)
**Depends on:** T38 (KGConfig fields for sv_filelist, sv_top_module)

### Contract

```python
# --- src/knowledge_graph/extraction/sv_connectivity.py (new file) ---

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.common.schemas import Triple

__all__ = ["SVConnectivityAnalyzer"]

logger = logging.getLogger("rag.knowledge_graph.extraction.sv_connectivity")

# Synthetic source key for all pyverilog-generated triples
SV_CONNECTIVITY_SOURCE = "__sv_connectivity_batch__"


class SVConnectivityAnalyzer:
    """Cross-module SV port connectivity analysis using pyverilog.

    Accepts a .f filelist path and optional top module name. Uses pyverilog's
    DataflowAnalyzer to resolve cross-module port connections and produce
    connects_to triples.

    Produces ONLY triples — no entity upserts — to prevent duplication
    with tree-sitter entities.
    """

    def __init__(
        self,
        filelist_path: str,
        backend: GraphStorageBackend,
        top_module: Optional[str] = None,
    ) -> None:
        """Initialize with filelist path and optional top module override.

        Args:
            filelist_path: Path to a .f filelist file.
            backend: Graph backend for top-module auto-detection queries.
            top_module: Explicit top module name. If empty/None, auto-detect.
        """
        ...

    def analyze(self) -> List[Triple]:
        """Run pyverilog DataflowAnalyzer and return connects_to triples.

        All returned triples have:
        - predicate = "connects_to"
        - source = SV_CONNECTIVITY_SOURCE ("__sv_connectivity_batch__")
        - extractor_source = "sv_connectivity"

        Returns:
            List of connects_to Triple objects. Empty list on any failure.
        """
        ...

    # ------------------------------------------------------------------
    # Filelist parsing
    # ------------------------------------------------------------------

    @staticmethod
    def parse_filelist(filelist_path: str) -> tuple[List[str], List[str]]:
        """Parse a .f filelist into file paths and include directories.

        Supports:
        - One file path per line
        - // line comments
        - +incdir+<path> include directory directives
        - -f <path> recursive filelist inclusion
        - Relative paths resolved relative to filelist's parent directory

        Args:
            filelist_path: Path to the .f filelist file.

        Returns:
            Tuple of (file_paths, include_dirs).
        """
        ...

    # ------------------------------------------------------------------
    # Top module auto-detection
    # ------------------------------------------------------------------

    def _auto_detect_top_module(self) -> Optional[str]:
        """Auto-detect the top module from the graph backend.

        Heuristic: query all RTL_Module entities and identify modules that
        are never the target of an 'instantiates' edge.

        Returns:
            Module name if exactly one candidate found, None otherwise.
            Logs WARNING if zero or multiple candidates found.
        """
        ...

    # ------------------------------------------------------------------
    # Pyverilog integration
    # ------------------------------------------------------------------

    def _run_pyverilog(
        self,
        file_paths: List[str],
        include_dirs: List[str],
        top_module: str,
    ) -> List[Triple]:
        """Run pyverilog DataflowAnalyzer and extract connectivity triples.

        Gracefully handles:
        - ImportError (pyverilog not installed): WARNING + return []
        - DataflowAnalyzer exceptions: WARNING + return []

        Returns:
            List of connects_to triples.
        """
        ...
```

### Implementation Notes

- pyverilog import must be guarded with try/except for graceful degradation (REQ-KG-739).
- The `.f` filelist parser is a static method so it can be tested independently.
- Relative paths in the filelist are resolved relative to `Path(filelist_path).parent`, NOT `os.getcwd()`.
- `-f sub_filelist.f` directives are resolved recursively. Guard against circular references with a visited-set.
- The analyzer queries the backend for `RTL_Module` entities and `instantiates` edges for auto-detection. This requires the backend to be populated from tree-sitter extraction first.
- Each `connects_to` triple maps a source Port/Signal entity to a target Port/Signal entity. Entity names must match the canonical names already in the graph (from tree-sitter extraction).
- Use `connects_to` (NOT `connected_to`) everywhere.

---

## T37: SV Connectivity Batch Step Wiring

**Req:** REQ-KG-737, REQ-KG-734
**File(s):** `src/knowledge_graph/__init__.py` or pipeline orchestration
**Depends on:** T35, T36

### Contract

```python
# --- Integration point: called after all per-file extractions complete ---

def run_post_ingestion_steps(
    backend: GraphStorageBackend,
    config: KGConfig,
    update_mode: bool = False,
) -> None:
    """Execute post-ingestion batch steps.

    Ordering:
    1. SV connectivity batch (if sv_filelist configured)
    2. Entity resolution (if enabled) — T40
    3. Community detection (hierarchical Leiden) — T41

    Args:
        backend: Populated graph backend.
        config: KG runtime configuration.
        update_mode: Whether this is an incremental update run.
    """
    # Step 1: SV connectivity
    if config.sv_filelist:
        filelist_path = Path(config.sv_filelist)
        if not filelist_path.is_file():
            logger.warning(
                "sv_filelist configured but file not found: %s — skipping",
                config.sv_filelist,
            )
        else:
            if update_mode:
                # Remove previous batch triples before regenerating
                stats = backend.remove_by_source(SV_CONNECTIVITY_SOURCE)
                logger.info("Removed previous SV connectivity: %s", stats)
            analyzer = SVConnectivityAnalyzer(
                filelist_path=config.sv_filelist,
                backend=backend,
                top_module=config.sv_top_module or None,
            )
            triples = analyzer.analyze()
            if triples:
                backend.upsert_triples(triples)
                logger.info("SV connectivity: upserted %d connects_to triples", len(triples))

    # Step 2: Entity resolution (T40)
    # Step 3: Hierarchical Leiden (T41)
    ...
```

### Implementation Notes

- This function serves as the Phase 3 post-ingestion orchestrator. It must be called from the pipeline after all per-file nodes have executed.
- The ordering is critical: SV connectivity first (produces new triples), then entity resolution (deduplicates entities), then community detection (clusters resolved entities).
- Each step is independently skippable via config flags.
- The batch step runs on the FULL filelist every time (not incrementally per-file), because pyverilog requires all-files context for cross-module elaboration.

---

## T38: KGConfig Phase 3 Fields

**Req:** REQ-KG-740, REQ-KG-750, REQ-KG-751 (community_max_levels)
**File(s):** `src/knowledge_graph/common/types.py`, `config/settings.py`
**Depends on:** None (foundation task)

### Contract

```python
# --- Delta to src/knowledge_graph/common/types.py — KGConfig dataclass ---

@dataclass
class KGConfig:
    # ... existing Phase 1 / 1b / 2 fields unchanged ...

    # Phase 3: SV connectivity (pyverilog)
    sv_filelist: str = ""
    """Path to .f filelist for pyverilog batch connectivity analysis.
    Empty string disables the batch step. Env: RAG_KG_SV_FILELIST."""

    sv_top_module: str = ""
    """Explicit top module name for pyverilog. Empty = auto-detect.
    Env: RAG_KG_SV_TOP_MODULE."""

    # Phase 3: Entity resolution
    enable_entity_resolution: bool = False
    """Enable embedding-based entity deduplication. Default off for safety.
    Env: RAG_KG_ENABLE_ENTITY_RESOLUTION."""

    entity_resolution_threshold: float = 0.85
    """Cosine similarity threshold for embedding-based merges.
    Range: (0.0, 1.0]. Env: RAG_KG_RESOLUTION_THRESHOLD."""

    entity_resolution_alias_path: str = "config/kg_aliases.yaml"
    """Path to YAML alias table for deterministic merges.
    Env: RAG_KG_RESOLUTION_ALIAS_PATH."""

    # Phase 3: Hierarchical community detection
    community_max_levels: int = 3
    """Maximum hierarchy depth for recursive Leiden partitioning.
    1 = flat (backward compatible). Env: RAG_KG_COMMUNITY_MAX_LEVELS."""
```

```python
# --- Delta to KGConfig.__post_init__ ---

def __post_init__(self) -> None:
    # ... existing Phase 2 validations ...
    if not (0.0 < self.entity_resolution_threshold <= 1.0):
        raise ValueError(
            f"entity_resolution_threshold must be in (0.0, 1.0], "
            f"got {self.entity_resolution_threshold}"
        )
    if self.community_max_levels < 1:
        raise ValueError(
            f"community_max_levels must be >= 1, got {self.community_max_levels}"
        )
```

```python
# --- Delta to config/settings.py — new env var bindings ---

RAG_KG_SV_FILELIST = os.environ.get("RAG_KG_SV_FILELIST", "")
RAG_KG_SV_TOP_MODULE = os.environ.get("RAG_KG_SV_TOP_MODULE", "")
RAG_KG_ENABLE_ENTITY_RESOLUTION = os.environ.get(
    "RAG_KG_ENABLE_ENTITY_RESOLUTION", "false"
).lower() in ("true", "1", "yes")
RAG_KG_RESOLUTION_THRESHOLD = float(
    os.environ.get("RAG_KG_RESOLUTION_THRESHOLD", "0.85")
)
RAG_KG_RESOLUTION_ALIAS_PATH = os.environ.get(
    "RAG_KG_RESOLUTION_ALIAS_PATH", "config/kg_aliases.yaml"
)
RAG_KG_COMMUNITY_MAX_LEVELS = int(
    os.environ.get("RAG_KG_COMMUNITY_MAX_LEVELS", "3")
)
```

### Implementation Notes

- Add `VALID_PHASES` update: include `"phase_3"` in the valid phases set for schema validation if needed, or keep Phase 3 features activated by config flags rather than runtime_phase.
- All new fields have safe defaults that preserve Phase 2 behavior (entity resolution off, community_max_levels=3 produces hierarchy but 1 would be backward-compatible -- the default of 3 is acceptable because detect() handles it transparently).
- Config validation must fail fast with clear error messages for out-of-range values.

---

## T39: export_html (Sigma.js Visualization)

**Req:** REQ-KG-741, REQ-KG-742, REQ-KG-743, REQ-KG-744, REQ-KG-745
**File(s):** `src/knowledge_graph/export/sigma_export.py` (new file), `src/knowledge_graph/__init__.py`
**Depends on:** T41 (hierarchical communities, for community grouping)

### Contract

```python
# --- src/knowledge_graph/export/sigma_export.py (new file) ---

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.knowledge_graph.community.detector import CommunityDetector

from src.knowledge_graph.backend import GraphStorageBackend

__all__ = ["export_html"]

logger = logging.getLogger("rag.knowledge_graph.export.sigma")

# HTML template with embedded Sigma.js v3 + graphology from CDN.
# Loaded from unpkg CDN — no pip dependency.
_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>RagWeave Knowledge Graph</title>
  <script src="https://unpkg.com/graphology@0.25.4/dist/graphology.umd.min.js"></script>
  <script src="https://unpkg.com/sigma@3/build/sigma.min.js"></script>
  <script src="https://unpkg.com/graphology-layout-forceatlas2@0.10.1/dist/graphology-layout-forceatlas2.umd.min.js"></script>
  <style>
    /* Full-viewport graph canvas, search box, legend */
    ...
  </style>
</head>
<body>
  <div id="search-container">
    <input id="search-input" type="text" placeholder="Search entities..." />
  </div>
  <div id="graph-container"></div>
  <div id="legend"></div>
  <script>
    const graphData = __GRAPH_DATA__;
    // Initialize graphology graph, add nodes/edges from graphData
    // Apply ForceAtlas2 layout
    // Initialize Sigma renderer
    // Wire search, hover tooltips, zoom/pan
    ...
  </script>
</body>
</html>"""


def export_html(
    backend: GraphStorageBackend,
    output_path: str,
    community_detector: Optional["CommunityDetector"] = None,
) -> int:
    """Generate a self-contained interactive HTML graph visualization.

    The output is a single HTML file with:
    - Graph data embedded as inline JSON
    - Sigma.js v3 and graphology loaded from CDN
    - ForceAtlas2 layout for spatial clustering
    - Node coloring by community (if detector provided) or entity type
    - Node size proportional to mention_count or degree
    - Edge styling by predicate type (connects_to visually distinct)
    - Search box with substring filtering
    - Hover tooltips (name, type, sources, relationship count)
    - Zoom and pan controls

    Args:
        backend: Graph storage backend to export from.
        output_path: Path for the output HTML file.
        community_detector: Optional detector for community-based coloring
            and spatial grouping. Falls back to type-based coloring if None
            or not ready.

    Returns:
        Number of nodes rendered.
    """
    ...


def _build_graph_json(
    backend: GraphStorageBackend,
    community_detector: Optional["CommunityDetector"] = None,
) -> Dict[str, Any]:
    """Build the graph data structure for Sigma.js rendering.

    Returns:
        Dict with keys:
        - "nodes": List of {id, label, type, community, size, color, ...}
        - "edges": List of {source, target, predicate, color, type, ...}
        - "legend": {type_colors: {...}, edge_styles: {...}}
    """
    ...


# Edge style categories
_EDGE_STYLES: Dict[str, Dict[str, str]] = {
    "connects_to":  {"color": "#e74c3c", "type": "dashed"},   # Red dashed — port connectivity
    "contains":     {"color": "#95a5a6", "type": "solid"},     # Gray — structural hierarchy
    "instantiates": {"color": "#3498db", "type": "solid"},     # Blue — instantiation
    "specified_by": {"color": "#2ecc71", "type": "dotted"},    # Green dotted — semantic
    "relates_to":   {"color": "#9b59b6", "type": "dotted"},    # Purple dotted — semantic
}

# Deterministic color palette for entity types (hashed from type name)
_TYPE_COLORS: Dict[str, str]  # Populated at module load from kg_schema node types
```

### Implementation Notes

- The HTML template is a Python multiline string embedded in the module. No external template file.
- `__GRAPH_DATA__` placeholder is replaced with `json.dumps(graph_data)` via string substitution.
- Node color logic: if `community_detector` is provided and `is_ready`, color by community ID using a deterministic palette. Otherwise color by entity type.
- Node size: `max(3, min(20, entity.mention_count or graph_degree))` for reasonable visual range.
- `connects_to` edges are red and dashed to be visually distinct from structural (gray solid) and semantic (dotted) edges.
- ForceAtlas2 layout is run client-side via graphology-layout-forceatlas2. This naturally clusters connected nodes.
- When hierarchical communities are available, inject community-level metadata into node data so the JS can group nodes spatially and enable zoom-based level selection.
- The search box dims non-matching nodes (set opacity to 0.1) rather than hiding them.
- Hover tooltip is a CSS-positioned div updated on Sigma's `enterNode` event.
- Add `export_html` to `__all__` in `src/knowledge_graph/__init__.py`.
- Target performance: usable for graphs up to 5,000 nodes. For larger graphs, consider adding a sampling/filtering option in a future phase.

---

## T40: Entity Resolution Pipeline

**Req:** REQ-KG-746, REQ-KG-747, REQ-KG-748, REQ-KG-749, REQ-KG-750
**File(s):**
- `src/knowledge_graph/resolution/__init__.py` (new package)
- `src/knowledge_graph/resolution/resolver.py` (new)
- `src/knowledge_graph/resolution/embedding_resolver.py` (new)
- `src/knowledge_graph/resolution/alias_resolver.py` (new)
- `src/knowledge_graph/resolution/schemas.py` (new)
**Depends on:** T32 (merge_entities on ABC), T33/T34 (backend implementations), T38 (config fields)

### Contract

```python
# --- src/knowledge_graph/resolution/schemas.py ---

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List

__all__ = ["MergeCandidate", "MergeReport"]


@dataclass
class MergeCandidate:
    """A pair of entities identified for merging.

    Attributes:
        canonical: Name of the entity to keep.
        duplicate: Name of the entity to absorb.
        similarity: Cosine similarity score (1.0 for alias matches).
        reason: Human-readable merge reason ("alias_table" or "embedding_similarity").
    """
    canonical: str
    duplicate: str
    similarity: float
    reason: str


@dataclass
class MergeReport:
    """Results from a full entity resolution pass.

    Attributes:
        merges: Ordered list of merge operations performed.
        total_merged: Count of entities absorbed (= len(merges)).
    """
    merges: List[MergeCandidate] = field(default_factory=list)
    total_merged: int = 0
```

```python
# --- src/knowledge_graph/resolution/resolver.py ---

from __future__ import annotations
import logging
from typing import TYPE_CHECKING

from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.common.types import KGConfig
from src.knowledge_graph.resolution.schemas import MergeCandidate, MergeReport

__all__ = ["EntityResolver"]

logger = logging.getLogger("rag.knowledge_graph.resolution")


class EntityResolver:
    """Orchestrates entity resolution: alias merges first, then embedding-based.

    Controlled by KGConfig.enable_entity_resolution (default False).
    When disabled, resolve() returns an empty MergeReport.
    """

    def __init__(self, backend: GraphStorageBackend, config: KGConfig) -> None:
        """Initialize with graph backend and configuration.

        Args:
            backend: Graph storage backend containing entities to resolve.
            config: KG config with resolution threshold and alias path.
        """
        ...

    def resolve(self) -> MergeReport:
        """Run the full entity resolution pipeline.

        Algorithm:
        1. Run AliasResolver to produce deterministic merge candidates.
        2. Execute alias merges via backend.merge_entities().
        3. Run EmbeddingResolver to produce fuzzy merge candidates.
        4. Execute embedding merges via backend.merge_entities().
        5. Return consolidated MergeReport.

        Alias merges run first to reduce the candidate set for embedding
        comparison (fewer entities = fewer pairwise comparisons).

        Returns:
            MergeReport with all merge operations performed.
        """
        ...
```

```python
# --- src/knowledge_graph/resolution/embedding_resolver.py ---

from __future__ import annotations
import logging
from typing import Dict, List

from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.resolution.schemas import MergeCandidate

__all__ = ["EmbeddingResolver"]

logger = logging.getLogger("rag.knowledge_graph.resolution.embedding")


class EmbeddingResolver:
    """Find merge candidates using embedding cosine similarity.

    Type-constrained: only entities of the same type are compared.
    Uses the configured embedding model (EMBEDDING_MODEL_PATH).

    When EMBEDDING_MODEL_PATH is not set, logs WARNING and returns
    no candidates.
    """

    def __init__(self, threshold: float = 0.85) -> None:
        """Initialize with similarity threshold.

        Args:
            threshold: Minimum cosine similarity for a merge candidate.
                Must be in (0.0, 1.0].
        """
        ...

    def find_candidates(
        self, backend: GraphStorageBackend
    ) -> List[MergeCandidate]:
        """Load entities, compute embeddings, find merge candidates.

        Algorithm:
        1. Load all entities from backend.
        2. Group entities by type.
        3. For each type bucket with 2+ entities:
           a. Compute embeddings for all entity names.
           b. Compute pairwise cosine similarity (numpy batch).
           c. For each pair above threshold, emit MergeCandidate.
              Canonical = entity with higher mention_count.
        4. Return deduplicated candidates.

        Returns:
            List of MergeCandidate objects.
        """
        ...
```

```python
# --- src/knowledge_graph/resolution/alias_resolver.py ---

from __future__ import annotations
import logging
from pathlib import Path
from typing import Dict, List

import yaml

from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.resolution.schemas import MergeCandidate

__all__ = ["AliasResolver"]

logger = logging.getLogger("rag.knowledge_graph.resolution.alias")


class AliasResolver:
    """Find merge candidates using a YAML alias table.

    Alias table format (config/kg_aliases.yaml):
        - canonical: "AXI4_Arbiter"
          aliases:
            - "axi4_arb"
            - "AXI_ARB"
        - canonical: "EthernetController"
          aliases:
            - "eth_ctrl"
            - "ethernet_ctrl"

    Matching is case-insensitive.
    """

    def __init__(self, alias_path: str = "config/kg_aliases.yaml") -> None:
        """Initialize with alias table path.

        Args:
            alias_path: Path to YAML alias table. If file does not exist,
                logs WARNING and operates with empty table.
        """
        ...

    def find_candidates(
        self, backend: GraphStorageBackend
    ) -> List[MergeCandidate]:
        """Match entity names against alias table entries.

        For each entity whose name (case-insensitive) matches an alias
        in a group, produce a MergeCandidate toward the group's canonical
        name. Only produces candidates where both canonical and alias
        entities actually exist in the backend.

        Returns:
            List of MergeCandidate with reason="alias_table", similarity=1.0.
        """
        ...
```

### Implementation Notes

- Entity resolution runs AFTER all extraction (including SV connectivity batch) and BEFORE community detection. This ordering is enforced in `run_post_ingestion_steps()` (T37).
- The `EmbeddingResolver` loads the embedding model from `EMBEDDING_MODEL_PATH` (same model as the vector pipeline). If not available, it logs a WARNING and returns empty candidates.
- For pairwise cosine similarity, use numpy broadcasting: `similarities = embeddings @ embeddings.T` after L2 normalization. This handles 1000 entities per type in milliseconds.
- `merge_entities()` is called iteratively for each candidate. Order matters: merge alias candidates first, then embedding candidates. After alias merges, some embedding candidates may become invalid (entity already merged). Check existence before each merge.
- The alias YAML format is a list of groups, each with `canonical` (str) and `aliases` (list of str).
- When the alias file does not exist, `AliasResolver` logs a WARNING and returns no candidates (does not raise).

---

## T41: Hierarchical Leiden Community Detection

**Req:** REQ-KG-751, REQ-KG-752, REQ-KG-754
**File(s):** `src/knowledge_graph/community/detector.py`, `src/knowledge_graph/community/schemas.py`
**Depends on:** T38 (community_max_levels config), T40 (entity resolution should complete first)

### Contract

```python
# --- Delta to src/knowledge_graph/community/schemas.py ---

@dataclass
class CommunitySummary:
    """Summarised representation of a single community cluster.

    Phase 3 addition: level field for hierarchical community support.
    """
    community_id: int
    summary_text: str
    member_count: int
    member_names: List[str] = field(default_factory=list)
    generated_at: str = ""
    level: int = 0  # NEW: hierarchy level (0 = coarsest)
```

```python
# --- Delta to src/knowledge_graph/community/detector.py ---

from typing import Dict, List, Optional, Set, Tuple

class CommunityDetector:
    """Extended for hierarchical multi-level Leiden partitioning.

    Phase 3 additions:
    - _hierarchical_communities: Dict[Tuple[int, int], List[str]]
      Maps (level, community_id) -> [member_names]
    - _parent_map: Dict[Tuple[int, int], Tuple[int, int]]
      Maps (level, cid) -> (parent_level, parent_cid)
    """

    def __init__(
        self,
        backend: GraphStorageBackend,
        config: KGConfig,
        graph_path: Optional[str] = None,
    ) -> None:
        # ... existing init plus:
        self._hierarchical_communities: Dict[Tuple[int, int], List[str]] = {}
        self._parent_map: Dict[Tuple[int, int], Tuple[int, int]] = {}
        ...

    def detect(self) -> Dict[int, List[str]]:
        """Run hierarchical Leiden community detection.

        Phase 3 behavior:
        - When community_max_levels == 1: identical to Phase 2 flat Leiden.
        - When community_max_levels > 1: recursive partitioning.

        Algorithm for hierarchical mode:
        1. Run Leiden at level 0 (coarsest) on the full graph.
        2. For each community at level 0 with size > community_min_size:
           a. Extract subgraph for community members.
           b. Run Leiden on the subgraph to produce level 1 sub-communities.
           c. Record parent_map entries: (1, sub_cid) -> (0, parent_cid).
        3. Repeat recursively up to community_max_levels.
        4. Stop recursion when:
           - Community size < community_min_size, OR
           - Leiden returns a single community for the subgraph, OR
           - Max levels reached.

        Returns:
            Level-0 community dict {cid: [members]} for backward compatibility.
            Full hierarchy available via hierarchical_communities property.
        """
        ...

    @property
    def hierarchical_communities(self) -> Dict[Tuple[int, int], List[str]]:
        """Full hierarchical partition: {(level, cid): [member_names]}.

        Level 0 is coarsest (fewest, largest communities).
        Deeper levels are finer sub-partitions.
        """
        return self._hierarchical_communities

    @property
    def parent_map(self) -> Dict[Tuple[int, int], Tuple[int, int]]:
        """Hierarchy links: {(level, cid): (parent_level, parent_cid)}.

        Every community at level N > 0 maps to exactly one parent at level N-1.
        Level 0 communities have no parent entries.
        """
        return self._parent_map

    def get_communities_at_level(self, level: int) -> Dict[int, List[str]]:
        """Return communities at a specific hierarchy level.

        Args:
            level: Hierarchy level (0 = coarsest).

        Returns:
            Dict of {cid: [members]} for the requested level.
            Empty dict if level does not exist.
        """
        ...

    # ------------------------------------------------------------------
    # Sidecar persistence (extended for hierarchy)
    # ------------------------------------------------------------------

    def save_sidecar(self) -> None:
        """Persist hierarchical communities and summaries to sidecar JSON.

        Sidecar format v2:
        {
            "version": 2,
            "hierarchical_communities": {
                "0,0": ["entityA", "entityB", ...],
                "0,1": ["entityC", ...],
                "1,0": ["entityA"],
                ...
            },
            "parent_map": {
                "1,0": "0,0",
                "1,1": "0,0",
                ...
            },
            "summaries": { ... per-level summaries ... },
            "previous_assignments": { ... }
        }

        Keys use "level,cid" string format for JSON compatibility.
        """
        ...

    def _load_sidecar(self) -> None:
        """Load sidecar with backward compatibility.

        - version 2: full hierarchical data
        - version 1 (or missing version): treat all data as level 0
        """
        ...
```

### Implementation Notes

- The `detect()` return type remains `Dict[int, List[str]]` for backward compatibility (returns level-0 communities). Full hierarchy is available via `hierarchical_communities` property.
- Recursive partitioning: for each level-0 community, extract the subgraph (igraph induced subgraph), run Leiden on it, and record the sub-communities as level 1. Repeat for level 1 communities to get level 2, etc.
- Every member at level N must be a subset of exactly one community at level N-1. This is guaranteed by the subgraph extraction approach.
- `_apply_min_size` applies at each level independently.
- Sidecar backward compatibility: loading a v1 sidecar (no `hierarchical_communities` key) treats all summaries/assignments as level 0 and populates `_hierarchical_communities` with `{(0, cid): members}`.
- The `CommunitySummarizer` (existing Phase 2 code) needs a minor update to accept a `levels` parameter controlling which levels are summarized. Default: levels 0 and 1.

---

## T42: Query Expander Updates

**Req:** REQ-KG-756, REQ-KG-753
**File(s):** `src/knowledge_graph/query/expander.py`
**Depends on:** T41 (hierarchical communities), T36 (connects_to edges)

### Contract

```python
# --- Delta to src/knowledge_graph/query/expander.py ---

class GraphQueryExpander:
    """Phase 3 additions to query expansion."""

    def expand(self, query: str, depth: Optional[int] = None) -> List[str]:
        """Return related entity names to augment the search query.

        Phase 3 additions:

        1. Multi-hop for connects_to (REQ-KG-756):
           After matching seed entities, check if any has connects_to edges.
           If yes, use max(depth, 2) to enable port->signal->port traversal.
           Log depth adjustment at DEBUG level.

        2. Hierarchical level selection (REQ-KG-753):
           When hierarchical communities are available:
           - 0 matched entities -> use level 0 (coarsest) community summaries
           - 1-2 matched entities -> use level 1 (mid-level)
           - 3+ matched entities -> use deepest available level
           When only flat communities are available, fall back to flat expansion.
        """
        ...

    def _has_connects_to_edges(self, entity_name: str) -> bool:
        """Check if entity has any connects_to edges in the graph.

        Args:
            entity_name: Canonical entity name.

        Returns:
            True if at least one outgoing or incoming edge has
            predicate == "connects_to".
        """
        outgoing = self._backend.get_outgoing_edges(entity_name)
        incoming = self._backend.get_incoming_edges(entity_name)
        return any(
            e.predicate == "connects_to" for e in outgoing + incoming
        )

    def _select_community_level(self, num_matches: int) -> int:
        """Select community hierarchy level based on query specificity.

        Heuristic:
        - 0 matches: level 0 (broadest communities for broad queries)
        - 1-2 matches: level 1
        - 3+ matches: deepest available level

        Args:
            num_matches: Number of entities matched in the query.

        Returns:
            Hierarchy level to use for community expansion.
        """
        ...

    def _expand_with_communities(
        self, seed_entities: List[str], existing_terms: set[str]
    ) -> List[str]:
        """Extended for hierarchical community support.

        Phase 3: uses _select_community_level() to pick the right
        hierarchy level for community term extraction.
        Falls back to flat expansion when hierarchical data is unavailable.
        """
        ...
```

### Implementation Notes

- The `connects_to` depth adjustment is conservative: `max(configured_depth, 2)`. It only activates when at least one seed entity has `connects_to` edges. This ensures standard queries are not affected.
- Level selection is deterministic for the same query and graph state (same number of matches -> same level).
- The expander must handle the case where the community detector has hierarchical data but the requested level does not exist (fall back to the deepest available level).
- `_has_connects_to_edges` checks both outgoing and incoming edges. This is important because a port may be the target of a `connects_to` edge rather than the source.

---

## T43: pyproject.toml and requirements.txt

**Req:** REQ-KG-755
**File(s):** `pyproject.toml`, `requirements.txt`
**Depends on:** None (foundation task, can run in parallel with T38)

### Contract

```toml
# --- Delta to pyproject.toml ---

[project]
dependencies = [
    # ... existing dependencies ...
    "tree-sitter",
    "tree-sitter-verilog",
    "pyverilog",
]

[project.optional-dependencies]
# ... existing optional groups ...
kg-community = ["igraph", "leidenalg"]
kg-neo4j = ["neo4j"]
all = [
    # ... existing all entries ...
    "igraph",
    "leidenalg",
    "neo4j",
]
```

```
# --- Delta to requirements.txt ---
# Add to default section:
tree-sitter
tree-sitter-verilog
pyverilog

# Add to optional section (commented):
# kg-community:
# igraph
# leidenalg
# kg-neo4j:
# neo4j
```

### Implementation Notes

- `tree-sitter`, `tree-sitter-verilog`, and `pyverilog` go into default dependencies because they are lightweight and central to an ASIC-focused tool.
- `igraph` and `leidenalg` go into `kg-community` optional group because `leidenalg` has C extensions that can be tricky to build on some platforms.
- `neo4j` goes into `kg-neo4j` optional group because it is useless without a running Neo4j server.
- Existing try/except import guards in `detector.py` (igraph/leidenalg), `neo4j_backend.py` (neo4j), and the new `sv_connectivity.py` (pyverilog) MUST be preserved for graceful degradation.
- The `all` optional group must include all new optional dependencies.
- Version pins may be added during implementation based on compatibility testing.

---

## Cross-Task Dependency Summary

| Task | Depends On | Parallelism Group |
|------|-----------|-------------------|
| T32 | None | A (foundation) |
| T38 | None | A (foundation) |
| T43 | None | A (foundation) |
| T33 | T32 | B |
| T34 | T32 | B (parallel with T33) |
| T36 | T38 | B |
| T35 | T32, T33, T34 | C |
| T37 | T35, T36 | D |
| T40 | T32, T33, T34, T38 | C (parallel with T35) |
| T41 | T38, T40 | D |
| T39 | T41 | E |
| T42 | T41, T36 | E (parallel with T39) |

**Minimum critical path:** T38 -> T32 -> T33 -> T40 -> T41 -> T42

---

## Requirement Traceability Matrix

| REQ | Task(s) | Priority |
|-----|---------|----------|
| REQ-KG-730 | T32 | MUST |
| REQ-KG-731 | T33 | MUST |
| REQ-KG-732 | T34 | MUST |
| REQ-KG-733 | T35 | MUST |
| REQ-KG-734 | T35, T37 | MUST |
| REQ-KG-735 | T36 | MUST |
| REQ-KG-736 | T36 | MUST |
| REQ-KG-737 | T37 | MUST |
| REQ-KG-738 | T36 | MUST |
| REQ-KG-739 | T36 | SHOULD |
| REQ-KG-740 | T38 | MUST |
| REQ-KG-741 | T39 | MUST |
| REQ-KG-742 | T39 | MUST |
| REQ-KG-743 | T39 | MUST |
| REQ-KG-744 | T39 | SHOULD |
| REQ-KG-745 | T39 | MUST |
| REQ-KG-746 | T40 | MUST |
| REQ-KG-747 | T40 | MUST |
| REQ-KG-748 | T40 | MUST |
| REQ-KG-749 | T32, T33, T34 | MUST |
| REQ-KG-750 | T38, T40 | MUST |
| REQ-KG-751 | T41 | MUST |
| REQ-KG-752 | T41 | MUST |
| REQ-KG-753 | T42 | SHOULD |
| REQ-KG-754 | T41 | MUST |
| REQ-KG-755 | T43 | MUST |
| REQ-KG-756 | T42 | SHOULD |
