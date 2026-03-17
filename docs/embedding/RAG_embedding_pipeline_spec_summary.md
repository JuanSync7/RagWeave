# RAG Document Embedding Pipeline — Specification Summary

**Companion document to:** `RAG_embedding_pipeline_spec.md` (v2.0.0)
**Purpose:** Combined requirements-level and architecture-level summary for stakeholders, reviewers, and implementers.
**Version:** 2.0 | **Consolidated from:** `RAG_embedding_pipeline_summary.md`, `RAG_embedding_pipeline_arch.md`, and previous `RAG_embedding_pipeline_spec_summary.md`

> **Note:** This summary reflects specification intent and architecture design.
> For implemented ingestion behavior and code navigation, use:
>
> - `docs/embedding/INGESTION_PIPELINE_ENGINEERING_GUIDE.md`
> - `docs/embedding/INGESTION_NEW_ENGINEER_ONBOARDING_CHECKLIST.md`
> - `src/ingest/README.md`

---

## 1) System Intent

The AION RAG Document Embedding Pipeline converts engineering documents (PDFs, DOCX, PPTX, XLSX, Markdown, HTML, RST, plain text) into semantically searchable vector embeddings stored in Weaviate, with an optional knowledge graph capturing relationships between documents, concepts, and specifications.

It targets mission-critical ASIC knowledge workflows where retrieval errors can propagate to design mistakes. The specification defines pipeline behavior, quality controls, fallback paths, and measurable acceptance criteria.

---

## 2) Scope and Boundaries

**Entry point:** Source document file on local filesystem.
**Exit points:**

- Vector embeddings + metadata in vector database
- Knowledge graph triples in graph store (when enabled)

### In scope

- Document ingestion, processing, and embedding
- Vector storage with hybrid search capability (vector + keyword)
- Knowledge graph construction and storage
- Document review tier management
- Re-ingestion of updated documents
- Batch processing of document directories
- Retrieval quality evaluation framework

### Out of scope

- Query processing, reranking, and answer generation (downstream retrieval layer)
- User authentication and access control
- Document authoring or editing
- Real-time document change detection (push-based ingestion)

### Key Constraints

The spec defines 7 explicit assumptions (Section 1.6) that bound the operating envelope: Python 3.11+ runtime, LangGraph/LangChain availability, accessible vector database, LLM provider (with fallback to deterministic alternatives), sequential document processing (no concurrent ingestion of the same document), documents <= ~100 pages (larger documents should be pre-split), and embedding model token limits accommodating target chunk sizes.

---

## 3) Architecture Overview

### 3.1 End-to-End System Context

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            EXTERNAL INPUTS                                  │
│                                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │   PDFs   │  │   DOCX   │  │   PPTX   │  │   XLSX   │  │ MD/HTML/ │       │
│  │          │  │          │  │          │  │          │  │ RST/TXT  │       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│       └─────────────┴─────────────┼─────────────┴─────────────┘             │
│                                   │                                         │
│                                   ▼                                         │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                     CLI / Programmatic API                             │ │
│  │  python main.py doc.pdf --domain dft --review-tier partially_reviewed  │ │
│  └────────────────────────────────┬───────────────────────────────────────┘ │
└───────────────────────────────────┼─────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                                                                            │
│                    EMBEDDING PIPELINE (LangGraph DAG)                      │
│                                                                            │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐           │
│  │ Node 1  │─>│ Node 2  │─>│ Node 3  │─>│ Node 4  │─>│ Node 5  │           │
│  │ Ingest  │  │Structure│  │   VLM   │  │ Clean   │  │Refactor │           │
│  │ + Hash  │  │ Detect  │  │ Figures │  │  Text   │  │(agentic)│           │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘           │
│       │            │         optional        │         optional            │
│       │            │            │            │            │                │
│       ▼            ▼            ▼            ▼            ▼                │
│  ┌──────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐          │
│  │ Node 6   │─>│ Node 7  │─>│ Node 8  │─>│ Node 9  │─>│ Node 10 │          │
│  │ Chunk    │  │ Enrich  │  │Metadata │  │ X-Refs  │  │   KG    │          │
│  │(semantic)│  │+boundary│  │Keywords │  │ Extract │  │ Triples │          │
│  └────┬─────┘  └─────────┘  └─────────┘  └────┬────┘  └────┬────┘          │
│       │                                   optional     optional            │
│       │                                      │            │                │
│       ▼                                      ▼            ▼                │
│  ┌─────────┐                             ┌─────────┐  ┌─────────┐          │
│  │ Node 11 │────────────────────────────>│ Node 12 │─>│ Node 13 │          │
│  │ Quality │                             │ Embed & │  │KG Store │          │
│  │Validate │                             │ Store   │  │         │          │
│  └─────────┘                             └────┬────┘  └────┬────┘          │
│                                               │            │               │
└───────────────────────────────────────────────┼────────────┼───────────────┘
                                                │            │
                        ┌───────────────────────┘            │
                        ▼                                    ▼
┌───────────────────────────────────┐  ┌──────────────────────────────────────┐
│         WEAVIATE VECTOR STORE     │  │        KNOWLEDGE GRAPH STORE         │
│                                   │  │                                      │
│  HNSW Index (vectors)             │  │  v1: Weaviate cross-references       │
│  BM25 Index (keywords)            │  │  v2: Neo4j (optional)                │
│  32 metadata properties           │  │                                      │
│  Review tier filtering            │  │  Document → Concept → Entity → Spec  │
│                                   │  │                                      │
│  Hybrid Search (vector + BM25)    │  │                                      │
└───────────────────────────────────┘  └──────────────────────────────────────┘
```

### 3.2 Configuration & Support Systems

```
┌──────────────────────────────────────────────────────────────────────┐
│                    CONFIGURATION LAYER                               │
│                                                                      │
│  ┌───────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │  PipelineConfig   │  │ model_registry  │  │ domain_vocabulary  │  │
│  │  (13 sub-configs) │  │    .yaml        │  │      .yaml         │  │
│  │                   │  │                 │  │                    │  │
│  │  LLM provider     │  │ BGE-large: 1024 │  │ DFT: Design for    │  │
│  │  Embedding model  │  │ E5-large: 1024  │  │   Testability      │  │
│  │  Weaviate URL     │  │ Jina-v2: 768    │  │ STA: Static Timing │  │
│  │  Chunk sizes      │  │ ...             │  │   Analysis         │  │
│  │  Skip flags       │  │                 │  │ CDR: [ambiguous]   │  │
│  │  Review defaults  │  │ Cross-validated │  │ ...                │  │
│  │  KG settings      │  │ at startup      │  │                    │  │
│  └────────┬──────────┘  └───────┬─────────┘  └─────────┬──────────┘  │
│           └─────────────────────┼──────────────────────┘             │
│                                 ▼                                    │
│                    ┌───────────────────────┐                         │
│                    │  config_validator.py  │                         │
│                    │  (startup checks)     │                         │
│                    └───────────────────────┘                         │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.3 Data Flow Through a Single Chunk

```
  Raw PDF page text
  "The DFT scan chain operates at 100MHz. See Section 3.2 for timing."
       │
       ▼ [Node 2: Structure Detection]
  Section: "Power Domains > DFT > Scan Chain Timing"
       │
       ▼ [Node 4: Text Cleaning]
  Boilerplate removed, whitespace normalised
       │
       ▼ [Node 5: Refactoring]
  "The DFT (Design for Testability) scan chain operates at 100MHz clock
   frequency. The timing constraints are defined in Section 3.2 of the
   DFT Scan Chain Specification (DOC-042)."
       │
       ▼ [Node 6: Chunking]
  chunk_id: deterministic (doc_id + index + hash)
  chunk_index: 5 | chunking_method: "llm_semantic"
       │
       ▼ [Node 7: Enrichment]
  context_header: "[Context: dft | specification | DFT Guide | Power > DFT]"
  enriched_content: "[Previous context: ...2 sentences...]\n{chunk content}"
       │
       ▼ [Node 8: Metadata]
  keywords: ["scan chain", "100MHz", "timing constraints"] (validated)
  entities: ["DFT Scan Chain Specification", "DOC-042"]
       │
       ▼ [Node 11: Quality]
  quality_score: 0.78
       │
       ▼ [Node 12: Embed & Store]
  vector: [0.023, -0.145, 0.089, ...] (1024 dimensions, BGE-large)
       │
       ▼ WEAVIATE OBJECT (32 total properties)
```

### 3.4 Re-ingestion Flow

```
  Document arrives ──> Compute SHA-256 hash
                       │
                  Query Weaviate: "Does document_id exist?"
                       │
               ┌───────┴──────────┐
          [NO: new doc]    [YES: existing]
               │                  │
          Normal pipeline    Compare content_hash
                              │
                     ┌────────┴────────┐
              [SAME hash]       [DIFFERENT hash]
                     │                 │
              strategy?         is_reingestion = True
              │                 Auto-demote review tier
     ┌────────┴──────┐         Process through pipeline
  [skip_unchanged] [delete_*]         │
     │               │         Node 12: Delete old → Insert new
   SKIP           Continue     On failure: ABORT (preserve old data)
```

### 3.5 Review Tier System

```
  ┌──────────────────┐    peer review    ┌────────────────────┐
  │  SELF_REVIEWED   │ ──────────────>   │ PARTIALLY_REVIEWED │
  │  (Tier 3)        │ <──────────────   │ (Tier 2)           │
  │  Utility scripts │   major revision  │  Draft specs       │
  │  Personal notes  │                   │  WIP processes     │
  └──────────────────┘                   └─────────┬──────────┘
                                                   │
                                          domain lead sign-off
                                                   ▼
                                        ┌───────────────────┐
                                        │  FULLY_REVIEWED   │
                                        │  (Tier 1)         │
                                        │  Approved specs   │
                                        └─────────┬─────────┘
                                                  │
                                          doc re-ingested → Auto-demote

  RETRIEVAL SEARCH SPACES:
  DEFAULT:  [Tier 1 only]              ──  Authoritative results
  EXPANDED: [Tier 1 + Tier 2]          ──  + Draft/WIP results
  FULL:     [Tier 1 + Tier 2 + Tier 3] ──  All knowledge
```

---

## 4) Pipeline Stages (13 Nodes)

```text
    Source Document (filesystem path)
              │
              ▼
    ┌────────────────────────────────────┐
    │  [1]  Document Ingestion           │
    │  [2]  Structure Detection          │
    │  [3]  Multimodal Processing    *   │
    │  [4]  Text Cleaning                │
    │  [5]  Document Refactoring     *   │
    │  [6]  Chunking                     │
    │  [7]  Chunk Enrichment             │
    │  [8]  Metadata Generation          │
    │  [9]  Cross-Reference Extr.    *   │
    │  [10] KG Extraction            *   │
    │  [11] Quality Validation           │
    │  [12] Embedding & Storage          │
    │  [13] KG Storage               *   │
    └───────────────┬────────────────────┘
                    │
           ┌────────┴────────┐
           ▼                 ▼
      Vector DB        Graph Store

      * = optional / configurable
```

All stages share a common state object (`PipelineDocument`), write bounded outputs, and support fail-safe fallback behavior to avoid batch-halting failures.

---

## 5) Requirement Framework in v2

The v2 specification uses:

- **RFC 2119 keywords** for requirement strength (`SHALL`, `SHOULD`, `MAY`)
- **Requirement families:** `FR-*` (functional), `NFR-*` (non-functional), `SC-*` (security/compliance)
- **Per-requirement rationale and acceptance criteria**
- **Terminology, assumptions/constraints, and traceability matrix**

### Functional Requirement Domains

| ID Range | Domain |
|----------|--------|
| FR-100 to FR-999 | Core pipeline stages |
| FR-1030 to FR-1034 | Data model and deterministic identity |
| FR-1100 to FR-1199 | Quality validation |
| FR-1120 to FR-1133 | Storage schema, hybrid search, schema versioning |
| FR-1200 to FR-1399 | Embedding and storage |
| FR-1400 | Re-ingestion |
| FR-1500 | Review tiers |
| FR-1600 | Domain vocabulary |
| FR-1700 | Error handling / fallback matrix |
| FR-1800 | Configuration system |
| FR-1900 to FR-1952 | Interfaces: CLI and programmatic API |
| FR-2000 | Evaluation framework |
| FR-2100 | Feedback and continuous improvement |

### Non-functional areas (NFR-*)

Performance, scalability, reliability, maintainability, deployment (offline-capable).

### Security/compliance (SC-*)

Auditability, data residency, credential handling, data lifecycle/retention.

---

## 6) Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Orchestration | LangGraph StateGraph | Typed state, conditional routing, compilable DAG |
| Embedding approach | BYOM (Bring Your Own Model) | Model control, prefix handling, offline deployment |
| Default embedding model | BAAI/bge-large-en-v1.5 (1024d) | Best MTEB general-purpose; requires query prefix |
| Chunk target size | 450 tokens | BGE-large max (512) minus boundary context overhead (~60) |
| Re-ingestion strategy | Delete-and-reinsert | Chunk boundaries change; no stable update target |
| ID generation | Deterministic (SHA-256 based) | Idempotent re-ingestion; identical content = identical IDs |
| Context headers | Metadata only, NOT embedded | Preserves full embedding capacity for semantic signal |
| Boundary context | Embedded (last 2 sentences of prev chunk) | Improves recall at embedding time; adjacency links for retrieval-time |
| BM25 enrichment | Validated LLM keywords + TF-IDF fallback | Closes vocabulary gap; validation prevents hallucinated keywords |
| KG storage (v1) | Weaviate cross-references | Simpler deployment; Neo4j as v2 upgrade path |
| Error handling | Fail-safe (fallback) except re-ingestion cleanup (fail-hard) | One bad LLM call must not kill a 500-doc batch |

---

## 7) Core Design Principles

- **Swappability over lock-in**: providers behind interfaces and config
- **Fail-safe over fail-fast**: deterministic fallbacks for model failures
- **Context preservation over compression**: no loss of technical facts
- **Configuration-driven behavior**: stage toggles and runtime overrides
- **Idempotency by construction**: deterministic IDs and repeatable outputs
- **Controlled access over restriction**: ingest broadly, filter by trust tier

### Refactor-Provenance Contract

When document refactoring is enabled:

- original source remains immutable,
- refactored text is treated as a derived retrieval representation,
- chunk metadata must include mapping back to original source spans,
- citations must resolve to original source URI/location, not only derived text.

---

## 8) Glossary of Key Abstractions

| Abstraction | What it is | Where defined |
|-------------|-----------|---------------|
| `PipelineDocument` | State object flowing through all 13 nodes | `pipeline/models.py` |
| `BaseNode` | Abstract base class for pipeline nodes | `pipeline/nodes/base.py` |
| `PipelineConfig` | Master config with 13 sub-configs | `pipeline/config.py` |
| `Chunk` | The atom of retrieval — gets embedded, stored, returned in search | `pipeline/models.py` |
| `KGTriple` | Subject-predicate-object relationship for knowledge graph | `pipeline/models.py` |
| `ReviewTier` | Coarse trust level (FULLY / PARTIALLY / SELF_REVIEWED) | `pipeline/models.py` |
| `deterministic_id()` | SHA-256-based UUID generator | `pipeline/id_generation.py` |
| `enriched_content` | Chunk content + boundary context — what gets embedded | `pipeline/nodes/chunk_enrichment.py` |
| `context_header` | Metadata string for display — stored but NOT embedded | `pipeline/nodes/chunk_enrichment.py` |

---

## 9) Implementation Phasing (Recommended)

```
PHASE 1 — Core Pipeline (MVP)
├── Nodes 1, 2, 4, 6, 7, 11, 12
├── Config system + validator
├── CLI (single file + batch)
├── Deterministic IDs + re-ingestion
└── Recursive fallback chunking (no LLM dependency for MVP)

PHASE 2 — LLM Enhancement
├── Node 6 LLM chunking (upgrade from fallback)
├── Node 8 metadata generation + keyword validation
├── Node 5 refactoring (optional, behind skip flag)
└── Domain vocabulary system

PHASE 3 — Extended Features
├── Node 3 multimodal processing (VLM)
├── Node 9 cross-reference extraction
├── Nodes 10 + 13 knowledge graph
├── Review tier system + API
└── PPTX / XLSX format extractors

PHASE 4 — Quality & Operations
├── Evaluation framework + dataset
├── Langfuse observability integration
├── Batch processing hardening
└── Schema migration tooling
```

For the full phased implementation plan with tasks and code appendix, see `INGESTION_PIPELINE_IMPLEMENTATION.md`.

---

## 10) Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| LLM API cost overrun on large batches | Medium | Medium | Cost estimator in CLI; refactoring skip for non-critical docs |
| Silent embedding truncation from config mismatch | High (was default) | High | target_chunk_size accounts for boundary overhead; config validator |
| Evaluation dataset goes stale | High | High | Named owner; auto-eval after batch; dataset versioning |
| Weaviate unavailable during re-ingestion | Low | High | Old data preserved on failure; blue-green for production |
| LLM generates hallucinated keywords in BM25 index | Medium | Medium | Keyword validation gate; TF-IDF fallback |
| Abbreviation disambiguation failure | Medium | Medium | Domain-aware vocab; confidence scoring; manual review flag |

---

## 11) External Dependencies

**Required:** Vector database (e.g., Weaviate), LLM provider (e.g., OpenAI, Anthropic, Ollama)
**Optional:** VLM provider for figure-to-text, dedicated graph database (e.g., Neo4j), observability platform (e.g., Langfuse)
**Downstream contract only:** Reranker and answer-generation systems consume pipeline outputs but are outside this spec's scope.

---

## 12) Document Relationship

| Document | Purpose |
|----------|---------|
| `RAG_embedding_pipeline_spec.md` | Authoritative requirements baseline (v2) |
| `RAG_embedding_pipeline_spec_summary.md` (this document) | Combined requirements + architecture digest |
| `INGESTION_PIPELINE_ENGINEERING_GUIDE.md` | Practical developer guide for modifying the pipeline |
| `INGESTION_NEW_ENGINEER_ONBOARDING_CHECKLIST.md` | Quick-start for new engineers |
| `INGESTION_PIPELINE_IMPLEMENTATION.md` | Phased implementation plan with task breakdown |

---

## 13) Sync Status

Aligned to `RAG_embedding_pipeline_spec.md` v2.0.0 as of 2026-03-13.
Consolidated from previous `_summary.md`, `_arch.md`, and `_spec_summary.md`.
