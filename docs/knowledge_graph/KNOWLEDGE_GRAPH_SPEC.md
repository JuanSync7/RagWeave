# Knowledge Graph Subsystem -- Specification (v1.0.0)

## Document Information

> **Document intent:** This is a formal specification for the **Knowledge Graph (KG) subsystem** of RagWeave -- the package responsible for entity extraction, graph storage, query expansion, and entity description management. This subsystem replaces the monolithic `src/core/knowledge_graph.py` with a modular `src/knowledge_graph/` package mirroring the `src/guardrails/` ABC backend pattern. It integrates with the Embedding Pipeline (Nodes 10/13) for ingestion and the Retrieval Pipeline (Stage 2) for query-time expansion.
> For Embedding Pipeline requirements, see `EMBEDDING_PIPELINE_SPEC.md`.
> For Retrieval Pipeline requirements, see `RETRIEVAL_QUERY_SPEC.md`.

| Field | Value |
|-------|-------|
| System | RagWeave Knowledge Graph Subsystem |
| Document Type | Subsystem Specification |
| Companion Documents | `EMBEDDING_PIPELINE_SPEC.md` (Embedding Pipeline), `RETRIEVAL_QUERY_SPEC.md` (Query Processing), `2026-04-08-kg-subsystem-sketch.md` (Design Sketch) |
| Version | 1.0.0 |
| Status | Draft |
| Supersedes | `src/core/knowledge_graph.py` (monolithic implementation) |

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-04-08 | AI Assistant | Initial specification. Covers schema, package architecture, extraction, entity descriptions, storage, query/retrieval, community detection (Phase 2), export, integration, performance, and testing. |
| 1.1.0 | 2026-04-09 | AI Assistant | Appendix E: Phase 3 requirements (REQ-KG-730 through REQ-KG-756). Incremental graph updates, SV port connectivity, Sigma.js visualization, entity resolution, hierarchical Leiden, pyproject.toml deps. |

---

## 1. Scope & Definitions

### 1.1 Scope

This specification defines the requirements for the **Knowledge Graph subsystem** of RagWeave. The subsystem boundary is:

- **Ingestion entry point:** Embedding Pipeline Node 10 (extraction) and Node 13 (storage) invoke the KG subsystem to extract entities/triples from document chunks and persist them to the graph store.
- **Retrieval entry point:** Retrieval Pipeline Stage 2 invokes the KG subsystem to match entities in user queries and expand them with graph-derived terms.
- **Configuration entry point:** A YAML schema file (`config/kg_schema.yaml`) defines all valid entity and edge types. Runtime settings control extractor selection, query matching strategy, and storage backend.

**In scope:**

- YAML-driven entity/edge type schema with validation
- `GraphStorageBackend` ABC and concrete `NetworkXBackend` implementation
- Multi-extractor architecture: regex, GLiNER, LLM (Phase 1b), SV parser (Phase 1b)
- LangGraph subgraph for extraction pipeline (parallel branches, merge node)
- Entity descriptions: accumulated rich text per node with LLM summarization
- Two-tier query matching: spaCy rule-based + LLM fallback (Phase 1b)
- Query sanitization: token-boundary matching, alias expansion, fan-out control
- Package structure (`src/knowledge_graph/`) with public API and lazy singleton
- Backward compatibility with `src/core/knowledge_graph.py` during migration
- Obsidian export (migrated from monolith)
- Neo4j backend stub (Phase 1 -- stub only; full implementation Phase 2)
- Community detection stub (Phase 2)

**Out of scope:**

- Document parsing, text extraction, cleaning (see `DOCUMENT_PROCESSING_SPEC.md`)
- Vector embedding generation and storage (see `EMBEDDING_PIPELINE_SPEC.md`)
- Answer generation, reranking, guardrails (see `RETRIEVAL_QUERY_SPEC.md`, `RETRIEVAL_GENERATION_SPEC.md`)
- Real-time graph streaming or event-driven updates
- Multi-tenant graph isolation (single-tenant only in Phase 1)

### 1.2 Terminology

| Term | Definition |
|------|-----------|
| **Entity** | A named concept, component, person, or artifact extracted from document text and stored as a node in the knowledge graph |
| **Triple** | A subject-predicate-object relationship linking two entities via a typed edge |
| **Entity Description** | Accumulated textual context about an entity, sourced from all document chunks that mention it |
| **Extraction Result** | The output of the extraction pipeline: a set of entities, triples, and entity descriptions for a batch of chunks |
| **Extractor** | A component that processes text and produces entities and/or triples. Multiple extractors run in parallel. |
| **Merge Node** | The LangGraph node that reconciles overlapping extraction results from parallel extractors |
| **Entity Resolution** | The process of determining that two extracted mentions refer to the same real-world entity |
| **Alias** | An alternative surface form for an entity (e.g., "RAG" for "Retrieval-Augmented Generation") |
| **Schema** | The YAML-defined set of valid node types and edge types, serving as both LLM prompt context and runtime validator |
| **GLiNER** | A zero-shot named entity recognition model that identifies entities given a list of label types |
| **Fan-out** | The number of expansion terms added to a query from graph traversal; controlled to prevent noise |
| **Community** | A densely connected subgraph identified by clustering algorithms (Phase 2) |
| **Backend** | A concrete implementation of the `GraphStorageBackend` ABC (e.g., NetworkX, Neo4j) |
| **Lazy Singleton** | A pattern where the backend instance is created on first access and reused for all subsequent calls |
| **Node Type** | A classification category for an entity (e.g., `RTL_Module`, `Specification`, `Person`) |
| **Edge Type** | A classification category for a relationship (e.g., `instantiates`, `specified_by`, `authored_by`) |
| **Phase Tag** | A label on each node/edge type in the schema indicating when it becomes active (`phase_1`, `phase_1b`, `phase_2`) |
| **Structural Type** | A node or edge type derived from deterministic parsing of source code or document structure |
| **Semantic Type** | A node or edge type derived from LLM or NER-based interpretation of natural language text |

### 1.3 Requirement Priority Levels

This document uses RFC 2119 language:

- **MUST** -- Absolute requirement. The system is non-conformant without it.
- **SHOULD** -- Recommended. May be omitted only with documented justification.
- **MAY** -- Optional. Included at the implementor's discretion.

### 1.4 Requirement Format

Each requirement follows this structure:

> **REQ-KG-xxx** | Priority: MUST/SHOULD/MAY | Phase: [Phase 1/1b/2]
> **Description:** What the system shall do.
> **Rationale:** Why this requirement exists.
> **Acceptance Criteria:** How to verify conformance.

### 1.5 Requirement ID Ranges

| ID Range | Section |
|----------|---------|
| REQ-KG-100--199 | 4. Schema & Configuration |
| REQ-KG-200--299 | 5. Package Architecture |
| REQ-KG-300--399 | 6. Entity Extraction |
| REQ-KG-400--499 | 7. Entity Descriptions |
| REQ-KG-500--599 | 8. Graph Storage |
| REQ-KG-600--699 | 9. Query & Retrieval |
| REQ-KG-700--799 | 10. Community Detection |
| REQ-KG-800--899 | 11. Export & Visualization |
| REQ-KG-900--999 | 12. Integration Points |
| REQ-KG-1000--1099 | 13. Performance & Scalability |
| REQ-KG-1100--1199 | 14. Testing Requirements |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | Python 3.11+ runtime | Type hint syntax and dataclass features fail |
| A-2 | LangGraph/LangChain available | Extraction subgraph cannot be compiled |
| A-3 | NetworkX available | Default graph backend unavailable |
| A-4 | orjson available | Graph serialization/deserialization fails |
| A-5 | spaCy `en_core_web_sm` (or `blank("en")`) available for query matching | Entity matching falls back to substring only |
| A-6 | GLiNER model available at configured path when GLiNER extractor is enabled | GLiNER extraction fails; regex extractor remains functional |
| A-7 | LLM provider accessible when LLM extractor is enabled (Phase 1b) | LLM extraction fails; other extractors remain functional |
| A-8 | tree-sitter-verilog grammar available when SV parser is enabled (Phase 1b) | SV parsing fails; other extractors remain functional |
| A-9 | Graph fits in memory for NetworkX backend | For graphs exceeding single-machine memory, Neo4j backend (Phase 2) is required |
| A-10 | Sequential document processing (no concurrent ingestion of same document) | Race conditions on graph state |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **ABC backend abstraction** | All graph operations go through the `GraphStorageBackend` ABC. Swapping backends requires only a configuration change. |
| **YAML schema as single source of truth** | Entity and edge types are defined once in `config/kg_schema.yaml` and used for LLM prompting, extraction validation, and runtime type checking. |
| **Fail-safe extraction** | When any extractor fails, the pipeline continues with results from other extractors. A single extractor failure does not halt ingestion. |
| **Explicit composition over registry** | Extractors are composed as a LangGraph subgraph with parallel branches, not a dynamic registry. The topology is visible and testable. |
| **Incremental by default** | Graph updates merge new data with existing data. Re-ingesting a document updates affected nodes/edges without full graph rebuild. |
| **Bounded expansion** | Query expansion is always bounded by configurable fan-out limits to prevent retrieval noise. |

---

## 2. Pipeline Overview

### 2.1 KG Subsystem in the Overall Architecture

```text
                    INGESTION PIPELINE
                    ==================

Clean Document Store
        |
        v
  [Node 6-9]  Chunking, Enrichment, Metadata, Cross-Ref
        |
        v
  ┌─────────────────────────────────────────────────────┐
  │ [Node 10] KNOWLEDGE GRAPH EXTRACTION                │
  │                                                     │
  │   ┌──────────────────────────────────────────────┐  │
  │   │  KG Extraction Subgraph (LangGraph)          │  │
  │   │                                              │  │
  │   │   ┌─────────┐  ┌─────────┐  ┌───────────┐   │  │
  │   │   │  Regex  │  │ GLiNER  │  │ LLM [1b]  │   │  │
  │   │   │Extractor│  │Extractor│  │ Extractor  │   │  │
  │   │   └────┬────┘  └────┬────┘  └─────┬─────┘   │  │
  │   │        │            │             │          │  │
  │   │   ┌────┴────┐       │        ┌────┴────┐    │  │
  │   │   │         │       │        │SV Parser│    │  │
  │   │   │         │       │        │  [1b]   │    │  │
  │   │   │         │       │        └────┬────┘    │  │
  │   │   │         v       v             │         │  │
  │   │   │     ┌───────────────────────┐ │         │  │
  │   │   └────>│     MERGE NODE        │<┘         │  │
  │   │         │  Dedup + Validation   │           │  │
  │   │         └──────────┬────────────┘           │  │
  │   │                    │                        │  │
  │   │                    v                        │  │
  │   │           ExtractionResult                  │  │
  │   └──────────────────────────────────────────────┘  │
  └─────────────────────┬──────────────────────────────┘
                        |
                        v
  [Node 11-12]  Quality Validation, Embedding Storage
                        |
                        v
  ┌─────────────────────────────────────────────────────┐
  │ [Node 13] KNOWLEDGE GRAPH STORAGE                   │
  │   backend = get_graph_backend()                     │
  │   backend.upsert_entities(result.entities)          │
  │   backend.upsert_triples(result.triples)            │
  │   backend.upsert_descriptions(result.descriptions)  │
  └─────────────────────────────────────────────────────┘


                    RETRIEVAL PIPELINE
                    ==================

  User Query
        |
        v
  [Stage 1]  Query Processing + Conversation Memory
        |
        v
  ┌─────────────────────────────────────────────────────┐
  │ [Stage 2] KG EXPANSION                              │
  │                                                     │
  │   expander = get_query_expander()                   │
  │   matched = expander.match_entities(query)          │
  │     -> spaCy rule-based (fast path)                 │
  │     -> LLM fallback [1b] (if no matches)            │
  │   expanded = expander.expand(matched, depth=1)      │
  │   bm25_query += expanded[:max_expansion_terms]      │
  └─────────────────────┬──────────────────────────────┘
                        |
                        v
  [Stage 3+]  Embedding, Retrieval, Reranking, Generation
```

### 2.2 Package Structure

```text
src/knowledge_graph/
  __init__.py                       # Public API: get_graph_backend(), get_query_expander()
                                    # Lazy singleton dispatcher (mirrors src/guardrails/__init__.py)
  backend.py                        # GraphStorageBackend ABC
  common/
    __init__.py
    schemas.py                      # Entity, Triple, ExtractionResult, EntityDescription
    types.py                        # KGConfig, SchemaDefinition (loaded from kg_schema.yaml)
    utils.py                        # Shared helpers: alias normalization, type validation
  extraction/
    __init__.py                     # ExtractionPipeline: compiles and runs the subgraph
    base.py                         # EntityExtractor protocol (extract_entities, extract_triples)
    regex_extractor.py              # Migrated from core/knowledge_graph.py
    gliner_extractor.py             # Migrated from core/knowledge_graph.py
    llm_extractor.py                # Phase 1b: LLM structured-output extractor
    sv_parser.py                    # Phase 1b: tree-sitter-verilog structural extractor
    merge.py                        # Merge node: dedup, alias resolution, type validation
  query/
    __init__.py
    entity_matcher.py               # spaCy rule-based matcher
    expander.py                     # GraphQueryExpander (migrated, enhanced)
    sanitizer.py                    # Token-boundary matching, alias expansion, fan-out
    llm_fallback.py                 # Phase 1b: LLM entity identification from query
  backends/
    __init__.py
    networkx_backend.py             # NetworkX + orjson persistence
    neo4j_backend.py                # Phase 2 stub
  community/
    __init__.py
    detector.py                     # Phase 2 stub: Leiden algorithm interface
    summarizer.py                   # Phase 2 stub: LLM community summarization
  export/
    __init__.py
    obsidian.py                     # Migrated from core/knowledge_graph.py

config/
  kg_schema.yaml                    # Entity types, edge types, phase tags, extraction hints
```

---

## 3. Cross-References

This specification references and is referenced by the following documents:

| Reference | Location | Relationship |
|-----------|----------|-------------|
| Embedding Pipeline Spec | `docs/ingestion/embedding/EMBEDDING_PIPELINE_SPEC.md` | Node 10 (FR-1000--FR-1099) and Node 13 (FR-1300--FR-1399) are modified by this spec |
| Retrieval Query Spec | `docs/retrieval/query/RETRIEVAL_QUERY_SPEC.md` | REQ-304 (KG expansion) is superseded and expanded by REQ-KG-600--REQ-KG-699 |
| Design Sketch | `docs/knowledge_graph/2026-04-08-kg-subsystem-sketch.md` | Informative: design rationale and approach selection |
| Guardrails Package | `src/guardrails/` | Pattern reference for ABC backend, lazy singleton, `common/schemas.py` |

---

## 4. Schema & Configuration

### 4.1 YAML Schema Format

> **REQ-KG-100** | Priority: MUST | Phase: Phase 1
>
> **Description:** The system MUST define all valid entity (node) types and relationship (edge) types in a single YAML schema file at `config/kg_schema.yaml`. This file is the single source of truth for type governance across all extractors and the storage backend.
>
> **Rationale:** Without a canonical schema, each extractor produces ad-hoc types, leading to inconsistent graphs and unreliable query matching. The current `_classify_type()` heuristic in the monolith uses only three types (`technology`, `acronym`, `concept`), which is insufficient for ASIC domain coverage.
>
> **Acceptance Criteria:**
> 1. A file `config/kg_schema.yaml` exists and is loaded at subsystem initialization.
> 2. The file defines `node_types` and `edge_types` as top-level keys.
> 3. Removing the file or providing an invalid YAML causes a clear startup error.

> **REQ-KG-101** | Priority: MUST | Phase: Phase 1
>
> **Description:** Each node type definition in the YAML schema MUST include at minimum: `name` (string, unique), `description` (string), `category` (one of `structural` or `semantic`), and `phase` (one of `phase_1`, `phase_1b`, `phase_2`).
>
> **Rationale:** Category distinguishes parser-derived types (deterministic) from NER/LLM-derived types (probabilistic), enabling different validation strategies. Phase tags control which types are active at runtime.
>
> **Acceptance Criteria:**
> 1. A node type missing any required field causes a schema validation error at startup.
> 2. The `category` field accepts only `structural` or `semantic`.
> 3. The `phase` field accepts only `phase_1`, `phase_1b`, or `phase_2`.

> **REQ-KG-102** | Priority: MUST | Phase: Phase 1
>
> **Description:** The YAML schema MUST define the following **structural** node types (category: `structural`): `RTL_Module`, `Port`, `Parameter`, `Instance`, `Signal`, `ClockDomain`, `Interface`, `Package`, `TypeDef`, `FSM_State`, `Generate`, `Task_Function`, `SVA_Assertion`, `UVM_Component`, `TestCase`, `CoverGroup`, `Sequence`, `Constraint`, `Pipeline_Stage`, `FIFO_Buffer`, `Arbiter`, `Decoder_Encoder`, `RegisterFile`, `MemoryMap`. A baseline subset of these types (`RTL_Module`, `Port`, `Parameter`, `Instance`, `Signal`, `Interface`, `Package`) MUST be tagged `phase: phase_1` in the schema because they are detectable by regex and GLiNER extractors. The remaining specialized structural types (`ClockDomain`, `TypeDef`, `FSM_State`, `Generate`, `Task_Function`, `SVA_Assertion`, `UVM_Component`, `TestCase`, `CoverGroup`, `Sequence`, `Constraint`, `Pipeline_Stage`, `FIFO_Buffer`, `Arbiter`, `Decoder_Encoder`, `RegisterFile`, `MemoryMap`) MUST be tagged `phase: phase_1b` as they require the SV parser for reliable extraction.
>
> **Rationale:** These types represent the core structural elements of ASIC design artifacts. They are exhaustively enumerated to ensure deterministic parser extractors produce only recognized types. The phase split ensures that basic module hierarchy types are available to regex/GLiNER extractors in Phase 1, while specialized types that need parser support are deferred to Phase 1b.
>
> **Acceptance Criteria:**
> 1. All 24 structural node types listed above are present in `config/kg_schema.yaml` with `category: structural`.
> 2. Each type has a non-empty `description` field.
> 3. The 7 baseline types (`RTL_Module`, `Port`, `Parameter`, `Instance`, `Signal`, `Interface`, `Package`) have `phase: phase_1`.
> 4. The remaining 17 specialized types have `phase: phase_1b`.

> **REQ-KG-103** | Priority: MUST | Phase: Phase 1
>
> **Description:** The YAML schema MUST define the following **semantic** node types (category: `semantic`): `Specification`, `DesignDecision`, `Requirement`, `TradeOff`, `KnownIssue`, `Assumption`, `Person`, `Team`, `Project`, `Review`, `Protocol`, `IP_Block`, `EDA_Tool`, `Script`, `TimingConstraint`, `AreaConstraint`, `PowerConstraint`.
>
> **Rationale:** These types represent domain concepts that require NER or LLM interpretation to extract. They cover the organizational, decisional, and constraint dimensions of ASIC projects.
>
> **Acceptance Criteria:**
> 1. All 17 semantic node types listed above are present in `config/kg_schema.yaml` with `category: semantic`.
> 2. Each type has a non-empty `description` field.

> **REQ-KG-104** | Priority: MUST | Phase: Phase 1
>
> **Description:** Each edge type definition in the YAML schema MUST include at minimum: `name` (string, unique), `description` (string), `category` (one of `structural` or `semantic`), and `phase` (one of `phase_1`, `phase_1b`, `phase_2`).
>
> **Rationale:** Consistent edge type governance prevents the graph from accumulating arbitrary relation labels from different extractors.
>
> **Acceptance Criteria:**
> 1. An edge type missing any required field causes a schema validation error at startup.
> 2. The `category` and `phase` fields follow the same constraints as node types (REQ-KG-101).

> **REQ-KG-105** | Priority: MUST | Phase: Phase 1
>
> **Description:** The YAML schema MUST define the following **structural** edge types: `instantiates`, `connects_to`, `depends_on`, `parameterized_by`, `belongs_to_clock_domain`, `implements_interface`, `contains`, `transitions_to`, `drives`, `reads`.
>
> **Rationale:** These edges capture the deterministic structural relationships between ASIC design entities that parser extractors can identify with certainty.
>
> **Acceptance Criteria:**
> 1. All 10 structural edge types listed above are present in `config/kg_schema.yaml` with `category: structural`.

> **REQ-KG-106** | Priority: MUST | Phase: Phase 1
>
> **Description:** The YAML schema MUST define the following **semantic** edge types: `specified_by`, `verified_by`, `authored_by`, `reviewed_by`, `blocks`, `supersedes`, `constrained_by`, `trades_off_against`, `assumes`, `complies_with`, `relates_to`, `design_decision_for`.
>
> **Rationale:** These edges capture the semantic relationships identified by NER/LLM extractors: authorship, verification chains, design decisions, and cross-document dependencies.
>
> **Acceptance Criteria:**
> 1. All 12 semantic edge types listed above are present in `config/kg_schema.yaml` with `category: semantic`.

> **REQ-KG-107** | Priority: MUST | Phase: Phase 1
>
> **Description:** Each node type in the YAML schema MUST include a `phase` tag. At runtime, the system MUST activate only node types whose phase tag is less than or equal to the current runtime phase. Extractors MUST NOT produce entities with types tagged for a later phase.
>
> **Rationale:** Phase tags enable the schema to be fully specified upfront while controlling which types are active. This avoids schema drift between phases and ensures extractors do not produce types the storage backend or query layer does not yet handle.
>
> **Acceptance Criteria:**
> 1. Given a runtime phase of `phase_1`, only node types tagged `phase_1` are active.
> 2. Given a runtime phase of `phase_1b`, node types tagged `phase_1` and `phase_1b` are active.
> 3. An entity extracted with a type tagged for a later phase is either dropped or re-classified to a generic fallback type, with a warning logged.

> **REQ-KG-108** | Priority: MUST | Phase: Phase 1
>
> **Description:** Each node type in the YAML schema MAY include an optional `gliner_label` field. When present, this value MUST be used as the GLiNER label for that type instead of the type `name`. At startup, the system MUST derive the GLiNER label list by collecting `gliner_label` (if present) or `name` (otherwise) from all active node types.
>
> **Rationale:** GLiNER performs better with short, natural-language labels (e.g., "FSM" instead of "finite_state_machine"). This derivation replaces the current hardcoded `GLINER_ENTITY_LABELS` configuration list in `config/settings.py`.
>
> **Acceptance Criteria:**
> 1. Given a node type `{name: finite_state_machine, gliner_label: FSM}`, the derived GLiNER label list contains `"FSM"`, not `"finite_state_machine"`.
> 2. Given a node type `{name: module}` with no `gliner_label`, the derived list contains `"module"`.
> 3. The system validates that all `gliner_label` values are unique across node types at startup.
> 4. A warning is logged if a `gliner_label` collides with another type's `name`.

> **REQ-KG-109** | Priority: MUST | Phase: Phase 1
>
> **Description:** The system MUST validate the YAML schema at startup and fail fast with a clear error message if any of the following conditions are detected: (a) duplicate node type names, (b) duplicate edge type names, (c) missing required fields, (d) invalid `category` or `phase` values, (e) duplicate `gliner_label` values.
>
> **Rationale:** Schema errors should be caught at startup, not at extraction time when they are harder to diagnose.
>
> **Acceptance Criteria:**
> 1. Each validation condition (a--e) produces a distinct error message identifying the offending type.
> 2. The system does not proceed past initialization if schema validation fails.

> **REQ-KG-110** | Priority: SHOULD | Phase: Phase 1
>
> **Description:** Each node type in the YAML schema SHOULD include an optional `extraction_hints` field containing a short natural-language description of how to identify entities of this type. When present, these hints SHOULD be included in the LLM extractor's prompt template (Phase 1b).
>
> **Rationale:** Domain-specific extraction hints improve LLM recall for types that have non-obvious surface forms (e.g., "a `CoverGroup` is defined by a `covergroup...endgroup` block in SystemVerilog").
>
> **Acceptance Criteria:**
> 1. Extraction hints, when present, appear in the LLM extractor's prompt context.
> 2. Extraction hints are optional; their absence does not cause errors.

> **REQ-KG-111** | Priority: SHOULD | Phase: Phase 1
>
> **Description:** Edge type definitions in the YAML schema SHOULD include optional `source_types` and `target_types` fields listing the allowed node types for the edge's source and target. When present, the merge node (REQ-KG-308) SHOULD validate extracted triples against these constraints.
>
> **Rationale:** Type constraints on edges prevent semantically invalid triples (e.g., a `Person` node connected via `instantiates` to another `Person`).
>
> **Acceptance Criteria:**
> 1. Given an edge type `instantiates` with `source_types: [RTL_Module]` and `target_types: [RTL_Module, IP_Block]`, a triple `(Person, instantiates, RTL_Module)` is flagged as invalid.
> 2. Triples violating type constraints are logged as warnings and optionally dropped (configurable).

---

## 5. Package Architecture

> **REQ-KG-200** | Priority: MUST | Phase: Phase 1
>
> **Description:** The KG subsystem MUST be implemented as a Python package at `src/knowledge_graph/` with the directory structure specified in Section 2.2 of this document.
>
> **Rationale:** The monolithic `src/core/knowledge_graph.py` (558 lines) mixes extraction, storage, query expansion, and export in a single file. A package structure enables independent testing, clear ownership boundaries, and room for backend-specific implementations.
>
> **Acceptance Criteria:**
> 1. The package `src/knowledge_graph/` exists with `__init__.py` and all subpackages listed in Section 2.2.
> 2. Each subpackage has its own `__init__.py`.
> 3. No circular imports exist between subpackages.

> **REQ-KG-201** | Priority: MUST | Phase: Phase 1
>
> **Description:** The system MUST define a `GraphStorageBackend` ABC in `src/knowledge_graph/backend.py` with the following abstract methods: `add_node`, `add_edge`, `upsert_entities`, `upsert_triples`, `upsert_descriptions`, `query_neighbors`, `get_entity`, `get_predecessors`, `save`, `load`, `stats`. Each method MUST have full type annotations and docstrings specifying the contract.
>
> **Rationale:** A rich ABC (as opposed to a thin CRUD interface) allows backends to optimize traversal and query operations internally. This mirrors the `GuardrailBackend` ABC pattern in `src/guardrails/backend.py`.
>
> **Acceptance Criteria:**
> 1. `GraphStorageBackend` is an `abc.ABC` subclass.
> 2. All listed methods are `@abstractmethod`.
> 3. Each method has type annotations for all parameters and the return type.
> 4. Each method has a docstring describing preconditions, postconditions, and error behavior.

> **REQ-KG-202** | Priority: MUST | Phase: Phase 1
>
> **Description:** The system MUST implement a `NetworkXBackend` class in `src/knowledge_graph/backends/networkx_backend.py` that implements all `GraphStorageBackend` abstract methods using NetworkX `DiGraph` and orjson for JSON serialization.
>
> **Rationale:** NetworkX is the current storage mechanism (via `KnowledgeGraphBuilder`). Migrating it into an ABC-conforming backend preserves existing behavior while enabling future backend swaps.
>
> **Acceptance Criteria:**
> 1. `NetworkXBackend` passes all ABC contract tests (REQ-KG-1100).
> 2. `NetworkXBackend.save()` produces JSON output compatible with the current `KnowledgeGraphBuilder.save()` format (node-link JSON).
> 3. `NetworkXBackend.load()` can read graphs saved by the current `KnowledgeGraphBuilder.save()`.

> **REQ-KG-203** | Priority: MUST | Phase: Phase 1
>
> **Description:** The system MUST include a `Neo4jBackend` stub in `src/knowledge_graph/backends/neo4j_backend.py` that implements all `GraphStorageBackend` abstract methods. Each method MUST raise `NotImplementedError` with a message indicating Phase 2.
>
> **Rationale:** The stub proves the ABC contract is complete from day one and provides a clear extension point for full Neo4j implementation in Phase 2.
>
> **Acceptance Criteria:**
> 1. `Neo4jBackend` is a concrete subclass of `GraphStorageBackend`.
> 2. Every method raises `NotImplementedError("Neo4j backend is Phase 2")`.
> 3. The stub passes ABC instantiation (no abstract methods left unimplemented).

> **REQ-KG-204** | Priority: MUST | Phase: Phase 1
>
> **Description:** The `src/knowledge_graph/__init__.py` module MUST expose a public API consisting of at minimum: `get_graph_backend()`, `get_query_expander()`. These functions MUST use a lazy singleton pattern: the backend/expander instance is created on first call and reused for all subsequent calls within the same process. Backend selection MUST be controlled by a configuration key (`KG_BACKEND`).
>
> **Rationale:** The lazy singleton pattern mirrors `src/guardrails/__init__.py` and ensures callers (Node 13, Stage 2) do not need to manage backend lifecycle. Configuration-driven selection enables backend swapping without code changes.
>
> **Acceptance Criteria:**
> 1. `get_graph_backend()` returns the same instance on repeated calls within the same process.
> 2. Setting `KG_BACKEND = "networkx"` returns a `NetworkXBackend` instance.
> 3. Setting `KG_BACKEND = "neo4j"` returns a `Neo4jBackend` instance (which raises `NotImplementedError` on use).
> 4. Setting `KG_BACKEND` to an unknown value raises `ValueError` with a message listing valid backends.
> 5. Setting `KG_BACKEND` to `""` or `"none"` returns a no-op backend that silently accepts all calls.

> **REQ-KG-205** | Priority: MUST | Phase: Phase 1
>
> **Description:** The system MUST define typed data contracts in `src/knowledge_graph/common/schemas.py` including at minimum: `Entity` (name, type, sources, mention_count, aliases, raw_mentions, current_summary), `Triple` (subject, predicate, object, source, weight), `ExtractionResult` (entities: list[Entity], triples: list[Triple], descriptions: dict), `EntityDescription` (text, source, chunk_id).
>
> **Rationale:** Typed contracts ensure all extractors produce compatible output and all consumers (storage, query, export) receive well-defined data structures. This mirrors `src/guardrails/common/schemas.py`.
>
> **Acceptance Criteria:**
> 1. All listed dataclasses exist in `src/knowledge_graph/common/schemas.py`.
> 2. All fields have type annotations.
> 3. Constructing an `ExtractionResult` with invalid field types raises a `TypeError`.

> **REQ-KG-206** | Priority: MUST | Phase: Phase 1
>
> **Description:** The system MUST define configuration types in `src/knowledge_graph/common/types.py` including at minimum: `KGConfig` (backend selection, extractor toggles, query matching settings, entity description budgets) and `SchemaDefinition` (parsed representation of `config/kg_schema.yaml`).
>
> **Rationale:** Centralizing configuration in typed dataclasses prevents config-related bugs (typos, type mismatches) and makes config validation testable.
>
> **Acceptance Criteria:**
> 1. `KGConfig` and `SchemaDefinition` are defined as dataclasses or TypedDict with full type annotations.
> 2. `SchemaDefinition` can be constructed from parsed YAML output.

> **REQ-KG-207** | Priority: MUST | Phase: Phase 1
>
> **Description:** During the migration period, `src/core/knowledge_graph.py` MUST be preserved as a thin shim that re-exports all public names (`KnowledgeGraphBuilder`, `GraphQueryExpander`, `EntityExtractor`, `GLiNEREntityExtractor`, `export_obsidian`) from the new `src/knowledge_graph/` package. The shim MUST emit a `DeprecationWarning` on first import.
>
> **Rationale:** Existing callers (tests, scripts, notebook imports) that import from `src/core/knowledge_graph` must continue to work during the migration period. The deprecation warning signals that callers should update their imports.
>
> **Acceptance Criteria:**
> 1. `from src.core.knowledge_graph import KnowledgeGraphBuilder` works and returns the class from `src/knowledge_graph/`.
> 2. A `DeprecationWarning` is emitted on the first import from `src.core.knowledge_graph`.
> 3. All names listed above are re-exported.

> **REQ-KG-208** | Priority: SHOULD | Phase: Phase 1
>
> **Description:** The `src/knowledge_graph/common/utils.py` module SHOULD provide shared helper functions including at minimum: `normalize_alias(name: str) -> str` (case-insensitive normalization), `validate_type(type_name: str, schema: SchemaDefinition) -> bool` (check if a type is valid and active), `derive_gliner_labels(schema: SchemaDefinition) -> list[str]` (build GLiNER label list from schema).
>
> **Rationale:** Centralizing shared helpers prevents duplication across extractors and the merge node.
>
> **Acceptance Criteria:**
> 1. `normalize_alias("Retrieval-Augmented Generation")` and `normalize_alias("retrieval-augmented generation")` return the same value.
> 2. `validate_type("RTL_Module", schema)` returns `True` when `RTL_Module` is in the schema with an active phase.
> 3. `derive_gliner_labels(schema)` returns the correct list per REQ-KG-108.

---

## 6. Entity Extraction

### 6.1 Multi-Extractor Architecture

> **REQ-KG-300** | Priority: MUST | Phase: Phase 1
>
> **Description:** The KG subsystem MUST support multiple entity extractors running as parallel branches in a LangGraph subgraph. The subgraph MUST be compiled once at initialization and reused for all extraction invocations. Each branch processes the same input (a batch of text chunks) and produces an `ExtractionResult`.
>
> **Rationale:** Different extractors have complementary strengths: regex is fast and precise for surface patterns, GLiNER handles zero-shot NER, LLM handles implicit relations, and SV parser handles deterministic code structure. Running them in parallel avoids sequential latency accumulation. The LangGraph subgraph is native to the existing pipeline architecture.
>
> **Acceptance Criteria:**
> 1. The extraction subgraph compiles without error.
> 2. Enabling two extractors (e.g., regex + GLiNER) produces results from both.
> 3. Disabling all extractors produces an empty `ExtractionResult`.
> 4. Adding a chunk to the subgraph input triggers all enabled extractors in parallel.

> **REQ-KG-301** | Priority: MUST | Phase: Phase 1
>
> **Description:** Each extractor MUST implement the `EntityExtractor` protocol defined in `src/knowledge_graph/extraction/base.py`. The protocol MUST require at minimum: `extract_entities(text: str) -> set[str]`, `extract_relations(text: str, known_entities: set[str]) -> list[Triple]`, and `name` (a string property identifying the extractor for logging).
>
> **Rationale:** A common protocol ensures all extractors are interchangeable in the subgraph and produce compatible output for the merge node.
>
> **Acceptance Criteria:**
> 1. All concrete extractors satisfy the protocol (checked via `isinstance` or structural subtyping).
> 2. Each extractor's `name` property returns a unique, non-empty string.

> **REQ-KG-302** | Priority: MUST | Phase: Phase 1
>
> **Description:** Each extractor MUST be independently toggleable via configuration. The configuration keys MUST be: `kg.enable_regex_extractor` (default: `true`), `kg.enable_gliner_extractor` (default: `false`), `kg.enable_llm_extractor` (default: `false`), `kg.enable_sv_parser` (default: `false`).
>
> **Rationale:** Not all extractors are needed for every deployment. GLiNER and LLM extractors have model dependencies; SV parser is only relevant for SystemVerilog codebases. Independent toggles allow minimal-dependency deployments.
>
> **Acceptance Criteria:**
> 1. Setting `kg.enable_regex_extractor = false` removes the regex branch from the subgraph.
> 2. Setting `kg.enable_gliner_extractor = true` adds the GLiNER branch.
> 3. The subgraph compiles successfully with any combination of enabled extractors (including none).

### 6.2 Regex Extractor

> **REQ-KG-303** | Priority: MUST | Phase: Phase 1
>
> **Description:** The regex extractor MUST be migrated from the current `EntityExtractor` class in `src/core/knowledge_graph.py` into `src/knowledge_graph/extraction/regex_extractor.py`. It MUST preserve the existing extraction patterns: CamelCase (`_CAMEL_PAT`), ALL-CAPS acronyms (`_ACRONYM_PAT`), multi-word capitalized phrases (`_MULTI_WORD_PAT`), and acronym expansion (`_EXPAND_PAT_1`, `_EXPAND_PAT_2`). It MUST preserve the existing stopword filtering (`_STOPWORDS`), sentence-starter filtering (`_SENTENCE_STARTERS`), and relation extraction patterns (is_a, subset_of, used_for, uses, such-as expansion).
>
> **Rationale:** The regex extractor is the baseline with known precision/recall characteristics. Migration must not regress existing behavior.
>
> **Acceptance Criteria:**
> 1. Given the same input text, the migrated regex extractor produces identical entity and relation output as the current `EntityExtractor`.
> 2. All regex patterns from the monolith are present in the migrated module.
> 3. Existing unit tests for `EntityExtractor` pass against the migrated class.

> **REQ-KG-304** | Priority: SHOULD | Phase: Phase 1
>
> **Description:** The regex extractor SHOULD validate extracted entity types against the YAML schema (REQ-KG-100). Entities whose heuristic type (from `_classify_type`) does not map to a valid schema type SHOULD be assigned a configurable fallback type (default: `"concept"`).
>
> **Rationale:** The current `_classify_type` heuristic produces only three types (`technology`, `acronym`, `concept`). Schema validation ensures the regex extractor's output aligns with the formal type system while preserving backward compatibility via the fallback.
>
> **Acceptance Criteria:**
> 1. Entities classified as `technology` or `acronym` are mapped to the nearest schema type or the fallback.
> 2. The fallback type is configurable via `kg.regex_fallback_type`.

### 6.3 GLiNER Extractor

> **REQ-KG-305** | Priority: MUST | Phase: Phase 1
>
> **Description:** The GLiNER extractor MUST be migrated from the current `GLiNEREntityExtractor` class in `src/core/knowledge_graph.py` into `src/knowledge_graph/extraction/gliner_extractor.py`. It MUST use the YAML-derived label list (REQ-KG-108) instead of the hardcoded `GLINER_ENTITY_LABELS`. It MUST delegate acronym alias detection and relation extraction to the regex extractor (preserving current behavior).
>
> **Rationale:** GLiNER's zero-shot NER capability is most effective when its labels are aligned with the domain schema. Derivation from YAML eliminates the maintenance burden of a separate label list.
>
> **Acceptance Criteria:**
> 1. The GLiNER extractor uses labels derived from `config/kg_schema.yaml`, not a hardcoded list.
> 2. Adding a new node type to the YAML schema automatically adds it to the GLiNER label list (no code change required).
> 3. Acronym aliases and relations are produced by delegating to the regex extractor.

### 6.4 LLM Extractor

> **REQ-KG-306** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The system MUST implement an LLM-based extractor in `src/knowledge_graph/extraction/llm_extractor.py` that uses structured JSON output to extract entities and triples. The extractor MUST: (a) construct a prompt containing the YAML schema node/edge types and their descriptions, (b) include `extraction_hints` from the schema where available, (c) submit the prompt + chunk text to the configured LLM via the existing LiteLLM router, (d) parse the structured JSON response into `Entity` and `Triple` objects, (e) validate all extracted types against the schema.
>
> **Rationale:** LLM extraction captures implicit relations and domain-specific semantics that regex and GLiNER miss (e.g., "the team decided to use AXI4 instead of APB for the high-bandwidth path" implies a `DesignDecision` entity and a `trades_off_against` edge). Structured JSON output provides reliable parsing compared to free-text extraction.
>
> **Acceptance Criteria:**
> 1. Given a text chunk containing an implicit design decision, the LLM extractor produces at least one entity of type `DesignDecision` or `TradeOff`.
> 2. All extracted entity types are valid per the YAML schema.
> 3. The prompt template includes all active node types, edge types, and extraction hints.
> 4. Invalid JSON responses are handled gracefully (logged, not raised).
> 5. The extractor uses the existing LiteLLM router (no separate LLM client).

> **REQ-KG-307** | Priority: SHOULD | Phase: Phase 1b
>
> **Description:** The LLM extractor SHOULD use a configurable prompt template stored in a separate file or configuration key (`kg.llm_extraction_prompt_template`). The template SHOULD support variable substitution for `{schema_types}`, `{schema_edges}`, `{extraction_hints}`, and `{chunk_text}`.
>
> **Rationale:** Prompt engineering iteration should not require code changes. A configurable template enables domain-specific tuning.
>
> **Acceptance Criteria:**
> 1. Changing the prompt template via configuration changes the LLM input without code changes.
> 2. All template variables are substituted correctly.

### 6.5 SV Parser Extractor

> **REQ-KG-308** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The system MUST implement a SystemVerilog parser extractor in `src/knowledge_graph/extraction/sv_parser.py` that uses tree-sitter-verilog to parse `.sv` and `.v` files and extract structural entities (modules, ports, parameters, instances, signals, FSM states, generate blocks) and structural relationships (instantiates, connects_to, parameterized_by, contains). Extraction MUST be deterministic: the same input file always produces the same entities and triples.
>
> **Rationale:** Structural ASIC entities can be extracted with 100% precision from source code, unlike probabilistic NER/LLM extraction. tree-sitter provides fast, incremental parsing without requiring a full compiler frontend.
>
> **Acceptance Criteria:**
> 1. Given a SystemVerilog file containing `module top (input clk); sub_mod u0 (.clk(clk)); endmodule`, the parser extracts: entities `top` (RTL_Module), `clk` (Port), `sub_mod` (RTL_Module), `u0` (Instance); triples `(top, contains, u0)`, `(u0, instantiates, sub_mod)`, `(clk, connects_to, u0.clk)`.
> 2. Non-SV files are skipped without error.
> 3. tree-sitter parse errors are caught and logged; partial results from parseable portions are returned.

> **REQ-KG-309** | Priority: SHOULD | Phase: Phase 1b
>
> **Description:** The SV parser extractor SHOULD maintain a list of known unsupported SystemVerilog constructs (e.g., certain UVM macros, complex generate patterns). When an unsupported construct is encountered, the parser SHOULD log a warning and continue parsing the remainder of the file.
>
> **Rationale:** tree-sitter grammars may not cover all SystemVerilog constructs. A known-unsupported list helps users understand coverage gaps and prioritize grammar improvements.
>
> **Acceptance Criteria:**
> 1. The unsupported constructs list is maintained in a configuration file or module constant.
> 2. Encountering an unsupported construct logs a warning including the construct type and file location.

### 6.6 Merge Node

> **REQ-KG-310** | Priority: MUST | Phase: Phase 1
>
> **Description:** The extraction subgraph MUST include a merge node (`src/knowledge_graph/extraction/merge.py`) that receives `ExtractionResult` objects from all extractor branches and produces a single unified `ExtractionResult`. The merge node MUST: (a) deduplicate entities by alias (case-insensitive matching), (b) validate all entity types and edge types against the YAML schema, (c) merge triples that share the same subject-predicate-object (incrementing weight), (d) preserve source attribution for all entities and triples.
>
> **Rationale:** Multiple extractors will produce overlapping results. Without deduplication, the graph accumulates duplicate nodes with slightly different surface forms. Schema validation ensures only recognized types enter the graph.
>
> **Acceptance Criteria:**
> 1. Given regex extracting "AXI_Arbiter" and GLiNER extracting "axi_arbiter", the merge node produces a single entity with both forms as aliases.
> 2. A triple `(A, uses, B)` extracted by both regex and GLiNER appears once in the merged result with weight 2.
> 3. An entity with an invalid type (not in schema) is either re-classified to the fallback type or dropped, with a warning logged.
> 4. Source attribution (which extractor produced each entity/triple) is preserved in the merged result.

> **REQ-KG-311** | Priority: SHOULD | Phase: Phase 1
>
> **Description:** The merge node SHOULD assign a priority order to extractors for conflict resolution when the same entity is extracted with different types by different extractors. The default priority SHOULD be: SV parser > LLM > GLiNER > regex (highest to lowest confidence).
>
> **Rationale:** Parser-derived types are deterministic and should take precedence over probabilistic types. LLM extraction is more context-aware than GLiNER, which in turn is more targeted than regex heuristics.
>
> **Acceptance Criteria:**
> 1. Given the SV parser classifying "top" as `RTL_Module` and regex classifying "top" as `concept`, the merged entity has type `RTL_Module`.
> 2. The priority order is configurable via `kg.extractor_priority`.

> **REQ-KG-312** | Priority: MAY | Phase: Phase 1b
>
> **Description:** The merge node MAY implement embedding-based entity resolution using the existing BGE-M3 model. When enabled, entity names with cosine similarity above a configurable threshold (default: 0.85) SHOULD be merged as aliases of the same entity.
>
> **Rationale:** Alias dedup (exact + case-insensitive) misses paraphrased entity names (e.g., "clock divider" vs "clock division module"). Embedding similarity provides a targeted upgrade without requiring a full entity resolution model.
>
> **Acceptance Criteria:**
> 1. Given entity names "clock divider" and "clock division circuit" with cosine similarity 0.88 and threshold 0.85, the merge node merges them.
> 2. The similarity threshold is configurable via `kg.entity_resolution_threshold`.
> 3. This feature is disabled by default and enabled via `kg.enable_embedding_entity_resolution`.

> **REQ-KG-313** | Priority: MAY | Phase: Phase 2
>
> **Description:** The extraction subsystem MAY support Python (ast module) and Bash (tree-sitter-bash) parser extractors for deterministic structural extraction from Python and Bash source files.
>
> **Rationale:** Extends parser coverage beyond SystemVerilog to other languages used in ASIC design flows (build scripts, verification scripts, tooling).
>
> **Acceptance Criteria:**
> 1. Parser extractors for Python and Bash exist, implement the same extractor interface as the SV parser, and produce typed nodes/edges per the YAML schema.

---

## 7. Entity Descriptions

> **REQ-KG-400** | Priority: MUST | Phase: Phase 1
>
> **Description:** Each entity node in the knowledge graph MUST support an accumulated description consisting of two fields: `raw_mentions` (a list of `EntityDescription` objects) and `current_summary` (a string, initially empty). Each `EntityDescription` MUST include: `text` (the relevant sentence or passage), `source` (document path), and `chunk_id` (originating chunk identifier).
>
> **Rationale:** Entity descriptions provide textual grounding for retrieval. Without them, entity nodes carry only structural metadata (type, sources, mention_count) with no information about what the entity means or how it is used. This follows the LightRAG pattern for entity-level context.
>
> **Acceptance Criteria:**
> 1. The `Entity` dataclass (REQ-KG-205) includes `raw_mentions: list[EntityDescription]` and `current_summary: str` fields.
> 2. After extracting an entity from a chunk, the relevant sentence containing the entity is appended to `raw_mentions` with source and chunk_id.

> **REQ-KG-401** | Priority: MUST | Phase: Phase 1
>
> **Description:** When a new mention of an existing entity is extracted, the system MUST append the mention to the entity's `raw_mentions` list with source attribution. The system MUST NOT replace or overwrite existing mentions.
>
> **Rationale:** Append-only accumulation ensures no information is lost. Source attribution enables provenance tracking and retrieval-time source citation.
>
> **Acceptance Criteria:**
> 1. After processing two chunks that both mention entity "AXI_Arbiter", the entity's `raw_mentions` list has at least two entries with distinct `chunk_id` values.
> 2. No existing mention is overwritten.

> **REQ-KG-402** | Priority: MUST | Phase: Phase 1
>
> **Description:** The system MUST implement a token budget trigger for entity description summarization. When the combined token count of an entity's `raw_mentions` exceeds a configurable budget (default: 512 tokens, controlled by `kg.entity_description_token_budget`), the system MUST invoke an LLM summarization pass to condense the mentions into the `current_summary` field.
>
> **Rationale:** Unbounded mention accumulation leads to token bloat at retrieval time. A budget trigger ensures descriptions stay within a usable size while preserving information via summarization.
>
> **Acceptance Criteria:**
> 1. Given `kg.entity_description_token_budget = 512` and an entity with 600 tokens of accumulated mentions, the system triggers summarization.
> 2. After summarization, `current_summary` is non-empty.
> 3. The budget is configurable; changing it changes the trigger threshold.

> **REQ-KG-403** | Priority: MUST | Phase: Phase 1
>
> **Description:** After LLM summarization, the system MUST retain the top-K most informative mentions in `raw_mentions` (default K=5, configurable via `kg.entity_description_top_k_mentions`). Retention scoring MUST favor: (a) recency -- more recent mentions rank higher, and (b) source diversity -- mentions from distinct documents rank higher than repeated mentions from the same source.
>
> **Rationale:** Retaining top-K mentions alongside the summary provides raw evidence for debugging and retrieval grounding. Recency bias captures evolving understanding; source diversity captures breadth.
>
> **Acceptance Criteria:**
> 1. After summarization of an entity with 20 mentions, `raw_mentions` contains exactly K entries (default 5).
> 2. Given 10 mentions from "doc_A.md" and 10 from "doc_B.md", the retained mentions include at least one from each document.
> 3. K is configurable; changing it changes the number of retained mentions.

> **REQ-KG-404** | Priority: MUST | Phase: Phase 1
>
> **Description:** At retrieval time, the system MUST use `current_summary` (when non-empty) as the entity's textual representation for context grounding. When `current_summary` is empty (entity has not yet exceeded the token budget), the system MUST fall back to concatenating `raw_mentions` text.
>
> **Rationale:** The summary provides a concise, coherent description. The raw mentions fallback ensures entities are usable from the first mention, before summarization is triggered.
>
> **Acceptance Criteria:**
> 1. An entity with a non-empty `current_summary` uses the summary in retrieval context.
> 2. An entity with an empty `current_summary` uses concatenated `raw_mentions` text.
> 3. The fallback does not exceed a configurable maximum token count for retrieval context.

> **REQ-KG-405** | Priority: SHOULD | Phase: Phase 1
>
> **Description:** The `GraphStorageBackend` ABC SHOULD include an `upsert_descriptions` method that accepts a mapping of entity names to lists of new `EntityDescription` objects. The method SHOULD append new descriptions to existing ones and trigger summarization when the token budget is exceeded.
>
> **Rationale:** Centralizing description management in the backend ensures consistent behavior across all callers (Node 13, manual imports, future bulk operations).
>
> **Acceptance Criteria:**
> 1. Calling `upsert_descriptions({"AXI_Arbiter": [desc1, desc2]})` appends `desc1` and `desc2` to the entity's `raw_mentions`.
> 2. If the token budget is exceeded after appending, summarization is triggered automatically.

---

## 8. Graph Storage

> **REQ-KG-500** | Priority: MUST | Phase: Phase 1
>
> **Description:** The `GraphStorageBackend` ABC MUST define the following method contracts (with type signatures):
>
> - `add_node(name: str, type: str, source: str, aliases: list[str] = None) -> None` -- Add or update a node.
> - `add_edge(subject: str, object: str, relation: str, source: str, weight: float = 1.0) -> None` -- Add or update an edge.
> - `upsert_entities(entities: list[Entity]) -> None` -- Batch upsert entities from an `ExtractionResult`.
> - `upsert_triples(triples: list[Triple]) -> None` -- Batch upsert triples from an `ExtractionResult`.
> - `upsert_descriptions(descriptions: dict[str, list[EntityDescription]]) -> None` -- Batch upsert entity descriptions.
> - `query_neighbors(entity: str, depth: int = 1) -> list[str]` -- Return entity names reachable within `depth` hops (forward + backward).
> - `get_entity(name: str) -> Entity | None` -- Return full entity data or None.
> - `get_predecessors(entity: str) -> list[str]` -- Return entities with edges pointing to this entity.
> - `save(path: Path) -> None` -- Persist the graph to disk.
> - `load(path: Path) -> None` -- Load a graph from disk.
> - `stats() -> dict` -- Return graph statistics (node count, edge count, top entities).
>
> **Rationale:** A rich ABC with explicit method contracts enables backend-specific optimizations (e.g., Neo4j can use Cypher queries for `query_neighbors`). The method set covers all current access patterns in the monolith plus the new entity description operations.
>
> **Acceptance Criteria:**
> 1. All methods are `@abstractmethod` on the ABC.
> 2. All methods have complete type annotations and docstrings.
> 3. The method signatures cover all operations currently performed by `KnowledgeGraphBuilder` and `GraphQueryExpander`.

> **REQ-KG-501** | Priority: MUST | Phase: Phase 1
>
> **Description:** The `NetworkXBackend` MUST implement `add_node` with case-insensitive deduplication. When a node with the same name (case-insensitive) already exists, the backend MUST: (a) increment `mention_count`, (b) append new sources (without duplicates), (c) append new aliases (without duplicates). The first-seen surface form MUST be preserved as the canonical name.
>
> **Rationale:** This preserves the deduplication behavior of the current `KnowledgeGraphBuilder._resolve()` and `_upsert_node()` methods.
>
> **Acceptance Criteria:**
> 1. Adding "AXI_Arbiter" then "axi_arbiter" results in one node named "AXI_Arbiter" (first-seen form) with "axi_arbiter" as an alias.
> 2. `mention_count` is 2 after both additions.
> 3. Sources from both additions are present without duplicates.

> **REQ-KG-502** | Priority: MUST | Phase: Phase 1
>
> **Description:** The `NetworkXBackend` MUST implement `add_edge` with weight accumulation. When an edge between the same subject and object already exists, the backend MUST increment the edge weight and append new sources without duplicates. Self-edges (subject == object) MUST be silently dropped.
>
> **Rationale:** This preserves the behavior of the current `KnowledgeGraphBuilder._upsert_edge()` method.
>
> **Acceptance Criteria:**
> 1. Adding edge `(A, uses, B)` twice results in one edge with weight 2.0.
> 2. Adding edge `(A, uses, A)` is a no-op.
> 3. Sources from both additions are present without duplicates.

> **REQ-KG-503** | Priority: MUST | Phase: Phase 1
>
> **Description:** The `NetworkXBackend` MUST implement `save()` using orjson to serialize the graph in NetworkX node-link JSON format. The output MUST be compatible with the current `KnowledgeGraphBuilder.save()` format so that existing persisted graphs can be loaded by the new backend.
>
> **Rationale:** Backward compatibility with existing graph files ensures zero-downtime migration.
>
> **Acceptance Criteria:**
> 1. A graph saved by `NetworkXBackend.save()` can be loaded by `KnowledgeGraphBuilder.load()`.
> 2. A graph saved by `KnowledgeGraphBuilder.save()` can be loaded by `NetworkXBackend.load()`.
> 3. The JSON output uses `orjson.OPT_INDENT_2` for readability.

> **REQ-KG-504** | Priority: MUST | Phase: Phase 1
>
> **Description:** The `NetworkXBackend` MUST support incremental updates. Calling `upsert_entities` and `upsert_triples` MUST merge new data with the existing graph without requiring a full rebuild. Specifically: new entities are added, existing entities are updated (mention count, sources, aliases), new edges are added, existing edges have their weight incremented.
>
> **Rationale:** Re-ingesting a single document should update only the affected portion of the graph, not rebuild the entire graph from scratch.
>
> **Acceptance Criteria:**
> 1. Given a graph with 100 nodes, upserting 5 entities (3 new, 2 existing) results in a graph with 103 nodes and updated metadata on the 2 existing nodes.
> 2. The operation completes without calling `load()` or `save()` (in-memory merge).

> **REQ-KG-505** | Priority: MUST | Phase: Phase 1
>
> **Description:** The `Neo4jBackend` stub MUST implement all `GraphStorageBackend` methods. Each method MUST raise `NotImplementedError` with a descriptive message.
>
> **Rationale:** The stub proves the ABC contract is complete from day one and provides a clear extension point for full Neo4j implementation in Phase 2.
>
> **Acceptance Criteria:**
> 1. `Neo4jBackend` can be instantiated without error.
> 2. Calling any method raises `NotImplementedError`.
> 3. The error message includes "Phase 2" or "not yet implemented".

> **REQ-KG-506** | Priority: SHOULD | Phase: Phase 1
>
> **Description:** The `NetworkXBackend` SHOULD rebuild the case-insensitive index and alias index from graph data when loading a graph via `load()`. This ensures that graphs persisted before entity resolution was implemented are fully indexed.
>
> **Rationale:** Legacy graph files may not have been saved with index data. Rebuilding on load ensures correct deduplication behavior.
>
> **Acceptance Criteria:**
> 1. After loading a legacy graph, `add_node("axi_arbiter", ...)` correctly resolves to an existing node "AXI_Arbiter" if it exists.

---

## 9. Query & Retrieval

### 9.1 Entity Matching

> **REQ-KG-600** | Priority: MUST | Phase: Phase 1
>
> **Description:** The system MUST implement a spaCy-based rule-based entity matcher in `src/knowledge_graph/query/entity_matcher.py` that replaces the current substring matching in `GraphQueryExpander.find_entities_in_query()`. The matcher MUST use token-boundary matching (not substring) to prevent false positives on short entity names.
>
> **Rationale:** The current substring matching produces false positives (e.g., matching entity "AXI" inside the word "TAXIING"). Token-boundary matching ensures entities are matched only at word boundaries. spaCy provides efficient, rule-based matching with token-level precision.
>
> **Acceptance Criteria:**
> 1. The query "what is the AXI arbiter?" matches entity "AXI" and "AXI_Arbiter" (if it exists).
> 2. The query "taxiing on the runway" does NOT match entity "AXI".
> 3. Matching is case-insensitive.
> 4. The matcher uses spaCy's `Matcher` or `PhraseMatcher` with token-boundary rules.

> **REQ-KG-601** | Priority: MUST | Phase: Phase 1
>
> **Description:** The entity matcher MUST build its pattern set from the graph's node names and aliases at initialization. When the graph is updated (new nodes/aliases added), the matcher MUST be rebuilt or incrementally updated.
>
> **Rationale:** The matcher's pattern set must stay in sync with the graph to match newly ingested entities.
>
> **Acceptance Criteria:**
> 1. After adding a new entity "DDR5_Controller" to the graph and rebuilding the matcher, the query "how does the DDR5 controller work?" matches it.
> 2. Aliases are included in the pattern set.

> **REQ-KG-602** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The system MUST implement an LLM fallback entity matcher in `src/knowledge_graph/query/llm_fallback.py`. When the spaCy matcher finds zero matches on a query that contains at least 3 tokens, the system MUST invoke the LLM to identify entities from the query given the YAML schema's node type list. The LLM fallback MUST be gated behind a configurable timeout (default: 1000ms, controlled by `kg.llm_fallback_timeout_ms`). If the LLM call exceeds the timeout, the system MUST proceed without expansion.
>
> **Rationale:** spaCy rule-based matching cannot handle paraphrased entity references (e.g., "the module that handles memory arbitration" referring to entity "MemArbiter"). LLM fallback provides semantic understanding at the cost of latency. The timeout prevents the LLM from blocking the retrieval hot path.
>
> **Acceptance Criteria:**
> 1. Given a query "how does the memory arbiter prioritize requests?" and no spaCy matches, the LLM fallback identifies "MemArbiter" (or similar) from the graph.
> 2. A query with fewer than 3 tokens does not trigger the fallback.
> 3. An LLM call exceeding the timeout returns an empty match list (no error raised).
> 4. The fallback is disabled by default and enabled via `kg.enable_llm_query_fallback`.

### 9.2 Query Normalization & Expansion

> **REQ-KG-603** | Priority: MUST | Phase: Phase 1
>
> **Description:** The system MUST implement query sanitization in `src/knowledge_graph/query/sanitizer.py` that normalizes entity names before matching. Normalization MUST include: (a) case-insensitive comparison, (b) alias expansion (using the graph's alias index), (c) whitespace normalization, (d) punctuation stripping for matching purposes.
>
> **Rationale:** Users may refer to entities in forms different from the canonical graph name (e.g., "retrieval augmented generation" vs "Retrieval-Augmented Generation"). Normalization bridges the gap.
>
> **Acceptance Criteria:**
> 1. Query "rag pipeline" matches entity "RAG" if "RAG" has alias "Retrieval-Augmented Generation".
> 2. Query "axi-arbiter" matches entity "AXI_Arbiter".
> 3. Normalization does not modify the original query string passed to downstream stages.

> **REQ-KG-604** | Priority: MUST | Phase: Phase 1
>
> **Description:** The query expander MUST implement configurable fan-out control. The following parameters MUST be configurable: `kg.max_expansion_depth` (default: 1, maximum graph traversal depth), `kg.max_expansion_terms` (default: 3, maximum number of expansion terms appended to the BM25 query). Expansion MUST NOT exceed these limits.
>
> **Rationale:** Unbounded expansion adds noise to BM25 queries, degrading retrieval precision. The current implementation appends up to 3 terms (`kg_expanded_terms[:3]` in `rag_chain.py`); this makes the limit explicit and configurable.
>
> **Acceptance Criteria:**
> 1. Given `kg.max_expansion_depth = 1`, only 1-hop neighbors are considered.
> 2. Given `kg.max_expansion_terms = 3`, at most 3 terms are appended to the BM25 query.
> 3. Changing these values via configuration changes expansion behavior without code changes.

> **REQ-KG-605** | Priority: MUST | Phase: Phase 1
>
> **Description:** The query expander MUST implement the `expand(query: str, depth: int = 1) -> list[str]` method that: (a) matches entities in the query using the entity matcher (REQ-KG-600), (b) traverses the graph outward and inward from matched entities up to `depth` hops, (c) returns related entity names not already present in the query, (d) respects fan-out limits (REQ-KG-604).
>
> **Rationale:** This preserves and enhances the behavior of the current `GraphQueryExpander.expand()` method.
>
> **Acceptance Criteria:**
> 1. Given a query mentioning entity "AXI_Arbiter" with graph neighbors "AXI_Protocol" and "MemController", expansion returns `["AXI_Protocol", "MemController"]` (up to the fan-out limit).
> 2. Terms already in the query are excluded from expansion results.
> 3. Predecessor entities (nodes pointing to matched entities) are included.

> **REQ-KG-606** | Priority: SHOULD | Phase: Phase 1
>
> **Description:** The query expander SHOULD include entity descriptions in the expansion context. When returning expansion terms, the expander SHOULD also provide a `get_context_summary(entities: list[str], max_lines: int = 5) -> str` method that returns a short text summary of entity relationships, using `current_summary` or `raw_mentions` fallback per REQ-KG-404.
>
> **Rationale:** Entity descriptions provide richer context than bare entity names for retrieval augmentation.
>
> **Acceptance Criteria:**
> 1. `get_context_summary(["AXI_Arbiter"])` returns a string containing relationship information and entity description text.
> 2. The summary respects `max_lines`.

### 9.3 Retrieval Integration

> **REQ-KG-607** | Priority: MUST | Phase: Phase 1
>
> **Description:** The KG expansion in the retrieval pipeline (Stage 2 in `rag_chain.py`) MUST use `get_query_expander()` from `src/knowledge_graph/__init__.py` instead of directly constructing a `GraphQueryExpander`. The integration MUST preserve the existing behavior: expansion terms are appended to the BM25 query (not the vector query), limited to `max_expansion_terms`.
>
> **Rationale:** The lazy singleton pattern ensures the retrieval pipeline uses the same graph instance as the ingestion pipeline within the same process. Direct construction bypasses the backend abstraction.
>
> **Acceptance Criteria:**
> 1. `rag_chain.py` imports `get_query_expander` from `src.knowledge_graph`, not from `src.core.knowledge_graph`.
> 2. The retrieval pipeline produces identical expansion results as the current implementation for the same graph.
> 3. The integration point cross-references REQ-304 in `RETRIEVAL_QUERY_SPEC.md`.

> **REQ-KG-608** | Priority: MUST | Phase: Phase 1
>
> **Description:** Local retrieval mode (Phase 1) MUST retrieve expansion terms from entity neighbors and entity descriptions. Given matched entities, the expander MUST return neighbor entity names and MAY include description snippets in the expansion context.
>
> **Rationale:** Local retrieval (entity-centric) is the Phase 1 retrieval strategy. Global retrieval (community-centric) is deferred to Phase 2.
>
> **Acceptance Criteria:**
> 1. Expansion results include direct graph neighbors of matched entities.
> 2. Entity descriptions are available for matched entities via `get_context_summary()`.

> **REQ-KG-609** | Priority: MUST | Phase: Phase 2
>
> **Description:** Global retrieval mode MUST search community summaries (REQ-KG-702) in addition to local entity neighbors. When enabled, the expander MUST: (a) identify which community the matched entities belong to, (b) retrieve the community summary, (c) include community-level terms in expansion.
>
> **Rationale:** Community summaries capture high-level thematic clusters that individual entity neighbors miss. This enables answering broad questions like "what are the main design challenges?" that do not map to specific entities.
>
> **Acceptance Criteria:**
> 1. When global retrieval is enabled and a matched entity belongs to community C, the community summary for C is included in expansion context.
> 2. Global retrieval is disabled by default; enabled via `kg.enable_global_retrieval`.

---

## 10. Community Detection

> **REQ-KG-700** | Priority: MUST | Phase: Phase 2
>
> **Description:** The system MUST implement community detection using the Leiden algorithm in `src/knowledge_graph/community/detector.py`. The detector MUST: (a) accept a `GraphStorageBackend` instance, (b) compute communities on the current graph, (c) assign each entity to exactly one community, (d) store community assignments as node attributes.
>
> **Rationale:** Community detection enables global retrieval by clustering related entities into thematic groups. The Leiden algorithm is preferred over Louvain for its guaranteed well-connected communities.
>
> **Acceptance Criteria:**
> 1. Given a graph with 100+ nodes and clear cluster structure, the detector produces at least 2 communities.
> 2. Every node is assigned to exactly one community.
> 3. Community assignments are persisted across graph save/load cycles.

> **REQ-KG-701** | Priority: MUST | Phase: Phase 2
>
> **Description:** The system MUST implement community summary generation in `src/knowledge_graph/community/summarizer.py`. For each community, the summarizer MUST: (a) collect all entity descriptions within the community, (b) invoke an LLM to generate a thematic summary of the community, (c) store the summary as a community-level attribute.
>
> **Rationale:** Community summaries enable global retrieval by providing a concise representation of each cluster's theme and contents.
>
> **Acceptance Criteria:**
> 1. Each community has a non-empty summary after summarization.
> 2. The summary references key entities within the community.
> 3. Summaries are regenerated when community membership changes.

> **REQ-KG-702** | Priority: SHOULD | Phase: Phase 2
>
> **Description:** Community summaries SHOULD be refreshed when the graph is updated with new entities or triples that change community membership. The system SHOULD detect community membership changes after each ingestion batch and trigger re-summarization only for affected communities.
>
> **Rationale:** Full re-summarization on every update is expensive. Incremental refresh targets only changed communities.
>
> **Acceptance Criteria:**
> 1. Adding 10 new entities to a graph with 5 communities triggers re-summarization of only the communities whose membership changed.
> 2. Communities with no membership changes retain their existing summaries.

> **REQ-KG-703** | Priority: MUST | Phase: Phase 2
>
> **Description:** In Phase 2, `src/knowledge_graph/community/detector.py` and `src/knowledge_graph/community/summarizer.py` MUST exist as stub modules with class definitions that raise `NotImplementedError` on all public methods.
>
> **Rationale:** Stubs satisfy the package structure and provide clear extension points.
>
> **Acceptance Criteria:**
> 1. Importing the modules does not raise errors.
> 2. Calling any public method raises `NotImplementedError`.

---

## 11. Export & Visualization

> **REQ-KG-800** | Priority: MUST | Phase: Phase 1
>
> **Description:** The system MUST migrate the Obsidian export functionality from `src/core/knowledge_graph.py` `export_obsidian()` to `src/knowledge_graph/export/obsidian.py`. The migrated function MUST: (a) accept a `GraphStorageBackend` instance (not a raw NetworkX graph), (b) produce one `.md` file per entity node with `[[wikilinks]]` to neighbors, (c) include entity descriptions (`current_summary` or `raw_mentions` fallback) in each file, (d) sanitize filenames for filesystem safety.
>
> **Rationale:** Obsidian export is a user-facing feature. Migration to the new package must preserve functionality while adding entity descriptions (not present in the current export).
>
> **Acceptance Criteria:**
> 1. Given a graph with entity "AXI_Arbiter" connected to "MemController", the export produces `AXI_Arbiter.md` containing `[[MemController]]`.
> 2. Entity descriptions appear in the exported markdown.
> 3. Filenames are sanitized (no special characters that break filesystem paths).
> 4. The function signature accepts `GraphStorageBackend`, not `nx.DiGraph`.

> **REQ-KG-801** | Priority: MAY | Phase: Phase 2
>
> **Description:** The system MAY support Neo4j browser visualization as an export/visualization option when the `Neo4jBackend` is active. This requires only that the Neo4j backend stores data in a format compatible with the Neo4j browser's default visualization.
>
> **Rationale:** Neo4j's built-in browser provides interactive graph exploration without custom UI development.
>
> **Acceptance Criteria:**
> 1. When `Neo4jBackend` is fully implemented (Phase 2), data stored in Neo4j is browseable via the Neo4j browser without additional configuration.

---

## 12. Integration Points

### 12.1 Ingestion Pipeline

> **REQ-KG-900** | Priority: MUST | Phase: Phase 1
>
> **Description:** Embedding Pipeline Node 10 (`src/ingest/embedding/nodes/knowledge_graph_extraction.py`) MUST be updated to use the new `ExtractionPipeline` from `src/knowledge_graph/extraction/`. The node MUST: (a) instantiate the extraction pipeline with the configured extractors, (b) pass all chunks through the pipeline, (c) store the resulting `ExtractionResult` in pipeline state as `kg_extraction_result` (replacing the current `kg_triples` key).
>
> **Rationale:** The current Node 10 uses only the regex `EntityExtractor` directly. The new node delegates to the multi-extractor pipeline, enabling GLiNER, LLM, and SV parser extraction without changing the node's interface to the embedding workflow.
>
> **Acceptance Criteria:**
> 1. Node 10 imports from `src.knowledge_graph.extraction`, not from `src.core.knowledge_graph`.
> 2. The pipeline state key `kg_extraction_result` contains an `ExtractionResult` object (not a list of triple dicts).
> 3. The node handles extraction pipeline errors gracefully (logs error, does not crash the embedding pipeline).
> 4. Cross-reference: FR-1000--FR-1099 in `EMBEDDING_PIPELINE_SPEC.md`.

> **REQ-KG-901** | Priority: MUST | Phase: Phase 1
>
> **Description:** Embedding Pipeline Node 13 (`src/ingest/embedding/nodes/knowledge_graph_storage.py`) MUST be updated to use the `GraphStorageBackend` via `get_graph_backend()`. The node MUST: (a) retrieve the backend singleton, (b) call `upsert_entities()`, `upsert_triples()`, and `upsert_descriptions()` with data from `kg_extraction_result`, (c) NOT directly access `KnowledgeGraphBuilder` or NetworkX internals.
>
> **Rationale:** The current Node 13 calls `kg_builder.add_chunk()` directly. The new node uses the ABC interface, ensuring backend portability.
>
> **Acceptance Criteria:**
> 1. Node 13 imports `get_graph_backend` from `src.knowledge_graph`, not from `src.core.knowledge_graph`.
> 2. The node does not reference `KnowledgeGraphBuilder` or `nx.DiGraph`.
> 3. The node consumes `kg_extraction_result` from pipeline state (not raw chunks).
> 4. Cross-reference: FR-1300--FR-1399 in `EMBEDDING_PIPELINE_SPEC.md`.

> **REQ-KG-902** | Priority: MUST | Phase: Phase 1
>
> **Description:** The embedding pipeline state (`EmbeddingPipelineState`) MUST be updated to include a `kg_extraction_result` field of type `ExtractionResult | None` (replacing the current `kg_triples: list[dict]` field). The state MUST preserve backward compatibility by accepting both the old and new field formats during the migration period.
>
> **Rationale:** The pipeline state is the contract between Node 10 and Node 13. Changing the field type requires a coordinated update.
>
> **Acceptance Criteria:**
> 1. `EmbeddingPipelineState` includes `kg_extraction_result: ExtractionResult | None`.
> 2. Node 13 reads from `kg_extraction_result`; if absent, falls back to `kg_triples` for backward compatibility.

### 12.2 Retrieval Pipeline

> **REQ-KG-903** | Priority: MUST | Phase: Phase 1
>
> **Description:** Retrieval Pipeline Stage 2 in `rag_chain.py` MUST be updated to use `get_query_expander()` from `src/knowledge_graph/`. The integration MUST preserve the current behavior: (a) KG expansion is independently toggleable, (b) expansion terms are appended to the BM25 query only, (c) expansion is limited to `max_expansion_terms` (default 3), (d) expansion timing is tracked via the timing profiler.
>
> **Rationale:** The retrieval pipeline is the primary consumer of KG query expansion. The update must be transparent to downstream stages.
>
> **Acceptance Criteria:**
> 1. `rag_chain.py` imports from `src.knowledge_graph`, not `src.core.knowledge_graph`.
> 2. The `_kg_expander` attribute is obtained via `get_query_expander()`.
> 3. All timing, tracing, and budget checks in Stage 2 remain functional.
> 4. Cross-reference: REQ-304 in `RETRIEVAL_QUERY_SPEC.md`.

### 12.3 Configuration

> **REQ-KG-904** | Priority: MUST | Phase: Phase 1
>
> **Description:** The following configuration keys MUST be added to the system configuration:
>
> | Key | Type | Default | Description |
> |-----|------|---------|-------------|
> | `KG_BACKEND` | str | `"networkx"` | Backend selection: `"networkx"`, `"neo4j"`, `""`, `"none"` |
> | `KG_SCHEMA_PATH` | str | `"config/kg_schema.yaml"` | Path to the YAML schema file |
> | `kg.enable_regex_extractor` | bool | `true` | Enable regex extractor |
> | `kg.enable_gliner_extractor` | bool | `false` | Enable GLiNER extractor |
> | `kg.enable_llm_extractor` | bool | `false` | Enable LLM extractor (Phase 1b) |
> | `kg.enable_sv_parser` | bool | `false` | Enable SV parser (Phase 1b) |
> | `kg.entity_description_token_budget` | int | `512` | Token budget for description summarization |
> | `kg.entity_description_top_k_mentions` | int | `5` | Top-K mentions to retain after summarization |
> | `kg.max_expansion_depth` | int | `1` | Maximum graph traversal depth for query expansion |
> | `kg.max_expansion_terms` | int | `3` | Maximum expansion terms appended to BM25 query |
> | `kg.enable_llm_query_fallback` | bool | `false` | Enable LLM fallback for query matching (Phase 1b) |
> | `kg.llm_fallback_timeout_ms` | int | `1000` | Timeout for LLM query fallback |
> | `kg.enable_global_retrieval` | bool | `false` | Enable global (community) retrieval (Phase 2) |
> | `kg.runtime_phase` | str | `"phase_1"` | Active runtime phase for schema filtering |
>
> **Rationale:** Centralized configuration enables runtime behavior control without code changes, following the project's configuration-driven-behavior principle.
>
> **Acceptance Criteria:**
> 1. All configuration keys are accessible via the existing configuration system.
> 2. Default values are applied when keys are not explicitly set.
> 3. Invalid values for enum-like keys (`KG_BACKEND`, `kg.runtime_phase`) raise clear errors.

### 12.4 CLI/UI Parity

> **REQ-KG-905** | Priority: SHOULD | Phase: Phase 1
>
> **Description:** Any KG-related settings or commands exposed via CLI (e.g., enabling/disabling extractors, triggering graph export, viewing graph stats) SHOULD also be accessible via the web console UI, and vice versa.
>
> **Rationale:** Per the project's CLI/UI parity contract, both interfaces must reflect the same capabilities. A setting available only via CLI creates a discoverability gap for UI users.
>
> **Acceptance Criteria:**
> 1. KG configuration keys are viewable and modifiable in both CLI and UI.
> 2. Graph statistics (`stats()`) are displayable in both interfaces.
> 3. Obsidian export is triggerable from both interfaces.

---

## 13. Performance & Scalability

> **REQ-KG-1000** | Priority: MUST | Phase: Phase 1
>
> **Description:** Each extractor in the extraction pipeline MUST complete processing of a single chunk (up to 1024 tokens) within the following latency budgets:
>
> | Extractor | Max Latency (p95) |
> |-----------|-------------------|
> | Regex | 10ms |
> | GLiNER | 200ms |
> | LLM (Phase 1b) | 5000ms |
> | SV Parser (Phase 1b) | 100ms |
>
> The extraction subgraph runs extractors in parallel, so the total extraction latency per chunk MUST NOT exceed the maximum of the enabled extractors' budgets (not the sum).
>
> **Rationale:** Extraction is on the ingestion hot path. Regex and parser must be fast; LLM is expected to be slow but runs in parallel. The parallel architecture means total latency is bounded by the slowest extractor, not the sum.
>
> **Acceptance Criteria:**
> 1. Regex extraction of a 1024-token chunk completes in < 10ms (p95) in benchmarks.
> 2. With regex + GLiNER enabled (no LLM), total extraction latency per chunk is < 200ms (p95).
> 3. With all extractors enabled, total extraction latency per chunk is < 5000ms (p95), not > 5310ms (sum).

> **REQ-KG-1001** | Priority: SHOULD | Phase: Phase 1
>
> **Description:** The `NetworkXBackend` SHOULD support graphs of up to 100,000 nodes and 500,000 edges without degradation below the performance budgets in this section. The backend SHOULD log a warning when node count exceeds a configurable threshold (default: 50,000 nodes, controlled by `kg.max_nodes_warning`).
>
> **Rationale:** Typical ASIC project graphs are expected to be in the thousands-to-tens-of-thousands range. A warning at 50K provides early notice before performance degradation.
>
> **Acceptance Criteria:**
> 1. A graph with 50,000 nodes can be loaded, queried, and saved within the time budgets specified.
> 2. A warning is logged when node count exceeds `kg.max_nodes_warning`.
> 3. The system does not crash or hang at 100,000 nodes (may be slow).

> **REQ-KG-1002** | Priority: MUST | Phase: Phase 1
>
> **Description:** Query expansion (entity matching + graph traversal + term selection) MUST complete within 1000ms (p95) for the spaCy rule-based matcher path. When LLM fallback is triggered (Phase 1b), total query expansion MUST complete within the `kg.llm_fallback_timeout_ms` budget (default 1000ms) plus 100ms for the spaCy attempt.
>
> **Rationale:** Query expansion is on the retrieval hot path. The current implementation in `rag_chain.py` has a budget check that can abort if KG expansion is too slow. The 1000ms budget aligns with the existing stage timing budget.
>
> **Acceptance Criteria:**
> 1. spaCy matching + 1-hop traversal on a 10,000-node graph completes in < 1000ms (p95).
> 2. When LLM fallback is triggered and times out, total expansion time does not exceed `kg.llm_fallback_timeout_ms + 100ms`.
> 3. Cross-reference: Stage 2 timing budget in `rag_chain.py`.

> **REQ-KG-1003** | Priority: SHOULD | Phase: Phase 1
>
> **Description:** Graph serialization (`save()`) and deserialization (`load()`) SHOULD complete within 5 seconds for a graph with 50,000 nodes and 200,000 edges.
>
> **Rationale:** Graph persistence occurs at the end of ingestion and at retrieval startup. Slow serialization blocks the ingestion pipeline; slow deserialization delays retrieval readiness.
>
> **Acceptance Criteria:**
> 1. `save()` completes within 5 seconds for the specified graph size.
> 2. `load()` completes within 5 seconds for the specified graph size.

---

## 14. Testing Requirements

> **REQ-KG-1100** | Priority: MUST | Phase: Phase 1
>
> **Description:** The system MUST include contract tests for the `GraphStorageBackend` ABC that verify all abstract methods are implemented and behave correctly. Contract tests MUST be parameterized to run against all concrete backends (`NetworkXBackend`, and `Neo4jBackend` where applicable).
>
> **Rationale:** Contract tests ensure that any new backend implementation satisfies the same behavioral guarantees. This is the testing analog of the ABC pattern.
>
> **Acceptance Criteria:**
> 1. A test suite exists that instantiates each backend and calls every ABC method.
> 2. `NetworkXBackend` passes all contract tests.
> 3. `Neo4jBackend` is tested to verify it raises `NotImplementedError` for all methods.
> 4. Adding a new backend requires only adding it to the parameterized test list.

> **REQ-KG-1101** | Priority: MUST | Phase: Phase 1
>
> **Description:** The system MUST include extraction accuracy tests that verify the regex extractor produces the same output as the current `EntityExtractor` for a fixed set of test inputs. The test corpus MUST include at least: (a) CamelCase entities, (b) acronyms, (c) multi-word phrases, (d) acronym expansions, (e) relation patterns (is_a, used_for, uses, subset_of, such-as).
>
> **Rationale:** Regression tests ensure the migration from `src/core/knowledge_graph.py` does not change extraction behavior.
>
> **Acceptance Criteria:**
> 1. A test module exists with at least 10 test cases covering the categories listed above.
> 2. All tests pass with the migrated regex extractor.
> 3. The test corpus is committed alongside the test module for reproducibility.

> **REQ-KG-1102** | Priority: MUST | Phase: Phase 1
>
> **Description:** The system MUST include query expansion correctness tests that verify: (a) entity matching finds known entities in queries, (b) expansion returns graph neighbors, (c) fan-out limits are respected, (d) terms already in the query are excluded.
>
> **Rationale:** Query expansion directly affects retrieval quality. Incorrect expansion (false positives, over-expansion, under-expansion) degrades search results.
>
> **Acceptance Criteria:**
> 1. A test module exists with at least 8 test cases covering the scenarios listed above.
> 2. Tests use a known test graph (constructed in fixtures).
> 3. All tests pass with the spaCy-based matcher.

> **REQ-KG-1103** | Priority: MUST | Phase: Phase 1
>
> **Description:** The system MUST include integration tests that verify the full ingestion flow: chunks enter Node 10, pass through the extraction pipeline, produce an `ExtractionResult`, and are stored by Node 13 via the `GraphStorageBackend`. Integration tests MUST use the `NetworkXBackend` and verify that entities and triples appear in the persisted graph.
>
> **Rationale:** Integration tests verify that the KG subsystem works correctly within the embedding pipeline, not just in isolation.
>
> **Acceptance Criteria:**
> 1. An integration test processes at least 5 text chunks through the extraction and storage pipeline.
> 2. The resulting graph contains at least 3 entities and 1 triple.
> 3. Entity descriptions are present for at least one entity.
> 4. The test uses a temporary directory for graph persistence.

> **REQ-KG-1104** | Priority: SHOULD | Phase: Phase 1
>
> **Description:** The system SHOULD include schema validation tests that verify: (a) a valid schema passes validation, (b) each error condition in REQ-KG-109 is detected and produces the correct error message.
>
> **Rationale:** Schema validation is a critical startup gate. Testing all error paths prevents silent misconfigurations.
>
> **Acceptance Criteria:**
> 1. A test module exercises all 5 validation conditions from REQ-KG-109.
> 2. Each condition has at least one positive and one negative test case.

> **REQ-KG-1105** | Priority: SHOULD | Phase: Phase 1
>
> **Description:** The system SHOULD include merge node tests that verify: (a) alias-based deduplication merges entities with case-insensitive matching, (b) type conflict resolution follows extractor priority (REQ-KG-311), (c) schema-invalid types are handled per policy, (d) source attribution is preserved.
>
> **Rationale:** The merge node is the most complex component in the extraction pipeline. Thorough testing prevents deduplication bugs that corrupt the graph.
>
> **Acceptance Criteria:**
> 1. A test module exists with at least 6 test cases covering scenarios (a)--(d).
> 2. Tests use mock extraction results to exercise each merge path.

> **REQ-KG-1106** | Priority: SHOULD | Phase: Phase 1
>
> **Description:** The system SHOULD include entity description tests that verify: (a) mentions accumulate correctly, (b) summarization triggers at the token budget, (c) top-K retention selects the correct mentions, (d) retrieval-time fallback works when no summary exists.
>
> **Rationale:** Entity descriptions are a new capability with complex accumulation/summarization logic. Testing ensures correctness before retrieval consumers depend on it.
>
> **Acceptance Criteria:**
> 1. A test module exists with at least 5 test cases covering scenarios (a)--(d).
> 2. LLM summarization tests use a mock LLM response.

> **REQ-KG-1107** | Priority: SHOULD | Phase: Phase 1
>
> **Description:** The system SHOULD include backward compatibility tests that verify `src/core/knowledge_graph.py` re-exports work correctly and emit `DeprecationWarning`.
>
> **Rationale:** The migration shim must be verified to prevent import breakage for existing callers.
>
> **Acceptance Criteria:**
> 1. `from src.core.knowledge_graph import KnowledgeGraphBuilder` succeeds and returns the same class as `from src.knowledge_graph import KnowledgeGraphBuilder`.
> 2. A `DeprecationWarning` is captured by the test framework.

---

## Appendix A: YAML Schema Example

```yaml
# config/kg_schema.yaml
# Knowledge Graph entity and edge type schema for RagWeave

version: "1.0"
description: "ASIC-focused knowledge graph schema"

node_types:
  # --- Structural (parser-derived) ---
  - name: RTL_Module
    description: "A hardware module definition (module...endmodule)"
    category: structural
    phase: phase_1
    extraction_hints: "Identified by `module <name>` declarations in SystemVerilog"

  - name: Port
    description: "An input, output, or inout port on a module"
    category: structural
    phase: phase_1
    extraction_hints: "Declared in module port list or body (input, output, inout)"

  - name: Parameter
    description: "A parameterizable value in a module (parameter, localparam)"
    category: structural
    phase: phase_1

  - name: Instance
    description: "An instantiation of one module inside another"
    category: structural
    phase: phase_1

  - name: Signal
    description: "A wire, reg, or logic signal declaration"
    category: structural
    phase: phase_1

  - name: ClockDomain
    description: "A clock domain grouping signals and logic"
    category: structural
    phase: phase_1b

  - name: Interface
    description: "A SystemVerilog interface definition"
    category: structural
    phase: phase_1

  - name: Package
    description: "A SystemVerilog package definition"
    category: structural
    phase: phase_1

  - name: TypeDef
    description: "A typedef or enum type definition"
    category: structural
    phase: phase_1b

  - name: FSM_State
    description: "A state in a finite state machine"
    category: structural
    phase: phase_1b
    gliner_label: "FSM"
    extraction_hints: "Identified by enum state declarations or case statements in always blocks"

  - name: Generate
    description: "A generate block (for, if, case)"
    category: structural
    phase: phase_1b

  - name: Task_Function
    description: "A task or function definition"
    category: structural
    phase: phase_1b

  - name: SVA_Assertion
    description: "A SystemVerilog assertion (assert, assume, cover)"
    category: structural
    phase: phase_1b

  - name: UVM_Component
    description: "A UVM component (uvm_test, uvm_env, uvm_agent, etc.)"
    category: structural
    phase: phase_1b
    extraction_hints: "Classes extending uvm_* base classes"

  - name: TestCase
    description: "A verification test case"
    category: structural
    phase: phase_1b

  - name: CoverGroup
    description: "A coverage group definition"
    category: structural
    phase: phase_1b

  - name: Sequence
    description: "A sequence definition for assertions or coverage"
    category: structural
    phase: phase_1b

  - name: Constraint
    description: "A constraint block in a class"
    category: structural
    phase: phase_1b

  - name: Pipeline_Stage
    description: "A pipeline stage in a datapath design"
    category: structural
    phase: phase_1b

  - name: FIFO_Buffer
    description: "A FIFO or buffer component"
    category: structural
    phase: phase_1b

  - name: Arbiter
    description: "An arbitration component"
    category: structural
    phase: phase_1b

  - name: Decoder_Encoder
    description: "A decoder or encoder component"
    category: structural
    phase: phase_1b

  - name: RegisterFile
    description: "A register file or register bank"
    category: structural
    phase: phase_1b

  - name: MemoryMap
    description: "A memory map or address map definition"
    category: structural
    phase: phase_1b

  # --- Semantic (NER/LLM-derived) ---
  - name: Specification
    description: "A formal specification or requirements document"
    category: semantic
    phase: phase_1

  - name: DesignDecision
    description: "A documented design choice or architectural decision"
    category: semantic
    phase: phase_1

  - name: Requirement
    description: "A functional or non-functional requirement"
    category: semantic
    phase: phase_1

  - name: TradeOff
    description: "A documented trade-off between competing design goals"
    category: semantic
    phase: phase_1

  - name: KnownIssue
    description: "A documented known issue, bug, or limitation"
    category: semantic
    phase: phase_1

  - name: Assumption
    description: "A documented assumption underlying a design or decision"
    category: semantic
    phase: phase_1

  - name: Person
    description: "An individual (engineer, reviewer, author)"
    category: semantic
    phase: phase_1

  - name: Team
    description: "A team or organizational unit"
    category: semantic
    phase: phase_1

  - name: Project
    description: "A project or program"
    category: semantic
    phase: phase_1

  - name: Review
    description: "A design review, code review, or sign-off event"
    category: semantic
    phase: phase_1

  - name: Protocol
    description: "A communication protocol (AXI, APB, SPI, I2C, etc.)"
    category: semantic
    phase: phase_1

  - name: IP_Block
    description: "A reusable IP block or macro"
    category: semantic
    phase: phase_1

  - name: EDA_Tool
    description: "An EDA tool (Synopsys DC, Cadence Innovus, etc.)"
    category: semantic
    phase: phase_1

  - name: Script
    description: "An automation script (TCL, Python, shell)"
    category: semantic
    phase: phase_1

  - name: TimingConstraint
    description: "A timing constraint (clock period, setup/hold, multicycle)"
    category: semantic
    phase: phase_1

  - name: AreaConstraint
    description: "An area constraint or utilization target"
    category: semantic
    phase: phase_1

  - name: PowerConstraint
    description: "A power constraint or power domain definition"
    category: semantic
    phase: phase_1

edge_types:
  # --- Structural ---
  - name: instantiates
    description: "Module A instantiates module B"
    category: structural
    phase: phase_1b
    source_types: [RTL_Module, Instance]
    target_types: [RTL_Module, IP_Block]

  - name: connects_to
    description: "Signal or port A connects to signal or port B"
    category: structural
    phase: phase_1b
    source_types: [Port, Signal]
    target_types: [Port, Signal, Instance]

  - name: depends_on
    description: "Component A depends on component B"
    category: structural
    phase: phase_1

  - name: parameterized_by
    description: "Module or instance is parameterized by a parameter"
    category: structural
    phase: phase_1b
    source_types: [RTL_Module, Instance]
    target_types: [Parameter]

  - name: belongs_to_clock_domain
    description: "Signal or module belongs to a clock domain"
    category: structural
    phase: phase_1b
    source_types: [Signal, RTL_Module]
    target_types: [ClockDomain]

  - name: implements_interface
    description: "Module implements an interface"
    category: structural
    phase: phase_1b
    source_types: [RTL_Module]
    target_types: [Interface]

  - name: contains
    description: "Parent entity contains child entity"
    category: structural
    phase: phase_1

  - name: transitions_to
    description: "FSM state A transitions to state B"
    category: structural
    phase: phase_1b
    source_types: [FSM_State]
    target_types: [FSM_State]

  - name: drives
    description: "Signal or port drives another signal or port"
    category: structural
    phase: phase_1b
    source_types: [Signal, Port]
    target_types: [Signal, Port]

  - name: reads
    description: "Component reads from a signal or register"
    category: structural
    phase: phase_1b
    source_types: [RTL_Module, Task_Function]
    target_types: [Signal, RegisterFile]

  # --- Semantic ---
  - name: specified_by
    description: "Component or feature is specified by a specification"
    category: semantic
    phase: phase_1

  - name: verified_by
    description: "Component is verified by a test case or assertion"
    category: semantic
    phase: phase_1

  - name: authored_by
    description: "Document or component was authored by a person"
    category: semantic
    phase: phase_1

  - name: reviewed_by
    description: "Document or component was reviewed by a person"
    category: semantic
    phase: phase_1

  - name: blocks
    description: "Issue or dependency blocks another item"
    category: semantic
    phase: phase_1

  - name: supersedes
    description: "Document or version supersedes a previous version"
    category: semantic
    phase: phase_1

  - name: constrained_by
    description: "Component is constrained by a timing/area/power constraint"
    category: semantic
    phase: phase_1

  - name: trades_off_against
    description: "Design decision trades off one quality against another"
    category: semantic
    phase: phase_1

  - name: assumes
    description: "Design or decision assumes a precondition"
    category: semantic
    phase: phase_1

  - name: complies_with
    description: "Component complies with a protocol or standard"
    category: semantic
    phase: phase_1

  - name: relates_to
    description: "Generic relation when no specific edge type applies"
    category: semantic
    phase: phase_1

  - name: design_decision_for
    description: "A design decision applies to a specific component or feature"
    category: semantic
    phase: phase_1
```

---

## Appendix B: Requirement Traceability Matrix

| Req ID | Phase | Priority | Section | Description (short) |
|--------|-------|----------|---------|---------------------|
| REQ-KG-100 | 1 | MUST | 4 | YAML schema file as single source of truth |
| REQ-KG-101 | 1 | MUST | 4 | Node type required fields |
| REQ-KG-102 | 1 | MUST | 4 | 24 structural node types |
| REQ-KG-103 | 1 | MUST | 4 | 17 semantic node types |
| REQ-KG-104 | 1 | MUST | 4 | Edge type required fields |
| REQ-KG-105 | 1 | MUST | 4 | 10 structural edge types |
| REQ-KG-106 | 1 | MUST | 4 | 12 semantic edge types |
| REQ-KG-107 | 1 | MUST | 4 | Phase tags and runtime activation |
| REQ-KG-108 | 1 | MUST | 4 | GLiNER label derivation from YAML |
| REQ-KG-109 | 1 | MUST | 4 | Schema validation rules |
| REQ-KG-110 | 1 | SHOULD | 4 | Extraction hints in schema |
| REQ-KG-111 | 1 | SHOULD | 4 | Edge type constraints |
| REQ-KG-200 | 1 | MUST | 5 | Package structure |
| REQ-KG-201 | 1 | MUST | 5 | GraphStorageBackend ABC |
| REQ-KG-202 | 1 | MUST | 5 | NetworkXBackend implementation |
| REQ-KG-203 | 1 | MUST | 5 | Neo4jBackend stub |
| REQ-KG-204 | 1 | MUST | 5 | Public API with lazy singleton |
| REQ-KG-205 | 1 | MUST | 5 | Typed data contracts (schemas.py) |
| REQ-KG-206 | 1 | MUST | 5 | Configuration types (types.py) |
| REQ-KG-207 | 1 | MUST | 5 | Backward compatibility shim |
| REQ-KG-208 | 1 | SHOULD | 5 | Shared utility helpers |
| REQ-KG-300 | 1 | MUST | 6 | Multi-extractor LangGraph subgraph |
| REQ-KG-301 | 1 | MUST | 6 | EntityExtractor protocol |
| REQ-KG-302 | 1 | MUST | 6 | Extractor toggle configuration |
| REQ-KG-303 | 1 | MUST | 6 | Regex extractor migration |
| REQ-KG-304 | 1 | SHOULD | 6 | Regex type validation against schema |
| REQ-KG-305 | 1 | MUST | 6 | GLiNER extractor migration |
| REQ-KG-306 | 1b | MUST | 6 | LLM extractor implementation |
| REQ-KG-307 | 1b | SHOULD | 6 | Configurable LLM prompt template |
| REQ-KG-308 | 1b | MUST | 6 | SV parser extractor |
| REQ-KG-309 | 1b | SHOULD | 6 | Known unsupported SV constructs |
| REQ-KG-310 | 1 | MUST | 6 | Merge node (dedup + validation) |
| REQ-KG-311 | 1 | SHOULD | 6 | Extractor priority for conflicts |
| REQ-KG-312 | 1b | MAY | 6 | Embedding-based entity resolution |
| REQ-KG-313 | 2 | MAY | 6 | Python/Bash parser extractors |
| REQ-KG-400 | 1 | MUST | 7 | Entity description data model |
| REQ-KG-401 | 1 | MUST | 7 | Append-only mention accumulation |
| REQ-KG-402 | 1 | MUST | 7 | Token budget summarization trigger |
| REQ-KG-403 | 1 | MUST | 7 | Top-K retention after summarization |
| REQ-KG-404 | 1 | MUST | 7 | Retrieval-time description usage |
| REQ-KG-405 | 1 | SHOULD | 7 | upsert_descriptions backend method |
| REQ-KG-500 | 1 | MUST | 8 | ABC method contracts |
| REQ-KG-501 | 1 | MUST | 8 | NetworkX case-insensitive dedup |
| REQ-KG-502 | 1 | MUST | 8 | NetworkX edge weight accumulation |
| REQ-KG-503 | 1 | MUST | 8 | NetworkX serialization compatibility |
| REQ-KG-504 | 1 | MUST | 8 | Incremental update semantics |
| REQ-KG-505 | 1 | MUST | 8 | Neo4j stub methods |
| REQ-KG-506 | 1 | SHOULD | 8 | Index rebuild on load |
| REQ-KG-600 | 1 | MUST | 9 | spaCy rule-based entity matcher |
| REQ-KG-601 | 1 | MUST | 9 | Matcher pattern sync with graph |
| REQ-KG-602 | 1b | MUST | 9 | LLM fallback entity matcher |
| REQ-KG-603 | 1 | MUST | 9 | Query sanitization/normalization |
| REQ-KG-604 | 1 | MUST | 9 | Fan-out control configuration |
| REQ-KG-605 | 1 | MUST | 9 | Query expand method |
| REQ-KG-606 | 1 | SHOULD | 9 | Entity descriptions in expansion |
| REQ-KG-607 | 1 | MUST | 9 | Retrieval pipeline integration |
| REQ-KG-608 | 1 | MUST | 9 | Local retrieval mode |
| REQ-KG-609 | 2 | MUST | 9 | Global retrieval mode |
| REQ-KG-700 | 2 | MUST | 10 | Leiden community detection |
| REQ-KG-701 | 2 | MUST | 10 | Community summary generation |
| REQ-KG-702 | 2 | SHOULD | 10 | Incremental summary refresh |
| REQ-KG-703 | 2 | MUST | 10 | Community module stubs |
| REQ-KG-704 | 2 | MUST | D.1 | igraph + leidenalg dependency and resolution config |
| REQ-KG-705 | 2 | MUST | D.1 | Directed-to-undirected conversion for Leiden |
| REQ-KG-706 | 2 | MUST | D.1 | Community ID storage as node attribute |
| REQ-KG-707 | 2 | SHOULD | D.1 | Minimum community size threshold |
| REQ-KG-708 | 2 | SHOULD | D.1 | Graceful fallback when igraph/leidenalg unavailable |
| REQ-KG-709 | 2 | MUST | D.2 | Input token budget for community summarization |
| REQ-KG-710 | 2 | MUST | D.2 | Output token budget for community summarization |
| REQ-KG-711 | 2 | SHOULD | D.2 | Parallel summarization via ThreadPoolExecutor |
| REQ-KG-712 | 2 | MUST | D.2 | CommunitySummary dataclass |
| REQ-KG-713 | 2 | MUST | D.3 | CommunityDiff dataclass |
| REQ-KG-714 | 2 | SHOULD | D.3 | Selective re-summarization |
| REQ-KG-715 | 2 | MUST | D.4 | Sidecar JSON persistence for community data |
| REQ-KG-716 | 2 | MUST | D.4 | Automatic sidecar load on initialization |
| REQ-KG-717 | 2 | MUST | D.5 | CommunityDetector.is_ready lifecycle contract |
| REQ-KG-718 | 2 | MUST | D.5 | enable_global_retrieval config flag |
| REQ-KG-719 | 2 | MUST | D.5 | Ordering — local terms first, community fill |
| REQ-KG-720 | 2 | MUST | D.6 | Full Neo4j GraphStorageBackend implementation |
| REQ-KG-721 | 2 | MUST | D.6 | MERGE-based entity resolution |
| REQ-KG-722 | 2 | MUST | D.6 | Index creation on initialization |
| REQ-KG-723 | 2 | SHOULD | D.6 | UNWIND-based bulk operations |
| REQ-KG-724 | 2 | MUST | D.6 | save/load export/import semantics |
| REQ-KG-725 | 2 | SHOULD | D.6 | Community storage in Neo4j |
| REQ-KG-726 | 2 | MAY | D.7 | Python ast-based extractor |
| REQ-KG-727 | 2 | MAY | D.7 | Bash tree-sitter-based extractor |
| REQ-KG-728 | 2 | MAY | D.7 | Phase 2 node types in YAML schema |
| REQ-KG-729 | 2 | MUST | D.8 | KGConfig Phase 2 field extensions |
| REQ-KG-730 | 3 | MUST | E.1 | `remove_by_source()` ABC method and RemovalStats |
| REQ-KG-731 | 3 | MUST | E.1 | NetworkXBackend `remove_by_source()` with index rebuild |
| REQ-KG-732 | 3 | MUST | E.1 | Neo4jBackend `remove_by_source()` atomic Cypher |
| REQ-KG-733 | 3 | MUST | E.1 | Delete-before-upsert wiring in storage node |
| REQ-KG-734 | 3 | MUST | E.1 | Pyverilog batch `connects_to` cleanup on incremental update |
| REQ-KG-735 | 3 | MUST | E.2 | SVConnectivityAnalyzer class and `connects_to` triples |
| REQ-KG-736 | 3 | MUST | E.2 | `.f` filelist parsing (standard format) |
| REQ-KG-737 | 3 | MUST | E.2 | Post-ingestion batch step wiring |
| REQ-KG-738 | 3 | MUST | E.2 | Top module auto-detection heuristic |
| REQ-KG-739 | 3 | SHOULD | E.2 | Graceful pyverilog fallback on failure |
| REQ-KG-740 | 3 | MUST | E.2 | KGConfig `sv_filelist` and `sv_top_module` fields |
| REQ-KG-741 | 3 | MUST | E.3 | `export_html()` Sigma.js single-file visualization |
| REQ-KG-742 | 3 | MUST | E.3 | Node coloring by type or community |
| REQ-KG-743 | 3 | MUST | E.3 | Edge styling by predicate type |
| REQ-KG-744 | 3 | SHOULD | E.3 | Community-based grouping and hierarchical zoom |
| REQ-KG-745 | 3 | MUST | E.3 | Search, hover tooltips, zoom/pan interactivity |
| REQ-KG-746 | 3 | MUST | E.4 | EntityResolver orchestrator with MergeReport |
| REQ-KG-747 | 3 | MUST | E.4 | EmbeddingResolver type-constrained matching |
| REQ-KG-748 | 3 | MUST | E.4 | AliasResolver YAML alias table |
| REQ-KG-749 | 3 | MUST | E.4 | `merge_entities()` backend method |
| REQ-KG-750 | 3 | MUST | E.4 | Entity resolution KGConfig fields |
| REQ-KG-751 | 3 | MUST | E.5 | Hierarchical Leiden multi-level partition |
| REQ-KG-752 | 3 | MUST | E.5 | Per-level community summaries with `level` field |
| REQ-KG-753 | 3 | SHOULD | E.5 | Query expander level selection by specificity |
| REQ-KG-754 | 3 | MUST | E.5 | Sidecar JSON hierarchical format (backward-compatible) |
| REQ-KG-755 | 3 | MUST | E.6 | pyproject.toml default + optional dependency groups |
| REQ-KG-756 | 3 | SHOULD | E.2 | Multi-hop query expansion for connects_to edges |
| REQ-KG-800 | 1 | MUST | 11 | Obsidian export migration |
| REQ-KG-801 | 2 | MAY | 11 | Neo4j browser visualization |
| REQ-KG-900 | 1 | MUST | 12 | Node 10 extraction update |
| REQ-KG-901 | 1 | MUST | 12 | Node 13 storage update |
| REQ-KG-902 | 1 | MUST | 12 | Pipeline state schema update |
| REQ-KG-903 | 1 | MUST | 12 | Retrieval Stage 2 update |
| REQ-KG-904 | 1 | MUST | 12 | Configuration keys |
| REQ-KG-905 | 1 | SHOULD | 12 | CLI/UI parity |
| REQ-KG-1000 | 1 | MUST | 13 | Extraction latency budgets |
| REQ-KG-1001 | 1 | SHOULD | 13 | Graph size limits and warnings |
| REQ-KG-1002 | 1 | MUST | 13 | Query expansion time budget |
| REQ-KG-1003 | 1 | SHOULD | 13 | Serialization time budget |
| REQ-KG-1100 | 1 | MUST | 14 | ABC contract tests |
| REQ-KG-1101 | 1 | MUST | 14 | Extraction accuracy tests |
| REQ-KG-1102 | 1 | MUST | 14 | Query expansion correctness tests |
| REQ-KG-1103 | 1 | MUST | 14 | Integration tests |
| REQ-KG-1104 | 1 | SHOULD | 14 | Schema validation tests |
| REQ-KG-1105 | 1 | SHOULD | 14 | Merge node tests |
| REQ-KG-1106 | 1 | SHOULD | 14 | Entity description tests |
| REQ-KG-1107 | 1 | SHOULD | 14 | Backward compatibility tests |

---

## Appendix C: Phase 1b Detailed Requirements

This appendix provides detailed specifications for the three Phase 1b deliverables: the LLM Entity/Relation Extractor, the SystemVerilog Parser Extractor, and the LLM Query Fallback. These requirements refine and decompose the high-level Phase 1b stubs in sections 6.4, 6.5, and 9.1 (REQ-KG-306 through REQ-KG-312 and REQ-KG-602) into implementation-level acceptance criteria.

**Companion documents:**

- `2026-04-08-kg-phase1b-sketch.md` — Approved design sketch with approach evaluations and technical decisions.
- `src/knowledge_graph/common/schemas.py` — `Entity`, `Triple`, `ExtractionResult`, `EntityDescription` data contracts.
- `config/kg_schema.yaml` — YAML schema (41 node types, 22 edge types) serving as extraction prompt context and runtime validator.

**ID Range:** REQ-KG-1b-100 through REQ-KG-1b-399.

---

### C.1 LLM Entity/Relation Extractor

These requirements detail the LLM-based extraction pipeline referenced by REQ-KG-306 and REQ-KG-307. The extractor lives at `src/knowledge_graph/extraction/llm_extractor.py` and returns `ExtractionResult` objects compatible with the merge node (REQ-KG-310).

---

> **REQ-KG-1b-100** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The LLM extractor MUST use LiteLLM for all LLM calls via the existing `LLMProvider` class (`src/platform/llm/provider.py`). The extractor MUST accept an optional `LLMProvider` instance via constructor injection and fall back to the `get_llm_provider()` singleton when none is provided. No separate LLM client or direct API calls are permitted.
>
> **Rationale:** The project standardizes LLM access through `LLMProvider`, which manages router configuration, retry logic, and cost tracking. Bypassing it would create a parallel LLM integration path that diverges from project conventions and loses observability.
>
> **Acceptance Criteria:**
> 1. The `LLMEntityExtractor.__init__()` constructor accepts an optional `llm_provider` parameter.
> 2. When no provider is passed, the extractor calls `get_llm_provider()` to obtain the singleton.
> 3. All LLM calls route through `LLMProvider.json_completion()` -- no direct `litellm.completion()` or `openai.ChatCompletion` calls exist in the module.
> 4. The extractor functions correctly with a mock `LLMProvider` in unit tests.

---

> **REQ-KG-1b-101** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The LLM extractor MUST inject the active YAML schema types into the extraction prompt. Specifically, the prompt MUST include: (a) all node types whose `phase` tag is active for the current runtime phase (filtered via `SchemaDefinition.active_node_types(runtime_phase)`), with their descriptions and extraction hints, and (b) all edge types with their descriptions and source/target constraints. Schema content MUST be rendered into the prompt template via the `{schema_types}`, `{schema_edges}`, and `{extraction_hints}` substitution variables.
>
> **Rationale:** Schema-guided prompting constrains the LLM's output to valid types, reducing hallucinated entity categories and improving downstream validation pass rates. Including extraction hints provides domain-specific guidance that improves recall for specialized types (e.g., `RTL_Module` identified by "`module <name>`" declarations).
>
> **Acceptance Criteria:**
> 1. Given a schema with `RTL_Module` (phase_1) and `Generate` (phase_1b), both appear in the prompt when runtime phase is `phase_1b`.
> 2. A type with `phase: phase_2` does NOT appear in the prompt when runtime phase is `phase_1b`.
> 3. Each rendered node type includes its `description` and `extraction_hints` fields from the YAML schema.
> 4. Each rendered edge type includes its `description` and any `source_types`/`target_types` constraints.
> 5. The rendered schema block fits within 4K tokens for the current 41-node/22-edge schema.

---

> **REQ-KG-1b-102** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The LLM extractor MUST use JSON structured output mode for all extraction calls. The call MUST use `LLMProvider.json_completion()`, which sets `response_format: {"type": "json_object"}`. The expected output schema is a JSON object with two arrays: `entities` (each with `name`, `type`, `description` fields) and `triples` (each with `subject`, `predicate`, `object` fields).
>
> **Rationale:** Structured output mode forces the LLM to produce valid JSON, reducing parse failures. A defined output schema enables deterministic post-processing and validation.
>
> **Acceptance Criteria:**
> 1. Every LLM call uses `json_completion()`, not `completion()` or `chat()`.
> 2. The system message specifies the expected JSON output structure.
> 3. A valid LLM response parses into a Python dict with `entities` and `triples` keys.
> 4. Each entity dict contains at minimum `name` (str), `type` (str), and `description` (str).
> 5. Each triple dict contains at minimum `subject` (str), `predicate` (str), and `object` (str).

---

> **REQ-KG-1b-103** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The LLM extractor MUST validate all extracted entities and triples against the `SchemaDefinition`. Entity types MUST be checked via `SchemaDefinition.is_valid_node_type(type, runtime_phase)`. Triple predicates MUST be checked via `SchemaDefinition.is_valid_edge_type()`. Entities with invalid types MUST be reclassified to the `"concept"` fallback type with a logged warning. Triples with invalid predicates MUST be dropped with a logged warning.
>
> **Rationale:** LLMs hallucinate entity types not present in the schema (e.g., inventing "HardwareBlock" when the schema defines "RTL_Module"). Post-extraction validation enforces schema conformance and prevents invalid types from entering the graph.
>
> **Acceptance Criteria:**
> 1. An entity extracted with type `"HardwareBlock"` (not in schema) is reclassified to `"concept"` and a warning is logged.
> 2. An entity extracted with type `"RTL_Module"` (valid in schema) retains its type.
> 3. A triple with predicate `"relates_to"` (not in schema) is dropped and a warning is logged.
> 4. A triple with predicate `"instantiates"` (valid in schema) is retained.
> 5. Validation failures do not raise exceptions -- they are handled inline and logged.

---

> **REQ-KG-1b-104** | Priority: MUST | Phase: Phase 1b
>
> **Description:** On a malformed JSON response (parsing failure), the LLM extractor MUST retry exactly once with a corrective follow-up message ("fix your JSON") appended to the conversation. If the retry also fails to produce valid JSON, the extractor MUST return an empty `ExtractionResult` (no entities, no triples, no descriptions) rather than raising an exception.
>
> **Rationale:** LLMs occasionally produce malformed JSON even in structured output mode (truncated responses, encoding issues). A single retry recovers most transient failures. Returning empty on persistent failure ensures the extraction pipeline continues processing remaining chunks.
>
> **Acceptance Criteria:**
> 1. Given a first response that is invalid JSON, the extractor sends a second request with a corrective message.
> 2. Given two consecutive invalid JSON responses, the extractor returns `ExtractionResult(entities=[], triples=[], descriptions={})`.
> 3. No exception propagates to the caller on JSON parse failure.
> 4. Both the initial failure and the retry failure are logged at WARNING level.
> 5. The maximum retry count (1) is configurable via `KGConfig` for future adjustment.

---

> **REQ-KG-1b-105** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The LLM extractor MUST extract entity descriptions -- a textual explanation of what each entity is or does -- as part of the extraction output. Each entity in the LLM response MUST include a `description` field. These descriptions MUST be converted to `EntityDescription` objects and included in the `ExtractionResult.descriptions` dict, keyed by canonical entity name.
>
> **Rationale:** Entity descriptions provide the raw material for the entity description accumulation pipeline (REQ-KG-400 through REQ-KG-403). LLM-generated descriptions are often more informative than raw text spans because the LLM can synthesize context from the surrounding chunk.
>
> **Acceptance Criteria:**
> 1. Given a chunk mentioning "AXI_Arbiter", the extraction result includes a description entry for "AXI_Arbiter" in `ExtractionResult.descriptions`.
> 2. The `EntityDescription.text` field contains the LLM-generated description text (not an empty string).
> 3. The `EntityDescription.source` field is populated with the source document path passed to `extract()`.
> 4. Entities with empty or missing `description` fields in the LLM response are still included in the entity list but omitted from the descriptions dict.

---

> **REQ-KG-1b-106** | Priority: SHOULD | Phase: Phase 1b
>
> **Description:** The LLM extractor SHOULD support a configurable prompt template. The default template SHOULD be embedded as a module-level constant string in `llm_extractor.py`. An override path SHOULD be configurable via `KGConfig.llm_extraction_prompt_template` (a file path). The template SHOULD be rendered using `str.format_map()` with the variables `{schema_types}`, `{schema_edges}`, `{extraction_hints}`, and `{chunk_text}`. Template variable validation SHOULD occur at init time, raising `ValueError` if required variables are missing from the template.
>
> **Rationale:** Prompt engineering iteration should not require code changes. Domain-specific deployments may need customized extraction prompts. Init-time validation prevents silent failures from typos in template variable names.
>
> **Acceptance Criteria:**
> 1. With no override configured, the extractor uses the default embedded template.
> 2. With `KGConfig.llm_extraction_prompt_template` set to a valid file path, the extractor loads and uses that template.
> 3. A template missing the `{chunk_text}` variable raises `ValueError` at init time.
> 4. All four substitution variables (`{schema_types}`, `{schema_edges}`, `{extraction_hints}`, `{chunk_text}`) are replaced in the rendered prompt.

---

> **REQ-KG-1b-107** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The LLM extractor MUST set `extractor_source="llm"` on all `Entity` and `Triple` objects it produces. For `Entity` objects, the value MUST be appended to the `extractor_source` list. For `Triple` objects, the value MUST be set on the `extractor_source` string field.
>
> **Rationale:** Source attribution enables the merge node (REQ-KG-310) to apply extractor priority rules (REQ-KG-311) and allows downstream analysis to distinguish LLM-extracted data from parser-extracted or regex-extracted data.
>
> **Acceptance Criteria:**
> 1. Every `Entity` in the `ExtractionResult` has `"llm"` in its `extractor_source` list.
> 2. Every `Triple` in the `ExtractionResult` has `extractor_source == "llm"`.
> 3. The merge node can distinguish LLM-sourced entities from other sources by checking the `extractor_source` field.

---

> **REQ-KG-1b-108** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The LLM extractor MUST handle rate limiting from the LLM provider gracefully. When the provider returns a rate-limit error (HTTP 429 or equivalent), the extractor MUST apply exponential backoff (starting at 1 second, doubling per retry, maximum 3 retries for rate limits specifically) before re-attempting the call. The extractor MUST NOT crash or propagate unhandled exceptions on rate-limit responses. After exhausting rate-limit retries, the extractor MUST return an empty `ExtractionResult`.
>
> **Rationale:** LLM API rate limits are expected during batch extraction of large document corpora. Crashing on rate limits would halt the entire ingestion pipeline. Backoff allows the pipeline to self-regulate without operator intervention.
>
> **Acceptance Criteria:**
> 1. Given a mock provider that returns HTTP 429 twice then succeeds, the extractor produces a valid `ExtractionResult` after backoff.
> 2. Given a mock provider that returns HTTP 429 four consecutive times, the extractor returns an empty `ExtractionResult` (no crash).
> 3. Backoff durations increase exponentially (1s, 2s, 4s for the three retries).
> 4. Rate-limit retries are logged at WARNING level with the retry count.

---

> **REQ-KG-1b-109** | Priority: SHOULD | Phase: Phase 1b
>
> **Description:** The LLM extractor SHOULD log extraction statistics after each `extract()` call. Statistics SHOULD include: (a) number of entities extracted, (b) number of triples extracted, (c) number of entities reclassified due to invalid type, (d) number of triples dropped due to invalid predicate, (e) LLM call latency in milliseconds, (f) LLM response token count (if available from `LLMResponse`). Statistics SHOULD be logged at INFO level.
>
> **Rationale:** Extraction statistics enable operators to monitor extraction quality and cost without enabling debug logging. They also support regression detection during prompt template changes.
>
> **Acceptance Criteria:**
> 1. After a successful extraction, the log contains entity count, triple count, and latency.
> 2. After an extraction with reclassified entities, the log contains the reclassification count.
> 3. Statistics are logged at INFO level (visible in default logging configuration).

---

### C.2 SystemVerilog Parser Extractor

These requirements detail the tree-sitter-based SV parser referenced by REQ-KG-308 and REQ-KG-309. The extractor lives at `src/knowledge_graph/extraction/parser_extractor.py` and returns `ExtractionResult` objects compatible with the merge node (REQ-KG-310).

---

> **REQ-KG-1b-200** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The SV parser extractor MUST use tree-sitter (version >= 0.22) with the `tree-sitter-verilog` grammar for parsing SystemVerilog files. The parser MUST be created once per `SVParserExtractor` instance and reused across calls. The language object MUST be loaded via `tree_sitter_verilog.language()` (new API). The extractor MUST support `.sv`, `.v`, and `.svh` file extensions.
>
> **Rationale:** tree-sitter provides incremental, error-tolerant parsing with a mature SystemVerilog grammar. Reusing the parser instance avoids repeated grammar loading overhead. The new 0.22+ API is the supported path forward for tree-sitter Python bindings.
>
> **Acceptance Criteria:**
> 1. The extractor initializes a tree-sitter parser with the SystemVerilog grammar without error.
> 2. Parsing a valid `.sv` file produces a concrete syntax tree (CST) with no ERROR nodes.
> 3. The parser instance is reused across multiple `extract()` / `extract_file()` calls (not recreated each time).
> 4. Files with extensions `.sv`, `.v`, and `.svh` are accepted; other extensions cause `extract_file()` to return an empty `ExtractionResult`.

---

> **REQ-KG-1b-201** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The SV parser extractor MUST extract the following structural entities from SystemVerilog source: modules (`module_declaration` -> `RTL_Module`), ports (`port_declaration` / `ansi_port_declaration` -> `Port`), parameters (`parameter_declaration` / `local_parameter_declaration` -> `Parameter`), module instances (`module_instantiation` -> `Instance`), signals (`net_declaration` / `data_declaration` -> `Signal`), interfaces (`interface_declaration` -> `Interface`), and packages (`package_declaration` -> `Package`). Each entity MUST be mapped to its corresponding YAML schema type.
>
> **Rationale:** These seven constructs represent the fundamental hardware module hierarchy that the knowledge graph must capture for structural queries. They correspond to the `phase_1` structural types in the YAML schema.
>
> **Acceptance Criteria:**
> 1. Given a `.sv` file containing `module top(input clk, output data); wire bus; sub_mod u0(...); endmodule`, the extractor produces entities: `top` (RTL_Module), `clk` (Port), `data` (Port), `bus` (Signal), `u0` (Instance).
> 2. Given a file containing `interface axi_if; ... endinterface`, the extractor produces an `axi_if` (Interface) entity.
> 3. Given a file containing `package utils_pkg; ... endpackage`, the extractor produces a `utils_pkg` (Package) entity.
> 4. All entity types match the corresponding type names in `config/kg_schema.yaml`.

---

> **REQ-KG-1b-202** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The SV parser extractor MUST derive structural relationships from the parsed AST: (a) `contains` -- parent module/interface/package to child entities (ports, parameters, signals, instances), (b) `instantiates` -- instance entity to the module type being instantiated, (c) `connects_to` -- port connections in module instantiations to the connected signal/port, (d) `parameterized_by` -- instance with parameter overrides to the overridden parameter, (e) `depends_on` -- package import dependencies between modules and packages. Each relationship MUST be emitted as a `Triple` object with the correct predicate.
>
> **Rationale:** Structural relationships are the primary value of deterministic parsing. They enable graph queries like "what modules does top instantiate?" and "which signals connect to port clk?" that LLM extraction cannot reliably produce for large designs.
>
> **Acceptance Criteria:**
> 1. Given `module top; sub_mod u0(...); endmodule`, a triple `("top", "contains", "u0")` and a triple `("u0", "instantiates", "sub_mod")` are produced.
> 2. Given `sub_mod u0(.clk(sys_clk))`, a triple `("sys_clk", "connects_to", "clk")` is produced (or equivalent directionality).
> 3. Given `module top #(.WIDTH(8))`, a triple relating the instance to the `WIDTH` parameter is produced.
> 4. All predicate strings match valid edge types in `config/kg_schema.yaml`.

---

> **REQ-KG-1b-203** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The SV parser extractor MUST map tree-sitter AST node types to YAML schema entity types using an explicit mapping table defined as a module-level constant. The mapping MUST cover all seven mandatory entity types from REQ-KG-1b-201. Unmapped AST node types MUST be skipped (not extracted), with a DEBUG-level log message.
>
> **Rationale:** An explicit mapping table makes the AST-to-schema relationship auditable and maintainable. It prevents accidental extraction of AST nodes that have no schema representation and enables future extension by adding entries to the table.
>
> **Acceptance Criteria:**
> 1. The mapping table is a visible constant (e.g., `AST_TO_SCHEMA_MAP`) in the module source.
> 2. The table maps at minimum: `module_declaration` -> `RTL_Module`, `port_declaration` -> `Port`, `parameter_declaration` -> `Parameter`, `module_instantiation` -> `Instance`, `net_declaration` -> `Signal`, `interface_declaration` -> `Interface`, `package_declaration` -> `Package`.
> 3. An AST node type not in the mapping (e.g., `comment`) is skipped and logged at DEBUG level.

---

> **REQ-KG-1b-204** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The SV parser extractor MUST handle tree-sitter syntax errors gracefully. When the parsed CST contains `ERROR` or `MISSING` nodes, the extractor MUST: (a) skip the ERROR subtree entirely, (b) continue extracting from sibling and parent nodes, (c) log a WARNING with the file path and the byte range of the error node. The extractor MUST NOT raise exceptions or return empty results solely because of parse errors -- partial results from parseable portions MUST be returned.
>
> **Rationale:** Real-world SystemVerilog files frequently contain constructs the grammar cannot parse (macros, vendor extensions, partial files). Skipping error regions and extracting what is parseable maximizes the value of deterministic extraction.
>
> **Acceptance Criteria:**
> 1. Given a `.sv` file with a syntax error on line 50, entities from lines 1-49 and 51+ are still extracted.
> 2. A WARNING log entry identifies the file path and byte range of the error.
> 3. The `ExtractionResult` contains entities from parseable portions (not empty).
> 4. No exception propagates to the caller due to parse errors.

---

> **REQ-KG-1b-205** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The SV parser extractor MUST implement an `extract_file(file_path: str) -> ExtractionResult` method that reads a file from disk and extracts entities and triples. The method MUST: (a) validate the file extension (`.sv`, `.v`, `.svh`), (b) read the file contents, (c) delegate to the standard `extract(text, source)` method with `source` set to the file path, (d) return an empty `ExtractionResult` for non-SV file extensions without error. This method supplements the standard `extract(text, source)` interface that all extractors share.
>
> **Rationale:** File-level extraction is the natural interface for the SV parser since SystemVerilog files are parsed as complete compilation units, unlike document chunks processed by the LLM extractor. The `extract_file()` method provides a convenient entry point while preserving the shared `extract()` interface for pipeline compatibility.
>
> **Acceptance Criteria:**
> 1. `extract_file("design/top.sv")` reads the file and returns an `ExtractionResult` with entities.
> 2. `extract_file("readme.md")` returns an empty `ExtractionResult` (no error, no warning).
> 3. `extract_file("missing.sv")` raises `FileNotFoundError` (standard Python behavior).
> 4. The `source` field on all produced entities and triples contains the file path.

---

> **REQ-KG-1b-206** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The SV parser extractor MUST set `extractor_source="sv_parser"` on all `Entity` and `Triple` objects it produces. For `Entity` objects, the value MUST be appended to the `extractor_source` list. For `Triple` objects, the value MUST be set on the `extractor_source` string field.
>
> **Rationale:** Source attribution enables the merge node to apply the SV parser's highest-priority status in conflict resolution (REQ-KG-311: SV parser > LLM > GLiNER > regex) and allows provenance tracking in the stored graph.
>
> **Acceptance Criteria:**
> 1. Every `Entity` in the `ExtractionResult` has `"sv_parser"` in its `extractor_source` list.
> 2. Every `Triple` in the `ExtractionResult` has `extractor_source == "sv_parser"`.
> 3. The merge node recognizes `"sv_parser"` as the highest-priority source.

---

> **REQ-KG-1b-207** | Priority: SHOULD | Phase: Phase 1b
>
> **Description:** The SV parser extractor SHOULD extract additional structural entities beyond the mandatory seven: (a) FSM states from `always` blocks with `case` statements containing symbolic state names, mapped to a `State` or equivalent schema type, (b) generate blocks from `generate_region` nodes, mapped to `Generate` (phase_1b schema type), (c) task and function declarations from `task_declaration` and `function_declaration` nodes, mapped to `Task_Function` (phase_1b schema type). These SHOULD be added to the AST-to-schema mapping table.
>
> **Rationale:** FSM states, generate blocks, and tasks/functions provide richer structural context for design understanding. They are lower priority than the seven core constructs but add significant value for RTL-heavy corpora.
>
> **Acceptance Criteria:**
> 1. Given an `always` block with `case(state) IDLE: ... ACTIVE: ... endcase`, the extractor produces `IDLE` and `ACTIVE` entities of the appropriate state type.
> 2. Given a `generate for ... endgenerate` block, the extractor produces a `Generate` entity.
> 3. Given `task automatic reset_bus; ... endtask`, the extractor produces a `Task_Function` entity.

---

> **REQ-KG-1b-208** | Priority: SHOULD | Phase: Phase 1b
>
> **Description:** The SV parser extractor SHOULD detect potential clock domain crossings (CDC) when clock signals are identifiable. When an `always` block is sensitive to one clock (e.g., `posedge clk_a`) and a signal assigned within that block is read in another `always` block sensitive to a different clock (e.g., `posedge clk_b`), the extractor SHOULD emit a `ClockDomain` entity for each clock domain and a `crosses_domain` (or equivalent) triple linking the signal to both domains.
>
> **Rationale:** CDC detection is a high-value structural analysis for ASIC design verification. Even approximate CDC identification from source-level analysis provides useful graph context for design review queries.
>
> **Acceptance Criteria:**
> 1. Given two `always @(posedge clk_a)` and `always @(posedge clk_b)` blocks sharing a signal, the extractor produces two `ClockDomain` entities and a crossing triple.
> 2. When only one clock domain exists, no crossing triples are produced.
> 3. False positives are acceptable at this stage (SHOULD-level requirement); the feature documents known limitations.

---

> **REQ-KG-1b-209** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The SV parser extractor MUST populate the `file_path` property on all produced `Entity` objects for source traceability. For entities produced via `extract_file()`, `file_path` MUST be set to the input file path. For entities produced via `extract(text, source)`, `file_path` MUST be set to the `source` parameter value. The `file_path` MUST be stored in the `Entity` properties (via the `sources` list) so that downstream consumers can trace any entity back to its originating file.
>
> **Rationale:** File-level traceability is essential for design navigation queries ("which file defines module X?") and for incremental re-extraction when source files change.
>
> **Acceptance Criteria:**
> 1. Every `Entity` produced by `extract_file("design/top.sv")` has `"design/top.sv"` in its `sources` list.
> 2. Every `Entity` produced by `extract(text, source="design/top.sv")` has `"design/top.sv"` in its `sources` list.
> 3. The source path is preserved through the merge node into the stored graph.

---

### C.3 LLM Query Fallback

These requirements detail the LLM-based entity matching fallback referenced by REQ-KG-602. The fallback enhances the existing `match_with_llm_fallback()` method in `src/knowledge_graph/query/entity_matcher.py`.

---

> **REQ-KG-1b-300** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The system MUST enhance the `match_with_llm_fallback()` method in the `EntityMatcher` class with an actual LLM call. When the spaCy/substring matcher returns zero results, and the query meets the minimum token threshold, and the feature is enabled via configuration, the method MUST invoke the LLM to identify which known entities the query refers to. The LLM call MUST use the existing `LLMProvider.json_completion()` interface.
>
> **Rationale:** The current `match_with_llm_fallback()` is a stub that returns an empty list. Implementing the actual LLM call enables semantic entity resolution for paraphrased queries that rule-based matching cannot handle (e.g., "the module that handles memory arbitration" -> "MemArbiter").
>
> **Acceptance Criteria:**
> 1. Given a query "how does the memory arbiter prioritize requests?" with no spaCy matches, the method calls the LLM and returns matching entity names.
> 2. The LLM call uses `LLMProvider.json_completion()`.
> 3. The method no longer returns an unconditional empty list when the stub conditions are met.
> 4. On any LLM error (timeout, parse error, provider error), the method returns an empty list without raising.

---

> **REQ-KG-1b-301** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The LLM fallback prompt MUST send the user query and all known entity names grouped by type to the LLM. The prompt format MUST be: system message defining the entity resolver role, user message containing the query text and entity list formatted as `TYPE: name1, name2, ...` groups. Only entity names and types are sent -- descriptions and aliases are excluded from the prompt to minimize token usage. If the entity list exceeds a configurable token budget (default: 4096 tokens via `KGConfig.llm_fallback_token_budget`), entities MUST be truncated to the highest-mention-count entities first.
>
> **Rationale:** Grouping by type gives the LLM categorical context that improves resolution accuracy. Excluding descriptions keeps prompt size manageable. Truncation by mention count prioritizes the most referenced (and therefore most likely queried) entities.
>
> **Acceptance Criteria:**
> 1. The prompt contains the query text verbatim.
> 2. Entity names are grouped by type (e.g., `RTL_Module: top, sub_mod, axi_arb`).
> 3. Entity descriptions are NOT included in the prompt.
> 4. With 5000 tokens of entity names and a 4096-token budget, the list is truncated to fit.
> 5. Truncation prioritizes entities with higher `mention_count`.

---

> **REQ-KG-1b-302** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The LLM fallback MUST return only canonical entity names that actually exist in the graph. The LLM response MUST be a JSON array of entity name strings. Each returned name MUST be validated against the `EntityMatcher`'s known entity set. Names returned by the LLM that do not exist in the graph MUST be silently discarded (logged at DEBUG level).
>
> **Rationale:** The LLM may hallucinate entity names that sound plausible but do not exist in the graph. Validating against the known entity set prevents phantom entities from appearing in query expansion results.
>
> **Acceptance Criteria:**
> 1. Given the LLM returns `["MemArbiter", "NonExistentModule"]` and only `MemArbiter` exists in the graph, the method returns `["MemArbiter"]`.
> 2. Given the LLM returns `["FakeEntity"]` and it does not exist, the method returns `[]`.
> 3. Discarded names are logged at DEBUG level.
> 4. The returned names use the canonical casing from the graph (not the LLM's casing).

---

> **REQ-KG-1b-303** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The LLM query fallback MUST be gated by the configuration flag `KGConfig.enable_llm_query_fallback` (or equivalent key `kg.enable_llm_query_fallback`). The default value MUST be `False` (disabled). When disabled, `match_with_llm_fallback()` MUST behave identically to `match()` -- returning only spaCy/substring results with no LLM call.
>
> **Rationale:** LLM calls on the query path add latency (typically 500-2000ms). The fallback should be opt-in so that deployments prioritizing query speed are not penalized. Disabled-by-default also prevents unexpected LLM costs in environments where cost control is critical.
>
> **Acceptance Criteria:**
> 1. With `enable_llm_query_fallback=False` (default), no LLM call is made regardless of spaCy match results.
> 2. With `enable_llm_query_fallback=True` and zero spaCy matches, the LLM fallback is invoked.
> 3. With `enable_llm_query_fallback=True` and non-zero spaCy matches, the LLM fallback is NOT invoked (spaCy results are sufficient).

---

> **REQ-KG-1b-304** | Priority: MUST | Phase: Phase 1b
>
> **Description:** The LLM query fallback MUST have a configurable timeout controlled by `KGConfig.llm_fallback_timeout_ms` (default: 1000ms). The timeout MUST be passed to the `LLMProvider.json_completion()` call (converted to seconds). If the LLM call exceeds the timeout, the fallback MUST return an empty list without raising an exception. Timeout events MUST be logged at WARNING level.
>
> **Rationale:** The query fallback is on the retrieval hot path. An unbounded LLM call could make the entire query pipeline unresponsive. A configurable timeout allows operators to tune the latency-quality tradeoff for their deployment.
>
> **Acceptance Criteria:**
> 1. With `llm_fallback_timeout_ms=1000`, the LLM call times out after 1 second.
> 2. A timed-out call returns `[]` (empty list), not an exception.
> 3. A timeout event is logged at WARNING level with the configured timeout value.
> 4. The timeout value is configurable and respected at runtime (changing it changes the actual timeout).

---

> **REQ-KG-1b-305** | Priority: SHOULD | Phase: Phase 1b
>
> **Description:** The LLM query fallback SHOULD skip the LLM call entirely for very short queries containing fewer than 3 tokens (whitespace-split). Such queries are unlikely to benefit from semantic matching and would waste LLM resources. The method SHOULD return the spaCy/substring results (even if empty) without invoking the LLM.
>
> **Rationale:** Queries like "AXI" or "clk reset" are best served by exact/substring matching. Sending them to the LLM adds latency without meaningful benefit, since the query text provides insufficient context for semantic resolution.
>
> **Acceptance Criteria:**
> 1. A query "AXI" (1 token) does not trigger the LLM fallback even if spaCy returns no matches and the fallback is enabled.
> 2. A query "clk reset" (2 tokens) does not trigger the LLM fallback.
> 3. A query "how does the arbiter work" (5 tokens) does trigger the LLM fallback when spaCy returns no matches and the fallback is enabled.
> 4. Token count is determined by whitespace splitting (`len(query.split())`).

---

## Appendix D: Phase 2 Detailed Requirements

This appendix provides detailed specifications for all Phase 2 deliverables: community detection, community summarization, incremental refresh, community persistence, global retrieval, the full Neo4j backend, optional Python/Bash parsers, and KGConfig extensions. These requirements refine and decompose the high-level Phase 2 stubs in sections 6.6, 8.2, 9.3, and 10 (REQ-KG-313, REQ-KG-505, REQ-KG-609, REQ-KG-700 through REQ-KG-703) into implementation-level acceptance criteria.

**Companion documents:**

- `2026-04-08-kg-phase2-sketch.md` — Approved design sketch with approach evaluations and technical decisions.
- `src/knowledge_graph/common/schemas.py` — `Entity`, `Triple`, `ExtractionResult`, `EntityDescription` data contracts.
- `src/knowledge_graph/community/` — Community detection and summarization package (stubs delivered in Phase 1).
- `config/kg_schema.yaml` — YAML schema serving as extraction prompt context and runtime validator.

**ID Range:** REQ-KG-704 through REQ-KG-729.

---

### D.1 Community Detection

These requirements detail the Leiden community detection implementation referenced by REQ-KG-700. The detector lives at `src/knowledge_graph/community/detector.py` and replaces the Phase 1 stubs (REQ-KG-703).

---

> **REQ-KG-704** | Priority: MUST | Phase: Phase 2
>
> **Description:** The community detector MUST use `python-igraph` and `leidenalg` as its detection backend. The `CommunityDetector` MUST accept a `community_resolution: float` parameter (from `KGConfig`, default 1.0) that controls the Leiden resolution parameter. Higher values produce more, smaller communities. The default partition type MUST be `RBConfigurationVertexPartition` (modularity with resolution). The system SHOULD allow config override to `CPMVertexPartition` for constant Potts model partitioning.
>
> **Rationale:** `leidenalg` is the canonical Leiden implementation by the algorithm's authors (Traag et al.), providing direct control over resolution and partition quality metrics. igraph conversion is a one-time O(V+E) operation, negligible compared to the algorithm itself.
>
> **Acceptance Criteria:**
> 1. `CommunityDetector` imports `igraph` and `leidenalg` for detection.
> 2. `KGConfig.community_resolution` is passed to `leidenalg.find_partition()` as the `resolution_parameter`.
> 3. With `community_resolution=1.0`, the detector produces standard modularity-based communities.
> 4. With `community_resolution=2.0` on the same graph, the detector produces more communities than at 1.0.
> 5. The partition type defaults to `RBConfigurationVertexPartition` and is overridable via config.

---

> **REQ-KG-705** | Priority: MUST | Phase: Phase 2
>
> **Description:** Before running Leiden, the detector MUST convert the directed graph (`DiGraph`) to an undirected graph. The conversion MUST preserve the maximum edge weight when collapsing bidirectional edges (i.e., if edge A->B has weight 3 and B->A has weight 5, the undirected edge A-B has weight 5).
>
> **Rationale:** The Leiden algorithm operates on undirected graphs. Directed-to-undirected conversion with max-weight preservation is standard practice (GraphRAG, LightRAG) and ensures that the strongest relationship signal is retained.
>
> **Acceptance Criteria:**
> 1. Given a DiGraph with edges A->B (weight 3) and B->A (weight 5), the converted undirected graph has edge A-B with weight 5.
> 2. Single-direction edges are preserved with their original weight.
> 3. The conversion is an internal implementation detail; the original DiGraph is not modified.

---

> **REQ-KG-706** | Priority: MUST | Phase: Phase 2
>
> **Description:** After Leiden detection, the detector MUST store `community_id: int` as a node attribute on each entity in the graph backend. Community metadata (member count, summary text) MUST be stored on the `CommunityDetector` instance, not as individual node attributes, to avoid polluting the entity data model.
>
> **Rationale:** Storing `community_id` as a node attribute ensures community assignments survive graph save/load cycles via existing serialization paths. Keeping metadata on the detector keeps the entity data model clean and avoids schema changes to the backend.
>
> **Acceptance Criteria:**
> 1. After `detect()`, every node in the backend has a `community_id` integer attribute.
> 2. `backend.get_entity(name)` returns an entity whose metadata includes `community_id`.
> 3. Community metadata (summaries, member lists) is accessible via `CommunityDetector` methods, not from entity attributes.
> 4. Community assignments persist across `backend.save()` / `backend.load()` cycles.

---

> **REQ-KG-707** | Priority: SHOULD | Phase: Phase 2
>
> **Description:** Communities with fewer than `community_min_size` entities (default 3, configurable via `KGConfig`) SHOULD be merged into a "miscellaneous" bucket with `community_id = -1`. The miscellaneous bucket SHOULD NOT receive LLM summarization.
>
> **Rationale:** Trivially small clusters (1-2 entities) do not benefit from thematic summarization. Merging them into a known bucket avoids wasting LLM calls and simplifies downstream logic.
>
> **Acceptance Criteria:**
> 1. With `community_min_size=3`, a community containing 2 entities is reassigned to `community_id = -1`.
> 2. Entities in community -1 are excluded from community summarization.
> 3. The `community_min_size` threshold is configurable via `KGConfig.community_min_size`.
> 4. A community with exactly `community_min_size` entities is NOT reassigned to -1.

---

> **REQ-KG-708** | Priority: SHOULD | Phase: Phase 2
>
> **Description:** When `igraph` or `leidenalg` is not installed, the `CommunityDetector` SHOULD fail gracefully. On initialization, if the imports fail, the detector SHOULD log a WARNING and set `is_ready` to False permanently. All public methods (`detect()`, `get_community_for_entity()`, etc.) SHOULD return empty/None results rather than raising exceptions.
>
> **Rationale:** `igraph` and `leidenalg` require C extensions that may fail to build on some platforms. The KG subsystem must remain functional (local retrieval, extraction, storage) even when community detection is unavailable.
>
> **Acceptance Criteria:**
> 1. When `leidenalg` is not importable, `CommunityDetector.__init__` completes without error and logs a WARNING.
> 2. `detector.is_ready` returns False when dependencies are missing.
> 3. `detector.detect()` returns an empty dict when dependencies are missing.
> 4. `detector.get_community_for_entity(name)` returns None when dependencies are missing.
> 5. The rest of the KG subsystem (extraction, storage, local retrieval) is unaffected.

---

### D.2 Community Summarization

These requirements detail the LLM-based community summarization referenced by REQ-KG-701. The summarizer lives at `src/knowledge_graph/community/summarizer.py`.

---

> **REQ-KG-709** | Priority: MUST | Phase: Phase 2
>
> **Description:** The `CommunitySummarizer` MUST enforce an input token budget (`KGConfig.community_summary_input_max_tokens`, default 4096) on the concatenated entity descriptions sent to the LLM as prompt context. When the total token count of entity descriptions for a community exceeds this budget, the summarizer MUST truncate by removing descriptions of entities with the fewest raw mentions first (lowest `mention_count`), until the concatenated text fits within the budget.
>
> **Rationale:** Large communities can produce prompt contexts that exceed LLM context windows. The input budget prevents prompt overflow while retaining the most-mentioned (most important) entity descriptions.
>
> **Acceptance Criteria:**
> 1. Given a community whose concatenated descriptions total 6000 tokens with `community_summary_input_max_tokens=4096`, the prompt sent to the LLM contains at most 4096 tokens of description context.
> 2. Entities with lower mention counts are truncated first.
> 3. The budget is configurable via `KGConfig.community_summary_input_max_tokens`.
> 4. A community whose descriptions fit within the budget is sent in full (no unnecessary truncation).

---

> **REQ-KG-710** | Priority: MUST | Phase: Phase 2
>
> **Description:** The `CommunitySummarizer` MUST pass `KGConfig.community_summary_output_max_tokens` (default 512) as the `max_tokens` parameter to the LLM call, bounding the generated summary length. The system prompt MUST instruct the LLM to produce a 2-4 sentence thematic summary identifying the community's primary topic, key entities, and relationships.
>
> **Rationale:** Concise summaries are more useful for query expansion than verbose ones. Bounding output tokens ensures consistent summary lengths regardless of input size.
>
> **Acceptance Criteria:**
> 1. The LLM call includes `max_tokens=512` (or the configured value).
> 2. Generated summaries are 2-4 sentences and reference key entities from the community.
> 3. The output budget is configurable via `KGConfig.community_summary_output_max_tokens`.
> 4. The LLM temperature is set to `KGConfig.community_summary_temperature` (default 0.2).

---

> **REQ-KG-711** | Priority: SHOULD | Phase: Phase 2
>
> **Description:** The `CommunitySummarizer.summarize_all()` method SHOULD execute community summarization calls in parallel using `concurrent.futures.ThreadPoolExecutor` with `max_workers` controlled by `KGConfig.community_summary_max_workers` (default 4). Each community summarization is an independent I/O-bound LLM call.
>
> **Rationale:** Parallel execution reduces total summarization time proportionally to the number of workers. LLM calls are I/O-bound, making threads appropriate (no GIL contention).
>
> **Acceptance Criteria:**
> 1. `summarize_all()` uses `ThreadPoolExecutor` for parallel LLM calls.
> 2. The `max_workers` parameter is configurable via `KGConfig.community_summary_max_workers`.
> 3. With 10 communities and `max_workers=4`, summarization completes faster than sequential execution.
> 4. A failure in one community's summarization does not prevent others from completing. Failed communities are logged at WARNING level and excluded from results.

---

> **REQ-KG-712** | Priority: MUST | Phase: Phase 2
>
> **Description:** The system MUST define a `CommunitySummary` dataclass in `src/knowledge_graph/community/schemas.py` with the following fields: `community_id: int`, `summary_text: str`, `member_count: int`, `member_names: List[str]`, `generated_at: str` (ISO 8601 timestamp). The `CommunityDetector` MUST store summaries as `Dict[int, CommunitySummary]` accessible via a public property or method.
>
> **Rationale:** A typed dataclass provides a stable contract for community summary data, ensuring consistent serialization and downstream access patterns.
>
> **Acceptance Criteria:**
> 1. `CommunitySummary` is importable from `src/knowledge_graph/community/schemas.py`.
> 2. All five fields (`community_id`, `summary_text`, `member_count`, `member_names`, `generated_at`) are present and typed.
> 3. `generated_at` is a valid ISO 8601 timestamp string.
> 4. `CommunityDetector` exposes summaries via a `get_summary(community_id)` method or `summaries` property.

---

### D.3 Incremental Refresh

These requirements detail the incremental community refresh mechanism referenced by REQ-KG-702.

---

> **REQ-KG-713** | Priority: MUST | Phase: Phase 2
>
> **Description:** The system MUST define a `CommunityDiff` dataclass in `src/knowledge_graph/community/schemas.py` with the following fields: `new_communities: Set[int]` (communities that did not exist in the previous detection), `removed_communities: Set[int]` (communities that no longer exist), `changed_communities: Set[int]` (communities whose member set changed), `unchanged_communities: Set[int]` (communities with identical membership). The `CommunityDetector.detect()` method MUST return a `CommunityDiff` on every invocation after the first.
>
> **Rationale:** The diff enables selective re-summarization, avoiding expensive LLM calls for communities that have not changed.
>
> **Acceptance Criteria:**
> 1. `CommunityDiff` is importable from `src/knowledge_graph/community/schemas.py`.
> 2. All four fields are present and typed as `Set[int]`.
> 3. On first invocation (no previous assignments), all communities appear in `new_communities`.
> 4. When re-running `detect()` after adding 5 entities that join an existing community, that community appears in `changed_communities` and others in `unchanged_communities`.
> 5. `new_communities | removed_communities | changed_communities | unchanged_communities` covers all community IDs across both old and new partitions.

---

> **REQ-KG-714** | Priority: SHOULD | Phase: Phase 2
>
> **Description:** The `CommunitySummarizer` SHOULD provide a `refresh(diff: CommunityDiff, communities: Dict[int, List[str]], backend: GraphStorageBackend) -> Dict[int, CommunitySummary]` method that re-summarizes only communities in `diff.new_communities | diff.changed_communities`. Summaries for `diff.unchanged_communities` SHOULD be carried forward from the previous run. Summaries for `diff.removed_communities` SHOULD be discarded.
>
> **Rationale:** Full re-summarization on every update is expensive. Incremental refresh targets only changed communities, reducing LLM calls proportionally to the change set.
>
> **Acceptance Criteria:**
> 1. Given a diff with 2 changed and 8 unchanged communities, `refresh()` makes exactly 2 LLM calls.
> 2. Summaries for unchanged communities are identical to the previous run (same `summary_text`, same `generated_at`).
> 3. Summaries for removed communities are no longer present in the detector's summary store.
> 4. New community summaries have a `generated_at` timestamp from the current run.

---

### D.4 Community Persistence

These requirements define how community data survives process restarts.

---

> **REQ-KG-715** | Priority: MUST | Phase: Phase 2
>
> **Description:** Community summaries and previous community assignments MUST be persisted to a sidecar JSON file at `<graph_path>.communities.json` alongside the main graph file. The sidecar MUST contain: (a) a serialized dict of `CommunitySummary` objects (keyed by community_id), (b) the `_previous_assignments` dict mapping entity names to community IDs. The sidecar MUST be written atomically (write to temp file, then rename) to prevent corruption on crash.
>
> **Rationale:** Community summaries are expensive to regenerate (LLM calls). Persisting them ensures that process restarts do not trigger unnecessary re-summarization. The sidecar approach avoids modifying the main graph serialization format.
>
> **Acceptance Criteria:**
> 1. After `detect()` + `summarize_all()`, a file `<graph_path>.communities.json` exists.
> 2. The JSON file contains both summaries and previous assignments.
> 3. The file is written atomically (temp file + rename pattern).
> 4. The JSON file is valid JSON and parseable by `json.loads()`.
> 5. Deleting the sidecar file does not prevent the system from functioning (treated as first run).

---

> **REQ-KG-716** | Priority: MUST | Phase: Phase 2
>
> **Description:** On `CommunityDetector.__init__`, if the sidecar JSON file (`<graph_path>.communities.json`) exists, the detector MUST load summaries and previous assignments from it. This restores the detector to a state equivalent to having run `detect()` + `summarize_all()` in a previous session. If the sidecar file is missing or corrupt, the detector MUST treat it as a first run (empty summaries, no previous assignments) and log a WARNING.
>
> **Rationale:** Automatic sidecar loading ensures continuity across process restarts without requiring explicit user action.
>
> **Acceptance Criteria:**
> 1. Given a valid sidecar file from a previous run, `CommunityDetector.__init__` restores summaries and previous assignments.
> 2. After restoration, `detector.is_ready` returns True (if igraph/leidenalg are available).
> 3. A subsequent `detect()` call produces a meaningful `CommunityDiff` against the restored previous assignments.
> 4. A corrupt sidecar file (invalid JSON) triggers a WARNING log and is treated as a first run.
> 5. A missing sidecar file is treated as a first run (no warning, this is the normal initial state).

---

### D.5 Global Retrieval

These requirements detail the community-aware query expansion referenced by REQ-KG-609. Modifications target `src/knowledge_graph/query/expander.py`.

---

> **REQ-KG-717** | Priority: MUST | Phase: Phase 2
>
> **Description:** The `CommunityDetector` MUST expose an `is_ready: bool` property that returns True only when both community detection and summarization have completed at least once (either from a live run or from sidecar restoration). The `GraphQueryExpander` MUST check `detector.is_ready` before attempting community expansion. If the detector is injected but not ready, the expander MUST log a WARNING and fall back to local-only expansion.
>
> **Rationale:** Community expansion depends on both detection results (community assignments) and summarization results (summary text). Attempting expansion before both are available would produce empty or incorrect results. The warning ensures operators notice the misconfiguration without a hard failure.
>
> **Acceptance Criteria:**
> 1. A freshly constructed `CommunityDetector` (no sidecar, no `detect()` called) has `is_ready == False`.
> 2. After `detect()` but before `summarize_all()`, `is_ready == False`.
> 3. After both `detect()` and `summarize_all()`, `is_ready == True`.
> 4. After sidecar restoration with valid summaries and assignments, `is_ready == True`.
> 5. When `is_ready == False`, the expander logs a WARNING and returns local-only expansion results.

---

> **REQ-KG-718** | Priority: MUST | Phase: Phase 2
>
> **Description:** Global retrieval MUST be controlled by the `KGConfig.enable_global_retrieval: bool` flag (default False). When False, the `GraphQueryExpander` MUST perform local-only expansion regardless of whether a `CommunityDetector` is injected. When True and a ready detector is available, the expander MUST include community-level terms in expansion results.
>
> **Rationale:** Global retrieval adds latency and depends on community detection being configured. Defaulting to disabled ensures backward compatibility and opt-in activation.
>
> **Acceptance Criteria:**
> 1. With `enable_global_retrieval=False`, expansion results contain only local neighbour terms (no community terms), even if a ready detector is injected.
> 2. With `enable_global_retrieval=True` and a ready detector, expansion results include community summary terms.
> 3. With `enable_global_retrieval=True` but no detector injected, the expander performs local-only expansion without error.
> 4. The flag is configurable via `KGConfig.enable_global_retrieval` and the `KG_ENABLE_GLOBAL_RETRIEVAL` environment variable.

---

> **REQ-KG-719** | Priority: MUST | Phase: Phase 2
>
> **Description:** When global retrieval is active, the `GraphQueryExpander` MUST order expansion terms so that local expansion terms (direct entity neighbours) appear first and community-derived terms fill remaining slots up to `max_terms`. Local terms MUST NOT be displaced by community terms. If local terms alone fill `max_terms`, no community terms are included.
>
> **Rationale:** Local expansion terms have higher direct relevance to the query. Community terms provide thematic context but are less specific. Prioritizing local terms ensures retrieval quality does not degrade when community detection is enabled.
>
> **Acceptance Criteria:**
> 1. Given `max_terms=10`, 8 local terms, and 5 community terms, the result contains the 8 local terms followed by 2 community terms (total 10).
> 2. Given `max_terms=5` and 7 local terms, the result contains 5 local terms and 0 community terms.
> 3. Given `max_terms=10` and 3 local terms, the result contains the 3 local terms followed by up to 7 community terms.
> 4. The ordering is deterministic for the same graph state and query.

---

### D.6 Neo4j Backend

These requirements detail the full Neo4j backend implementation referenced by REQ-KG-505. The backend lives at `src/knowledge_graph/backends/neo4j_backend.py` and replaces the Phase 1 stub.

---

> **REQ-KG-720** | Priority: MUST | Phase: Phase 2
>
> **Description:** The `Neo4jBackend` MUST provide a full implementation of all `GraphStorageBackend` abstract methods using the official `neo4j` Python sync driver. The constructor MUST accept `uri: str`, `auth: Tuple[str, str]`, and `database: str` parameters (sourced from `KGConfig`). The backend MUST use driver-managed connection pooling (default pool size).
>
> **Rationale:** Neo4j provides persistent server-side graph storage suitable for production deployments where in-memory NetworkX is insufficient. The official sync driver aligns with the synchronous pipeline architecture.
>
> **Acceptance Criteria:**
> 1. `Neo4jBackend` implements all abstract methods of `GraphStorageBackend` without raising `NotImplementedError`.
> 2. The backend connects to a running Neo4j instance using the configured URI and credentials.
> 3. All CRUD operations (add/get/query entities, add/get triples, neighbours) function correctly against Neo4j 5.x.
> 4. Connection pooling is managed by the driver (no manual pool implementation).
> 5. The backend is selectable via configuration (e.g., `kg.backend_type = "neo4j"`).

---

> **REQ-KG-721** | Priority: MUST | Phase: Phase 2
>
> **Description:** The `Neo4jBackend` MUST perform entity resolution server-side using Cypher `MERGE` with case-insensitive matching via `toLower()`. When upserting an entity whose lowercased name matches an existing node, the backend MUST update the existing node's properties rather than creating a duplicate. Alias lists MUST be stored as a node property (list type).
>
> **Rationale:** Server-side entity resolution via MERGE is idempotent and avoids race conditions in concurrent access. Case-insensitive matching mirrors the NetworkX backend's dedup behavior for consistency.
>
> **Acceptance Criteria:**
> 1. Upserting entity "AXI_Arbiter" followed by "axi_arbiter" results in one node (not two).
> 2. The surviving node retains the most recently upserted properties.
> 3. Aliases for an entity are stored as a list property on the node.
> 4. `MERGE` is used (not `CREATE`) for all entity upsert operations.

---

> **REQ-KG-722** | Priority: MUST | Phase: Phase 2
>
> **Description:** On initialization, the `Neo4jBackend` MUST create database indexes using `CREATE INDEX IF NOT EXISTS` for: (a) entity name (text index for exact and prefix lookup), (b) entity type, (c) `community_id` node property. The backend SHOULD also create a full-text index on entity names for fuzzy matching support.
>
> **Rationale:** Indexes are essential for query performance on non-trivial graph sizes. Creating them on init with `IF NOT EXISTS` is idempotent and safe for repeated restarts.
>
> **Acceptance Criteria:**
> 1. After `Neo4jBackend.__init__`, indexes exist on entity name, entity type, and community_id.
> 2. Re-initializing the backend does not error or duplicate indexes.
> 3. Entity lookup by name uses the index (verified by query plan or performance).

---

> **REQ-KG-723** | Priority: SHOULD | Phase: Phase 2
>
> **Description:** Batch operations (`upsert_entities`, `upsert_triples`) SHOULD use explicit write transactions with Cypher `UNWIND` for bulk operations. Single-entity operations MAY use auto-commit transactions.
>
> **Rationale:** `UNWIND` reduces the number of round-trips to the Neo4j server from O(N) to O(1) for batch operations, significantly improving ingestion throughput.
>
> **Acceptance Criteria:**
> 1. Upserting 100 entities issues a single Cypher statement using `UNWIND` (not 100 separate statements).
> 2. Upserting 100 triples issues a single Cypher statement using `UNWIND`.
> 3. A batch operation failure rolls back the entire transaction (no partial writes).

---

> **REQ-KG-724** | Priority: MUST | Phase: Phase 2
>
> **Description:** The `Neo4jBackend.save()` and `load()` methods MUST implement export/import semantics, not primary persistence. `save(path)` MUST export the current graph state to a portable format (Cypher script or JSON). `load(path)` MUST import from the same format. These operations are for migration and backup, not the primary persistence path (Neo4j persists server-side).
>
> **Rationale:** Unlike NetworkX (which requires explicit save/load for persistence), Neo4j persists server-side. The save/load methods serve a different purpose: portability and backup. Making this semantic distinction explicit prevents misuse.
>
> **Acceptance Criteria:**
> 1. `save(path)` produces a file that, when applied to an empty Neo4j database via `load(path)`, recreates the original graph.
> 2. The export format is human-readable (Cypher script or structured JSON).
> 3. `save()` and `load()` are documented as export/import operations in their docstrings.
> 4. Normal CRUD operations persist to Neo4j without requiring explicit `save()` calls.

---

> **REQ-KG-725** | Priority: SHOULD | Phase: Phase 2
>
> **Description:** Community data in Neo4j SHOULD be stored as dedicated `(:Community)` nodes with properties `id`, `summary`, `member_count`, and `generated_at`. Entity nodes belonging to a community SHOULD be connected via `[:BELONGS_TO]` relationships to the corresponding `(:Community)` node. The `community_id` node property on entity nodes (REQ-KG-706) SHOULD be maintained as a denormalized shortcut for fast lookup.
>
> **Rationale:** Representing communities as first-class nodes with relationships enables Cypher traversal queries (e.g., "find all entities in community X") and supports future Neo4j browser visualization (REQ-KG-801). The denormalized `community_id` property enables fast single-hop lookup without relationship traversal.
>
> **Acceptance Criteria:**
> 1. After community detection and summarization, `(:Community)` nodes exist in Neo4j with summary text.
> 2. Entity nodes have `[:BELONGS_TO]` edges to their community node.
> 3. Entity nodes also have a `community_id` property matching the community node's `id`.
> 4. Re-running detection updates both the `[:BELONGS_TO]` edges and the `community_id` properties.

---

### D.7 Python/Bash Parsers

These requirements detail the optional parser extractors referenced by REQ-KG-313. Both parsers implement the existing `EntityExtractor` protocol.

---

> **REQ-KG-726** | Priority: MAY | Phase: Phase 2
>
> **Description:** The system MAY implement a Python parser extractor at `src/knowledge_graph/extraction/python_parser.py` using the stdlib `ast` module. The extractor MUST implement the `EntityExtractor` protocol and produce `ExtractionResult` objects. It MUST extract: (a) classes as `PythonClass` entities, (b) top-level functions as `PythonFunction` entities, (c) import statements as `depends_on` triples, (d) class-function containment as `contains` triples.
>
> **Rationale:** Python source files in ASIC design flows (build scripts, verification frameworks, tooling) contain structural relationships that deterministic parsing captures more reliably than LLM extraction.
>
> **Acceptance Criteria:**
> 1. Given a Python file with class `Foo` containing method `bar`, the extractor produces a `PythonClass` entity "Foo", a `PythonFunction` entity "bar", and a `contains` triple from Foo to bar.
> 2. Given `import os` and `from pathlib import Path`, the extractor produces `depends_on` triples to "os" and "pathlib".
> 3. The extractor implements the `EntityExtractor` protocol and returns `ExtractionResult`.
> 4. The extractor is toggled via `KGConfig.enable_python_parser`.

---

> **REQ-KG-727** | Priority: MAY | Phase: Phase 2
>
> **Description:** The system MAY implement a Bash parser extractor at `src/knowledge_graph/extraction/bash_parser.py` using `tree-sitter-bash`. The extractor MUST implement the `EntityExtractor` protocol and produce `ExtractionResult` objects. It MUST extract: (a) function definitions as `BashFunction` entities, (b) `source`/`.` commands as `depends_on` triples, (c) significant command invocations (configurable list) as relationship triples.
>
> **Rationale:** Bash scripts in ASIC flows (synthesis scripts, simulation runners, CI pipelines) encode critical workflow dependencies that structural parsing captures deterministically.
>
> **Acceptance Criteria:**
> 1. Given a Bash script with `function build_rtl() { ... }`, the extractor produces a `BashFunction` entity "build_rtl".
> 2. Given `source ./common.sh`, the extractor produces a `depends_on` triple to "common.sh".
> 3. The extractor implements the `EntityExtractor` protocol and returns `ExtractionResult`.
> 4. The extractor is toggled via `KGConfig.enable_bash_parser`.

---

> **REQ-KG-728** | Priority: MAY | Phase: Phase 2
>
> **Description:** The YAML schema (`config/kg_schema.yaml`) MAY be extended with the following Phase 2 node types: `PythonClass` (structural), `PythonFunction` (structural), `BashFunction` (structural), `BashScript` (structural). All new types MUST have `phase: phase_2` and `origin: structural`. Existing node and edge types MUST NOT be modified.
>
> **Rationale:** New parser extractors require corresponding schema types for validation and LLM prompt context. Phase-tagging ensures they are only active when Phase 2 features are enabled.
>
> **Acceptance Criteria:**
> 1. `PythonClass`, `PythonFunction`, `BashFunction`, and `BashScript` appear in `kg_schema.yaml` with `phase: phase_2`.
> 2. All four types have `origin: structural`.
> 3. Existing Phase 1/1b types are unchanged.
> 4. Schema validation passes after the additions.

---

### D.8 Config Extensions

These requirements define the KGConfig fields needed to control all Phase 2 features.

---

> **REQ-KG-729** | Priority: MUST | Phase: Phase 2
>
> **Description:** The `KGConfig` dataclass in `src/knowledge_graph/common/types.py` MUST be extended with the following fields, all with the specified defaults. Each field MUST support override via the corresponding environment variable.
>
> | Field | Type | Default | Env Var |
> |-------|------|---------|---------|
> | `enable_global_retrieval` | `bool` | `False` | `KG_ENABLE_GLOBAL_RETRIEVAL` |
> | `community_resolution` | `float` | `1.0` | `KG_COMMUNITY_RESOLUTION` |
> | `community_min_size` | `int` | `3` | `KG_COMMUNITY_MIN_SIZE` |
> | `community_summary_input_max_tokens` | `int` | `4096` | `KG_COMMUNITY_SUMMARY_INPUT_MAX_TOKENS` |
> | `community_summary_output_max_tokens` | `int` | `512` | `KG_COMMUNITY_SUMMARY_OUTPUT_MAX_TOKENS` |
> | `community_summary_temperature` | `float` | `0.2` | `KG_COMMUNITY_SUMMARY_TEMPERATURE` |
> | `community_summary_max_workers` | `int` | `4` | `KG_COMMUNITY_SUMMARY_MAX_WORKERS` |
> | `neo4j_uri` | `str` | `"bolt://localhost:7687"` | `KG_NEO4J_URI` |
> | `neo4j_auth_user` | `str` | `"neo4j"` | `KG_NEO4J_AUTH_USER` |
> | `neo4j_auth_password` | `str` | `""` | `KG_NEO4J_AUTH_PASSWORD` |
> | `neo4j_database` | `str` | `"neo4j"` | `KG_NEO4J_DATABASE` |
> | `enable_python_parser` | `bool` | `False` | `KG_ENABLE_PYTHON_PARSER` |
> | `enable_bash_parser` | `bool` | `False` | `KG_ENABLE_BASH_PARSER` |
>
> **Rationale:** Typed config fields with env var overrides ensure all Phase 2 behavior is controllable without code changes, consistent with the project's configurability requirements.
>
> **Acceptance Criteria:**
> 1. All 13 fields are present on `KGConfig` with the specified types and defaults.
> 2. Each field is overridable via the corresponding environment variable.
> 3. `neo4j_auth_password` is never logged or serialized in plain text (masked in any debug output).
> 4. Setting `KG_COMMUNITY_RESOLUTION=2.5` results in `KGConfig.community_resolution == 2.5`.
> 5. Config validation rejects `community_min_size < 1` and `community_resolution <= 0`.

---

## Appendix E: Phase 3 Detailed Requirements

This appendix provides detailed specifications for all Phase 3 deliverables: incremental graph updates, SV port connectivity via pyverilog, Sigma.js graph visualization, embedding-based entity resolution, hierarchical Leiden community detection, and pyproject.toml dependency management. These requirements build on the Phase 2 foundation (Appendix D) and close the gap between "graph exists" and "graph is useful for real ASIC design queries."

**Companion documents:**

- `2026-04-09-kg-phase3-sketch.md` — Approved design sketch with approach evaluations and technical decisions.
- `src/knowledge_graph/backends/networkx_backend.py` — NetworkX backend (incremental update target).
- `src/knowledge_graph/backends/neo4j_backend.py` — Neo4j backend (incremental update target).
- `src/ingest/embedding/nodes/knowledge_graph_storage.py` — Storage node (delete-before-upsert wiring).
- `src/knowledge_graph/extraction/parser_extractor.py` — Existing tree-sitter SV extractor.
- `src/knowledge_graph/community/detector.py` — Community detector (hierarchical Leiden target).
- `src/knowledge_graph/query/expander.py` — Query expander (level-selection target).
- `config/kg_schema.yaml` — YAML schema (`connects_to` edge type already defined).

**ID Range:** REQ-KG-730 through REQ-KG-756.

---

### E.1 Incremental Graph Updates

These requirements define source-level incremental delete support for the graph backends, mirroring the vector pipeline's `delete_by_source_key()` pattern. The wiring occurs in `knowledge_graph_storage.py`.

---

> **REQ-KG-730** | Priority: MUST | Phase: Phase 3
>
> **Description:** The `GraphStorageBackend` ABC MUST define a new abstract method `remove_by_source(source_key: str) -> RemovalStats`. This method removes all entities and triples contributed solely by the given source. For entities contributed by multiple sources, the method MUST prune `source_key` from the entity's `sources` list and delete the entity only when its `sources` list becomes empty. Triples MUST follow the same multi-source pruning logic. The method MUST return a `RemovalStats` dataclass reporting `nodes_removed: int`, `edges_removed: int`, and `nodes_pruned: int`.
>
> **Rationale:** The vector pipeline already implements `delete_by_source_key()` for incremental updates. Without an equivalent on the graph side, re-ingesting a changed file in `--update` mode leaves stale entities and triples from the previous version alongside new ones, producing an inconsistent graph.
>
> **Acceptance Criteria:**
> 1. `GraphStorageBackend` defines `remove_by_source(source_key: str) -> RemovalStats` as an abstract method.
> 2. `RemovalStats` is a dataclass in `src/knowledge_graph/common/schemas.py` with fields `nodes_removed`, `edges_removed`, and `nodes_pruned` (all `int`).
> 3. Calling `remove_by_source("file_a.sv")` on a backend containing entities sourced only from `file_a.sv` removes those entities and their triples entirely.
> 4. Calling `remove_by_source("file_a.sv")` on an entity whose `sources` is `["file_a.sv", "file_b.sv"]` prunes the list to `["file_b.sv"]` and does NOT delete the entity.
> 5. The returned `RemovalStats` accurately reflects the counts of removed and pruned items.

---

> **REQ-KG-731** | Priority: MUST | Phase: Phase 3
>
> **Description:** The `NetworkXBackend` MUST implement `remove_by_source(source_key)` by iterating all nodes and edges, removing `source_key` from each item's `sources` list, and deleting items whose `sources` list becomes empty. After all removals, the backend MUST rebuild internal indexes (`_case_index`, `_aliases`) to remove stale references.
>
> **Rationale:** NetworkX stores the graph in memory with `sources` as a list on both node data and edge data. Index rebuild after batch removal prevents stale lookup results.
>
> **Acceptance Criteria:**
> 1. After `remove_by_source("src_a")`, no node or edge in the graph has `"src_a"` in its `sources` list.
> 2. Nodes and edges whose `sources` list became empty are fully removed from the graph.
> 3. `_case_index` and `_aliases` are consistent with the remaining nodes after removal.
> 4. Calling `get_entity(name)` for a removed entity returns None (or raises, per ABC contract).

---

> **REQ-KG-732** | Priority: MUST | Phase: Phase 3
>
> **Description:** The `Neo4jBackend` MUST implement `remove_by_source(source_key)` using Cypher queries that: (a) remove `source_key` from `sources` list properties on Entity nodes and RELATES_TO relationships, (b) `DETACH DELETE` Entity nodes whose `sources` list becomes empty, and (c) delete RELATES_TO relationships whose `sources` list becomes empty. The operation MUST execute within a single write transaction for atomicity.
>
> **Rationale:** Neo4j stores `sources` as list properties. Server-side Cypher manipulation ensures atomicity and avoids round-tripping entity data to the client.
>
> **Acceptance Criteria:**
> 1. After `remove_by_source("src_a")`, no Entity node or relationship in Neo4j has `"src_a"` in its `sources` property.
> 2. Entity nodes with empty `sources` are removed via `DETACH DELETE`.
> 3. Relationships with empty `sources` are removed.
> 4. The entire operation is atomic (rolled back on failure).
> 5. The returned `RemovalStats` reflects the actual Neo4j-side removals.

---

> **REQ-KG-733** | Priority: MUST | Phase: Phase 3
>
> **Description:** The `knowledge_graph_storage` embedding pipeline node MUST call `backend.remove_by_source(state["source_key"])` before the extraction-and-upsert loop when `runtime.config.update_mode` is True. This mirrors the vector pipeline's delete-before-upsert pattern in `embedding_storage.py`.
>
> **Rationale:** Without pre-deletion, incremental updates accumulate stale entities. The delete-before-upsert pattern ensures each source key maps to exactly one version of its entities and triples.
>
> **Acceptance Criteria:**
> 1. In update mode, `remove_by_source()` is called with the current source key before any `upsert_entities()` or `upsert_triples()` calls.
> 2. In non-update mode (fresh ingestion), `remove_by_source()` is NOT called.
> 3. The `RemovalStats` from the deletion step is logged at INFO level.

---

> **REQ-KG-734** | Priority: MUST | Phase: Phase 3
>
> **Description:** When running in update mode, the pyverilog batch connectivity step (REQ-KG-737) MUST re-run on the full `.f` filelist after per-file incremental updates complete. All `connects_to` triples with `extractor_source="sv_connectivity"` MUST be removed (via `remove_by_source` using a synthetic source key such as `"__sv_connectivity_batch__"`) before re-generating them. This ensures `connects_to` triples reflect the current state of all SV source files.
>
> **Rationale:** `connects_to` triples are cross-module and cannot be incrementally updated per-file. Removing and regenerating the full batch is simpler and correct, since pyverilog requires all-files context for elaboration.
>
> **Acceptance Criteria:**
> 1. In update mode, the batch step removes all triples with source `"__sv_connectivity_batch__"` before re-generating.
> 2. After incremental update of one file, the `connects_to` triples reflect the current state of all files (not just the changed file).
> 3. The synthetic source key `"__sv_connectivity_batch__"` is used consistently for all pyverilog-generated triples.

---

### E.2 SV Port Connectivity (Pyverilog)

These requirements define a post-ingestion batch step that uses pyverilog's `DataflowAnalyzer` to extract cross-module port connectivity as `connects_to` triples. This complements the per-file tree-sitter extraction (REQ-KG-308).

---

> **REQ-KG-735** | Priority: MUST | Phase: Phase 3
>
> **Description:** A new `SVConnectivityAnalyzer` class MUST be implemented at `src/knowledge_graph/extraction/sv_connectivity.py`. The class MUST accept a filelist path and an optional top module name. It MUST use pyverilog's `DataflowAnalyzer` to resolve cross-module port connections and produce a list of `Triple` objects with predicate `connects_to` and `extractor_source="sv_connectivity"`.
>
> **Rationale:** Tree-sitter operates per-file and cannot resolve cross-module port connections (which port of module A connects to which port of module B through an instantiation). Pyverilog provides elaboration-level analysis that resolves these connections.
>
> **Acceptance Criteria:**
> 1. `SVConnectivityAnalyzer` exists at `src/knowledge_graph/extraction/sv_connectivity.py`.
> 2. Given a filelist containing module A that instantiates module B with port connection `.data_in(sig_out)`, the analyzer produces a `connects_to` triple from the appropriate Port/Signal entities.
> 3. All produced triples have `predicate="connects_to"` and `extractor_source="sv_connectivity"`.
> 4. The analyzer produces ONLY triples (no entity upserts), preventing duplication with tree-sitter entities.

---

> **REQ-KG-736** | Priority: MUST | Phase: Phase 3
>
> **Description:** The `SVConnectivityAnalyzer` MUST read `.f` filelists via the `RAG_KG_SV_FILELIST` configuration value. The parser MUST support standard `.f` format: one file path per line, `//` line comments, `+incdir+<path>` include directives, and recursive `-f <path>` nesting. Relative paths in the filelist MUST be resolved relative to the filelist's parent directory.
>
> **Rationale:** `.f` filelists are the ASIC industry standard for specifying compilation units. Supporting the standard format ensures compatibility with existing project structures.
>
> **Acceptance Criteria:**
> 1. A `.f` file with three SV paths (one per line) is parsed into three file paths.
> 2. Lines starting with `//` are ignored.
> 3. `+incdir+./rtl/includes` is parsed as an include directory directive.
> 4. `-f sub_filelist.f` recursively includes that filelist's contents.
> 5. Relative paths are resolved relative to the filelist file's directory, not the working directory.

---

> **REQ-KG-737** | Priority: MUST | Phase: Phase 3
>
> **Description:** The `SVConnectivityAnalyzer` MUST run as a post-ingestion batch step (not per-chunk). It MUST be wired into the ingestion pipeline (via `src/knowledge_graph/__init__.py` or the storage node) so that it executes after all per-file tree-sitter extractions are complete. The batch step MUST only run when `RAG_KG_SV_FILELIST` is configured and the filelist file exists.
>
> **Rationale:** Pyverilog requires all source files for elaboration context. Running per-chunk would fail because cross-module references are unresolved until all files are available.
>
> **Acceptance Criteria:**
> 1. The batch step runs after all per-file extraction and storage operations complete.
> 2. When `RAG_KG_SV_FILELIST` is not configured, the batch step is skipped silently.
> 3. When `RAG_KG_SV_FILELIST` points to a non-existent file, the batch step logs a WARNING and is skipped.
> 4. After the batch step, `connects_to` triples are present in the graph backend.

---

> **REQ-KG-738** | Priority: MUST | Phase: Phase 3
>
> **Description:** The `SVConnectivityAnalyzer` MUST auto-detect the top module when `RAG_KG_SV_TOP_MODULE` is not configured. Auto-detection MUST use the heuristic: query all `RTL_Module` entities from the graph backend and identify modules that are never the target of an `instantiates` edge. If exactly one candidate is found, it is used as the top module. If multiple candidates are found, the analyzer MUST log a WARNING listing the candidates and skip analysis. The `RAG_KG_SV_TOP_MODULE` configuration value overrides auto-detection.
>
> **Rationale:** "Modules never instantiated by another" is the standard heuristic for identifying the top module. Explicit override handles ambiguous cases (e.g., testbench setups with multiple top-level modules).
>
> **Acceptance Criteria:**
> 1. Given a graph where module `top` instantiates modules `a` and `b` (and no module instantiates `top`), auto-detection selects `top`.
> 2. Given two uninstantiated modules `top1` and `top2`, auto-detection logs a WARNING and skips analysis.
> 3. Setting `RAG_KG_SV_TOP_MODULE=top1` overrides auto-detection and uses `top1` regardless of graph state.
> 4. With no `RTL_Module` entities in the graph, auto-detection logs a WARNING and skips analysis.

---

> **REQ-KG-739** | Priority: SHOULD | Phase: Phase 3
>
> **Description:** The `SVConnectivityAnalyzer` SHOULD gracefully handle pyverilog failures. If pyverilog is not installed (ImportError), the analyzer SHOULD log a WARNING and return an empty triple list. If `DataflowAnalyzer` raises an exception for a given filelist (e.g., unsupported SV constructs), the analyzer SHOULD log the exception at WARNING level and return an empty triple list rather than propagating the error.
>
> **Rationale:** Pyverilog's SystemVerilog support is incomplete for newer language features. Graceful degradation ensures the rest of the ingestion pipeline is not blocked by pyverilog failures.
>
> **Acceptance Criteria:**
> 1. When pyverilog is not installed, the batch step logs a WARNING and produces no triples (no exception propagated).
> 2. When `DataflowAnalyzer` raises an exception, the batch step logs the exception at WARNING and produces no triples.
> 3. The rest of the ingestion pipeline (tree-sitter extraction, entity descriptions, community detection) completes normally regardless of pyverilog failures.

---

> **REQ-KG-740** | Priority: MUST | Phase: Phase 3
>
> **Description:** The `KGConfig` dataclass MUST be extended with fields `sv_filelist: str` (default `""`, env var `RAG_KG_SV_FILELIST`) and `sv_top_module: str` (default `""`, env var `RAG_KG_SV_TOP_MODULE`). When `sv_filelist` is empty, the pyverilog batch step is disabled. When `sv_top_module` is empty, auto-detection is used.
>
> **Rationale:** Typed config fields with env var overrides maintain consistency with the project's configurability conventions (REQ-KG-729).
>
> **Acceptance Criteria:**
> 1. `KGConfig.sv_filelist` and `KGConfig.sv_top_module` exist with type `str` and default `""`.
> 2. Setting `RAG_KG_SV_FILELIST=/path/to/files.f` results in `KGConfig.sv_filelist == "/path/to/files.f"`.
> 3. Setting `RAG_KG_SV_TOP_MODULE=my_top` results in `KGConfig.sv_top_module == "my_top"`.
> 4. Empty `sv_filelist` disables the pyverilog batch step entirely.

---

> **REQ-KG-756** | Priority: SHOULD | Phase: Phase 3
>
> **Description:** The `GraphQueryExpander` SHOULD increase `max_depth` to at least 2 when matched entities have `connects_to` edges in the graph, enabling multi-hop connectivity chain traversal (e.g., `port A → signal → port B`). When no `connects_to` edges are present for matched entities, the default `max_depth` from `KGConfig` applies unchanged.
>
> **Rationale:** Port connectivity queries require at least 2-hop traversal to follow the path through an intermediate signal. Without this, the expander would return only the directly connected signal but not the destination port on the other module.
>
> **Acceptance Criteria:**
> 1. When a matched entity has at least one `connects_to` edge, the expansion depth is at least 2 (regardless of `KGConfig.max_expansion_depth`).
> 2. When no `connects_to` edges exist for matched entities, the configured `max_expansion_depth` is used unchanged.
> 3. The depth adjustment is logged at DEBUG level.

---

### E.3 Graph Visualization (Sigma.js)

These requirements define an interactive HTML graph visualization export using Sigma.js and graphology loaded from CDN.

---

> **REQ-KG-741** | Priority: MUST | Phase: Phase 3
>
> **Description:** A new function `export_html(backend: GraphStorageBackend, output_path: str, community_detector: Optional[CommunityDetector] = None)` MUST be implemented at `src/knowledge_graph/export/sigma_export.py`. The function MUST generate a single self-contained HTML file that renders the graph using Sigma.js v3 and graphology loaded from CDN (unpkg or cdnjs). The HTML file MUST embed graph data as inline JSON within a `<script>` tag. The HTML template MUST be embedded in the Python module as a multiline string (no external template file dependency).
>
> **Rationale:** Interactive graph visualization enables engineers to explore the graph structure, identify clusters, and navigate relationships. A single HTML file is shareable via email or Slack without requiring a server.
>
> **Acceptance Criteria:**
> 1. `export_html()` exists at `src/knowledge_graph/export/sigma_export.py`.
> 2. The output is a single `.html` file with no external file dependencies (JS loaded from CDN).
> 3. Opening the HTML file in a browser renders the graph with nodes and edges.
> 4. The graph data is embedded as JSON in an inline `<script>` tag.
> 5. `export_html` is added to the public API in `src/knowledge_graph/__init__.py` and `__all__`.

---

> **REQ-KG-742** | Priority: MUST | Phase: Phase 3
>
> **Description:** Nodes in the visualization MUST be colored by entity type (using a deterministic color palette mapped from type names). If a `CommunityDetector` with completed detection is provided, nodes MUST be colored by community ID instead (overriding type-based coloring). Node size MUST be proportional to the entity's `mention_count` or graph degree.
>
> **Rationale:** Visual encoding of type or community membership makes graph structure immediately legible without inspecting individual nodes.
>
> **Acceptance Criteria:**
> 1. Without a community detector, nodes of the same entity type share the same color and different types have distinct colors.
> 2. With a ready community detector, nodes in the same community share the same color.
> 3. Node size varies based on mention_count or degree (higher values produce larger nodes).
> 4. The color palette is deterministic (same graph produces same colors across exports).

---

> **REQ-KG-743** | Priority: MUST | Phase: Phase 3
>
> **Description:** Edges in the visualization MUST be styled by predicate type. At minimum, `connects_to` edges MUST be visually distinguishable from structural edges (`contains`, `instantiates`) and semantic edges (`relates_to`, `specified_by`). Edge styling MAY use color, dash pattern, or width variation.
>
> **Rationale:** `connects_to` edges from pyverilog represent a different kind of relationship (port connectivity) than structural containment. Visual distinction prevents confusion.
>
> **Acceptance Criteria:**
> 1. `connects_to` edges are visually distinct from `contains` and `instantiates` edges.
> 2. At least two edge style categories are used (structural vs. semantic, or finer).
> 3. An edge legend or tooltip identifies the predicate type.

---

> **REQ-KG-744** | Priority: SHOULD | Phase: Phase 3
>
> **Description:** When a `CommunityDetector` with hierarchical community data (REQ-KG-750) is provided, the visualization SHOULD support community-based grouping. Nodes within the same community SHOULD be spatially clustered (via ForceAtlas2 layout from graphology-layout-forceatlas2). Zoom interaction SHOULD reveal finer community granularity at deeper zoom levels.
>
> **Rationale:** Hierarchical zoom lets engineers start with a high-level view of major subsystems and drill down into specific module clusters without being overwhelmed by detail.
>
> **Acceptance Criteria:**
> 1. Nodes in the same community are spatially grouped in the layout.
> 2. Zooming in reveals individual nodes within a cluster.
> 3. The visualization degrades gracefully when no community data is available (flat layout by entity type).

---

> **REQ-KG-745** | Priority: MUST | Phase: Phase 3
>
> **Description:** The visualization MUST provide: (a) a search box that filters/highlights nodes by name substring, (b) hover tooltips showing entity name, type, sources, and relationship count, and (c) zoom and pan controls.
>
> **Rationale:** Basic interactivity (search, hover, zoom) is essential for navigating graphs beyond trivial size. Without search, finding a specific entity in a 500+ node graph is impractical.
>
> **Acceptance Criteria:**
> 1. Typing a substring in the search box highlights matching nodes and dims non-matching ones.
> 2. Hovering over a node shows a tooltip with at minimum: name, entity type, and number of relationships.
> 3. Mouse wheel zoom and click-drag pan are functional.
> 4. The visualization is usable for graphs up to 5,000 nodes without severe performance degradation.

---

### E.4 Entity Resolution

These requirements define embedding-based entity deduplication with alias table support. Entity resolution runs as a post-ingestion step before community detection.

---

> **REQ-KG-746** | Priority: MUST | Phase: Phase 3
>
> **Description:** An `EntityResolver` class MUST be implemented at `src/knowledge_graph/resolution/resolver.py` with a `resolve(backend: GraphStorageBackend) -> MergeReport` method. The resolver orchestrates: (a) deterministic alias-table merges first, then (b) embedding-based fuzzy matching. The `MergeReport` dataclass MUST track `merges: List[MergeCandidate]` (each recording canonical name, merged name, similarity score, and merge reason) and `total_merged: int`.
>
> **Rationale:** Entity resolution eliminates duplicate entities created by different extractors using different surface forms for the same concept. Running alias merges first (fast, deterministic) reduces the candidate set for the more expensive embedding pass.
>
> **Acceptance Criteria:**
> 1. `EntityResolver` exists at `src/knowledge_graph/resolution/resolver.py`.
> 2. `MergeReport` and `MergeCandidate` dataclasses exist in `src/knowledge_graph/resolution/schemas.py`.
> 3. `resolve()` returns a `MergeReport` with accurate counts and merge details.
> 4. Alias-table merges execute before embedding-based merges.
> 5. The resolver is invoked after all extraction completes but before community detection.

---

> **REQ-KG-747** | Priority: MUST | Phase: Phase 3
>
> **Description:** An `EmbeddingResolver` MUST be implemented at `src/knowledge_graph/resolution/embedding_resolver.py`. It MUST: (a) load all entities from the backend grouped by type, (b) compute embeddings for entity names using the configured embedding model (`EMBEDDING_MODEL_PATH` or KGConfig), (c) compute pairwise cosine similarity within each type bucket, (d) identify merge candidates above the configured threshold (default 0.85). Matching MUST be type-constrained: only entities of the same type are compared.
>
> **Rationale:** Embedding-based similarity catches semantic equivalences that case-insensitive dedup misses (e.g., "ethernet_controller" and "eth_ctrl"). Type-constraining prevents false merges across entity categories.
>
> **Acceptance Criteria:**
> 1. `EmbeddingResolver` exists at `src/knowledge_graph/resolution/embedding_resolver.py`.
> 2. Only entities of the same type are compared (an `RTL_Module` named "AXI4" is never compared to a `Protocol` named "AXI4").
> 3. Pairs with cosine similarity >= 0.85 (default) are flagged as merge candidates.
> 4. The embedding model is loaded from `EMBEDDING_MODEL_PATH` or a KGConfig field.
> 5. When `EMBEDDING_MODEL_PATH` is not set and no model is configured, the embedding resolver logs a WARNING and returns no candidates.

---

> **REQ-KG-748** | Priority: MUST | Phase: Phase 3
>
> **Description:** An `AliasResolver` MUST be implemented at `src/knowledge_graph/resolution/alias_resolver.py`. It MUST load a YAML alias table from the path specified by `KGConfig.entity_resolution_alias_path` (default `config/kg_aliases.yaml`). The alias table format MUST be a list of groups, where each group specifies a `canonical` name and a list of `aliases`. The resolver MUST produce merge candidates for any entity whose name matches an alias in a group, merging toward the group's canonical name. Matching MUST be case-insensitive.
>
> **Rationale:** A YAML alias table provides a deterministic escape hatch for domain-specific synonyms that embeddings might miss or get wrong. It is faster and more predictable than embedding comparison.
>
> **Acceptance Criteria:**
> 1. `AliasResolver` exists at `src/knowledge_graph/resolution/alias_resolver.py`.
> 2. Given an alias table entry `{canonical: "AXI4_Arbiter", aliases: ["axi4_arb", "AXI_ARB"]}` and an entity named "axi4_arb", the resolver produces a merge candidate toward "AXI4_Arbiter".
> 3. Matching is case-insensitive.
> 4. When the alias file does not exist, the resolver logs a WARNING and returns no candidates.
> 5. The alias file path is configurable via `KGConfig.entity_resolution_alias_path`.

---

> **REQ-KG-749** | Priority: MUST | Phase: Phase 3
>
> **Description:** The `GraphStorageBackend` ABC MUST define a new abstract method `merge_entities(canonical: str, duplicate: str) -> None`. This method MUST: (a) transfer all triples referencing the duplicate entity to reference the canonical entity instead, (b) merge `sources`, `aliases`, and `raw_mentions` lists from the duplicate into the canonical entity, (c) keep the higher `mention_count` between the two entities, and (d) delete the duplicate entity. Both the `NetworkXBackend` and `Neo4jBackend` MUST implement this method.
>
> **Rationale:** Entity merging requires atomic redirection of all triples plus metadata consolidation. A backend-level method encapsulates the complexity and ensures both backends handle it correctly (graph mutation for NetworkX, multi-statement Cypher transaction for Neo4j).
>
> **Acceptance Criteria:**
> 1. `merge_entities(canonical, duplicate)` is an abstract method on `GraphStorageBackend`.
> 2. After merging, all triples that referenced the duplicate now reference the canonical entity.
> 3. The canonical entity's `sources` list is the union of both entities' sources.
> 4. The canonical entity's `aliases` list includes the duplicate's name and its aliases.
> 5. The duplicate entity no longer exists in the backend.
> 6. The operation is atomic in Neo4j (single transaction).

---

> **REQ-KG-750** | Priority: MUST | Phase: Phase 3
>
> **Description:** The `EntityResolver` MUST be controlled by the `KGConfig.enable_entity_resolution: bool` flag (default False). The cosine similarity threshold MUST be configurable via `KGConfig.entity_resolution_threshold: float` (default 0.85, env var `RAG_KG_RESOLUTION_THRESHOLD`). The alias table path MUST be configurable via `KGConfig.entity_resolution_alias_path: str` (default `"config/kg_aliases.yaml"`, env var `RAG_KG_RESOLUTION_ALIAS_PATH`).
>
> **Rationale:** Entity resolution is a potentially destructive operation (merging entities). Defaulting to disabled ensures backward compatibility and opt-in activation. A configurable threshold lets operators tune the aggressiveness of merging.
>
> **Acceptance Criteria:**
> 1. With `enable_entity_resolution=False`, the resolver is not invoked during ingestion.
> 2. With `enable_entity_resolution=True`, the resolver runs after extraction and before community detection.
> 3. Setting `RAG_KG_RESOLUTION_THRESHOLD=0.90` results in `KGConfig.entity_resolution_threshold == 0.90`.
> 4. Setting `RAG_KG_RESOLUTION_ALIAS_PATH=/custom/aliases.yaml` results in `KGConfig.entity_resolution_alias_path == "/custom/aliases.yaml"`.
> 5. Config validation rejects `entity_resolution_threshold` values outside the range (0.0, 1.0].

---

### E.5 Hierarchical Leiden Community Detection

These requirements extend the existing flat Leiden community detection (REQ-KG-700 through REQ-KG-716) to produce multi-level hierarchical partitions.

---

> **REQ-KG-751** | Priority: MUST | Phase: Phase 3
>
> **Description:** The `CommunityDetector.detect()` method MUST be extended to return multi-level community results. The data structure MUST be a flat dict `{(level, community_id): [member_names]}` plus a `parent_map: Dict[Tuple[int, int], Tuple[int, int]]` mapping each `(level, community_id)` to its parent `(parent_level, parent_community_id)`. Level 0 is the coarsest (fewest, largest communities). Deeper levels represent finer sub-partitions. The maximum number of levels MUST be controlled by `KGConfig.community_max_levels: int` (default 3).
>
> **Rationale:** Flat single-level communities produce either too many small communities or too few large ones for large graphs. Hierarchical partitioning gives both overview and detail. The flat dict + parent_map structure avoids nested data complexity while preserving the full hierarchy.
>
> **Acceptance Criteria:**
> 1. `detect()` returns a hierarchical partition with at least 2 levels for a graph with 50+ entities.
> 2. The partition structure is `{(level, cid): [members]}` with `parent_map: {(level, cid): (parent_level, parent_cid)}`.
> 3. Level 0 contains the fewest communities (coarsest granularity).
> 4. Every member at level N is a subset of exactly one community at level N-1.
> 5. With `community_max_levels=1`, behavior is equivalent to the current flat Leiden (backward compatible).
> 6. Recursion stops when a community is smaller than `community_min_size` or Leiden returns a single community for a sub-partition.

---

> **REQ-KG-752** | Priority: MUST | Phase: Phase 3
>
> **Description:** The `CommunitySummary` dataclass (or a new `HierarchicalCommunitySummary`) MUST include a `level: int` field indicating which hierarchy level the summary belongs to. The `CommunitySummarizer` MUST accept a `levels` parameter controlling which levels are summarized (default: levels 0 and 1). Higher-level summaries SHOULD be coarser (broader scope), and lower-level summaries SHOULD be more specific.
>
> **Rationale:** Pre-summarizing all levels is expensive (LLM calls scale with communities x levels). Summarizing only the top 2 levels by default balances utility with cost. Deeper levels can be summarized on demand or by configuration.
>
> **Acceptance Criteria:**
> 1. `CommunitySummary` (or `HierarchicalCommunitySummary`) has a `level: int` field.
> 2. By default, only levels 0 and 1 are summarized.
> 3. Setting `community_summarize_levels=[0, 1, 2]` causes level 2 communities to also be summarized.
> 4. A level-0 summary for a community of 50 members is broader in scope than a level-2 summary for a sub-community of 10 members.

---

> **REQ-KG-753** | Priority: SHOULD | Phase: Phase 3
>
> **Description:** The `GraphQueryExpander` SHOULD select the community hierarchy level based on query specificity when hierarchical communities are available. Broad queries (few or no entity matches) SHOULD use level 0 (coarsest communities) for expansion. Specific queries (multiple entity matches) SHOULD use the deepest available level. The level selection heuristic SHOULD use the number of matched entities as a proxy for specificity.
>
> **Rationale:** A broad query like "what is the memory subsystem?" benefits from a high-level community summary. A specific query like "what drives the AXI read channel FIFO?" benefits from a fine-grained community containing only closely related entities.
>
> **Acceptance Criteria:**
> 1. A query matching 0 entities uses level 0 community summaries for expansion.
> 2. A query matching 3+ entities uses the deepest available level.
> 3. When hierarchical communities are not available (flat Leiden only), the expander falls back to flat community expansion.
> 4. The level selection is deterministic for the same query and graph state.

---

> **REQ-KG-754** | Priority: MUST | Phase: Phase 3
>
> **Description:** The sidecar JSON file (`<graph_path>.communities.json`) MUST be updated to include hierarchical community data. The format MUST include: (a) the hierarchical partition dict (serialized with string keys for JSON compatibility), (b) the parent_map, (c) per-level summaries. The sidecar MUST be backward-compatible: loading an old flat-format sidecar MUST treat all data as level 0.
>
> **Rationale:** Hierarchical community data must survive process restarts. Backward compatibility ensures existing deployments are not broken by the format change.
>
> **Acceptance Criteria:**
> 1. After hierarchical `detect()` + `summarize_all()`, the sidecar contains multi-level data.
> 2. Loading an old flat-format sidecar (no level keys) treats all communities as level 0.
> 3. The sidecar round-trips correctly: save then load produces equivalent hierarchical state.
> 4. The sidecar file remains valid JSON and is human-inspectable.

---

### E.6 pyproject.toml Dependency Management

These requirements define the packaging changes needed to support Phase 3 features.

---

> **REQ-KG-755** | Priority: MUST | Phase: Phase 3
>
> **Description:** The `pyproject.toml` MUST be updated as follows: (a) Add `tree-sitter`, `tree-sitter-verilog`, and `pyverilog` to the default `[project.dependencies]` list. (b) Add optional dependency groups: `kg-community = ["igraph", "leidenalg"]` for hierarchical Leiden, and `kg-neo4j = ["neo4j"]` for the Neo4j backend. (c) Update the `[all]` optional group to include the new `kg-community` and `kg-neo4j` groups. (d) Update `requirements.txt` to match the new dependency set. Existing try/except import guards in the codebase MUST be preserved for graceful degradation when optional dependencies are missing.
>
> **Rationale:** Tree-sitter-verilog and pyverilog are lightweight pure-Python packages central to an ASIC-focused tool and belong in default dependencies. igraph/leidenalg have C extensions that can be tricky to build on some platforms, and neo4j requires a running server, so both belong in optional groups.
>
> **Acceptance Criteria:**
> 1. `pip install .` installs tree-sitter, tree-sitter-verilog, and pyverilog without extras.
> 2. `pip install ".[kg-community]"` installs igraph and leidenalg.
> 3. `pip install ".[kg-neo4j]"` installs the neo4j driver.
> 4. `pip install ".[all]"` installs all optional dependencies including the new groups.
> 5. `requirements.txt` lists all default and optional dependencies consistent with pyproject.toml.
> 6. Try/except guards in `detector.py`, `neo4j_backend.py`, and `sv_connectivity.py` remain in place.
