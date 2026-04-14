# Knowledge Graph Subsystem — Implementation Reference

## Document Information

| Field | Value |
|-------|-------|
| System | RagWeave Knowledge Graph Subsystem |
| Document Type | Implementation Source-of-Truth |
| Source of Truth | `KNOWLEDGE_GRAPH_DESIGN.md` (task decomposition + code contracts) |
| Companion | `KNOWLEDGE_GRAPH_SPEC_SUMMARY.md`, `KNOWLEDGE_GRAPH_DESIGN.md` |
| Date | 2026-04-08 |
| Status | Draft — Phase 1 |

This document bridges design contracts to code. A developer should be able to implement each task by reading the corresponding section here — without needing to cross-reference the design doc for implementation detail.

---

## 1. Implementation Overview

### 1.1 Ordered Execution Sequence

Execute in group order. Within a group, tasks are independent and can run in parallel.

| Group | Tasks | Block Until |
|-------|-------|-------------|
| **G0** | T1, T12 | — |
| **G1** | T2, T5, T6, T8, T10, T14, T15, T16, T19 | T1 complete |
| **G2** | T3, T4, T7, T9, T13 | T2 (for T3/T4/T13), T5+T6 (for T7), T8+T10 (for T9) |
| **G3** | T11 | T3, T9 |
| **G4** | T17, T18, T20 | T11 |

### 1.2 Phase Scope

**Phase 1 (full implementation):** T1–T13, T17–T20  
**Phase 1b (stub only):** T15, T16  
**Phase 2 (stub only):** T4, T14  

### 1.3 Dependency Map (Quick Reference)

```
T1 ──> T2 ──> T3 ──> T11
       T2 ──> T4 (stub)
T1 ──> T5 ──> T7
T1 ──> T6 ──> T7
T7 ──────────> T11 (via T3)
T1 ──> T8 ──> T9
T1 ──> T10 ──> T9
T9 ──────────> T11
T11 ──> T17, T18, T20
T1 ──> T12 (no other deps)
T1 ──> T13
T1 ──> T14, T15, T16 (stubs)
T1 ──> T19
```

---

## 2. Per-Task Implementation Reference

---

### T1: Package Skeleton + Common Contracts

**Files to create:**

```
src/knowledge_graph/__init__.py              # placeholder only
src/knowledge_graph/backend.py               # empty placeholder
src/knowledge_graph/common/__init__.py
src/knowledge_graph/common/schemas.py
src/knowledge_graph/common/types.py
src/knowledge_graph/common/utils.py
src/knowledge_graph/extraction/__init__.py
src/knowledge_graph/query/__init__.py
src/knowledge_graph/backends/__init__.py
src/knowledge_graph/community/__init__.py
src/knowledge_graph/export/__init__.py
```

#### `src/knowledge_graph/common/schemas.py`

Complete implementation — no stubs.

```python
# @summary
# Typed data contracts for the KG subsystem.
# Exports: EntityDescription, Entity, Triple, ExtractionResult
# Deps: dataclasses, typing
# @end-summary
"""Typed data contracts for the KG subsystem."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EntityDescription:
    text: str        # sentence/passage containing the mention
    source: str      # document path
    chunk_id: str    # originating chunk ID


@dataclass
class Entity:
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
    subject: str
    predicate: str
    object: str
    source: str = ""
    weight: float = 1.0
    extractor_source: str = ""


@dataclass
class ExtractionResult:
    entities: List[Entity] = field(default_factory=list)
    triples: List[Triple] = field(default_factory=list)
    descriptions: Dict[str, List[EntityDescription]] = field(default_factory=dict)
```

**Implementation notes:**
- `ExtractionResult.descriptions` keys are entity `name` (canonical, first-seen form).
- All dataclasses use `field(default_factory=...)` to avoid mutable defaults.
- No business logic in schemas — they are pure data containers.

#### `src/knowledge_graph/common/types.py`

Complete implementation with `load_schema()` function.

```python
# @summary
# Configuration types and YAML schema loader for the KG subsystem.
# Exports: NodeTypeDefinition, EdgeTypeDefinition, SchemaDefinition, KGConfig, load_schema
# Deps: dataclasses, typing, yaml
# @end-summary
"""Configuration and schema types for the KG subsystem."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class NodeTypeDefinition:
    name: str
    description: str
    category: str          # "structural" | "semantic"
    phase: str             # "phase_1" | "phase_1b" | "phase_2"
    gliner_label: Optional[str] = None
    extraction_hints: Optional[str] = None


@dataclass
class EdgeTypeDefinition:
    name: str
    description: str
    category: str
    phase: str
    source_types: List[str] = field(default_factory=list)
    target_types: List[str] = field(default_factory=list)


@dataclass
class SchemaDefinition:
    version: str
    description: str
    node_types: List[NodeTypeDefinition] = field(default_factory=list)
    edge_types: List[EdgeTypeDefinition] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._node_index: Dict[str, NodeTypeDefinition] = {n.name: n for n in self.node_types}
        self._edge_index: Dict[str, EdgeTypeDefinition] = {e.name: e for e in self.edge_types}

    def active_node_types(self, runtime_phase: str) -> List[NodeTypeDefinition]:
        from src.knowledge_graph.common.utils import is_phase_active
        return [n for n in self.node_types if is_phase_active(n.phase, runtime_phase)]

    def active_edge_types(self, runtime_phase: str) -> List[EdgeTypeDefinition]:
        from src.knowledge_graph.common.utils import is_phase_active
        return [e for e in self.edge_types if is_phase_active(e.phase, runtime_phase)]

    def is_valid_node_type(self, type_name: str, runtime_phase: str) -> bool:
        if type_name not in self._node_index:
            return False
        from src.knowledge_graph.common.utils import is_phase_active
        return is_phase_active(self._node_index[type_name].phase, runtime_phase)

    def is_valid_edge_type(self, type_name: str, runtime_phase: str) -> bool:
        if type_name not in self._edge_index:
            return False
        from src.knowledge_graph.common.utils import is_phase_active
        return is_phase_active(self._edge_index[type_name].phase, runtime_phase)


@dataclass
class KGConfig:
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

**`load_schema()` function — implement inside `types.py`:**

```python
import logging
import yaml

_schema_logger = logging.getLogger("rag.knowledge_graph.schema")

VALID_CATEGORIES = {"structural", "semantic"}
VALID_PHASES = {"phase_1", "phase_1b", "phase_2"}


def load_schema(path: str) -> "SchemaDefinition":
    """Load and validate config/kg_schema.yaml."""
    ...
```

**Implementation algorithm for `load_schema()`:**
1. Open the YAML file with `yaml.safe_load()`. Raise `FileNotFoundError` if missing.
2. Parse `node_types` list: for each entry, construct `NodeTypeDefinition`. Required fields: `name`, `description`, `category`, `phase`. Optional: `gliner_label`, `extraction_hints`.
3. Parse `edge_types` list: for each entry, construct `EdgeTypeDefinition`. Required fields: `name`, `description`, `category`, `phase`. Optional: `source_types`, `target_types`.
4. Validation checks — raise `ValueError` for any of:
   - Duplicate `name` values within `node_types`.
   - Duplicate `name` values within `edge_types`.
   - `category` not in `{"structural", "semantic"}`.
   - `phase` not in `{"phase_1", "phase_1b", "phase_2"}`.
   - Duplicate `gliner_label` values (among non-None labels).
5. Warnings only (use `_schema_logger.warning()`):
   - A `gliner_label` that collides with another type's `name` (not an error, just ambiguous).
   - Missing optional fields (no warning needed — they have defaults).
6. Build and return `SchemaDefinition(version=..., description=..., node_types=..., edge_types=...)`.

#### `src/knowledge_graph/common/utils.py`

```python
# @summary
# Shared helpers for the KG subsystem: normalization, type validation, GLiNER label derivation.
# Exports: normalize_alias, validate_type, derive_gliner_labels, is_phase_active, PHASE_ORDER
# Deps: src.knowledge_graph.common.types
# @end-summary
"""Shared helpers for the KG subsystem."""
from __future__ import annotations
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from src.knowledge_graph.common.types import SchemaDefinition

PHASE_ORDER = {"phase_1": 1, "phase_1b": 2, "phase_2": 3}


def is_phase_active(type_phase: str, runtime_phase: str) -> bool:
    return PHASE_ORDER.get(type_phase, 99) <= PHASE_ORDER.get(runtime_phase, 0)


def normalize_alias(name: str) -> str:
    """Lowercase, strip whitespace, replace hyphens/underscores with spaces."""
    return name.lower().strip().replace("-", " ").replace("_", " ")


def validate_type(type_name: str, schema: "SchemaDefinition", runtime_phase: str) -> bool:
    return (
        schema.is_valid_node_type(type_name, runtime_phase)
        or schema.is_valid_edge_type(type_name, runtime_phase)
    )


def derive_gliner_labels(schema: "SchemaDefinition", runtime_phase: str) -> List[str]:
    labels = []
    for node in schema.active_node_types(runtime_phase):
        labels.append(node.gliner_label if node.gliner_label else node.name)
    return labels
```

**Implementation notes for `normalize_alias()`:**
- Used as the dedup key for entities across the merge node and backend.
- Must be deterministic and side-effect-free.
- The normalized form is internal only — the canonical `name` (first-seen surface form) is always returned to callers.

**`TYPE_CHECKING` guard:** `SchemaDefinition` is imported inside `TYPE_CHECKING` to avoid a circular import at module load time, since `types.py` will eventually import from `utils.py` in `__post_init__`.

---

### T2: GraphStorageBackend ABC

**File to create:** `src/knowledge_graph/backend.py`

```python
# @summary
# GraphStorageBackend ABC: formal swappable backend contract for all KG storage implementations.
# Exports: GraphStorageBackend
# Deps: abc, pathlib, typing, src.knowledge_graph.common.schemas
# @end-summary
```

**Complete method list (all abstract unless noted):**

| Method | Abstract | Notes |
|--------|----------|-------|
| `add_node(name, type, source, aliases=None)` | Yes | Case-insensitive dedup |
| `add_edge(subject, object, relation, source, weight=1.0)` | Yes | Drop self-edges |
| `upsert_entities(entities: List[Entity])` | Yes | Batch `add_node` |
| `upsert_triples(triples: List[Triple])` | Yes | Batch `add_edge` |
| `upsert_descriptions(descriptions: Dict[str, List[EntityDescription]])` | Yes | Append + summarize |
| `query_neighbors(entity, depth=1)` | Yes | Forward + backward |
| `get_entity(name)` | Yes | Case-insensitive lookup |
| `get_predecessors(entity)` | Yes | Reverse edge traversal |
| `save(path: Path)` | Yes | Serialize to disk |
| `load(path: Path)` | Yes | Deserialize + rebuild indices |
| `stats()` | Yes | Returns `{nodes, edges, top_entities}` |
| `get_all_entities()` | No (concrete default) | Iterates all nodes |
| `get_all_node_names_and_aliases()` | No (concrete default) | Builds {lowercase -> canonical} |
| `get_outgoing_edges(node_id)` | No (concrete default) | Returns `[]`; needed by T13 (Obsidian export) |
| `get_incoming_edges(node_id)` | No (concrete default) | Returns `[]`; needed by T13 (Obsidian export) |

**Implementation notes:**
- Mirror `src/guardrails/backend.py` pattern exactly: ABC with `@abstractmethod` on all core methods, and concrete optional-override methods at the bottom.
- `get_all_entities()` default: call `get_entity()` for every node name. Backends may override for efficiency.
- `get_all_node_names_and_aliases()` default: call `get_all_entities()` and build the index. Backends may override by directly reading `_case_index` + `_alias_index`.
- `upsert_descriptions()` contract: appends new descriptions to the entity's `raw_mentions` list. Token budget check and LLM summarization are triggered here or in `NetworkXBackend` directly.

**Imports:**
```python
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional
from src.knowledge_graph.common.schemas import Entity, EntityDescription, Triple
```

---

### T3: NetworkXBackend

**File to create:** `src/knowledge_graph/backends/networkx_backend.py`

**Imports:**
```python
from __future__ import annotations
import logging
from pathlib import Path
from typing import Dict, List, Optional
import networkx as nx
import orjson
from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.common.schemas import Entity, EntityDescription, Triple
```

**Class structure:**

```python
class NetworkXBackend(GraphStorageBackend):
    def __init__(self) -> None:
        self.graph: nx.DiGraph = nx.DiGraph()
        self._case_index: Dict[str, str] = {}   # lowercase -> canonical name
        self._alias_index: Dict[str, str] = {}  # alias -> canonical name
```

**`_resolve(name: str) -> str` — critical helper:**

```python
def _resolve(self, name: str) -> str:
    # 1. Check alias index first (acronym expansion)
    resolved = self._alias_index.get(name, name)
    # 2. Case-insensitive dedup: reuse existing canonical form
    lower = resolved.lower()
    if lower in self._case_index:
        return self._case_index[lower]
    # 3. First time seeing this — register as canonical
    self._case_index[lower] = resolved
    return resolved
```

**`add_node()` algorithm:**
1. Call `_resolve(name)` to get canonical form.
2. If node exists in `self.graph`: increment `mention_count`, extend `sources` (no duplicates), extend `aliases` (no duplicates), register new aliases in `self._alias_index`.
3. If node does not exist: `self.graph.add_node(canonical, type=type, sources=[source], mention_count=1, aliases=aliases or [], raw_mentions=[], current_summary="")`. Register all aliases in `self._alias_index`.

**`add_edge()` algorithm:**
1. Drop self-edges: `if subject == object: return`.
2. Resolve both `subject` and `object` via `_resolve()`.
3. If edge exists: `self.graph[subj_c][obj_c]["weight"] += weight`, extend sources.
4. If edge does not exist: `self.graph.add_edge(subj_c, obj_c, relation=relation, weight=weight, sources=[source])`.

**`upsert_entities()` algorithm:**
- For each `Entity`, call `add_node(entity.name, entity.type, source, entity.aliases)` for each source in `entity.sources`. Use the first source if sources is empty.
- After `add_node`, merge `entity.extractor_source` into node `extractor_source` attribute.

**`upsert_descriptions()` algorithm:**
1. For each `(entity_name, new_descriptions)` in `descriptions.items()`:
   - Resolve `entity_name` via `_resolve()`.
   - If node exists, append new descriptions to node's `raw_mentions` list.
   - Count tokens: `sum(len(d.text.split()) for d in all_mentions)` × 1.33 (word-to-token heuristic).
   - If token count exceeds `entity_description_token_budget` (from `KGConfig`): call `trigger_summarization_if_needed()` from `src.knowledge_graph.extraction.merge`. Update node `current_summary` and `raw_mentions` with the returned values.

**`save()` algorithm:**
```python
def save(self, path: Path) -> None:
    data = nx.node_link_data(self.graph, edges="edges")
    path.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))
```
This preserves backward compatibility with `KnowledgeGraphBuilder.save()`.

**`load()` algorithm:**
```python
def load(self, path: Path) -> None:
    data = orjson.loads(path.read_bytes())
    self.graph = nx.node_link_graph(data, directed=True, edges="edges")
    self._case_index = {}
    self._alias_index = {}
    for node, node_data in self.graph.nodes(data=True):
        self._case_index[node.lower()] = node
        for alias in node_data.get("aliases", []):
            self._alias_index[alias] = node
```
Legacy graphs (without `raw_mentions`, `current_summary`, `extractor_source`) load correctly — those attributes will be absent from node data and must be treated as defaults (`[]`, `""`, `[]`).

**`query_neighbors()` algorithm:**
```python
def query_neighbors(self, entity: str, depth: int = 1) -> List[str]:
    canonical = self._resolve(entity)
    if not self.graph.has_node(canonical):
        return []
    forward = set(nx.single_source_shortest_path_length(self.graph, canonical, cutoff=depth))
    backward = set(self.graph.predecessors(canonical))
    result = (forward | backward) - {canonical}
    return list(result)
```

**`get_entity()` algorithm:**
1. Resolve via `_resolve(name)`.
2. If not in graph, return `None`.
3. Build and return `Entity` from node data. Map node attributes to Entity fields. Use `.get()` with defaults for backward-compat attributes (`raw_mentions=[]`, `current_summary=""`, `extractor_source=[]`).

**`stats()` return shape:**
```python
{
    "nodes": self.graph.number_of_nodes(),
    "edges": self.graph.number_of_edges(),
    "top_entities": [
        (name, data.get("mention_count", 0))
        for name, data in sorted(
            self.graph.nodes(data=True),
            key=lambda x: x[1].get("mention_count", 0),
            reverse=True,
        )[:10]
    ],
}
```

**Error handling:**
- `save()`: catch `OSError` and re-raise with a descriptive message including the path.
- `load()`: catch `orjson.JSONDecodeError` and `KeyError`; raise `ValueError("Malformed KG file: ...")`.
- All `add_*`/`upsert_*`: wrap in `try/except Exception` and log at WARNING; do not propagate to callers (fail-safe ingestion).

---

### T4: Neo4jBackend Stub (Phase 2)

**File to create:** `src/knowledge_graph/backends/neo4j_backend.py`

All 11 abstract methods raise `NotImplementedError("Neo4j backend is Phase 2: not yet implemented")`.

**Class signature:**
```python
class Neo4jBackend(GraphStorageBackend):
    """Phase 2 stub. All methods raise NotImplementedError."""
```

No `__init__` needed — or a minimal `__init__(self) -> None: pass`.

---

### T5: Regex Extractor + EntityExtractor Protocol

**Files to create:**
- `src/knowledge_graph/extraction/base.py`
- `src/knowledge_graph/extraction/regex_extractor.py`

#### `src/knowledge_graph/extraction/base.py`

```python
# @summary
# EntityExtractor protocol: formal contract for all KG extractor implementations.
# Exports: EntityExtractor
# Deps: typing, src.knowledge_graph.common.schemas
# @end-summary
"""EntityExtractor protocol for all KG extractors."""
from __future__ import annotations
from typing import List, Protocol, Set, runtime_checkable
from src.knowledge_graph.common.schemas import Triple


@runtime_checkable
class EntityExtractor(Protocol):
    @property
    def name(self) -> str: ...
    def extract_entities(self, text: str) -> Set[str]: ...
    def extract_relations(self, text: str, known_entities: Set[str]) -> List[Triple]: ...
```

**Note:** `extract_relations` now returns `List[Triple]` (not `List[Tuple[str, str, str]]` as in the monolith). This is a key interface change — all extractors must produce `Triple` objects.

#### `src/knowledge_graph/extraction/regex_extractor.py`

**Migration source:** `src/core/knowledge_graph.py` — classes `EntityExtractor` and `GLiNEREntityExtractor` (regex portions).

**Key changes from monolith:**
1. Class renamed `EntityExtractor` → `RegexEntityExtractor`.
2. `extract_relations()` returns `List[Triple]` instead of `List[Tuple[str, str, str]]`.
3. `classify_type()` method added (extracted from `KnowledgeGraphBuilder._classify_type()`). Accepts optional `SchemaDefinition` for schema-based typing.
4. `extract_acronym_aliases()` stays as a public method (used by `NetworkXBackend._resolve()` path during `upsert_entities()`).

**What to preserve exactly:**
- `_STOPWORDS` frozenset (all entries).
- `_CAMEL_PAT`, `_ACRONYM_PAT`, `_MULTI_WORD_PAT` regex patterns.
- `_EXPAND_PAT_1`, `_EXPAND_PAT_2` acronym expansion patterns.
- `_SENTENCE_STARTERS` frozenset.
- `_TRAILING_JUNK`, `_VERB_STARTS`, `_TRAILING_ADVERBS` for relation cleanup.
- All filtering logic in `extract_entities()` and `extract_relations()`.

**`classify_type()` implementation:**
```python
def classify_type(self, name: str) -> str:
    if self._schema:
        # Try schema-based classification first
        # Use heuristics to guess likely type
        if re.match(r"^[A-Z][a-z]+[A-Z]", name):
            candidate = "technology"  # fallback for CamelCase
        elif re.match(r"^[A-Z][A-Z0-9]+$", name):
            candidate = "acronym"
        else:
            candidate = self._fallback_type
        # Return candidate if valid, otherwise fallback
        from src.knowledge_graph.common.utils import is_phase_active
        if self._schema.is_valid_node_type(candidate, "phase_1"):
            return candidate
    # Legacy heuristics (no schema)
    if re.match(r"^[A-Z][a-z]+[A-Z]", name):
        return "technology"
    if re.match(r"^[A-Z][A-Z0-9]+$", name):
        return "acronym"
    return self._fallback_type
```

**Imports for `regex_extractor.py`:**
```python
from __future__ import annotations
import re
from typing import Dict, List, Optional, Set
from src.knowledge_graph.common.schemas import Triple
from src.knowledge_graph.common.types import SchemaDefinition
```

---

### T6: GLiNER Extractor

**File to create:** `src/knowledge_graph/extraction/gliner_extractor.py`

**Migration source:** `src/core/knowledge_graph.py` — class `GLiNEREntityExtractor`.

**Key changes from monolith:**
1. Class renamed to `GLiNERExtractor`.
2. Labels are now derived from the YAML schema via `derive_gliner_labels()` instead of `config.GLINER_ENTITY_LABELS`.
3. `extract_relations()` delegates to `RegexEntityExtractor` and returns `List[Triple]`.
4. Constructor accepts `schema: SchemaDefinition` and `runtime_phase: str`.

**Constructor implementation:**
```python
def __init__(
    self,
    schema: SchemaDefinition,
    runtime_phase: str = "phase_1",
    model_path: Optional[str] = None,
) -> None:
    from gliner import GLiNER
    from config.settings import GLINER_MODEL_PATH
    from src.knowledge_graph.common.utils import derive_gliner_labels
    from src.knowledge_graph.extraction.regex_extractor import RegexEntityExtractor

    model_path = model_path or GLINER_MODEL_PATH
    self._model = GLiNER.from_pretrained(model_path, local_files_only=True)
    self._labels = derive_gliner_labels(schema, runtime_phase)
    self._regex = RegexEntityExtractor(schema=schema)
```

**`extract_entities()` — preserve all filtering from monolith:**
- Strip markdown headers.
- Call `self._model.predict_entities(clean, self._labels, threshold=0.5)`.
- Skip entities with `len(entity_text) <= 2`.
- Skip entities in `_STOPWORDS` (import from `regex_extractor`).

**`extract_relations()` — delegate entirely:**
```python
def extract_relations(self, text: str, known_entities: Set[str]) -> List[Triple]:
    return self._regex.extract_relations(text, known_entities)
```

**Imports:**
```python
from __future__ import annotations
import re
from typing import List, Optional, Set
from src.knowledge_graph.common.schemas import Triple
from src.knowledge_graph.common.types import SchemaDefinition
from src.knowledge_graph.common.utils import derive_gliner_labels
```

---

### T7: Merge Node + Entity Description Accumulation

**File to create:** `src/knowledge_graph/extraction/merge.py`

**Imports:**
```python
from __future__ import annotations
import logging
from typing import Dict, List, Optional, Tuple
from src.knowledge_graph.common.schemas import Entity, EntityDescription, ExtractionResult, Triple
from src.knowledge_graph.common.types import KGConfig, SchemaDefinition
from src.knowledge_graph.common.utils import normalize_alias, validate_type

logger = logging.getLogger("rag.knowledge_graph.merge")
DEFAULT_EXTRACTOR_PRIORITY = ["sv_parser", "llm", "gliner", "regex"]
```

#### `merge_extraction_results()` algorithm

```
Input: List[ExtractionResult], SchemaDefinition, KGConfig
Output: Single ExtractionResult
```

1. Flatten all entities from all results into `all_entities: List[Entity]`.
2. Flatten all triples into `all_triples: List[Triple]`.
3. Call `_deduplicate_entities(all_entities, schema, config)` → `merged_entities`.
4. Call `_deduplicate_triples(all_triples, schema, config)` → `merged_triples`.
5. Call `_accumulate_descriptions(merged_entities)` → `descriptions`.
6. Return `ExtractionResult(entities=merged_entities, triples=merged_triples, descriptions=descriptions)`.

#### `_deduplicate_entities()` algorithm

Dedup key: `normalize_alias(entity.name)`.

```python
seen: Dict[str, Entity] = {}  # normalized_name -> canonical Entity
priority = config.extractor_priority or DEFAULT_EXTRACTOR_PRIORITY

for entity in all_entities:
    key = normalize_alias(entity.name)
    if key not in seen:
        # First time — validate type
        if not schema.is_valid_node_type(entity.type, config.runtime_phase):
            logger.warning("Unknown type %r for entity %r, using fallback", entity.type, entity.name)
            entity.type = config.regex_fallback_type
        seen[key] = entity
    else:
        existing = seen[key]
        # Type conflict resolution: higher-priority extractor wins
        if entity.type != existing.type:
            entity_priority = _extractor_rank(entity.extractor_source, priority)
            existing_priority = _extractor_rank(existing.extractor_source, priority)
            if entity_priority < existing_priority:  # lower index = higher priority
                existing.type = entity.type
        # Merge other fields
        existing.mention_count += entity.mention_count
        existing.sources.extend(s for s in entity.sources if s not in existing.sources)
        existing.aliases.extend(a for a in entity.aliases if a not in existing.aliases)
        existing.raw_mentions.extend(entity.raw_mentions)
        existing.extractor_source.extend(
            s for s in entity.extractor_source if s not in existing.extractor_source
        )

return list(seen.values())
```

Helper:
```python
def _extractor_rank(sources: List[str], priority: List[str]) -> int:
    for i, p in enumerate(priority):
        if p in sources:
            return i
    return len(priority)  # unknown extractor = lowest priority
```

#### `_deduplicate_triples()` algorithm

Dedup key: `(normalize_alias(t.subject), t.predicate, normalize_alias(t.object))`.

```python
seen: Dict[Tuple, Triple] = {}
for triple in all_triples:
    # Validate predicate type
    if not schema.is_valid_edge_type(triple.predicate, config.runtime_phase):
        logger.warning("Unknown predicate %r, skipping triple", triple.predicate)
        continue
    key = (normalize_alias(triple.subject), triple.predicate, normalize_alias(triple.object))
    if key not in seen:
        seen[key] = triple
    else:
        seen[key].weight += triple.weight
return list(seen.values())
```

#### `_accumulate_descriptions()` algorithm

```python
def _accumulate_descriptions(entities: List[Entity]) -> Dict[str, List[EntityDescription]]:
    result = {}
    for entity in entities:
        if entity.raw_mentions:
            result[entity.name] = entity.raw_mentions
    return result
```

#### `trigger_summarization_if_needed()` algorithm

```python
def trigger_summarization_if_needed(
    entity_name: str,
    mentions: List[EntityDescription],
    current_summary: str,
    config: KGConfig,
) -> Tuple[str, List[EntityDescription]]:
    # Token budget: 1 word ≈ 1.33 tokens (heuristic — not precise)
    total_words = sum(len(d.text.split()) for d in mentions)
    estimated_tokens = int(total_words * 1.33)

    if estimated_tokens <= config.entity_description_token_budget:
        return current_summary, mentions  # No summarization needed

    # Summarize: build context from current_summary + mention texts
    context = current_summary + "\n" + "\n".join(d.text for d in mentions)
    new_summary = _call_llm_summarize(entity_name, context)

    # Retain top-K mentions after summarization
    retained = _score_mentions_for_retention(mentions, config.entity_description_top_k_mentions)
    return new_summary, retained
```

**`_call_llm_summarize()` — implement as a thin LLM call:**
```python
def _call_llm_summarize(entity_name: str, context: str) -> str:
    """Call LLM to condense entity description context."""
    try:
        from src.support.llm_client import call_llm  # or equivalent internal LLM helper
        prompt = (
            f"Summarize the following descriptions of the entity '{entity_name}' "
            f"in 2-3 sentences:\n\n{context}"
        )
        return call_llm(prompt, max_tokens=200)
    except Exception as exc:
        logger.warning("LLM summarization failed for %r: %s", entity_name, exc)
        return current_summary  # preserve existing summary on failure
```

**`_score_mentions_for_retention()` algorithm:**
- Score by recency (later indices score higher) and source diversity.
- Simple implementation: take the last `top_k` mentions (recency priority). Source diversity can be added later without breaking the interface.
- Return `mentions[-top_k:]`.

#### `ExtractionPipeline` (in `src/knowledge_graph/extraction/__init__.py`)

The extraction subgraph lives here, not in a separate file. This is the public entry point for T17 (Node 10).

```python
# @summary
# ExtractionPipeline: compiles and runs the multi-extractor LangGraph subgraph.
# Exports: ExtractionPipeline
# Deps: langgraph, src.knowledge_graph.extraction.*, src.knowledge_graph.common.*
# @end-summary
"""Public API for the KG extraction subpackage."""
from __future__ import annotations
import logging
from typing import List

from src.knowledge_graph.common.schemas import ExtractionResult
from src.knowledge_graph.common.types import KGConfig, SchemaDefinition
from src.knowledge_graph.extraction.merge import merge_extraction_results

logger = logging.getLogger("rag.knowledge_graph.extraction")


class ExtractionPipeline:
    """Compiles and runs the multi-extractor LangGraph subgraph.

    The subgraph topology is:
        START -> fan_out -> [regex?, gliner?, llm?, sv_parser?] -> merge -> END

    Args:
        config: KGConfig controlling which extractors are enabled.
        schema: SchemaDefinition for type validation.
    """

    def __init__(self, config: KGConfig, schema: SchemaDefinition) -> None:
        self._config = config
        self._schema = schema
        self._extractors = self._build_extractors()

    def _build_extractors(self):
        extractors = []
        if self._config.enable_regex_extractor:
            from src.knowledge_graph.extraction.regex_extractor import RegexEntityExtractor
            extractors.append(RegexEntityExtractor(schema=self._schema))
        if self._config.enable_gliner_extractor:
            from src.knowledge_graph.extraction.gliner_extractor import GLiNERExtractor
            extractors.append(GLiNERExtractor(self._schema, self._config.runtime_phase))
        if self._config.enable_llm_extractor:
            from src.knowledge_graph.extraction.llm_extractor import LLMExtractor
            extractors.append(LLMExtractor(self._schema, self._config.runtime_phase))
        if self._config.enable_sv_parser:
            from src.knowledge_graph.extraction.sv_parser import SVParserExtractor
            extractors.append(SVParserExtractor(self._schema))
        return extractors

    def run(self, chunks) -> ExtractionResult:
        """Run all enabled extractors over chunks and merge results.

        Each extractor runs on all chunks. Extractor failures are caught and
        logged but do not halt processing (fail-safe extraction).

        Args:
            chunks: Iterable of objects with .text and .chunk_id/.id attributes.

        Returns:
            Merged ExtractionResult.
        """
        all_results: List[ExtractionResult] = []

        for extractor in self._extractors:
            try:
                result = self._run_extractor(extractor, chunks)
                all_results.append(result)
            except Exception as exc:
                logger.warning("Extractor %r failed: %s", extractor.name, exc)

        if not all_results:
            return ExtractionResult()

        return merge_extraction_results(all_results, self._schema, self._config)
```

**`_run_extractor()` helper** (inside `ExtractionPipeline`):

```python
def _run_extractor(self, extractor, chunks) -> ExtractionResult:
    from src.knowledge_graph.common.schemas import Entity, EntityDescription, ExtractionResult, Triple
    entities_map = {}
    triples = []
    descriptions = {}

    for chunk in chunks:
        text = chunk.text
        chunk_id = getattr(chunk, "chunk_id", getattr(chunk, "id", ""))
        source = getattr(chunk, "source", "")

        raw_entities = extractor.extract_entities(text)
        raw_triples = extractor.extract_relations(text, raw_entities)

        for name in raw_entities:
            key = name.lower()
            if key not in entities_map:
                entities_map[key] = Entity(
                    name=name,
                    type=extractor.classify_type(name) if hasattr(extractor, "classify_type") else "concept",
                    sources=[source],
                    mention_count=1,
                    extractor_source=[extractor.name],
                )
            else:
                entities_map[key].mention_count += 1
                if source not in entities_map[key].sources:
                    entities_map[key].sources.append(source)

            # Accumulate mention description
            desc = EntityDescription(text=text[:500], source=source, chunk_id=chunk_id)
            descriptions.setdefault(name, []).append(desc)

        triples.extend(raw_triples)

    return ExtractionResult(
        entities=list(entities_map.values()),
        triples=triples,
        descriptions=descriptions,
    )
```

**LangGraph note:** Phase 1 uses a simple sequential loop (above) rather than a compiled LangGraph subgraph. The LangGraph subgraph architecture (parallel branches) is the Phase 1b enhancement. The `ExtractionPipeline.run()` interface is stable — the internal execution model can change without breaking callers.

---

### T8: spaCy Entity Matcher

**File to create:** `src/knowledge_graph/query/entity_matcher.py`

**Imports:**
```python
from __future__ import annotations
import logging
from typing import Dict, List
import spacy
from spacy.matcher import PhraseMatcher

logger = logging.getLogger("rag.knowledge_graph.entity_matcher")
```

**Constructor implementation:**
```python
def __init__(self, entity_index: Dict[str, str]) -> None:
    # Use blank English model — no transformer, minimal footprint
    self._nlp = spacy.blank("en")
    self._matcher = PhraseMatcher(self._nlp.vocab, attr="LOWER")
    self._entity_index = entity_index
    self._build_patterns(entity_index)

def _build_patterns(self, entity_index: Dict[str, str]) -> None:
    self._matcher.remove("ENTITIES") if "ENTITIES" in self._matcher else None
    patterns = [self._nlp.make_doc(name) for name in entity_index.keys()]
    if patterns:
        self._matcher.add("ENTITIES", patterns)
```

**`match()` implementation:**
```python
def match(self, query: str) -> List[str]:
    doc = self._nlp(query)
    matched_spans = []
    for match_id, start, end in self._matcher(doc):
        span = doc[start:end]
        matched_spans.append(span)

    # Prefer longer matches (filter out spans that are substrings of longer matches)
    matched_spans = spacy.util.filter_spans(matched_spans)

    result = []
    for span in matched_spans:
        key = span.text.lower()
        canonical = self._entity_index.get(key)
        if canonical:
            result.append(canonical)
    return result
```

**`rebuild()` implementation:**
```python
def rebuild(self, entity_index: Dict[str, str]) -> None:
    self._entity_index = entity_index
    self._build_patterns(entity_index)
```

**Key behavior:**
- `spacy.blank("en")` provides only a tokenizer — no NER, no vectors. Load time is negligible (<10ms).
- `PhraseMatcher(attr="LOWER")` performs case-insensitive matching on token lowercases — this is token-boundary matching, not substring matching. "AXI" will not match inside "TAXIING".
- `spacy.util.filter_spans()` resolves overlapping/nested matches by preferring the longest.

**Fallback:** If spaCy is not installed, raise `ImportError` with a clear message in `__init__`. Do not silently fall back to substring matching — the caller (expander) can catch this and degrade gracefully.

---

### T9: Query Expander

**File to create:** `src/knowledge_graph/query/expander.py`

**Imports:**
```python
from __future__ import annotations
import logging
from typing import List, Optional
from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.common.types import KGConfig
from src.knowledge_graph.query.entity_matcher import SpacyEntityMatcher
from src.knowledge_graph.query.sanitizer import QuerySanitizer

logger = logging.getLogger("rag.knowledge_graph.expander")
```

**Constructor:**
```python
def __init__(self, backend: GraphStorageBackend, config: KGConfig) -> None:
    self._backend = backend
    self._config = config
    entity_index = backend.get_all_node_names_and_aliases()
    self._matcher = SpacyEntityMatcher(entity_index)
    self._sanitizer = QuerySanitizer(alias_index=entity_index)
```

**`match_entities()` implementation:**
```python
def match_entities(self, query: str) -> List[str]:
    normalized = self._sanitizer.normalize(query)
    return self._matcher.match(normalized)
```

**`expand()` implementation:**
```python
def expand(self, query: str, depth: Optional[int] = None) -> List[str]:
    effective_depth = depth if depth is not None else self._config.max_expansion_depth
    effective_depth = min(effective_depth, 3)  # hard cap from spec

    seed_entities = self.match_entities(query)

    if not seed_entities and self._config.enable_llm_query_fallback:
        # Phase 1b: LLM fallback (stub raises NotImplementedError; catch and skip)
        try:
            from src.knowledge_graph.query.llm_fallback import LLMFallbackMatcher
            all_names = list(self._backend.get_all_node_names_and_aliases().values())
            seed_entities = LLMFallbackMatcher().match(query, all_names)
        except NotImplementedError:
            pass

    expanded: set = set(seed_entities)
    for entity in seed_entities:
        neighbors = self._backend.query_neighbors(entity, depth=effective_depth)
        expanded.update(neighbors)

    # Filter out terms already in the query
    query_lower = query.lower()
    result = [e for e in expanded if e.lower() not in query_lower]

    # Apply fan-out limit
    return result[:self._config.max_expansion_terms]
```

**`get_context_summary()` implementation:**
```python
def get_context_summary(self, entities: List[str], max_lines: int = 5) -> str:
    lines = []
    for entity_name in entities:
        entity = self._backend.get_entity(entity_name)
        if entity is None:
            continue
        # Use LLM summary if available, otherwise first raw mention
        if entity.current_summary:
            lines.append(f"{entity_name}: {entity.current_summary}")
        elif entity.raw_mentions:
            lines.append(f"{entity_name}: {entity.raw_mentions[0].text[:200]}")
        if len(lines) >= max_lines:
            break
    return "\n".join(lines)
```

**`rebuild_matcher()` implementation:**
```python
def rebuild_matcher(self) -> None:
    entity_index = self._backend.get_all_node_names_and_aliases()
    self._matcher.rebuild(entity_index)
    self._sanitizer.rebuild(entity_index)
```

---

### T10: Query Sanitizer

**File to create:** `src/knowledge_graph/query/sanitizer.py`

```python
# @summary
# Query sanitizer: normalization, alias expansion, and alias index management.
# Exports: QuerySanitizer
# Deps: re, typing
# @end-summary
"""Query sanitization: normalization, alias expansion, and fan-out control."""
from __future__ import annotations
import re
from typing import Dict, List


class QuerySanitizer:
    def __init__(self, alias_index: Dict[str, str]) -> None:
        self._alias_index = alias_index

    def normalize(self, query: str) -> str:
        """Lowercase, normalize whitespace, replace hyphens/underscores with spaces."""
        q = query.lower().strip()
        q = re.sub(r"[-_]", " ", q)
        q = re.sub(r"\s+", " ", q)
        return q

    def expand_aliases(self, terms: List[str]) -> List[str]:
        """Given matched entity names, also include their aliases."""
        result = list(terms)
        for term in terms:
            # Look up what aliases point to this canonical term
            for alias, canonical in self._alias_index.items():
                if canonical == term and alias not in result:
                    result.append(alias)
        return result

    def rebuild(self, alias_index: Dict[str, str]) -> None:
        self._alias_index = alias_index
```

---

### T11: Public API (`__init__.py`)

**File to create:** `src/knowledge_graph/__init__.py` (replace the placeholder)

**Implementation pattern — mirror `src/guardrails/__init__.py` exactly:**

```python
# @summary
# Public API for the knowledge graph subsystem: lazy singleton dispatcher.
# Exports: get_graph_backend, get_query_expander, Entity, EntityDescription,
#          ExtractionResult, Triple, KGConfig, SchemaDefinition, GraphStorageBackend
# Deps: config.settings, src.knowledge_graph.backend, src.knowledge_graph.common.*
# @end-summary
```

**`_NoOpBackend` — full implementation (inline, not a separate file):**

All 11 abstract methods are no-ops or return empty values:
- `add_node`, `add_edge`, `upsert_entities`, `upsert_triples`, `upsert_descriptions` → `pass`
- `query_neighbors` → `return []`
- `get_entity` → `return None`
- `get_predecessors` → `return []`
- `save`, `load` → `pass`
- `stats` → `return {"nodes": 0, "edges": 0, "top_entities": []}`

**`get_graph_backend()` dispatcher:**
```python
def get_graph_backend() -> GraphStorageBackend:
    global _backend
    if _backend is None:
        config = _build_kg_config()
        backend_key = config.backend.lower()
        if backend_key == "networkx":
            from src.knowledge_graph.backends.networkx_backend import NetworkXBackend
            _backend = NetworkXBackend()
            # Load existing graph if KG_PATH exists
            from config.settings import KG_PATH
            import pathlib
            p = pathlib.Path(KG_PATH)
            if p.exists():
                _backend.load(p)
        elif backend_key in ("", "none", "noop"):
            _backend = _NoOpBackend()
        else:
            raise ValueError(
                f"Unknown KG_BACKEND: {backend_key!r}. Valid values: 'networkx', 'none'."
            )
    return _backend
```

**`get_query_expander()` dispatcher:**
```python
def get_query_expander():
    global _expander
    if _expander is None:
        from src.knowledge_graph.query.expander import GraphQueryExpander
        backend = get_graph_backend()
        config = _build_kg_config()
        _expander = GraphQueryExpander(backend=backend, config=config)
    return _expander
```

**`_build_kg_config()` — read from `config.settings`:**
```python
def _build_kg_config() -> KGConfig:
    from config.settings import (
        KG_BACKEND, KG_SCHEMA_PATH,
        KG_ENABLE_REGEX_EXTRACTOR, KG_ENABLE_GLINER_EXTRACTOR,
        KG_ENABLE_LLM_EXTRACTOR, KG_ENABLE_SV_PARSER,
        KG_ENTITY_DESCRIPTION_TOKEN_BUDGET, KG_ENTITY_DESCRIPTION_TOP_K_MENTIONS,
        KG_MAX_EXPANSION_DEPTH, KG_MAX_EXPANSION_TERMS,
        KG_ENABLE_LLM_QUERY_FALLBACK, KG_LLM_FALLBACK_TIMEOUT_MS,
        KG_ENABLE_GLOBAL_RETRIEVAL, KG_RUNTIME_PHASE,
    )
    return KGConfig(
        backend=KG_BACKEND,
        schema_path=KG_SCHEMA_PATH,
        enable_regex_extractor=KG_ENABLE_REGEX_EXTRACTOR,
        enable_gliner_extractor=KG_ENABLE_GLINER_EXTRACTOR,
        enable_llm_extractor=KG_ENABLE_LLM_EXTRACTOR,
        enable_sv_parser=KG_ENABLE_SV_PARSER,
        entity_description_token_budget=KG_ENTITY_DESCRIPTION_TOKEN_BUDGET,
        entity_description_top_k_mentions=KG_ENTITY_DESCRIPTION_TOP_K_MENTIONS,
        max_expansion_depth=KG_MAX_EXPANSION_DEPTH,
        max_expansion_terms=KG_MAX_EXPANSION_TERMS,
        enable_llm_query_fallback=KG_ENABLE_LLM_QUERY_FALLBACK,
        llm_fallback_timeout_ms=KG_LLM_FALLBACK_TIMEOUT_MS,
        enable_global_retrieval=KG_ENABLE_GLOBAL_RETRIEVAL,
        runtime_phase=KG_RUNTIME_PHASE,
    )
```

**`_load_schema()` — call `load_schema()` from `common/types.py`:**
```python
def _load_schema(config: KGConfig) -> SchemaDefinition:
    from src.knowledge_graph.common.types import load_schema
    return load_schema(config.schema_path)
```

---

### T12: YAML Schema + Loader

**File to create:** `config/kg_schema.yaml`

**Top-level YAML structure:**
```yaml
version: "1.0.0"
description: "RagWeave ASIC knowledge graph schema"

node_types:
  # --- Structural (Phase 1) ---
  - name: RTL_Module
    description: "A SystemVerilog or VHDL module"
    category: structural
    phase: phase_1
    gliner_label: "RTL module"
    extraction_hints: "module declarations in SV/VHDL"

  # ... (24 structural types)

  # --- Semantic (Phase 1b) ---
  - name: Specification
    description: "A design specification document or section"
    category: semantic
    phase: phase_1b
    gliner_label: "specification"

  # ... (17 semantic types)

edge_types:
  # --- Structural (Phase 1) ---
  - name: instantiates
    description: "Module A instantiates module B"
    category: structural
    phase: phase_1
    source_types: [RTL_Module]
    target_types: [RTL_Module]

  # ... (10 structural edge types)

  # --- Semantic (Phase 1b) ---
  - name: specified_by
    description: "Entity A is specified by specification B"
    category: semantic
    phase: phase_1b

  # ... (12 semantic edge types)
```

**Complete node type list (from spec):**

Structural (phase_1): `RTL_Module`, `Port`, `Parameter`, `Instance`, `Signal`, `ClockDomain`, `Interface`, `Package`, `TypeDef`, `FSM_State`, `Generate`, `Task_Function`, `SVA_Assertion`, `UVM_Component`, `TestCase`, `CoverGroup`, `Sequence`, `Constraint`, `Pipeline_Stage`, `FIFO_Buffer`, `Arbiter`, `Decoder_Encoder`, `RegisterFile`, `MemoryMap`

Semantic (phase_1b): `Specification`, `DesignDecision`, `Requirement`, `TradeOff`, `KnownIssue`, `Assumption`, `Person`, `Team`, `Project`, `Review`, `Protocol`, `IP_Block`, `EDA_Tool`, `Script`, `TimingConstraint`, `AreaConstraint`, `PowerConstraint`

**Legacy/compatibility types (phase_1, for regex extractor):** Also add `technology`, `acronym`, `concept` as phase_1 structural types so the regex extractor's heuristic types remain valid.

**Complete edge type list (from spec):**

Structural (phase_1): `instantiates`, `connects_to`, `depends_on`, `parameterized_by`, `belongs_to_clock_domain`, `implements_interface`, `contains`, `transitions_to`, `drives`, `reads`

Semantic (phase_1b): `specified_by`, `verified_by`, `authored_by`, `reviewed_by`, `blocks`, `supersedes`, `constrained_by`, `trades_off_against`, `assumes`, `complies_with`, `relates_to`, `design_decision_for`

**Legacy edge types (phase_1):** Also add `is_a`, `subset_of`, `used_for`, `uses` as phase_1 structural edges (from the regex extractor's relation patterns).

**Loader location:** `load_schema()` function lives in `src/knowledge_graph/common/types.py` (same file as `SchemaDefinition`). See T1 for its validation algorithm.

---

### T13: Obsidian Export

**File to create:** `src/knowledge_graph/export/obsidian.py`

**Migration source:** `src/core/knowledge_graph.py` — function `export_obsidian()`.

**Key change:** Accepts `GraphStorageBackend` instead of `nx.DiGraph`.

**Implementation:**
```python
def export_obsidian(backend: GraphStorageBackend, output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for entity in backend.get_all_entities():
        safe_name = re.sub(r"[^\w\s\-]", "", entity.name).strip()
        safe_name = Path(safe_name).name if safe_name else "unnamed_node"

        lines = [f"# {entity.name}"]
        lines.append(f"\n**Type**: {entity.type}")
        if entity.aliases:
            lines.append(f"**Aliases**: {', '.join(entity.aliases)}")
        lines.append(f"**Mentions**: {entity.mention_count}")
        lines.append(f"**Sources**: {', '.join(entity.sources)}")

        # Entity description: prefer LLM summary, fall back to raw mentions
        if entity.current_summary:
            lines.append(f"\n**Description**: {entity.current_summary}")
        elif entity.raw_mentions:
            lines.append(f"\n**Description**: {entity.raw_mentions[0].text[:300]}")

        # Relationships from backend — use backend's graph for neighbors
        # NetworkXBackend exposes self.graph; other backends must implement get_all_entities
        # with enough data, or we iterate via query_neighbors
        # ... (out_edges and in_edges via backend)

        (output_dir / f"{safe_name}.md").write_text("\n".join(lines), encoding="utf-8")
        count += 1

    return count
```

**Edge traversal in `export_obsidian()`:** `GraphStorageBackend` has no method to enumerate edges. Two options:
1. Add `get_outgoing_edges(entity_name)` to the ABC (requires ABC update).
2. Downcast to `NetworkXBackend` and access `.graph` directly inside the export function (not clean but practical for Phase 1).

**Recommended for Phase 1:** Add optional `get_outgoing_edges()` and `get_incoming_edges()` as non-abstract concrete methods in the ABC (default: return `[]`). `NetworkXBackend` overrides them. This avoids a breaking change while keeping the export functional.

**Add to `GraphStorageBackend` ABC (non-abstract):**
```python
def get_outgoing_edges(self, entity: str) -> List[dict]:
    """Return outgoing edges as {target, relation, weight} dicts. Default: empty."""
    return []

def get_incoming_edges(self, entity: str) -> List[dict]:
    """Return incoming edges as {source, relation, weight} dicts. Default: empty."""
    return []
```

**`NetworkXBackend` overrides:**
```python
def get_outgoing_edges(self, entity: str):
    canonical = self._resolve(entity)
    return [
        {"target": t, "relation": d["relation"], "weight": d["weight"]}
        for _, t, d in self.graph.out_edges(canonical, data=True)
    ]

def get_incoming_edges(self, entity: str):
    canonical = self._resolve(entity)
    return [
        {"source": s, "relation": d["relation"], "weight": d["weight"]}
        for s, _, d in self.graph.in_edges(canonical, data=True)
    ]
```

**Imports for `obsidian.py`:**
```python
from __future__ import annotations
import re
from pathlib import Path
from typing import List
from src.knowledge_graph.backend import GraphStorageBackend
```

---

### T14: Community Detection Stubs (Phase 2)

**Files to create:**
- `src/knowledge_graph/community/detector.py`
- `src/knowledge_graph/community/summarizer.py`

Both are complete as shown in the design doc — all methods raise `NotImplementedError("... is Phase 2: not yet implemented")`. No additional implementation detail needed.

---

### T15: LLM Extractor + LLM Query Fallback Stubs (Phase 1b)

**Files to create:**
- `src/knowledge_graph/extraction/llm_extractor.py`
- `src/knowledge_graph/query/llm_fallback.py`

Both are complete as shown in the design doc — all operational methods raise `NotImplementedError("... is Phase 1b: not yet implemented")`. Include `@property def name(self) -> str: return "llm"` on `LLMExtractor`.

---

### T16: SV Parser Extractor Stub (Phase 1b)

**File to create:** `src/knowledge_graph/extraction/sv_parser.py`

Complete as shown in the design doc. Include `@property def name(self) -> str: return "sv_parser"`.

---

### T17: Update Ingest Pipeline Nodes

**Files to modify:**
- `src/ingest/embedding/nodes/knowledge_graph_extraction.py`
- `src/ingest/embedding/nodes/knowledge_graph_storage.py`
- `src/ingest/embedding/state.py`

#### `knowledge_graph_extraction.py` — new implementation

**Replace** the existing content with:

```python
# @summary
# LangGraph node for multi-extractor KG entity/relation extraction.
# Exports: knowledge_graph_extraction_node
# Deps: src.knowledge_graph, src.ingest.embedding.state
# @end-summary
"""Knowledge-graph extraction node — delegates to ExtractionPipeline."""
from __future__ import annotations
from typing import Any
from src.ingest.common.shared import append_processing_log
from src.ingest.embedding.state import EmbeddingPipelineState


def knowledge_graph_extraction_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    if not state["runtime"].config.enable_knowledge_graph_extraction:
        return {
            "processing_log": append_processing_log(
                state, "knowledge_graph_extraction:skipped"
            )
        }

    try:
        from src.knowledge_graph import get_graph_backend
        from src.knowledge_graph.common.types import KGConfig, load_schema
        from src.knowledge_graph.extraction import ExtractionPipeline

        config = KGConfig()  # defaults from KGConfig; override via env vars in settings.py
        schema = load_schema(config.schema_path)
        pipeline = ExtractionPipeline(config=config, schema=schema)
        result = pipeline.run(state["chunks"])

        return {
            "kg_extraction_result": result,
            "processing_log": append_processing_log(
                state, f"knowledge_graph_extraction:ok entities={len(result.entities)}"
            ),
        }
    except Exception as exc:
        return {
            **state,
            "errors": state.get("errors", []) + [f"kg_extraction:{exc}"],
            "processing_log": append_processing_log(state, "knowledge_graph_extraction:error"),
        }
```

**Note:** The node constructs `KGConfig` directly and calls `load_schema()` from `common/types.py`. This keeps the extraction pipeline self-contained and avoids any dependency on private helpers in `src.knowledge_graph.__init__`.

#### `knowledge_graph_storage.py` — new implementation

```python
def knowledge_graph_storage_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    """Store extraction results in the graph backend."""
    try:
        from src.knowledge_graph import get_graph_backend
        from config.settings import KG_PATH

        backend = get_graph_backend()

        # Prefer new ExtractionResult; fall back to legacy kg_triples for compat
        result = state.get("kg_extraction_result")
        if result is not None:
            backend.upsert_entities(result.entities)
            backend.upsert_triples(result.triples)
            backend.upsert_descriptions(result.descriptions)
        else:
            # Legacy path: kg_triples is List[Dict[str, str]]
            from src.knowledge_graph.common.schemas import Triple
            triples = [
                Triple(
                    subject=t["subject"],
                    predicate=t["predicate"],
                    object=t["object"],
                    source=t.get("source", ""),
                )
                for t in state.get("kg_triples", [])
            ]
            backend.upsert_triples(triples)

        import pathlib
        backend.save(pathlib.Path(KG_PATH))

        return {
            "processing_log": append_processing_log(state, "knowledge_graph_storage:ok")
        }
    except Exception as exc:
        return {
            **state,
            "errors": state.get("errors", []) + [f"kg_storage:{exc}"],
            "processing_log": append_processing_log(state, "knowledge_graph_storage:error"),
        }
```

#### `state.py` — add `kg_extraction_result` field

Locate the `EmbeddingPipelineState` TypedDict and add:

```python
from typing import Optional, Any  # already imported

class EmbeddingPipelineState(TypedDict, total=False):
    # ... existing fields ...
    kg_triples: List[Dict[str, Any]]         # Kept for backward compat
    kg_extraction_result: Optional[Any]       # ExtractionResult | None (new)
```

Use `Optional[Any]` (not `Optional[ExtractionResult]`) to avoid a circular import between state and the knowledge_graph package. The type annotation is purely for IDE hints.

---

### T18: Update Retrieval Pipeline

**File to modify:** `src/retrieval/pipeline/rag_chain.py`

**Change:** Replace direct `KnowledgeGraphBuilder` + `GraphQueryExpander` construction with lazy singleton.

**Before (current code):**
```python
from src.core.knowledge_graph import KnowledgeGraphBuilder, GraphQueryExpander
# In Stage 2:
kg_builder = KnowledgeGraphBuilder.load(KG_PATH)
expander = GraphQueryExpander(kg_builder.graph)
expanded = expander.expand(query)
bm25_query += " ".join(expanded[:3])
```

**After (new code):**
```python
from src.knowledge_graph import get_query_expander
# In Stage 2:
expander = get_query_expander()
expanded = expander.expand(query)  # fan-out limit applied internally via config
bm25_query += " ".join(expanded)
```

**Important:** `get_query_expander()` is process-wide. The first call initializes the backend (loading the graph from disk). Subsequent calls return the cached singleton. Do not construct a new expander per query — the current code may construct a new `KnowledgeGraphBuilder.load()` on every call, which is expensive and should be fixed as part of this migration.

---

### T19: Add Config Keys to `config/settings.py`

**File to modify:** `config/settings.py`

**Add after the existing `KG_ENABLED` and `KG_PATH` lines (around line 93):**

```python
# --- Knowledge Graph Subsystem Configuration ---
KG_BACKEND = os.environ.get("RAG_KG_BACKEND", "networkx")
KG_SCHEMA_PATH = os.environ.get(
    "RAG_KG_SCHEMA_PATH",
    str(PROJECT_ROOT / "config" / "kg_schema.yaml")
)
KG_ENABLE_REGEX_EXTRACTOR = os.environ.get(
    "RAG_KG_ENABLE_REGEX_EXTRACTOR", "true"
).lower() in ("true", "1", "yes")
KG_ENABLE_GLINER_EXTRACTOR = os.environ.get(
    "RAG_KG_ENABLE_GLINER_EXTRACTOR", "false"
).lower() in ("true", "1", "yes")
KG_ENABLE_LLM_EXTRACTOR = os.environ.get(
    "RAG_KG_ENABLE_LLM_EXTRACTOR", "false"
).lower() in ("true", "1", "yes")
KG_ENABLE_SV_PARSER = os.environ.get(
    "RAG_KG_ENABLE_SV_PARSER", "false"
).lower() in ("true", "1", "yes")
KG_ENTITY_DESCRIPTION_TOKEN_BUDGET = int(
    os.environ.get("RAG_KG_ENTITY_DESCRIPTION_TOKEN_BUDGET", "512")
)
KG_ENTITY_DESCRIPTION_TOP_K_MENTIONS = int(
    os.environ.get("RAG_KG_ENTITY_DESCRIPTION_TOP_K_MENTIONS", "5")
)
KG_MAX_EXPANSION_DEPTH = int(os.environ.get("RAG_KG_MAX_EXPANSION_DEPTH", "1"))
KG_MAX_EXPANSION_TERMS = int(os.environ.get("RAG_KG_MAX_EXPANSION_TERMS", "3"))
KG_ENABLE_LLM_QUERY_FALLBACK = os.environ.get(
    "RAG_KG_ENABLE_LLM_QUERY_FALLBACK", "false"
).lower() in ("true", "1", "yes")
KG_LLM_FALLBACK_TIMEOUT_MS = int(
    os.environ.get("RAG_KG_LLM_FALLBACK_TIMEOUT_MS", "1000")
)
KG_ENABLE_GLOBAL_RETRIEVAL = os.environ.get(
    "RAG_KG_ENABLE_GLOBAL_RETRIEVAL", "false"
).lower() in ("true", "1", "yes")
KG_RUNTIME_PHASE = os.environ.get("RAG_KG_RUNTIME_PHASE", "phase_1")
```

**Existing keys to preserve unchanged:**
- `KG_ENABLED` — still controls whether the extraction/storage nodes run at all in the pipeline.
- `KG_PATH` — still controls where the graph JSON file is stored/loaded from.
- `KG_OBSIDIAN_EXPORT_DIR` — still controls where Obsidian export writes.

---

### T20: Backward Compatibility Shim

**File to modify:** `src/core/knowledge_graph.py` (full replacement)

Replace the entire 558-line file with:

```python
# @summary
# Backward compatibility shim for src.core.knowledge_graph.
# All names re-exported from src.knowledge_graph.
# Emits DeprecationWarning on first import.
# Exports: KnowledgeGraphBuilder, GraphQueryExpander, EntityExtractor,
#          GLiNEREntityExtractor, export_obsidian
# Deps: src.knowledge_graph.*
# @end-summary
"""Backward compatibility shim for src.core.knowledge_graph.

All public names are re-exported from src.knowledge_graph.
This module emits a DeprecationWarning on first import.

Migration: update all imports to use src.knowledge_graph directly.
"""
import warnings

warnings.warn(
    "Importing from src.core.knowledge_graph is deprecated. "
    "Use src.knowledge_graph instead.",
    DeprecationWarning,
    stacklevel=2,
)

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

**Note on `KnowledgeGraphBuilder` alias:** `NetworkXBackend` does not have an `add_chunk()` method — the monolith's `add_chunk()` is replaced by `upsert_entities()` + `upsert_triples()` + `upsert_descriptions()`. Any code still calling `KnowledgeGraphBuilder().add_chunk()` will get an `AttributeError`. That code must be updated before T20 is deployed (T17 handles the ingestion pipeline; T18 handles retrieval). The shim is the last task — all callers must be migrated first.

---

## 3. Configuration Reference

All new environment variables, their defaults, and the `KGConfig` field they map to:

| Env Variable | Default | `KGConfig` Field | Notes |
|---|---|---|---|
| `RAG_KG_BACKEND` | `networkx` | `backend` | Valid: `networkx`, `none` |
| `RAG_KG_SCHEMA_PATH` | `config/kg_schema.yaml` | `schema_path` | Relative to project root |
| `RAG_KG_ENABLE_REGEX_EXTRACTOR` | `true` | `enable_regex_extractor` | |
| `RAG_KG_ENABLE_GLINER_EXTRACTOR` | `false` | `enable_gliner_extractor` | Requires GLiNER model |
| `RAG_KG_ENABLE_LLM_EXTRACTOR` | `false` | `enable_llm_extractor` | Phase 1b stub |
| `RAG_KG_ENABLE_SV_PARSER` | `false` | `enable_sv_parser` | Phase 1b stub |
| `RAG_KG_ENTITY_DESCRIPTION_TOKEN_BUDGET` | `512` | `entity_description_token_budget` | Soft trigger for LLM summarization |
| `RAG_KG_ENTITY_DESCRIPTION_TOP_K_MENTIONS` | `5` | `entity_description_top_k_mentions` | Mentions retained after summarization |
| `RAG_KG_MAX_EXPANSION_DEPTH` | `1` | `max_expansion_depth` | Hard cap: 3 |
| `RAG_KG_MAX_EXPANSION_TERMS` | `3` | `max_expansion_terms` | BM25 term budget |
| `RAG_KG_ENABLE_LLM_QUERY_FALLBACK` | `false` | `enable_llm_query_fallback` | Phase 1b stub |
| `RAG_KG_LLM_FALLBACK_TIMEOUT_MS` | `1000` | `llm_fallback_timeout_ms` | Phase 1b |
| `RAG_KG_ENABLE_GLOBAL_RETRIEVAL` | `false` | `enable_global_retrieval` | Phase 2 |
| `RAG_KG_RUNTIME_PHASE` | `phase_1` | `runtime_phase` | Controls which schema types are active |

**Existing keys (unchanged):**

| Key | Current Default | Purpose |
|---|---|---|
| `RAG_KG_ENABLED` | `true` | Master switch for KG ingestion/retrieval |
| `KG_PATH` | `.knowledge_graph.json` | Graph persistence file location |
| `KG_OBSIDIAN_EXPORT_DIR` | `obsidian_graph/` | Obsidian export output |

---

## 4. Testing Hooks

### What to Mock

| Module | Mock Target | Why |
|---|---|---|
| `networkx_backend.py` | `NetworkXBackend` | Heavy graph operations in unit tests |
| `gliner_extractor.py` | `GLiNER.from_pretrained()` | Avoids model loading in tests |
| `merge.py` | `_call_llm_summarize()` | Avoids LLM calls in unit tests |
| `expander.py` | `GraphStorageBackend` | Use `_NoOpBackend` or MagicMock |
| `entity_matcher.py` | `spacy.blank("en")` | Not needed — blank model loads fast |
| `types.py` | `yaml.safe_load()` | Test validation without file I/O |

### Key Assertions per Module

**`common/types.py` — schema loader:**
- Valid YAML loads without error.
- Duplicate `name` raises `ValueError`.
- Invalid `category` raises `ValueError`.
- Missing required field raises `ValueError`.
- `SchemaDefinition.active_node_types("phase_1")` excludes phase_1b types.
- `SchemaDefinition.is_valid_node_type("RTL_Module", "phase_1")` returns `True`.
- `SchemaDefinition.is_valid_node_type("Specification", "phase_1")` returns `False`.

**`backends/networkx_backend.py`:**
- `add_node("AXI", "acronym", "doc.sv")` twice → `mention_count == 2`.
- `add_node("axi", "acronym", "doc2.sv")` → reuses canonical "AXI" (case dedup).
- `save()` then `load()` on a fresh instance → same `stats()`.
- Legacy graph (no `raw_mentions`) loads without `KeyError`.
- Self-edge `add_edge("A", "A", ...)` is silently dropped.

**`extraction/merge.py`:**
- Two extractors produce the same entity → `mention_count` is summed.
- Type conflict: sv_parser vs regex → sv_parser wins.
- Unknown type → fallback to `config.regex_fallback_type` with warning.
- Duplicate triple `(A, r, B)` → weight is summed (not duplicated).
- Invalid predicate → triple is dropped with warning.

**`query/entity_matcher.py`:**
- "AXI" matches in "AXI4 protocol" (token boundary).
- "AXI" does not match in "TAXIING" (token boundary enforced).
- `rebuild()` picks up new entities added after initial construction.

**`query/expander.py`:**
- `expand("AXI protocol")` returns neighbors of AXI entity.
- Fan-out respects `max_expansion_terms`.
- Terms already in the query are filtered out.
- Empty graph → `expand()` returns `[]`.

**`T20` backward compat shim:**
- `from src.core.knowledge_graph import KnowledgeGraphBuilder` issues `DeprecationWarning`.
- `KnowledgeGraphBuilder` is `NetworkXBackend`.
- `EntityExtractor` is `RegexEntityExtractor`.

---

## 5. Migration Checklist

Execute in strict order. Each step can be code-reviewed independently.

- [ ] **Step 1 (T1):** Create `src/knowledge_graph/` package skeleton. All `__init__.py` files are empty or contain placeholder docstrings. Run `python -c "import src.knowledge_graph"` — must not raise.
- [ ] **Step 2 (T12 — schema file):** Write `config/kg_schema.yaml`. Run `python -c "from src.knowledge_graph.common.types import load_schema; load_schema('config/kg_schema.yaml')"` — must not raise.
- [ ] **Step 3 (T19):** Add new config keys to `config/settings.py`. Run `python -c "from config.settings import KG_BACKEND"` — must not raise.
- [ ] **Step 4 (T2):** Write `backend.py`. Run `python -c "from src.knowledge_graph.backend import GraphStorageBackend"` — must not raise.
- [ ] **Step 5 (T5):** Write `extraction/base.py` and `extraction/regex_extractor.py`. Run regex extractor tests. Verify extraction parity with the monolith on a representative text sample.
- [ ] **Step 6 (T6):** Write `extraction/gliner_extractor.py`. GLiNER tests should pass with a mocked model.
- [ ] **Step 7 (T3):** Write `backends/networkx_backend.py`. Run backend ABC contract tests. Verify save/load round-trip with an existing `.knowledge_graph.json` file.
- [ ] **Step 8 (T4, T14, T15, T16):** Write all stubs. All stub tests should confirm `NotImplementedError` is raised.
- [ ] **Step 9 (T7):** Write `extraction/merge.py`. Run merge node tests with two extractor fixtures.
- [ ] **Step 10 (T8):** Write `query/entity_matcher.py`. Run entity matcher tests including token-boundary edge cases.
- [ ] **Step 11 (T10):** Write `query/sanitizer.py`.
- [ ] **Step 12 (T9):** Write `query/expander.py`. Run expander tests with a mock backend.
- [ ] **Step 13 (T13):** Write `export/obsidian.py`. Verify output against existing Obsidian export on a test graph.
- [ ] **Step 14 (T11):** Write `src/knowledge_graph/__init__.py` (final, replacing placeholder). Run end-to-end smoke test: `from src.knowledge_graph import get_graph_backend, get_query_expander; b = get_graph_backend(); e = get_query_expander()`.
- [ ] **Step 15 (T17):** Update `knowledge_graph_extraction_node` and `knowledge_graph_storage_node`. Update `state.py`. Run ingestion pipeline integration test with a small document.
- [ ] **Step 16 (T18):** Update `rag_chain.py`. Run retrieval pipeline test with a query that should expand.
- [ ] **Step 17 (T20 — last):** Replace `src/core/knowledge_graph.py` with the shim. Run backward-compat tests. Confirm `DeprecationWarning` is emitted. Run full test suite — no regressions.

---

## 6. Import Dependency Rules

To prevent circular imports, these rules must be followed strictly:

| Module | May Import From | Must NOT Import From |
|---|---|---|
| `common/schemas.py` | stdlib only | Anything in `src.knowledge_graph` |
| `common/types.py` | stdlib, `yaml`, `common/schemas.py` | `backend.py`, `extraction/`, `query/`, `backends/` |
| `common/utils.py` | stdlib, `common/types.py` (TYPE_CHECKING only) | `backend.py`, `extraction/`, `query/`, `backends/` |
| `backend.py` | stdlib, `common/schemas.py` | `backends/`, `extraction/`, `query/`, `__init__.py` |
| `backends/*.py` | `backend.py`, `common/` | `extraction/`, `query/`, `__init__.py` |
| `extraction/*.py` | `common/`, `backend.py` | `backends/`, `query/`, `__init__.py` |
| `query/*.py` | `common/`, `backend.py` | `backends/`, `extraction/`, `__init__.py` |
| `export/*.py` | `common/`, `backend.py` | `backends/`, `extraction/`, `query/`, `__init__.py` |
| `community/*.py` | `common/`, `backend.py` | `backends/`, `extraction/`, `query/`, `__init__.py` |
| `__init__.py` | All of the above | (is the top — nothing else in the package imports it) |

**Circular import trap to avoid:** `common/utils.py` uses `SchemaDefinition` from `common/types.py`. `common/types.py`'s `SchemaDefinition.__post_init__` imports from `common/utils.py`. This is safe — `__post_init__` is called after the module is loaded. Use `TYPE_CHECKING` guard in `utils.py` for the type annotation only.
