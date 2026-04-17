# Knowledge Graph Retrieval — Test Docs

> **For write-module-tests agents:** This document is your source of truth.
> Read ONLY your assigned module section. Do not read source files, implementation code,
> or other modules' test specs.

**Engineering guide:** `docs/knowledge_graph/KNOWLEDGE_GRAPH_RETRIEVAL_ENGINEERING_GUIDE.md`
**Phase 0 contracts:** `docs/knowledge_graph/KNOWLEDGE_GRAPH_RETRIEVAL_IMPLEMENTATION_DOCS.md` (Phase 0 section)
**Spec:** `docs/knowledge_graph/KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md`
**Produced by:** write-test-docs

---

## Mock/Stub Interface Specifications

### Mock: Graph Backend (`GraphStorageBackend`)

**What it replaces:** The graph storage backend (NetworkX or Neo4j)

**Interface to mock:**

```python
class MockBackend(GraphStorageBackend):
    def query_neighbors_typed(
        self, entity: str, edge_types: List[str], depth: int = 1
    ) -> List[Entity]:
        ...

    def query_neighbors(self, entity: str, depth: int = 1) -> List[Entity]:
        ...

    def get_outgoing_edges(self, entity: str) -> List[Triple]:
        ...

    def get_entity(self, name: str) -> Optional[Entity]:
        ...

    def get_all_node_names_and_aliases(self) -> Dict[str, str]:
        ...
```

**Happy path return (typed):**

```python
# query_neighbors_typed("TimingViolation_001", ["fixed_by"], depth=1)
[Entity(name="ClockGating_Approach", type="DesignDecision")]
```

**Happy path return (untyped):**

```python
# query_neighbors("TimingViolation_001", depth=1)
[Entity(name="ClockGating_Approach", type="DesignDecision"),
 Entity(name="SomeOther", type="Concept")]
```

**Error path return:**

```python
raise RuntimeError("Backend connection timeout")
```

**Used by modules:** `query/expander.py`, `query/path_matcher.py`

---

### Mock: Schema File (`kg_schema.yaml`)

**What it replaces:** The YAML schema file on disk

**Interface to mock:** Provide a temporary file with known edge types and constraints.

**Happy path fixture:**

```yaml
edge_types:
  structural:
    depends_on:
      source_types: [RTL_Module]
      target_types: [RTL_Module]
    connects_to:
      source_types: [Port, Signal]
      target_types: [Port, Signal]
  semantic:
    specified_by:
      source_types: [DesignDecision]
      target_types: [Specification]
    design_decision_for:
      source_types: [DesignDecision]
      target_types: [KnownIssue, RTL_Module]
```

**Used by modules:** `common/validation.py`

---

## Per-Module Test Specifications

---

### `src/knowledge_graph/query/schemas.py` — Retrieval Type Definitions

**Module purpose:** Defines `ExpansionResult`, `PathHop`, and `PathResult` — the shared data contracts for KG retrieval.

**In scope:**
- `ExpansionResult` backward-compatibility (iteration protocol)
- `PathResult.length` property
- Default values

**Out of scope:**
- How these types are used by other modules

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| ExpansionResult iteration | `ExpansionResult(terms=["a", "b"])` | `list(result) == ["a", "b"]` |
| ExpansionResult len | `ExpansionResult(terms=["a", "b"])` | `len(result) == 2` |
| ExpansionResult getitem | `ExpansionResult(terms=["a", "b"])` | `result[0] == "a"`, `result[1] == "b"` |
| ExpansionResult default context | `ExpansionResult(terms=[])` | `result.graph_context == ""` |
| PathResult length | `PathResult(hops=[PathHop(...), PathHop(...)], ...)` | `result.length == 2` |
| PathResult empty hops | `PathResult(hops=[], ...)` | `result.length == 0` |

#### Error scenarios

No exceptions defined — these are pure data containers.

#### Boundary conditions

- `ExpansionResult(terms=[])` — empty terms, iteration yields nothing
- `ExpansionResult(terms=["x"])` — single term
- Slice access: `result.terms[:2]` works as expected

#### Integration points

- Consumed by `expander.py` as return type
- Consumed by `context_formatter.py` for `PathResult`/`PathHop`
- Consumed by `rag_chain.py` (destructures `.terms` and `.graph_context`)

#### Known test gaps

None — pure dataclasses are fully testable.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### `src/knowledge_graph/common/validation.py` — Schema Validation

**Module purpose:** Validates `retrieval_edge_types` and `retrieval_path_patterns` against `kg_schema.yaml`, catching config errors at startup.

**In scope:**
- Edge type validation against schema vocabulary
- Path pattern validation (unknown types + hop compatibility)
- Error accumulation (all errors in one raise)
- Strict mode (warnings promoted to errors)

**Out of scope:**
- Schema file format/parsing (mock the file)
- KGConfig construction (tested in KGConfig module)

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Valid edge types | `validate_edge_types(["depends_on", "specified_by"], schema_path)` | Returns `None` (no error) |
| Valid path pattern | `validate_path_patterns([["depends_on"]], schema_path)` | Returns `[]` (no warnings) |
| Compatible consecutive hops | `validate_path_patterns([["design_decision_for", "specified_by"]], schema_path)` | Returns `[]` (types are compatible) |
| Multiple valid patterns | `validate_path_patterns([["depends_on"], ["connects_to", "connects_to"]], schema_path)` | Returns `[]` |
| Length-1 pattern | `validate_path_patterns([["depends_on"]], schema_path)` | Returns `[]` (no consecutive hops to check) |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `KGConfigValidationError` | Unknown edge type in `retrieval_edge_types` | `.errors` list contains the unknown type name; message includes valid options |
| `KGConfigValidationError` | Multiple unknown types | `.errors` list contains ALL unknown types (accumulated, not first-only) |
| `KGConfigValidationError` | Unknown edge type in path pattern | Error names the specific pattern index and hop index |
| `KGConfigValidationError` | Strict mode + incompatible hops | Raised with warning messages when `strict=True` |
| `FileNotFoundError` | Non-existent schema path | Raised with path in message |

#### Boundary conditions

- Empty `edge_types` list `[]` → no validation needed, no error (REQ-KG-764 AC 3)
- Empty `patterns` list `[]` → no validation needed, no error
- Pattern with single element `[["depends_on"]]` → no hop compatibility check needed
- All edge types invalid → error accumulates all of them
- Mix of valid and invalid types → only invalid ones in error list

#### Integration points

- Called by `__init__.py` `_build_kg_config()` at startup when `enable_graph_context_injection` is True
- Called by `PathMatcher.evaluate()` when `schema_path` is set
- Returns `PatternWarning` objects → callers log at WARNING level

#### Known test gaps

- Schema reload at runtime (REQ-KG-778 AC 4) — depends on config reload mechanism not yet tested

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### `src/knowledge_graph/query/path_matcher.py` — Path Pattern Engine

**Module purpose:** Evaluates ordered multi-hop path patterns against the KG via step-by-step typed traversal with per-path cycle guards.

**In scope:**
- Single-pattern evaluation (step-by-step BFS)
- Multi-pattern evaluation (merged, deduplicated)
- Cycle guard (per-path visited set)
- Fan-out guard (`_MAX_HOP_FANOUT = 50`)
- Pattern validation delegation (when schema_path set)

**Out of scope:**
- Backend traversal implementation (mocked)
- Schema validation logic (tested in validation module)

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Single hop pattern | seed=`"A"`, patterns=`[["edge_x"]]`, backend returns `[B]` for edge_x | 1 PathResult: seed=A, terminal=B, hops=[A→edge_x→B] |
| Two-hop pattern | seed=`"A"`, patterns=`[["edge_x", "edge_y"]]`, A→B via edge_x, B→C via edge_y | 1 PathResult: seed=A, terminal=C, hops=[A→edge_x→B, B→edge_y→C] |
| Multiple patterns merged | seed=`"A"`, patterns=`[["edge_x"], ["edge_y"]]` | Results from both patterns combined |
| Diamond graph (not a cycle) | A→B and A→C via edge_x; B→D and C→D via edge_y | 2 PathResults (A→B→D, A→C→D) — diamond allowed |
| Pattern with repeated edge type | patterns=`[["connects_to", "connects_to"]]` | Valid: follows connects_to twice |
| Deduplication | Same (seed, terminal, pattern_label) from multiple frontier branches | Single PathResult retained |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `ValueError` | Empty `patterns` list `[]` | Raises `ValueError("patterns must be non-empty")` |
| `ValueError` | Any pattern is empty `[[], ["edge_x"]]` | Raises `ValueError("Each pattern must be a non-empty list")` |
| Backend exception per-branch | `query_neighbors_typed` raises for one entity | WARNING logged, that branch skipped, other branches continue |
| `KGConfigValidationError` | Unknown edge type when `schema_path` set | Raised from validation module |

#### Boundary conditions

- Zero results at any hop → empty result list (no fallback to BFS per REQ-KG-772 AC 3)
- Single seed, single pattern, single result → 1 PathResult
- Cycle in graph (A→B→A) → cycle guard prevents revisit, returns `[]` for that branch
- Fan-out > 50 at one hop → truncated to 50, DEBUG log emitted
- Non-existent seed entity (backend returns `[]`) → empty results

#### Integration points

- Calls `backend.query_neighbors_typed(entity, [edge_type], depth=1)` per frontier entry per hop
- When `schema_path` set: calls `validate_path_patterns()` at evaluate() entry
- Called by `expander.py` during `expand()` when patterns configured

#### Known test gaps

- Fan-out guard threshold (50) is a module constant — testing exact threshold requires constructing a graph with >50 neighbors for a single edge type

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### `src/knowledge_graph/query/context_formatter.py` — Graph Context Formatter

**Module purpose:** Transforms traversal results into a structured text block (Entity Summaries, Relationship Triples, Path Narratives) with token budget enforcement and configurable section markers.

**In scope:**
- Three-section output assembly
- Entity description fallback chain (current_summary → raw_mentions → placeholder)
- Triple grouping by predicate
- Path narrative generation with verb normalization
- Token budget with priority-based truncation
- Three marker styles (markdown, xml, plain)
- Empty section omission

**Out of scope:**
- Entity/Triple/PathResult construction (use fixtures)
- Token budget accuracy (approximate by design)

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| All three sections populated | entities + triples + paths | Output contains "Entities", "Relationships", "Paths" sections |
| Entity with current_summary | Entity with `current_summary="desc"` | Summary text appears, not raw_mentions |
| Entity with raw_mentions only | Entity with `current_summary=None`, `raw_mentions=[m1,m2,m3]` | Top 3 mention texts joined by space |
| Entity with neither | Entity with no summary, no mentions | `"[No description available]"` |
| Entity with aliases | Entity with `aliases=["alias1"]` | `"(also: alias1)"` appended |
| Triples grouped by predicate | 3 triples: 2 depends_on + 1 connects_to | Two groups with bold predicate headings |
| Path narrative 1-hop | PathResult with 1 hop: A→edge_x→B | `"A edge x B"` (underscores→spaces) |
| Path narrative 2-hop | PathResult with 2 hops | `"A edge x B, which edge y C"` |
| Markdown markers | `marker_style="markdown"` | `"## Graph Context"`, `"### Entities"` etc. |
| XML markers | `marker_style="xml"` | `"<graph_context>"`, `"<entities>"` etc. |
| Plain markers | `marker_style="plain"` | `"=== GRAPH CONTEXT ==="`, `"--- ENTITIES ---"` etc. |
| All empty inputs | `format([], [], [])` | Returns `""` |
| Entities only | entities populated, triples=[], paths=[] | Only Entities section; Relationships and Paths omitted |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `ValueError` | Unknown `marker_style` (e.g., `"html"`) | Raises with message listing valid styles |

#### Boundary conditions

- Token budget = 0 → no truncation (unlimited)
- Token budget = 1 → aggressive truncation; seed name+type lines preserved
- Single entity, single triple, single path → minimal valid output
- Path exceeding `max_path_hops` (5) → truncated with `"[... N additional hops]"`
- Budget exceeded by entities alone → neighbour entities dropped first, then seed descriptions truncated (name+type stub preserved)
- `description_fallback_k=0` → no raw_mentions used, placeholder shown
- Truncation metadata annotation → `"[Context truncated: ...]"` line present in output

#### Integration points

- Receives `Entity` objects (from `src.knowledge_graph.common.schemas`), `Triple` objects, `PathResult` objects
- Called by `expander.py` via `self._formatter.format()`
- Output string is placed into `ExpansionResult.graph_context`

#### Known test gaps

- Token budget accuracy depends on `_CHARS_PER_TOKEN = 4` approximation — exact token count tests not meaningful

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### `src/knowledge_graph/query/expander.py` — Query Expander (Retrieval Enhancement)

**Module purpose:** The single choke point for graph-based query expansion. Dispatches typed or untyped traversal, evaluates path patterns, formats graph context, and returns `ExpansionResult`.

**In scope:**
- Typed dispatch conditional (config-gated)
- Untyped fallback when edge_types empty or feature disabled
- Graceful degradation (3 independent try/except blocks)
- `ExpansionResult` return with `graph_context`
- PathMatcher integration (path pattern evaluation)
- GraphContextFormatter integration (context formatting)

**Out of scope:**
- Entity matching logic (existing, not modified)
- Community-aware expansion (existing, not modified)
- Backend traversal implementation (mocked)
- PathMatcher internals (mocked)
- GraphContextFormatter internals (mocked)

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Feature disabled (default) | `config.enable_graph_context_injection=False` | `ExpansionResult(terms=[...], graph_context="")` — only untyped path |
| Typed dispatch | `enable_graph_context_injection=True`, `retrieval_edge_types=["depends_on"]` | `query_neighbors_typed` called, not `query_neighbors` |
| Untyped fallback | `enable_graph_context_injection=True`, `retrieval_edge_types=[]` | `query_neighbors` called (untyped) |
| Path patterns evaluated | `retrieval_path_patterns=[["depends_on", "specified_by"]]` | PathMatcher.evaluate called for each seed entity |
| Graph context populated | Feature enabled, formatter returns context | `result.graph_context != ""` |
| Backward compat | Feature disabled | `list(result)` yields same strings as pre-enhancement |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| Typed traversal exception | `query_neighbors_typed` raises `RuntimeError` | Falls back to `query_neighbors`, WARNING logged with exc_info |
| Path evaluation exception | `PathMatcher.evaluate` raises `Exception` | Empty paths, WARNING logged |
| Formatting exception | `GraphContextFormatter.format` raises `Exception` | Empty `graph_context=""`, WARNING logged |
| All three fail | Backend + matcher + formatter all raise | `ExpansionResult(terms=untyped_terms, graph_context="")` — degraded but complete |
| Complete failure | Entity matching itself fails | Outer try/except returns `ExpansionResult(terms=[], graph_context="")` |

#### Boundary conditions

- No seed entities matched → early return with `ExpansionResult(terms=[], graph_context="")`
- Single seed entity → one traversal call, one path evaluation
- `max_terms` truncation applies after both typed and untyped paths (REQ-KG-768)
- `graph_context` is always `str`, never `None`

#### Integration points

- Calls `backend.query_neighbors_typed()` or `backend.query_neighbors()` (mocked)
- Calls `PathMatcher.evaluate()` (mocked)
- Calls `GraphContextFormatter.format()` (mocked)
- Called by `rag_chain.py` which destructures `ExpansionResult`
- Constructor receives `config: KGConfig` for typed dispatch configuration

#### Known test gaps

- Entity matching and community expansion are pre-existing behaviors — test only the new retrieval enhancement branches
- `connects_to` depth-2 override (REQ-KG-756) is pre-existing — not retested here

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### `src/knowledge_graph/backends/networkx_backend.py` — NetworkX Typed Traversal

**Module purpose:** Implements `query_neighbors_typed` on the NetworkX backend — BFS with edge predicate filtering.

**In scope:**
- Typed traversal returning only edges matching `edge_types`
- Input validation (`ValueError` on empty edge_types or depth < 1)
- Deduplication of results
- Non-existent entity → empty list
- Non-existent edge types → empty list

**Out of scope:**
- Other NetworkXBackend methods (pre-existing)
- Graph loading/persistence

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Single matching edge type | Entity with `fixed_by` edge → `query_neighbors_typed(entity, ["fixed_by"], 1)` | Returns only target of `fixed_by` edge |
| Multiple matching edge types | `["fixed_by", "specified_by"]` | Returns targets of both edge types |
| Depth > 1 | depth=2 with chain A→B→C via matching edges | Returns both B and C |
| Non-existent edge type | `["nonexistent"]` | Returns `[]` (no exception) |
| Non-existent entity | `query_neighbors_typed("no_such_entity", ["depends_on"], 1)` | Returns `[]` |
| Deduplication | Multiple paths to same entity | Entity appears once in result |
| Incoming edges | Entity is target of a matching edge | Source entity included in results |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `ValueError` | `edge_types=[]` | Raises `ValueError` |
| `ValueError` | `depth=0` or `depth=-1` | Raises `ValueError` |

#### Boundary conditions

- Empty graph → `[]`
- Entity with no outgoing or incoming matching edges → `[]`
- depth=1 with matching edge at depth=2 → not returned (depth respected)

#### Integration points

- Called by `expander.py` via `backend.query_neighbors_typed()`
- Called by `PathMatcher._match_pattern()` via `backend.query_neighbors_typed(entity, [edge_type], depth=1)`
- Uses internal `get_outgoing_edges()`/`get_incoming_edges()` and `get_entity()`

#### Known test gaps

None — uses in-memory NetworkX graph, fully testable.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

## Integration Test Specifications

### Integration: Happy path — Typed traversal with path patterns

**Scenario:** A query triggers typed traversal, path pattern matching, context formatting, and prompt injection.

**Entry point:** `GraphQueryExpander.expand(query, depth=1)` with full config

**Setup:**
- NetworkXBackend with entities: `A(KnownIssue)`, `B(DesignDecision)`, `C(Specification)`
- Triples: A→design_decision_for→B, B→specified_by→C
- Config: `enable_graph_context_injection=True`, `retrieval_edge_types=["design_decision_for","specified_by"]`, `retrieval_path_patterns=[["design_decision_for","specified_by"]]`

**Flow:**
1. Entity matching finds seed entity `A`
2. Typed dispatch calls `query_neighbors_typed("A", ["design_decision_for","specified_by"], depth=1)` → returns B, C
3. PathMatcher evaluates pattern against seed A → finds path A→B→C
4. GraphContextFormatter formats entities + triples + path → produces context string
5. Returns `ExpansionResult(terms=["B","C"], graph_context="## Graph Context\n...")`

**What to assert:**
- `result.terms` contains expansion terms
- `result.graph_context` contains "Graph Context" section marker
- `result.graph_context` contains entity names
- `result.graph_context` contains path narrative text
- `result.graph_context` is non-empty string

**Mocks required:** None — uses real NetworkXBackend with fixture data. Mock EntityMatcher to return known seed entities.

---

### Integration: Error path — Typed traversal failure with degradation

**Scenario:** Typed traversal fails, system degrades to untyped expansion.

**Setup:** Same graph as happy path. Mock `query_neighbors_typed` to raise `RuntimeError`.

**Flow:**
1. Entity matching finds seed entity `A`
2. Typed dispatch calls `query_neighbors_typed` → raises `RuntimeError`
3. Degradation wrapper catches, logs WARNING, calls `query_neighbors("A", depth=1)` → returns B, C (all edges)
4. Returns `ExpansionResult(terms=[...], graph_context="")` or with context if formatting succeeds

**What to assert:**
- Request completes (no exception propagated)
- WARNING log contains "Typed traversal failed"
- `result.terms` is non-empty (untyped fallback worked)
- `result.graph_context` may be empty (depends on whether formatting also failed)

---

### Integration: Edge case — Feature disabled (zero overhead)

**Scenario:** `enable_graph_context_injection=False` — verify pre-enhancement behavior unchanged.

**Setup:** Any graph. Config with `enable_graph_context_injection=False`.

**Flow:**
1. Entity matching finds seed entities
2. Untyped `query_neighbors` called (typed never called)
3. No PathMatcher or GraphContextFormatter instantiated
4. Returns `ExpansionResult(terms=[...], graph_context="")`

**What to assert:**
- `query_neighbors_typed` never called
- `result.graph_context == ""`
- `list(result)` yields same strings as `result.terms`

---

## FR-to-Test Traceability Matrix

| REQ ID | AC Summary | Module Test | Integration Test |
|--------|-----------|-------------|-----------------|
| REQ-KG-760 | Backend ABC defines `query_neighbors_typed`; returns typed neighbors only | `networkx_backend` — happy path, error scenarios | integration_happy |
| REQ-KG-762 | Expander invokes `query_neighbors_typed` when config set | `expander` — typed dispatch | integration_happy |
| REQ-KG-764 | Edge types validated against schema at startup | `validation` — error scenarios (unknown types) | — |
| REQ-KG-766 | Empty `retrieval_edge_types` falls back to untyped | `expander` — untyped fallback | integration_disabled |
| REQ-KG-768 | Same fan-out limits on typed and untyped | `expander` — boundary (max_terms) | — |
| REQ-KG-770 | Path pattern = ordered edge type sequence | `path_matcher` — happy path (single/multi hop) | integration_happy |
| REQ-KG-772 | Step-by-step traversal with cycle guard | `path_matcher` — happy path, boundary (cycle) | — |
| REQ-KG-774 | Multiple patterns per query, merged | `path_matcher` — happy path (multi-pattern) | — |
| REQ-KG-776 | Full hop chains in PathResult | `path_matcher` — happy path, `schemas` — PathResult | integration_happy |
| REQ-KG-778 | Schema-validated patterns; warnings for incompatible hops | `validation` — happy path, error scenarios | — |
| REQ-KG-780 | Three-section structured output | `context_formatter` — happy path (all sections) | integration_happy |
| REQ-KG-782 | Entity description fallback chain | `context_formatter` — happy path (summary, mentions, placeholder) | — |
| REQ-KG-784 | Path narrative sentences | `context_formatter` — happy path (1-hop, 2-hop) | — |
| REQ-KG-786 | Token budget with priority truncation | `context_formatter` — boundary (budget scenarios) | — |
| REQ-KG-788 | Configurable section markers | `context_formatter` — happy path (markdown, xml, plain) | — |
| REQ-KG-790 | `ExpansionResult` with terms + graph_context | `schemas` — ExpansionResult iteration | integration_happy |
| REQ-KG-792 | Pipeline threads graph_context to generation | `expander` — happy path (context populated) | integration_happy |
| REQ-KG-794 | Prompt template slot before doc chunks | — | integration_happy (verified at prompt level) |
| REQ-KG-796 | Empty context → section omitted entirely | — | integration_disabled |
| REQ-KG-1200 | `KGConfig.retrieval_edge_types` field | `expander` — typed dispatch | — |
| REQ-KG-1202 | `KGConfig.retrieval_path_patterns` field | `expander` — path patterns evaluated | — |
| REQ-KG-1204 | `KGConfig.graph_context_token_budget` field | `context_formatter` — boundary (budget) | — |
| REQ-KG-1206 | `KGConfig.enable_graph_context_injection` toggle | `expander` — feature disabled/enabled | integration_disabled |
| REQ-KG-1208 | Config validation at startup | `validation` — error scenarios | — |
| REQ-KG-1210 | Typed traversal P95 delta <= 50ms | `benchmarks/kg_retrieval_bench.py` (existing) | — |
| REQ-KG-1212 | Formatting P95 <= 100ms | `benchmarks/kg_retrieval_bench.py` (existing) | — |
| REQ-KG-1214 | Graceful degradation | `expander` — error scenarios (3 fallbacks) | integration_error |
| REQ-KG-1216 | Env var loading with `RAG_KG_` prefix | `expander` — config wiring (unit) | — |

**Coverage: 28/28 requirements mapped.** REQ-KG-1210 and REQ-KG-1212 are covered by existing benchmark tests.
