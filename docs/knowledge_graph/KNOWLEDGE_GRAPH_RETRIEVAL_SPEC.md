# Knowledge Graph Retrieval — Specification

**RagWeave**
Version: 1.0.0 | Status: Draft | Domain: Knowledge Graph

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-04-13 | AI Assistant | Initial specification. Typed edge traversal, path pattern queries, graph-context formatting, prompt injection integration. Extends KNOWLEDGE_GRAPH_SPEC.md v1.1.0. |

---

## 1. Scope & Definitions

### 1.1 Problem Statement

The knowledge graph stores rich typed relationships (`instantiates`, `connects_to`, `fixed_by`, `specified_by`, etc.) extracted during ingestion. However, the retrieval pipeline currently treats the graph as an untyped neighbor store:

- `GraphQueryExpander.expand()` calls `query_neighbors(entity, depth=N)` which traverses ALL edge types indiscriminately — a query about "what fixes timing violation X" follows `authored_by` and `contains` edges with equal weight as `fixed_by` edges
- Expansion terms are string-appended to the BM25 query (`query + " " + " ".join(terms[:3])`) — the LLM generation prompt never sees graph-derived relationship context
- No mechanism exists to specify path patterns like `violation → fixed_by → approach` for domain-specific multi-hop reasoning
- `get_context_summary()` exists but produces flat "subject predicate object" text that is never injected into the LLM prompt

The result: the graph is populated with valuable ASIC domain knowledge (design decisions, fix policies, port connectivity, specification traceability) but retrieval ignores the relationship structure that makes this knowledge actionable.

### 1.2 Scope

This specification defines requirements for **graph-aware retrieval** in the Knowledge Graph subsystem. The boundary is:

- **Entry point:** A user query arrives at the retrieval pipeline's KG expansion stage (Stage 2 in rag_chain)
- **Exit point:** (a) Typed expansion terms augment the BM25 query, and (b) a structured graph-context block is injected into the LLM generation prompt

Everything between these two points is in scope.

**Relationship to parent spec:** This spec extends `KNOWLEDGE_GRAPH_SPEC.md` (v1.1.0). Requirements REQ-KG-600–609 in the parent define basic entity matching and untyped fan-out expansion. This spec supersedes none of those requirements — it adds typed traversal, path pattern matching, graph-context formatting, and prompt injection on top of the existing expansion mechanism.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **Typed traversal** | Graph traversal that follows only edges matching a specified set of predicate types, ignoring all others |
| **Path pattern** | An ordered sequence of edge types defining a multi-hop traversal template (e.g., `[fixed_by, specified_by]`) |
| **Graph context block** | A structured text representation of graph-derived relationships, formatted for injection into an LLM generation prompt |
| **Edge-type filter** | A set of predicate strings that restricts which edges are followed during graph traversal |
| **Prompt injection** | The act of inserting graph-derived context into the LLM prompt template alongside retrieved document chunks |
| **Local expansion** | Entity-neighbor expansion terms appended to the BM25 query (existing behavior, REQ-KG-608) |
| **Structural context** | Graph relationships derived from deterministic parsing (`instantiates`, `connects_to`, `contains`) |
| **Semantic context** | Graph relationships derived from LLM/NER extraction (`specified_by`, `fixed_by`, `authored_by`) |

### 1.4 Requirement Priority Levels

This document uses RFC 2119 language:

- **MUST** — Absolute requirement. The system is non-conformant without it.
- **SHOULD** — Recommended. May be omitted only with documented justification.
- **MAY** — Optional. Included at the implementor's discretion.

### 1.5 Requirement Format

Each requirement follows this structure:

> **REQ-KG-xxx** | Priority: MUST/SHOULD/MAY
> **Description:** What the system shall do.
> **Rationale:** Why this requirement exists.
> **Acceptance Criteria:** How to verify conformance.

Requirements are grouped by section with the following ID ranges:

| Section | ID Range | Component |
|---------|----------|-----------|
| 3 | REQ-KG-760–769 | Typed Edge Traversal & Filtering |
| 4 | REQ-KG-770–779 | Path Pattern Queries |
| 5 | REQ-KG-780–789 | Graph Context Formatting |
| 6 | REQ-KG-790–799 | Prompt Injection Integration |
| 7 | REQ-KG-1200–1209 | Configuration |
| 8 | REQ-KG-1210–1219 | Non-Functional Requirements |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | The graph backend already stores typed edges with predicate labels matching `kg_schema.yaml` | Edge-type filtering has nothing to filter on |
| A-2 | Entity matching (REQ-KG-600–602) correctly identifies seed entities in queries | Typed traversal requires seed entities to start from |
| A-3 | The LLM generation prompt template supports inserting additional context sections | Prompt injection requires a template slot |
| A-4 | Edge types in `kg_schema.yaml` are the single source of truth for valid predicates | Path patterns and filters reference these types |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **Typed-first, untyped-fallback** | When edge-type filters are configured, traversal follows only those types. When no filters are configured, existing untyped expansion (REQ-KG-605) applies unchanged — zero regression. |
| **Graph context is additive** | Graph-derived context supplements retrieved document chunks — it does not replace them. The LLM always receives both. |
| **Schema-validated paths** | Path patterns reference edge types defined in the YAML schema. Invalid edge types in a path pattern are rejected at config validation time, not silently ignored at query time. |
| **Bounded complexity** | Path pattern traversal respects the same fan-out limits (`max_terms`, `max_depth`) as untyped expansion. Typed traversal narrows the result set — it never increases it beyond configured limits. |

### 1.8 Out of Scope

**Out of scope — this spec:**

- Entity extraction and graph ingestion (see `KNOWLEDGE_GRAPH_SPEC.md` §6)
- Entity matching and query normalization (see `KNOWLEDGE_GRAPH_SPEC.md` §9.1)
- Community detection and global retrieval (see `KNOWLEDGE_GRAPH_SPEC.md` §10, REQ-KG-609)
- Graph storage backend internals (see `KNOWLEDGE_GRAPH_SPEC.md` §8)
- Graph visualization and export (see `KNOWLEDGE_GRAPH_SPEC.md` §11)

**Out of scope — this project:**

- Natural-language-to-graph-query translation (e.g., "show me all modules connected to the AXI bus" → Cypher)
- Graph neural network embeddings for retrieval
- Real-time graph updates during a query session

---

## 2. System Overview

### 2.1 Architecture Diagram

```
User Query
    │
    ▼
┌──────────────────────────────────────────────┐
│ [1] ENTITY MATCHING (existing — REQ-KG-600)  │
│     spaCy token-boundary + LLM fallback      │
│     Produces: seed_entities[]                 │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ [2] TYPED EDGE TRAVERSAL    (REQ-KG-760–769) │
│     Filter edges by predicate type            │
│     Follow only configured edge types         │
│     Produces: typed_neighbors[]               │
│                                               │
│     ┌─── path patterns configured? ──┐       │
│     │ YES                        NO  │       │
│     ▼                            ▼   │       │
│   PATH PATTERN          UNTYPED      │       │
│   MATCHING              FALLBACK     │       │
│   (REQ-KG-770–779)     (REQ-KG-605) │       │
│     │                        │       │       │
│     └────────┬───────────────┘       │       │
│              ▼                               │
│     expansion_terms[]                        │
└──────────────────┬───────────────────────────┘
                   │
                   ├──→ BM25 query augmentation (existing)
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ [3] GRAPH CONTEXT FORMATTING (REQ-KG-780–789)│
│     Build structured context block from       │
│     seed entities + traversal results         │
│     Format: relationship triples, entity      │
│     descriptions, path narratives             │
│     Produces: graph_context_block (text)      │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ [4] PROMPT INJECTION        (REQ-KG-790–799) │
│     Insert graph_context_block into LLM       │
│     generation prompt alongside retrieved     │
│     document chunks                           │
│     Produces: augmented_prompt                │
└──────────────────────────────────────────────┘
                   │
                   ▼
            LLM Generation
```

### 2.2 Data Flow Summary

| Stage | Input | Output |
|-------|-------|--------|
| Entity Matching | User query text | List of seed entity names matched in the graph |
| Typed Edge Traversal | Seed entities + edge-type filter config | Filtered neighbor entities + traversal paths |
| Path Pattern Matching | Seed entities + path pattern templates | Entities reachable via typed multi-hop paths |
| Graph Context Formatting | Seed entities + neighbors + paths + entity descriptions | Structured text block for LLM prompt |
| Prompt Injection | Graph context block + retrieved doc chunks + prompt template | Augmented LLM generation prompt |

---

## 3. Typed Edge Traversal & Filtering

The current graph expander performs untyped BFS, treating all edge types as equivalent during neighbor expansion. This section defines the requirements for adding edge-type-aware traversal to the backend ABC and the query expander, while preserving the existing untyped behavior as a zero-configuration fallback.

---

> **REQ-KG-760** | Priority: MUST
>
> **Description:** The `GraphStorageBackend` ABC MUST declare a new abstract method `query_neighbors_typed(entity: str, edge_types: List[str], depth: int = 1) -> List[Entity]` that returns only neighbors reachable via edges whose predicate is in `edge_types`, up to `depth` hops. Both forward (outgoing) and backward (incoming) edges are traversed, consistent with `query_neighbors`. Concrete backends that do not override this method MUST raise `NotImplementedError`.
>
> **Rationale:** The existing `query_neighbors` method has no mechanism to restrict traversal by predicate. Without a typed variant on the ABC, each backend implementation would need to filter after the fact, duplicating logic and losing the opportunity for backend-level query optimization (e.g., index-filtered Cypher traversals in Neo4j). Placing the contract on the ABC ensures all backends conform to the same typed-traversal interface.
>
> **Acceptance Criteria:**
> 1. `GraphStorageBackend` defines `query_neighbors_typed(entity: str, edge_types: List[str], depth: int = 1) -> List[Entity]` as an abstract method.
> 2. Calling `query_neighbors_typed("TimingViolation_001", ["fixed_by"], depth=1)` on a backend containing a `fixed_by` edge from `TimingViolation_001` to `ClockGating_Approach` returns `[ClockGating_Approach]` and does not return entities reachable only via other edge types.
> 3. Calling `query_neighbors_typed` with `edge_types=["nonexistent_predicate"]` returns an empty list without raising an exception.
> 4. A concrete backend subclass that does not implement `query_neighbors_typed` raises `NotImplementedError` when the method is invoked.

---

> **REQ-KG-762** | Priority: MUST
>
> **Description:** The graph expander MUST invoke `query_neighbors_typed(entity, edge_types, depth)` in place of `query_neighbors(entity, depth)` when the active retrieval configuration supplies a non-empty `retrieval_edge_types` list. The substitution MUST be transparent to callers — the return shape, fan-out limits, and deduplication behavior remain identical.
>
> **Rationale:** The expander is the single choke point through which all graph traversal passes. Placing the typed/untyped dispatch here avoids scattering conditional logic across call sites and ensures that future query strategies inherit the filtering behavior without additional changes.
>
> **Acceptance Criteria:**
> 1. Given a config with `retrieval_edge_types: ["depends_on", "constrained_by"]`, a query anchored on entity `ClockDomain_Core` expands only along `depends_on` and `constrained_by` edges; entities reachable exclusively via `contains` or `relates_to` edges are absent from the result set.
> 2. The expander passes the full `retrieval_edge_types` list from config directly to `query_neighbors_typed` without mutation.
> 3. The expander does not call `query_neighbors` and `query_neighbors_typed` simultaneously for the same traversal step; exactly one path is taken based on whether `retrieval_edge_types` is populated.
> 4. Logging at DEBUG level records which traversal mode (typed or untyped) was selected and which edge types were applied.

---

> **REQ-KG-764** | Priority: MUST
>
> **Description:** At application startup and on any configuration reload, each predicate in `retrieval_edge_types` MUST be validated against the canonical edge type list defined in `kg_schema.yaml`. Any unrecognized predicate MUST cause a `ConfigurationError` to be raised with a message that names the offending predicate(s) and lists the valid options. Validation MUST occur before any graph query is executed.
>
> **Rationale:** The YAML schema is the single source of truth for predicate vocabulary. Allowing an unrecognized predicate to silently pass through would produce empty result sets with no diagnostic signal — a particularly opaque failure mode. Fail-fast validation surfaces misspellings (e.g., `"depend_on"` instead of `"depends_on"`) before they corrupt query results.
>
> **Acceptance Criteria:**
> 1. The validator reads the structural and semantic edge type lists from `kg_schema.yaml` and constructs a combined valid-predicate set.
> 2. A config containing `retrieval_edge_types: ["depends_on", "fixes"]` raises `ConfigurationError` naming `"fixes"` as unrecognized.
> 3. A config containing `retrieval_edge_types: ["depends_on", "specified_by"]` passes validation without error.
> 4. Validation runs before the backend is queried; no graph I/O occurs when validation fails.
> 5. Adding a new predicate to `kg_schema.yaml` and reloading config immediately makes that predicate accepted without code changes.

---

> **REQ-KG-766** | Priority: MUST
>
> **Description:** When `retrieval_edge_types` is absent, null, or an empty list in the retrieval configuration, the expander MUST fall back to the existing untyped `query_neighbors(entity, depth)` behavior defined in REQ-KG-605, with no change in semantics, performance characteristics, or result ordering.
>
> **Rationale:** Typed traversal is an opt-in refinement. Forcing all consumers to specify an explicit edge-type filter would be a breaking change for existing query paths that benefit from unrestricted BFS. The "typed-first, untyped-fallback" principle ensures backward compatibility and allows incremental adoption.
>
> **Acceptance Criteria:**
> 1. A config with `retrieval_edge_types` omitted routes all expander calls through `query_neighbors`, not `query_neighbors_typed`.
> 2. A config with `retrieval_edge_types: []` is treated identically to the omitted case.
> 3. No regression is introduced in existing expander unit tests; all tests that do not set `retrieval_edge_types` continue to pass without modification.
> 4. The expander does not instantiate or call any typed-traversal code path when operating in untyped-fallback mode.

---

> **REQ-KG-768** | Priority: MUST
>
> **Description:** Typed traversal via `query_neighbors_typed` MUST honor the same `max_terms` and `max_depth` limits that govern untyped expansion. The typed traversal MUST NOT bypass, relax, or independently re-configure these limits.
>
> **Rationale:** Fan-out limits exist to bound context window consumption and prevent runaway expansion in densely connected graphs. A typed traversal that bypasses these limits would silently produce oversized context payloads — particularly dangerous in ASIC design graphs where structural edge types like `contains` can yield hundreds of neighbors within two hops.
>
> **Acceptance Criteria:**
> 1. With `max_terms=5` and `retrieval_edge_types: ["depends_on"]`, a typed BFS that would otherwise yield 12 reachable entities returns exactly 5.
> 2. With `max_depth=1`, typed traversal does not follow edges beyond the immediate neighbors.
> 3. The same limit-enforcement code path is exercised by both typed and untyped traversal.
> 4. When typed traversal is truncated by `max_terms`, the expander emits a DEBUG-level log entry indicating how many candidates were discarded.

---

## 4. Path Pattern Queries

Single-hop typed traversal answers questions about direct relationships. However, many diagnostic and traceability questions require following a chain of semantically distinct edge types before reaching the answer. A question like "how was timing violation X fixed, and what specification governs the fix?" requires a two-hop path `KnownIssue --fixed_by--> DesignDecision --specified_by--> Specification`. This section defines a path pattern mechanism that lets the retrieval layer express multi-hop traversal templates as first-class query constructs.

---

> **REQ-KG-770** | Priority: MUST
>
> **Description:** The system MUST support a **path pattern** construct defined as an ordered, finite sequence of edge type labels that together describe a traversal template. A path pattern of length N specifies exactly N hops; each element in the sequence names one edge type to follow at that hop. A pattern MAY use the same edge type at multiple positions. The pattern MUST be expressible in configuration as a plain list of strings drawn from the canonical edge type vocabulary, with an optional human-readable `label` field.
>
> **Rationale:** Ad-hoc special cases such as the `connects_to` depth bump in REQ-KG-756 are evidence that the expander already needs path-aware logic. Encoding these as named, reusable templates rather than hard-coded conditions makes the traversal strategy auditable, testable, and extendable. An ordered sequence is necessary because `A --fixed_by--> B --specified_by--> C` differs from `A --specified_by--> B --fixed_by--> C`.
>
> **Acceptance Criteria:**
> 1. A path pattern is represented as an ordered list of one or more edge type strings, e.g., `["fixed_by", "specified_by"]` or `["connects_to", "connects_to"]`.
> 2. Patterns are loadable from configuration and are also expressible inline at query time.
> 3. A pattern of length 1 is valid and produces behavior equivalent to a single-hop typed edge filter.
> 4. The system rejects a pattern that is empty or null with a descriptive configuration error at load time.
> 5. Pattern definitions carry an optional `label` field used in logging and result metadata.

---

> **REQ-KG-772** | Priority: MUST
>
> **Description:** Given a set of seed entities and a path pattern, the retrieval layer MUST evaluate the pattern by performing a step-by-step traversal: at hop 1, follow only edges matching `pattern[0]` from each seed; at hop 2, follow only edges matching `pattern[1]` from the entities reached at hop 1; and so on until the pattern is exhausted. Entities and edges collected at every intermediate step MUST be retained. The traversal follows the graph's stored edge directions.
>
> **Rationale:** Faithful multi-hop answers require that each hop is constrained to the specific edge type prescribed at that position. Unrestricted BFS at any hop would reintroduce the noise problem that path patterns are designed to solve. Retaining intermediate entities is necessary for full path results (REQ-KG-776).
>
> **Acceptance Criteria:**
> 1. For `["fixed_by", "specified_by"]` applied to a `KnownIssue` seed, hop 1 yields only entities reachable via `fixed_by` edges; hop 2 yields only entities reachable from those via `specified_by` edges.
> 2. For `["connects_to", "connects_to"]` applied to a `Port` seed, the traversal finds `Port --connects_to--> Signal --connects_to--> Port`.
> 3. If no entities survive a given hop, traversal halts for that seed and produces an empty result set — it does not fall back to BFS.
> 4. A single seed entity MAY produce multiple result paths if multiple edges of the required type exist at any hop.
> 5. Traversal does not revisit a node already present in the current path (cycle guard).

---

> **REQ-KG-774** | Priority: MUST
>
> **Description:** A single retrieval query MUST support configuring multiple path patterns simultaneously. The system MUST attempt every configured pattern against every seed entity and merge all resulting paths into the query's result set. A failure (zero results) for one pattern MUST NOT suppress evaluation of other patterns.
>
> **Rationale:** A single user question often activates several distinct reasoning chains. For a timing violation entity, a useful response might require both the `fix_chain` pattern and a `blocks` pattern to identify impact. Merging at the retrieval layer keeps the caller's interface simple while maximizing context coverage.
>
> **Acceptance Criteria:**
> 1. Query configuration accepts a list of path pattern definitions.
> 2. Given patterns `["fixed_by", "specified_by"]` and `["blocks"]`, the expander evaluates both and returns the union of their result paths.
> 3. If pattern A yields results and pattern B yields no results for a given seed, the response includes pattern A's results — the overall query does not fail.
> 4. Duplicate nodes from multiple patterns are deduplicated in the merged entity set, but each path record retains its own pattern attribution.

---

> **REQ-KG-776** | Priority: MUST
>
> **Description:** Path pattern results MUST expose the full traversal chain for each matched path: the ordered sequence of `(entity, edge_type, entity)` tuples from seed to terminal node. The retrieval layer MUST NOT collapse multi-hop results to a flat list of terminal entities.
>
> **Rationale:** The intermediate nodes and the edge types connecting them are part of the answer, not merely stepping stones. A context formatter that receives only the terminal entity cannot explain why it is relevant — it needs the full chain to generate a coherent reasoning trace.
>
> **Acceptance Criteria:**
> 1. Each path result is a structured record containing: `pattern_label` (string), `seed_entity`, `hops` (ordered list of `{from_entity, edge_type, to_entity}` tuples), and `terminal_entity`.
> 2. For the 2-hop pattern `["fixed_by", "specified_by"]`, the `hops` list contains exactly two entries.
> 3. For the 1-hop pattern `["blocks"]`, the `hops` list contains exactly one entry.
> 4. The context formatter can reconstruct a human-readable chain using only the `hops` list and entity display names — no additional graph queries required.

---

> **REQ-KG-778** | Priority: MUST
>
> **Description:** Before a path pattern is used in traversal, the system MUST validate each pattern against `kg_schema.yaml`: every edge type label in the pattern MUST exist in the schema's edge type vocabulary. Where the schema defines source and target entity type constraints for an edge type, consecutive hops SHOULD be checked for type compatibility (the target types of hop N intersect the source types of hop N+1). A non-intersecting pair MUST emit a WARNING-level log entry but MUST NOT block startup unless a `strict_pattern_validation` config flag is set.
>
> **Rationale:** An unvalidated pattern containing a misspelled edge type silently produces zero results, which is indistinguishable from a valid pattern with no matches. Schema validation at load time catches configuration errors early. Type compatibility checks across hops catch logically incoherent patterns — for example, `["authored_by", "connects_to"]` is suspicious because `authored_by` targets `Person` entities and `connects_to` sources from `Port`/`Signal`.
>
> **Acceptance Criteria:**
> 1. A pattern containing an unrecognized edge type causes a startup error naming the offending pattern and edge type.
> 2. For consecutive hops with non-intersecting types, a WARNING log entry is emitted identifying the pattern, hop index, and type mismatch.
> 3. A valid pattern with type-compatible hops produces no warnings.
> 4. Validation re-runs when `kg_schema.yaml` is reloaded at runtime.

---

## 5. Graph Context Formatting

After typed traversal and path pattern matching, the raw graph data must be serialized into a structured text block for LLM consumption. The current `get_context_summary()` emits flat semicolon-separated triples, which discard entity descriptions and give the LLM no signal about which facts are most relevant. This section defines the structure, content rules, token budget, and section-marker conventions for the graph context block.

---

> **REQ-KG-780** | Priority: MUST
>
> **Description:** The graph context formatter MUST produce a structured text block organized into three named sections: (a) **Entity Summaries** — one entry per entity containing name, type, and description; (b) **Relationship Triples** — edges grouped by predicate type, each rendered as `<subject> --[<predicate>]--> <object>`; (c) **Path Narratives** — one narrative per matched path pattern result, present only when path pattern matching produced results. Sections with no content MUST be omitted rather than rendered empty.
>
> **Rationale:** Flat triple strings lose the distinction between what an entity is (its description) and what it does (its relationships). Grouping by section lets the LLM apply different reading strategies to each kind of evidence.
>
> **Acceptance Criteria:**
> 1. The formatter produces output containing all three sections when all three kinds of data are present.
> 2. Entity entries include name, type, and at least one description token.
> 3. Relationship triples are grouped under a label per distinct predicate type.
> 4. The path narratives section is absent when no path patterns were matched.

---

> **REQ-KG-782** | Priority: MUST
>
> **Description:** For each seed entity and each key neighbor in the context block, the formatter MUST include an entity description. `current_summary` (the LLM-generated summarization) is the preferred source. When `current_summary` is absent, the formatter MUST fall back to the top-K `raw_mentions` excerpts (default K=3, configurable). Entities with neither field MUST still appear with a placeholder indicating no description is available.
>
> **Rationale:** `current_summary` is the distilled, LLM-friendly form. The fallback to `raw_mentions` ensures newly ingested entities whose summarization has not yet run still contribute useful context rather than a blank entry.
>
> **Acceptance Criteria:**
> 1. When `current_summary` is non-empty, the entity entry contains exactly that string; `raw_mentions` are not appended.
> 2. When `current_summary` is absent and `raw_mentions` is non-empty, the entity entry contains the top-K mention excerpts.
> 3. When both fields are absent, the entity entry renders `"[No description available]"`.
> 4. The value of K is configurable and defaults to 3.

---

> **REQ-KG-784** | Priority: MUST
>
> **Description:** For each path returned by path pattern matching, the formatter MUST produce a human-readable narrative sentence that traverses the path in order. The narrative MUST follow the template: `"<entity_0> <predicate_label> <entity_1>, which <predicate_label> <entity_2>[, which ...]"`, where predicate labels are rendered in a readable form (underscores replaced with spaces). Example: `"TimingViolation_001 was fixed by ClockGating_Approach, which is specified by UART_Timing_Spec"`. Paths longer than a configurable maximum hop count (default: 5) MUST be truncated with an ellipsis.
>
> **Rationale:** Multi-hop reasoning chains are the primary value of path pattern matching. Presenting them as narrative sentences mirrors how an LLM would articulate the chain, reducing cognitive distance between retrieved evidence and generated text.
>
> **Acceptance Criteria:**
> 1. A two-hop path produces `"A <pred1> B, which <pred2> C"`.
> 2. A one-hop path produces `"A <pred> B"` without a dangling clause.
> 3. Predicate labels have underscores replaced with spaces; known verbs are mapped through a configurable normalization table.
> 4. A path exceeding the maximum hop count is truncated with `"[... N additional hops]"`.

---

> **REQ-KG-786** | Priority: MUST
>
> **Description:** The graph context block MUST respect a configurable token budget (default: 500 tokens). When the fully assembled context exceeds the budget, content MUST be truncated in priority order, trimming lowest priority first: (1) neighbor entity descriptions, (2) relationship triples (by ascending weight), (3) path narratives (by ascending match score), (4) seed entity descriptions. Seed entity name and type lines MUST NOT be dropped regardless of budget pressure. The formatter MUST emit a metadata annotation indicating truncation counts per tier.
>
> **Rationale:** Graph context competes with document chunk context for the LLM's context window. An unbounded graph context block can crowd out retrieved passages. The priority order reflects relative retrieval value: path narratives encode the highest-value multi-hop reasoning and should survive longest.
>
> **Acceptance Criteria:**
> 1. A context block exceeding 500 tokens is truncated to within budget.
> 2. Seed entity name and type lines are present even when all other content is truncated.
> 3. The truncation order follows the defined priority tiers.
> 4. The output includes a structured annotation reflecting actual truncation counts.
> 5. Setting the budget to 0 disables truncation (unlimited).

---

> **REQ-KG-788** | Priority: SHOULD
>
> **Description:** The graph context block SHOULD be formatted with explicit section markers so the LLM can distinguish graph-derived facts from document chunks. Default markers: `## Graph Context` with subsections `### Entities`, `### Relationships`, `### Paths`. The marker style MUST be configurable, supporting at minimum `markdown` (default), `xml`, and `plain` styles.
>
> **Rationale:** LLMs attend differently to structured versus unstructured context. Explicit section markers create predictable landmarks that prompt engineers can reference in system instructions. Configurability is required because different deployment surfaces impose conflicting formatting constraints.
>
> **Acceptance Criteria:**
> 1. Default output contains `## Graph Context` with `### Entities`, `### Relationships`, `### Paths` subsections.
> 2. Switching to `xml` produces `<graph_context>`, `<entities>`, etc.
> 3. Switching to `plain` produces `=== GRAPH CONTEXT ===`, `--- ENTITIES ---`, etc.
> 4. Entity names, predicate labels, and path narrative text appear identically across all three styles.

---

## 6. Prompt Injection Integration

The retrieval pipeline currently discards all graph-derived context after query expansion, limiting the LLM to document chunks alone. This section specifies the changes required to thread the graph context block through the pipeline and surface it in the generation prompt.

---

> **REQ-KG-790** | Priority: MUST
>
> **Description:** The query expander MUST return a structured result object containing both a list of expansion term strings and a pre-formatted graph context block (plain text), rather than a bare list of strings. The expansion terms list retains its existing semantics for BM25 augmentation. The graph context block is forwarded to the generation stage.
>
> **Rationale:** The current single-list return type has no channel for graph-derived prose context. Changing the return contract at the expander boundary is the minimal intervention — it avoids a separate graph-lookup call later in the pipeline.
>
> **Acceptance Criteria:**
> 1. `expand()` returns an object with at minimum `terms: List[str]` and `graph_context: str`.
> 2. Existing callers that use only `terms` continue to work without modification (backward-compatible accessor or migration path).
> 3. When graph context is empty, `graph_context` is `""` — never `None`.
> 4. Unit tests cover non-empty, empty, and error cases.

---

> **REQ-KG-792** | Priority: MUST
>
> **Description:** The retrieval pipeline MUST extract the `graph_context` field from the expander result and forward it as a named parameter to the generation stage. The graph context block MUST NOT be silently discarded at any intermediate step.
>
> **Rationale:** The pipeline is the only transport layer between query expansion and generation. If the context block is not explicitly threaded through, it will be silently lost.
>
> **Acceptance Criteria:**
> 1. After calling `expand()`, the pipeline binds `graph_context` to a named local variable.
> 2. `graph_context` is passed as an explicit keyword argument to the generation function.
> 3. An integration test asserts that a non-empty `graph_context` from the expander reaches the generation stage.

---

> **REQ-KG-794** | Priority: MUST
>
> **Description:** The LLM prompt template MUST include a named slot for graph-derived context. This slot MUST be positioned immediately before the retrieved document chunks section and after the system instruction preamble. The slot renders the graph context block verbatim inside a labeled section.
>
> **Rationale:** Placing graph context before document chunks follows the pattern that background knowledge precedes evidence so the model can use it as a lens when reading the chunks. Naming the section explicitly reduces prompt ambiguity.
>
> **Acceptance Criteria:**
> 1. The prompt template contains a conditional render block for graph context, identified by a stable template variable name.
> 2. When rendered with non-empty graph context, the output contains the graph context section appearing before document chunks.
> 3. The ordering is verified by a prompt-rendering test.

---

> **REQ-KG-796** | Priority: MUST
>
> **Description:** When the graph context block is empty — due to no matches, the feature being disabled, or a non-fatal error — the prompt MUST omit the graph context section and its heading entirely. No empty placeholder, blank line cluster, or `N/A` substitution is permitted.
>
> **Rationale:** Empty placeholder sections consume tokens without benefit and can confuse the model. Clean omission ensures the prompt is identical in structure to the pre-enhancement baseline when the feature is off, simplifying A/B comparisons.
>
> **Acceptance Criteria:**
> 1. When `graph_context` is `""`, the rendered prompt does not contain the graph context heading or any residual whitespace.
> 2. The rendered prompt with empty graph context is structurally identical to the pre-enhancement prompt.
> 3. A unit test explicitly asserts the absence of the heading when `graph_context=""`.

---

## 7. Configuration

All behavior introduced in Sections 3–6 must be governed by `KGConfig` so that operators can tune or disable each capability without code changes. New fields follow the existing `KGConfig` pattern: typed fields with safe defaults, validation at load time, and environment variable bindings under the `RAG_KG_` prefix. The master toggle defaults to `False` so the feature is opt-in.

---

> **REQ-KG-1200** | Priority: MUST
>
> **Description:** `KGConfig` MUST add a field `retrieval_edge_types: List[str]` with a default value of `[]` (empty list). When empty, the system falls back to untyped traversal (REQ-KG-766). When non-empty, only edges whose predicate appears in this list are followed during traversal.
>
> **Rationale:** Restricting traversal to specific edge types is the primary mechanism for controlling relevance. An empty default ensures no behavior change for existing deployments.
>
> **Acceptance Criteria:**
> 1. `KGConfig` defines `retrieval_edge_types: List[str]` with default `[]`.
> 2. The field is populated from `RAG_KG_RETRIEVAL_EDGE_TYPES` (comma-separated string).
> 3. When the env var is absent or empty, the field value is `[]`.

---

> **REQ-KG-1202** | Priority: MUST
>
> **Description:** `KGConfig` MUST add a field `retrieval_path_patterns: List[List[str]]` with a default value of `[]`. Each inner list is an ordered sequence of edge type labels defining a traversal path pattern. When empty, path-pattern matching is disabled.
>
> **Rationale:** Multi-hop reasoning requires controlling which sequences of edges produce useful inference chains. Flat edge-type filtering cannot express ordering; path patterns fill that gap.
>
> **Acceptance Criteria:**
> 1. `KGConfig` defines `retrieval_path_patterns: List[List[str]]` with default `[]`.
> 2. The field is populated from `RAG_KG_RETRIEVAL_PATH_PATTERNS` using JSON serialization (e.g., `'[["fixed_by","specified_by"],["blocks"]]'`).
> 3. When the env var is absent, the field value is `[]`.
> 4. Config validation (REQ-KG-1208) runs on this field at load time.

---

> **REQ-KG-1204** | Priority: MUST
>
> **Description:** `KGConfig` MUST add a field `graph_context_token_budget: int` with a default value of `500`. This is the maximum number of tokens the graph context block may occupy. The context formatter (Section 5) MUST truncate the block to fit within this budget.
>
> **Rationale:** Without a token budget, graph context can grow unboundedly as graph density increases, crowding out retrieved document chunks. A conservative default preserves the document-retrieval-first character of the system.
>
> **Acceptance Criteria:**
> 1. `KGConfig` defines `graph_context_token_budget: int = 500`.
> 2. The field is populated from `RAG_KG_GRAPH_CONTEXT_TOKEN_BUDGET`.
> 3. Config validation rejects values < 0 with a clear error message.

---

> **REQ-KG-1206** | Priority: MUST
>
> **Description:** `KGConfig` MUST add a field `enable_graph_context_injection: bool` with a default value of `False`. This is the master toggle for all retrieval enhancements. When `False`, the pipeline MUST skip typed traversal, graph context formatting, and prompt injection entirely, executing the pre-enhancement code path with no overhead.
>
> **Rationale:** A master toggle is essential for safe rollout: deployed disabled, enabled per-environment, rolled back instantly without redeployment. Defaulting to `False` is a deliberate safety-first choice.
>
> **Acceptance Criteria:**
> 1. `KGConfig` defines `enable_graph_context_injection: bool = False`.
> 2. The field is populated from `RAG_KG_ENABLE_GRAPH_CONTEXT_INJECTION` (truthy: `"true"` / `"1"`, case-insensitive).
> 3. When `False`, no typed traversal or context formatting code executes.
> 4. When `True`, the full Sections 3–6 pipeline executes.

---

> **REQ-KG-1208** | Priority: MUST
>
> **Description:** Config validation MUST reject path patterns in `retrieval_path_patterns` that contain edge type labels not defined in `kg_schema.yaml`. Validation MUST run at startup, not lazily at query time. The error message MUST identify the specific unknown label and the pattern it was found in. Validation does NOT run when `enable_graph_context_injection` is `False`.
>
> **Rationale:** Unknown edge type labels silently produce zero results at query time, which is indistinguishable from a valid configuration with no matches. Failing fast at startup with a precise error is preferable to silent misconfiguration.
>
> **Acceptance Criteria:**
> 1. Each label in `retrieval_path_patterns` is checked against the schema's edge type set.
> 2. Unknown labels raise an error at load time with the form: `"Unknown edge type 'X' in path pattern ['Y', 'X'] — not defined in kg_schema.yaml"`.
> 3. Valid configurations load without error.
> 4. When `enable_graph_context_injection` is `False`, validation is skipped.

---

## 8. Non-Functional Requirements

These requirements bound the observable operational behavior of the retrieval enhancements independently of functional correctness.

---

> **REQ-KG-1210** | Priority: MUST
>
> **Description:** Typed traversal MUST NOT add more than 50ms of latency at P95 over untyped traversal on the same graph, for graphs containing fewer than 50,000 nodes.
>
> **Rationale:** Query expansion is on the critical path of every RAG request. A 50ms P95 ceiling prevents typed traversal from meaningfully degrading end-to-end response time.
>
> **Acceptance Criteria:**
> 1. A benchmark runs 100 typed and 100 untyped traversal queries against a graph with 49,000 nodes.
> 2. The P95 delta (typed minus untyped) is ≤ 50ms.
> 3. The benchmark is part of the CI performance suite.

---

> **REQ-KG-1212** | Priority: MUST
>
> **Description:** Graph context formatting MUST complete within 100ms at P95 for context blocks under 500 tokens.
>
> **Rationale:** Formatting is synchronous on the generation path. A 100ms ceiling at the default budget ensures formatting does not become a bottleneck.
>
> **Acceptance Criteria:**
> 1. A benchmark calls the formatter 50 times with a ≤ 500 token payload.
> 2. P95 wall-clock time is ≤ 100ms.
> 3. The benchmark is parameterized at 100, 300, and 500 tokens.

---

> **REQ-KG-1214** | Priority: MUST
>
> **Description:** The system MUST degrade gracefully at two failure boundaries: (a) If typed traversal fails, fall back to untyped expansion and log at WARNING level. (b) If context formatting fails, proceed with empty `graph_context` (omitted per REQ-KG-796) and log at WARNING level. Neither failure MUST cause the request to fail.
>
> **Rationale:** Graph enrichment is additive, not a correctness requirement. The unenhanced pipeline produces valid (if less informed) answers. Propagating graph errors as request failures would violate the availability contract for an opt-in feature.
>
> **Acceptance Criteria:**
> 1. A test injecting an exception into typed traversal confirms: pipeline completes, untyped expansion used, WARNING logged.
> 2. A test injecting an exception into context formatting confirms: pipeline completes, prompt omits graph context, WARNING logged.
> 3. Neither fallback suppresses the exception silently — log entries include exception type and message.

---

> **REQ-KG-1216** | Priority: MUST
>
> **Description:** All configurable parameters introduced in Section 7 MUST be readable from environment variables with the `RAG_KG_` prefix, following the existing `KGConfig` naming convention. Defaults MUST remain in `KGConfig` field definitions; environment variables override defaults at runtime.
>
> **Rationale:** Operator deployments configure services through environment variables. Consistent prefix convention makes the full configuration surface discoverable.
>
> **Acceptance Criteria:**
> 1. Each Section 7 field has a corresponding `RAG_KG_` environment variable.
> 2. A smoke test sets all new variables to non-default values and asserts `KGConfig` reflects them.
> 3. No new defaults are hardcoded outside `KGConfig`.

---

## 9. System-Level Acceptance Criteria

| Criterion | Threshold | Related Requirements |
|-----------|-----------|---------------------|
| Typed traversal latency overhead | ≤ 50ms P95 delta vs untyped (< 50K nodes) | REQ-KG-760, REQ-KG-1210 |
| Context formatting latency | ≤ 100ms P95 (≤ 500 tokens) | REQ-KG-780, REQ-KG-1212 |
| Graceful degradation | Zero request failures from graph errors | REQ-KG-1214 |
| Backward compatibility | All pre-enhancement tests pass unchanged | REQ-KG-766 |
| Config validation | All invalid edge types caught at startup | REQ-KG-764, REQ-KG-1208 |

---

## 10. Requirements Traceability Matrix

| REQ ID | Section | Priority | Component |
|--------|---------|----------|-----------|
| REQ-KG-760 | 3 | MUST | Typed Edge Traversal |
| REQ-KG-762 | 3 | MUST | Typed Edge Traversal |
| REQ-KG-764 | 3 | MUST | Typed Edge Traversal |
| REQ-KG-766 | 3 | MUST | Typed Edge Traversal |
| REQ-KG-768 | 3 | MUST | Typed Edge Traversal |
| REQ-KG-770 | 4 | MUST | Path Pattern Queries |
| REQ-KG-772 | 4 | MUST | Path Pattern Queries |
| REQ-KG-774 | 4 | MUST | Path Pattern Queries |
| REQ-KG-776 | 4 | MUST | Path Pattern Queries |
| REQ-KG-778 | 4 | MUST | Path Pattern Queries |
| REQ-KG-780 | 5 | MUST | Graph Context Formatting |
| REQ-KG-782 | 5 | MUST | Graph Context Formatting |
| REQ-KG-784 | 5 | MUST | Graph Context Formatting |
| REQ-KG-786 | 5 | MUST | Graph Context Formatting |
| REQ-KG-788 | 5 | SHOULD | Graph Context Formatting |
| REQ-KG-790 | 6 | MUST | Prompt Injection |
| REQ-KG-792 | 6 | MUST | Prompt Injection |
| REQ-KG-794 | 6 | MUST | Prompt Injection |
| REQ-KG-796 | 6 | MUST | Prompt Injection |
| REQ-KG-1200 | 7 | MUST | Configuration |
| REQ-KG-1202 | 7 | MUST | Configuration |
| REQ-KG-1204 | 7 | MUST | Configuration |
| REQ-KG-1206 | 7 | MUST | Configuration |
| REQ-KG-1208 | 7 | MUST | Configuration |
| REQ-KG-1210 | 8 | MUST | Non-Functional |
| REQ-KG-1212 | 8 | MUST | Non-Functional |
| REQ-KG-1214 | 8 | MUST | Non-Functional |
| REQ-KG-1216 | 8 | MUST | Non-Functional |

**Total Requirements: 28**

- MUST: 27
- SHOULD: 1
- MAY: 0

---

## Appendix A. Glossary

| Term | Definition |
|------|-----------|
| **BFS** | Breadth-first search — the traversal strategy used by `query_neighbors` |
| **BM25** | Best Matching 25 — the lexical scoring function used for keyword retrieval |
| **Seed entity** | An entity matched in the user query that serves as the starting point for graph traversal |
| **Fan-out** | The number of expansion terms added from graph traversal, bounded by `max_terms` |
| **Predicate** | The edge type label on a Triple (e.g., `fixed_by`, `instantiates`, `connects_to`) |
| **Context window** | The maximum token capacity of the LLM prompt |
| **Token budget** | A configurable limit on how many tokens the graph context block may consume |
| **Verb normalization** | Mapping predicate labels to natural-language verb phrases (e.g., `fixed_by` → `was fixed by`) |

---

## Appendix B. Document References

| Document | Purpose |
|----------|---------|
| `KNOWLEDGE_GRAPH_SPEC.md` (v1.1.0) | Parent specification — entity extraction, storage, basic query expansion (REQ-KG-100–756) |
| `KNOWLEDGE_GRAPH_SPEC_SUMMARY.md` | Requirements digest of the parent spec |
| `KNOWLEDGE_GRAPH_DESIGN.md` | Phase 1 design document |
| `KNOWLEDGE_GRAPH_PHASE2_DESIGN.md` | Phase 2 design document (community detection, Neo4j) |
| `KNOWLEDGE_GRAPH_PHASE3_DESIGN.md` | Phase 3 design document (incremental updates, SV connectivity, entity resolution) |
| `KNOWLEDGE_GRAPH_ENGINEERING_GUIDE.md` | Operator guide for the KG subsystem |
| `RETRIEVAL_QUERY_SPEC.md` | Retrieval pipeline spec (Stage 2 query expansion integration point) |
| `config/kg_schema.yaml` | YAML schema defining valid entity and edge types |

---

## Appendix C. Open Questions

1. **Verb normalization table scope:** Should the predicate-to-verb mapping be maintained in `kg_schema.yaml` (alongside edge type definitions) or in a separate configuration file? Placing it in the schema keeps the single-source-of-truth property; a separate file avoids schema bloat. *(Affects REQ-KG-784.)*

2. **Path pattern configuration ergonomics:** Should path patterns support named references (e.g., `"fix_chain"`) that expand to predefined patterns in `kg_schema.yaml`, or must patterns always be specified inline as edge type lists? Named references reduce duplication across deployment configs but add indirection. *(Affects REQ-KG-770, REQ-KG-1202.)*

3. **Token budget estimation method:** Should the graph context formatter use the retrieval pipeline's existing tokenizer (if any) or a character-based approximation? Using the real tokenizer is more accurate but introduces a dependency on the specific LLM provider. *(Affects REQ-KG-786, REQ-KG-1204.)*
