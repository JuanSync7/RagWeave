# Knowledge Graph Subsystem -- Design Document

## Document Information

| Field | Value |
|-------|-------|
| System | RagWeave Knowledge Graph Subsystem |
| Document Type | Technical Design with Task Decomposition |
| Source of Truth | `KNOWLEDGE_GRAPH_SPEC.md` (v1.0.0) |
| Companion | `KNOWLEDGE_GRAPH_SPEC_SUMMARY.md`, `2026-04-08-kg-subsystem-sketch.md` |
| Date | 2026-04-08 |
| Status | Draft |

---

## 1. Architecture Overview

### 1.1 Component Diagram

```text
                        config/kg_schema.yaml
                               |
                               v
                    ┌─────────────────────┐
                    │  Schema Loader       │
                    │  common/types.py     │
                    └──────────┬──────────┘
                               |
            ┌──────────────────┼──────────────────┐
            v                  v                  v
  ┌──────────────┐  ┌──────────────────┐  ┌──────────────────┐
  │  Extraction   │  │  Storage          │  │  Query            │
  │  Pipeline     │  │  Backend (ABC)    │  │  Pipeline         │
  │               │  │                   │  │                   │
  │  regex ─┐     │  │  NetworkXBackend  │  │  entity_matcher   │
  │  gliner ├─>M  │  │  Neo4jBackend(s)  │  │  sanitizer        │
  │  llm*  ─┘     │  │  NoOpBackend      │  │  expander         │
  │  sv*   ─┘     │  │                   │  │  llm_fallback*    │
  └──────┬────────┘  └────────┬──────────┘  └────────┬──────────┘
         |                    |                      |
         v                    v                      v
  ┌──────────────────────────────────────────────────────────────┐
  │  __init__.py  (Public API)                                    │
  │  get_graph_backend()  get_query_expander()                    │
  │  Lazy singleton dispatcher                                    │
  └──────────────────────────────────────────────────────────────┘
         |                    |                      |
         v                    v                      v
  Node 10 (extraction)  Node 13 (storage)   Stage 2 (retrieval)
  Embedding Pipeline    Embedding Pipeline   Retrieval Pipeline
```

`*` = Phase 1b (stub only in Phase 1), `M` = merge node, `(s)` = stub

### 1.2 Data Flow

**Ingestion path:**
1. Node 10 receives chunks from the embedding pipeline.
2. Node 10 calls `ExtractionPipeline.run(chunks)` which compiles a LangGraph subgraph.
3. Enabled extractors (regex, GLiNER, etc.) run in parallel branches.
4. Merge node deduplicates, validates against YAML schema, and produces a single `ExtractionResult`.
5. `ExtractionResult` is stored in pipeline state as `kg_extraction_result`.
6. Node 13 reads `kg_extraction_result` and calls `backend.upsert_entities()`, `backend.upsert_triples()`, `backend.upsert_descriptions()`.

**Retrieval path:**
1. Stage 2 calls `get_query_expander()` to obtain the singleton expander.
2. Expander uses spaCy entity matcher to find entities in the query (fast path).
3. If no matches and LLM fallback is enabled (Phase 1b), LLM identifies entities.
4. Expander traverses the graph from matched entities and returns expansion terms.
5. Expansion terms are appended to the BM25 query (bounded by `max_expansion_terms`).

### 1.3 Package Layout

```
src/knowledge_graph/
  __init__.py                       # T11: Public API, lazy singleton
  backend.py                        # T2:  GraphStorageBackend ABC
  common/
    __init__.py                     # T1
    schemas.py                      # T1:  Entity, Triple, ExtractionResult, EntityDescription
    types.py                        # T1:  KGConfig, SchemaDefinition
    utils.py                        # T1:  normalize_alias, validate_type, derive_gliner_labels
  extraction/
    __init__.py                     # T5/T6: ExtractionPipeline entry point
    base.py                         # T5:  EntityExtractor protocol
    regex_extractor.py              # T5:  Migrated from monolith
    gliner_extractor.py             # T6:  Migrated from monolith
    llm_extractor.py                # T15: Phase 1b stub
    sv_parser.py                    # T16: Phase 1b stub
    merge.py                        # T7:  Merge node: dedup, validation
  query/
    __init__.py                     # T9
    entity_matcher.py               # T8:  spaCy rule-based matcher
    expander.py                     # T9:  GraphQueryExpander (migrated + enhanced)
    sanitizer.py                    # T10: Normalization, alias expansion, fan-out
    llm_fallback.py                 # T15: Phase 1b stub (shared with T15)
  backends/
    __init__.py                     # T3
    networkx_backend.py             # T3:  NetworkX + orjson
    neo4j_backend.py                # T4:  Phase 2 stub
  community/
    __init__.py                     # T14
    detector.py                     # T14: Phase 2 stub
    summarizer.py                   # T14: Phase 2 stub
  export/
    __init__.py                     # T13
    obsidian.py                     # T13: Migrated from monolith

config/
  kg_schema.yaml                    # T12: YAML schema (41 node types, 22 edge types)
```

---

## 2. Task Decomposition

### 2.1 Dependency Graph

```text
T1 ──────────────┬──> T2 ──┬──> T3 ──┐
(schemas/types)  │         │         ├──> T11 (public API)
                 │         ├──> T4   │
                 │         │         │
                 ├──> T5 ──┤         │
                 │         ├──> T7 ──┤
                 ├──> T6 ──┘         │
                 │                   │
                 ├──> T8 ──┬──> T9 ──┤
                 │         │         │
                 ├──> T10 ─┘         │
                 │                   │
                 ├──> T12            │
                 │                   │
                 ├──> T13 ──────────>│
                 │                   │
                 ├──> T14            │
                 │                   │
                 ├──> T15            │
                 │                   │
                 └──> T16            │
                                    │
                 T11 ───────────────┤
                                    │
                 T11 + T5/T6 ──────>├──> T17 (ingest pipeline)
                 T11 + T9 ─────────>├──> T18 (retrieval pipeline)
                 T1 ────────────────>──> T19 (config/settings.py)
                 T11 ───────────────>──> T20 (backward compat shim)
```

### 2.2 Parallelism Groups

Tasks within each group can execute in parallel once their dependencies are met.

| Group | Tasks | Dependency |
|-------|-------|------------|
| **G0** | T1, T12 | None |
| **G1** | T2, T5, T6, T8, T10, T14, T15, T16, T19 | T1 |
| **G2** | T3, T4, T7, T9, T13 | T2 (for T3/T4/T13), T5+T6 (for T7), T8+T10 (for T9) |
| **G3** | T11 | T3, T9 |
| **G4** | T17, T18, T20 | T11 |

---

## 3. Task Specifications

### T1: Package Skeleton + Common Contracts

| Field | Value |
|-------|-------|
| **Task ID** | T1 |
| **Title** | Create package skeleton with common/schemas.py, common/types.py, common/utils.py |
| **Dependencies** | None |
| **Files Created** | `src/knowledge_graph/__init__.py` (placeholder), `src/knowledge_graph/common/__init__.py`, `src/knowledge_graph/common/schemas.py`, `src/knowledge_graph/common/types.py`, `src/knowledge_graph/common/utils.py`, `src/knowledge_graph/extraction/__init__.py`, `src/knowledge_graph/query/__init__.py`, `src/knowledge_graph/backends/__init__.py`, `src/knowledge_graph/community/__init__.py`, `src/knowledge_graph/export/__init__.py` |
| **REQ Coverage** | REQ-KG-200, REQ-KG-205, REQ-KG-206, REQ-KG-208 |
| **Estimated LOC** | 250 |

**Code Contract -- `src/knowledge_graph/common/schemas.py`:**

```python
"""Typed data contracts for the KG subsystem."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EntityDescription:
    """A single mention of an entity in a document chunk.

    Attributes:
        text: The relevant sentence or passage containing the entity mention.
        source: Document path where the mention was found.
        chunk_id: Originating chunk identifier.
    """
    text: str
    source: str
    chunk_id: str


@dataclass
class Entity:
    """A named entity extracted from document text.

    Attributes:
        name: Canonical entity name (first-seen form).
        type: Entity type from the YAML schema (e.g., 'RTL_Module', 'Protocol').
        sources: Document paths where this entity was found.
        mention_count: Number of times this entity was mentioned.
        aliases: Alternative surface forms for this entity.
        raw_mentions: Accumulated mention descriptions with source attribution.
        current_summary: LLM-condensed description (empty until token budget exceeded).
        extractor_source: Which extractor(s) produced this entity.
    """
    name: str
    type: str
    sources: List[str] = field(default_factory=list)
    mention_count: int = 1
    aliases: List[str] = field(default_factory=list)
    raw_mentions: List[EntityDescription] = field(default_factory=list)
    current_summary: str = ""
    extractor_source: List[str] = field(default_factory=list)


@dataclass
class Triple:
    """A subject-predicate-object relationship between two entities.

    Attributes:
        subject: Source entity name.
        predicate: Relationship type from the YAML schema.
        object: Target entity name.
        source: Document path where this relation was extracted.
        weight: Accumulated weight (incremented on repeated observation).
        extractor_source: Which extractor produced this triple.
    """
    subject: str
    predicate: str
    object: str
    source: str = ""
    weight: float = 1.0
    extractor_source: str = ""


@dataclass
class ExtractionResult:
    """Combined output of the extraction pipeline for a batch of chunks.

    Attributes:
        entities: Extracted and deduplicated entities.
        triples: Extracted and deduplicated triples.
        descriptions: Mapping of entity name to list of new EntityDescriptions.
    """
    entities: List[Entity] = field(default_factory=list)
    triples: List[Triple] = field(default_factory=list)
    descriptions: Dict[str, List[EntityDescription]] = field(default_factory=dict)
```

**Code Contract -- `src/knowledge_graph/common/types.py`:**

```python
"""Configuration and schema types for the KG subsystem."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class NodeTypeDefinition:
    """A single node type from the YAML schema.

    Attributes:
        name: Unique type identifier (e.g., 'RTL_Module').
        description: Human-readable description.
        category: 'structural' or 'semantic'.
        phase: 'phase_1', 'phase_1b', or 'phase_2'.
        gliner_label: Optional override label for GLiNER. Defaults to name.
        extraction_hints: Optional hints for LLM extractor prompts.
    """
    name: str
    description: str
    category: str  # "structural" | "semantic"
    phase: str  # "phase_1" | "phase_1b" | "phase_2"
    gliner_label: Optional[str] = None
    extraction_hints: Optional[str] = None


@dataclass
class EdgeTypeDefinition:
    """A single edge type from the YAML schema.

    Attributes:
        name: Unique type identifier (e.g., 'instantiates').
        description: Human-readable description.
        category: 'structural' or 'semantic'.
        phase: 'phase_1', 'phase_1b', or 'phase_2'.
        source_types: Allowed source node types (empty = any).
        target_types: Allowed target node types (empty = any).
    """
    name: str
    description: str
    category: str
    phase: str
    source_types: List[str] = field(default_factory=list)
    target_types: List[str] = field(default_factory=list)


@dataclass
class SchemaDefinition:
    """Parsed representation of config/kg_schema.yaml.

    Attributes:
        version: Schema version string.
        description: Schema description.
        node_types: All defined node types.
        edge_types: All defined edge types.
        _node_index: Internal lookup by name (built on construction).
        _edge_index: Internal lookup by name (built on construction).
    """
    version: str
    description: str
    node_types: List[NodeTypeDefinition] = field(default_factory=list)
    edge_types: List[EdgeTypeDefinition] = field(default_factory=list)

    def active_node_types(self, runtime_phase: str) -> List[NodeTypeDefinition]:
        """Return node types active at the given runtime phase."""
        ...

    def active_edge_types(self, runtime_phase: str) -> List[EdgeTypeDefinition]:
        """Return edge types active at the given runtime phase."""
        ...

    def is_valid_node_type(self, type_name: str, runtime_phase: str) -> bool:
        """Check if a node type is valid and active at the given phase."""
        ...

    def is_valid_edge_type(self, type_name: str, runtime_phase: str) -> bool:
        """Check if an edge type is valid and active at the given phase."""
        ...


@dataclass
class KGConfig:
    """Runtime configuration for the KG subsystem.

    All fields map to configuration keys defined in REQ-KG-904.
    """
    backend: str = "networkx"
    schema_path: str = "config/kg_schema.yaml"
    enable_regex_extractor: bool = True
    enable_gliner_extractor: bool = False
    enable_llm_extractor: bool = False
    enable_sv_parser: bool = False
    entity_description_token_budget: int = 512
    entity_description_top_k_mentions: int = 5
    max_expansion_depth: int = 1
    max_expansion_terms: int = 3
    enable_llm_query_fallback: bool = False
    llm_fallback_timeout_ms: int = 1000
    enable_global_retrieval: bool = False
    runtime_phase: str = "phase_1"
    regex_fallback_type: str = "concept"
    extractor_priority: List[str] = field(
        default_factory=lambda: ["sv_parser", "llm", "gliner", "regex"]
    )
```

**Code Contract -- `src/knowledge_graph/common/utils.py`:**

```python
"""Shared helpers for the KG subsystem."""
from __future__ import annotations
from typing import List
from src.knowledge_graph.common.types import SchemaDefinition


def normalize_alias(name: str) -> str:
    """Normalize an entity name for case-insensitive comparison.

    Lowercases, strips whitespace, replaces hyphens/underscores with spaces.

    Args:
        name: Raw entity name or alias.

    Returns:
        Normalized string suitable for comparison keys.
    """
    ...


def validate_type(type_name: str, schema: SchemaDefinition, runtime_phase: str) -> bool:
    """Check if a type name is valid and active in the schema at the given phase.

    Args:
        type_name: Entity or edge type name.
        schema: Loaded schema definition.
        runtime_phase: Current runtime phase string.

    Returns:
        True if the type is defined and active.
    """
    ...


def derive_gliner_labels(schema: SchemaDefinition, runtime_phase: str) -> List[str]:
    """Build the GLiNER label list from active schema node types.

    Uses the gliner_label override when present, otherwise the type name.

    Args:
        schema: Loaded schema definition.
        runtime_phase: Current runtime phase string.

    Returns:
        List of label strings for GLiNER.
    """
    ...


PHASE_ORDER = {"phase_1": 1, "phase_1b": 2, "phase_2": 3}


def is_phase_active(type_phase: str, runtime_phase: str) -> bool:
    """Check if a type's phase tag is active at the given runtime phase.

    A type is active if its phase ordinal is <= the runtime phase ordinal.

    Args:
        type_phase: Phase tag from the schema type definition.
        runtime_phase: Current runtime phase.

    Returns:
        True if the type should be active.
    """
    ...
```

---

### T2: GraphStorageBackend ABC

| Field | Value |
|-------|-------|
| **Task ID** | T2 |
| **Title** | Write GraphStorageBackend ABC in backend.py |
| **Dependencies** | T1 |
| **Files Created** | `src/knowledge_graph/backend.py` |
| **REQ Coverage** | REQ-KG-201, REQ-KG-500, REQ-KG-405 |
| **Estimated LOC** | 150 |

**Code Contract -- `src/knowledge_graph/backend.py`:**

```python
"""GraphStorageBackend -- abstract base class for all KG storage backends."""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

from src.knowledge_graph.common.schemas import Entity, EntityDescription, Triple


class GraphStorageBackend(ABC):
    """Abstract contract for a knowledge graph storage backend.

    Callers interact only through these methods. Swapping backends requires
    only a change to the KG_BACKEND config key.
    """

    @abstractmethod
    def add_node(
        self,
        name: str,
        type: str,
        source: str,
        aliases: Optional[List[str]] = None,
    ) -> None:
        """Add or update a node in the graph.

        If a node with the same name (case-insensitive) exists, increment
        mention_count and append sources/aliases without duplicates.
        First-seen surface form is preserved as canonical.

        Args:
            name: Entity name.
            type: Entity type (must be valid per YAML schema).
            source: Document path where the entity was found.
            aliases: Alternative surface forms.
        """
        ...

    @abstractmethod
    def add_edge(
        self,
        subject: str,
        object: str,
        relation: str,
        source: str,
        weight: float = 1.0,
    ) -> None:
        """Add or update an edge in the graph.

        If an edge between subject and object exists, increment weight and
        append source. Self-edges (subject == object) are silently dropped.

        Args:
            subject: Source entity name.
            object: Target entity name.
            relation: Edge type (must be valid per YAML schema).
            source: Document path where the relation was found.
            weight: Edge weight (default 1.0).
        """
        ...

    @abstractmethod
    def upsert_entities(self, entities: List[Entity]) -> None:
        """Batch upsert entities from an ExtractionResult.

        For each entity, calls add_node with the entity's attributes.

        Args:
            entities: List of Entity objects to upsert.
        """
        ...

    @abstractmethod
    def upsert_triples(self, triples: List[Triple]) -> None:
        """Batch upsert triples from an ExtractionResult.

        For each triple, calls add_edge with the triple's attributes.

        Args:
            triples: List of Triple objects to upsert.
        """
        ...

    @abstractmethod
    def upsert_descriptions(
        self, descriptions: Dict[str, List[EntityDescription]]
    ) -> None:
        """Batch upsert entity descriptions.

        Appends new descriptions to existing ones. Triggers LLM summarization
        when the token budget is exceeded for any entity.

        Args:
            descriptions: Mapping of entity name to new EntityDescription objects.
        """
        ...

    @abstractmethod
    def query_neighbors(self, entity: str, depth: int = 1) -> List[str]:
        """Return entity names reachable within depth hops (forward + backward).

        Args:
            entity: Entity name to start traversal from.
            depth: Maximum traversal depth.

        Returns:
            List of reachable entity names (excluding the input entity).
        """
        ...

    @abstractmethod
    def get_entity(self, name: str) -> Optional[Entity]:
        """Return full entity data or None if not found.

        Lookup is case-insensitive.

        Args:
            name: Entity name to look up.

        Returns:
            Entity object or None.
        """
        ...

    @abstractmethod
    def get_predecessors(self, entity: str) -> List[str]:
        """Return entity names with edges pointing to this entity.

        Args:
            entity: Target entity name.

        Returns:
            List of predecessor entity names.
        """
        ...

    @abstractmethod
    def save(self, path: Path) -> None:
        """Persist the graph to disk.

        Args:
            path: File path for serialization.
        """
        ...

    @abstractmethod
    def load(self, path: Path) -> None:
        """Load a graph from disk, replacing current in-memory state.

        Rebuilds internal indices (case index, alias index) from loaded data.

        Args:
            path: File path to load from.
        """
        ...

    @abstractmethod
    def stats(self) -> dict:
        """Return graph statistics.

        Returns:
            Dict with keys: 'nodes' (int), 'edges' (int),
            'top_entities' (list of (name, mention_count) tuples).
        """
        ...

    def get_all_entities(self) -> List[Entity]:
        """Return all entities in the graph.

        Default implementation iterates all nodes. Backends may override
        for efficiency.

        Returns:
            List of all Entity objects.
        """
        ...

    def get_all_node_names_and_aliases(self) -> Dict[str, str]:
        """Return a mapping of all names and aliases to canonical names.

        Used by the entity matcher to build its pattern set.

        Returns:
            Dict mapping lowercase name/alias -> canonical entity name.
        """
        ...
```

---

### T3: NetworkXBackend Implementation

| Field | Value |
|-------|-------|
| **Task ID** | T3 |
| **Title** | Implement NetworkXBackend |
| **Dependencies** | T1, T2 |
| **Files Created** | `src/knowledge_graph/backends/networkx_backend.py` |
| **REQ Coverage** | REQ-KG-202, REQ-KG-501, REQ-KG-502, REQ-KG-503, REQ-KG-504, REQ-KG-506 |
| **Estimated LOC** | 300 |

**Code Contract -- `src/knowledge_graph/backends/networkx_backend.py`:**

```python
"""NetworkXBackend -- NetworkX DiGraph implementation of GraphStorageBackend."""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Dict, List, Optional

import networkx as nx

from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.common.schemas import Entity, EntityDescription, Triple

logger = logging.getLogger("rag.knowledge_graph.networkx")


class NetworkXBackend(GraphStorageBackend):
    """NetworkX-backed graph storage with orjson serialization.

    Maintains case-insensitive dedup via _case_index and _alias_index.
    Serialization uses NetworkX node-link JSON format via orjson for
    backward compatibility with KnowledgeGraphBuilder.save()/load().
    """

    def __init__(self) -> None:
        self.graph: nx.DiGraph = nx.DiGraph()
        self._case_index: Dict[str, str] = {}  # lowercase -> canonical name
        self._alias_index: Dict[str, str] = {}  # alias -> canonical name

    def _resolve(self, name: str) -> str:
        """Resolve a name to its canonical form via alias + case index.

        Priority: alias index -> case index -> register as new.
        """
        ...

    def add_node(self, name: str, type: str, source: str,
                 aliases: Optional[List[str]] = None) -> None: ...
    def add_edge(self, subject: str, object: str, relation: str,
                 source: str, weight: float = 1.0) -> None: ...
    def upsert_entities(self, entities: List[Entity]) -> None: ...
    def upsert_triples(self, triples: List[Triple]) -> None: ...
    def upsert_descriptions(self, descriptions: Dict[str, List[EntityDescription]]) -> None: ...
    def query_neighbors(self, entity: str, depth: int = 1) -> List[str]: ...
    def get_entity(self, name: str) -> Optional[Entity]: ...
    def get_predecessors(self, entity: str) -> List[str]: ...
    def save(self, path: Path) -> None: ...
    def load(self, path: Path) -> None: ...
    def stats(self) -> dict: ...
    def get_all_entities(self) -> List[Entity]: ...
    def get_all_node_names_and_aliases(self) -> Dict[str, str]: ...
```

**Key invariants:**
- `_resolve()` mirrors the current `KnowledgeGraphBuilder._resolve()` logic: alias expansion, then case-insensitive dedup, first-seen form is canonical.
- `save()` uses `nx.node_link_data()` + `orjson.dumps()` (same as current `KnowledgeGraphBuilder.save()`).
- `load()` uses `orjson.loads()` + `nx.node_link_graph()` then rebuilds `_case_index` and `_alias_index` from node data.
- `upsert_descriptions()` appends to `raw_mentions` on node data and checks token budget; if exceeded, triggers summarization and top-K retention.

---

### T4: Neo4j Backend Stub

| Field | Value |
|-------|-------|
| **Task ID** | T4 |
| **Title** | Write Neo4jBackend stub |
| **Dependencies** | T1, T2 |
| **Files Created** | `src/knowledge_graph/backends/neo4j_backend.py` |
| **REQ Coverage** | REQ-KG-203, REQ-KG-505 |
| **Estimated LOC** | 80 |

**Code Contract -- `src/knowledge_graph/backends/neo4j_backend.py`:**

```python
"""Neo4jBackend -- Phase 2 stub for Neo4j graph storage."""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional

from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.common.schemas import Entity, EntityDescription, Triple


class Neo4jBackend(GraphStorageBackend):
    """Phase 2 stub. All methods raise NotImplementedError."""

    def add_node(self, name: str, type: str, source: str,
                 aliases: Optional[List[str]] = None) -> None:
        raise NotImplementedError("Neo4j backend is Phase 2: not yet implemented")

    def add_edge(self, subject: str, object: str, relation: str,
                 source: str, weight: float = 1.0) -> None:
        raise NotImplementedError("Neo4j backend is Phase 2: not yet implemented")

    # ... (all remaining methods follow the same pattern)
```

---

### T5: Migrate Regex Extractor + EntityExtractor Protocol

| Field | Value |
|-------|-------|
| **Task ID** | T5 |
| **Title** | Migrate regex extractor and define EntityExtractor protocol |
| **Dependencies** | T1 |
| **Files Created** | `src/knowledge_graph/extraction/base.py`, `src/knowledge_graph/extraction/regex_extractor.py` |
| **REQ Coverage** | REQ-KG-301, REQ-KG-303, REQ-KG-304 |
| **Estimated LOC** | 250 |

**Code Contract -- `src/knowledge_graph/extraction/base.py`:**

```python
"""EntityExtractor protocol for all KG extractors."""
from __future__ import annotations
from typing import Protocol, Set, List, runtime_checkable

from src.knowledge_graph.common.schemas import Triple


@runtime_checkable
class EntityExtractor(Protocol):
    """Protocol for entity and relation extraction.

    All extractors in the KG subsystem must satisfy this protocol.
    """

    @property
    def name(self) -> str:
        """Unique extractor identifier for logging and priority resolution."""
        ...

    def extract_entities(self, text: str) -> Set[str]:
        """Extract entity names from text.

        Args:
            text: Input text (a single chunk).

        Returns:
            Set of extracted entity name strings.
        """
        ...

    def extract_relations(
        self, text: str, known_entities: Set[str]
    ) -> List[Triple]:
        """Extract triples from text given a set of known entities.

        Args:
            text: Input text (a single chunk).
            known_entities: Entities already extracted (for relation anchoring).

        Returns:
            List of Triple objects.
        """
        ...
```

**Code Contract -- `src/knowledge_graph/extraction/regex_extractor.py`:**

```python
"""Regex-based entity and relationship extractor.

Migrated from src/core/knowledge_graph.py EntityExtractor.
Preserves all patterns: CamelCase, acronyms, multi-word phrases,
acronym expansion, stopword filtering, sentence-starter filtering,
and relation extraction (is_a, subset_of, used_for, uses, such-as).
"""
from __future__ import annotations
import re
from typing import Dict, List, Optional, Set

from src.knowledge_graph.common.schemas import Triple
from src.knowledge_graph.common.types import SchemaDefinition


class RegexEntityExtractor:
    """Rule-based entity and relationship extractor.

    Implements the EntityExtractor protocol. Preserves all extraction
    behavior from the monolithic EntityExtractor class.

    Args:
        schema: Optional SchemaDefinition for type validation.
        fallback_type: Type assigned when heuristic type is not in schema.
    """

    def __init__(
        self,
        schema: Optional[SchemaDefinition] = None,
        fallback_type: str = "concept",
    ) -> None: ...

    @property
    def name(self) -> str:
        return "regex"

    def extract_entities(self, text: str) -> Set[str]: ...

    def extract_acronym_aliases(self, text: str) -> Dict[str, str]:
        """Find acronym expansions. Returns {acronym: long_form}."""
        ...

    def extract_relations(
        self, text: str, known_entities: Set[str]
    ) -> List[Triple]: ...

    def classify_type(self, name: str) -> str:
        """Heuristic entity type classification.

        Maps to schema types when schema is available, otherwise
        falls back to legacy types (technology, acronym, concept).
        """
        ...
```

---

### T6: Migrate GLiNER Extractor

| Field | Value |
|-------|-------|
| **Task ID** | T6 |
| **Title** | Migrate GLiNER extractor with YAML-derived labels |
| **Dependencies** | T1, T5 |
| **Files Created** | `src/knowledge_graph/extraction/gliner_extractor.py` |
| **REQ Coverage** | REQ-KG-305 |
| **Estimated LOC** | 120 |

**Code Contract -- `src/knowledge_graph/extraction/gliner_extractor.py`:**

```python
"""GLiNER-based zero-shot NER entity extractor.

Migrated from src/core/knowledge_graph.py GLiNEREntityExtractor.
Uses YAML-derived labels instead of hardcoded GLINER_ENTITY_LABELS.
"""
from __future__ import annotations
import re
from typing import Dict, List, Optional, Set

from src.knowledge_graph.common.schemas import Triple
from src.knowledge_graph.common.types import SchemaDefinition
from src.knowledge_graph.common.utils import derive_gliner_labels


class GLiNERExtractor:
    """Zero-shot NER extractor using GLiNER with schema-derived labels.

    Delegates acronym alias detection and relation extraction to
    RegexEntityExtractor.

    Args:
        schema: SchemaDefinition for label derivation.
        runtime_phase: Current runtime phase for filtering active types.
        model_path: Path to the GLiNER model (defaults to config value).
    """

    def __init__(
        self,
        schema: SchemaDefinition,
        runtime_phase: str = "phase_1",
        model_path: Optional[str] = None,
    ) -> None: ...

    @property
    def name(self) -> str:
        return "gliner"

    def extract_entities(self, text: str) -> Set[str]: ...

    def extract_relations(
        self, text: str, known_entities: Set[str]
    ) -> List[Triple]: ...
```

---

### T7: Entity Description Accumulation + Merge Node

| Field | Value |
|-------|-------|
| **Task ID** | T7 |
| **Title** | Write merge node with entity description accumulation logic |
| **Dependencies** | T1, T5, T6 |
| **Files Created** | `src/knowledge_graph/extraction/merge.py` |
| **REQ Coverage** | REQ-KG-310, REQ-KG-311, REQ-KG-400, REQ-KG-401, REQ-KG-402, REQ-KG-403 |
| **Estimated LOC** | 250 |

**Code Contract -- `src/knowledge_graph/extraction/merge.py`:**

```python
"""Merge node: deduplication, validation, and entity description accumulation.

Receives ExtractionResult objects from multiple extractor branches and
produces a single unified ExtractionResult. Also handles entity description
accumulation and LLM summarization triggers.
"""
from __future__ import annotations
import logging
from typing import Dict, List, Optional

from src.knowledge_graph.common.schemas import (
    Entity,
    EntityDescription,
    ExtractionResult,
    Triple,
)
from src.knowledge_graph.common.types import KGConfig, SchemaDefinition
from src.knowledge_graph.common.utils import normalize_alias, validate_type

logger = logging.getLogger("rag.knowledge_graph.merge")

# Default extractor priority (highest confidence first)
DEFAULT_EXTRACTOR_PRIORITY = ["sv_parser", "llm", "gliner", "regex"]


def merge_extraction_results(
    results: List[ExtractionResult],
    schema: SchemaDefinition,
    config: KGConfig,
) -> ExtractionResult:
    """Merge multiple ExtractionResults into a single unified result.

    Deduplication rules:
    1. Entities with the same normalized name are merged (case-insensitive).
    2. Type conflicts resolved by extractor priority (REQ-KG-311).
    3. Triples with same (subject, predicate, object) are merged (weight summed).
    4. Entity descriptions are accumulated (append-only).
    5. Invalid types (not in schema) are re-classified to fallback type with warning.

    Args:
        results: List of ExtractionResult from parallel extractors.
        schema: Loaded SchemaDefinition for type validation.
        config: KGConfig with extractor_priority and fallback_type.

    Returns:
        Single merged ExtractionResult.
    """
    ...


def _deduplicate_entities(
    all_entities: List[Entity],
    schema: SchemaDefinition,
    config: KGConfig,
) -> List[Entity]:
    """Deduplicate entities by normalized name, resolving type conflicts."""
    ...


def _deduplicate_triples(
    all_triples: List[Triple],
    schema: SchemaDefinition,
    config: KGConfig,
) -> List[Triple]:
    """Deduplicate triples by (subject, predicate, object) key."""
    ...


def _accumulate_descriptions(
    all_entities: List[Entity],
) -> Dict[str, List[EntityDescription]]:
    """Collect entity descriptions across all extraction results."""
    ...


def trigger_summarization_if_needed(
    entity_name: str,
    mentions: List[EntityDescription],
    current_summary: str,
    config: KGConfig,
) -> tuple[str, List[EntityDescription]]:
    """Check token budget and trigger LLM summarization if exceeded.

    Args:
        entity_name: Name of the entity.
        mentions: All raw mentions for this entity.
        current_summary: Current summary (may be empty).
        config: KGConfig with token budget and top-K settings.

    Returns:
        Tuple of (updated_summary, retained_mentions) where retained_mentions
        is the top-K selection after summarization (or all mentions if budget
        not exceeded).
    """
    ...


def _score_mentions_for_retention(
    mentions: List[EntityDescription],
    top_k: int,
) -> List[EntityDescription]:
    """Score and select top-K mentions by recency and source diversity.

    Args:
        mentions: All raw mentions.
        top_k: Number of mentions to retain.

    Returns:
        Top-K EntityDescription objects.
    """
    ...
```

---

### T8: spaCy Entity Matcher

| Field | Value |
|-------|-------|
| **Task ID** | T8 |
| **Title** | Write spaCy rule-based entity matcher |
| **Dependencies** | T1 |
| **Files Created** | `src/knowledge_graph/query/entity_matcher.py` |
| **REQ Coverage** | REQ-KG-600, REQ-KG-601 |
| **Estimated LOC** | 130 |

**Code Contract -- `src/knowledge_graph/query/entity_matcher.py`:**

```python
"""spaCy-based rule-based entity matcher.

Replaces substring matching with token-boundary matching for
higher precision (e.g., 'AXI' does not match inside 'TAXIING').
"""
from __future__ import annotations
import logging
from typing import Dict, List

logger = logging.getLogger("rag.knowledge_graph.entity_matcher")


class SpacyEntityMatcher:
    """Token-boundary entity matcher using spaCy Matcher/PhraseMatcher.

    Builds patterns from graph node names and aliases. Performs
    case-insensitive, token-boundary matching on query text.

    Args:
        entity_index: Mapping of lowercase name/alias -> canonical entity name.
    """

    def __init__(self, entity_index: Dict[str, str]) -> None:
        """Initialize the matcher with entity patterns.

        Loads spaCy blank('en') model (no transformer needed).
        Builds PhraseMatcher patterns from all entity names and aliases.
        """
        ...

    def match(self, query: str) -> List[str]:
        """Find entities mentioned in the query using token-boundary matching.

        Args:
            query: User query text.

        Returns:
            List of canonical entity names found in the query.
            Longer matches are preferred over shorter ones.
        """
        ...

    def rebuild(self, entity_index: Dict[str, str]) -> None:
        """Rebuild patterns from an updated entity index.

        Called when the graph is updated with new nodes/aliases.

        Args:
            entity_index: Updated mapping of lowercase name/alias -> canonical name.
        """
        ...
```

---

### T9: Query Expander (Migrate + Enhance)

| Field | Value |
|-------|-------|
| **Task ID** | T9 |
| **Title** | Write GraphQueryExpander with spaCy matcher integration |
| **Dependencies** | T1, T2, T8, T10 |
| **Files Created** | `src/knowledge_graph/query/expander.py` |
| **REQ Coverage** | REQ-KG-604, REQ-KG-605, REQ-KG-606, REQ-KG-607, REQ-KG-608 |
| **Estimated LOC** | 150 |

**Code Contract -- `src/knowledge_graph/query/expander.py`:**

```python
"""GraphQueryExpander -- entity matching and graph-based query expansion.

Migrated from src/core/knowledge_graph.py GraphQueryExpander.
Enhanced with spaCy token-boundary matching and entity descriptions.
"""
from __future__ import annotations
import logging
from typing import List, Optional

from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.common.types import KGConfig
from src.knowledge_graph.query.entity_matcher import SpacyEntityMatcher
from src.knowledge_graph.query.sanitizer import QuerySanitizer

logger = logging.getLogger("rag.knowledge_graph.expander")


class GraphQueryExpander:
    """Find entities in a query and expand via graph neighbors.

    Uses spaCy entity matcher for token-boundary matching (fast path).
    Expansion traverses the graph outward and inward from matched entities.
    Fan-out is bounded by config (max_expansion_depth, max_expansion_terms).

    Args:
        backend: The graph storage backend to query.
        config: KGConfig with expansion settings.
    """

    def __init__(self, backend: GraphStorageBackend, config: KGConfig) -> None:
        ...

    def match_entities(self, query: str) -> List[str]:
        """Match graph entities in the query using spaCy matcher.

        Args:
            query: User query text.

        Returns:
            List of canonical entity names matched in the query.
        """
        ...

    def expand(self, query: str, depth: Optional[int] = None) -> List[str]:
        """Return related entity names to augment the search query.

        Traverses graph outward and inward from matched entities up to
        depth hops. Returns only terms not already in the query.
        Respects fan-out limits from config.

        Args:
            query: User query text.
            depth: Override for max_expansion_depth (uses config default if None).

        Returns:
            List of expansion terms (at most max_expansion_terms).
        """
        ...

    def get_context_summary(
        self, entities: List[str], max_lines: int = 5
    ) -> str:
        """Build a text summary of entity relationships and descriptions.

        Uses current_summary when available, raw_mentions fallback otherwise.

        Args:
            entities: Entity names to summarize.
            max_lines: Maximum lines in the summary.

        Returns:
            Summary string.
        """
        ...

    def rebuild_matcher(self) -> None:
        """Rebuild the spaCy matcher from the current graph state.

        Called after graph updates to ensure new entities are matchable.
        """
        ...
```

---

### T10: Query Sanitizer

| Field | Value |
|-------|-------|
| **Task ID** | T10 |
| **Title** | Write query sanitizer with normalization and alias expansion |
| **Dependencies** | T1 |
| **Files Created** | `src/knowledge_graph/query/sanitizer.py` |
| **REQ Coverage** | REQ-KG-603 |
| **Estimated LOC** | 100 |

**Code Contract -- `src/knowledge_graph/query/sanitizer.py`:**

```python
"""Query sanitization: normalization, alias expansion, and fan-out control."""
from __future__ import annotations
from typing import Dict, List


class QuerySanitizer:
    """Normalizes query text for entity matching.

    Provides case-insensitive comparison, alias expansion,
    whitespace normalization, and punctuation stripping.

    Args:
        alias_index: Mapping of alias -> canonical entity name.
    """

    def __init__(self, alias_index: Dict[str, str]) -> None: ...

    def normalize(self, query: str) -> str:
        """Normalize a query for matching without modifying the original.

        Lowercases, normalizes whitespace, strips matching-irrelevant
        punctuation (hyphens, underscores replaced with spaces).

        Args:
            query: Raw user query.

        Returns:
            Normalized query string for internal matching use.
        """
        ...

    def expand_aliases(self, terms: List[str]) -> List[str]:
        """Expand matched terms by adding their aliases and canonical forms.

        Args:
            terms: List of matched entity names.

        Returns:
            Expanded list including alias variants.
        """
        ...

    def rebuild(self, alias_index: Dict[str, str]) -> None:
        """Rebuild the alias index from updated graph data.

        Args:
            alias_index: Updated mapping of alias -> canonical entity name.
        """
        ...
```

---

### T11: Public API (__init__.py) with Lazy Singleton

| Field | Value |
|-------|-------|
| **Task ID** | T11 |
| **Title** | Write public API with lazy singleton dispatcher |
| **Dependencies** | T3, T4, T9 |
| **Files Created/Modified** | `src/knowledge_graph/__init__.py` (replace placeholder) |
| **REQ Coverage** | REQ-KG-204 |
| **Estimated LOC** | 130 |

**Code Contract -- `src/knowledge_graph/__init__.py`:**

```python
"""Public API for the knowledge graph subsystem.

The ingestion pipeline (Node 13) and retrieval pipeline (Stage 2)
import only from this module. Backend selection is controlled by
the KG_BACKEND config key.

Dispatcher pattern:
    get_graph_backend() is a lazy singleton that constructs the configured
    backend on first call. get_query_expander() creates an expander bound
    to the singleton backend.
"""
from __future__ import annotations
import logging
from typing import Optional

from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.common.schemas import (
    Entity,
    EntityDescription,
    ExtractionResult,
    Triple,
)
from src.knowledge_graph.common.types import KGConfig, SchemaDefinition

logger = logging.getLogger("rag.knowledge_graph")

_backend: Optional[GraphStorageBackend] = None
_expander = None  # GraphQueryExpander | None


class _NoOpBackend(GraphStorageBackend):
    """Pass-through backend used when KG_BACKEND is empty or 'none'.

    All methods are no-ops or return empty results.
    """
    def add_node(self, name, type, source, aliases=None): pass
    def add_edge(self, subject, object, relation, source, weight=1.0): pass
    def upsert_entities(self, entities): pass
    def upsert_triples(self, triples): pass
    def upsert_descriptions(self, descriptions): pass
    def query_neighbors(self, entity, depth=1): return []
    def get_entity(self, name): return None
    def get_predecessors(self, entity): return []
    def save(self, path): pass
    def load(self, path): pass
    def stats(self): return {"nodes": 0, "edges": 0, "top_entities": []}


def get_graph_backend() -> GraphStorageBackend:
    """Return the process-wide graph backend singleton.

    Constructs the backend on first call based on KG_BACKEND config.

    Returns:
        The active GraphStorageBackend instance.

    Raises:
        ValueError: If KG_BACKEND is set to an unknown value.
    """
    ...


def get_query_expander():
    """Return the process-wide query expander singleton.

    Creates a GraphQueryExpander bound to the singleton backend
    on first call.

    Returns:
        The active GraphQueryExpander instance.
    """
    ...


def _build_kg_config() -> KGConfig:
    """Build KGConfig from the project configuration system."""
    ...


def _load_schema(config: KGConfig) -> SchemaDefinition:
    """Load and validate the YAML schema from config.schema_path."""
    ...


__all__ = [
    "get_graph_backend",
    "get_query_expander",
    "Entity",
    "EntityDescription",
    "ExtractionResult",
    "Triple",
    "KGConfig",
    "SchemaDefinition",
    "GraphStorageBackend",
]
```

---

### T12: YAML Schema + Loader

| Field | Value |
|-------|-------|
| **Task ID** | T12 |
| **Title** | Write YAML schema file and schema loader with validation |
| **Dependencies** | None (schema file) / T1 (loader uses types.py) |
| **Files Created** | `config/kg_schema.yaml`, validation logic in `common/types.py` or `__init__.py` |
| **REQ Coverage** | REQ-KG-100, REQ-KG-101, REQ-KG-102, REQ-KG-103, REQ-KG-104, REQ-KG-105, REQ-KG-106, REQ-KG-107, REQ-KG-108, REQ-KG-109, REQ-KG-110, REQ-KG-111 |
| **Estimated LOC** | 250 (YAML) + 100 (loader/validation) = 350 |

**Code Contract -- schema loader (in `common/types.py`):**

```python
def load_schema(path: str) -> SchemaDefinition:
    """Load and validate the YAML schema from a file path.

    Validation rules (REQ-KG-109):
    - No duplicate node type names.
    - No duplicate edge type names.
    - All required fields present on every type definition.
    - category must be 'structural' or 'semantic'.
    - phase must be 'phase_1', 'phase_1b', or 'phase_2'.
    - No duplicate gliner_label values.
    - Warning if a gliner_label collides with another type's name.

    Args:
        path: Path to the YAML schema file.

    Returns:
        Validated SchemaDefinition.

    Raises:
        FileNotFoundError: If the schema file does not exist.
        ValueError: If schema validation fails (with specific error message).
    """
    ...
```

**YAML file:** Contains the full schema from Appendix A of the spec (41 node types, 22 edge types with phase tags, categories, descriptions, gliner_labels, extraction_hints, and source/target type constraints).

---

### T13: Obsidian Export (Migrate)

| Field | Value |
|-------|-------|
| **Task ID** | T13 |
| **Title** | Migrate Obsidian export to accept GraphStorageBackend |
| **Dependencies** | T1, T2 |
| **Files Created** | `src/knowledge_graph/export/obsidian.py` |
| **REQ Coverage** | REQ-KG-800 |
| **Estimated LOC** | 100 |

**Code Contract -- `src/knowledge_graph/export/obsidian.py`:**

```python
"""Obsidian export -- one .md file per entity with [[wikilinks]].

Migrated from src/core/knowledge_graph.py export_obsidian().
Enhanced with entity descriptions (current_summary or raw_mentions fallback).
"""
from __future__ import annotations
from pathlib import Path

from src.knowledge_graph.backend import GraphStorageBackend


def export_obsidian(backend: GraphStorageBackend, output_dir: Path) -> int:
    """Write one .md file per entity with [[wikilinks]] to neighbors.

    Includes entity descriptions: uses current_summary when available,
    falls back to concatenated raw_mentions text.

    Args:
        backend: The graph storage backend (not a raw NetworkX graph).
        output_dir: Directory to write markdown files.

    Returns:
        Number of files written.
    """
    ...
```

---

### T14: Community Detection Stubs (Phase 2)

| Field | Value |
|-------|-------|
| **Task ID** | T14 |
| **Title** | Write community detection and summarizer stubs |
| **Dependencies** | T1 |
| **Files Created** | `src/knowledge_graph/community/detector.py`, `src/knowledge_graph/community/summarizer.py` |
| **REQ Coverage** | REQ-KG-703 |
| **Estimated LOC** | 60 |

**Code Contract -- `src/knowledge_graph/community/detector.py`:**

```python
"""Phase 2 stub: Leiden community detection."""
from __future__ import annotations
from src.knowledge_graph.backend import GraphStorageBackend


class CommunityDetector:
    """Detects communities in the knowledge graph using Leiden algorithm.

    Phase 2 stub -- all methods raise NotImplementedError.
    """

    def __init__(self, backend: GraphStorageBackend) -> None:
        self._backend = backend

    def detect(self) -> dict:
        """Compute communities and assign each entity to a community.

        Returns:
            Dict mapping community_id -> list of entity names.

        Raises:
            NotImplementedError: Phase 2.
        """
        raise NotImplementedError("Community detection is Phase 2: not yet implemented")
```

**Code Contract -- `src/knowledge_graph/community/summarizer.py`:**

```python
"""Phase 2 stub: LLM community summarization."""
from __future__ import annotations


class CommunitySummarizer:
    """Generates LLM summaries for graph communities.

    Phase 2 stub -- all methods raise NotImplementedError.
    """

    def summarize(self, community_id: str, entity_names: list[str]) -> str:
        """Generate a thematic summary for a community.

        Raises:
            NotImplementedError: Phase 2.
        """
        raise NotImplementedError("Community summarization is Phase 2: not yet implemented")
```

---

### T15: LLM Extractor Stub + LLM Query Fallback Stub (Phase 1b)

| Field | Value |
|-------|-------|
| **Task ID** | T15 |
| **Title** | Write LLM extractor and LLM query fallback stubs |
| **Dependencies** | T1 |
| **Files Created** | `src/knowledge_graph/extraction/llm_extractor.py`, `src/knowledge_graph/query/llm_fallback.py` |
| **REQ Coverage** | REQ-KG-306 (stub), REQ-KG-602 (stub) |
| **Estimated LOC** | 100 |

**Code Contract -- `src/knowledge_graph/extraction/llm_extractor.py`:**

```python
"""Phase 1b stub: LLM structured-output entity extractor."""
from __future__ import annotations
from typing import List, Set

from src.knowledge_graph.common.schemas import Triple
from src.knowledge_graph.common.types import SchemaDefinition


class LLMExtractor:
    """LLM-based entity and triple extractor using structured JSON output.

    Phase 1b stub -- extract methods raise NotImplementedError.

    Args:
        schema: SchemaDefinition for prompt construction.
        runtime_phase: Current runtime phase.
    """

    def __init__(self, schema: SchemaDefinition, runtime_phase: str = "phase_1b") -> None:
        self._schema = schema
        self._runtime_phase = runtime_phase

    @property
    def name(self) -> str:
        return "llm"

    def extract_entities(self, text: str) -> Set[str]:
        raise NotImplementedError("LLM extractor is Phase 1b: not yet implemented")

    def extract_relations(self, text: str, known_entities: Set[str]) -> List[Triple]:
        raise NotImplementedError("LLM extractor is Phase 1b: not yet implemented")
```

**Code Contract -- `src/knowledge_graph/query/llm_fallback.py`:**

```python
"""Phase 1b stub: LLM fallback entity matcher."""
from __future__ import annotations
from typing import List


class LLMFallbackMatcher:
    """LLM-based entity identification for queries with no spaCy matches.

    Phase 1b stub -- match method raises NotImplementedError.
    """

    def match(self, query: str, entity_names: List[str]) -> List[str]:
        """Identify entities in the query using LLM.

        Raises:
            NotImplementedError: Phase 1b.
        """
        raise NotImplementedError("LLM query fallback is Phase 1b: not yet implemented")
```

---

### T16: SV Parser Extractor Stub (Phase 1b)

| Field | Value |
|-------|-------|
| **Task ID** | T16 |
| **Title** | Write SV parser extractor stub |
| **Dependencies** | T1 |
| **Files Created** | `src/knowledge_graph/extraction/sv_parser.py` |
| **REQ Coverage** | REQ-KG-308 (stub) |
| **Estimated LOC** | 60 |

**Code Contract -- `src/knowledge_graph/extraction/sv_parser.py`:**

```python
"""Phase 1b stub: SystemVerilog tree-sitter parser extractor."""
from __future__ import annotations
from typing import List, Set

from src.knowledge_graph.common.schemas import Triple
from src.knowledge_graph.common.types import SchemaDefinition


class SVParserExtractor:
    """Deterministic structural extractor using tree-sitter-verilog.

    Phase 1b stub -- extract methods raise NotImplementedError.

    Args:
        schema: SchemaDefinition for type validation.
    """

    def __init__(self, schema: SchemaDefinition) -> None:
        self._schema = schema

    @property
    def name(self) -> str:
        return "sv_parser"

    def extract_entities(self, text: str) -> Set[str]:
        raise NotImplementedError("SV parser is Phase 1b: not yet implemented")

    def extract_relations(self, text: str, known_entities: Set[str]) -> List[Triple]:
        raise NotImplementedError("SV parser is Phase 1b: not yet implemented")
```

---

### T17: Update Ingest Pipeline Nodes (Node 10, Node 13)

| Field | Value |
|-------|-------|
| **Task ID** | T17 |
| **Title** | Update Node 10 (extraction) and Node 13 (storage) to use new KG package |
| **Dependencies** | T11, T5, T6, T7 |
| **Files Modified** | `src/ingest/embedding/nodes/knowledge_graph_extraction.py`, `src/ingest/embedding/nodes/knowledge_graph_storage.py`, `src/ingest/embedding/state.py` |
| **REQ Coverage** | REQ-KG-900, REQ-KG-901, REQ-KG-902 |
| **Estimated LOC** | 150 |

**Code Contract -- Node 10 changes:**

```python
# src/ingest/embedding/nodes/knowledge_graph_extraction.py
# Key change: import from src.knowledge_graph.extraction instead of src.core.knowledge_graph

from src.knowledge_graph.extraction import ExtractionPipeline
from src.knowledge_graph.common.schemas import ExtractionResult

def knowledge_graph_extraction_node(state: EmbeddingPipelineState) -> dict:
    """Extract entities and triples from chunks using the multi-extractor pipeline.

    Stores ExtractionResult in state['kg_extraction_result'].
    """
    ...
```

**Code Contract -- Node 13 changes:**

```python
# src/ingest/embedding/nodes/knowledge_graph_storage.py
# Key change: use get_graph_backend() instead of KnowledgeGraphBuilder

from src.knowledge_graph import get_graph_backend

def knowledge_graph_storage_node(state: EmbeddingPipelineState) -> dict:
    """Store extraction results in the graph backend.

    Reads kg_extraction_result from state. Falls back to kg_triples
    for backward compatibility during migration.
    """
    ...
```

**Code Contract -- State changes:**

```python
# src/ingest/embedding/state.py
# Add kg_extraction_result field alongside existing kg_triples

class EmbeddingPipelineState(TypedDict, total=False):
    # ... existing fields ...
    kg_triples: List[Dict[str, Any]]  # Kept for backward compat
    kg_extraction_result: Optional[Any]  # ExtractionResult | None (new)
```

---

### T18: Update Retrieval Pipeline (Stage 2 KG Expansion)

| Field | Value |
|-------|-------|
| **Task ID** | T18 |
| **Title** | Update retrieval Stage 2 to use get_query_expander() |
| **Dependencies** | T11, T9 |
| **Files Modified** | `src/retrieval/pipeline/rag_chain.py` |
| **REQ Coverage** | REQ-KG-903, REQ-KG-607 |
| **Estimated LOC** | 50 |

**Code Contract -- rag_chain.py changes:**

```python
# Key change: replace direct KG construction with lazy singleton

# Before:
# from src.core.knowledge_graph import KnowledgeGraphBuilder, GraphQueryExpander

# After:
from src.knowledge_graph import get_query_expander

# In __init__ or startup:
# self._kg_expander = get_query_expander()

# In Stage 2:
# expanded_terms = self._kg_expander.expand(query)
# bm25_query += " ".join(expanded_terms[:config.max_expansion_terms])
```

---

### T19: Update config/settings.py

| Field | Value |
|-------|-------|
| **Task ID** | T19 |
| **Title** | Add KG configuration keys to config/settings.py |
| **Dependencies** | T1 |
| **Files Modified** | `config/settings.py` |
| **REQ Coverage** | REQ-KG-904 |
| **Estimated LOC** | 60 |

**Code Contract:**

```python
# config/settings.py -- new keys to add

# --- Knowledge Graph Configuration ---
KG_BACKEND = os.environ.get("RAG_KG_BACKEND", "networkx")
KG_SCHEMA_PATH = os.environ.get("RAG_KG_SCHEMA_PATH", str(PROJECT_ROOT / "config" / "kg_schema.yaml"))
KG_ENABLE_REGEX_EXTRACTOR = os.environ.get("RAG_KG_ENABLE_REGEX_EXTRACTOR", "true").lower() in ("true", "1", "yes")
KG_ENABLE_GLINER_EXTRACTOR = os.environ.get("RAG_KG_ENABLE_GLINER_EXTRACTOR", "false").lower() in ("true", "1", "yes")
KG_ENABLE_LLM_EXTRACTOR = os.environ.get("RAG_KG_ENABLE_LLM_EXTRACTOR", "false").lower() in ("true", "1", "yes")
KG_ENABLE_SV_PARSER = os.environ.get("RAG_KG_ENABLE_SV_PARSER", "false").lower() in ("true", "1", "yes")
KG_ENTITY_DESCRIPTION_TOKEN_BUDGET = int(os.environ.get("RAG_KG_ENTITY_DESCRIPTION_TOKEN_BUDGET", "512"))
KG_ENTITY_DESCRIPTION_TOP_K_MENTIONS = int(os.environ.get("RAG_KG_ENTITY_DESCRIPTION_TOP_K_MENTIONS", "5"))
KG_MAX_EXPANSION_DEPTH = int(os.environ.get("RAG_KG_MAX_EXPANSION_DEPTH", "1"))
KG_MAX_EXPANSION_TERMS = int(os.environ.get("RAG_KG_MAX_EXPANSION_TERMS", "3"))
KG_ENABLE_LLM_QUERY_FALLBACK = os.environ.get("RAG_KG_ENABLE_LLM_QUERY_FALLBACK", "false").lower() in ("true", "1", "yes")
KG_LLM_FALLBACK_TIMEOUT_MS = int(os.environ.get("RAG_KG_LLM_FALLBACK_TIMEOUT_MS", "1000"))
KG_ENABLE_GLOBAL_RETRIEVAL = os.environ.get("RAG_KG_ENABLE_GLOBAL_RETRIEVAL", "false").lower() in ("true", "1", "yes")
KG_RUNTIME_PHASE = os.environ.get("RAG_KG_RUNTIME_PHASE", "phase_1")
```

---

### T20: Backward Compatibility Shim

| Field | Value |
|-------|-------|
| **Task ID** | T20 |
| **Title** | Replace src/core/knowledge_graph.py with re-export shim |
| **Dependencies** | T11, T3, T5, T6, T9, T13 |
| **Files Modified** | `src/core/knowledge_graph.py` |
| **REQ Coverage** | REQ-KG-207 |
| **Estimated LOC** | 50 |

**Code Contract -- `src/core/knowledge_graph.py` (replacement):**

```python
"""Backward compatibility shim for src.core.knowledge_graph.

All public names are re-exported from src.knowledge_graph.
This module emits a DeprecationWarning on first import.

Callers should update imports to use src.knowledge_graph directly.
"""
import warnings

warnings.warn(
    "Importing from src.core.knowledge_graph is deprecated. "
    "Use src.knowledge_graph instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export all public names for backward compatibility
from src.knowledge_graph.backends.networkx_backend import NetworkXBackend as KnowledgeGraphBuilder
from src.knowledge_graph.query.expander import GraphQueryExpander
from src.knowledge_graph.extraction.regex_extractor import RegexEntityExtractor as EntityExtractor
from src.knowledge_graph.extraction.gliner_extractor import GLiNERExtractor as GLiNEREntityExtractor
from src.knowledge_graph.export.obsidian import export_obsidian

__all__ = [
    "KnowledgeGraphBuilder",
    "GraphQueryExpander",
    "EntityExtractor",
    "GLiNEREntityExtractor",
    "export_obsidian",
]
```

---

## 4. Integration Design

### 4.1 Ingestion Pipeline Integration

**Current flow (Node 10):**
```
knowledge_graph_extraction_node(state)
  -> EntityExtractor().extract_entities(chunk)
  -> EntityExtractor().extract_relations(chunk, entities)
  -> state["kg_triples"] = list of dict triples
```

**New flow (Node 10):**
```
knowledge_graph_extraction_node(state)
  -> ExtractionPipeline(config).run(chunks)
     -> LangGraph subgraph: [regex | gliner | llm* | sv_parser*] -> merge
  -> state["kg_extraction_result"] = ExtractionResult
```

**Current flow (Node 13):**
```
knowledge_graph_storage_node(state)
  -> kg_builder = KnowledgeGraphBuilder(use_gliner=...)
  -> for chunk: kg_builder.add_chunk(text, source)
  -> kg_builder.save(path)
```

**New flow (Node 13):**
```
knowledge_graph_storage_node(state)
  -> backend = get_graph_backend()
  -> result = state["kg_extraction_result"]
  -> backend.upsert_entities(result.entities)
  -> backend.upsert_triples(result.triples)
  -> backend.upsert_descriptions(result.descriptions)
  -> backend.save(path)
```

### 4.2 Retrieval Pipeline Integration

**Current flow (Stage 2):**
```
kg_builder = KnowledgeGraphBuilder.load(KG_PATH)
expander = GraphQueryExpander(kg_builder.graph)
expanded = expander.expand(query)
bm25_query += " ".join(expanded[:3])
```

**New flow (Stage 2):**
```
expander = get_query_expander()
expanded = expander.expand(query)
bm25_query += " ".join(expanded)  # fan-out limit applied internally
```

### 4.3 ExtractionPipeline LangGraph Subgraph

The `ExtractionPipeline` (in `src/knowledge_graph/extraction/__init__.py`) compiles a LangGraph StateGraph:

```python
class ExtractionPipeline:
    """Compiles and runs the multi-extractor LangGraph subgraph."""

    def __init__(self, config: KGConfig, schema: SchemaDefinition) -> None:
        """Compile the subgraph based on enabled extractors."""
        ...

    def run(self, chunks: List[ProcessedChunk]) -> ExtractionResult:
        """Run all enabled extractors and merge results.

        Args:
            chunks: Document chunks to extract from.

        Returns:
            Merged ExtractionResult.
        """
        ...
```

Subgraph topology:
```text
START -> fan_out -> [regex_branch?, gliner_branch?, llm_branch?, sv_branch?] -> merge -> END
```

Each branch runs one extractor and produces an `ExtractionResult`. The merge node (T7) combines all branch outputs.

---

## 5. Migration Plan

### 5.1 Sequence

1. **T1** creates the package skeleton -- no functional changes, no imports broken.
2. **T2-T4** create the backend layer. No callers use it yet.
3. **T5-T7** migrate extractors and create merge node. No callers use them yet.
4. **T8-T10** create query components. No callers use them yet.
5. **T11** wires up the public API. The new package is now usable.
6. **T12** creates the YAML schema. Required by extractors at runtime.
7. **T13** migrates Obsidian export.
8. **T17-T18** switch the ingestion and retrieval pipelines to use the new package.
9. **T19** adds config keys.
10. **T20** replaces `src/core/knowledge_graph.py` with the shim. This is the last step to ensure nothing breaks.

### 5.2 Backward Compatibility

- `src/core/knowledge_graph.py` becomes a thin shim (T20) that re-exports all public names.
- The shim emits `DeprecationWarning` on first import.
- `KnowledgeGraphBuilder` is aliased to `NetworkXBackend` (which preserves the same save/load format).
- `GraphQueryExpander` is re-exported from the new location.
- `EntityExtractor` is aliased to `RegexEntityExtractor`.
- `GLiNEREntityExtractor` is aliased to `GLiNERExtractor`.
- `export_obsidian` is re-exported from the new location.
- Pipeline state adds `kg_extraction_result` alongside existing `kg_triples` (T17). Node 13 falls back to `kg_triples` if `kg_extraction_result` is absent.

### 5.3 Graph File Compatibility

- `NetworkXBackend.save()` uses the same `nx.node_link_data()` + `orjson.dumps()` format as `KnowledgeGraphBuilder.save()`.
- `NetworkXBackend.load()` can read files saved by `KnowledgeGraphBuilder.save()` and vice versa.
- Entity descriptions are stored as additional node attributes in the JSON. Legacy graphs without descriptions load correctly (empty `raw_mentions`, empty `current_summary`).

---

## 6. Risk Mitigations

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| **Circular imports between subpackages** | Medium | High (blocks all imports) | Package skeleton (T1) establishes dependency direction: `common/` has no upward imports; `extraction/`, `query/`, `backends/`, `export/` depend on `common/` and `backend.py`; `__init__.py` imports from all subpackages. Validated by T1 before other tasks start. |
| **Merge node dedup produces incorrect results** | Medium | High (corrupts graph) | Conservative strategy: alias dedup + case-insensitive matching only in Phase 1. Embedding similarity deferred to Phase 1b (REQ-KG-312). Merge decisions logged for debugging. Extensive merge node tests (REQ-KG-1105). |
| **spaCy model load time at retrieval startup** | Low | Medium (delays first query) | Use `spacy.blank("en")` with `PhraseMatcher` patterns only -- no transformer model, ~0ms load time. If `en_core_web_sm` is needed for tokenization, lazy-load on first query. |
| **Backward compat shim breaks existing callers** | Low | High (production breakage) | Shim is the last task (T20). All re-exports tested with backward compatibility tests (REQ-KG-1107). The shim preserves class names via aliases. |
| **YAML schema validation too strict at startup** | Low | Medium (blocks startup on minor issues) | Validation distinguishes errors (missing required fields, duplicates) from warnings (unused types, gliner_label collisions). Only errors block startup. |
| **ExtractionPipeline LangGraph compilation overhead** | Low | Low (slows first extraction) | Pipeline compiled once in `__init__` and reused. Compilation typically < 50ms for a 4-branch subgraph. |
| **Entity description token counting inaccuracy** | Medium | Low (summarization triggers too early/late) | Use `tiktoken` or simple word-count heuristic (1 token per 0.75 words). Exact token counting is not critical -- the budget is a soft trigger. |
| **Config key naming conflicts with existing settings** | Low | Medium | All new keys use `KG_` prefix or `kg.` namespace. Existing `KG_ENABLED`, `KG_PATH` are preserved and consumed by the new package. |

---

## 7. Requirement Traceability Summary

| Task | Requirements Covered |
|------|---------------------|
| T1 | REQ-KG-200, REQ-KG-205, REQ-KG-206, REQ-KG-208 |
| T2 | REQ-KG-201, REQ-KG-500, REQ-KG-405 |
| T3 | REQ-KG-202, REQ-KG-501, REQ-KG-502, REQ-KG-503, REQ-KG-504, REQ-KG-506 |
| T4 | REQ-KG-203, REQ-KG-505 |
| T5 | REQ-KG-301, REQ-KG-303, REQ-KG-304 |
| T6 | REQ-KG-305 |
| T7 | REQ-KG-310, REQ-KG-311, REQ-KG-400, REQ-KG-401, REQ-KG-402, REQ-KG-403 |
| T8 | REQ-KG-600, REQ-KG-601 |
| T9 | REQ-KG-604, REQ-KG-605, REQ-KG-606, REQ-KG-607, REQ-KG-608 |
| T10 | REQ-KG-603 |
| T11 | REQ-KG-204 |
| T12 | REQ-KG-100, REQ-KG-101, REQ-KG-102, REQ-KG-103, REQ-KG-104, REQ-KG-105, REQ-KG-106, REQ-KG-107, REQ-KG-108, REQ-KG-109, REQ-KG-110, REQ-KG-111 |
| T13 | REQ-KG-800 |
| T14 | REQ-KG-703 |
| T15 | REQ-KG-306 (stub), REQ-KG-602 (stub) |
| T16 | REQ-KG-308 (stub) |
| T17 | REQ-KG-900, REQ-KG-901, REQ-KG-902, REQ-KG-300, REQ-KG-302 |
| T18 | REQ-KG-903, REQ-KG-607 |
| T19 | REQ-KG-904 |
| T20 | REQ-KG-207 |

**Phase 1b stub coverage:** REQ-KG-306, REQ-KG-308, REQ-KG-602 (stubs created in T15, T16).
**Phase 2 stub coverage:** REQ-KG-703 (T14), REQ-KG-203/505 (T4).
**Not covered (deferred to implementation):** REQ-KG-404 (retrieval-time usage -- addressed by T9 contract), REQ-KG-905 (CLI/UI parity -- cross-cutting concern), REQ-KG-1000--1003 (performance -- validated in testing phase), REQ-KG-1100--1107 (testing -- covered by test plan document).
