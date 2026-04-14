# Knowledge Graph Evaluation Framework

**Status:** Planning  
**Date:** 2026-04-09  
**Subsystem:** `src/knowledge_graph/`  
**Eval root:** `evals/`

---

## 1. Purpose and Scope

This document defines an evaluation framework for measuring the **output quality** of the RagWeave Knowledge Graph subsystem. It is distinct from the unit test suite (`tests/knowledge_graph/`), which tests code correctness against synthetic data.

The eval framework answers three questions:

1. **How good are the extractors?** -- Given real ASIC/semiconductor documents, how accurately does each extractor (regex, GLiNER, LLM, SV tree-sitter, Python AST, Bash regex) identify entities and relationships compared to human-labeled ground truth?
2. **How good is entity resolution?** -- When multiple extractors produce overlapping entities, does the merge logic correctly unify duplicates without collapsing distinct entities?
3. **How much does KG augmentation help retrieval?** -- Does KG-based query expansion improve retrieval quality compared to vanilla vector search?

### Goals

- **Quality tracking:** Establish baseline metrics and track them across releases.
- **Regression detection:** Catch quality degradations when extractors, schemas, or resolution logic change.
- **Extractor comparison:** Quantify the marginal value of each extractor (regex vs GLiNER vs LLM vs parser) on the same document set.
- **Retrieval impact measurement:** Isolate the retrieval lift attributable to KG expansion and community summaries.

### Non-Goals

- This framework does not test code correctness (that is `tests/knowledge_graph/`).
- This framework does not benchmark latency or throughput (that is a performance harness).
- This framework does not produce training data for model fine-tuning.

---

## 2. Evaluation Dimensions

### 2.1 Entity Extraction Quality

Measure per-extractor accuracy against golden entity labels.

| Metric | Definition | Granularity |
|--------|-----------|-------------|
| Precision | TP / (TP + FP) | Per extractor, per entity type |
| Recall | TP / (TP + FN) | Per extractor, per entity type |
| F1 | 2 * P * R / (P + R) | Per extractor, per entity type |
| Macro-F1 | Unweighted mean of per-type F1 scores | Per extractor |
| Type accuracy | Fraction of extracted entities assigned the correct type | Per extractor |

**Matching strategy:** An extracted entity is a true positive if it matches a golden entity by normalized name (case-folded, underscore-normalized) AND type. Partial name matches (see Section 5) are scored separately.

**Extractor breakdown:** Results are reported individually for each extractor registered in `src/knowledge_graph/extraction/`:

- `regex_extractor` -- regex patterns over raw text
- `gliner_extractor` -- GLiNER NER model
- `llm_extractor` -- LLM structured-output extraction
- `parser_extractor` (SV) -- tree-sitter SystemVerilog parser
- `python_parser` -- Python AST parser
- `bash_parser` -- Bash regex parser

Additionally, report the **union** (all extractors merged) to measure ensemble quality.

### 2.2 Relationship Extraction Quality

Measure accuracy of extracted triples against golden relationship labels.

| Metric | Definition | Granularity |
|--------|-----------|-------------|
| Triple precision | TP / (TP + FP) | Per extractor, per edge type |
| Triple recall | TP / (TP + FN) | Per extractor, per edge type |
| Triple F1 | Harmonic mean of triple precision and recall | Per extractor, per edge type |
| Predicate accuracy | Fraction of triples with correct predicate given correct subject-object pair | Per extractor |

**Matching strategy:** A triple (S, P, O) is a true positive if subject and object match golden entities by normalized name AND the predicate matches the golden edge type. Subject-object matches with wrong predicate count as predicate errors (FP for the wrong predicate, FN for the correct one).

### 2.3 Entity Resolution Quality

Measure correctness of the merge/deduplication logic that unifies entities across extractors and documents.

| Metric | Definition |
|--------|-----------|
| Merge precision | Fraction of performed merges that are correct (same real-world entity) |
| Merge recall | Fraction of golden merge pairs that were actually merged |
| Split rate | Fraction of golden entities that were incorrectly split into 2+ graph nodes |
| Lump rate | Fraction of distinct golden entities that were incorrectly merged together |

**Golden data format:** The golden dataset includes a `merge_groups` field -- a list of sets where each set contains entity names that refer to the same real-world entity (e.g., `["axi_master", "AXI Master", "axi_mstr"]`). The eval compares actual merge behavior against these groups.

### 2.4 Community Detection Quality

Measure the quality of Leiden community partitioning and LLM-generated community summaries.

| Metric | Definition |
|--------|-----------|
| Modularity | Newman modularity score of the detected partition |
| Coverage | Fraction of graph nodes assigned to a non-singleton community |
| Summary coherence | LLM-as-judge score (1-5) of whether the community summary accurately describes the community members |
| Summary faithfulness | LLM-as-judge score (1-5) of whether the summary contains only claims supported by the community's entities and edges |

**Note:** Community detection evals require a populated graph and are run as an end-to-end step, not per-extractor.

### 2.5 Retrieval Augmentation Quality

Measure whether KG-augmented retrieval outperforms vanilla vector search.

| Metric | Definition |
|--------|-----------|
| Hit rate (H@k) | Fraction of queries where at least one relevant chunk appears in top-k results |
| Mean Reciprocal Rank (MRR) | Mean of 1/rank for the first relevant result across all queries |
| Precision@k | Mean fraction of relevant chunks in top-k results |
| KG lift (delta) | Difference in each metric between KG-augmented and vanilla retrieval |

**Experimental conditions:**

1. **Vanilla:** Vector search only (no KG expansion).
2. **KG-local:** Vector search + entity neighbour expansion via `GraphQueryExpander`.
3. **KG-global:** Vector search + entity expansion + community summary terms (Phase 2).

All three conditions use the same query set, embeddings, and reranker. Only the query expansion step differs.

---

## 3. Golden Dataset Specification

### 3.1 Directory Structure

```
evals/
  knowledge_graph/
    fixtures/
      asic/
        documents/
          sv/               # SystemVerilog source files
          specs/            # Specification excerpts (markdown/text)
          scripts/          # EDA flow scripts (TCL, Bash, Python)
        golden_entities.json
        golden_triples.json
        golden_merges.json
        golden_queries.json
      # Future domain splits:
      # general/            # Non-ASIC technical documents
      # analog/             # Analog/mixed-signal domain
    test_extraction_quality.py
    test_entity_resolution.py
    test_community_quality.py
    conftest.py
  retrieval/
    fixtures/
      asic/
        golden_queries.json   # Queries with expected relevant chunks
    test_retrieval_quality.py
    conftest.py
```

### 3.2 Schema: `golden_entities.json`

```json
{
  "version": "1.0",
  "domain": "asic",
  "documents": [
    {
      "document_id": "sv/axi_master.sv",
      "file_path": "evals/knowledge_graph/fixtures/asic/documents/sv/axi_master.sv",
      "entities": [
        {
          "name": "axi_master",
          "type": "RTL_Module",
          "span": {"start_line": 1, "end_line": 150},
          "aliases": ["AXI Master", "axi_mstr"],
          "properties": {
            "port_count": 12
          },
          "extraction_methods": ["parser", "regex", "gliner"],
          "notes": "Top-level AXI master module"
        }
      ]
    }
  ]
}
```

**Field semantics:**

| Field | Required | Description |
|-------|----------|-------------|
| `document_id` | Yes | Relative path within `documents/`, used as join key |
| `file_path` | Yes | Full relative path to the source document |
| `entities[].name` | Yes | Canonical name (the "correct" name for the entity) |
| `entities[].type` | Yes | Entity type from `config/kg_schema.yaml` |
| `entities[].span` | No | Line range where the entity is defined (for structural types) |
| `entities[].aliases` | No | Alternative names that should resolve to this entity |
| `entities[].properties` | No | Expected property values for property-level eval (future) |
| `entities[].extraction_methods` | Yes | Which extractors are expected to find this entity |
| `entities[].notes` | No | Free-text annotation for labeler disambiguation |

### 3.3 Schema: `golden_triples.json`

```json
{
  "version": "1.0",
  "domain": "asic",
  "documents": [
    {
      "document_id": "sv/axi_master.sv",
      "triples": [
        {
          "subject": "axi_master",
          "predicate": "contains",
          "object": "axi_wr_channel",
          "evidence": "Instance declaration at line 45",
          "extraction_methods": ["parser"]
        }
      ]
    }
  ]
}
```

### 3.4 Schema: `golden_merges.json`

```json
{
  "version": "1.0",
  "domain": "asic",
  "merge_groups": [
    {
      "canonical": "axi_master",
      "members": ["axi_master", "AXI Master", "axi_mstr"],
      "type": "RTL_Module",
      "notes": "Same module referenced in SV source, spec doc, and build script"
    }
  ]
}
```

### 3.5 Schema: `golden_queries.json` (retrieval)

```json
{
  "version": "1.0",
  "domain": "asic",
  "queries": [
    {
      "query_id": "q001",
      "query": "How does the AXI master handle write bursts?",
      "relevant_chunks": ["axi_master.sv:chunk_003", "axi_spec.md:chunk_012"],
      "relevant_entities": ["axi_master", "axi_wr_channel"],
      "difficulty": "easy",
      "notes": "Tests basic entity-to-chunk linkage"
    }
  ]
}
```

**Difficulty levels:**
- `easy` -- Query directly names an entity; relevant chunks are obvious.
- `medium` -- Query uses synonyms or abbreviations; requires alias resolution.
- `hard` -- Query is abstract; requires multi-hop graph traversal or community context.

### 3.6 Labeling Guidelines

**Who labels:** The person who creates or curates a fixture document also creates its golden labels. A second person reviews labels for disagreements.

**Ambiguity rules:**
- If an entity could be typed as two valid types (e.g., a module that is also an IP block), label it as the more specific type and note the ambiguity.
- If a triple could use two valid predicates (e.g., `depends_on` vs `instantiates`), prefer the more specific predicate.
- Entities appearing in prose that are not defined in the document itself (e.g., "VCS" mentioned in a spec) are labeled if and only if they are extractable from the text passage alone -- do not label entities that require external knowledge.

**Labeling workflow:**
1. Read the document.
2. Enumerate all entities visible in the text, assign types per `config/kg_schema.yaml`.
3. Enumerate all relationships visible in the text, assign predicates per schema edge types.
4. Identify merge groups (same entity appearing with different surface forms).
5. Peer review: a second labeler checks for missed entities and type disagreements.
6. Resolve disagreements by discussion; document unresolvable cases in `notes`.

### 3.7 Domain Extensibility

The `fixtures/` directory is organized by domain. To add a new domain:

1. Create `evals/knowledge_graph/fixtures/<domain>/` with the same structure as `asic/`.
2. Add golden JSON files following the same schemas.
3. The eval harness parameterizes over domains automatically via `conftest.py` fixture discovery.

---

## 4. Fixture Requirements

### 4.1 Document Types

| Document type | Directory | Description | Minimum count |
|--------------|-----------|-------------|---------------|
| SystemVerilog source | `documents/sv/` | Module definitions with ports, parameters, instances, FSMs | 5 files |
| Specification excerpts | `documents/specs/` | Markdown/text excerpts from design specs, datasheets | 3 files |
| EDA flow scripts | `documents/scripts/` | TCL/Python/Bash scripts for synthesis, simulation, build flows | 3 files |

### 4.2 Minimum Fixture Sizes

For extraction quality metrics to be meaningful:

| Requirement | Minimum |
|-------------|---------|
| Total labeled entities | 100 |
| Distinct entity types covered | 10+ (of the ~40 types in `kg_schema.yaml`) |
| Total labeled triples | 50 |
| Distinct edge types covered | 5+ |
| Merge groups | 10 |
| Retrieval queries | 20 (balanced across difficulty levels) |

These minimums give rough statistical grounding. Confidence intervals should be reported alongside point estimates once fixture size allows it.

### 4.3 Proprietary Data Avoidance

All fixture documents must be one of:
- **Synthetic-realistic:** Written to look like real ASIC documents but containing no proprietary IP. Module names, signal names, and spec content are invented.
- **Open-source:** Drawn from public SV repositories (e.g., OpenTitan, PULP Platform) with attribution.
- **Anonymized:** Real documents with all proprietary names replaced by plausible substitutes.

Each fixture file must include a header comment stating its provenance (synthetic, open-source with URL, or anonymized).

---

## 5. Metrics Definitions

### 5.1 Core Formulas

**Precision, Recall, F1 (entity and triple extraction):**

```
TP = |extracted ∩ golden|
FP = |extracted \ golden|
FN = |golden \ extracted|

Precision = TP / (TP + FP)       [0 if TP + FP = 0]
Recall    = TP / (TP + FN)       [0 if TP + FN = 0]
F1        = 2PR / (P + R)        [0 if P + R = 0]
```

**Macro-F1:**

```
Macro-F1 = (1/N) * sum(F1_i for i in entity_types)
```

where N is the number of entity types that appear in the golden set.

**MRR (retrieval):**

```
MRR = (1/|Q|) * sum(1/rank_i for i in Q)
```

where `rank_i` is the rank of the first relevant result for query i, or infinity if no relevant result appears.

**Hit rate at k:**

```
H@k = (1/|Q|) * sum(1 if any relevant in top-k_i else 0 for i in Q)
```

**Merge precision and recall:**

```
Merge precision = |correct_merges| / |total_merges_performed|
Merge recall    = |correct_merges| / |total_merges_in_golden|
```

A merge is "correct" if both entities in the merged pair belong to the same golden merge group.

### 5.2 Partial Match Handling

Entity names in ASIC documents have high surface variation (e.g., `axi_master` vs `AXI_MASTER` vs `axi master`). The eval harness applies a normalization pipeline before matching:

1. **Case folding:** Lowercase both sides.
2. **Separator normalization:** Replace `_`, `-`, and whitespace with a single underscore.
3. **Alias expansion:** Check if the extracted name appears in the golden entity's `aliases` list.

If an extracted entity matches a golden entity only after alias expansion, it is counted as a TP but flagged as an "alias match" in the detailed report.

Fuzzy matching (edit distance, token overlap) is NOT used for pass/fail scoring but is logged as a diagnostic to surface near-misses.

### 5.3 Thresholds

Initial thresholds are baselines to be calibrated after the first eval run. They represent the minimum acceptable quality for a passing eval.

| Metric | Threshold | Notes |
|--------|-----------|-------|
| Entity extraction F1 (parser extractors) | >= 0.85 | Parser extractors should be near-deterministic on structural types |
| Entity extraction F1 (regex extractor) | >= 0.50 | Regex is a coarse baseline; lower bar expected |
| Entity extraction F1 (GLiNER) | >= 0.60 | NER model with domain-specific labels |
| Entity extraction F1 (LLM extractor) | >= 0.70 | LLM structured output; higher variance expected |
| Triple extraction F1 (parser) | >= 0.80 | Structural relationships from parsed AST |
| Triple extraction F1 (LLM) | >= 0.55 | Semantic relationships from prose |
| Merge precision | >= 0.90 | False merges are worse than missed merges |
| Merge recall | >= 0.70 | Some missed merges are tolerable |
| Retrieval MRR (KG-augmented) | >= baseline + 0.05 | KG must demonstrably improve over vanilla |
| Retrieval H@10 (KG-augmented) | >= baseline + 0.03 | Minimum measurable lift |
| Community summary coherence | >= 3.5 / 5.0 | LLM-as-judge mean score |

Thresholds are stored in `evals/knowledge_graph/conftest.py` as constants so they can be updated without modifying test logic.

---

## 6. Execution Model

### 6.1 Pytest Marker

All eval files use the `@pytest.mark.eval` marker:

```python
import pytest

pytestmark = pytest.mark.eval
```

This marker is registered in `evals/conftest.py`:

```python
def pytest_configure(config):
    config.addinivalue_line("markers", "eval: quality evaluation tests (not unit tests)")
```

### 6.2 Running Evals

```bash
# Run all evals
pytest evals/ -m eval

# Run only KG extraction evals
pytest evals/knowledge_graph/test_extraction_quality.py -m eval

# Run only retrieval evals
pytest evals/retrieval/test_retrieval_quality.py -m eval

# Run with verbose JSON report
pytest evals/ -m eval --json-report --json-report-file=eval_results.json
```

### 6.3 CI Integration

Evals are **not** run on every commit. They are triggered:

- **On PR:** Full eval suite runs as a required check. PRs that regress below thresholds are blocked.
- **Nightly:** Full eval suite runs against `main` to track quality over time.
- **Manual:** Developers can trigger evals locally or via CI dispatch for ad-hoc comparison.

CI configuration should use a dedicated eval job that:
1. Installs optional dependencies (spaCy model, GLiNER weights, leidenalg).
2. Runs `pytest evals/ -m eval --json-report --json-report-file=eval_results.json`.
3. Parses `eval_results.json` and posts a summary comment on the PR.

### 6.4 Reporting Format

Each eval run produces two artifacts:

**1. JSON summary (`eval_results.json`):**

```json
{
  "timestamp": "2026-04-09T12:00:00Z",
  "domain": "asic",
  "extraction": {
    "by_extractor": {
      "regex_extractor": {
        "entity_precision": 0.62,
        "entity_recall": 0.48,
        "entity_f1": 0.54,
        "triple_f1": 0.41,
        "by_type": {
          "RTL_Module": {"precision": 0.80, "recall": 0.75, "f1": 0.77},
          "Signal": {"precision": 0.55, "recall": 0.40, "f1": 0.46}
        }
      }
    },
    "ensemble": {
      "entity_f1": 0.78,
      "triple_f1": 0.65
    }
  },
  "entity_resolution": {
    "merge_precision": 0.92,
    "merge_recall": 0.71,
    "split_rate": 0.08,
    "lump_rate": 0.02
  },
  "retrieval": {
    "vanilla": {"mrr": 0.55, "h_at_10": 0.72, "p_at_10": 0.31},
    "kg_local": {"mrr": 0.62, "h_at_10": 0.78, "p_at_10": 0.35},
    "kg_global": {"mrr": 0.65, "h_at_10": 0.81, "p_at_10": 0.37}
  },
  "thresholds_passed": true
}
```

**2. Human-readable table (stdout):**

```
=== KG Extraction Quality (asic) ===

Extractor          | Entity P | Entity R | Entity F1 | Triple F1
-------------------|----------|----------|-----------|----------
regex_extractor    |    0.62  |    0.48  |     0.54  |     0.41
gliner_extractor   |    0.71  |    0.65  |     0.68  |     0.52
llm_extractor      |    0.75  |    0.70  |     0.72  |     0.58
parser (SV)        |    0.92  |    0.88  |     0.90  |     0.85
Ensemble (union)   |    0.68  |    0.85  |     0.76  |     0.65

=== Entity Resolution ===
Merge precision: 0.92  Merge recall: 0.71  Split: 0.08  Lump: 0.02

=== Retrieval Augmentation ===
Condition   | MRR  | H@10 | P@10
------------|------|------|-----
Vanilla     | 0.55 | 0.72 | 0.31
KG-local    | 0.62 | 0.78 | 0.35
KG-global   | 0.65 | 0.81 | 0.37

All thresholds passed: YES
```

---

## 7. Eval vs Test Distinction

| Dimension | Unit Tests (`tests/knowledge_graph/`) | Evals (`evals/knowledge_graph/`) |
|-----------|---------------------------------------|----------------------------------|
| **Purpose** | Verify code correctness | Measure output quality |
| **Data** | Synthetic, minimal | Real or synthetic-realistic, labeled |
| **Speed** | Fast (< 30s total) | Slow (minutes; LLM calls, model loading) |
| **Pass criteria** | Assertions on exact behavior | Metric thresholds on aggregate quality |
| **Marker** | Default (no marker needed) | `@pytest.mark.eval` |
| **CI trigger** | Every commit | PR and nightly only |
| **Failure meaning** | Bug in code | Quality regression or threshold miscalibration |
| **Golden data** | Inline or minimal fixtures | Curated golden datasets with labeling provenance |
| **Extractor deps** | Mocked or minimal | Full extractor stack (models loaded) |

Both use pytest. Both live in the repo. They serve fundamentally different purposes and should never be conflated.

---

## 8. Implementation Roadmap

This section outlines the order of work to stand up the eval framework.

### Phase A: Foundation (prerequisite for all evals)

1. Create `evals/` directory structure as specified in Section 3.1.
2. Create `evals/conftest.py` with marker registration and fixture discovery.
3. Create `evals/knowledge_graph/conftest.py` with threshold constants and golden data loading helpers.
4. Write 2-3 synthetic-realistic SV files as seed fixtures with complete golden labels.

### Phase B: Extraction Evals

5. Implement `test_extraction_quality.py`:
   - Load golden entities and documents.
   - Run each extractor independently on each document.
   - Compute precision/recall/F1 per extractor per type.
   - Assert against thresholds.
6. Implement `test_entity_resolution.py`:
   - Run all extractors, merge results through the resolution pipeline.
   - Compare merge groups against `golden_merges.json`.
7. Calibrate thresholds from the first full run (expect threshold adjustments).

### Phase C: Retrieval Evals

8. Create retrieval golden queries (`evals/retrieval/fixtures/asic/golden_queries.json`).
9. Implement `test_retrieval_quality.py`:
   - Ingest fixture documents into a test vector store.
   - Run queries under three conditions (vanilla, KG-local, KG-global).
   - Compute MRR, H@k, P@k.
   - Assert KG lift deltas.

### Phase D: Community Evals

10. Implement `test_community_quality.py`:
    - Build graph from fixture documents.
    - Run Leiden detection.
    - Compute modularity and coverage.
    - Run LLM-as-judge on community summaries.

### Phase E: CI and Reporting

11. Add CI job for eval runs on PR.
12. Build JSON report parser and PR comment formatter.
13. Set up nightly eval run with historical tracking.

---

## Appendix A: Entity Type Coverage Matrix

This table maps entity types from `config/kg_schema.yaml` to the minimum fixture coverage target. Types marked "required" must be present in the initial golden dataset. Types marked "stretch" can be added incrementally.

| Entity Type | Category | Phase | Fixture Priority |
|------------|----------|-------|-----------------|
| RTL_Module | structural | 1 | Required |
| Port | structural | 1 | Required |
| Parameter | structural | 1 | Required |
| Instance | structural | 1 | Required |
| Signal | structural | 1 | Required |
| Interface | structural | 1 | Required |
| Package | structural | 1 | Stretch |
| ClockDomain | structural | 1b | Required |
| FSM_State | structural | 1b | Required |
| UVM_Component | structural | 1b | Stretch |
| Specification | semantic | 1 | Required |
| EDA_Tool | semantic | 1 | Required |
| Protocol | semantic | 1 | Stretch |
| Requirement | semantic | 1 | Stretch |
| PythonClass | structural | 2 | Stretch |
| PythonFunction | structural | 2 | Stretch |
| BashFunction | structural | 2 | Stretch |

## Appendix B: Edge Type Coverage Matrix

| Edge Type | Category | Phase | Fixture Priority |
|-----------|----------|-------|-----------------|
| contains | structural | 1 | Required |
| depends_on | structural | 1 | Required |
| instantiates | structural | 1b | Required |
| connects_to | structural | 1b | Required |
| belongs_to_clock_domain | structural | 1b | Stretch |
| transitions_to | structural | 1b | Stretch |
| specified_by | semantic | 1 | Required |
| verified_by | semantic | 1 | Stretch |
| constrained_by | semantic | 1 | Stretch |
| relates_to | semantic | 1 | Required |
