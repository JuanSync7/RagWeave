# Knowledge Graph Retrieval — Implementation Docs

> **For implement-code agents:** This document is your source of truth.
> Read ONLY your assigned task section. Your section contains your FR context,
> Phase 0 contracts inlined, implementation steps, and isolation contract verbatim.
> Do not read the full document, the spec, the design doc, or other task sections.

**Goal:** Make the knowledge graph's typed relationships actionable at query time — typed edge traversal, multi-hop path patterns, graph-context formatting, and prompt injection into the LLM generation prompt.
**Spec:** `docs/knowledge_graph/KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md`
**Design doc:** `docs/knowledge_graph/KNOWLEDGE_GRAPH_RETRIEVAL_DESIGN.md`
**Output path:** `docs/knowledge_graph/KNOWLEDGE_GRAPH_RETRIEVAL_IMPLEMENTATION_DOCS.md`
**Produced by:** write-implementation-docs
**Phase 0 status:** [ ] Awaiting human review

---

## Phase 0: Contract Definitions

### 0.1 Retrieval Schemas

Defines the typed data contracts for KG retrieval: new `KGConfig` fields, `ExpansionResult` with backward-compatible iteration, and `PathResult`/`PathHop` for structured path output.

```python
# src/knowledge_graph/common/schemas.py — additions
# src/knowledge_graph/query/schemas.py — new module

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, List


# ---------------------------------------------------------------------------
# KGConfig additions (add to existing dataclass)
# ---------------------------------------------------------------------------

# retrieval_edge_types: List[str] = field(default_factory=list)
# """REQ-KG-1200: Edge type whitelist for typed traversal. Empty = untyped."""

# retrieval_path_patterns: List[List[str]] = field(default_factory=list)
# """REQ-KG-1202: Ordered edge type sequences for path pattern matching."""

# graph_context_token_budget: int = 500
# """REQ-KG-1204: Max tokens for graph context block in generation prompt."""

# enable_graph_context_injection: bool = False
# """REQ-KG-1206: Master toggle. False = skip all retrieval enhancements."""


# ---------------------------------------------------------------------------
# ExpansionResult — REQ-KG-790
# ---------------------------------------------------------------------------

@dataclass
class ExpansionResult:
    """Return type for GraphQueryExpander.expand().

    Backward-compat: iterating yields the same strings as List[str].
    """

    terms: List[str]                     # REQ-KG-790
    graph_context: str = ""              # REQ-KG-1206

    def __iter__(self) -> Iterator[str]:
        return iter(self.terms)

    def __len__(self) -> int:
        return len(self.terms)

    def __getitem__(self, index: int) -> str:
        return self.terms[index]


# ---------------------------------------------------------------------------
# PathHop / PathResult — REQ-KG-770, REQ-KG-772, REQ-KG-776
# ---------------------------------------------------------------------------

@dataclass
class PathHop:
    """One directed hop in a matched traversal path."""

    from_entity: str                     # REQ-KG-776
    edge_type: str                       # REQ-KG-776
    to_entity: str                       # REQ-KG-776


@dataclass
class PathResult:
    """A fully matched traversal path."""

    pattern_label: str                   # REQ-KG-770
    seed_entity: str                     # REQ-KG-772
    hops: List[PathHop]                  # REQ-KG-776
    terminal_entity: str                 # REQ-KG-776

    @property
    def length(self) -> int:
        return len(self.hops)
```

### 0.2 Validation Module

Defines the validation interface and exception types for retrieval config fields.

```python
# src/knowledge_graph/common/validation.py

from __future__ import annotations

from dataclasses import dataclass
from typing import List


class KGConfigValidationError(Exception):
    """Raised when retrieval config fails schema validation.

    REQ-KG-1208: Accumulates all errors into a single raise.
    """

    def __init__(self, errors: List[str]) -> None:
        self.errors = errors
        formatted = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"KGConfig validation failed:\n{formatted}")


@dataclass
class PatternWarning:
    """Non-fatal warning for type-incompatible consecutive hops.

    REQ-KG-778: Returned (not raised) — callers log at WARNING level.
    """

    pattern_index: int                   # REQ-KG-778
    hop_index: int                       # REQ-KG-778
    edge_type_a: str
    edge_type_b: str
    message: str


def validate_edge_types(edge_types: List[str], schema_path: str) -> None:
    """Validate that all edge types exist in kg_schema.yaml.

    Args:
        edge_types: KGConfig.retrieval_edge_types value.
        schema_path: Path to kg_schema.yaml.

    Raises:
        KGConfigValidationError: If any edge type is unknown.
    """
    raise NotImplementedError("Task 1.3")


def validate_path_patterns(
    patterns: List[List[str]],
    schema_path: str,
) -> List[PatternWarning]:
    """Validate path patterns against schema.

    Args:
        patterns: KGConfig.retrieval_path_patterns value.
        schema_path: Path to kg_schema.yaml.

    Returns:
        List of PatternWarning for type-incompatible hops.

    Raises:
        KGConfigValidationError: If any edge type is unknown.
    """
    raise NotImplementedError("Task 1.3")
```

### 0.3 Backend Typed Traversal

Adds the typed-neighbor method to the backend ABC.

```python
# src/knowledge_graph/backend.py — addition to GraphStorageBackend ABC

from __future__ import annotations

from abc import abstractmethod
from typing import List

from src.knowledge_graph.common import Entity


# Add to GraphStorageBackend class:

@abstractmethod
def query_neighbors_typed(
    self,
    entity: str,
    edge_types: List[str],
    depth: int = 1,
) -> List[Entity]:
    """Return neighbors reachable via edges whose type is in edge_types.

    REQ-KG-760: Backends filter by edge type natively when possible.

    Args:
        entity: Name of the seed entity.
        edge_types: Non-empty whitelist of edge type labels.
        depth: Maximum hop depth (>= 1).

    Returns:
        Deduplicated Entity list within depth hops via matching edges.

    Raises:
        ValueError: If edge_types is empty or depth < 1.
    """
    raise NotImplementedError("Task 1.2")
```

### Error Taxonomy

| Error Type | Trigger Condition | Expected Message Format | Retryable | Raising Module |
|---|---|---|---|---|
| `KGConfigValidationError` | Unknown edge types in `retrieval_edge_types` or `retrieval_path_patterns` at startup | `"KGConfig validation failed:\n  - Unknown edge type 'X' in ..."` | No — config error, fix and restart | `src/knowledge_graph/common/validation.py` |
| `ValueError` | Empty `edge_types` list or `depth < 1` passed to `query_neighbors_typed` | `"edge_types must be non-empty"` / `"depth must be >= 1"` | No — programming error | `src/knowledge_graph/backend.py` |
| `ValueError` | Negative `graph_context_token_budget` in KGConfig | `"graph_context_token_budget must be >= 0"` | No — config error | `src/knowledge_graph/common/schemas.py` |
| `NotImplementedError` | Concrete backend subclass does not override `query_neighbors_typed` | `"Task 1.2"` (stub) → backend name at runtime | No — implementation missing | Backend subclass files |

### Integration Contracts

```
__init__.py → validation.validate_edge_types(edge_types, schema_path) → None
  Called when: startup, enable_graph_context_injection is True
  On KGConfigValidationError: startup fails with accumulated error list

__init__.py → validation.validate_path_patterns(patterns, schema_path) → List[PatternWarning]
  Called when: startup, enable_graph_context_injection is True and patterns non-empty
  On KGConfigValidationError: startup fails with accumulated error list
  On PatternWarning list non-empty: log each at WARNING level, continue

expander.py → backend.query_neighbors_typed(entity, edge_types, depth) → List[Entity]
  Called when: expand() with non-empty retrieval_edge_types
  On ValueError: surfaces unchanged (programming error — should not occur with validated config)
  On Exception (REQ-KG-1214): falls back to untyped query_neighbors, log WARNING

expander.py → PathMatcher.evaluate(seed, patterns) → List[PathResult]
  Called when: expand() with non-empty retrieval_path_patterns
  On Exception (REQ-KG-1214): returns empty list, log WARNING

expander.py → GraphContextFormatter.format(entities, triples, paths) → str
  Called when: expand() with enable_graph_context_injection True
  On Exception (REQ-KG-1214): returns "", log WARNING

rag_chain.py → expander.expand(query) → ExpansionResult
  Called when: KG expansion stage (Stage 2)
  Extracts: .terms for BM25 augmentation, .graph_context for prompt injection
  ExpansionResult is iterable — backward compat with List[str] callers

rag_chain.py → prompt template rendering with graph_context_section
  Called when: building LLM generation prompt
  On graph_context empty: omit section entirely (REQ-KG-796)
```

---

## Task 1.1: KGConfig Retrieval Fields

**Description:** Extend the `KGConfig` dataclass with four new fields that gate and configure graph-context retrieval: `retrieval_edge_types`, `retrieval_path_patterns`, `graph_context_token_budget`, and `enable_graph_context_injection`. Wire environment variable loading and add post-init validation.

**Spec requirements:** REQ-KG-1200, REQ-KG-1202, REQ-KG-1204, REQ-KG-1206, REQ-KG-1208, REQ-KG-1216

**Dependencies:** None

**Source files:**
- MODIFY `src/knowledge_graph/common/schemas.py`
- MODIFY `src/knowledge_graph/__init__.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

```python
# KGConfig additions (add to existing dataclass in src/knowledge_graph/common/schemas.py)

# retrieval_edge_types: List[str] = field(default_factory=list)
# """REQ-KG-1200: Edge type whitelist for typed traversal. Empty = untyped."""

# retrieval_path_patterns: List[List[str]] = field(default_factory=list)
# """REQ-KG-1202: Ordered edge type sequences for path pattern matching."""

# graph_context_token_budget: int = 500
# """REQ-KG-1204: Max tokens for graph context block in generation prompt."""

# enable_graph_context_injection: bool = False
# """REQ-KG-1206: Master toggle. False = skip all retrieval enhancements."""
```

No function stubs — this task adds dataclass fields and env var wiring.

---

**Implementation steps:**

1. [REQ-KG-1200] Add `retrieval_edge_types: List[str] = field(default_factory=list)` to the `KGConfig` dataclass in `src/knowledge_graph/common/schemas.py`
2. [REQ-KG-1202] Add `retrieval_path_patterns: List[List[str]] = field(default_factory=list)` to `KGConfig`
3. [REQ-KG-1204] Add `graph_context_token_budget: int = 500` to `KGConfig`. Add `__post_init__` validation: reject `graph_context_token_budget < 0` with `ValueError`
4. [REQ-KG-1206] Add `enable_graph_context_injection: bool = False` to `KGConfig`
5. [REQ-KG-1216] In `src/knowledge_graph/__init__.py` `_build_kg_config()`, add env var loading block: `RAG_KG_RETRIEVAL_EDGE_TYPES` (comma-split to list), `RAG_KG_RETRIEVAL_PATH_PATTERNS` (JSON parse), `RAG-KG_GRAPH_CONTEXT_TOKEN_BUDGET` (int), `RAG_KG_ENABLE_GRAPH_CONTEXT_INJECTION` (truthy bool)
6. [REQ-KG-1208] Wire startup validation: when `enable_graph_context_injection` is True, call `validate_edge_types()` and `validate_path_patterns()` (implemented in Task 1.3). For now, add a TODO comment noting the validation call site.
7. Update `@summary` block and docstring in both files

**Completion criteria:**
- [ ] All four fields added to `KGConfig` with correct defaults
- [ ] `__post_init__` rejects negative token budget
- [ ] Env var loading wired for all four fields
- [ ] `@summary` block updated in both modified files
- [ ] Module-level docstring updated

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 1.2: Backend Typed Traversal ABC + Implementations

**Description:** Add `query_neighbors_typed(entity: str, edge_types: List[str], depth: int = 1) -> List[Entity]` as an abstract method to the `GraphStorageBackend` ABC. Implement in `NetworkXBackend` using edge predicate filtering and in `Neo4jBackend` with typed Cypher traversal.

**Spec requirements:** REQ-KG-760

**Dependencies:** None

**Source files:**
- MODIFY `src/knowledge_graph/backend.py`
- MODIFY `src/knowledge_graph/backends/networkx_backend.py`
- MODIFY `src/knowledge_graph/backends/neo4j_backend.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

```python
# src/knowledge_graph/backend.py — addition to GraphStorageBackend ABC

from __future__ import annotations

from abc import abstractmethod
from typing import List

from src.knowledge_graph.common import Entity


# Add to GraphStorageBackend class:

@abstractmethod
def query_neighbors_typed(
    self,
    entity: str,
    edge_types: List[str],
    depth: int = 1,
) -> List[Entity]:
    """Return neighbors reachable via edges whose type is in edge_types.

    REQ-KG-760: Backends filter by edge type natively when possible.

    Args:
        entity: Name of the seed entity.
        edge_types: Non-empty whitelist of edge type labels.
        depth: Maximum hop depth (>= 1).

    Returns:
        Deduplicated Entity list within depth hops via matching edges.

    Raises:
        ValueError: If edge_types is empty or depth < 1.
    """
    raise NotImplementedError("Task 1.2")
```

---

**Implementation steps:**

1. [REQ-KG-760] Add the `query_neighbors_typed` abstract method signature to `GraphStorageBackend` in `src/knowledge_graph/backend.py` — exactly as shown in the Phase 0 contract above
2. [REQ-KG-760] Implement in `NetworkXBackend`: BFS using `get_outgoing_edges`/`get_incoming_edges`, filtering each edge by `triple.predicate in edge_types_set`. Deduplicate visited nodes. Clamp depth to `max(1, depth)`. Raise `ValueError` if `edge_types` is empty or `depth < 1`
3. [REQ-KG-760] Implement in `Neo4jBackend`: parameterized Cypher query with relationship type filter (`WHERE type(r) IN $edge_types`). Use variable-length path syntax `[*1..depth]`. Raise `ValueError` on invalid inputs
4. [REQ-KG-760] Add depth clamping guard to both implementations — ensure depth is bounded by any existing `max_depth` configuration
5. Update `@summary` blocks in all three modified files

**Completion criteria:**
- [ ] ABC declares `query_neighbors_typed` as abstract
- [ ] `NetworkXBackend.query_neighbors_typed` implemented with BFS + predicate filter + deduplication
- [ ] `Neo4jBackend.query_neighbors_typed` implemented with typed Cypher
- [ ] Both raise `ValueError` on empty `edge_types` or `depth < 1`
- [ ] Calling with `["nonexistent_predicate"]` returns `[]` without exception
- [ ] `@summary` blocks updated

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 1.3: Schema Validation for Edge Types & Patterns

**Description:** Create `src/knowledge_graph/common/validation.py` implementing schema validation for retrieval config fields. Loads `kg_schema.yaml`, extracts valid edge types, validates `retrieval_edge_types` and `retrieval_path_patterns`. Raises `KGConfigValidationError` for unknown types, returns `PatternWarning` list for non-intersecting consecutive hop types.

**Spec requirements:** REQ-KG-764, REQ-KG-778, REQ-KG-1208

**Dependencies:** Task 1.1

**Source files:**
- CREATE `src/knowledge_graph/common/validation.py`
- MODIFY `src/knowledge_graph/__init__.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

```python
# src/knowledge_graph/common/validation.py

from __future__ import annotations

from dataclasses import dataclass
from typing import List


class KGConfigValidationError(Exception):
    """Raised when retrieval config fails schema validation.

    REQ-KG-1208: Accumulates all errors into a single raise.
    """

    def __init__(self, errors: List[str]) -> None:
        self.errors = errors
        formatted = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"KGConfig validation failed:\n{formatted}")


@dataclass
class PatternWarning:
    """Non-fatal warning for type-incompatible consecutive hops.

    REQ-KG-778: Returned (not raised) — callers log at WARNING level.
    """

    pattern_index: int                   # REQ-KG-778
    hop_index: int                       # REQ-KG-778
    edge_type_a: str
    edge_type_b: str
    message: str


def validate_edge_types(edge_types: List[str], schema_path: str) -> None:
    """Validate that all edge types exist in kg_schema.yaml.

    Args:
        edge_types: KGConfig.retrieval_edge_types value.
        schema_path: Path to kg_schema.yaml.

    Raises:
        KGConfigValidationError: If any edge type is unknown.
    """
    raise NotImplementedError("Task 1.3")


def validate_path_patterns(
    patterns: List[List[str]],
    schema_path: str,
) -> List[PatternWarning]:
    """Validate path patterns against schema.

    Args:
        patterns: KGConfig.retrieval_path_patterns value.
        schema_path: Path to kg_schema.yaml.

    Returns:
        List of PatternWarning for type-incompatible hops.

    Raises:
        KGConfigValidationError: If any edge type is unknown.
    """
    raise NotImplementedError("Task 1.3")
```

---

**Implementation steps:**

1. [REQ-KG-764] Implement `load_kg_schema(schema_path)` helper — reads `kg_schema.yaml` using YAML loader, returns parsed dict. Use the existing `load_schema()` from `src/knowledge_graph/common` if available.
2. [REQ-KG-764] Implement `extract_valid_edge_types(schema)` helper — combines structural and semantic edge type lists from schema into a single `set[str]`
3. [REQ-KG-764] Implement `validate_edge_types()` — check each entry in `edge_types` against the valid set. Accumulate all unknown types. Raise `KGConfigValidationError` with accumulated errors if any found.
4. [REQ-KG-778] Implement `validate_path_patterns()` — first validate all edge type labels exist (same as step 3). Then for each consecutive hop pair, check type compatibility: the target entity types of `pattern[i]` must intersect the source entity types of `pattern[i+1]` per schema constraints. Return `PatternWarning` for non-intersecting pairs.
5. [REQ-KG-1208] Wire validation calls into `_build_kg_config()` in `src/knowledge_graph/__init__.py`: when `enable_graph_context_injection` is True, call `validate_edge_types()` for `retrieval_edge_types` and `validate_path_patterns()` for `retrieval_path_patterns`. Log each `PatternWarning` at WARNING level.
6. Add `@summary` block, module docstring, and per-function docstrings

**Completion criteria:**
- [ ] `validate_edge_types` raises `KGConfigValidationError` for unknown edge types
- [ ] `validate_path_patterns` raises `KGConfigValidationError` for unknown types, returns `PatternWarning` list for type-incompatible consecutive hops
- [ ] Validation wired into startup path when `enable_graph_context_injection` is True
- [ ] Validation skipped when `enable_graph_context_injection` is False
- [ ] `@summary` block at top of new file
- [ ] Module-level docstring present

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.1: Typed Expander Dispatch

**Description:** Modify the `expand()` method in `expander.py` to branch on configuration: when `enable_graph_context_injection` is True and `retrieval_edge_types` is non-empty, call `query_neighbors_typed`; otherwise use existing `query_neighbors`. Same fan-out limits apply to both paths.

**Spec requirements:** REQ-KG-762, REQ-KG-766, REQ-KG-768

**Dependencies:** Task 1.1, Task 1.2

**Source files:**
- MODIFY `src/knowledge_graph/query/expander.py`

---

**Phase 0 contracts (inlined):**

```python
# From 0.3 — the backend method this task dispatches to:

@abstractmethod
def query_neighbors_typed(
    self,
    entity: str,
    edge_types: List[str],
    depth: int = 1,
) -> List[Entity]:
    """Return neighbors reachable via edges whose type is in edge_types.

    REQ-KG-760: Backends filter by edge type natively when possible.

    Args:
        entity: Name of the seed entity.
        edge_types: Non-empty whitelist of edge type labels.
        depth: Maximum hop depth (>= 1).

    Returns:
        Deduplicated Entity list within depth hops via matching edges.

    Raises:
        ValueError: If edge_types is empty or depth < 1.
    """
    raise NotImplementedError("Task 1.2")
```

```python
# From 0.1 — KGConfig fields this task reads:
# retrieval_edge_types: List[str]       — REQ-KG-1200
# enable_graph_context_injection: bool  — REQ-KG-1206
```

No new stubs — this task modifies the existing `expand()` method body.

---

**Implementation steps:**

1. [REQ-KG-762] At the `query_neighbors` call site in `expand()`, add a conditional: if `self._config.enable_graph_context_injection` and `self._config.retrieval_edge_types` is non-empty, call `self._backend.query_neighbors_typed(entity, self._config.retrieval_edge_types, depth=depth)` instead of `self._backend.query_neighbors(entity, depth=depth)`
2. [REQ-KG-768] Extract the fan-out limit logic (max_terms truncation) into a shared helper used by both typed and untyped code paths. Ensure both paths apply the same `max_terms` and `max_depth` limits.
3. [REQ-KG-762] Add DEBUG-level log recording which traversal mode was selected and which edge types were applied: `logger.debug("typed dispatch: edge_types=%s", edge_types)` or `logger.debug("untyped dispatch")`
4. [REQ-KG-766] Verify the untyped fallback: when `retrieval_edge_types` is empty or absent, only `query_neighbors` is called — no typed-traversal code path executes
5. Update `@summary` and docstring in `expander.py`

**Completion criteria:**
- [ ] `expand()` calls `query_neighbors_typed` when both conditions met
- [ ] `expand()` calls `query_neighbors` (unchanged) when either condition is false
- [ ] Fan-out limits shared between both paths
- [ ] DEBUG log records traversal mode
- [ ] `@summary` block updated

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.2: Path Pattern Engine

**Description:** Create `src/knowledge_graph/query/path_matcher.py` with `PathMatcher` class. Evaluates ordered multi-hop path patterns against the graph step-by-step with per-path cycle guard. Returns `PathResult` objects with full hop chains. Supports multiple patterns per query.

**Spec requirements:** REQ-KG-770, REQ-KG-772, REQ-KG-774, REQ-KG-776

**Dependencies:** Task 1.2, Task 1.3

**Source files:**
- CREATE `src/knowledge_graph/query/path_matcher.py`
- CREATE `src/knowledge_graph/query/schemas.py`

---

**Phase 0 contracts (inlined — implement these types):**

```python
# src/knowledge_graph/query/schemas.py — new module

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class PathHop:
    """One directed hop in a matched traversal path."""

    from_entity: str                     # REQ-KG-776
    edge_type: str                       # REQ-KG-776
    to_entity: str                       # REQ-KG-776


@dataclass
class PathResult:
    """A fully matched traversal path."""

    pattern_label: str                   # REQ-KG-770
    seed_entity: str                     # REQ-KG-772
    hops: List[PathHop]                  # REQ-KG-776
    terminal_entity: str                 # REQ-KG-776

    @property
    def length(self) -> int:
        return len(self.hops)
```

```python
# From 0.3 — the backend method used for each hop:

@abstractmethod
def query_neighbors_typed(
    self,
    entity: str,
    edge_types: List[str],
    depth: int = 1,
) -> List[Entity]:
    """..."""
    raise NotImplementedError("Task 1.2")
```

---

**Implementation steps:**

1. [REQ-KG-770, REQ-KG-776] Create `src/knowledge_graph/query/schemas.py` with `PathHop` and `PathResult` dataclasses as shown in Phase 0 contracts above
2. [REQ-KG-770] Create `PathMatcher` class in `src/knowledge_graph/query/path_matcher.py` with `__init__(self, backend: GraphStorageBackend)` storing the backend reference
3. [REQ-KG-774] Implement `evaluate(self, seed_entity: str, patterns: List[List[str]]) -> List[PathResult]` — iterate all patterns, call `_match_pattern()` for each, merge results. Deduplicate by `(seed, terminal, pattern_label)` tuple.
4. [REQ-KG-772] Implement `_match_pattern(self, seed_entity: str, pattern: List[str]) -> List[PathResult]` — step-by-step frontier-based BFS. At each hop, call `query_neighbors_typed(current, [pattern[i]], depth=1)`. Maintain per-path visited set as cycle guard. Build `PathHop` for each step. Return `PathResult` for each frontier entry that survives all hops.
5. [REQ-KG-772] Add fan-out guard: `_MAX_HOP_FANOUT = 50` — at each hop, if the frontier exceeds this, truncate with DEBUG log. This prevents exponential blowup on dense graphs.
6. [REQ-KG-770] Reject empty or null patterns with `ValueError` at `evaluate()` entry
7. Add `@summary` block, module docstring, per-method docstrings

**Completion criteria:**
- [ ] `PathMatcher.evaluate()` processes multiple patterns and merges results
- [ ] `_match_pattern()` performs step-by-step typed traversal with per-path cycle guard
- [ ] Each hop uses `query_neighbors_typed(entity, [edge_type], depth=1)`
- [ ] `PathResult` objects contain full hop chains with intermediate entities
- [ ] Fan-out guard prevents exponential blowup
- [ ] Empty patterns rejected with `ValueError`
- [ ] `@summary` block at top of each new file
- [ ] Module-level docstring present

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.3: Path Pattern Validation Integration

**Description:** Wire schema validation into `PathMatcher` initialization. Validate consecutive hop type compatibility from `kg_schema.yaml` source/target constraints. WARNING for mismatches, error for unknown types.

**Spec requirements:** REQ-KG-778

**Dependencies:** Task 1.3, Task 2.2

**Source files:**
- MODIFY `src/knowledge_graph/query/path_matcher.py`
- MODIFY `src/knowledge_graph/common/validation.py`

---

**Phase 0 contracts (inlined):**

```python
# From 0.2 — the validation functions this task wires in:

def validate_path_patterns(
    patterns: List[List[str]],
    schema_path: str,
) -> List[PatternWarning]:
    """Validate path patterns against schema.

    Args:
        patterns: KGConfig.retrieval_path_patterns value.
        schema_path: Path to kg_schema.yaml.

    Returns:
        List of PatternWarning for type-incompatible hops.

    Raises:
        KGConfigValidationError: If any edge type is unknown.
    """
    raise NotImplementedError("Task 1.3")
```

```python
@dataclass
class PatternWarning:
    pattern_index: int
    hop_index: int
    edge_type_a: str
    edge_type_b: str
    message: str
```

---

**Implementation steps:**

1. [REQ-KG-778] Add `validate_path_patterns()` call to `PathMatcher.__init__` when a `schema_path` is provided. Pass the patterns and schema path. Log each returned `PatternWarning` at WARNING level.
2. [REQ-KG-778] In `validation.py`, implement the consecutive hop intersection check: for each pair `(pattern[i], pattern[i+1])`, look up the target entity types of `pattern[i]` and the source entity types of `pattern[i+1]` from the schema. If the intersection is empty, create a `PatternWarning`.
3. [REQ-KG-778] Add `strict_path_validation` config field (default False) to `KGConfig`. When True, `PatternWarning` entries are promoted to errors (added to `KGConfigValidationError.errors` list).
4. Update `@summary` blocks and docstrings in both modified files

**Completion criteria:**
- [ ] `PathMatcher.__init__` calls validation when schema_path provided
- [ ] Consecutive hop type compatibility check implemented in `validate_path_patterns`
- [ ] Warnings logged, errors raised for unknown types
- [ ] `strict_path_validation` promotes warnings to errors when True
- [ ] `@summary` blocks updated

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 3.1: Graph Context Formatter

**Description:** Create `src/knowledge_graph/query/context_formatter.py` with `GraphContextFormatter` class. Transforms traversal results into a structured text block with three sections: Entity Summaries, Relationship Triples (grouped by predicate), Path Narratives. Enforces token budget with priority-based truncation. Configurable section markers (markdown/xml/plain).

**Spec requirements:** REQ-KG-780, REQ-KG-782, REQ-KG-784, REQ-KG-786, REQ-KG-788

**Dependencies:** Task 2.1, Task 2.2

**Source files:**
- CREATE `src/knowledge_graph/query/context_formatter.py`

---

**Phase 0 contracts (inlined — types this task consumes):**

```python
# From 0.1 — path result types:

@dataclass
class PathHop:
    from_entity: str
    edge_type: str
    to_entity: str

@dataclass
class PathResult:
    pattern_label: str
    seed_entity: str
    hops: List[PathHop]
    terminal_entity: str

    @property
    def length(self) -> int:
        return len(self.hops)
```

```python
# From existing codebase — Entity and Triple types:
# Entity has: name, type, current_summary (optional), raw_mentions (optional), aliases (optional)
# Triple has: subject, predicate, object
```

```python
# From 0.1 — KGConfig field:
# graph_context_token_budget: int = 500  — REQ-KG-1204
```

No stubs — this task creates a new module from scratch.

---

**Implementation steps:**

1. [REQ-KG-780] Create `GraphContextFormatter` class with `__init__(self, token_budget: int, marker_style: str = "markdown")`. Store `_budget_chars = token_budget * _CHARS_PER_TOKEN` (approximate, `_CHARS_PER_TOKEN = 4`).
2. [REQ-KG-780] Implement `format(self, entities: List[Entity], triples: List[Triple], paths: List[PathResult]) -> str` — assembles three sections in order: Entity Summaries, Relationship Triples, Path Narratives. Omit sections with no content.
3. [REQ-KG-782] Implement `_format_entity_summaries(entities)` — for each entity, use `current_summary` if available; fall back to top-K `raw_mentions` (default K=3); use `"[No description available]"` as last resort. Include entity name and type.
4. [REQ-KG-780] Implement `_format_relationship_triples(triples)` — group triples by `predicate`, render each as `subject --[predicate]--> object` under a predicate-type subheading.
5. [REQ-KG-784] Implement `_format_path_narratives(paths)` — for each `PathResult`, produce a human-readable sentence: `"A was fixed by B, which is specified by C"`. Replace underscores with spaces in predicate labels. Truncate paths exceeding max hop count (default 5) with `"[... N additional hops]"`.
6. [REQ-KG-786] Implement `_apply_token_budget(sections)` — priority-based truncation in order: (1) neighbor entity descriptions, (2) relationship triples, (3) path narratives, (4) seed entity descriptions. Seed entity name+type lines never dropped. Emit metadata annotation with truncation counts.
7. [REQ-KG-788] Implement section marker rendering: `markdown` (default) uses `## Graph Context` / `### Entities` etc., `xml` uses `<graph_context>` / `<entities>` etc., `plain` uses `=== GRAPH CONTEXT ===` / `--- ENTITIES ---` etc.
8. Add `@summary` block, module docstring, per-method docstrings

**Completion criteria:**
- [ ] Three-section output: Entity Summaries, Relationship Triples, Path Narratives
- [ ] Entity description fallback chain: current_summary → raw_mentions → placeholder
- [ ] Triples grouped by predicate
- [ ] Path narratives in natural-language form with verb normalization
- [ ] Token budget enforced with priority-based truncation
- [ ] Three marker styles supported (markdown, xml, plain)
- [ ] Empty sections omitted
- [ ] `@summary` block at top of new file
- [ ] Module-level docstring present

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 3.2: Expander Return Type + Pipeline Threading

**Description:** Define `ExpansionResult` dataclass with `terms: List[str]` and `graph_context: str`. Change `expand()` return type. Implement `__iter__`/`__len__`/`__getitem__` for backward compatibility. Thread `graph_context` through `rag_chain.py` to the generation stage.

**Spec requirements:** REQ-KG-790, REQ-KG-792

**Dependencies:** Task 2.1, Task 3.1

**Source files:**
- MODIFY `src/knowledge_graph/query/schemas.py`
- MODIFY `src/knowledge_graph/query/expander.py`
- MODIFY `src/retrieval/pipeline/rag_chain.py`
- MODIFY `src/knowledge_graph/query/__init__.py`

---

**Phase 0 contracts (inlined — implement this type):**

```python
# src/knowledge_graph/query/schemas.py — add to existing module (created in Task 2.2)

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List


@dataclass
class ExpansionResult:
    """Return type for GraphQueryExpander.expand().

    Backward-compat: iterating yields the same strings as List[str].
    """

    terms: List[str]                     # REQ-KG-790
    graph_context: str = ""              # REQ-KG-1206

    def __iter__(self) -> Iterator[str]:
        return iter(self.terms)

    def __len__(self) -> int:
        return len(self.terms)

    def __getitem__(self, index: int) -> str:
        return self.terms[index]
```

---

**Implementation steps:**

1. [REQ-KG-790] Add `ExpansionResult` dataclass to `src/knowledge_graph/query/schemas.py` as shown in the Phase 0 contract above. The `__iter__`, `__len__`, `__getitem__` methods delegate to `self.terms` for backward compatibility.
2. [REQ-KG-790] Update `expand()` in `expander.py` to return `ExpansionResult(terms=terms_list, graph_context=graph_context_str)` instead of a bare `List[str]`. When graph context injection is disabled or formatting is not yet wired, `graph_context` defaults to `""`.
3. [REQ-KG-792] In `src/retrieval/pipeline/rag_chain.py`, update the `expand()` call site (currently `kg_expanded_terms = self._kg_expander.expand(processed_query, depth=1)`). Destructure to: `expansion_result = self._kg_expander.expand(...)`, then `kg_expanded_terms = expansion_result.terms` and `graph_context = expansion_result.graph_context`. Forward `graph_context` as a named parameter to the generation stage.
4. [REQ-KG-790] Export `ExpansionResult` from `src/knowledge_graph/query/__init__.py`
5. Update `@summary` blocks and docstrings in all modified files

**Completion criteria:**
- [ ] `ExpansionResult` defined with iteration protocol
- [ ] `expand()` returns `ExpansionResult`
- [ ] Existing callers that iterate over `expand()` result still work
- [ ] `rag_chain.py` extracts and forwards `graph_context` to generation
- [ ] `graph_context` is `""` when empty — never `None`
- [ ] `@summary` blocks updated

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 3.3: Prompt Template Integration

**Description:** Add a `{graph_context_section}` slot to the LLM prompt template, positioned before document chunks. When `graph_context` is empty, omit the section entirely — no placeholder.

**Spec requirements:** REQ-KG-794, REQ-KG-796

**Dependencies:** Task 3.2

**Source files:**
- MODIFY `src/retrieval/pipeline/rag_chain.py` (prompt assembly section)

---

**Phase 0 contracts (inlined):**

```python
# From 0.1 — ExpansionResult provides the graph_context string:

@dataclass
class ExpansionResult:
    terms: List[str]
    graph_context: str = ""
```

No new stubs — this task modifies prompt template rendering logic.

---

**Implementation steps:**

1. [REQ-KG-794] Locate the prompt template construction in `rag_chain.py` (the section that assembles the system prompt with document chunks). Add a `{graph_context_section}` placeholder positioned before the document chunks section and after the system instruction preamble.
2. [REQ-KG-794] Implement `render_graph_context_section(graph_context: str) -> str` helper function: when `graph_context` is non-empty, return the graph context block as-is (it already has section markers from the formatter); when empty, return `""`.
3. [REQ-KG-796] Wire the helper into the template rendering call site. When `graph_context` is `""`, the section and its heading are completely absent from the rendered prompt — no empty placeholder, no blank lines, no `N/A`.
4. [REQ-KG-796] Verify: rendered prompt with empty `graph_context` is structurally identical to the pre-enhancement prompt
5. Update `@summary` and docstring

**Completion criteria:**
- [ ] Graph context section appears before document chunks when non-empty
- [ ] Section completely absent when `graph_context` is `""`
- [ ] No residual whitespace or placeholder when section is omitted
- [ ] `render_graph_context_section()` helper implemented
- [ ] `@summary` block updated

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 4.1: Graceful Degradation Wrappers

**Description:** Wrap typed traversal and context formatting in try/except blocks in `expander.py`. On typed traversal failure: fall back to untyped expansion, log WARNING. On formatting failure: empty `graph_context`, log WARNING. Neither failure causes the request to fail.

**Spec requirements:** REQ-KG-1214

**Dependencies:** Task 2.1, Task 3.1

**Source files:**
- MODIFY `src/knowledge_graph/query/expander.py`

---

**Phase 0 contracts (inlined):**

```python
# From 0.3 — backend methods involved in degradation:

# query_neighbors_typed(...) — may raise on backend errors
# query_neighbors(...) — untyped fallback target

# From 0.1 — KGConfig fields:
# enable_graph_context_injection: bool — master toggle
```

No new stubs — this task adds exception handling to existing `expand()` flow.

---

**Implementation steps:**

1. [REQ-KG-1214] Wrap the `query_neighbors_typed` call in `expand()` with `try/except Exception`. On failure: log `WARNING` with exception info (`exc_info=True`), fall back to `self._backend.query_neighbors(entity, depth=depth)`. Do NOT catch `SystemExit` or `KeyboardInterrupt`.
2. [REQ-KG-1214] Wrap the `GraphContextFormatter.format()` call in `expand()` with `try/except Exception`. On failure: log `WARNING` with exception info, set `graph_context = ""`. The request continues with an `ExpansionResult` that has empty graph context.
3. [REQ-KG-1214] Wrap the path pattern evaluation call (`PathMatcher.evaluate()`) in `expand()` with `try/except Exception`. On failure: log `WARNING`, use empty paths list.
4. [REQ-KG-1214] Verify: neither fallback block swallows `SystemExit` or `KeyboardInterrupt` — catch `Exception` only, not bare `except:`
5. Update `@summary` and docstring

**Completion criteria:**
- [ ] Typed traversal failure falls back to untyped, WARNING logged
- [ ] Formatting failure results in empty graph_context, WARNING logged
- [ ] Path evaluation failure results in empty paths, WARNING logged
- [ ] Log entries include exception type and message (`exc_info=True`)
- [ ] `SystemExit` and `KeyboardInterrupt` not caught
- [ ] Request never fails due to graph errors
- [ ] `@summary` block updated

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 4.2: Performance Benchmarks

**Description:** Create benchmark scripts measuring typed vs untyped traversal latency on a synthetic 49K-node graph, and context formatting latency at 100/300/500 token payloads. Assert P95 deltas within spec thresholds.

**Spec requirements:** REQ-KG-1210, REQ-KG-1212

**Dependencies:** Task 2.1, Task 3.1

**Source files:**
- CREATE `tests/benchmarks/kg_retrieval_bench.py`
- CREATE `tests/benchmarks/fixtures.py`

---

**Phase 0 contracts (inlined):**

```python
# From 0.3 — backend methods being benchmarked:

# query_neighbors(entity, depth) → List[Entity]       — untyped baseline
# query_neighbors_typed(entity, edge_types, depth) → List[Entity]  — typed variant

# From Task 3.1 — formatter being benchmarked:
# GraphContextFormatter.format(entities, triples, paths) → str
```

No stubs — this task creates new benchmark files.

---

**Implementation steps:**

1. [REQ-KG-1210] Create `tests/benchmarks/fixtures.py` with a `build_synthetic_graph(num_nodes: int = 49_000)` factory. Generate a NetworkX-backed graph with realistic edge type distribution (mix of `depends_on`, `connects_to`, `fixed_by`, `specified_by`, etc.). Return a populated `NetworkXBackend` instance.
2. [REQ-KG-1210] Create `tests/benchmarks/kg_retrieval_bench.py`. Implement typed traversal benchmark: run 100 `query_neighbors_typed` calls and 100 `query_neighbors` calls on the 49K-node graph. Compute P95 for each. Assert P95 delta (typed - untyped) <= 50ms.
3. [REQ-KG-1212] Implement formatting benchmark: call `GraphContextFormatter.format()` 50 times with payloads at 100, 300, and 500 token budgets. Assert P95 wall-clock time <= 100ms for each.
4. Add `@pytest.mark.benchmark` marker to all benchmark tests. Add a smoke-level import test (no timing assertion) for CI.
5. Add `@summary` block, module docstring

**Completion criteria:**
- [ ] Synthetic graph factory generates 49K-node graph with typed edges
- [ ] Traversal benchmark: 100 typed + 100 untyped, P95 delta <= 50ms
- [ ] Formatting benchmark: 50 calls at 100/300/500 tokens, P95 <= 100ms
- [ ] Benchmarks marked with `@pytest.mark.benchmark`, excluded from default test run
- [ ] Smoke import test for CI
- [ ] `@summary` block at top of each new file

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Module Boundary Map

| Task | Source File | Action |
|------|-----------|--------|
| 1.1 | `src/knowledge_graph/common/schemas.py` | MODIFY |
| 1.1 | `src/knowledge_graph/__init__.py` | MODIFY |
| 1.2 | `src/knowledge_graph/backend.py` | MODIFY |
| 1.2 | `src/knowledge_graph/backends/networkx_backend.py` | MODIFY |
| 1.2 | `src/knowledge_graph/backends/neo4j_backend.py` | MODIFY |
| 1.3 | `src/knowledge_graph/common/validation.py` | CREATE |
| 1.3 | `src/knowledge_graph/__init__.py` | MODIFY |
| 2.1 | `src/knowledge_graph/query/expander.py` | MODIFY |
| 2.2 | `src/knowledge_graph/query/path_matcher.py` | CREATE |
| 2.2 | `src/knowledge_graph/query/schemas.py` | CREATE |
| 2.3 | `src/knowledge_graph/query/path_matcher.py` | MODIFY |
| 2.3 | `src/knowledge_graph/common/validation.py` | MODIFY |
| 3.1 | `src/knowledge_graph/query/context_formatter.py` | CREATE |
| 3.2 | `src/knowledge_graph/query/schemas.py` | MODIFY |
| 3.2 | `src/knowledge_graph/query/expander.py` | MODIFY |
| 3.2 | `src/retrieval/pipeline/rag_chain.py` | MODIFY |
| 3.2 | `src/knowledge_graph/query/__init__.py` | MODIFY |
| 3.3 | `src/retrieval/pipeline/rag_chain.py` | MODIFY |
| 4.1 | `src/knowledge_graph/query/expander.py` | MODIFY |
| 4.2 | `tests/benchmarks/kg_retrieval_bench.py` | CREATE |
| 4.2 | `tests/benchmarks/fixtures.py` | CREATE |

**New files (5):** `validation.py`, `path_matcher.py`, `query/schemas.py`, `context_formatter.py`, `kg_retrieval_bench.py` + `fixtures.py`
**Modified files (8):** `common/schemas.py`, `__init__.py`, `backend.py`, `networkx_backend.py`, `neo4j_backend.py`, `expander.py`, `rag_chain.py`, `query/__init__.py`

---

## Dependency Graph

```
                    ┌───────────┐
                    │ Task 1.1  │  KGConfig fields
                    │ (S)       │
                    └─────┬─────┘
                          │
           ┌──────────────┼──────────────┐
           │              │              │
           ▼              ▼              │
    ┌───────────┐  ┌───────────┐        │
    │ Task 1.2  │  │ Task 1.3  │        │
    │ Backend   │  │ Validation│        │
    │ (M)       │  │ (S)       │        │
    └─────┬─────┘  └─────┬─────┘        │
          │              │              │
          ├──────┬───────┤              │
          │      │       │              │
          ▼      ▼       ▼              │
   ┌───────────┐ ┌───────────┐         │
   │ Task 2.1  │ │ Task 2.2  │         │
   │ Dispatch  │ │ PathMatch │         │
   │ (M) [CRIT]│ │ (L)       │         │
   └─────┬─────┘ └─────┬─────┘         │
         │              │              │
         │              ▼              │
         │       ┌───────────┐         │
         │       │ Task 2.3  │         │
         │       │ Validation│         │
         │       │ (S)       │         │
         │       └───────────┘         │
         │              │              │
         ├──────────────┤              │
         │              │              │
         ▼              ▼              │
  ┌───────────┐                       │
  │ Task 3.1  │  Context Formatter    │
  │ (M) [CRIT]│                       │
  └─────┬─────┘                       │
        │                             │
        ▼                             │
  ┌───────────┐                       │
  │ Task 3.2  │  Return Type + Thread │
  │ (M) [CRIT]│                       │
  └─────┬─────┘                       │
        │                             │
        ▼                             │
  ┌───────────┐                       │
  │ Task 3.3  │  Prompt Integration   │
  │ (S) [CRIT]│                       │
  └───────────┘                       │

  ┌───────────┐  ┌───────────┐
  │ Task 4.1  │  │ Task 4.2  │
  │ Degrad.   │  │ Benchmarks│
  │ (S)       │  │ (S)       │
  └───────────┘  └───────────┘

  Deps: 4.1 ← 2.1, 3.1    4.2 ← 2.1, 3.1

  [CRIT] = Critical Path: 1.1 → 1.2 → 2.1 → 3.1 → 3.2 → 3.3
```

**Parallel waves for implement-code:**

| Wave | Tasks | Reason |
|------|-------|--------|
| 1 | 1.1, 1.2 | No inter-task dependencies |
| 2 | 1.3, 2.1 | Both depend on Wave 1 only |
| 3 | 2.2 | Depends on 1.2 + 1.3 |
| 4 | 2.3, 3.1 | 2.3 depends on 1.3 + 2.2; 3.1 depends on 2.1 + 2.2 |
| 5 | 3.2, 4.1, 4.2 | 3.2 depends on 2.1 + 3.1; 4.1/4.2 depend on 2.1 + 3.1 |
| 6 | 3.3 | Depends on 3.2 |

---

## Task-to-FR Traceability Table

| REQ ID | Priority | Task(s) | Source Files |
|--------|----------|---------|-------------|
| REQ-KG-760 | MUST | 1.2 | `backend.py`, `networkx_backend.py`, `neo4j_backend.py` (MODIFY) |
| REQ-KG-762 | MUST | 2.1 | `expander.py` (MODIFY) |
| REQ-KG-764 | MUST | 1.3 | `validation.py` (CREATE), `__init__.py` (MODIFY) |
| REQ-KG-766 | MUST | 2.1 | `expander.py` (MODIFY) |
| REQ-KG-768 | MUST | 2.1 | `expander.py` (MODIFY) |
| REQ-KG-770 | MUST | 2.2 | `path_matcher.py` (CREATE), `query/schemas.py` (CREATE) |
| REQ-KG-772 | MUST | 2.2 | `path_matcher.py` (CREATE) |
| REQ-KG-774 | MUST | 2.2 | `path_matcher.py` (CREATE) |
| REQ-KG-776 | MUST | 2.2 | `path_matcher.py` (CREATE), `query/schemas.py` (CREATE) |
| REQ-KG-778 | MUST | 1.3, 2.3 | `validation.py` (CREATE/MODIFY), `path_matcher.py` (MODIFY) |
| REQ-KG-780 | MUST | 3.1 | `context_formatter.py` (CREATE) |
| REQ-KG-782 | MUST | 3.1 | `context_formatter.py` (CREATE) |
| REQ-KG-784 | MUST | 3.1 | `context_formatter.py` (CREATE) |
| REQ-KG-786 | MUST | 3.1 | `context_formatter.py` (CREATE) |
| REQ-KG-788 | SHOULD | 3.1 | `context_formatter.py` (CREATE) |
| REQ-KG-790 | MUST | 3.2 | `query/schemas.py` (MODIFY), `expander.py` (MODIFY) |
| REQ-KG-792 | MUST | 3.2 | `rag_chain.py` (MODIFY), `query/__init__.py` (MODIFY) |
| REQ-KG-794 | MUST | 3.3 | `rag_chain.py` (MODIFY) |
| REQ-KG-796 | MUST | 3.3 | `rag_chain.py` (MODIFY) |
| REQ-KG-1200 | MUST | 1.1 | `common/schemas.py` (MODIFY) |
| REQ-KG-1202 | MUST | 1.1 | `common/schemas.py` (MODIFY) |
| REQ-KG-1204 | MUST | 1.1 | `common/schemas.py` (MODIFY) |
| REQ-KG-1206 | MUST | 1.1 | `common/schemas.py` (MODIFY) |
| REQ-KG-1208 | MUST | 1.1, 1.3 | `common/schemas.py` (MODIFY), `validation.py` (CREATE), `__init__.py` (MODIFY) |
| REQ-KG-1210 | MUST | 4.2 | `kg_retrieval_bench.py` (CREATE), `fixtures.py` (CREATE) |
| REQ-KG-1212 | MUST | 4.2 | `kg_retrieval_bench.py` (CREATE) |
| REQ-KG-1214 | MUST | 4.1 | `expander.py` (MODIFY) |
| REQ-KG-1216 | MUST | 1.1 | `__init__.py` (MODIFY) |

**Coverage:** 28/28 requirements mapped. 0 orphan tasks. All 11 tasks trace to at least one REQ.
