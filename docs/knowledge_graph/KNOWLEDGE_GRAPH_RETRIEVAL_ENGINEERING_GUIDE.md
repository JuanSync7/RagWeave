# Knowledge Graph Retrieval — Engineering Guide

> **Document type:** Post-implementation engineering reference
> **Companion spec:** `docs/knowledge_graph/KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md`
> **Companion design:** `docs/knowledge_graph/KNOWLEDGE_GRAPH_RETRIEVAL_DESIGN.md`
> **Source location:** `src/knowledge_graph/query/`, `src/knowledge_graph/common/validation.py`
> **Last updated:** 2026-04-14

---

## 1. System Overview

### Purpose

The KG Retrieval subsystem makes the knowledge graph's typed relationships actionable at query time. Without it, the graph stores rich ASIC domain knowledge (fix policies, port connectivity, specification traceability, design decisions) but the retrieval pipeline treats all edges identically during BFS expansion. This subsystem adds edge-type-filtered traversal, multi-hop path pattern matching, structured graph context formatting, and prompt injection — so the LLM receives both expansion terms *and* relationship-aware context alongside document chunks.

The subsystem is opt-in: when `enable_graph_context_injection` is `False` (the default), the pre-existing untyped expansion code path runs with zero overhead.

### Architecture at a Glance

```
User Query
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ Entity Matching (existing)                            │
│   Produces: seed_entities[]                           │
└──────────────────┬───────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────┐
│ GraphQueryExpander.expand()                           │
│   ┌────────────────────────────────────────┐         │
│   │ Typed/Untyped Dispatch                 │         │
│   │   config.retrieval_edge_types? ───┐    │         │
│   │     YES → query_neighbors_typed   │    │         │
│   │     NO  → query_neighbors         │    │         │
│   └───────────────────┬────────────────┘   │         │
│                       │                              │
│   ┌───────────────────▼────────────────┐   │         │
│   │ PathMatcher.evaluate()             │   │         │
│   │   Step-by-step frontier BFS        │   │         │
│   │   Per-path cycle guard             │   │         │
│   │   Fan-out cap: 50 per hop          │   │         │
│   └───────────────────┬────────────────┘   │         │
│                       │                              │
│   ┌───────────────────▼────────────────┐   │         │
│   │ GraphContextFormatter.format()     │   │         │
│   │   Entity summaries + triples +     │   │         │
│   │   path narratives → token budget   │   │         │
│   └───────────────────┬────────────────┘   │         │
│                       │                              │
│   Returns: ExpansionResult(terms, graph_context)      │
└──────────────────┬───────────────────────────────────┘
                   │
          ┌────────┴────────┐
          ▼                 ▼
  BM25 augmentation   Prompt injection
  (terms[:3])         (graph_context before doc chunks)
          │                 │
          └────────┬────────┘
                   ▼
           LLM Generation
```

### Design Goals

1. **Typed-first, untyped-fallback** — When edge-type filters are configured, only matching edges are followed. When no filters are configured, existing BFS applies unchanged. Zero regression.
2. **Graph context is additive** — Graph-derived context supplements document chunks, never replaces them.
3. **Schema-validated paths** — Invalid edge types in config are rejected at startup, not silently ignored at query time.
4. **Bounded complexity** — Path pattern traversal respects the same fan-out limits as untyped expansion.
5. **Graceful degradation** — Any graph error falls back silently with a WARNING log. The request never fails because of graph enrichment.

### Technology Choices

| Technology | Role | Why |
|-----------|------|-----|
| `frozenset` for visited sets | Per-path cycle guard in PathMatcher | Immutable — safe to share across frontier branches without accidental mutation |
| Character-based token approximation (`chars/4`) | Token budget enforcement | Avoids tokenizer dependency; stays fast; ±20-30% variance is acceptable for a budget that truncates conservatively |
| Internal tag prefixes (`__seed__`/`__neighbour__`) | Priority-based truncation in formatter | Enables O(n) truncation without maintaining a separate priority index structure |

---

## 2. Architecture Decisions

### Decision: New `query_neighbors_typed` ABC method vs. filter parameter on existing `query_neighbors`

**Context:** The backend needed typed traversal. Two approaches: add a new method or extend the existing method signature.

**Options considered:**
1. **New method `query_neighbors_typed`** — clean contract, no signature pollution, backends that don't support it fail at instantiation
2. **Add `edge_types: Optional[List[str]] = None` to `query_neighbors`** — fewer methods, but optional parameter changes the semantic contract

**Choice:** New method

**Rationale:** Adding an optional filter to `query_neighbors` silently changes behavior for all existing callers (they would need to pass `None` explicitly to get untyped behavior). A separate method makes the typed/untyped distinction explicit and lets the expander dispatch cleanly.

**Consequences:**
- **Positive:** Clear API boundary; backends fail at class instantiation if they don't implement it
- **Negative:** Two traversal methods to maintain
- **Watch for:** If more traversal variants emerge, consider a strategy/visitor pattern

---

### Decision: `ExpansionResult` with iteration protocol vs. breaking the `List[str]` return type

**Context:** `expand()` returned `List[str]`. Adding `graph_context` required a new return type.

**Options considered:**
1. **`ExpansionResult` dataclass with `__iter__`/`__len__`/`__getitem__`** — backward-compatible iteration
2. **`Tuple[List[str], str]`** — simpler, but breaks all callers
3. **Separate `expand()` and `expand_with_context()`** — no breaking change, but callers must know which to call

**Choice:** `ExpansionResult` with iteration protocol

**Rationale:** The dataclass delegates `__iter__`, `__len__`, `__getitem__` to `self.terms`, so existing code like `for term in expander.expand(query)` and `terms[:3]` continues to work. New callers access `.graph_context` directly.

**Consequences:**
- **Positive:** Zero migration for existing callers
- **Negative:** `isinstance(result, list)` checks will fail — audited and none found in the codebase
- **Watch for:** If any downstream code does `type(result) is list`, it will break

---

### Decision: Graph context positioned before document chunks in prompt

**Context:** The graph context block needed a fixed position in the LLM prompt.

**Options considered:**
1. **Before document chunks** — background knowledge as a lens for reading evidence
2. **After document chunks** — evidence first, graph as supplemental
3. **Interleaved per-chunk** — each chunk gets its relevant graph context

**Choice:** Before document chunks

**Rationale:** LLMs attend to earlier context as "priming" for later content. Placing graph relationships first gives the model a structural frame for interpreting document evidence. This mirrors how a human expert reviews background knowledge before reading source documents.

---

## 3. Module Reference

*Each section below is self-contained. You can read any section independently.*

---

### `src/knowledge_graph/query/schemas.py` — Retrieval Type Definitions

**Purpose:**

Defines the typed data contracts for KG retrieval query results: `ExpansionResult` (the new return type for `expand()`), `PathHop` (one directed edge traversal), and `PathResult` (a complete multi-hop path). These types are the shared language between the expander, path matcher, and context formatter.

```python
@dataclass
class ExpansionResult:
    terms: List[str]           # BM25 augmentation terms
    graph_context: str = ""    # formatted text for prompt injection

    def __iter__(self) -> Iterator[str]:   # backward compat
        return iter(self.terms)
    def __len__(self) -> int:
        return len(self.terms)
    def __getitem__(self, index: int) -> str:
        return self.terms[index]

@dataclass
class PathHop:
    from_entity: str
    edge_type: str
    to_entity: str

@dataclass
class PathResult:
    pattern_label: str         # e.g. "fixed_by->specified_by"
    seed_entity: str
    hops: List[PathHop]
    terminal_entity: str
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| `ExpansionResult` with iteration protocol | Tuple return, separate method | Backward-compatible — existing `for term in expand()` callers work unchanged |
| `PathHop` separate from `PathResult` | Embedded tuples | Formatter operates on individual hops for narrative generation |

---

### `src/knowledge_graph/common/validation.py` — Schema Validation

**Purpose:**

Validates retrieval configuration fields (`retrieval_edge_types`, `retrieval_path_patterns`) against the canonical edge type vocabulary in `kg_schema.yaml`. Catches configuration errors at startup rather than producing silent zero-result queries at runtime.

**How it works:**

1. `validate_edge_types(edge_types, schema_path)` loads the YAML schema, extracts all valid edge type names from both structural and semantic sections, and checks each configured edge type against this set. Unknown types are accumulated into a single `KGConfigValidationError`.

2. `validate_path_patterns(patterns, schema_path, strict=False)` runs in two passes:
   - **Error pass:** Every edge type label in every pattern must exist in the schema. All unknowns are collected and raised together.
   - **Warning pass:** For consecutive hops `(pattern[i], pattern[i+1])`, checks whether the target entity types of hop i intersect the source entity types of hop i+1 per schema constraints. Non-intersecting pairs produce `PatternWarning` objects (logged at WARNING level). If `strict=True`, warnings are promoted to errors.

3. Schema loading uses `load_schema()` from `src.knowledge_graph.common.types` when available, with a direct `yaml.safe_load` fallback for bootstrap scenarios.

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Accumulate all errors before raising | Raise on first error | Operators see every problem in one startup failure instead of fix-restart-fix cycles |
| Type incompatibility is a warning, not error | Hard error on all mismatches | Compatibility is data-dependent — schema constraints may not capture all valid paths |
| `strict` parameter (default False) | Always warn | Allows strict mode for CI/staging without blocking production |

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `strict_path_validation` | `bool` | `False` | When True, type-incompatibility warnings become errors |

**Error behavior:**

- `KGConfigValidationError` — raised when any edge type is unknown. Contains `.errors: List[str]` with all offending types. Callers should let this propagate to fail startup.
- `FileNotFoundError` — raised when `schema_path` doesn't exist.
- `PatternWarning` — returned (not raised) for non-fatal type-incompatibility. Callers log at WARNING level.

---

### `src/knowledge_graph/query/path_matcher.py` — Path Pattern Engine

**Purpose:**

Evaluates ordered multi-hop path patterns against the knowledge graph. Given a seed entity and a list of patterns (each an ordered sequence of edge types), the `PathMatcher` performs step-by-step typed traversal with per-path cycle guards and returns `PathResult` objects containing the full hop chain.

**How it works:**

1. `evaluate(seed_entity, patterns)` iterates all patterns, calls `_match_pattern()` for each, and deduplicates results by `(seed, terminal, pattern_label)` tuple.

2. `_match_pattern(seed_entity, pattern)` uses a frontier-based BFS:
   - Initial frontier: `[(seed_entity, [], frozenset({seed_entity}))]`
   - For each edge type in the pattern sequence:
     - For each frontier entry, call `query_neighbors_typed(entity, [edge_type], depth=1)`
     - For each neighbor not in the visited set (cycle guard), create a new frontier entry with the hop appended
     - Apply fan-out guard: if frontier exceeds `_MAX_HOP_FANOUT` (50), truncate with DEBUG log
   - If frontier is empty after any step, return `[]` — no fallback to BFS
   - Convert surviving frontier entries into `PathResult` objects

```python
# Core frontier step (from _match_pattern):
for edge_type in pattern:
    next_frontier = []
    for current, hops, visited in frontier:
        neighbors = self._backend.query_neighbors_typed(
            entity=current, edge_types=[edge_type], depth=1
        )
        for neighbor in neighbors:
            if neighbor.name in visited:
                continue  # per-path cycle guard
            new_hops = hops + [PathHop(current, edge_type, neighbor.name)]
            next_frontier.append(
                (neighbor.name, new_hops, visited | frozenset({neighbor.name}))
            )
    # Fan-out guard: cap at 50 entries per hop
    if len(next_frontier) > _MAX_HOP_FANOUT:
        next_frontier = next_frontier[:_MAX_HOP_FANOUT]
    frontier = next_frontier
```

3. When `schema_path` is set on the constructor, `evaluate()` calls `validate_path_patterns()` before processing. Validation warnings are logged at WARNING level.

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Per-path visited set (`frozenset`) | Global visited set | Allows diamond-shaped graphs (A→B→D, A→C→D) while blocking true cycles (A→B→A) |
| Fan-out cap at 50 per hop | No cap; configurable cap | Fixed cap prevents exponential blowup on dense structural edges; 50 is generous for most patterns |
| `query_neighbors_typed(..., depth=1)` per hop | Single multi-hop query | Step-by-step control over each edge type; matches the pattern semantics exactly |
| Exception caught per-branch, not per-pattern | Abort entire pattern on error | One bad node doesn't suppress results from other frontier branches |

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `_MAX_HOP_FANOUT` | `int` (module constant) | `50` | Maximum frontier entries per hop step. Truncation logged at DEBUG level. |

**Error behavior:**

- `ValueError` — raised when `patterns` is empty or any individual pattern is empty/null.
- Backend exceptions during `query_neighbors_typed` are caught per-branch with WARNING log. The branch is skipped but other branches continue.
- `KGConfigValidationError` — raised (from validation module) if patterns contain unknown edge types and `schema_path` is set.

---

### `src/knowledge_graph/query/context_formatter.py` — Graph Context Formatter

**Purpose:**

Transforms graph traversal results (entities, triples, paths) into a structured text block for LLM prompt injection. The output has three sections (Entity Summaries, Relationship Triples, Path Narratives) with configurable section markers (markdown/xml/plain) and a token budget enforced through priority-based truncation.

**How it works:**

1. `format(entities, triples, paths, seed_entity_names=None)` is the main entry point:
   - Calls three section formatters to produce line lists
   - Applies token budget truncation
   - Assembles non-empty sections with appropriate markers
   - Returns `""` if all sections are empty

2. **Entity summaries** (`_format_entity_summaries`):
   - Each entity: `"- **name** [type]: description (also: aliases)"`
   - Description priority: `current_summary` → top-K `raw_mentions` → `"[No description available]"`
   - Lines are internally tagged with `__seed__` or `__neighbour__` prefixes for budget prioritization

3. **Relationship triples** (`_format_relationship_triples`):
   - Grouped by predicate using `collections.defaultdict`
   - Each group: bold predicate heading + `"- subject --[predicate]--> object"` per triple

4. **Path narratives** (`_format_path_narratives`):
   - Builds natural-language sentences: `"A fixed by B, which specified by C"`
   - Underscores replaced with spaces in predicate labels
   - Paths exceeding `max_path_hops` truncated with `"[... N additional hops]"`

5. **Token budget** (`_apply_token_budget`):
   - Budget in chars = `token_budget * 4` (approximate)
   - Four-phase truncation (lowest priority dropped first):
     1. Neighbour entity descriptions
     2. Relationship triple groups (smallest group first)
     3. Path narratives (trailing first)
     4. Seed entity descriptions (name+type stub preserved)
   - Emits `"[Context truncated: ...]"` annotation when content is dropped
   - Budget of `0` disables truncation entirely

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Character-based token approximation (`chars/4`) | Real tokenizer | Avoids LLM provider dependency; fast at inference time; ±20-30% variance acceptable |
| Internal tag prefixes for priority tracking | Separate priority map | O(n) inline — no additional data structure to maintain |
| Truncation drops entire groups/lines, not partial | Character-level truncation | Produces coherent partial context rather than cut-off sentences |
| Three marker styles (markdown/xml/plain) | Single style | Different deployment surfaces impose different formatting constraints |

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `token_budget` | `int` | `500` | Max tokens for the entire output block. 0 = unlimited. |
| `marker_style` | `str` | `"markdown"` | Section header style: `"markdown"`, `"xml"`, or `"plain"` |
| `description_fallback_k` | `int` | `3` | Number of raw_mentions to use when current_summary is absent |
| `max_path_hops` | `int` | `5` | Paths longer than this are truncated with ellipsis |

**Error behavior:**

- `ValueError` — raised when `marker_style` is not one of the three supported values.
- All other errors propagate to the caller (the expander catches them for graceful degradation).

---

### `src/knowledge_graph/query/expander.py` — Query Expander (Retrieval Enhancement)

**Purpose:**

The `GraphQueryExpander` is the single choke point for all graph-based query expansion. The retrieval enhancement modifies `expand()` to conditionally dispatch typed traversal, evaluate path patterns, format graph context, and return an `ExpansionResult` instead of a bare `List[str]`.

**How it works:**

1. **Constructor** accepts an optional `config: KGConfig`. When `enable_graph_context_injection` is True, creates `PathMatcher` and `GraphContextFormatter` instances.

2. **`expand(query, depth=None)`** flow:
   - Entity matching: spaCy + LLM fallback (existing)
   - `connects_to` depth bump to 2 (existing, REQ-KG-756)
   - **Typed dispatch** (new): If `config.enable_graph_context_injection` and `config.retrieval_edge_types` are set, calls `query_neighbors_typed(entity, edge_types, depth)`. Otherwise calls `query_neighbors(entity, depth)`. On typed failure, falls back to untyped with WARNING log.
   - **Path pattern evaluation** (new): If `retrieval_path_patterns` is configured, evaluates each pattern against each seed entity via `PathMatcher.evaluate()`. On failure, empty paths with WARNING log.
   - **Context formatting** (new): Collects Entity objects and triples for seed + expanded entities, calls `GraphContextFormatter.format()`. On failure, empty string with WARNING log.
   - Returns `ExpansionResult(terms=all_terms, graph_context=graph_context)`

3. **Graceful degradation** (REQ-KG-1214): Three independent try/except blocks:
   - Typed traversal → untyped fallback
   - Path evaluation → empty paths
   - Context formatting → empty string
   Each catches `Exception` (not bare `except:`), uses `exc_info=True` in WARNING logs.

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Config gated via `enable_graph_context_injection` | Always-on typed traversal | Opt-in rollout; zero overhead when disabled; instant rollback |
| Three independent try/except blocks | Single outer try/except | Typed traversal failure doesn't prevent context formatting from prior data |
| Fan-out limits shared between typed and untyped | Separate limits | Same `max_terms` truncation code runs after both paths (line 231) |

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `enable_graph_context_injection` | `bool` | `False` | Master toggle for all retrieval enhancements |
| `retrieval_edge_types` | `List[str]` | `[]` | Edge types for typed traversal. Empty = untyped fallback. |
| `retrieval_path_patterns` | `List[List[str]]` | `[]` | Path patterns for multi-hop evaluation. Empty = skip. |
| `graph_context_token_budget` | `int` | `500` | Token budget passed to GraphContextFormatter |

**Error behavior:**

- Any exception in typed traversal, path evaluation, or formatting is caught and logged at WARNING. The request always completes.
- The outer `except Exception` around the entire method returns `ExpansionResult(terms=[], graph_context="")` — the query proceeds with zero graph augmentation rather than failing.

---

### `src/knowledge_graph/backend.py` + Backends — Typed Traversal

**Purpose:**

The `GraphStorageBackend` ABC gained `query_neighbors_typed(entity, edge_types, depth)` as a new abstract method. Both `NetworkXBackend` and `Neo4jBackend` implement it.

**How it works:**

- **NetworkXBackend:** BFS using `get_outgoing_edges()`/`get_incoming_edges()`, filtering by `triple.predicate in edge_types_set`. Deduplicates via visited set. Returns empty list for non-existent entities or edge types.
- **Neo4jBackend:** Two Cypher queries (outgoing + incoming) with `[r*1..{depth}]` variable-length paths and `WHERE ALL(rel IN r WHERE rel.relation IN $edge_types)` filter. Results deduplicated via seen set, converted with `_to_entity`.

**Error behavior:**

- `ValueError` — raised when `edge_types` is empty or `depth < 1`. Callers should validate before calling.
- Non-existent entity → empty list (no exception).
- Non-existent edge types → empty list (no exception).

---

## 4. End-to-End Data Flow

### Scenario 1: Typed traversal with path patterns (happy path)

**Input:**

```python
query = "How was timing violation in clock domain fixed?"
# Config: enable_graph_context_injection=True
#         retrieval_edge_types=["design_decision_for", "specified_by"]
#         retrieval_path_patterns=[["design_decision_for", "specified_by"]]
```

**Stage 1: Entity Matching** (`expander.py:142-148`)
- spaCy matches `"clock domain"` → seed entity `ClockDomain_Core`

**Stage 2: Typed Dispatch** (`expander.py:174-197`)
- `retrieval_edge_types` is non-empty → calls `query_neighbors_typed("ClockDomain_Core", ["design_decision_for", "specified_by"], depth=1)`
- Returns: `[DesignDecision_ClkGating, Specification_UART_Timing]`

**Stage 3: Path Pattern Evaluation** (`expander.py:245-257`)
- Pattern `["design_decision_for", "specified_by"]` evaluated against seed `ClockDomain_Core`
- Hop 1: `ClockDomain_Core --design_decision_for--> DesignDecision_ClkGating`
- Hop 2: `DesignDecision_ClkGating --specified_by--> Specification_UART_Timing`
- Result: `PathResult(seed="ClockDomain_Core", terminal="Specification_UART_Timing", hops=[...])`

**Stage 4: Context Formatting** (`expander.py:260-284`)
- Formats entity summaries, triples, and path narrative
- Output: `"## Graph Context\n### Entities\n- **ClockDomain_Core** [ClockDomain]: ...\n### Paths\nClockDomain_Core design decision for DesignDecision_ClkGating, which specified by Specification_UART_Timing"`

**Stage 5: Pipeline Threading** (`rag_chain.py:648-654`)
- `expansion_result.terms` → BM25 augmentation
- `expansion_result.graph_context` → forwarded to generation

**Stage 6: Prompt Injection** (`generator.py:156`)
- Graph context section prepended before document chunks in LLM prompt
- LLM sees relationship structure alongside retrieved passages

**Final output:** `ExpansionResult(terms=["DesignDecision_ClkGating", "Specification_UART_Timing"], graph_context="## Graph Context\n...")`

---

### Scenario 2: Typed traversal failure with graceful degradation

**Input:**

```python
query = "What connects to AXI bus?"
# Config: enable_graph_context_injection=True
#         retrieval_edge_types=["connects_to"]
# Backend: Neo4j backend with connection timeout
```

**Stage 1: Entity Matching** — matches `AXI_Bus`

**Stage 2: Typed Dispatch** — calls `query_neighbors_typed("AXI_Bus", ["connects_to"], depth=1)`
- Backend raises `ConnectionError: Neo4j timeout`
- **Degradation:** try/except catches, logs WARNING with traceback, falls back to `query_neighbors("AXI_Bus", depth=2)` (untyped)
- Returns untyped neighbors (all edge types)

**Stage 3: Path Pattern Evaluation** — proceeds normally with empty path results (patterns may also fail but independently)

**Stage 4: Context Formatting** — formats available entities/triples (no path narratives)

**Result:** Query completes with less-targeted expansion terms and no path narratives, but does not fail. WARNING log captures the Neo4j timeout for operator investigation.

---

### Scenario 3: Feature disabled (zero overhead)

**Input:**

```python
query = "What is the clock domain?"
# Config: enable_graph_context_injection=False (default)
```

**Flow:** `expand()` takes the existing untyped path. No `PathMatcher` or `GraphContextFormatter` are instantiated. Returns `ExpansionResult(terms=[...], graph_context="")`. In `rag_chain.py`, `graph_context` is `""`. In `generator.py`, `_render_graph_context_section("")` returns `""` — no graph context section in the prompt. Structurally identical to pre-enhancement behavior.

---

### Branching Points Summary

| Condition | Path Taken | Where Decided |
|-----------|-----------|---------------|
| `enable_graph_context_injection=False` | Untyped BFS, no context | `expander.py:174-178` |
| `retrieval_edge_types` empty | Untyped fallback | `expander.py:178` |
| Typed traversal exception | Fall back to untyped + WARNING | `expander.py:189-194` |
| Path evaluation exception | Empty paths + WARNING | `expander.py:252-257` |
| Formatting exception | Empty graph_context + WARNING | `expander.py:279-284` |
| `graph_context` empty | Section omitted from prompt | `generator.py:156` |
| Token budget exceeded | Priority-based truncation | `context_formatter.py:280-386` |

---

## 5. Configuration Reference

### KGConfig Retrieval Parameters

| Parameter | Env Var | Type | Default | Valid Range | Effect |
|-----------|---------|------|---------|-------------|--------|
| `enable_graph_context_injection` | `RAG_KG_ENABLE_GRAPH_CONTEXT_INJECTION` | `bool` | `False` | `true`/`false` | Master toggle. When False, all retrieval enhancements are skipped. |
| `retrieval_edge_types` | `RAG_KG_RETRIEVAL_EDGE_TYPES` | `List[str]` | `[]` | Comma-separated edge type names from `kg_schema.yaml` | Edge types for typed traversal. Empty = untyped fallback. |
| `retrieval_path_patterns` | `RAG_KG_RETRIEVAL_PATH_PATTERNS` | `List[List[str]]` | `[]` | JSON array of arrays | Path patterns for multi-hop traversal. Empty = skip path matching. |
| `graph_context_token_budget` | `RAG_KG_GRAPH_CONTEXT_TOKEN_BUDGET` | `int` | `500` | `>= 0` (0 = unlimited) | Max tokens for graph context block. |
| `strict_path_validation` | N/A (code-only) | `bool` | `False` | `true`/`false` | When True, type-incompatibility warnings become startup errors. |

### GraphContextFormatter Parameters (constructor)

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `token_budget` | `int` | `500` | From `KGConfig.graph_context_token_budget` |
| `marker_style` | `str` | `"markdown"` | Section markers: `"markdown"`, `"xml"`, or `"plain"` |
| `description_fallback_k` | `int` | `3` | Number of raw_mentions used when current_summary is absent |
| `max_path_hops` | `int` | `5` | Paths longer than this are truncated with ellipsis |

### PathMatcher Constants

| Constant | Value | Effect |
|----------|-------|--------|
| `_MAX_HOP_FANOUT` | `50` | Maximum frontier entries per hop step in path matching |

---

## 6. Integration Contracts

### What callers provide

The retrieval pipeline calls `GraphQueryExpander.expand()`:

```python
expansion_result = expander.expand(query: str, depth: Optional[int] = None)
# Returns: ExpansionResult
```

The expander is constructed by `get_query_expander()` in `src/knowledge_graph/__init__.py`, which passes `config=config` with all retrieval fields populated from environment variables.

### What callers receive

```python
ExpansionResult:
    terms: List[str]       # always present; may be empty
    graph_context: str     # always present; "" when disabled/empty/error
```

`ExpansionResult` is iterable — existing callers that treated the return as `List[str]` continue to work.

### External dependency contracts

| Dependency | Role | Assumption |
|-----------|------|------------|
| `kg_schema.yaml` | Edge type vocabulary | Must exist at the configured path for validation to run |
| Graph backend (NetworkX or Neo4j) | Typed neighbor queries | `query_neighbors_typed` available on the backend instance |
| LLM prompt template | Graph context injection point | `generator.py` accepts `graph_context` parameter |

---

## 7. Operational Notes

### Enabling the feature

```bash
# Minimum viable config for typed traversal
export RAG_KG_ENABLE_GRAPH_CONTEXT_INJECTION=true
export RAG_KG_RETRIEVAL_EDGE_TYPES=depends_on,specified_by,design_decision_for

# Optional: add path patterns for multi-hop reasoning
export RAG_KG_RETRIEVAL_PATH_PATTERNS='[["design_decision_for","specified_by"],["connects_to","connects_to"]]'

# Optional: adjust token budget
export RAG_KG_GRAPH_CONTEXT_TOKEN_BUDGET=300
```

### Monitoring Signals

| Log Event | Level | What It Means | Action |
|-----------|-------|--------------|--------|
| `"typed dispatch: edge_types=..."` | DEBUG | Typed traversal selected | Normal when feature is enabled |
| `"untyped dispatch"` | DEBUG | Untyped fallback active | Normal when feature is disabled |
| `"Typed traversal failed, falling back to untyped"` | WARNING | Backend error in typed path | Check backend connectivity; graph errors degrade gracefully |
| `"Path pattern evaluation failed"` | WARNING | Path matcher error | Check schema validity; may indicate graph data issues |
| `"Graph context formatting failed"` | WARNING | Formatter error | Check entity/triple data integrity |
| `"Fan-out guard: truncating frontier from N to 50"` | DEBUG | Path matching hit density cap | Consider more specific edge types in patterns |
| `"Context truncated: ..."` | INFO (in output) | Token budget exceeded | Increase budget or narrow edge types to reduce context size |

### Common Failure Modes

| Symptom | Root Cause | Debug Path |
|---------|-----------|-----------|
| Startup fails with `KGConfigValidationError` | Edge type in config not in `kg_schema.yaml` | Read the error message — it lists the unknown type and valid options |
| Graph context always empty despite feature being enabled | No seed entities matched in query | Check entity matcher logs; verify graph is populated |
| Typed traversal always falls back to untyped | Backend doesn't support the configured edge types | Verify edge types exist in the actual graph data, not just the schema |
| Token budget truncation removing all content | Budget too low for graph density | Increase `RAG_KG_GRAPH_CONTEXT_TOKEN_BUDGET` or use more specific edge types |

---

## 8. Known Limitations

| Limitation | Impact | Workaround / Future Path |
|-----------|--------|--------------------------|
| Token budget uses `chars/4` approximation | ±20-30% variance from actual token count | Open question in spec (Appendix C.3) — inject real tokenizer if precision needed |
| No verb normalization table | Path narratives use raw predicate labels with underscores replaced by spaces (e.g., "design decision for" not "is the design decision for") | Open question in spec (Appendix C.1) — add predicate-to-verb mapping in schema |
| Path patterns evaluated per-seed-entity sequentially | Latency scales linearly with seed count × pattern count | Acceptable for typical ASIC queries (1-3 seeds, 1-5 patterns) |
| `_MAX_HOP_FANOUT` is a module constant, not configurable | Cannot be tuned without code change | Promote to KGConfig if production use cases need different caps |
| No named pattern references | Patterns must be specified inline as edge type lists | Open question in spec (Appendix C.2) — add named references in schema |
| `marker_style` not configurable via env var | Hardcoded to "markdown" in current wiring | Add `RAG_KG_GRAPH_CONTEXT_MARKER_STYLE` env var if needed |

---

## 9. Extension Guide

### Adding a new edge type for typed traversal

1. **Add the edge type to `config/kg_schema.yaml`** — define name, source_types, target_types
2. **Include it in the env var** — append to `RAG_KG_RETRIEVAL_EDGE_TYPES` (comma-separated)
3. **Restart the application** — validation runs at startup; the new type is immediately recognized

No code changes required.

### Adding a new path pattern

1. **Define the pattern** — an ordered list of edge types, e.g., `["depends_on", "constrained_by"]`
2. **Add to env var** — append to the JSON array in `RAG_KG_RETRIEVAL_PATH_PATTERNS`
3. **Verify at startup** — check logs for validation warnings about type compatibility

No code changes required.

### Adding a new marker style

1. **Add a new branch** in `GraphContextFormatter._get_section_markers()` in `src/knowledge_graph/query/context_formatter.py`
2. **Define the markers dict** — keys: `header`, `entities_open`, `entities_close`, `triples_open`, `triples_close`, `paths_open`, `paths_close`, `footer`
3. **Update the `ValueError`** message to include the new style name

**Pitfall:** The `_assemble()` method uses the dict keys, not the style name — no changes needed there.

### Adding a new graph backend

1. **Implement `query_neighbors_typed`** in the new backend class (extends `GraphStorageBackend`)
2. **Follow the contract:** validate inputs (`ValueError` on empty `edge_types` or `depth < 1`), deduplicate results, return empty list for non-existent entities
3. **Register** the backend in `get_graph_backend()` in `src/knowledge_graph/__init__.py`

**Pitfall:** If the new backend doesn't natively support edge-type-filtered traversal, implement a filter-after-fetch pattern: call the unfiltered query, then filter results by predicate.

---

## Appendix: Requirement Coverage

| Spec Requirement | Covered By |
|------------------|------------|
| REQ-KG-760 | `backend.py` + `networkx_backend.py` + `neo4j_backend.py` — `query_neighbors_typed` |
| REQ-KG-762 | `expander.py` — typed dispatch conditional |
| REQ-KG-764 | `validation.py` — `validate_edge_types()` |
| REQ-KG-766 | `expander.py` — untyped fallback when edge_types empty |
| REQ-KG-768 | `expander.py` — shared fan-out limits |
| REQ-KG-770 | `path_matcher.py` — pattern definition + `query/schemas.py` PathResult |
| REQ-KG-772 | `path_matcher.py` — step-by-step frontier BFS |
| REQ-KG-774 | `path_matcher.py` — multiple patterns merged |
| REQ-KG-776 | `path_matcher.py` + `query/schemas.py` — full hop chains |
| REQ-KG-778 | `validation.py` — `validate_path_patterns()` with strict mode |
| REQ-KG-780 | `context_formatter.py` — three-section output |
| REQ-KG-782 | `context_formatter.py` — entity description fallback chain |
| REQ-KG-784 | `context_formatter.py` — path narrative generation |
| REQ-KG-786 | `context_formatter.py` — token budget truncation |
| REQ-KG-788 | `context_formatter.py` — configurable marker styles |
| REQ-KG-790 | `query/schemas.py` — `ExpansionResult` dataclass |
| REQ-KG-792 | `rag_chain.py` — pipeline threading of `graph_context` |
| REQ-KG-794 | `generator.py` — prompt slot before document chunks |
| REQ-KG-796 | `generator.py` — clean omission when empty |
| REQ-KG-1200 | `common/types.py` — `KGConfig.retrieval_edge_types` |
| REQ-KG-1202 | `common/types.py` — `KGConfig.retrieval_path_patterns` |
| REQ-KG-1204 | `common/types.py` — `KGConfig.graph_context_token_budget` |
| REQ-KG-1206 | `common/types.py` — `KGConfig.enable_graph_context_injection` |
| REQ-KG-1208 | `validation.py` — startup validation wired in `__init__.py` |
| REQ-KG-1210 | `tests/benchmarks/kg_retrieval_bench.py` — traversal benchmark |
| REQ-KG-1212 | `tests/benchmarks/kg_retrieval_bench.py` — formatting benchmark |
| REQ-KG-1214 | `expander.py` — graceful degradation wrappers |
| REQ-KG-1216 | `config/settings.py` + `__init__.py` — env var loading |

**Coverage: 28/28 requirements implemented.**
