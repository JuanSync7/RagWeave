# Knowledge Graph Retrieval — Design Document

| Field | Value |
|-------|-------|
| **Document** | Knowledge Graph Retrieval Design Document |
| **Version** | 0.1 |
| **Status** | Draft |
| **Spec Reference** | `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md` (REQ-KG-760–799, 1200–1219) |
| **Companion Documents** | `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md`, `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC_SUMMARY.md` |
| **Output Path** | `docs/knowledge_graph/KNOWLEDGE_GRAPH_RETRIEVAL_DESIGN.md` |
| **Produced by** | write-design-docs |
| **Task Decomposition Status** | [x] Approved |

> **Document Intent.** This document provides a technical design with task decomposition
> and contract-grade code appendix for the Knowledge Graph Retrieval subsystem specified in
> `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md`. Every task references the requirements it satisfies.
> Part B contract entries are consumed verbatim by the companion implementation docs.

---

# Part A: Task-Oriented Overview

## Phase 1 — Foundation

### Task 1.1: KGConfig Retrieval Fields

**Description:** Extend the `KGConfig` dataclass with four new fields that gate and configure graph-context retrieval: `retrieval_edge_types` (List[str], default `[]`), `retrieval_path_patterns` (List[List[str]], default `[]`), `graph_context_token_budget` (int, default `500`), and `enable_graph_context_injection` (bool, default `False`). Wire env var loading with `RAG_KG_` prefix and add a post-init validation hook.

**Requirements Covered:** REQ-KG-1200, REQ-KG-1202, REQ-KG-1204, REQ-KG-1206, REQ-KG-1208, REQ-KG-1216

**Dependencies:** None

**Complexity:** S

**Subtasks:**
1. Add the four new fields with defaults to `KGConfig` in `src/knowledge_graph/common/schemas.py`
2. Add `__post_init__` validation: reject `graph_context_token_budget < 0`
3. Add env var loading in `src/knowledge_graph/__init__.py` for `RAG_KG_RETRIEVAL_EDGE_TYPES` (comma-split), `RAG_KG_RETRIEVAL_PATH_PATTERNS` (JSON), `RAG_KG_GRAPH_CONTEXT_TOKEN_BUDGET` (int), `RAG_KG_ENABLE_GRAPH_CONTEXT_INJECTION` (bool)
4. Update `@summary` block and docstring

**Testing Strategy:** Unit tests for default values, env var override (mocked), and validation error on invalid config.

---

### Task 1.2: Backend Typed Traversal ABC + Implementations

**Description:** Add `query_neighbors_typed(entity: str, edge_types: List[str], depth: int = 1) -> List[Entity]` to the `GraphStorageBackend` ABC. Implement in `NetworkXBackend` using edge predicate filtering and in `Neo4jBackend` with typed Cypher traversal.

**Requirements Covered:** REQ-KG-760

**Dependencies:** None

**Complexity:** M

**Subtasks:**
1. Add abstract method signature to `GraphStorageBackend` in `backend.py`
2. Implement in `NetworkXBackend`: BFS with `get_outgoing_edges`/`get_incoming_edges` filtered by predicate
3. Implement in `Neo4jBackend`: parameterized Cypher with relationship type filter
4. Add depth clamping guard to both implementations
5. Update `@summary` blocks

**Risks:** Neo4j variable-length relationship type filtering syntax varies by driver version — verify against pinned version. NetworkX BFS must deduplicate visited nodes to prevent blowup on dense graphs.

**Testing Strategy:** Unit tests with in-memory NetworkX fixture; integration tests for Neo4j with mock driver verifying Cypher shape.

---

### Task 1.3: Schema Validation for Edge Types & Patterns

**Description:** Create `src/knowledge_graph/common/validation.py` that loads `kg_schema.yaml`, extracts valid edge types, and validates `retrieval_edge_types` and `retrieval_path_patterns`. Raises `KGConfigValidationError` for unknown types, emits WARNING for non-intersecting consecutive hop types.

**Requirements Covered:** REQ-KG-764, REQ-KG-778

**Dependencies:** Task 1.1

**Complexity:** S

**Subtasks:**
1. Create `validation.py` with `load_kg_schema()` and `extract_valid_edge_types()` helpers
2. Implement `validate_edge_types()` — check each entry against schema
3. Implement `validate_path_patterns()` — check existence + consecutive hop type compatibility
4. Wire validation into KGConfig loading (only when `enable_graph_context_injection` is True)

**Testing Strategy:** Unit tests with fixture schema; assert errors for unknown types, warnings for type mismatches.

---

## Phase 2 — Traversal Logic

### Task 2.1: Typed Expander Dispatch

**Description:** Modify `expand()` in `expander.py` to branch on config: when `enable_graph_context_injection` is True and `retrieval_edge_types` is non-empty, call `query_neighbors_typed`; otherwise use existing `query_neighbors`. Same fan-out limits apply to both paths.

**Requirements Covered:** REQ-KG-762, REQ-KG-766, REQ-KG-768

**Dependencies:** Task 1.1, Task 1.2

**Complexity:** M

**Subtasks:**
1. Add conditional dispatch at the `query_neighbors` call site
2. Extract fan-out limit logic into shared helper used by both paths
3. Add DEBUG log recording traversal mode and edge types
4. Preserve existing return type (deferred to Task 3.2)
5. Update `@summary` and docstring

**Risks:** Regression in untyped path if fan-out extraction changes behavior — verify with regression tests.

**Testing Strategy:** Parameterized tests across all 4 branch combinations; verify `query_neighbors_typed` called only when both conditions met.

---

### Task 2.2: Path Pattern Engine

**Description:** Create `src/knowledge_graph/query/path_matcher.py` with `PathMatcher` class. Evaluates ordered multi-hop path patterns against the graph step-by-step with cycle guard. Returns `PathResult` objects with full hop chains. Supports multiple patterns per query.

**Requirements Covered:** REQ-KG-770, REQ-KG-772, REQ-KG-774, REQ-KG-776

**Dependencies:** Task 1.2, Task 1.3

**Complexity:** L

**Subtasks:**
1. Define `PathResult` and `PathHop` dataclasses (see B.1)
2. Implement `PathMatcher.__init__` with backend reference and validation call
3. Implement `_evaluate_pattern()` — step-by-step BFS with per-path visited set
4. Implement `evaluate()` — iterate all patterns, merge results, deduplicate
5. Add fan-out guard per hop (configurable `_MAX_HOP_FANOUT`, default 50)
6. Add `@summary`, module docstring, per-method docstrings

**Risks:** Path evaluation is exponential in fan-out × pattern length. The hop fan-out guard is the critical safety valve — must be well-documented and testable.

**Testing Strategy:** Unit tests with synthetic graph fixture; assert correct chains, cycle guard, deduplication, fan-out cap, and zero-result case.

---

### Task 2.3: Path Pattern Validation Integration

**Description:** Wire schema validation into `PathMatcher` initialization. Validate consecutive hop type compatibility from `kg_schema.yaml` source/target constraints. WARNING for mismatches, error for unknown types.

**Requirements Covered:** REQ-KG-778

**Dependencies:** Task 1.3, Task 2.2

**Complexity:** S

**Subtasks:**
1. Add `validate_path_patterns()` call to `PathMatcher.__init__`
2. Implement consecutive hop intersection check in validation module
3. Add `strict_path_validation` config field (default False) to promote warnings to errors
4. Log warnings via standard logger

**Testing Strategy:** Unit tests with fixture schema; assert errors for unknown types, warnings for mismatches, promotion to error in strict mode.

---

## Phase 3 — Context & Prompt

### Task 3.1: Graph Context Formatter

**Description:** Create `src/knowledge_graph/query/context_formatter.py` with `GraphContextFormatter`. Transforms traversal results into a structured text block with three sections: Entity Summaries, Relationship Triples (grouped by predicate), Path Narratives. Enforces token budget with priority-based truncation. Configurable section markers (markdown/xml/plain).

**Requirements Covered:** REQ-KG-780, REQ-KG-782, REQ-KG-784, REQ-KG-786, REQ-KG-788

**Dependencies:** Task 2.1, Task 2.2

**Complexity:** M

**Subtasks:**
1. Define `GraphContextInput` dataclass grouping all inputs
2. Implement `_format_entity_summaries()` with current_summary/raw_mentions fallback
3. Implement `_format_relationship_triples()` grouped by predicate
4. Implement `_format_path_narratives()` with verb normalization
5. Implement `_apply_token_budget()` with priority-based truncation
6. Implement `format()` assembling sections with configurable markers
7. Add `@summary`, module docstring

**Risks:** Character-to-token approximation is imprecise — document it and add an injection point for exact tokenizer.

**Testing Strategy:** Unit tests for each section formatter; token budget tests across priority levels; section marker tests for all three modes.

---

### Task 3.2: Expander Return Type + Pipeline Threading

**Description:** Define `ExpansionResult` dataclass with `terms: List[str]` and `graph_context: str`. Change `expand()` return type. Implement `__iter__`/`__len__`/`__getitem__` for backward compat. Thread `graph_context` through `rag_chain.py` to generation stage.

**Requirements Covered:** REQ-KG-790, REQ-KG-792

**Dependencies:** Task 2.1, Task 3.1

**Complexity:** M

**Subtasks:**
1. Create `src/knowledge_graph/query/schemas.py` with `ExpansionResult`
2. Implement iteration protocol (`__iter__`, `__len__`, `__getitem__`) delegating to `terms`
3. Update `expand()` to return `ExpansionResult`
4. Update `rag_chain.py` to destructure `ExpansionResult` and forward `graph_context`
5. Update public exports in `query/__init__.py`

**Risks:** `isinstance(result, list)` checks in existing code will break — audit codebase before merge.

**Testing Strategy:** Unit tests for iteration compat; integration test through rag_chain asserting graph_context reaches generation; regression test for existing callers.

---

### Task 3.3: Prompt Template Integration

**Description:** Add `{graph_context_section}` slot to the LLM prompt template, positioned before document chunks. When empty, omit entirely — no placeholder.

**Requirements Covered:** REQ-KG-794, REQ-KG-796

**Dependencies:** Task 3.2

**Complexity:** S

**Subtasks:**
1. Locate the prompt template module
2. Add `{graph_context_section}` placeholder before document chunks
3. Implement `render_graph_context_section()` helper (non-empty: passthrough, empty: "")
4. Wire into template rendering call site
5. Update `@summary` and docstring

**Testing Strategy:** Unit tests for helper; snapshot tests on rendered prompt for empty and non-empty cases.

---

## Phase 4 — Resilience & Performance

### Task 4.1: Graceful Degradation Wrappers

**Description:** Wrap typed traversal and context formatting in try/except blocks in `expander.py`. On typed traversal failure: fall back to untyped, log WARNING. On formatting failure: empty graph_context, log WARNING. Query never fails.

**Requirements Covered:** REQ-KG-1214

**Dependencies:** Task 2.1, Task 3.1

**Complexity:** S

**Subtasks:**
1. Wrap `query_neighbors_typed` call in try/except with untyped fallback
2. Wrap `GraphContextFormatter.format()` call in try/except with empty-string fallback
3. Verify neither block swallows `SystemExit`/`KeyboardInterrupt`
4. Add degradation metric increment if observability hook exists

**Testing Strategy:** Mock backend/formatter raising RuntimeError; assert fallback taken, WARNING logged, valid ExpansionResult returned.

---

### Task 4.2: Performance Benchmarks

**Description:** Create benchmark scripts measuring typed vs untyped traversal latency on a synthetic 49K-node graph, and context formatting latency at 100/300/500 token payloads. Assert P95 deltas within spec thresholds.

**Requirements Covered:** REQ-KG-1210, REQ-KG-1212

**Dependencies:** Task 2.1, Task 3.1

**Complexity:** S

**Subtasks:**
1. Create `tests/benchmarks/fixtures.py` with synthetic graph factory
2. Implement traversal latency benchmark (100 typed + 100 untyped, assert P95 delta)
3. Implement formatting latency benchmark (parameterized at 100/300/500 tokens)
4. Add `@pytest.mark.benchmark` marker excluded from default test run

**Testing Strategy:** The benchmarks are the tests. Add a smoke-level import test for CI.

---

## Task Dependency Graph

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
                                      │
  ┌───────────┐  ┌───────────┐       │
  │ Task 4.1  │  │ Task 4.2  │       │
  │ Degrad.   │  │ Benchmarks│       │
  │ (S)       │  │ (S)       │       │
  └───────────┘  └───────────┘       │

  [CRIT] = Critical Path: 1.1 → 1.2 → 2.1 → 3.1 → 3.2 → 3.3
```

---

## Task-to-Requirement Mapping

| REQ ID | Priority | Task(s) |
|--------|----------|---------|
| REQ-KG-760 | MUST | 1.2 |
| REQ-KG-762 | MUST | 2.1 |
| REQ-KG-764 | MUST | 1.3 |
| REQ-KG-766 | MUST | 2.1 |
| REQ-KG-768 | MUST | 2.1 |
| REQ-KG-770 | MUST | 2.2 |
| REQ-KG-772 | MUST | 2.2 |
| REQ-KG-774 | MUST | 2.2 |
| REQ-KG-776 | MUST | 2.2 |
| REQ-KG-778 | MUST | 1.3, 2.3 |
| REQ-KG-780 | MUST | 3.1 |
| REQ-KG-782 | MUST | 3.1 |
| REQ-KG-784 | MUST | 3.1 |
| REQ-KG-786 | MUST | 3.1 |
| REQ-KG-788 | SHOULD | 3.1 |
| REQ-KG-790 | MUST | 3.2 |
| REQ-KG-792 | MUST | 3.2 |
| REQ-KG-794 | MUST | 3.3 |
| REQ-KG-796 | MUST | 3.3 |
| REQ-KG-1200 | MUST | 1.1 |
| REQ-KG-1202 | MUST | 1.1 |
| REQ-KG-1204 | MUST | 1.1 |
| REQ-KG-1206 | MUST | 1.1 |
| REQ-KG-1208 | MUST | 1.1, 1.3 |
| REQ-KG-1210 | MUST | 4.2 |
| REQ-KG-1212 | MUST | 4.2 |
| REQ-KG-1214 | MUST | 4.1 |
| REQ-KG-1216 | MUST | 1.1 |

**Coverage:** 28/28 requirements mapped. 0 orphan tasks.

---

# Part B: Code Appendix

## B.1: Retrieval Schemas — Contract

Defines the typed data contracts for KG retrieval: new `KGConfig` fields, `ExpansionResult` with backward-compatible iteration, and `PathResult`/`PathHop` for structured path output.

**Tasks:** Task 1.1, Task 3.2
**Requirements:** REQ-KG-1200, REQ-KG-1202, REQ-KG-1204, REQ-KG-1206, REQ-KG-790
**Type:** Contract (exact — copied to implementation docs Phase 0)

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

**Key design decisions:**
- `ExpansionResult` implements `__iter__`/`__len__`/`__getitem__` so existing callers treating the return as `List[str]` require no changes
- `PathHop` is separate from `PathResult` so the formatter can operate on individual hops
- KGConfig fields shown as comments to indicate insertion points in the existing dataclass

---

## B.2: Validation Module — Contract

Defines the validation interface and exception types for retrieval config fields.

**Tasks:** Task 1.3
**Requirements:** REQ-KG-764, REQ-KG-778, REQ-KG-1208
**Type:** Contract (exact — copied to implementation docs Phase 0)

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

**Key design decisions:**
- `KGConfigValidationError` accumulates all errors so operators see every problem in one startup failure
- Type-incompatibility is a `PatternWarning` (not error) because compatibility is data-dependent
- Functions accept `schema_path` as string so validation runs before full backend instantiation

---

## B.3: Backend Typed Traversal — Contract

Adds the typed-neighbor method to the backend ABC.

**Tasks:** Task 1.2
**Requirements:** REQ-KG-760
**Type:** Contract (exact — copied to implementation docs Phase 0)

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

**Key design decisions:**
- `@abstractmethod` so backends that don't implement it fail at instantiation, not runtime
- `ValueError` on empty `edge_types` prevents silent full-graph scans
- Docstring permits fallback-to-`query_neighbors`-plus-filter for backends with limited query APIs

---

## B.4: Path Pattern Engine — Pattern

Illustrates step-by-step path pattern evaluation with per-path cycle guard.

**Tasks:** Task 2.2
**Requirements:** REQ-KG-770, REQ-KG-772, REQ-KG-774, REQ-KG-776
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
# src/knowledge_graph/query/path_matcher.py

from __future__ import annotations

import logging
from typing import List

from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.common.schemas import PathHop, PathResult

logger = logging.getLogger(__name__)


class PathMatcher:
    """Evaluates ordered path patterns against the KG."""

    def __init__(self, backend: GraphStorageBackend) -> None:
        self._backend = backend

    def evaluate(
        self, seed_entity: str, patterns: List[List[str]]
    ) -> List[PathResult]:
        results: List[PathResult] = []
        for pattern in patterns:
            results.extend(self._match_pattern(seed_entity, pattern))
        return results

    def _match_pattern(
        self, seed_entity: str, pattern: List[str]
    ) -> List[PathResult]:
        if not pattern:
            return []

        label = "->".join(pattern)
        # frontier: (current_entity, hops_so_far, visited_set)
        frontier = [(seed_entity, [], {seed_entity})]

        for edge_type in pattern:
            next_frontier = []
            for current, hops, visited in frontier:
                try:
                    neighbors = self._backend.query_neighbors_typed(
                        entity=current, edge_types=[edge_type], depth=1
                    )
                except Exception:
                    logger.warning(
                        "typed traversal failed for %r edge=%r",
                        current, edge_type, exc_info=True,
                    )
                    continue

                for neighbor in neighbors:
                    if neighbor.name in visited:
                        continue  # cycle guard
                    new_hops = hops + [
                        PathHop(current, edge_type, neighbor.name)
                    ]
                    next_frontier.append(
                        (neighbor.name, new_hops, visited | {neighbor.name})
                    )

            frontier = next_frontier
            if not frontier:
                return []

        return [
            PathResult(label, seed_entity, hops, terminal)
            for terminal, hops, _ in frontier
        ]
```

**Key design decisions:**
- Frontier carries `(entity, hops, visited)` triples — visited set is per-path, allowing diamond-shaped graphs while blocking true cycles
- One `query_neighbors_typed(depth=1)` call per frontier node per step keeps memory bounded
- Exceptions caught per-branch so one bad node doesn't abort the entire pattern

---

## B.5: Graph Context Formatter — Pattern

Illustrates three-section context assembly with token budget truncation.

**Tasks:** Task 3.1
**Requirements:** REQ-KG-780, REQ-KG-782, REQ-KG-784, REQ-KG-786, REQ-KG-788
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
# src/knowledge_graph/query/context_formatter.py

from __future__ import annotations

import logging
from typing import List

from src.knowledge_graph.common import Entity, Triple
from src.knowledge_graph.common.schemas import PathResult

logger = logging.getLogger(__name__)


class GraphContextFormatter:
    """Assembles a prompt-injectable graph context string."""

    _CHARS_PER_TOKEN = 4  # approximate

    def __init__(self, token_budget: int) -> None:
        self._budget_chars = token_budget * self._CHARS_PER_TOKEN

    def format(
        self,
        entities: List[Entity],
        triples: List[Triple],
        paths: List[PathResult],
    ) -> str:
        lines: List[str] = []

        if entities:
            lines.append("### Entities")
            for e in entities:
                aliases = f" (also: {', '.join(e.aliases)})" if e.aliases else ""
                lines.append(f"- **{e.name}** [{e.type}]{aliases}")

        if triples:
            lines.append("### Relationships")
            for t in triples:
                lines.append(
                    f"- {t.subject} --[{t.predicate}]--> {t.object}"
                )

        if paths:
            lines.append("### Paths")
            for p in paths:
                chain = " -> ".join(
                    f"{h.from_entity} --[{h.edge_type}]--> {h.to_entity}"
                    for h in p.hops
                )
                lines.append(f"- {chain}")

        return self._truncate(lines)

    def _truncate(self, lines: List[str]) -> str:
        kept: List[str] = []
        used = 0
        for line in lines:
            cost = len(line) + 1
            if used + cost > self._budget_chars:
                logger.debug(
                    "graph context truncated at %d chars; %d lines dropped",
                    used, len(lines) - len(kept),
                )
                break
            kept.append(line)
            used += cost
        return "\n".join(kept)
```

**Key design decisions:**
- Token budget converted to character count once at construction — avoids tokenizer dependency
- Truncation iterates forward, breaking at first over-budget line — section headers always followed by content
- Static helpers for entity/triple formatting enable independent unit testing

---

## B.6: Typed Expander Dispatch — Pattern

Illustrates the revised `expand()` flow with config-gated dispatch and graceful degradation.

**Tasks:** Task 2.1, Task 4.1
**Requirements:** REQ-KG-762, REQ-KG-766, REQ-KG-768, REQ-KG-1214
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
# src/knowledge_graph/query/expander.py

from __future__ import annotations

import logging
from typing import List

from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.common import Entity
from src.knowledge_graph.common.schemas import ExpansionResult, KGConfig
from src.knowledge_graph.query.context_formatter import GraphContextFormatter
from src.knowledge_graph.query.path_matcher import PathMatcher

logger = logging.getLogger(__name__)


class GraphQueryExpander:

    def __init__(self, backend: GraphStorageBackend, config: KGConfig) -> None:
        self._backend = backend
        self._config = config
        self._path_matcher = PathMatcher(backend)
        self._formatter = GraphContextFormatter(config.graph_context_token_budget)

    def expand(self, query: str) -> ExpansionResult:
        # Stage 1: typed or untyped neighbor expansion
        neighbors = self._expand_neighbors(query)
        terms = [e.name for e in neighbors]

        # Stage 2: path pattern evaluation
        paths = self._evaluate_paths(query)

        # Stage 3: context formatting (only if enabled)
        graph_context = ""
        if self._config.enable_graph_context_injection:
            graph_context = self._format_context(neighbors, paths)

        return ExpansionResult(terms=terms, graph_context=graph_context)

    def _expand_neighbors(self, query: str) -> List[Entity]:
        try:
            if self._config.retrieval_edge_types:
                logger.debug("typed dispatch: edge_types=%s", self._config.retrieval_edge_types)
                return self._backend.query_neighbors_typed(
                    query, self._config.retrieval_edge_types,
                    depth=self._config.max_expansion_depth,
                )
            else:
                logger.debug("untyped dispatch")
                return self._backend.query_neighbors(
                    query, depth=self._config.max_expansion_depth,
                )
        except Exception:
            logger.warning("Neighbor expansion failed", exc_info=True)
            return []

    def _evaluate_paths(self, seed: str) -> list:
        if not self._config.retrieval_path_patterns:
            return []
        try:
            return self._path_matcher.evaluate(seed, self._config.retrieval_path_patterns)
        except Exception:
            logger.warning("Path evaluation failed", exc_info=True)
            return []

    def _format_context(self, neighbors: List[Entity], paths: list) -> str:
        try:
            triples = []
            for e in neighbors:
                triples.extend(self._backend.get_outgoing_edges(e.name))
            return self._formatter.format(neighbors, triples, paths)
        except Exception:
            logger.warning("Context formatting failed", exc_info=True)
            return ""
```

**Key design decisions:**
- Each stage isolated in its own method with its own try/except — backend error in stage 1 doesn't prevent valid `ExpansionResult` (REQ-KG-1214)
- `enable_graph_context_injection` gates formatting before entry — zero overhead when disabled
- `_evaluate_paths` returns early when patterns are empty — preserves legacy zero-overhead path
