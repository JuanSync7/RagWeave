# Knowledge Graph Subsystem — Test Plan

**System:** RagWeave Knowledge Graph Subsystem
**Date:** 2026-04-08
**Spec Reference:** `KNOWLEDGE_GRAPH_SPEC.md`

---

## 1. Test Scope

### In Scope
- All Phase 1 modules in `src/knowledge_graph/`
- Integration with ingest pipeline (Node 10, Node 13)
- Integration with retrieval pipeline (Stage 2 KG expansion)
- Backward compatibility shim (`src/core/knowledge_graph.py`)
- YAML schema loading and validation
- Configuration from environment variables

### Out of Scope
- Phase 1b stubs (they raise NotImplementedError by design)
- Phase 2 stubs (same)
- GLiNER model loading (requires model files)
- spaCy-specific tests (optional dependency)

---

## 2. Test Modules

### Module 1: `test_schemas.py` — Data Contract Tests

| Test ID | Description | REQ |
|---------|-------------|-----|
| S-01 | Entity dataclass creates with defaults | KG-201 |
| S-02 | Triple dataclass creates with all fields | KG-201 |
| S-03 | ExtractionResult aggregates entities and triples | KG-201 |
| S-04 | EntityDescription stores text, source, chunk_id | KG-400 |
| S-05 | Entity with raw_mentions list | KG-400 |

### Module 2: `test_types.py` — Config and Schema Tests

| Test ID | Description | REQ |
|---------|-------------|-----|
| T-01 | KGConfig.from_env() reads defaults | KG-904 |
| T-02 | KGConfig.from_env() reads custom env vars | KG-904 |
| T-03 | load_schema() loads valid YAML | KG-100 |
| T-04 | load_schema() validates duplicate node names | KG-100 |
| T-05 | load_schema() validates invalid phase values | KG-100 |
| T-06 | load_schema() validates duplicate gliner_labels | KG-110 |
| T-07 | SchemaDefinition.active_node_types() filters by phase | KG-107 |
| T-08 | SchemaDefinition.active_edge_types() filters by phase | KG-107 |

### Module 3: `test_utils.py` — Helper Function Tests

| Test ID | Description | REQ |
|---------|-------------|-----|
| U-01 | normalize_alias resolves acronym | KG-301 |
| U-02 | normalize_alias deduplicates case-insensitively | KG-301 |
| U-03 | normalize_alias first-seen form is canonical | KG-301 |
| U-04 | validate_type accepts active phase type | KG-107 |
| U-05 | validate_type rejects inactive phase type | KG-107 |
| U-06 | derive_gliner_labels returns active types only | KG-110 |
| U-07 | derive_gliner_labels uses gliner_label override | KG-110 |
| U-08 | is_phase_active ordering: phase_1 < phase_1b < phase_2 | KG-107 |

### Module 4: `test_networkx_backend.py` — Backend Contract Tests

| Test ID | Description | REQ |
|---------|-------------|-----|
| B-01 | add_node creates entity | KG-500 |
| B-02 | add_node deduplicates case-insensitively | KG-500 |
| B-03 | add_node increments mention_count | KG-500 |
| B-04 | add_node merges sources and aliases | KG-500 |
| B-05 | add_edge creates relationship | KG-501 |
| B-06 | add_edge increments weight on repeat | KG-501 |
| B-07 | add_edge drops self-edges silently | KG-501 |
| B-08 | get_entity returns Entity by name | KG-502 |
| B-09 | get_entity returns None for missing | KG-502 |
| B-10 | get_entity is case-insensitive | KG-502 |
| B-11 | query_neighbors returns 1-hop neighbours | KG-600 |
| B-12 | query_neighbors respects depth | KG-600 |
| B-13 | get_predecessors returns incoming entities | KG-600 |
| B-14 | upsert_entities batch adds | KG-500 |
| B-15 | upsert_triples batch adds | KG-501 |
| B-16 | upsert_descriptions appends mentions | KG-400 |
| B-17 | save/load roundtrip preserves graph | KG-503 |
| B-18 | save/load backward compatible with legacy format | KG-503 |
| B-19 | stats returns node/edge counts | KG-504 |
| B-20 | get_outgoing_edges returns triples | KG-800 |
| B-21 | get_incoming_edges returns triples | KG-800 |
| B-22 | get_all_entities returns all | KG-502 |
| B-23 | get_all_node_names_and_aliases builds index | KG-502 |

### Module 5: `test_regex_extractor.py` — Regex Extraction Tests

| Test ID | Description | REQ |
|---------|-------------|-----|
| R-01 | Extracts CamelCase entities (TensorFlow, PyTorch) | KG-300 |
| R-02 | Extracts ALL-CAPS acronyms (RAG, BM25) | KG-300 |
| R-03 | Extracts multi-word phrases (Machine Learning) | KG-300 |
| R-04 | Filters stopwords | KG-300 |
| R-05 | Extracts acronym aliases (RAG → Retrieval-Augmented Generation) | KG-301 |
| R-06 | Extracts "is_a" relations | KG-302 |
| R-07 | Extracts "subset_of" relations | KG-302 |
| R-08 | Extracts "used_for" relations | KG-302 |
| R-09 | Extracts "such as" relations | KG-302 |
| R-10 | extract() returns ExtractionResult with entities and triples | KG-300 |
| R-11 | Sets extractor_source correctly | KG-300 |

### Module 6: `test_entity_matcher.py` — Query Matching Tests

| Test ID | Description | REQ |
|---------|-------------|-----|
| M-01 | Substring match finds exact entity name | KG-600 |
| M-02 | Substring match is case-insensitive | KG-600 |
| M-03 | Substring match prefers longer matches | KG-600 |
| M-04 | Alias resolution returns canonical name | KG-600 |
| M-05 | match_with_llm_fallback returns same as match (Phase 1) | KG-600 |
| M-06 | Empty query returns empty list | KG-600 |

### Module 7: `test_expander.py` — Query Expansion Tests

| Test ID | Description | REQ |
|---------|-------------|-----|
| E-01 | Expands query with 1-hop neighbours | KG-600 |
| E-02 | Includes predecessors in expansion | KG-600 |
| E-03 | Filters terms already in query | KG-601 |
| E-04 | Respects max_terms limit | KG-601 |
| E-05 | Returns empty for unknown entities | KG-600 |
| E-06 | get_context_summary builds relationship text | KG-602 |
| E-07 | rebuild_matcher picks up new entities | KG-600 |

### Module 8: `test_sanitizer.py` — Query Sanitization Tests

| Test ID | Description | REQ |
|---------|-------------|-----|
| Q-01 | normalize lowercases and strips whitespace | KG-601 |
| Q-02 | normalize replaces hyphens/underscores with spaces | KG-601 |
| Q-03 | expand_aliases adds known aliases | KG-601 |
| Q-04 | sanitize_cypher returns identity (Phase 1) | KG-601 |
| Q-05 | rebuild replaces alias index | KG-601 |

### Module 9: `test_description_manager.py` — Description Tests

| Test ID | Description | REQ |
|---------|-------------|-----|
| D-01 | add_mention appends new mention | KG-400 |
| D-02 | add_mention deduplicates same text+source | KG-400 |
| D-03 | add_mention trims when over budget | KG-401 |
| D-04 | build_summary concatenates with source tags | KG-402 |
| D-05 | get_retrieval_text prefers summary over raw | KG-403 |

### Module 10: `test_public_api.py` — Integration Tests

| Test ID | Description | REQ |
|---------|-------------|-----|
| A-01 | get_graph_backend returns NetworkXBackend | KG-200 |
| A-02 | get_graph_backend returns singleton | KG-200 |
| A-03 | get_query_expander returns functional expander | KG-200 |
| A-04 | reset_singletons clears cached backend | KG-200 |
| A-05 | export_obsidian writes markdown files | KG-800 |

### Module 11: `test_backward_compat.py` — Shim Tests

| Test ID | Description | REQ |
|---------|-------------|-----|
| C-01 | Import from src.core.knowledge_graph emits DeprecationWarning | KG-206 |
| C-02 | KnowledgeGraphBuilder.add_chunk works | KG-206 |
| C-03 | KnowledgeGraphBuilder.save/load roundtrip | KG-206 |
| C-04 | KnowledgeGraphBuilder.stats returns dict | KG-206 |
| C-05 | EntityExtractor alias resolves to RegexEntityExtractor | KG-206 |

### Module 12: `test_pipeline_integration.py` — Pipeline Tests

| Test ID | Description | REQ |
|---------|-------------|-----|
| P-01 | knowledge_graph_extraction_node returns triples | KG-900 |
| P-02 | knowledge_graph_extraction_node skips when disabled | KG-900 |
| P-03 | knowledge_graph_extraction_node handles errors | KG-900 |
| P-04 | knowledge_graph_storage_node upserts to backend | KG-901 |
| P-05 | knowledge_graph_storage_node skips when disabled | KG-901 |
| P-06 | knowledge_graph_storage_node falls back to legacy | KG-901 |

---

## 3. Test Directory Structure

```
tests/knowledge_graph/
├── __init__.py
├── test_schemas.py
├── test_types.py
├── test_utils.py
├── test_networkx_backend.py
├── test_regex_extractor.py
├── test_entity_matcher.py
├── test_expander.py
├── test_sanitizer.py
├── test_description_manager.py
├── test_public_api.py
├── test_backward_compat.py
└── test_pipeline_integration.py
```

---

## 4. Test Priorities

**Must run (CI blocking):** Modules 1-5 (contracts, config, backend, extraction)
**Should run:** Modules 6-9 (query layer)
**Integration:** Modules 10-12 (may need fixtures/mocks for pipeline state)
