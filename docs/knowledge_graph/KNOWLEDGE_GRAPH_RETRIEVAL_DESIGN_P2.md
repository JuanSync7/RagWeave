# Knowledge Graph Retrieval Phase 2 — Design Document

| Field | Value |
|-------|-------|
| **Document** | KG Retrieval Phase 2 Design Document |
| **Version** | 0.1 |
| **Status** | Draft |
| **Spec Reference** | `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC_P2.md` (REQ-KG-1300–1334) |
| **Companion Documents** | `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC_P2.md`, `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC_SUMMARY_P2.md`, `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md` (Phase 1) |
| **Output Path** | `docs/knowledge_graph/KNOWLEDGE_GRAPH_RETRIEVAL_DESIGN_P2.md` |
| **Produced by** | write-design-docs |
| **Phase** | P2 |
| **Prior phases** | [KNOWLEDGE_GRAPH_RETRIEVAL_DESIGN.md](KNOWLEDGE_GRAPH_RETRIEVAL_DESIGN.md) (Tasks 1.1–4.2) |
| **Extends contracts** | `KGConfig`, `GraphContextFormatter`, `PathMatcher`, `GraphQueryExpander` (from P1 Part B) |
| **Task Decomposition Status** | [x] Approved |

> **Document Intent.** This document provides a technical design with task decomposition
> and contract-grade code appendix for the KG Retrieval Phase 2 enhancements specified in
> `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC_P2.md`. Phase 2 adds community context injection into the
> graph context block, configurable verb normalization, and operator-tunable parameters for
> marker style, hop fanout, and community budget. Every task references the requirements it
> satisfies. Part B contract entries are consumed verbatim by the companion implementation docs.

---

# Part A: Task-Oriented Overview

## Phase 5 — Configuration & Foundation

### Task 5.1: Configuration Fields and Environment Variables

**Description:** Add three new `KGConfig` fields (`community_context_token_budget`, `graph_context_marker_style`, `max_hop_fanout`) with corresponding `RAG_KG_` environment variable bindings in `settings.py`. Add validation for each: marker style must be one of `{"markdown", "xml", "plain"}`, max hop fanout must be >= 1, community context token budget must be >= 0.

**Requirements Covered:** REQ-KG-1320, REQ-KG-1322, REQ-KG-1324, REQ-KG-1326

**Dependencies:** None (P1 complete — extends established `KGConfig` and `settings.py`)

**Complexity:** S

**Subtasks:**
1. Add `community_context_token_budget: int = 200` to `KGConfig` in `common/types.py`
2. Add `graph_context_marker_style: str = "markdown"` to `KGConfig`
3. Add `max_hop_fanout: int = 50` to `KGConfig`
4. Add `__post_init__` validation for marker style enum and numeric bounds
5. Add `RAG_KG_COMMUNITY_CONTEXT_TOKEN_BUDGET`, `RAG_KG_GRAPH_CONTEXT_MARKER_STYLE`, `RAG_KG_MAX_HOP_FANOUT` to `config/settings.py`
6. Wire env vars into KGConfig construction in `src/knowledge_graph/__init__.py`

---

## Phase 6 — Feature Implementation

### Task 5.2: Verb Normalization Table Loading

**Description:** Load a verb normalization table from `kg_schema.yaml` under a new `verb_normalization` key and use it in path narrative rendering. The table maps predicate labels to natural-language verb phrases. When a predicate has a mapping, use it; otherwise fall back to underscore-to-space replacement. The table is loaded once at formatter initialization and cached.

**Requirements Covered:** REQ-KG-1310, REQ-KG-1312, REQ-KG-1332

**Dependencies:** Task 5.1 (config fields must exist)

**Complexity:** S

**Subtasks:**
1. Add `verb_normalization` key to `config/kg_schema.yaml` with initial mappings for existing edge types
2. Add `_load_verb_table(schema_path: Optional[str]) -> Dict[str, str]` helper to `context_formatter.py`
3. Modify `GraphContextFormatter.__init__` to accept optional `schema_path` and load verb table once
4. Modify `_format_path_narratives` to look up each predicate in the verb table before falling back to `replace("_", " ")`
5. Verify that a missing `verb_normalization` key in the schema produces an empty table (no error)

**Testing Strategy:** Unit test with table present (mapped predicate renders mapped phrase), table absent (fallback), and mixed (some mapped, some fallback).

---

### Task 5.3: Community ID Collection from Traversal

**Description:** After typed traversal and path pattern matching, collect the `community_id` attribute from every entity encountered — seeds, typed neighbors, and all entities on matched path hops. Produce a deduplicated set of community IDs, excluding `-1` (miscellaneous bucket). Entities without a `community_id` attribute are silently skipped.

**Requirements Covered:** REQ-KG-1300

**Dependencies:** Task 5.1 (config fields must exist)

**Complexity:** S

**Subtasks:**
1. Add `_collect_community_ids(entities: List[Entity], paths: List[PathResult]) -> Set[int]` method to `GraphQueryExpander`
2. Extract `community_id` from entity attributes (via `entity.community_id` or graph node attribute lookup)
3. For paths, extract community IDs from each hop's `from_entity` and `to_entity` via backend lookup
4. Exclude `community_id == -1` and `None` values
5. Call this method after typed traversal + path matching in `expand()`

---

### Task 5.4: Community Summary Lookup and Formatting

**Description:** For each community ID collected in Task 5.3, look up the pre-built `CommunitySummary` via `CommunityDetector.get_summary()`. Format retrieved summaries into a new "Community Context" section in the graph context block. The section appears after Path Narratives. Each entry renders as `[Community {id}] ({N} entities touched): {summary_text}`. Apply an independent token sub-budget (`community_context_token_budget`) — when summaries exceed the budget, drop the community with fewest traversed entities first.

**Requirements Covered:** REQ-KG-1302, REQ-KG-1304, REQ-KG-1306

**Dependencies:** Task 5.3 (community IDs must be collected)

**Complexity:** M

**Subtasks:**
1. Add `_lookup_community_summaries(community_ids: Set[int], entity_community_counts: Dict[int, int]) -> List[Tuple[int, CommunitySummary, int]]` method
2. Add `_format_community_context(summaries: List[Tuple[int, CommunitySummary, int]]) -> List[str]` to `GraphContextFormatter`
3. Add community section markers to `_get_section_markers()` for all three styles (markdown: `### Communities`, xml: `<communities>...</communities>`, plain: `--- COMMUNITIES ---`)
4. Add `_apply_community_budget(lines: List[str], entity_counts: List[int]) -> List[str]` with lowest-entity-count-first truncation
5. Modify `format()` to accept optional `community_summaries` parameter and render the section after paths
6. Modify `_assemble()` to include community section before truncation annotation and footer

**Risks:** Community IDs on entities may be stored differently in NetworkX vs Neo4j backends — need to handle both attribute access patterns.

**Testing Strategy:** Unit test formatter with 0, 1, 3, 5 community summaries; test budget truncation drops lowest-count community first; test all three marker styles include community section markers.

---

### Task 5.5: Max Hop Fanout from Config

**Description:** Replace the module-level constant `_MAX_HOP_FANOUT = 50` in `path_matcher.py` with a config-driven value. `PathMatcher` reads `config.max_hop_fanout` at construction time.

**Requirements Covered:** REQ-KG-1324

**Dependencies:** Task 5.1 (config field must exist)

**Complexity:** S

**Subtasks:**
1. Modify `PathMatcher.__init__` to accept `max_hop_fanout: int = 50` parameter
2. Store as `self._max_hop_fanout` instance attribute
3. Replace all references to `_MAX_HOP_FANOUT` module constant with `self._max_hop_fanout`
4. Update expander to pass `config.max_hop_fanout` when constructing `PathMatcher`

---

## Phase 7 — Integration & Resilience

### Task 5.6: Graceful Degradation and End-to-End Integration

**Description:** Wire all Phase 2 features into the expander and formatter with graceful degradation. Community context injection is wrapped in a try/except that falls back to Phase 1 behavior on any error. Verb normalization falls back to underscore replacement when schema is missing. All Phase 2 features degrade to exact Phase 1 output when their dependencies are unavailable (`CommunityDetector` is None, `verb_normalization` key absent, `community_context_token_budget=0`).

**Requirements Covered:** REQ-KG-1308, REQ-KG-1334, REQ-KG-1330

**Dependencies:** Task 5.2, Task 5.4, Task 5.5

**Complexity:** M

**Subtasks:**
1. Wrap community ID collection + summary lookup + formatting in a single try/except in `expand()` — on error, log WARNING with exception details, proceed with Phase 1 context
2. Thread `community_context_token_budget` and `graph_context_marker_style` from config through to formatter construction
3. Thread `max_hop_fanout` from config through to `PathMatcher` construction
4. Verify: when `CommunityDetector` is None or `is_ready=False` → community section omitted, output identical to Phase 1
5. Verify: when `verb_normalization` key absent from schema → path narratives identical to Phase 1
6. Verify: when `community_context_token_budget=0` → community section disabled

**Risks:** Multiple independent degradation paths may interact unexpectedly — test each in isolation and in combination.

**Testing Strategy:** Integration test with all features enabled; degradation tests for each: missing detector, detector not ready, schema without verb table, community budget zero, exception during community lookup.

---

## Task Dependency Graph

```
--- Prior Phase Boundary (P1 Tasks 1.1–4.2 complete) ---

        Task 5.1: Config fields + env vars
        /          |          \
       /           |           \
      v            v            v
Task 5.2      Task 5.3      Task 5.5
Verb norm     Community     Hop fanout
   |          ID collect       |
   |              |            |
   |              v            |
   |          Task 5.4         |
   |          Community        |
   |          formatting       |
    \             |           /
     \            |          /
      v           v         v
        Task 5.6: Integration
        [CRITICAL]
```

**Critical path:** 5.1 → 5.3 → 5.4 → 5.6

**Parallel opportunities:** After 5.1 completes, tasks 5.2, 5.3, and 5.5 can run in parallel (Wave 1). Task 5.4 depends only on 5.3. Task 5.6 waits for all.

---

## Task-to-Requirement Mapping

| REQ ID | Priority | Task(s) | Component |
|--------|----------|---------|-----------|
| REQ-KG-1300 | MUST | 5.3 | Community ID collection |
| REQ-KG-1302 | MUST | 5.4 | Community summary lookup |
| REQ-KG-1304 | MUST | 5.4 | Community section formatting |
| REQ-KG-1306 | MUST | 5.4 | Community token sub-budget |
| REQ-KG-1308 | MUST | 5.6 | Community degradation |
| REQ-KG-1310 | MUST | 5.2 | Verb normalization table |
| REQ-KG-1312 | SHOULD | 5.2 | Schema co-location |
| REQ-KG-1320 | MUST | 5.1 | Community budget config |
| REQ-KG-1322 | MUST | 5.1 | Marker style config |
| REQ-KG-1324 | MUST | 5.1, 5.5 | Hop fanout config + wire-up |
| REQ-KG-1326 | MUST | 5.1 | Env var convention |
| REQ-KG-1330 | MUST | 5.6 | Injection latency |
| REQ-KG-1332 | MUST | 5.2 | One-time YAML load |
| REQ-KG-1334 | MUST | 5.6 | Phase 1 degradation |

**Coverage:** 14/14 requirements mapped. No orphan tasks.

---

# Part B: Code Appendix

## B.7: KGConfig Phase 2 Fields — Contract

New fields added to `KGConfig` for Phase 2. Extends the established P1 dataclass.

**Tasks:** Task 5.1
**Requirements:** REQ-KG-1320, REQ-KG-1322, REQ-KG-1324, REQ-KG-1326
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
# Established in P1 — KNOWLEDGE_GRAPH_RETRIEVAL_DESIGN.md B.1
# Real implementation: src/knowledge_graph/common/types.py
from src.knowledge_graph.common.types import KGConfig

# --- New P2 fields to add to KGConfig ---

# Phase 2: Community context + operator configurability (REQ-KG-1320..1326)
# community_context_token_budget: int = 200    # REQ-KG-1320 — independent budget for community section
# graph_context_marker_style: str = "markdown"  # REQ-KG-1322 — "markdown" | "xml" | "plain"
# max_hop_fanout: int = 50                      # REQ-KG-1324 — replaces _MAX_HOP_FANOUT constant

# --- __post_init__ validation additions ---
# if self.graph_context_marker_style not in {"markdown", "xml", "plain"}:
#     raise ValueError(f"graph_context_marker_style must be 'markdown', 'xml', or 'plain', got '{self.graph_context_marker_style}'")
# if self.max_hop_fanout < 1:
#     raise ValueError(f"max_hop_fanout must be >= 1, got {self.max_hop_fanout}")
# if self.community_context_token_budget < 0:
#     raise ValueError(f"community_context_token_budget must be >= 0, got {self.community_context_token_budget}")
```

**Key design decisions:**
- Fields added to the existing `KGConfig` dataclass rather than a new config object — single config surface
- `community_context_token_budget=0` acts as a disable toggle for community context (no separate boolean needed)
- `max_hop_fanout` default matches the P1 module constant (50) — zero behavioral change for existing deployments

---

## B.8: Environment Variable Bindings — Contract

New environment variable bindings in `config/settings.py` for Phase 2 fields.

**Tasks:** Task 5.1
**Requirements:** REQ-KG-1326
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
# Established in P1 — config/settings.py
# Real implementation: config/settings.py

# --- New P2 env vars to add ---

RAG_KG_COMMUNITY_CONTEXT_TOKEN_BUDGET: int = 200     # REQ-KG-1320
RAG_KG_GRAPH_CONTEXT_MARKER_STYLE: str = "markdown"   # REQ-KG-1322
RAG_KG_MAX_HOP_FANOUT: int = 50                       # REQ-KG-1324
```

**Key design decisions:**
- Follows existing `RAG_KG_` prefix convention from P1
- `RAG_KG_GRAPH_CONTEXT_MARKER_STYLE` is a plain string — no special parsing needed
- `RAG_KG_MAX_HOP_FANOUT` is parsed as int, matching `RAG_KG_GRAPH_CONTEXT_TOKEN_BUDGET` pattern

---

## B.9: Verb Normalization Schema Extension — Contract

New `verb_normalization` key in `kg_schema.yaml`.

**Tasks:** Task 5.2
**Requirements:** REQ-KG-1312
**Type:** Contract (exact — copied to implementation docs Phase 0)

```yaml
# Added to config/kg_schema.yaml under top level

verb_normalization:
  # Structural edge types
  depends_on: "depends on"
  contains: "contains"
  instantiates: "instantiates"
  connects_to: "connects to"
  parameterized_by: "is parameterized by"
  belongs_to_clock_domain: "belongs to clock domain"
  implements_interface: "implements"
  transitions_to: "transitions to"
  drives: "drives"
  reads: "reads"
  # Semantic edge types
  specified_by: "is specified by"
  verified_by: "is verified by"
  authored_by: "was authored by"
  reviewed_by: "was reviewed by"
  blocks: "blocks"
  supersedes: "supersedes"
  constrained_by: "is constrained by"
  trades_off_against: "trades off against"
  assumes: "assumes"
  complies_with: "complies with"
  relates_to: "relates to"
  design_decision_for: "has design decision for"
```

**Key design decisions:**
- Co-located with edge type definitions in `kg_schema.yaml` — single source of truth
- Covers all existing edge types — new edge types added later simply fall back to underscore replacement if no entry is added
- Passive voice used where grammatically appropriate ("was authored by", "is specified by") to produce natural path narratives

---

## B.10: Community ID Collection — Contract

Function stub for collecting community IDs from traversal results.

**Tasks:** Task 5.3
**Requirements:** REQ-KG-1300
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

# Established in P1 — real implementation
from src.knowledge_graph.common.schemas import Entity
from src.knowledge_graph.query.schemas import PathResult


def collect_community_ids(
    entities: List[Entity],
    paths: List[PathResult],
    backend: "GraphStorageBackend",
) -> Tuple[Set[int], Dict[int, int]]:
    """Collect deduplicated community IDs from all traversal results.

    Examines every entity encountered during traversal — seeds, typed
    neighbors, and all entities on matched path hops — and extracts
    their ``community_id`` attribute.

    Args:
        entities: All entities from typed traversal (seeds + neighbors).
        paths: All matched path results from path pattern evaluation.
        backend: Graph backend for looking up path hop entity attributes.

    Returns:
        Tuple of:
        - Set of deduplicated community IDs (excluding -1 and None).
        - Dict mapping community_id -> count of traversed entities in
          that community (for budget truncation priority).

    Note:
        Entities without a ``community_id`` attribute are silently skipped.
        Community ID -1 (miscellaneous bucket) is always excluded.
    """
    raise NotImplementedError("Task 5.3")
```

**Key design decisions:**
- Returns both the ID set and a per-community entity count — the count is needed by Task 5.4 for budget truncation priority
- Accepts `backend` parameter for looking up path hop entities that may not be in the `entities` list
- Standalone function rather than method — can be tested independently of the expander

---

## B.11: Community Context Formatting — Contract

Function stub for formatting community summaries into the graph context block.

**Tasks:** Task 5.4
**Requirements:** REQ-KG-1304, REQ-KG-1306
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

# Established in P1 — real implementation
from src.knowledge_graph.community.schemas import CommunitySummary


def format_community_section(
    summaries: Dict[int, CommunitySummary],
    entity_counts: Dict[int, int],
    token_budget: int,
    section_markers: Dict[str, str],
) -> str:
    """Format community summaries into a budget-bounded text section.

    Each entry renders as::

        [Community {id}] ({N} entities touched): {summary_text}

    When the total exceeds ``token_budget``, communities with the
    fewest traversed entities are dropped first.

    Args:
        summaries: Mapping of community_id to CommunitySummary.
        entity_counts: Mapping of community_id to number of traversed
            entities in that community.
        token_budget: Maximum token count for the community section.
            Uses the same chars/4 approximation as the main formatter.
            Setting to 0 returns "".
        section_markers: Marker strings for the community section
            (keys: ``communities_open``, ``communities_close``).

    Returns:
        Formatted community context section, or ``""`` if no summaries
        survive budget truncation or token_budget is 0.
    """
    raise NotImplementedError("Task 5.4")
```

**Key design decisions:**
- Standalone function rather than a method on `GraphContextFormatter` — keeps the formatter's `format()` signature clean and allows independent testing
- Takes pre-resolved `summaries` dict — the lookup from `CommunityDetector` happens in the expander, not here
- Same chars/4 token approximation as the main formatter — consistency over precision

---

## B.12: Community Context Integration — Pattern

Illustrative pattern showing how community context flows through the expander and formatter.

**Tasks:** Task 5.3, Task 5.4, Task 5.6
**Requirements:** REQ-KG-1300, REQ-KG-1302, REQ-KG-1304, REQ-KG-1308
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
# Shows the community context integration flow in GraphQueryExpander.expand()

def expand(self, query: str, depth: Optional[int] = None) -> ExpansionResult:
    # ... existing P1 entity matching, typed traversal, path matching ...
    # At this point we have: seed_entities, all_entities, all_triples, all_paths

    # Phase 2: Community context injection
    community_section = ""
    if (
        self._config
        and self._config.community_context_token_budget > 0
        and self._community_detector is not None
        and self._community_detector.is_ready
    ):
        try:
            # Task 5.3: Collect community IDs from all traversed entities
            community_ids, entity_counts = collect_community_ids(
                entities=all_entities,
                paths=all_paths,
                backend=self._backend,
            )

            # Task 5.4 (REQ-KG-1302): Look up pre-built summaries
            summaries = {}
            for cid in community_ids:
                summary = self._community_detector.get_summary(cid)
                if summary is not None:
                    summaries[cid] = summary

            # Task 5.4 (REQ-KG-1304, REQ-KG-1306): Format with budget
            if summaries:
                community_section = format_community_section(
                    summaries=summaries,
                    entity_counts=entity_counts,
                    token_budget=self._config.community_context_token_budget,
                    section_markers=self._formatter._section_markers,
                )
        except Exception as exc:
            # REQ-KG-1308: Graceful degradation — log and proceed without
            _log.warning(
                "Community context injection failed, proceeding without: %s(%s)",
                type(exc).__name__, exc,
            )

    # Phase 1 context formatting (unchanged)
    graph_context = self._formatter.format(
        entities=all_entities,
        triples=all_triples,
        paths=all_paths,
        seed_entity_names=[e.name for e in seed_entities],
    )

    # Append community section if present
    if community_section:
        graph_context = graph_context + "\n" + community_section if graph_context else community_section

    return ExpansionResult(terms=expansion_terms, graph_context=graph_context)
```

**Key design decisions:**
- Community context is assembled separately from the Phase 1 formatter output, then appended — avoids modifying the Phase 1 `format()` signature or truncation logic
- Single try/except wraps the entire community path — any failure (ID collection, lookup, or formatting) degrades to Phase 1 output
- Guard checks `community_context_token_budget > 0` first — when budget is 0, no community code executes at all
- `is_ready` check prevents attempts when detection/summarization hasn't run

---

## B.13: Verb Normalization Integration — Pattern

Illustrative pattern showing how verb normalization modifies path narrative rendering.

**Tasks:** Task 5.2
**Requirements:** REQ-KG-1310, REQ-KG-1312
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
# Shows verb normalization in _format_path_narratives

import logging
from pathlib import Path
from typing import Dict, Optional

import yaml

_log = logging.getLogger("rag.knowledge_graph.query.context_formatter")


def _load_verb_table(schema_path: Optional[str]) -> Dict[str, str]:
    """Load verb normalization table from kg_schema.yaml.

    Returns empty dict if schema_path is None, file missing,
    or 'verb_normalization' key absent. Never raises.
    """
    if schema_path is None:
        return {}
    try:
        path = Path(schema_path)
        if not path.exists():
            return {}
        with open(path) as f:
            schema = yaml.safe_load(f)
        return schema.get("verb_normalization", {}) or {}
    except Exception as exc:
        _log.warning("Failed to load verb normalization table: %s", exc)
        return {}


def _normalize_predicate(self, predicate: str) -> str:
    """Map predicate label to natural-language verb phrase.

    Uses the verb normalization table if a mapping exists;
    otherwise falls back to underscore-to-space replacement.
    """
    if predicate in self._verb_table:
        return self._verb_table[predicate]
    return predicate.replace("_", " ")


# In _format_path_narratives, replace:
#   predicate_str = first_hop.edge_type.replace("_", " ")
# with:
#   predicate_str = self._normalize_predicate(first_hop.edge_type)
```

**Key design decisions:**
- `_load_verb_table` never raises — returns empty dict on any failure, ensuring Phase 1 fallback behavior
- Table is loaded once at `__init__` time, not per-query (REQ-KG-1332)
- Schema is the single source of truth — no separate config file needed for ~20 entries
