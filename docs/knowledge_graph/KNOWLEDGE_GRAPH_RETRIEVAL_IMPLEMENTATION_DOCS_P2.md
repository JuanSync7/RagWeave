# Knowledge Graph Retrieval Phase 2 — Implementation Docs

> **For implement-code agents:** Each task section below is self-contained.
> Read ONLY your assigned task section. Do not read source files, other task sections,
> or the design doc directly.

**Goal:** Implement community context injection, verb normalization, and operator configurability
for the KG retrieval subsystem.

**Spec:** `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC_P2.md` (REQ-KG-1300–1334)
**Design doc:** `KNOWLEDGE_GRAPH_RETRIEVAL_DESIGN_P2.md` (Tasks 5.1–5.6)
**Prior phase:** `KNOWLEDGE_GRAPH_RETRIEVAL_IMPLEMENTATION_DOCS.md` (Tasks 1.1–4.2, P1 complete)
**Produced by:** write-implementation-docs
**Phase:** P2

---

## Phase 0: Contract Definitions

### Phase 0a: Established Contracts (from Phase 1)

Interfaces from Phase 1 that this phase's tasks build against. These are **real code** — reference by import path.

| Interface | Source File | Established In | Used By (This Phase) |
|-----------|-----------|---------------|---------------------|
| `KGConfig` | `src/knowledge_graph/common/types.py` | P1 Task 1.1 | Tasks 5.1, 5.2, 5.3, 5.4, 5.5, 5.6 |
| `GraphContextFormatter` | `src/knowledge_graph/query/context_formatter.py` | P1 Task 3.1 | Tasks 5.2, 5.4, 5.6 |
| `PathMatcher` | `src/knowledge_graph/query/path_matcher.py` | P1 Task 2.2 | Task 5.5 |
| `GraphQueryExpander` | `src/knowledge_graph/query/expander.py` | P1 Task 3.3 | Tasks 5.3, 5.6 |
| `ExpansionResult` | `src/knowledge_graph/query/schemas.py` | P1 Task 3.1 | Task 5.6 |
| `PathResult`, `PathHop` | `src/knowledge_graph/query/schemas.py` | P1 Task 2.1 | Task 5.3 |
| `Entity`, `Triple` | `src/knowledge_graph/common/schemas.py` | P1 (parent KG) | Tasks 5.3, 5.4 |
| `CommunitySummary` | `src/knowledge_graph/community/schemas.py` | P1 (parent KG Phase 2) | Task 5.4 |
| `CommunityDetector` | `src/knowledge_graph/community/detector.py` | P1 (parent KG Phase 2) | Tasks 5.3, 5.4, 5.6 |
| `GraphStorageBackend` | `src/knowledge_graph/backend.py` | P1 (parent KG) | Task 5.3 |

Import block for task agents:

```python
# Phase 0a — established contracts (real code, do not redefine)
from src.knowledge_graph.common.types import KGConfig
from src.knowledge_graph.common.schemas import Entity, Triple
from src.knowledge_graph.query.schemas import ExpansionResult, PathResult, PathHop
from src.knowledge_graph.query.context_formatter import GraphContextFormatter
from src.knowledge_graph.query.path_matcher import PathMatcher
from src.knowledge_graph.query.expander import GraphQueryExpander
from src.knowledge_graph.community.schemas import CommunitySummary
from src.knowledge_graph.community.detector import CommunityDetector
from src.knowledge_graph.backend import GraphStorageBackend
```

---

### Phase 0b: New Contracts (this phase)

#### New KGConfig Fields

```python
# Add to existing KGConfig in src/knowledge_graph/common/types.py
# These fields are NEW — add after the existing retrieval fields.

# Phase 2: Community context + operator configurability (REQ-KG-1320..1326)
# community_context_token_budget: int = 200    # REQ-KG-1320 — independent budget for community section
# graph_context_marker_style: str = "markdown"  # REQ-KG-1322 — "markdown" | "xml" | "plain"
# max_hop_fanout: int = 50                      # REQ-KG-1324 — replaces _MAX_HOP_FANOUT constant

# __post_init__ validation additions:
# if self.graph_context_marker_style not in {"markdown", "xml", "plain"}:
#     raise ValueError(...)
# if self.max_hop_fanout < 1:
#     raise ValueError(...)
# if self.community_context_token_budget < 0:
#     raise ValueError(...)
```

#### New Environment Variables

```python
# Add to config/settings.py — follows existing RAG_KG_ convention

RAG_KG_COMMUNITY_CONTEXT_TOKEN_BUDGET: int = 200     # REQ-KG-1320
RAG_KG_GRAPH_CONTEXT_MARKER_STYLE: str = "markdown"   # REQ-KG-1322
RAG_KG_MAX_HOP_FANOUT: int = 50                       # REQ-KG-1324
```

#### Verb Normalization Schema Extension

```yaml
# Add to config/kg_schema.yaml under top level

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

#### Function Stubs

```python
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from src.knowledge_graph.common.schemas import Entity
from src.knowledge_graph.query.schemas import PathResult
from src.knowledge_graph.community.schemas import CommunitySummary
from src.knowledge_graph.backend import GraphStorageBackend


def collect_community_ids(
    entities: List[Entity],
    paths: List[PathResult],
    backend: GraphStorageBackend,
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

#### Error Taxonomy (accumulated from P1)

| Exception | Module | When Raised | Introduced |
|-----------|--------|-------------|-----------|
| `KGConfigValidationError` | `common/validation.py` | Invalid edge types or path patterns in config | P1 |
| `PatternWarning` | `common/validation.py` | Hop type incompatibility in path patterns (non-fatal) | P1 |
| `ValueError` | `common/types.py` | Invalid config field values (`marker_style`, `max_hop_fanout < 1`, `community_context_token_budget < 0`) | P1 (extended P2) |

No new exception classes in Phase 2. `ValueError` from `KGConfig.__post_init__` is extended with three new validation checks.

#### Integration Contracts

```
config/settings.py → KGConfig.__init__()
    Env vars flow into KGConfig fields. P2 adds 3 new vars.

GraphQueryExpander.expand() → collect_community_ids()
    After typed traversal + path matching, expander calls collect_community_ids
    with all traversed entities and paths. Returns (community_ids, entity_counts).
    On error: expander catches, logs WARNING, proceeds without community context.

GraphQueryExpander.expand() → CommunityDetector.get_summary(cid)
    For each community ID, looks up pre-built summary. Returns CommunitySummary or None.
    Zero-cost dict lookup. No LLM calls.

GraphQueryExpander.expand() → format_community_section()
    Formats retrieved summaries into text section with independent budget.
    On error: expander catches, logs WARNING, proceeds without community context.

GraphContextFormatter.__init__() → _load_verb_table(schema_path)
    Loads verb normalization table from kg_schema.yaml once at init.
    On error: returns empty dict, falls back to underscore replacement.

GraphContextFormatter._format_path_narratives() → _normalize_predicate()
    Each predicate checked against verb table. Hit → mapped phrase. Miss → replace("_", " ").
```

---

## Task 5.1: Configuration Fields and Environment Variables

**Description:** Add three new `KGConfig` fields (`community_context_token_budget`, `graph_context_marker_style`, `max_hop_fanout`) with corresponding `RAG_KG_` environment variable bindings in `settings.py`. Add validation for each field.

**Spec requirements:** REQ-KG-1320, REQ-KG-1322, REQ-KG-1324, REQ-KG-1326

**Dependencies:** None (P1 complete — extends established `KGConfig`)

**Source files:**
- MODIFY `src/knowledge_graph/common/types.py`
- MODIFY `config/settings.py`
- MODIFY `src/knowledge_graph/__init__.py`

---

**Phase 0 contracts (inlined):**

```python
# Established in P1 — real implementation at src/knowledge_graph/common/types.py
from src.knowledge_graph.common.types import KGConfig

# NEW fields to add to KGConfig:
# community_context_token_budget: int = 200    # REQ-KG-1320
# graph_context_marker_style: str = "markdown"  # REQ-KG-1322
# max_hop_fanout: int = 50                      # REQ-KG-1324

# NEW __post_init__ validations:
# graph_context_marker_style not in {"markdown", "xml", "plain"} → ValueError
# max_hop_fanout < 1 → ValueError
# community_context_token_budget < 0 → ValueError

# NEW env vars in config/settings.py:
# RAG_KG_COMMUNITY_CONTEXT_TOKEN_BUDGET: int = 200
# RAG_KG_GRAPH_CONTEXT_MARKER_STYLE: str = "markdown"
# RAG_KG_MAX_HOP_FANOUT: int = 50
```

---

**Implementation steps:**

1. [REQ-KG-1320] Add `community_context_token_budget: int = 200` field to `KGConfig` dataclass after the existing `strict_path_validation` field
2. [REQ-KG-1322] Add `graph_context_marker_style: str = "markdown"` field to `KGConfig`
3. [REQ-KG-1324] Add `max_hop_fanout: int = 50` field to `KGConfig`
4. [REQ-KG-1320, 1322, 1324] Add `__post_init__` validation: `marker_style` enum check, `max_hop_fanout >= 1`, `community_context_token_budget >= 0`
5. [REQ-KG-1326] Add `RAG_KG_COMMUNITY_CONTEXT_TOKEN_BUDGET`, `RAG_KG_GRAPH_CONTEXT_MARKER_STYLE`, `RAG_KG_MAX_HOP_FANOUT` to `config/settings.py`
6. [REQ-KG-1326] Wire new env vars into KGConfig construction in `src/knowledge_graph/__init__.py` retrieval settings block

**Completion criteria:**
- [ ] All three fields added to `KGConfig` with correct types and defaults
- [ ] `__post_init__` validation raises `ValueError` for invalid values
- [ ] All three env vars defined in `settings.py`
- [ ] `__init__.py` reads env vars and passes to KGConfig

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 5.2: Verb Normalization Table Loading

**Description:** Load a verb normalization table from `kg_schema.yaml` under a `verb_normalization` key and use it in path narrative rendering. When a predicate has a mapping, use the mapped verb phrase; otherwise fall back to underscore-to-space replacement. The table is loaded once at formatter initialization.

**Spec requirements:** REQ-KG-1310, REQ-KG-1312, REQ-KG-1332

**Dependencies:** Task 5.1

**Source files:**
- MODIFY `src/knowledge_graph/query/context_formatter.py`
- MODIFY `config/kg_schema.yaml`

---

**Phase 0 contracts (inlined):**

```python
# Established in P1 — real implementation at src/knowledge_graph/query/context_formatter.py
from src.knowledge_graph.query.context_formatter import GraphContextFormatter
# GraphContextFormatter.__init__(token_budget, marker_style, description_fallback_k, max_path_hops)
# GraphContextFormatter._format_path_narratives(paths) — uses replace("_", " ") for predicates

# NEW: Add schema_path parameter to __init__ for verb table loading
# NEW: Add _load_verb_table(schema_path) helper — loads once, returns Dict[str, str]
# NEW: Add _normalize_predicate(predicate) method — table lookup with fallback
```

```yaml
# NEW: Add to config/kg_schema.yaml top level
verb_normalization:
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

---

**Implementation steps:**

1. [REQ-KG-1312] Add `verb_normalization` key with all edge type mappings to `config/kg_schema.yaml`
2. [REQ-KG-1332] Add `_load_verb_table(schema_path: Optional[str]) -> Dict[str, str]` module-level function to `context_formatter.py` — loads YAML once, returns verb dict. Returns empty dict on any error (file missing, key absent, parse error). Never raises.
3. [REQ-KG-1310] Add `schema_path: Optional[str] = None` parameter to `GraphContextFormatter.__init__`. Call `_load_verb_table(schema_path)` and store as `self._verb_table`.
4. [REQ-KG-1310] Add `_normalize_predicate(self, predicate: str) -> str` method — returns `self._verb_table[predicate]` if present, else `predicate.replace("_", " ")`
5. [REQ-KG-1310] Replace all `replace("_", " ")` calls in `_format_path_narratives` with `self._normalize_predicate()`
6. Update `@summary` block and module-level docstring

**Completion criteria:**
- [ ] Verb table loaded from schema once at init, cached as `self._verb_table`
- [ ] Path narratives use mapped phrases for mapped predicates
- [ ] Missing schema or key produces empty table (no error)
- [ ] No file I/O on second call to `format()`

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 5.3: Community ID Collection from Traversal

**Description:** After typed traversal and path pattern matching, collect the `community_id` attribute from every entity encountered — seeds, typed neighbors, and all entities on matched path hops. Produce a deduplicated set of community IDs (excluding -1) and a per-community entity count for budget truncation priority.

**Spec requirements:** REQ-KG-1300

**Dependencies:** Task 5.1

**Source files:**
- MODIFY `src/knowledge_graph/query/expander.py`

---

**Phase 0 contracts (inlined):**

```python
from __future__ import annotations
from typing import Dict, List, Optional, Set, Tuple
from src.knowledge_graph.common.schemas import Entity
from src.knowledge_graph.query.schemas import PathResult
from src.knowledge_graph.backend import GraphStorageBackend


def collect_community_ids(
    entities: List[Entity],
    paths: List[PathResult],
    backend: GraphStorageBackend,
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

---

**Implementation steps:**

1. [REQ-KG-1300] Add `collect_community_ids` function to `expander.py` (or as a module-level helper)
2. [REQ-KG-1300] For each entity in `entities`, extract `community_id` from `entity.community_id` attribute (if present). Use `getattr(entity, 'community_id', None)` for safe access.
3. [REQ-KG-1300] For each path in `paths`, iterate over `path.hops` and look up each `hop.from_entity` and `hop.to_entity` via the backend to get their community IDs. Use `backend.get_entity(name)` if available, or graph node attribute lookup.
4. [REQ-KG-1300] Exclude `community_id == -1` and `None` values. Build `entity_counts: Dict[int, int]` counting how many traversed entities belong to each community.
5. [REQ-KG-1300] Return `(community_ids_set, entity_counts)`
6. Update `@summary` block

**Completion criteria:**
- [ ] Function returns deduplicated set of community IDs
- [ ] Community ID -1 excluded
- [ ] Entities without community_id silently skipped
- [ ] Entity counts accurate per community
- [ ] Community IDs collected from both entities and path hops

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 5.4: Community Summary Lookup and Formatting

**Description:** For each community ID collected by Task 5.3, look up the pre-built `CommunitySummary` via `CommunityDetector.get_summary()`. Format retrieved summaries into a "Community Context" section in the graph context block. Apply an independent token sub-budget, dropping communities with fewest traversed entities first when over budget.

**Spec requirements:** REQ-KG-1302, REQ-KG-1304, REQ-KG-1306

**Dependencies:** Task 5.3

**Source files:**
- MODIFY `src/knowledge_graph/query/context_formatter.py`

---

**Phase 0 contracts (inlined):**

```python
from __future__ import annotations
from typing import Dict, List, Optional, Set, Tuple
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

```python
# Established in P1 — CommunityDetector API
from src.knowledge_graph.community.detector import CommunityDetector
# CommunityDetector.get_summary(community_id: int) -> Optional[CommunitySummary]
# CommunityDetector.is_ready -> bool
```

---

**Implementation steps:**

1. [REQ-KG-1304] Add community section markers to `_get_section_markers()` in `GraphContextFormatter`: markdown `### Communities`, xml `<communities>...</communities>`, plain `--- COMMUNITIES ---`
2. [REQ-KG-1304] Implement `format_community_section()` — for each summary, render as `[Community {id}] ({N} entities touched): {summary_text}`
3. [REQ-KG-1306] Add budget truncation: calculate char budget as `token_budget * 4`, sort communities by `entity_counts[cid]` ascending, drop lowest-count communities until within budget
4. [REQ-KG-1304] Wrap formatted lines with section markers (open + lines + close)
5. [REQ-KG-1306] Return `""` when token_budget is 0 or no summaries survive truncation
6. Update `@summary` block and module-level docstring

**Completion criteria:**
- [ ] Community section renders with correct entry format
- [ ] Budget truncation drops lowest-entity-count communities first
- [ ] `token_budget=0` returns empty string
- [ ] All three marker styles include community section markers
- [ ] Empty summaries dict produces no section

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 5.5: Max Hop Fanout from Config

**Description:** Replace the module-level constant `_MAX_HOP_FANOUT = 50` in `path_matcher.py` with a config-driven value. `PathMatcher` reads `max_hop_fanout` at construction time.

**Spec requirements:** REQ-KG-1324

**Dependencies:** Task 5.1

**Source files:**
- MODIFY `src/knowledge_graph/query/path_matcher.py`

---

**Phase 0 contracts (inlined):**

```python
# Established in P1 — real implementation at src/knowledge_graph/query/path_matcher.py
from src.knowledge_graph.query.path_matcher import PathMatcher
# PathMatcher.__init__(backend, schema_path=None)
# Module constant: _MAX_HOP_FANOUT = 50

# NEW: Add max_hop_fanout parameter to __init__
# PathMatcher.__init__(backend, schema_path=None, max_hop_fanout=50)
# Replace _MAX_HOP_FANOUT references with self._max_hop_fanout
```

---

**Implementation steps:**

1. [REQ-KG-1324] Add `max_hop_fanout: int = 50` parameter to `PathMatcher.__init__`
2. [REQ-KG-1324] Store as `self._max_hop_fanout`
3. [REQ-KG-1324] Replace all references to `_MAX_HOP_FANOUT` module constant with `self._max_hop_fanout` in `_match_pattern`
4. [REQ-KG-1324] Keep `_MAX_HOP_FANOUT = 50` as a module constant for backward compatibility (default value reference), but the instance attribute takes precedence
5. Update `@summary` block

**Completion criteria:**
- [ ] `PathMatcher.__init__` accepts `max_hop_fanout` parameter
- [ ] `_match_pattern` uses `self._max_hop_fanout` instead of module constant
- [ ] Default behavior unchanged (50) when parameter not specified

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 5.6: Graceful Degradation and End-to-End Integration

**Description:** Wire all Phase 2 features into the expander and formatter with graceful degradation. Community context injection is wrapped in a try/except that falls back to Phase 1 behavior on any error. All Phase 2 features degrade to exact Phase 1 output when their dependencies are unavailable.

**Spec requirements:** REQ-KG-1308, REQ-KG-1334, REQ-KG-1330

**Dependencies:** Task 5.2, Task 5.4, Task 5.5

**Source files:**
- MODIFY `src/knowledge_graph/query/expander.py`
- MODIFY `src/knowledge_graph/query/context_formatter.py`
- MODIFY `src/knowledge_graph/__init__.py`

---

**Phase 0 contracts (inlined):**

```python
# Established in P1 — real implementations
from src.knowledge_graph.query.expander import GraphQueryExpander
# GraphQueryExpander.__init__(backend, max_depth, max_terms, community_detector, enable_global_retrieval, config)
# GraphQueryExpander.expand(query, depth) -> ExpansionResult

from src.knowledge_graph.query.context_formatter import GraphContextFormatter
# GraphContextFormatter.__init__(token_budget, marker_style, description_fallback_k, max_path_hops)
# NEW P2: + schema_path parameter (Task 5.2)

from src.knowledge_graph.query.path_matcher import PathMatcher
# PathMatcher.__init__(backend, schema_path)
# NEW P2: + max_hop_fanout parameter (Task 5.5)

# NEW P2 functions (Tasks 5.3, 5.4):
# collect_community_ids(entities, paths, backend) -> (Set[int], Dict[int, int])
# format_community_section(summaries, entity_counts, token_budget, section_markers) -> str

from src.knowledge_graph.community.detector import CommunityDetector
# CommunityDetector.get_summary(cid) -> Optional[CommunitySummary]
# CommunityDetector.is_ready -> bool
```

---

**Implementation steps:**

1. [REQ-KG-1334] In `GraphQueryExpander.__init__`, thread `config.graph_context_marker_style` to `GraphContextFormatter(marker_style=...)` and `config.max_hop_fanout` to `PathMatcher(max_hop_fanout=...)`
2. [REQ-KG-1334] In `GraphQueryExpander.__init__`, thread `config.schema_path` to `GraphContextFormatter(schema_path=...)` for verb normalization loading
3. [REQ-KG-1308] In `expand()`, after typed traversal + path matching produces entities/triples/paths, add community context injection block:
   - Guard: `config.community_context_token_budget > 0 and community_detector is not None and community_detector.is_ready`
   - Call `collect_community_ids(all_entities, all_paths, backend)`
   - For each community ID, call `community_detector.get_summary(cid)`, skip None
   - Call `format_community_section(summaries, entity_counts, config.community_context_token_budget, formatter._section_markers)`
   - Wrap entire block in `try/except Exception` — on error, log WARNING with exception details, set `community_section = ""`
4. [REQ-KG-1304] Append community section to graph context: `graph_context + "\n" + community_section` if both non-empty
5. [REQ-KG-1334] Verify degradation: when `CommunityDetector` is None → community block skipped, output identical to P1
6. [REQ-KG-1334] Verify degradation: when `community_context_token_budget=0` → community block skipped
7. [REQ-KG-1334] In `__init__.py`, update `get_query_expander()` to pass `config.graph_context_marker_style`, `config.max_hop_fanout`, and `config.schema_path` through to the expander/formatter/matcher constructors

**Completion criteria:**
- [ ] Community context appended to graph context when available
- [ ] Any community error produces WARNING log + Phase 1 fallback
- [ ] Missing detector → no community section
- [ ] `community_context_token_budget=0` → no community section
- [ ] Config fields thread correctly through constructor chain
- [ ] Output identical to Phase 1 when all P2 deps unavailable

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Module Boundary Map

| Task | Source Files | Action |
|------|-------------|--------|
| 5.1 | `src/knowledge_graph/common/types.py` | MODIFY |
| 5.1 | `config/settings.py` | MODIFY |
| 5.1 | `src/knowledge_graph/__init__.py` | MODIFY |
| 5.2 | `src/knowledge_graph/query/context_formatter.py` | MODIFY |
| 5.2 | `config/kg_schema.yaml` | MODIFY |
| 5.3 | `src/knowledge_graph/query/expander.py` | MODIFY |
| 5.4 | `src/knowledge_graph/query/context_formatter.py` | MODIFY |
| 5.5 | `src/knowledge_graph/query/path_matcher.py` | MODIFY |
| 5.6 | `src/knowledge_graph/query/expander.py` | MODIFY |
| 5.6 | `src/knowledge_graph/query/context_formatter.py` | MODIFY |
| 5.6 | `src/knowledge_graph/__init__.py` | MODIFY |

**All files are MODIFY** — no new files created in Phase 2.

---

## Dependency Graph

```
--- Prior Phase Boundary (P1 Tasks 1.1–4.2 complete) ---

Wave 1:
  Task 5.1: Config fields + env vars              [no deps]

Wave 2 (parallel after 5.1):
  Task 5.2: Verb normalization                     [depends: 5.1]
  Task 5.3: Community ID collection                [depends: 5.1]
  Task 5.5: Max hop fanout from config             [depends: 5.1]

Wave 3:
  Task 5.4: Community summary formatting           [depends: 5.3]  [CRITICAL]

Wave 4:
  Task 5.6: Degradation + integration              [depends: 5.2, 5.4, 5.5]  [CRITICAL]
```

**Critical path:** 5.1 → 5.3 → 5.4 → 5.6

---

## Task-to-FR Traceability Table

| Task | FR (This Phase) | Extends (Prior Phase) | Source Files |
|------|-----------------|----------------------|-------------|
| 5.1 | REQ-KG-1320, 1322, 1324, 1326 | KGConfig (P1) | `types.py`, `settings.py`, `__init__.py` (MODIFY) |
| 5.2 | REQ-KG-1310, 1312, 1332 | context_formatter (P1) | `context_formatter.py`, `kg_schema.yaml` (MODIFY) |
| 5.3 | REQ-KG-1300 | expander (P1) | `expander.py` (MODIFY) |
| 5.4 | REQ-KG-1302, 1304, 1306 | context_formatter (P1) | `context_formatter.py` (MODIFY) |
| 5.5 | REQ-KG-1324 | path_matcher (P1) | `path_matcher.py` (MODIFY) |
| 5.6 | REQ-KG-1308, 1334, 1330 | expander, formatter (P1) | `expander.py`, `context_formatter.py`, `__init__.py` (MODIFY) |

**Coverage:** 14/14 requirements mapped. No orphan tasks. No orphan FRs.
