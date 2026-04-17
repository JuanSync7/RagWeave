# Knowledge Graph Subsystem — Build Execution Plan

## Document Information

| Field | Value |
|-------|-------|
| System | RagWeave Knowledge Graph Subsystem |
| Document Type | Build Execution Plan |
| Source of Truth | `KNOWLEDGE_GRAPH_DESIGN.md`, `KNOWLEDGE_GRAPH_IMPLEMENTATION.md` |
| Date | 2026-04-08 |
| Status | Ready for dispatch |

---

## 1. Execution Groups

### Group Summary

| Group | Tasks | Blocks On | Max Parallel Agents |
|-------|-------|-----------|---------------------|
| **G0** | T1, T12 | Nothing | 2 |
| **G1** | T2, T5, T6, T8, T10, T14, T15, T16, T19 | T1 complete | 9 |
| **G2** | T3, T4, T7, T9, T13 | T2 (for T3/T4/T13), T5+T6 (for T7), T8+T10 (for T9) | 5 (with partial unlock) |
| **G3** | T11 | T3, T9 | 1 |
| **G4** | T17, T18, T20 | T11 | 3 |

### G2 Partial Unlock Logic

G2 does not require all of G1 — it unlocks in sub-waves:
- **G2a** (unlocks when T2 done): T3, T4, T13
- **G2b** (unlocks when T5 + T6 done): T7
- **G2c** (unlocks when T8 + T10 done): T9

G3 unlocks only when **both T3 and T9** are complete.

---

## 2. Task Cards

### G0 — No Dependencies

---

#### T1 — Package Skeleton + Common Contracts
| Field | Value |
|-------|-------|
| **Group** | G0 |
| **Dependencies** | None |
| **Complexity** | simple |
| **Estimated LOC** | 250 |
| **Subagent?** | Yes |
| **Model** | haiku |

**Files to create:**
```
src/knowledge_graph/__init__.py           # placeholder docstring only
src/knowledge_graph/backend.py            # empty placeholder
src/knowledge_graph/common/__init__.py
src/knowledge_graph/common/schemas.py     # Entity, Triple, ExtractionResult, EntityDescription
src/knowledge_graph/common/types.py       # KGConfig, SchemaDefinition, load_schema() stub
src/knowledge_graph/common/utils.py       # normalize_alias, validate_type, derive_gliner_labels, is_phase_active
src/knowledge_graph/extraction/__init__.py
src/knowledge_graph/query/__init__.py
src/knowledge_graph/backends/__init__.py
src/knowledge_graph/community/__init__.py
src/knowledge_graph/export/__init__.py
```

**Summary:** Create the package directory tree and write the three `common/` modules with complete, final implementations (no stubs). `schemas.py` is pure dataclasses. `types.py` holds `KGConfig`, `SchemaDefinition`, and a `load_schema()` stub (algorithm detailed in the impl doc). `utils.py` holds four deterministic helpers. All subpackage `__init__.py` files are empty or contain placeholder docstrings. No business logic beyond what is listed.

---

#### T12 — YAML Schema File + Loader
| Field | Value |
|-------|-------|
| **Group** | G0 |
| **Dependencies** | None (schema file); T1 required for the `load_schema()` body to be merged in |
| **Complexity** | simple |
| **Estimated LOC** | 350 (250 YAML + 100 loader) |
| **Subagent?** | Yes |
| **Model** | haiku |

**Files to create/modify:**
```
config/kg_schema.yaml                     # Full schema: 41 node types, 22 edge types + 7 legacy types
```
**Files to modify after T1:**
```
src/knowledge_graph/common/types.py       # Implement load_schema() body (validation algorithm)
```

**Summary:** Write `config/kg_schema.yaml` with all node and edge types from the spec (24 structural phase_1 node types, 17 semantic phase_1b node types, 3 legacy compatibility types, 10 structural phase_1 edge types, 12 semantic phase_1b edge types, 4 legacy edge types). Then implement the `load_schema()` function in `common/types.py`: open with `yaml.safe_load`, parse into typed dataclasses, validate for duplicate names, invalid category/phase values, and duplicate `gliner_label` values — raise `ValueError` on hard errors, log warnings on soft ones.

---

### G1 — Requires T1

---

#### T2 — GraphStorageBackend ABC
| Field | Value |
|-------|-------|
| **Group** | G1 |
| **Dependencies** | T1 |
| **Complexity** | medium |
| **Estimated LOC** | 150 |
| **Subagent?** | Yes |
| **Model** | sonnet |

**Files to create:**
```
src/knowledge_graph/backend.py            # GraphStorageBackend ABC (replaces placeholder)
```

**Summary:** Write the `GraphStorageBackend` ABC mirroring the `src/guardrails/backend.py` pattern. Eleven abstract methods (`add_node`, `add_edge`, `upsert_entities`, `upsert_triples`, `upsert_descriptions`, `query_neighbors`, `get_entity`, `get_predecessors`, `save`, `load`, `stats`) plus four concrete optional-override methods with empty defaults (`get_all_entities`, `get_all_node_names_and_aliases`, `get_outgoing_edges`, `get_incoming_edges`). The last two are non-abstract and return `[]` by default to support T13 (Obsidian export) without requiring backend changes.

---

#### T5 — Regex Extractor + EntityExtractor Protocol
| Field | Value |
|-------|-------|
| **Group** | G1 |
| **Dependencies** | T1 |
| **Complexity** | medium |
| **Estimated LOC** | 250 |
| **Subagent?** | Yes |
| **Model** | sonnet |

**Files to create:**
```
src/knowledge_graph/extraction/base.py          # EntityExtractor Protocol (runtime_checkable)
src/knowledge_graph/extraction/regex_extractor.py  # RegexEntityExtractor
```

**Summary:** Write the `EntityExtractor` `@runtime_checkable` Protocol in `base.py` with three members (`name` property, `extract_entities`, `extract_relations`). Migrate `RegexEntityExtractor` from `src/core/knowledge_graph.py`, preserving all regex patterns (`_CAMEL_PAT`, `_ACRONYM_PAT`, `_MULTI_WORD_PAT`, etc.), `_STOPWORDS`, and all filtering logic exactly. Key interface change: `extract_relations()` now returns `List[Triple]` instead of `List[Tuple]`. Add `classify_type()` method and `extract_acronym_aliases()` as public methods.

---

#### T6 — GLiNER Extractor
| Field | Value |
|-------|-------|
| **Group** | G1 |
| **Dependencies** | T1, T5 |
| **Complexity** | medium |
| **Estimated LOC** | 120 |
| **Subagent?** | Yes |
| **Model** | sonnet |

**Files to create:**
```
src/knowledge_graph/extraction/gliner_extractor.py  # GLiNERExtractor
```

**Summary:** Migrate `GLiNEREntityExtractor` from the monolith, renaming it to `GLiNERExtractor`. Constructor accepts `SchemaDefinition` and derives labels via `derive_gliner_labels()` instead of hardcoded `GLINER_ENTITY_LABELS`. `extract_entities()` preserves all filtering (markdown strip, threshold=0.5, length > 2, stopwords). `extract_relations()` delegates entirely to `RegexEntityExtractor`. Implements `EntityExtractor` protocol.

---

#### T8 — spaCy Entity Matcher
| Field | Value |
|-------|-------|
| **Group** | G1 |
| **Dependencies** | T1 |
| **Complexity** | medium |
| **Estimated LOC** | 130 |
| **Subagent?** | Yes |
| **Model** | sonnet |

**Files to create:**
```
src/knowledge_graph/query/entity_matcher.py  # SpacyEntityMatcher
```

**Summary:** Write `SpacyEntityMatcher` using `spacy.blank("en")` (tokenizer only, no transformer) and `PhraseMatcher(attr="LOWER")` for token-boundary case-insensitive matching. `match()` returns canonical entity names for all matched phrases, using `spacy.util.filter_spans()` to prefer longer matches over nested shorter ones. `rebuild()` replaces the pattern set from an updated entity index. Raise `ImportError` with a clear message if spaCy is not installed.

---

#### T10 — Query Sanitizer
| Field | Value |
|-------|-------|
| **Group** | G1 |
| **Dependencies** | T1 |
| **Complexity** | simple |
| **Estimated LOC** | 100 |
| **Subagent?** | Yes |
| **Model** | sonnet |

**Files to create:**
```
src/knowledge_graph/query/sanitizer.py  # QuerySanitizer
```

**Summary:** Write `QuerySanitizer` with three methods: `normalize()` (lowercase, strip, replace hyphens/underscores with spaces, collapse whitespace), `expand_aliases()` (given matched entity names, return list including alias variants from the alias index), and `rebuild()` (replace alias index from updated graph data). Purely deterministic; no external dependencies beyond `re`.

---

#### T14 — Community Detection Stubs (Phase 2)
| Field | Value |
|-------|-------|
| **Group** | G1 |
| **Dependencies** | T1 |
| **Complexity** | simple |
| **Estimated LOC** | 60 |
| **Subagent?** | Yes |
| **Model** | haiku |

**Files to create:**
```
src/knowledge_graph/community/detector.py    # CommunityDetector stub
src/knowledge_graph/community/summarizer.py  # CommunitySummarizer stub
```

**Summary:** Write two Phase 2 stub classes. `CommunityDetector.__init__` accepts a `GraphStorageBackend`; its `detect()` method raises `NotImplementedError("Community detection is Phase 2: not yet implemented")`. `CommunitySummarizer.summarize()` similarly raises `NotImplementedError`. Both include proper `@summary` blocks and docstrings.

---

#### T15 — LLM Extractor + LLM Query Fallback Stubs (Phase 1b)
| Field | Value |
|-------|-------|
| **Group** | G1 |
| **Dependencies** | T1 |
| **Complexity** | simple |
| **Estimated LOC** | 100 |
| **Subagent?** | Yes |
| **Model** | haiku |

**Files to create:**
```
src/knowledge_graph/extraction/llm_extractor.py  # LLMExtractor stub
src/knowledge_graph/query/llm_fallback.py         # LLMFallbackMatcher stub
```

**Summary:** Write two Phase 1b stub classes. `LLMExtractor` accepts `SchemaDefinition` and `runtime_phase`; has `@property name -> "llm"`. Both `extract_entities()` and `extract_relations()` raise `NotImplementedError("LLM extractor is Phase 1b: not yet implemented")`. `LLMFallbackMatcher.match()` similarly raises `NotImplementedError`. Stubs must be importable and instantiatable without error.

---

#### T16 — SV Parser Extractor Stub (Phase 1b)
| Field | Value |
|-------|-------|
| **Group** | G1 |
| **Dependencies** | T1 |
| **Complexity** | simple |
| **Estimated LOC** | 60 |
| **Subagent?** | Yes |
| **Model** | haiku |

**Files to create:**
```
src/knowledge_graph/extraction/sv_parser.py  # SVParserExtractor stub
```

**Summary:** Write `SVParserExtractor` as a Phase 1b stub. Constructor accepts `SchemaDefinition`; `@property name -> "sv_parser"`. Both `extract_entities()` and `extract_relations()` raise `NotImplementedError("SV parser is Phase 1b: not yet implemented")`. Implements the `EntityExtractor` protocol structurally (duck-typing compatible).

---

#### T19 — Config Keys in settings.py
| Field | Value |
|-------|-------|
| **Group** | G1 |
| **Dependencies** | T1 |
| **Complexity** | simple |
| **Estimated LOC** | 60 |
| **Subagent?** | Yes |
| **Model** | sonnet |

**Files to modify:**
```
config/settings.py  # Add 14 new KG_* environment variable bindings
```

**Summary:** Read `config/settings.py` and insert the 14 new `KG_*` keys (listed in the implementation doc Section T19) after the existing `KG_ENABLED`/`KG_PATH` block. All keys read from `os.environ` with typed defaults. Preserve `KG_ENABLED`, `KG_PATH`, and `KG_OBSIDIAN_EXPORT_DIR` unchanged. No other files touched.

---

### G2 — Partial Unlock (see G2a/G2b/G2c)

---

#### T3 — NetworkXBackend
| Field | Value |
|-------|-------|
| **Group** | G2a (unlocks: T2) |
| **Dependencies** | T1, T2 |
| **Complexity** | complex |
| **Estimated LOC** | 300 |
| **Subagent?** | Yes |
| **Model** | opus |

**Files to create:**
```
src/knowledge_graph/backends/networkx_backend.py  # NetworkXBackend
```

**Summary:** Implement `NetworkXBackend(GraphStorageBackend)` backed by `nx.DiGraph` with `orjson` serialization. Core: `_resolve()` helper (alias index → case index → register-first-seen). `add_node` increments `mention_count` and extends `sources`/`aliases` on collision; first-seen form is canonical. `add_edge` accumulates weight on duplicate edges; silently drops self-edges. `save()`/`load()` use `nx.node_link_data`/`nx.node_link_graph` + orjson — must be backward-compatible with existing `.knowledge_graph.json` files. `upsert_descriptions()` appends to `raw_mentions` and triggers `trigger_summarization_if_needed()` from `extraction/merge.py` when token budget is exceeded. `query_neighbors()` combines BFS forward + direct predecessors. Override `get_outgoing_edges()` and `get_incoming_edges()` (needed by Obsidian export). Error handling: wrap all `add_*`/`upsert_*` in try/except and log at WARNING; save/load raise with descriptive messages.

---

#### T4 — Neo4j Backend Stub (Phase 2)
| Field | Value |
|-------|-------|
| **Group** | G2a (unlocks: T2) |
| **Dependencies** | T1, T2 |
| **Complexity** | simple |
| **Estimated LOC** | 80 |
| **Subagent?** | Yes |
| **Model** | haiku |

**Files to create:**
```
src/knowledge_graph/backends/neo4j_backend.py  # Neo4jBackend stub
```

**Summary:** Write `Neo4jBackend(GraphStorageBackend)` as a Phase 2 stub. All 11 abstract methods raise `NotImplementedError("Neo4j backend is Phase 2: not yet implemented")`. Minimal or no `__init__`. Importable and instantiatable without error; the only behavior is the `NotImplementedError` on method calls.

---

#### T7 — Merge Node + Entity Description Accumulation
| Field | Value |
|-------|-------|
| **Group** | G2b (unlocks: T5 + T6) |
| **Dependencies** | T1, T5, T6 |
| **Complexity** | complex |
| **Estimated LOC** | 250 |
| **Subagent?** | Yes |
| **Model** | opus |

**Files to create:**
```
src/knowledge_graph/extraction/merge.py  # merge_extraction_results and helpers
```
**Files to modify:**
```
src/knowledge_graph/extraction/__init__.py  # ExtractionPipeline class
```

**Summary:** Write `merge.py` with `merge_extraction_results()` (flatten → dedup entities → dedup triples → accumulate descriptions), `_deduplicate_entities()` (normalize-alias key, type-conflict resolution by extractor priority rank), `_deduplicate_triples()` (key on normalized subject+predicate+object, sum weights, drop invalid predicates with warning), `_accumulate_descriptions()`, and `trigger_summarization_if_needed()` (token budget check with 1.33 word-to-token heuristic, LLM summarize via internal helper, top-K retention). Also implement `ExtractionPipeline` in `extraction/__init__.py`: `_build_extractors()` based on `KGConfig` flags, `run()` as a sequential loop over extractors + chunks (Phase 1 — LangGraph parallel subgraph is Phase 1b), `_run_extractor()` helper that produces `ExtractionResult` per extractor.

---

#### T9 — Query Expander
| Field | Value |
|-------|-------|
| **Group** | G2c (unlocks: T8 + T10) |
| **Dependencies** | T1, T2, T8, T10 |
| **Complexity** | complex |
| **Estimated LOC** | 150 |
| **Subagent?** | Yes |
| **Model** | opus |

**Files to create:**
```
src/knowledge_graph/query/expander.py  # GraphQueryExpander
```

**Summary:** Migrate and enhance `GraphQueryExpander` from the monolith. Constructor takes `GraphStorageBackend` and `KGConfig`; builds `SpacyEntityMatcher` and `QuerySanitizer` from the backend's entity index. `match_entities()` normalizes then delegates to the matcher. `expand()` gets seed entities, optionally falls back to `LLMFallbackMatcher` (catching `NotImplementedError` silently), traverses graph neighbors up to depth (hard cap: 3), filters terms already in the query, and applies `max_expansion_terms` fan-out limit. `get_context_summary()` builds a text summary preferring `current_summary` over `raw_mentions[0].text`. `rebuild_matcher()` refreshes both matcher and sanitizer from the current graph state.

---

#### T13 — Obsidian Export
| Field | Value |
|-------|-------|
| **Group** | G2a (unlocks: T2) |
| **Dependencies** | T1, T2 |
| **Complexity** | medium |
| **Estimated LOC** | 100 |
| **Subagent?** | Yes |
| **Model** | sonnet |

**Files to create:**
```
src/knowledge_graph/export/obsidian.py  # export_obsidian()
```

**Summary:** Migrate `export_obsidian()` from `src/core/knowledge_graph.py`. New signature accepts `GraphStorageBackend` (not `nx.DiGraph`). Iterates all entities via `backend.get_all_entities()`, writes one `.md` file per entity with safe filename, type/aliases/mentions/sources metadata, entity description (prefer `current_summary` then `raw_mentions[0].text[:300]`), and `[[wikilink]]`-formatted outgoing and incoming edges from `backend.get_outgoing_edges()` and `backend.get_incoming_edges()`. Returns count of files written.

---

### G3 — Requires T3 + T9

---

#### T11 — Public API (`__init__.py`) with Lazy Singleton
| Field | Value |
|-------|-------|
| **Group** | G3 |
| **Dependencies** | T3, T4, T9 |
| **Complexity** | medium |
| **Estimated LOC** | 130 |
| **Subagent?** | Yes |
| **Model** | sonnet |

**Files to modify:**
```
src/knowledge_graph/__init__.py  # Replace placeholder with full public API
```

**Summary:** Replace the placeholder `__init__.py` with the lazy singleton dispatcher. Inline `_NoOpBackend` (all 11 methods are no-ops or return empties). `get_graph_backend()` checks `_backend` global; on first call, reads config, selects `NetworkXBackend` or `_NoOpBackend` (or raises `ValueError` for unknown keys), and loads existing graph from `KG_PATH` if the file exists. `get_query_expander()` checks `_expander` global; on first call, creates `GraphQueryExpander` bound to the singleton backend. `_build_kg_config()` reads all 14 `KG_*` settings from `config.settings`. Export `__all__` with all public names. Mirror `src/guardrails/__init__.py` pattern exactly.

---

### G4 — Requires T11

---

#### T17 — Update Ingest Pipeline Nodes
| Field | Value |
|-------|-------|
| **Group** | G4 |
| **Dependencies** | T11, T5, T6, T7 |
| **Complexity** | complex |
| **Estimated LOC** | 150 |
| **Subagent?** | Yes |
| **Model** | opus |

**Files to modify:**
```
src/ingest/embedding/nodes/knowledge_graph_extraction.py  # Replace with ExtractionPipeline delegation
src/ingest/embedding/nodes/knowledge_graph_storage.py      # Replace with get_graph_backend() delegation
src/ingest/embedding/state.py                              # Add kg_extraction_result field
```

**Summary:** Replace Node 10 (`knowledge_graph_extraction_node`) to construct `KGConfig` + `SchemaDefinition`, run `ExtractionPipeline.run(state["chunks"])`, and store the result in `state["kg_extraction_result"]`. Replace Node 13 (`knowledge_graph_storage_node`) to call `get_graph_backend()`, read `kg_extraction_result` (or fall back to legacy `kg_triples`), call `upsert_entities`/`upsert_triples`/`upsert_descriptions`, then `backend.save(KG_PATH)`. Add `kg_extraction_result: Optional[Any]` to `EmbeddingPipelineState` TypedDict alongside the existing `kg_triples` field (keep for backward compat). Both nodes must handle exceptions and log to `processing_log`.

---

#### T18 — Update Retrieval Pipeline
| Field | Value |
|-------|-------|
| **Group** | G4 |
| **Dependencies** | T11, T9 |
| **Complexity** | complex |
| **Estimated LOC** | 50 |
| **Subagent?** | Yes |
| **Model** | opus |

**Files to modify:**
```
src/retrieval/pipeline/rag_chain.py  # Replace direct KG construction with lazy singleton
```

**Summary:** Read `rag_chain.py` and locate Stage 2 KG expansion logic. Replace the `from src.core.knowledge_graph import KnowledgeGraphBuilder, GraphQueryExpander` import and any per-call `KnowledgeGraphBuilder.load()` / `GraphQueryExpander()` construction with a single `from src.knowledge_graph import get_query_expander` and `expander = get_query_expander()` call (process-wide singleton). Remove the manual BM25 term limit (now enforced inside `expander.expand()` via `max_expansion_terms`). Do not construct a new expander per query.

---

#### T20 — Backward Compatibility Shim
| Field | Value |
|-------|-------|
| **Group** | G4 |
| **Dependencies** | T11, T3, T5, T6, T9, T13 |
| **Complexity** | medium |
| **Estimated LOC** | 50 |
| **Subagent?** | Yes |
| **Model** | sonnet |

**Files to modify:**
```
src/core/knowledge_graph.py  # Full replacement with re-export shim
```

**Summary:** Replace the 558-line monolith with a minimal shim that emits `DeprecationWarning` on import and re-exports the five legacy public names as aliases: `KnowledgeGraphBuilder = NetworkXBackend`, `GraphQueryExpander` (same name), `EntityExtractor = RegexEntityExtractor`, `GLiNEREntityExtractor = GLiNERExtractor`, `export_obsidian` (same name). This is the last task — all callers (T17, T18) must be migrated before T20 is deployed, since `add_chunk()` no longer exists.

---

## 3. Dispatch Strategy

### Model Assignment

| Model | Tasks | Rationale |
|-------|-------|-----------|
| **opus** | T3, T7, T9, T17, T18 | High algorithmic complexity: `_resolve()` correctness, merge dedup logic, expander fan-out + fallback, pipeline node rewiring |
| **sonnet** | T2, T5, T6, T8, T10, T11, T13, T19, T20 | Medium complexity: well-specified contracts with clear input/output; migration + wiring work |
| **haiku** | T1, T4, T12, T14, T15, T16 | Simple/stub work: dataclass definitions, NotImplementedError stubs, env-var bindings, YAML authoring |

### Parallel Dispatch per Group

```
G0  [2 agents]:  T1(haiku), T12(haiku)
                       |
G1  [9 agents]:  T2(sonnet), T5(sonnet), T6(sonnet), T8(sonnet),
                 T10(sonnet), T14(haiku), T15(haiku), T16(haiku), T19(sonnet)
                       |
G2a [3 agents]:  T3(opus), T4(haiku), T13(sonnet)          ← after T2
G2b [1 agent]:   T7(opus)                                   ← after T5 + T6
G2c [1 agent]:   T9(opus)                                   ← after T8 + T10
                       |
G3  [1 agent]:   T11(sonnet)                                ← after T3 + T9
                       |
G4  [3 agents]:  T17(opus), T18(opus), T20(sonnet)
```

**Total agents in flight (peak):** 9 (G1)
**Sequential bottlenecks:** G3 (T11) and the G2 partial unlocks create natural synchronization points.

---

## 4. Verification Checkpoints

### After G0

**Goal:** Package skeleton exists; YAML schema parseable.

```bash
# Skeleton importable
python -c "import src.knowledge_graph; print('OK')"

# Schema loads cleanly
python -c "
from src.knowledge_graph.common.types import load_schema
s = load_schema('config/kg_schema.yaml')
print(f'Nodes: {len(s.node_types)}, Edges: {len(s.edge_types)}')
"
# Expected: Nodes: 44, Edges: 26  (41 + 3 legacy / 22 + 4 legacy)

# Schemas importable
python -c "
from src.knowledge_graph.common.schemas import Entity, Triple, ExtractionResult
from src.knowledge_graph.common.types import KGConfig
print('schemas OK')
"
```

---

### After G1

**Goal:** ABC, extractors, query helpers, stubs, and settings all importable.

```bash
# ABC importable
python -c "from src.knowledge_graph.backend import GraphStorageBackend; print('ABC OK')"

# Regex extractor protocol check
python -c "
from src.knowledge_graph.extraction.base import EntityExtractor
from src.knowledge_graph.extraction.regex_extractor import RegexEntityExtractor
e = RegexEntityExtractor()
assert isinstance(e, EntityExtractor), 'Protocol check failed'
print('regex OK')
"

# Stubs raise NotImplementedError (not ImportError)
python -c "
from src.knowledge_graph.extraction.llm_extractor import LLMExtractor
from src.knowledge_graph.extraction.sv_parser import SVParserExtractor
from src.knowledge_graph.backends.neo4j_backend import Neo4jBackend
print('stubs importable OK')
"

# Settings keys present
python -c "from config.settings import KG_BACKEND, KG_SCHEMA_PATH, KG_MAX_EXPANSION_DEPTH; print('settings OK')"
```

---

### After G2

**Goal:** Backend operational; merge node correct; query pipeline functional.

```bash
# NetworkX backend round-trip
python -c "
import pathlib, tempfile
from src.knowledge_graph.backends.networkx_backend import NetworkXBackend
b = NetworkXBackend()
b.add_node('AXI', 'acronym', 'test.sv')
b.add_node('axi', 'acronym', 'test2.sv')  # case dedup
assert b.stats()['nodes'] == 1, 'Dedup failed'
with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
    path = pathlib.Path(f.name)
b.save(path)
b2 = NetworkXBackend()
b2.load(path)
assert b2.stats()['nodes'] == 1, 'Load failed'
print('NetworkX OK')
"

# Self-edge drop
python -c "
from src.knowledge_graph.backends.networkx_backend import NetworkXBackend
b = NetworkXBackend()
b.add_node('A', 'concept', 'doc')
b.add_edge('A', 'A', 'relates_to', 'doc')
assert b.stats()['edges'] == 0, 'Self-edge not dropped'
print('self-edge OK')
"

# Entity matcher token-boundary check
python -c "
from src.knowledge_graph.query.entity_matcher import SpacyEntityMatcher
m = SpacyEntityMatcher({'axi': 'AXI'})
assert 'AXI' in m.match('AXI4 protocol')
assert 'AXI' not in m.match('TAXIING')
print('matcher OK')
"

# Expander smoke test with NoOp backend
python -c "
from src.knowledge_graph.common.types import KGConfig
from src.knowledge_graph.query.expander import GraphQueryExpander

class _Noop:
    def get_all_node_names_and_aliases(self): return {}
    def query_neighbors(self, e, depth=1): return []
    def get_entity(self, n): return None

exp = GraphQueryExpander(backend=_Noop(), config=KGConfig())
result = exp.expand('AXI protocol')
assert result == [], f'Expected empty, got {result}'
print('expander OK')
"
```

---

### After G3

**Goal:** Public API singleton works end-to-end.

```bash
# Full public API smoke test
python -c "
from src.knowledge_graph import get_graph_backend, get_query_expander
b = get_graph_backend()
e = get_query_expander()
print(f'Backend: {type(b).__name__}')
print(f'Expander: {type(e).__name__}')
print('public API OK')
"

# __all__ completeness
python -c "
import src.knowledge_graph as kg
required = {'get_graph_backend', 'get_query_expander', 'Entity', 'Triple',
            'ExtractionResult', 'EntityDescription', 'KGConfig',
            'SchemaDefinition', 'GraphStorageBackend'}
missing = required - set(kg.__all__)
assert not missing, f'Missing from __all__: {missing}'
print('__all__ OK')
"
```

---

### After G4

**Goal:** Full integration; backward compat shim emits warning; no regressions.

```bash
# Ingest pipeline state has new field
python -c "
from src.ingest.embedding.state import EmbeddingPipelineState
import typing
hints = typing.get_type_hints(EmbeddingPipelineState)
assert 'kg_extraction_result' in hints, 'State field missing'
print('state OK')
"

# Backward compat shim
python -c "
import warnings
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter('always')
    from src.core.knowledge_graph import KnowledgeGraphBuilder, GraphQueryExpander
    assert len(w) == 1
    assert issubclass(w[0].category, DeprecationWarning)
    print('shim DeprecationWarning OK')
"

# Shim aliases are correct types
python -c "
import warnings
warnings.simplefilter('ignore', DeprecationWarning)
from src.core.knowledge_graph import KnowledgeGraphBuilder
from src.knowledge_graph.backends.networkx_backend import NetworkXBackend
assert KnowledgeGraphBuilder is NetworkXBackend
print('shim alias OK')
"

# Run existing KG tests
pytest tests/ingest/embedding/test_kg_extraction.py tests/ingest/embedding/test_kg_storage.py -v
```

---

## 5. Critical Constraints

### Import Dependency Rules (must not be violated)

| Module | May Import | Must NOT Import |
|--------|------------|-----------------|
| `common/schemas.py` | stdlib only | Anything in `src.knowledge_graph` |
| `common/types.py` | stdlib, yaml, `common/schemas.py` | `backend.py`, `extraction/`, `query/`, `backends/` |
| `common/utils.py` | stdlib, `common/types.py` (TYPE_CHECKING only) | `backend.py`, `extraction/`, `query/`, `backends/` |
| `backend.py` | stdlib, `common/schemas.py` | `backends/`, `extraction/`, `query/`, `__init__.py` |
| `backends/*.py` | `backend.py`, `common/` | `extraction/`, `query/`, `__init__.py` |
| `extraction/*.py` | `common/`, `backend.py` | `backends/`, `query/`, `__init__.py` |
| `query/*.py` | `common/`, `backend.py` | `backends/`, `extraction/`, `__init__.py` |
| `export/*.py` | `common/`, `backend.py` | `backends/`, `extraction/`, `query/`, `__init__.py` |
| `community/*.py` | `common/`, `backend.py` | `backends/`, `extraction/`, `query/`, `__init__.py` |
| `__init__.py` | All of the above | (nothing else in the package imports it) |

### T20 Sequencing

T20 (backward compat shim) must be the **last task dispatched**. All callers (`rag_chain.py`, `knowledge_graph_extraction.py`, `knowledge_graph_storage.py`) must be migrated via T17 and T18 before T20 replaces the monolith, because `KnowledgeGraphBuilder.add_chunk()` no longer exists in the new package.

### T3 ↔ T7 Circular Reference

`NetworkXBackend.upsert_descriptions()` calls `trigger_summarization_if_needed()` from `extraction/merge.py`. This is a runtime import (inside the method body), not a module-level import. Ensure T3 uses a deferred import to avoid a circular dependency at module load time.
