# KG Phase 2 Design — Task Decomposition and Code Contracts

**Date:** 2026-04-08
**Status:** Draft
**Parent:** `KNOWLEDGE_GRAPH_SPEC.md` Appendix D (REQ-KG-704 through REQ-KG-729)
**Companion:** `2026-04-08-kg-phase2-sketch.md` (approved design sketch)
**Scope:** REQ-KG-700, REQ-KG-701, REQ-KG-702, REQ-KG-703, REQ-KG-609, REQ-KG-505, REQ-KG-313, REQ-KG-704 through REQ-KG-729

---

## Overview

This document decomposes Phase 2 into eleven implementation tasks with full code contracts (typed Python signatures), dependency lists, files modified, requirement traceability, and LOC estimates. Each task is independently testable against the acceptance criteria defined in the spec.

Task IDs continue from Phase 1b (which ended at T1b-5 / T20). Phase 2 tasks are numbered T21 through T31.

**Total estimated LOC:** ~1,075 (MUST/SHOULD: ~775, MAY: ~220, integration: ~80).

---

## T21: KGConfig Phase 2 Extensions

**Estimated LOC:** ~15 (delta to existing file) + ~20 (env var bindings)
**File(s):** `src/knowledge_graph/common/types.py`, `config/settings.py`
**Parallelism group:** A (foundation, no dependencies)

### Summary

Add all Phase 2 configuration fields to the `KGConfig` dataclass and add corresponding environment variable bindings in `config/settings.py`. This unblocks every other Phase 2 task.

### Requirements Covered

| REQ | Priority | Description |
|-----|----------|-------------|
| REQ-KG-729 | MUST | KGConfig Phase 2 field extensions |

### Dependencies

None. This is the foundation task.

### Contract

```python
# Delta to src/knowledge_graph/common/types.py — KGConfig dataclass

@dataclass
class KGConfig:
    # ... existing Phase 1 / 1b fields unchanged ...

    # Phase 2: Community detection
    community_resolution: float = 1.0
    """Leiden resolution parameter. Higher = more, smaller communities."""

    community_min_size: int = 3
    """Minimum entities per community; smaller clusters merge to community_id=-1."""

    # Phase 2: Community summarization
    community_summary_input_max_tokens: int = 4096
    """Max token budget for concatenated entity descriptions in LLM prompt."""

    community_summary_output_max_tokens: int = 512
    """max_tokens passed to LLM call for summary generation."""

    community_summary_temperature: float = 0.2
    """LLM temperature for community summarization calls."""

    community_summary_max_workers: int = 4
    """ThreadPoolExecutor worker count for parallel summarization."""

    # Phase 2: Neo4j backend
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_auth_user: str = "neo4j"
    neo4j_auth_password: str = ""
    neo4j_database: str = "neo4j"

    # Phase 2: Optional parsers
    enable_python_parser: bool = False
    enable_bash_parser: bool = False
```

```python
# Delta to config/settings.py — new env var bindings in KG section

RAG_KG_ENABLE_GLOBAL_RETRIEVAL = os.environ.get(
    "KG_ENABLE_GLOBAL_RETRIEVAL", "false"
).lower() in ("true", "1", "yes")
RAG_KG_COMMUNITY_RESOLUTION = float(
    os.environ.get("KG_COMMUNITY_RESOLUTION", "1.0")
)
RAG_KG_COMMUNITY_MIN_SIZE = int(
    os.environ.get("KG_COMMUNITY_MIN_SIZE", "3")
)
RAG_KG_COMMUNITY_SUMMARY_INPUT_MAX_TOKENS = int(
    os.environ.get("KG_COMMUNITY_SUMMARY_INPUT_MAX_TOKENS", "4096")
)
RAG_KG_COMMUNITY_SUMMARY_OUTPUT_MAX_TOKENS = int(
    os.environ.get("KG_COMMUNITY_SUMMARY_OUTPUT_MAX_TOKENS", "512")
)
RAG_KG_COMMUNITY_SUMMARY_TEMPERATURE = float(
    os.environ.get("KG_COMMUNITY_SUMMARY_TEMPERATURE", "0.2")
)
RAG_KG_COMMUNITY_SUMMARY_MAX_WORKERS = int(
    os.environ.get("KG_COMMUNITY_SUMMARY_MAX_WORKERS", "4")
)
RAG_KG_NEO4J_URI = os.environ.get("KG_NEO4J_URI", "bolt://localhost:7687")
RAG_KG_NEO4J_AUTH_USER = os.environ.get("KG_NEO4J_AUTH_USER", "neo4j")
RAG_KG_NEO4J_AUTH_PASSWORD = os.environ.get("KG_NEO4J_AUTH_PASSWORD", "")
RAG_KG_NEO4J_DATABASE = os.environ.get("KG_NEO4J_DATABASE", "neo4j")
RAG_KG_ENABLE_PYTHON_PARSER = os.environ.get(
    "KG_ENABLE_PYTHON_PARSER", "false"
).lower() in ("true", "1", "yes")
RAG_KG_ENABLE_BASH_PARSER = os.environ.get(
    "KG_ENABLE_BASH_PARSER", "false"
).lower() in ("true", "1", "yes")
```

### Implementation Notes

- `enable_global_retrieval` already exists on `KGConfig` (default False). No change needed for that field; only add the env var binding.
- Config validation: reject `community_min_size < 1` and `community_resolution <= 0` in a new `__post_init__` check on `KGConfig`.
- `neo4j_auth_password` must be masked in any debug/logging output. Add a `__repr__` override or use `field(repr=False)`.

---

## T22: Community Schemas

**Estimated LOC:** ~50
**File(s):** `src/knowledge_graph/community/schemas.py` (new file)
**Parallelism group:** A (foundation, no dependencies)

### Summary

Define the `CommunitySummary` and `CommunityDiff` dataclasses used by the detector, summarizer, and expander. These are pure data contracts with no business logic.

### Requirements Covered

| REQ | Priority | Description |
|-----|----------|-------------|
| REQ-KG-712 | MUST | CommunitySummary dataclass |
| REQ-KG-713 | MUST | CommunityDiff dataclass |

### Dependencies

None.

### Contract

```python
# src/knowledge_graph/community/schemas.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set


__all__ = ["CommunitySummary", "CommunityDiff"]


@dataclass
class CommunitySummary:
    """Summarised representation of a single community cluster.

    Attributes:
        community_id: Integer identifier assigned by Leiden.
        summary_text: LLM-generated thematic summary (2-4 sentences).
        member_count: Number of entities in this community.
        member_names: Canonical names of member entities.
        generated_at: ISO 8601 timestamp of summary generation.
    """

    community_id: int
    summary_text: str
    member_count: int
    member_names: List[str] = field(default_factory=list)
    generated_at: str = ""


@dataclass
class CommunityDiff:
    """Diff between two consecutive community detection runs.

    The union of all four sets covers every community ID that appeared
    in either the old or new partition.

    Attributes:
        new_communities: IDs present in new partition but not old.
        removed_communities: IDs present in old partition but not new.
        changed_communities: IDs present in both but with different member sets.
        unchanged_communities: IDs present in both with identical member sets.
    """

    new_communities: Set[int] = field(default_factory=set)
    removed_communities: Set[int] = field(default_factory=set)
    changed_communities: Set[int] = field(default_factory=set)
    unchanged_communities: Set[int] = field(default_factory=set)
```

### Implementation Notes

- `CommunitySummary` must be JSON-serializable for sidecar persistence (T26). All field types are primitives or lists of primitives.
- `CommunityDiff` uses `Set[int]` for efficient membership tests. Convert to lists for JSON serialization.

---

## T23: CommunityDetector — Leiden Algorithm Implementation

**Estimated LOC:** ~150
**File(s):** `src/knowledge_graph/community/detector.py` (full rewrite, replace stub)
**Parallelism group:** B (depends on T21, T22)

### Summary

Replace the Phase 1 stub with a full Leiden-based community detector. Converts the backend's graph to igraph, runs `leidenalg.find_partition()`, assigns community IDs to entities, computes membership diffs against previous runs, and manages the lifecycle (`is_ready` property).

### Requirements Covered

| REQ | Priority | Description |
|-----|----------|-------------|
| REQ-KG-700 | MUST | Leiden community detection |
| REQ-KG-703 | MUST | Replaces Phase 1 stubs |
| REQ-KG-704 | MUST | igraph + leidenalg, resolution config |
| REQ-KG-705 | MUST | Directed-to-undirected conversion |
| REQ-KG-706 | MUST | community_id as node attribute |
| REQ-KG-707 | SHOULD | Minimum community size threshold |
| REQ-KG-708 | SHOULD | Graceful fallback when deps unavailable |
| REQ-KG-717 | MUST | is_ready lifecycle contract |

### Dependencies

- T21 (KGConfig fields: `community_resolution`, `community_min_size`)
- T22 (schemas: `CommunitySummary`, `CommunityDiff`)
- External: `python-igraph`, `leidenalg`
- Internal: `GraphStorageBackend` ABC (no changes needed)

### Contract

```python
# src/knowledge_graph/community/detector.py

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.common.types import KGConfig
from src.knowledge_graph.community.schemas import CommunityDiff, CommunitySummary

__all__ = ["CommunityDetector"]

logger: logging.Logger

# Sentinel for missing igraph/leidenalg
_LEIDEN_AVAILABLE: bool  # Set at import time via try/except


class CommunityDetector:
    """Detects communities in the knowledge graph using the Leiden algorithm.

    Requires python-igraph and leidenalg. When dependencies are unavailable,
    degrades gracefully: is_ready=False, all public methods return empty/None.
    """

    def __init__(
        self,
        backend: GraphStorageBackend,
        config: KGConfig,
        graph_path: Optional[str] = None,
    ) -> None:
        """Initialise with a graph backend and configuration.

        If a sidecar JSON file exists at ``<graph_path>.communities.json``,
        restores summaries and previous assignments from it.

        Args:
            backend: Graph storage backend for entity/edge access.
            config: KG runtime configuration (resolution, min_size, etc.).
            graph_path: Path to the main graph file; used to locate the
                sidecar JSON. None disables sidecar persistence.
        """
        ...

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        """True when both detection and summarization have completed.

        Returns True after:
        - A live ``detect()`` + summaries stored (via summarizer), OR
        - Sidecar restoration with valid summaries and assignments.

        Returns False when:
        - igraph/leidenalg are not installed.
        - detect() has not been called and no sidecar was loaded.
        - detect() was called but no summaries exist yet.
        """
        ...

    def detect(self) -> Dict[int, List[str]]:
        """Run Leiden community detection on the current graph.

        Returns:
            Mapping of ``{community_id: [entity_names]}`` for all
            communities (including the miscellaneous bucket at -1).
            Returns empty dict if igraph/leidenalg unavailable.
        """
        ...

    @property
    def diff(self) -> Optional[CommunityDiff]:
        """The diff from the most recent ``detect()`` call, or None."""
        ...

    def get_community_for_entity(self, name: str) -> Optional[int]:
        """Return the community ID for *name*, or None if not assigned."""
        ...

    def get_community_members(self, community_id: int) -> List[str]:
        """Return entity names belonging to *community_id*."""
        ...

    def get_summary(self, community_id: int) -> Optional[CommunitySummary]:
        """Return the summary for *community_id*, or None."""
        ...

    @property
    def summaries(self) -> Dict[int, CommunitySummary]:
        """All stored community summaries."""
        ...

    @summaries.setter
    def summaries(self, value: Dict[int, CommunitySummary]) -> None:
        """Set summaries (called by CommunitySummarizer)."""
        ...

    def save_sidecar(self) -> None:
        """Persist summaries and assignments to the sidecar JSON file.

        Writes atomically via temp file + rename. No-op if graph_path is None.
        """
        ...

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _to_igraph(self) -> "igraph.Graph":
        """Convert the backend's graph to an undirected igraph.Graph.

        Directed edges are collapsed to undirected with max-weight
        preservation: if A->B has weight 3 and B->A has weight 5,
        the undirected edge A-B has weight max(3, 5) = 5.

        Returns:
            igraph.Graph with entity names as vertex attributes.
        """
        ...

    def _run_leiden(self, ig: "igraph.Graph") -> Dict[int, List[str]]:
        """Execute leidenalg.find_partition() on the igraph graph.

        Uses RBConfigurationVertexPartition by default (modularity
        with resolution). Resolution parameter from config.

        Args:
            ig: Undirected igraph.Graph.

        Returns:
            Raw partition: {community_id: [entity_names]}.
        """
        ...

    def _apply_min_size(
        self, communities: Dict[int, List[str]]
    ) -> Dict[int, List[str]]:
        """Merge communities below min_size into the miscellaneous bucket (-1).

        Args:
            communities: Raw partition from _run_leiden().

        Returns:
            Filtered partition with small communities merged to -1.
        """
        ...

    def _assign_communities(self, communities: Dict[int, List[str]]) -> None:
        """Store community_id as a node attribute on each entity in the backend.

        Args:
            communities: Final partition after min_size filtering.
        """
        ...

    def _compute_diff(
        self, new_communities: Dict[int, List[str]]
    ) -> CommunityDiff:
        """Compare new partition against _previous_assignments.

        Args:
            new_communities: The newly detected partition.

        Returns:
            CommunityDiff describing what changed.
        """
        ...

    def _load_sidecar(self) -> None:
        """Load summaries and previous assignments from the sidecar JSON.

        On corrupt/missing file, treats as first run.
        """
        ...
```

### Implementation Notes

- The `_to_igraph()` method must handle graphs with zero edges (igraph requires explicit vertex creation).
- Use `leidenalg.find_partition(ig, leidenalg.RBConfigurationVertexPartition, resolution_parameter=config.community_resolution, seed=42)` for deterministic results.
- The `_assign_communities()` method writes `community_id` into the backend. For `NetworkXBackend`, this means setting a node attribute directly. For `Neo4jBackend`, this will use the standard `add_node` / property-update path. Since the current `GraphStorageBackend` ABC does not have a `set_node_attribute()` method, use backend-specific logic: check `isinstance(backend, NetworkXBackend)` and access `_graph` directly for NetworkX, or issue a Cypher SET for Neo4j. Alternatively, add a non-abstract `set_node_attribute()` with a default no-op on the ABC — this is a lightweight extension that does not break the existing contract.
- The `is_ready` property returns True when `_detection_complete and len(self._summaries) > 0`.

---

## T24: CommunitySummarizer — LLM Community Summarization

**Estimated LOC:** ~120
**File(s):** `src/knowledge_graph/community/summarizer.py` (new file)
**Parallelism group:** B (depends on T21, T22)

### Summary

LLM-based community summarizer. For each community, collects entity descriptions from the backend, builds a prompt, calls the LLM, and returns a `CommunitySummary`. Supports parallel execution and incremental refresh.

### Requirements Covered

| REQ | Priority | Description |
|-----|----------|-------------|
| REQ-KG-701 | MUST | Community summary generation |
| REQ-KG-709 | MUST | Input token budget |
| REQ-KG-710 | MUST | Output token budget, system prompt |
| REQ-KG-711 | SHOULD | Parallel summarization |
| REQ-KG-714 | SHOULD | Selective re-summarization |

### Dependencies

- T21 (KGConfig fields: summary token budgets, temperature, max_workers)
- T22 (schemas: `CommunitySummary`, `CommunityDiff`)
- Internal: `LLMProvider` (runtime, lazy import)
- Internal: `GraphStorageBackend` (for entity description access)

### Contract

```python
# src/knowledge_graph/community/summarizer.py

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.common.types import KGConfig
from src.knowledge_graph.community.schemas import CommunityDiff, CommunitySummary

__all__ = ["CommunitySummarizer"]

logger: logging.Logger

SYSTEM_PROMPT: str  # Module-level constant: role definition for community summarization


class CommunitySummarizer:
    """LLM-based community summarizer.

    For each community, collects entity descriptions, builds a prompt,
    and calls the LLM to generate a 2-4 sentence thematic summary.
    """

    def __init__(
        self,
        config: KGConfig,
        llm_provider: Optional[Any] = None,
    ) -> None:
        """Initialise with config and optional LLM provider.

        Args:
            config: KG runtime configuration (token budgets, temperature, workers).
            llm_provider: Optional LLMProvider instance. Falls back to
                get_llm_provider() singleton when None.
        """
        ...

    def summarize_community(
        self,
        community_id: int,
        members: List[str],
        backend: GraphStorageBackend,
    ) -> CommunitySummary:
        """Generate a summary for a single community.

        Args:
            community_id: Integer community identifier.
            members: Canonical entity names in this community.
            backend: Backend for fetching entity descriptions.

        Returns:
            CommunitySummary with generated text and metadata.
        """
        ...

    def summarize_all(
        self,
        communities: Dict[int, List[str]],
        backend: GraphStorageBackend,
    ) -> Dict[int, CommunitySummary]:
        """Summarize all communities in parallel.

        Skips the miscellaneous bucket (community_id=-1).
        Uses ThreadPoolExecutor with max_workers from config.

        Args:
            communities: {community_id: [entity_names]} partition.
            backend: Backend for fetching entity descriptions.

        Returns:
            {community_id: CommunitySummary} for all summarized communities.
        """
        ...

    def refresh(
        self,
        diff: CommunityDiff,
        communities: Dict[int, List[str]],
        backend: GraphStorageBackend,
        existing_summaries: Dict[int, CommunitySummary],
    ) -> Dict[int, CommunitySummary]:
        """Incremental refresh: re-summarize only changed/new communities.

        Carries forward unchanged summaries. Discards removed.

        Args:
            diff: CommunityDiff from the most recent detect() call.
            communities: Current partition.
            backend: Backend for entity descriptions.
            existing_summaries: Summaries from the previous run.

        Returns:
            Updated {community_id: CommunitySummary} dict.
        """
        ...

    # -- Internal methods --

    def _build_prompt(
        self, members: List[str], backend: GraphStorageBackend
    ) -> List[Dict[str, str]]:
        """Build OpenAI-style messages for a community summarization call.

        Collects entity descriptions from the backend, truncates to the
        input token budget, and formats as system + user messages.

        Args:
            members: Entity names in the community.
            backend: Backend for entity lookups.

        Returns:
            Messages list (system + user).
        """
        ...

    def _truncate_descriptions(
        self, entities_with_desc: List[tuple], max_tokens: int
    ) -> str:
        """Truncate entity descriptions to fit the input token budget.

        Sorts by mention_count ascending (fewest mentions first) and
        removes descriptions from the bottom until the total fits.

        Args:
            entities_with_desc: List of (entity_name, description_text, mention_count).
            max_tokens: Maximum token budget.

        Returns:
            Concatenated description text within budget.
        """
        ...

    def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """Call LLMProvider.generate() with output token budget.

        Args:
            messages: Chat messages for the LLM.

        Returns:
            Raw summary text from LLM response.
        """
        ...
```

### Implementation Notes

- Token counting: use a simple heuristic (word count * 1.3) or `tiktoken` if available. The sketch uses "tokens" loosely — word-level approximation is sufficient for budget enforcement.
- `summarize_all()` skips `community_id == -1` (miscellaneous bucket per REQ-KG-707).
- `refresh()` is the key optimization: only calls `summarize_community()` for IDs in `diff.new_communities | diff.changed_communities`. All others are carried forward.
- Failure isolation per REQ-KG-711 AC4: catch exceptions per-community in the ThreadPoolExecutor, log at WARNING, exclude from results.

---

## T25: Incremental Refresh — Membership Diff + Selective Re-summarization

**Estimated LOC:** ~50 (spread across T23 and T24 contracts; this task is the integration glue)
**File(s):** `src/knowledge_graph/community/detector.py` (delta), `src/knowledge_graph/community/summarizer.py` (delta)
**Parallelism group:** C (depends on T23, T24)

### Summary

Wire the `CommunityDiff` computation in the detector to the `refresh()` method on the summarizer. This task covers the `_compute_diff()` implementation and the `_previous_assignments` tracking state.

### Requirements Covered

| REQ | Priority | Description |
|-----|----------|-------------|
| REQ-KG-702 | SHOULD | Incremental summary refresh |
| REQ-KG-713 | MUST | CommunityDiff computation |
| REQ-KG-714 | SHOULD | Selective re-summarization |

### Dependencies

- T23 (detector: `_compute_diff()`, `_previous_assignments`)
- T24 (summarizer: `refresh()`)

### Contract

The contracts are defined in T23 (`_compute_diff`) and T24 (`refresh`). This task ensures:

1. `detect()` stores `_previous_assignments: Dict[str, int]` (entity_name -> community_id) after each run.
2. `_compute_diff()` compares old vs. new by inverting the assignment dicts into `Dict[int, Set[str]]` and computing set differences.
3. On first run (no `_previous_assignments`), all communities are `new_communities`.
4. The diff is stored on `self._last_diff` and accessible via the `diff` property.

### Implementation Notes

- The diff algorithm:
  ```
  old_members = invert(_previous_assignments)  # {community_id: {entity_names}}
  new_members = {cid: set(names) for cid, names in communities.items()}
  old_ids = set(old_members.keys())
  new_ids = set(new_members.keys())
  new_communities = new_ids - old_ids
  removed_communities = old_ids - new_ids
  common_ids = old_ids & new_ids
  changed = {cid for cid in common_ids if old_members[cid] != new_members[cid]}
  unchanged = common_ids - changed
  ```
- LOC is low because the logic is algorithmically simple. The complexity is in correctness and testing.

---

## T26: Community Persistence — Sidecar JSON

**Estimated LOC:** ~60
**File(s):** `src/knowledge_graph/community/detector.py` (delta — `save_sidecar`, `_load_sidecar`)
**Parallelism group:** C (depends on T23)

### Summary

Implement atomic sidecar JSON persistence for community summaries and previous assignments. The sidecar file lives at `<graph_path>.communities.json`.

### Requirements Covered

| REQ | Priority | Description |
|-----|----------|-------------|
| REQ-KG-715 | MUST | Sidecar JSON persistence |
| REQ-KG-716 | MUST | Automatic sidecar load on init |

### Dependencies

- T23 (detector: sidecar methods are part of the detector class)
- T22 (schemas: `CommunitySummary` for serialization)

### Contract

Defined in T23's contract (`save_sidecar`, `_load_sidecar`). The sidecar JSON format:

```json
{
  "version": 1,
  "summaries": {
    "0": {
      "community_id": 0,
      "summary_text": "This community covers...",
      "member_count": 12,
      "member_names": ["EntityA", "EntityB", ...],
      "generated_at": "2026-04-08T14:30:00+00:00"
    }
  },
  "previous_assignments": {
    "EntityA": 0,
    "EntityB": 0,
    "EntityC": 1
  }
}
```

### Implementation Notes

- Atomic write: `tempfile.NamedTemporaryFile(dir=parent, delete=False)` + `os.replace(tmp, target)`.
- `_load_sidecar()` is called in `__init__`. On `json.JSONDecodeError` or `KeyError`, log WARNING and treat as first run.
- Missing sidecar is not a warning — it is the normal initial state.
- `save_sidecar()` should be called by the orchestration layer after `detect()` + `summarize_all()` (or `refresh()`). The detector itself does not auto-save.

---

## T27: Global Retrieval — Extend GraphQueryExpander

**Estimated LOC:** ~40 (delta)
**File(s):** `src/knowledge_graph/query/expander.py` (modify existing class)
**Parallelism group:** C (depends on T23, T24)

### Summary

Extend `GraphQueryExpander` to support community-aware global retrieval. After local neighbour expansion, look up matched entities' communities, retrieve community summaries, and include community-derived terms in expansion results.

### Requirements Covered

| REQ | Priority | Description |
|-----|----------|-------------|
| REQ-KG-609 | MUST | Global retrieval via community summaries |
| REQ-KG-717 | MUST | is_ready lifecycle check |
| REQ-KG-718 | MUST | enable_global_retrieval config flag |
| REQ-KG-719 | MUST | Ordering — local first, community fill |

### Dependencies

- T23 (detector: `get_community_for_entity`, `get_summary`, `is_ready`)
- T24 (summarizer: summaries must be generated before expander uses them)
- T21 (config: `enable_global_retrieval`)

### Contract

```python
# Modifications to src/knowledge_graph/query/expander.py

from src.knowledge_graph.community.detector import CommunityDetector  # new import


class GraphQueryExpander:

    def __init__(
        self,
        backend: GraphStorageBackend,
        max_depth: int = 1,
        max_terms: int = 3,
        community_detector: Optional[CommunityDetector] = None,  # NEW
        enable_global_retrieval: bool = False,                     # NEW
    ) -> None:
        """Initialise with a graph backend and optional community detector.

        Args:
            backend: Graph storage backend for neighbour queries.
            max_depth: Maximum hop depth for expansion.
            max_terms: Maximum number of expansion terms to return.
            community_detector: Optional detector for community-aware expansion.
                Must have is_ready==True for community terms to be included.
            enable_global_retrieval: When True and detector is ready, include
                community terms in expansion. Default False.
        """
        ...

    def expand(self, query: str, depth: Optional[int] = None) -> List[str]:
        """Return related entity names to augment the search query.

        Updated flow:
        1. Local expansion (existing logic): match entities, fan out neighbours.
        2. If enable_global_retrieval and detector.is_ready:
           a. For each matched entity, look up community_id.
           b. Retrieve CommunitySummary for each community.
           c. Extract key terms from summary text.
        3. Merge: local terms first, community terms fill remaining slots.
        4. Cap at max_terms.

        Args:
            query: User query text.
            depth: Override max depth.

        Returns:
            List of related entity names, local-first ordering.
        """
        ...

    def _expand_with_communities(
        self, seed_entities: List[str], existing_terms: Set[str]
    ) -> List[str]:
        """Extract community-derived expansion terms.

        For each seed entity:
        1. Look up community_id via detector.get_community_for_entity().
        2. Retrieve CommunitySummary via detector.get_summary().
        3. Extract entity names from summary.member_names that are not
           already in existing_terms.

        Args:
            seed_entities: Entities matched in the query.
            existing_terms: Local expansion terms already collected.

        Returns:
            Community-derived terms, deduplicated.
        """
        ...
```

### Implementation Notes

- The `_expand_with_communities()` method extracts terms from `CommunitySummary.member_names` — these are entity names in the same community as the matched entity. This is more reliable than NLP-parsing the `summary_text`.
- Ordering: `result = local_terms[:max_terms]` then `result.extend(community_terms[:max_terms - len(result)])`.
- When `enable_global_retrieval=True` but detector is None or `not detector.is_ready`, log a WARNING once (use a flag to avoid repeated warnings) and fall back to local-only.
- The `get_context_summary()` method is also extended: when community summaries are available, append the community summary text for matched entities.

### Backward Compatibility

The new `__init__` parameters (`community_detector`, `enable_global_retrieval`) are optional with defaults. Existing callers that construct `GraphQueryExpander(backend, max_depth, max_terms)` continue to work unchanged.

---

## T28: Neo4j Backend — Full Implementation

**Estimated LOC:** ~350
**File(s):** `src/knowledge_graph/backends/neo4j_backend.py` (full rewrite, replace stub)
**Parallelism group:** B (depends on T21 only; independent of community work)

### Summary

Replace the Phase 1 stub with a complete `Neo4jBackend` implementing all `GraphStorageBackend` abstract methods and concrete helpers using the official `neo4j` Python sync driver.

### Requirements Covered

| REQ | Priority | Description |
|-----|----------|-------------|
| REQ-KG-505 | MUST | Full Neo4j implementation (replaces stub) |
| REQ-KG-720 | MUST | All abstract methods, sync driver, connection pooling |
| REQ-KG-721 | MUST | MERGE-based entity resolution |
| REQ-KG-722 | MUST | Index creation on init |
| REQ-KG-723 | SHOULD | UNWIND bulk operations |
| REQ-KG-724 | MUST | save/load as export/import |
| REQ-KG-725 | SHOULD | Community storage as (:Community) nodes |

### Dependencies

- T21 (KGConfig fields: `neo4j_uri`, `neo4j_auth_user`, `neo4j_auth_password`, `neo4j_database`)
- External: `neo4j` Python package (official sync driver)
- Internal: `GraphStorageBackend` ABC (no changes needed)

### Contract

```python
# src/knowledge_graph/backends/neo4j_backend.py

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.common.schemas import Entity, EntityDescription, Triple

__all__ = ["Neo4jBackend"]

logger: logging.Logger

# Module-level Cypher templates
CYPHER_MERGE_ENTITY: str       # MERGE (e:Entity {name_lower: toLower($name)}) ...
CYPHER_MERGE_EDGE: str         # MATCH (s:Entity ...) MATCH (t:Entity ...) MERGE (s)-[r:REL]-(t) ...
CYPHER_UNWIND_ENTITIES: str    # UNWIND $entities AS ent MERGE ...
CYPHER_UNWIND_TRIPLES: str     # UNWIND $triples AS tri MATCH ... MERGE ...
CYPHER_QUERY_NEIGHBORS: str    # MATCH (e:Entity)-[*1..N]-(n:Entity) WHERE ...
CYPHER_GET_ENTITY: str         # MATCH (e:Entity {name_lower: toLower($name)}) RETURN e
CYPHER_GET_PREDECESSORS: str   # MATCH (p:Entity)-[]->(e:Entity {name_lower: ...}) RETURN p
CYPHER_EXPORT_NODES: str       # MATCH (n) RETURN n
CYPHER_EXPORT_EDGES: str       # MATCH ()-[r]->() RETURN r


class Neo4jBackend(GraphStorageBackend):
    """Neo4j graph storage backend using the official sync driver.

    Uses driver-managed connection pooling. Entity resolution is
    server-side via Cypher MERGE with case-insensitive matching.
    """

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        auth: Tuple[str, str] = ("neo4j", ""),
        database: str = "neo4j",
    ) -> None:
        """Connect to Neo4j and create required indexes.

        Args:
            uri: Neo4j bolt URI.
            auth: Tuple of (username, password).
            database: Neo4j database name.

        Raises:
            ImportError: If the neo4j package is not installed.
            neo4j.exceptions.ServiceUnavailable: If Neo4j is not reachable.
        """
        ...

    def close(self) -> None:
        """Close the driver connection pool."""
        ...

    # ------------------------------------------------------------------
    # Write operations (all abstract methods implemented)
    # ------------------------------------------------------------------

    def add_node(
        self,
        name: str,
        type: str,
        source: str,
        aliases: Optional[List[str]] = None,
    ) -> None:
        """Add or update an entity via MERGE with case-insensitive matching."""
        ...

    def add_edge(
        self,
        subject: str,
        object: str,
        relation: str,
        source: str,
        weight: float = 1.0,
    ) -> None:
        """Add a relationship edge. Self-edges silently dropped."""
        ...

    def upsert_entities(self, entities: List[Entity]) -> None:
        """Batch upsert via UNWIND in a single write transaction."""
        ...

    def upsert_triples(self, triples: List[Triple]) -> None:
        """Batch upsert via UNWIND in a single write transaction."""
        ...

    def upsert_descriptions(
        self, descriptions: Dict[str, List[EntityDescription]]
    ) -> None:
        """Append descriptions to entity nodes as a list property."""
        ...

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def query_neighbors(self, entity: str, depth: int = 1) -> List[Entity]:
        """Variable-length path query up to *depth* hops."""
        ...

    def get_entity(self, name: str) -> Optional[Entity]:
        """Case-insensitive entity lookup via toLower() index."""
        ...

    def get_predecessors(self, entity: str) -> List[Entity]:
        """Entities with directed edges into *entity*."""
        ...

    # ------------------------------------------------------------------
    # Persistence (export/import semantics)
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Export graph to a JSON file for backup/migration."""
        ...

    def load(self, path: Path) -> None:
        """Import graph from a JSON file produced by save()."""
        ...

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, object]:
        """Return node count, edge count, and top entities by mention_count."""
        ...

    # ------------------------------------------------------------------
    # Concrete helper overrides (efficiency)
    # ------------------------------------------------------------------

    def get_all_entities(self) -> List[Entity]:
        """Bulk read all entities via single Cypher query."""
        ...

    def get_all_node_names_and_aliases(self) -> Dict[str, str]:
        """Build name/alias index from a single Cypher query."""
        ...

    def get_outgoing_edges(self, node_id: str) -> List[Triple]:
        """Outgoing edges for an entity via Cypher."""
        ...

    def get_incoming_edges(self, node_id: str) -> List[Triple]:
        """Incoming edges for an entity via Cypher."""
        ...

    # ------------------------------------------------------------------
    # Community storage (REQ-KG-725)
    # ------------------------------------------------------------------

    def upsert_community(
        self, community_id: int, summary: str, member_count: int, generated_at: str
    ) -> None:
        """Create or update a (:Community) node and [:BELONGS_TO] edges.

        Args:
            community_id: Integer community identifier.
            summary: LLM-generated summary text.
            member_count: Number of entities in this community.
            generated_at: ISO 8601 timestamp.
        """
        ...

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_indexes(self) -> None:
        """Create indexes IF NOT EXISTS on entity name, type, community_id."""
        ...

    def _to_entity(self, record: Any) -> Entity:
        """Convert a Neo4j Record to an Entity dataclass."""
        ...

    def _run_read(self, query: str, **params) -> List[Any]:
        """Execute a read transaction and return all records."""
        ...

    def _run_write(self, query: str, **params) -> None:
        """Execute a write transaction."""
        ...
```

### Implementation Notes

- The `neo4j` package import is wrapped in try/except at the top of the module. If unavailable, `__init__` raises `ImportError`.
- Entity node label: `:Entity`. Community node label: `:Community`. Relationship types use the triple's predicate as the relationship type.
- `name_lower` is a dedicated indexed property set to `toLower(name)` on every entity node. This enables O(1) case-insensitive lookups without runtime function evaluation in queries.
- `save()`/`load()` use a structured JSON format (not Cypher scripts) for simplicity and cross-version compatibility. The JSON mirrors the node-link format used by the NetworkX backend.
- Community storage (REQ-KG-725): `upsert_community()` is a bonus method not on the ABC. It is called by the integration layer after community detection + summarization when the backend is Neo4j.

---

## T29: Python Parser Extractor (MAY)

**Estimated LOC:** ~120
**File(s):** `src/knowledge_graph/extraction/python_parser.py` (new file)
**Parallelism group:** D (depends on T21 only; MAY priority)

### Summary

AST-based Python source file extractor. Uses stdlib `ast` to extract classes, functions, imports, and structural relationships.

### Requirements Covered

| REQ | Priority | Description |
|-----|----------|-------------|
| REQ-KG-726 | MAY | Python ast-based extractor |
| REQ-KG-728 | MAY | Phase 2 node types in YAML schema (PythonClass, PythonFunction) |

### Dependencies

- T21 (KGConfig: `enable_python_parser`)
- Internal: `EntityExtractor` protocol from `extraction/base.py`

### Contract

```python
# src/knowledge_graph/extraction/python_parser.py

from __future__ import annotations

import ast
import logging
from typing import List, Set

from src.knowledge_graph.common.schemas import Entity, ExtractionResult, Triple

__all__ = ["PythonParserExtractor"]

logger: logging.Logger


class PythonParserExtractor:
    """Deterministic Python source extractor using stdlib ast.

    Extracts classes, functions, imports, and containment/dependency
    relationships from Python source files.
    """

    extractor_name: str = "python_parser"

    @property
    def name(self) -> str:
        return self.extractor_name

    def extract_entities(self, text: str) -> Set[str]:
        """Extract entity names (class/function names) from Python source.

        Args:
            text: Python source code as a string.

        Returns:
            Set of entity name strings.
        """
        ...

    def extract_relations(
        self, text: str, known_entities: Set[str]
    ) -> List[Triple]:
        """Extract structural relations from Python source.

        Produces:
        - ``contains`` triples: class -> method
        - ``depends_on`` triples: module -> imported module

        Args:
            text: Python source code.
            known_entities: Known entity names for relation filtering.

        Returns:
            List of Triple objects.
        """
        ...

    def extract(self, text: str, source: str = "") -> ExtractionResult:
        """Full extraction: entities, triples, descriptions.

        Args:
            text: Python source code.
            source: File path for provenance.

        Returns:
            ExtractionResult with PythonClass/PythonFunction entities and triples.
        """
        ...

    # -- Internal --

    def _walk_ast(
        self, tree: ast.Module, source: str
    ) -> tuple[List[Entity], List[Triple]]:
        """Walk the AST and extract entities and relationships."""
        ...
```

### Implementation Notes

- Entity types: `PythonClass` for `ast.ClassDef`, `PythonFunction` for `ast.FunctionDef`/`ast.AsyncFunctionDef` at module or class level.
- Import triples: `ast.Import` and `ast.ImportFrom` produce `depends_on` triples.
- Methods inside classes produce `contains` triples from the class to the method.
- This task also requires adding `PythonClass` and `PythonFunction` to `config/kg_schema.yaml` (phase: phase_2, category: structural).

---

## T30: Bash Parser Extractor (MAY)

**Estimated LOC:** ~100
**File(s):** `src/knowledge_graph/extraction/bash_parser.py` (new file)
**Parallelism group:** D (depends on T21 only; MAY priority)

### Summary

Tree-sitter-based Bash script extractor. Extracts function definitions, source commands, and significant command invocations.

### Requirements Covered

| REQ | Priority | Description |
|-----|----------|-------------|
| REQ-KG-727 | MAY | Bash tree-sitter-based extractor |
| REQ-KG-728 | MAY | Phase 2 node types in YAML schema (BashFunction, BashScript) |

### Dependencies

- T21 (KGConfig: `enable_bash_parser`)
- External: `tree-sitter`, `tree-sitter-bash`
- Internal: `EntityExtractor` protocol from `extraction/base.py`

### Contract

```python
# src/knowledge_graph/extraction/bash_parser.py

from __future__ import annotations

import logging
from typing import Any, List, Set

from src.knowledge_graph.common.schemas import Entity, ExtractionResult, Triple

__all__ = ["BashParserExtractor"]

logger: logging.Logger


class BashParserExtractor:
    """Deterministic Bash script extractor using tree-sitter-bash.

    Extracts function definitions, source/dot commands, and
    structural dependencies from Bash scripts.
    """

    extractor_name: str = "bash_parser"

    def __init__(self) -> None:
        """Initialize the tree-sitter parser for Bash.

        Raises:
            ImportError: If tree-sitter or tree-sitter-bash is not installed.
        """
        ...

    @property
    def name(self) -> str:
        return self.extractor_name

    def extract_entities(self, text: str) -> Set[str]:
        """Extract entity names (function names) from Bash source."""
        ...

    def extract_relations(
        self, text: str, known_entities: Set[str]
    ) -> List[Triple]:
        """Extract structural relations from Bash source.

        Produces:
        - ``depends_on`` triples for source/dot commands.
        """
        ...

    def extract(self, text: str, source: str = "") -> ExtractionResult:
        """Full extraction: entities, triples, descriptions."""
        ...

    # -- Internal --

    def _parse_tree(self, text: str) -> Any:
        """Parse text into a tree-sitter CST."""
        ...

    def _walk_tree(
        self, node: Any, source: str
    ) -> tuple[List[Entity], List[Triple]]:
        """Walk the CST and extract entities and relationships."""
        ...
```

### Implementation Notes

- Entity types: `BashFunction` for function definitions, `BashScript` for the file itself.
- `source ./common.sh` and `. ./common.sh` produce `depends_on` triples.
- This task also requires adding `BashFunction` and `BashScript` to `config/kg_schema.yaml` (phase: phase_2, category: structural).
- Follows the same tree-sitter pattern established by `SVParserExtractor` in Phase 1b.

---

## T31: Integration Wiring

**Estimated LOC:** ~30
**File(s):**
- `src/knowledge_graph/__init__.py` (modify)
- `src/knowledge_graph/community/__init__.py` (modify)
**Parallelism group:** E (depends on T23, T24, T27, T28)

### Summary

Update package exports, factory functions, and wiring to integrate all Phase 2 components. The `get_query_expander()` factory must optionally construct and inject a `CommunityDetector` when global retrieval is enabled.

### Requirements Covered

| REQ | Priority | Description |
|-----|----------|-------------|
| REQ-KG-609 | MUST | Global retrieval wiring via factory |
| REQ-KG-718 | MUST | enable_global_retrieval factory check |

### Dependencies

- T23 (CommunityDetector)
- T24 (CommunitySummarizer)
- T27 (GraphQueryExpander extensions)
- T28 (Neo4jBackend constructor changes)

### Contract

```python
# Modified get_graph_backend() in src/knowledge_graph/__init__.py

def get_graph_backend(config: Optional[KGConfig] = None) -> GraphStorageBackend:
    """Return the process-wide graph backend singleton.

    Updated for Phase 2: Neo4j backend receives config-driven connection params.
    """
    # ... existing logic ...

    elif backend_name == "neo4j":
        from src.knowledge_graph.backends.neo4j_backend import Neo4jBackend

        _graph_backend = Neo4jBackend(
            uri=config.neo4j_uri,
            auth=(config.neo4j_auth_user, config.neo4j_auth_password),
            database=config.neo4j_database,
        )
    # ... rest unchanged ...


# Modified get_query_expander() in src/knowledge_graph/__init__.py

def get_query_expander(
    backend: Optional[GraphStorageBackend] = None,
    config: Optional[KGConfig] = None,
):
    """Build a query expander with optional community detector.

    When enable_global_retrieval is True:
    1. Construct CommunityDetector(backend, config, graph_path).
    2. If detector dependencies are available and sidecar exists,
       the detector will auto-restore to ready state.
    3. If no sidecar, run detect() + summarize_all() eagerly.
    4. Inject detector into GraphQueryExpander.
    """
    from src.knowledge_graph.query.expander import GraphQueryExpander

    if backend is None:
        backend = get_graph_backend()
    if config is None:
        config = _build_kg_config()

    community_detector = None
    if config.enable_global_retrieval:
        try:
            from src.knowledge_graph.community.detector import CommunityDetector
            from src.knowledge_graph.community.summarizer import CommunitySummarizer

            detector = CommunityDetector(
                backend=backend,
                config=config,
                graph_path=getattr(config, "graph_path", None),
            )
            if not detector.is_ready:
                communities = detector.detect()
                if communities:
                    summarizer = CommunitySummarizer(config=config)
                    summaries = summarizer.summarize_all(communities, backend)
                    detector.summaries = summaries
                    detector.save_sidecar()
            community_detector = detector
        except Exception as exc:
            logger.warning(
                "Community detection unavailable: %s. "
                "Falling back to local-only expansion.",
                exc,
            )

    return GraphQueryExpander(
        backend=backend,
        max_depth=config.max_expansion_depth,
        max_terms=config.max_expansion_terms,
        community_detector=community_detector,
        enable_global_retrieval=config.enable_global_retrieval,
    )
```

```python
# Updated src/knowledge_graph/community/__init__.py

"""Community detection sub-package for the KG subsystem.

Provides Leiden-based community detection (CommunityDetector),
LLM-based community summarization (CommunitySummarizer),
and typed data contracts (CommunitySummary, CommunityDiff).
"""

from src.knowledge_graph.community.detector import CommunityDetector
from src.knowledge_graph.community.schemas import CommunitySummary, CommunityDiff
from src.knowledge_graph.community.summarizer import CommunitySummarizer

__all__ = [
    "CommunityDetector",
    "CommunitySummarizer",
    "CommunitySummary",
    "CommunityDiff",
]
```

### Implementation Notes

- The `get_query_expander()` factory eagerly runs `detect()` + `summarize_all()` when global retrieval is enabled and no sidecar exists. This adds startup latency but ensures the expander is ready for queries. Document this in the engineering guide.
- The `__init__.py` `__all__` list should be updated to export `CommunityDetector`, `CommunitySummarizer`, etc.
- Neo4j backend construction now passes config-derived connection parameters instead of the current hardcoded defaults.

---

## Task Dependency Graph

```
T21 (KGConfig)          T22 (Community Schemas)
  |    \                      |
  |     \                     |
  |      \                    |
  |       +---+---+---+------+
  |       |   |   |   |
  v       v   v   v   v
T23 (Detector)  T24 (Summarizer)    T28 (Neo4j Backend)
  |       |        |                     |
  |       v        v                     |
  |     T25 (Incremental Refresh)        |
  |       |                              |
  v       |                              |
T26 (Sidecar Persistence)               |
  |       |                              |
  +---+---+---+--------------------------+
      |       |
      v       v
    T27 (Global Retrieval)
      |
      v
    T31 (Integration Wiring)
      |
    T29 (Python Parser, MAY)   T30 (Bash Parser, MAY)
    (independent, lowest priority)
```

---

## Parallelism Groups

| Group | Tasks | Can Start After | Description |
|-------|-------|-----------------|-------------|
| **A** | T21, T22 | Immediately | Foundation: config + schemas. No deps. |
| **B** | T23, T24, T28 | Group A complete | Core implementations. T23/T24 need schemas; T28 needs config. All three are independent of each other. |
| **C** | T25, T26, T27 | Group B complete | Integration features: incremental refresh, persistence, global retrieval. T25 needs T23+T24. T26 needs T23. T27 needs T23+T24. |
| **D** | T29, T30 | T21 complete | MAY-priority parsers. Independent of community work. Can run any time after config exists. |
| **E** | T31 | Groups B+C complete | Final wiring. Depends on all MUST components. |

### Recommended Implementation Order

1. **T21 + T22** (parallel) — unblocks everything
2. **T23 + T24 + T28** (parallel) — three independent high-LOC tasks
3. **T25 + T26 + T27** (parallel after T23/T24) — integration features
4. **T31** — final wiring
5. **T29 + T30** (if time permits) — MAY parsers, any time after step 1

---

## Summary Table

| Task | File(s) | Est. LOC | Priority | REQs Covered | Dependencies | Group |
|------|---------|----------|----------|--------------|--------------|-------|
| T21: KGConfig Extensions | `common/types.py`, `config/settings.py` | ~35 | MUST | 729 | None | A |
| T22: Community Schemas | `community/schemas.py` | ~50 | MUST | 712, 713 | None | A |
| T23: CommunityDetector | `community/detector.py` | ~150 | MUST | 700, 703, 704, 705, 706, 707, 708, 717 | T21, T22 | B |
| T24: CommunitySummarizer | `community/summarizer.py` | ~120 | MUST | 701, 709, 710, 711, 714 | T21, T22 | B |
| T25: Incremental Refresh | `community/detector.py`, `community/summarizer.py` | ~50 | SHOULD | 702, 713, 714 | T23, T24 | C |
| T26: Sidecar Persistence | `community/detector.py` | ~60 | MUST | 715, 716 | T23, T22 | C |
| T27: Global Retrieval | `query/expander.py` | ~40 | MUST | 609, 717, 718, 719 | T23, T24, T21 | C |
| T28: Neo4j Backend | `backends/neo4j_backend.py` | ~350 | MUST | 505, 720, 721, 722, 723, 724, 725 | T21 | B |
| T29: Python Parser (MAY) | `extraction/python_parser.py` | ~120 | MAY | 726, 728 | T21 | D |
| T30: Bash Parser (MAY) | `extraction/bash_parser.py` | ~100 | MAY | 727, 728 | T21 | D |
| T31: Integration Wiring | `__init__.py`, `community/__init__.py` | ~30 | MUST | 609, 718 | T23, T24, T27, T28 | E |
| **Total (MUST/SHOULD)** | | **~885** | | | | |
| **Total (all)** | | **~1,105** | | | | |

---

## Risk Register

| # | Risk | Impact | Likelihood | Mitigation |
|---|------|--------|------------|------------|
| R1 | `leidenalg` C extension fails to build on target platform | Blocks community detection | Low | Pin known-good wheel versions (leidenalg 0.10.x ships manylinux wheels). REQ-KG-708 mandates graceful fallback; T23 implements it. |
| R2 | LLM summarization cost scales with community count | Budget overrun on large graphs | Medium | Default `community_min_size=3` reduces community count. Input/output token budgets cap per-call cost. `max_workers` limits parallelism. Add a `max_communities_to_summarize` safeguard if needed. |
| R3 | Neo4j version incompatibility (Community vs Enterprise) | Backend fails on customer infra | Medium | Test against Neo4j 5.x Community. Avoid Enterprise-only features (APOC). Document minimum Neo4j version (5.0+). |
| R4 | Leiden produces unstable partitions on small graphs (<50 nodes) | Inconsistent community assignments between runs | Medium | Pass `seed=42` to `find_partition()` for deterministic results. Document that small graphs may produce trivial single-community partitions. |
| R5 | `GraphStorageBackend` ABC lacks `set_node_attribute()` for community_id storage | T23 needs backend-specific code to write community_id | Medium | Use isinstance checks for NetworkX (direct `_graph` access) and Neo4j (Cypher SET). If this pattern proves brittle, add a non-abstract `set_node_attribute()` to the ABC with a default no-op. |
| R6 | Sidecar JSON corruption on crash during write | Lost summaries, triggers full re-summarization | Low | Atomic write via temp file + `os.replace()` (T26). Even worst case is safe — treated as first run. |
| R7 | `get_query_expander()` startup latency when global retrieval enabled | Slow first-query experience | Medium | Sidecar restoration avoids live `detect()+summarize_all()` on most restarts. When sidecar is missing, log a message explaining the one-time cost. Consider background initialization in a future iteration. |
| R8 | Community terms dilute local expansion quality | Reduced retrieval precision | Low | REQ-KG-719 mandates local-first ordering. Community terms only fill remaining slots. Worst case is same as without community terms (all slots filled by local terms). |

---

## Open Questions

1. **`set_node_attribute()` on ABC:** T23 needs to write `community_id` as a node attribute. The current ABC has no such method. Options: (a) add a non-abstract method with default no-op, (b) use isinstance dispatch in the detector, (c) add a new abstract method (breaking change). Recommendation: option (a), which is backward-compatible and can be overridden by backends that support it natively.

2. **Token counting strategy:** T24 needs to count tokens for the input budget. Options: (a) `tiktoken` for accurate counts (adds a dependency), (b) `len(text.split()) * 1.3` heuristic (no dependency). Recommendation: (b) for simplicity, with a config knob to switch to tiktoken if available.

3. **Eager vs. lazy community initialization in `get_query_expander()`:** T31 currently proposes eager initialization (run detect+summarize at factory time). This adds startup latency. Alternative: lazy initialization on first `expand()` call. Trade-off: eager gives predictable readiness; lazy has faster startup but first query is slow. Recommendation: eager, with sidecar restoration making subsequent starts fast.
